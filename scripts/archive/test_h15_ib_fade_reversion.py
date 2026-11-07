#!/usr/bin/env python3
"""
Initial Balance (IB) Failed Breakout / Fade Mean-Reversion Research.
Hypothesis:
On days that open inside the prior Value Area (balanced market), breakouts beyond the
60-minute Initial Balance (IB) between 10:30 and 11:30 ET are often liquidity traps.
When price pokes outside the IB and fails back inside below IB High (or above IB Low)
with confirming candle reversal, fading back toward VWAP / IB Midpoint yields edge.
"""

from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def evaluate_ib_fade(df: pd.DataFrame, sym: str, micro_val: float, tick_cost: float):
    print(f"\n=======================================================")
    print(f"  ANALYZING INITIAL BALANCE FADE / REVERSION ON {sym}")
    print(f"=======================================================")
    
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
            
        rth_bars = day_bars[(day_bars["hhmm"] >= "09:30") & (day_bars["hhmm"] <= "16:00")].copy().reset_index(drop=True)
        if len(rth_bars) < 60:
            continue
            
        open_0930 = float(rth_bars.iloc[0]["open"])
        opened_inside_va = (open_0930 <= p_va["vah"]) and (open_0930 >= p_va["val"])
        
        # Only analyze days opened inside VA where Strategy 1 has no signal
        if not opened_inside_va:
            continue
            
        ib_bars = rth_bars[rth_bars["hhmm"] <= "10:29"]
        if len(ib_bars) < 50:
            continue
            
        ib_high = float(ib_bars["high"].max())
        ib_low = float(ib_bars["low"].min())
        ib_mid = (ib_high + ib_low) / 2.0
        ib_range = ib_high - ib_low
        
        min_ib_range = 25.0 if sym == "NQ" else 6.0
        max_ib_range = 350.0 if sym == "NQ" else 90.0
        if not (min_ib_range <= ib_range <= max_ib_range):
            continue
            
        # Post-IB window: 10:30 - 11:30 ET
        post_ib = rth_bars[(rth_bars["hhmm"] >= "10:30") & (rth_bars["hhmm"] <= "11:30")].copy()
        if post_ib.empty:
            continue
            
        # Cumulative VWAP
        tp = (rth_bars["high"] + rth_bars["low"] + rth_bars["close"]) / 3.0
        cum_vol = rth_bars["volume"].clip(lower=1.0).cumsum()
        cum_pv = (tp * rth_bars["volume"].clip(lower=1.0)).cumsum()
        rth_bars["vwap"] = cum_pv / cum_vol
        
        found_trade = False
        direction = 0
        entry_time = None
        poked_above = False
        poked_below = False
        
        for _, b in post_ib.iterrows():
            b_high = float(b["high"])
            b_low = float(b["low"])
            b_close = float(b["close"])
            b_range = b_high - b_low
            cl_loc = (b_close - b_low) / b_range if b_range > 0 else 0.5
            
            if b_high > ib_high:
                poked_above = True
            if b_low < ib_low:
                poked_below = True
                
            # Fade Short: Poked above IB High, now closed back inside below IB High with bearish candle
            if poked_above and b_close < ib_high and cl_loc <= 0.40:
                direction = -1 # Short fade
                entry_time = pd.Timestamp(b["time"])
                found_trade = True
                break
                
            # Fade Long: Poked below IB Low, now closed back inside above IB Low with bullish candle
            elif poked_below and b_close > ib_low and cl_loc >= 0.60:
                direction = 1 # Long fade
                entry_time = pd.Timestamp(b["time"])
                found_trade = True
                break
                
        if not found_trade or entry_time is None:
            continue
            
        exec_bars = rth_bars[rth_bars["time"] > entry_time].reset_index(drop=True)
        if len(exec_bars) < 5:
            continue
            
        entry_price = float(exec_bars.iloc[0]["open"])
        
        # Stop loss: Just above the high of the trap poke (or below the low)
        # Cap stop between 20-45 pts on NQ, 5-12 pts on ES
        stop_pts = float(np.clip(ib_range * 0.25, 20.0 if sym == "NQ" else 5.0, 45.0 if sym == "NQ" else 12.0))
        # Target: IB Midpoint or 1.5R
        target_pts = stop_pts * 1.50
        stop_price = entry_price - direction * stop_pts
        target_price = entry_price + direction * target_pts
        
        exit_price = float(exec_bars.iloc[min(45, len(exec_bars) - 1)]["close"])
        exit_time = pd.Timestamp(exec_bars.iloc[min(45, len(exec_bars) - 1)]["time"])
        reason = "time_exit_45m"
        
        for _, rb in exec_bars.iterrows():
            if rb["hhmm"] >= "12:00":
                exit_price = float(rb["close"])
                exit_time = pd.Timestamp(rb["time"])
                reason = "time_exit_1200"
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
        net_pts = raw_pts - (1.0 if sym == "NQ" else 0.5)
        contracts = int(np.clip(np.round(250.0 / max(stop_pts * micro_val, 1.0)), 1, 4))
        comm = 1.24 * contracts
        net_dollars = net_pts * micro_val * contracts - comm
        
        trades.append({
            "date_str": d_str,
            "year": entry_time.year,
            "sym": sym,
            "entry_time": entry_time,
            "direction": "long" if direction == 1 else "short",
            "contracts": contracts,
            "net_dollars": net_dollars,
            "reason": reason
        })
        
    t_df = pd.DataFrame(trades)
    if t_df.empty:
        print("  No fade trades found.")
        return t_df
        
    print(f"\nTotal IB Fade Trades (Inside-VA Days 2021-2026): {len(t_df)} trades")
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

def main():
    df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
    df_es = pd.read_parquet(ROOT / "data/raw/es_1m_2020_2026_cqg_et.parquet")
    evaluate_ib_fade(df_nq, "NQ", 2.0, 1.0)
    evaluate_ib_fade(df_es, "ES", 5.0, 2.5)

if __name__ == "__main__":
    main()
