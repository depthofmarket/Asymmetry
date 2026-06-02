#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_book_validation import (  # noqa: E402
    validate_l2_book_semantics,
    write_l2_book_validation_artifacts,
)
from backtest.l2_mbp import decode_l2_mbp_sources, select_l2_parquet_sources  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate action-code semantics for the one-column NQ L2 parquet data by reconstructing "
            "bounded top-of-book snapshots under several hypotheses. This is not a backtest."
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
    parser.add_argument("--max-rows-per-member", type=int, default=100_000)
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument("--max-reasonable-spread-ticks", type=float, default=20.0)
    parser.add_argument("--max-snapshots-per-policy", type=int, default=10_000)
    parser.add_argument("--out-dir", default="results/research_master/l2_book_validation")
    parser.add_argument("--prefix", default="l2_book_validation")
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

    decoded = decode_l2_mbp_sources(refs, max_rows_per_source=int(args.max_rows_per_member))
    artifacts = validate_l2_book_semantics(
        decoded.events,
        tick_size=float(args.tick_size),
        max_reasonable_spread_ticks=float(args.max_reasonable_spread_ticks),
        max_snapshots_per_policy=int(args.max_snapshots_per_policy),
    )
    paths = write_l2_book_validation_artifacts(artifacts, args.out_dir, prefix=args.prefix)
    print(f"L2 book validation report:    {paths['report_md']}")
    print(f"L2 book validation summary:   {paths['summary_csv']}")
    print(f"L2 book validation snapshots: {paths['snapshots_csv']}")
    print(f"Decoded sources:              {len(refs)}")
    print(f"Decoded rows:                 {len(decoded.events):,}")
    if not artifacts.summary.empty:
        cols = [
            "source_label",
            "policy",
            "sanity_score",
            "valid_top_book_pct",
            "crossed_or_locked_pct",
            "monotonic_violation_pct",
            "median_spread_ticks",
            "p95_spread_ticks",
        ]
        print(artifacts.summary[[col for col in cols if col in artifacts.summary.columns]].head(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
