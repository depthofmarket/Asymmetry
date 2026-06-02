#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_archive_inventory import (  # noqa: E402
    create_semester_folder_skeleton,
    discover_zip_archives,
    inspect_l2_zip_archives,
    write_l2_zip_inventory_csv,
)


DEFAULT_PATTERNS = (
    "drive-download-*.zip",
    "20*.zip",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Organize Google Drive NQ L2 parquet zip chunks into semester folders by inspecting "
            "the dated parquet members inside each zip. Default mode is a dry run; pass --move "
            "to move archives."
        )
    )
    parser.add_argument("--download-dir", default="~/Downloads", help="Directory containing downloaded zip files.")
    parser.add_argument(
        "--archive-root",
        default="data/raw/l2_nq/zip_archives",
        help="Destination root for semester archive folders.",
    )
    parser.add_argument(
        "--manifest",
        default="data/raw/l2_nq/manifests/l2_zip_archive_inventory.csv",
        help="CSV manifest path to write after inspection.",
    )
    parser.add_argument(
        "--pattern",
        action="append",
        default=[],
        help="Zip glob under --download-dir. Can be repeated. Defaults target Google Drive chunks and yyyy zip names.",
    )
    parser.add_argument("--start-year", type=int, default=2020, help="First year for folder skeleton creation.")
    parser.add_argument("--end-year", type=int, default=2025, help="Last year for folder skeleton creation.")
    parser.add_argument("--init-folders", action="store_true", help="Create semester folder skeleton and exit.")
    parser.add_argument("--move", action="store_true", help="Move each inspected zip into its assigned semester folder.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    download_dir = Path(args.download_dir).expanduser()
    archive_root = Path(args.archive_root)
    patterns = tuple(args.pattern) if args.pattern else DEFAULT_PATTERNS

    if args.init_folders:
        folders = create_semester_folder_skeleton(
            archive_root,
            start_year=int(args.start_year),
            end_year=int(args.end_year),
        )
        print(f"Created/verified {len(folders)} folders under {archive_root}")
        for folder in folders:
            print(folder)
        return 0

    archives = discover_zip_archives(download_dir, patterns)
    inventories = inspect_l2_zip_archives(archives)
    manifest_path = write_l2_zip_inventory_csv(inventories, args.manifest)

    print(f"Download dir: {download_dir}")
    print(f"Archive root: {archive_root}")
    print(f"Zip archives inspected: {len(inventories)}")
    print(f"Manifest: {manifest_path}")
    print()

    for item in inventories:
        size_gb = item.zip_size_bytes / 1_000_000_000
        range_text = f"{item.first_date}-{item.last_date}" if item.first_date else "no_dates"
        destination = archive_root / item.assigned_folder / item.archive_name
        action = "MOVE" if args.move else "DRY_RUN"
        print(
            f"{action}\t{item.archive_name}\t{range_text}\t"
            f"parquet={item.parquet_file_count}\t{size_gb:.2f}GB\t-> {destination}"
        )
        if item.status != "ok":
            print(f"  warning: status={item.status} error={item.error}")
        if item.assigned_folder.endswith("_review"):
            print("  warning: archive needs manual review before trusting semester placement")
        if item.duplicate_parquet_file_count:
            print(f"  warning: duplicate parquet names inside zip={item.duplicate_parquet_file_count}")
        if args.move:
            _move_archive(Path(item.archive_path), destination)

    if not inventories:
        print("No zip archives matched the selected patterns.")
    elif not args.move:
        print()
        print("Dry run only. Re-run with --move after reviewing the plan.")
    return 0


def _move_archive(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.stat().st_size == source.stat().st_size:
            print("  skipped: destination already exists with same size")
            return
        raise FileExistsError(f"Destination exists with a different size: {destination}")
    shutil.move(str(source), str(destination))


if __name__ == "__main__":
    raise SystemExit(main())
