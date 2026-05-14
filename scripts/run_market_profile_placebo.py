#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.engine import BacktestEngine
from backtest.placebo import run_market_profile_placebo_test
from backtest.portfolio import Portfolio
from config.backtest_config import BACKTEST_CONFIG, CANDIDATE_CONFIGS, FUTURES_SPECS, STRATEGY_PARAMS
from main_backtest import load_data, resolve_max_drawdown_pct


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run market-profile placebo validation.")
    parser.add_argument("--candidate", default="market_profile_cross_signal_probe", choices=sorted(CANDIDATE_CONFIGS))
    parser.add_argument("--data-path", default="data/raw/glbx-mdp3-20100606-20260428.ohlcv-1m.csv")
    parser.add_argument("--n-placebos", type=int, default=25)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--min-offset-points", type=float, default=4.0)
    parser.add_argument("--max-offset-points", type=float, default=40.0)
    parser.add_argument("--out-dir", default="results/research_master/placebo")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-placebo progress messages.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG, **CANDIDATE_CONFIGS[args.candidate], "_candidate_name": args.candidate}
    data = load_data(args.data_path)
    portfolio = Portfolio(
        BACKTEST_CONFIG["starting_capital"],
        FUTURES_SPECS,
        max_drawdown_pct=resolve_max_drawdown_pct(params),
    )
    engine = BacktestEngine(data, portfolio, FUTURES_SPECS, params)
    print("Preprocessing once...", flush=True)
    pre_df = engine.preprocess()
    print(f"Running {args.n_placebos} placebo simulations for {args.candidate}...", flush=True)
    result = run_market_profile_placebo_test(
        pre_df=pre_df,
        raw_data=data,
        futures_specs=FUTURES_SPECS,
        params=params,
        starting_capital=BACKTEST_CONFIG["starting_capital"],
        out_dir=Path(args.out_dir) / args.candidate,
        artifact_name=args.candidate,
        n_placebos=args.n_placebos,
        seed=args.seed,
        min_offset_points=args.min_offset_points,
        max_offset_points=args.max_offset_points,
        verbose=not args.quiet,
    )
    print(f"Saved: {result.summary_csv}")
    print(f"Actual total P&L: ${result.actual_total_pnl:,.2f}")
    print(f"Actual PF:        {result.actual_profit_factor:.3f}")
    print(f"Placebo PnL p:    {result.placebo_total_pnl_p_value:.4f}")
    print(f"Placebo PF p:     {result.placebo_profit_factor_p_value:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
