#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.tbbo_execution_baseline import (  # noqa: E402
    build_tbbo_execution_baseline,
    read_tbbo_minute_stats,
    write_tbbo_execution_baseline,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a TBBO execution-cost baseline from processed NQ minute stats."
    )
    parser.add_argument(
        "--tbbo-minute",
        default="data/processed/tbbo/tbbo_minute_execution_stats.csv",
        help="Processed TBBO minute stats CSV from build_tbbo_execution_stats.py.",
    )
    parser.add_argument(
        "--out-dir",
        default="results/research_master/tbbo_execution_baseline",
        help="Output directory for baseline CSVs and Markdown report.",
    )
    parser.add_argument(
        "--assumed-round-trip-cost-points",
        type=float,
        default=1.5,
        help="Backtest round-trip cost assumption to compare against TBBO spread/trade-vs-mid costs.",
    )
    parser.add_argument(
        "--min-rows-per-minute",
        type=int,
        default=5,
        help="Minutes below this quote/trade row count are flagged as sparse.",
    )
    parser.add_argument(
        "--min-daily-minutes",
        type=int,
        default=30,
        help="Date/symbol groups below this minute count are flagged as sparse.",
    )
    parser.add_argument(
        "--wide-spread-points",
        type=float,
        default=10.0,
        help="Date/symbol groups with median spread-implied round-trip cost above this are flagged.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    minute_stats = read_tbbo_minute_stats(args.tbbo_minute)
    baseline = build_tbbo_execution_baseline(
        minute_stats,
        assumed_round_trip_cost_points=float(args.assumed_round_trip_cost_points),
        min_rows_per_minute=int(args.min_rows_per_minute),
        min_daily_minutes=int(args.min_daily_minutes),
        wide_spread_points=float(args.wide_spread_points),
    )
    paths = write_tbbo_execution_baseline(baseline, args.out_dir)

    print(f"TBBO minute stats: {args.tbbo_minute}")
    print(baseline.summary.to_string(index=False))
    print(f"summary:       {paths.summary_csv}")
    print(f"by_session:    {paths.by_session_csv}")
    print(f"by_hour:       {paths.by_hour_csv}")
    print(f"by_date:       {paths.by_date_csv}")
    print(f"quality_flags: {paths.quality_flags_csv}")
    print(f"report:        {paths.report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
