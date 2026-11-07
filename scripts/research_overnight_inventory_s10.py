#!/usr/bin/env python3
"""
Candidate Strategy S10: Dalton's Overnight Inventory Imbalance Correction (09:35 ET).

Structural Premise:
Tests whether a heavily one-sided overnight Globex inventory (>=85% of overnight volume
trading on one side of prior session settlement) followed by a 09:30–09:34 ET cash open
failure to accept outside overnight extremes forces a mechanical liquidation back to
prior settlement on Micro S&P 500 (MES) and Micro Nasdaq 100 (MNQ).

Belfort Systematic Trading Framework (2026) — Steps 03 to 05.
Governance: Auto-records into results/backtest_provenance.db under StrategyTier.CANDIDATE.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.strategy_registry import StrategyTier, register_strategy
from backtest.provenance import default_store

STRATEGY_ID = "candidate_overnight_inventory_s10"
STRATEGY_NAME = "Dalton Overnight Inventory Correction (09:35 ET)"

ES_PATH = REPO_ROOT / "data" / "raw" / "es_1m_2020_2026_cqg_et.parquet"
NQ_PATH = REPO_ROOT / "data" / "raw" / "nq_1m_2017_2026_cqg_et.parquet"

def evaluate_asset(asset: str, data_path: Path, point_val: float, tick_size: float = 0.25):
    df = pd.read_parquet(data_path)
    df["m"] = df["time"].dt.hour * 60 + df["time"].dt.minute
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")

    sub = df[((df["m"] >= 955) & (df["m"] <= 965)) | (df["m"] >= 1080) | (df["m"] <= 615)].copy()
    sub = sub.sort_values("time").reset_index(drop=True)

    day_dict = {d: group for d, group in sub.groupby("date_str")}
    dates = sorted(day_dict.keys())

    trades = []
    comm = 1.24
    slip_cost = 1 * tick_size * point_val * 2 # 1 tick adverse entry & exit

    min_dist = 6.0 if asset == "MES" else 25.0
    buffer_pts = 1.0 if asset == "MES" else 4.0
    max_stop = 12.0 if asset == "MES" else 50.0

    for i in range(1, len(dates)):
        d_curr = dates[i]
        d_prev = dates[i - 1]

        if d_curr < "2021-01-01":
            continue

        prev_day_bars = day_dict.get(d_prev)
        curr_day_bars = day_dict.get(d_curr)

        if prev_day_bars is None or curr_day_bars is None:
            continue

        settle_bars = prev_day_bars[(prev_day_bars["m"] >= 955) & (prev_day_bars["m"] <= 965)]
        if settle_bars.empty:
            continue
        p_settle = float(settle_bars.iloc[-1]["close"])

        on_prev = prev_day_bars[prev_day_bars["m"] >= 1080]
        on_curr = curr_day_bars[curr_day_bars["m"] <= 569]
        on_bars = pd.concat([on_prev, on_curr], ignore_index=True)

        if len(on_bars) < 200:
            continue

        on_high = float(on_bars["high"].max())
        on_low = float(on_bars["low"].min())

        vol_above = on_bars[on_bars["close"] > p_settle]["volume"].sum()
        vol_below = on_bars[on_bars["close"] < p_settle]["volume"].sum()
        total_vol = on_bars["volume"].sum()

        if total_vol <= 0:
            continue

        ratio_long = vol_above / total_vol
        ratio_short = vol_below / total_vol

        open_5m = curr_day_bars[(curr_day_bars["m"] >= 570) & (curr_day_bars["m"] <= 574)]
        if len(open_5m) < 4:
            continue

        o_0930 = float(open_5m.iloc[0]["open"])
        c_0934 = float(open_5m.iloc[-1]["close"])
        h_5m = float(open_5m["high"].max())
        l_5m = float(open_5m["low"].min())

        exec_bars = curr_day_bars[(curr_day_bars["m"] >= 575) & (curr_day_bars["m"] <= 615)]
        if len(exec_bars) < 20:
            continue

        sig = 0
        if ratio_long >= 0.85 and (o_0930 - p_settle) >= min_dist:
            if c_0934 < (h_5m + l_5m) / 2.0 and c_0934 < (on_high - buffer_pts):
                sig = -1
        elif ratio_short >= 0.85 and (p_settle - o_0930) >= min_dist:
            if c_0934 > (h_5m + l_5m) / 2.0 and c_0934 > (on_low + buffer_pts):
                sig = 1

        if sig != 0:
            entry_p = float(exec_bars.iloc[0]["open"])
            if sig == -1:
                raw_stop = (on_high + buffer_pts) - entry_p
                stop_dist = min(max(raw_stop, min_dist * 0.5), max_stop)
                stop_p = entry_p + stop_dist
                target_p = p_settle + buffer_pts
            else:
                raw_stop = entry_p - (on_low - buffer_pts)
                stop_dist = min(max(raw_stop, min_dist * 0.5), max_stop)
                stop_p = entry_p - stop_dist
                target_p = p_settle - buffer_pts

            exit_p = float(exec_bars.iloc[-1]["close"])
            reason = "time_exit_1015"

            for _, b in exec_bars.iterrows():
                bh = float(b["high"])
                bl = float(b["low"])
                if sig == -1:
                    if bh >= stop_p:
                        exit_p = stop_p
                        reason = "stop_loss"
                        break
                    if bl <= target_p:
                        exit_p = target_p
                        reason = "target_settle"
                        break
                else:
                    if bl <= stop_p:
                        exit_p = stop_p
                        reason = "stop_loss"
                        break
                    if bh >= target_p:
                        exit_p = target_p
                        reason = "target_settle"
                        break

            pts = (exit_p - entry_p) * sig
            net_pnl = pts * point_val - comm - slip_cost
            trades.append({
                "date": d_curr,
                "year": d_curr[:4],
                "sig": sig,
                "entry_p": entry_p,
                "exit_p": exit_p,
                "pts": pts,
                "net_pnl": net_pnl,
                "win": net_pnl > 0,
                "reason": reason,
                "is_oos": "IS" if d_curr < "2025-01-01" else "OOS",
            })

    return pd.DataFrame(trades)

def compute_metrics(tdf: pd.DataFrame):
    if len(tdf) == 0:
        return {"trades": 0, "pf": 0.0, "win_rate": 0.0, "net_pnl": 0.0, "gross_profit": 0.0, "max_dd": 0.0, "largest_win": 0.0, "sharpe": 0.0}
    w = float(tdf[tdf["net_pnl"] > 0]["net_pnl"].sum())
    l = float(abs(tdf[tdf["net_pnl"] < 0]["net_pnl"].sum()))
    pf = w / l if l > 0 else 0.0
    wr = float(tdf["win"].mean() * 100)
    net = float(tdf["net_pnl"].sum())
    cum = tdf["net_pnl"].cumsum()
    max_dd = float((cum.cummax() - cum).max())
    largest_win = float(tdf["net_pnl"].max()) if not tdf.empty else 0.0
    daily_pnl = tdf.groupby("date")["net_pnl"].sum()
    sharpe = float(daily_pnl.mean() / (daily_pnl.std() + 1e-6) * np.sqrt(252)) if len(daily_pnl) > 1 else 0.0
    return {
        "trades": len(tdf),
        "pf": pf,
        "win_rate": wr,
        "net_pnl": net,
        "gross_profit": w,
        "max_dd": max_dd,
        "largest_win": largest_win,
        "sharpe": sharpe,
    }

def main():
    print("=" * 80)
    print(" CANDIDATE EVALUATION: DALTON OVERNIGHT INVENTORY CORRECTION (09:35 ET)")
    print("=" * 80)

    register_strategy(
        strategy_id=STRATEGY_ID,
        tier=StrategyTier.CANDIDATE,
        name=STRATEGY_NAME,
        instrument="MES/MNQ",
        description="Dalton overnight inventory imbalance correction (09:35 ET) to prior settlement.",
    )

    store = default_store
    h_es = store.compute_data_hash(ES_PATH)
    h_nq = store.compute_data_hash(NQ_PATH)

    print(f"Data SHA-256 (ES): {h_es[:16]}...")
    print(f"Data SHA-256 (NQ): {h_nq[:16]}...")

    t_es = evaluate_asset("MES", ES_PATH, point_val=5.0, tick_size=0.25)
    t_nq = evaluate_asset("MNQ", NQ_PATH, point_val=2.0, tick_size=0.25)

    m_es = compute_metrics(t_es)
    m_nq = compute_metrics(t_nq)

    combined = pd.concat([t_es, t_nq], ignore_index=True)
    m_comb = compute_metrics(combined)

    print("\nRESULTS SUMMARY:")
    print(f"  MES Standalone : {m_es['trades']} tr | PF: {m_es['pf']:.2f} | WR: {m_es['win_rate']:.1f}% | Net: ${m_es['net_pnl']:,.2f} | MaxDD: -${m_es['max_dd']:,.2f}")
    print(f"  MNQ Standalone : {m_nq['trades']} tr | PF: {m_nq['pf']:.2f} | WR: {m_nq['win_rate']:.1f}% | Net: ${m_nq['net_pnl']:,.2f} | MaxDD: -${m_nq['max_dd']:,.2f}")
    print(f"  Combined (MES+MNQ): {m_comb['trades']} tr | PF: {m_comb['pf']:.2f} | WR: {m_comb['win_rate']:.1f}% | Net: ${m_comb['net_pnl']:,.2f} | MaxDD: -${m_comb['max_dd']:,.2f}")

    run_id = f"{STRATEGY_ID}_2021_2026"
    store.record_run(
        run_id=run_id,
        strategy_id=STRATEGY_ID,
        strategy_name=STRATEGY_NAME,
        strategy_tier=StrategyTier.CANDIDATE.value,
        methodology="multi_year_walkforward",
        date_start="2021-01-04",
        date_end="2026-10-30",
        data_path=str(ES_PATH),
        total_trades=m_comb["trades"],
        win_rate=m_comb["win_rate"],
        profit_factor=m_comb["pf"],
        gross_profit=m_comb["gross_profit"],
        net_profit=m_comb["net_pnl"],
        max_drawdown=m_comb["max_dd"],
        sharpe_ratio=m_comb["sharpe"],
        largest_win=m_comb["largest_win"],
        slippage_model="1 tick adverse parity",
        commission_model="$1.24/round-trip",
        is_net=True,
        explicit_warnings=["CANDIDATE_TIER_QUARANTINED", "FALSIFIED_HYPOTHESIS"],
    )

    print(f"\n[OK] Run recorded in provenance store: {run_id}")

if __name__ == "__main__":
    main()
