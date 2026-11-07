import pandas as pd
import numpy as np
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backtest.markov_regime import add_markov_regime_features

df = pd.read_parquet(ROOT / "data/processed/unified_three_strategy_garch_portfolio_trades_2021_2026.parquet")
s3 = df[df["strategy"].str.contains("Strategy 3")].copy()

df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
df_nq["date_str"] = df_nq["time"].dt.strftime("%Y-%m-%d")
daily_nq = df_nq.groupby("date_str").agg(open=("open","first"), high=("high","max"), low=("low","min"), close=("close","last")).reset_index()

daily_markov = add_markov_regime_features(daily_nq, n_states=3, calibration_bars=60, min_calibration_bars=30, refit_every_bars=5)
daily_markov["trade_date_str"] = daily_markov["date_str"].shift(-1)
s3["date_str"] = pd.to_datetime(s3["entry_time"]).dt.strftime("%Y-%m-%d")
s3 = s3.merge(daily_markov.set_index("trade_date_str")[["markov_state_label"]], left_on="date_str", right_index=True, how="left")

print("=== Strategy 3 Detailed Stats by Daily Markov Regime ===")
for reg, g in s3.groupby("markov_state_label"):
    wr = (g["net_dollars_micro"] > 0).mean() * 100
    pos = g.loc[g["net_dollars_micro"] > 0, "net_dollars_micro"].sum()
    neg = abs(g.loc[g["net_dollars_micro"] <= 0, "net_dollars_micro"].sum())
    pf = pos / neg if neg > 0 else np.nan
    tot = g["net_dollars_micro"].sum()
    avg_win = g.loc[g["net_dollars_micro"] > 0, "net_dollars_micro"].mean()
    avg_loss = g.loc[g["net_dollars_micro"] <= 0, "net_dollars_micro"].mean()
    print(f"Regime: {reg:<10} | Trades: {len(g):>3} | WR: {wr:>5.1f}% | PF: {pf:>4.2f} | Net: ${tot:>9.2f} | Avg Win: ${avg_win:>6.2f} | Avg Loss: ${avg_loss:>6.2f}")
