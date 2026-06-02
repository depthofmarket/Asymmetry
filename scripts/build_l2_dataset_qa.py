#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_dataset_qa import build_l2_dataset_qa, write_l2_dataset_qa_artifacts  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build NQ L2 CSV archive source index and calendar QA artifacts. This scans zip "
            "metadata only; it does not run a backtest, replay orders, or mine signals."
        )
    )
    parser.add_argument(
        "--archive-root",
        default="data/raw/l2_nq/csv_archives",
        help="Root containing semester folders with L2 CSV zip archives.",
    )
    parser.add_argument(
        "--out-dir",
        default="data/raw/l2_nq/manifests",
        help="Directory where QA CSVs and report should be written.",
    )
    parser.add_argument("--start-date", default="20201201", help="Coverage start date, YYYYMMDD.")
    parser.add_argument("--end-date", default="20251130", help="Coverage end date, YYYYMMDD.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    qa = build_l2_dataset_qa(
        args.archive_root,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    paths = write_l2_dataset_qa_artifacts(qa, args.out_dir)
    source_gaps = [row for row in qa.missing_days if row.action == "review_source_gap"]
    duplicates = {row.trade_date for row in qa.source_index if row.duplicate_status == "duplicate"}
    unique_dates = {row.trade_date for row in qa.source_index}

    print(f"L2 source index:       {paths['source_index_csv']}")
    print(f"L2 missing days:       {paths['missing_days_csv']}")
    print(f"L2 month coverage:     {paths['month_coverage_csv']}")
    print(f"L2 archive errors:     {paths['archive_errors_csv']}")
    print(f"L2 QA report:          {paths['report_md']}")
    print(f"Unique source dates:   {len(unique_dates):,}")
    print(f"Missing calendar days: {len(qa.missing_days):,}")
    print(f"Source gaps to review: {len(source_gaps):,}")
    print(f"Duplicate dates:       {len(duplicates):,}")
    print(f"Archive read errors:   {len(qa.archive_errors):,}")
    if source_gaps:
        print("Review source gaps before treating the archive as fully clean.")
    if qa.archive_errors:
        print("Archive read errors found. Check l2_archive_errors.csv.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
