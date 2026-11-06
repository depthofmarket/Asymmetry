#!/usr/bin/env python3
"""
One-shot L2 parquet data ingestion coordinator.

Orchestrates: folder creation → archive discovery → organization → audit.
Minimal input: just specify where your L2 data lives.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_command(cmd: list[str], check: bool = True, timeout: int = 600, **kwargs) -> int:
    """Run a CLI command and return exit code."""
    print(f"\n{'='*80}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*80}")
    kwargs.setdefault("timeout", timeout)
    result = subprocess.run(cmd, check=False, **kwargs)
    if check and result.returncode != 0:
        print(f"Error: Command failed with exit code {result.returncode}")
        return result.returncode
    return result.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot L2 parquet ingestion: organize archives, create folders, and audit schema. "
            "Specify your download directory (where Google Drive/email archives live) and this "
            "script handles the rest in stages."
        )
    )
    parser.add_argument(
        "--download-dir",
        default="~/Downloads",
        help="Directory containing downloaded L2 zip files (default: ~/Downloads).",
    )
    parser.add_argument(
        "--archive-root",
        default="data/raw/l2_nq/zip_archives",
        help="Destination root for organized semester folders.",
    )
    parser.add_argument(
        "--manifest",
        default="data/raw/l2_nq/manifests/l2_zip_archive_inventory.csv",
        help="Manifest CSV path to write after archive inspection.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2021,
        help="First year for folder skeleton (default: 2021).",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2026,
        help="Last year for folder skeleton (default: 2026).",
    )
    parser.add_argument(
        "--no-move",
        action="store_true",
        help="Skip archive movement (dry-run only). Default: move after inspection.",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Skip parquet audit. Default: run full audit.",
    )
    parser.add_argument(
        "--audit-files",
        type=int,
        default=10,
        help="Number of parquet files to sample in audit (default: 10).",
    )
    parser.add_argument(
        "--audit-rows",
        type=int,
        default=2000,
        help="Rows per file to sample in audit (default: 2000).",
    )
    parser.add_argument(
        "--audit-out-dir",
        default="results/research_master/l2_parquet_audit",
        help="Output directory for audit reports.",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable to use (default: current interpreter).",
    )
    return parser.parse_args()


def stage_1_create_folders(args: argparse.Namespace) -> int:
    """Stage 1: Create semester folder skeleton."""
    print("\n" + "="*80)
    print("STAGE 1: CREATE SEMESTER FOLDER STRUCTURE")
    print("="*80)
    
    cmd = [
        str(args.python),
        str(REPO_ROOT / "scripts" / "manage_l2_download_archives.py"),
        "--download-dir", str(Path(args.download_dir).expanduser()),
        "--archive-root", str(args.archive_root),
        "--start-year", str(args.start_year),
        "--end-year", str(args.end_year),
        "--init-folders",
    ]
    return run_command(cmd)


def stage_2_discover_archives(args: argparse.Namespace) -> int:
    """Stage 2: Discover and inspect archives (dry-run)."""
    print("\n" + "="*80)
    print("STAGE 2: DISCOVER & INSPECT ARCHIVES (DRY RUN)")
    print("="*80)
    
    cmd = [
        str(args.python),
        str(REPO_ROOT / "scripts" / "manage_l2_download_archives.py"),
        "--download-dir", str(Path(args.download_dir).expanduser()),
        "--archive-root", str(args.archive_root),
        "--manifest", str(args.manifest),
    ]
    return run_command(cmd)


def stage_3_move_archives(args: argparse.Namespace) -> int:
    """Stage 3: Move archives to semester folders."""
    print("\n" + "="*80)
    print("STAGE 3: MOVE ARCHIVES INTO SEMESTER FOLDERS")
    print("="*80)
    
    if args.no_move:
        print("Skipped (--no-move)")
        return 0
    
    cmd = [
        str(args.python),
        str(REPO_ROOT / "scripts" / "manage_l2_download_archives.py"),
        "--download-dir", str(Path(args.download_dir).expanduser()),
        "--archive-root", str(args.archive_root),
        "--manifest", str(args.manifest),
        "--move",
    ]
    return run_command(cmd)


def stage_4_audit_schema(args: argparse.Namespace) -> int:
    """Stage 4: Audit parquet schema and quality."""
    print("\n" + "="*80)
    print("STAGE 4: AUDIT PARQUET SCHEMA & QUALITY")
    print("="*80)
    
    if args.no_audit:
        print("Skipped (--no-audit)")
        return 0
    
    cmd = [
        str(args.python),
        str(REPO_ROOT / "scripts" / "inspect_l2_parquet_dataset.py"),
        "--source", str(args.archive_root),
        "--out-dir", str(args.audit_out_dir),
        "--max-files", str(args.audit_files),
        "--sample-rows", str(args.audit_rows),
        "--tick-size", "0.25",
    ]
    return run_command(cmd)


def main() -> int:
    """Run all stages."""
    args = parse_args()
    
    print("\n" + "#"*80)
    print("# L2 PARQUET INGESTION COORDINATOR")
    print("#"*80)
    print(f"Download dir:     {Path(args.download_dir).expanduser()}")
    print(f"Archive root:     {args.archive_root}")
    print(f"Manifest:         {args.manifest}")
    print(f"Year range:       {args.start_year}-{args.end_year}")
    print(f"Skip move:        {args.no_move}")
    print(f"Skip audit:       {args.no_audit}")
    print("#"*80)
    
    # Stage 1: Create folders
    if stage_1_create_folders(args) != 0:
        print("Stage 1 failed; aborting.")
        return 1
    
    # Stage 2: Inspect (dry-run)
    if stage_2_discover_archives(args) != 0:
        print("Stage 2 failed; aborting.")
        return 1
    
    # Prompt user before moving
    if not args.no_move:
        response = input("\nReady to move archives? (yes/no): ").strip().lower()
        if response != "yes":
            print("Aborted: archives not moved.")
            return 0
    
    # Stage 3: Move archives
    if stage_3_move_archives(args) != 0:
        print("Stage 3 failed; aborting.")
        return 1
    
    # Stage 4: Audit
    if stage_4_audit_schema(args) != 0:
        print("Stage 4 completed with warnings (see report).")
        # Don't fail; audit warnings are informational
    
    print("\n" + "#"*80)
    print("# L2 INGESTION COMPLETE")
    print("#"*80)
    print(f"Archives organized in:     {args.archive_root}")
    print(f"Manifest written:          {args.manifest}")
    if not args.no_audit:
        print(f"Audit reports in:          {args.audit_out_dir}")
        print("  → Review l2_parquet_audit_report.md for warnings")
    print("#"*80)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
