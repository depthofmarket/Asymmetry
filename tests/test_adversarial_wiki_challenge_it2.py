"""
tests/test_adversarial_wiki_challenge_it2.py
============================================
Adversarial Challenge Verification Suite (teamwork_challenger_wiki_it2_1).

Empirical stress tests for Karpathy LLM Wiki Iteration 2 fixes:
1. Staging Isolation Live Mock: Non-wiki staged files (mods, additions, deletions)
   MUST NEVER be swept into wiki commits by cmd_stop.
2. Zero Wiki Changes Staging Invariance: Non-wiki staged files remain intact and
   no commit is made when wiki has no changes.
3. External CWD Execution: sync_wiki.sh and wiki_sync.py invoked from /tmp and other
   arbitrary CWDs must resolve repo root cleanly without RuntimeError.
4. Git Porcelain Whitespace Parsing: Verify unstaged (" M "), staged ("M  "),
   untracked ("?? "), renames ("R  "), deletions ("D  ", " D "), and quoted paths
   never suffer from 'iki/' path truncation.
5. Wiki File Deletion Lifecycle: Deletion of wiki files is cleanly staged and committed.
6. Merge Conflict Guard: Unresolved git conflict markers are intercepted by cmd_start.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.wiki_sync import (
    check_conflict_markers,
    cmd_start,
    cmd_status,
    cmd_stop,
    get_repo_root,
    get_wiki_changes,
)


def _init_mock_repo(path: Path) -> None:
    """Initialize a full mock git repository with standard user config."""
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Challenger"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "challenger@test.local"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=str(path), check=True, capture_output=True)


class TestStagingIsolationEmpirical:
    """Adversarial stress-testing of Git commit staging isolation in wiki_sync.py."""

    def test_live_staging_isolation_with_heterogeneous_staged_files(self, tmp_path: Path):
        """
        Adversarial Test:
        Stage heterogeneous non-wiki modifications (modified code, new addition, deleted doc).
        Stage a wiki update.
        Execute cmd_stop() in live mode.
        Assert that HEAD commit contains STRICTLY wiki/ files and all non-wiki staged files
        remain in the git staging index untouched.
        """
        _init_mock_repo(tmp_path)

        # 1. Establish baseline repository structure
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)
        code_file = src_dir / "quant_engine.py"
        code_file.write_text("class QuantEngine:\n    pass\n", encoding="utf-8")

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True)
        old_doc = docs_dir / "deprecated_manual.md"
        old_doc.write_text("# Old Manual\n", encoding="utf-8")

        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir(parents=True)
        (wiki_dir / "index.md").write_text("# Knowledge Base\nInitial catalog.\n", encoding="utf-8")
        (wiki_dir / "log.md").write_text("## [2026-11-05 12:00:00 UTC] [init] [SETUP] | Init\n", encoding="utf-8")
        (wiki_dir / "hot.md").write_text("# Active State\nBaseline\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Baseline repository commit"], cwd=str(tmp_path), check=True, capture_output=True)

        baseline_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(tmp_path), check=True, capture_output=True, text=True
        ).stdout.strip()

        # 2. Stage multiple diverse non-wiki changes:
        # A) Modify existing code and stage it
        code_file.write_text("class QuantEngine:\n    ADVERSARIAL_PAYLOAD = True\n", encoding="utf-8")
        subprocess.run(["git", "add", str(code_file)], cwd=str(tmp_path), check=True, capture_output=True)

        # B) Create new non-wiki file and stage it
        new_test = tmp_path / "tests" / "test_adversarial_feature.py"
        new_test.parent.mkdir(parents=True, exist_ok=True)
        new_test.write_text("def test_adversarial(): assert True\n", encoding="utf-8")
        subprocess.run(["git", "add", str(new_test)], cwd=str(tmp_path), check=True, capture_output=True)

        # C) Delete a doc file and stage the deletion
        old_doc.unlink()
        subprocess.run(["git", "rm", "docs/deprecated_manual.md"], cwd=str(tmp_path), check=True, capture_output=True)

        # D) Leave an untracked file outside wiki/
        untracked_script = tmp_path / "scripts" / "untracked_helper.py"
        untracked_script.parent.mkdir(parents=True, exist_ok=True)
        untracked_script.write_text("# untracked script\n", encoding="utf-8")

        # Verify staging state before wiki operation
        pre_status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(tmp_path), check=True, capture_output=True, text=True
        ).stdout
        assert "M  src/quant_engine.py" in pre_status
        assert "A  tests/test_adversarial_feature.py" in pre_status
        assert "D  docs/deprecated_manual.md" in pre_status
        assert "?? scripts/" in pre_status or "?? scripts/untracked_helper.py" in pre_status

        # 3. Create changes in wiki/ (one modified, one new untracked)
        (wiki_dir / "index.md").write_text("# Knowledge Base\nUpdated with new strategy!\n", encoding="utf-8")
        (wiki_dir / "new_strategy.md").write_text("# New Strategy\nNotes.\n", encoding="utf-8")

        # 4. Execute cmd_stop (live, non-dry-run)
        ret = cmd_stop(repo_root=tmp_path, no_push=True)
        assert ret == 0, f"cmd_stop failed with exit code {ret}"

        # 5. Assertions on the new commit at HEAD
        new_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(tmp_path), check=True, capture_output=True, text=True
        ).stdout.strip()
        assert new_head != baseline_head, "No commit was created at HEAD!"

        # Inspect exact files committed in this new HEAD commit
        diff_tree = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip().splitlines()

        # CRITICAL ASSERTION: Every single file in the commit must start with 'wiki/'
        for committed_file in diff_tree:
            assert committed_file.startswith("wiki/"), (
                f"STAGING LEAK BUG! Non-wiki file swept into wiki commit: '{committed_file}'"
            )

        assert "wiki/index.md" in diff_tree
        assert "wiki/new_strategy.md" in diff_tree
        assert "src/quant_engine.py" not in diff_tree
        assert "tests/test_adversarial_feature.py" not in diff_tree
        assert "docs/deprecated_manual.md" not in diff_tree
        assert "scripts/untracked_helper.py" not in diff_tree

        # 6. CRITICAL ASSERTION: Staged non-wiki changes MUST remain staged in the Git index
        post_status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(tmp_path), check=True, capture_output=True, text=True
        ).stdout
        assert "M  src/quant_engine.py" in post_status, f"src/quant_engine.py lost from staging index: {post_status}"
        assert "A  tests/test_adversarial_feature.py" in post_status, f"tests/test_adversarial_feature.py lost: {post_status}"
        assert "D  docs/deprecated_manual.md" in post_status, f"docs/deprecated_manual.md lost: {post_status}"
        assert "?? scripts/" in post_status or "?? scripts/untracked_helper.py" in post_status
        # And wiki files must be 100% clean
        for line in post_status.splitlines():
            assert not line.endswith("wiki/index.md"), f"wiki/index.md should be committed: {line}"
            assert not line.endswith("wiki/new_strategy.md"), f"wiki/new_strategy.md should be committed: {line}"

    def test_staging_isolation_when_zero_wiki_changes(self, tmp_path: Path):
        """
        Adversarial Test:
        If developer has non-wiki files staged, but wiki/ has zero changes,
        cmd_stop must exit cleanly without committing anything.
        """
        _init_mock_repo(tmp_path)
        src_file = tmp_path / "foo.py"
        src_file.write_text("x = 1\n", encoding="utf-8")
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "index.md").write_text("# Wiki\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Baseline"], cwd=str(tmp_path), check=True, capture_output=True)

        head_before = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(tmp_path), check=True, capture_output=True, text=True
        ).stdout.strip()

        # Stage non-wiki change
        src_file.write_text("x = 2\n", encoding="utf-8")
        subprocess.run(["git", "add", "foo.py"], cwd=str(tmp_path), check=True, capture_output=True)

        # Zero changes in wiki/
        ret = cmd_stop(repo_root=tmp_path, no_push=True)
        assert ret == 0

        head_after = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(tmp_path), check=True, capture_output=True, text=True
        ).stdout.strip()
        assert head_after == head_before, "A commit was incorrectly made when no wiki changes were present!"

        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(tmp_path), check=True, capture_output=True, text=True
        ).stdout
        assert "M  foo.py" in status, "foo.py lost its staged status!"


class TestExternalCWDExecutionEmpirical:
    """Empirical verification of execution from external working directories."""

    def test_sync_wiki_sh_status_from_tmp(self):
        """Test invoking scripts/sync_wiki.sh status from /tmp."""
        script_sh = ROOT / "scripts" / "sync_wiki.sh"
        proc = subprocess.run(
            ["bash", str(script_sh), "status"],
            cwd="/tmp",
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"Failed: stderr={proc.stderr}"
        assert f"Repository Root : {ROOT}" in proc.stdout
        assert "[WIKI_SYNC] Knowledge Base Status" in proc.stdout

    def test_sync_wiki_sh_start_dry_run_from_tmp(self):
        """Test invoking scripts/sync_wiki.sh start --dry-run from /tmp."""
        script_sh = ROOT / "scripts" / "sync_wiki.sh"
        proc = subprocess.run(
            ["bash", str(script_sh), "start", "--dry-run"],
            cwd="/tmp",
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"Failed: stderr={proc.stderr}"
        assert "Session Start: Synchronizing Knowledge Base" in proc.stdout

    def test_sync_wiki_sh_stop_dry_run_from_tmp(self):
        """Test invoking scripts/sync_wiki.sh stop --dry-run from /tmp."""
        script_sh = ROOT / "scripts" / "sync_wiki.sh"
        proc = subprocess.run(
            ["bash", str(script_sh), "stop", "--dry-run"],
            cwd="/tmp",
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"Failed: stderr={proc.stderr}"
        assert "Session Stop: Committing Knowledge Base Updates" in proc.stdout

    def test_wiki_sync_py_direct_from_tmp_resolves_fallback(self):
        """Test invoking python scripts/wiki_sync.py status directly from /tmp without --repo-root."""
        script_py = ROOT / "scripts" / "wiki_sync.py"
        proc = subprocess.run(
            [sys.executable, str(script_py), "status"],
            cwd="/tmp",
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"Failed: stderr={proc.stderr}"
        assert f"Repository Root : {ROOT}" in proc.stdout


class TestPorcelainLeadingWhitespaceParsingEmpirical:
    """Stress-test porcelain v1 parsing across all possible status codes and white space combinations."""

    def test_all_porcelain_variants_in_live_git_repo(self, tmp_path: Path):
        """
        Adversarial Test:
        Construct a real git repository with all possible status combinations in wiki/:
        1. Unstaged modification (' M')
        2. Staged modification ('M ')
        3. Staged + unstaged modification ('MM')
        4. Staged addition ('A ')
        5. Staged addition + unstaged mod ('AM')
        6. Untracked ('??')
        7. Staged rename ('R ')
        8. Unstaged deletion (' D')
        9. Staged deletion ('D ')
        10. File with spaces in path ('wiki/spaced file.md')
        Verify get_wiki_changes cleanly parses every file with valid prefix and zero 'iki/' truncations.
        """
        _init_mock_repo(tmp_path)
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()

        # Files to be committed initially
        (wiki_dir / "unstaged_mod.md").write_text("# Unstaged Mod\n", encoding="utf-8")
        (wiki_dir / "staged_mod.md").write_text("# Staged Mod\n", encoding="utf-8")
        (wiki_dir / "both_mod.md").write_text("# Both Mod\n", encoding="utf-8")
        (wiki_dir / "old_rename.md").write_text("# Old Name\n", encoding="utf-8")
        (wiki_dir / "unstaged_del.md").write_text("# Unstaged Del\n", encoding="utf-8")
        (wiki_dir / "staged_del.md").write_text("# Staged Del\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Baseline files"], cwd=str(tmp_path), check=True, capture_output=True)

        # 1. Unstaged mod (" M")
        (wiki_dir / "unstaged_mod.md").write_text("# Unstaged Mod v2\n", encoding="utf-8")

        # 2. Staged mod ("M ")
        (wiki_dir / "staged_mod.md").write_text("# Staged Mod v2\n", encoding="utf-8")
        subprocess.run(["git", "add", "wiki/staged_mod.md"], cwd=str(tmp_path), check=True, capture_output=True)

        # 3. Both mod ("MM")
        (wiki_dir / "both_mod.md").write_text("# Both Mod staged\n", encoding="utf-8")
        subprocess.run(["git", "add", "wiki/both_mod.md"], cwd=str(tmp_path), check=True, capture_output=True)
        (wiki_dir / "both_mod.md").write_text("# Both Mod unstaged worktree\n", encoding="utf-8")

        # 4. Staged add ("A ")
        (wiki_dir / "staged_add.md").write_text("# Staged Add\n", encoding="utf-8")
        subprocess.run(["git", "add", "wiki/staged_add.md"], cwd=str(tmp_path), check=True, capture_output=True)

        # 5. Staged add + unstaged mod ("AM")
        (wiki_dir / "staged_add_mod.md").write_text("# Staged Add Mod v1\n", encoding="utf-8")
        subprocess.run(["git", "add", "wiki/staged_add_mod.md"], cwd=str(tmp_path), check=True, capture_output=True)
        (wiki_dir / "staged_add_mod.md").write_text("# Staged Add Mod v2\n", encoding="utf-8")

        # 6. Untracked ("??")
        (wiki_dir / "untracked.md").write_text("# Untracked\n", encoding="utf-8")

        # 7. Staged rename ("R ")
        subprocess.run(["git", "mv", "wiki/old_rename.md", "wiki/new_rename.md"], cwd=str(tmp_path), check=True, capture_output=True)

        # 8. Unstaged deletion (" D")
        (wiki_dir / "unstaged_del.md").unlink()

        # 9. Staged deletion ("D ")
        subprocess.run(["git", "rm", "wiki/staged_del.md"], cwd=str(tmp_path), check=True, capture_output=True)

        # 10. File with spaces
        (wiki_dir / "spaced file name.md").write_text("# Spaced\n", encoding="utf-8")

        changes = get_wiki_changes(tmp_path)
        assert len(changes) == 10, f"Expected exactly 10 changed files, got {len(changes)}: {changes}"

        parsed_paths = {path: status for status, path in changes}

        # Check for path truncation bugs
        for p in parsed_paths:
            assert not p.startswith("iki/"), f"Path truncation bug on '{p}'"
            assert p.startswith("wiki/"), f"Path must start with 'wiki/': '{p}'"

        # Verify key expected files
        assert "wiki/unstaged_mod.md" in parsed_paths
        assert parsed_paths["wiki/unstaged_mod.md"] == "M"

        assert "wiki/staged_mod.md" in parsed_paths
        assert parsed_paths["wiki/staged_mod.md"] == "M"

        assert "wiki/both_mod.md" in parsed_paths
        assert parsed_paths["wiki/both_mod.md"] == "MM"

        assert "wiki/staged_add.md" in parsed_paths
        assert parsed_paths["wiki/staged_add.md"] == "A"

        assert "wiki/staged_add_mod.md" in parsed_paths
        assert parsed_paths["wiki/staged_add_mod.md"] == "AM"

        assert "wiki/untracked.md" in parsed_paths
        assert parsed_paths["wiki/untracked.md"] == "??"

        assert "wiki/new_rename.md" in parsed_paths
        assert parsed_paths["wiki/new_rename.md"] == "R"

        assert "wiki/unstaged_del.md" in parsed_paths
        assert parsed_paths["wiki/unstaged_del.md"] == "D"

        assert "wiki/staged_del.md" in parsed_paths
        assert parsed_paths["wiki/staged_del.md"] == "D"

        assert "wiki/spaced file name.md" in parsed_paths
        assert parsed_paths["wiki/spaced file name.md"] == "??"


class TestWikiLifecycleEdgeCases:
    """Additional adversarial edge-case verifications."""

    def test_conflict_marker_detection_prevents_start(self, tmp_path: Path):
        """Verify that cmd_start aborts when git conflict markers are present in wiki/."""
        _init_mock_repo(tmp_path)
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        conflicted_file = wiki_dir / "index.md"
        conflicted_file.write_text(
            "# Catalog\n<<<<<<< HEAD\nLocal version\n=======\nRemote version\n>>>>>>> branch\n",
            encoding="utf-8",
        )

        conflicts = check_conflict_markers(wiki_dir)
        assert len(conflicts) == 1
        assert conflicts[0] == conflicted_file

        ret = cmd_start(repo_root=tmp_path, dry_run=False)
        assert ret == 1, "cmd_start should fail when conflict markers are present!"

    def test_wiki_deletion_staged_and_committed(self, tmp_path: Path):
        """Verify cmd_stop correctly handles deleted wiki files."""
        _init_mock_repo(tmp_path)
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        f1 = wiki_dir / "keep.md"
        f1.write_text("# Keep\n", encoding="utf-8")
        f2 = wiki_dir / "remove.md"
        f2.write_text("# Remove\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=str(tmp_path), check=True, capture_output=True)

        # Delete remove.md from filesystem
        f2.unlink()

        ret = cmd_stop(repo_root=tmp_path, no_push=True)
        assert ret == 0

        diff_tree = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip().splitlines()
        assert "wiki/remove.md" in diff_tree

    def test_cmd_stop_aborts_gracefully_when_pre_commit_hook_fails(self, tmp_path: Path):
        """
        Verify that if pre-commit hook rejects a commit (e.g. failing validation),
        cmd_stop returns exit code 1 and outputs error message rather than crashing or hanging.
        """
        _init_mock_repo(tmp_path)
        wiki_dir = tmp_path / "wiki"
        wiki_dir.mkdir()
        (wiki_dir / "page.md").write_text("# Clean page\n", encoding="utf-8")

        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial"], cwd=str(tmp_path), check=True, capture_output=True)

        # Install an adversarial pre-commit hook that deliberately fails
        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        failing_hook = hooks_dir / "pre-commit"
        failing_hook.write_text("#!/bin/sh\necho 'REJECTED BY ADVERSARIAL HOOK' >&2\nexit 1\n", encoding="utf-8")
        failing_hook.chmod(0o755)

        # Modify wiki file
        (wiki_dir / "page.md").write_text("# Modified page\n", encoding="utf-8")

        ret = cmd_stop(repo_root=tmp_path, no_push=True)
        assert ret == 1, "cmd_stop should have returned 1 when pre-commit hook aborted the commit!"
