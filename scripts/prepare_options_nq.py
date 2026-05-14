#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.options_ingestion import (
    build_definition_sample,
    build_schema_sample,
    discover_options_raw_files,
    ensure_options_dirs,
    file_manifest,
    write_options_manifest,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare / inspect raw Databento NQ options data.")
    parser.add_argument("--base-dir", default="data")
    parser.add_argument("--definition-source", help="Specific definition ZIP/CSV/dir. Defaults to first discovered file.")
    parser.add_argument("--statistics-source", help="Specific statistics ZIP/CSV/dir. Defaults to first discovered file.")
    parser.add_argument("--trades-source", help="Specific trades ZIP/CSV/dir. Defaults to first discovered file.")
    parser.add_argument("--max-definition-files", type=int, default=5)
    parser.add_argument("--rows-per-file", type=int, default=1000)
    parser.add_argument("--sample-trades", action="store_true", help="Write a small trades_sample.csv if raw trades data exists.")
    parser.add_argument("--sample-statistics", action="store_true", help="Write a small statistics_sample.csv if raw statistics data exists.")
    parser.add_argument("--manifest-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dirs = ensure_options_dirs(args.base_dir)
    raw_base = dirs["raw_base"]
    processed_base = dirs["processed_base"]

    manifest_path = write_options_manifest(raw_base, processed_base / "manifest.csv")
    manifest = file_manifest(discover_options_raw_files(raw_base))
    print(f"Manifest: {manifest_path}")
    if not manifest.empty:
        print(manifest[["schema", "path", "size_mb"]].to_string(index=False))

    if args.manifest_only:
        return 0

    definition_source = Path(args.definition_source) if args.definition_source else None
    if definition_source is None:
        raw_files = discover_options_raw_files(raw_base)
        definition_source = raw_files.definition[0] if raw_files.definition else None
    if definition_source is None:
        print("No definition source found yet.")
    else:
        sample = build_definition_sample(
            definition_source,
            max_files=args.max_definition_files,
            rows_per_file=args.rows_per_file,
        )
        sample_path = processed_base / "definition_sample.csv"
        sample.to_csv(sample_path, index=False)
        print(f"Definition sample: {sample_path} ({len(sample):,} rows)")

    raw_files = discover_options_raw_files(raw_base)
    trades_source = Path(args.trades_source) if args.trades_source else (raw_files.trades[0] if raw_files.trades else None)
    if args.sample_trades and trades_source is not None:
        sample = build_schema_sample(
            trades_source,
            "trades",
            max_files=args.max_definition_files,
            rows_per_file=args.rows_per_file,
        )
        sample_path = processed_base / "trades_sample.csv"
        sample.to_csv(sample_path, index=False)
        print(f"Trades sample: {sample_path} ({len(sample):,} rows)")

    statistics_source = Path(args.statistics_source) if args.statistics_source else (
        raw_files.statistics[0] if raw_files.statistics else None
    )
    if args.sample_statistics and statistics_source is not None:
        sample = build_schema_sample(
            statistics_source,
            "statistics",
            max_files=args.max_definition_files,
            rows_per_file=args.rows_per_file,
        )
        sample_path = processed_base / "statistics_sample.csv"
        sample.to_csv(sample_path, index=False)
        print(f"Statistics sample: {sample_path} ({len(sample):,} rows)")
    elif args.sample_statistics:
        print("No statistics source found yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
