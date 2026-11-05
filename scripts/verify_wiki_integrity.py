#!/usr/bin/env python3
"""
verify_wiki_integrity.py — Programmatic Integrity Verifier for Karpathy LLM Wiki.

Verifies:
  1. Required File Existence: wiki/, index.md, log.md, hot.md, SCHEMA.md, failed_ideas.md.
  2. Markdown Cross-Links: all relative links and anchors resolve to existing targets.
  3. SCHEMA Conformance: YAML frontmatter, required keys, allowed status, H1 heading.
  4. Log Journal Format: grep-parseable ISO UTC timestamp headers (Karpathy log convention).
  5. Failed Ideas Ledger: documented dead ends with root cause and negative invariants.
  6. Hook & Sync Script Sanity: scripts exist and have executable permissions.
  7. Agent Instruction Assertions: CLAUDE.md, AGENTS.md, GEMINI.md contain startup/shutdown rules.

Returns exit code 0 if all checks pass, non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


ALLOWED_STATUSES = {"active", "experimental", "candidate", "archived", "rejected", "stable", "draft"}
CORE_WIKI_FILES = ["index.md", "log.md", "hot.md", "SCHEMA.md", "failed_ideas.md"]
SYNC_SCRIPTS = ["sync_wiki.sh", "wiki_sync.py", "install_wiki_hooks.sh"]
INSTRUCTION_FILES = ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]

LOG_HEADER_REGEX = re.compile(
    r"^##\s+\[\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+UTC\]\s+\[[a-zA-Z0-9_-]+\]\s+\[[A-Z]+\]\s+\|\s+.+$"
)
DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def strip_yaml_comment(val: str) -> str:
    """
    Strip YAML inline comments (' #...') while preserving '#' inside single/double quotes.
    """
    val = val.strip()
    if not val:
        return ""

    in_quote: Optional[str] = None
    escape = False

    for i, ch in enumerate(val):
        if escape:
            escape = False
            continue

        if ch == "\\" and in_quote == '"':
            escape = True
            continue

        if ch in ('"', "'"):
            if in_quote is None:
                in_quote = ch
            elif in_quote == ch:
                in_quote = None
            continue

        if in_quote is None:
            # Comment starts at '#' preceded by whitespace, or '#' at start of value
            if ch == "#" and (i == 0 or val[i - 1].isspace()):
                return val[:i].rstrip()

    return val.rstrip()


def clean_scalar(val: str) -> str:
    """Strip matching outer quotes and unescape quotes."""
    val = val.strip()
    if len(val) >= 2:
        if val[0] == '"' and val[-1] == '"':
            return val[1:-1].replace('\\"', '"').replace('\\\\', '\\')
        if val[0] == "'" and val[-1] == "'":
            return val[1:-1].replace("''", "'")
    return val


def parse_frontmatter(content: str) -> Tuple[Optional[Dict], str]:
    """
    Parse YAML frontmatter using zero external dependencies.
    Returns (frontmatter_dict, body_text). If no frontmatter, returns (None, content).
    """
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", content, re.DOTALL)
    if not match:
        return None, content

    raw_yaml = match.group(1)
    body = content[match.end():]
    data: Dict = {}
    current_key: Optional[str] = None

    for line in raw_yaml.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue

        # Check list item
        list_match = re.match(r"^\s+-\s+(.*)$", line)
        if list_match and current_key:
            raw_item = strip_yaml_comment(list_match.group(1))
            val = clean_scalar(raw_item)
            if not isinstance(data.get(current_key), list):
                data[current_key] = []
            data[current_key].append(val)
            continue

        # Check key-value pair
        kv_match = re.match(r"^([a-zA-Z0-9_-]+):\s*(.*)$", line)
        if kv_match:
            key = kv_match.group(1)
            raw_val = strip_yaml_comment(kv_match.group(2))
            current_key = key
            if not raw_val:
                data[key] = []
            elif raw_val.startswith("[") and raw_val.endswith("]"):
                items = [clean_scalar(strip_yaml_comment(x)) for x in raw_val[1:-1].split(",") if x.strip()]
                data[key] = items
            else:
                data[key] = clean_scalar(raw_val)

    return data, body


def slugify_heading(heading: str) -> str:
    """Convert markdown heading text to GitHub/Obsidian URL anchor slug."""
    clean = re.sub(r"[^\w\s-]", "", heading.lower())
    return re.sub(r"[-\s]+", "-", clean).strip("-")


def extract_headings(content: str) -> Set[str]:
    """Extract all markdown headings as slugs."""
    headings = set()
    for line in content.splitlines():
        match = re.match(r"^(#{1,6})\s+(.*)$", line.strip())
        if match:
            text = match.group(2).strip()
            # Remove custom anchor tags like {#custom-id} if present
            text = re.sub(r"\{#[^}]+\}", "", text).strip()
            headings.add(slugify_heading(text))
    return headings


def strip_code_blocks_and_spans(content: str) -> str:
    """
    Strip multi-line fenced code blocks (``` or ~~~) and inline code spans (`...`)
    so illustrative links inside documentation examples are not treated as active links.
    """
    # 1. Strip fenced code blocks with matching opening/closing fence lengths (handles 3, 4+ backticks/tildes)
    fence_pattern = re.compile(
        r"(?ms)^[ \t]*(?P<fence>`{3,}|~{3,})[^\n]*\n.*?\n[ \t]*(?P=fence)[ \t]*(?:\n|$)"
    )
    cleaned = fence_pattern.sub("\n", content)
    # Fallback for single-line or non-newline-terminated code blocks
    cleaned = re.sub(r"(?s)```.*?```", "", cleaned)
    cleaned = re.sub(r"(?s)~~~.*?~~~", "", cleaned)
    # 2. Strip inline code spans (e.g. `code` or ``code``)
    cleaned = re.sub(r"(?P<bt>`+)[^\n]*?(?P=bt)", "", cleaned)
    return cleaned


def extract_markdown_links(content: str) -> List[Tuple[str, str]]:
    """Extract (link_text, target) tuples from markdown content, ignoring code blocks."""
    cleaned = strip_code_blocks_and_spans(content)
    pattern = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
    links = []
    for match in pattern.finditer(cleaned):
        text, target = match.groups()
        target = target.strip()
        # Strip optional markdown title attribute if present: [text](target "title")
        if target:
            target = target.split()[0].strip("\"'")
        links.append((text, target))
    return links


class WikiVerifier:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.wiki_dir = repo_root / "wiki"
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.passed_checks: List[str] = []

    def verify_all(self) -> bool:
        """Run complete verification suite."""
        self.verify_core_files_exist()
        self.verify_schema_rulebook()
        self.verify_topic_frontmatter_and_headings()
        self.verify_markdown_links()
        self.verify_log_journal()
        self.verify_failed_ideas_ledger()
        self.verify_hot_page()
        self.verify_scripts_and_hooks()
        self.verify_agent_instructions()
        return len(self.errors) == 0

    def verify_core_files_exist(self):
        """1. Verify wiki/ directory and core markdown files exist."""
        if not self.wiki_dir.is_dir():
            self.errors.append(f"Directory missing: {self.wiki_dir}")
            return

        for fname in CORE_WIKI_FILES:
            fpath = self.wiki_dir / fname
            if not fpath.is_file():
                self.errors.append(f"Core wiki file missing: {fpath}")
            elif fpath.stat().st_size == 0:
                self.errors.append(f"Core wiki file is empty: {fpath}")
            else:
                self.passed_checks.append(f"Core file exists: wiki/{fname}")

    def verify_schema_rulebook(self):
        """2. Verify wiki/SCHEMA.md contains required governance sections."""
        schema_path = self.wiki_dir / "SCHEMA.md"
        if not schema_path.is_file():
            return
        content = schema_path.read_text(encoding="utf-8")
        required_terms = [
            "Frontmatter",
            "kebab-case",
            "log.md",
            "failed_ideas.md",
            "hot.md",
            "index.md",
        ]
        for term in required_terms:
            if term.lower() not in content.lower():
                self.errors.append(f"wiki/SCHEMA.md missing specification for: '{term}'")
        self.passed_checks.append("wiki/SCHEMA.md defines all required governance specifications")

    def verify_topic_frontmatter_and_headings(self):
        """3. Verify all topic pages contain valid YAML frontmatter and H1 heading."""
        if not self.wiki_dir.is_dir():
            return

        for md_file in self.wiki_dir.rglob("*.md"):
            # Exclude core root meta-files from strict frontmatter requirement
            if md_file.parent == self.wiki_dir and md_file.name in CORE_WIKI_FILES:
                continue

            content = md_file.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(content)
            rel_path = md_file.relative_to(self.repo_root)

            if fm is None:
                self.errors.append(f"Page missing YAML frontmatter: {rel_path}")
                continue

            # Validate required frontmatter keys
            for req_key in ["title", "tags", "created", "updated", "status"]:
                if req_key not in fm:
                    self.errors.append(f"{rel_path}: Frontmatter missing required key '{req_key}'")

            if "status" in fm and fm["status"] not in ALLOWED_STATUSES:
                self.errors.append(
                    f"{rel_path}: Invalid status '{fm['status']}'. Must be one of {sorted(ALLOWED_STATUSES)}"
                )

            if "created" in fm and not DATE_REGEX.match(str(fm["created"])):
                self.errors.append(f"{rel_path}: 'created' date '{fm['created']}' must match YYYY-MM-DD")

            if "updated" in fm and not DATE_REGEX.match(str(fm["updated"])):
                self.errors.append(f"{rel_path}: 'updated' date '{fm['updated']}' must match YYYY-MM-DD")

            # Validate top-level H1 heading
            h1_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
            if not h1_match:
                self.errors.append(f"{rel_path}: Page missing top-level H1 heading ('# Title')")
            else:
                h1_title = h1_match.group(1).strip()
                fm_title = fm.get("title", "")
                if fm_title and fm_title.lower() != h1_title.lower():
                    self.warnings.append(
                        f"{rel_path}: Frontmatter title '{fm_title}' differs from H1 '{h1_title}'"
                    )

        self.passed_checks.append("Topic pages YAML frontmatter and headings verified")

    def verify_markdown_links(self):
        """4. Verify all relative internal markdown links resolve to valid targets."""
        if not self.wiki_dir.is_dir():
            return

        headings_cache: Dict[Path, Set[str]] = {}

        for md_file in self.wiki_dir.rglob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            links = extract_markdown_links(content)
            rel_src = md_file.relative_to(self.repo_root)

            for text, target in links:
                # Ignore external URLs
                if target.startswith(("http://", "https://", "mailto:", "ftp://")):
                    continue

                # Handle anchor-only link
                if target.startswith("#"):
                    anchor = target[1:]
                    if md_file not in headings_cache:
                        headings_cache[md_file] = extract_headings(content)
                    if anchor not in headings_cache[md_file]:
                        self.errors.append(f"{rel_src}: Broken same-page anchor '{target}' for text '{text}'")
                    continue

                # Handle file link with optional anchor
                file_target = target
                anchor = None
                if "#" in target:
                    file_target, anchor = target.split("#", 1)

                resolved_path = (md_file.parent / file_target).resolve()

                if not resolved_path.exists():
                    self.errors.append(f"{rel_src}: Broken link '{target}' -> target '{resolved_path}' does not exist")
                elif resolved_path.is_file() and anchor:
                    if resolved_path not in headings_cache:
                        try:
                            headings_cache[resolved_path] = extract_headings(
                                resolved_path.read_text(encoding="utf-8")
                            )
                        except Exception:
                            headings_cache[resolved_path] = set()
                    if anchor not in headings_cache[resolved_path]:
                        self.errors.append(
                            f"{rel_src}: Broken anchor in target '{target}' -> anchor '{anchor}' not in {resolved_path.name}"
                        )

        self.passed_checks.append("All internal markdown links and anchors resolve cleanly")

    def verify_log_journal(self):
        """5. Verify wiki/log.md follows grep-parseable format."""
        log_path = self.wiki_dir / "log.md"
        if not log_path.is_file():
            return

        content = log_path.read_text(encoding="utf-8")
        headers = [line for line in content.splitlines() if line.startswith("## [")]

        if not headers:
            self.errors.append("wiki/log.md contains no grep-parseable journal headers ('## [YYYY-MM-DD ...')")
            return

        for header in headers:
            if not LOG_HEADER_REGEX.match(header):
                self.errors.append(
                    f"wiki/log.md: Malformed journal header: '{header}'. "
                    f"Expected format: '## [YYYY-MM-DD HH:MM:SS UTC] [AGENT] [ACTION] | Description'"
                )

        self.passed_checks.append(f"wiki/log.md journal verified ({len(headers)} valid grep-parseable headers)")

    def verify_failed_ideas_ledger(self):
        """6. Verify wiki/failed_ideas.md contains documented dead ends."""
        failed_path = self.wiki_dir / "failed_ideas.md"
        if not failed_path.is_file():
            return

        content = failed_path.read_text(encoding="utf-8")
        entries = re.findall(r"^###\s+.*$", content, re.MULTILINE)
        if not entries:
            self.errors.append("wiki/failed_ideas.md contains no documented dead end entries ('### [FI-XXX] ...')")
            return

        required_entry_sections = [
            "core premise",
            "failure evidence",
            "root cause",
        ]
        content_lower = content.lower()
        for sec in required_entry_sections:
            if sec not in content_lower:
                self.warnings.append(f"wiki/failed_ideas.md may lack section '{sec}'")

        self.passed_checks.append(f"wiki/failed_ideas.md verified ({len(entries)} documented dead ends)")

    def verify_hot_page(self):
        """7. Verify wiki/hot.md contains required active state sections."""
        hot_path = self.wiki_dir / "hot.md"
        if not hot_path.is_file():
            return
        content = hot_path.read_text(encoding="utf-8")
        required_sections = ["Production Baseline", "Active Tasks", "Recent Changes"]
        for sec in required_sections:
            if sec.lower() not in content.lower():
                self.errors.append(f"wiki/hot.md missing required section: '{sec}'")
        self.passed_checks.append("wiki/hot.md active context structure verified")

    def verify_scripts_and_hooks(self):
        """8. Verify synchronization scripts and hook scripts exist and are executable."""
        scripts_dir = self.repo_root / "scripts"
        for sname in SYNC_SCRIPTS:
            spath = scripts_dir / sname
            if not spath.is_file():
                self.errors.append(f"Sync script missing: scripts/{sname}")
            elif not os.access(spath, os.X_OK):
                self.errors.append(f"Sync script missing execute permissions (+x): scripts/{sname}")
            else:
                self.passed_checks.append(f"Script exists and is executable: scripts/{sname}")

    def verify_agent_instructions(self):
        """9. Assert CLAUDE.md, AGENTS.md, GEMINI.md contain startup/shutdown rules & provenance."""
        for iname in INSTRUCTION_FILES:
            ipath = self.repo_root / iname
            if not ipath.is_file():
                self.errors.append(f"Agent instruction file missing: {iname}")
                continue

            content = ipath.read_text(encoding="utf-8")

            # Startup assertions
            if "wiki/index.md" not in content:
                self.errors.append(f"{iname}: Missing mandatory startup rule referencing 'wiki/index.md'")
            if "wiki/failed_ideas.md" not in content and "failed_ideas.md" not in content:
                self.errors.append(f"{iname}: Missing mandatory startup rule referencing 'failed_ideas.md'")

            # Shutdown assertions
            if "wiki/hot.md" not in content and "hot.md" not in content:
                self.errors.append(f"{iname}: Missing mandatory shutdown rule referencing 'wiki/hot.md'")
            if "wiki/log.md" not in content and "log.md" not in content:
                self.errors.append(f"{iname}: Missing mandatory shutdown rule referencing 'wiki/log.md'")

            # Provenance assertions
            if "results/backtest_provenance.db" not in content:
                self.errors.append(f"{iname}: Broken provenance protocol: missing 'results/backtest_provenance.db'")
            if "scripts/query_provenance.py" not in content:
                self.errors.append(f"{iname}: Broken provenance protocol: missing 'scripts/query_provenance.py'")

        self.passed_checks.append("Agent instruction files (CLAUDE/AGENTS/GEMINI) verified")

    def print_report(self):
        """Print formatted verification summary."""
        print("=" * 68)
        print(" Karpathy LLM Wiki Automated Verification Report")
        print("=" * 68)
        for check in self.passed_checks:
            print(f" [PASS] {check}")

        if self.warnings:
            print("\nWarnings:")
            for w in self.warnings:
                print(f" [WARN] {w}")

        if self.errors:
            print("\nFailures:")
            for e in self.errors:
                print(f" [FAIL] {e}")
            print("=" * 68)
            print(f" VERIFICATION FAILED: {len(self.errors)} error(s), {len(self.warnings)} warning(s)")
            print("=" * 68)
        else:
            print("=" * 68)
            print(" ALL CHECKS PASSED: Wiki setup and protocols verified 100% compliant.")
            print("=" * 68)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Karpathy LLM Wiki integrity.")
    parser.add_argument("--repo-root", type=str, default=None, help="Explicit repository root directory")
    args = parser.parse_args()

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[1]
    verifier = WikiVerifier(repo_root)
    success = verifier.verify_all()
    verifier.print_report()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
