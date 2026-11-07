#!/usr/bin/env python3
"""
Researching Pre-Market US Macro Release Momentum on MNQ (08:30 - 08:45 ET).
Evaluates 2021-2026.

Hypothesis:
On days with major US economic data releases (08:30 ET: CPI, NFP, Retail Sales, PPI),
institutional repricing creates huge volume (spike > 3x pre-release average).
If the initial 5-minute reaction bar (08:30-08:34 ET) establishes strong directional momentum
(close location >= 0.70 or <= 0.30, breaking the Asian/London overnight high/low),
entering at 08:35 ET captures the pre-market continuation into the 09:30 RTH cash open.
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def evaluate_macro_0835(sym: str, path_str: str, val: float, slip: float):
    print(f"\n=======================================================")
    print(f"  PRE-MARKET MACRO RELEASE (08:35 ET) ON {sym} (2021-2026)")
    print(f"=======================================================")
    
    df = pd.read_parquet(ROOT / path_str)
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["time"].dt.strftime("%H:%M")
    
    bars_by_date = {d: g.reset_index(drop=True) for d, g in df.groupby("date_str")}
    trades = []
    
    for d_str, g in bars_by_date.items():
        if d_str < "2021-01-01":
            continue
            
        # Overnight range: 00:00 to 08:29 ET
        ovn = g[(g["hhmm"] >= "00:00") & (g["hhmm"] <= "08:29")]
        if len(ovn) < 180:
            continue
        ovn_high = float(ovn["high"].max())
        ovn_low = float(ovn["low"].min())
        ovn_range = ovn_high - ovn_low
        if ovn_range <= 0:
            continue
            
        # 08:30 - 08:34 ET release spike
        spike = g[(g["hhmm"] >= "08:30") & (g["hhmm"] <= "08:34")]
        if len(spike) < 4:
            continue
            
        spike_vol = float(spike["volume"].sum())
        pre_vol_5m = float(ovn["volume"].tail(30).mean()) * 5.0
        
        # Only evaluate actual high-impact macro days (volume spike > 2.5x pre-release volume)
        if spike_vol < pre_vol_5m * 2.5:
            continue
            
        spike_c = float(spike.iloc[-1]["close"])
        spike_o = float(spike.iloc[0]["open"])
        spike_h = float(spike["high"].max())
        spike_l = float(spike["low"].min())
        spike_rng = spike_h - spike_l
        spike_cl_loc = (spike_c - spike_l) / spike_rng if spike_rng > 0 else 0.5
        
        # 08:35 ET entry bar
        entry_bars = g[g["hhmm"] == "08:35"]
        if entry_bars.empty:
            continue
        eb = entry_bars.iloc[0]
        
        # Long: 08:30-08:34 broke overnight high with bullish close location
        direction = 0
        if spike_c > ovn_high and spike_cl_loc >= 0.65:
            direction = 1
        elif spike_c < ovn_low and spike_cl_loc <= 0.35:
            direction = -1
            
        if direction == 0:
            continue
            
        exec_bars = g[g["time"] >= eb["time"]].reset_index(drop=True)
        if len(exec_bars) < 20:
            continue
            
        entry_p = float(exec_bars.iloc[0]["open"])
        stop_pts = float(np.clip(spike_rng * 0.50, 20.0 if sym == "NQ" else 5.0, 50.0 if sym == "NQ" else 15.0))
        target_pts = stop_pts * 1.50
        stop_p = entry_p - direction * stop_pts
        target_p = entry_p + direction * target_pts
        
        # Exit before 09:30 cash open (flat at 09:25 to avoid opening bell gap risk)
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
        net_pts = raw_pts - slip
        contracts = int(np.clip(np.round(250.0 / max(stop_pts * val, 1.0)), 1, 4))
        comm = 1.24 * contracts
        net_dollars = net_pts * val * contracts - comm
        
        trades.append({
            "date_str": d_str,
            "year": int(d_str[:4]),
            "direction": "long" if direction == 1 else "short",
            "net_dollars": net_dollars,
            "reason": reason
        })
        
    tdf = pd.DataFrame(trades)
    if tdf.empty:
        print("  No trades found.")
        return tdf
        
    print(f"\nTotal Macro Release Trades (2021-2026): {len(tdf)} trades across {tdf['date_str'].nunique()} days (~{len(tdf)/5.8:.1f} trades/yr, ~{len(tdf)/70:.1f}/mo)")
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

def main():
    evaluate_macro_0835("NQ", "data/raw/nq_1m_2017_2026_cqg_et.parquet", 2.0, 1.0)
    evaluate_macro_0835("ES", "data/raw/es_1m_2020_2026_cqg_et.parquet", 5.0, 2.5)

if __name__ == "__main__":
    main()
