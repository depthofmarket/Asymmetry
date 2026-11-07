#!/usr/bin/env python3
"""
Candidate Strategy S8 (H38): 0DTE Dealer Gamma Absorption & IB Re-entry Trap (10:15 ET on MES).

Structural Premise:
On sessions opening inside the prior day's Value Area, the market is structurally in an equilibrium/rotational
regime dominated by high positive dealer gamma (0DTE options market makers). When price temporarily breaks outside
the 45-minute Initial Balance (09:30–10:14 ET) by 1.50 to 12.00 points, dealers are forced into aggressive counter-trend
gamma hedging (buying into dips, selling into rips). Once breakout momentum exhausts and price re-enters the Initial
Balance (closing back inside by 0.50 pt), dealer hedging snaps price back to session VWAP and the Initial Balance midpoint.

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

STRATEGY_ID = "candidate_gamma_absorption_s8"
STRATEGY_NAME = "0DTE Dealer Gamma Absorption & IB Re-entry Trap (10:15 ET on MES)"

ES_PATH = REPO_ROOT / "data" / "raw" / "es_1m_2020_2026_cqg_et.parquet"

# MES Contract Specifications
MES_POINT_VAL = 5.00         # $5.00 per index point ($1.25 per 0.25 tick)
MES_TICK_SIZE = 0.25         # 0.25 index points
MES_COMMISSION_RT = 1.40     # $1.40 round-trip per micro contract ($0.70/side)
MES_SLIPPAGE_TICKS = 1       # 1 tick adverse entry + 1 tick adverse exit
MES_SLIPPAGE_COST = 2 * MES_TICK_SIZE * MES_POINT_VAL  # $2.50 total slippage ($1.25 / side)
MES_TOTAL_FRICTION = MES_COMMISSION_RT + MES_SLIPPAGE_COST  # $3.90 total round-turn friction

# Initial Balance & Filter Parameters
IB_START_MIN = 570           # 09:30 ET
IB_END_MIN = 614             # 10:14 ET (45-minute IB)
IB_MIN_RANGE = 10.00         # Range_IB >= 10.0 pts
IB_MAX_RANGE = 45.00         # Range_IB <= 45.0 pts

# Re-entry Scan Window & Triggers
SCAN_START_MIN = 615         # 10:15 ET
SCAN_END_MIN = 690           # 11:30 ET
TIME_EXIT_MIN = 735          # 12:15 ET

PROBE_MIN_DIST = 1.50        # Probe >= 1.50 pts outside IB
PROBE_MAX_DIST = 12.00       # Probe <= 12.00 pts outside IB (runaway trend filter)
REENTRY_BUFFER = 0.50        # Close <= H_IB - 0.50 or Close >= L_IB + 0.50

STOP_PROBE_BUFFER = 1.50     # Stop placed 1.50 pts beyond probe extreme
STOP_MIN_POINTS = 5.00       # Minimum stop loss distance
STOP_MAX_POINTS = 10.00      # Maximum stop loss distance cap
TARGET_MIN_POINTS = 6.00     # Minimum target distance
BREAKEVEN_BUFFER = 0.25      # +1 tick breakeven buffer

EVAL_START_DATE = "2021-01-04"
EVAL_END_DATE = "2026-10-30"
IS_SPLIT_DATE = "2025-01-01"


# ─────────────────────────────────────────────────────────────────────────────
# VALUE AREA COMPUTATION
# ─────────────────────────────────────────────────────────────────────────────

def compute_daily_value_areas(df: pd.DataFrame, bin_size: float = 0.25, va_pct: float = 0.70) -> Dict[str, Tuple[float, float, float]]:
    """
    Computes prior session 70% Value Area (POC, VAH, VAL) from completed RTH bars (09:30 to 16:00 ET).
    """
    rth = df[(df["m"] >= 570) & (df["m"] <= 960)].copy()
    dates = sorted(rth["date_str"].unique())
    profile_dict: Dict[str, Tuple[float, float, float]] = {}

    for i in range(1, len(dates)):
        d_curr = dates[i]
        d_prev = dates[i - 1]
        prev_bars = rth[rth["date_str"] == d_prev]

        if len(prev_bars) < 300:
            continue

        typical = (prev_bars["high"] + prev_bars["low"] + prev_bars["close"]) / 3.0
        bins = np.round(typical / bin_size) * bin_size
        vol_by_price = prev_bars.groupby(bins, sort=True)["volume"].sum()

        if vol_by_price.empty or float(vol_by_price.sum()) <= 0:
            continue

        prices = vol_by_price.index.to_numpy(dtype=float)
        weights = vol_by_price.to_numpy(dtype=float)
        total_vol = float(np.sum(weights))
        target_vol = total_vol * va_pct

        poc_idx = int(np.argmax(weights))
        poc = float(prices[poc_idx])

        left_idx = poc_idx
        right_idx = poc_idx
        current_vol = float(weights[poc_idx])
        n_weights = len(weights)

        while current_vol < target_vol and (left_idx > 0 or right_idx + 1 < n_weights):
            left_w = weights[left_idx - 1] if left_idx > 0 else -np.inf
            right_w = weights[right_idx + 1] if right_idx + 1 < n_weights else -np.inf

            if left_w >= right_w:
                left_idx -= 1
                current_vol += float(weights[left_idx])
            else:
                right_idx += 1
                current_vol += float(weights[right_idx])

        val = float(prices[left_idx])
        vah = float(prices[right_idx])
        profile_dict[d_curr] = (poc, vah, val)

    return profile_dict


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
        schedule="10:15–12:15 ET",
        description="0DTE dealer gamma absorption and Initial Balance re-entry trap on MES when session opens inside prior Value Area.",
    )

    store = default_store
    h_es = store.compute_data_hash(ES_PATH)
    print(f"Data SHA-256 (ES / MES): {h_es}")

    print("Loading raw 1-minute MES dataset...")
    df_raw = pd.read_parquet(ES_PATH, columns=["time", "open", "high", "low", "close", "volume"])
    df_raw["time"] = pd.to_datetime(df_raw["time"])
    df_raw["m"] = df_raw["time"].dt.hour * 60 + df_raw["time"].dt.minute
    df_raw["date_str"] = df_raw["time"].dt.strftime("%Y-%m-%d")

    print("Calculating prior session 70% Value Areas (0.25 pt bins)...")
    va_dict = compute_daily_value_areas(df_raw, bin_size=0.25, va_pct=0.70)

    # Filter to RTH evaluation window: 09:30 to 12:20 ET (m in [570, 740])
    df_eval = df_raw[(df_raw["m"] >= 570) & (df_raw["m"] <= 740)].sort_values("time").reset_index(drop=True)
    day_dict = {d: group.reset_index(drop=True) for d, group in df_eval.groupby("date_str")}
    dates = sorted([d for d in day_dict.keys() if EVAL_START_DATE <= d <= EVAL_END_DATE])

    print(f"Simulating across {len(dates)} sessions ({EVAL_START_DATE} to {EVAL_END_DATE})...\n")

    trades: List[Dict[str, Any]] = []

    for d in dates:
        day_bars = day_dict.get(d)
        if day_bars is None or day_bars.empty:
            continue

        va_levels = va_dict.get(d)
        if va_levels is None:
            continue

        poc_prior, vah_prior, val_prior = va_levels

        # 1. 09:30:00 ET Open Invariant: Strictly INSIDE prior Value Area
        bar_0930 = day_bars[day_bars["m"] == 570]
        if bar_0930.empty:
            continue

        open_0930 = float(bar_0930.iloc[0]["open"])
        if not (val_prior <= open_0930 <= vah_prior):
            continue

        # 2. 45-Minute Initial Balance (09:30 to 10:14 ET, m in [570, 614])
        ib_bars = day_bars[(day_bars["m"] >= IB_START_MIN) & (day_bars["m"] <= IB_END_MIN)]
        if len(ib_bars) < 42:
            continue

        h_ib = float(ib_bars["high"].max())
        l_ib = float(ib_bars["low"].min())
        range_ib = h_ib - l_ib

        if not (IB_MIN_RANGE <= range_ib <= IB_MAX_RANGE):
            continue

        ib_mid = (h_ib + l_ib) / 2.0

        # Precompute cumulative session VWAP from 09:30:00 ET onwards
        cum_tp_vol = ((day_bars["high"] + day_bars["low"] + day_bars["close"]) / 3.0 * day_bars["volume"]).cumsum()
        cum_vol = day_bars["volume"].cumsum()
        day_bars["vwap"] = cum_tp_vol / cum_vol.replace(0, np.nan)

        # 3. False Breakout & Re-entry Scan (10:15 to 11:30 ET, m in [615, 690])
        scan_bars = day_bars[(day_bars["m"] >= SCAN_START_MIN) & (day_bars["m"] <= SCAN_END_MIN)]
        if scan_bars.empty:
            continue

        sig_direction = 0
        entry_idx = -1
        stop_p = 0.0
        target_p = 0.0
        be_trigger = 0.0
        be_stop = 0.0

        probe_high = h_ib
        probe_low = l_ib

        for idx, row in scan_bars.iterrows():
            bh = float(row["high"])
            bl = float(row["low"])
            bc = float(row["close"])
            vwap_now = float(row["vwap"])

            probe_high = max(probe_high, bh)
            probe_low = min(probe_low, bl)

            # Check Upside Trap (Short Setup)
            upside_probed = (probe_high >= h_ib + PROBE_MIN_DIST) and (probe_high <= h_ib + PROBE_MAX_DIST)
            if upside_probed and bc <= (h_ib - REENTRY_BUFFER):
                sig_direction = -1
                entry_idx = idx + 1
                entry_p_approx = float(day_bars.loc[entry_idx]["open"]) if entry_idx < len(day_bars) else bc

                raw_stop_dist = (probe_high + STOP_PROBE_BUFFER) - entry_p_approx
                stop_dist = min(max(raw_stop_dist, STOP_MIN_POINTS), STOP_MAX_POINTS)
                stop_p = entry_p_approx + stop_dist

                target_p = max(vwap_now, ib_mid)
                if (entry_p_approx - target_p) < TARGET_MIN_POINTS or vwap_now < ib_mid:
                    target_p = ib_mid
                if (entry_p_approx - target_p) < STOP_MIN_POINTS:
                    target_p = entry_p_approx - max(TARGET_MIN_POINTS, stop_dist * 1.5)

                be_trigger = entry_p_approx - stop_dist
                be_stop = entry_p_approx - BREAKEVEN_BUFFER
                break

            # Check Downside Trap (Long Setup)
            downside_probed = (probe_low <= l_ib - PROBE_MIN_DIST) and (probe_low >= l_ib - PROBE_MAX_DIST)
            if downside_probed and bc >= (l_ib + REENTRY_BUFFER):
                sig_direction = 1
                entry_idx = idx + 1
                entry_p_approx = float(day_bars.loc[entry_idx]["open"]) if entry_idx < len(day_bars) else bc

                raw_stop_dist = entry_p_approx - (probe_low - STOP_PROBE_BUFFER)
                stop_dist = min(max(raw_stop_dist, STOP_MIN_POINTS), STOP_MAX_POINTS)
                stop_p = entry_p_approx - stop_dist

                target_p = min(vwap_now, ib_mid)
                if (target_p - entry_p_approx) < TARGET_MIN_POINTS or vwap_now > ib_mid:
                    target_p = ib_mid
                if (target_p - entry_p_approx) < STOP_MIN_POINTS:
                    target_p = entry_p_approx + max(TARGET_MIN_POINTS, stop_dist * 1.5)

                be_trigger = entry_p_approx + stop_dist
                be_stop = entry_p_approx + BREAKEVEN_BUFFER
                break

        if sig_direction == 0 or entry_idx >= len(day_bars):
            continue

        trade_bars = day_bars.loc[entry_idx:]
        trade_bars = trade_bars[trade_bars["m"] <= TIME_EXIT_MIN]
        if trade_bars.empty:
            continue

        entry_p = float(trade_bars.iloc[0]["open"])
        entry_time = trade_bars.iloc[0]["time"]

        exit_p = float(trade_bars.iloc[-1]["close"])
        exit_reason = "time_exit_1215"
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
            "range_ib": range_ib,
            "vah_prior": vah_prior,
            "val_prior": val_prior,
            "open_0930": open_0930,
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
    print(" CANDIDATE RESEARCH: 0DTE DEALER GAMMA ABSORPTION & RE-ENTRY TRAP (H38 / MES)")
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
            "ib_window": "09:30-10:14 ET",
            "scan_window": "10:15-11:30 ET",
            "time_exit": "12:15 ET",
            "ib_min_range": IB_MIN_RANGE,
            "ib_max_range": IB_MAX_RANGE,
            "probe_min_dist": PROBE_MIN_DIST,
            "probe_max_dist": PROBE_MAX_DIST,
            "reentry_buffer": REENTRY_BUFFER,
            "stop_min_points": STOP_MIN_POINTS,
            "stop_max_points": STOP_MAX_POINTS,
            "target_min_points": TARGET_MIN_POINTS,
            "breakeven_buffer": BREAKEVEN_BUFFER,
            "point_value": MES_POINT_VAL,
            "commission_rt": MES_COMMISSION_RT,
            "slippage_rt": MES_SLIPPAGE_COST,
            "total_friction": MES_TOTAL_FRICTION,
        },
        notes="H38 0DTE dealer gamma absorption and Initial Balance re-entry trap on MES when session opens inside prior Value Area.",
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