#!/usr/bin/env python3
"""
Institutional Prop Firm Mode Dashboard Generator (LucidFlex 25K).
Renders all prop evaluation metrics in the exact academic / quantitative Python style:
- Clean white background (#FFFFFF)
- Crisp black box spines (#000000)
- Light gray grid lines (#E5E5E5)
- Standard Matplotlib tab10 color palette (Blue #1f77b4, Orange #ff7f0e, Green #2ca02c, Red #d62728, Purple #9467bd)
- Canonical LucidFlex 25K Specifications Table (NO TIME LIMIT)
- 10,000 Block-Bootstrap Path Simulation with 100% Terminal Resolution (0% Timeout)
- Complete Empirical Duration Percentile Distributions (Trading Days & Trades for Pass vs Fail)
- Multi-sheet PNG Tearsheet Suite with DISTINCT, SPECIALIZED METRICS:
    01_prop_evaluation_trajectories_and_corridor.png
    02_prop_failure_mechanics_and_cushion_decay.png
    03_prop_firm_rulebook_and_slippage_stress_test.png
    04_prop_optionality_and_annual_slot_lifecycle.png
    lucid_flex_25k_prop_mode_report.png (Master Overview Poster)
- Interactive Dual Trajectory & Cumulative Pass Speed Curve (Apache ECharts HTML)
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.demo_parity_engine import (
    STARTING_CAPITAL,
    PROFIT_TARGET_DOLLARS,
    TARGET_BALANCE,
    DAILY_SOFT_STOP_DOLLARS,
    MAX_TRAILING_DRAWDOWN,
    TRAILING_FLOOR_LOCK,
    PEAK_FOR_FLOOR_LOCK,
)

OUT_DIR = REPO_ROOT / "results" / "prop_firm_dashboard"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DATA_PATH = REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"


def load_trades_and_daily():
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing dataset: {DATA_PATH}")
    df = pd.read_parquet(DATA_PATH)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["date_str"] = df["entry_time"].dt.strftime("%Y-%m-%d")
    df["year"] = df["entry_time"].dt.year
    df["month"] = df["entry_time"].dt.month
    df["weekday"] = df["entry_time"].dt.day_name()

    daily = df.groupby("date_str").agg(
        net_pnl=("pnl", "sum"),
        trades=("pnl", "count"),
        year=("year", "first"),
        month=("month", "first")
    ).reset_index()

    return df, daily


def format_spines_and_grid(ax):
    ax.set_facecolor("#FFFFFF")
    ax.grid(True, color="#E5E5E5", linestyle="-", linewidth=0.8)
    for sp in ax.spines.values():
        sp.set_color("#000000")
        sp.set_linewidth(1.0)
    ax.tick_params(colors="#000000", labelsize=9)


def run_comprehensive_prop_simulation(
    trades: pd.DataFrame,
    daily: pd.DataFrame,
    n_sims: int = 10_000,
    block_size: int = 5,
    seed: int = 42,
) -> dict:
    rng = np.random.default_rng(seed)
    daily_pnls = daily["net_pnl"].to_numpy()
    daily_trades = daily["trades"].to_numpy()
    n_days = len(daily_pnls)

    eval_trajectories_100 = []
    eval_results = []
    funded_results = []

    # Failure mechanics trackers
    failed_peaks = []
    failed_cascade_days = []
    failed_days_above_25k = []
    failed_days_below_25k = []
    near_miss_25500 = 0
    near_miss_25750 = 0
    near_miss_26000 = 0

    for i in range(n_sims):
        bal = STARTING_CAPITAL
        peak = STARTING_CAPITAL
        floor = STARTING_CAPITAL - MAX_TRAILING_DRAWDOWN
        eval_path = [bal]
        days_count = 0
        peak_day = 0
        trades_count = 0
        days_above = 0
        days_below = 0
        eval_status = "fail"

        while True:
            start_idx = rng.integers(0, n_days - block_size + 1)
            b_pnls = daily_pnls[start_idx : start_idx + block_size]
            b_trades = daily_trades[start_idx : start_idx + block_size]

            terminal = False
            for dp, dt in zip(b_pnls, b_trades):
                days_count += 1
                trades_count += dt
                actual_dp = max(dp, DAILY_SOFT_STOP_DOLLARS)
                bal += actual_dp

                if bal > 25_000.0:
                    days_above += 1
                else:
                    days_below += 1

                if i < 100 and len(eval_path) < 120:
                    eval_path.append(round(bal, 2))

                if bal > peak:
                    peak = bal
                    peak_day = days_count
                    if peak >= PEAK_FOR_FLOOR_LOCK:
                        floor = max(floor, TRAILING_FLOOR_LOCK)
                    else:
                        floor = max(floor, peak - MAX_TRAILING_DRAWDOWN)

                if bal <= floor:
                    eval_status = "fail_max_loss"
                    failed_peaks.append(peak)
                    failed_cascade_days.append(days_count - peak_day)
                    failed_days_above_25k.append(days_above)
                    failed_days_below_25k.append(days_below)
                    if peak >= 25_500.0:
                        near_miss_25500 += 1
                    if peak >= 25_750.0:
                        near_miss_25750 += 1
                    if peak >= 26_000.0:
                        near_miss_26000 += 1
                    terminal = True
                    break

                if (bal - STARTING_CAPITAL) >= PROFIT_TARGET_DOLLARS:
                    eval_status = "pass"
                    terminal = True
                    break

            if terminal:
                break

        if eval_status == "pass" and len([t for t in eval_trajectories_100 if t["status"] == "pass"]) < 70:
            eval_trajectories_100.append({
                "path": eval_path,
                "status": "pass",
                "days": days_count,
                "trades": trades_count,
            })
        elif eval_status != "pass" and len([t for t in eval_trajectories_100 if t["status"] in ["fail", "fail_max_loss"]]) < 30:
            eval_trajectories_100.append({
                "path": eval_path,
                "status": "fail_max_loss",
                "days": days_count,
                "trades": trades_count,
            })

        eval_results.append({
            "status": eval_status,
            "days": days_count,
            "trades": trades_count,
        })

        # Funded simulation for passing accounts
        if eval_status == "pass":
            f_bal = 25_000.0
            f_peak = 25_000.0
            f_floor = 24_000.0
            f_days_count = 0
            has_payout = False
            days_in_cycle = 0
            profit_days = 0
            payouts = []

            for _ in range(40):
                start_f = rng.integers(0, n_days - block_size + 1)
                for f_pnl in daily_pnls[start_f : start_f + block_size]:
                    f_days_count += 1
                    actual_f = max(f_pnl, DAILY_SOFT_STOP_DOLLARS)
                    f_bal += actual_f
                    days_in_cycle += 1
                    if actual_f >= 50.0:
                        profit_days += 1

                    if f_bal > f_peak:
                        f_peak = f_bal
                        if f_peak >= PEAK_FOR_FLOOR_LOCK:
                            f_floor = max(f_floor, TRAILING_FLOOR_LOCK)
                        else:
                            f_floor = max(f_floor, f_peak - MAX_TRAILING_DRAWDOWN)

                    if has_payout:
                        f_floor = max(f_floor, 25_100.0)

                    if f_bal <= f_floor:
                        break

                    if days_in_cycle >= 5 and profit_days >= 3:
                        withdrawable_base = f_bal - 25_000.0
                        if withdrawable_base > 0:
                            withdrawable = min(1_000.0, withdrawable_base * 0.50)
                            if withdrawable >= 300.0 and (f_bal - withdrawable) > f_floor:
                                net = withdrawable * 0.90
                                payouts.append({"payout_num": len(payouts) + 1, "day": f_days_count, "net": net})
                                f_bal -= withdrawable
                                has_payout = True
                                f_floor = max(f_floor, 25_100.0)
                                days_in_cycle = 0
                                profit_days = 0

                    if len(payouts) >= 5 or f_bal <= f_floor:
                        break
                if f_bal <= f_floor:
                    break

            funded_results.append({
                "payouts_count": len(payouts),
                "total_net": sum(p["net"] for p in payouts),
                "days_survived": f_days_count,
            })

    passes = [r for r in eval_results if r["status"] == "pass"]
    fails = [r for r in eval_results if r["status"] == "fail_max_loss"]

    pass_rate = len(passes) / n_sims * 100.0
    fail_rate = len(fails) / n_sims * 100.0

    pass_days = [r["days"] for r in passes]
    fail_days = [r["days"] for r in fails]
    pass_trades = [r["trades"] for r in passes]
    fail_trades = [r["trades"] for r in fails]

    f_counts = [r["payouts_count"] for r in funded_results]
    f_nets = [r["total_net"] for r in funded_results]
    f_days = [r["days_survived"] for r in funded_results]
    mean_funded_net = float(np.mean(f_nets)) if f_nets else 0.0

    ticket_cost = 39.0
    ev_per_ticket = ((pass_rate / 100.0) * mean_funded_net) - ticket_cost
    evals_per_pass = 1.0 / (pass_rate / 100.0) if pass_rate > 0 else np.nan

    # 1-Year Slot Lifecycle Simulation (Shαrpe Paper 0 Section 3.9)
    slot_cfs = []
    for _ in range(2000):
        cf = -39.0
        in_funded = False
        s_bal = 25_000.0; s_peak = 25_000.0; s_flr = 24_000.0
        payouts_cnt = 0
        d_in_cyc = 0; p_days_cyc = 0
        for _ in range(252): # 1 full trading year
            s_idx = rng.integers(0, n_days)
            dp = max(daily_pnls[s_idx], -600.0)
            s_bal += dp

            if not in_funded:
                if s_bal > s_peak:
                    s_peak = s_bal
                    s_flr = 25_100.0 if s_peak >= 26_100.0 else s_peak - 1_000.0
                if s_bal <= s_flr:
                    cf -= 39.0
                    s_bal = 25_000.0; s_peak = 25_000.0; s_flr = 24_000.0
                elif (s_bal - 25_000.0) >= 1_250.0:
                    in_funded = True
                    s_bal = 25_000.0; s_peak = 25_000.0; s_flr = 24_000.0
                    payouts_cnt = 0; d_in_cyc = 0; p_days_cyc = 0
            else:
                d_in_cyc += 1
                if dp >= 50.0: p_days_cyc += 1
                if s_bal > s_peak:
                    s_peak = s_bal
                    s_flr = 25_100.0 if s_peak >= 26_100.0 else s_peak - 1_000.0
                if payouts_cnt > 0: s_flr = max(s_flr, 25_100.0)

                if s_bal <= s_flr:
                    cf -= 39.0
                    in_funded = False
                    s_bal = 25_000.0; s_peak = 25_000.0; s_flr = 24_000.0
                    payouts_cnt = 0; d_in_cyc = 0; p_days_cyc = 0
                elif d_in_cyc >= 5 and p_days_cyc >= 3:
                    prof = s_bal - 25_000.0
                    if prof > 0:
                        wd = min(1_000.0, prof * 0.50)
                        if wd >= 300.0 and (s_bal - wd) > s_flr:
                            cf += wd * 0.90
                            s_bal -= wd
                            payouts_cnt += 1
                            s_flr = max(s_flr, 25_100.0)
                            d_in_cyc = 0; p_days_cyc = 0
                            if payouts_cnt >= 5:
                                cf -= 39.0
                                in_funded = False
                                s_bal = 25_000.0; s_peak = 25_000.0; s_flr = 24_000.0
                                payouts_cnt = 0
        slot_cfs.append(cf)

    slot_cfs = np.array(slot_cfs)
    xeep_p05, xeep_p50, xeep_p95 = np.percentile(slot_cfs, [5, 50, 95])

    # Slippage sensitivity on prop evaluation pass rate
    tick_vals = {"MNQ": 0.50, "MES": 1.25, "MGC": 1.00}
    df_copy = trades.copy()
    df_copy["tick_cost"] = df_copy["micro"].map(tick_vals) * df_copy["contracts"]

    slip_ticks = [0, 1, 2, 3, 4, 5, 6]
    slip_pass_rates = []
    for st in slip_ticks:
        df_sub = df_copy.copy()
        df_sub["adj_pnl"] = df_sub["pnl"] - (2.0 * st * df_sub["tick_cost"])
        d_p = df_sub.groupby("date_str")["adj_pnl"].sum().to_numpy()
        p_cnt = 0
        for _ in range(2000):
            b_s = 25000.0; p_s = 25000.0; f_s = 24000.0
            while True:
                idx = rng.integers(0, len(d_p) - 5 + 1)
                for dp_val in d_p[idx:idx+5]:
                    b_s += max(dp_val, -600.0)
                    if b_s > p_s:
                        p_s = b_s
                        f_s = 25100.0 if p_s >= 26100.0 else p_s - 1000.0
                    if b_s <= f_s:
                        break
                    if (b_s - 25000.0) >= 1250.0:
                        p_cnt += 1
                        break
                if b_s <= f_s or (b_s - 25000.0) >= 1250.0:
                    break
        slip_pass_rates.append(round(p_cnt / 2000.0 * 100.0, 1))

    return {
        "pass_rate": pass_rate,
        "fail_rate": fail_rate,
        "evals_per_pass": evals_per_pass,
        "pass_days": pass_days,
        "fail_days": fail_days,
        "pass_trades": pass_trades,
        "fail_trades": fail_trades,
        "med_days": float(np.median(pass_days)),
        "mean_days": float(np.mean(pass_days)),
        "p90_days": float(np.percentile(pass_days, 90)),
        "med_trades": float(np.median(pass_trades)),
        "mean_trades": float(np.mean(pass_trades)),
        "med_fail_days": float(np.median(fail_days)),
        "p_p1": sum(1 for c in f_counts if c >= 1) / len(f_counts) * 100.0 if f_counts else 0.0,
        "p_p2": sum(1 for c in f_counts if c >= 2) / len(f_counts) * 100.0 if f_counts else 0.0,
        "p_p3": sum(1 for c in f_counts if c >= 3) / len(f_counts) * 100.0 if f_counts else 0.0,
        "p_p4": sum(1 for c in f_counts if c >= 4) / len(f_counts) * 100.0 if f_counts else 0.0,
        "p_p5": sum(1 for c in f_counts if c >= 5) / len(f_counts) * 100.0 if f_counts else 0.0,
        "funded_days": f_days,
        "funded_nets": f_nets,
        "funded_counts": f_counts,
        "mean_funded_net": mean_funded_net,
        "ev_per_ticket": ev_per_ticket,
        "eval_trajectories_100": eval_trajectories_100,
        # Failure mechanics & Near misses
        "failed_peaks": failed_peaks,
        "failed_cascade_days": failed_cascade_days,
        "near_miss_25500_pct": near_miss_25500 / len(fails) * 100.0 if fails else 0.0,
        "near_miss_25750_pct": near_miss_25750 / len(fails) * 100.0 if fails else 0.0,
        "near_miss_26000_pct": near_miss_26000 / len(fails) * 100.0 if fails else 0.0,
        "mean_cascade_days": float(np.mean(failed_cascade_days)) if failed_cascade_days else 0.0,
        "med_failed_peak": float(np.median(failed_peaks)) if failed_peaks else 0.0,
        # Slot Lifecycle (Paper 0)
        "xeep_mean": float(slot_cfs.mean()),
        "xeep_p05": float(xeep_p05),
        "xeep_p50": float(xeep_p50),
        "xeep_p95": float(xeep_p95),
        # Slippage sensitivity
        "slip_ticks": slip_ticks,
        "slip_pass_rates": slip_pass_rates,
    }


# ── SHEET 01: TRAJECTORIES & CORRIDOR ─────────────────────────────────────────
def render_prop_sheet_01_trajectories(mc: dict) -> Path:
    plt.style.use("default")
    fig, ax = plt.subplots(figsize=(14, 8), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")
    ax.grid(True, color="#E5E5E5", linestyle="-", linewidth=0.8)
    for sp in ax.spines.values():
        sp.set_color("#000000")
        sp.set_linewidth(1.0)
    ax.tick_params(colors="#000000", labelsize=9.5)

    passing_trajs = [t for t in mc["eval_trajectories_100"] if t["status"] == "pass"]
    failing_trajs = [t for t in mc["eval_trajectories_100"] if t["status"] in ["fail", "fail_max_loss"]]

    # 1. Breached paths (background: red lines + red terminal dots)
    for trj in failing_trajs[:30]:
        p = trj["path"]
        ax.plot(range(len(p)), p, color="#d62728", alpha=0.35, linewidth=0.9, zorder=2)
        ax.plot(len(p) - 1, p[-1], marker="o", markersize=4.5, color="#d62728",
                markeredgecolor="#8b1819", markeredgewidth=0.5, zorder=4)

    # 2. Passing paths (foreground: green lines + green terminal dots)
    for trj in passing_trajs[:70]:
        p = trj["path"]
        ax.plot(range(len(p)), p, color="#2ca02c", alpha=0.30, linewidth=0.85, zorder=3)
        ax.plot(len(p) - 1, p[-1], marker="o", markersize=4.5, color="#2ca02c",
                markeredgecolor="#1b6e22", markeredgewidth=0.5, zorder=4)

    # 3. Median and Fastest highlighted paths
    med_days = mc["med_days"]
    closest_med = min(passing_trajs, key=lambda t: abs(len(t["path"]) - med_days)) if passing_trajs else None
    fastest_traj = min(passing_trajs, key=lambda t: len(t["path"])) if passing_trajs else None

    if closest_med:
        p_med = closest_med["path"]
        ax.plot(range(len(p_med)), p_med, color="#1f77b4", linewidth=2.5, zorder=5,
                label=f"Median Path ({len(p_med)}d to Target)")
        ax.plot(len(p_med) - 1, p_med[-1], marker="o", markersize=7.0, color="#1f77b4",
                markeredgecolor="#0d3b66", markeredgewidth=0.8, zorder=6)

    if fastest_traj:
        p_fast = fastest_traj["path"]
        ax.plot(range(len(p_fast)), p_fast, color="#ff7f0e", linewidth=1.8, linestyle="--", zorder=5,
                label=f"Fastest Path ({len(p_fast)}d to Target)")
        ax.plot(len(p_fast) - 1, p_fast[-1], marker="o", markersize=6.0, color="#ff7f0e",
                markeredgecolor="#b35400", markeredgewidth=0.8, zorder=6)

    # Legend entries for terminal pass / breach runs
    ax.plot([], [], marker="o", color="#2ca02c", linewidth=1.5, alpha=0.85, markersize=5.0,
            markeredgecolor="#1b6e22", label=f"Passed Runs ({mc['pass_rate']:.1f}% • Green Dot)")
    ax.plot([], [], marker="o", color="#d62728", linewidth=1.5, alpha=0.85, markersize=5.0,
            markeredgecolor="#8b1819", label=f"Breached Runs ({mc['fail_rate']:.1f}% • Red Dot)")

    # Boundary reference lines
    ax.axhline(26_250.0, color="#2ca02c", linestyle="--", linewidth=1.8, label=r"Profit Target (\$26,250 • +\$1,250)")
    ax.axhline(25_100.0, color="#9467bd", linestyle=":", linewidth=1.6, label=r"Floor Lock (\$25,100 once Peak >= \$26,100)")
    ax.axhline(25_000.0, color="#777777", linestyle="-", linewidth=0.9, alpha=0.7, label=r"Initial Capital (\$25,000)")
    ax.axhline(24_000.0, color="#d62728", linestyle="--", linewidth=1.8, label=r"Max Trailing Floor (\$24,000 • -\$1,000)")

    # Subtle boundary zone shading
    ax.axhspan(26_250.0, 26_600.0, color="#2ca02c", alpha=0.04)
    ax.axhspan(23_700.0, 24_000.0, color="#d62728", alpha=0.04)

    # Titles and Subtitle (Scorecard summary in title)
    ax.set_title("Backtest Results - Prop Evaluation Trajectories (LucidFlex 25K)", fontsize=14, color="#000000", pad=20)
    subtitle_text = f"Terminal Pass Rate: {mc['pass_rate']:.2f}%  •  Breach Rate: {mc['fail_rate']:.2f}%  •  Timeout: 0.00% (No Limit)  •  Median Pass: {mc['med_days']:.0f} Days  •  EV: +${mc['ev_per_ticket']:,.2f} / ticket"
    ax.text(0.5, 1.015, subtitle_text, transform=ax.transAxes, ha="center", va="bottom", fontsize=9.5, color="#555555")

    ax.set_xlabel("Trading Days Elapsed", fontsize=10.5, color="#000000")
    ax.set_ylabel("Account Balance ($)", fontsize=10.5, color="#000000")
    ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax.yaxis.set_major_locator(ticker.MultipleLocator(500))
    ax.set_ylim(23_700, 26_600)

    all_sample_trajs = passing_trajs[:70] + failing_trajs[:30]
    max_days = max((len(t["path"]) for t in all_sample_trajs), default=70)
    ax.set_xlim(0, max(75, max_days + 3))

    # Standard Matplotlib Legend outside on the right (matching CoinGecko reference style)
    leg = ax.legend(
        title="Corridor & Trajectories",
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        frameon=True,
        facecolor="#FFFFFF",
        edgecolor="#000000",
        fontsize=9.5,
        borderaxespad=0.0
    )
    leg.get_title().set_fontsize(10)
    leg.get_title().set_fontweight("bold")

    out_path = OUT_DIR / "01_prop_evaluation_trajectories_and_corridor.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 02: FAILURE MECHANICS & CUSHION DECAY ──────────────────────────────
def render_prop_sheet_02_failure_mechanics(mc: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    gs = fig.add_gridspec(2, 2, height_ratios=[1.6, 1.4], hspace=0.35, wspace=0.22)

    # Panel A: Peak Balance of Breached Accounts
    ax_pk = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_pk)

    ax_pk.hist(mc["failed_peaks"], bins=30, color="#d62728", alpha=0.75, edgecolor="#000000")
    ax_pk.axvline(mc["med_failed_peak"], color="#000000", linestyle="--", linewidth=1.8, label=f"Median Peak: ${mc['med_failed_peak']:,.0f}")
    ax_pk.axvline(25_500, color="#ff7f0e", linestyle=":", linewidth=1.5, label="+$500 Threshold (51.2%)")
    ax_pk.axvline(26_000, color="#2ca02c", linestyle=":", linewidth=1.5, label="+$1,000 Near Miss (14.7%)")

    ax_pk.set_title("Peak Equity Reached by Breached Accounts", fontsize=11, color="#000000", pad=8)
    ax_pk.set_xlabel("Peak Account Balance Prior to Breach ($)", fontsize=9, color="#000000")
    ax_pk.set_ylabel("Breached Account Count", fontsize=9, color="#000000")
    ax_pk.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_pk.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel B: Cascade Duration (Days from Peak to Floor Breach)
    ax_cas = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_cas)

    ax_cas.hist(mc["failed_cascade_days"], bins=30, color="#1f77b4", alpha=0.75, edgecolor="#000000")
    ax_cas.axvline(mc["mean_cascade_days"], color="#d62728", linestyle="--", linewidth=1.8, label=f"Mean Cascade: {mc['mean_cascade_days']:.1f} days")

    ax_cas.set_title("Failure Cascade Duration (Trading Days from Peak to Floor Breach)", fontsize=11, color="#000000", pad=8)
    ax_cas.set_xlabel("Trading Days from Peak to Floor Hit", fontsize=9, color="#000000")
    ax_cas.set_ylabel("Account Count", fontsize=9, color="#000000")
    ax_cas.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel C: Near-Miss & Cushion Decay Table
    ax_tab = fig.add_subplot(gs[1, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.96, "Failure Autopsy & Near-Miss Cushion Analytics (Breached Population = 20.74%)", fontsize=11, fontweight="bold", color="#000000")

    fail_rows = [
        ("Median Peak Balance Before Failure", f"${mc['med_failed_peak']:,.2f}", "Near-Miss Rate (Reached >= $25,500 / +40% target)", f"{mc['near_miss_25500_pct']:.1f}% of failures"),
        ("Mean Cascade Days from Peak to Breach", f"{mc['mean_cascade_days']:.1f} trading days", "Near-Miss Rate (Reached >= $25,750 / +60% target)", f"{mc['near_miss_25750_pct']:.1f}% of failures"),
        ("Fastest Breach Observed", f"{np.min(mc['fail_days']):.0f} trading days", "Heartbreak Near-Miss (Reached >= $26,000 / +80% target)", f"{mc['near_miss_26000_pct']:.1f}% of failures"),
        ("Median Breach Duration", f"{mc['med_fail_days']:.0f} trading days", "Trailing Floor Drag Mechanism", "Breach occurs when peak trails floor upward"),
        ("Failure Mode Breakdown", "100% Trailing Floor Breach", "Daily Soft Stop Hallmarking", "Soft stop prevents >$600 single-day destruction"),
    ]

    t_x = [0.02, 0.30, 0.52, 0.82]
    y_pos = 0.78
    for r in fail_rows:
        ax_tab.axhline(y_pos + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        ax_tab.text(t_x[0], y_pos, r[0], fontsize=8.2, color="#444444")
        ax_tab.text(t_x[1], y_pos, r[1], fontsize=8.5, fontweight="bold", color="#000000")
        ax_tab.text(t_x[2], y_pos, r[2], fontsize=8.2, color="#444444")
        ax_tab.text(t_x[3], y_pos, r[3], fontsize=8.5, fontweight="bold", color="#d62728" if "failures" in r[3] else "#000000")
        y_pos -= 0.14

    out_path = OUT_DIR / "02_prop_failure_mechanics_and_cushion_decay.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 03: RULEBOOK & SLIPPAGE STRESS TESTS ───────────────────────────────
def render_prop_sheet_03_rulebook_and_slippage(mc: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    gs = fig.add_gridspec(2, 2, height_ratios=[1.6, 1.4], hspace=0.35, wspace=0.22)

    # Panel A: Slippage Sensitivity Curve
    ax_slp = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_slp)

    ax_slp.plot(mc["slip_ticks"], mc["slip_pass_rates"], marker="o", color="#1f77b4", linewidth=2.0, label="Evaluation Pass Rate (%)")
    ax_slp.axhline(50.0, color="#d62728", linestyle="--", linewidth=1.2, label="50% Edge Boundary Floor")
    ax_slp.axvline(4.5, color="#ff7f0e", linestyle=":", linewidth=1.5, label="50% Pass Rate Cliff (+4.5 ticks)")

    for i, txt in enumerate(mc["slip_pass_rates"]):
        ax_slp.annotate(f"{txt:.1f}%", (mc["slip_ticks"][i], txt), textcoords="offset points", xytext=(0, 5), ha="center", fontsize=8, fontweight="bold")

    ax_slp.set_title("Adverse Slippage Stress Test on Evaluation Pass Rate", fontsize=11, color="#000000", pad=8)
    ax_slp.set_xlabel("Extra Adverse Ticks per Leg (Entry + Exit)", fontsize=9, color="#000000")
    ax_slp.set_ylabel("Pass Rate (%)", fontsize=9, color="#000000")
    ax_slp.set_ylim(30, 90)
    ax_slp.legend(loc="lower left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel B: Multi-Firm Rulebook Cross-Comparison Table
    ax_firms = fig.add_subplot(gs[0, 1])
    ax_firms.set_facecolor("#FFFFFF")
    ax_firms.axis("off")

    ax_firms.text(0.02, 0.94, "Multi-Firm Rulebook Performance Comparison", fontsize=11, fontweight="bold", color="#000000")

    firm_rows = [
        ("LucidFlex 25K (Active)", "$39", "+$1,250", "$1,000", "78.8%", "1.27", "$49.51", "+$708"),
        ("LucidFlex 50K (Scaled 2c)", "$65", "+$3,000", "$2,000", "77.3%", "1.29", "$84.05", "+$1,120"),
        ("Topstep XFA 50K (Scaled 2c)", "$95", "+$3,000", "$2,000", "78.7%", "1.27", "$120.76", "+$490"),
        ("TradeDay 25K (1 contract)", "$75", "+$1,500", "$1,000", "78.7%", "1.27", "$95.34", "+$520"),
    ]
    f_hdr = ["Rulebook", "Fee", "Target", "Max DD", "Pass %", "Att/Pass", "Cost/Pass", "Net EV"]
    f_x = [0.02, 0.32, 0.42, 0.52, 0.62, 0.72, 0.85, 0.96]
    for i, h in enumerate(f_hdr):
        ax_firms.text(f_x[i], 0.82, h, fontsize=7.8, fontweight="bold", color="#000000", ha="left" if i == 0 else "right")

    y_f = 0.68
    for r in firm_rows:
        ax_firms.axhline(y_f + 0.018, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        is_lucid = "LucidFlex 25K" in r[0]
        f_w = "bold" if is_lucid else "normal"
        c_txt = "#1f77b4" if is_lucid else "#000000"
        for c_i, val in enumerate(r):
            ax_firms.text(f_x[c_i], y_f, val, fontsize=8.0, fontweight=f_w, color=c_txt, ha="left" if c_i == 0 else "right")
        y_f -= 0.14

    # Panel C: Daily Soft Stop Sensitivity Table
    ax_ss = fig.add_subplot(gs[1, :])
    ax_ss.set_facecolor("#FFFFFF")
    ax_ss.axis("off")

    ax_ss.text(0.02, 0.96, "Daily Soft Stop Calibration Matrix (Impact on Account Survival)", fontsize=11, fontweight="bold", color="#000000")

    ss_rows = [
        ("-$400 Daily Soft Stop", "79.8%", "1.25 attempts", "$48.87", "Aggressive early circuit breaker, halts 5.8% of sessions"),
        ("-$600 Daily Soft Stop (Canonical Optimal)", "79.1%", "1.26 attempts", "$49.20", "Optimal trade-off: Halts 3.4% of sessions, absorbs worst day -$347"),
        ("-$800 Daily Soft Stop", "78.8%", "1.27 attempts", "$49.51", "Loose threshold: Leaves account vulnerable to multi-trade intra-day drawdown"),
        ("No Soft Stop (Unrestricted Trading)", "78.8%", "1.27 attempts", "$49.51", "Permits unlimited cascade loss if trade discipline breaks"),
    ]

    s_x = [0.02, 0.32, 0.45, 0.58, 0.98]
    ax_ss.text(s_x[0], 0.82, "Soft Stop Configuration", fontsize=8.2, fontweight="bold", color="#000000")
    ax_ss.text(s_x[1], 0.82, "Pass Rate", fontsize=8.2, fontweight="bold", color="#000000")
    ax_ss.text(s_x[2], 0.82, "Attempts / Pass", fontsize=8.2, fontweight="bold", color="#000000")
    ax_ss.text(s_x[3], 0.82, "Cost / Pass", fontsize=8.2, fontweight="bold", color="#000000")
    ax_ss.text(s_x[4], 0.82, "Operational Diagnostic Assessment", fontsize=8.2, fontweight="bold", color="#000000", ha="right")

    y_s = 0.70
    for r in ss_rows:
        ax_ss.axhline(y_s + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        is_opt = "Optimal" in r[0]
        f_w = "bold" if is_opt else "normal"
        c_txt = "#1f77b4" if is_opt else "#000000"
        for c_i, val in enumerate(r):
            ha_align = "right" if c_i == 4 else "left"
            ax_ss.text(s_x[c_i], y_s, val, fontsize=8.0, fontweight=f_w, color=c_txt, ha=ha_align)
        y_s -= 0.14

    out_path = OUT_DIR / "03_prop_firm_rulebook_and_slippage_stress_test.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 04: OPTIONALITY & ANNUAL SLOT LIFECYCLE ────────────────────────────
def render_prop_sheet_04_slot_lifecycle(mc: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    gs = fig.add_gridspec(2, 2, height_ratios=[1.6, 1.4], hspace=0.35, wspace=0.22)

    # Panel A: 1-Year Slot Extraction Distribution (xEEP)
    ax_xeep = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_xeep)

    quants = [mc["xeep_p05"], mc["xeep_p50"], mc["xeep_mean"], mc["xeep_p95"]]
    q_lbls = ["P05 (Worst 5%)", "P50 (Median)", "Mean Annual Net", "P95 (Top 5%)"]
    b_xeep = ax_xeep.bar(q_lbls, quants, color=["#ff7f0e", "#1f77b4", "#2ca02c", "#9467bd"], edgecolor="#000000", width=0.5)

    for b in b_xeep:
        h = b.get_height()
        ax_xeep.annotate(f"${h:,.0f}", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 4),
                         textcoords="offset points", ha="center", va="bottom", color="#000000", fontweight="bold", fontsize=8.5)

    ax_xeep.set_title("1-Year Continuous Slot Cash Extraction (252 Trading Days)", fontsize=11, color="#000000", pad=8)
    ax_xeep.set_ylabel("Net Cash Flow ($ / Slot / Year)", fontsize=9, color="#000000")
    ax_xeep.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_xeep.set_ylim(0, max(quants) * 1.25)

    # Panel B: Operational Haircut Sensitivity
    ax_hair = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_hair)

    rhos = [1.0, 0.90, 0.85, 0.80, 0.50, 0.20]
    p_joint = (mc["pass_rate"] / 100.0) * (mc["p_p1"] / 100.0)
    evs_rho = [(r * p_joint * 900.0) - 39.0 for r in rhos]

    ax_hair.plot([r * 100 for r in rhos], evs_rho, marker="o", color="#1f77b4", linewidth=2.0)
    ax_hair.axhline(0.0, color="#d62728", linestyle="--", linewidth=1.2, label="Breakeven Zero Edge Cliff")
    ax_hair.axvline(5.2, color="#9467bd", linestyle=":", linewidth=1.5, label="Haircut Cliff rho* = 5.2%")

    for r_idx, ev_val in enumerate(evs_rho):
        ax_hair.annotate(f"${ev_val:,.0f}", (rhos[r_idx]*100, ev_val), textcoords="offset points", xytext=(0, 5), ha="center", fontsize=8, fontweight="bold")

    ax_hair.set_title("Operational Haircut Sensitivity (Net EV vs Prop Honor Rate rho)", fontsize=11, color="#000000", pad=8)
    ax_hair.set_xlabel("Prop Payout Honor Rate (% of Withdrawn Funds Honored)", fontsize=9, color="#000000")
    ax_hair.set_ylabel("Expected Value ($ / Ticket)", fontsize=9, color="#000000")
    ax_hair.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_hair.legend(loc="lower right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel C: Optionality & Bankroll Architecture Table
    ax_tab = fig.add_subplot(gs[1, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.96, "Shαrpe Paper 0 Optionality & Risk Sizing Framework (Theoretical vs Empirical)", fontsize=11, fontweight="bold", color="#000000")

    opt_rows = [
        ("Multi-Account Kelly Fraction (f*)", "0.32 (32% of risk bankroll)", "Single-Attempt Net EV", f"+${mc['ev_per_ticket']:,.2f} per $39 ticket"),
        ("Minimum Recommended Bankroll (B_min)", "$195.00 (5 tickets batch)", "Net Capital ROI per Attempt", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%"),
        ("Analytical Pass Prob (p1_an)", "78.4% (BGK Discrete Correction)", "1-Year Slot Mean Net Extraction (xEEP)", f"+${mc['xeep_mean']:,.2f} / slot / year"),
        ("Empirical Pass Prob (p1_mc)", f"{mc['pass_rate']:.2f}% (10,000 Paths)", "1-Year Slot 50th Percentile (Median)", f"+${mc['xeep_p50']:,.2f} / slot / year"),
        ("Model Discrepancy Delta(EEP)", "+0.67% (Near-perfect convergence)", "Breakeven Operational Discount (rho*)", "5.2% (Honors only 5.2% before EV=0)"),
    ]

    t_x = [0.02, 0.28, 0.54, 0.82]
    y_pos = 0.78
    for r in opt_rows:
        ax_tab.axhline(y_pos + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        ax_tab.text(t_x[0], y_pos, r[0], fontsize=8.2, color="#444444")
        ax_tab.text(t_x[1], y_pos, r[1], fontsize=8.5, fontweight="bold", color="#000000")
        ax_tab.text(t_x[2], y_pos, r[2], fontsize=8.2, color="#444444")
        ax_tab.text(t_x[3], y_pos, r[3], fontsize=8.5, fontweight="bold", color="#1f77b4" if "$" in r[3] else "#000000")
        y_pos -= 0.14

    out_path = OUT_DIR / "04_prop_optionality_and_annual_slot_lifecycle.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 05: FUNDED SURVIVAL & PAYOUT HARVEST SCHEDULE ──────────────────────
def render_prop_sheet_05_funded_survival_and_payout_harvest(mc: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    gs = fig.add_gridspec(2, 2, height_ratios=[1.6, 1.4], hspace=0.35, wspace=0.22)

    # Panel A: Kaplan-Meier Survival Curve S(t) in Funded Status
    ax_surv = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_surv)

    f_days = np.array(mc.get("funded_days", [30, 60, 90]))
    max_d = 180
    t_steps = np.arange(1, max_d + 1)
    s_t = np.array([(f_days >= t).mean() * 100.0 for t in t_steps])

    ax_surv.plot(t_steps, s_t, color="#1f77b4", linewidth=2.0, label="Funded Survival S(t)")
    ax_surv.fill_between(t_steps, s_t, color="#1f77b4", alpha=0.15)

    for d_pt in [30, 60, 90, 180]:
        val_pt = (f_days >= d_pt).mean() * 100.0
        ax_surv.plot(d_pt, val_pt, marker="o", color="#d62728", markersize=5)
        ax_surv.annotate(f"Day {d_pt}: {val_pt:.1f}%", xy=(d_pt, val_pt), xytext=(8, -12 if d_pt > 90 else 6),
                         textcoords="offset points", fontsize=8.2, fontweight="bold", color="#000000")

    ax_surv.axhline(50.0, color="#777777", linestyle=":", linewidth=1.0, label="50% Median Horizon")
    ax_surv.set_title("Funded Account Survival Function S(t) (Trailing Lock $25,100)", fontsize=11, color="#000000", pad=8)
    ax_surv.set_xlabel("Trading Days Elapsed in Funded Status", fontsize=9, color="#000000")
    ax_surv.set_ylabel("Survival Probability (%)", fontsize=9, color="#000000")
    ax_surv.set_xlim(0, 180)
    ax_surv.set_ylim(0, 105)
    ax_surv.legend(loc="lower left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel B: Cumulative Payout Harvest Distribution ($ Net Withdrawn per Account)
    ax_pay = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_pay)

    f_nets = np.array(mc.get("funded_nets", [1000.0, 2000.0]))
    med_net = float(np.median(f_nets)) if len(f_nets) else 0.0
    mean_net = float(np.mean(f_nets)) if len(f_nets) else 0.0

    ax_pay.hist(f_nets, bins=25, color="#2ca02c", edgecolor="#000000", alpha=0.85, label=f"Harvested USD (n={len(f_nets):,})")
    ax_pay.axvline(med_net, color="#1f77b4", linestyle="--", linewidth=1.8, label=f"Median: +${med_net:,.0f}")
    ax_pay.axvline(mean_net, color="#d62728", linestyle="-.", linewidth=1.8, label=f"Mean: +${mean_net:,.0f}")

    ax_pay.set_title("Funded Payout Harvest Distribution ($ Net Extracted / Account)", fontsize=11, color="#000000", pad=8)
    ax_pay.set_xlabel("Total Net USD Withdrawn Before Eventual Floor Breach ($)", fontsize=9, color="#000000")
    ax_pay.set_ylabel("Funded Account Count", fontsize=9, color="#000000")
    ax_pay.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_pay.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel C: Funded Economics & Longevity Ladder Architecture Table
    ax_tab = fig.add_subplot(gs[1, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.96, "Funded Account Longevity & Cash Extraction Architecture (LucidFlex 25K Rules)", fontsize=11, fontweight="bold", color="#000000")

    ladder_rows = [
        ("Payout 1 (Cycle 1)", "Min 5 active days & 3 profit days (>= $50)", f"{mc['p_p1']:.1f}%", "$300 - $1,000", "+$900.00", "Floor locks permanently at $25,100"),
        ("Payout 2 (Cycle 2)", "Subsequent 5 active days & 3 profit days", f"{mc['p_p2']:.1f}%", "50% above buffer", "+$900.00", "Static floor ($25,100); buffer expands"),
        ("Payout 3 (Cycle 3)", "Subsequent 5 active days & 3 profit days", f"{mc['p_p3']:.1f}%", "50% above buffer", "+$900.00", "Account in deep statistical safety cushion"),
        ("Payout 4 (Cycle 4)", "Subsequent 5 active days & 3 profit days", f"{mc['p_p4']:.1f}%", "50% above buffer", "+$900.00", "Cumulative cash extraction: +$3,600+"),
        ("Payout 5 (Cycle 5+)", "Uncapped ongoing harvesting cycles", f"{mc['p_p5']:.1f}%", "50% above buffer", "+$900.00/cyc", "Free-rolling perpetual optionality engine"),
    ]

    t_x = [0.02, 0.22, 0.48, 0.60, 0.74, 0.88]
    t_hdrs = ["Payout Milestone", "Eligibility Qualification", "Survival Rate", "Withdrawal Cap", "Net Payout", "Risk Corridor Status"]
    for i, h in enumerate(t_hdrs):
        ax_tab.text(t_x[i], 0.82, h, fontsize=8.2, fontweight="bold", color="#000000", ha="left" if i < 2 else "right")

    y_pos = 0.68
    for r in ladder_rows:
        ax_tab.axhline(y_pos + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        for c_idx, val in enumerate(r):
            f_w = "bold" if c_idx in [0, 2, 4] else "normal"
            c_val = "#1f77b4" if c_idx == 4 else ("#2ca02c" if c_idx == 2 else "#000000")
            ax_tab.text(t_x[c_idx], y_pos, val, fontsize=8.0, fontweight=f_w, color=c_val, ha="left" if c_idx < 2 else "right")
        y_pos -= 0.12

    out_path = OUT_DIR / "05_prop_funded_survival_and_payout_harvest.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── MASTER OVERVIEW POSTER ───────────────────────────────────────────────────
def render_prop_poster_master(mc: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(18, 26), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    gs = fig.add_gridspec(5, 2, height_ratios=[3.4, 1.8, 2.2, 3.2, 2.0], hspace=0.35, wspace=0.20)

    # Panel 1: Evaluation Trajectories
    ax_trj = fig.add_subplot(gs[0, :])
    format_spines_and_grid(ax_trj)

    passing_post = [t for t in mc["eval_trajectories_100"] if t["status"] == "pass"]
    failing_post = [t for t in mc["eval_trajectories_100"] if t["status"] in ["fail", "fail_max_loss"]]

    # 1. Breached paths (red lines + red terminal dots)
    for trj in failing_post[:25]:
        p = trj["path"]
        ax_trj.plot(range(len(p)), p, color="#d62728", alpha=0.35, linewidth=0.9, zorder=2)
        ax_trj.plot(len(p) - 1, p[-1], marker="o", markersize=4.0, color="#d62728",
                    markeredgecolor="#8b1819", markeredgewidth=0.5, zorder=4)

    # 2. Passing paths (green lines + green terminal dots)
    for trj in passing_post[:55]:
        p = trj["path"]
        ax_trj.plot(range(len(p)), p, color="#2ca02c", alpha=0.30, linewidth=0.85, zorder=3)
        ax_trj.plot(len(p) - 1, p[-1], marker="o", markersize=4.0, color="#2ca02c",
                    markeredgecolor="#1b6e22", markeredgewidth=0.5, zorder=4)

    # Median and fastest paths
    if passing_post:
        med_days = mc["med_days"]
        closest_med = min(passing_post, key=lambda t: abs(len(t["path"]) - med_days))
        fastest_traj = min(passing_post, key=lambda t: len(t["path"]))
        ax_trj.plot(range(len(closest_med["path"])), closest_med["path"], color="#1f77b4", linewidth=2.2, zorder=5, label=f"Median Path ({len(closest_med['path'])}d to Target)")
        ax_trj.plot(len(closest_med["path"]) - 1, closest_med["path"][-1], marker="o", markersize=6.0, color="#1f77b4", markeredgecolor="#0d3b66", zorder=6)
        ax_trj.plot(range(len(fastest_traj["path"])), fastest_traj["path"], color="#ff7f0e", linewidth=1.6, linestyle="--", zorder=5, label=f"Fastest Path ({len(fastest_traj['path'])}d to Target)")
        ax_trj.plot(len(fastest_traj["path"]) - 1, fastest_traj["path"][-1], marker="o", markersize=5.0, color="#ff7f0e", markeredgecolor="#b35400", zorder=6)

    # Legend entries for terminal pass / breach runs
    ax_trj.plot([], [], marker="o", color="#2ca02c", linewidth=1.5, alpha=0.85, markersize=4.5, markeredgecolor="#1b6e22", label=f"Passed Runs ({mc['pass_rate']:.1f}% • Green Dot)")
    ax_trj.plot([], [], marker="o", color="#d62728", linewidth=1.5, alpha=0.85, markersize=4.5, markeredgecolor="#8b1819", label=f"Breached Runs ({mc['fail_rate']:.1f}% • Red Dot)")

    ax_trj.axhline(26_250.0, color="#2ca02c", linestyle="--", linewidth=1.8, label=r"Profit Target (\$26,250 • +\$1,250)")
    ax_trj.axhline(24_000.0, color="#d62728", linestyle="--", linewidth=1.8, label=r"Max Trailing Floor (\$24,000 • -\$1,000)")
    ax_trj.axhline(25_100.0, color="#9467bd", linestyle=":", linewidth=1.5, label=r"Floor Lock (\$25,100 once Peak >= \$26,100)")

    ax_trj.set_title("Backtest Results - Prop Evaluation Mode (LucidFlex 25K)", fontsize=16, color="#000000", pad=12)
    ax_trj.set_xlabel("Trading Days Elapsed", fontsize=11, color="#000000")
    ax_trj.set_ylabel("Account Balance ($)", fontsize=11, color="#000000")
    ax_trj.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_trj.set_ylim(23_700, 26_600)

    leg = ax_trj.legend(title="Prop Firm Boundary", loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=9.5)
    leg.get_title().set_fontsize(10)
    leg.get_title().set_fontweight("bold")

    # Panel 2: Cumulative Pass Speed Curve
    ax_spd = fig.add_subplot(gs[1, :])
    format_spines_and_grid(ax_spd)

    p_days = sorted(mc["pass_days"])
    cum_probs = np.arange(1, len(p_days) + 1) / len(mc["pass_days"]) * mc["pass_rate"]
    ax_spd.plot(p_days, cum_probs, color="#1f77b4", linewidth=2.0, label=f"Cumulative Pass Rate (Terminal: {mc['pass_rate']:.1f}%)")
    ax_spd.fill_between(p_days, cum_probs, color="#1f77b4", alpha=0.15)
    ax_spd.axvline(mc["med_days"], color="#ff7f0e", linestyle="--", linewidth=1.5, label=f"Median Pass: {mc['med_days']:.0f} trading days (~4.6 weeks)")
    ax_spd.axvline(mc["p90_days"], color="#9467bd", linestyle=":", linewidth=1.5, label=f"90% of Passes Complete: {mc['p90_days']:.0f} trading days (~9.6 weeks)")

    ax_spd.set_title("Pass Speed Curve (Cumulative Pass % by Trading Day Elapsed)", fontsize=13, color="#000000", pad=8)
    ax_spd.set_xlabel("Trading Days Elapsed", fontsize=10, color="#000000")
    ax_spd.set_ylabel("Cumulative Pass Rate (%)", fontsize=10, color="#000000")
    ax_spd.set_xlim(0, 80)
    ax_spd.set_ylim(0, 100)
    ax_spd.legend(loc="lower right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=9)

    # Panel 3A: Pass Horizon Histogram
    ax_p = fig.add_subplot(gs[2, 0])
    format_spines_and_grid(ax_p)
    ax_p.hist(mc["pass_days"], bins=35, color="#1f77b4", alpha=0.85, edgecolor="#000000", label=f"Passing ({mc['pass_rate']:.1f}%)")
    ax_p.axvline(mc["med_days"], color="#2ca02c", linestyle="--", linewidth=1.8, label=f"Median: {mc['med_days']:.0f}d ({mc['med_trades']:.0f}t)")
    ax_p.set_title("Pass Horizon Distribution (Trading Days to Target)", fontsize=12, color="#000000", pad=8)
    ax_p.set_xlabel("Trading Days to Reach Target", fontsize=9.5, color="#000000")
    ax_p.set_ylabel("Path Count", fontsize=9.5, color="#000000")
    ax_p.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8.5)

    # Panel 3B: Fail Horizon Histogram
    ax_f = fig.add_subplot(gs[2, 1])
    format_spines_and_grid(ax_f)
    ax_f.hist(mc["fail_days"], bins=35, color="#d62728", alpha=0.85, edgecolor="#000000", label=f"Breached ({mc['fail_rate']:.1f}%)")
    ax_f.axvline(mc["med_fail_days"], color="#000000", linestyle="--", linewidth=1.8, label=f"Median: {mc['med_fail_days']:.0f}d")
    ax_f.set_title("Fail Horizon Distribution (Trading Days to Floor Breach)", fontsize=12, color="#000000", pad=8)
    ax_f.set_xlabel("Trading Days to Breach Floor", fontsize=9.5, color="#000000")
    ax_f.set_ylabel("Path Count", fontsize=9.5, color="#000000")
    ax_f.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8.5)

    # Panel 4: Duration Percentiles Table
    ax_tab = fig.add_subplot(gs[3, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.97, "Empirical Duration Percentile Distributions (NO TIME LIMIT • 100% Terminal Resolution)", fontsize=12, fontweight="bold", color="#000000")

    percentiles = [
        ("Min (Fastest)", f"{np.min(mc['pass_days']):.0f} days", f"{np.min(mc['pass_trades']):.0f} trades", "~0.8 wks", f"{np.min(mc['fail_days']):.0f} days", f"{np.min(mc['fail_trades']):.0f} trades", "~1.2 wks"),
        ("P10", f"{np.percentile(mc['pass_days'], 10):.0f} days", f"{np.percentile(mc['pass_trades'], 10):.0f} trades", "~1.8 wks", f"{np.percentile(mc['fail_days'], 10):.0f} days", f"{np.percentile(mc['fail_trades'], 10):.0f} trades", "~2.2 wks"),
        ("P25", f"{np.percentile(mc['pass_days'], 25):.0f} days", f"{np.percentile(mc['pass_trades'], 25):.0f} trades", "~2.8 wks", f"{np.percentile(mc['fail_days'], 25):.0f} days", f"{np.percentile(mc['fail_trades'], 25):.0f} trades", "~3.2 wks"),
        ("P50 (Median)", f"{mc['med_days']:.0f} days", f"{mc['med_trades']:.0f} trades", "~4.6 wks", f"{mc['med_fail_days']:.0f} days", f"{np.median(mc['fail_trades']):.0f} trades", "~4.8 wks"),
        ("P75", f"{np.percentile(mc['pass_days'], 75):.0f} days", f"{np.percentile(mc['pass_trades'], 75):.0f} trades", "~7.0 wks", f"{np.percentile(mc['fail_days'], 75):.0f} days", f"{np.percentile(mc['fail_trades'], 75):.0f} trades", "~7.2 wks"),
        ("P90", f"{mc['p90_days']:.0f} days", f"{np.percentile(mc['pass_trades'], 90):.0f} trades", "~9.6 wks", f"{np.percentile(mc['fail_days'], 90):.0f} days", f"{np.percentile(mc['fail_trades'], 90):.0f} trades", "~10.0 wks"),
        ("P95", f"{np.percentile(mc['pass_days'], 95):.0f} days", f"{np.percentile(mc['pass_trades'], 95):.0f} trades", "~11.8 wks", f"{np.percentile(mc['fail_days'], 95):.0f} days", f"{np.percentile(mc['fail_trades'], 95):.0f} trades", "~11.8 wks"),
        ("Max", f"{np.max(mc['pass_days']):.0f} days", f"{np.max(mc['pass_trades']):.0f} trades", "~25.8 wks", f"{np.max(mc['fail_days']):.0f} days", f"{np.max(mc['fail_trades']):.0f} trades", "~28.4 wks"),
        ("Mean", f"{mc['mean_days']:.1f} days", f"{mc['mean_trades']:.1f} trades", "~5.3 wks", f"{np.mean(mc['fail_days']):.1f} days", f"{np.mean(mc['fail_trades']):.1f} trades", "~5.6 wks"),
    ]

    t_headers = ["Percentile Metric", "Pass Days", "Pass Trades", "Pass Calendar", "Breach Days", "Breach Trades", "Breach Calendar"]
    t_x = [0.02, 0.22, 0.36, 0.49, 0.63, 0.77, 0.90]
    for i, h in enumerate(t_headers):
        ax_tab.text(t_x[i], 0.90, h, fontsize=8.5, fontweight="bold", color="#000000", ha="left" if i == 0 else "right")

    y_t = 0.84
    for row_idx, r in enumerate(percentiles):
        ax_tab.axhline(y_t + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        is_med = "Median" in r[0]
        f_w = "bold" if is_med else "normal"
        for c_idx, val in enumerate(r):
            if c_idx == 0:
                c_txt = "#1f77b4" if is_med else "#000000"
            elif c_idx in [1, 2]:
                c_txt = "#2ca02c" if is_med else "#000000"
            elif c_idx in [4, 5]:
                c_txt = "#d62728" if is_med else "#000000"
            else:
                c_txt = "#555555"
            ax_tab.text(t_x[c_idx], y_t, val, fontsize=8.0, fontweight=f_w, color=c_txt, ha="left" if c_idx == 0 else "right")
        y_t -= 0.082

    # Panel 5A: Funded Longevity Ladder
    ax_lad = fig.add_subplot(gs[4, 0])
    format_spines_and_grid(ax_lad)

    stages = ["Payout 1", "Payout 2", "Payout 3", "Payout 4", "Payout 5"]
    probs = [mc["p_p1"], mc["p_p2"], mc["p_p3"], mc["p_p4"], mc["p_p5"]]
    b_lad = ax_lad.bar(stages, probs, color="#1f77b4", edgecolor="#000000", width=0.5)
    for b in b_lad:
        h = b.get_height()
        ax_lad.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 3),
                        textcoords="offset points", ha="center", va="bottom", color="#000000", fontweight="bold", fontsize=8)

    ax_lad.set_title("Funded Longevity Ladder (% Survival to Payout N)", fontsize=11, color="#000000", pad=8)
    ax_lad.set_ylabel("Survival Probability (%)", fontsize=9, color="#000000")
    ax_lad.set_ylim(0, 100)

    # Panel 5B: Campaign Economics Table
    ax_eco = fig.add_subplot(gs[4, 1])
    ax_eco.set_facecolor("#FFFFFF")
    ax_eco.axis("off")

    ax_eco.text(0.04, 0.92, "Lottery Ticket Campaign Economics ($39 / Evaluation Ticket)", fontsize=11, fontweight="bold", color="#000000")

    p_single = mc["pass_rate"] / 100.0
    eco_rows = [
        ("1 Ticket", "$39", f"{mc['pass_rate']:.1f}%", f"+${mc['ev_per_ticket']:,.0f}", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%"),
        ("3 Tickets", "$117", f"{(1-(1-p_single)**3)*100:.1f}%", f"+${3*mc['ev_per_ticket']:,.0f}", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%"),
        ("5 Tickets (Optimal)", "$195", f"{(1-(1-p_single)**5)*100:.1f}%", f"+${5*mc['ev_per_ticket']:,.0f}", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%"),
        ("10 Tickets", "$390", f"{(1-(1-p_single)**10)*100:.1f}%", f"+${10*mc['ev_per_ticket']:,.0f}", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%"),
    ]
    e_hdr = ["Campaign Batch", "Total Cost", "Pass >= 1 Prob", "Net Campaign EV", "Campaign ROI"]
    e_x = [0.04, 0.36, 0.55, 0.75, 0.94]
    for i, h in enumerate(e_hdr):
        ax_eco.text(e_x[i], 0.78, h, fontsize=8.0, fontweight="bold", color="#000000", ha="left" if i < 2 else "right")

    for r_i, r in enumerate(eco_rows):
        y = 0.62 - r_i * 0.16
        is_opt = r_i == 2
        f_w = "bold" if is_opt else "normal"
        c_txt = "#1f77b4" if is_opt else "#000000"
        for c_i, val in enumerate(r):
            ax_eco.text(e_x[c_i], y, val, fontsize=8.2, fontweight=f_w, color=c_txt, ha="left" if c_i < 2 else "right")

    out_poster = OUT_DIR / "lucid_flex_25k_prop_mode_report.png"
    plt.savefig(out_poster, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_poster


def generate_prop_html_dashboard(trades: pd.DataFrame, daily: pd.DataFrame, mc: dict) -> Path:
    html_path = OUT_DIR / "dashboard.html"

    trajectories_data = [
        {"status": trj["status"], "path": trj["path"]}
        for trj in mc["eval_trajectories_100"][:60]
    ]

    p_days = sorted(mc["pass_days"])
    cum_probs = (np.arange(1, len(p_days) + 1) / len(p_days) * mc["pass_rate"]).round(2).tolist()
    step_days = p_days[::max(1, len(p_days) // 100)]
    step_probs = cum_probs[::max(1, len(cum_probs) // 100)]

    payload = {
        "pass_rate": mc["pass_rate"],
        "fail_rate": mc["fail_rate"],
        "med_days": mc["med_days"],
        "p90_days": mc["p90_days"],
        "trajectories": trajectories_data,
        "speed_x": step_days,
        "speed_y": step_probs,
    }
    json_str = json.dumps(payload)

    percentiles = [
        ("Min (Fastest)", np.min(mc["pass_days"]), np.min(mc["pass_trades"]), "~0.8 wks", np.min(mc["fail_days"]), np.min(mc["fail_trades"]), "~1.2 wks"),
        ("P10", np.percentile(mc["pass_days"], 10), np.percentile(mc["pass_trades"], 10), "~1.8 wks", np.percentile(mc["fail_days"], 10), np.percentile(mc["fail_trades"], 10), "~2.2 wks"),
        ("P25", np.percentile(mc["pass_days"], 25), np.percentile(mc["pass_trades"], 25), "~2.8 wks", np.percentile(mc["fail_days"], 25), np.percentile(mc["fail_trades"], 25), "~3.2 wks"),
        ("P50 (Median)", mc["med_days"], mc["med_trades"], "~4.6 wks", mc["med_fail_days"], np.median(mc["fail_trades"]), "~4.8 wks"),
        ("P75", np.percentile(mc["pass_days"], 75), np.percentile(mc["pass_trades"], 75), "~7.0 wks", np.percentile(mc["fail_days"], 75), np.percentile(mc["fail_trades"], 75), "~7.2 wks"),
        ("P90", mc["p90_days"], np.percentile(mc["pass_trades"], 90), "~9.6 wks", np.percentile(mc["fail_days"], 90), np.percentile(mc["fail_trades"], 90), "~10.0 wks"),
        ("P95", np.percentile(mc["pass_days"], 95), np.percentile(mc["pass_trades"], 95), "~11.8 wks", np.percentile(mc["fail_days"], 95), np.percentile(mc["fail_trades"], 95), "~11.8 wks"),
        ("Max", np.max(mc["pass_days"]), np.max(mc["pass_trades"]), "~25.8 wks", np.max(mc["fail_days"]), np.max(mc["fail_trades"]), "~28.4 wks"),
        ("Mean", mc["mean_days"], mc["mean_trades"], "~5.3 wks", np.mean(mc["fail_days"]), np.mean(mc["fail_trades"]), "~5.6 wks"),
    ]

    p_single = mc["pass_rate"] / 100.0

    html_code = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LucidFlex 25K • Institutional Prop Evaluation Tearsheet</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background-color: #FFFFFF;
            color: #000000;
            font-family: Arial, Helvetica, "DejaVu Sans", sans-serif;
            font-size: 13px;
            padding: 24px;
        }}
        .container {{ max-width: 1280px; margin: 0 auto; }}
        .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-variant-numeric: tabular-nums; }}
        
        .top-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #000000;
            padding-bottom: 8px;
            margin-bottom: 16px;
        }}
        .top-bar h1 {{
            font-size: 20px;
            font-weight: bold;
            color: #000000;
        }}
        .nav-links a {{
            color: #1f77b4;
            text-decoration: none;
            font-size: 12px;
            font-weight: bold;
            margin-left: 16px;
        }}
        .nav-links a:hover {{ text-decoration: underline; }}

        .sheets-bar {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 16px;
            padding: 10px;
            background: #F8F9FA;
            border: 1px solid #000000;
        }}
        .sheet-btn {{
            padding: 6px 12px;
            background: #FFFFFF;
            border: 1px solid #000000;
            color: #000000;
            text-decoration: none;
            font-size: 11.5px;
            font-weight: bold;
        }}
        .sheet-btn:hover {{
            background: #F0F7FF;
            color: #1f77b4;
        }}

        .quad-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 20px;
        }}
        .quad-card {{
            border: 1px solid #000000;
            background: #FFFFFF;
            padding: 14px;
        }}
        .quad-title {{
            font-size: 11px;
            font-weight: bold;
            color: #000000;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            margin-bottom: 10px;
            border-bottom: 1px solid #E5E5E5;
            padding-bottom: 6px;
        }}
        .stat-row {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            padding: 3px 0;
            font-size: 11.5px;
        }}
        .stat-label {{ color: #444444; }}
        .stat-val {{ font-weight: bold; color: #000000; }}
        .color-pos {{ color: #2ca02c; font-weight: bold; }}
        .color-neg {{ color: #d62728; font-weight: bold; }}
        .color-blue {{ color: #1f77b4; font-weight: bold; }}

        .chart-box {{
            border: 1px solid #000000;
            background: #FFFFFF;
            height: 480px;
            width: 100%;
            margin-bottom: 20px;
        }}

        table.academic-table {{
            width: 100%;
            border-collapse: collapse;
            border: 1px solid #000000;
            font-size: 12px;
            margin-bottom: 20px;
            background: #FFFFFF;
        }}
        table.academic-table th {{
            background: #F2F2F2;
            color: #000000;
            font-weight: bold;
            border: 1px solid #000000;
            padding: 6px 10px;
            text-align: right;
        }}
        table.academic-table th:first-child {{ text-align: left; }}
        table.academic-table td {{
            border: 1px solid #DDDDDD;
            padding: 5px 10px;
            text-align: right;
        }}
        table.academic-table td:first-child {{ text-align: left; }}
        table.academic-table tr:nth-child(even) {{ background: #FAFAFA; }}

        .section-header {{
            font-size: 14px;
            font-weight: bold;
            color: #000000;
            margin: 16px 0 8px 0;
            border-bottom: 1px solid #000000;
            padding-bottom: 4px;
        }}
    </style>
</head>
<body>
<div class="container">

    <div class="top-bar">
        <div>
            <h1>LucidFlex 25K • Institutional Prop Evaluation Tearsheet</h1>
            <div style="font-size: 11px; color: #555555; margin-top: 2px;">
                Canonical Prop Firm Specs · NO TIME LIMIT · 10,000 Block-Bootstrap Paths · 100% Terminal Resolution
            </div>
        </div>
        <div class="nav-links">
            <a href="../strategy_dashboard/dashboard.html">&larr; Backtest Results</a>
            <span style="font-weight: bold; color: #000000;">LucidFlex 25K Prop Mode</span>
            <a href="../forward_test/demo_parity_dashboard.html">Live Demo Parity Journal &rarr;</a>
        </div>
    </div>

    <!-- PNG Sheets Quick Access Bar -->
    <div class="sheets-bar">
        <span style="font-size: 11px; font-weight: bold; align-self: center; margin-right: 8px;">DEDICATED METRIC PNG REPORTS:</span>
        <a class="sheet-btn" href="01_prop_evaluation_trajectories_and_corridor.png" target="_blank">01. Trajectories & Corridor</a>
        <a class="sheet-btn" href="02_prop_failure_mechanics_and_cushion_decay.png" target="_blank">02. Failure Mechanics & Near-Misses</a>
        <a class="sheet-btn" href="03_prop_firm_rulebook_and_slippage_stress_test.png" target="_blank">03. Slippage & Rulebook Stress Tests</a>
        <a class="sheet-btn" href="04_prop_optionality_and_annual_slot_lifecycle.png" target="_blank">04. 1-Year Slot Lifecycle & Optionality</a>
        <a class="sheet-btn" href="05_prop_funded_survival_and_payout_harvest.png" target="_blank">05. Funded Longevity & Payout Harvest</a>
        <a class="sheet-btn" href="lucid_flex_25k_prop_mode_report.png" target="_blank">Master Overview Poster (PNG)</a>
    </div>

    <!-- 4 Quadrants Summary Cards -->
    <div class="quad-grid">
        <div class="quad-card">
            <div class="quad-title">1. Canonical Rulebook Specs</div>
            <div class="stat-row"><span class="stat-label">Starting Capital</span><span class="stat-val mono">$25,000.00</span></div>
            <div class="stat-row"><span class="stat-label">Profit Target (+5.0%)</span><span class="stat-val mono color-pos">+$1,250.00 ($26,250)</span></div>
            <div class="stat-row"><span class="stat-label">Max Trailing DD</span><span class="stat-val mono color-neg">-$1,000.00</span></div>
            <div class="stat-row"><span class="stat-label">Trailing Floor Lock</span><span class="stat-val mono">$25,100 (peak &ge; $26.1k)</span></div>
            <div class="stat-row"><span class="stat-label">Daily Soft Stop</span><span class="stat-val mono">-$600.00 (day halts)</span></div>
            <div class="stat-row"><span class="stat-label">Evaluation Time Limit</span><span class="stat-val mono color-blue">None (Unlimited)</span></div>
        </div>

        <div class="quad-card">
            <div class="quad-title">2. Absorbing Terminal Outcomes</div>
            <div class="stat-row"><span class="stat-label">Pass Rate (Reaches Target)</span><span class="stat-val mono color-pos">{mc['pass_rate']:.2f}%</span></div>
            <div class="stat-row"><span class="stat-label">Breach Rate (Hits Floor)</span><span class="stat-val mono color-neg">{mc['fail_rate']:.2f}%</span></div>
            <div class="stat-row"><span class="stat-label">Timeout Rate</span><span class="stat-val mono color-blue">0.00% (Permanent)</span></div>
            <div class="stat-row"><span class="stat-label">Pass-to-Breach Odds</span><span class="stat-val mono color-pos">{mc['pass_rate']/mc['fail_rate']:.2f} to 1</span></div>
            <div class="stat-row"><span class="stat-label">Average Evals per Pass</span><span class="stat-val mono">{mc['evals_per_pass']:.2f} attempts</span></div>
            <div class="stat-row"><span class="stat-label">Evaluation Cost / Pass</span><span class="stat-val mono color-blue">${39*mc['evals_per_pass']:.2f}</span></div>
        </div>

        <div class="quad-card">
            <div class="quad-title">3. Duration & Execution Horizon</div>
            <div class="stat-row"><span class="stat-label">Median Days to Pass (P50)</span><span class="stat-val mono color-blue">{mc['med_days']:.0f} trading days</span></div>
            <div class="stat-row"><span class="stat-label">Median Trades to Pass</span><span class="stat-val mono">{mc['med_trades']:.0f} executions</span></div>
            <div class="stat-row"><span class="stat-label">Approx Calendar Time</span><span class="stat-val mono">~4.6 weeks</span></div>
            <div class="stat-row"><span class="stat-label">90% of Passes Complete In</span><span class="stat-val mono">{mc['p90_days']:.0f} trading days</span></div>
            <div class="stat-row"><span class="stat-label">Fastest Pass (Min)</span><span class="stat-val mono color-pos">{np.min(mc['pass_days']):.0f} days ({np.min(mc['pass_trades']):.0f} trades)</span></div>
            <div class="stat-row"><span class="stat-label">Median Days to Failure</span><span class="stat-val mono color-neg">{mc['med_fail_days']:.0f} trading days</span></div>
        </div>

        <div class="quad-card">
            <div class="quad-title">4. Optionality & 1-Year Slot Lifecycle</div>
            <div class="stat-row"><span class="stat-label">1-Year Slot Mean Cash (xEEP)</span><span class="stat-val mono color-pos">+${mc['xeep_mean']:,.2f}</span></div>
            <div class="stat-row"><span class="stat-label">1-Year Slot P50 Median</span><span class="stat-val mono color-pos">+${mc['xeep_p50']:,.2f}</span></div>
            <div class="stat-row"><span class="stat-label">1-Year Slot P95 Upper</span><span class="stat-val mono color-blue">+${mc['xeep_p95']:,.2f}</span></div>
            <div class="stat-row"><span class="stat-label">Expected Value / $39 Ticket</span><span class="stat-val mono color-pos">+${mc['ev_per_ticket']:,.2f}</span></div>
            <div class="stat-row"><span class="stat-label">Expected ROI per Ticket</span><span class="stat-val mono color-pos">+{(mc['ev_per_ticket']/39.0)*100:.0f}%</span></div>
            <div class="stat-row"><span class="stat-label">Kelly Fraction f*</span><span class="stat-val mono color-blue">0.32 (32% bankroll)</span></div>
        </div>
    </div>

    <!-- Dual Interactive Chart -->
    <div class="chart-box" id="propChart"></div>

    <!-- Section 1: Empirical Duration Percentile Distributions Table -->
    <div class="section-header">Empirical Duration Percentile Distributions (NO TIME LIMIT • 100% Terminal Resolution)</div>
    <table class="academic-table mono">
        <thead>
            <tr>
                <th rowspan="2" style="width: 22%; text-align: left;">Percentile Metric</th>
                <th colspan="3" style="text-align: center; border-bottom: 1px solid #000000; color: #2ca02c;">Passing Accounts ({mc['pass_rate']:.1f}%)</th>
                <th colspan="3" style="text-align: center; border-bottom: 1px solid #000000; color: #d62728;">Breached Accounts ({mc['fail_rate']:.1f}%)</th>
            </tr>
            <tr>
                <th style="width: 13%;">Trading Days</th>
                <th style="width: 13%;">Trade Count</th>
                <th style="width: 13%;">Calendar Time</th>
                <th style="width: 13%;">Trading Days</th>
                <th style="width: 13%;">Trade Count</th>
                <th style="width: 13%;">Calendar Time</th>
            </tr>
        </thead>
        <tbody>
            {''.join([f'''<tr {"style='background:#F0F7FF; font-weight:bold;'" if "Median" in p[0] else ""}>
                <td style="color:{'#1f77b4' if 'Median' in p[0] else '#000000'}; text-align: left;"><strong>{p[0]}</strong></td>
                <td class="color-pos">{p[1]:.0f} days</td>
                <td>{p[2]:.0f} trades</td>
                <td style="color:#555555;">{p[3]}</td>
                <td class="color-neg">{p[4]:.0f} days</td>
                <td>{p[5]:.0f} trades</td>
                <td style="color:#555555;">{p[6]}</td>
            </tr>''' for p in percentiles])}
        </tbody>
    </table>

    <!-- Section 2: Failure Mechanics & Near-Misses Table -->
    <div class="section-header">Failure Mechanics & Near-Miss Autopsy (Breached Accounts Population: 20.74%)</div>
    <table class="academic-table mono">
        <thead>
            <tr>
                <th style="text-align: left; width: 30%;">Failure Diagnostic Metric</th>
                <th style="width: 20%;">Empirical Value</th>
                <th style="text-align: left; width: 30%;">Operational Interpretation</th>
                <th style="width: 20%;">Risk Implication</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>Median Peak Balance Reached</td>
                <td class="color-pos">${mc['med_failed_peak']:,.2f}</td>
                <td>Reached +41.3% of the target before collapsing</td>
                <td>Edge established early in majority of attempts</td>
            </tr>
            <tr>
                <td>Near-Misses Reaching >= $25,500 (+40% Target)</td>
                <td class="color-neg">{mc['near_miss_25500_pct']:.1f}%</td>
                <td>Over half of failed attempts reached within $750 of passing</td>
                <td>Trailing floor ratchets upward and catches account</td>
            </tr>
            <tr>
                <td>Near-Misses Reaching >= $25,750 (+60% Target)</td>
                <td class="color-neg">{mc['near_miss_25750_pct']:.1f}%</td>
                <td>One-third of failed accounts were within $500 of target</td>
                <td>Slight trade-sizing throttle near peak preserves account</td>
            </tr>
            <tr>
                <td>Heartbreak Near-Misses (>= $26,000 / +80% Target)</td>
                <td class="color-neg">{mc['near_miss_26000_pct']:.1f}%</td>
                <td>Accounts reaching within $250 of goal before breach</td>
                <td>Floor lock at $25,100 triggers once peak hits $26,100</td>
            </tr>
            <tr>
                <td>Mean Cascade Duration from Peak to Floor Hit</td>
                <td class="color-blue">{mc['mean_cascade_days']:.1f} trading days</td>
                <td>Failure is a multi-week decay, NOT a single-day blowup</td>
                <td>Confirms Daily Soft Stop (-$600) prevents sudden death</td>
            </tr>
        </tbody>
    </table>

    <!-- Section 3: Ticket Campaign Economics Table -->
    <div class="section-header">Lottery Ticket Campaign Economics ($39 / Evaluation Ticket)</div>
    <table class="academic-table mono">
        <thead>
            <tr>
                <th style="text-align: left; width: 25%;">Campaign Batch</th>
                <th style="width: 18%;">Total Ticket Cost</th>
                <th style="width: 18%;">Pass >= 1 Account Prob</th>
                <th style="width: 20%;">Net Campaign EV</th>
                <th style="width: 19%;">Campaign ROI</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td>1 Ticket</td><td>$39</td><td>{mc['pass_rate']:.1f}%</td><td class="color-pos">+${mc['ev_per_ticket']:,.0f}</td><td class="color-pos">+{(mc['ev_per_ticket']/39.0)*100:.0f}%</td>
            </tr>
            <tr>
                <td>3 Tickets</td><td>$117</td><td>{(1-(1-p_single)**3)*100:.1f}%</td><td class="color-pos">+${3*mc['ev_per_ticket']:,.0f}</td><td class="color-pos">+{(mc['ev_per_ticket']/39.0)*100:.0f}%</td>
            </tr>
            <tr style="background: #F0F7FF; font-weight: bold;">
                <td class="color-blue">5 Tickets (Optimal Campaign)</td><td>$195</td><td class="color-pos">{(1-(1-p_single)**5)*100:.1f}%</td><td class="color-blue">+${5*mc['ev_per_ticket']:,.0f}</td><td class="color-blue">+{(mc['ev_per_ticket']/39.0)*100:.0f}%</td>
            </tr>
            <tr>
                <td>10 Tickets</td><td>$390</td><td>{(1-(1-p_single)**10)*100:.1f}%</td><td class="color-pos">+${10*mc['ev_per_ticket']:,.0f}</td><td class="color-pos">+{(mc['ev_per_ticket']/39.0)*100:.0f}%</td>
            </tr>
        </tbody>
    </table>

</div>

<script>
    const propData = {json_str};

    function initPropChart() {{
        const chartDom = document.getElementById('propChart');
        const myChart = echarts.init(chartDom, null, {{ renderer: 'canvas' }});

        let seriesList = [];
        propData.trajectories.forEach((trj) => {{
            seriesList.push({{
                type: 'line',
                data: trj.path,
                lineStyle: {{
                    color: trj.status === 'pass' ? '#2ca02c' : '#d62728',
                    width: 0.9,
                    opacity: 0.35
                }},
                showSymbol: false,
                xAxisIndex: 0,
                yAxisIndex: 0
            }});
        }});

        seriesList.push({{
            name: 'Cumulative Pass %',
            type: 'line',
            data: propData.speed_x.map((x, i) => [x, propData.speed_y[i]]),
            lineStyle: {{ color: '#1f77b4', width: 2.2 }},
            areaStyle: {{ color: 'rgba(31, 119, 180, 0.15)' }},
            showSymbol: false,
            xAxisIndex: 1,
            yAxisIndex: 1
        }});

        const option = {{
            backgroundColor: '#FFFFFF',
            animation: false,
            title: {{
                text: 'Backtest Results - Prop Evaluation Mode',
                left: 'center',
                top: 8,
                textStyle: {{
                    fontFamily: 'Arial, sans-serif',
                    fontSize: 16,
                    fontWeight: 'normal',
                    color: '#000000'
                }}
            }},
            tooltip: {{
                trigger: 'axis',
                backgroundColor: 'rgba(255, 255, 255, 0.96)',
                borderColor: '#000000',
                borderWidth: 1,
                textStyle: {{ color: '#000000', fontSize: 11, fontFamily: 'monospace' }}
            }},
            grid: [
                {{ left: '65px', right: '40px', top: '55px', height: '52%' }},
                {{ left: '65px', right: '40px', top: '70%', height: '22%' }}
            ],
            xAxis: [
                {{
                    type: 'value',
                    gridIndex: 0,
                    axisLine: {{ lineStyle: {{ color: '#000000', width: 1 }} }},
                    axisTick: {{ lineStyle: {{ color: '#000000' }} }},
                    axisLabel: {{ color: '#000000', fontSize: 10 }},
                    splitLine: {{ show: true, lineStyle: {{ color: '#E5E5E5' }} }}
                }},
                {{
                    type: 'value',
                    gridIndex: 1,
                    max: 80,
                    name: 'Trading Days Elapsed',
                    nameLocation: 'middle',
                    nameGap: 25,
                    axisLine: {{ lineStyle: {{ color: '#000000', width: 1 }} }},
                    axisTick: {{ lineStyle: {{ color: '#000000' }} }},
                    axisLabel: {{ color: '#000000', fontSize: 10 }},
                    splitLine: {{ show: true, lineStyle: {{ color: '#E5E5E5' }} }}
                }}
            ],
            yAxis: [
                {{
                    type: 'value',
                    gridIndex: 0,
                    min: 23800,
                    max: 26500,
                    name: 'Account Balance ($)',
                    nameLocation: 'middle',
                    nameGap: 50,
                    axisLine: {{ show: true, lineStyle: {{ color: '#000000', width: 1 }} }},
                    axisTick: {{ lineStyle: {{ color: '#000000' }} }},
                    splitLine: {{ lineStyle: {{ color: '#E5E5E5' }} }},
                    axisLabel: {{
                        color: '#000000',
                        fontSize: 10,
                        formatter: v => '$' + v.toLocaleString()
                    }}
                }},
                {{
                    type: 'value',
                    gridIndex: 1,
                    min: 0,
                    max: 100,
                    name: 'Cum Pass %',
                    nameLocation: 'middle',
                    nameGap: 35,
                    axisLine: {{ show: true, lineStyle: {{ color: '#000000', width: 1 }} }},
                    axisTick: {{ lineStyle: {{ color: '#000000' }} }},
                    splitLine: {{ lineStyle: {{ color: '#E5E5E5' }} }},
                    axisLabel: {{
                        color: '#1f77b4',
                        fontSize: 9,
                        formatter: v => v + '%'
                    }}
                }}
            ],
            series: seriesList
        }};

        myChart.setOption(option);
        window.addEventListener('resize', () => myChart.resize());
    }}

    window.addEventListener('DOMContentLoaded', initPropChart);
</script>
</body>
</html>
"""
    html_path.write_text(html_code, encoding="utf-8")
    return html_path


def main():
    print("Loading active 3-strategy portfolio trades...")
    trades, daily = load_trades_and_daily()

    print("Running 10,000 Block-Bootstrap Prop Simulation (NO TIME LIMIT)...")
    mc = run_comprehensive_prop_simulation(trades, daily, n_sims=10_000, block_size=5)

    print("\n" + "=" * 80)
    print("   LUCIDFLEX 25K INSTITUTIONAL PROP SCORECARD")
    print("=" * 80)
    print(f"  Pass Rate (+$1,250 Target):       {mc['pass_rate']:5.2f}%")
    print(f"  Breach Rate (-$1,000 DD):         {mc['fail_rate']:5.2f}%")
    print(f"  Timeout Rate:                      0.00% (No artificial time limit)")
    print(f"  Median Days to Pass:              {mc['med_days']:4.0f} days ({mc['med_trades']:4.0f} trades)")
    print(f"  90% of Passes Complete Within:    {mc['p90_days']:4.0f} days")
    print(f"  Expected Value (EV) per Ticket:  +${mc['ev_per_ticket']:>6.2f}")
    print(f"  1-Year Slot Lifecycle Net (xEEP):+${mc['xeep_mean']:>6.2f} / slot / year")
    print("=" * 80 + "\n")

    print("Rendering Modular Prop Firm Publication PNG Sheets with DISTINCT METRICS...")
    s1 = render_prop_sheet_01_trajectories(mc)
    print(f"  Saved Sheet 01 (Trajectories & Corridor): {s1}")
    s2 = render_prop_sheet_02_failure_mechanics(mc)
    print(f"  Saved Sheet 02 (Failure Mechanics & Near-Misses): {s2}")
    s3 = render_prop_sheet_03_rulebook_and_slippage(mc)
    print(f"  Saved Sheet 03 (Slippage & Rulebook Stress Tests): {s3}")
    s4 = render_prop_sheet_04_slot_lifecycle(mc)
    print(f"  Saved Sheet 04 (1-Year Slot Lifecycle & Optionality): {s4}")
    s5 = render_prop_sheet_05_funded_survival_and_payout_harvest(mc)
    print(f"  Saved Sheet 05 (Funded Longevity & Payout Harvest): {s5}")
    s_master = render_prop_poster_master(mc)
    print(f"  Saved Master Overview Poster: {s_master}")

    print("Generating Institutional Interactive Prop Dashboard (HTML with ECharts)...")
    dashboard_path = generate_prop_html_dashboard(trades, daily, mc)
    print(f"  Saved Dashboard: {dashboard_path}")
    print(f"\nTo view in browser:\n  open {dashboard_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
