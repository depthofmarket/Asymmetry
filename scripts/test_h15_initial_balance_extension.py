#!/usr/bin/env python3
"""
Initial Balance (IB) 60-Minute Extension Breakout Research & Multi-Era Evaluation.
Candidate ID: H15

Hypothesis:
On days where price opens inside the prior Value Area (where Strategy 1 at 09:45 ET
has NO signal), the first 60 minutes (09:30–10:30 ET) establish the Initial Balance (IB).
When price breaks out beyond the IB High (or Low) between 10:30 and 11:15 ET with
VWAP confirmation and close-location momentum, it signals institutional extension
(Trend or Double-Distribution day type) with positive expectancy.

Evaluates:
- Horizons: 6m, 12m, 24m, 30m, 45m unstopped returns
- Bracket: Stop = 1.0R (stop below IB breakout level / bar extreme), Target = 1.50R
- Multi-Era: 2021-2024 (Core Dev) vs 2025-2026 (Out-of-Sample Holdout)
"""

from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def evaluate_ib_extension(df: pd.DataFrame, sym: str, micro_val: float, tick_cost: float):
    print(f"\n=======================================================")
    print(f"  ANALYZING INITIAL BALANCE EXTENSION ON {sym}")
    print(f"=======================================================")
    
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["time"].dt.strftime("%H:%M")
    
    # 1. Compute Prior Day Value Area (09:30 - 16:00 ET)
    rth = df[(df["hhmm"] >= "09:30") & (df["hhmm"] <= "16:00")].copy()
    
    # Prior VA per session
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
        
    # Group bars by date
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
            
        rth_bars = day_bars[(day_bars["hhmm"] >= "09:30") & (day_bars["hhmm"] <= "16:00")]
        if len(rth_bars) < 60:
            continue
            
        open_0930 = float(rth_bars.iloc[0]["open"])
        
        # Check if opened inside prior VA (Strategy 1 had NO trade)
        opened_inside_va = (open_0930 <= p_va["vah"]) and (open_0930 >= p_va["val"])
        
        # Compute Initial Balance (09:30 - 10:29 ET)
        ib_bars = rth_bars[rth_bars["hhmm"] <= "10:29"]
        if len(ib_bars) < 50:
            continue
            
        ib_high = float(ib_bars["high"].max())
        ib_low = float(ib_bars["low"].min())
        ib_range = ib_high - ib_low
        
        # Min and Max IB Range sanity checks (avoid abnormal holiday dead sessions)
        min_ib_range = 25.0 if sym == "NQ" else 6.0
        max_ib_range = 350.0 if sym == "NQ" else 90.0
        if not (min_ib_range <= ib_range <= max_ib_range):
            continue
            
        # Cumulative VWAP calculation
        tp = (rth_bars["high"] + rth_bars["low"] + rth_bars["close"]) / 3.0
        cum_vol = rth_bars["volume"].clip(lower=1.0).cumsum()
        cum_pv = (tp * rth_bars["volume"].clip(lower=1.0)).cumsum()
        rth_bars["vwap"] = cum_pv / cum_vol
        
        # Look for IB Breakout in window 10:30 - 11:15 ET
        post_ib = rth_bars[(rth_bars["hhmm"] >= "10:30") & (rth_bars["hhmm"] <= "11:15")]
        if post_ib.empty:
            continue
            
        found_trade = False
        entry_time = None
        for b_time, b in post_ib.iterrows():
            b_close = float(b["close"])
            b_open = float(b["open"])
            b_high = float(b["high"])
            b_low = float(b["low"])
            b_range = b_high - b_low
            cl_loc = (b_close - b_low) / b_range if b_range > 0 else 0.5
            b_vwap = float(b["vwap"])
            
            # Long Breakout: Close > IB High, Close Loc >= 0.60, Above VWAP
            if b_close > ib_high and cl_loc >= 0.60 and b_close > b_vwap:
                direction = 1
                entry_time = pd.Timestamp(b["time"])
                found_trade = True
                break
                
            # Short Breakout: Close < IB Low, Close Loc <= 0.40, Below VWAP
            elif b_close < ib_low and cl_loc <= 0.40 and b_close < b_vwap:
                direction = -1
                entry_time = pd.Timestamp(b["time"])
                found_trade = True
                break
                
        if not found_trade or entry_time is None:
            continue
            
        # Forward bars after signal
        exec_bars = rth_bars[rth_bars["time"] > entry_time].reset_index(drop=True)
        if len(exec_bars) < 5:
            continue
            
        entry_bar_time = pd.Timestamp(exec_bars.iloc[0]["time"])
        entry_price = float(exec_bars.iloc[0]["open"])
        
        # Risk-budgeted stop: 25-45 pts on NQ, 6-12 pts on ES
        stop_pts = float(np.clip(ib_range * 0.25, 20.0 if sym == "NQ" else 5.0, 50.0 if sym == "NQ" else 15.0))
        target_pts = stop_pts * 1.50
        stop_price = entry_price - direction * stop_pts
        target_price = entry_price + direction * target_pts
        
        # Forward evaluation up to 45 bars or 12:00 ET
        exit_price = float(exec_bars.iloc[min(45, len(exec_bars) - 1)]["close"])
        exit_time = pd.Timestamp(exec_bars.iloc[min(45, len(exec_bars) - 1)]["time"])
        reason = "time_exit_45m"
        
        for r_i, rb in exec_bars.iterrows():
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
        net_pts = raw_pts - (1.0 if sym == "NQ" else 0.5) # slippage
        contracts = int(np.clip(np.round(250.0 / max(stop_pts * micro_val, 1.0)), 1, 4))
        comm = 1.24 * contracts
        net_dollars = net_pts * micro_val * contracts - comm
        
        trades.append({
            "date_str": d_str,
            "year": entry_time.year,
            "sym": sym,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "direction": "long" if direction == 1 else "short",
            "opened_inside_va": opened_inside_va,
            "ib_range": ib_range,
            "stop_pts": stop_pts,
            "target_pts": target_pts,
            "contracts": contracts,
            "net_pts": net_pts,
            "net_dollars": net_dollars,
            "reason": reason
        })
        
    t_df = pd.DataFrame(trades)
    if t_df.empty:
        print("  No trades found.")
        return t_df
        
    print(f"\nTotal Candidate Trades (2021-2026): {len(t_df)} trades across {t_df['date_str'].nunique()} days")
    
    # Era breakdown
    for label, mask in [
        ("Full (2021-2026)", t_df["year"] >= 2021),
        ("Core Dev (2021-2024)", (t_df["year"] >= 2021) & (t_df["year"] <= 2024)),
        ("Out-of-Sample Holdout (2025-2026)", t_df["year"] >= 2025),
        ("Inside-VA Opening Only", t_df["opened_inside_va"] == True),
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
    
    t_nq = evaluate_ib_extension(df_nq, "NQ", micro_val=2.0, tick_cost=1.0)
    t_es = evaluate_ib_extension(df_es, "ES", micro_val=5.0, tick_cost=2.5)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
