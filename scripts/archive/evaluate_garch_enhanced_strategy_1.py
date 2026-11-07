#!/usr/bin/env python3
"""
Evaluate GARCH(1,1) MVT Volatility Filter & Dynamic Brackets on Strategy 1 (09:45 ET).
Compares:
1. Baseline Strategy 1 (Fixed Brackets, No GARCH Gate)
2. GARCH MVT Overextension Filter (Drop Z > 2.0 DP)
3. GARCH MVT Sweet-Spot Sizing (Boost size in 0.5-1.5 DP sweet spot)
4. Multi-Era Stability (2021-2024 Dev vs 2025-2026 Holdout)
"""

from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from arch import arch_model

ROOT = Path(__file__).resolve().parents[1]

# 1. Load Trades & NQ Data
df_trades = pd.read_parquet(ROOT / "data/processed/unified_three_strategy_portfolio_trades_2021_2026.parquet")
s1_trades = df_trades[df_trades["strategy"].str.contains("Strategy 1")].copy()
s1_trades["entry_time"] = pd.to_datetime(s1_trades["entry_time"])
s1_trades["date_str"] = s1_trades["entry_time"].dt.strftime("%Y-%m-%d")

df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
df_nq["date_str"] = df_nq["time"].dt.strftime("%Y-%m-%d")
df_nq["hhmm"] = df_nq["time"].dt.strftime("%H:%M")

# 2. Compute Point-in-Time Daily GARCH(1,1)
daily_closes = df_nq.groupby("date_str")["close"].last()
daily_ret = (np.log(daily_closes / daily_closes.shift(1)).dropna() * 100.0).to_frame(name="ret")
all_dates = daily_ret.index.tolist()
garch_sigma = pd.Series(index=daily_ret.index, dtype=float)

current_params = None
last_refit_idx = -100

for idx in range(252, len(all_dates)):
    if current_params is None or (idx - last_refit_idx) >= 21:
        train_window = daily_ret["ret"].iloc[max(0, idx-500):idx]
        am = arch_model(train_window, vol="Garch", p=1, q=1, dist="Normal", rescale=False)
        res = am.fit(disp="off", show_warning=False)
        current_params = res.params
        last_refit_idx = idx
    
    prev_ret = daily_ret["ret"].iloc[idx-1]
    prev_sig = garch_sigma.iloc[idx-1] if (idx > 252 and np.isfinite(garch_sigma.iloc[idx-1])) else daily_ret["ret"].iloc[max(0, idx-21):idx].std()
    omega = current_params.get("omega", 0.05)
    alpha = current_params.get("alpha[1]", 0.08)
    beta = current_params.get("beta[1]", 0.88)
    sig2 = omega + alpha * (prev_ret ** 2) + beta * (prev_sig ** 2)
    garch_sigma.iloc[idx] = np.sqrt(max(sig2, 1e-4))

# 3. Enrich Trades
unique_trade_dates = s1_trades["date_str"].unique()
bars_by_date = {d: g.reset_index(drop=True) for d, g in df_nq[df_nq["date_str"].isin(unique_trade_dates)].groupby("date_str")}

enriched = []
for _, tr in s1_trades.iterrows():
    d_str = tr["date_str"]
    if d_str not in garch_sigma or d_str not in bars_by_date:
        continue
    cond_vol_pct = garch_sigma.loc[d_str]
    if not np.isfinite(cond_vol_pct):
        continue
    g = bars_by_date[d_str]
    rth_bars = g[(g["hhmm"] >= "09:30") & (g["hhmm"] <= "09:45")]
    if len(rth_bars) < 10:
        continue
    cum_vol = rth_bars["volume"].sum()
    vwap_0945 = float((rth_bars["close"] * rth_bars["volume"]).sum() / cum_vol) if cum_vol > 0 else float(rth_bars["close"].mean())
    entry_p = float(rth_bars.iloc[-1]["close"])
    sigma_day_pts = entry_p * (cond_vol_pct / 100.0)
    sigma_open_pts = sigma_day_pts * np.sqrt(15.0 / 390.0)
    diff_pts = entry_p - vwap_0945
    direction_val = 1 if tr["direction"] == "long" else -1
    z_score_open = (diff_pts * direction_val) / max(sigma_open_pts, 1.0)
    
    row = dict(tr)
    row["cond_vol_pct"] = cond_vol_pct
    row["vwap_0945"] = vwap_0945
    row["entry_p"] = entry_p
    row["sigma_day_pts"] = sigma_day_pts
    row["sigma_open_pts"] = sigma_open_pts
    row["z_score_open"] = z_score_open
    enriched.append(row)

df_all = pd.DataFrame(enriched)

def print_metrics(name: str, df: pd.DataFrame):
    pos = df.loc[df["net_dollars_micro"] > 0, "net_dollars_micro"].sum()
    neg = abs(df.loc[df["net_dollars_micro"] <= 0, "net_dollars_micro"].sum())
    pf = pos / neg if neg > 0 else np.nan
    wr = (df["net_dollars_micro"] > 0).mean() * 100
    net = df["net_dollars_micro"].sum()
    
    # Era Breakdown
    dev = df[df["year"] <= 2024]
    dev_pf = dev.loc[dev["net_dollars_micro"] > 0, "net_dollars_micro"].sum() / abs(dev.loc[dev["net_dollars_micro"] <= 0, "net_dollars_micro"].sum())
    dev_net = dev["net_dollars_micro"].sum()
    
    oos = df[df["year"] >= 2025]
    oos_pf = oos.loc[oos["net_dollars_micro"] > 0, "net_dollars_micro"].sum() / abs(oos.loc[oos["net_dollars_micro"] <= 0, "net_dollars_micro"].sum())
    oos_net = oos["net_dollars_micro"].sum()
    
    print(f"=== {name} ===")
    print(f"  FULL (2021-2026): {len(df):>3} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net: ${net:>8,.2f}")
    print(f"  DEV  (2021-2024): {len(dev):>3} trades | WR: {(dev['net_dollars_micro']>0).mean()*100:>5.1f}% | PF: {dev_pf:>4.2f} | Net: ${dev_net:>8,.2f}")
    print(f"  OOS  (2025-2026): {len(oos):>3} trades | WR: {(oos['net_dollars_micro']>0).mean()*100:>5.1f}% | PF: {oos_pf:>4.2f} | Net: ${oos_net:>8,.2f}\n")

print("\n" + "=" * 75)
print("  EMPIRICAL VALIDATION: GARCH(1,1) MVT FILTERS ON STRATEGY 1")
print("=" * 75 + "\n")

print_metrics("1. Baseline Strategy 1 (No GARCH Filter)", df_all)

# Candidate A: Hard Exhaustion Filter (Drop Z > 2.0 DP)
cand_a = df_all[df_all["z_score_open"] <= 2.0].copy()
print_metrics("2. Candidate A: Drop Overextended Exhaustions (Z <= 2.0 DP)", cand_a)

# Candidate B: Sweet-Spot Priority (Require Z >= 0.3 DP and Z <= 2.2 DP)
cand_b = df_all[(df_all["z_score_open"] >= 0.3) & (df_all["z_score_open"] <= 2.2)].copy()
print_metrics("3. Candidate B: Sweet-Spot Only (0.3 DP <= Z <= 2.2 DP)", cand_b)

# Candidate C: AntiAchismo Asymmetric Volatility Sizing:
# In Sweet Spot (0.5 - 2.0 DP), scale allocation by 1.25x. In low momentum (<0.5 DP), scale by 0.75x.
df_scaled = df_all[df_all["z_score_open"] <= 2.2].copy()
multiplier = np.where((df_scaled["z_score_open"] >= 0.5) & (df_scaled["z_score_open"] <= 2.0), 1.25, 0.75)
df_scaled["net_dollars_micro"] = df_scaled["net_dollars_micro"] * multiplier
print_metrics("4. Candidate C: Dynamic GARCH Allocation (Boost Sweet Spot, Cut Chop)", df_scaled)
