"""
test_wiki_integrity.py — Pytest Automated Verification Suite for Karpathy LLM Wiki.

Verifies Requirements R1, R2, R3, R4:
  - R1: Core directory and markdown structure (index, log, hot, SCHEMA, failed_ideas).
  - R2: Agent instruction integration (CLAUDE.md, AGENTS.md, GEMINI.md) with startup/shutdown
        rules and 100% quantitative provenance preservation.
  - R3: Git synchronization and automation scripts (sync_wiki.sh, wiki_sync.py, install_wiki_hooks.sh).
  - R4: Programmatic validation of cross-links, SCHEMA frontmatter, grep-parseable logs,
        and hook execution paths.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WIKI_DIR = ROOT / "wiki"
SCRIPTS_DIR = ROOT / "scripts"
from scripts.verify_wiki_integrity import (
    ALLOWED_STATUSES,
    CORE_WIKI_FILES,
    DATE_REGEX,
    LOG_HEADER_REGEX,
    WikiVerifier,
    extract_headings,
    extract_markdown_links,
    parse_frontmatter,
)


# ─── TESTS ──────────────────────────────────────────────────────────────────

def test_wiki_core_directory_and_files_exist():
    """Verify wiki/ directory and all 5 core files exist and are non-empty."""
    assert WIKI_DIR.is_dir(), f"Wiki directory does not exist at {WIKI_DIR}"
    for fname in CORE_WIKI_FILES:
        fpath = WIKI_DIR / fname
        assert fpath.is_file(), f"Core wiki file missing: {fpath}"
        assert fpath.stat().st_size > 0, f"Core wiki file is empty: {fpath}"


def test_wiki_schema_specification():
    """Verify SCHEMA.md defines page conventions, log format, frontmatter, and failed ideas."""
    schema_file = WIKI_DIR / "SCHEMA.md"
    assert schema_file.is_file(), "SCHEMA.md missing"
    content = schema_file.read_text(encoding="utf-8")
    for keyword in ["Frontmatter", "kebab-case", "log.md", "failed_ideas.md", "hot.md", "index.md"]:
        assert keyword.lower() in content.lower(), f"SCHEMA.md missing specification for '{keyword}'"


def test_wiki_index_catalog_coverage():
    """Verify index.md catalogs wiki pages and contains valid relative links."""
    index_file = WIKI_DIR / "index.md"
    assert index_file.is_file(), "index.md missing"
    content = index_file.read_text(encoding="utf-8")
    links = extract_markdown_links(content)
    assert len(links) >= 4, f"index.md has too few links ({len(links)} found)"

    # Verify that all linked targets exist on disk
    for text, target in links:
        if target.startswith(("http://", "https://")):
            continue
        file_target = target.split("#")[0] if "#" in target else target
        target_path = (index_file.parent / file_target).resolve()
        assert target_path.exists(), f"Broken link in index.md: [{text}]({target}) -> {target_path} missing"


def test_wiki_markdown_internal_links_resolve():
    """Verify that every relative markdown link in every wiki file resolves to an existing file."""
    assert WIKI_DIR.is_dir(), "wiki directory missing"
    broken_links = []
    headings_cache: Dict[Path, Set[str]] = {}

    for md_file in WIKI_DIR.rglob("*.md"):
        content = md_file.read_text(encoding="utf-8")
        links = extract_markdown_links(content)
        rel_src = md_file.relative_to(ROOT)

        for text, target in links:
            if target.startswith(("http://", "https://", "mailto:", "ftp://")):
                continue

            if target.startswith("#"):
                anchor = target[1:]
                if md_file not in headings_cache:
                    headings_cache[md_file] = extract_headings(content)
                if anchor not in headings_cache[md_file]:
                    broken_links.append(f"{rel_src}: broken anchor '{target}' for text '{text}'")
                continue

            file_target = target
            anchor = None
            if "#" in target:
                file_target, anchor = target.split("#", 1)

            resolved_path = (md_file.parent / file_target).resolve()
            if not resolved_path.exists():
                broken_links.append(f"{rel_src}: broken link '{target}' -> {resolved_path} not found")
            elif resolved_path.is_file() and anchor:
                if resolved_path not in headings_cache:
                    headings_cache[resolved_path] = extract_headings(resolved_path.read_text(encoding="utf-8"))
                if anchor not in headings_cache[resolved_path]:
                    broken_links.append(f"{rel_src}: broken anchor '{anchor}' in target {resolved_path.name}")

    assert not broken_links, "Broken markdown links found:\n" + "\n".join(broken_links)


def test_wiki_topic_pages_frontmatter_conformance():
    """Verify all domain topic pages have valid YAML frontmatter, required keys, and H1 header."""
    assert WIKI_DIR.is_dir(), "wiki directory missing"
    errors = []

    for md_file in WIKI_DIR.rglob("*.md"):
        if md_file.parent == WIKI_DIR and md_file.name in CORE_WIKI_FILES:
            continue

        content = md_file.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)
        rel_path = md_file.relative_to(ROOT)

        if fm is None:
            errors.append(f"{rel_path}: missing YAML frontmatter")
            continue

        for key in ["title", "tags", "created", "updated", "status"]:
            if key not in fm:
                errors.append(f"{rel_path}: frontmatter missing key '{key}'")

        if "status" in fm and fm["status"] not in ALLOWED_STATUSES:
            errors.append(f"{rel_path}: invalid status '{fm['status']}'")

        if "created" in fm and not DATE_REGEX.match(str(fm["created"])):
            errors.append(f"{rel_path}: invalid created date '{fm['created']}' (must be YYYY-MM-DD)")

        if "updated" in fm and not DATE_REGEX.match(str(fm["updated"])):
            errors.append(f"{rel_path}: invalid updated date '{fm['updated']}' (must be YYYY-MM-DD)")

        if not re.search(r"^#\s+.+$", body, re.MULTILINE):
            errors.append(f"{rel_path}: missing top-level H1 header ('# Title')")

    assert not errors, "Frontmatter errors found:\n" + "\n".join(errors)


def test_wiki_log_journal_format_and_grep_parseability():
    """Verify wiki/log.md contains grep-parseable ISO UTC headers."""
    log_file = WIKI_DIR / "log.md"
    assert log_file.is_file(), "log.md missing"
    content = log_file.read_text(encoding="utf-8")
    headers = [line for line in content.splitlines() if line.startswith("## [")]

    assert len(headers) >= 1, "log.md must contain at least 1 journal entry header"
    for header in headers:
        assert LOG_HEADER_REGEX.match(header), (
            f"Malformed log header in log.md: '{header}'. "
            "Must match format: '## [YYYY-MM-DD HH:MM:SS UTC] [AGENT] [ACTION] | Description'"
        )


def test_wiki_failed_ideas_ledger_structure():
    """Verify failed_ideas.md contains documented dead ends with root cause analysis."""
    failed_file = WIKI_DIR / "failed_ideas.md"
    assert failed_file.is_file(), "failed_ideas.md missing"
    content = failed_file.read_text(encoding="utf-8")
    entries = re.findall(r"^###\s+.*$", content, re.MULTILINE)
    assert len(entries) >= 1, "failed_ideas.md must contain at least one documented dead end entry"
    content_lower = content.lower()
    for term in ["premise", "root cause"]:
        assert term in content_lower, f"failed_ideas.md should contain section '{term}'"


def test_wiki_hot_page_active_state():
    """Verify hot.md contains current status and active initiatives."""
    hot_file = WIKI_DIR / "hot.md"
    assert hot_file.is_file(), "hot.md missing"
    content = hot_file.read_text(encoding="utf-8")
    for sec in ["Production Baseline", "Active Tasks", "Recent Changes"]:
        assert sec.lower() in content.lower(), f"hot.md missing section '{sec}'"


def test_wiki_sync_scripts_executable():
    """Verify scripts/sync_wiki.sh, scripts/wiki_sync.py, and scripts/install_wiki_hooks.sh exist and are executable."""
    for script_name in ["sync_wiki.sh", "wiki_sync.py", "install_wiki_hooks.sh"]:
        spath = SCRIPTS_DIR / script_name
        assert spath.is_file(), f"Missing script: scripts/{script_name}"
        assert os.access(spath, os.X_OK), f"Script scripts/{script_name} is not executable (+x)"


def test_wiki_sync_cli_dry_run():
    """Verify wiki_sync.py and sync_wiki.sh execute cleanly in status and dry-run modes."""
    script_py = SCRIPTS_DIR / "wiki_sync.py"
    assert script_py.is_file(), "scripts/wiki_sync.py missing"

    # 1. Test python scripts/wiki_sync.py status
    proc_status = subprocess.run(
        [sys.executable, str(script_py), "status"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "[WIKI_SYNC] Knowledge Base Status" in proc_status.stdout

    # 2. Test python scripts/wiki_sync.py start --dry-run
    proc_start = subprocess.run(
        [sys.executable, str(script_py), "start", "--dry-run"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Session Start" in proc_start.stdout

    # 3. Test python scripts/wiki_sync.py stop --dry-run
    proc_stop = subprocess.run(
        [sys.executable, str(script_py), "stop", "--dry-run"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Session Stop" in proc_stop.stdout


def test_agent_instruction_startup_shutdown_and_provenance_assertions():
    """Verify CLAUDE.md, AGENTS.md, and GEMINI.md contain startup/shutdown rules and 100% provenance rules."""
    for fname in ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]:
        fpath = ROOT / fname
        assert fpath.is_file(), f"Agent instruction file {fname} missing"
        content = fpath.read_text(encoding="utf-8")

        # Startup rules
        assert "wiki/index.md" in content, f"{fname} missing reference to 'wiki/index.md'"
        assert "failed_ideas.md" in content, f"{fname} missing reference to 'failed_ideas.md'"

        # Shutdown rules
        assert "hot.md" in content, f"{fname} missing reference to 'hot.md'"
        assert "log.md" in content, f"{fname} missing reference to 'log.md'"

        # Provenance preservation
        assert "results/backtest_provenance.db" in content, f"{fname} missing 'results/backtest_provenance.db'"
        assert "query_provenance.py" in content, f"{fname} missing 'query_provenance.py'"
        assert "One source of truth" in content or "One Source of Truth" in content, (
            f"{fname} missing 5 Golden Rules rule 1"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ITERATION 2 HARDENING TESTS (Regression Prevention & Safety Invariants)
# ─────────────────────────────────────────────────────────────────────────────

def test_wiki_sync_staging_isolation(tmp_path: Path):
    """
    Verify that wiki_sync.py stop commits ONLY files in wiki/ and leaves
    other staged files (outside wiki/) staged and uncommitted in the index.
    """
    from scripts.wiki_sync import cmd_stop

    def run_git_local(args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + args,
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=True,
        )

    # 1. Initialize git repo and configure identity
    run_git_local(["init"])
    run_git_local(["config", "user.name", "Test Committer"])
    run_git_local(["config", "user.email", "committer@test.local"])
    run_git_local(["config", "commit.gpgsign", "false"])

    # 2. Set up initial files across source and wiki
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    strategy_file = src_dir / "strategy.py"
    strategy_file.write_text("class Strategy:\n    pass\n", encoding="utf-8")

    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir(parents=True)
    index_file = wiki_dir / "index.md"
    index_file.write_text("# Knowledge Base\n\nInitial index.\n", encoding="utf-8")
    log_file = wiki_dir / "log.md"
    log_file.write_text("## [2026-11-05 12:00:00 UTC] [worker] [INIT] | Initial\n", encoding="utf-8")

    run_git_local(["add", "."])
    run_git_local(["commit", "-m", "Initial baseline commit"])

    # 3. Stage changes outside wiki/
    strategy_file.write_text("class Strategy:\n    # Staged work in progress\n    wip = True\n", encoding="utf-8")
    run_git_local(["add", str(strategy_file)])

    new_code_file = src_dir / "new_indicator.py"
    new_code_file.write_text("# New uncommitted indicator\n", encoding="utf-8")
    run_git_local(["add", str(new_code_file)])

    # Verify both non-wiki files are staged in the git index
    pre_status = run_git_local(["status", "--porcelain"]).stdout
    assert "M  src/strategy.py" in pre_status or "M src/strategy.py" in pre_status
    assert "A  src/new_indicator.py" in pre_status or "A src/new_indicator.py" in pre_status

    # 4. Modify a wiki file
    index_file.write_text("# Knowledge Base\n\nUpdated index with new notes.\n", encoding="utf-8")

    # 5. Run wiki_sync.py stop
    ret = cmd_stop(repo_root=tmp_path, no_push=True)
    assert ret == 0, f"cmd_stop failed with exit code {ret}"

    # 6. Assertions on the new HEAD commit
    diff_tree = run_git_local(["diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"])
    committed_files = diff_tree.stdout.strip().splitlines()

    for cf in committed_files:
        assert cf.startswith("wiki/"), f"Staging leak! Non-wiki file committed in HEAD: {cf}"
    assert "wiki/index.md" in committed_files
    assert "src/strategy.py" not in committed_files
    assert "src/new_indicator.py" not in committed_files

    # 7. Assertions on the remaining Git index
    post_status = run_git_local(["status", "--porcelain"]).stdout.splitlines()
    strategy_st = next((line for line in post_status if "src/strategy.py" in line), None)
    indicator_st = next((line for line in post_status if "src/new_indicator.py" in line), None)
    wiki_st = next((line for line in post_status if "wiki/index.md" in line), None)

    assert strategy_st is not None, "src/strategy.py lost from git status!"
    assert strategy_st.startswith("M "), f"src/strategy.py is no longer staged: '{strategy_st}'"

    assert indicator_st is not None, "src/new_indicator.py lost from git status!"
    assert indicator_st.startswith("A "), f"src/new_indicator.py is no longer staged: '{indicator_st}'"

    assert wiki_st is None, f"wiki/index.md should have been committed but remains dirty: '{wiki_st}'"


def test_wiki_sync_porcelain_path_parsing(tmp_path: Path):
    """
    Verify that porcelain status parsing handles unstaged leading whitespace correctly
    and does not corrupt or truncate paths (e.g. slicing 'wiki/...' into 'iki/...').
    """
    from scripts.wiki_sync import get_wiki_changes

    def run_git_local(args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + args,
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=True,
        )

    run_git_local(["init"])
    run_git_local(["config", "user.name", "Tester"])
    run_git_local(["config", "user.email", "test@test.local"])
    run_git_local(["config", "commit.gpgsign", "false"])

    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "SCHEMA.md").write_text("# Schema\n", encoding="utf-8")
    (wiki_dir / "hot.md").write_text("# Hot\n", encoding="utf-8")
    (wiki_dir / "index.md").write_text("# Index\n", encoding="utf-8")

    run_git_local(["add", "."])
    run_git_local(["commit", "-m", "Initial commit"])

    # 1. Unstaged modification: git status --porcelain formats as " M wiki/SCHEMA.md"
    (wiki_dir / "SCHEMA.md").write_text("# Schema v2 (unstaged)\n", encoding="utf-8")

    # 2. Staged modification: git status --porcelain formats as "M  wiki/hot.md"
    (wiki_dir / "hot.md").write_text("# Hot v2 (staged)\n", encoding="utf-8")
    run_git_local(["add", "wiki/hot.md"])

    # 3. Untracked file: git status --porcelain formats as "?? wiki/new_notes.md"
    (wiki_dir / "new_notes.md").write_text("# Untracked notes\n", encoding="utf-8")

    changes = get_wiki_changes(tmp_path)

    # Must contain 3 changes
    assert len(changes) == 3, f"Expected 3 changes, got {len(changes)}: {changes}"

    paths = {filepath: status for status, filepath in changes}

    # Verify no paths suffer from leading-character truncation ('iki/...')
    for path in paths:
        assert not path.startswith("iki/"), f"Detected path truncation bug: '{path}'"
        assert path.startswith("wiki/"), f"Path should start with 'wiki/': '{path}'"

    # Verify exact path and status mappings
    assert "wiki/SCHEMA.md" in paths, f"Missing wiki/SCHEMA.md in parsed paths: {list(paths.keys())}"
    assert paths["wiki/SCHEMA.md"] == "M", f"Expected status 'M', got '{paths['wiki/SCHEMA.md']}'"

    assert "wiki/hot.md" in paths, f"Missing wiki/hot.md in parsed paths: {list(paths.keys())}"
    assert paths["wiki/hot.md"] == "M", f"Expected status 'M', got '{paths['wiki/hot.md']}'"

    assert "wiki/new_notes.md" in paths, f"Missing wiki/new_notes.md in parsed paths: {list(paths.keys())}"
    assert paths["wiki/new_notes.md"] == "??", f"Expected status '??', got '{paths['wiki/new_notes.md']}'"


def test_pre_commit_hook_blocks_invalid_wiki_content(tmp_path: Path):
    """
    Verify that invoking .git/hooks/pre-commit rejects broken links or invalid frontmatter
    when wiki/ files are staged, while cleanly bypassing non-wiki staged files.
    """
    import shutil

    def run_git_local(args: List[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + args,
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=True,
        )

    # 1. Initialize repo
    run_git_local(["init"])
    run_git_local(["config", "user.name", "Hook Tester"])
    run_git_local(["config", "user.email", "hook@test.local"])
    run_git_local(["config", "commit.gpgsign", "false"])

    # 2. Copy baseline wiki files and verification scripts into tmp_path
    shutil.copytree(ROOT / "wiki", tmp_path / "wiki")
    shutil.copytree(ROOT / "config", tmp_path / "config")

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True)
    for s in ["verify_wiki_integrity.py", "sync_wiki.sh", "wiki_sync.py", "install_wiki_hooks.sh"]:
        shutil.copy(ROOT / "scripts" / s, scripts_dir / s)
        (scripts_dir / s).chmod(0o755)

    for doc in ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]:
        shutil.copy(ROOT / doc, tmp_path / doc)

    # 3. Install pre-commit hook
    install_hooks = subprocess.run(
        ["bash", str(scripts_dir / "install_wiki_hooks.sh")],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert install_hooks.returncode == 0, install_hooks.stderr
    hook_file = tmp_path / ".git" / "hooks" / "pre-commit"
    assert hook_file.is_file()

    run_git_local(["add", "."])
    run_git_local(["commit", "-m", "Initial clean repository state"])

    # ── Subtest A: Broken Markdown Link Staged ──
    broken_md = tmp_path / "wiki" / "strategies" / "test_broken_link.md"
    broken_md.write_text("""---
title: Test Broken Link
tags: [test]
created: 2026-11-05
updated: 2026-11-05
status: active
---
# Test Broken Link
[Broken target](nonexistent_document_file_99999.md)
""", encoding="utf-8")
    run_git_local(["add", str(broken_md)])

    # Direct hook invocation must fail
    hook_res_broken = subprocess.run([str(hook_file)], cwd=str(tmp_path), capture_output=True, text=True)
    assert hook_res_broken.returncode != 0, "Hook should have failed on broken link"
    assert "Wiki integrity verification failed" in hook_res_broken.stderr or "Broken link" in hook_res_broken.stdout

    # git commit must be intercepted and rejected
    commit_res_broken = subprocess.run(["git", "commit", "-m", "Commit with broken link"], cwd=str(tmp_path), capture_output=True, text=True)
    assert commit_res_broken.returncode != 0, "git commit should have been blocked by pre-commit hook"

    # Clean up broken file from staging and disk
    broken_md.unlink()
    run_git_local(["rm", str(broken_md)])

    # ── Subtest B: Invalid Frontmatter Status Staged ──
    bad_fm_md = tmp_path / "wiki" / "strategies" / "test_bad_status.md"
    bad_fm_md.write_text("""---
title: Test Bad Status
tags: [test]
created: 2026-11-05
updated: 2026-11-05
status: totally_invalid_status_enum
---
# Test Bad Status
Some content.
""", encoding="utf-8")
    run_git_local(["add", str(bad_fm_md)])

    # Direct hook invocation must fail
    hook_res_fm = subprocess.run([str(hook_file)], cwd=str(tmp_path), capture_output=True, text=True)
    assert hook_res_fm.returncode != 0, "Hook should have failed on invalid frontmatter status"

    # git commit must be intercepted and rejected
    commit_res_fm = subprocess.run(["git", "commit", "-m", "Commit with bad status"], cwd=str(tmp_path), capture_output=True, text=True)
    assert commit_res_fm.returncode != 0, "git commit should have been blocked by pre-commit hook"

    # Clean up bad status file
    bad_fm_md.unlink()
    run_git_local(["rm", str(bad_fm_md)])

    # ── Subtest C: Non-Wiki File Staged (Fast-path Bypass) ──
    outside_file = tmp_path / "outside_code.py"
    outside_file.write_text("x = 42\n", encoding="utf-8")
    run_git_local(["add", str(outside_file)])

    # Hook should immediately bypass without running verification
    hook_res_outside = subprocess.run([str(hook_file)], cwd=str(tmp_path), capture_output=True, text=True)
    assert hook_res_outside.returncode == 0, f"Hook should bypass for non-wiki staged files, got {hook_res_outside.returncode}"

    # Commit should succeed cleanly
    commit_res_outside = subprocess.run(["git", "commit", "-m", "Commit non-wiki code"], cwd=str(tmp_path), capture_output=True, text=True)
    assert commit_res_outside.returncode == 0, "Commit of non-wiki file should succeed"


def test_verify_wiki_ignores_code_block_links(tmp_path: Path):
    """
    Verify that links inside fenced code blocks (``` or ~~~) and inline code spans (`...`)
    are ignored by link extraction and do not trigger false-positive broken link failures.
    """
    from scripts.verify_wiki_integrity import WikiVerifier, extract_markdown_links

    # 1. Direct unit-level verification on extract_markdown_links
    content_with_code = """# Markdown Linking Guide

[Legitimate Header Link](header_target.md)

Here is a fenced code block illustrating a markdown link example:
```markdown
[Fenced Dummy Link](nonexistent_fenced_example.md)
```

Here is a tilde-fenced code block:
~~~python
# Example comment
dummy_link = "[Tilde Dummy Link](nonexistent_tilde_example.md)"
~~~

Here is an inline code snippet: `[Inline Dummy Link](nonexistent_inline_example.md)`.

[Legitimate Footer Link](footer_target.md)
"""

    links = extract_markdown_links(content_with_code)
    targets = [target for _, target in links]

    # Verify that dummy links inside code blocks are ignored
    assert "nonexistent_fenced_example.md" not in targets, "Fenced code block link was not ignored"
    assert "nonexistent_tilde_example.md" not in targets, "Tilde fenced code block link was not ignored"
    assert "nonexistent_inline_example.md" not in targets, "Inline code span link was not ignored"

    # Verify that legitimate links outside code blocks ARE extracted
    assert ("Legitimate Header Link", "header_target.md") in links
    assert ("Legitimate Footer Link", "footer_target.md") in links
    assert len(links) == 2, f"Expected exactly 2 legitimate links, got {len(links)}: {links}"

    # 2. Integration verification using WikiVerifier
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir(parents=True)
    for fname in CORE_WIKI_FILES:
        (wiki_dir / fname).write_text(f"# {fname}\n", encoding="utf-8")

    # Write a topic page containing illustrative code block links
    topic_page = wiki_dir / "syntax_guide.md"
    topic_page.write_text("""---
title: Syntax Guide
tags: [guide, syntax]
created: 2026-11-05
updated: 2026-11-05
status: active
---
# Syntax Guide

See the active state in [Hot Tracker](hot.md).

Example link syntax:
```markdown
[Example](nonexistent_dummy_target_123.md)
```

And inline `[Sample](nonexistent_dummy_target_456.md)`.
""", encoding="utf-8")

    verifier = WikiVerifier(tmp_path)
    verifier.verify_markdown_links()
    assert len(verifier.errors) == 0, f"Verifier reported false-positive link errors: {verifier.errors}"

    # 3. Sensitivity verification: ensure broken link OUTSIDE code block is caught
    broken_topic = wiki_dir / "broken_guide.md"
    broken_topic.write_text("""---
title: Broken Guide
tags: [broken]
created: 2026-11-05
updated: 2026-11-05
status: active
---
# Broken Guide
[Real Broken Link](definitely_missing_file_789.md)
""", encoding="utf-8")

    verifier_sensitive = WikiVerifier(tmp_path)
    verifier_sensitive.verify_markdown_links()
    assert any("definitely_missing_file_789.md" in err for err in verifier_sensitive.errors), (
        "Verifier failed to report genuine broken link outside code blocks"
    )


def test_sync_wiki_shell_external_invocation():
    """Verify sync_wiki.sh succeeds when invoked from an external directory."""
    script_sh = ROOT / "scripts" / "sync_wiki.sh"
    proc = subprocess.run(
        ["bash", str(script_sh), "status"],
        cwd="/tmp",
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"sync_wiki.sh failed from /tmp: {proc.stderr}"
    assert "[WIKI_SYNC] Knowledge Base Status" in proc.stdout
