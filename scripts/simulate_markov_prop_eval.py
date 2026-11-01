#!/usr/bin/env python3
"""Run Monte Carlo Prop Firm Simulation on Markov-Conditioned Portfolios."""

from __future__ import annotations
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from backtest.markov_regime import add_markov_regime_features

from backtest.demo_parity_engine import (
    STARTING_CAPITAL,
    PROFIT_TARGET_DOLLARS,
    MAX_TRAILING_DRAWDOWN,
    DAILY_SOFT_STOP_DOLLARS,
    TRAILING_FLOOR_LOCK,
    PEAK_FOR_FLOOR_LOCK,
)

# Load active 543-trade Candidate A ensemble
trades_path = ROOT / "data/processed/unified_three_strategy_garch_portfolio_trades_2021_2026.parquet"
df_trades = pd.read_parquet(trades_path)
df_trades["entry_time"] = pd.to_datetime(df_trades["entry_time"])
df_trades["date_str"] = df_trades["entry_time"].dt.strftime("%Y-%m-%d")

# Daily NQ Markov Regime
df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
df_nq["date_str"] = df_nq["time"].dt.strftime("%Y-%m-%d")
daily_nq = df_nq.groupby("date_str").agg(
    open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")
).reset_index()

daily_markov = add_markov_regime_features(
    daily_nq, n_states=3, calibration_bars=60, min_calibration_bars=30, refit_every_bars=5
)
daily_markov["trade_date_str"] = daily_markov["date_str"].shift(-1)
df_trades = df_trades.merge(daily_markov.set_index("trade_date_str")[["markov_state_label"]], left_on="date_str", right_index=True, how="left")

# Option 1: Gate Strategy 3 in High-Vol
opt1_trades = df_trades[~((df_trades["strategy"].str.contains("Strategy 3")) & (df_trades["markov_state_label"] == "high_vol"))].copy()

# Option 2: Adaptive Sizing
opt2_trades = df_trades.copy()
mult = np.ones(len(opt2_trades))
is_s3 = opt2_trades["strategy"].str.contains("Strategy 3")
is_high = opt2_trades["markov_state_label"] == "high_vol"
is_low = opt2_trades["markov_state_label"] == "low_vol"
mult = np.where(is_low, 1.25, mult)
mult = np.where(is_high & is_s3, 0.50, mult)
opt2_trades["net_dollars_micro"] = opt2_trades["net_dollars_micro"] * mult

def run_mc(name: str, trades_df: pd.DataFrame, n_sims: int = 10_000, block_size: int = 5, seed: int = 42):
    daily = trades_df.groupby("date_str").agg(
        pnl=("net_dollars_micro", "sum"),
        trades=("net_dollars_micro", "count")
    ).reset_index()
    
    daily_pnls = daily["pnl"].to_numpy()
    daily_trades = daily["trades"].to_numpy()
    n_days = len(daily_pnls)
    
    rng = np.random.default_rng(seed)
    passes = 0
    fails = 0
    pass_days = []
    fail_days = []
    pass_trades = []
    fail_trades = []
    
    for _ in range(n_sims):
        bal = STARTING_CAPITAL
        peak = STARTING_CAPITAL
        flr = STARTING_CAPITAL - MAX_TRAILING_DRAWDOWN
        
        days_count = 0
        trades_count = 0
        
        while True:
            start_idx = rng.integers(0, n_days - block_size + 1)
            b_pnls = daily_pnls[start_idx : start_idx + block_size]
            b_trades = daily_trades[start_idx : start_idx + block_size]
            
            terminal = False
            for dp, dt in zip(b_pnls, b_trades):
                days_count += 1
                trades_count += dt
                actual_dp = max(dp, DAILY_SOFT_STOP_DOLLARS)
                bal += actual_dp
                
                if bal > peak:
                    peak = bal
                    if peak >= PEAK_FOR_FLOOR_LOCK:
                        flr = max(flr, TRAILING_FLOOR_LOCK)
                    else:
                        flr = max(flr, peak - MAX_TRAILING_DRAWDOWN)
                        
                if bal <= flr:
                    fails += 1
                    fail_days.append(days_count)
                    fail_trades.append(trades_count)
                    terminal = True
                    break
                    
                if (bal - STARTING_CAPITAL) >= PROFIT_TARGET_DOLLARS:
                    passes += 1
                    pass_days.append(days_count)
                    pass_trades.append(trades_count)
                    terminal = True
                    break
                    
            if terminal:
                break
                
    p_rate = passes / n_sims * 100
    f_rate = fails / n_sims * 100
    ev = (passes / n_sims) * PROFIT_TARGET_DOLLARS - (fails / n_sims) * 150.0
    
    print(f"=== {name} ===")
    print(f"  Pass Rate:         {p_rate:>5.2f}%")
    print(f"  Fail Rate:         {f_rate:>5.2f}%")
    print(f"  Median Pass Time:  {np.median(pass_days):>4.1f} days ({np.median(pass_trades):>4.1f} trades)")
    print(f"  Mean Pass Time:    {np.mean(pass_days):>4.1f} days ({np.mean(pass_trades):>4.1f} trades)")
    print(f"  Median Fail Time:  {np.median(fail_days):>4.1f} days ({np.median(fail_trades):>4.1f} trades)")
    print(f"  Est EV / Attempt:  ${ev:>7.2f}\n")

print("=" * 65)
print("  MONTE CARLO (10,000 PATHS): LUCIDFLEX 25K PROP EVALUATION")
print("=" * 65 + "\n")

run_mc("1. Baseline Ensemble (543 Trades)", df_trades)
run_mc("2. Option 1: S3 High-Vol Gate (501 Trades)", opt1_trades)
run_mc("3. Option 2: Markov Adaptive Sizing (543 Trades)", opt2_trades)
