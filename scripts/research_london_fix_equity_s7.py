#!/usr/bin/env python3
"""
Candidate Strategy S7 (H33): London 4 PM Global Benchmark Fix Equity Drive (10:50 ET on MES).

Structural Premise:
At 11:00 AM ET (16:00 London), the WM/Refinitiv 4:00 PM London Fix settles the daily benchmark exchange
rates and equity index portfolio valuations for global asset managers (MSCI World, FTSE, global pension funds).
Multi-trillion dollar asset allocators rebalance international equity hedges and cash overlays leading directly
into the 11:00 AM ET fixing valuation window. When pre-fix accumulation (10:45–10:49 ET) breaks toward morning
extremes, institutional momentum drives through the 11:00 AM ET fix. Liquidating at 11:15 ET captures this
institutional hedging wave while exiting before the 11:30 ET European cash equity closing auction.

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

STRATEGY_ID = "candidate_london_fix_equity_s7"
STRATEGY_NAME = "London 4 PM Global Benchmark Fix Equity Drive (10:50 ET on MES)"

ES_PATH = REPO_ROOT / "data" / "raw" / "es_1m_2020_2026_cqg_et.parquet"

# MES Contract Specifications
MES_POINT_VAL = 5.00         # $5.00 per index point ($1.25 per 0.25 tick)
MES_TICK_SIZE = 0.25         # 0.25 index points
MES_COMMISSION_RT = 1.40     # $1.40 round-trip per micro contract ($0.70/side)
MES_SLIPPAGE_TICKS = 1       # 1 tick adverse entry + 1 tick adverse exit
MES_SLIPPAGE_COST = 2 * MES_TICK_SIZE * MES_POINT_VAL  # $2.50 total slippage ($1.25 / side)
MES_TOTAL_FRICTION = MES_COMMISSION_RT + MES_SLIPPAGE_COST  # $3.90 total round-turn friction

# Risk Brackets (in index points)
STOP_LOSS_POINTS = 7.00       # $35.00 risk per micro contract
PROFIT_TARGET_POINTS = 14.00  # $70.00 target per micro contract (1:2.0 R:R)
BREAKEVEN_TRIGGER_POINTS = 7.00   # +1.0R excursion moves stop to Breakeven
BREAKEVEN_BUFFER_POINTS = 0.25    # +1 tick breakeven buffer (+0.25 pt)

# Gate Parameters
DISPLACEMENT_BUFFER_POINTS = 2.00  # Close_1049 > Open_1045 + 2.0 or Close_1049 < Open_1045 - 2.0
PRE_FIX_EXTREME_RATIO = 0.15       # Within top/bottom 15% of pre-fix range

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
        instrument="MES",
        timeframe="1m",
        schedule="10:50–11:15 ET",
        description="London 4 PM (11:00 AM ET) WM/Refinitiv global benchmark fix equity hedging drive on MES leading into fixing valuation window.",
    )

    store = default_store
    h_es = store.compute_data_hash(ES_PATH)
    print(f"Data SHA-256 (ES / MES): {h_es}")

    print("Loading raw 1-minute MES dataset...")
    df_raw = pd.read_parquet(ES_PATH, columns=["time", "open", "high", "low", "close", "volume"])
    df_raw["time"] = pd.to_datetime(df_raw["time"])
    df_raw["m"] = df_raw["time"].dt.hour * 60 + df_raw["time"].dt.minute
    df_raw["date_str"] = df_raw["time"].dt.strftime("%Y-%m-%d")

    # Filter to 10:00 to 11:20 ET window (m in [600, 680])
    df_rth = df_raw[(df_raw["m"] >= 600) & (df_raw["m"] <= 680)].sort_values("time").reset_index(drop=True)
    day_dict = {d: group.reset_index(drop=True) for d, group in df_rth.groupby("date_str")}
    dates = sorted([d for d in day_dict.keys() if EVAL_START_DATE <= d <= EVAL_END_DATE])

    print(f"Simulating across {len(dates)} sessions ({EVAL_START_DATE} to {EVAL_END_DATE})...\n")

    trades: List[Dict[str, Any]] = []

    for d in dates:
        day_bars = day_dict.get(d)
        if day_bars is None or day_bars.empty:
            continue

        # 1. European Morning Consolidation Range: 10:00:00 to 10:44:59 ET (m in [600, 644])
        pre_fix_bars = day_bars[(day_bars["m"] >= 600) & (day_bars["m"] <= 644)]
        if len(pre_fix_bars) < 40:
            continue

        h_pre_fix = float(pre_fix_bars["high"].max())
        l_pre_fix = float(pre_fix_bars["low"].min())
        range_pre_fix = h_pre_fix - l_pre_fix
        if range_pre_fix <= 0:
            continue

        # 2. Momentum Displacement Window: 10:45:00 to 10:49:59 ET (m in [645, 649])
        thrust_bars = day_bars[(day_bars["m"] >= 645) & (day_bars["m"] <= 649)]
        if len(thrust_bars) < 4:
            continue

        o_1045 = float(thrust_bars.iloc[0]["open"])
        c_1049 = float(thrust_bars.iloc[-1]["close"])

        sig_direction = 0
        # Bullish Fixing Drive
        if c_1049 >= (h_pre_fix - PRE_FIX_EXTREME_RATIO * range_pre_fix) and c_1049 > (o_1045 + DISPLACEMENT_BUFFER_POINTS):
            sig_direction = 1
        # Bearish Fixing Drive
        elif c_1049 <= (l_pre_fix + PRE_FIX_EXTREME_RATIO * range_pre_fix) and c_1049 < (o_1045 - DISPLACEMENT_BUFFER_POINTS):
            sig_direction = -1

        if sig_direction == 0:
            continue

        # 3. Entry at 10:50:00 ET Open (m = 650)
        trade_bars = day_bars[(day_bars["m"] >= 650) & (day_bars["m"] <= 675)]
        if trade_bars.empty or trade_bars.iloc[0]["m"] != 650:
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
        exit_reason = "time_exit_1115"
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
                    if bh >= be_stop:
                        exit_p = be_stop
                        exit_reason = "breakeven_stop"
                        exit_time = bt
                        break

        gross_pts = (exit_p - entry_p) * sig_direction
        gross_pnl = gross_pts * MES_POINT_VAL
        net_pnl = gross_pnl - MES_TOTAL_FRICTION

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
            "range_pre_fix": range_pre_fix,
            "thrust_points": (c_1049 - o_1045),
            "is_oos": "IS" if d < IS_SPLIT_DATE else "OOS",
        })

    tdf = pd.DataFrame(trades)
    return tdf, h_es


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
    print(" CANDIDATE RESEARCH: LONDON 4 PM BENCHMARK FIX EQUITY DRIVE (H33 / MES)")
    print("=" * 80)

    tdf, h_es = run_backtest()

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
        data_path=str(ES_PATH),
        total_trades=m_walk["trades"],
        win_rate=m_walk["win_rate"],
        profit_factor=m_walk["profit_factor"],
        gross_profit=m_walk["gross_profit"],
        net_profit=m_walk["net_profit"],
        max_drawdown=m_walk["max_drawdown"],
        sharpe_ratio=m_walk["sharpe_ratio"],
        largest_win=m_walk["largest_win"],
        slippage_model="1 tick adverse parity ($2.50/RT)",
        commission_model="$1.40 round-trip micro",
        is_net=True,
        explicit_warnings=warnings,
        extended_metrics=inst_metrics,
        params={
            "es_hash": h_es,
            "pre_fix_window": "10:00-10:44 ET",
            "thrust_window": "10:45-10:49 ET",
            "entry_time": "10:50 ET",
            "time_exit": "11:15 ET",
            "displacement_buffer_points": DISPLACEMENT_BUFFER_POINTS,
            "pre_fix_extreme_ratio": PRE_FIX_EXTREME_RATIO,
            "stop_loss_points": STOP_LOSS_POINTS,
            "profit_target_points": PROFIT_TARGET_POINTS,
            "breakeven_trigger_points": BREAKEVEN_TRIGGER_POINTS,
            "breakeven_buffer_points": BREAKEVEN_BUFFER_POINTS,
            "point_value": MES_POINT_VAL,
            "commission_rt": MES_COMMISSION_RT,
            "slippage_rt": MES_SLIPPAGE_COST,
            "total_friction": MES_TOTAL_FRICTION,
        },
        notes="H33 London 4 PM (11:00 AM ET) WM/Refinitiv global benchmark fix equity hedging drive on MES leading into fixing valuation window.",
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
