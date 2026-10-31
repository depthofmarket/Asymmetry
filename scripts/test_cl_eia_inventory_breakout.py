#!/usr/bin/env python3
"""
Research on Crude Oil (CL / MCL) EIA Weekly Inventory Catalyst (Wednesdays @ 10:30 ET).
Evaluates 2021-2026.

Hypothesis:
Every Wednesday at 10:30 ET, the EIA publishes weekly petroleum status reports.
This is the single most liquid and volatile event in global energy markets.
After the initial 5-minute absorption window (10:30-10:34 ET), a decisive breakout
beyond the morning pre-release range with momentum produces a clean directional trend
into the European/London floor close (11:30 ET).

Target: Infrequent, high-conviction structural kicker (~1-2 trades/month).
Contract: MCL ($100/point, $1.00 per $0.01 tick)
Slippage: 2 ticks ($2.00)
Commissions: $1.24 RT
Risk Cap: $250
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def evaluate_eia_breakout():
    print("\n=======================================================")
    print("  EIA WEEKLY CRUDE OIL (MCL) INVENTORY CATALYST (2021-2026)")
    print("=======================================================")
    
    cl_path = ROOT / "data/raw/cl_1m_2020_2026_et.parquet"
    df = pd.read_parquet(cl_path)
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["day_name"] = df["time"].dt.day_name()
    df["hhmm"] = df["time"].dt.strftime("%H:%M")
    
    # Focus on Wednesday sessions (and Thursdays following Mon holidays)
    wed_df = df[df["day_name"].isin(["Wednesday", "Thursday"])].copy()
    bars_by_date = {d: g.reset_index(drop=True) for d, g in wed_df.groupby("date_str")}
    
    trades = []
    
    for d_str, g in bars_by_date.items():
        if d_str < "2021-01-01":
            continue
            
        rth_bars = g[(g["hhmm"] >= "09:00") & (g["hhmm"] <= "14:30")].reset_index(drop=True)
        if len(rth_bars) < 120:
            continue
            
        # 1. Pre-release morning range (09:00 to 10:29 ET)
        pre_bars = rth_bars[rth_bars["hhmm"] <= "10:29"]
        if len(pre_bars) < 60:
            continue
        pre_high = float(pre_bars["high"].max())
        pre_low = float(pre_bars["low"].min())
        pre_range = pre_high - pre_low
        
        # 2. Spike window: 10:30 to 10:34 ET (EIA release reaction)
        spike_bars = rth_bars[(rth_bars["hhmm"] >= "10:30") & (rth_bars["hhmm"] <= "10:34")]
        if len(spike_bars) < 4:
            continue
        spike_vol = float(spike_bars["volume"].sum())
        
        # Require genuine EIA volume spike (average pre-release 5m volume vs spike 5m)
        pre_5m_avg_vol = float(pre_bars["volume"].tail(30).mean()) * 5.0
        if spike_vol < pre_5m_avg_vol * 1.5:
            # Not an active EIA release day
            continue
            
        spike_high = float(spike_bars["high"].max())
        spike_low = float(spike_bars["low"].min())
        spike_close = float(spike_bars.iloc[-1]["close"])
        spike_open = float(spike_bars.iloc[0]["open"])
        
        # 3. Signal bar: 10:35 ET
        sig_bars = rth_bars[rth_bars["hhmm"] == "10:35"]
        if sig_bars.empty:
            continue
        sb = sig_bars.iloc[0]
        sb_c = float(sb["close"])
        sb_h = float(sb["high"])
        sb_l = float(sb["low"])
        sb_rng = sb_h - sb_l
        sb_cl_loc = (sb_c - sb_l) / sb_rng if sb_rng > 0 else 0.5
        
        # Cumulative VWAP from 09:00 ET
        tp = (rth_bars["high"] + rth_bars["low"] + rth_bars["close"]) / 3.0
        cum_vol = rth_bars["volume"].clip(lower=1.0).cumsum()
        cum_pv = (tp * rth_bars["volume"].clip(lower=1.0)).cumsum()
        rth_bars["vwap"] = cum_pv / cum_vol
        sb_vwap = float(rth_bars.loc[rth_bars["time"] == sb["time"], "vwap"].iloc[0])
        
        # Breakout criteria:
        # Long: 10:35 close > pre_high and > spike_high and > VWAP, strong close loc
        direction = 0
        if sb_c > pre_high and sb_c > spike_high and sb_c > sb_vwap and sb_cl_loc >= 0.65:
            direction = 1
        # Short: 10:35 close < pre_low and < spike_low and < VWAP, weak close loc
        elif sb_c < pre_low and sb_c < spike_low and sb_c < sb_vwap and sb_cl_loc <= 0.35:
            direction = -1
            
        if direction == 0:
            continue
            
        exec_bars = rth_bars[rth_bars["time"] > sb["time"]].reset_index(drop=True)
        if len(exec_bars) < 15:
            continue
            
        entry_p = float(exec_bars.iloc[0]["open"])
        
        # Stop loss: half of the spike range or 0.30 - 0.70 pts ($30 - $70 risk)
        stop_pts = float(np.clip((spike_high - spike_low) * 0.50, 0.30, 0.80))
        target_pts = stop_pts * 1.50
        stop_p = entry_p - direction * stop_pts
        target_p = entry_p + direction * target_pts
        
        exit_p = float(exec_bars.iloc[min(50, len(exec_bars) - 1)]["close"])
        exit_time = pd.Timestamp(exec_bars.iloc[min(50, len(exec_bars) - 1)]["time"])
        reason = "time_exit_50m"
        
        for _, rb in exec_bars.iterrows():
            if rb["hhmm"] >= "11:45":
                exit_p = float(rb["close"])
                exit_time = pd.Timestamp(rb["time"])
                reason = "time_exit_1145"
                break
            rb_h, rb_l = float(rb["high"]), float(rb["low"])
            if direction == 1 and rb_l <= stop_p:
                exit_p = stop_p
                exit_time = pd.Timestamp(rb["time"])
                reason = "stop_loss"
                break
            elif direction == -1 and rb_h >= stop_p:
                exit_p = stop_p
                exit_time = pd.Timestamp(rb["time"])
                reason = "stop_loss"
                break
            if direction == 1 and rb_h >= target_p:
                exit_p = target_p
                exit_time = pd.Timestamp(rb["time"])
                reason = "profit_target"
                break
            elif direction == -1 and rb_l <= target_p:
                exit_p = target_p
                exit_time = pd.Timestamp(rb["time"])
                reason = "profit_target"
                break
                
        raw_pts = (exit_p - entry_p) * direction
        net_pts = raw_pts - 0.02 # 2 ticks slippage ($2)
        contracts = int(np.clip(np.round(250.0 / max(stop_pts * 100.0, 1.0)), 1, 4))
        comm = 1.24 * contracts
        net_dollars = net_pts * 100.0 * contracts - comm
        
        trades.append({
            "date_str": d_str,
            "year": int(d_str[:4]),
            "direction": "long" if direction == 1 else "short",
            "entry_time": pd.Timestamp(exec_bars.iloc[0]["time"]),
            "exit_time": exit_time,
            "stop_pts": stop_pts,
            "contracts": contracts,
            "net_dollars": net_dollars,
            "reason": reason
        })
        
    tdf = pd.DataFrame(trades)
    if tdf.empty:
        print("No EIA trades found.")
        return tdf
        
    print(f"\nTotal EIA Catalyst Trades (2021-2026): {len(tdf)} trades across {tdf['date_str'].nunique()} days (~{len(tdf)/5.8:.1f} trades/yr, ~{len(tdf)/70:.1f}/mo)")
    for label, mask in [
        ("Full (2021-2026)", tdf["year"] >= 2021),
        ("Core Dev (2021-2024)", (tdf["year"] >= 2021) & (tdf["year"] <= 2024)),
        ("Out-of-Sample Holdout (2025-2026)", tdf["year"] >= 2025),
        ("Long Only", tdf["direction"] == "long"),
        ("Short Only", tdf["direction"] == "short"),
    ]:
        sub = tdf[mask]
        if sub.empty:
            continue
        n = len(sub)
        wr = (sub["net_dollars"] > 0).mean() * 100
        pnl = sub["net_dollars"].sum()
        pos = sub.loc[sub["net_dollars"] > 0, "net_dollars"].sum()
        neg = abs(sub.loc[sub["net_dollars"] <= 0, "net_dollars"].sum())
        pf = pos / neg if neg > 0 else np.nan
        print(f"  {label:<35}: {n:>4} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net PnL: ${pnl:>9,.2f}")
        
    return tdf

if __name__ == "__main__":
    evaluate_eia_breakout()
