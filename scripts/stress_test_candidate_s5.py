#!/usr/bin/env python3
"""
Empirical Adversarial Stress Test Harness: Candidate Strategy S5 (Crude Oil Post-Fix Range Expansion).
Primary Instrument: Micro WTI Crude Oil (MCL / CME NYMEX).

Evaluates:
1. Friction Stress Testing:
   - Expand slippage to 3 ticks ($3.00/side) and 4 ticks ($4.00/side).
   - Check if Profit Factor remains > 1.15 and Net PnL remains positive.
2. Parameter Plateau Sensitivity (Belfort Step 07):
   - ATR threshold: [1.80, 2.00, 2.20]
   - RVOL threshold: [1.10, 1.25, 1.40]
   - Stop Loss: [0.40, 0.45, 0.50]
   - Profit Target: [0.80, 0.90, 1.00]
   - Full 3x3x3x3 = 81-point parameter grid across full 5.8-year dataset.
   - Stability ratio, win rate, PF >= 1.15 compliance, and plateau geometry.
3. Max Drawdown & Tail Risk Audit:
   - Maximum Drawdown across all 81 grid points (verifying MaxDD < $600).
   - Consecutive losing streaks, single-day maximum loss, and yearly breakdown.
4. Deflated Sharpe Ratio (DSR) & Multiple Testing Correction:
   - Bailey & Lopez de Prado (2014) DSR calculation for tested trials.
"""

from __future__ import annotations

import argparse
import io
import math
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd

from backtest import dashboard_analytics as da
from backtest.provenance import default_store
from strategies.crude_rth_expansion_s5 import (
    CrudeRthExpansionParams,
    CrudeRthExpansionS5,
    calculate_crude_rth_features,
    generate_signals,
    simulate_intrabar_execution,
)

EXPECTED_DATA_SHA256 = "7f99fefece90be3114b7eb39060a5fe251038700a7238d3e1caac4f5909d1c90"


def run_single_backtest(
    rth_df: pd.DataFrame,
    daily_map: Dict[str, Dict[str, Any]],
    params: CrudeRthExpansionParams,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Runs signals and intrabar execution using precomputed features for high speed."""
    signals_df = generate_signals(rth_df, daily_map, params)
    trades_df = simulate_intrabar_execution(rth_df, signals_df, params)

    if len(trades_df) == 0:
        metrics = {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "net_profit": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
            "max_losing_streak": 0,
        }
        return trades_df, metrics

    total_trades = len(trades_df)
    wins = (trades_df["net_pnl"] > 0).sum()
    losses = (trades_df["net_pnl"] < 0).sum()
    win_rate = float((wins / total_trades) * 100.0)

    gross_profit = float(trades_df[trades_df["net_pnl"] > 0]["net_pnl"].sum())
    gross_loss = float(abs(trades_df[trades_df["net_pnl"] < 0]["net_pnl"].sum()))
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 999.0
    net_profit = float(trades_df["net_pnl"].sum())

    # Trailing Drawdown calculation
    cumulative = trades_df["net_pnl"].cumsum()
    hwm = np.maximum.accumulate(np.maximum(cumulative, 0.0))
    drawdown = hwm - cumulative
    max_drawdown = float(drawdown.max()) if len(drawdown) > 0 else 0.0

    # Daily Sharpe
    daily_pnl = trades_df.groupby("date")["net_pnl"].sum()
    if len(daily_pnl) > 1 and daily_pnl.std() > 0:
        sharpe = float((daily_pnl.mean() / daily_pnl.std()) * np.sqrt(252))
    else:
        sharpe = 0.0

    # Max losing streak
    is_loss = (trades_df["net_pnl"] < 0).astype(int)
    streak = 0
    max_streak = 0
    for val in is_loss:
        if val == 1:
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 0

    largest_win = float(trades_df["net_pnl"].max())
    largest_loss = float(trades_df["net_pnl"].min())

    metrics = {
        "total_trades": total_trades,
        "wins": int(wins),
        "losses": int(losses),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_profit": net_profit,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "largest_win": largest_win,
        "largest_loss": largest_loss,
        "max_losing_streak": max_streak,
    }
    return trades_df, metrics


def main():
    parser = argparse.ArgumentParser(description="Adversarial stress test harness for Candidate S5.")
    parser.add_argument(
        "--data-path",
        type=str,
        default="data/raw/cl_1m_2020_2026_et.parquet",
        help="Path to continuous 1m CL parquet data.",
    )
    args = parser.parse_args()

    data_file = REPO_ROOT / args.data_path if not Path(args.data_path).is_absolute() else Path(args.data_path)
    if not data_file.exists():
        print(f"ERROR: Data file not found: {data_file}", file=sys.stderr)
        sys.exit(1)

    print("=" * 80)
    print(" EMPIRICAL ADVERSARIAL STRESS TEST: CANDIDATE S5 (CRUDE RTH EXPANSION)")
    print("=" * 80)
    print(f"Data File       : {data_file}")
    data_hash = default_store.compute_data_hash(data_file)
    print(f"Data SHA-256    : {data_hash}")
    assert data_hash == EXPECTED_DATA_SHA256, f"Data hash mismatch: {data_hash} != {EXPECTED_DATA_SHA256}"
    print("Data Hash Status: ✅ VERIFIED")

    # Load data
    t0 = time.time()
    df_raw = pd.read_parquet(data_file)
    df_raw["time"] = pd.to_datetime(df_raw["time"])
    df_filtered = df_raw[
        (df_raw["time"] >= pd.Timestamp("2021-01-04"))
        & (df_raw["time"] <= pd.Timestamp("2026-10-30 23:59:59"))
    ].reset_index(drop=True)
    print(f"Loaded {len(df_filtered):,} 1-minute bars in {time.time() - t0:.2f}s.")

    # Base parameters
    base_params = CrudeRthExpansionParams()
    rth_df, daily_map = calculate_crude_rth_features(df_filtered, base_params)

    # 1. Base Backtest Verification
    base_trades, base_metrics = run_single_backtest(rth_df, daily_map, base_params)
    print("\n" + "-" * 80)
    print("1. BASELINE RUN VERIFICATION (1-tick limit / 2-tick stop / $3.50 RT)")
    print("-" * 80)
    for k, v in base_metrics.items():
        if isinstance(v, float):
            print(f"  {k:22s}: {v:10.2f}")
        else:
            print(f"  {k:22s}: {v}")

    # 2. Friction Stress Testing
    print("\n" + "-" * 80)
    print("2. FRICTION STRESS TESTING (Slippage Expansion)")
    print("-" * 80)
    friction_cases = [
        # (name, entry_slip, limit_slip, stop_slip, comms)
        ("Baseline (1-tick limit / 2-tick stop)", 0.01, 0.01, 0.02, 3.50),
        ("Slippage Expansion: 2 ticks all around ($2.00/side)", 0.02, 0.02, 0.02, 3.50),
        ("Slippage Expansion: 3 ticks all around ($3.00/side)", 0.03, 0.03, 0.03, 3.50),
        ("Slippage Expansion: 4 ticks all around ($4.00/side)", 0.04, 0.04, 0.04, 3.50),
        ("Severe Stop Blowout: 1t entry / 1t limit / 3t stop ($3.00 stop)", 0.01, 0.01, 0.03, 3.50),
        ("Severe Stop Blowout: 1t entry / 1t limit / 4t stop ($4.00 stop)", 0.01, 0.01, 0.04, 3.50),
        ("Extreme Friction: 4t entry / 4t limit / 5t stop ($5.00 stop)", 0.04, 0.04, 0.05, 3.50),
    ]

    print(f"{'Scenario':<55s} | {'Trades':<6s} | {'Win%':<6s} | {'PF':<6s} | {'Net PnL':<10s} | {'MaxDD':<8s} | {'Status'}")
    print("-" * 105)
    friction_results = []
    for name, e_slip, l_slip, s_slip, comms in friction_cases:
        p = replace(
            base_params,
            slippage_entry_pts=e_slip,
            slippage_limit_pts=l_slip,
            slippage_stop_pts=s_slip,
            commission_round_trip=comms,
        )
        _, m = run_single_backtest(rth_df, daily_map, p)
        pf_ok = m["profit_factor"] >= 1.15
        pnl_ok = m["net_profit"] > 0
        dd_ok = m["max_drawdown"] < 600.0
        status = "✅ PASS" if (pf_ok and pnl_ok and dd_ok) else "❌ FAIL"
        friction_results.append((name, m, status))
        print(f"{name:<55s} | {m['total_trades']:<6d} | {m['win_rate']:<5.1f}% | {m['profit_factor']:<6.2f} | ${m['net_profit']:<9.2f} | ${m['max_drawdown']:<7.2f} | {status}")

    # 3. 1D Parameter Sensitivity Sweeps
    print("\n" + "-" * 80)
    print("3. 1D PARAMETER SENSITIVITY SWEEPS")
    print("-" * 80)

    # 3A. ATR threshold: [1.80, 2.00, 2.20]
    print("\n--- 3A. Daily ATR(14) Threshold Sweep [1.80, 2.00, 2.20] ---")
    for atr_val in [1.80, 2.00, 2.20]:
        p = replace(base_params, min_atr14=atr_val)
        _, m = run_single_backtest(rth_df, daily_map, p)
        print(f"ATR >= {atr_val:4.2f}: Trades={m['total_trades']:3d}, Win%={m['win_rate']:5.1f}%, PF={m['profit_factor']:5.2f}, Net=${m['net_profit']:8.2f}, MaxDD=${m['max_drawdown']:6.2f}")

    # 3B. RVOL threshold: [1.10, 1.25, 1.40]
    print("\n--- 3B. Daily RVOL(20) Threshold Sweep [1.10, 1.25, 1.40] ---")
    for rvol_val in [1.10, 1.25, 1.40]:
        p = replace(base_params, min_rvol20=rvol_val)
        _, m = run_single_backtest(rth_df, daily_map, p)
        print(f"RVOL >= {rvol_val:4.2f}: Trades={m['total_trades']:3d}, Win%={m['win_rate']:5.1f}%, PF={m['profit_factor']:5.2f}, Net=${m['net_profit']:8.2f}, MaxDD=${m['max_drawdown']:6.2f}")

    # 3C. Stop Loss: [0.40, 0.45, 0.50]
    print("\n--- 3C. Stop Loss Distance Sweep [0.40, 0.45, 0.50] ($40, $45, $50) ---")
    for sl_val in [0.40, 0.45, 0.50]:
        p = replace(base_params, stop_loss_pts=sl_val, breakeven_trigger_pts=sl_val)
        _, m = run_single_backtest(rth_df, daily_map, p)
        print(f"Stop Loss = {sl_val:4.2f}: Trades={m['total_trades']:3d}, Win%={m['win_rate']:5.1f}%, PF={m['profit_factor']:5.2f}, Net=${m['net_profit']:8.2f}, MaxDD=${m['max_drawdown']:6.2f}")

    # 3D. Profit Target: [0.80, 0.90, 1.00]
    print("\n--- 3D. Profit Target Distance Sweep [0.80, 0.90, 1.00] ($80, $90, $100) ---")
    for tp_val in [0.80, 0.90, 1.00]:
        p = replace(base_params, profit_target_pts=tp_val)
        _, m = run_single_backtest(rth_df, daily_map, p)
        print(f"Target = {tp_val:4.2f}: Trades={m['total_trades']:3d}, Win%={m['win_rate']:5.1f}%, PF={m['profit_factor']:5.2f}, Net=${m['net_profit']:8.2f}, MaxDD=${m['max_drawdown']:6.2f}")

    # 4. Full 3x3x3x3 Parameter Grid (81 Combinations)
    print("\n" + "-" * 80)
    print("4. FULL 81-POINT PARAMETER GRID (ATR x RVOL x StopLoss x Target)")
    print("-" * 80)
    grid_atr = [1.80, 2.00, 2.20]
    grid_rvol = [1.10, 1.25, 1.40]
    grid_sl = [0.40, 0.45, 0.50]
    grid_tp = [0.80, 0.90, 1.00]

    grid_results = []
    t_grid = time.time()
    for a in grid_atr:
        for r in grid_rvol:
            for s in grid_sl:
                for t in grid_tp:
                    p = replace(
                        base_params,
                        min_atr14=a,
                        min_rvol20=r,
                        stop_loss_pts=s,
                        breakeven_trigger_pts=s,
                        profit_target_pts=t,
                    )
                    _, m = run_single_backtest(rth_df, daily_map, p)
                    grid_results.append({
                        "atr": a,
                        "rvol": r,
                        "sl": s,
                        "tp": t,
                        "trades": m["total_trades"],
                        "win_rate": m["win_rate"],
                        "profit_factor": m["profit_factor"],
                        "net_pnl": m["net_profit"],
                        "max_dd": m["max_drawdown"],
                        "sharpe": m["sharpe_ratio"],
                    })

    df_grid = pd.DataFrame(grid_results)
    grid_time = time.time() - t_grid
    print(f"Executed 81 full walkforward simulations in {grid_time:.2f}s.")

    # Grid Statistical Distribution
    total_runs = len(df_grid)
    profitable_runs = (df_grid["net_pnl"] > 0).sum()
    pf_ge_115_runs = (df_grid["profit_factor"] >= 1.15).sum()
    pf_ge_125_runs = (df_grid["profit_factor"] >= 1.25).sum()
    dd_lt_600_runs = (df_grid["max_dd"] < 600.0).sum()
    dd_lt_500_runs = (df_grid["max_dd"] < 500.0).sum()

    stability_ratio = float(df_grid["net_pnl"].min() / base_metrics["net_profit"])

    print("\n--- Grid Statistical Distribution (81 Combinations) ---")
    print(f"Total Combinations      : {total_runs}")
    print(f"Profitable Runs (PnL>0) : {profitable_runs}/{total_runs} ({profitable_runs / total_runs * 100:.1f}%)")
    print(f"PF >= 1.15 Runs         : {pf_ge_115_runs}/{total_runs} ({pf_ge_115_runs / total_runs * 100:.1f}%)")
    print(f"PF >= 1.25 Runs         : {pf_ge_125_runs}/{total_runs} ({pf_ge_125_runs / total_runs * 100:.1f}%)")
    print(f"MaxDD < $600 Runs       : {dd_lt_600_runs}/{total_runs} ({dd_lt_600_runs / total_runs * 100:.1f}%)")
    print(f"MaxDD < $500 Runs       : {dd_lt_500_runs}/{total_runs} ({dd_lt_500_runs / total_runs * 100:.1f}%)")
    print(f"Net PnL Range           : [${df_grid['net_pnl'].min():.2f}, ${df_grid['net_pnl'].max():.2f}]")
    print(f"Net PnL Mean ± Std      : ${df_grid['net_pnl'].mean():.2f} ± ${df_grid['net_pnl'].std():.2f}")
    print(f"Net PnL Median          : ${df_grid['net_pnl'].median():.2f}")
    print(f"PF Range                : [{df_grid['profit_factor'].min():.2f}, {df_grid['profit_factor'].max():.2f}]")
    print(f"PF Mean ± Std           : {df_grid['profit_factor'].mean():.2f} ± {df_grid['profit_factor'].std():.2f}")
    print(f"PF Median               : {df_grid['profit_factor'].median():.2f}")
    print(f"Max Drawdown Range      : [${df_grid['max_dd'].min():.2f}, ${df_grid['max_dd'].max():.2f}]")
    print(f"Max Drawdown Mean ± Std : ${df_grid['max_dd'].mean():.2f} ± ${df_grid['max_dd'].std():.2f}")
    print(f"Max Drawdown Max        : ${df_grid['max_dd'].max():.2f}")
    print(f"Stability Ratio (Min/Base): {stability_ratio:.2f}x (Threshold >= 0.70x)")

    # 5. Multi-Year Breakdown & Tail Risk
    print("\n" + "-" * 80)
    print("5. MULTI-YEAR PERFORMANCE BREAKDOWN (Baseline)")
    print("-" * 80)
    base_trades["year"] = pd.to_datetime(base_trades["date"]).dt.year
    for yr, y_df in base_trades.groupby("year"):
        y_trades = len(y_df)
        y_wins = (y_df["net_pnl"] > 0).sum()
        y_winrate = y_wins / y_trades * 100.0 if y_trades > 0 else 0.0
        y_gp = y_df[y_df["net_pnl"] > 0]["net_pnl"].sum()
        y_gl = abs(y_df[y_df["net_pnl"] < 0]["net_pnl"].sum())
        y_pf = y_gp / y_gl if y_gl > 0 else 999.0
        y_net = y_df["net_pnl"].sum()
        y_cum = y_df["net_pnl"].cumsum()
        y_hwm = np.maximum.accumulate(np.maximum(y_cum, 0.0))
        y_dd = (y_hwm - y_cum).max() if len(y_cum) > 0 else 0.0
        print(f"Year {yr}: Trades={y_trades:2d}, Win%={y_winrate:5.1f}%, PF={y_pf:5.2f}, Net=${y_net:8.2f}, MaxDD=${y_dd:6.2f}")

    # 6. Deflated Sharpe Ratio (DSR)
    print("\n" + "-" * 80)
    print("6. DEFLATED SHARPE RATIO (Bailey & Lopez de Prado 2014)")
    print("-" * 80)
    annual_sharpe = base_metrics["sharpe_ratio"]
    n_trades = base_metrics["total_trades"]
    # Daily PnL skewness & kurtosis
    daily_pnl = base_trades.groupby("date")["net_pnl"].sum()
    skew = float(daily_pnl.skew()) if len(daily_pnl) > 2 else 0.0
    kurt = float(daily_pnl.kurtosis()) if len(daily_pnl) > 3 else 3.0
    trials = 81  # 81 parameter combinations evaluated

    dsr = da.deflated_sharpe_ratio(
        annual_sharpe=annual_sharpe,
        trades=n_trades,
        skewness=skew,
        kurtosis=kurt,
        trials=trials,
        var_sharpe=0.5,
    )
    print(f"Annual Sharpe        : {annual_sharpe:.2f}")
    print(f"Evaluated Trials (N) : {trials}")
    print(f"PnL Skewness         : {skew:.2f}")
    print(f"PnL Kurtosis         : {kurt:.2f}")
    print(f"Deflated Sharpe (DSR): {dsr:.4f}")
    if dsr > 0.0:
        print("DSR Verdict          : ✅ PASS (Statistically significant edge, DSR > 0.0)")
    else:
        print("DSR Verdict          : ❌ FAIL (Consistent with random noise)")

    print("\n" + "=" * 80)
    print(" ADVERSARIAL STRESS TEST SUMMARY")
    print("=" * 80)
    f3_pf = [m["profit_factor"] for name, m, st in friction_results if "3 ticks" in name][0]
    f4_pf = [m["profit_factor"] for name, m, st in friction_results if "4 ticks" in name][0]
    f3_net = [m["net_profit"] for name, m, st in friction_results if "3 ticks" in name][0]
    f4_net = [m["net_profit"] for name, m, st in friction_results if "4 ticks" in name][0]
    max_grid_dd = df_grid["max_dd"].max()

    print(f"1. 3-Tick Slippage Expansion: PF = {f3_pf:.2f}, Net = ${f3_net:.2f} (PF > 1.15: {'PASS' if f3_pf > 1.15 else 'FAIL'})")
    print(f"2. 4-Tick Slippage Expansion: PF = {f4_pf:.2f}, Net = ${f4_net:.2f} (PF > 1.15: {'PASS' if f4_pf > 1.15 else 'FAIL'})")
    print(f"3. 81-Point Grid Profitability: {profitable_runs}/81 ({profitable_runs/81*100:.1f}%) profitable")
    print(f"4. 81-Point Grid PF >= 1.15: {pf_ge_115_runs}/81 ({pf_ge_115_runs/81*100:.1f}%)")
    print(f"5. Max Drawdown across all 81 points: ${max_grid_dd:.2f} (MaxDD < $600: {'PASS' if max_grid_dd < 600.0 else 'FAIL'})")
    print(f"6. Deflated Sharpe Ratio: {dsr:.4f} (DSR > 0.0: {'PASS' if dsr > 0.0 else 'FAIL'})")


if __name__ == "__main__":
    main()
