#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_depth_semantics_matrix import (  # noqa: E402
    L2DepthSemanticsProofConfig,
    build_l2_depth_semantics_proof_matrix,
    write_l2_depth_semantics_proof_matrix,
)
from backtest.l2_topbook_validation_matrix import DEFAULT_VALIDATION_DATES  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a bounded L2 depth-semantics proof matrix. "
            "This validates depth reconstruction policies; it is not a strategy backtest."
        )
    )
    parser.add_argument("--archive-root", default="data/raw/l2_nq/zip_archives")
    parser.add_argument(
        "--date",
        action="append",
        default=[],
        help="YYYYMMDD target date. Repeat for multiple dates. Defaults to the standard six-date matrix.",
    )
    parser.add_argument("--out-dir", default="results/research_master/l2_depth_semantics_proof_matrix")
    parser.add_argument("--prefix", default="l2_depth_semantics_proof_matrix")
    parser.add_argument("--max-rows-per-member", type=int, default=200_000)
    parser.add_argument("--start-row-group", type=int, default=0)
    parser.add_argument("--max-snapshots-per-policy", type=int, default=20_000)
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument("--max-reasonable-spread-ticks", type=float, default=20.0)
    parser.add_argument("--min-depth-events", type=int, default=1_000)
    parser.add_argument("--min-snapshots", type=int, default=1_000)
    parser.add_argument("--min-valid-top-book-pct", type=float, default=0.95)
    parser.add_argument("--max-crossed-or-locked-pct", type=float, default=0.005)
    parser.add_argument("--max-monotonic-violation-pct", type=float, default=0.01)
    parser.add_argument("--min-reasonable-spread-pct", type=float, default=0.95)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target_dates = tuple(args.date or DEFAULT_VALIDATION_DATES)
    config = L2DepthSemanticsProofConfig(
        tick_size=float(args.tick_size),
        max_reasonable_spread_ticks=float(args.max_reasonable_spread_ticks),
        max_rows_per_member=int(args.max_rows_per_member),
        start_row_group=int(args.start_row_group),
        max_snapshots_per_policy=int(args.max_snapshots_per_policy),
        min_depth_events=int(args.min_depth_events),
        min_snapshots=int(args.min_snapshots),
        min_valid_top_book_pct=float(args.min_valid_top_book_pct),
        max_crossed_or_locked_pct=float(args.max_crossed_or_locked_pct),
        max_monotonic_violation_pct=float(args.max_monotonic_violation_pct),
        min_reasonable_spread_pct=float(args.min_reasonable_spread_pct),
    )
    result = build_l2_depth_semantics_proof_matrix(
        args.archive_root,
        target_dates=target_dates,
        config=config,
        dry_run=bool(args.dry_run),
    )
    paths = write_l2_depth_semantics_proof_matrix(result, args.out_dir, prefix=args.prefix)
    if not result.decision_summary.empty:
        print(result.decision_summary.to_string(index=False))
    else:
        print(result.targets.to_string(index=False))
    print(f"targets:          {paths['targets_csv']}")
    print(f"policy evidence:  {paths['policy_evidence_csv']}")
    print(f"decision summary: {paths['decision_summary_csv']}")
    print(f"report:           {paths['report_md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
