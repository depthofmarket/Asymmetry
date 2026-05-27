#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.tbbo_dbn import build_tbbo_execution_stats_from_dbn
from backtest.tbbo_execution import NQ_OUTRIGHT_SYMBOL_PATTERN, build_tbbo_execution_stats_from_source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build NQ futures TBBO execution-quality stats for fill/slippage validation."
    )
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help="Databento TBBO zip, directory, CSV, or DBN file. Can be passed multiple times.",
    )
    parser.add_argument("--out", default="data/processed/tbbo/tbbo_minute_execution_stats.csv")
    parser.add_argument("--daily-out", default="data/processed/tbbo/tbbo_daily_execution_stats.csv")
    parser.add_argument("--start", default=None, help="Optional member start date, e.g. 2026-02-16.")
    parser.add_argument("--end", default=None, help="Optional member end date, e.g. 2026-05-07.")
    parser.add_argument("--max-files", type=int, default=None, help="Limit daily files for smoke tests.")
    parser.add_argument("--rows-per-file", type=int, default=None, help="Limit rows per file for smoke tests.")
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument(
        "--dbn-symbol",
        default=None,
        help="Symbol label to use for DBN files. Defaults to the first continuous symbol found in DBN metadata.",
    )
    parser.add_argument(
        "--dbn-chunk-records",
        type=int,
        default=500_000,
        help="Number of DBN records to decode per streaming chunk.",
    )
    parser.add_argument(
        "--dbn-limit-records",
        type=int,
        default=None,
        help="Limit DBN records for bounded smoke tests.",
    )
    parser.add_argument(
        "--symbol-regex",
        default=None,
        help=(
            "Regex filter for symbols. CSV/zip defaults to NQ outright futures and excludes calendar spreads; "
            "DBN sources default to the inferred DBN symbol."
        ),
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
        source_path = Path(source)
        if source_path.suffix.lower() == ".dbn":
            stats = build_tbbo_execution_stats_from_dbn(
                source_path,
                start=args.start,
                end=args.end,
                limit_records=args.dbn_limit_records if args.dbn_limit_records is not None else args.rows_per_file,
                chunk_records=int(args.dbn_chunk_records),
                tick_size=float(args.tick_size),
                symbol=args.dbn_symbol,
                symbol_regex=args.symbol_regex,
                progress_every=int(args.progress_every),
            )
        else:
            symbol_regex = args.symbol_regex if args.symbol_regex is not None else NQ_OUTRIGHT_SYMBOL_PATTERN
            stats = build_tbbo_execution_stats_from_source(
                source_path,
                start=args.start,
                end=args.end,
                max_files=args.max_files,
                rows_per_file=args.rows_per_file,
                tick_size=float(args.tick_size),
                symbol_regex=symbol_regex,
                progress_every=int(args.progress_every),
            )
        if not stats.minute_stats.empty:
            minute_frames.append(stats.minute_stats)
        if not stats.daily_stats.empty:
            daily_frames.append(stats.daily_stats)

    out = Path(args.out)
    if args.merge_existing and out.exists():
        minute_frames.insert(0, pd.read_csv(out, low_memory=False))
    minute_stats = _merge_minute_stats(minute_frames)
    out.parent.mkdir(parents=True, exist_ok=True)
    minute_stats.to_csv(out, index=False)

    daily_out = Path(args.daily_out)
    if args.merge_existing and daily_out.exists():
        daily_frames.insert(0, pd.read_csv(daily_out, low_memory=False))
    daily_stats = _merge_daily_stats(daily_frames)
    daily_out.parent.mkdir(parents=True, exist_ok=True)
    daily_stats.to_csv(daily_out, index=False)

    print(f"TBBO minute execution stats: {out} ({len(minute_stats):,} rows)")
    print(f"TBBO daily execution stats:  {daily_out} ({len(daily_stats):,} rows)")
    if not daily_stats.empty:
        cols = [
            "symbol",
            "trade_date",
            "minutes",
            "total_trades",
            "median_spread_points",
            "p95_spread_points",
            "p95_abs_trade_price_vs_mid",
            "raw_b_minus_a_trade_size",
        ]
        print(daily_stats[[col for col in cols if col in daily_stats.columns]].tail(10).to_string(index=False))
    return 0


def _merge_minute_stats(frames: list[pd.DataFrame]) -> pd.DataFrame:
    non_empty = [frame for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return pd.DataFrame()
    out = pd.concat(non_empty, ignore_index=True)
    out["minute"] = pd.to_datetime(out["minute"], errors="coerce")
    out = out.dropna(subset=["symbol", "minute"])
    return out.drop_duplicates(subset=["symbol", "minute"], keep="last").sort_values(["symbol", "minute"]).reset_index(drop=True)


def _merge_daily_stats(frames: list[pd.DataFrame]) -> pd.DataFrame:
    non_empty = [frame for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return pd.DataFrame()
    out = pd.concat(non_empty, ignore_index=True)
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.date.astype("string")
    out = out.dropna(subset=["symbol", "trade_date"])
    return out.drop_duplicates(subset=["symbol", "trade_date"], keep="last").sort_values(["symbol", "trade_date"]).reset_index(drop=True)


if __name__ == "__main__":
    raise SystemExit(main())
