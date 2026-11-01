#!/usr/bin/env python3
"""Evaluate Upgraded 3-Window Ensemble with GARCH MVT Sweet-Spot Gate."""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

# Load unified trades
df_comb = pd.read_parquet(ROOT / "data/processed/unified_three_strategy_portfolio_trades_2021_2026.parquet")
s1 = df_comb[df_comb["strategy"].str.contains("Strategy 1")].copy()
s2 = df_comb[df_comb["strategy"].str.contains("Strategy 2")].copy()
s3 = df_comb[df_comb["strategy"].str.contains("Strategy 3")].copy()

# Load GARCH forecasts
garch = pd.read_parquet(ROOT / "data/processed/nq_daily_garch_forecasts_2020_2026.parquet")
garch_map = dict(zip(garch["date_str"], garch["garch_cond_vol_pct"]))

# Load NQ 1m bars for VWAP at 09:45
df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
df_nq["date_str"] = df_nq["time"].dt.strftime("%Y-%m-%d")
df_nq["hhmm"] = df_nq["time"].dt.strftime("%H:%M")

bars_by_date = {d: g.reset_index(drop=True) for d, g in df_nq[df_nq["date_str"].isin(s1["date_str"].unique())].groupby("date_str")}

s1_kept = []
for _, tr in s1.iterrows():
    d_str = tr["date_str"]
    if d_str not in garch_map or d_str not in bars_by_date:
        s1_kept.append(tr)
        continue
    g = bars_by_date[d_str]
    rth_bars = g[(g["hhmm"] >= "09:30") & (g["hhmm"] <= "09:45")]
    if len(rth_bars) < 10:
        s1_kept.append(tr)
        continue
    cum_vol = rth_bars["volume"].sum()
    vwap_0945 = float((rth_bars["close"] * rth_bars["volume"]).sum() / cum_vol) if cum_vol > 0 else float(rth_bars["close"].mean())
    entry_p = float(rth_bars.iloc[-1]["close"])
    sigma_open_pts = entry_p * (garch_map[d_str] / 100.0) * np.sqrt(15.0 / 390.0)
    diff_pts = entry_p - vwap_0945
    direction_val = 1 if tr["direction"] == "long" else -1
    z_score_open = (diff_pts * direction_val) / max(sigma_open_pts, 1.0)
    
    # Candidate B filter: 0.3 <= z_score <= 2.2
    if 0.3 <= z_score_open <= 2.2:
        s1_kept.append(tr)

df_s1_b = pd.DataFrame(s1_kept)

# Combine with S2 and S3
df_ensemble_b = pd.concat([df_s1_b, s2, s3], ignore_index=True)
df_ensemble_b["entry_time"] = pd.to_datetime(df_ensemble_b["entry_time"])
df_ensemble_b = df_ensemble_b.sort_values("entry_time").reset_index(drop=True)

df_ensemble_b["cum_pnl"] = df_ensemble_b["net_dollars_micro"].cumsum()
peak = df_ensemble_b["cum_pnl"].cummax()
df_ensemble_b["dd"] = peak - df_ensemble_b["cum_pnl"]
max_dd = df_ensemble_b["dd"].max()
tot_pnl = df_ensemble_b["net_dollars_micro"].sum()
pos = df_ensemble_b.loc[df_ensemble_b["net_dollars_micro"] > 0, "net_dollars_micro"].sum()
neg = abs(df_ensemble_b.loc[df_ensemble_b["net_dollars_micro"] <= 0, "net_dollars_micro"].sum())
pf = pos / neg
wr = (df_ensemble_b["net_dollars_micro"] > 0).mean() * 100

print("=" * 72)
print("  UPGRADED 3-WINDOW ENSEMBLE WITH CANDIDATE B (GARCH MVT SWEET-SPOT)")
print("=" * 72)
print(f"Total Trades: {len(df_ensemble_b)} trades (~{len(df_ensemble_b)/5.8:.1f}/yr, ~{len(df_ensemble_b)/70:.1f}/mo)")
print(f"Win Rate:     {wr:.1f}%  (Baseline: 54.9%)")
print(f"Profit Factor:{pf:.2f}  (Baseline: 1.47)")
print(f"Net P&L:      ${tot_pnl:,.2f}  (Baseline: $12,771.88)")
print(f"Max Drawdown: ${max_dd:,.2f}  (Baseline: $1,768.47)")
print(f"Profit/MaxDD: {tot_pnl / max_dd:.2f}x  (Baseline: 7.22x)")
print("=" * 72)

# Save upgraded ensemble dataset
out_p = ROOT / "data/processed/unified_three_strategy_garch_portfolio_trades_2021_2026.parquet"
df_ensemble_b.to_parquet(out_p, index=False)
print(f"Saved upgraded portfolio dataset to {out_p}")
