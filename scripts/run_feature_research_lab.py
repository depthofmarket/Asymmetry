#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.engine import BacktestEngine
from backtest.feature_research import run_feature_research_lab
from backtest.portfolio import Portfolio
from config.backtest_config import BACKTEST_CONFIG, CANDIDATE_CONFIGS, FUTURES_SPECS, STRATEGY_PARAMS
from main_backtest import load_data, resolve_max_drawdown_pct


def _csv_ints(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the feature-first research lab.")
    parser.add_argument("--candidate", default="current", choices=sorted(CANDIDATE_CONFIGS))
    parser.add_argument("--data-path", default="data/raw/glbx-mdp3-20100606-20260428.ohlcv-1m.csv")
    parser.add_argument("--out-dir", default="results/research_master/feature_lab")
    parser.add_argument("--horizons", default="1,3,6,12,24", help="Comma-separated forward horizons in 5-min bars.")
    parser.add_argument("--target-atr", type=float, default=1.0)
    parser.add_argument("--stop-atr", type=float, default=1.0)
    parser.add_argument("--max-hold-bars", type=int, default=24)
    parser.add_argument("--bootstrap-samples", type=int, default=300)
    parser.add_argument("--min-events", type=int, default=30)
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

    out_dir = Path(args.out_dir) / args.candidate
    paths = run_feature_research_lab(
        pre_df,
        out_dir=out_dir,
        artifact_name="feature_research",
        horizons_bars=_csv_ints(args.horizons),
        target_atr_multiple=float(args.target_atr),
        stop_atr_multiple=float(args.stop_atr),
        max_hold_bars=int(args.max_hold_bars),
        bootstrap_samples=int(args.bootstrap_samples),
        min_events=int(args.min_events),
        random_seed=7,
    )
    print(f"Saved events:             {paths.events_csv}")
    print(f"Saved event summary:      {paths.event_summary_csv}")
    print(f"Saved barrier summary:    {paths.barrier_summary_csv}")
    print(f"Saved context summary:    {paths.context_summary_csv}")
    print(f"Saved feature leaderboard:{paths.feature_leaderboard_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
