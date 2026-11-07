#!/usr/bin/env python3
"""
Candidate Strategy S11: Micro Gold Morning Value Area Breakout (09:45 ET on MGC).

Structural Premise:
Evaluates whether applying canonical Strategy 1 (09:45 ET Value Area Breakout outside 70% VA
with overnight gap) to Micro Gold (MGC) produces a viable multi-asset trend-following edge.

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
from backtest.morning_value_area_breakout_signal import (
    MorningValueAreaBreakoutConfig,
    build_morning_value_area_breakout_signal_frame,
)

STRATEGY_ID = "candidate_gold_va_breakout_s11"
STRATEGY_NAME = "Micro Gold Morning VA Breakout (09:45 ET)"

GC_PATH = REPO_ROOT / "data" / "raw" / "gc_1m_2020_2026_et.parquet"

def evaluate_gold_va():
    df_raw = pd.read_parquet(GC_PATH)
    df_clean = df_raw[["time", "open", "high", "low", "close", "volume"]].copy()

    cfg = MorningValueAreaBreakoutConfig(
        min_abs_return_pct=0.0008,
        min_long_close_location=0.60,
        max_short_close_location=0.40,
        require_outside_prior_va=True,
        require_with_gap=True,
        allow_long=True,
        allow_short=True,
        min_stop_points=2.5,
        max_stop_points=12.0,
        reward_risk_ratio=1.5,
        profile_bin_size=0.5,
        value_area_pct=0.70,
        rth_start="09:30",
        signal_bar_time="09:44",
        rth_end="16:00",
    )

    sig_frame = build_morning_value_area_breakout_signal_frame(df_clean, config=cfg)
    active = sig_frame[sig_frame["candidate_signal"] != 0.0].copy()

    df_clean["date_str"] = df_clean["time"].dt.strftime("%Y-%m-%d")
    df_clean["hhmm"] = df_clean["time"].dt.strftime("%H:%M")

    post_window = df_clean[(df_clean["hhmm"] >= "09:45") & (df_clean["hhmm"] <= "10:15")].copy()
    bars_by_date = {d: g.reset_index(drop=True) for d, g in post_window.groupby("date_str")}

    pt_val = 10.0
    tick_size = 0.10
    slip_cost = 2.00 # 1 tick adverse each side ($2.00/micro)
    comm = 1.24

    trades = []
    for _, srow in active.iterrows():
        sig_time = pd.Timestamp(srow["time"])
        d_str = sig_time.strftime("%Y-%m-%d")
        if d_str < "2021-01-01":
            continue

        day_bars = bars_by_date.get(d_str)
        if day_bars is None or day_bars.empty:
            continue

        post_bars = day_bars[day_bars["time"] >= sig_time + pd.Timedelta(minutes=1)]
        if post_bars.empty:
            continue

        entry_p = float(post_bars.iloc[0]["open"])
        sig = float(srow["candidate_signal"])
        stop_pts = float(srow["or15_range_points"])
        stop_pts = max(min(stop_pts, 12.0), 2.5)
        target_pts = stop_pts * 1.5

        stop_p = entry_p - sig * stop_pts
        target_p = entry_p + sig * target_pts
        exit_p = float(post_bars.iloc[-1]["close"])
        reason = "time_exit_1015"

        for _, b in post_bars.iterrows():
            bh, bl = float(b["high"]), float(b["low"])
            if sig == 1:
                if bl <= stop_p:
                    exit_p = stop_p
                    reason = "stop_loss"
                    break
                if bh >= target_p:
                    exit_p = target_p
                    reason = "target"
                    break
            else:
                if bh >= stop_p:
                    exit_p = stop_p
                    reason = "stop_loss"
                    break
                if bl <= target_p:
                    exit_p = target_p
                    reason = "target"
                    break

        pts = (exit_p - entry_p) * sig
        net_pnl = pts * pt_val - comm - slip_cost
        trades.append({
            "date": d_str,
            "year": d_str[:4],
            "sig": sig,
            "pts": pts,
            "net_pnl": net_pnl,
            "win": net_pnl > 0,
            "reason": reason,
            "is_oos": "IS" if d_str < "2025-01-01" else "OOS",
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
    print(" CANDIDATE EVALUATION: GOLD MORNING VA BREAKOUT (09:45 ET on MGC)")
    print("=" * 80)

    register_strategy(
        strategy_id=STRATEGY_ID,
        tier=StrategyTier.CANDIDATE,
        name=STRATEGY_NAME,
        instrument="MGC",
        description="Micro Gold 09:45 ET Value Area Breakout (canonical S1 twin).",
    )

    store = default_store
    h_gc = store.compute_data_hash(GC_PATH)
    print(f"Data SHA-256 (GC): {h_gc[:16]}...")

    tdf = evaluate_gold_va()
    m = compute_metrics(tdf)

    print("\nRESULTS SUMMARY:")
    print(f"  MGC 09:45 VA Breakout: {m['trades']} tr | PF: {m['pf']:.2f} | WR: {m['win_rate']:.1f}% | Net: ${m['net_pnl']:,.2f} | MaxDD: -${m['max_dd']:,.2f}")

    run_id = f"{STRATEGY_ID}_2021_2026"
    store.record_run(
        run_id=run_id,
        strategy_id=STRATEGY_ID,
        strategy_name=STRATEGY_NAME,
        strategy_tier=StrategyTier.CANDIDATE.value,
        methodology="multi_year_walkforward",
        date_start="2021-01-04",
        date_end="2026-10-30",
        data_path=str(GC_PATH),
        total_trades=m["trades"],
        win_rate=m["win_rate"],
        profit_factor=m["pf"],
        gross_profit=m["gross_profit"],
        net_profit=m["net_pnl"],
        max_drawdown=m["max_dd"],
        sharpe_ratio=m["sharpe"],
        largest_win=m["largest_win"],
        slippage_model="1 tick adverse parity",
        commission_model="$1.24/round-trip",
        is_net=True,
        explicit_warnings=["CANDIDATE_TIER_QUARANTINED", "FALSIFIED_HYPOTHESIS"],
    )

    print(f"\n[OK] Run recorded in provenance store: {run_id}")

if __name__ == "__main__":
    main()
