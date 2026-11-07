#!/usr/bin/env python3
"""
Research Script: Point-in-Time Markov Volatility Regimes on the 543-Trade Ensemble (Track C).
Evaluates whether Hidden Markov Model (HMM) states (low_vol, mid_vol, high_vol) condition
trade expectancy, win rate, and profit factor across Strategy 1, Strategy 2, and Strategy 3.
"""

from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.markov_regime import add_markov_regime_features, GaussianMarkovRegimeModel

# 1. Load active 543-trade Candidate A ensemble
trades_path = ROOT / "data/processed/unified_three_strategy_garch_portfolio_trades_2021_2026.parquet"
df_trades = pd.read_parquet(trades_path)
df_trades["entry_time"] = pd.to_datetime(df_trades["entry_time"])
df_trades["date_str"] = df_trades["entry_time"].dt.strftime("%Y-%m-%d")

print(f"Loaded {len(df_trades)} ensemble trades across {df_trades['date_str'].nunique()} trading days.\n")

# 2. Build Daily Session Bars for NQ (2017-2026) for Macro Daily Markov Regime
df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
df_nq["date_str"] = df_nq["time"].dt.strftime("%Y-%m-%d")

daily_nq = df_nq.groupby("date_str").agg(
    open=("open", "first"),
    high=("high", "max"),
    low=("low", "min"),
    close=("close", "last"),
    volume=("volume", "sum")
).reset_index()

# 3. Compute Point-in-Time Daily Markov Regime (e.g. 60-day calibration, refit every 5 days)
print("Computing Daily Markov Regime on NQ (Point-in-Time)...")
daily_markov = add_markov_regime_features(
    daily_nq,
    n_states=3,
    calibration_bars=60,
    min_calibration_bars=30,
    refit_every_bars=5,
    volatility_method="range_close"
)

# Merge daily regime with trades
# To ensure strictly zero lookahead: trade on date d sees Markov state from completed session d-1
daily_markov["prior_date_str"] = daily_markov["date_str"]
daily_markov["trade_date_str"] = daily_markov["date_str"].shift(-1) # state on date d applies to session d+1

regime_lookup = daily_markov.set_index("trade_date_str")[["markov_state", "markov_state_label", "markov_state_confidence", "markov_prob_low_vol", "markov_prob_mid_vol", "markov_prob_high_vol"]]

df_trades = df_trades.merge(regime_lookup, left_on="date_str", right_index=True, how="left")

print("Merged daily Markov regime with trades.")
print("Trades with valid Markov regime:", df_trades["markov_state_label"].notna().sum(), "out of", len(df_trades))

# 4. Overall Ensemble Performance by Daily Markov Regime
def print_regime_summary(df: pd.DataFrame, title: str):
    print("=" * 75)
    print(f"  {title}")
    print("=" * 75)
    
    summary = df.groupby("markov_state_label", observed=False).agg(
        trades=("net_dollars_micro", "count"),
        wr=("net_dollars_micro", lambda x: (x > 0).mean() * 100),
        net_pnl=("net_dollars_micro", "sum"),
        avg_trade=("net_dollars_micro", "mean"),
        pos_pnl=("net_dollars_micro", lambda x: x[x > 0].sum()),
        neg_pnl=("net_dollars_micro", lambda x: abs(x[x <= 0].sum())),
    )
    summary["pf"] = summary["pos_pnl"] / summary["neg_pnl"]
    print(summary[["trades", "wr", "pf", "net_pnl", "avg_trade"]].round(2).to_string())
    print()

print_regime_summary(df_trades, "UNIFIED 3-WINDOW ENSEMBLE BY DAILY MARKOV REGIME (NQ)")

# 5. Breakdown by Strategy
for strat in ["Strategy 1", "Strategy 2", "Strategy 3"]:
    sub = df_trades[df_trades["strategy"].str.contains(strat)].copy()
    print_regime_summary(sub, f"{strat.upper()} BY DAILY MARKOV REGIME")

# 6. Check Intraday Markov Regime (computed directly on 15m or 1m bars prior to trade)
print("Evaluating Intraday Pre-Trade Markov Volatility State...")
