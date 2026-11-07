#!/usr/bin/env python3
"""
Evaluate Markov Volatility Regime Adaptive Sizing & Filtering on 543-Trade Ensemble.
Tests:
1. Baseline (Unconditioned 543 trades)
2. Option 1: Strategy 3 High-Vol Gate (Suppress S3 on high_vol days)
3. Option 2: Regime-Adaptive Sizing (Low-vol 1.25x, Mid-vol 1.0x, High-vol 0.5x for S3)
4. Multi-Era Holdout Validation (2021-2024 Dev vs 2025-2026 OOS)
5. Monte Carlo LucidFlex 25K Prop Evaluation
"""

from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.markov_regime import add_markov_regime_features

# 1. Load active 543-trade Candidate A ensemble
trades_path = ROOT / "data/processed/unified_three_strategy_garch_portfolio_trades_2021_2026.parquet"
df_trades = pd.read_parquet(trades_path)
df_trades["entry_time"] = pd.to_datetime(df_trades["entry_time"])
df_trades["date_str"] = df_trades["entry_time"].dt.strftime("%Y-%m-%d")

# 2. Daily NQ Markov Regime
df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
df_nq["date_str"] = df_nq["time"].dt.strftime("%Y-%m-%d")

daily_nq = df_nq.groupby("date_str").agg(
    open=("open", "first"),
    high=("high", "max"),
    low=("low", "min"),
    close=("close", "last"),
    volume=("volume", "sum")
).reset_index()

daily_markov = add_markov_regime_features(
    daily_nq,
    n_states=3,
    calibration_bars=60,
    min_calibration_bars=30,
    refit_every_bars=5,
    volatility_method="range_close"
)

# Strictly point-in-time: trade on date d uses regime from completed session d-1
daily_markov["trade_date_str"] = daily_markov["date_str"].shift(-1)
regime_cols = ["markov_state_label", "markov_prob_low_vol", "markov_prob_mid_vol", "markov_prob_high_vol"]
df_trades = df_trades.merge(daily_markov.set_index("trade_date_str")[regime_cols], left_on="date_str", right_index=True, how="left")

def calc_portfolio_stats(name: str, df: pd.DataFrame):
    df_sorted = df.sort_values("entry_time").reset_index(drop=True).copy()
    df_sorted["cum"] = df_sorted["net_dollars_micro"].cumsum()
    peak = df_sorted["cum"].cummax()
    df_sorted["dd"] = peak - df_sorted["cum"]
    max_dd = df_sorted["dd"].max()
    tot_pnl = df_sorted["net_dollars_micro"].sum()
    pos = df_sorted.loc[df_sorted["net_dollars_micro"] > 0, "net_dollars_micro"].sum()
    neg = abs(df_sorted.loc[df_sorted["net_dollars_micro"] <= 0, "net_dollars_micro"].sum())
    pf = pos / neg if neg > 0 else np.nan
    wr = (df_sorted["net_dollars_micro"] > 0).mean() * 100
    
    # Dev vs OOS
    dev = df_sorted[df_sorted["year"] <= 2024]
    dev_pos = dev.loc[dev["net_dollars_micro"] > 0, "net_dollars_micro"].sum()
    dev_neg = abs(dev.loc[dev["net_dollars_micro"] <= 0, "net_dollars_micro"].sum())
    dev_pf = dev_pos / dev_neg if dev_neg > 0 else np.nan
    dev_net = dev["net_dollars_micro"].sum()
    dev_wr = (dev["net_dollars_micro"] > 0).mean() * 100
    
    oos = df_sorted[df_sorted["year"] >= 2025]
    oos_pos = oos.loc[oos["net_dollars_micro"] > 0, "net_dollars_micro"].sum()
    oos_neg = abs(oos.loc[oos["net_dollars_micro"] <= 0, "net_dollars_micro"].sum())
    oos_pf = oos_pos / oos_neg if oos_neg > 0 else np.nan
    oos_net = oos["net_dollars_micro"].sum()
    oos_wr = (oos["net_dollars_micro"] > 0).mean() * 100
    
    print(f"=== {name} ===")
    print(f"  FULL (2021-2026): {len(df_sorted):>3} trades | WR: {wr:>5.2f}% | PF: {pf:>4.2f} | Net: ${tot_pnl:>9,.2f} | MaxDD: ${max_dd:>7,.2f} | Ret/DD: {tot_pnl/max_dd:>4.2f}x")
    print(f"  DEV  (2021-2024): {len(dev):>3} trades | WR: {dev_wr:>5.2f}% | PF: {dev_pf:>4.2f} | Net: ${dev_net:>9,.2f}")
    print(f"  OOS  (2025-2026): {len(oos):>3} trades | WR: {oos_wr:>5.2f}% | PF: {oos_pf:>4.2f} | Net: ${oos_net:>9,.2f}\n")

print("\n" + "=" * 80)
print("  EMPIRICAL EVALUATION: MARKOV REGIME ADAPTATIONS ON THE 3-WINDOW ENSEMBLE")
print("=" * 80 + "\n")

calc_portfolio_stats("1. Active Baseline Ensemble (No Markov Filter)", df_trades)

# Option 1: Strategy 3 High-Vol Gate (Suppress S3 on high_vol days)
opt1_df = df_trades[~((df_trades["strategy"].str.contains("Strategy 3")) & (df_trades["markov_state_label"] == "high_vol"))].copy()
calc_portfolio_stats("2. Option 1: Gate Strategy 3 in High-Vol Regime (Drop S3 when High-Vol)", opt1_df)

# Option 2: Adaptive Sizing Multiplier
# In low_vol: 1.25x across board
# In mid_vol: 1.00x baseline
# In high_vol: 0.50x for S3 (reduce risk in whipsaws), 1.00x for S1/S2
opt2_df = df_trades.copy()
mult = np.ones(len(opt2_df))
is_s3 = opt2_df["strategy"].str.contains("Strategy 3")
is_high = opt2_df["markov_state_label"] == "high_vol"
is_low = opt2_df["markov_state_label"] == "low_vol"

mult = np.where(is_low, 1.25, mult)
mult = np.where(is_high & is_s3, 0.50, mult)
opt2_df["net_dollars_micro"] = opt2_df["net_dollars_micro"] * mult
calc_portfolio_stats("3. Option 2: Markov Adaptive Sizing (1.25x Low-Vol, 0.5x High-Vol S3)", opt2_df)

# Option 3: High-Vol Filter on Both S2 & S3 (Gold & Macro Gate)
opt3_df = df_trades[~((df_trades["strategy"].str.contains("Strategy 3|Strategy 2")) & (df_trades["markov_state_label"] == "high_vol"))].copy()
calc_portfolio_stats("4. Option 3: Gate S2 & S3 in High-Vol (Only Strategy 1 Active in High-Vol)", opt3_df)
