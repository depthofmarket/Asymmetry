#!/usr/bin/env python3
"""
Candidate Strategy S9 (H39): Cash Open Uncrossing Momentum Thrust (09:35 ET on MNQ).

Structural Premise:
At 09:30:00 ET, the NYSE and Nasdaq execute their official Opening Crosses, unlocking cash equity trading
and releasing millions of shares of pent-up overnight institutional orders. When the 09:30–09:34 ET 5-minute
opening bar experiences an extraordinary volume shock (>= 2.20x rolling 20-day median) accompanied by an
extended range displacement (>= 1.25x rolling 20-day ATR) and closes at its directional extreme (top/bottom 20%),
it signifies massive one-sided institutional basket execution and index arbitrage basis realignment.
Entering at 09:35:00 ET captures the secondary momentum thrust into 09:55:00 ET before opening order flow exhausts.

Belfort Systematic Trading Framework (2026) — Step 03 (Code It), Step 04 (In-Sample), Step 05 (Out-of-Sample).
Governance: Auto-records into results/backtest_provenance.db under StrategyTier.CANDIDATE.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.metrics import calculate_institutional_metrics
from backtest.provenance import ProvenanceStore, default_store
from config.strategy_registry import StrategyTier, register_strategy

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION & CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

STRATEGY_ID = "candidate_cash_open_thrust_s9"
STRATEGY_NAME = "Cash Open Uncrossing Momentum Thrust (09:35 ET on MNQ)"

NQ_PATH = REPO_ROOT / "data" / "raw" / "nq_1m_2017_2026_cqg_et.parquet"

# MNQ Contract Specifications
MNQ_POINT_VAL = 2.00         # $2.00 per index point ($0.50 per 0.25 tick)
MNQ_TICK_SIZE = 0.25         # 0.25 index points
MNQ_COMMISSION_RT = 1.40     # $1.40 round-trip per micro contract ($0.70/side)
MNQ_SLIPPAGE_TICKS = 1       # 1 tick adverse entry + 1 tick adverse exit
MNQ_SLIPPAGE_COST = 2 * MNQ_TICK_SIZE * MNQ_POINT_VAL  # $1.00 total slippage ($0.50 / side)
MNQ_TOTAL_FRICTION = MNQ_COMMISSION_RT + MNQ_SLIPPAGE_COST  # $2.40 total round-turn friction

# Risk Brackets (in index points)
STOP_LOSS_POINTS = 30.00      # $60.00 risk per micro contract
PROFIT_TARGET_POINTS = 60.00  # $120.00 target per micro contract (1:2.0 R:R)
BREAKEVEN_TRIGGER_POINTS = 30.00  # +1.0R excursion moves stop
BREAKEVEN_BUFFER_POINTS = 6.00    # Move stop to entry + 6.00 pts (+0.2R lock-in)

# Gate Parameters
VOLUME_SHOCK_MULT = 2.20     # V_0930_0934 >= 2.20 * rolling 20-day median 5m volume
RANGE_ATR_MULT = 1.25        # Range_0934 >= 1.25 * rolling 20-day 5m ATR
SKEW_THRESHOLD = 0.80        # Close in top 20% (>= 0.80) or bottom 20% (<= 0.20)
ROLLING_WINDOW = 20          # 20-day rolling window

EVAL_START_DATE = "2021-01-04"
EVAL_END_DATE = "2026-10-30"
IS_SPLIT_DATE = "2025-01-01"


# ─────────────────────────────────────────────────────────────────────────────
# ROLLING BASELINE PRECOMPUTATION (ZERO LOOKAHEAD)
# ─────────────────────────────────────────────────────────────────────────────

def precompute_opening_baselines(df_raw: pd.DataFrame) -> Dict[str, Tuple[float, float]]:
    """
    Computes strictly point-in-time rolling 20-day median 5-minute volume and ATR for the 09:30-09:34 window.
    For each session d, calculation uses ONLY completed sessions d-20 to d-1.
    """
    open5 = df_raw[(df_raw["m"] >= 570) & (df_raw["m"] <= 574)].copy()
    daily_stats = []

    for d, grp in open5.groupby("date_str", sort=True):
        if len(grp) < 5:
            continue
        v_tot = float(grp["volume"].sum())
        h_max = float(grp["high"].max())
        l_min = float(grp["low"].min())
        rng = h_max - l_min
        daily_stats.append({"date_str": d, "volume": v_tot, "range": rng})

    stats_df = pd.DataFrame(daily_stats)
    stats_df = stats_df.sort_values("date_str").reset_index(drop=True)

    baselines: Dict[str, Tuple[float, float]] = {}
    dates = stats_df["date_str"].tolist()
    volumes = stats_df["volume"].to_numpy()
    ranges = stats_df["range"].to_numpy()

    for i, d in enumerate(dates):
        if i < ROLLING_WINDOW:
            continue
        prior_vol = volumes[i - ROLLING_WINDOW : i]
        prior_rng = ranges[i - ROLLING_WINDOW : i]
        med_vol = float(np.median(prior_vol))
        atr_rng = float(np.mean(prior_rng))
        baselines[d] = (med_vol, atr_rng)

    return baselines


# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def run_backtest():
    register_strategy(
        strategy_id=STRATEGY_ID,
        tier=StrategyTier.CANDIDATE,
        name=STRATEGY_NAME,
        instrument="MNQ",
        timeframe="1m",
        schedule="09:35–09:55 ET",
        description="Cash open uncrossing momentum thrust on MNQ capturing 09:30-09:34 ET volume surge and directional skew.",
    )

    store = default_store
    h_nq = store.compute_data_hash(NQ_PATH)
    print(f"Data SHA-256 (NQ / MNQ): {h_nq}")

    print("Loading raw 1-minute MNQ dataset...")
    df_raw = pd.read_parquet(NQ_PATH, columns=["time", "open", "high", "low", "close", "volume"])
    df_raw["time"] = pd.to_datetime(df_raw["time"])
    df_raw["m"] = df_raw["time"].dt.hour * 60 + df_raw["time"].dt.minute
    df_raw["date_str"] = df_raw["time"].dt.strftime("%Y-%m-%d")

    print("Precomputing point-in-time rolling 20-day 5-minute baselines...")
    baselines = precompute_opening_baselines(df_raw)

    # Filter to 09:30 to 10:00 ET window (m in [570, 600])
    df_rth = df_raw[(df_raw["m"] >= 570) & (df_raw["m"] <= 600)].sort_values("time").reset_index(drop=True)
    day_dict = {d: group.reset_index(drop=True) for d, group in df_rth.groupby("date_str")}
    dates = sorted([d for d in day_dict.keys() if EVAL_START_DATE <= d <= EVAL_END_DATE])

    print(f"Simulating across {len(dates)} sessions ({EVAL_START_DATE} to {EVAL_END_DATE})...\n")

    trades: List[Dict[str, Any]] = []

    for d in dates:
        day_bars = day_dict.get(d)
        if day_bars is None or day_bars.empty:
            continue

        base = baselines.get(d)
        if base is None:
            continue
        med_vol_20, atr_rng_20 = base

        # 1. Opening 5-Minute Window: 09:30:00 to 09:34:59 ET (m in [570, 574])
        open5_bars = day_bars[(day_bars["m"] >= 570) & (day_bars["m"] <= 574)]
        if len(open5_bars) < 5:
            continue

        v_open5 = float(open5_bars["volume"].sum())
        h_open5 = float(open5_bars["high"].max())
        l_open5 = float(open5_bars["low"].min())
        c_open5 = float(open5_bars.iloc[-1]["close"])
        rng_open5 = h_open5 - l_open5

        if rng_open5 <= 0:
            continue

        # 2. Volume Shock & Range Displacement Gates
        if v_open5 < VOLUME_SHOCK_MULT * med_vol_20:
            continue
        if rng_open5 < RANGE_ATR_MULT * atr_rng_20:
            continue

        # 3. Directional Skew Gate
        sig_direction = 0
        # Long Skew: Close >= Low + 0.80 * Range
        if c_open5 >= (l_open5 + SKEW_THRESHOLD * rng_open5):
            sig_direction = 1
        # Short Skew: Close <= Low + 0.20 * Range
        elif c_open5 <= (l_open5 + (1.0 - SKEW_THRESHOLD) * rng_open5):
            sig_direction = -1

        if sig_direction == 0:
            continue

        # 4. Entry at 09:35:00 ET Open (m = 575)
        trade_bars = day_bars[(day_bars["m"] >= 575) & (day_bars["m"] <= 595)]
        if trade_bars.empty or trade_bars.iloc[0]["m"] != 575:
            continue

        entry_p = float(trade_bars.iloc[0]["open"])
        entry_time = trade_bars.iloc[0]["time"]

        # Initial risk brackets
        if sig_direction == 1:
            stop_p = entry_p - STOP_LOSS_POINTS
            target_p = entry_p + PROFIT_TARGET_POINTS
            be_trigger = entry_p + BREAKEVEN_TRIGGER_POINTS
            be_stop = entry_p + BREAKEVEN_BUFFER_POINTS
        else:
            stop_p = entry_p + STOP_LOSS_POINTS
            target_p = entry_p - PROFIT_TARGET_POINTS
            be_trigger = entry_p - BREAKEVEN_TRIGGER_POINTS
            be_stop = entry_p - BREAKEVEN_BUFFER_POINTS

        exit_p = float(trade_bars.iloc[-1]["close"])
        exit_reason = "time_exit_0955"
        exit_time = trade_bars.iloc[-1]["time"]
        is_be_active = False

        for row in trade_bars.itertuples():
            bh = float(row.high)
            bl = float(row.low)
            bo = float(row.open)
            bt = row.time

            if sig_direction == 1:
                # 1. Stop loss check
                if bl <= stop_p:
                    exit_p = min(bo, stop_p) if bo < stop_p else stop_p
                    exit_reason = "breakeven_stop" if is_be_active else "stop_loss"
                    exit_time = bt
                    break

                # 2. Profit target check
                if bh >= target_p:
                    exit_p = target_p
                    exit_reason = "profit_target"
                    exit_time = bt
                    break

                # 3. Trailing Breakeven Trigger (+1.0R MFE -> move to entry + 6.0 pts)
                if not is_be_active and bh >= be_trigger:
                    is_be_active = True
                    stop_p = max(stop_p, be_stop)
                    if bl <= be_stop:
                        exit_p = be_stop
                        exit_reason = "breakeven_stop"
                        exit_time = bt
                        break

            else:  # sig_direction == -1 (Short)
                # 1. Stop loss check
                if bh >= stop_p:
                    exit_p = max(bo, stop_p) if bo > stop_p else stop_p
                    exit_reason = "breakeven_stop" if is_be_active else "stop_loss"
                    exit_time = bt
                    break

                # 2. Profit target check
                if bl <= target_p:
                    exit_p = target_p
                    exit_reason = "profit_target"
                    exit_time = bt
                    break

                # 3. Trailing Breakeven Trigger (+1.0R MFE -> move to entry - 6.0 pts)
                if not is_be_active and bl <= be_trigger:
                    is_be_active = True
                    stop_p = min(stop_p, be_stop)
                    if bh >= be_stop:
                        exit_p = be_stop
                        exit_reason = "breakeven_stop"
                        exit_time = bt
                        break

        gross_pts = (exit_p - entry_p) * sig_direction
        gross_pnl = gross_pts * MNQ_POINT_VAL
        net_pnl = gross_pnl - MNQ_TOTAL_FRICTION

        trades.append({
            "date": d,
            "year": d[:4],
            "entry_time": entry_time,
            "exit_time": exit_time,
            "direction": "LONG" if sig_direction == 1 else "SHORT",
            "dir_num": sig_direction,
            "entry_p": entry_p,
            "exit_p": exit_p,
            "gross_pts": gross_pts,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "win": net_pnl > 0,
            "exit_reason": exit_reason,
            "rng_open5": rng_open5,
            "v_open5": v_open5,
            "med_vol_20": med_vol_20,
            "atr_rng_20": atr_rng_20,
            "is_oos": "IS" if d < IS_SPLIT_DATE else "OOS",
        })

    tdf = pd.DataFrame(trades)
    return tdf, h_nq


# ─────────────────────────────────────────────────────────────────────────────
# METRICS & REPORTING
# ─────────────────────────────────────────────────────────────────────────────

def compute_summary_metrics(tdf: pd.DataFrame, label: str = "") -> Dict[str, Any]:
    if tdf.empty:
        return {
            "label": label,
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "net_profit": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "largest_win": 0.0,
            "largest_win_pct_of_net": 0.0,
        }

    trades_n = len(tdf)
    wins = tdf[tdf["net_pnl"] > 0]["net_pnl"]
    losses = tdf[tdf["net_pnl"] < 0]["net_pnl"]
    gross_win = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    wr = float((tdf["net_pnl"] > 0).mean() * 100.0)
    net_pnl = float(tdf["net_pnl"].sum())

    cum = tdf["net_pnl"].cumsum()
    peak = cum.cummax()
    dd = peak - cum
    max_dd = float(dd.max()) if not dd.empty else 0.0

    daily_pnl = tdf.groupby("date")["net_pnl"].sum()
    if len(daily_pnl) > 1 and daily_pnl.std() > 1e-12:
        sharpe = float(daily_pnl.mean() / daily_pnl.std() * np.sqrt(252.0))
    else:
        sharpe = 0.0

    largest_win = float(tdf["net_pnl"].max()) if not tdf.empty else 0.0
    largest_win_pct = (largest_win / net_pnl * 100.0) if (net_pnl > 0 and largest_win > 0) else 0.0

    return {
        "label": label,
        "trades": trades_n,
        "win_rate": wr,
        "profit_factor": pf,
        "gross_profit": gross_win,
        "gross_loss": gross_loss,
        "net_profit": net_pnl,
        "max_drawdown": max_dd,
        "sharpe_ratio": sharpe,
        "largest_win": largest_win,
        "largest_win_pct_of_net": largest_win_pct,
    }


def main():
    print("=" * 80)
    print(" CANDIDATE RESEARCH: CASH OPEN UNCROSSING MOMENTUM THRUST (H39 / MNQ)")
    print("=" * 80)

    tdf, h_nq = run_backtest()

    m_walk = compute_summary_metrics(tdf, "Full Walkforward (2021-2026)")
    m_is = compute_summary_metrics(tdf[tdf["is_oos"] == "IS"], "In-Sample (2021-2024)")
    m_oos = compute_summary_metrics(tdf[tdf["is_oos"] == "OOS"], "Out-of-Sample (2025-2026)")

    print("\n" + "=" * 80)
    print(" PERFORMANCE SCORECARD (Belfort Steps 04 & 05)")
    print("=" * 80)
    print(f"{'Partition':<28} | {'Trades':<7} | {'Win%':<7} | {'PF':<6} | {'Net PnL':<12} | {'MaxDD':<10} | {'Sharpe':<6}")
    print("-" * 86)
    for m in (m_walk, m_is, m_oos):
        print(f"{m['label']:<28} | {m['trades']:<7} | {m['win_rate']:>6.1f}% | {m['profit_factor']:>6.2f} | ${m['net_profit']:>10,.2f} | -${m['max_drawdown']:>8,.2f} | {m['sharpe_ratio']:>6.2f}")

    print("\n" + "-" * 80)
    print(" YEARLY BREAKDOWN:")
    print("-" * 80)
    for yr in sorted(tdf["year"].unique()):
        sub_yr = tdf[tdf["year"] == yr]
        myr = compute_summary_metrics(sub_yr, yr)
        print(f"  {yr}: {myr['trades']:>3} tr | WR: {myr['win_rate']:>5.1f}% | PF: {myr['profit_factor']:>5.2f} | Net: ${myr['net_profit']:>9,.2f} | MaxDD: -${myr['max_drawdown']:>7,.2f}")

    print("\n" + "-" * 80)
    print(" DIRECTIONAL & EXIT BREAKDOWN:")
    print("-" * 80)
    for d in ("LONG", "SHORT"):
        sub_d = tdf[tdf["direction"] == d]
        md = compute_summary_metrics(sub_d, d)
        print(f"  Direction {d:<5}: {md['trades']:>3} tr | WR: {md['win_rate']:>5.1f}% | PF: {md['profit_factor']:>5.2f} | Net: ${md['net_profit']:>9,.2f}")

    print("\n  Exit Reasons:")
    for reason, cnt in tdf["exit_reason"].value_counts().items():
        sub_r = tdf[tdf["exit_reason"] == reason]
        pnl_r = sub_r["net_pnl"].sum()
        print(f"    - {reason:<16}: {cnt:>3} trades ({cnt / len(tdf) * 100:.1f}%) | Net PnL: ${pnl_r:>9,.2f}")

    # ACID Provenance Store Recording
    store = default_store
    run_id = f"{STRATEGY_ID}_2021_2026"

    daily_returns_series = tdf.groupby("date")["net_pnl"].sum()
    inst_metrics = calculate_institutional_metrics(
        tdf["net_pnl"].to_numpy(),
        daily_returns=daily_returns_series,
        capital=25000.0,
    )

    warnings = ["CANDIDATE_TIER_QUARANTINED"]
    if m_walk["profit_factor"] < 1.0 or m_walk["net_profit"] < 0:
        warnings.append("FALSIFIED_HYPOTHESIS")
    if m_walk["trades"] < 30:
        warnings.append("LOW_SAMPLE_SIZE")
    if m_walk["largest_win_pct_of_net"] > 35.0:
        warnings.append("OUTLIER_DOMINANCE")

    record = store.record_run(
        run_id=run_id,
        strategy_id=STRATEGY_ID,
        strategy_name=STRATEGY_NAME,
        strategy_tier=StrategyTier.CANDIDATE.value,
        methodology="multi_year_walkforward",
        date_start=EVAL_START_DATE,
        date_end=EVAL_END_DATE,
        data_path=str(NQ_PATH),
        total_trades=m_walk["trades"],
        win_rate=m_walk["win_rate"],
        profit_factor=m_walk["profit_factor"],
        gross_profit=m_walk["gross_profit"],
        net_profit=m_walk["net_profit"],
        max_drawdown=m_walk["max_drawdown"],
        sharpe_ratio=m_walk["sharpe_ratio"],
        largest_win=m_walk["largest_win"],
        slippage_model="1 tick adverse parity ($1.00/RT)",
        commission_model="$1.40 round-trip micro",
        is_net=True,
        explicit_warnings=warnings,
        extended_metrics=inst_metrics,
        params={
            "nq_hash": h_nq,
            "open5_window": "09:30-09:34 ET",
            "entry_time": "09:35 ET",
            "time_exit": "09:55 ET",
            "volume_shock_mult": VOLUME_SHOCK_MULT,
            "range_atr_mult": RANGE_ATR_MULT,
            "skew_threshold": SKEW_THRESHOLD,
            "stop_loss_points": STOP_LOSS_POINTS,
            "profit_target_points": PROFIT_TARGET_POINTS,
            "breakeven_trigger_points": BREAKEVEN_TRIGGER_POINTS,
            "breakeven_buffer_points": BREAKEVEN_BUFFER_POINTS,
            "point_value": MNQ_POINT_VAL,
            "commission_rt": MNQ_COMMISSION_RT,
            "slippage_rt": MNQ_SLIPPAGE_COST,
            "total_friction": MNQ_TOTAL_FRICTION,
        },
        notes="H39 Cash open uncrossing momentum thrust on MNQ capturing 09:30-09:34 ET volume surge and directional skew.",
    )

    # Standardized Provenance Verification Footer (Rule 2 & 3)
    print("\n" + "─" * 76)
    print("PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)")
    print("─" * 76)
    print(f"Run ID       : {record.run_id}")
    print(f"Strategy     : {record.strategy_id} — {record.strategy_name} [{record.strategy_tier}]")
    print(f"Methodology  : {record.methodology}")
    print(f"Date Range   : {record.date_start} to {record.date_end} ({record.days_count} days)")
    print(f"Data File    : {record.data_path}")
    print(f"Data SHA-256 : {record.data_hash}")
    print(f"Git Commit   : {record.git_commit}")
    print(f"Cost Model   : {record.slippage_model} | {record.commission_model} [NET]")
    print(f"Metrics      : Trades: {record.total_trades} | Win%: {record.win_rate:.1f}% | PF: {record.profit_factor:.2f} | Net: ${record.net_profit:,.2f} | MaxDD: -${record.max_drawdown:,.2f} | Sharpe: {record.sharpe_ratio:.2f}")
    warn_str = ", ".join(record.warnings) if record.warnings else "None"
    print(f"Warning Flags: {warn_str}")
    print("─" * 76)


if __name__ == "__main__":
    main()