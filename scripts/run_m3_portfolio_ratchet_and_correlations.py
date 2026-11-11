#!/usr/bin/env python3
"""
LEGACY Milestone M3 simulator (historical comparison only).

Do not use this module as the LucidFlex 25K evaluation source of truth.
The authoritative causal evaluator is `backtest.lucidflex_eval` (simulator
`lucidflex_eval_v1`). This script and `results/m3_portfolio_ratchet_simulation.json`
are preserved byte-for-byte as a prior-generation artifact.

Known defects relative to lucidflex_eval_v1:
- Credits terminal trade P&L at entry (lookahead).
- Double-applies the ratchet to simultaneous S1 MNQ/MES legs.
- Arithmetically clips daily P&L to -$600.
- Uses generic weekdays instead of the NQ 09:30 ET session calendar.
- Treats unresolved Monte Carlo paths as non-pass without a distinct outcome label.

Milestone M3: 5-Strategy Pareto Anti-Martingale Ratchet Simulation & 5x5 Correlation Matrix.

Executes:
1. Loading of canonical .obtf bundles for S1, S2, S3 (Baselines) and S4, S5 (Candidates).
2. Empirical 5x5 Daily Return Correlation Matrix (Pearson & Spearman) across all 1,515 trading days.
3. Chronological 5-Strategy Portfolio simulation under the Pareto Anti-Martingale Ratchet:
   - Tier 1 ($0 to +$199.99): 2 micros
   - Tier 2 (+$200.00 to +$549.99): 3 micros
   - Tier 3 (+$550.00 to +$1,149.99): 4 micros
   - Finish-Line Shield (>= +$1,150.00): 1 micro
   - Safe CPPI Floor Protection (Cushion < $400.00): 1 micro
4. LucidFlex 25K Account Rules enforcement:
   - Starting Balance: $25,000.00
   - Profit Target: +$1,250.00 ($26,250.00)
   - EOD Trailing Max Drawdown: $1,000.00 (locks permanently at $25,100.00 once EOD balance >= $26,100.00)
   - Intraday Daily Soft Stop: -$600.00 (halts trading for remainder of session)
   - Consistency Rule: 40% cap ($500.00 max profit/day; dynamically extends target to MaxDayProfit / 0.40)
   - Evaluation Fee: $39.00 One-Time Payment (OTP) — STRICTLY ZERO monthly rebill, ZERO time expiration.
5. 10,000-Path Block-Bootstrap Monte Carlo Simulation comparing 3-Strategy (S1-S3) vs 5-Strategy (S1-S5).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.bundle import BacktestBundle
from backtest.provenance import default_store


def pareto_ratchet_contracts(profit: float, cushion: float) -> Tuple[int, str]:
    """
    Pareto Anti-Martingale Ratchet contract sizing schedule (wiki/sizing/ratchet-and-cushion.md):
    - Safe CPPI Floor Override: Cushion < $400 -> 1 micro
    - Finish-Line Shield: Profit >= +$1,150 -> 1 micro
    - Tier 3: +$550 <= Profit < +$1,150 -> 4 micros
    - Tier 2: +$200 <= Profit < +$550 -> 3 micros
    - Tier 1: Profit < +$200 -> 2 micros
    """
    if cushion < 400.0:
        return 1, "Safe CPPI (<$400 Cushion -> 1 micro)"
    if profit >= 1150.0:
        return 1, "Finish-Line Shield (>=$1,150 -> 1 micro)"
    if profit >= 550.0:
        return 4, "Tier 3 (+$550 to +$1,149 -> 4 micros)"
    if profit >= 200.0:
        return 3, "Tier 2 (+$200 to +$549 -> 3 micros)"
    return 2, "Tier 1 ($0 to +$199 -> 2 micros)"


def load_canonical_trades() -> Dict[str, pd.DataFrame]:
    """Loads the 5 canonical .obtf bundles and normalizes 1-micro base PnL and timestamps."""
    bundles_cfg = [
        ("S1_MNQ_MES", "morning_va_breakout_s1", "run_canonical_s1_va_breakout_2021_2026.obtf"),
        ("S2_MNQ", "macro_momentum_s2", "run_canonical_s2_macro_momentum_2021_2026.obtf"),
        ("S3_MGC", "gold_london_fix_s3", "run_canonical_s3_gold_london_fix_2021_2026.obtf"),
        ("S4_MNQ_EVENING", "asian_evening_reversion_s4", "run_canonical_s4_asian_evening_reversion_2021_2026.obtf"),
        ("S5_MCL_CRUDE", "crude_rth_expansion_s5", "run_canonical_s5_crude_rth_expansion_2021_2026.obtf"),
    ]

    strat_dfs: Dict[str, pd.DataFrame] = {}
    for label, strat_id, fname in bundles_cfg:
        bpath = REPO_ROOT / "results" / "bundles" / fname
        bundle = BacktestBundle.load(bpath)
        t = bundle.trades.copy()

        # Normalize date string
        if "date_str" in t.columns:
            t["date"] = t["date_str"].astype(str).str.slice(0, 10)
        else:
            t["date"] = t["date"].astype(str).str.slice(0, 10)

        t["entry_time"] = pd.to_datetime(t["entry_time"])
        t["exit_time"] = pd.to_datetime(t["exit_time"])

        # Normalize 1-micro base net PnL and canonical research PnL
        if "per_contract_pnl" in t.columns:
            t["unit_micro_pnl"] = t["per_contract_pnl"].astype(float)
            t["canonical_pnl"] = t["research_pnl"].astype(float)
        else:
            t["unit_micro_pnl"] = t["net_pnl"].astype(float)
            t["canonical_pnl"] = t["net_pnl"].astype(float)

        t["strategy_id"] = strat_id
        t["strategy_label"] = label
        strat_dfs[label] = t

    return strat_dfs


def compute_correlation_matrix(strat_dfs: Dict[str, pd.DataFrame]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Computes 5x5 daily return correlation matrix (Pearson & Spearman) over 2021-01-04 to 2026-10-30."""
    all_dates = pd.date_range("2021-01-04", "2026-10-30", freq="B").strftime("%Y-%m-%d")
    daily_mat = pd.DataFrame(0.0, index=all_dates, columns=list(strat_dfs.keys()))

    for label, df in strat_dfs.items():
        d_pnl = df.groupby("date")["unit_micro_pnl"].sum()
        for d, val in d_pnl.items():
            if d in daily_mat.index:
                daily_mat.loc[d, label] = float(val)

    pearson_corr = daily_mat.corr(method="pearson")
    spearman_corr = daily_mat.corr(method="spearman")
    return pearson_corr, spearman_corr


def simulate_sequential_evaluations(trades_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Runs sequential LucidFlex 25K evaluation campaigns across the chronological trade stream
    using the Pareto Anti-Martingale Ratchet (2 -> 3 -> 4 micros).
    """
    df = trades_df.sort_values("entry_time").reset_index(drop=True)
    day_groups = [(d, g) for d, g in df.groupby("date", sort=True)]

    evals: List[Dict[str, Any]] = []
    idx = 0
    n_days = len(day_groups)

    while idx < n_days:
        balance = 25000.0
        hwm_eod = 25000.0
        floor = 24000.0
        locked = False
        start_date = day_groups[idx][0]
        active_days = 0
        trades_taken = 0
        max_single_day_profit = 0.0
        soft_stop_hits = 0
        tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        status = "in_progress"
        end_date = start_date

        while idx < n_days:
            d_str, day_trades = day_groups[idx]
            idx += 1
            active_days += 1
            end_date = d_str
            day_pnl = 0.0

            for _, tr in day_trades.iterrows():
                # Check intraday soft stop (-$600) before taking next trade
                if day_pnl <= -600.0:
                    soft_stop_hits += 1
                    break

                cur_profit = balance + day_pnl - 25000.0
                cur_cushion = (balance + day_pnl) - floor
                contracts, _ = pareto_ratchet_contracts(cur_profit, cur_cushion)
                tier_counts[contracts] = tier_counts.get(contracts, 0) + 1

                tr_pnl = float(tr["unit_micro_pnl"]) * contracts
                # Cap single-day loss at -$600 soft stop if breached
                if day_pnl + tr_pnl <= -600.0:
                    tr_pnl = -600.0 - day_pnl
                    day_pnl += tr_pnl
                    trades_taken += 1
                    soft_stop_hits += 1
                    break

                day_pnl += tr_pnl
                trades_taken += 1

            balance += day_pnl
            if day_pnl > max_single_day_profit:
                max_single_day_profit = day_pnl

            # EOD Trailing Drawdown Floor Update
            if balance > hwm_eod:
                hwm_eod = balance
            if not locked and hwm_eod >= 26100.0:
                floor = 25100.0
                locked = True
            elif not locked:
                floor = max(floor, hwm_eod - 1000.0)

            # Check EOD Liquidation Breach
            if balance <= floor:
                status = "fail"
                break

            # Check Target & 40% Consistency Cap
            cum_profit = balance - 25000.0
            required_profit = max(1250.0, max_single_day_profit / 0.40)
            if cum_profit >= required_profit:
                status = "pass"
                break

        cal_days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days + 1
        evals.append({
            "start_date": start_date,
            "end_date": end_date,
            "status": status,
            "active_days": active_days,
            "calendar_days": cal_days,
            "trades_taken": trades_taken,
            "final_balance": round(balance, 2),
            "net_profit": round(balance - 25000.0, 2),
            "soft_stop_hits": soft_stop_hits,
            "tier_counts": tier_counts,
        })

    completed = [e for e in evals if e["status"] in ("pass", "fail")]
    passes = [e for e in completed if e["status"] == "pass"]
    fails = [e for e in completed if e["status"] == "fail"]

    return {
        "total_completed_campaigns": len(completed),
        "passes": len(passes),
        "fails": len(fails),
        "pass_rate_pct": round(len(passes) / max(len(completed), 1) * 100.0, 2),
        "median_active_days_to_pass": float(np.median([e["active_days"] for e in passes])) if passes else 0.0,
        "median_calendar_days_to_pass": float(np.median([e["calendar_days"] for e in passes])) if passes else 0.0,
        "median_trades_to_pass": float(np.median([e["trades_taken"] for e in passes])) if passes else 0.0,
        "total_soft_stop_hits": sum(e["soft_stop_hits"] for e in evals),
        "campaigns": evals,
    }


def run_monte_carlo_block_bootstrap(
    trades_df: pd.DataFrame,
    all_dates: Sequence[str],
    n_paths: int = 10000,
    block_size: int = 5,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Runs 10,000-path Block-Bootstrap Monte Carlo simulation on daily unit-micro trade vectors
    under the Pareto Anti-Martingale Ratchet (2 -> 3 -> 4 micros) and LucidFlex 25K rules.
    """
    rng = np.random.default_rng(seed)

    # Pre-group each calendar trading day's ordered list of unit_micro_pnl trades
    day_trades_map: Dict[str, List[float]] = {d: [] for d in all_dates}
    for d, g in trades_df.sort_values("entry_time").groupby("date"):
        if d in day_trades_map:
            day_trades_map[d] = g["unit_micro_pnl"].astype(float).tolist()

    day_list = [day_trades_map[d] for d in all_dates]
    n_total_days = len(day_list)
    horizon_days = 252  # 1 trading year max horizon (no time limit on LucidFlex OTP)
    n_blocks = (horizon_days // block_size) + 2

    pass_count = 0
    fail_count = 0
    pass_active_days: List[int] = []
    pass_cal_days: List[int] = []
    pass_trades: List[int] = []
    max_dds: List[float] = []

    for _ in range(n_paths):
        block_starts = rng.integers(0, n_total_days - block_size + 1, size=n_blocks)
        balance = 25000.0
        hwm_eod = 25000.0
        floor = 24000.0
        locked = False
        max_day_profit = 0.0
        active_d = 0
        cal_d = 0
        tr_cnt = 0
        peak_bal = 25000.0
        max_dd = 0.0
        outcome = "open"

        for b_start in block_starts:
            for offset in range(block_size):
                cal_d += 1
                trades_today = day_list[b_start + offset]
                if not trades_today:
                    continue
                active_d += 1
                day_pnl = 0.0
                for unit_pnl in trades_today:
                    if day_pnl <= -600.0:
                        break
                    cur_profit = balance + day_pnl - 25000.0
                    cur_cushion = (balance + day_pnl) - floor
                    contracts, _ = pareto_ratchet_contracts(cur_profit, cur_cushion)
                    tr_pnl = unit_pnl * contracts
                    if day_pnl + tr_pnl <= -600.0:
                        tr_pnl = -600.0 - day_pnl
                        day_pnl += tr_pnl
                        tr_cnt += 1
                        break
                    day_pnl += tr_pnl
                    tr_cnt += 1

                balance += day_pnl
                if balance > peak_bal:
                    peak_bal = balance
                cur_dd = peak_bal - balance
                if cur_dd > max_dd:
                    max_dd = cur_dd

                if day_pnl > max_day_profit:
                    max_day_profit = day_pnl

                if balance > hwm_eod:
                    hwm_eod = balance
                if not locked and hwm_eod >= 26100.0:
                    floor = 25100.0
                    locked = True
                elif not locked:
                    floor = max(floor, hwm_eod - 1000.0)

                if balance <= floor:
                    outcome = "fail"
                    break

                req_profit = max(1250.0, max_day_profit / 0.40)
                if (balance - 25000.0) >= req_profit:
                    outcome = "pass"
                    break
            if outcome != "open":
                break

        max_dds.append(max_dd)
        if outcome == "pass":
            pass_count += 1
            pass_active_days.append(active_d)
            pass_cal_days.append(cal_d)
            pass_trades.append(tr_cnt)
        elif outcome == "fail":
            fail_count += 1

    pass_rate = (pass_count / n_paths) * 100.0
    fail_rate = (fail_count / n_paths) * 100.0
    # Expected OTP ticket cost per funded account ($39 OTP, zero monthly rebill)
    expected_otp_cost_per_funded = 39.0 / max(pass_count / n_paths, 1e-6)

    return {
        "n_paths": n_paths,
        "block_size_days": block_size,
        "pass_rate_pct": round(pass_rate, 2),
        "fail_rate_pct": round(fail_rate, 2),
        "median_active_days_to_pass": round(float(np.median(pass_active_days)), 1) if pass_active_days else 0.0,
        "median_sessions_to_pass": round(float(np.median(pass_cal_days)), 1) if pass_cal_days else 0.0,
        "p25_sessions_to_pass": round(float(np.percentile(pass_cal_days, 25)), 1) if pass_cal_days else 0.0,
        "p75_sessions_to_pass": round(float(np.percentile(pass_cal_days, 75)), 1) if pass_cal_days else 0.0,
        "median_trades_to_pass": round(float(np.median(pass_trades)), 1) if pass_trades else 0.0,
        "median_max_dd_dollars": round(float(np.median(max_dds)), 2),
        "p95_max_dd_dollars": round(float(np.percentile(max_dds, 95)), 2),
        "otp_fee_dollars": 39.0,
        "monthly_rebill_dollars": 0.0,
        "expected_otp_cost_per_funded_account": round(expected_otp_cost_per_funded, 2),
    }


def main():
    print("=" * 88)
    print(" MILESTONE M3: 5-STRATEGY PARETO RATCHET SIMULATION & 5x5 CORRELATION MATRIX")
    print("=" * 88)

    strat_dfs = load_canonical_trades()
    pearson_corr, spearman_corr = compute_correlation_matrix(strat_dfs)

    print("\n1. EMPIRICAL 5x5 DAILY RETURN CORRELATION MATRIX (PEARSON, 2021-2026, 1,515 DAYS):")
    print("-" * 88)
    print(pearson_corr.round(4).to_string())

    # Assert all off-diagonal correlations are < 0.20
    off_diag = pearson_corr.values[~np.eye(len(pearson_corr), dtype=bool)]
    max_abs_corr = float(np.max(np.abs(off_diag)))
    print(f"\nMax Absolute Pairwise Correlation: |rho| = {max_abs_corr:.4f} (Threshold: < 0.20) -> ✅ PASS")
    assert max_abs_corr < 0.20, f"Correlation violation: {max_abs_corr} >= 0.20"

    # Build 3-Strategy (S1-S3) and 5-Strategy (S1-S5) combined trade DataFrames
    df_3strat = pd.concat([strat_dfs["S1_MNQ_MES"], strat_dfs["S2_MNQ"], strat_dfs["S3_MGC"]], ignore_index=True)
    df_5strat = pd.concat(list(strat_dfs.values()), ignore_index=True)

    # Sequential historical campaigns
    seq_3 = simulate_sequential_evaluations(df_3strat)
    seq_5 = simulate_sequential_evaluations(df_5strat)

    print("\n2. HISTORICAL SEQUENTIAL LUCIDFLEX 25K EVALUATION CAMPAIGNS (PARETO RATCHET 2->3->4):")
    print("-" * 88)
    print(f"3-Strategy Baseline (S1-S3) : {seq_3['passes']}/{seq_3['total_completed_campaigns']} Passed ({seq_3['pass_rate_pct']:.1f}%) | "
          f"Median Active Days: {seq_3['median_active_days_to_pass']:.1f} | Median Calendar Days: {seq_3['median_calendar_days_to_pass']:.1f} | "
          f"Median Trades: {seq_3['median_trades_to_pass']:.1f}")
    print(f"5-Strategy Expanded (S1-S5) : {seq_5['passes']}/{seq_5['total_completed_campaigns']} Passed ({seq_5['pass_rate_pct']:.1f}%) | "
          f"Median Active Days: {seq_5['median_active_days_to_pass']:.1f} | Median Calendar Days: {seq_5['median_calendar_days_to_pass']:.1f} | "
          f"Median Trades: {seq_5['median_trades_to_pass']:.1f}")

    # 10,000-Path Block-Bootstrap Monte Carlo
    all_dates = pd.date_range("2021-01-04", "2026-10-30", freq="B").strftime("%Y-%m-%d").tolist()
    mc_3 = run_monte_carlo_block_bootstrap(df_3strat, all_dates, n_paths=10000, block_size=5, seed=42)
    mc_5 = run_monte_carlo_block_bootstrap(df_5strat, all_dates, n_paths=10000, block_size=5, seed=42)

    print("\n3. 10,000-PATH BLOCK-BOOTSTRAP MONTE CARLO (PARETO RATCHET 2->3->4 MICROS, $39 OTP):")
    print("-" * 88)
    print(f"3-Strategy Baseline (S1-S3) : Pass Rate = {mc_3['pass_rate_pct']:.2f}% | "
          f"Median Sessions to Pass = {mc_3['median_sessions_to_pass']:.1f} (Active Trade Days: {mc_3['median_active_days_to_pass']:.1f}, Trades: {mc_3['median_trades_to_pass']:.1f}) | "
          f"Median MaxDD = ${mc_3['median_max_dd_dollars']:.2f} | Expected OTP Cost/Funded = ${mc_3['expected_otp_cost_per_funded_account']:.2f}")
    print(f"5-Strategy Expanded (S1-S5) : Pass Rate = {mc_5['pass_rate_pct']:.2f}% | "
          f"Median Sessions to Pass = {mc_5['median_sessions_to_pass']:.1f} (Active Trade Days: {mc_5['median_active_days_to_pass']:.1f}, Trades: {mc_5['median_trades_to_pass']:.1f}) | "
          f"Median MaxDD = ${mc_5['median_max_dd_dollars']:.2f} | Expected OTP Cost/Funded = ${mc_5['expected_otp_cost_per_funded_account']:.2f}")

    out_payload = {
        "max_abs_pairwise_correlation": round(max_abs_corr, 4),
        "pearson_correlation_matrix": pearson_corr.round(4).to_dict(),
        "spearman_correlation_matrix": spearman_corr.round(4).to_dict(),
        "historical_sequential_3_strategy": seq_3,
        "historical_sequential_5_strategy": seq_5,
        "monte_carlo_10k_3_strategy": mc_3,
        "monte_carlo_10k_5_strategy": mc_5,
    }

    out_path = REPO_ROOT / "results" / "m3_portfolio_ratchet_simulation.json"
    if out_path.exists():
        print(
            f"\nLEGACY ARTIFACT PRESERVED (not overwritten): {out_path}\n"
            "Authoritative LucidFlex evaluation is backtest.lucidflex_eval / "
            "scripts/run_lucidflex_eval_v1.py"
        )
    else:
        out_path.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")
        print(f"\nSaved verified M3 simulation report to: {out_path}")


if __name__ == "__main__":
    main()
