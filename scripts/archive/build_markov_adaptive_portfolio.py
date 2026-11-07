#!/usr/bin/env python3
"""
Build the Standardized Option 2 (Markov Adaptive Sizing) Portfolio Dataset.
Preserves 100% of the 543 ensemble trades (2021-2026).
Applies point-in-time Markov volatility regime sizing:
- low_vol:  1.25x sizing across all strategies
- mid_vol:  1.00x baseline sizing
- high_vol: 0.50x sizing on Strategy 3 (Pre-Market Macro Momentum), 1.00x on Strategy 1 & 2
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

def main():
    trades_p = ROOT / "data/processed/unified_three_strategy_garch_portfolio_trades_2021_2026.parquet"
    mkv_p = ROOT / "data/processed/nq_daily_markov_regimes_2020_2026.parquet"
    out_p = ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"

    print(f"Loading trades from {trades_p.name}...")
    df = pd.read_parquet(trades_p)
    print(f"Loading Markov regimes from {mkv_p.name}...")
    mkv = pd.read_parquet(mkv_p)

    # Merge point-in-time daily Markov regime
    m = df.merge(
        mkv[[
            "date_str",
            "markov_state",
            "markov_state_label",
            "markov_state_confidence",
            "markov_prob_low_vol",
            "markov_prob_mid_vol",
            "markov_prob_high_vol",
        ]],
        on="date_str",
        how="left"
    )

    # Apply Option 2 Adaptive Multipliers
    is_s3 = m["strategy"].str.contains("Strategy 3")
    is_low = m["markov_state_label"] == "low_vol"
    is_high = m["markov_state_label"] == "high_vol"

    mult = np.ones(len(m), dtype=float)
    mult = np.where(is_low, 1.25, mult)
    mult = np.where(is_high & is_s3, 0.50, mult)

    m["markov_sizing_mult"] = mult
    m["scaled_pnl"] = m["net_dollars_micro"] * mult
    m["pnl"] = m["scaled_pnl"]
    m["cum_pnl"] = m["pnl"].cumsum()
    m["dd"] = m["cum_pnl"].cummax() - m["cum_pnl"]

    m.to_parquet(out_p, index=False)
    print(f"Saved {len(m)} trades to {out_p.name}.\n")

    # Metrics
    tot_trades = len(m)
    tot_pnl = m["pnl"].sum()
    pos = m.loc[m["pnl"] > 0, "pnl"].sum()
    neg = abs(m.loc[m["pnl"] <= 0, "pnl"].sum())
    pf = pos / neg if neg > 0 else np.nan
    wr = (m["pnl"] > 0).mean() * 100
    max_dd = m["dd"].max()

    dev = m[m["year"] <= 2024]
    dev_pos = dev.loc[dev["pnl"] > 0, "pnl"].sum()
    dev_neg = abs(dev.loc[dev["pnl"] <= 0, "pnl"].sum())
    dev_pf = dev_pos / dev_neg if dev_neg > 0 else np.nan
    dev_net = dev["pnl"].sum()
    dev_wr = (dev["pnl"] > 0).mean() * 100

    oos = m[m["year"] >= 2025]
    oos_pos = oos.loc[oos["pnl"] > 0, "pnl"].sum()
    oos_neg = abs(oos.loc[oos["pnl"] <= 0, "pnl"].sum())
    oos_pf = oos_pos / oos_neg if oos_neg > 0 else np.nan
    oos_net = oos["pnl"].sum()
    oos_wr = (oos["pnl"] > 0).mean() * 100

    print("=" * 75)
    print("  STANDARDIZED OPTION 2 ENSEMBLE METRICS (MARKOV ADAPTIVE SIZING)")
    print("=" * 75)
    print(f"  FULL (2021-2026): {tot_trades} trades | WR: {wr:.2f}% | PF: {pf:.2f} | Net: ${tot_pnl:,.2f} | MaxDD: ${max_dd:,.2f} | Ret/DD: {tot_pnl/max_dd:.2f}x")
    print(f"  DEV  (2021-2024): {len(dev)} trades | WR: {dev_wr:.2f}% | PF: {dev_pf:.2f} | Net: ${dev_net:,.2f}")
    print(f"  OOS  (2025-2026): {len(oos)} trades | WR: {oos_wr:.2f}% | PF: {oos_pf:.2f} | Net: ${oos_net:,.2f}")
    print("=" * 75 + "\n")

    # Strategy breakdown
    for strat in ["Strategy 1", "Strategy 2", "Strategy 3"]:
        sub = m[m["strategy"].str.contains(strat)]
        sub_pos = sub.loc[sub["pnl"] > 0, "pnl"].sum()
        sub_neg = abs(sub.loc[sub["pnl"] <= 0, "pnl"].sum())
        sub_pf = sub_pos / sub_neg if sub_neg > 0 else np.nan
        sub_wr = (sub["pnl"] > 0).mean() * 100
        print(f"  {strat:30s}: {len(sub):3d} trades | WR: {sub_wr:5.1f}% | PF: {sub_pf:4.2f} | Net: ${sub['pnl'].sum():8.2f}")

if __name__ == "__main__":
    main()
