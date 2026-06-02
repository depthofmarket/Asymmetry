#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_mbp import decode_l2_mbp_sources, select_l2_parquet_sources  # noqa: E402
from backtest.l2_source_resolver import decode_l2_source_selection, resolve_l2_source_index  # noqa: E402
from backtest.l2_topbook_execution import (  # noqa: E402
    L2TopBookExecutionConfig,
    build_l2_topbook_execution_artifacts,
    write_l2_topbook_execution_artifacts,
)
from backtest.tbbo_execution_baseline import build_tbbo_execution_baseline, write_tbbo_execution_baseline  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build guarded top-of-book execution stats from bounded NQ L2 CSV or parquet samples. "
            "The output minute stats are compatible with the existing TBBO execution baseline and "
            "trade audit modules. This is bounded by default and does not run a backtest."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--source", help="CSV/parquet file, directory, or zip archive.")
    input_group.add_argument(
        "--source-index",
        help="l2_source_index.csv produced by scripts/build_l2_dataset_qa.py.",
    )
    parser.add_argument(
        "--member",
        action="append",
        default=[],
        help="Specific CSV/parquet member inside a zip, or relative file path inside a directory.",
    )
    parser.add_argument("--member-glob", default="*.parquet")
    parser.add_argument("--max-members", type=int, default=1)
    parser.add_argument("--max-rows-per-member", type=int, default=200_000)
    parser.add_argument(
        "--trade-date",
        action="append",
        default=[],
        help="YYYYMMDD date to load from --source-index. Repeat for multiple dates.",
    )
    parser.add_argument("--start-date", help="Inclusive YYYYMMDD range start for --source-index.")
    parser.add_argument("--end-date", help="Inclusive YYYYMMDD range end for --source-index.")
    parser.add_argument(
        "--max-dates",
        type=int,
        help="Optional cap on resolved dates from --source-index. Useful for bounded smoke runs.",
    )
    parser.add_argument("--allow-missing-dates", action="store_true")
    parser.add_argument("--allow-duplicate-dates", action="store_true")
    parser.add_argument(
        "--start-row-group",
        type=int,
        default=0,
        help="Start decoding at this parquet row group. Useful for bounded later-session samples.",
    )
    parser.add_argument("--symbol", default="NQ_L2")
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument("--policy", default="auto")
    parser.add_argument("--coalesce-window", default="100ms")
    parser.add_argument("--max-spread-ticks", type=float, default=40.0)
    parser.add_argument("--trade-alignment-tolerance", default="5s")
    parser.add_argument("--include-unknown-side-trades", action="store_true")
    parser.add_argument("--out-dir", default="results/research_master/l2_topbook_execution")
    parser.add_argument("--prefix", default="l2_topbook_execution")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Also write a TBBO execution baseline report from the produced minute stats.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    refs, decoded = _decode_sources(args)
    config = L2TopBookExecutionConfig(
        symbol=str(args.symbol),
        tick_size=float(args.tick_size),
        policy=str(args.policy),
        coalesce_window=str(args.coalesce_window),
        max_spread_ticks=float(args.max_spread_ticks),
        trade_alignment_tolerance=str(args.trade_alignment_tolerance),
        include_unknown_side_trades=bool(args.include_unknown_side_trades),
    )
    artifacts = build_l2_topbook_execution_artifacts(decoded.events, config=config)
    paths = write_l2_topbook_execution_artifacts(artifacts, args.out_dir, prefix=args.prefix)
    print(f"L2 top-book events:          {paths['topbook_events_csv']}")
    print(f"L2 top-book minute stats:    {paths['minute_stats_csv']}")
    print(f"L2 top-book daily stats:     {paths['daily_stats_csv']}")
    print(f"L2 top-book quality summary: {paths['quality_summary_csv']}")
    print(f"L2 top-book report:          {paths['report_md']}")
    print(f"Decoded sources:             {len(refs)}")
    print(f"Decoded rows:                {len(decoded.events):,}")
    print(f"Minute rows:                 {len(artifacts.minute_stats):,}")
    if not artifacts.quality_summary.empty:
        print(artifacts.quality_summary.to_string(index=False))

    if args.write_baseline:
        baseline = build_tbbo_execution_baseline(artifacts.minute_stats)
        baseline_paths = write_tbbo_execution_baseline(
            baseline,
            Path(args.out_dir) / "tbbo_baseline",
            prefix=f"{args.prefix}_tbbo_baseline",
        )
        print(f"TBBO-compatible baseline:    {baseline_paths.report_md}")
    return 0


def _decode_sources(args: argparse.Namespace):
    if args.source_index:
        selection = resolve_l2_source_index(
            args.source_index,
            trade_dates=args.trade_date,
            start_date=args.start_date,
            end_date=args.end_date,
            max_dates=args.max_dates,
            allow_missing_dates=bool(args.allow_missing_dates),
            allow_duplicate_dates=bool(args.allow_duplicate_dates),
            repo_root=REPO_ROOT,
        )
        if not selection.refs:
            raise SystemExit("No L2 sources were resolved from --source-index.")
        decoded = decode_l2_source_selection(
            selection,
            max_rows_per_source=int(args.max_rows_per_member),
            start_row=int(args.start_row_group),
        )
        dates = ", ".join(dict.fromkeys(selection.resolved_dates))
        print(f"Resolved L2 dates:           {dates}")
        return selection.refs, decoded

    refs = select_l2_parquet_sources(
        args.source,
        members=args.member,
        member_glob=args.member_glob,
        max_members=args.max_members,
    )
    if not refs:
        raise SystemExit(f"No CSV/parquet files selected from source: {args.source}")
    decoded = decode_l2_mbp_sources(
        refs,
        max_rows_per_source=int(args.max_rows_per_member),
        start_row_group=int(args.start_row_group),
    )
    return refs, decoded


if __name__ == "__main__":
    raise SystemExit(main())
