#!/usr/bin/env python3
"""
wiki_sync.py — Git Synchronization & Automation Tool for Karpathy LLM Wiki.

Supports:
  - start: Pull/rebase remote wiki updates with offline safety and conflict guards.
  - stop: Detect changes in wiki/, generate structured commit message, auto-commit, and optional push.
  - status: Check wiki directory status, git status, and recent journal log entries.

Usage:
  python scripts/wiki_sync.py start [--timeout SECONDS] [--dry-run]
  python scripts/wiki_sync.py stop [--no-push] [--timeout SECONDS] [--dry-run]
  python scripts/wiki_sync.py status
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple


def run_git(args: List[str], cwd: Path, timeout: Optional[int] = None) -> Tuple[int, str, str]:
    """Execute a git command with timeout and return (code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.rstrip("\r\n"), proc.stderr.rstrip("\r\n")
    except subprocess.TimeoutExpired:
        return 124, "", f"Git command timed out after {timeout} seconds"
    except Exception as e:
        return 1, "", str(e)


def get_repo_root(cwd: Optional[Path] = None) -> Path:
    """Find repository root directory."""
    start_dir = cwd or Path.cwd()
    code, stdout, _ = run_git(["rev-parse", "--show-toplevel"], cwd=start_dir)
    if code == 0 and stdout:
        return Path(stdout.strip())
    # Fallback to repo root containing this script
    script_repo = Path(__file__).resolve().parents[1]
    code, stdout, _ = run_git(["rev-parse", "--show-toplevel"], cwd=script_repo)
    if code == 0 and stdout:
        return Path(stdout.strip())
    raise RuntimeError("Not inside a git repository.")


def get_current_branch(repo_root: Path) -> str:
    """Get active git branch name."""
    code, stdout, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
    return stdout if code == 0 and stdout else "main"


def get_remote_name(repo_root: Path) -> Optional[str]:
    """Return primary remote name if configured, otherwise None."""
    code, stdout, _ = run_git(["remote"], cwd=repo_root)
    if code != 0 or not stdout:
        return None
    remotes = stdout.splitlines()
    if "origin" in remotes:
        return "origin"
    return remotes[0] if remotes else None


def is_remote_reachable(repo_root: Path, remote: str, timeout: int = 3) -> bool:
    """Probe if remote repository is reachable within timeout."""
    code, _, _ = run_git(["ls-remote", "--exit-code", remote, "HEAD"], cwd=repo_root, timeout=timeout)
    return code == 0


def check_conflict_markers(wiki_dir: Path) -> List[Path]:
    """Check for git merge conflict markers in wiki markdown files."""
    conflicts = []
    if not wiki_dir.exists():
        return conflicts
    marker_pattern = re.compile(r"^(<{7}|={7}|>{7})(?:\s.*)?$", re.MULTILINE)
    for md_file in wiki_dir.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            if marker_pattern.search(content):
                conflicts.append(md_file)
        except Exception:
            pass
    return conflicts


def get_wiki_changes(repo_root: Path) -> List[Tuple[str, str]]:
    """Return list of (status_code, file_path) for files changed in wiki/."""
    code, stdout, _ = run_git(["status", "--porcelain", "--", "wiki/"], cwd=repo_root)
    if code != 0 or not stdout:
        return []
    changes = []
    for line in stdout.splitlines():
        line = line.rstrip("\r\n")
        if len(line) < 3:
            continue
        # In git status --porcelain v1:
        # If leading space preserved: line[:2] is status, line[3:] is path
        # If leading space was stripped: line[0] is status, line[2:] is path
        if line[1] == " ":
            status = line[0].strip()
            filepath = line[2:].strip()
        else:
            status = line[:2].strip()
            filepath = line[3:].strip()

        if " -> " in filepath:
            filepath = filepath.split(" -> ")[-1].strip()
        filepath = filepath.strip("\"'")
        changes.append((status, filepath))
    return changes


def get_latest_journal_entry(log_file: Path) -> str:
    """Extract latest journal entry header and summary from wiki/log.md."""
    if not log_file.exists():
        return "No prior log entries found."
    try:
        content = log_file.read_text(encoding="utf-8")
        headers = [m.group(0) for m in re.finditer(r"^##\s+\[.*?\]\s+.*$", content, re.MULTILINE)]
        if headers:
            return headers[-1]
    except Exception:
        pass
    return "Recent wiki updates recorded."


def cmd_start(repo_root: Path, timeout: int = 3, dry_run: bool = False) -> int:
    """Session start: verify repo, probe remote, pull updates, ensure clean state."""
    print("=" * 68)
    print(" [WIKI_SYNC] Session Start: Synchronizing Knowledge Base")
    print("=" * 68)

    wiki_dir = repo_root / "wiki"
    if not dry_run:
        wiki_dir.mkdir(parents=True, exist_ok=True)

    remote = get_remote_name(repo_root)
    branch = get_current_branch(repo_root)

    if not remote:
        print("[WIKI_SYNC] INFO: No git remote configured. Operating in local-only mode.")
    else:
        print(f"[WIKI_SYNC] Checking remote '{remote}' reachability (timeout: {timeout}s)...")
        if is_remote_reachable(repo_root, remote, timeout=timeout):
            print(f"[WIKI_SYNC] Remote reachable. Pulling latest updates on branch '{branch}'...")
            if dry_run:
                print(f"[DRY_RUN] Would execute: git pull --rebase --autostash {remote} {branch}")
            else:
                code, stdout, stderr = run_git(["pull", "--rebase", "--autostash", remote, branch], cwd=repo_root)
                if code == 0:
                    print(f"[WIKI_SYNC] SUCCESS: Knowledge base up to date with {remote}/{branch}.")
                else:
                    print(f"[WIKI_SYNC] WARNING: Pull/rebase returned non-zero code {code}.")
                    print(f"[WIKI_SYNC] Details: {stderr or stdout}")
                    print("[WIKI_SYNC] Aborting rebase to preserve pristine local state...")
                    run_git(["rebase", "--abort"], cwd=repo_root)
        else:
            print(f"[WIKI_SYNC] WARNING: Remote '{remote}' unreachable or offline. Proceeding with local wiki state.")

    conflicts = check_conflict_markers(wiki_dir)
    if conflicts:
        print("[WIKI_SYNC] ERROR: Unresolved git conflict markers detected in wiki files:")
        for cf in conflicts:
            print(f"  - {cf.relative_to(repo_root)}")
        print("[WIKI_SYNC] Resolve conflict markers before editing wiki.")
        return 1

    print("[WIKI_SYNC] Ready: Wiki workspace verified clean.")
    return 0


def cmd_stop(repo_root: Path, timeout: int = 3, no_push: bool = False, dry_run: bool = False) -> int:
    """Session stop: detect wiki changes, auto-commit wiki/ only, and optionally push."""
    print("=" * 68)
    print(" [WIKI_SYNC] Session Stop: Committing Knowledge Base Updates")
    print("=" * 68)

    changes = get_wiki_changes(repo_root)
    if not changes:
        print("[WIKI_SYNC] No changes detected in wiki/. Nothing to commit.")
        return 0

    print(f"[WIKI_SYNC] Detected {len(changes)} modified/untracked file(s) in wiki/:")
    for status, path in changes:
        print(f"  [{status or 'M'}] {path}")

    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = f"wiki: update knowledge base [{now_utc}]"

    log_file = repo_root / "wiki" / "log.md"
    latest_journal = get_latest_journal_entry(log_file)

    body_lines = [
        "Automated session commit of wiki knowledge base updates.",
        "",
        "Modified wiki files:",
    ]
    for status, path in changes:
        body_lines.append(f"- {path}")
    body_lines.extend([
        "",
        f"Latest Journal Header: {latest_journal}",
    ])
    body = "\n".join(body_lines)

    if dry_run:
        print("\n[DRY_RUN] Would execute:")
        print("  git add wiki/")
        print(f'  git commit -m "{subject}" -m "..." -- wiki/')
        if not no_push:
            remote = get_remote_name(repo_root)
            branch = get_current_branch(repo_root)
            print(f"  git push {remote or 'origin'} {branch}")
        return 0

    # Stage ONLY wiki directory
    code, _, stderr = run_git(["add", "wiki/"], cwd=repo_root)
    if code != 0:
        print(f"[WIKI_SYNC] ERROR staging wiki/ files: {stderr}")
        return 1

    code, stdout, stderr = run_git(["commit", "-m", subject, "-m", body, "--", "wiki/"], cwd=repo_root)
    if code != 0:
        print(f"[WIKI_SYNC] ERROR committing wiki/ changes: {stderr or stdout}")
        return 1

    print(f"[WIKI_SYNC] SUCCESS: Committed wiki updates: {subject}")

    if no_push:
        print("[WIKI_SYNC] Remote push skipped (--no-push flag set).")
        return 0

    remote = get_remote_name(repo_root)
    branch = get_current_branch(repo_root)
    if not remote:
        print("[WIKI_SYNC] Remote push skipped (no remote configured).")
        return 0

    print(f"[WIKI_SYNC] Probing remote '{remote}' for push...")
    if is_remote_reachable(repo_root, remote, timeout=timeout):
        code, stdout, stderr = run_git(["push", remote, branch], cwd=repo_root)
        if code == 0:
            print(f"[WIKI_SYNC] SUCCESS: Pushed wiki updates to {remote}/{branch}.")
        else:
            print(f"[WIKI_SYNC] WARNING: Remote push failed: {stderr or stdout}")
            print("[WIKI_SYNC] Local commit is safely preserved.")
    else:
        print(f"[WIKI_SYNC] WARNING: Remote unreachable. Local commit safely preserved.")

    return 0


def cmd_status(repo_root: Path) -> int:
    """Display wiki status, changed files, and last log entries."""
    print("=" * 68)
    print(" [WIKI_SYNC] Knowledge Base Status")
    print("=" * 68)
    print(f"Repository Root : {repo_root}")
    print(f"Current Branch  : {get_current_branch(repo_root)}")
    remote = get_remote_name(repo_root)
    print(f"Remote Name     : {remote or 'None (local-only)'}")

    wiki_dir = repo_root / "wiki"
    print(f"Wiki Directory  : {'EXISTS' if wiki_dir.is_dir() else 'MISSING'}")

    core_files = ["index.md", "log.md", "hot.md", "SCHEMA.md", "failed_ideas.md"]
    for fname in core_files:
        fpath = wiki_dir / fname
        status_str = "EXISTS" if fpath.is_file() else "MISSING"
        size_str = f"({fpath.stat().st_size} bytes)" if fpath.is_file() else ""
        print(f"  - {fname:<15}: {status_str} {size_str}")

    changes = get_wiki_changes(repo_root)
    print(f"\nUncommitted Wiki Changes: {len(changes)}")
    for status, path in changes:
        print(f"  [{status or 'M'}] {path}")

    log_file = wiki_dir / "log.md"
    print("\nRecent Journal Entries (wiki/log.md):")
    if log_file.exists():
        content = log_file.read_text(encoding="utf-8")
        headers = [m.group(0) for m in re.finditer(r"^##\s+\[.*?\]\s+.*$", content, re.MULTILINE)]
        if headers:
            for h in headers[-3:]:
                print(f"  {h}")
        else:
            print("  (No headers found in log.md)")
    else:
        print("  (wiki/log.md does not exist)")

    print("=" * 68)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Git synchronization tool for Karpathy LLM Wiki.")
    subparsers = parser.add_subparsers(dest="command", help="Sync command to execute")

    start_p = subparsers.add_parser("start", help="Session start: pull updates and check clean state")
    start_p.add_argument("--timeout", type=int, default=3, help="Remote reachability probe timeout in seconds")
    start_p.add_argument("--dry-run", action="store_true", help="Simulate actions without executing git changes")

    stop_p = subparsers.add_parser("stop", help="Session stop: auto-commit wiki/ changes and optional push")
    stop_p.add_argument("--timeout", type=int, default=3, help="Remote reachability probe timeout in seconds")
    stop_p.add_argument("--no-push", action="store_true", help="Do not push commit to remote")
    stop_p.add_argument("--dry-run", action="store_true", help="Simulate commit and push without executing")

    subparsers.add_parser("status", help="Show current wiki status and recent log entries")

    parser.add_argument("--dry-run", action="store_true", help="Simulate actions")
    parser.add_argument("--repo-root", type=str, default=None, help="Explicit repository root")

    args = parser.parse_args()
    repo_root = Path(args.repo_root) if args.repo_root else get_repo_root()

    if args.command == "start":
        return cmd_start(repo_root, timeout=args.timeout, dry_run=args.dry_run)
    elif args.command == "stop":
        return cmd_stop(repo_root, timeout=args.timeout, no_push=args.no_push, dry_run=args.dry_run)
    elif args.command == "status":
        return cmd_status(repo_root)
    else:
        return cmd_status(repo_root)


if __name__ == "__main__":
    sys.exit(main())
