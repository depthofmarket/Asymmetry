#!/usr/bin/env python3
"""
Deep-Dive Analysis of Candidate H17:
Pre-Market Macro Release Momentum (08:35 ET) on MNQ (2021-2026).
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def analyze_nq_macro():
    df = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["time"].dt.strftime("%H:%M")
    
    bars_by_date = {d: g.reset_index(drop=True) for d, g in df.groupby("date_str")}
    trades = []
    
    for d_str, g in bars_by_date.items():
        if d_str < "2021-01-01":
            continue
            
        ovn = g[(g["hhmm"] >= "00:00") & (g["hhmm"] <= "08:29")]
        if len(ovn) < 180:
            continue
        ovn_high = float(ovn["high"].max())
        ovn_low = float(ovn["low"].min())
        ovn_range = ovn_high - ovn_low
        if ovn_range <= 0:
            continue
            
        spike = g[(g["hhmm"] >= "08:30") & (g["hhmm"] <= "08:34")]
        if len(spike) < 4:
            continue
            
        spike_vol = float(spike["volume"].sum())
        pre_vol_5m = float(ovn["volume"].tail(30).mean()) * 5.0
        
        # High impact macro volume spike
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
        
        # Long and Short signals
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
                reason = "time_exit_0925"
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
        net_pts = raw_pts - 1.0 # 1 pt slippage
        contracts = int(np.clip(np.round(250.0 / max(stop_pts * 2.0, 1.0)), 1, 4))
        comm = 1.24 * contracts
        net_dollars = net_pts * 2.0 * contracts - comm
        
        trades.append({
            "date_str": d_str,
            "year": int(d_str[:4]),
            "direction": "long" if d == 1 else "short",
            "entry_time": pd.Timestamp(eb["time"]),
            "exit_time": exit_time,
            "stop_pts": stop_pts,
            "target_pts": target_pts,
            "contracts": contracts,
            "net_dollars": net_dollars,
            "reason": reason
        })
        
    tdf = pd.DataFrame(trades)
    print("=" * 60)
    print("  MNQ 08:35 ET PRE-MARKET MACRO DETAILED BREAKDOWN")
    print("=" * 60)
    
    # Year-by-year breakdown
    print("\nYear-by-Year Performance (Both Sides):")
    for yr, ydf in tdf.groupby("year"):
        wr = (ydf["net_dollars"] > 0).mean() * 100
        pnl = ydf["net_dollars"].sum()
        pos = ydf.loc[ydf["net_dollars"] > 0, "net_dollars"].sum()
        neg = abs(ydf.loc[ydf["net_dollars"] <= 0, "net_dollars"].sum())
        pf = pos / neg if neg > 0 else np.nan
        print(f"  {yr}: {len(ydf):>3} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net: ${pnl:>8,.2f}")
        
    # Short-Only Year-by-Year breakdown
    short_df = tdf[tdf["direction"] == "short"]
    print("\nYear-by-Year Performance (Short-Only Macro Panics):")
    for yr, ydf in short_df.groupby("year"):
        wr = (ydf["net_dollars"] > 0).mean() * 100
        pnl = ydf["net_dollars"].sum()
        pos = ydf.loc[ydf["net_dollars"] > 0, "net_dollars"].sum()
        neg = abs(ydf.loc[ydf["net_dollars"] <= 0, "net_dollars"].sum())
        pf = pos / neg if neg > 0 else np.nan
        print(f"  {yr}: {len(ydf):>3} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net: ${pnl:>8,.2f}")
        
    # Check overlap with Strategy 1
    strat1_df = pd.read_parquet(ROOT / "data/processed/tri_asset_portfolio_trades_2021_2026.parquet")
    s1_dates = set(strat1_df[strat1_df["strategy"].str.contains("Strategy 1")]["date_str"])
    
    same_day_s1 = tdf[tdf["date_str"].isin(s1_dates)]
    diff_day_s1 = tdf[~tdf["date_str"].isin(s1_dates)]
    
    print(f"\nOverlap Analysis with Strategy 1 (09:45 ET):")
    print(f"  Total Macro Trades: {len(tdf)}")
    print(f"  Trades on days Strategy 1 ALSO traded: {len(same_day_s1)} ({len(same_day_s1)/len(tdf)*100:.1f}%)")
    print(f"  Trades on days Strategy 1 was FLAT:     {len(diff_day_s1)} ({len(diff_day_s1)/len(tdf)*100:.1f}%) -> PURE NEW FREQUENCY!")
    
    # Performance on flat days
    wr_diff = (diff_day_s1["net_dollars"] > 0).mean() * 100
    pos_diff = diff_day_s1.loc[diff_day_s1["net_dollars"] > 0, "net_dollars"].sum()
    neg_diff = abs(diff_day_s1.loc[diff_day_s1["net_dollars"] <= 0, "net_dollars"].sum())
    pf_diff = pos_diff / neg_diff if neg_diff > 0 else np.nan
    pnl_diff = diff_day_s1["net_dollars"].sum()
    print(f"  Performance on Strategy 1 Flat Days: {len(diff_day_s1)} trades | WR: {wr_diff:.1f}% | PF: {pf_diff:.2f} | Net: ${pnl_diff:,.2f}")

if __name__ == "__main__":
    analyze_nq_macro()
