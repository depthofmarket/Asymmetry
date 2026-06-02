#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_parquet_audit import inspect_l2_parquet_dataset, write_l2_parquet_audit  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bounded first-look audit for NQ L2 parquet data. Reads parquet metadata and a capped "
            "sample only; it does not run a backtest or full-history signal scan."
        )
    )
    parser.add_argument("--source", required=True, help="Parquet file or directory containing parquet files.")
    parser.add_argument("--out-dir", default="results/research_master/l2_parquet_audit")
    parser.add_argument("--max-files", type=int, default=5, help="Maximum parquet files to inspect.")
    parser.add_argument("--sample-rows", type=int, default=2000, help="Maximum rows to sample per inspected file.")
    parser.add_argument("--tick-size", type=float, default=0.25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = inspect_l2_parquet_dataset(
        args.source,
        max_files=args.max_files,
        sample_rows=args.sample_rows,
        tick_size=float(args.tick_size),
    )
    paths = write_l2_parquet_audit(audit, args.out_dir)
    print(f"L2 parquet audit report:       {paths['report_md']}")
    print(f"L2 parquet file manifest:      {paths['manifest_csv']}")
    print(f"L2 parquet sample quality:     {paths['sample_quality_csv']}")
    print(f"L2 parquet schema summary:     {paths['schema_json']}")
    if audit.sample_quality.empty:
        print("No sample rows were read. Check --source and --max-files.")
    elif audit.sample_quality["warnings"].astype(str).str.len().gt(0).any():
        print("Sample warnings found. Review the report before using this data for execution audits.")
    else:
        print("No sample-level warnings found in inspected files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
