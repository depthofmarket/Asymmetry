#!/usr/bin/env python3
"""
Research Script: Point-in-Time GARCH(1,1) / GJR-GARCH Modeling & MVT Band Analysis (H18)
Evaluates whether GARCH-derived Desvio Padrao (DP) bands identify exhaustion in Strategy 1 (09:45 ET).
"""

from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from arch import arch_model

ROOT = Path(__file__).resolve().parents[1]

# 1. Load Strategy 1 trades
df_trades = pd.read_parquet(ROOT / "data/processed/unified_three_strategy_portfolio_trades_2021_2026.parquet")
s1_trades = df_trades[df_trades["strategy"].str.contains("Strategy 1")].copy()
s1_trades["entry_time"] = pd.to_datetime(s1_trades["entry_time"])
s1_trades["date_str"] = s1_trades["entry_time"].dt.strftime("%Y-%m-%d")

# 2. Load NQ 1m bars
df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
df_nq["date_str"] = df_nq["time"].dt.strftime("%Y-%m-%d")
df_nq["hhmm"] = df_nq["time"].dt.strftime("%H:%M")

print(f"Loaded {len(s1_trades)} Strategy 1 trades across {s1_trades['date_str'].nunique()} days.", flush=True)

# 3. Compute daily returns for GARCH calibration
daily_closes = df_nq.groupby("date_str")["close"].last()
daily_ret = (np.log(daily_closes / daily_closes.shift(1)).dropna() * 100.0).to_frame(name="ret")

# Calibration of GARCH(1,1) on rolling 252-day basis, refit monthly (every 21 days)
all_dates = daily_ret.index.tolist()
garch_sigma = pd.Series(index=daily_ret.index, dtype=float)

# Pre-calibrate on initial 500 days
current_params = None
last_refit_idx = -100

for idx in range(252, len(all_dates)):
    d_str = all_dates[idx]
    # Check if refit needed (monthly = 21 trading days)
    if current_params is None or (idx - last_refit_idx) >= 21:
        train_window = daily_ret["ret"].iloc[max(0, idx-500):idx]
        am = arch_model(train_window, vol="Garch", p=1, q=1, dist="Normal", rescale=False)
        res = am.fit(disp="off", show_warning=False)
        current_params = res.params
        last_refit_idx = idx
    
    # 1-step ahead forecast: sigma_t^2 = omega + alpha * eps_{t-1}^2 + beta * sigma_{t-1}^2
    # arch forecast at idx using information strictly prior to idx
    prev_ret = daily_ret["ret"].iloc[idx-1]
    prev_sig = garch_sigma.iloc[idx-1] if (idx > 252 and np.isfinite(garch_sigma.iloc[idx-1])) else daily_ret["ret"].iloc[max(0, idx-21):idx].std()
    
    omega = current_params.get("omega", 0.05)
    alpha = current_params.get("alpha[1]", 0.08)
    beta = current_params.get("beta[1]", 0.88)
    
    sig2 = omega + alpha * (prev_ret ** 2) + beta * (prev_sig ** 2)
    garch_sigma.iloc[idx] = np.sqrt(max(sig2, 1e-4))

print("GARCH conditional volatility series calibrated.", flush=True)

# 4. Now compute intraday MVT_0 (Session VWAP at 09:45) and Entry Distance in GARCH Sigmas
unique_trade_dates = s1_trades["date_str"].unique()
bars_by_date = {d: g.reset_index(drop=True) for d, g in df_nq[df_nq["date_str"].isin(unique_trade_dates)].groupby("date_str")}

enriched_trades = []
for _, tr in s1_trades.iterrows():
    d_str = tr["date_str"]
    if d_str not in garch_sigma or d_str not in bars_by_date:
        continue
    cond_vol_pct = garch_sigma.loc[d_str]
    if not np.isfinite(cond_vol_pct):
        continue
        
    g = bars_by_date[d_str]
    # RTH session bars up to 09:45:00
    rth_bars = g[(g["hhmm"] >= "09:30") & (g["hhmm"] <= "09:45")]
    if len(rth_bars) < 10:
        continue
    
    # Session VWAP at 09:45 ET (MVT 0)
    cum_vol = rth_bars["volume"].sum()
    if cum_vol <= 0:
        vwap_0945 = float(rth_bars["close"].mean())
    else:
        vwap_0945 = float((rth_bars["close"] * rth_bars["volume"]).sum() / cum_vol)
    
    entry_p = float(rth_bars.iloc[-1]["close"])
    # GARCH daily standard deviation in points
    sigma_day_pts = entry_p * (cond_vol_pct / 100.0)
    # Scaling to the 15-min open window (15 min / 390 min RTH session)
    sigma_open_pts = sigma_day_pts * np.sqrt(15.0 / 390.0)
    # Scaling to the 45-min holding window
    sigma_window_pts = sigma_day_pts * np.sqrt(45.0 / 390.0)
    
    # Distance from MVT 0 in units of sigma
    diff_pts = entry_p - vwap_0945
    direction_val = 1 if tr["direction"] == "long" else -1
    
    # Signed extension in trade direction
    z_score_open = (diff_pts * direction_val) / max(sigma_open_pts, 1.0)
    z_score_window = (diff_pts * direction_val) / max(sigma_window_pts, 1.0)
    
    row = dict(tr)
    row["cond_vol_pct"] = cond_vol_pct
    row["vwap_0945"] = vwap_0945
    row["entry_p"] = entry_p
    row["sigma_day_pts"] = sigma_day_pts
    row["sigma_open_pts"] = sigma_open_pts
    row["z_score_open"] = z_score_open
    row["z_score_window"] = z_score_window
    enriched_trades.append(row)

df_res = pd.DataFrame(enriched_trades)
print(f"Enriched {len(df_res)} trades with point-in-time GARCH metrics.\n", flush=True)

# 5. Analyze Performance by Z-score Buckets (MVT DP Bands)
print("=" * 75)
print("  STRATEGY 1 PERFORMANCE BY GARCH MVT OPENING EXTENSION (Z-Score on 15m Sigma)")
print("=" * 75)

bins = [-np.inf, 0.5, 1.0, 1.5, 2.0, 2.5, np.inf]
labels = ["< 0.5 DP", "0.5 - 1.0 DP", "1.0 - 1.5 DP", "1.5 - 2.0 DP", "2.0 - 2.5 DP", "> 2.5 DP (Exhaustion)"]
df_res["dp_bucket"] = pd.cut(df_res["z_score_open"], bins=bins, labels=labels)

summary = df_res.groupby("dp_bucket", observed=False).agg(
    trades=("net_dollars_micro", "count"),
    wr=("net_dollars_micro", lambda x: (x > 0).mean() * 100),
    net_pnl=("net_dollars_micro", "sum"),
    avg_trade=("net_dollars_micro", "mean"),
    pos_pnl=("net_dollars_micro", lambda x: x[x > 0].sum()),
    neg_pnl=("net_dollars_micro", lambda x: abs(x[x <= 0].sum())),
)
summary["pf"] = summary["pos_pnl"] / summary["neg_pnl"]
print(summary[["trades", "wr", "pf", "net_pnl", "avg_trade"]].round(2).to_string(), flush=True)

print("\n" + "=" * 75)
print("  FILTER IMPACT: EXCLUDING OVEREXTENDED EXHAUSTION TRADES (> 2.0 DP or > 2.5 DP)")
print("=" * 75)

for cut in [3.0, 2.5, 2.2, 2.0]:
    filtered = df_res[df_res["z_score_open"] <= cut]
    dropped = df_res[df_res["z_score_open"] > cut]
    
    pos = filtered.loc[filtered["net_dollars_micro"] > 0, "net_dollars_micro"].sum()
    neg = abs(filtered.loc[filtered["net_dollars_micro"] <= 0, "net_dollars_micro"].sum())
    pf = pos / neg if neg > 0 else np.nan
    wr = (filtered["net_dollars_micro"] > 0).mean() * 100
    
    d_pos = dropped.loc[dropped["net_dollars_micro"] > 0, "net_dollars_micro"].sum()
    d_neg = abs(dropped.loc[dropped["net_dollars_micro"] <= 0, "net_dollars_micro"].sum())
    d_pf = d_pos / d_neg if d_neg > 0 else np.nan
    d_wr = (dropped["net_dollars_micro"] > 0).mean() * 100
    
    print(f"Filter z_score <= {cut:.1f} DP:")
    print(f"  Kept:    {len(filtered):>3} trades | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net: ${filtered['net_dollars_micro'].sum():>8,.2f}")
    print(f"  Dropped: {len(dropped):>3} trades | WR: {d_wr:>5.1f}% | PF: {d_pf:>4.2f} | Net: ${dropped['net_dollars_micro'].sum():>8,.2f}")
    print()
