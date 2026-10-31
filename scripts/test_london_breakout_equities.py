#!/usr/bin/env python3
"""
London Cash Open (03:00 - 03:15 ET) Asian Range Breakout on MNQ and MES.
Evaluates 2021-2026.
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

for sym, path_str, val, slip in [
    ("NQ", "data/raw/nq_1m_2017_2026_cqg_et.parquet", 2.0, 1.0),
    ("ES", "data/raw/es_1m_2020_2026_cqg_et.parquet", 5.0, 2.5),
]:
    df = pd.read_parquet(ROOT / path_str)
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["time"].dt.strftime("%H:%M")
    
    trades = []
    for d_str, g in df.groupby("date_str"):
        if d_str < "2021-01-01":
            continue
        asia_bars = g[(g["hhmm"] >= "00:00") & (g["hhmm"] <= "02:59")]
        if len(asia_bars) < 100:
            continue
        a_high = float(asia_bars["high"].max())
        a_low = float(asia_bars["low"].min())
        a_rng = a_high - a_low
        if a_rng <= 0:
            continue
            
        m15 = g[(g["hhmm"] >= "03:00") & (g["hhmm"] <= "03:14")]
        if len(m15) < 14:
            continue
        c = float(m15.iloc[-1]["close"])
        o = float(m15.iloc[0]["open"])
        h = float(m15["high"].max())
        l = float(m15["low"].min())
        rng = h - l
        cl_loc = (c - l) / rng if rng > 0 else 0.5
        
        # Breakout of Asian range at London open
        d = 0
        if c > a_high and cl_loc >= 0.60:
            d = 1
        elif c < a_low and cl_loc <= 0.40:
            d = -1
            
        if d == 0:
            continue
            
        exec_bars = g[g["time"] > m15.iloc[-1]["time"]].reset_index(drop=True)
        if len(exec_bars) < 30:
            continue
        entry_p = float(exec_bars.iloc[0]["open"])
        stop_pts = float(np.clip(rng * 0.75, 20.0 if sym == "NQ" else 5.0, 50.0 if sym == "NQ" else 15.0))
        target_pts = stop_pts * 1.50
        stop_p = entry_p - d * stop_pts
        target_p = entry_p + d * target_pts
        
        exit_p = float(exec_bars.iloc[min(45, len(exec_bars) - 1)]["close"])
        for _, rb in exec_bars.iterrows():
            if rb["hhmm"] >= "05:00":
                exit_p = float(rb["close"])
                break
            rb_h, rb_l = float(rb["high"]), float(rb["low"])
            if d == 1 and rb_l <= stop_p:
                exit_p = stop_p
                break
            elif d == -1 and rb_h >= stop_p:
                exit_p = stop_p
                break
            if d == 1 and rb_h >= target_p:
                exit_p = target_p
                break
            elif d == -1 and rb_l <= target_p:
                exit_p = target_p
                break
                
        raw_pts = (exit_p - entry_p) * d
        net_pts = raw_pts - slip
        contracts = int(np.clip(np.round(250.0 / max(stop_pts * val, 1.0)), 1, 4))
        net_d = net_pts * val * contracts - 1.24 * contracts
        trades.append({"year": int(d_str[:4]), "net_d": net_d})
        
    tdf = pd.DataFrame(trades)
    if not tdf.empty:
        wr = (tdf["net_d"] > 0).mean() * 100
        pnl = tdf["net_d"].sum()
        pos = tdf.loc[tdf["net_d"] > 0, "net_d"].sum()
        neg = abs(tdf.loc[tdf["net_d"] <= 0, "net_d"].sum())
        pf = pos / neg if neg > 0 else 0
        print(f"{sym} London Breakout: {len(tdf)} trades | WR: {wr:.1f}% | PF: {pf:.2f} | Net: ${pnl:,.2f}")
    else:
        print(f"{sym}: No trades")
