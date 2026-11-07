#!/usr/bin/env python3
"""
Candidate Strategy S6 (H32): Post-Lunch Institutional Capital Deployment (13:00 ET on MNQ).

Structural Premise:
Between 11:30 and 12:59 ET (NY lunch lull), institutional algorithmic trading drops significantly,
compressing price into a narrow consolidation range. At 13:00:00 ET, US institutional desks return
and restart afternoon order flow (frequently catalyzed by 13:00 ET US Treasury note/bond auction settlements).
When institutional volume surges >= 1.30x lunch median and breaks through the lunch compression boundary,
price accelerates in a clean directional expansion toward morning session extremes. Trade exits strictly
by 13:55:00 ET, completely avoiding late-afternoon 0DTE gamma chop and MOC auction whipsaws.

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

STRATEGY_ID = "candidate_lunch_compression_s6"
STRATEGY_NAME = "Post-Lunch Institutional Capital Deployment (13:00 ET on MNQ)"

NQ_PATH = REPO_ROOT / "data" / "raw" / "nq_1m_2017_2026_cqg_et.parquet"

# MNQ Contract Specifications
MNQ_POINT_VAL = 2.00         # $2.00 per index point ($0.50 per 0.25 tick)
MNQ_TICK_SIZE = 0.25         # 0.25 index points
MNQ_COMMISSION_RT = 1.40     # $1.40 round-trip per micro contract ($0.70/side)
MNQ_SLIPPAGE_TICKS = 1       # 1 tick adverse entry + 1 tick adverse exit
MNQ_SLIPPAGE_COST = 2 * MNQ_TICK_SIZE * MNQ_POINT_VAL  # $1.00 total slippage ($0.50 / side)
MNQ_TOTAL_FRICTION = MNQ_COMMISSION_RT + MNQ_SLIPPAGE_COST  # $2.40 total round-turn friction

# Risk Brackets (in index points)
STOP_LOSS_POINTS = 26.00      # $52.00 risk per micro contract
PROFIT_TARGET_POINTS = 52.00  # $104.00 target per micro contract (1:2.0 R:R)
BREAKEVEN_TRIGGER_POINTS = 26.00  # +1.0R excursion moves stop to Breakeven
BREAKEVEN_BUFFER_POINTS = 0.25    # +1 tick breakeven buffer (+0.25 pt)

# Gate Parameters
LUNCH_COMPRESSION_RATIO = 0.45    # Range_lunch <= 0.45 * Range_morning
VOLUME_SURGE_RATIO = 1.30         # Breakout volume >= 1.30 * Volume_lunch_median
BREAKOUT_BUFFER_POINTS = 2.00     # Breakout requires Close > High_lunch + 2.0 or Close < Low_lunch - 2.0

EVAL_START_DATE = "2021-01-04"
EVAL_END_DATE = "2026-10-30"
IS_SPLIT_DATE = "2025-01-01"


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
        schedule="13:00–13:55 ET",
        description="Post-lunch institutional capital deployment on MNQ following 12:00-12:59 ET volume compression and 13:00-13:20 ET breakout.",
    )

    store = default_store
    h_nq = store.compute_data_hash(NQ_PATH)
    print(f"Data SHA-256 (NQ / MNQ): {h_nq}")

    print("Loading raw 1-minute NQ dataset...")
    df_raw = pd.read_parquet(NQ_PATH, columns=["time", "open", "high", "low", "close", "volume"])
    df_raw["time"] = pd.to_datetime(df_raw["time"])
    df_raw["m"] = df_raw["time"].dt.hour * 60 + df_raw["time"].dt.minute
    df_raw["date_str"] = df_raw["time"].dt.strftime("%Y-%m-%d")

    # Filter to 09:30 to 14:00 ET window (m in [570, 840])
    df_rth = df_raw[(df_raw["m"] >= 570) & (df_raw["m"] <= 840)].sort_values("time").reset_index(drop=True)
    day_dict = {d: group.reset_index(drop=True) for d, group in df_rth.groupby("date_str")}
    dates = sorted([d for d in day_dict.keys() if EVAL_START_DATE <= d <= EVAL_END_DATE])

    print(f"Simulating across {len(dates)} sessions ({EVAL_START_DATE} to {EVAL_END_DATE})...\n")

    trades: List[Dict[str, Any]] = []

    for d in dates:
        day_bars = day_dict.get(d)
        if day_bars is None or day_bars.empty:
            continue

        # 1. Morning Range Window: 09:30:00 to 11:59:59 ET (m in [570, 719])
        morning_bars = day_bars[(day_bars["m"] >= 570) & (day_bars["m"] <= 719)]
        if len(morning_bars) < 130:
            continue

        h_morning = float(morning_bars["high"].max())
        l_morning = float(morning_bars["low"].min())
        range_morning = h_morning - l_morning
        if range_morning <= 0:
            continue

        # 2. Lunch Consolidation Window: 12:00:00 to 12:59:59 ET (m in [720, 779])
        lunch_bars = day_bars[(day_bars["m"] >= 720) & (day_bars["m"] <= 779)]
        if len(lunch_bars) < 50:
            continue

        h_lunch = float(lunch_bars["high"].max())
        l_lunch = float(lunch_bars["low"].min())
        range_lunch = h_lunch - l_lunch
        v_lunch_median = float(lunch_bars["volume"].median())

        if v_lunch_median <= 0:
            continue

        # Gate: Lunch range must be compressed (<= 0.45 * Morning Range)
        if range_lunch > LUNCH_COMPRESSION_RATIO * range_morning:
            continue

        # 3. Post-Lunch Breakout Scan: 13:00:00 to 13:20:59 ET (m in [780, 800])
        post_lunch_bars = day_bars[(day_bars["m"] >= 780) & (day_bars["m"] <= 800)]
        if post_lunch_bars.empty:
            continue

        sig_direction = 0
        sig_bar_idx = -1

        for idx, row in post_lunch_bars.iterrows():
            c_bar = float(row["close"])
            v_bar = float(row["volume"])

            # Check volume surge condition
            if v_bar < VOLUME_SURGE_RATIO * v_lunch_median:
                continue

            # Check price breakout condition
            if c_bar > h_lunch + BREAKOUT_BUFFER_POINTS:
                sig_direction = 1  # Long
                sig_bar_idx = idx
                break
            elif c_bar < l_lunch - BREAKOUT_BUFFER_POINTS:
                sig_direction = -1  # Short
                sig_bar_idx = idx
                break

        # If no valid breakout occurred by 13:20:00 ET, cancel setup
        if sig_direction == 0 or sig_bar_idx < 0:
            continue

        # Entry at next bar open following confirmed breakout
        trade_bars = day_bars.loc[sig_bar_idx + 1 :]
        trade_bars = trade_bars[trade_bars["m"] <= 835]  # strictly up to 13:55:00 ET

        if trade_bars.empty:
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
        exit_reason = "time_exit_1355"
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

                # 3. Trailing Breakeven Trigger (+1.0R MFE)
                if not is_be_active and bh >= be_trigger:
                    is_be_active = True
                    stop_p = max(stop_p, be_stop)
                    # Conservative fill: if same bar also dipped back to breakeven stop
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

                # 3. Trailing Breakeven Trigger (+1.0R MFE)
                if not is_be_active and bl <= be_trigger:
                    is_be_active = True
                    stop_p = min(stop_p, be_stop)
                    # Conservative fill: if same bar also retraced back to breakeven stop
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
            "range_morning": range_morning,
            "range_lunch": range_lunch,
            "compression_ratio": range_lunch / range_morning,
            "v_lunch_median": v_lunch_median,
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
    print(" CANDIDATE RESEARCH: POST-LUNCH INSTITUTIONAL CAPITAL DEPLOYMENT (H32 / MNQ)")
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
            "morning_window": "09:30-11:59 ET",
            "lunch_window": "12:00-12:59 ET",
            "breakout_scan_window": "13:00-13:20 ET",
            "compression_ratio_max": LUNCH_COMPRESSION_RATIO,
            "volume_surge_ratio_min": VOLUME_SURGE_RATIO,
            "breakout_buffer_points": BREAKOUT_BUFFER_POINTS,
            "stop_loss_points": STOP_LOSS_POINTS,
            "profit_target_points": PROFIT_TARGET_POINTS,
            "breakeven_trigger_points": BREAKEVEN_TRIGGER_POINTS,
            "breakeven_buffer_points": BREAKEVEN_BUFFER_POINTS,
            "time_exit": "13:55 ET",
            "point_value": MNQ_POINT_VAL,
            "commission_rt": MNQ_COMMISSION_RT,
            "slippage_rt": MNQ_SLIPPAGE_COST,
            "total_friction": MNQ_TOTAL_FRICTION,
        },
        notes="H32 Post-Lunch Institutional Capital Deployment on MNQ following 12:00-12:59 ET lunch compression and 13:00-13:20 ET breakout.",
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
