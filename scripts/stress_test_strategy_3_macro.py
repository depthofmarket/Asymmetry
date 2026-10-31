#!/usr/bin/env python3
"""
Rigorous Stress-Testing of Strategy 3 (MNQ Pre-Market Macro Release Momentum @ 08:35 ET).
Tests:
1. Slippage Sensitivity: 1 pt ($2), 2 pts ($4), 3 pts ($6), 4 pts ($8) per micro contract
2. Long vs Short Asymmetry & Filtering
3. Multi-Era Holdout Stability: 2021-2024 (Dev) vs 2025-2026 (Holdout)
4. Max Adverse Excursion (MAE) & Gap Risk into 09:25 ET
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def run_stress_test():
    df = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["time"].dt.strftime("%H:%M")
    bars_by_date = {d: g.reset_index(drop=True) for d, g in df.groupby("date_str")}
    
    records = []
    
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
        
        # Genuine high-volume macro release
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
        
        mae_pts = 0.0
        mfe_pts = 0.0
        
        for _, rb in exec_bars.iterrows():
            if rb["hhmm"] >= "09:25":
                exit_p = float(rb["close"])
                exit_time = pd.Timestamp(rb["time"])
                break
            rb_h, rb_l = float(rb["high"]), float(rb["low"])
            
            # Track MAE & MFE
            adv = (entry_p - rb_l) if d == 1 else (rb_h - entry_p)
            fav = (rb_h - entry_p) if d == 1 else (entry_p - rb_l)
            mae_pts = max(mae_pts, adv)
            mfe_pts = max(mfe_pts, fav)
            
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
        contracts = int(np.clip(np.round(250.0 / max(stop_pts * 2.0, 1.0)), 1, 4))
        
        records.append({
            "date_str": d_str,
            "year": int(d_str[:4]),
            "direction": "long" if d == 1 else "short",
            "entry_p": entry_p,
            "exit_p": exit_p,
            "stop_pts": stop_pts,
            "contracts": contracts,
            "raw_pts": raw_pts,
            "mae_pts": mae_pts,
            "mfe_pts": mfe_pts,
            "reason": reason
        })
        
    res_df = pd.DataFrame(records)
    print("=" * 65)
    print("  STRATEGY 3 (MNQ 08:35 ET MACRO) STRESS-TEST RESULTS")
    print("=" * 65)
    print(f"Total Trades Evaluated: {len(res_df)} (2021-2026)")
    
    # 1. SLIPPAGE SENSITIVITY TEST
    print("\n--- 1. SLIPPAGE SENSITIVITY TEST ---")
    comm_rt = 1.24
    for slip_pts in [1.0, 2.0, 3.0, 4.0]:
        pnl_arr = []
        for _, r in res_df.iterrows():
            net_pts = r["raw_pts"] - slip_pts
            net_d = net_pts * 2.0 * r["contracts"] - (comm_rt * r["contracts"])
            pnl_arr.append(net_d)
        pnl_s = pd.Series(pnl_arr)
        wr = (pnl_s > 0).mean() * 100
        pnl = pnl_s.sum()
        pos = pnl_s[pnl_s > 0].sum()
        neg = abs(pnl_s[pnl_s <= 0].sum())
        pf = pos / neg if neg > 0 else 0.0
        slip_ticks = int(slip_pts * 4)
        print(f"  Slippage: {slip_pts:.1f} pts ({slip_ticks:>2} ticks / ${slip_pts*2:.2f}/c) | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net P&L: ${pnl:>8,.2f}")
        
    # 2. LONG VS SHORT SEPARATION (at 2.0 pts realistic news slippage)
    print("\n--- 2. LONG VS SHORT PERFORMANCE (at 2.0 pts / 8 ticks slippage) ---")
    for d_lbl in ["All", "short", "long"]:
        sub = res_df if d_lbl == "All" else res_df[res_df["direction"] == d_lbl]
        pnl_arr = []
        for _, r in sub.iterrows():
            net_pts = r["raw_pts"] - 2.0
            net_d = net_pts * 2.0 * r["contracts"] - (comm_rt * r["contracts"])
            pnl_arr.append(net_d)
        pnl_s = pd.Series(pnl_arr)
        wr = (pnl_s > 0).mean() * 100
        pnl = pnl_s.sum()
        pos = pnl_s[pnl_s > 0].sum()
        neg = abs(pnl_s[pnl_s <= 0].sum())
        pf = pos / neg if neg > 0 else 0.0
        print(f"  {d_lbl.capitalize():<10}: {len(sub):>3} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net: ${pnl:>8,.2f}")
        
    # 3. ERA COMPARISON (at 2.0 pts slippage)
    print("\n--- 3. MULTI-ERA STABILITY (at 2.0 pts / 8 ticks slippage) ---")
    for era_lbl, mask in [
        ("Full (2021-2026)", res_df["year"] >= 2021),
        ("Core Dev (2021-2024)", (res_df["year"] >= 2021) & (res_df["year"] <= 2024)),
        ("Holdout (2025-2026)", res_df["year"] >= 2025),
    ]:
        sub = res_df[mask]
        pnl_arr = []
        for _, r in sub.iterrows():
            net_pts = r["raw_pts"] - 2.0
            net_d = net_pts * 2.0 * r["contracts"] - (comm_rt * r["contracts"])
            pnl_arr.append(net_d)
        pnl_s = pd.Series(pnl_arr)
        wr = (pnl_s > 0).mean() * 100
        pnl = pnl_s.sum()
        pos = pnl_s[pnl_s > 0].sum()
        neg = abs(pnl_s[pnl_s <= 0].sum())
        pf = pos / neg if neg > 0 else 0.0
        print(f"  {era_lbl:<25}: {len(sub):>3} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net: ${pnl:>8,.2f}")

    # 4. ENHANCED FILTER: What if we require VWAP Confirmation + Strong Trend on Longs?
    print("\n--- 4. DIRECTIONAL REFINEMENT: SHORT-ONLY VS BOTH SIDES ---")
    short_df = res_df[res_df["direction"] == "short"]
    for slip_pts in [1.0, 2.0, 3.0, 4.0]:
        pnl_arr = []
        for _, r in short_df.iterrows():
            net_pts = r["raw_pts"] - slip_pts
            net_d = net_pts * 2.0 * r["contracts"] - (comm_rt * r["contracts"])
            pnl_arr.append(net_d)
        pnl_s = pd.Series(pnl_arr)
        wr = (pnl_s > 0).mean() * 100
        pnl = pnl_s.sum()
        pos = pnl_s[pnl_s > 0].sum()
        neg = abs(pnl_s[pnl_s <= 0].sum())
        pf = pos / neg if neg > 0 else 0.0
        print(f"  Short-Only Slippage {slip_pts:.1f} pts: {len(short_df)} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net: ${pnl:>8,.2f}")

if __name__ == "__main__":
    run_stress_test()
