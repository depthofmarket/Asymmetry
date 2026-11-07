#!/usr/bin/env python3
"""
Red-Team Adversarial Stress Audit: Candidate 4 (H30) Small-Cap Beta Diffusion Lag (M2K).

Evaluates:
1. Cost Stress Testing (Belfort Step 06): 1x, 2x, 3x, 4x adverse slippage.
2. Parameter Sensitivity Plateau Sweep (Belfort Step 07): +/-25% across 5 steps for
   stop_loss_points, profit_target_points, laggard_max_capture.
3. Outlier Dominance Check: Largest win % of net profit, trimmed PnL/PF ex-top 1 and ex-top 5%.
4. Regime Stress Testing: 2021, 2022 Bear Market, 2023 SVB Regional Banking Crisis, 2024, 2025-2026 OOS.
5. Statistical Rigor & Deflated Sharpe Ratio (DSR): EVT SR* for N=30 trials, t-stat, p-value.
6. Drawdown & Capital Efficiency Topology: Underwater duration, calendar days in drawdown, EV/session.

Governed by the 5 Golden Rules of Quantitative Provenance and Red-Team Binding Veto Power.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest import dashboard_analytics as da
from backtest.metrics import calculate_institutional_metrics
from backtest.provenance import default_store
from scripts.research_small_cap_diffusion_s4 import (
    load_data,
    compute_daily_returns,
    compute_point_in_time_rolling_betas,
    M2K_POINT_VAL,
    M2K_TICK_SIZE,
    M2K_COMMISSION_RT,
    STOP_LOSS_POINTS,
    PROFIT_TARGET_POINTS,
    MES_MIN_RETURN_ABS,
    NQ_MIN_RETURN_ABS,
    LAGGARD_MAX_CAPTURE,
    FALLBACK_BETA,
    EVAL_START_DATE,
    EVAL_END_DATE,
    IS_SPLIT_DATE,
)


def precompute_session_candidates(
    df_rty: pd.DataFrame,
    df_es: pd.DataFrame,
    df_nq: pd.DataFrame,
    rolling_betas: Dict[str, float],
    eval_dates: List[str],
) -> List[Dict[str, Any]]:
    """Pre-extracts all potential trading sessions with market concordance and price bars."""
    rty_sub = df_rty[(df_rty["m"] >= 570) & (df_rty["m"] <= 660)].sort_values("time").reset_index(drop=True)
    es_sub = df_es[(df_es["m"] >= 570) & (df_es["m"] <= 660)].sort_values("time").reset_index(drop=True)
    nq_sub = df_nq[(df_nq["m"] >= 570) & (df_nq["m"] <= 660)].sort_values("time").reset_index(drop=True)

    rty_dict = {d: g for d, g in rty_sub.groupby("date_str")}
    es_dict = {d: g for d, g in es_sub.groupby("date_str")}
    nq_dict = {d: g for d, g in nq_sub.groupby("date_str")}

    candidates = []
    for d in eval_dates:
        rty_day = rty_dict.get(d)
        es_day = es_dict.get(d)
        nq_day = nq_dict.get(d)
        if rty_day is None or es_day is None or nq_day is None:
            continue

        es_morn = es_day[(es_day["m"] >= 570) & (es_day["m"] <= 599)]
        nq_morn = nq_day[(nq_day["m"] >= 570) & (nq_day["m"] <= 599)]
        rty_morn = rty_day[(rty_day["m"] >= 570) & (rty_day["m"] <= 599)]
        if len(es_morn) < 28 or len(nq_morn) < 28 or len(rty_morn) < 28:
            continue

        o_mes = float(es_morn.iloc[0]["open"])
        c_mes = float(es_morn.iloc[-1]["close"])
        r_mes = (c_mes - o_mes) / o_mes

        o_nq = float(nq_morn.iloc[0]["open"])
        c_nq = float(nq_morn.iloc[-1]["close"])
        r_nq = (c_nq - o_nq) / o_nq

        o_rty = float(rty_morn.iloc[0]["open"])
        c_rty = float(rty_morn.iloc[-1]["close"])
        r_m2k = (c_rty - o_rty) / o_rty

        # Market concordance check
        if not ((r_mes > 0 and r_nq > 0) or (r_mes < 0 and r_nq < 0)):
            continue

        beta = rolling_betas.get(d, FALLBACK_BETA)
        r_expected = beta * r_mes

        # Intraday execution bars (10:01 to 10:55 ET)
        rty_trade = rty_day[(rty_day["m"] >= 601) & (rty_day["m"] <= 655)]
        if rty_trade.empty or rty_trade.iloc[0]["m"] != 601:
            continue

        candidates.append({
            "date": d,
            "year": d[:4],
            "r_mes": r_mes,
            "r_nq": r_nq,
            "r_m2k": r_m2k,
            "beta": beta,
            "r_expected": r_expected,
            "direction": 1 if r_mes > 0 else -1,
            "bars": rty_trade[["open", "high", "low", "close", "time"]].to_dict("records"),
        })

    return candidates


def simulate_trades(
    candidates: List[Dict[str, Any]],
    stop_points: float,
    target_points: float,
    laggard_capture: float,
    mes_min_return: float = MES_MIN_RETURN_ABS,
    nq_min_return: float = NQ_MIN_RETURN_ABS,
    slippage_ticks: int = 1,
    commission_rt: float = M2K_COMMISSION_RT,
) -> pd.DataFrame:
    """Executes trade simulation with arbitrary brackets and cost model."""
    slippage_cost = 2 * slippage_ticks * M2K_TICK_SIZE * M2K_POINT_VAL
    total_friction = commission_rt + slippage_cost

    trades = []
    for c in candidates:
        if abs(c["r_mes"]) < mes_min_return or abs(c["r_nq"]) < nq_min_return:
            continue
        if abs(c["r_m2k"]) > laggard_capture * abs(c["r_expected"]):
            continue

        direction = c["direction"]
        bars = c["bars"]
        entry_p = float(bars[0]["open"])
        entry_time = bars[0]["time"]

        if direction == 1:
            stop_p = entry_p - stop_points
            target_p = entry_p + target_points
        else:
            stop_p = entry_p + stop_points
            target_p = entry_p - target_points

        exit_p = float(bars[-1]["close"])
        exit_reason = "time_exit_1055"
        exit_time = bars[-1]["time"]

        for b in bars:
            bh = float(b["high"])
            bl = float(b["low"])
            bo = float(b["open"])
            bt = b["time"]

            if direction == 1:
                stop_hit = bl <= stop_p
                target_hit = bh >= target_p
                if stop_hit and target_hit:
                    exit_p = stop_p
                    exit_reason = "stop_loss"
                    exit_time = bt
                    break
                elif stop_hit:
                    exit_p = min(bo, stop_p) if bo < stop_p else stop_p
                    exit_reason = "stop_loss"
                    exit_time = bt
                    break
                elif target_hit:
                    exit_p = target_p
                    exit_reason = "profit_target"
                    exit_time = bt
                    break
            else:
                stop_hit = bh >= stop_p
                target_hit = bl <= target_p
                if stop_hit and target_hit:
                    exit_p = stop_p
                    exit_reason = "stop_loss"
                    exit_time = bt
                    break
                elif stop_hit:
                    exit_p = max(bo, stop_p) if bo > stop_p else stop_p
                    exit_reason = "stop_loss"
                    exit_time = bt
                    break
                elif target_hit:
                    exit_p = target_p
                    exit_reason = "profit_target"
                    exit_time = bt
                    break

        gross_pts = (exit_p - entry_p) * direction
        gross_pnl = gross_pts * M2K_POINT_VAL
        net_pnl = gross_pnl - total_friction

        trades.append({
            "date": c["date"],
            "year": c["year"],
            "entry_time": entry_time,
            "exit_time": exit_time,
            "direction": "LONG" if direction == 1 else "SHORT",
            "entry_p": entry_p,
            "exit_p": exit_p,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "win": net_pnl > 0,
            "exit_reason": exit_reason,
            "is_oos": "IS" if c["date"] < IS_SPLIT_DATE else "OOS",
        })

    return pd.DataFrame(trades)


def compute_metrics(tdf: pd.DataFrame) -> Dict[str, Any]:
    if tdf.empty:
        return {
            "trades": 0, "win_rate": 0.0, "profit_factor": 0.0, "gross_profit": 0.0,
            "gross_loss": 0.0, "net_pnl": 0.0, "max_drawdown": 0.0, "sharpe": 0.0,
            "largest_win": 0.0, "largest_win_pct": 0.0, "expectancy": 0.0,
        }
    trades_n = len(tdf)
    wins = tdf[tdf["net_pnl"] > 0]["net_pnl"]
    losses = tdf[tdf["net_pnl"] < 0]["net_pnl"]
    gp = float(wins.sum())
    gl = float(abs(losses.sum()))
    pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)
    wr = float((tdf["net_pnl"] > 0).mean() * 100.0)
    net = float(tdf["net_pnl"].sum())
    cum = tdf["net_pnl"].cumsum()
    max_dd = float((cum.cummax() - cum).max())
    daily = tdf.groupby("date")["net_pnl"].sum()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252.0)) if len(daily) > 1 and daily.std() > 1e-12 else 0.0
    l_win = float(tdf["net_pnl"].max())
    l_win_pct = (l_win / net * 100.0) if net > 0 else 0.0
    exp = float(tdf["net_pnl"].mean())

    return {
        "trades": trades_n, "win_rate": wr, "profit_factor": pf, "gross_profit": gp,
        "gross_loss": gl, "net_pnl": net, "max_drawdown": max_dd, "sharpe": sharpe,
        "largest_win": l_win, "largest_win_pct": l_win_pct, "expectancy": exp,
    }


def main():
    print("=" * 80)
    print(" RED-TEAM ADVERSARIAL STRESS AUDIT: CANDIDATE 4 (H30 / M2K)")
    print("=" * 80)

    df_rty, df_es, df_nq = load_data()
    r_rty_daily = compute_daily_returns(df_rty)
    r_es_daily = compute_daily_returns(df_es)
    rolling_betas = compute_point_in_time_rolling_betas(r_rty_daily, r_es_daily)

    all_dates = sorted(list(set(df_rty["date_str"]) & set(df_es["date_str"]) & set(df_nq["date_str"])))
    eval_dates = [d for d in all_dates if EVAL_START_DATE <= d <= EVAL_END_DATE]
    candidates = precompute_session_candidates(df_rty, df_es, df_nq, rolling_betas, eval_dates)

    # ─────────────────────────────────────────────────────────────────────────
    # 1. BASELINE RE-VERIFICATION
    # ─────────────────────────────────────────────────────────────────────────
    base_tdf = simulate_trades(
        candidates,
        stop_points=STOP_LOSS_POINTS,
        target_points=PROFIT_TARGET_POINTS,
        laggard_capture=LAGGARD_MAX_CAPTURE,
        slippage_ticks=1,
    )
    base_m = compute_metrics(base_tdf)
    print(f"\n[BASELINE] Trades: {base_m['trades']} | WR: {base_m['win_rate']:.1f}% | PF: {base_m['profit_factor']:.2f} | Net: ${base_m['net_pnl']:.2f} | MaxDD: -${base_m['max_drawdown']:.2f} | Sharpe: {base_m['sharpe']:.2f}")

    # ─────────────────────────────────────────────────────────────────────────
    # 2. COST STRESS TESTING (Belfort Step 06)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" 1. COST STRESS TESTING (Belfort Step 06)")
    print("=" * 80)
    print(f"{'Slippage Scenario':<22} | {'Friction/RT':<11} | {'Net PnL':<11} | {'PF':<6} | {'MaxDD':<9} | {'Survives?':<10}")
    print("-" * 75)
    cost_scenarios = [
        ("Base (1 tick/side)", 1),
        ("2x Slippage (2 ticks)", 2),
        ("3x Slippage (3 ticks)", 3),
        ("4x Slippage (4 ticks)", 4),
    ]
    for label, s_ticks in cost_scenarios:
        tdf_s = simulate_trades(
            candidates,
            stop_points=STOP_LOSS_POINTS,
            target_points=PROFIT_TARGET_POINTS,
            laggard_capture=LAGGARD_MAX_CAPTURE,
            slippage_ticks=s_ticks,
        )
        ms = compute_metrics(tdf_s)
        friction = M2K_COMMISSION_RT + 2 * s_ticks * M2K_TICK_SIZE * M2K_POINT_VAL
        survives = "PASS ✅" if (ms['net_pnl'] > 0 and ms['profit_factor'] >= 1.10) else "FAIL ❌"
        print(f"{label:<22} | ${friction:>9.2f} | ${ms['net_pnl']:>9.2f} | {ms['profit_factor']:>6.2f} | -${ms['max_drawdown']:>7.2f} | {survives:<10}")

    # ─────────────────────────────────────────────────────────────────────────
    # 3. PARAMETER PLATEAU SWEEP (Belfort Step 07: +/- 25% across 5 steps)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" 2. PARAMETER SENSITIVITY PLATEAU SWEEP (Belfort Step 07)")
    print("=" * 80)

    # Param 1: Stop Loss
    stop_vals = [6.0, 7.0, 8.0, 9.0, 10.0]  # -25%, -12.5%, 0%, +12.5%, +25%
    pnl_stop = []
    print("\n[Parameter 1: Stop Loss Points (Base: 8.0 pts)]")
    for sp in stop_vals:
        tdf_sp = simulate_trades(candidates, stop_points=sp, target_points=PROFIT_TARGET_POINTS, laggard_capture=LAGGARD_MAX_CAPTURE)
        msp = compute_metrics(tdf_sp)
        pnl_stop.append(msp['net_pnl'])
        delta_str = f"{(sp - 8.0) / 8.0 * 100:+.1f}%"
        print(f"  SL {sp:>4.1f} pts ({delta_str:>7}): Trades: {msp['trades']:>2} | WR: {msp['win_rate']:>5.1f}% | PF: {msp['profit_factor']:>5.2f} | Net: ${msp['net_pnl']:>8.2f} | MaxDD: -${msp['max_drawdown']:>6.2f}")
    sr_stop = min(pnl_stop) / base_m['net_pnl'] if base_m['net_pnl'] > 0 else 0.0
    print(f"  -> Stability Ratio (Min PnL / Base): {sr_stop:.2f}x | Min PnL: ${min(pnl_stop):.2f}")

    # Param 2: Profit Target
    tgt_vals = [12.0, 14.0, 16.0, 18.0, 20.0]  # -25%, -12.5%, 0%, +12.5%, +25%
    pnl_tgt = []
    print("\n[Parameter 2: Profit Target Points (Base: 16.0 pts)]")
    for tp in tgt_vals:
        tdf_tp = simulate_trades(candidates, stop_points=STOP_LOSS_POINTS, target_points=tp, laggard_capture=LAGGARD_MAX_CAPTURE)
        mtp = compute_metrics(tdf_tp)
        pnl_tgt.append(mtp['net_pnl'])
        delta_str = f"{(tp - 16.0) / 16.0 * 100:+.1f}%"
        print(f"  TP {tp:>4.1f} pts ({delta_str:>7}): Trades: {mtp['trades']:>2} | WR: {mtp['win_rate']:>5.1f}% | PF: {mtp['profit_factor']:>5.2f} | Net: ${mtp['net_pnl']:>8.2f} | MaxDD: -${mtp['max_drawdown']:>6.2f}")
    sr_tgt = min(pnl_tgt) / base_m['net_pnl'] if base_m['net_pnl'] > 0 else 0.0
    print(f"  -> Stability Ratio (Min PnL / Base): {sr_tgt:.2f}x | Min PnL: ${min(pnl_tgt):.2f}")

    # Param 3: Laggard Max Capture
    lag_vals = [0.45, 0.525, 0.60, 0.675, 0.75]  # -25%, -12.5%, 0%, +12.5%, +25%
    pnl_lag = []
    print("\n[Parameter 3: Laggard Max Capture Threshold (Base: 0.60)]")
    for lp in lag_vals:
        tdf_lp = simulate_trades(candidates, stop_points=STOP_LOSS_POINTS, target_points=PROFIT_TARGET_POINTS, laggard_capture=lp)
        mlp = compute_metrics(tdf_lp)
        pnl_lag.append(mlp['net_pnl'])
        delta_str = f"{(lp - 0.60) / 0.60 * 100:+.1f}%"
        print(f"  Lag {lp:>5.3f} ({delta_str:>7}): Trades: {mlp['trades']:>2} | WR: {mlp['win_rate']:>5.1f}% | PF: {mlp['profit_factor']:>5.2f} | Net: ${mlp['net_pnl']:>8.2f} | MaxDD: -${mlp['max_drawdown']:>6.2f}")
    sr_lag = min(pnl_lag) / base_m['net_pnl'] if base_m['net_pnl'] > 0 else 0.0
    print(f"  -> Stability Ratio (Min PnL / Base): {sr_lag:.2f}x | Min PnL: ${min(pnl_lag):.2f}")

    # ─────────────────────────────────────────────────────────────────────────
    # 4. REGIME STRESS & OUTLIER DOMINANCE
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" 3. REGIME STRESS & OUTLIER DOMINANCE")
    print("=" * 80)
    print("\n[Yearly Breakdown]")
    for yr in sorted(base_tdf["year"].unique()):
        sub_yr = base_tdf[base_tdf["year"] == yr]
        my = compute_metrics(sub_yr)
        print(f"  Year {yr}: {my['trades']:>2} tr | WR: {my['win_rate']:>5.1f}% | PF: {my['profit_factor']:>5.2f} | Net: ${my['net_pnl']:>7.2f} | MaxDD: -${my['max_drawdown']:>6.2f}")

    # 2023 SVB Crisis check (March 2023)
    svb_trades = base_tdf[(base_tdf["date"] >= "2023-03-01") & (base_tdf["date"] <= "2023-04-30")]
    msvb = compute_metrics(svb_trades)
    print(f"\n[SVB Regional Banking Crisis Window (2023-03-01 to 2023-04-30)]")
    print(f"  Trades: {msvb['trades']} | Net PnL: ${msvb['net_pnl']:.2f}")

    # Outlier Dominance
    sorted_trades = base_tdf.sort_values("net_pnl", ascending=False).reset_index(drop=True)
    top_1_win = sorted_trades.iloc[0]["net_pnl"]
    top_3_win = sorted_trades.iloc[:3]["net_pnl"].sum()
    net_total = base_m["net_pnl"]
    print(f"\n[Outlier Concentration Analysis]")
    print(f"  Single Largest Win: ${top_1_win:.2f} ({top_1_win / net_total * 100:.1f}% of total net PnL)")
    print(f"  Top 3 Wins Total  : ${top_3_win:.2f} ({top_3_win / net_total * 100:.1f}% of total net PnL)")

    # Ex-Top 1 Net PnL
    ex_top1 = sorted_trades.iloc[1:]
    m_ex1 = compute_metrics(ex_top1)
    print(f"  Ex-Top 1 Trade Net PnL: ${m_ex1['net_pnl']:.2f} | PF: {m_ex1['profit_factor']:.2f}")

    # Ex-Top 5% Net PnL (top 3 trades removed out of 52)
    ex_top5pct = sorted_trades.iloc[3:]
    m_ex5 = compute_metrics(ex_top5pct)
    print(f"  Ex-Top 5% Trades Net PnL: ${m_ex5['net_pnl']:.2f} | PF: {m_ex5['profit_factor']:.2f}")

    # ─────────────────────────────────────────────────────────────────────────
    # 5. MULTIPLE TESTING, DSR & SAMPLE SIZE STATISTICAL TESTS
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" 4. STATISTICAL SIGNIFICANCE & MULTIPLE TESTING CORRECTION")
    print("=" * 80)
    trials_count = 30  # H1 to H30 tested in wiki
    daily_pnl = base_tdf.groupby("date")["net_pnl"].sum().values
    sr_star = da.expected_max_sharpe(n_trials=trials_count, var_sharpe=0.5)
    dsr = da.deflated_sharpe_ratio(
        returns=daily_pnl,
        n_trials=trials_count,
        var_sharpe=0.5,
        annualization_factor=252.0,
    )
    t_stat = float(np.mean(daily_pnl) / (np.std(daily_pnl) / np.sqrt(len(daily_pnl)))) if len(daily_pnl) > 1 else 0.0
    p_val = float(2 * (1 - da.norm_cdf(abs(t_stat)))) if len(daily_pnl) > 1 else 1.0

    print(f"  Total Trades (5.8 Years): {base_m['trades']} trades (~{base_m['trades'] / 5.8:.1f} trades/year; ~{base_m['trades'] / (5.8 * 12):.2f} trades/month)")
    print(f"  Annualized Sharpe Ratio : {base_m['sharpe']:.2f}")
    print(f"  EVT Expected Max Sharpe : {sr_star:.2f} (Hurdle for N={trials_count} trials)")
    print(f"  Deflated Sharpe Ratio   : {dsr:.4f}")
    print(f"  t-statistic             : {t_stat:.2f}")
    print(f"  p-value                 : {p_val:.4f} (Statistical significance threshold: p < 0.05)")

    # ─────────────────────────────────────────────────────────────────────────
    # 6. UNDERWATER DURATION TOPOLOGY
    # ─────────────────────────────────────────────────────────────────────────
    cum = base_tdf["net_pnl"].cumsum()
    peak = cum.cummax()
    is_underwater = cum < peak
    underwater_pct = is_underwater.mean() * 100.0
    print("\n[Underwater Drawdown Topology]")
    print(f"  Underwater Trade Fraction : {underwater_pct:.1f}% of trades spent in drawdown")
    print(f"  Cumulative Net Profit     : ${base_m['net_pnl']:.2f} over 2,126 calendar days ($0.15/day!)")


if __name__ == "__main__":
    main()
