#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_topbook_execution import L2TopBookExecutionConfig  # noqa: E402
from backtest.l2_warm_state_matrix import (  # noqa: E402
    DEFAULT_WARM_STATE_DATES,
    build_l2_warm_state_execution_matrix,
    default_warm_state_window_specs,
    parse_window_spec,
    write_l2_warm_state_execution_matrix,
)


def parse_args() -> argparse.Namespace:
    default_windows = ", ".join(f"{item.name}={item.start_time}-{item.end_time}" for item in default_warm_state_window_specs())
    parser = argparse.ArgumentParser(
        description=(
            "Run a warm-state L2 execution-realism matrix over structured five-column parquet files. "
            "Each cell warms book state before the requested NY-time window and writes guarded artifacts. "
            "This does not run a strategy backtest."
        )
    )
    parser.add_argument("--archive-root", default="data/raw/l2_nq/zip_archives")
    parser.add_argument(
        "--date",
        action="append",
        default=[],
        help=f"YYYYMMDD date to validate. Defaults: {', '.join(DEFAULT_WARM_STATE_DATES)}",
    )
    parser.add_argument(
        "--window",
        action="append",
        default=[],
        help=f"Window spec `name=HH:MM:SS-HH:MM:SS`. Defaults: {default_windows}",
    )
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
    parser.add_argument("--out-dir", default="results/research_master/l2_warm_state_execution_matrix")
    parser.add_argument("--prefix", default="l2_warm_state_execution_matrix")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-baseline", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    windows = tuple(parse_window_spec(item) for item in args.window) if args.window else None
    execution_config = L2TopBookExecutionConfig(
        symbol=str(args.symbol),
        tick_size=float(args.tick_size),
        policy="price_key_all_actions_set",
        coalesce_window=str(args.coalesce_window),
        max_spread_ticks=float(args.max_spread_ticks),
        trade_alignment_tolerance=str(args.trade_alignment_tolerance),
        include_unknown_side_trades=bool(args.include_unknown_side_trades),
    )
    result = build_l2_warm_state_execution_matrix(
        args.archive_root,
        target_dates=tuple(args.date) if args.date else None,
        windows=windows,
        execution_config=execution_config,
        warmup_start_row_group=int(args.warmup_start_row_group),
        max_row_groups=int(args.max_row_groups) if args.max_row_groups is not None else None,
        max_rows=int(args.max_rows) if args.max_rows is not None else None,
        stale_level_ttl=str(args.stale_level_ttl) if args.stale_level_ttl else None,
        out_dir=args.out_dir,
        write_baselines=not bool(args.no_baseline),
        dry_run=bool(args.dry_run),
    )
    paths = write_l2_warm_state_execution_matrix(result, args.out_dir, prefix=args.prefix)
    print(f"L2 warm-state matrix report:           {paths['report_md']}")
    print(f"L2 warm-state matrix targets:          {paths['targets_csv']}")
    print(f"L2 warm-state matrix warm summary:     {paths['warm_state_summary_csv']}")
    print(f"L2 warm-state matrix quality summary:  {paths['quality_summary_csv']}")
    print(f"L2 warm-state matrix baseline summary: {paths['baseline_summary_csv']}")
    print()
    print(result.targets.to_string(index=False))
    if not result.warm_state_summary.empty:
        cols = [
            "date",
            "window",
            "warm_start_valid_top_book",
            "coalesced_quote_rows",
            "trade_rows",
            "minute_rows",
            "warnings",
        ]
        print()
        print(result.warm_state_summary[[col for col in cols if col in result.warm_state_summary.columns]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
