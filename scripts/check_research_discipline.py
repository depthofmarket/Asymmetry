#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.validation import export_research_discipline_report
from config.backtest_config import RESEARCH_CONFIG, VALIDATION_CONFIG


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate a saved run against the strict anti-overfit research discipline gate."
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        help="Saved results/runs/<run_label> directory. This reads saved artifacts only.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    paths = export_research_discipline_report(
        run_dir=Path(args.run_dir),
        validation_config=VALIDATION_CONFIG,
        research_config=RESEARCH_CONFIG,
    )
    print(f"Wrote {paths.csv_path}")
    print(f"Wrote {paths.markdown_path}")

    import pandas as pd

    report = pd.read_csv(paths.csv_path)
    summary = report.loc[report["check"].eq("promotion_eligible")]
    eligible = bool(not summary.empty and summary.iloc[0]["status"] == "PASS")
    print(f"Promotion eligible: {'yes' if eligible else 'no'}")
    return 0 if eligible else 1


if __name__ == "__main__":
    raise SystemExit(main())
