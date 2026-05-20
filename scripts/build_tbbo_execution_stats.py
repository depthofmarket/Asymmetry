#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.tbbo_execution import NQ_OUTRIGHT_SYMBOL_PATTERN, build_tbbo_execution_stats_from_source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build NQ futures TBBO execution-quality stats for fill/slippage validation."
    )
    parser.add_argument("--source", required=True, help="Databento TBBO zip, directory, or CSV file.")
    parser.add_argument("--out", default="data/processed/tbbo/tbbo_minute_execution_stats.csv")
    parser.add_argument("--daily-out", default="data/processed/tbbo/tbbo_daily_execution_stats.csv")
    parser.add_argument("--start", default=None, help="Optional member start date, e.g. 2026-02-16.")
    parser.add_argument("--end", default=None, help="Optional member end date, e.g. 2026-05-07.")
    parser.add_argument("--max-files", type=int, default=None, help="Limit daily files for smoke tests.")
    parser.add_argument("--rows-per-file", type=int, default=None, help="Limit rows per file for smoke tests.")
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument(
        "--symbol-regex",
        default=NQ_OUTRIGHT_SYMBOL_PATTERN,
        help="Regex filter for symbols. Defaults to NQ outright futures and excludes calendar spreads.",
    )
    parser.add_argument("--progress-every", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stats = build_tbbo_execution_stats_from_source(
        args.source,
        start=args.start,
        end=args.end,
        max_files=args.max_files,
        rows_per_file=args.rows_per_file,
        tick_size=float(args.tick_size),
        symbol_regex=args.symbol_regex,
        progress_every=int(args.progress_every),
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    stats.minute_stats.to_csv(out, index=False)

    daily_out = Path(args.daily_out)
    daily_out.parent.mkdir(parents=True, exist_ok=True)
    stats.daily_stats.to_csv(daily_out, index=False)

    print(f"TBBO minute execution stats: {out} ({len(stats.minute_stats):,} rows)")
    print(f"TBBO daily execution stats:  {daily_out} ({len(stats.daily_stats):,} rows)")
    if not stats.daily_stats.empty:
        cols = [
            "symbol",
            "trade_date",
            "minutes",
            "total_trades",
            "median_spread_points",
            "p95_spread_points",
            "p95_abs_trade_price_vs_mid",
        ]
        print(stats.daily_stats[[col for col in cols if col in stats.daily_stats.columns]].tail(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
