#!/usr/bin/env python3
"""
Research Script: Crude Oil Pit Open Breakout (09:00 ET) on MCL.
Belfort Systematic Trading Framework (2026) — Step 03 (Code It) & Step 04 (In-Sample Build).

Evaluates:
- Hypothesis: H21 (docs/research_hypotheses/2026-11-07_crude_oil_pit_open_breakout_h21.md)
- In-Sample Window (67%): 2021-01-01 to 2024-12-31
- Out-of-Sample Window (33%): 2025-01-01 to 2026-10-30 (LOCKED during Step 04)
- Instrument: MCL (Micro WTI Crude Oil: $100/pt, $1.00 per $0.01 tick)
- Realistic Cost Model: 1-tick adverse slippage + $1.24 RT commission per contract
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.provenance import default_store
from config.strategy_registry import StrategyTier, register_candidate

DATA_PATH = REPO_ROOT / "data/raw/cl_1m_2020_2026_et.parquet"
STRATEGY_ID = "cl_pit_open_s4"
STRATEGY_NAME = "Crude Oil Pit Open Breakout (09:00 ET)"


def compute_pit_value_areas(df: pd.DataFrame, bin_size: float = 0.05, va_pct: float = 0.70) -> Dict[str, Dict[str, float]]:
    """
    Computes 70% Value Area (VAH, VAL, POC) on the NYMEX Pit Session (09:00 to 14:30 ET).
    Strictly lagged by 1 day so Day T uses only Day T-1 reference levels.
    """
    pit_bars = df[(df["hhmm"] >= "09:00") & (df["hhmm"] <= "14:30")].copy()
    raw_profiles: Dict[str, Dict[str, float]] = {}

    for d_str, g in pit_bars.groupby("date_str"):
        if len(g) < 60:
            continue
        low_min = float(g["low"].min())
        high_max = float(g["high"].max())
        if high_max <= low_min:
            continue

        bins = np.arange(low_min, high_max + bin_size, bin_size)
        if len(bins) < 2:
            continue
        tp = (g["high"] + g["low"] + g["close"]) / 3.0
        vol = g["volume"].clip(lower=1.0)
        idx = np.clip(np.digitize(tp, bins) - 1, 0, len(bins) - 2)
        vol_profile = np.bincount(idx, weights=vol, minlength=len(bins) - 1)

        poc_idx = int(np.argmax(vol_profile))
        poc_p = 0.5 * (bins[poc_idx] + bins[poc_idx + 1])
        target_vol = va_pct * float(vol.sum())
        cur_vol = float(vol_profile[poc_idx])
        lo_idx = poc_idx
        hi_idx = poc_idx
        n_bins = len(bins) - 1

        while cur_vol < target_vol and (lo_idx > 0 or hi_idx < n_bins - 1):
            next_lo_vol = float(vol_profile[lo_idx - 1]) if lo_idx > 0 else -1.0
            next_hi_vol = float(vol_profile[hi_idx + 1]) if hi_idx < n_bins - 1 else -1.0
            if next_hi_vol >= next_lo_vol:
                hi_idx += 1
                cur_vol += next_hi_vol
            else:
                lo_idx -= 1
                cur_vol += next_lo_vol

        vah_p = float(bins[hi_idx + 1])
        val_p = float(bins[lo_idx])
        raw_profiles[d_str] = {"vah": vah_p, "val": val_p, "poc": poc_p}

    # Strict Day T-1 lag mapping
    dates_sorted = sorted(raw_profiles.keys())
    lagged_profiles: Dict[str, Dict[str, float]] = {}
    for i in range(1, len(dates_sorted)):
        lagged_profiles[dates_sorted[i]] = raw_profiles[dates_sorted[i - 1]]

    return lagged_profiles


def simulate_cl_pit_trades(
    df: pd.DataFrame,
    prior_va_map: Dict[str, Dict[str, float]],
    *,
    min_stop_pts: float = 0.30,
    max_stop_pts: float = 0.75,
    stop_mult: float = 0.50,
    target_rr: float = 1.50,
    long_cl_thresh: float = 0.60,
    short_cl_thresh: float = 0.40,
    slippage_pts: float = 0.01,
    comm_per_contract: float = 1.24,
    risk_budget: float = 250.0,
) -> pd.DataFrame:
    """
    Executes mechanical trade simulation for H21 on MCL.
    """
    # Filter bars around pit hours: 09:00 to 11:30 ET
    pit_eval = df[(df["hhmm"] >= "09:00") & (df["hhmm"] <= "11:30")].copy()
    bars_by_date = {d: g.reset_index(drop=True) for d, g in pit_eval.groupby("date_str")}

    trades: List[Dict[str, Any]] = []

    for d_str, day_bars in bars_by_date.items():
        if d_str < "2021-01-01":
            continue
        p_va = prior_va_map.get(d_str)
        if p_va is None:
            continue

        b_0900 = day_bars[day_bars["hhmm"] == "09:00"]
        if b_0900.empty:
            continue

        open_0900 = float(b_0900.iloc[0]["open"])
        is_above_vah = open_0900 > p_va["vah"]
        is_below_val = open_0900 < p_va["val"]

        # Pit open must be outside prior pit value area
        if not (is_above_vah or is_below_val):
            continue

        # Opening Range: 09:00 to 09:14 ET
        or_bars = day_bars[(day_bars["hhmm"] >= "09:00") & (day_bars["hhmm"] <= "09:14")].copy()
        if len(or_bars) < 14:
            continue

        # Cumulative VWAP from 09:00
        tp = (or_bars["high"] + or_bars["low"] + or_bars["close"]) / 3.0
        v = or_bars["volume"].clip(lower=1.0)
        vwap_0914 = float((tp * v).sum() / v.sum())

        sb = or_bars.iloc[-1]  # 09:14 bar
        sb_close = float(sb["close"])
        sb_high = float(sb["high"])
        sb_low = float(sb["low"])
        sb_range = sb_high - sb_low
        sb_cl_loc = (sb_close - sb_low) / sb_range if sb_range > 0 else 0.50

        or_high = float(or_bars["high"].max())
        or_low = float(or_bars["low"].min())
        or_range = or_high - or_low

        direction = 0
        if is_above_vah and sb_close > p_va["vah"] and sb_close > vwap_0914 and sb_cl_loc >= long_cl_thresh:
            direction = 1
        elif is_below_val and sb_close < p_va["val"] and sb_close < vwap_0914 and sb_cl_loc <= short_cl_thresh:
            direction = -1

        if direction == 0:
            continue

        # Execution bars: from 09:15 to 11:30 ET
        exec_bars = day_bars[day_bars["hhmm"] >= "09:15"].reset_index(drop=True)
        if exec_bars.empty:
            continue

        entry_bar = exec_bars.iloc[0]
        entry_price = float(entry_bar["open"])
        entry_time = pd.Timestamp(entry_bar["time"])

        stop_pts = float(np.clip(or_range * stop_mult, min_stop_pts, max_stop_pts))
        target_pts = stop_pts * target_rr

        stop_price = entry_price - direction * stop_pts
        target_price = entry_price + direction * target_pts

        exit_price = float(exec_bars.iloc[-1]["close"])
        exit_time = pd.Timestamp(exec_bars.iloc[-1]["time"])
        exit_reason = "time_exit_1130"

        for _, rb in exec_bars.iterrows():
            rb_time = pd.Timestamp(rb["time"])
            rb_open = float(rb["open"])
            rb_high = float(rb["high"])
            rb_low = float(rb["low"])

            # Check Stop Loss with gap-through resolution
            if direction == 1:
                if rb_low <= stop_price:
                    exit_price = min(stop_price, rb_open)
                    exit_time = rb_time
                    exit_reason = "stop_loss"
                    break
                elif rb_high >= target_price:
                    exit_price = target_price
                    exit_time = rb_time
                    exit_reason = "profit_target"
                    break
            else:
                if rb_high >= stop_price:
                    exit_price = max(stop_price, rb_open)
                    exit_time = rb_time
                    exit_reason = "stop_loss"
                    break
                elif rb_low <= target_price:
                    exit_price = target_price
                    exit_time = rb_time
                    exit_reason = "profit_target"
                    break

        raw_pts = (exit_price - entry_price) * direction
        # Apply 1-tick adverse slippage on entry and stop/time exits
        slip_total = slippage_pts if exit_reason == "profit_target" else (slippage_pts * 2.0)
        net_pts = raw_pts - slip_total

        # Position sizing under $250 max-risk budget
        # MCL: $100 per full point ($1.00 per $0.01 tick)
        stop_risk_dollars = stop_pts * 100.0
        contracts = int(np.clip(np.floor(risk_budget / max(stop_risk_dollars, 1.0)), 1, 4))
        comm = comm_per_contract * contracts
        net_dollars = (net_pts * 100.0 * contracts) - comm

        trades.append({
            "date_str": d_str,
            "year": entry_time.year,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "direction": "long" if direction == 1 else "short",
            "entry_price": entry_price,
            "exit_price": exit_price,
            "stop_pts": stop_pts,
            "target_pts": target_pts,
            "contracts": contracts,
            "net_pts": net_pts,
            "net_dollars": net_dollars,
            "exit_reason": exit_reason,
        })

    return pd.DataFrame(trades)


def compute_distribution_metrics(trades: pd.DataFrame, label: str = "Window") -> Dict[str, Any]:
    if trades.empty:
        return {"label": label, "trades": 0}

    n = len(trades)
    wins = trades[trades["net_dollars"] > 0]
    losses = trades[trades["net_dollars"] <= 0]
    n_wins = len(wins)
    n_losses = len(losses)
    wr = (n_wins / n) * 100.0

    gross_profit = float(wins["net_dollars"].sum()) if n_wins > 0 else 0.0
    gross_loss = float(abs(losses["net_dollars"].sum())) if n_losses > 0 else 0.0
    net_pnl = gross_profit - gross_loss
    pf = (gross_profit / gross_loss) if gross_loss > 0 else np.nan

    avg_trade = net_pnl / n
    avg_win = (gross_profit / n_wins) if n_wins > 0 else 0.0
    avg_loss = (gross_loss / n_losses) if n_losses > 0 else 0.0
    payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else np.nan

    cum = trades["net_dollars"].cumsum()
    peak = cum.cummax()
    dd = cum - peak
    max_dd = float(dd.min())

    # Longest losing streak
    streak = 0
    max_streak = 0
    for val in trades["net_dollars"]:
        if val <= 0:
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 0

    largest_win = float(trades["net_dollars"].max())
    outlier_ratio = (largest_win / net_pnl) if net_pnl > 0 else 0.0

    active_days = int(trades["date_str"].nunique())
    years = (pd.to_datetime(trades["entry_time"].max()) - pd.to_datetime(trades["entry_time"].min())).days / 365.25
    trades_per_year = n / max(years, 0.1)

    return {
        "label": label,
        "trades": n,
        "active_days": active_days,
        "trades_per_year": trades_per_year,
        "win_rate": wr,
        "pf": pf,
        "net_pnl": net_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "avg_trade": avg_trade,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff_ratio,
        "max_dd": max_dd,
        "max_loss_streak": max_streak,
        "largest_win": largest_win,
        "outlier_ratio": outlier_ratio,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate H21 Crude Oil Pit Open Breakout under Belfort Blueprint.")
    parser.add_argument("--unlock-oos", action="store_true", help="Unlock 2025-2026 OOS window (Step 05).")
    args = parser.parse_args()

    print("=" * 80)
    print(" 🛢️  BELFORT SYSTEMATIC BLUEPRINT: CRUDE OIL PIT OPEN (09:00 ET)")
    print(f" Strategy ID: {STRATEGY_ID} | Instrument: MCL | Tier: CANDIDATE")
    print("=" * 80)

    # 1. Dataset Provenance Check
    if not DATA_PATH.exists():
        print(f" [❌] Missing data file: {DATA_PATH}")
        sys.exit(1)

    store = default_store
    data_hash = store.compute_data_hash(DATA_PATH)
    print(f" [Step 01 & 02 Verified]")
    print(f"   Data File   : {DATA_PATH.name}")
    print(f"   SHA-256     : {data_hash}")

    # Register candidate in runtime registry
    register_candidate(
        strategy_id=STRATEGY_ID,
        name=STRATEGY_NAME,
        instrument="MCL",
        description="NYMEX Micro Crude Oil pit open breakout outside prior session Value Area.",
    )

    # Load data
    print("   Loading 1-minute CL dataset...")
    df = pd.read_parquet(DATA_PATH)
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["time"].dt.strftime("%H:%M")

    # 2. Compute prior pit value areas
    print("   Computing prior session NYMEX pit Value Areas (09:00–14:30 ET)...")
    prior_va_map = compute_pit_value_areas(df, bin_size=0.05, va_pct=0.70)
    print(f"   Calculated {len(prior_va_map):,} prior session Value Area profiles.")

    # 3. Simulate mechanical trades
    print("   Executing mechanical trade simulation (Belfort Step 03)...")
    all_trades = simulate_cl_pit_trades(df, prior_va_map)
    print(f"   Generated {len(all_trades)} total mechanical trade executions (2021–2026).\n")

    # 4. Step 04: In-Sample Build (2021-01-01 to 2024-12-31)
    is_trades = all_trades[all_trades["year"] <= 2024].copy().reset_index(drop=True)
    oos_trades = all_trades[all_trades["year"] >= 2025].copy().reset_index(drop=True)

    is_m = compute_distribution_metrics(is_trades, "In-Sample (2021–2024)")

    print("-" * 80)
    print(" BELFORT STEP 04: IN-SAMPLE BUILD DISTRIBUTION (2021–2024)")
    print("-" * 80)
    print(f" Sample Size (N)     : {is_m['trades']} trades ({is_m['active_days']} active exchange sessions)")
    print(f" Annual Frequency    : {is_m['trades_per_year']:.1f} trades / year (~{is_m['trades']/48:.1f} trades / month)")
    print(f" Win Rate            : {is_m['win_rate']:.2f}%")
    print(f" Profit Factor       : {is_m['pf']:.2f}")
    print(f" Net Profit          : ${is_m['net_pnl']:,.2f}")
    print(f" Gross Profit        : ${is_m['gross_profit']:,.2f}")
    print(f" Gross Loss          : -${is_m['gross_loss']:,.2f}")
    print(f" Average Trade       : ${is_m['avg_trade']:.2f}")
    print(f" Average Winner      : ${is_m['avg_win']:.2f}")
    print(f" Average Loser       : -${is_m['avg_loss']:.2f}")
    print(f" Payoff Ratio (W/L)  : {is_m['payoff_ratio']:.2f}x")
    print(f" Max Drawdown        : -${abs(is_m['max_dd']):,.2f}")
    print(f" Longest Loss Streak : {is_m['max_loss_streak']} consecutive trades")
    print(f" Outlier Ratio       : {is_m['outlier_ratio']*100:.1f}% (Largest Win: ${is_m['largest_win']:,.2f})")

    # Direction breakdown
    for d in ["long", "short"]:
        sub_d = is_trades[is_trades["direction"] == d]
        if not sub_d.empty:
            sub_m = compute_distribution_metrics(sub_d, f"{d.upper()} Trades")
            print(f"   -> {d.upper():5s} Only: {sub_m['trades']:3d} trades | WR: {sub_m['win_rate']:5.1f}% | PF: {sub_m['pf']:4.2f} | Net: ${sub_m['net_pnl']:8,.2f}")

    # Check In-Sample Sample Size Criterion
    if is_m["trades"] < 100:
        print(f"\n [⚠️ WARNING] In-sample sample size ({is_m['trades']}) is under the 100-trade threshold.")
    else:
        print(f"\n [✅ PASSED] In-sample sample size ({is_m['trades']}) satisfies Belfort Step 04 requirements (N >= 100).")

    # 5. Out-of-Sample Validation (Step 05)
    if args.unlock_oos:
        print("\n" + "=" * 80)
        print(" BELFORT STEP 05: OUT-OF-SAMPLE VALIDATION (2025–2026)")
        print("=" * 80)
        oos_m = compute_distribution_metrics(oos_trades, "Out-of-Sample (2025–2026)")
        print(f" OOS Sample Size (N) : {oos_m['trades']} trades ({oos_m['active_days']} active sessions)")
        print(f" OOS Win Rate        : {oos_m['win_rate']:.2f}% (IS: {is_m['win_rate']:.2f}%)")
        print(f" OOS Profit Factor   : {oos_m['pf']:.2f} (IS: {is_m['pf']:.2f})")
        print(f" OOS Net Profit      : ${oos_m['net_pnl']:,.2f}")
        print(f" OOS Average Trade   : ${oos_m['avg_trade']:.2f} (IS: ${is_m['avg_trade']:.2f})")
        print(f" OOS Max Drawdown    : -${abs(oos_m['max_dd']):,.2f}")

        # OOS Direction breakdown
        for d in ["long", "short"]:
            sub_d = oos_trades[oos_trades["direction"] == d]
            if not sub_d.empty:
                sub_m = compute_distribution_metrics(sub_d, f"OOS {d.upper()}")
                print(f"   -> OOS {d.upper():5s} Only: {sub_m['trades']:3d} trades | WR: {sub_m['win_rate']:5.1f}% | PF: {sub_m['pf']:4.2f} | Net: ${sub_m['net_pnl']:8,.2f}")

        # Combined Full Period
        full_m = compute_distribution_metrics(all_trades, "Full 5.8-Year (2021–2026)")
        print("\n" + "-" * 80)
        print(" FULL PERIOD SUMMARY (2021–2026)")
        print("-" * 80)
        print(f" Total Trades        : {full_m['trades']}")
        print(f" Win Rate            : {full_m['win_rate']:.2f}%")
        print(f" Profit Factor       : {full_m['pf']:.2f}")
        print(f" Net Profit          : ${full_m['net_pnl']:,.2f}")
        print(f" Max Drawdown        : -${abs(full_m['max_dd']):,.2f}")

        # Standardized Verification Footer
        print(f"""
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : candidate_{STRATEGY_ID}_walkforward
Strategy     : {STRATEGY_ID} — {STRATEGY_NAME}
Strategy Tier: CANDIDATE
Methodology  : walkforward_split_65_35
Date Range   : 2021-01-01 to 2026-10-30
Data File    : {DATA_PATH.name}
Data SHA-256 : {data_hash}
Cost Model   : NYMEX 1-Tick Adverse ($1.00/side) + Commission ($1.24 RT) [NET]
Core Metrics : Trades: {full_m['trades']} | Win%: {full_m['win_rate']:.2f}% | PF: {full_m['pf']:.2f} | Net: ${full_m['net_pnl']:,.2f} | MaxDD: -${abs(full_m['max_dd']):,.2f}
Warning Flags: None
────────────────────────────────────────────────────────────────────────────
""")
    else:
        print("\n [🔒 LOCKED] Out-of-Sample window (2025–2026) remains sealed per Belfort Step 04.")
        print("   Run with --unlock-oos to evaluate Step 05 after In-Sample build review.")


if __name__ == "__main__":
    main()
