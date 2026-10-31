#!/usr/bin/env python3
"""
Researching Additional Cash Open Setups on MNQ and MES (2021-2026):
1. ORB-30 (10:00 ET Breakout): 30-minute opening range breakout
2. Value Area Extension at 10:00 ET (for sessions that opened inside VA but broke out by 10:00 ET)
3. ORB-5 (09:35 ET Breakout): 5-minute momentum impulse
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def evaluate_cash_open_variants(sym: str, path_str: str, val: float, slip: float):
    print(f"\n=======================================================")
    print(f"  EVALUATING CASH OPEN ALTERNATIVES ON {sym} (2021-2026)")
    print(f"=======================================================")
    
    df = pd.read_parquet(ROOT / path_str)
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["time"].dt.strftime("%H:%M")
    
    # 1. Compute Prior Day Value Area (09:30 - 16:00 ET)
    rth = df[(df["hhmm"] >= "09:30") & (df["hhmm"] <= "16:00")].copy()
    va_records = {}
    for d_str, g in rth.groupby("date_str"):
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
        va_records[d_str] = {"vah": vah_p, "val": val_p}
        
    dates_sorted = sorted(va_records.keys())
    prior_va_map = {}
    for i in range(1, len(dates_sorted)):
        prior_va_map[dates_sorted[i]] = va_records[dates_sorted[i - 1]]
        
    bars_by_date = {d: g.reset_index(drop=True) for d, g in df.groupby("date_str")}
    
    trades_orb30 = []
    trades_va_1000 = []
    
    for d_str in dates_sorted:
        if d_str < "2021-01-01":
            continue
        g = bars_by_date.get(d_str)
        if g is None or len(g) < 150:
            continue
        p_va = prior_va_map.get(d_str)
        if p_va is None:
            continue
            
        rth_bars = g[(g["hhmm"] >= "09:30") & (g["hhmm"] <= "16:00")].copy().reset_index(drop=True)
        if len(rth_bars) < 60:
            continue
            
        # Cumulative VWAP
        tp = (rth_bars["high"] + rth_bars["low"] + rth_bars["close"]) / 3.0
        cum_vol = rth_bars["volume"].clip(lower=1.0).cumsum()
        cum_pv = (tp * rth_bars["volume"].clip(lower=1.0)).cumsum()
        rth_bars["vwap"] = cum_pv / cum_vol
        
        open_0930 = float(rth_bars.iloc[0]["open"])
        opened_inside_va = (open_0930 <= p_va["vah"]) and (open_0930 >= p_va["val"])
        
        # 30-minute range (09:30 - 09:59 ET)
        or30 = rth_bars[rth_bars["hhmm"] <= "09:59"]
        if len(or30) < 28:
            continue
        or30_high = float(or30["high"].max())
        or30_low = float(or30["low"].min())
        or30_range = or30_high - or30_low
        
        # 10:00 ET Bar
        bar_1000 = rth_bars[rth_bars["hhmm"] == "10:00"]
        if bar_1000.empty:
            continue
        b = bar_1000.iloc[0]
        b_c = float(b["close"])
        b_h = float(b["high"])
        b_l = float(b["low"])
        b_rng = b_h - b_l
        b_cl_loc = (b_c - b_l) / b_rng if b_rng > 0 else 0.5
        b_vwap = float(b["vwap"])
        
        # --- Variant 1: VA Breakout at 10:00 ET for Inside-VA Opens ---
        # Opened inside VA, but by 10:00 ET, price has decisively broken out of prior VA
        d_va = 0
        if opened_inside_va:
            if b_c > p_va["vah"] and b_c > b_vwap and b_cl_loc >= 0.60:
                d_va = 1
            elif b_c < p_va["val"] and b_c < b_vwap and b_cl_loc <= 0.40:
                d_va = -1
                
        if d_va != 0:
            exec_bars = rth_bars[rth_bars["time"] > b["time"]].reset_index(drop=True)
            if len(exec_bars) >= 15:
                entry_p = float(exec_bars.iloc[0]["open"])
                stop_pts = float(np.clip(or30_range * 0.30, 20.0 if sym == "NQ" else 5.0, 45.0 if sym == "NQ" else 12.0))
                target_pts = stop_pts * 1.50
                stop_p = entry_p - d_va * stop_pts
                target_p = entry_p + d_va * target_pts
                
                exit_p = float(exec_bars.iloc[min(45, len(exec_bars) - 1)]["close"])
                for _, rb in exec_bars.iterrows():
                    if rb["hhmm"] >= "12:00":
                        exit_p = float(rb["close"])
                        break
                    rb_h, rb_l = float(rb["high"]), float(rb["low"])
                    if d_va == 1 and rb_l <= stop_p:
                        exit_p = stop_p
                        break
                    elif d_va == -1 and rb_h >= stop_p:
                        exit_p = stop_p
                        break
                    if d_va == 1 and rb_h >= target_p:
                        exit_p = target_p
                        break
                    elif d_va == -1 and rb_l <= target_p:
                        exit_p = target_p
                        break
                raw_pts = (exit_p - entry_p) * d_va
                net_pts = raw_pts - slip
                contracts = int(np.clip(np.round(250.0 / max(stop_pts * val, 1.0)), 1, 4))
                net_d = net_pts * val * contracts - 1.24 * contracts
                trades_va_1000.append({"year": int(d_str[:4]), "net_d": net_d, "dir": d_va})

    tdf_va = pd.DataFrame(trades_va_1000)
    if not tdf_va.empty:
        wr = (tdf_va["net_d"] > 0).mean() * 100
        pnl = tdf_va["net_d"].sum()
        pos = tdf_va.loc[tdf_va["net_d"] > 0, "net_d"].sum()
        neg = abs(tdf_va.loc[tdf_va["net_d"] <= 0, "net_d"].sum())
        pf = pos / neg if neg > 0 else 0
        print(f"  {sym} 10:00 ET Delayed VA Breakout: {len(tdf_va)} trades | WR: {wr:.1f}% | PF: {pf:.2f} | Net: ${pnl:,.2f}")
    else:
        print(f"  {sym} 10:00 ET Delayed VA Breakout: 0 trades")

def main():
    evaluate_cash_open_variants("NQ", "data/raw/nq_1m_2017_2026_cqg_et.parquet", 2.0, 1.0)
    evaluate_cash_open_variants("ES", "data/raw/es_1m_2020_2026_cqg_et.parquet", 5.0, 2.5)

if __name__ == "__main__":
    main()
