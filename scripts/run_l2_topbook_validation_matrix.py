#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_topbook_execution import L2TopBookExecutionConfig  # noqa: E402
from backtest.l2_topbook_validation_matrix import (  # noqa: E402
    DEFAULT_VALIDATION_DATES,
    build_l2_topbook_validation_matrix,
    write_l2_topbook_validation_matrix,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a bounded L2 top-book execution-realism validation matrix across selected dates. "
            "This discovers dated parquet members inside archived zips, builds sample top-book "
            "minute stats, and writes a combined report. It does not run a backtest."
        )
    )
    parser.add_argument("--archive-root", default="data/raw/l2_nq/zip_archives")
    parser.add_argument(
        "--date",
        action="append",
        default=[],
        help=(
            "YYYYMMDD parquet date to validate. Can be repeated. "
            f"Defaults: {', '.join(DEFAULT_VALIDATION_DATES)}"
        ),
    )
    parser.add_argument("--max-rows-per-member", type=int, default=200_000)
    parser.add_argument(
        "--start-row-group",
        type=int,
        default=0,
        help="Start decoding at this parquet row group. Useful for bounded later-session samples.",
    )
    parser.add_argument("--symbol", default="NQ_L2")
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument(
        "--policy",
        default="auto",
        help=(
            "Top-book reconstruction policy. `auto` keeps level-key reconstruction for old semicolon files "
            "and switches to price-key reconstruction for structured five-column files."
        ),
    )
    parser.add_argument("--coalesce-window", default="100ms")
    parser.add_argument("--max-spread-ticks", type=float, default=40.0)
    parser.add_argument("--trade-alignment-tolerance", default="5s")
    parser.add_argument("--include-unknown-side-trades", action="store_true")
    parser.add_argument("--out-dir", default="results/research_master/l2_topbook_validation_matrix")
    parser.add_argument("--prefix", default="l2_topbook_validation_matrix")
    parser.add_argument("--dry-run", action="store_true", help="Only discover selected date members; do not decode.")
    parser.add_argument("--no-baseline", action="store_true", help="Do not write per-date TBBO baseline reports.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = L2TopBookExecutionConfig(
        symbol=str(args.symbol),
        tick_size=float(args.tick_size),
        policy=str(args.policy),
        coalesce_window=str(args.coalesce_window),
        max_spread_ticks=float(args.max_spread_ticks),
        trade_alignment_tolerance=str(args.trade_alignment_tolerance),
        include_unknown_side_trades=bool(args.include_unknown_side_trades),
    )
    result = build_l2_topbook_validation_matrix(
        args.archive_root,
        target_dates=tuple(args.date) if args.date else None,
        config=config,
        max_rows_per_member=int(args.max_rows_per_member),
        start_row_group=int(args.start_row_group),
        out_dir=args.out_dir,
        write_baselines=not bool(args.no_baseline),
        dry_run=bool(args.dry_run),
    )
    paths = write_l2_topbook_validation_matrix(result, args.out_dir, prefix=args.prefix)
    print(f"L2 top-book matrix report:           {paths['report_md']}")
    print(f"L2 top-book matrix targets:          {paths['targets_csv']}")
    print(f"L2 top-book matrix quality summary:  {paths['quality_summary_csv']}")
    print(f"L2 top-book matrix baseline summary: {paths['baseline_summary_csv']}")
    print()
    print(result.targets.to_string(index=False))
    if not result.quality_summary.empty:
        cols = [
            "date",
            "policy",
            "decoded_rows",
            "usable_quote_rows",
            "usable_trade_rows",
            "minute_rows",
            "median_spread_ticks",
            "p95_spread_ticks",
        ]
        print()
        print(result.quality_summary[[col for col in cols if col in result.quality_summary.columns]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
