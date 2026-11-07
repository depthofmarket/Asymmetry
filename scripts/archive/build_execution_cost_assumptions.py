#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.execution_cost_assumptions import (  # noqa: E402
    DEFAULT_L2_BASELINE_SUMMARY,
    DEFAULT_L2_QUALITY_SUMMARY,
    build_execution_cost_assumption_report_from_csv,
    write_execution_cost_assumption_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert validated L2 top-book evidence into static NQ backtest cost assumptions."
    )
    parser.add_argument(
        "--quality-summary",
        default=str(DEFAULT_L2_QUALITY_SUMMARY),
        help="L2 validation matrix quality summary CSV.",
    )
    parser.add_argument(
        "--baseline-summary",
        default=str(DEFAULT_L2_BASELINE_SUMMARY),
        help="L2 validation matrix execution baseline summary CSV.",
    )
    parser.add_argument(
        "--out-dir",
        default="results/research_master/execution_cost_assumptions",
        help="Output directory for recommendation CSVs and Markdown report.",
    )
    parser.add_argument(
        "--prefix",
        default="execution_cost_assumptions",
        help="Output filename prefix.",
    )
    parser.add_argument(
        "--min-accepted-minutes",
        type=int,
        default=30,
        help="Minimum minute rows required before a date sample can calibrate costs.",
    )
    parser.add_argument(
        "--min-accepted-quotes",
        type=int,
        default=1000,
        help="Minimum usable quote rows required before a date sample can calibrate costs.",
    )
    parser.add_argument(
        "--min-quote-rows-per-depth-update",
        type=float,
        default=0.01,
        help="Minimum quote/depth-update ratio required before a date sample can calibrate costs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_execution_cost_assumption_report_from_csv(
        quality_summary_path=args.quality_summary,
        baseline_summary_path=args.baseline_summary,
        min_accepted_minutes=int(args.min_accepted_minutes),
        min_accepted_quotes=int(args.min_accepted_quotes),
        min_quote_rows_per_depth_update=float(args.min_quote_rows_per_depth_update),
    )
    paths = write_execution_cost_assumption_report(report, args.out_dir, prefix=args.prefix)
    print(report.recommendation.to_string(index=False))
    print(f"evidence:       {paths.evidence_csv}")
    print(f"recommendation: {paths.recommendation_csv}")
    print(f"report:         {paths.report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
