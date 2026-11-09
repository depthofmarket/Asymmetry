#!/usr/bin/env python3
"""
Candidate Strategy S13 (H45): 10:00 AM ET Tier-2 Macro Surprise Momentum Drive (MNQ/MES).

Structural Premise:
At 10:00:00 ET on multiple trading sessions each month, Tier-2 US macroeconomic data releases are published
(ISM Manufacturing PMI, ISM Services PMI, JOLTS Job Openings, UMich Consumer Sentiment, CB Consumer Confidence,
and Existing/New Home Sales). Unlike 08:30 Tier-1 releases that execute in thin Globex liquidity, 10:00 AM releases
hit the market during peak cash RTH liquidity when high-frequency trading market makers and algorithmic execution desks
are fully staffed. When a release produces an authentic macro surprise (volume spike >= 2.20x or range shock >= 40 pts
on MNQ / >= 8.5 pts on MES with strong directional skew >= 0.55), institutional capital executes directional trend
drives lasting 20-30 minutes before midday European lunch liquidity decays.

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
# CONFIGURATION & ASSET SPECIFICATIONS
# ─────────────────────────────────────────────────────────────────────────────

STRATEGY_ID = "candidate_macro_momentum_1000_s13"
STRATEGY_NAME = "10:00 AM ET Tier-2 Macro Surprise Momentum Drive (MNQ/MES)"

NQ_PATH = REPO_ROOT / "data" / "raw" / "nq_1m_2017_2026_cqg_et.parquet"
ES_PATH = REPO_ROOT / "data" / "raw" / "es_1m_2020_2026_cqg_et.parquet"

ASSET_SPECS = {
    "MNQ": {
        "path": NQ_PATH,
        "point_val": 2.00,
        "tick_size": 0.25,
        "comm_rt": 1.40,
        "slip_ticks": 1,
        "slip_cost": 1.00,  # 2 * 0.25 * $2.00 = $1.00
        "total_friction": 2.40,
        "range_shock_thresh": 40.00,
        "disp_thresh": 24.00,
        "stop_min": 22.00,
        "stop_max": 35.00,
    },
    "MES": {
        "path": ES_PATH,
        "point_val": 5.00,
        "tick_size": 0.25,
        "comm_rt": 1.40,
        "slip_ticks": 1,
        "slip_cost": 2.50,  # 2 * 0.25 * $5.00 = $2.50
        "total_friction": 3.90,
        "range_shock_thresh": 8.50,
        "disp_thresh": 5.00,
        "stop_min": 5.00,
        "stop_max": 8.50,
    },
}

# Timing Constants
PRE_START_MIN = 585          # 09:45 ET
PRE_END_MIN = 599            # 09:59 ET
RELEASE_START_MIN = 600      # 10:00 ET
RELEASE_END_MIN = 604        # 10:04 ET
ENTRY_MIN = 605              # 10:05 ET
TIME_EXIT_MIN = 635          # 10:35 ET

VOL_RATIO_THRESH = 2.20      # Volume spike >= 2.20x pre-release median
SKEW_THRESH = 0.55           # Displacement / Range >= 0.55
BREAKEVEN_BUFFER = 0.25      # +1 tick breakeven buffer (+0.25 pt)

EVAL_START_DATE = "2020-01-01"
EVAL_END_DATE = "2026-10-30"
IS_SPLIT_DATE = "2025-01-01"


# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST ENGINE (ASSET-LEVEL)
# ─────────────────────────────────────────────────────────────────────────────

def simulate_asset(asset: str, rr_mult: float = 2.0) -> pd.DataFrame:
    spec = ASSET_SPECS[asset]
    df_raw = pd.read_parquet(spec["path"], columns=["time", "open", "high", "low", "close", "volume"])
    df_raw["time"] = pd.to_datetime(df_raw["time"])
    df_raw["m"] = df_raw["time"].dt.hour * 60 + df_raw["time"].dt.minute
    df_raw["date_str"] = df_raw["time"].dt.strftime("%Y-%m-%d")

    # Filter to 09:40 to 10:40 ET window (m in [580, 640])
    df_sub = df_raw[(df_raw["m"] >= 580) & (df_raw["m"] <= 640)].sort_values("time").reset_index(drop=True)
    day_dict = {d: group.reset_index(drop=True) for d, group in df_sub.groupby("date_str")}
    dates = sorted([d for d in day_dict.keys() if EVAL_START_DATE <= d <= EVAL_END_DATE])

    trades: List[Dict[str, Any]] = []

    for d in dates:
        day_bars = day_dict.get(d)
        if day_bars is None or day_bars.empty:
            continue

        # 1. Pre-Release Baseline Window: 09:45:00 to 09:59:59 ET (m in [585, 599])
        bin1 = day_bars[(day_bars["m"] >= 585) & (day_bars["m"] <= 589)]
        bin2 = day_bars[(day_bars["m"] >= 590) & (day_bars["m"] <= 594)]
        bin3 = day_bars[(day_bars["m"] >= 595) & (day_bars["m"] <= 599)]

        if len(bin1) < 4 or len(bin2) < 4 or len(bin3) < 4:
            continue

        v_bin1 = float(bin1["volume"].sum())
        v_bin2 = float(bin2["volume"].sum())
        v_bin3 = float(bin3["volume"].sum())
        v_pre = float(np.median([v_bin1, v_bin2, v_bin3]))

        if v_pre <= 0:
            continue

        # 2. Release Window: 10:00:00 to 10:04:59 ET (m in [600, 604])
        spike_bars = day_bars[(day_bars["m"] >= RELEASE_START_MIN) & (day_bars["m"] <= RELEASE_END_MIN)]
        if len(spike_bars) < 5:
            continue

        v_spike = float(spike_bars["volume"].sum())
        ratio_vol = v_spike / v_pre
        h_spike = float(spike_bars["high"].max())
        l_spike = float(spike_bars["low"].min())
        range_spike = h_spike - l_spike

        if range_spike <= 0:
            continue

        o_1000 = float(spike_bars.iloc[0]["open"])
        c_1004 = float(spike_bars.iloc[-1]["close"])
        displacement = c_1004 - o_1000
        skew_loc = abs(displacement) / range_spike

        # 3. Macro Shock Filter
        shock_vol_or_range = (ratio_vol >= VOL_RATIO_THRESH) or (range_spike >= spec["range_shock_thresh"])
        shock_disp = abs(displacement) >= spec["disp_thresh"]
        shock_skew = skew_loc >= SKEW_THRESH

        if not (shock_vol_or_range and shock_disp and shock_skew):
            continue

        sig_direction = 1 if displacement > 0 else -1

        # 4. Entry at 10:05:00 ET Open (m = 605)
        trade_bars = day_bars[(day_bars["m"] >= ENTRY_MIN) & (day_bars["m"] <= TIME_EXIT_MIN)]
        if trade_bars.empty or trade_bars.iloc[0]["m"] != ENTRY_MIN:
            continue

        entry_p = float(trade_bars.iloc[0]["open"])
        entry_time = trade_bars.iloc[0]["time"]

        raw_stop = range_spike / 2.0
        stop_dist = min(max(raw_stop, spec["stop_min"]), spec["stop_max"])
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
        exit_reason = "time_exit_1035"
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
        gross_pnl = gross_pts * spec["point_val"]
        net_pnl = gross_pnl - spec["total_friction"]

        trades.append({
            "asset": asset,
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
            "range_spike": range_spike,
            "displacement": displacement,
            "ratio_vol": ratio_vol,
            "skew_loc": skew_loc,
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
    print(" CANDIDATE RESEARCH: 10:00 AM ET TIER-2 MACRO SURPRISE MOMENTUM (H45)")
    print("=" * 80)

    register_strategy(
        strategy_id=STRATEGY_ID,
        tier=StrategyTier.CANDIDATE,
        name=STRATEGY_NAME,
        instrument="MNQ/MES",
        timeframe="1m",
        schedule="10:00–10:35 ET",
        description="10:00 AM ET Tier-2 macro surprise momentum drive on MNQ and MES following volume shock and directional displacement.",
    )

    store = default_store
    h_nq = store.compute_data_hash(NQ_PATH)
    h_es = store.compute_data_hash(ES_PATH)
    print(f"Data SHA-256 (NQ / MNQ): {h_nq}")
    print(f"Data SHA-256 (ES / MES): {h_es}")

    # ─────────────────────────────────────────────────────────────────────────
    # SENSITIVITY SWEEPS (Target Multipliers 1.5R, 2.0R, 2.5R)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" SENSITIVITY SWEEPS: ASSET & REWARD-TO-RISK MULTIPLIERS")
    print("=" * 80)
    print(f"{'Asset & Target Multiplier':<30} | {'Trades':<6} | {'Win%':<6} | {'PF':<5} | {'Net PnL':<11} | {'MaxDD':<9} | {'Sharpe':<6}")
    print("-" * 80)

    sweep_runs = {}
    for asset in ["MNQ", "MES"]:
        for rr in [1.5, 2.0, 2.5]:
            lbl = f"{asset} {rr:.1f}R Target"
            tdf_a = simulate_asset(asset, rr_mult=rr)
            m_a = compute_summary_metrics(tdf_a, lbl)
            sweep_runs[(asset, rr)] = (tdf_a, m_a)
            print(f"{lbl:<30} | {m_a['trades']:>6} | {m_a['win_rate']:>5.1f}% | {m_a['profit_factor']:>5.2f} | ${m_a['net_profit']:>9,.2f} | -${m_a['max_drawdown']:>7,.2f} | {m_a['sharpe_ratio']:>5.2f}")

    # Combined Basket at Baseline 2.0R
    tdf_nq_base = sweep_runs[("MNQ", 2.0)][0]
    tdf_es_base = sweep_runs[("MES", 2.0)][0]
    tdf_comb = pd.concat([tdf_nq_base, tdf_es_base], ignore_index=True)
    m_comb = compute_summary_metrics(tdf_comb, "Combined Basket (MNQ+MES 2.0R)")
    print("-" * 80)
    print(f"{m_comb['label']:<30} | {m_comb['trades']:>6} | {m_comb['win_rate']:>5.1f}% | {m_comb['profit_factor']:>5.2f} | ${m_comb['net_profit']:>9,.2f} | -${m_comb['max_drawdown']:>7,.2f} | {m_comb['sharpe_ratio']:>5.2f}")

    # ─────────────────────────────────────────────────────────────────────────
    # PERFORMANCE SCORECARD (Belfort Steps 04 & 05) FOR PRIMARY RUN (MNQ 2.0R)
    # ─────────────────────────────────────────────────────────────────────────
    primary_tdf = tdf_nq_base
    m_walk = compute_summary_metrics(primary_tdf, "Full Walkforward (2020-2026)")
    m_is = compute_summary_metrics(primary_tdf[primary_tdf["is_oos"] == "IS"], "In-Sample (2020-2024)")
    m_oos = compute_summary_metrics(primary_tdf[primary_tdf["is_oos"] == "OOS"], "Out-of-Sample (2025-2026)")

    print("\n" + "=" * 80)
    print(" PRIMARY RUN SCORECARD (MNQ 2.0R Baseline, Steps 04 & 05)")
    print("=" * 80)
    print(f"{'Partition':<28} | {'Trades':<7} | {'Win%':<7} | {'PF':<6} | {'Net PnL':<12} | {'MaxDD':<10} | {'Sharpe':<6}")
    print("-" * 86)
    for m in (m_walk, m_is, m_oos):
        print(f"{m['label']:<28} | {m['trades']:<7} | {m['win_rate']:>6.1f}% | {m['profit_factor']:>6.2f} | ${m['net_profit']:>10,.2f} | -${m['max_drawdown']:>8,.2f} | {m['sharpe_ratio']:>6.2f}")

    print("\n" + "-" * 80)
    print(" PRIMARY RUN YEARLY BREAKDOWN (MNQ 2.0R):")
    print("-" * 80)
    for yr in sorted(primary_tdf["year"].unique()):
        sub_yr = primary_tdf[primary_tdf["year"] == yr]
        myr = compute_summary_metrics(sub_yr, yr)
        print(f"  {yr}: {myr['trades']:>3} tr | WR: {myr['win_rate']:>5.1f}% | PF: {myr['profit_factor']:>5.2f} | Net: ${myr['net_profit']:>9,.2f} | MaxDD: -${myr['max_drawdown']:>7,.2f}")

    print("\n" + "-" * 80)
    print(" EXIT REASONS (MNQ 2.0R):")
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
            "es_hash": h_es,
            "pre_release_window": "09:45-09:59 ET",
            "release_window": "10:00-10:04 ET",
            "entry_time": "10:05 ET",
            "time_exit": "10:35 ET",
            "vol_ratio_thresh": VOL_RATIO_THRESH,
            "skew_thresh": SKEW_THRESH,
            "mnq_range_shock_thresh": ASSET_SPECS["MNQ"]["range_shock_thresh"],
            "mnq_disp_thresh": ASSET_SPECS["MNQ"]["disp_thresh"],
            "breakeven_buffer": BREAKEVEN_BUFFER,
            "mnq_friction": ASSET_SPECS["MNQ"]["total_friction"],
            "mes_friction": ASSET_SPECS["MES"]["total_friction"],
        },
        notes="H45 10:00 AM ET Tier-2 Macro Surprise Momentum Drive on MNQ/MES following volume shock and directional displacement.",
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
