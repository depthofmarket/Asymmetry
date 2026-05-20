#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.execution_realism import export_execution_realism_report  # noqa: E402
from config.backtest_config import CANDIDATE_CONFIGS, FUTURES_SPECS, STRATEGY_PARAMS  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a saved trade-log execution-realism report without rerunning a backtest."
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Run folder containing trades/trade_log.csv. Defaults to results/latest.txt.",
    )
    parser.add_argument("--candidate", default=None, help="Candidate config name for target-fill settings.")
    parser.add_argument("--trade-log", default=None, help="Explicit trade log CSV. Overrides --run-dir.")
    parser.add_argument("--out-dir", default=None, help="Output directory. Defaults to <run-dir>/research/execution_realism.")
    return parser.parse_args()


def _default_run_dir() -> Path:
    latest = Path("results/latest.txt")
    if not latest.exists():
        raise FileNotFoundError("results/latest.txt is missing; pass --run-dir or --trade-log")
    label = latest.read_text(encoding="utf-8").strip()
    if not label:
        raise ValueError("results/latest.txt is empty; pass --run-dir or --trade-log")
    return Path("results/runs") / label


def _strategy_params(candidate: str | None) -> dict:
    params = dict(STRATEGY_PARAMS)
    if candidate:
        if candidate not in CANDIDATE_CONFIGS:
            raise KeyError(f"Unknown candidate: {candidate}")
        params.update(CANDIDATE_CONFIGS[candidate])
        params["_candidate_name"] = candidate
    return params


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else _default_run_dir()
    trade_log = Path(args.trade_log) if args.trade_log else run_dir / "trades" / "trade_log.csv"
    out_dir = Path(args.out_dir) if args.out_dir else run_dir / "research" / "execution_realism"
    trades = pd.read_csv(trade_log)
    paths = export_execution_realism_report(
        trades,
        out_dir=out_dir,
        futures_specs=FUTURES_SPECS,
        strategy_params=_strategy_params(args.candidate),
        artifact_name="execution_realism",
    )
    print(f"Execution realism audit: {trade_log}")
    print(f"summary: {paths.summary_csv}")
    print(f"by_reason: {paths.by_reason_csv}")
    print(f"markdown: {paths.markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
