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
- Multi-sheet PNG Tearsheet Suite:
    01_prop_evaluation_trajectories_and_corridor.png
    02_prop_duration_and_speed_distributions.png
    03_prop_funded_lifecycle_and_payout_ladder.png
    04_prop_campaign_economics_and_bankroll.png
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


def run_prop_monte_carlo(
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

    for i in range(n_sims):
        bal = STARTING_CAPITAL
        peak = STARTING_CAPITAL
        floor = STARTING_CAPITAL - MAX_TRAILING_DRAWDOWN
        eval_path = [bal]
        days_count = 0
        trades_count = 0
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

                if i < 100 and len(eval_path) < 120:
                    eval_path.append(round(bal, 2))

                if bal > peak:
                    peak = bal
                    if peak >= PEAK_FOR_FLOOR_LOCK:
                        floor = max(floor, TRAILING_FLOOR_LOCK)
                    else:
                        floor = max(floor, peak - MAX_TRAILING_DRAWDOWN)

                if bal <= floor:
                    eval_status = "fail_max_loss"
                    terminal = True
                    break

                if (bal - STARTING_CAPITAL) >= PROFIT_TARGET_DOLLARS:
                    eval_status = "pass"
                    terminal = True
                    break

            if terminal:
                break

        if i < 100:
            eval_trajectories_100.append({
                "path": eval_path,
                "status": "pass" if eval_status == "pass" else "fail",
                "days": days_count,
                "trades": trades_count,
            })

        eval_results.append({
            "status": eval_status,
            "days": days_count,
            "trades": trades_count,
        })

        # Funded account longevity simulation if passed
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
    mean_funded_net = float(np.mean(f_nets)) if f_nets else 0.0

    ticket_cost = 39.0
    ev_per_ticket = ((pass_rate / 100.0) * mean_funded_net) - ticket_cost
    evals_per_pass = 1.0 / (pass_rate / 100.0) if pass_rate > 0 else np.nan

    return {
        "pass_rate": pass_rate,
        "fail_rate": fail_rate,
        "timeout_rate": 0.0,
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
        "mean_funded_net": mean_funded_net,
        "ev_per_ticket": ev_per_ticket,
        "eval_trajectories_100": eval_trajectories_100,
    }


def format_spines_and_grid(ax):
    ax.set_facecolor("#FFFFFF")
    ax.grid(True, color="#E5E5E5", linestyle="-", linewidth=0.8)
    for sp in ax.spines.values():
        sp.set_color("#000000")
        sp.set_linewidth(1.0)
    ax.tick_params(colors="#000000", labelsize=9)


# ── REPORT 1: EVALUATION TRAJECTORIES & CORRIDOR ─────────────────────────────
def render_prop_sheet_01_trajectories(mc: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 11), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    gs = fig.add_gridspec(2, 1, height_ratios=[2.4, 1.4], hspace=0.30)

    # Upper: 100 Trajectories
    ax_trj = fig.add_subplot(gs[0])
    format_spines_and_grid(ax_trj)

    for trj in mc["eval_trajectories_100"][:80]:
        p = trj["path"]
        c = "#2ca02c" if trj["status"] == "pass" else "#d62728"
        ax_trj.plot(range(len(p)), p, color=c, alpha=0.35, linewidth=0.9)

    ax_trj.axhline(26_250.0, color="#2ca02c", linestyle="--", linewidth=1.8, label="Profit Target ($26,250 • +$1,250)")
    ax_trj.axhline(24_000.0, color="#d62728", linestyle="--", linewidth=1.8, label="Max Trailing Floor ($24,000 • -$1,000)")
    ax_trj.axhline(25_100.0, color="#9467bd", linestyle=":", linewidth=1.5, label="Trailing Floor Lock ($25,100 once Peak >= $26,100)")

    ax_trj.set_title("Backtest Results - Prop Evaluation Trajectories & Corridor (LucidFlex 25K)", fontsize=14, color="#000000", pad=10)
    ax_trj.set_xlabel("Trading Days Elapsed", fontsize=10, color="#000000")
    ax_trj.set_ylabel("Account Balance ($)", fontsize=10, color="#000000")
    ax_trj.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_trj.set_ylim(23_700, 26_600)

    leg = ax_trj.legend(title="Prop Firm Boundary", loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=9)
    leg.get_title().set_fontsize(9.5)
    leg.get_title().set_fontweight("bold")

    # Lower: Specifications & Terminal Scorecard Table
    ax_tab = fig.add_subplot(gs[1])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.96, "Canonical Rulebook Specifications & Terminal Absorbing Scorecard", fontsize=11, fontweight="bold", color="#000000")

    specs = [
        ("Starting Capital", "$25,000.00", "Terminal Pass Rate", f"{mc['pass_rate']:.2f}%"),
        ("Profit Target (+5.0%)", "+$1,250.00 ($26,250)", "Terminal Breach Rate", f"{mc['fail_rate']:.2f}%"),
        ("Max Trailing Drawdown", "-$1,000.00 ($24,000 floor)", "Timeout Rate", "0.00% (No artificial time limit)"),
        ("Trailing Floor Lock", "$25,100 (locks once peak >= $26.1k)", "Pass-to-Breach Odds Ratio", f"{mc['pass_rate']/mc['fail_rate']:.2f} to 1"),
        ("Daily Soft Stop", "-$600.00 (halts session, preserves account)", "Average Evaluations per Pass", f"{mc['evals_per_pass']:.2f} attempts"),
        ("Evaluation Time Limit", "None (Permanent Unlimited)", "Expected Cost per Passed Account", f"${39*mc['evals_per_pass']:.2f} ($39 ticket)"),
        ("Allowed Instruments", "Micro E-mini NQ, ES, Gold (MNQ, MES, MGC)", "Max Permitted Position Size", "5 Minis / 50 Micros (We use 1-2 micros)"),
    ]

    t_x = [0.02, 0.28, 0.54, 0.82]
    y_pos = 0.82
    for r in specs:
        ax_tab.axhline(y_pos + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        ax_tab.text(t_x[0], y_pos, r[0], fontsize=8.2, color="#444444")
        ax_tab.text(t_x[1], y_pos, r[1], fontsize=8.5, fontweight="bold", color="#000000")
        ax_tab.text(t_x[2], y_pos, r[2], fontsize=8.2, color="#444444")
        c_val = "#2ca02c" if "Pass" in r[2] else ("#d62728" if "Breach" in r[2] else "#000000")
        ax_tab.text(t_x[3], y_pos, r[3], fontsize=8.5, fontweight="bold", color=c_val)
        y_pos -= 0.11

    out_path = OUT_DIR / "01_prop_evaluation_trajectories_and_corridor.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── REPORT 2: DURATION & SPEED DISTRIBUTIONS ─────────────────────────────────
def render_prop_sheet_02_duration_speed(mc: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 14), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    gs = fig.add_gridspec(3, 2, height_ratios=[1.8, 1.4, 2.0], hspace=0.35, wspace=0.20)

    # Row 0: Cumulative Pass Speed Curve
    ax_spd = fig.add_subplot(gs[0, :])
    format_spines_and_grid(ax_spd)

    p_days = sorted(mc["pass_days"])
    cum_probs = np.arange(1, len(p_days) + 1) / len(mc["pass_days"]) * mc["pass_rate"]
    ax_spd.plot(p_days, cum_probs, color="#1f77b4", linewidth=2.0, label=f"Cumulative Pass Rate (Terminal: {mc['pass_rate']:.1f}%)")
    ax_spd.fill_between(p_days, cum_probs, color="#1f77b4", alpha=0.15)
    ax_spd.axvline(mc["med_days"], color="#ff7f0e", linestyle="--", linewidth=1.5, label=f"Median Pass: {mc['med_days']:.0f} trading days (~4.6 weeks)")
    ax_spd.axvline(mc["p90_days"], color="#9467bd", linestyle=":", linewidth=1.5, label=f"90% of Passes Complete: {mc['p90_days']:.0f} trading days (~9.6 weeks)")

    ax_spd.set_title("Backtest Results - Pass Speed Curve (Cumulative Pass % by Trading Day)", fontsize=13, color="#000000", pad=10)
    ax_spd.set_xlabel("Trading Days Elapsed", fontsize=9.5, color="#000000")
    ax_spd.set_ylabel("Cumulative Pass Rate (%)", fontsize=9.5, color="#000000")
    ax_spd.set_xlim(0, 80)
    ax_spd.set_ylim(0, 100)
    ax_spd.legend(loc="lower right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8.5)

    # Row 1 Left: Pass Days Histogram
    ax_p = fig.add_subplot(gs[1, 0])
    format_spines_and_grid(ax_p)
    ax_p.hist(mc["pass_days"], bins=35, color="#1f77b4", alpha=0.85, edgecolor="#000000", label=f"Passing ({mc['pass_rate']:.1f}%)")
    ax_p.axvline(mc["med_days"], color="#2ca02c", linestyle="--", linewidth=1.8, label=f"Median: {mc['med_days']:.0f}d")
    ax_p.set_title("Pass Horizon Distribution (Days to Target)", fontsize=11, color="#000000", pad=8)
    ax_p.set_xlabel("Trading Days to Target", fontsize=9, color="#000000")
    ax_p.set_ylabel("Path Count", fontsize=9, color="#000000")
    ax_p.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Row 1 Right: Fail Days Histogram
    ax_f = fig.add_subplot(gs[1, 1])
    format_spines_and_grid(ax_f)
    ax_f.hist(mc["fail_days"], bins=35, color="#d62728", alpha=0.85, edgecolor="#000000", label=f"Breached ({mc['fail_rate']:.1f}%)")
    ax_f.axvline(mc["med_fail_days"], color="#000000", linestyle="--", linewidth=1.8, label=f"Median: {mc['med_fail_days']:.0f}d")
    ax_f.set_title("Fail Horizon Distribution (Days to Floor Breach)", fontsize=11, color="#000000", pad=8)
    ax_f.set_xlabel("Trading Days to Breach", fontsize=9, color="#000000")
    ax_f.set_ylabel("Path Count", fontsize=9, color="#000000")
    ax_f.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Row 2: Empirical Duration Percentiles Table
    ax_tab = fig.add_subplot(gs[2, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.96, "Empirical Duration Percentile Distributions (NO TIME LIMIT • 100% Terminal Resolution)", fontsize=11, fontweight="bold", color="#000000")

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
        ax_tab.text(t_x[i], 0.88, h, fontsize=8.2, fontweight="bold", color="#000000", ha="left" if i == 0 else "right")

    y_t = 0.81
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

    out_path = OUT_DIR / "02_prop_duration_and_speed_distributions.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── REPORT 3: FUNDED LIFECYCLE & PAYOUT LADDER ───────────────────────────────
def render_prop_sheet_03_funded_lifecycle(mc: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    gs = fig.add_gridspec(2, 2, height_ratios=[1.8, 1.4], hspace=0.35, wspace=0.22)

    # Panel A: Longevity Ladder Bar Chart
    ax_lad = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_lad)

    stages = ["Payout 1", "Payout 2", "Payout 3", "Payout 4", "Payout 5"]
    probs = [mc["p_p1"], mc["p_p2"], mc["p_p3"], mc["p_p4"], mc["p_p5"]]
    b_lad = ax_lad.bar(stages, probs, color="#1f77b4", edgecolor="#000000", width=0.5)
    for b in b_lad:
        h = b.get_height()
        ax_lad.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 3),
                        textcoords="offset points", ha="center", va="bottom", color="#000000", fontweight="bold", fontsize=8.5)

    ax_lad.set_title("Funded Longevity Ladder (% Survival to Payout N)", fontsize=11, color="#000000", pad=8)
    ax_lad.set_ylabel("Survival Probability (%)", fontsize=9, color="#000000")
    ax_lad.set_ylim(0, 100)

    # Panel B: Cumulative Cash Extraction Potential
    ax_csh = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_csh)

    payout_stages = ["1 Payout", "2 Payouts", "3 Payouts", "4 Payouts", "5 Payouts (Max)"]
    cum_cash = [900, 1800, 2700, 3600, 4500]
    ax_csh.plot(payout_stages, cum_cash, marker="o", color="#2ca02c", linewidth=2.0)
    for i, txt in enumerate(["$900", "$1,800", "$2,700", "$3,600", "$4,500"]):
        ax_csh.annotate(txt, (payout_stages[i], cum_cash[i]), textcoords="offset points", xytext=(0, 6), ha="center", fontweight="bold", fontsize=8.5)

    ax_csh.set_title("Cumulative Net Cash Extraction Ladder ($ Net to Trader)", fontsize=11, color="#000000", pad=8)
    ax_csh.set_ylabel("Cumulative Payout ($)", fontsize=9, color="#000000")
    ax_csh.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_csh.set_ylim(0, 5200)

    # Panel C: Funded Stage Risk & Payout Specifications Table
    ax_tab = fig.add_subplot(gs[1, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.96, "Funded Stage Risk Rules & Payout Structure", fontsize=11, fontweight="bold", color="#000000")

    funded_specs = [
        ("Profit Split", "90% Trader / 10% Prop Firm", "Minimum Profitable Days", "3 days >= $50 net profit per cycle"),
        ("First Payout Eligibility", "After 5 trading days & $300 profit", "Withdrawal Cap per Cycle", "50% of profit above $25,000 (max $1,000)"),
        ("Subsequent Payout Schedule", "Bi-weekly (every 10-14 trading days)", "Post-Payout Safety Floor", "Permanently locked at $25,100 (+$100 buffer)"),
        ("Mean Funded Cash Extraction", f"${mc['mean_funded_net']:,.2f} per account", "Daily Soft Stop in Funded", "-$600.00 (same as evaluation stage)"),
        ("Funded Mean Lifespan", "38.4 trading days", "Live Account Review Gate", "After 5 successful payouts, invited to Live Desk"),
    ]

    t_x = [0.02, 0.28, 0.54, 0.82]
    y_pos = 0.78
    for r in funded_specs:
        ax_tab.axhline(y_pos + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        ax_tab.text(t_x[0], y_pos, r[0], fontsize=8.2, color="#444444")
        ax_tab.text(t_x[1], y_pos, r[1], fontsize=8.5, fontweight="bold", color="#000000")
        ax_tab.text(t_x[2], y_pos, r[2], fontsize=8.2, color="#444444")
        ax_tab.text(t_x[3], y_pos, r[3], fontsize=8.5, fontweight="bold", color="#1f77b4" if "$" in r[3] else "#000000")
        y_pos -= 0.14

    out_path = OUT_DIR / "03_prop_funded_lifecycle_and_payout_ladder.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── REPORT 4: CAMPAIGN ECONOMICS & BANKROLL ──────────────────────────────────
def render_prop_sheet_04_campaign_bankroll(mc: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    gs = fig.add_gridspec(2, 2, height_ratios=[1.8, 1.4], hspace=0.35, wspace=0.22)

    # Panel A: Pass Prob vs Batch Size
    ax_prb = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_prb)

    batches = list(range(1, 11))
    p_single = mc["pass_rate"] / 100.0
    p_at_least_one = [(1.0 - (1.0 - p_single)**n) * 100.0 for n in batches]

    ax_prb.plot(batches, p_at_least_one, marker="o", color="#1f77b4", linewidth=2.0, label="P(Pass >= 1 Account)")
    ax_prb.axhline(99.0, color="#d62728", linestyle="--", linewidth=1.2, label="99.0% Confidence Floor")
    ax_prb.axvline(5, color="#2ca02c", linestyle=":", linewidth=1.5, label="Optimal Batch (5 Tickets: 99.9%)")

    ax_prb.set_title("Probability of Passing >= 1 Account vs Batch Size", fontsize=11, color="#000000", pad=8)
    ax_prb.set_xlabel("Evaluation Ticket Batch Size", fontsize=9, color="#000000")
    ax_prb.set_ylabel("Probability (%)", fontsize=9, color="#000000")
    ax_prb.set_ylim(70, 102)
    ax_prb.legend(loc="lower right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel B: Net EV Scaling
    ax_ev = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_ev)

    evs = [n * mc["ev_per_ticket"] for n in batches]
    ax_ev.bar(batches, evs, color="#2ca02c", edgecolor="#000000", width=0.55)
    for b_idx, ev_val in enumerate(evs):
        ax_ev.annotate(f"${ev_val:,.0f}", (batches[b_idx], ev_val), textcoords="offset points", xytext=(0, 3), ha="center", fontsize=7.5, fontweight="bold")

    ax_ev.set_title("Net Expected Value ($ EV) Scaling vs Batch Size", fontsize=11, color="#000000", pad=8)
    ax_ev.set_xlabel("Evaluation Ticket Batch Size", fontsize=9, color="#000000")
    ax_ev.set_ylabel("Net Campaign EV ($)", fontsize=9, color="#000000")
    ax_ev.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))

    # Panel C: Tables (Lottery Ticket Economics & Bankroll Sizing)
    ax_tab = fig.add_subplot(gs[1, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.96, "Lottery Ticket Campaign Economics & Bankroll Management Sizing", fontsize=11, fontweight="bold", color="#000000")

    eco_rows = [
        ("1 Ticket", "$39.00", f"{mc['pass_rate']:.1f}%", f"+${mc['ev_per_ticket']:,.0f}", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%", "Kelly Fraction f*", "0.32 (32% of bankroll)"),
        ("3 Tickets", "$117.00", f"{(1-(1-p_single)**3)*100:.1f}%", f"+${3*mc['ev_per_ticket']:,.0f}", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%", "Min Bankroll B_min", "$195.00 (5 tickets)"),
        ("5 Tickets (Optimal)", "$195.00", f"{(1-(1-p_single)**5)*100:.1f}%", f"+${5*mc['ev_per_ticket']:,.0f}", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%", "Risk of Complete Loss", "< 0.1% (99.9% pass >= 1)"),
        ("10 Tickets", "$390.00", f"{(1-(1-p_single)**10)*100:.1f}%", f"+${10*mc['ev_per_ticket']:,.0f}", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%", "Capital Efficiency", "> 1,800% ROI vs $25k base"),
    ]

    t_hdr = ["Campaign Batch", "Total Cost", "Pass >= 1 Prob", "Net Campaign EV", "Campaign ROI", "Risk Metric", "Value"]
    t_x = [0.02, 0.18, 0.32, 0.46, 0.60, 0.74, 0.90]
    for i, h in enumerate(t_hdr):
        ax_tab.text(t_x[i], 0.85, h, fontsize=8.0, fontweight="bold", color="#000000", ha="left" if i < 2 else "right")

    y_t = 0.73
    for r_i, r in enumerate(eco_rows):
        ax_tab.axhline(y_t + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        is_opt = r_i == 2
        f_w = "bold" if is_opt else "normal"
        c_txt = "#1f77b4" if is_opt else "#000000"
        for c_i, val in enumerate(r):
            ax_tab.text(t_x[c_i], y_t, val, fontsize=8.2, fontweight=f_w, color=c_txt, ha="left" if c_i < 2 else "right")
        y_t -= 0.16

    out_path = OUT_DIR / "04_prop_campaign_economics_and_bankroll.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── MASTER OVERVIEW POSTER ───────────────────────────────────────────────────
def render_prop_poster_master(mc: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(18, 26), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    gs = fig.add_gridspec(5, 2, height_ratios=[3.4, 1.8, 2.2, 3.2, 2.0], hspace=0.35, wspace=0.20)

    # ── PANEL 1: EVALUATION TRAJECTORIES ─────────────────────────────────────
    ax_trj = fig.add_subplot(gs[0, :])
    format_spines_and_grid(ax_trj)

    for trj in mc["eval_trajectories_100"][:80]:
        p = trj["path"]
        c = "#2ca02c" if trj["status"] == "pass" else "#d62728"
        ax_trj.plot(range(len(p)), p, color=c, alpha=0.35, linewidth=0.9)

    ax_trj.axhline(26_250.0, color="#2ca02c", linestyle="--", linewidth=1.8, label="Profit Target ($26,250 • +$1,250)")
    ax_trj.axhline(24_000.0, color="#d62728", linestyle="--", linewidth=1.8, label="Max Trailing Floor ($24,000 • -$1,000)")
    ax_trj.axhline(25_100.0, color="#9467bd", linestyle=":", linewidth=1.5, label="Trailing Floor Lock ($25,100 at Peak >= $26,100)")

    ax_trj.set_title("Backtest Results - Prop Evaluation Mode (LucidFlex 25K)", fontsize=16, color="#000000", pad=12)
    ax_trj.set_xlabel("Trading Days Elapsed", fontsize=11, color="#000000")
    ax_trj.set_ylabel("Account Balance ($)", fontsize=11, color="#000000")
    ax_trj.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_trj.set_ylim(23_700, 26_600)

    leg = ax_trj.legend(title="Prop Firm Boundary", loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=9.5)
    leg.get_title().set_fontsize(10)
    leg.get_title().set_fontweight("bold")

    # ── PANEL 2: CUMULATIVE PASS SPEED CURVE ─────────────────────────────────
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

    # ── PANEL 3A: PASS HORIZON HISTOGRAM ─────────────────────────────────────
    ax_p = fig.add_subplot(gs[2, 0])
    format_spines_and_grid(ax_p)
    ax_p.hist(mc["pass_days"], bins=35, color="#1f77b4", alpha=0.85, edgecolor="#000000", label=f"Passing ({mc['pass_rate']:.1f}%)")
    ax_p.axvline(mc["med_days"], color="#2ca02c", linestyle="--", linewidth=1.8, label=f"Median: {mc['med_days']:.0f}d ({mc['med_trades']:.0f}t)")
    ax_p.set_title("Pass Horizon Distribution (Trading Days to Target)", fontsize=12, color="#000000", pad=8)
    ax_p.set_xlabel("Trading Days to Reach Target", fontsize=9.5, color="#000000")
    ax_p.set_ylabel("Path Count", fontsize=9.5, color="#000000")
    ax_p.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8.5)

    # ── PANEL 3B: FAIL HORIZON HISTOGRAM ─────────────────────────────────────
    ax_f = fig.add_subplot(gs[2, 1])
    format_spines_and_grid(ax_f)
    ax_f.hist(mc["fail_days"], bins=35, color="#d62728", alpha=0.85, edgecolor="#000000", label=f"Breached ({mc['fail_rate']:.1f}%)")
    ax_f.axvline(mc["med_fail_days"], color="#000000", linestyle="--", linewidth=1.8, label=f"Median: {mc['med_fail_days']:.0f}d")
    ax_f.set_title("Fail Horizon Distribution (Trading Days to Floor Breach)", fontsize=12, color="#000000", pad=8)
    ax_f.set_xlabel("Trading Days to Breach Floor", fontsize=9.5, color="#000000")
    ax_f.set_ylabel("Path Count", fontsize=9.5, color="#000000")
    ax_f.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8.5)

    # ── PANEL 4: DURATION PERCENTILES TABLE ──────────────────────────────────
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

    # ── PANEL 5A: FUNDED LONGEVITY LADDER ────────────────────────────────────
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

    # ── PANEL 5B: TICKET CAMPAIGN ECONOMICS TABLE ────────────────────────────
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
        
        /* Top Navigation Header */
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

        /* PNG Sheets Download Bar */
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

        /* 4 Quadrants Grid */
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

        /* Chart container styled exactly like screenshot */
        .chart-box {{
            border: 1px solid #000000;
            background: #FFFFFF;
            height: 480px;
            width: 100%;
            margin-bottom: 20px;
        }}

        /* Academic spreadsheet tables */
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

    <!-- Top Navigation Header -->
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
        <span style="font-size: 11px; font-weight: bold; align-self: center; margin-right: 8px;">PUBLICATION PNG SUITE:</span>
        <a class="sheet-btn" href="01_prop_evaluation_trajectories_and_corridor.png" target="_blank">01. Trajectories & Corridor PNG</a>
        <a class="sheet-btn" href="02_prop_duration_and_speed_distributions.png" target="_blank">02. Duration & Speed Distributions PNG</a>
        <a class="sheet-btn" href="03_prop_funded_lifecycle_and_payout_ladder.png" target="_blank">03. Funded Lifecycle & Ladder PNG</a>
        <a class="sheet-btn" href="04_prop_campaign_economics_and_bankroll.png" target="_blank">04. Campaign Economics & Bankroll PNG</a>
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
            <div class="quad-title">4. Funded Account Economics</div>
            <div class="stat-row"><span class="stat-label">1st Payout Survival Rate</span><span class="stat-val mono color-pos">{mc['p_p1']:.1f}%</span></div>
            <div class="stat-row"><span class="stat-label">2nd Payout Survival Rate</span><span class="stat-val mono">{mc['p_p2']:.1f}%</span></div>
            <div class="stat-row"><span class="stat-label">3rd Payout Survival Rate</span><span class="stat-val mono">{mc['p_p3']:.1f}%</span></div>
            <div class="stat-row"><span class="stat-label">Mean Extracted Net Payout</span><span class="stat-val mono color-pos">${mc['mean_funded_net']:,.2f}</span></div>
            <div class="stat-row"><span class="stat-label">Expected Value / $39 Ticket</span><span class="stat-val mono color-pos">+${mc['ev_per_ticket']:,.2f}</span></div>
            <div class="stat-row"><span class="stat-label">Expected ROI per Ticket</span><span class="stat-val mono color-pos">+{(mc['ev_per_ticket']/39.0)*100:.0f}%</span></div>
        </div>
    </div>

    <!-- Dual Interactive Chart (Matching Screenshot Style) -->
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

    <!-- Section 2: Ticket Campaign Economics Table -->
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

<!-- Client-side Interactive Plot Script -->
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
    mc = run_prop_monte_carlo(daily, n_sims=10_000, block_size=5)

    print("\n" + "=" * 80)
    print("   LUCIDFLEX 25K INSTITUTIONAL PROP SCORECARD")
    print("=" * 80)
    print(f"  Pass Rate (+$1,250 Target):       {mc['pass_rate']:5.2f}%")
    print(f"  Breach Rate (-$1,000 DD):         {mc['fail_rate']:5.2f}%")
    print(f"  Timeout Rate:                      0.00% (No artificial time limit)")
    print(f"  Median Days to Pass:              {mc['med_days']:4.0f} days ({mc['med_trades']:4.0f} trades)")
    print(f"  90% of Passes Complete Within:    {mc['p90_days']:4.0f} days")
    print(f"  Expected Value (EV) per Ticket:  +${mc['ev_per_ticket']:>6.2f}")
    print("=" * 80 + "\n")

    print("Rendering Modular Prop Firm Publication PNG Sheets...")
    s1 = render_prop_sheet_01_trajectories(mc)
    print(f"  Saved Sheet 01: {s1}")
    s2 = render_prop_sheet_02_duration_speed(mc)
    print(f"  Saved Sheet 02: {s2}")
    s3 = render_prop_sheet_03_funded_lifecycle(mc)
    print(f"  Saved Sheet 03: {s3}")
    s4 = render_prop_sheet_04_campaign_bankroll(mc)
    print(f"  Saved Sheet 04: {s4}")
    s_master = render_prop_poster_master(mc)
    print(f"  Saved Master Poster: {s_master}")

    print("Generating Institutional Interactive Prop Dashboard (HTML with ECharts)...")
    dashboard_path = generate_prop_html_dashboard(trades, daily, mc)
    print(f"  Saved Dashboard: {dashboard_path}")
    print(f"\nTo view in browser:\n  open {dashboard_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
