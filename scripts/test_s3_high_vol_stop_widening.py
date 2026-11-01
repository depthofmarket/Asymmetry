import pandas as pd
import numpy as np
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backtest.markov_regime import add_markov_regime_features

# Load NQ 1m bars
df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")
df_nq["date_str"] = df_nq["time"].dt.strftime("%Y-%m-%d")
df_nq["hhmm"] = df_nq["time"].dt.strftime("%H:%M")

daily_nq = df_nq.groupby("date_str").agg(open=("open","first"), high=("high","max"), low=("low","min"), close=("close","last")).reset_index()
daily_markov = add_markov_regime_features(daily_nq, n_states=3, calibration_bars=60, min_calibration_bars=30, refit_every_bars=5)
daily_markov["trade_date_str"] = daily_markov["date_str"].shift(-1)
regime_map = dict(zip(daily_markov["trade_date_str"], daily_markov["markov_state_label"]))

bars_by_date = {d: g.reset_index(drop=True) for d, g in df_nq.groupby("date_str")}

# Test Strategy 3 with different stop caps in high_vol
for stop_mult in [0.50, 0.65, 0.75, 1.0]:
    for max_stop in [50.0, 70.0, 90.0]:
        trades_hv = []
        for d_str, g in bars_by_date.items():
            if d_str < "2021-01-01" or regime_map.get(d_str) != "high_vol":
                continue
            ovn = g[(g["hhmm"] >= "00:00") & (g["hhmm"] <= "08:29")]
            if len(ovn) < 180: continue
            ovn_h, ovn_l = float(ovn["high"].max()), float(ovn["low"].min())
            if ovn_h <= ovn_l: continue
            spike = g[(g["hhmm"] >= "08:30") & (g["hhmm"] <= "08:34")]
            if len(spike) < 4: continue
            spike_vol = float(spike["volume"].sum())
            pre_vol = float(ovn["volume"].tail(30).mean()) * 5.0
            if spike_vol < pre_vol * 2.5: continue
            spike_c = float(spike.iloc[-1]["close"])
            spike_rng = float(spike["high"].max()) - float(spike["low"].min())
            spike_loc = (spike_c - float(spike["low"].min())) / spike_rng if spike_rng > 0 else 0.5
            eb = g[g["hhmm"] == "08:35"]
            if eb.empty: continue
            d = 1 if (spike_c > ovn_h and spike_loc >= 0.65) else (-1 if (spike_c < ovn_l and spike_loc <= 0.35) else 0)
            if d == 0: continue
            exec_bars = g[g["time"] >= eb.iloc[0]["time"]].reset_index(drop=True)
            if len(exec_bars) < 20: continue
            entry_p = float(exec_bars.iloc[0]["open"])
            stop_pts = float(np.clip(spike_rng * stop_mult, 20.0, max_stop))
            target_pts = stop_pts * 1.5
            stop_p = entry_p - d * stop_pts
            target_p = entry_p + d * target_pts
            exit_p = float(exec_bars.iloc[min(45, len(exec_bars)-1)]["close"])
            for _, rb in exec_bars.iterrows():
                if rb["hhmm"] >= "09:25":
                    exit_p = float(rb["close"]); break
                rb_h, rb_l = float(rb["high"]), float(rb["low"])
                if d == 1 and rb_l <= stop_p: exit_p = stop_p; break
                elif d == -1 and rb_h >= stop_p: exit_p = stop_p; break
                if d == 1 and rb_h >= target_p: exit_p = target_p; break
                elif d == -1 and rb_l <= target_p: exit_p = target_p; break
            pnl = ((exit_p - entry_p) * d - 1.0) * 2.0 * max(1, int(round(250.0 / (stop_pts * 2.0)))) - 2.48
            trades_hv.append(pnl)
        if trades_hv:
            pos = sum(p for p in trades_hv if p > 0)
            neg = abs(sum(p for p in trades_hv if p <= 0))
            pf = pos / neg if neg > 0 else 0
            wr = np.mean([p > 0 for p in trades_hv]) * 100
            print(f"StopMult {stop_mult:.2f} | MaxStop {max_stop:.0f}: Trades {len(trades_hv)} | WR {wr:.1f}% | PF {pf:.2f} | Net ${sum(trades_hv):,.2f}")
