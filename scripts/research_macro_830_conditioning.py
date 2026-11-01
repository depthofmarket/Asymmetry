#!/usr/bin/env python3
"""
Research Script: Track B - 8:30 AM Macro Driver Cross-Window Conditioning.
Evaluates whether 08:30 AM economic release shocks (CPI, PPI, NFP, Retail Sales, GDP)
cross-condition Strategy 1 (09:45 ET VA Breakout) and Strategy 2 (10:15 ET Gold Fix).
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def extract_830_metrics():
    print("Loading NQ 1m bars...")
    df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
    df_nq["date_str"] = df_nq["time"].dt.strftime("%Y-%m-%d")
    df_nq["hhmm"] = df_nq["time"].dt.strftime("%H:%M")
    
    # Filter 2020-2026
    df_nq = df_nq[df_nq["date_str"] >= "2020-01-01"].copy()
    
    # Compute 08:30 metrics per session
    print("Computing 08:30 AM spike metrics per day...")
    records = []
    for d_str, g in df_nq.groupby("date_str"):
        ovn = g[(g["hhmm"] >= "00:00") & (g["hhmm"] <= "08:29")]
        spike = g[(g["hhmm"] >= "08:30") & (g["hhmm"] <= "08:34")]
        pre_cash = g[(g["hhmm"] >= "08:35") & (g["hhmm"] <= "09:29")]
        
        if len(ovn) < 60 or len(spike) < 4:
            continue
            
        ovn_h = float(ovn["high"].max())
        ovn_l = float(ovn["low"].min())
        ovn_rng = ovn_h - ovn_l
        ovn_c_pre = float(ovn.iloc[-1]["close"])
        
        pre_vol = float(ovn["volume"].tail(30).mean()) * 5.0
        spike_vol = float(spike["volume"].sum())
        vol_ratio = spike_vol / pre_vol if pre_vol > 0 else 1.0
        
        spike_o = float(spike.iloc[0]["open"])
        spike_c = float(spike.iloc[-1]["close"])
        spike_h = float(spike["high"].max())
        spike_l = float(spike["low"].min())
        spike_rng = spike_h - spike_l
        spike_ret_pct = (spike_c - spike_o) / spike_o * 100.0
        
        # Is there a recognized 8:30 macro release?
        # Institutional criterion: volume >= 2.5x pre-roll volume OR spike range >= 50 pts
        is_macro_release = (vol_ratio >= 2.50) or (spike_rng >= 50.0)
        
        # 8:30 Directional classification
        spike_dir = 0
        if is_macro_release:
            if spike_c > ovn_c_pre and spike_ret_pct > 0.15:
                spike_dir = 1
            elif spike_c < ovn_c_pre and spike_ret_pct < -0.15:
                spike_dir = -1
                
        # What happened in the pre-cash digestive window (08:35-09:29)?
        pre_cash_c = float(pre_cash.iloc[-1]["close"]) if len(pre_cash) > 10 else spike_c
        pre_cash_drift = (pre_cash_c - spike_c) / spike_c * 100.0
        
        # Was the 8:30 shock faded before the open?
        # Faded = price moved back against the spike direction by > 50% of the spike range
        faded_spike = False
        if spike_dir == 1 and pre_cash_c < (spike_c - 0.50 * spike_rng):
            faded_spike = True
        elif spike_dir == -1 and pre_cash_c > (spike_c + 0.50 * spike_rng):
            faded_spike = True
            
        records.append({
            "date_str": d_str,
            "ovn_range": ovn_rng,
            "spike_vol_ratio": vol_ratio,
            "spike_rng": spike_rng,
            "spike_ret_pct": spike_ret_pct,
            "is_macro_release": is_macro_release,
            "spike_dir": spike_dir,
            "pre_cash_drift": pre_cash_drift,
            "faded_spike": faded_spike,
        })
        
    df_metrics = pd.DataFrame(records)
    print(f"Extracted {len(df_metrics)} trading days with 08:30 metrics.")
    print(f"Macro release days: {df_metrics['is_macro_release'].sum()} ({df_metrics['is_macro_release'].mean()*100:.1f}%)")
    return df_metrics

def main():
    df_830 = extract_830_metrics()
    
    # Load 543 standardized portfolio trades
    trades_p = ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"
    trades = pd.read_parquet(trades_p)
    print(f"Loaded {len(trades)} trades from {trades_p.name}.")
    
    # Merge 08:30 metrics
    m = trades.merge(df_830, on="date_str", how="left")
    print(f"Merged trades: {len(m)} trades with 08:30 metrics.\n")
    
    # 1. Strategy 1 (09:45 VA Breakout) conditioned on 08:30 Macro Driver
    s1 = m[m["strategy"].str.contains("Strategy 1")].copy()
    print("=" * 80)
    print("  STRATEGY 1 (09:45 ET VA BREAKOUT): 08:30 MACRO CONDITIONING")
    print("=" * 80)
    
    # A. Macro Release Day vs Quiet Day
    for is_rel in [True, False]:
        sub = s1[s1["is_macro_release"] == is_rel]
        pos = sub.loc[sub["pnl"] > 0, "pnl"].sum()
        neg = abs(sub.loc[sub["pnl"] <= 0, "pnl"].sum())
        pf = pos / neg if neg > 0 else 0
        wr = (sub["pnl"] > 0).mean() * 100
        lbl = "08:30 Macro Release Days" if is_rel else "Quiet Days (No 08:30 Release)"
        print(f"  {lbl:<32s}: {len(sub):>3} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net: ${sub['pnl'].sum():>8.2f} | Avg: ${sub['pnl'].mean():>6.2f}")
    print()
    
    # B. Alignment: Does 09:45 trade agree with 08:30 Macro Shock Direction?
    # trade direction: 'long' (1) or 'short' (-1)
    s1_rel = s1[s1["is_macro_release"] & (s1["spike_dir"] != 0)].copy()
    s1_rel["trade_dir_int"] = s1_rel["direction"].apply(lambda d: 1 if d == "long" else -1)
    s1_rel["aligned_with_830"] = s1_rel["trade_dir_int"] == s1_rel["spike_dir"]
    
    print("  ALIGNMENT ON 08:30 MACRO DAYS (When 8:30 Spike had clear direction):")
    for aligned in [True, False]:
        sub = s1_rel[s1_rel["aligned_with_830"] == aligned]
        pos = sub.loc[sub["pnl"] > 0, "pnl"].sum()
        neg = abs(sub.loc[sub["pnl"] <= 0, "pnl"].sum())
        pf = pos / neg if neg > 0 else 0
        wr = (sub["pnl"] > 0).mean() * 100
        lbl = "ALIGNED (09:45 agrees with 08:30)" if aligned else "OPPOSING (09:45 fights 08:30 macro)"
        print(f"    {lbl:<36s}: {len(sub):>3} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net: ${sub['pnl'].sum():>8.2f} | Avg: ${sub['pnl'].mean():>6.2f}")
    print()

    # C. Magnitude of 8:30 Spike: Extreme Exhaustion Shocks
    print("  MAGNITUDE OF 08:30 SPIKE (Exhaustion vs Normal):")
    # Extreme spike: spike range > 100 pts or return > 0.75%
    s1["extreme_830_spike"] = (s1["spike_rng"] >= 100.0) | (s1["spike_ret_pct"].abs() >= 0.75)
    for ext in [False, True]:
        sub = s1[s1["extreme_830_spike"] == ext]
        pos = sub.loc[sub["pnl"] > 0, "pnl"].sum()
        neg = abs(sub.loc[sub["pnl"] <= 0, "pnl"].sum())
        pf = pos / neg if neg > 0 else 0
        wr = (sub["pnl"] > 0).mean() * 100
        lbl = "Extreme 08:30 Shock (Exhaustion)" if ext else "Normal / Controlled 08:30 Action"
        print(f"    {lbl:<36s}: {len(sub):>3} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net: ${sub['pnl'].sum():>8.2f} | Avg: ${sub['pnl'].mean():>6.2f}")
    print()

    # 2. Strategy 2 (10:15 ET Gold Fix) conditioned on 08:30 Macro Driver
    s2 = m[m["strategy"].str.contains("Strategy 2")].copy()
    print("=" * 80)
    print("  STRATEGY 2 (10:15 ET GOLD FIX): 08:30 MACRO CONDITIONING")
    print("=" * 80)
    for is_rel in [True, False]:
        sub = s2[s2["is_macro_release"] == is_rel]
        pos = sub.loc[sub["pnl"] > 0, "pnl"].sum()
        neg = abs(sub.loc[sub["pnl"] <= 0, "pnl"].sum())
        pf = pos / neg if neg > 0 else 0
        wr = (sub["pnl"] > 0).mean() * 100
        lbl = "08:30 Macro Release Days" if is_rel else "Quiet Days (No 08:30 Release)"
        print(f"  {lbl:<32s}: {len(sub):>3} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net: ${sub['pnl'].sum():>8.2f} | Avg: ${sub['pnl'].mean():>6.2f}")
    print()

if __name__ == "__main__":
    main()
