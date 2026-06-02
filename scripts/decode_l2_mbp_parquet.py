#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_mbp import (  # noqa: E402
    decode_l2_mbp_sources,
    select_l2_parquet_sources,
    write_l2_mbp_decode_artifacts,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Decode a bounded sample from NQ L2 CSV or parquet files. "
            "This writes clean event columns for schema/semantic validation only; it does not run "
            "a backtest or full-history scan."
        )
    )
    parser.add_argument("--source", required=True, help="CSV/parquet file, directory, or zip archive.")
    parser.add_argument(
        "--member",
        action="append",
        default=[],
        help="Specific CSV/parquet member to decode inside a zip, or relative file path inside a directory.",
    )
    parser.add_argument(
        "--member-glob",
        default="*.parquet",
        help="Glob used when --member is not supplied. For zip paths this matches names inside the archive.",
    )
    parser.add_argument("--max-members", type=int, default=1, help="Maximum files/members to decode.")
    parser.add_argument(
        "--max-rows-per-member",
        type=int,
        default=50_000,
        help="Maximum decoded rows per file/member. Must be positive; this CLI is intentionally bounded.",
    )
    parser.add_argument(
        "--start-row-group",
        type=int,
        default=0,
        help="Start decoding at this parquet row group. Useful for bounded later-session samples.",
    )
    parser.add_argument("--out-dir", default="results/research_master/l2_mbp_decode")
    parser.add_argument("--prefix", default="l2_mbp_decode")
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

    artifacts = decode_l2_mbp_sources(
        refs,
        max_rows_per_source=int(args.max_rows_per_member),
        start_row_group=int(args.start_row_group),
    )
    paths = write_l2_mbp_decode_artifacts(artifacts, args.out_dir, prefix=args.prefix)
    print(f"L2 decode report:  {paths['report_md']}")
    print(f"L2 decode summary: {paths['summary_csv']}")
    print(f"L2 events sample:  {paths['events_csv']}")
    print(f"Decoded sources:   {len(refs)}")
    print(f"Decoded rows:      {len(artifacts.events):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
