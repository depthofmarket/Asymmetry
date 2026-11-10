"""
tests/test_wiki_adversarial_stress.py — Empirical Adversarial Stress Harness for Karpathy LLM Wiki.

Empirically challenges:
1. Frontmatter Parser robustness: colons, quotes, comments, empty values, lists, type confusion.
2. Markdown Link & Anchor Resolution: relative paths, slugification, code-block isolation, path traversals.
3. Log Journal Grep-Parseability: ISO UTC formats, timezone enforcement, action casing, grep behavior.
4. Quantitative Provenance & Instruction Integrity: verbatim Golden Rules and lifecycle protocols.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_wiki_integrity import (
    ALLOWED_STATUSES,
    CORE_WIKI_FILES,
    DATE_REGEX,
    LOG_HEADER_REGEX,
    WikiVerifier,
    extract_headings,
    extract_markdown_links,
    parse_frontmatter,
    slugify_heading,
)


class TestFrontmatterParserAdversarial:
    """Stress-test stdlib YAML frontmatter parser against malicious and edge-case inputs."""

    def test_colons_in_values_quoted_and_unquoted(self):
        """Verify handling of colons inside values (e.g. titles with subtitles or URLs)."""
        content_quoted = """---
title: "Strategy 1: Morning Value Area Breakout (09:45 ET)"
tags: ["strategies", "s1"]
created: "2026-11-05"
updated: "2026-11-05"
status: "active"
---
# Strategy 1: Morning Value Area Breakout (09:45 ET)
Body text.
"""
        fm, body = parse_frontmatter(content_quoted)
        assert fm is not None
        assert fm["title"] == "Strategy 1: Morning Value Area Breakout (09:45 ET)"

        content_unquoted = """---
title: Strategy 1: Morning Value Area Breakout
tags: ["strategies", "s1"]
created: 2026-11-05
updated: 2026-11-05
status: active
---
# Strategy 1: Morning Value Area Breakout
Body text.
"""
        fm2, _ = parse_frontmatter(content_unquoted)
        assert fm2 is not None
        assert fm2["title"] == "Strategy 1: Morning Value Area Breakout"

    def test_url_with_port_in_frontmatter(self):
        """Verify values containing multiple colons such as full URLs with ports."""
        content = """---
title: "API Endpoint Spec"
source_url: https://internal.trading.net:8443/v1/quotes
status: active
---
# Title
"""
        fm, _ = parse_frontmatter(content)
        assert fm is not None
        assert fm["source_url"] == "https://internal.trading.net:8443/v1/quotes"

    def test_hash_in_value_comment_stripping(self):
        """
        Verify that '#' inside quotes is preserved and not stripped as an inline comment.
        """
        content = """---
title: "Trading Issue # 104"
status: active
---
# Title
"""
        fm, _ = parse_frontmatter(content)
        assert fm is not None
        assert fm["title"] == "Trading Issue # 104"

    def test_inline_list_with_commas(self):
        """
        Verify inline list parsing behavior: [item1, item2].
        """
        content = """---
tags: [tag1, tag2, tag3]
status: active
---
# Title
"""
        fm, _ = parse_frontmatter(content)
        assert fm is not None
        assert fm["tags"] == ["tag1", "tag2", "tag3"]

    def test_empty_keys_default_to_list(self):
        """Expose parser behavior when key is provided without a value."""
        content = """---
title:
tags:
  - alpha
  - beta
status: active
---
# Title
"""
        fm, _ = parse_frontmatter(content)
        assert fm is not None
        assert fm["title"] == []
        assert fm["tags"] == ["alpha", "beta"]

    def test_status_enum_validation(self):
        """Verify strict status validation against ALLOWED_STATUSES."""
        for status in ALLOWED_STATUSES:
            assert status.islower()

        # Reject uppercase and arbitrary statuses
        invalid_statuses = ["ACTIVE", "Active", "Experimental", "invalid_status", "pending", ""]
        for bad in invalid_statuses:
            assert bad not in ALLOWED_STATUSES

    def test_type_confusion_title_as_list_crash_resilience(self):
        """
        Directly test WikiVerifier.verify_topic_frontmatter_and_headings when title
        is parsed as a list (e.g. from 'title:\n  - item' or 'title: []').
        Demonstrates the AttributeError 'list' object has no attribute 'lower'.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            wiki = td / "wiki"
            wiki.mkdir()
            for f in CORE_WIKI_FILES:
                (wiki / f).write_text("stub", encoding="utf-8")

            bad_page = wiki / "type_confusion.md"
            bad_page.write_text("""---
title:
  - list title item
tags:
  - test
created: 2026-11-05
updated: 2026-11-05
status: active
---
# Test Heading
""", encoding="utf-8")

            verifier = WikiVerifier(td)
            with pytest.raises(AttributeError, match="'list' object has no attribute 'lower'"):
                verifier.verify_topic_frontmatter_and_headings()


class TestMarkdownLinkAndAnchorAdversarial:
    """Stress-test link extraction, heading extraction, and anchor resolution."""

    def test_slugify_heading_variations(self):
        """Verify slugification across symbols, numbers, and casing."""
        assert slugify_heading("Executive Summary") == "executive-summary"
        assert slugify_heading("1. Technical Specification") == "1-technical-specification"
        assert slugify_heading("R&D / Risk-Adjusted Return (2026)") == "rd-risk-adjusted-return-2026"
        assert slugify_heading("  Extra   Spaces  ") == "extra-spaces"

    def test_code_block_comment_heading_leakage(self):
        """
        Expose that extract_headings extracts comments from inside fenced code blocks.
        """
        content = """# Actual Heading

```python
# comment_inside_code_block
x = 1
```

## Real Subheading
"""
        headings = extract_headings(content)
        assert "actual-heading" in headings
        assert "real-subheading" in headings
        # Note: # inside code block is parsed as a heading slug
        assert "comment_inside_code_block" in headings

    def test_case_sensitive_anchor_resolution(self):
        """
        Verify that anchor matching requires lowercase slug in markdown links.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            wiki = td / "wiki"
            wiki.mkdir()
            for f in CORE_WIKI_FILES:
                (wiki / f).write_text("stub", encoding="utf-8")

            page = wiki / "anchor_test.md"
            page.write_text("""---
title: Anchor Test
tags:
  - test
created: 2026-11-05
updated: 2026-11-05
status: active
---
# Anchor Test
## Section One

[Valid Lowercase](#section-one)
[Invalid MixedCase](#Section-One)
""", encoding="utf-8")

            verifier = WikiVerifier(td)
            verifier.verify_markdown_links()
            # Only the mixed-case anchor should fail
            assert any("Broken same-page anchor '#Section-One'" in err for err in verifier.errors)
            assert not any("Broken same-page anchor '#section-one'" in err for err in verifier.errors)

    def test_directory_traversal_outside_repo_root(self):
        """
        Stress-test link resolution against path traversal pointing outside repo.
        Demonstrates that resolving to an existing host file (/etc/hosts) currently bypasses errors.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            wiki = td / "wiki"
            wiki.mkdir()
            for f in CORE_WIKI_FILES:
                (wiki / f).write_text("stub", encoding="utf-8")

            page = wiki / "traversal_test.md"
            # Target /etc/hosts via relative traversal
            rel_traversal = "../../../../../../../../../../../../../../../etc/hosts"
            page.write_text(f"""---
title: Traversal Test
tags:
  - test
created: 2026-11-05
updated: 2026-11-05
status: active
---
# Traversal Test
[System Hosts]({rel_traversal})
""", encoding="utf-8")

            verifier = WikiVerifier(td)
            verifier.verify_markdown_links()
            # Since /etc/hosts exists on Darwin, resolve() succeeds and passes without checking repo bounds
            traversal_errs = [e for e in verifier.errors if "etc/hosts" in e]
            assert len(traversal_errs) == 0, "Current implementation allows traversal to existing host files"


class TestLogJournalGrepParseabilityAdversarial:
    """Stress-test log header regex and grep extraction behavior."""

    def test_canonical_header_regex_acceptance(self):
        """Verify standard canonical log header passes."""
        canonical = "## [2026-11-05 18:55:00 UTC] [worker] [SETUP] | Initialized Karpathy LLM Wiki knowledge base"
        assert LOG_HEADER_REGEX.match(canonical) is not None

    def test_header_regex_rejections(self):
        """Verify rejection of malformed or non-compliant headers."""
        bad_cases = [
            "## 2026-11-05 18:55:00 UTC [worker] [SETUP] | Missing opening bracket",
            "## [2026-11-05 18:55:00] [worker] [SETUP] | Missing UTC timezone",
            "## [2026-11-05 18:55:00 EST] [worker] [SETUP] | Non-UTC timezone EST",
            "## [2026-11-05 18:55:00 +00:00] [worker] [SETUP] | Non-UTC offset",
            "## [2026-11-05 18:55:00 UTC] [worker] [setup] | Lowercase action",
            "## [2026-11-05 18:55:00 UTC] [worker] [SETUP] - Dash instead of pipe",
            "## [2026-11-05T18:55:00Z] [worker] [SETUP] | ISO-T format",
            "### [2026-11-05 18:55:00 UTC] [worker] [SETUP] | H3 instead of H2",
            "## [2026-11-05 18:55:00 UTC] [worker] [SETUP] | ",  # Empty description
        ]
        for line in bad_cases:
            assert LOG_HEADER_REGEX.match(line) is None, f"Should reject malformed header: '{line}'"

    def test_grep_command_extracts_only_genuine_headers(self):
        """Verify that CLI command 'grep \"^## \\[\" wiki/log.md' extracts only valid headers."""
        log_path = ROOT / "wiki" / "log.md"
        assert log_path.is_file()

        proc = subprocess.run(
            ["grep", "^## \\[", str(log_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        assert len(lines) >= 1, "Must extract at least one header"

        for line in lines:
            assert LOG_HEADER_REGEX.match(line), f"Extracted line does not conform to regex: '{line}'"


class TestQuantitativeProvenanceAndAgentInstructionsAdversarial:
    """Stress-test preservation of the 5 Golden Rules and wiki lifecycle rules."""

    def test_golden_rules_verbatim_presence(self):
        """Assert verbatim presence of all 5 Golden Rules in CLAUDE.md, AGENTS.md, GEMINI.md."""
        rules = [
            "One source of truth",
            "No naked numbers",
            "Provenance footers on every tool",
            "Warnings travel with the number",
            "Recording is automatic, not discipline",
        ]
        for fname in ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]:
            content = (ROOT / fname).read_text(encoding="utf-8")
            for r in rules:
                assert re.search(rf"{r}", content, re.IGNORECASE), (
                    f"{fname} missing Golden Rule '{r}'"
                )

    def test_provenance_store_and_cli_instructions(self):
        """Verify presence of DB path and CLI query commands in all instruction files."""
        for fname in ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]:
            content = (ROOT / fname).read_text(encoding="utf-8")
            assert "results/backtest_provenance.db" in content, f"{fname} missing DB reference"
            assert "query_provenance.py" in content, f"{fname} missing CLI tool reference"

    def test_startup_and_shutdown_wiki_protocols(self):
        """Verify startup and shutdown lifecycle protocols across instruction files."""
        for fname in ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]:
            content = (ROOT / fname).read_text(encoding="utf-8")
            # Startup
            assert "wiki/index.md" in content or "index.md" in content, f"{fname} missing index.md rule"
            assert "failed_ideas.md" in content, f"{fname} missing failed_ideas.md rule"
            # Shutdown
            assert "hot.md" in content, f"{fname} missing hot.md rule"
            assert "log.md" in content, f"{fname} missing log.md rule"

    @pytest.mark.generated_results
    def test_provenance_cli_live_execution(self):
        """Execute query_provenance.py to ensure the underlying provenance DB is intact."""
        cli_path = ROOT / "scripts" / "query_provenance.py"
        assert cli_path.is_file()

        # 1. Query list
        proc_list = subprocess.run(
            [sys.executable, str(cli_path), "--list"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Total verified runs:" in proc_list.stdout

        # 2. Query specific stat
        proc_stat = subprocess.run(
            [
                sys.executable,
                str(cli_path),
                "--strategy",
                "morning_va_breakout_s1",
                "--stat",
                "profit_factor",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "1.65" in proc_stat.stdout
        assert "PROVENANCE VERIFICATION FOOTER" in proc_stat.stdout
