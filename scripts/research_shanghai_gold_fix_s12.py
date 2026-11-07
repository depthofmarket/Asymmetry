#!/usr/bin/env python3
"""
Candidate Strategy S12 (H44): Shanghai Gold Exchange AM Benchmark Fix Arbitrage Drive (MGC).

Structural Premise:
At 10:15 AM Beijing Time (02:15:00 UTC invariant), the Shanghai Gold Exchange (SGE) publishes its official
AM Benchmark Price Fix. China is the world's largest physical gold consumer and importer. The SGE contract
trades at a structural premium or discount to London/COMEX pricing depending on domestic physical demand
and PBOC import quotas. Leading up to 02:15 UTC, global bullion banks, Swiss refiners, and domestic Chinese
commercials adjust COMEX inventory hedges. When 02:00–02:14 UTC pre-fix order flow breaks out past 02:15 UTC,
it triggers persistent arbitrage diffusion into the Asian morning session before European desks arrive.

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

STRATEGY_ID = "candidate_shanghai_gold_s12"
STRATEGY_NAME = "Shanghai Gold Exchange AM Benchmark Fix Arbitrage Drive (MGC)"

GC_PATH = REPO_ROOT / "data" / "raw" / "gc_1m_2020_2026_et.parquet"

# MGC Contract Specifications
MGC_POINT_VAL = 10.00        # $10.00 per index point ($1.00 per 0.10 tick)
MGC_TICK_SIZE = 0.10         # 0.10 index points
MGC_COMMISSION_RT = 1.40     # $1.40 round-trip per micro contract ($0.70/side)
MGC_SLIPPAGE_TICKS = 1       # 1 tick adverse entry + 1 tick adverse exit
MGC_SLIPPAGE_COST = 2 * MGC_TICK_SIZE * MGC_POINT_VAL  # $2.00 total slippage ($1.00 / side)
MGC_TOTAL_FRICTION = MGC_COMMISSION_RT + MGC_SLIPPAGE_COST  # $3.40 total round-turn friction

# SGE AM Fix Timing (UTC Invariant)
FIX_START_MIN_UTC = 120      # 02:00 UTC (10:00 Beijing)
FIX_END_MIN_UTC = 134        # 02:14 UTC (10:14 Beijing)
SCAN_START_MIN_UTC = 135     # 02:15 UTC (10:15 Beijing - Fix print)
SCAN_END_MIN_UTC = 165       # 02:45 UTC (10:45 Beijing)
TIME_EXIT_MIN_UTC = 225      # 03:45 UTC (11:45 Beijing)

# Gate & Risk Parameters
MIN_FIX_RANGE = 1.50         # Range_fix >= 1.50 pts
MAX_FIX_RANGE = 12.00        # Range_fix <= 12.00 pts
CLOSE_LOC_LONG_MIN = 0.65    # Close location >= 0.65 for Long
CLOSE_LOC_SHORT_MAX = 0.35   # Close location <= 0.35 for Short
BREAKOUT_BUFFER = 0.30       # Close > High_fix + 0.30 or Close < Low_fix - 0.30
MIN_STOP_POINTS = 3.50       # Minimum stop loss clamp
MAX_STOP_POINTS = 7.00       # Maximum stop loss clamp
BREAKEVEN_BUFFER = 0.10      # +1 tick breakeven buffer (+0.10 pt)

EVAL_START_DATE = "2020-01-01"
EVAL_END_DATE = "2026-10-30"
IS_SPLIT_DATE = "2025-01-01"


# ─────────────────────────────────────────────────────────────────────────────
# TIMEZONE NORMALIZATION & DATA INGESTION
# ─────────────────────────────────────────────────────────────────────────────

def load_and_convert_gc_data(gc_path: Path) -> pd.DataFrame:
    """
    Loads raw 1-minute MGC dataset in US Eastern Time and normalizes to UTC.
    Because China does not observe DST, SGE Fix is strictly invariant in UTC.
    """
    print("Loading raw 1-minute MGC dataset...")
    df = pd.read_parquet(gc_path, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"])

    # Localize to America/New_York and convert to UTC
    if df["time"].dt.tz is None:
        df["time_utc"] = df["time"].dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    else:
        df["time_utc"] = df["time"].dt.tz_convert("UTC")

    df = df.dropna(subset=["time_utc"]).copy()
    df["m_utc"] = df["time_utc"].dt.hour * 60 + df["time_utc"].dt.minute
    df["date_utc"] = df["time_utc"].dt.strftime("%Y-%m-%d")

    # Filter to UTC window of interest: 01:55 to 03:50 UTC (m_utc in [115, 230])
    df_window = df[(df["m_utc"] >= 115) & (df["m_utc"] <= 230)].sort_values("time_utc").reset_index(drop=True)
    return df_window


# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST ENGINE (PARAMETRIC)
# ─────────────────────────────────────────────────────────────────────────────

def simulate_strategy(
    day_dict: Dict[str, pd.DataFrame],
    dates: List[str],
    long_only: bool = True,
    rr_mult: float = 2.5,
) -> pd.DataFrame:
    trades: List[Dict[str, Any]] = []

    for d in dates:
        day_bars = day_dict.get(d)
        if day_bars is None or day_bars.empty:
            continue

        # 1. Pre-Fix Auction Window: 02:00:00 to 02:14:59 UTC (m_utc in [120, 134])
        fix_bars = day_bars[(day_bars["m_utc"] >= FIX_START_MIN_UTC) & (day_bars["m_utc"] <= FIX_END_MIN_UTC)]
        if len(fix_bars) < 12:
            continue

        h_fix = float(fix_bars["high"].max())
        l_fix = float(fix_bars["low"].min())
        range_fix = h_fix - l_fix

        if not (MIN_FIX_RANGE <= range_fix <= MAX_FIX_RANGE):
            continue

        o_fix = float(fix_bars.iloc[0]["open"])
        c_fix = float(fix_bars.iloc[-1]["close"])
        close_loc = (c_fix - l_fix) / range_fix

        # Directional qualification
        long_eligible = close_loc >= CLOSE_LOC_LONG_MIN
        short_eligible = (not long_only) and (close_loc <= CLOSE_LOC_SHORT_MAX)

        if not (long_eligible or short_eligible):
            continue

        # 2. Breakout Scan Window: 02:15:00 to 02:45:00 UTC (m_utc in [135, 165])
        scan_bars = day_bars[(day_bars["m_utc"] >= SCAN_START_MIN_UTC) & (day_bars["m_utc"] <= SCAN_END_MIN_UTC)]
        if scan_bars.empty:
            continue

        sig_direction = 0
        entry_idx = -1

        for idx, row in scan_bars.iterrows():
            bc = float(row["close"])

            if long_eligible and bc > (h_fix + BREAKOUT_BUFFER):
                sig_direction = 1
                entry_idx = idx + 1
                break
            elif short_eligible and bc < (l_fix - BREAKOUT_BUFFER):
                sig_direction = -1
                entry_idx = idx + 1
                break

        if sig_direction == 0 or entry_idx >= len(day_bars):
            continue

        # 3. Execution & Risk Brackets (up to 03:45:00 UTC / m_utc = 225)
        trade_bars = day_bars.loc[entry_idx:]
        trade_bars = trade_bars[trade_bars["m_utc"] <= TIME_EXIT_MIN_UTC]
        if trade_bars.empty:
            continue

        entry_p = float(trade_bars.iloc[0]["open"])
        entry_time = trade_bars.iloc[0]["time_utc"]

        stop_dist = min(max(range_fix, MIN_STOP_POINTS), MAX_STOP_POINTS)
        target_dist = rr_mult * stop_dist

        if sig_direction == 1:
            stop_p = entry_p - stop_dist
            target_p = entry_p + target_dist
            be_trigger = entry_p + stop_dist
            be_stop = entry_p + BREAKEVEN_BUFFER
        else:
            stop_p = entry_p + stop_dist
            target_p = entry_p - target_dist
            be_trigger = entry_p - stop_dist
            be_stop = entry_p - BREAKEVEN_BUFFER

        exit_p = float(trade_bars.iloc[-1]["close"])
        exit_reason = "time_exit_0345"
        exit_time = trade_bars.iloc[-1]["time_utc"]
        is_be_active = False

        for row in trade_bars.itertuples():
            bh = float(row.high)
            bl = float(row.low)
            bo = float(row.open)
            bt = row.time_utc

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
        gross_pnl = gross_pts * MGC_POINT_VAL
        net_pnl = gross_pnl - MGC_TOTAL_FRICTION

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
            "range_fix": range_fix,
            "close_loc": close_loc,
            "is_oos": "IS" if d < IS_SPLIT_DATE else "OOS",
        })

    return pd.DataFrame(trades)


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
    print(" CANDIDATE RESEARCH: SHANGHAI GOLD EXCHANGE AM FIX ARBITRAGE (H44 / MGC)")
    print("=" * 80)

    register_strategy(
        strategy_id=STRATEGY_ID,
        tier=StrategyTier.CANDIDATE,
        name=STRATEGY_NAME,
        instrument="MGC",
        timeframe="1m",
        schedule="02:00–03:45 UTC",
        description="Shanghai Gold Exchange AM Benchmark Fix arbitrage drive on MGC following 02:15 UTC auction benchmark clearing.",
    )

    store = default_store
    h_gc = store.compute_data_hash(GC_PATH)
    print(f"Data SHA-256 (GC / MGC): {h_gc}")

    df_window = load_and_convert_gc_data(GC_PATH)
    day_dict = {d: group.reset_index(drop=True) for d, group in df_window.groupby("date_utc")}
    dates = sorted([d for d in day_dict.keys() if EVAL_START_DATE <= d <= EVAL_END_DATE])

    print(f"Pre-processed {len(dates)} UTC sessions ({EVAL_START_DATE} to {EVAL_END_DATE})...\n")

    # ─────────────────────────────────────────────────────────────────────────
    # SENSITIVITY SWEEP ACROSS CONFIGURATIONS
    # ─────────────────────────────────────────────────────────────────────────
    print("=" * 80)
    print(" SENSITIVITY SWEEPS (Long-Only vs L+S, Target R:R 1.5 to 2.5)")
    print("=" * 80)
    print(f"{'Variant':<26} | {'Trades':<6} | {'Win%':<6} | {'PF':<5} | {'Net PnL':<11} | {'MaxDD':<9} | {'Sharpe':<6}")
    print("-" * 76)

    sweep_results = {}
    for long_only in [True, False]:
        for rr in [1.5, 2.0, 2.5]:
            mode_name = "Long-Only" if long_only else "Long+Short"
            cfg_name = f"{mode_name} {rr:.1f}R"
            tdf_cfg = simulate_strategy(day_dict, dates, long_only=long_only, rr_mult=rr)
            m_cfg = compute_summary_metrics(tdf_cfg, cfg_name)
            sweep_results[(long_only, rr)] = (tdf_cfg, m_cfg)
            print(f"{cfg_name:<26} | {m_cfg['trades']:>6} | {m_cfg['win_rate']:>5.1f}% | {m_cfg['profit_factor']:>5.2f} | ${m_cfg['net_profit']:>9,.2f} | -${m_cfg['max_drawdown']:>7,.2f} | {m_cfg['sharpe_ratio']:>5.2f}")

    # Primary Baseline: Long-Only 2.5R
    primary_tdf, primary_m = sweep_results[(True, 2.5)]

    m_walk = compute_summary_metrics(primary_tdf, "Full Walkforward (2020-2026)")
    m_is = compute_summary_metrics(primary_tdf[primary_tdf["is_oos"] == "IS"], "In-Sample (2020-2024)")
    m_oos = compute_summary_metrics(primary_tdf[primary_tdf["is_oos"] == "OOS"], "Out-of-Sample (2025-2026)")

    print("\n" + "=" * 80)
    print(" PRIMARY BASELINE PERFORMANCE SCORECARD (Long-Only 2.5R, Steps 04 & 05)")
    print("=" * 80)
    print(f"{'Partition':<28} | {'Trades':<7} | {'Win%':<7} | {'PF':<6} | {'Net PnL':<12} | {'MaxDD':<10} | {'Sharpe':<6}")
    print("-" * 86)
    for m in (m_walk, m_is, m_oos):
        print(f"{m['label']:<28} | {m['trades']:<7} | {m['win_rate']:>6.1f}% | {m['profit_factor']:>6.2f} | ${m['net_profit']:>10,.2f} | -${m['max_drawdown']:>8,.2f} | {m['sharpe_ratio']:>6.2f}")

    print("\n" + "-" * 80)
    print(" PRIMARY BASELINE YEARLY BREAKDOWN:")
    print("-" * 80)
    for yr in sorted(primary_tdf["year"].unique()):
        sub_yr = primary_tdf[primary_tdf["year"] == yr]
        myr = compute_summary_metrics(sub_yr, yr)
        print(f"  {yr}: {myr['trades']:>3} tr | WR: {myr['win_rate']:>5.1f}% | PF: {myr['profit_factor']:>5.2f} | Net: ${myr['net_profit']:>9,.2f} | MaxDD: -${myr['max_drawdown']:>7,.2f}")

    print("\n" + "-" * 80)
    print(" EXIT REASONS:")
    print("-" * 80)
    for reason, cnt in primary_tdf["exit_reason"].value_counts().items():
        sub_r = primary_tdf[primary_tdf["exit_reason"] == reason]
        pnl_r = sub_r["net_pnl"].sum()
        print(f"  - {reason:<16}: {cnt:>3} trades ({cnt / len(primary_tdf) * 100:.1f}%) | Net PnL: ${pnl_r:>9,.2f}")

    # ACID Provenance Store Recording
    run_id = f"{STRATEGY_ID}_2020_2026"
    daily_returns_series = primary_tdf.groupby("date")["net_pnl"].sum()
    inst_metrics = calculate_institutional_metrics(
        primary_tdf["net_pnl"].to_numpy(),
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
        data_path=str(GC_PATH),
        total_trades=m_walk["trades"],
        win_rate=m_walk["win_rate"],
        profit_factor=m_walk["profit_factor"],
        gross_profit=m_walk["gross_profit"],
        net_profit=m_walk["net_profit"],
        max_drawdown=m_walk["max_drawdown"],
        sharpe_ratio=m_walk["sharpe_ratio"],
        largest_win=m_walk["largest_win"],
        slippage_model="1 tick adverse parity ($2.00/RT)",
        commission_model="$1.40 round-trip micro",
        is_net=True,
        explicit_warnings=warnings,
        extended_metrics=inst_metrics,
        params={
            "gc_hash": h_gc,
            "fix_window_utc": "02:00-02:14 UTC",
            "scan_window_utc": "02:15-02:45 UTC",
            "time_exit_utc": "03:45 UTC",
            "min_fix_range": MIN_FIX_RANGE,
            "max_fix_range": MAX_FIX_RANGE,
            "close_loc_long_min": CLOSE_LOC_LONG_MIN,
            "breakout_buffer": BREAKOUT_BUFFER,
            "min_stop_points": MIN_STOP_POINTS,
            "max_stop_points": MAX_STOP_POINTS,
            "rr_mult": 2.5,
            "breakeven_buffer": BREAKEVEN_BUFFER,
            "point_value": MGC_POINT_VAL,
            "commission_rt": MGC_COMMISSION_RT,
            "slippage_rt": MGC_SLIPPAGE_COST,
            "total_friction": MGC_TOTAL_FRICTION,
        },
        notes="H44 Shanghai Gold Exchange AM Benchmark Fix Arbitrage Drive on MGC following 02:15 UTC auction benchmark clearing.",
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
