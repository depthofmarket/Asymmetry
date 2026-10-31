#!/usr/bin/env python3
"""
Test Candidate Frequency Expansion across:
1. 4-Index Equity Basket: NQ (MNQ), ES (MES), YM (MYM), RTY (M2K) at 09:45 ET
2. Crude Oil (CL / MCL) Pit Opening Range at 09:15 ET (09:00 RTH floor open)
3. Commodity Energy Weekly Inventory Breakout (CL 10:30 ET Wednesday EIA release)
4. London Session Morning Breakout (03:00 - 04:00 ET) on NQ, ES, and Gold
"""

from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.convert_and_evaluate_multi_asset_cqg_2020_2026 import (
    CQG_EXPORTS,
    compute_daily_or15_dir,
    simulate_asset_trades,
)

def evaluate_equity_indices():
    print("=== EVALUATING 4-INDEX EQUITY BASKET (2021-2026) ===")
    df_es = pd.read_parquet(ROOT / "data/raw/es_1m_2020_2026_cqg_et.parquet")
    df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
    df_ym = pd.read_parquet(ROOT / "data/raw/ym_1m_2020_2026_et.parquet")
    df_rty = pd.read_parquet(ROOT / "data/raw/rty_1m_2020_2026_et.parquet")

    es_dir = compute_daily_or15_dir(df_es)
    nq_dir = compute_daily_or15_dir(df_nq)

    m_df = pd.read_parquet(ROOT / "data/processed/macro_context/morning_cross_asset_features_0945.parquet")
    macro_map = {}
    for _, r in m_df.iterrows():
        vx_c = (
            float(r["vx_or15_change_pct"])
            if pd.notna(r.get("vx_or15_change_pct"))
            else (float(r["vix_spot_or15_change_pct"]) if pd.notna(r.get("vix_spot_or15_change_pct")) else float("nan"))
        )
        tk_m = float(r["tick_or15_mean"]) if pd.notna(r.get("tick_or15_mean")) else float("nan")
        macro_map[str(r["date_str"])] = (vx_c, tk_m)

    v_1h_path = ROOT / "data/raw/vix_spot_1h_2026_et.csv"
    if v_1h_path.exists():
        v_1h = pd.read_csv(v_1h_path)
        v_1h["time"] = pd.to_datetime(v_1h["time"], utc=True).dt.tz_convert("America/New_York")
        v_1h["date_str"] = v_1h["time"].dt.strftime("%Y-%m-%d")
        v_1h["hhmm"] = v_1h["time"].dt.strftime("%H:%M")
        for d_str, g in v_1h.groupby("date_str"):
            if d_str not in macro_map or np.isnan(macro_map[d_str][0]):
                b9 = g[g["hhmm"] == "09:00"]
                if not b9.empty:
                    o, c = float(b9.iloc[0]["open"]), float(b9.iloc[-1]["close"])
                    macro_map[d_str] = ((c - o) / o * 100.0 if o > 0 else 0.0, float("nan"))

    dfs = {"NQ": df_nq, "ES": df_es, "YM": df_ym, "RTY": df_rty}
    results = {}
    trade_dfs = []

    for sym in ["NQ", "ES", "YM", "RTY"]:
        spec = next(x for x in CQG_EXPORTS if x["sym"] == sym)
        df_raw = dfs[sym]
        t_raw = simulate_asset_trades(
            df_raw, spec, require_with_gap=True, es_dir_map=es_dir, nq_dir_map=nq_dir, macro_map=macro_map
        )
        t_gated = t_raw[t_raw["full_gate_ok"] & (t_raw["date_str"] >= "2021-01-01")].copy().reset_index(drop=True)
        if not t_gated.empty:
            wr = float((t_gated["net_dollars_micro"] > 0).mean() * 100.0)
            pnl = float(t_gated["net_dollars_micro"].sum())
            pos = float(t_gated.loc[t_gated["net_dollars_micro"] > 0, "net_dollars_micro"].sum())
            neg = float(abs(t_gated.loc[t_gated["net_dollars_micro"] <= 0, "net_dollars_micro"].sum()))
            pf = pos / neg if neg > 0 else float("inf")
            cum = t_gated["net_dollars_micro"].cumsum()
            mdd = float((cum - cum.cummax()).min())
            results[sym] = {
                "trades": len(t_gated),
                "active_days": t_gated["date_str"].nunique(),
                "wr": wr,
                "pf": pf,
                "pnl": pnl,
                "mdd": mdd,
            }
            trade_dfs.append(t_gated)
            print(f"  {sym} ({spec['micro']}): {len(t_gated)} trades ({t_gated['date_str'].nunique()} days) | WR: {wr:.1f}% | PF: {pf:.2f} | PnL: ${pnl:,.2f} | MaxDD: ${mdd:,.2f}")

    # Combined Basket
    all_eq = pd.concat(trade_dfs, ignore_index=True)
    all_eq_days = all_eq["date_str"].nunique()
    print(f"\nTotal Equities Basket ({len(all_eq)} trades across {all_eq_days} active days out of ~1,450 RTH days):")
    print(f"  Frequency: {all_eq_days / 5.83:.1f} active days/yr ({len(all_eq) / 5.83:.1f} trades/yr)")
    return results

if __name__ == "__main__":
    evaluate_equity_indices()
