#!/usr/bin/env python3
"""
Candidate Strategy S12: WTI Crude Oil NYMEX Settlement Auction Imbalance (14:27 ET on MCL).

Structural Premise:
Evaluates whether pre-settlement expansion (14:20 to 14:27 ET) reliably predicts the 14:28–14:30 ET
NYMEX settlement auction cross drift or post-settlement snapback on Micro WTI Crude Oil (MCL).

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

STRATEGY_ID = "candidate_crude_settlement_s12"
STRATEGY_NAME = "WTI Crude Oil NYMEX Settlement Auction (14:27 ET)"

CL_PATH = REPO_ROOT / "data" / "raw" / "cl_1m_2020_2026_et.parquet"

def evaluate_crude_settlement():
    df = pd.read_parquet(CL_PATH)
    df["m"] = df["time"].dt.hour * 60 + df["time"].dt.minute
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")

    sub = df[(df["m"] >= 840) & (df["m"] <= 885)].copy()
    sub = sub.sort_values("time").reset_index(drop=True)

    day_dict = {d: group for d, group in sub.groupby("date_str")}
    dates = sorted(day_dict.keys())

    pt_val = 100.0
    tick_size = 0.01
    comm = 1.24
    slip_cost = 1 * tick_size * pt_val * 2 # 1 tick adverse each side = $2.00

    trades_v1 = []
    trades_v2 = []

    for d in dates:
        if d < "2021-01-01":
            continue

        day_bars = day_dict.get(d)
        if day_bars is None or len(day_bars) < 35:
            continue

        base_bars = day_bars[(day_bars["m"] >= 840) & (day_bars["m"] <= 859)]
        if len(base_bars) < 15:
            continue
        h_base = float(base_bars["high"].max())
        l_base = float(base_bars["low"].min())

        thrust_bars = day_bars[(day_bars["m"] >= 860) & (day_bars["m"] <= 867)]
        if len(thrust_bars) < 7:
            continue

        o_1420 = float(thrust_bars.iloc[0]["open"])
        c_1427 = float(thrust_bars.iloc[-1]["close"])
        h_thrust = float(thrust_bars["high"].max())
        l_thrust = float(thrust_bars["low"].min())
        rng_thrust = h_thrust - l_thrust
        if rng_thrust <= 0:
            continue

        ret_thrust = (c_1427 - o_1420) / o_1420
        cl_thrust = (c_1427 - l_thrust) / rng_thrust

        sig = 0
        if ret_thrust >= 0.0015 and c_1427 > h_base and cl_thrust >= 0.65:
            sig = 1
        elif ret_thrust <= -0.0015 and c_1427 < l_base and cl_thrust <= 0.35:
            sig = -1

        if sig != 0:
            settle_bars = day_bars[(day_bars["m"] >= 868) & (day_bars["m"] <= 869)]
            post_settle_bars = day_bars[(day_bars["m"] >= 870) & (day_bars["m"] <= 875)]

            # Variant 1: Drive into settlement
            if not settle_bars.empty:
                v1_entry = float(settle_bars.iloc[0]["open"])
                v1_exit = float(settle_bars.iloc[-1]["close"])
                stop_dist = 0.20
                target_dist = 0.30
                stop_p = v1_entry - sig * stop_dist
                target_p = v1_entry + sig * target_dist
                v1_final = v1_exit
                for _, b in settle_bars.iterrows():
                    bh, bl = float(b["high"]), float(b["low"])
                    if sig == 1:
                        if bl <= stop_p:
                            v1_final = stop_p
                            break
                        if bh >= target_p:
                            v1_final = target_p
                            break
                    else:
                        if bh >= stop_p:
                            v1_final = stop_p
                            break
                        if bl <= target_p:
                            v1_final = target_p
                            break
                v1_pts = (v1_final - v1_entry) * sig
                v1_pnl = v1_pts * pt_val - comm - slip_cost
                trades_v1.append({"date": d, "year": d[:4], "net_pnl": v1_pnl, "win": v1_pnl > 0, "is_oos": "IS" if d < "2025-01-01" else "OOS"})

            # Variant 2: Post-settlement snapback
            if not post_settle_bars.empty:
                v2_sig = -sig
                v2_entry = float(post_settle_bars.iloc[0]["open"])
                v2_exit = float(post_settle_bars.iloc[-1]["close"])
                stop_p2 = v2_entry - v2_sig * stop_dist
                target_p2 = v2_entry + v2_sig * target_dist
                v2_final = v2_exit
                for _, b in post_settle_bars.iterrows():
                    bh, bl = float(b["high"]), float(b["low"])
                    if v2_sig == 1:
                        if bl <= stop_p2:
                            v2_final = stop_p2
                            break
                        if bh >= target_p2:
                            v2_final = target_p2
                            break
                    else:
                        if bh >= stop_p2:
                            v2_final = stop_p2
                            break
                        if bl <= target_p2:
                            v2_final = target_p2
                            break
                v2_pts = (v2_final - v2_entry) * v2_sig
                v2_pnl = v2_pts * pt_val - comm - slip_cost
                trades_v2.append({"date": d, "year": d[:4], "net_pnl": v2_pnl, "win": v2_pnl > 0, "is_oos": "IS" if d < "2025-01-01" else "OOS"})

    return pd.DataFrame(trades_v1), pd.DataFrame(trades_v2)

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
    print(" CANDIDATE EVALUATION: WTI CRUDE OIL SETTLEMENT AUCTION (14:27 ET on MCL)")
    print("=" * 80)

    register_strategy(
        strategy_id=STRATEGY_ID,
        tier=StrategyTier.CANDIDATE,
        name=STRATEGY_NAME,
        instrument="MCL",
        description="WTI Crude Oil NYMEX 14:28-14:30 ET settlement auction imbalance drive and snapback.",
    )

    store = default_store
    h_cl = store.compute_data_hash(CL_PATH)
    print(f"Data SHA-256 (CL): {h_cl[:16]}...")

    t_v1, t_v2 = evaluate_crude_settlement()
    m_v1 = compute_metrics(t_v1)
    m_v2 = compute_metrics(t_v2)

    print("\nRESULTS SUMMARY:")
    print(f"  Variant 1 (Drive into Settlement): {m_v1['trades']} tr | PF: {m_v1['pf']:.2f} | WR: {m_v1['win_rate']:.1f}% | Net: ${m_v1['net_pnl']:,.2f} | MaxDD: -${m_v1['max_dd']:,.2f}")
    print(f"  Variant 2 (Post-Settlement Fade) : {m_v2['trades']} tr | PF: {m_v2['pf']:.2f} | WR: {m_v2['win_rate']:.1f}% | Net: ${m_v2['net_pnl']:,.2f} | MaxDD: -${m_v2['max_dd']:,.2f}")

    run_id = f"{STRATEGY_ID}_2021_2026"
    store.record_run(
        run_id=run_id,
        strategy_id=STRATEGY_ID,
        strategy_name=STRATEGY_NAME,
        strategy_tier=StrategyTier.CANDIDATE.value,
        methodology="multi_year_walkforward",
        date_start="2021-01-04",
        date_end="2026-10-30",
        data_path=str(CL_PATH),
        total_trades=m_v1["trades"],
        win_rate=m_v1["win_rate"],
        profit_factor=m_v1["pf"],
        gross_profit=m_v1["gross_profit"],
        net_profit=m_v1["net_pnl"],
        max_drawdown=m_v1["max_dd"],
        sharpe_ratio=m_v1["sharpe"],
        largest_win=m_v1["largest_win"],
        slippage_model="1 tick adverse parity",
        commission_model="$1.24/round-trip",
        is_net=True,
        explicit_warnings=["CANDIDATE_TIER_QUARANTINED", "FALSIFIED_HYPOTHESIS"],
    )

    print(f"\n[OK] Run recorded in provenance store: {run_id}")

if __name__ == "__main__":
    main()
