#!/usr/bin/env python3
"""
Evaluate Track B: 8:30 AM Macro Driver Filters on the 543-Trade Ensemble.
Tests whether filtering or sizing based on 08:30 macro shock alignment
improves ensemble performance while respecting trade preservation.
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research_macro_830_conditioning import extract_830_metrics

def main():
    mkv_830_p = ROOT / "data/processed/nq_daily_830_macro_metrics_2020_2026.parquet"
    if mkv_830_p.exists():
        df_830 = pd.read_parquet(mkv_830_p)
    else:
        df_830 = extract_830_metrics()
    
    trades_p = ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"
    df = pd.read_parquet(trades_p)
    m = df.merge(df_830, on="date_str", how="left")
    
    def calc_stats(name: str, t: pd.DataFrame):
        t_sorted = t.sort_values("entry_time").reset_index(drop=True).copy()
        t_sorted["cum"] = t_sorted["pnl"].cumsum()
        peak = t_sorted["cum"].cummax()
        t_sorted["dd"] = peak - t_sorted["cum"]
        max_dd = t_sorted["dd"].max()
        tot_pnl = t_sorted["pnl"].sum()
        pos = t_sorted.loc[t_sorted["pnl"] > 0, "pnl"].sum()
        neg = abs(t_sorted.loc[t_sorted["pnl"] <= 0, "pnl"].sum())
        pf = pos / neg if neg > 0 else np.nan
        wr = (t_sorted["pnl"] > 0).mean() * 100
        
        dev = t_sorted[t_sorted["year"] <= 2024]
        dev_pos = dev.loc[dev["pnl"] > 0, "pnl"].sum()
        dev_neg = abs(dev.loc[dev["pnl"] <= 0, "pnl"].sum())
        dev_pf = dev_pos / dev_neg if dev_neg > 0 else np.nan
        dev_net = dev["pnl"].sum()
        dev_wr = (dev["pnl"] > 0).mean() * 100
        
        oos = t_sorted[t_sorted["year"] >= 2025]
        oos_pos = oos.loc[oos["pnl"] > 0, "pnl"].sum()
        oos_neg = abs(oos.loc[oos["pnl"] <= 0, "pnl"].sum())
        oos_pf = oos_pos / oos_neg if oos_neg > 0 else np.nan
        oos_net = oos["pnl"].sum()
        oos_wr = (oos["pnl"] > 0).mean() * 100
        
        print(f"=== {name} ===")
        print(f"  FULL (2021-2026): {len(t_sorted):>3} trades | WR: {wr:>5.2f}% | PF: {pf:>4.2f} | Net: ${tot_pnl:>9,.2f} | MaxDD: ${max_dd:>7,.2f} | Ret/DD: {tot_pnl/max_dd:>4.2f}x")
        print(f"  DEV  (2021-2024): {len(dev):>3} trades | WR: {dev_wr:>5.2f}% | PF: {dev_pf:>4.2f} | Net: ${dev_net:>9,.2f}")
        print(f"  OOS  (2025-2026): {len(oos):>3} trades | WR: {oos_wr:>5.2f}% | PF: {oos_pf:>4.2f} | Net: ${oos_net:>9,.2f}\n")

    print("\n" + "=" * 80)
    print("  EMPIRICAL EVALUATION: TRACK B (8:30 AM MACRO DRIVER FILTERS)")
    print("=" * 80 + "\n")

    # Baseline (Option 2 standardized)
    calc_stats("1. Standardized Option 2 Baseline (543 Trades, Markov Adaptive Sizing)", m)

    # Candidate B1: Hard Gate Strategy 1 when opposing 08:30 Macro Release
    # i.e., drop the 18 trades that fought 08:30 macro
    m["trade_dir_int"] = m["direction"].apply(lambda d: 1 if d == "long" else -1)
    is_s1 = m["strategy"].str.contains("Strategy 1")
    is_opposing_s1 = is_s1 & m["is_macro_release"] & (m["spike_dir"] != 0) & (m["trade_dir_int"] != m["spike_dir"])
    
    b1_df = m[~is_opposing_s1].copy()
    calc_stats("2. Candidate B1: Filter Opposing S1 Trades (Prune 18 Trades Fighting 08:30)", b1_df)

    # Candidate B2: Adaptive Macro Sizing (0.50x when S1 opposes 08:30, preserving 100% of trades)
    b2_df = m.copy()
    b2_mult = np.where(is_opposing_s1, 0.50, 1.00)
    b2_df["pnl"] = b2_df["pnl"] * b2_mult
    calc_stats("3. Candidate B2: Adaptive Macro Sizing (0.50x S1 When Opposing 08:30, 100% Trades Kept)", b2_df)

    # Candidate B3: Macro Alignment Boost (1.25x when S1 aligns with 08:30, 0.75x when opposing)
    is_aligned_s1 = is_s1 & m["is_macro_release"] & (m["spike_dir"] != 0) & (m["trade_dir_int"] == m["spike_dir"])
    b3_df = m.copy()
    b3_mult = np.ones(len(b3_df))
    b3_mult = np.where(is_aligned_s1, 1.25, b3_mult)
    b3_mult = np.where(is_opposing_s1, 0.50, b3_mult)
    b3_df["pnl"] = b3_df["pnl"] * b3_mult
    calc_stats("4. Candidate B3: Macro Alignment Asymmetric Sizing (1.25x Aligned, 0.50x Opposing)", b3_df)

if __name__ == "__main__":
    main()
