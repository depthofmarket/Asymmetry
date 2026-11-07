#!/usr/bin/env python3
"""
Candidate Strategy S5 (H31): Value vs Growth Factor Dispersion Momentum (10:15 ET on MYM).

Structural Premise:
By 10:15 ET (45 minutes post-open), the cash market has completed its initial price discovery.
When a substantial factor dispersion opens between Value (Dow 30 / MYM) and Growth (Nasdaq 100 / MNQ)
such that |r_MYM - r_NQ| >= 0.30% and MYM trades near morning session extremes, institutional sector
rotation programs exhibit directional persistence. Entering on a breakout of the 10:15 ET candle
extreme captures the 10:16–11:00 ET factor expansion before European cash closes.

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

STRATEGY_ID = "candidate_factor_dispersion_s5"
STRATEGY_NAME = "Value vs Growth Factor Dispersion Momentum (10:15 ET on MYM)"

YM_PATH = REPO_ROOT / "data" / "raw" / "ym_1m_2020_2026_et.parquet"
NQ_PATH = REPO_ROOT / "data" / "raw" / "nq_1m_2017_2026_cqg_et.parquet"

# MYM Contract Specifications
MYM_POINT_VAL = 0.50         # $0.50 per index point ($0.50 per 1.0 tick)
MYM_TICK_SIZE = 1.00         # 1.0 index point
MYM_COMMISSION_RT = 1.40     # $1.40 round-trip per micro contract ($0.70/side)
MYM_SLIPPAGE_TICKS = 1       # 1 tick adverse entry + 1 tick adverse exit
MYM_SLIPPAGE_COST = 2 * MYM_TICK_SIZE * MYM_POINT_VAL  # $1.00 total slippage ($0.50 / side)
MYM_TOTAL_FRICTION = MYM_COMMISSION_RT + MYM_SLIPPAGE_COST  # $2.40 total round-turn friction

# Risk Brackets (in index points)
STOP_LOSS_POINTS = 50.00       # $25.00 risk per micro contract
PROFIT_TARGET_POINTS = 100.00  # $50.00 target per micro contract (1:2.0 R:R)
BREAKEVEN_TRIGGER_POINTS = 50.00  # +1.0R excursion moves stop to Breakeven
BREAKEVEN_BUFFER_POINTS = 1.00    # +1 tick breakeven buffer (+1.0 pt)

# Gate Parameters
DISPERSION_THRESHOLD = 0.0030  # |r_MYM - r_NQ| >= 0.30%
RANGE_EXTREME_RATIO = 0.20     # Within 20% of morning high/low

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
        instrument="MYM",
        timeframe="1m",
        schedule="10:15–11:00 ET",
        description="Value vs Growth Factor Dispersion Momentum on MYM following 10:15 ET cross-asset divergence with NQ.",
    )

    store = default_store
    h_ym = store.compute_data_hash(YM_PATH)
    h_nq = store.compute_data_hash(NQ_PATH)
    print(f"Data SHA-256 (YM / MYM): {h_ym}")
    print(f"Data SHA-256 (NQ / MNQ): {h_nq}")

    print("Loading raw 1-minute datasets (YM & NQ)...")
    df_ym = pd.read_parquet(YM_PATH, columns=["time", "open", "high", "low", "close", "volume"])
    df_nq = pd.read_parquet(NQ_PATH, columns=["time", "open", "high", "low", "close", "volume"])

    for df in (df_ym, df_nq):
        df["time"] = pd.to_datetime(df["time"])
        df["m"] = df["time"].dt.hour * 60 + df["time"].dt.minute
        df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")

    # Filter to 09:30 to 11:05 ET window (m in [570, 665])
    ym_rth = df_ym[(df_ym["m"] >= 570) & (df_ym["m"] <= 665)].sort_values("time").reset_index(drop=True)
    nq_rth = df_nq[(df_nq["m"] >= 570) & (df_nq["m"] <= 665)].sort_values("time").reset_index(drop=True)

    ym_dict = {d: group.reset_index(drop=True) for d, group in ym_rth.groupby("date_str")}
    nq_dict = {d: group.reset_index(drop=True) for d, group in nq_rth.groupby("date_str")}

    common_dates = sorted(list(set(ym_dict.keys()) & set(nq_dict.keys())))
    dates = [d for d in common_dates if EVAL_START_DATE <= d <= EVAL_END_DATE]

    print(f"Simulating across {len(dates)} sessions ({EVAL_START_DATE} to {EVAL_END_DATE})...\n")

    trades: List[Dict[str, Any]] = []

    for d in dates:
        ym_day = ym_dict.get(d)
        nq_day = nq_dict.get(d)

        if ym_day is None or nq_day is None:
            continue

        # 1. Morning Range on MYM: 09:30:00 to 10:14:59 ET (m in [570, 614])
        ym_morning = ym_day[(ym_day["m"] >= 570) & (ym_day["m"] <= 614)]
        nq_morning = nq_day[(nq_day["m"] >= 570) & (nq_day["m"] <= 614)]

        if len(ym_morning) < 42 or len(nq_morning) < 42:
            continue

        h_morning = float(ym_morning["high"].max())
        l_morning = float(ym_morning["low"].min())
        range_morning = h_morning - l_morning
        if range_morning <= 0:
            continue

        o_mym_0930 = float(ym_morning.iloc[0]["open"])
        o_nq_0930 = float(nq_morning.iloc[0]["open"])
        if o_mym_0930 <= 0 or o_nq_0930 <= 0:
            continue

        # 2. 10:15:00 ET Reference Candle (m = 615)
        ym_1015 = ym_day[ym_day["m"] == 615]
        nq_1015 = nq_day[nq_day["m"] == 615]
        if ym_1015.empty or nq_1015.empty:
            continue

        c_mym_1015 = float(ym_1015.iloc[0]["close"])
        c_nq_1015 = float(nq_1015.iloc[0]["close"])
        h_ref = float(ym_1015.iloc[0]["high"])
        l_ref = float(ym_1015.iloc[0]["low"])

        # 3. Factor Dispersion Calculation
        r_mym = (c_mym_1015 - o_mym_0930) / o_mym_0930
        r_nq = (c_nq_1015 - o_nq_0930) / o_nq_0930
        delta_factor = r_mym - r_nq

        # Dispersion Gate & Range Confirmation
        sig_direction = 0
        if delta_factor >= DISPERSION_THRESHOLD and c_mym_1015 >= (h_morning - RANGE_EXTREME_RATIO * range_morning):
            sig_direction = 1  # Bullish Value
        elif delta_factor <= -DISPERSION_THRESHOLD and c_mym_1015 <= (l_morning + RANGE_EXTREME_RATIO * range_morning):
            sig_direction = -1  # Bearish Value

        if sig_direction == 0:
            continue

        # 4. Entry Scan: Break of 10:15 candle extreme between 10:16 and 10:25 ET (m in [616, 625])
        scan_bars = ym_day[(ym_day["m"] >= 616) & (ym_day["m"] <= 625)]
        if scan_bars.empty:
            continue

        entry_idx = -1
        entry_p = 0.0
        entry_time = None

        for idx, row in scan_bars.iterrows():
            bh = float(row["high"])
            bl = float(row["low"])
            bo = float(row["open"])

            if sig_direction == 1:
                if bh > h_ref:
                    # Breakout Long: stop order filled at level + 1 tick or bar open if gapped
                    entry_p = max(bo, h_ref + MYM_TICK_SIZE)
                    entry_idx = idx
                    entry_time = row["time"]
                    break
            else:
                if bl < l_ref:
                    # Breakout Short: stop order filled at level - 1 tick or bar open if gapped
                    entry_p = min(bo, l_ref - MYM_TICK_SIZE)
                    entry_idx = idx
                    entry_time = row["time"]
                    break

        # If no breakout by 10:25 ET, setup canceled
        if entry_idx < 0 or entry_time is None:
            continue

        # 5. Risk Brackets & Intrabar Simulation (up to 11:00:00 ET / m = 660)
        trade_bars = ym_day.loc[entry_idx:]
        trade_bars = trade_bars[trade_bars["m"] <= 660]
        if trade_bars.empty:
            continue

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
        exit_reason = "time_exit_1100"
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
        gross_pnl = gross_pts * MYM_POINT_VAL
        net_pnl = gross_pnl - MYM_TOTAL_FRICTION

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
            "delta_factor": delta_factor,
            "r_mym": r_mym,
            "r_nq": r_nq,
            "range_morning": range_morning,
            "is_oos": "IS" if d < IS_SPLIT_DATE else "OOS",
        })

    tdf = pd.DataFrame(trades)
    return tdf, h_ym, h_nq


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
    print(" CANDIDATE RESEARCH: VALUE VS GROWTH FACTOR DISPERSION (H31 / MYM)")
    print("=" * 80)

    tdf, h_ym, h_nq = run_backtest()

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
        data_path=str(YM_PATH),
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
            "ym_hash": h_ym,
            "nq_hash": h_nq,
            "dispersion_threshold": DISPERSION_THRESHOLD,
            "range_extreme_ratio": RANGE_EXTREME_RATIO,
            "stop_loss_points": STOP_LOSS_POINTS,
            "profit_target_points": PROFIT_TARGET_POINTS,
            "breakeven_trigger_points": BREAKEVEN_TRIGGER_POINTS,
            "breakeven_buffer_points": BREAKEVEN_BUFFER_POINTS,
            "time_exit": "11:00 ET",
            "point_value": MYM_POINT_VAL,
            "commission_rt": MYM_COMMISSION_RT,
            "slippage_rt": MYM_SLIPPAGE_COST,
            "total_friction": MYM_TOTAL_FRICTION,
        },
        notes="H31 Value vs Growth Factor Dispersion Momentum on MYM following 10:15 ET cross-asset divergence with NQ.",
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
