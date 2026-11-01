#!/usr/bin/env python3
"""
Generate and save point-in-time daily GARCH(1,1) conditional volatility forecasts for NQ (2020-2026).
Saves to `data/processed/nq_daily_garch_forecasts_2020_2026.parquet`.
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from arch import arch_model

ROOT = Path(__file__).resolve().parents[1]

df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
df_nq["date_str"] = df_nq["time"].dt.strftime("%Y-%m-%d")

daily_closes = df_nq.groupby("date_str")["close"].last()
daily_ret = (np.log(daily_closes / daily_closes.shift(1)).dropna() * 100.0).to_frame(name="ret")
all_dates = daily_ret.index.tolist()

garch_sigma = pd.Series(index=daily_ret.index, dtype=float)
current_params = None
last_refit_idx = -100

print(f"Fitting rolling GARCH(1,1) over {len(all_dates)} trading sessions...", flush=True)

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

out_df = pd.DataFrame({
    "date_str": daily_ret.index,
    "close": daily_closes.loc[daily_ret.index],
    "daily_ret_pct": daily_ret["ret"],
    "garch_cond_vol_pct": garch_sigma
}).dropna().reset_index(drop=True)

out_path = ROOT / "data/processed/nq_daily_garch_forecasts_2020_2026.parquet"
out_df.to_parquet(out_path, index=False)
print(f"Saved {len(out_df)} daily GARCH forecasts to {out_path}", flush=True)
