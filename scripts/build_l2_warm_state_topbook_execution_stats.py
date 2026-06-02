#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_mbp import select_l2_parquet_sources  # noqa: E402
from backtest.l2_topbook_execution import L2TopBookExecutionConfig  # noqa: E402
from backtest.l2_warm_state import (  # noqa: E402
    L2WarmStateWindowConfig,
    build_l2_warm_state_topbook_execution_artifacts,
    write_l2_warm_state_topbook_artifacts,
)
from backtest.tbbo_execution_baseline import build_tbbo_execution_baseline, write_tbbo_execution_baseline  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build warm-state top-book execution stats from one structured five-column NQ L2 parquet file. "
            "Rows before the requested window warm the price-key book state but are not emitted. "
            "This does not run a backtest."
        )
    )
    parser.add_argument("--source", required=True, help="Structured parquet file or zip archive.")
    parser.add_argument(
        "--member",
        action="append",
        default=[],
        help="Specific parquet member inside a zip, or relative parquet path inside a directory.",
    )
    parser.add_argument("--member-glob", default="*.parquet")
    parser.add_argument("--window-start", required=True, help="Window start. Naive values are interpreted as New York time.")
    parser.add_argument("--window-end", required=True, help="Window end. Naive values are interpreted as New York time.")
    parser.add_argument("--timezone", default="America/New_York")
    parser.add_argument("--warmup-start-row-group", type=int, default=0)
    parser.add_argument("--max-row-groups", type=int)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument(
        "--stale-level-ttl",
        help=(
            "Optional TTL for structured price levels, for example 30s. "
            "This is an explicit reconstruction assumption for feeds with missing deletes."
        ),
    )
    parser.add_argument("--symbol", default="NQ_L2")
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument("--coalesce-window", default="100ms")
    parser.add_argument("--max-spread-ticks", type=float, default=40.0)
    parser.add_argument("--trade-alignment-tolerance", default="5s")
    parser.add_argument("--include-unknown-side-trades", action="store_true")
    parser.add_argument("--out-dir", default="results/research_master/l2_warm_state_topbook")
    parser.add_argument("--prefix", default="l2_warm_state_topbook")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Also write a TBBO execution baseline report from the produced minute stats.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    refs = select_l2_parquet_sources(
        args.source,
        members=args.member,
        member_glob=args.member_glob,
        max_members=1,
    )
    if not refs:
        raise SystemExit(f"No parquet files selected from source: {args.source}")

    window_config = L2WarmStateWindowConfig(
        window_start=str(args.window_start),
        window_end=str(args.window_end),
        source_timezone=str(args.timezone),
        warmup_start_row_group=int(args.warmup_start_row_group),
        max_row_groups=int(args.max_row_groups) if args.max_row_groups is not None else None,
        max_rows=int(args.max_rows) if args.max_rows is not None else None,
        stale_level_ttl=str(args.stale_level_ttl) if args.stale_level_ttl else None,
    )
    execution_config = L2TopBookExecutionConfig(
        symbol=str(args.symbol),
        tick_size=float(args.tick_size),
        policy="price_key_all_actions_set",
        coalesce_window=str(args.coalesce_window),
        max_spread_ticks=float(args.max_spread_ticks),
        trade_alignment_tolerance=str(args.trade_alignment_tolerance),
        include_unknown_side_trades=bool(args.include_unknown_side_trades),
    )
    artifacts = build_l2_warm_state_topbook_execution_artifacts(
        refs[0],
        window_config=window_config,
        execution_config=execution_config,
    )
    paths = write_l2_warm_state_topbook_artifacts(artifacts, args.out_dir, prefix=args.prefix)
    print(f"L2 warm-state events:          {paths['topbook_events_csv']}")
    print(f"L2 warm-state minute stats:    {paths['minute_stats_csv']}")
    print(f"L2 warm-state daily stats:     {paths['daily_stats_csv']}")
    print(f"L2 warm-state quality summary: {paths['quality_summary_csv']}")
    print(f"L2 warm-state summary:         {paths['warm_state_summary_csv']}")
    print(f"L2 warm-state report:          {paths['report_md']}")
    if not artifacts.warm_state_summary.empty:
        print()
        print(artifacts.warm_state_summary.to_string(index=False))

    if args.write_baseline:
        if artifacts.minute_stats.empty:
            print("TBBO-compatible baseline:      skipped; no minute stats were produced")
        else:
            baseline = build_tbbo_execution_baseline(artifacts.minute_stats)
            baseline_paths = write_tbbo_execution_baseline(
                baseline,
                Path(args.out_dir) / "tbbo_baseline",
                prefix=f"{args.prefix}_tbbo_baseline",
            )
            print(f"TBBO-compatible baseline:      {baseline_paths.report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
