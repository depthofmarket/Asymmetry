#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.tbbo_trade_audit import (  # noqa: E402
    build_tbbo_trade_audit,
    read_tbbo_minute_stats,
    read_trade_log,
    write_tbbo_trade_audit,
)
from config.backtest_config import FUTURES_SPECS  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit saved backtest trades against processed NQ TBBO execution-quality stats."
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Run folder containing trades/trade_log.csv. Defaults to results/latest.txt.",
    )
    parser.add_argument(
        "--trade-log",
        default=None,
        help="Explicit trade log CSV. Overrides --run-dir/trades/trade_log.csv.",
    )
    parser.add_argument(
        "--tbbo-minute",
        default="data/processed/tbbo/tbbo_minute_execution_stats.csv",
        help="Processed TBBO minute stats CSV from build_tbbo_execution_stats.py.",
    )
    parser.add_argument(
        "--volatility-state-csv",
        default="",
        help="Optional volatility-state CSV from backtest.volatility_state for volatility-conditioned cost stress.",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory. Defaults to <run-dir>/research/tbbo_execution.",
    )
    parser.add_argument(
        "--nearest-tolerance",
        default="1min",
        help="Nearest TBBO minute tolerance for matching entry/exit timestamps.",
    )
    return parser.parse_args()


def _default_run_dir() -> Path:
    latest = Path("results/latest.txt")
    if not latest.exists():
        raise FileNotFoundError("results/latest.txt is missing; pass --run-dir or --trade-log")
    label = latest.read_text(encoding="utf-8").strip()
    if not label:
        raise ValueError("results/latest.txt is empty; pass --run-dir or --trade-log")
    return Path("results/runs") / label


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else _default_run_dir()
    trade_log = Path(args.trade_log) if args.trade_log else run_dir / "trades" / "trade_log.csv"
    out_dir = Path(args.out_dir) if args.out_dir else run_dir / "research" / "tbbo_execution"

    trades = read_trade_log(trade_log)
    minute_stats = read_tbbo_minute_stats(args.tbbo_minute)
    volatility_state = (
        pd.read_csv(args.volatility_state_csv, low_memory=False)
        if args.volatility_state_csv and Path(args.volatility_state_csv).exists()
        else None
    )
    audit = build_tbbo_trade_audit(
        trades,
        minute_stats,
        futures_specs=FUTURES_SPECS,
        volatility_state=volatility_state,
        nearest_tolerance=args.nearest_tolerance,
    )
    paths = write_tbbo_trade_audit(audit, out_dir)

    print(f"TBBO trade audit: {trade_log}")
    print(f"TBBO minute stats: {args.tbbo_minute}")
    if volatility_state is not None:
        print(f"Volatility state: {args.volatility_state_csv}")
    print(audit.summary.to_string(index=False))
    for key, path in paths.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
