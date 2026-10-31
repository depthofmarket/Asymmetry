#!/usr/bin/env python3
"""
Research & Systematic Evaluation of Gold (GC / MGC) Intraday Trading Windows.
Tests 4 distinct structural windows across 2021-2026:
1. COMEX RTH Open (08:20 - 08:35 ET): Morning Value Area Breakout
2. US Macro Data Release (08:30 - 08:45 ET): High-Impact Repricing
3. LBMA PM Fix Filter Relaxation (10:14 ET): Long + Short, Relaxed Confluence
4. London Cash Open (03:00 - 03:15 ET): European Overnight Impulse

Contract Mechanics for MGC:
- Point Value: $10.00 ($1.00 move = $10 per micro, $0.10 tick = $1.00)
- Commissions: $1.50 RT per micro
- Slippage: 2 ticks = $0.20 ($2.00 per micro)
- Risk Cap: $250 max risk (ratchet 1 to 4 micros)
- Reward/Risk: 1.50R
"""

from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def load_gold_data():
    p = ROOT / "data/raw/gc_1m_2019_2026_merged_et.parquet"
    df = pd.read_parquet(p)
    df = df[(df["time"] >= "2020-01-01") & (df["open"] > 0)].copy()
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["time"].dt.strftime("%H:%M")
    return df

def compute_prior_comex_profiles(df: pd.DataFrame):
    # COMEX RTH: 08:20 to 13:30 ET
    rth = df[(df["hhmm"] >= "08:20") & (df["hhmm"] <= "13:30")].copy()
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
    return prior_va_map

def summarize_trades(trades, window_name):
    t_df = pd.DataFrame(trades)
    if t_df.empty:
        print(f"\n[{window_name}] No trades generated.")
        return t_df
        
    print(f"\n=======================================================")
    print(f"  {window_name.upper()} (2021-2026)")
    print(f"=======================================================")
    print(f"Total Trades: {len(t_df)} trades across {t_df['date_str'].nunique()} days (~{len(t_df)/5.8:.1f} trades/yr, ~{len(t_df)/70:.1f}/mo)")
    
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

def simulate_bracket(exec_bars, direction, entry_price, stop_pts, target_pts, max_bars=45):
    stop_price = entry_price - direction * stop_pts
    target_price = entry_price + direction * target_pts
    
    exit_price = float(exec_bars.iloc[min(max_bars - 1, len(exec_bars) - 1)]["close"])
    exit_time = pd.Timestamp(exec_bars.iloc[min(max_bars - 1, len(exec_bars) - 1)]["time"])
    reason = "time_exit"
    
    for _, rb in exec_bars.iterrows():
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
    net_pts = raw_pts - 0.20 # 2 ticks slippage ($2)
    contracts = int(np.clip(np.round(250.0 / max(stop_pts * 10.0, 1.0)), 1, 4))
    comm = 1.50 * contracts
    net_dollars = net_pts * 10.0 * contracts - comm
    
    return {
        "exit_price": exit_price,
        "exit_time": exit_time,
        "contracts": contracts,
        "net_pts": net_pts,
        "net_dollars": net_dollars,
        "reason": reason
    }

def test_all_windows():
    df = load_gold_data()
    prior_va_map = compute_prior_comex_profiles(df)
    bars_by_date = {d: g.reset_index(drop=True) for d, g in df.groupby("date_str")}
    dates_sorted = sorted(prior_va_map.keys())
    
    # Storage for trades across windows
    trades_w1_comex_open = []      # 08:20 - 08:35 ET Value Area Breakout
    trades_w2_macro_0835 = []       # 08:30 - 08:45 ET Macro Release Momentum
    trades_w3_fix_relaxed = []      # 10:14 ET Fix (Long + Short, Relaxed Confluence)
    trades_w3_fix_all_days = []     # 10:14 ET Fix original logic but Monday-Friday all days
    trades_w4_london_0315 = []      # 03:00 - 03:15 ET London Open
    
    for d_str in dates_sorted:
        if d_str < "2021-01-01":
            continue
        day_bars = bars_by_date.get(d_str)
        if day_bars is None or len(day_bars) < 200:
            continue
        p_va = prior_va_map.get(d_str)
        if p_va is None:
            continue
            
        d_obj = pd.Timestamp(d_str)
        day_of_week = d_obj.day_name()
        
        # -------------------------------------------------------------
        # Window 1: COMEX Open Breakout (08:20 - 08:35 ET)
        # -------------------------------------------------------------
        comex_bars = day_bars[(day_bars["hhmm"] >= "08:20") & (day_bars["hhmm"] <= "13:30")].reset_index(drop=True)
        if len(comex_bars) >= 20:
            open_0820 = float(comex_bars.iloc[0]["open"])
            is_above_vah = open_0820 > p_va["vah"]
            is_below_val = open_0820 < p_va["val"]
            
            if is_above_vah or is_below_val:
                tp = (comex_bars["high"] + comex_bars["low"] + comex_bars["close"]) / 3.0
                cum_vol = comex_bars["volume"].clip(lower=1.0).cumsum()
                cum_pv = (tp * comex_bars["volume"].clip(lower=1.0)).cumsum()
                comex_bars["vwap"] = cum_pv / cum_vol
                
                sig_bars = comex_bars[comex_bars["hhmm"] == "08:35"]
                if not sig_bars.empty:
                    sb = sig_bars.iloc[0]
                    sb_c = float(sb["close"])
                    sb_h = float(sb["high"])
                    sb_l = float(sb["low"])
                    sb_rng = sb_h - sb_l
                    sb_cl_loc = (sb_c - sb_l) / sb_rng if sb_rng > 0 else 0.5
                    sb_vwap = float(sb["vwap"])
                    
                    d1 = 0
                    if is_above_vah and sb_c > p_va["vah"] and sb_c > sb_vwap and sb_cl_loc >= 0.55:
                        d1 = 1
                    elif is_below_val and sb_c < p_va["val"] and sb_c < sb_vwap and sb_cl_loc <= 0.45:
                        d1 = -1
                        
                    if d1 != 0:
                        exec_bars = comex_bars[comex_bars["time"] > sb["time"]].reset_index(drop=True)
                        if len(exec_bars) >= 15:
                            entry_p = float(exec_bars.iloc[0]["open"])
                            # stop = 08:20-08:35 range * 0.5, clamped [3.0, 12.0] pts
                            m15_rng = float(comex_bars[comex_bars["hhmm"] <= "08:35"]["high"].max() - comex_bars[comex_bars["hhmm"] <= "08:35"]["low"].min())
                            stop_pts = float(np.clip(m15_rng * 0.5, 3.0, 12.0))
                            target_pts = stop_pts * 1.50
                            res = simulate_bracket(exec_bars, d1, entry_p, stop_pts, target_pts, max_bars=45)
                            trades_w1_comex_open.append({
                                "date_str": d_str, "year": d_obj.year, "direction": "long" if d1 == 1 else "short",
                                **res
                            })

        # -------------------------------------------------------------
        # Window 2: Macro Release Repricing (08:30 - 08:45 ET)
        # -------------------------------------------------------------
        macro_bars = day_bars[(day_bars["hhmm"] >= "08:30") & (day_bars["hhmm"] <= "13:30")].reset_index(drop=True)
        if len(macro_bars) >= 20:
            tp = (macro_bars["high"] + macro_bars["low"] + macro_bars["close"]) / 3.0
            cum_vol = macro_bars["volume"].clip(lower=1.0).cumsum()
            cum_pv = (tp * macro_bars["volume"].clip(lower=1.0)).cumsum()
            macro_bars["vwap"] = cum_pv / cum_vol
            
            sig_bars = macro_bars[macro_bars["hhmm"] == "08:45"]
            if not sig_bars.empty:
                sb = sig_bars.iloc[0]
                sb_c = float(sb["close"])
                sb_h = float(sb["high"])
                sb_l = float(sb["low"])
                sb_rng = sb_h - sb_l
                sb_cl_loc = (sb_c - sb_l) / sb_rng if sb_rng > 0 else 0.5
                sb_vwap = float(sb["vwap"])
                
                # Check momentum over the 15m release window
                m15_bars = macro_bars[macro_bars["hhmm"] <= "08:45"]
                m15_ret = (sb_c - float(m15_bars.iloc[0]["open"])) / float(m15_bars.iloc[0]["open"])
                
                d2 = 0
                if m15_ret >= 0.0015 and sb_cl_loc >= 0.65 and sb_c > sb_vwap and sb_c > p_va["vah"]:
                    d2 = 1
                elif m15_ret <= -0.0015 and sb_cl_loc <= 0.35 and sb_c < sb_vwap and sb_c < p_va["val"]:
                    d2 = -1
                    
                if d2 != 0:
                    exec_bars = macro_bars[macro_bars["time"] > sb["time"]].reset_index(drop=True)
                    if len(exec_bars) >= 15:
                        entry_p = float(exec_bars.iloc[0]["open"])
                        m15_rng = float(m15_bars["high"].max() - m15_bars["low"].min())
                        stop_pts = float(np.clip(m15_rng * 0.5, 3.0, 15.0))
                        target_pts = stop_pts * 1.50
                        res = simulate_bracket(exec_bars, d2, entry_p, stop_pts, target_pts, max_bars=45)
                        trades_w2_macro_0835.append({
                            "date_str": d_str, "year": d_obj.year, "direction": "long" if d2 == 1 else "short",
                            **res
                        })

        # -------------------------------------------------------------
        # Window 3: LBMA PM Fix at 10:14 ET (Filter Relaxation)
        # -------------------------------------------------------------
        # 10:00 - 10:14 bar
        fix_bars = day_bars[(day_bars["hhmm"] >= "10:00") & (day_bars["hhmm"] <= "10:14")]
        ib_bars = day_bars[(day_bars["hhmm"] >= "08:20") & (day_bars["hhmm"] <= "09:19")]
        lon_bars = day_bars[(day_bars["hhmm"] >= "03:00") & (day_bars["hhmm"] <= "08:19")]
        exec_fix = day_bars[(day_bars["hhmm"] >= "10:15") & (day_bars["hhmm"] <= "11:00")].reset_index(drop=True)
        
        if len(fix_bars) >= 10 and len(ib_bars) >= 40 and len(lon_bars) >= 60 and len(exec_fix) >= 15:
            fix_open = float(fix_bars.iloc[0]["open"])
            fix_close = float(fix_bars.iloc[-1]["close"])
            fix_high = float(fix_bars["high"].max())
            fix_low = float(fix_bars["low"].min())
            fix_range = fix_high - fix_low
            fix_cl_loc = (fix_close - fix_low) / fix_range if fix_range > 0 else 0.5
            fix_ret_pct = (fix_close - fix_open) / fix_open if fix_open > 0 else 0.0
            
            ib_high = float(ib_bars["high"].max())
            ib_low = float(ib_bars["low"].min())
            lon_high = float(lon_bars["high"].max())
            lon_low = float(lon_bars["low"].min())
            
            # Original Strict Logic (Long Only, requires ALL 3 barriers)
            orig_qualifies = (
                fix_ret_pct >= 0.001125
                and fix_cl_loc >= 0.70
                and fix_close > ib_high
                and fix_close > lon_high
                and fix_close > p_va["vah"]
            )
            if orig_qualifies:
                entry_p = float(exec_fix.iloc[0]["open"])
                stop_pts = float(np.clip(fix_range * 0.75, 3.0, 18.0))
                target_pts = stop_pts * 1.50
                res = simulate_bracket(exec_fix, 1, entry_p, stop_pts, target_pts, max_bars=45)
                trades_w3_fix_all_days.append({
                    "date_str": d_str, "year": d_obj.year, "direction": "long",
                    **res
                })
                
            # Relaxed Confluence: Long & Short, requires (Above VAH OR Above Lon High) + Above IB High
            d3 = 0
            if fix_ret_pct >= 0.0010 and fix_cl_loc >= 0.65 and fix_close > ib_high and (fix_close > p_va["vah"] or fix_close > lon_high):
                d3 = 1
            elif fix_ret_pct <= -0.0010 and fix_cl_loc <= 0.35 and fix_close < ib_low and (fix_close < p_va["val"] or fix_close < lon_low):
                d3 = -1
                
            if d3 != 0:
                entry_p = float(exec_fix.iloc[0]["open"])
                stop_pts = float(np.clip(fix_range * 0.75, 3.0, 18.0))
                target_pts = stop_pts * 1.50
                res = simulate_bracket(exec_fix, d3, entry_p, stop_pts, target_pts, max_bars=45)
                trades_w3_fix_relaxed.append({
                    "date_str": d_str, "year": d_obj.year, "direction": "long" if d3 == 1 else "short",
                    **res
                })

        # -------------------------------------------------------------
        # Window 4: London Cash Open (03:00 - 03:15 ET)
        # -------------------------------------------------------------
        lon_open_bars = day_bars[(day_bars["hhmm"] >= "03:00") & (day_bars["hhmm"] <= "06:00")].reset_index(drop=True)
        if len(lon_open_bars) >= 20:
            tp = (lon_open_bars["high"] + lon_open_bars["low"] + lon_open_bars["close"]) / 3.0
            cum_vol = lon_open_bars["volume"].clip(lower=1.0).cumsum()
            cum_pv = (tp * lon_open_bars["volume"].clip(lower=1.0)).cumsum()
            lon_open_bars["vwap"] = cum_pv / cum_vol
            
            sig_bars = lon_open_bars[lon_open_bars["hhmm"] == "03:15"]
            if not sig_bars.empty:
                sb = sig_bars.iloc[0]
                sb_c = float(sb["close"])
                sb_h = float(sb["high"])
                sb_l = float(sb["low"])
                sb_rng = sb_h - sb_l
                sb_cl_loc = (sb_c - sb_l) / sb_rng if sb_rng > 0 else 0.5
                sb_vwap = float(sb["vwap"])
                
                # Check 03:00-03:15 return
                m15 = lon_open_bars[lon_open_bars["hhmm"] <= "03:15"]
                ret15 = (sb_c - float(m15.iloc[0]["open"])) / float(m15.iloc[0]["open"])
                
                d4 = 0
                if ret15 >= 0.0010 and sb_cl_loc >= 0.65 and sb_c > sb_vwap and sb_c > p_va["vah"]:
                    d4 = 1
                elif ret15 <= -0.0010 and sb_cl_loc <= 0.35 and sb_c < sb_vwap and sb_c < p_va["val"]:
                    d4 = -1
                    
                if d4 != 0:
                    exec_bars = lon_open_bars[lon_open_bars["time"] > sb["time"]].reset_index(drop=True)
                    if len(exec_bars) >= 15:
                        entry_p = float(exec_bars.iloc[0]["open"])
                        m15_rng = float(m15["high"].max() - m15["low"].min())
                        stop_pts = float(np.clip(m15_rng * 0.5, 3.0, 12.0))
                        target_pts = stop_pts * 1.50
                        res = simulate_bracket(exec_bars, d4, entry_p, stop_pts, target_pts, max_bars=45)
                        trades_w4_london_0315.append({
                            "date_str": d_str, "year": d_obj.year, "direction": "long" if d4 == 1 else "short",
                            **res
                        })

    # Summaries
    summarize_trades(trades_w1_comex_open, "Window 1: COMEX Open Breakout (08:20-08:35 ET)")
    summarize_trades(trades_w2_macro_0835, "Window 2: US Macro Release Momentum (08:30-08:45 ET)")
    summarize_trades(trades_w3_fix_all_days, "Window 3: LBMA Fix H14 (Original Strict, All Weekdays)")
    summarize_trades(trades_w3_fix_relaxed, "Window 3: LBMA Fix Relaxed (Long + Short Confluence)")
    summarize_trades(trades_w4_london_0315, "Window 4: London Cash Open (03:00-03:15 ET)")

if __name__ == "__main__":
    test_all_windows()
