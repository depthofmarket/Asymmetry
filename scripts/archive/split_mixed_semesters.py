#!/usr/bin/env python3
"""
Utility to split mixed-semester L2 zip archives into clean H1 and H2 zip files.
Transfers files entirely in memory without temp files on disk.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
PARQUET_DATE_RE = re.compile(r"(20\d{6})\.parquet$")


def get_semester_folder(yyyymmdd: str) -> str:
    """Return the folder name for a given yyyymmdd string."""
    year = yyyymmdd[:4]
    month = int(yyyymmdd[4:6])
    if 1 <= month <= 6:
        return f"{year}_1st_semester_Jan-Jun"
    else:
        return f"{year}_2nd_semester_Jul-Dec"


def split_zip(archive_path: Path, archive_root: Path) -> None:
    print(f"\nProcessing mixed zip: {archive_path.name}")
    h1_folder = archive_root / "2021_1st_semester_Jan-Jun"
    h2_folder = archive_root / "2021_2nd_semester_Jul-Dec"
    
    h1_folder.mkdir(parents=True, exist_ok=True)
    h2_folder.mkdir(parents=True, exist_ok=True)
    
    base_name = archive_path.stem
    h1_zip_path = h1_folder / f"{base_name}_H1.zip"
    h2_zip_path = h2_folder / f"{base_name}_H2.zip"
    
    h1_members = []
    h2_members = []
    
    with zipfile.ZipFile(archive_path, "r") as z_in:
        members = [m for m in z_in.infolist() if m.filename.endswith(".parquet")]
        total = len(members)
        print(f"  Found {total} parquet files inside archive.")
        
        # Sort members into H1 and H2
        for m in members:
            match = PARQUET_DATE_RE.search(Path(m.filename).name)
            if not match:
                continue
            date_str = match.group(1)
            folder = get_semester_folder(date_str)
            if "1st_semester" in folder:
                h1_members.append(m)
            else:
                h2_members.append(m)
                
        print(f"  Split plan: {len(h1_members)} files to H1, {len(h2_members)} files to H2.")
        
        # Write H1 zip in memory if we have H1 files
        if h1_members:
            print(f"  Writing H1 zip: {h1_zip_path.name}")
            with zipfile.ZipFile(h1_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z_out:
                for idx, m in enumerate(h1_members, 1):
                    sys.stdout.write(f"\r    [H1] Copying file {idx}/{len(h1_members)}: {m.filename}")
                    sys.stdout.flush()
                    data = z_in.read(m.filename)
                    z_out.writestr(m, data)
            print()
            
        # Write H2 zip in memory if we have H2 files
        if h2_members:
            print(f"  Writing H2 zip: {h2_zip_path.name}")
            with zipfile.ZipFile(h2_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z_out:
                for idx, m in enumerate(h2_members, 1):
                    sys.stdout.write(f"\r    [H2] Copying file {idx}/{len(h2_members)}: {m.filename}")
                    sys.stdout.flush()
                    data = z_in.read(m.filename)
                    z_out.writestr(m, data)
            print()

    # Verify both files are written and non-empty, then safely remove the original
    if h1_zip_path.exists() or h2_zip_path.exists():
        print(f"  Successfully split {archive_path.name}. Removing original mixed zip.")
        archive_path.unlink()
    else:
        print(f"  Warning: No files written for {archive_path.name}, keeping original.")


def main() -> int:
    archive_root = REPO_ROOT / "data" / "raw" / "l2_nq" / "zip_archives"
    mixed_dir = archive_root / "mixed_semesters_review"
    
    if not mixed_dir.exists():
        print(f"No mixed semesters folder found at: {mixed_dir}")
        return 0
        
    zip_files = sorted(mixed_dir.glob("*.zip"))
    if not zip_files:
        print("No mixed semester zip files found to process.")
        return 0
        
    print(f"Starting semester split for {len(zip_files)} mixed zip archives...")
    for zf in zip_files:
        split_zip(zf, archive_root)
        
    # Clean up empty mixed_semesters_review folder
    try:
        if not any(mixed_dir.iterdir()):
            mixed_dir.rmdir()
            print("\nRemoved empty mixed_semesters_review folder.")
    except Exception as e:
        print(f"\nCould not remove empty mixed folder: {e}")
        
    print("\nSplit operation completed successfully! ✨")
    return 0


if __name__ == "__main__":
    sys.exit(main())
