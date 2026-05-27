#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.aggressive_flow import (  # noqa: E402
    build_aggressive_flow_stats_from_source,
    merge_aggressive_flow_daily_stats,
    merge_aggressive_flow_minute_stats,
)
from backtest.tbbo_execution import NQ_OUTRIGHT_SYMBOL_PATTERN  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build NQ futures realized aggressive-flow stats from Databento trades archives."
    )
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="Databento trades zip, directory, or CSV file. Can be passed multiple times.",
    )
    parser.add_argument("--out", default="data/processed/orderflow/aggressive_flow_minute_stats.csv")
    parser.add_argument("--daily-out", default="data/processed/orderflow/aggressive_flow_daily_stats.csv")
    parser.add_argument("--start", default=None, help="Optional member start date, e.g. 2024-06-24.")
    parser.add_argument("--end", default=None, help="Optional member end date, e.g. 2025-06-13.")
    parser.add_argument("--max-files", type=int, default=None, help="Limit daily files per source for smoke tests.")
    parser.add_argument("--rows-per-file", type=int, default=None, help="Limit rows per file for smoke tests.")
    parser.add_argument(
        "--symbol-regex",
        default=NQ_OUTRIGHT_SYMBOL_PATTERN,
        help="Regex filter for symbols. Defaults to NQ outright futures and excludes calendar spreads.",
    )
    parser.add_argument("--progress-every", type=int, default=10)
    parser.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge new stats with existing output files instead of replacing them.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    minute_frames: list[pd.DataFrame] = []
    daily_frames: list[pd.DataFrame] = []
    for source in args.source:
        stats = build_aggressive_flow_stats_from_source(
            source,
            start=args.start,
            end=args.end,
            max_files=args.max_files,
            rows_per_file=args.rows_per_file,
            symbol_regex=args.symbol_regex,
            progress_every=int(args.progress_every),
        )
        if not stats.minute_stats.empty:
            minute_frames.append(stats.minute_stats)
        if not stats.daily_stats.empty:
            daily_frames.append(stats.daily_stats)

    out = Path(args.out)
    daily_out = Path(args.daily_out)
    if args.merge_existing and out.exists():
        minute_frames.insert(0, pd.read_csv(out, low_memory=False))
    if args.merge_existing and daily_out.exists():
        daily_frames.insert(0, pd.read_csv(daily_out, low_memory=False))

    minute_stats = merge_aggressive_flow_minute_stats(*minute_frames)
    daily_stats = merge_aggressive_flow_daily_stats(*daily_frames)

    out.parent.mkdir(parents=True, exist_ok=True)
    minute_stats.to_csv(out, index=False)

    daily_out.parent.mkdir(parents=True, exist_ok=True)
    daily_stats.to_csv(daily_out, index=False)

    print(f"Aggressive-flow minute stats: {out} ({len(minute_stats):,} rows)")
    print(f"Aggressive-flow daily stats:  {daily_out} ({len(daily_stats):,} rows)")
    if not daily_stats.empty:
        cols = [
            "symbol",
            "trade_date",
            "minutes",
            "total_trades",
            "total_trade_size",
            "raw_b_side_trade_size",
            "raw_a_side_trade_size",
            "raw_b_minus_a_trade_size",
            "raw_b_minus_a_trade_size_share",
        ]
        print(daily_stats[[col for col in cols if col in daily_stats.columns]].tail(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
