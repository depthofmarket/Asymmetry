#!/usr/bin/env python3
"""
Crude Oil (CL / MCL) Pit Open (09:00 ET) Value Area Breakout Research.
Candidate ID: H16

Hypothesis:
WTI Crude Oil pit trading opens at 09:00 ET. When price opens outside the prior session
Value Area (VAH/VAL computed on NYMEX pit session 09:00–14:30 ET), a directional impulse
at 09:15 ET confirms commercial order flow with positive expectancy, providing non-correlated
trade frequency before US Equity RTH opens at 09:30 ET.

Contract: MCL (Micro WTI Crude Oil)
- Tick size: $0.01 ($1.00 per micro)
- Point value: $100.00 ($1.00 price change = $100 per micro)
- Commission: $1.24 RT per contract
- Slippage: 1 tick ($1.00 per contract)
- Risk Cap: $250 max risk per trade
"""

from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def evaluate_cl_oil():
    print("\n=======================================================")
    print("  ANALYZING CRUDE OIL (MCL) PIT OPEN BREAKOUT (09:00 ET)")
    print("=======================================================")
    
    cl_path = ROOT / "data/raw/cl_1m_2020_2026_et.parquet"
    if not cl_path.exists():
        print("CL parquet not found.")
        return
        
    df = pd.read_parquet(cl_path)
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["time"].dt.strftime("%H:%M")
    
    # 1. Compute Prior Pit Value Area (09:00 - 14:30 ET)
    pit = df[(df["hhmm"] >= "09:00") & (df["hhmm"] <= "14:30")].copy()
    
    va_records = {}
    for d_str, g in pit.groupby("date_str"):
        if len(g) < 60:
            continue
        low_min = float(g["low"].min())
        high_max = float(g["high"].max())
        if high_max <= low_min:
            continue
        bins = np.linspace(low_min, high_max, 51)
        tp = (g["high"] + g["low"] + g["close"]) / 3.0
        vol = g["volume"].clip(lower=1.0)
        idx = np.clip(np.digitize(tp, bins) - 1, 0, 49)
        vol_profile = np.bincount(idx, weights=vol, minlength=50)
        poc_idx = int(np.argmax(vol_profile))
        poc_p = 0.5 * (bins[poc_idx] + bins[poc_idx + 1])
        target_vol = 0.70 * vol.sum()
        cur_vol = vol_profile[poc_idx]
        lo_idx = poc_idx
        hi_idx = poc_idx
        while cur_vol < target_vol and (lo_idx > 0 or hi_idx < 49):
            next_lo_vol = vol_profile[lo_idx - 1] if lo_idx > 0 else -1.0
            next_hi_vol = vol_profile[hi_idx + 1] if hi_idx < 49 else -1.0
            if next_hi_vol >= next_lo_vol:
                hi_idx += 1
                cur_vol += next_hi_vol
            else:
                lo_idx -= 1
                cur_vol += next_lo_vol
        vah_p = bins[hi_idx + 1]
        val_p = bins[lo_idx]
        va_records[d_str] = {"vah": vah_p, "val": val_p, "poc": poc_p}
        
    dates_sorted = sorted(va_records.keys())
    prior_va_map = {}
    for i in range(1, len(dates_sorted)):
        prior_va_map[dates_sorted[i]] = va_records[dates_sorted[i - 1]]
        
    bars_by_date = {d: g.reset_index(drop=True) for d, g in df.groupby("date_str")}
    
    trades = []
    
    for d_str in dates_sorted[1:]:
        if d_str < "2021-01-01":
            continue
        day_bars = bars_by_date.get(d_str)
        if day_bars is None or len(day_bars) < 120:
            continue
            
        p_va = prior_va_map.get(d_str)
        if p_va is None:
            continue
            
        pit_bars = day_bars[(day_bars["hhmm"] >= "09:00") & (day_bars["hhmm"] <= "14:30")].reset_index(drop=True)
        if len(pit_bars) < 30:
            continue
            
        open_0900 = float(pit_bars.iloc[0]["open"])
        
        # Test 1: Pit Open outside prior Value Area
        is_above_vah = open_0900 > p_va["vah"]
        is_below_val = open_0900 < p_va["val"]
        
        if not (is_above_vah or is_below_val):
            continue
            
        # Cumulative VWAP
        tp = (pit_bars["high"] + pit_bars["low"] + pit_bars["close"]) / 3.0
        cum_vol = pit_bars["volume"].clip(lower=1.0).cumsum()
        cum_pv = (tp * pit_bars["volume"].clip(lower=1.0)).cumsum()
        pit_bars["vwap"] = cum_pv / cum_vol
        
        # Signal window: 09:15 ET (after 15 minutes of trade)
        sig_bars = pit_bars[pit_bars["hhmm"] == "09:15"]
        if sig_bars.empty:
            continue
            
        sb = sig_bars.iloc[0]
        sb_close = float(sb["close"])
        sb_open = float(sb["open"])
        sb_high = float(sb["high"])
        sb_low = float(sb["low"])
        sb_range = sb_high - sb_low
        sb_cl_loc = (sb_close - sb_low) / sb_range if sb_range > 0 else 0.5
        sb_vwap = float(sb["vwap"])
        
        direction = 0
        if is_above_vah and sb_close > p_va["vah"] and sb_close > sb_vwap and sb_cl_loc >= 0.50:
            direction = 1
        elif is_below_val and sb_close < p_va["val"] and sb_close < sb_vwap and sb_cl_loc <= 0.50:
            direction = -1
            
        if direction == 0:
            continue
            
        entry_time = pd.Timestamp(sb["time"])
        exec_bars = pit_bars[pit_bars["time"] > entry_time].reset_index(drop=True)
        if len(exec_bars) < 5:
            continue
            
        entry_price = float(exec_bars.iloc[0]["open"])
        
        # In Crude Oil, typical 15m ATR / stop is 0.30 to 0.70 points ($30 to $70 on 1 micro)
        # Compute range of first 15 mins
        m15_bars = pit_bars[pit_bars["hhmm"] <= "09:15"]
        m15_range = float(m15_bars["high"].max() - m15_bars["low"].min())
        stop_pts = float(np.clip(m15_range * 0.50, 0.30, 0.80))
        target_pts = stop_pts * 1.50
        
        stop_price = entry_price - direction * stop_pts
        target_price = entry_price + direction * target_pts
        
        exit_price = float(exec_bars.iloc[min(60, len(exec_bars) - 1)]["close"])
        exit_time = pd.Timestamp(exec_bars.iloc[min(60, len(exec_bars) - 1)]["time"])
        reason = "time_exit_60m"
        
        for r_i, rb in exec_bars.iterrows():
            if rb["hhmm"] >= "11:30":
                exit_price = float(rb["close"])
                exit_time = pd.Timestamp(rb["time"])
                reason = "time_exit_1130"
                break
            rb_h, rb_l = float(rb["high"]), float(rb["low"])
            if direction == 1 and rb_l <= stop_price:
                exit_price = stop_price
                exit_time = pd.Timestamp(rb["time"])
                reason = "stop_loss"
                break
            elif direction == -1 and rb_h >= stop_price:
                exit_price = stop_price
                exit_time = pd.Timestamp(rb["time"])
                reason = "stop_loss"
                break
            if direction == 1 and rb_h >= target_price:
                exit_price = target_price
                exit_time = pd.Timestamp(rb["time"])
                reason = "profit_target"
                break
            elif direction == -1 and rb_l <= target_price:
                exit_price = target_price
                exit_time = pd.Timestamp(rb["time"])
                reason = "profit_target"
                break
                
        raw_pts = (exit_price - entry_price) * direction
        # 1 tick slippage = 0.01 pt ($1.00)
        net_pts = raw_pts - 0.01
        # Contract sizing: $250 max risk cap
        # stop_risk_per_contract = stop_pts * $100
        stop_risk = stop_pts * 100.0
        contracts = int(np.clip(np.floor(250.0 / max(stop_risk, 1.0)), 1, 4))
        comm = 1.24 * contracts
        net_dollars = net_pts * 100.0 * contracts - comm
        
        trades.append({
            "date_str": d_str,
            "year": entry_time.year,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "direction": "long" if direction == 1 else "short",
            "stop_pts": stop_pts,
            "target_pts": target_pts,
            "contracts": contracts,
            "net_pts": net_pts,
            "net_dollars": net_dollars,
            "reason": reason
        })
        
    t_df = pd.DataFrame(trades)
    if t_df.empty:
        print("No trades found.")
        return t_df
        
    print(f"\nTotal Candidate MCL Trades (2021-2026): {len(t_df)} trades across {t_df['date_str'].nunique()} days")
    
    for label, mask in [
        ("Full (2021-2026)", t_df["year"] >= 2021),
        ("Core Dev (2021-2024)", (t_df["year"] >= 2021) & (t_df["year"] <= 2024)),
        ("Out-of-Sample Holdout (2025-2026)", t_df["year"] >= 2025),
        ("Long Only", t_df["direction"] == "long"),
        ("Short Only", t_df["direction"] == "short"),
    ]:
        sub = t_df[mask]
        if sub.empty:
            continue
        n = len(sub)
        wr = (sub["net_dollars"] > 0).mean() * 100
        pnl = sub["net_dollars"].sum()
        pos = sub.loc[sub["net_dollars"] > 0, "net_dollars"].sum()
        neg = abs(sub.loc[sub["net_dollars"] <= 0, "net_dollars"].sum())
        pf = pos / neg if neg > 0 else np.nan
        print(f"  {label:<35}: {n:>4} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net PnL: ${pnl:>9,.2f}")
        
    return t_df

if __name__ == "__main__":
    evaluate_cl_oil()
