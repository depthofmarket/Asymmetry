#!/usr/bin/env python3
"""
Cache Point-in-Time Daily 08:30 AM Macro Release Metrics (2020-2026).
Implements Track B telemetry from Jeffy Motta's AntiAchismo Quant Masterclass.
Zero-lookahead: At 09:45 ET and 10:15 ET, the 08:30 AM release spike is fully completed history.
"""

from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

def main():
    print("Loading NQ 1m bars...")
    df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
    df_nq["date_str"] = df_nq["time"].dt.strftime("%Y-%m-%d")
    df_nq["hhmm"] = df_nq["time"].dt.strftime("%H:%M")
    df_nq = df_nq[df_nq["date_str"] >= "2020-01-01"].copy()

    records = []
    for d_str, g in df_nq.groupby("date_str"):
        ovn = g[(g["hhmm"] >= "00:00") & (g["hhmm"] <= "08:29")]
        spike = g[(g["hhmm"] >= "08:30") & (g["hhmm"] <= "08:34")]
        pre_cash = g[(g["hhmm"] >= "08:35") & (g["hhmm"] <= "09:29")]

        if len(ovn) < 60 or len(spike) < 4:
            continue

        ovn_h = float(ovn["high"].max())
        ovn_l = float(ovn["low"].min())
        ovn_rng = ovn_h - ovn_l
        ovn_c_pre = float(ovn.iloc[-1]["close"])

        pre_vol = float(ovn["volume"].tail(30).mean()) * 5.0
        spike_vol = float(spike["volume"].sum())
        vol_ratio = spike_vol / pre_vol if pre_vol > 0 else 1.0

        spike_o = float(spike.iloc[0]["open"])
        spike_c = float(spike.iloc[-1]["close"])
        spike_h = float(spike["high"].max())
        spike_l = float(spike["low"].min())
        spike_rng = spike_h - spike_l
        spike_ret_pct = (spike_c - spike_o) / spike_o * 100.0

        is_macro_release = (vol_ratio >= 2.50) or (spike_rng >= 50.0)

        spike_dir = 0
        if is_macro_release:
            if spike_c > ovn_c_pre and spike_ret_pct > 0.15:
                spike_dir = 1
            elif spike_c < ovn_c_pre and spike_ret_pct < -0.15:
                spike_dir = -1

        pre_cash_c = float(pre_cash.iloc[-1]["close"]) if len(pre_cash) > 10 else spike_c
        pre_cash_drift = (pre_cash_c - spike_c) / spike_c * 100.0

        records.append({
            "date_str": d_str,
            "ovn_range": round(ovn_rng, 2),
            "spike_vol_ratio": round(vol_ratio, 2),
            "spike_rng": round(spike_rng, 2),
            "spike_ret_pct": round(spike_ret_pct, 3),
            "is_macro_release": is_macro_release,
            "spike_dir": spike_dir,
            "pre_cash_drift": round(pre_cash_drift, 3),
        })

    out_df = pd.DataFrame(records)
    out_p = ROOT / "data/processed/nq_daily_830_macro_metrics_2020_2026.parquet"
    out_df.to_parquet(out_p, index=False)
    print(f"Saved {len(out_df)} days of 08:30 macro metrics to {out_p.name}.")
    print(f"Total macro release days: {out_df['is_macro_release'].sum()} ({out_df['is_macro_release'].mean()*100:.1f}%)")

if __name__ == "__main__":
    main()
