#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_prop_bridge import write_l2_prop_bridge_artifacts  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert an existing L2 replay fills CSV into realized trade and daily prop-path artifacts. "
            "This does not run a backtest or replay."
        )
    )
    parser.add_argument("--fills-csv", required=True, help="L2 replay fills CSV, usually *_fills.csv.")
    parser.add_argument("--out-dir", default="results/research_master/l2_prop_bridge")
    parser.add_argument("--prefix", default="l2_prop_bridge")
    parser.add_argument("--contract-value", type=float, default=20.0)
    parser.add_argument("--timezone", default="America/New_York")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = write_l2_prop_bridge_artifacts(
        args.fills_csv,
        args.out_dir,
        prefix=args.prefix,
        contract_value=float(args.contract_value),
        timezone=args.timezone,
    )
    print(f"trade log:       {paths.trade_log_csv}")
    print(f"daily prop path: {paths.daily_prop_path_csv}")
    print(f"summary:         {paths.summary_csv}")
    print(f"report:          {paths.report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
