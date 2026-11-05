"""
tests/test_challenger_wiki_it2.py — Empirical Challenger Stress Suite for Iteration 2.

Adversarially validates:
1. Markdown code block and inline code link filtering in scripts/verify_wiki_integrity.py.
   - Fenced blocks: ```markdown [fake](broken.md) ``` and multi-line variants.
   - Inline code spans: `[inline](broken.md)` and ``[inline](broken.md)``.
   - Assert code block links are ignored and do NOT trigger false positives.
   - Assert broken links OUTSIDE code blocks are still caught and flagged.
2. Quote-aware frontmatter comment parsing in scripts/verify_wiki_integrity.py.
   - Titles like "Trading Issue # 104" # real comment.
   - Assert scalar is "Trading Issue # 104" and inline comments are cleanly stripped.
   - Single quotes, escaped quotes, list items, and adversarial boundaries.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List

import pytest

from scripts.verify_wiki_integrity import (
    CORE_WIKI_FILES,
    WikiVerifier,
    clean_scalar,
    extract_markdown_links,
    parse_frontmatter,
    strip_code_blocks_and_spans,
    strip_yaml_comment,
)


class TestMarkdownCodeBlockFilteringChallenger:
    """Empirical challenge on code block and inline code link exclusion."""

    @pytest.mark.parametrize(
        "markdown_snippet,description",
        [
            (
                "```markdown [fake](broken.md) ```",
                "Single-line triple-backtick fenced code block",
            ),
            (
                "```markdown\n[fake](broken.md)\n```",
                "Standard multi-line triple-backtick fenced code block",
            ),
            (
                "`[inline](broken.md)`",
                "Single-backtick inline code span",
            ),
            (
                "``[inline](broken.md)``",
                "Double-backtick inline code span",
            ),
            (
                "~~~markdown\n[fake](broken.md)\n~~~",
                "Tilde-fenced multi-line code block",
            ),
            (
                "~~~markdown [fake](broken.md) ~~~",
                "Tilde-fenced single-line code block",
            ),
            (
                "   ```markdown\n   [fake](broken.md)\n   ```",
                "Indented triple-backtick fenced code block",
            ),
            (
                "````markdown\n```markdown\n[fake](broken.md)\n```\n````",
                "Nested 4-backtick code block containing 3-backtick fence",
            ),
        ],
    )
    def test_code_block_links_are_strictly_ignored(self, markdown_snippet: str, description: str):
        """Assert that link extractor ignores links within fenced code and inline spans."""
        links = extract_markdown_links(markdown_snippet)
        assert len(links) == 0, (
            f"Failed for {description}: expected 0 extracted links, got {links}"
        )

    def test_mixed_markdown_extracts_only_prose_links(self):
        """Verify that genuine prose links are extracted while code block links are ignored."""
        content = """# Verification Guide

Here is an illustrative example of broken syntax:
```markdown [fake](broken_fenced.md) ```

Here is an inline snippet: `[inline](broken_inline.md)`.

And a multi-line fenced tutorial:
```markdown
[tutorial](broken_tutorial.md)
```

Now, genuine navigation links:
1. [Schema Reference](SCHEMA.md)
2. [Failed Ideas Ledger](failed_ideas.md#table-of-ruled-out-concepts)
3. [Hot State Summary](hot.md "Current Project Baseline")
"""
        links = extract_markdown_links(content)
        extracted_targets = [target for _, target in links]

        # Assert no dummy code targets are present
        assert "broken_fenced.md" not in extracted_targets
        assert "broken_inline.md" not in extracted_targets
        assert "broken_tutorial.md" not in extracted_targets

        # Assert genuine links are extracted
        assert ("Schema Reference", "SCHEMA.md") in links
        assert (
            "Failed Ideas Ledger",
            "failed_ideas.md#table-of-ruled-out-concepts",
        ) in links
        assert ("Hot State Summary", "hot.md") in links
        assert len(links) == 3

    def test_verifier_end_to_end_false_positive_and_sensitivity(self, tmp_path: Path):
        """
        Integration test with WikiVerifier:
        1. Assert zero false-positive errors on code block links.
        2. Assert sensitivity: broken link outside code block is caught.
        """
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir(parents=True)
        for fname in CORE_WIKI_FILES:
            (wiki_dir / fname).write_text(f"# {fname}\n", encoding="utf-8")

        # Step 1: Create a page with code block links only
        code_page = wiki_dir / "code_examples.md"
        code_page.write_text(
            """---
title: Code Examples
tags: [test, docs]
created: 2026-11-05
updated: 2026-11-05
status: active
---
# Code Examples

Fenced single-line:
```markdown [fake](broken.md) ```

Inline code:
`[inline](broken.md)`

Multi-line fence:
```markdown
[fake_multi](broken_multi.md)
```
""",
            encoding="utf-8",
        )

        verifier_clean = WikiVerifier(tmp_path)
        verifier_clean.verify_markdown_links()
        assert len(verifier_clean.errors) == 0, (
            f"Verifier raised false positive errors on code blocks: {verifier_clean.errors}"
        )

        # Step 2: Append a genuine broken link outside any code block
        code_page.write_text(
            code_page.read_text(encoding="utf-8")
            + "\nGenuine broken link:\n[Missing Target](nonexistent_outside_doc.md)\n",
            encoding="utf-8",
        )

        verifier_broken = WikiVerifier(tmp_path)
        verifier_broken.verify_markdown_links()
        assert len(verifier_broken.errors) == 1, (
            f"Expected exactly 1 broken link error, got {len(verifier_broken.errors)}: {verifier_broken.errors}"
        )
        assert "nonexistent_outside_doc.md" in verifier_broken.errors[0]


class TestFrontmatterQuoteCommentParsingChallenger:
    """Empirical challenge on quote-aware YAML comment parsing."""

    def test_dispatch_canonical_title_with_hash_and_comment(self):
        """
        Directly verify the dispatch prompt scenario:
        title: "Trading Issue # 104" # real comment
        Scalar must be 'Trading Issue # 104' and comment stripped cleanly.
        """
        raw_yaml_line = '"Trading Issue # 104" # real comment'
        comment_stripped = strip_yaml_comment(raw_yaml_line)
        scalar = clean_scalar(comment_stripped)

        assert comment_stripped == '"Trading Issue # 104"'
        assert scalar == "Trading Issue # 104"

        full_doc = """---
title: "Trading Issue # 104" # real comment
tags: [trading, bug]
created: 2026-11-05
updated: 2026-11-05
status: active
---
# Trading Issue # 104
Body content.
"""
        fm, body = parse_frontmatter(full_doc)
        assert fm is not None
        assert fm["title"] == "Trading Issue # 104"
        assert fm["tags"] == ["trading", "bug"]

    def test_single_quoted_title_with_hash_and_comment(self):
        """Verify single-quote protection for '#' with trailing comment."""
        raw_yaml_line = "'Trading Issue # 104' # real comment"
        comment_stripped = strip_yaml_comment(raw_yaml_line)
        scalar = clean_scalar(comment_stripped)

        assert comment_stripped == "'Trading Issue # 104'"
        assert scalar == "Trading Issue # 104"

    def test_escaped_quotes_and_multiple_hashes(self):
        """Verify escaped quote handling and multiple '#' occurrences."""
        raw_val = '"Issue # 104: \\"Sub-Issue # 2\\"" # trailing # comment'
        comment_stripped = strip_yaml_comment(raw_val)
        scalar = clean_scalar(comment_stripped)

        assert scalar == 'Issue # 104: "Sub-Issue # 2"'

    def test_list_items_with_hashes_and_comments(self):
        """Verify list items containing '#' inside quotes with trailing inline comments."""
        full_doc = """---
title: List Item Test
tags:
  - "issue # 101" # primary issue
  - 'issue # 102' # secondary issue
  - plain_item # unquoted comment
created: 2026-11-05
updated: 2026-11-05
status: active
---
# List Item Test
"""
        fm, _ = parse_frontmatter(full_doc)
        assert fm is not None
        assert fm["tags"] == ["issue # 101", "issue # 102", "plain_item"]

    def test_unquoted_hash_comment_boundary(self):
        """
        Verify that an unquoted '#' preceded by whitespace is correctly treated
        as an inline comment start and stripped.
        """
        raw_val = "Trading Issue 104 # plain comment"
        comment_stripped = strip_yaml_comment(raw_val)
        scalar = clean_scalar(comment_stripped)

        assert scalar == "Trading Issue 104"
