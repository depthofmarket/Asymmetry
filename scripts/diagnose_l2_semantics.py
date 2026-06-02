#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_mbp import decode_l2_mbp_sources, select_l2_parquet_sources  # noqa: E402
from backtest.l2_semantic_diagnostics import (  # noqa: E402
    diagnose_l2_semantics,
    write_l2_semantic_diagnostics_artifacts,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run bounded semantic diagnostics for NQ L2 parquet data. "
            "This inspects event codes, depth update behavior, top-book reconstruction stability, and "
            "type-1 event alignment. It does not run a backtest or full-history scan."
        )
    )
    parser.add_argument("--source", required=True, help="Parquet file, directory, or zip archive.")
    parser.add_argument(
        "--member",
        action="append",
        default=[],
        help="Specific parquet member inside a zip, or relative parquet path inside a directory.",
    )
    parser.add_argument("--member-glob", default="*.parquet")
    parser.add_argument("--max-members", type=int, default=1)
    parser.add_argument("--max-rows-per-member", type=int, default=200_000)
    parser.add_argument(
        "--start-row-group",
        type=int,
        default=0,
        help="Start decoding at this parquet row group. Useful for bounded later-session samples.",
    )
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument(
        "--coalesce-window",
        action="append",
        default=[],
        help="Top-book coalescing window, for example event, 1ms, 10ms, 100ms, 1s. Can be repeated.",
    )
    parser.add_argument(
        "--policy",
        action="append",
        default=[],
        help="Book reconstruction policy name. Can be repeated.",
    )
    parser.add_argument("--out-dir", default="results/research_master/l2_semantic_diagnostics")
    parser.add_argument("--prefix", default="l2_semantic_diagnostics")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    refs = select_l2_parquet_sources(
        args.source,
        members=args.member,
        member_glob=args.member_glob,
        max_members=args.max_members,
    )
    if not refs:
        raise SystemExit(f"No parquet files selected from source: {args.source}")

    decoded = decode_l2_mbp_sources(
        refs,
        max_rows_per_source=int(args.max_rows_per_member),
        start_row_group=int(args.start_row_group),
    )
    artifacts = diagnose_l2_semantics(
        decoded.events,
        tick_size=float(args.tick_size),
        coalesce_windows=tuple(args.coalesce_window) if args.coalesce_window else ("event", "1ms", "10ms", "100ms", "1s"),
        policy_names=tuple(args.policy) if args.policy else ("0_insert_1_update_2_delete", "all_actions_set"),
    )
    paths = write_l2_semantic_diagnostics_artifacts(artifacts, args.out_dir, prefix=args.prefix)
    print(f"L2 semantic diagnostics report:        {paths['report_md']}")
    print(f"L2 semantic field summary:             {paths['field_summary_csv']}")
    print(f"L2 semantic depth action summary:      {paths['depth_action_summary_csv']}")
    print(f"L2 semantic initial depth sample:      {paths['initial_depth_sample_csv']}")
    print(f"L2 semantic top-book summary:          {paths['top_book_summary_csv']}")
    print(f"L2 semantic type-1 alignment summary:  {paths['trade_alignment_summary_csv']}")
    print(f"Decoded sources:                       {len(refs)}")
    print(f"Decoded rows:                          {len(decoded.events):,}")
    if not artifacts.top_book_summary.empty:
        cols = [
            "policy",
            "window",
            "snapshots",
            "valid_top_book_pct",
            "crossed_or_locked_pct",
            "median_spread_ticks",
            "duplicate_price_level_pct",
            "monotonic_violation_pct",
        ]
        print(artifacts.top_book_summary[cols].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
