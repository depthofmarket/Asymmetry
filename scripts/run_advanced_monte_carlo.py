#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.simulations import run_advanced_monte_carlo
from config.backtest_config import BACKTEST_CONFIG


def _latest_run_dir() -> Path:
    latest_path = Path("results/latest.txt")
    if not latest_path.exists():
        raise FileNotFoundError("results/latest.txt not found. Pass --run-dir or --trades-csv.")
    run_label = latest_path.read_text(encoding="utf-8").strip()
    if not run_label:
        raise ValueError("results/latest.txt is empty. Pass --run-dir or --trades-csv.")
    return Path("results/runs") / run_label


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run advanced Monte Carlo on an existing trade log.")
    parser.add_argument("--run-dir", default=None, help="Run folder containing trades/trade_log.csv. Defaults to results/latest.txt.")
    parser.add_argument("--trades-csv", default=None, help="Direct path to a trade log CSV.")
    parser.add_argument("--out-dir", default=None, help="Output folder. Defaults to <run-dir>/simulations or the trade CSV folder.")
    parser.add_argument("--starting-capital", type=float, default=float(BACKTEST_CONFIG["starting_capital"]))
    parser.add_argument("--n-sims", type=int, default=2000)
    parser.add_argument("--regime-col", default="entry_day_regime")
    parser.add_argument("--student-t-df", type=float, default=5.0)
    parser.add_argument("--transition-smoothing", type=float, default=1.0)
    parser.add_argument("--path-horizons", default="40,100,250,500,1000", help="Comma-separated trade-count horizons.")
    parser.add_argument("--drawdown-barriers", default="5,10,15,20,25", help="Comma-separated max drawdown probability thresholds in percent.")
    parser.add_argument("--profit-target-pct", type=float, default=8.0)
    parser.add_argument("--drawdown-limit-pct", type=float, default=5.0)
    parser.add_argument("--artifact-name", default="mc")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir: Path | None = Path(args.run_dir) if args.run_dir else None
    if args.trades_csv:
        trades_csv = Path(args.trades_csv)
    else:
        run_dir = run_dir or _latest_run_dir()
        trades_csv = run_dir / "trades" / "trade_log.csv"

    if not trades_csv.exists():
        raise FileNotFoundError(f"Trade log not found: {trades_csv}")

    if args.out_dir:
        out_dir = Path(args.out_dir)
    elif run_dir is not None:
        out_dir = run_dir / "simulations"
    else:
        out_dir = trades_csv.parent / "simulations"

    trades = pd.read_csv(trades_csv)
    summary = run_advanced_monte_carlo(
        {"trades": trades},
        starting_capital=float(args.starting_capital),
        artifact_name=str(args.artifact_name),
        n_sims=int(args.n_sims),
        seed=11,
        out_dir=out_dir,
        regime_col=str(args.regime_col),
        transition_smoothing=float(args.transition_smoothing),
        student_t_df=float(args.student_t_df),
        path_horizons=tuple(int(item.strip()) for item in str(args.path_horizons).split(",") if item.strip()),
        drawdown_barriers_pct=tuple(float(item.strip()) for item in str(args.drawdown_barriers).split(",") if item.strip()),
        profit_target_pct=float(args.profit_target_pct),
        drawdown_limit_pct=float(args.drawdown_limit_pct),
    )
    print(f"Saved summary:       {summary.summary_csv}")
    print(f"Saved distributions: {summary.distributions_csv}")
    print(f"Saved path risk:     {summary.path_risk_csv}")
    if summary.transition_matrix_csv is not None:
        print(f"Saved transition:    {summary.transition_matrix_csv}")
    for method, path in summary.path_pngs.items():
        print(f"Saved {method} paths: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
