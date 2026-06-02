#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_execution_comparison import write_l2_execution_comparison  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare existing OHLCV/bar-assumed trade artifacts against L2-filled trade artifacts. "
            "This does not run a backtest or replay."
        )
    )
    parser.add_argument("--bar-trades-csv", required=True, help="Saved OHLCV/bar-assumed trade log CSV.")
    parser.add_argument("--l2-trades-csv", required=True, help="Trade log CSV from build_l2_prop_bridge.py.")
    parser.add_argument("--out-dir", default="results/research_master/l2_execution_comparison")
    parser.add_argument("--prefix", default="l2_execution_comparison")
    parser.add_argument("--timezone", default="America/New_York")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = write_l2_execution_comparison(
        args.bar_trades_csv,
        args.l2_trades_csv,
        args.out_dir,
        prefix=args.prefix,
        timezone=args.timezone,
    )
    print(f"normalized trades: {paths.normalized_trades_csv}")
    print(f"grouped summary:   {paths.grouped_summary_csv}")
    print(f"comparison:        {paths.comparison_csv}")
    print(f"report:            {paths.report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
