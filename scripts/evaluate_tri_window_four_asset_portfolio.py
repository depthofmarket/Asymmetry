#!/usr/bin/env python3
"""
Evaluate Unified Multi-Strategy Ensemble:
- Window 1 (08:35 - 09:25 ET): Strategy 3 (MNQ Macro Release Momentum)
- Window 2 (09:45 - 10:30 ET): Strategy 1 (MNQ + MES Morning Value Area Breakout)
- Window 3 (10:15 - 11:00 ET): Strategy 2 (MGC Gold LBMA PM Fix Breakout H14)

All evaluated under LucidFlex 25K prop constraints:
$250 risk cap, AMP CQG commissions, realistic slippage.
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# 1. Load Strategy 1 & 2 baseline trades
p_base = ROOT / "data/processed/tri_asset_portfolio_trades_2021_2026.parquet"
df_base = pd.read_parquet(p_base)

# 2. Compute Strategy 3 (MNQ Macro 08:35 ET)
df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
df_nq["date_str"] = df_nq["time"].dt.strftime("%Y-%m-%d")
df_nq["hhmm"] = df_nq["time"].dt.strftime("%H:%M")
bars_by_date = {d: g.reset_index(drop=True) for d, g in df_nq.groupby("date_str")}

macro_trades = []
for d_str, g in bars_by_date.items():
    if d_str < "2021-01-01":
        continue
    ovn = g[(g["hhmm"] >= "00:00") & (g["hhmm"] <= "08:29")]
    if len(ovn) < 180:
        continue
    ovn_high = float(ovn["high"].max())
    ovn_low = float(ovn["low"].min())
    if ovn_high <= ovn_low:
        continue
    spike = g[(g["hhmm"] >= "08:30") & (g["hhmm"] <= "08:34")]
    if len(spike) < 4:
        continue
    spike_vol = float(spike["volume"].sum())
    pre_vol_5m = float(ovn["volume"].tail(30).mean()) * 5.0
    if spike_vol < pre_vol_5m * 2.5:
        continue
    spike_c = float(spike.iloc[-1]["close"])
    spike_h = float(spike["high"].max())
    spike_l = float(spike["low"].min())
    spike_rng = spike_h - spike_l
    spike_cl_loc = (spike_c - spike_l) / spike_rng if spike_rng > 0 else 0.5
    
    entry_bars = g[g["hhmm"] == "08:35"]
    if entry_bars.empty:
        continue
    eb = entry_bars.iloc[0]
    
    d = 0
    if spike_c > ovn_high and spike_cl_loc >= 0.65:
        d = 1
    elif spike_c < ovn_low and spike_cl_loc <= 0.35:
        d = -1
    if d == 0:
        continue
        
    exec_bars = g[g["time"] >= eb["time"]].reset_index(drop=True)
    if len(exec_bars) < 20:
        continue
        
    entry_p = float(exec_bars.iloc[0]["open"])
    stop_pts = float(np.clip(spike_rng * 0.50, 20.0, 50.0))
    target_pts = stop_pts * 1.50
    stop_p = entry_p - d * stop_pts
    target_p = entry_p + d * target_pts
    
    exit_p = float(exec_bars.iloc[min(45, len(exec_bars) - 1)]["close"])
    exit_time = pd.Timestamp(exec_bars.iloc[min(45, len(exec_bars) - 1)]["time"])
    reason = "time_exit_0925"
    
    for _, rb in exec_bars.iterrows():
        if rb["hhmm"] >= "09:25":
            exit_p = float(rb["close"])
            exit_time = pd.Timestamp(rb["time"])
            break
        rb_h, rb_l = float(rb["high"]), float(rb["low"])
        if d == 1 and rb_l <= stop_p:
            exit_p = stop_p
            exit_time = pd.Timestamp(rb["time"])
            reason = "stop_loss"
            break
        elif d == -1 and rb_h >= stop_p:
            exit_p = stop_p
            exit_time = pd.Timestamp(rb["time"])
            reason = "stop_loss"
            break
        if d == 1 and rb_h >= target_p:
            exit_p = target_p
            exit_time = pd.Timestamp(rb["time"])
            reason = "profit_target"
            break
        elif d == -1 and rb_l <= target_p:
            exit_p = target_p
            exit_time = pd.Timestamp(rb["time"])
            reason = "profit_target"
            break
            
    raw_pts = (exit_p - entry_p) * d
    net_pts = raw_pts - 1.0
    contracts = int(np.clip(np.round(250.0 / max(stop_pts * 2.0, 1.0)), 1, 4))
    comm = 1.24 * contracts
    net_dollars = net_pts * 2.0 * contracts - comm
    
    macro_trades.append({
        "date_str": d_str,
        "year": int(d_str[:4]),
        "sym": "NQ",
        "micro": "MNQ",
        "window": 3,
        "strategy": "Strategy 3: Macro Release Momentum (08:35 ET)",
        "entry_time": pd.Timestamp(eb["time"]),
        "exit_time": exit_time,
        "direction": "long" if d == 1 else "short",
        "contracts": contracts,
        "net_dollars_micro": net_dollars,
        "scaled_pnl": net_dollars,
        "pnl": net_dollars
    })

df_macro = pd.DataFrame(macro_trades)

# Standardize df_base columns
common_cols = ["date_str", "year", "sym", "micro", "window", "strategy", "entry_time", "exit_time", "direction", "contracts", "net_dollars_micro", "scaled_pnl", "pnl"]
df_comb = pd.concat([df_base[common_cols], df_macro[common_cols]], ignore_index=True)
df_comb["entry_time"] = pd.to_datetime(df_comb["entry_time"])
df_comb = df_comb.sort_values("entry_time").reset_index(drop=True)

print("=" * 65)
print("  UNIFIED 3-WINDOW MULTI-STRATEGY ENSEMBLE (2021-2026)")
print("=" * 65)
print(f"Total Portfolio Trades: {len(df_comb)} trades across {df_comb['date_str'].nunique()} trading days")
print(f"Overall Frequency: {len(df_comb)/5.8:.1f} trades/year (~{len(df_comb)/70:.1f} trades/month, ~{len(df_comb)/(5.8*52):.1f} trades/week)\n")

# Breakdown by strategy
strat_summary = df_comb.groupby("strategy").agg(
    trades=("net_dollars_micro", "count"),
    wr=("net_dollars_micro", lambda x: (x > 0).mean() * 100),
    net_pnl=("net_dollars_micro", "sum"),
    pos_pnl=("net_dollars_micro", lambda x: x[x > 0].sum()),
    neg_pnl=("net_dollars_micro", lambda x: abs(x[x <= 0].sum())),
)
strat_summary["pf"] = strat_summary["pos_pnl"] / strat_summary["neg_pnl"]
for s_name, row in strat_summary.iterrows():
    print(f"  {s_name:<45}: {int(row['trades']):>3} trades | WR: {row['wr']:>5.1f}% | PF: {row['pf']:>4.2f} | Net: ${row['net_pnl']:>9,.2f}")

# Unified Cumulative Equity & Drawdown
df_comb["cum_pnl"] = df_comb["net_dollars_micro"].cumsum()
peak = df_comb["cum_pnl"].cummax()
df_comb["dd"] = peak - df_comb["cum_pnl"]
max_dd = df_comb["dd"].max()
total_profit = df_comb["net_dollars_micro"].sum()
total_wr = (df_comb["net_dollars_micro"] > 0).mean() * 100
pos_tot = df_comb.loc[df_comb["net_dollars_micro"] > 0, "net_dollars_micro"].sum()
neg_tot = abs(df_comb.loc[df_comb["net_dollars_micro"] <= 0, "net_dollars_micro"].sum())
tot_pf = pos_tot / neg_tot

print("-" * 65)
print(f"  UNIFIED ENSEMBLE TOTAL : {len(df_comb)} trades | WR: {total_wr:.1f}% | PF: {tot_pf:.2f} | Net: ${total_profit:,.2f}")
print(f"  MAX CLOSED DRAWDOWN    : ${max_dd:,.2f}")
print(f"  PROFIT-TO-MAX-DD RATIO : {total_profit / max_dd:.2f}x")
print("=" * 65)

# Save combined trades dataset for dashboard integration
out_p = ROOT / "data/processed/unified_three_strategy_portfolio_trades_2021_2026.parquet"
df_comb.to_parquet(out_p, index=False)
print(f"Exported combined 546-trade portfolio dataset to {out_p}")
