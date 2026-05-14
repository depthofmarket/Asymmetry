#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.engine import BacktestEngine
from backtest.event_sampling import export_cusum_event_study
from backtest.portfolio import Portfolio
from config.backtest_config import BACKTEST_CONFIG, CANDIDATE_CONFIGS, FUTURES_SPECS, STRATEGY_PARAMS
from main_backtest import load_data, resolve_max_drawdown_pct


def _csv_floats(value: str) -> tuple[float, ...]:
    return tuple(float(item.strip()) for item in value.split(",") if item.strip())


def _csv_ints(value: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export CUSUM/ATR candle-sampling event study.")
    parser.add_argument("--candidate", default="current", choices=sorted(CANDIDATE_CONFIGS))
    parser.add_argument("--data-path", default="data/raw/glbx-mdp3-20100606-20260428.ohlcv-1m.csv")
    parser.add_argument("--out-dir", default="results/research_master/events")
    parser.add_argument("--threshold", type=float, default=None, help="CUSUM threshold as ATR multiple.")
    parser.add_argument("--min-threshold-points", type=float, default=None)
    parser.add_argument("--horizons", default="1,3,6,12,24", help="Comma-separated forward horizons in 5-min bars.")
    parser.add_argument("--frequency-thresholds", default="0.5,0.75,1.0,1.25,1.5,2.0,3.0")
    parser.add_argument("--random-baseline-samples", type=int, default=200)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG, **CANDIDATE_CONFIGS[args.candidate], "_candidate_name": args.candidate}
    if args.threshold is not None:
        params["cusum_event_atr_multiple"] = args.threshold
    if args.min_threshold_points is not None:
        params["cusum_event_min_threshold_points"] = args.min_threshold_points

    data = load_data(args.data_path)
    portfolio = Portfolio(
        BACKTEST_CONFIG["starting_capital"],
        FUTURES_SPECS,
        max_drawdown_pct=resolve_max_drawdown_pct(params),
    )
    engine = BacktestEngine(data, portfolio, FUTURES_SPECS, params)
    print("Preprocessing once...", flush=True)
    pre_df = engine.preprocess()

    threshold = float(params.get("cusum_event_atr_multiple", 1.0))
    out_dir = Path(args.out_dir) / args.candidate / f"threshold_{str(threshold).replace('.', '_')}"
    paths = export_cusum_event_study(
        pre_df,
        out_dir=out_dir,
        artifact_name="cusum_events",
        horizons_bars=_csv_ints(args.horizons),
        threshold_atr_multiple=threshold,
        min_threshold_points=float(params.get("cusum_event_min_threshold_points", 0.25)),
        frequency_thresholds=_csv_floats(args.frequency_thresholds),
        random_baseline_samples=int(args.random_baseline_samples),
        random_seed=7,
    )
    print(f"Saved events:          {paths.events_csv}")
    print(f"Saved summary:         {paths.summary_csv}")
    print(f"Saved frequency sweep: {paths.frequency_sweep_csv}")
    print(f"Saved random baseline: {paths.random_baseline_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
