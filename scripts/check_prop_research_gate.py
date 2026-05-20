#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.live_prop_rules import validate_prop_research_gate


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate saved prop-firm research artifacts before funded/payout trading modes."
    )
    parser.add_argument("--run-dir", default=None, help="Saved results/runs/<label> directory. Defaults to results/latest.txt.")
    parser.add_argument("--min-combined-mild-pf", type=float, default=1.05)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = validate_prop_research_gate(
            args.run_dir,
            min_combined_mild_pf=float(args.min_combined_mild_pf),
        )
    except Exception as exc:
        print(f"Prop research gate failed before checks: {exc}")
        return 2
    print(report.summary())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
