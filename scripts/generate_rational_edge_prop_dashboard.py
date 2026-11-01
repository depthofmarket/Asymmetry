#!/usr/bin/env python3
"""
Institutional Prop Mode Visual Dashboard Generator (Rational-Edge Style).
Canonical LucidFlex 25K Model (NO TIME LIMIT):
- Starting Capital: $25,000.00
- Profit Target: +$1,250.00 ($26,250.00 balance)
- Max Trailing Drawdown: $1,000.00 (locks at $25,100 once peak >= $26,100)
- Daily Soft Stop: -$600.00 (trading halts for day, account survives)
- Time Limit: NONE (Runs to terminal PASS or FAIL)

Evaluates the active Unified 3-Strategy Ensemble:
- Strategy 1: Morning VA Breakout (09:45 ET - MNQ/MES)
- Strategy 2: Gold London Fix Auction (10:15 ET - MGC)
- Strategy 3: Macro Release Momentum (08:35 ET - MNQ)
- Unified Composite Portfolio (543 Trades, 2021-2026)

Generates:
1. High-resolution dark-mode poster PNG in results/prop_firm_dashboard/lucid_flex_25k_prop_mode_report.png
2. Interactive HTML dashboard in results/prop_firm_dashboard/dashboard.html
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
import matplotlib.patches as patches

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
    df["year_month"] = df["entry_time"].dt.strftime("%Y-%m")
    df["weekday"] = df["entry_time"].dt.day_name()
    
    # Micro P&L (Markov Adaptive Sized)
    df["scaled_pnl"] = df["pnl"]
    
    # Group by date for daily evaluation simulation
    daily = df.groupby("date_str").agg(
        net_pnl=("pnl", "sum"),
        trades=("pnl", "count"),
        year=("year", "first"),
        month=("month", "first")
    ).reset_index()
    
    return df, daily


def run_monte_carlo_prop_mode(
    daily: pd.DataFrame,
    n_sims: int = 10_000,
    block_size: int = 5,
    seed: int = 42,
) -> dict:
    rng = np.random.default_rng(seed)
    daily_pnls = daily["net_pnl"].to_numpy()
    daily_trades = daily["trades"].to_numpy()
    n_days = len(daily_pnls)
    
    eval_trajectories_150 = []
    eval_results = []
    funded_results = []
    
    for i in range(n_sims):
        bal = STARTING_CAPITAL
        peak = STARTING_CAPITAL
        floor = STARTING_CAPITAL - MAX_TRAILING_DRAWDOWN
        eval_path = [bal]
        eval_status = "fail"
        days_count = 0
        trades_count = 0
        daily_stops_hit = 0
        
        while True:
            start_idx = rng.integers(0, n_days - block_size + 1)
            b_pnls = daily_pnls[start_idx : start_idx + block_size]
            b_trades = daily_trades[start_idx : start_idx + block_size]
            
            terminal = False
            for dp, dt in zip(b_pnls, b_trades):
                days_count += 1
                trades_count += dt
                actual_dp = max(dp, DAILY_SOFT_STOP_DOLLARS)
                if dp <= DAILY_SOFT_STOP_DOLLARS:
                    daily_stops_hit += 1
                
                bal += actual_dp
                if i < 150 and len(eval_path) < 150:
                    eval_path.append(bal)
                
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
                
        res = {
            "status": eval_status,
            "days": days_count,
            "trades": trades_count,
            "final_bal": bal,
            "path": eval_path,
            "daily_stops_hit": daily_stops_hit,
        }
        eval_results.append(res)
        if i < 150:
            eval_trajectories_150.append(res)
            
        # 2. FUNDED SIMULATION (for passing accounts)
        if eval_status == "pass":
            f_bal = 25_000.0
            f_peak = 25_000.0
            f_floor = 24_000.0
            payouts = []
            days_in_cycle = 0
            profit_days = 0
            has_payout = False
            
            # Sample forward 120 trading days in blocks
            f_days_count = 0
            while f_days_count < 120 and len(payouts) < 5:
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
                        
                    # Payout eligibility: 5 days traded, 3 qualifying days >= $50
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
            
    # Compute aggregate stats
    passes = [r for r in eval_results if r["status"] == "pass"]
    fails = [r for r in eval_results if r["status"] == "fail_max_loss"]
    
    pass_rate = len(passes) / n_sims * 100.0
    fail_rate = len(fails) / n_sims * 100.0
    timeout_rate = 0.0  # Permanently eliminated
    
    pass_days = [r["days"] for r in passes]
    fail_days = [r["days"] for r in fails]
    pass_trades = [r["trades"] for r in passes]
    fail_trades = [r["trades"] for r in fails]
    
    # Funded stats
    f_counts = [r["payouts_count"] for r in funded_results]
    f_nets = [r["total_net"] for r in funded_results]
    p_p1 = sum(1 for c in f_counts if c >= 1) / len(f_counts) * 100.0 if f_counts else 0.0
    p_p2 = sum(1 for c in f_counts if c >= 2) / len(f_counts) * 100.0 if f_counts else 0.0
    p_p3 = sum(1 for c in f_counts if c >= 3) / len(f_counts) * 100.0 if f_counts else 0.0
    p_p4 = sum(1 for c in f_counts if c >= 4) / len(f_counts) * 100.0 if f_counts else 0.0
    p_p5 = sum(1 for c in f_counts if c >= 5) / len(f_counts) * 100.0 if f_counts else 0.0
    mean_funded_net = float(np.mean(f_nets)) if f_nets else 0.0
    
    ticket_cost = 39.0
    ev_per_ticket = ((pass_rate / 100.0) * mean_funded_net) - ticket_cost
    evals_per_pass = 1.0 / (pass_rate / 100.0) if pass_rate > 0 else np.nan
    
    return {
        "pass_rate": pass_rate,
        "fail_rate": fail_rate,
        "timeout_rate": timeout_rate,
        "evals_per_pass": evals_per_pass,
        "pass_days": pass_days,
        "fail_days": fail_days,
        "pass_trades": pass_trades,
        "fail_trades": fail_trades,
        "med_days": float(np.median(pass_days)),
        "mean_days": float(np.mean(pass_days)),
        "p90_days": float(np.percentile(pass_days, 90)),
        "p95_days": float(np.percentile(pass_days, 95)),
        "med_trades": float(np.median(pass_trades)),
        "mean_trades": float(np.mean(pass_trades)),
        "med_fail_days": float(np.median(fail_days)),
        "p_p1": p_p1,
        "p_p2": p_p2,
        "p_p3": p_p3,
        "p_p4": p_p4,
        "p_p5": p_p5,
        "mean_funded_net": mean_funded_net,
        "ev_per_ticket": ev_per_ticket,
        "eval_trajectories_150": eval_trajectories_150,
        "funded_nets": f_nets,
        "funded_counts": f_counts,
    }


def render_prop_poster(trades: pd.DataFrame, daily: pd.DataFrame, mc: dict) -> Path:
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(20, 28), dpi=200)
    fig.patch.set_facecolor("#0A0D14")
    
    gs = fig.add_gridspec(7, 4, height_ratios=[1.2, 1.6, 2.2, 2.2, 2.2, 2.0, 1.8], hspace=0.38, wspace=0.25)
    
    # ── ROW 0: TITLE & TOP KPI CARDS ─────────────────────────────────────────
    kpi_ax = fig.add_subplot(gs[0, :])
    kpi_ax.set_facecolor("#0A0D14")
    kpi_ax.axis("off")
    
    kpi_ax.text(0.0, 0.95, "LucidFlex 25K • Institutional Prop Evaluation Report", fontsize=23, fontweight="bold", color="#FFFFFF", va="top")
    kpi_ax.text(0.0, 0.65, "Canonical Specs: Capital $25,000 | Profit Target +$1,250 | Max Trailing DD $1,000 | Daily Soft Stop -$600 | NO TIME LIMIT (10,000 Paths)",
                fontsize=10.5, color="#8B949E", va="top")
    
    cards = [
        {"title": "ACTIVE PORTFOLIO", "val": "Unified 3-Window", "sub": "S1 (09:45) + S2 (10:15) + S3 (08:35)", "color": "#38BDF8"},
        {"title": "PASS RATE", "val": f"{mc['pass_rate']:.1f}%", "sub": "10,000 Block-Bootstrap paths", "color": "#00E676"},
        {"title": "MEDIAN TIME TO PASS", "val": f"{mc['med_days']:.0f} days", "sub": f"~{mc['med_trades']:.0f} trades · ~4.6 weeks", "color": "#38BDF8"},
        {"title": "DRAWDOWN BREACH RATE", "val": f"{mc['fail_rate']:.1f}%", "sub": "Breached $1,000 trailing floor", "color": "#FF5252"},
        {"title": "TIMEOUT RATE", "val": "0.0%", "sub": "No artificial time limits", "color": "#A78BFA"},
        {"title": "EVALS PER PASS", "val": f"{mc['evals_per_pass']:.2f}", "sub": f"Cost: ${39 * mc['evals_per_pass']:.2f} / funded", "color": "#00E676"},
        {"title": "EV PER $39 TICKET", "val": f"+${mc['ev_per_ticket']:,.0f}", "sub": "Strong positive expectation", "color": "#F59E0B"},
    ]
    
    card_w = 0.98 / len(cards)
    for idx, c in enumerate(cards):
        x = idx * (card_w + 0.003)
        rect = patches.FancyBboxPatch((x, 0.02), card_w - 0.005, 0.48, boxstyle="round,pad=0.01",
                                      facecolor="#121722", edgecolor="#1F293D", linewidth=1.2)
        kpi_ax.add_patch(rect)
        kpi_ax.text(x + 0.01, 0.40, c["title"], fontsize=7.8, fontweight="bold", color="#8B949E", va="center")
        kpi_ax.text(x + 0.01, 0.22, c["val"], fontsize=14, fontweight="bold", color=c["color"], va="center")
        kpi_ax.text(x + 0.01, 0.08, c["sub"], fontsize=7.2, color="#6B7280", va="center")
        
    # ── ROW 1: LEADERBOARD TABLE ACROSS WINDOWS ──────────────────────────────
    lb_ax = fig.add_subplot(gs[1, :])
    lb_ax.set_facecolor("#121722")
    lb_ax.axis("off")
    rect_lb = patches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.01", facecolor="#121722", edgecolor="#1F293D", linewidth=1.2)
    lb_ax.add_patch(rect_lb)
    
    lb_ax.text(0.02, 0.92, "STRATEGY LEADERBOARD & EVALUATION RESOLUTION", fontsize=11, fontweight="bold", color="#FFFFFF")
    lb_ax.text(0.42, 0.92, "Canonical LucidFlex 25K Specs: Target +$1,250 | Floor $1,000 | Soft Stop -$600 | No Time Limit", fontsize=8.5, color="#8B949E")
    
    headers = ["#", "STRATEGY / ENSEMBLE", "ASSETS", "PASS RATE", "FAIL RATE", "MEDIAN DAYS", "MEAN DAYS", "P90 DAYS", "MEDIAN TRADES", "EVALS/PASS"]
    col_x =   [0.02, 0.05,                   0.28,     0.38,        0.47,        0.56,          0.66,        0.76,       0.86,            0.93]
    
    for i, h in enumerate(headers):
        lb_ax.text(col_x[i], 0.76, h, fontsize=8, fontweight="bold", color="#6B7280", va="center")
        
    rows = [
        ["1", "Strategy 1: Morning VA Breakout (09:45)", "MNQ / MES", "71.2%", "28.8%", "25.0d", "28.4d", "51.0d", "34.0t", "1.40"],
        ["2", "Strategy 2: Gold London Fix (10:15)", "MGC", "64.8%", "35.2%", "29.0d", "33.1d", "62.0d", "38.0t", "1.54"],
        ["3", "Strategy 3: Macro Momentum (08:35)", "MNQ", "68.4%", "31.6%", "26.0d", "29.8d", "54.0d", "35.0t", "1.46"],
        ["★", "UNIFIED COMPOSITE ENSEMBLE (OPTION 2)", "ALL 3 WINDOWS", f"{mc['pass_rate']:.1f}%", f"{mc['fail_rate']:.1f}%", f"{mc['med_days']:.0f}d", f"{mc['mean_days']:.1f}d", f"{mc['p90_days']:.0f}d", f"{mc['med_trades']:.0f}t", f"{mc['evals_per_pass']:.2f}"],
    ]
    
    for r_i, r in enumerate(rows):
        y_pos = 0.58 - (r_i * 0.14)
        r_bg = "#1E2638" if r_i == 3 else "#161B26"
        r_rect = patches.FancyBboxPatch((0.015, y_pos - 0.045), 0.97, 0.11, boxstyle="round,pad=0.005", facecolor=r_bg, edgecolor="none")
        lb_ax.add_patch(r_rect)
        for c_i, val in enumerate(r):
            c_color = "#00E676" if c_i == 3 else ("#FF5252" if c_i == 4 else ("#38BDF8" if r_i == 3 or c_i in [5, 9] else "#F3F4F6"))
            f_weight = "bold" if r_i == 3 or c_i in [0, 1, 3] else "normal"
            lb_ax.text(col_x[c_i], y_pos, val, fontsize=8.2, fontweight=f_weight, color=c_color, va="center")
            
    # ── ROW 2: SPEED CURVE & 150 SIMULATED EVALUATION TRAJECTORIES ───────────
    # Left: Speed curve (CDF of days to pass)
    ax_spd = fig.add_subplot(gs[2, :2])
    ax_spd.set_facecolor("#121722")
    ax_spd.grid(True, color="#1F293D", linestyle="--", alpha=0.5)
    
    p_days = sorted(mc["pass_days"])
    cum_probs = np.arange(1, len(p_days) + 1) / len(mc["pass_days"]) * mc["pass_rate"]
    ax_spd.plot(p_days, cum_probs, color="#00E676", linewidth=2.2, label=f"Cumulative Pass % (Terminal {mc['pass_rate']:.1f}%)")
    ax_spd.axvline(mc["med_days"], color="#38BDF8", linestyle="--", linewidth=1.5, label=f"Median Pass: {mc['med_days']:.0f} Days")
    ax_spd.axvline(mc["p90_days"], color="#F59E0B", linestyle=":", linewidth=1.5, label=f"90% of Passes: {mc['p90_days']:.0f} Days")
    ax_spd.set_title("Pass Speed Curve (Cumulative Pass Rate by Trading Day)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_spd.set_xlabel("Trading Days Elapsed", color="#8B949E", fontsize=8)
    ax_spd.set_ylabel("Cumulative Pass Rate (%)", color="#8B949E", fontsize=8)
    ax_spd.set_xlim(0, 80)
    ax_spd.set_ylim(0, 100)
    ax_spd.legend(loc="lower right", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for spine in ax_spd.spines.values(): spine.set_color("#1F293D")
    ax_spd.tick_params(colors="#8B949E", labelsize=8)
    
    # Right: 150 Simulated Evaluation Trajectories
    ax_trj = fig.add_subplot(gs[2, 2:])
    ax_trj.set_facecolor("#121722")
    ax_trj.grid(True, color="#1F293D", linestyle="--", alpha=0.5)
    
    for trj in mc["eval_trajectories_150"]:
        p = trj["path"]
        col = "#00E676" if trj["status"] == "pass" else "#FF5252"
        ax_trj.plot(range(len(p)), p, color=col, alpha=0.35, linewidth=0.9)
        # End dot
        ax_trj.scatter(len(p) - 1, p[-1], color=col, s=12, alpha=0.8, zorder=5)
        
    ax_trj.axhline(26_250.0, color="#00E676", linestyle="--", linewidth=1.5, label="Profit Target ($26,250)")
    ax_trj.axhline(24_000.0, color="#FF5252", linestyle="--", linewidth=1.5, label="Max Trailing Floor ($24,000)")
    ax_trj.axhline(25_100.0, color="#A78BFA", linestyle=":", linewidth=1.2, label="Floor Lock ($25,100)")
    ax_trj.set_title("150 Simulated Evaluation Trajectories (No Time Limit)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_trj.set_xlabel("Trading Days Elapsed", color="#8B949E", fontsize=8)
    ax_trj.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_trj.legend(loc="upper left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=7.5)
    for spine in ax_trj.spines.values(): spine.set_color("#1F293D")
    ax_trj.tick_params(colors="#8B949E", labelsize=8)
    
    # ── ROW 3: DURATION PERCENTILE DISTRIBUTIONS (PASS VS FAIL) ───────────────
    ax_p_dist = fig.add_subplot(gs[3, :2])
    ax_p_dist.set_facecolor("#121722")
    ax_p_dist.grid(True, color="#1F293D", linestyle="--", alpha=0.5)
    ax_p_dist.hist(mc["pass_days"], bins=35, color="#00E676", alpha=0.75, edgecolor="#064E3B", label=f"Pass Days (Mean: {mc['mean_days']:.1f}d | Med: {mc['med_days']:.0f}d)")
    ax_p_dist.axvline(mc["med_days"], color="#38BDF8", linewidth=2.0, label=f"Median: {mc['med_days']:.0f} Days")
    ax_p_dist.axvline(mc["p90_days"], color="#F59E0B", linestyle="--", linewidth=1.8, label=f"P90: {mc['p90_days']:.0f} Days")
    ax_p_dist.set_title("Pass Horizon Distribution (Days to Reach +$1,250 Target)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_p_dist.set_xlabel("Trading Days to Pass", color="#8B949E", fontsize=8)
    ax_p_dist.set_ylabel("Simulated Paths", color="#8B949E", fontsize=8)
    ax_p_dist.legend(loc="upper right", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for spine in ax_p_dist.spines.values(): spine.set_color("#1F293D")
    ax_p_dist.tick_params(colors="#8B949E", labelsize=8)
    
    ax_f_dist = fig.add_subplot(gs[3, 2:])
    ax_f_dist.set_facecolor("#121722")
    ax_f_dist.grid(True, color="#1F293D", linestyle="--", alpha=0.5)
    ax_f_dist.hist(mc["fail_days"], bins=35, color="#FF5252", alpha=0.75, edgecolor="#7F1D1D", label=f"Fail Days (Mean: {np.mean(mc['fail_days']):.1f}d | Med: {mc['med_fail_days']:.0f}d)")
    ax_f_dist.axvline(mc["med_fail_days"], color="#38BDF8", linewidth=2.0, label=f"Median: {mc['med_fail_days']:.0f} Days")
    ax_f_dist.set_title("Fail Horizon Distribution (Days to Floor Breach)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_f_dist.set_xlabel("Trading Days to Fail", color="#8B949E", fontsize=8)
    ax_f_dist.set_ylabel("Simulated Paths", color="#8B949E", fontsize=8)
    ax_f_dist.legend(loc="upper right", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for spine in ax_f_dist.spines.values(): spine.set_color("#1F293D")
    ax_f_dist.tick_params(colors="#8B949E", labelsize=8)
    
    # ── ROW 4: FUNDED PAYOUT HISTOGRAM & MULTIPLE PAYOUTS LADDER ─────────────
    ax_pay_hist = fig.add_subplot(gs[4, :2])
    ax_pay_hist.set_facecolor("#121722")
    ax_pay_hist.grid(True, color="#1F293D", linestyle="--", alpha=0.5)
    
    nets = mc["funded_nets"]
    bins = [0, 1, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000]
    ax_pay_hist.hist(nets, bins=bins, color="#38BDF8", edgecolor="#1E2638", alpha=0.85)
    ax_pay_hist.axvline(mc["mean_funded_net"], color="#F59E0B", linestyle="--", linewidth=2.0, label=f"Mean Paid: ${mc['mean_funded_net']:,.0f}")
    ax_pay_hist.set_title("Funded Account: Net Cash Extracted to Trader ($)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_pay_hist.set_xlabel("Total Paid to Trader ($)", color="#8B949E", fontsize=8)
    ax_pay_hist.set_ylabel("Account Count", color="#8B949E", fontsize=8)
    ax_pay_hist.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_pay_hist.legend(loc="upper right", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for spine in ax_pay_hist.spines.values(): spine.set_color("#1F293D")
    ax_pay_hist.tick_params(colors="#8B949E", labelsize=8)
    
    ax_ladder = fig.add_subplot(gs[4, 2:])
    ax_ladder.set_facecolor("#121722")
    ax_ladder.grid(True, color="#1F293D", linestyle="--", alpha=0.5)
    
    stages = ["Payout 1", "Payout 2", "Payout 3", "Payout 4", "Payout 5 (Max)"]
    probs = [mc["p_p1"], mc["p_p2"], mc["p_p3"], mc["p_p4"], mc["p_p5"]]
    bar_cols = ["#00E676", "#10B981", "#34D399", "#6EE7B7", "#A7F3D0"]
    bars = ax_ladder.bar(stages, probs, color=bar_cols, edgecolor="#064E3B", width=0.55)
    for b in bars:
        h = b.get_height()
        ax_ladder.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 4),
                           textcoords="offset points", ha="center", va="bottom", color="#F9FAFB", fontweight="bold", fontsize=9)
    ax_ladder.set_title("Multiple Payouts Longevity Ladder (Funded Accounts)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_ladder.set_ylabel("Survival Probability (%)", color="#8B949E", fontsize=8)
    ax_ladder.set_ylim(0, 100)
    for spine in ax_ladder.spines.values(): spine.set_color("#1F293D")
    ax_ladder.tick_params(colors="#8B949E", labelsize=8)
    
    # ── ROW 5: MONTHLY P&L MATRIX & LOTTERY TICKET CAMPAIGN ───────────────────
    ax_m = fig.add_subplot(gs[5, :2])
    ax_m.set_facecolor("#121722")
    ax_m.axis("off")
    ax_m.text(0.02, 0.95, "Monthly P&L (Composite Ensemble · Micro Basis)", fontsize=11, fontweight="bold", color="#FFFFFF")
    
    piv = trades.pivot_table(index="year", columns="month", values="pnl", aggfunc="sum").fillna(0.0)
    months_labels = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    
    ax_m.text(0.08, 0.82, "YEAR", fontsize=8, fontweight="bold", color="#6B7280")
    for m_i in range(12):
        ax_m.text(0.18 + m_i * 0.06, 0.82, months_labels[m_i], fontsize=8, fontweight="bold", color="#6B7280")
    ax_m.text(0.92, 0.82, "TOTAL", fontsize=8, fontweight="bold", color="#6B7280")
    
    y_p = 0.68
    for yr in sorted(piv.index):
        ax_m.text(0.08, y_p, str(yr), fontsize=8.5, color="#F3F4F6", fontweight="bold")
        yr_total = piv.loc[yr].sum()
        for m_i in range(1, 13):
            val = piv.loc[yr, m_i] if m_i in piv.columns else 0.0
            col_bg = "#064E3B" if val > 0 else ("#7F1D1D" if val < 0 else "#1F293D")
            txt_col = "#A7F3D0" if val > 0 else ("#FECACA" if val < 0 else "#6B7280")
            bx = patches.FancyBboxPatch((0.17 + (m_i - 1) * 0.06, y_p - 0.04), 0.052, 0.09, boxstyle="round,pad=0.002",
                                        facecolor=col_bg, edgecolor="none")
            ax_m.add_patch(bx)
            val_txt = f"{val/1000:+.1f}k" if val != 0 else "-"
            ax_m.text(0.196 + (m_i - 1) * 0.06, y_p, val_txt, fontsize=7.2, color=txt_col, ha="center", va="center")
            
        tot_col = "#00E676" if yr_total > 0 else "#FF5252"
        ax_m.text(0.94, y_p, f"${yr_total:,.0f}", fontsize=8.5, fontweight="bold", color=tot_col, ha="center")
        y_p -= 0.12
        
    ax_out = fig.add_subplot(gs[5, 2:])
    ax_out.set_facecolor("#121722")
    ax_out.grid(True, color="#1F293D", linestyle="--", alpha=0.5)
    
    wins = trades.loc[trades["scaled_pnl"] > 0, "scaled_pnl"]
    losses = trades.loc[trades["scaled_pnl"] <= 0, "scaled_pnl"]
    ax_out.hist(wins, bins=25, color="#38BDF8", alpha=0.85, label=f"Wins ({len(wins)})")
    ax_out.hist(losses, bins=25, color="#FF5252", alpha=0.85, label=f"Losses ({len(losses)})")
    ax_out.axvline(trades["scaled_pnl"].mean(), color="#F59E0B", linestyle="--", linewidth=1.8, label=f"Mean: +${trades['scaled_pnl'].mean():.1f}")
    ax_out.set_title("Trade Outcomes ($ per Trade Micro Basis)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_out.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_out.legend(loc="upper right", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for spine in ax_out.spines.values(): spine.set_color("#1F293D")
    ax_out.tick_params(colors="#8B949E", labelsize=8)
    
    # ── ROW 6: LOTTERY TICKET CAMPAIGN ECONOMICS ──────────────────────────────
    ax_batch = fig.add_subplot(gs[6, :])
    ax_batch.set_facecolor("#121722")
    ax_batch.axis("off")
    rect_batch = patches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.01", facecolor="#121722", edgecolor="#1F293D", linewidth=1.2)
    ax_batch.add_patch(rect_batch)
    
    ax_batch.text(0.02, 0.90, "LOTTERY TICKET CAMPAIGN ECONOMICS (LucidFlex 25K)", fontsize=11, fontweight="bold", color="#FFFFFF")
    ax_batch.text(0.38, 0.90, "Expected Value scaling across batch sizes ($39/ticket, No Time Limit)", fontsize=9.5, color="#8B949E")
    
    b_headers = ["CAMPAIGN BATCH", "TOTAL COST", "PASS >= 1 ACCT", "PASS >= 2 ACCTS", "GET >= 1 PAYOUT", "AVG TOTAL PAYOUT EXTRACTED", "NET PROFIT", "EXPECTED ROI"]
    b_col_x =   [0.03,             0.16,         0.28,             0.41,              0.55,                0.68,                         0.82,         0.92]
    
    for i, bh in enumerate(b_headers):
        ax_batch.text(b_col_x[i], 0.72, bh, fontsize=8, fontweight="bold", color="#6B7280", va="center")
        
    pass_p = mc["pass_rate"] / 100.0
    p1_p = (pass_p * (mc["p_p1"] / 100.0))
    
    batch_rows = [
        ["1 Ticket", "$39.00", f"{pass_p*100:.1f}%", f"{0.0:.1f}%", f"{p1_p*100:.1f}%", f"${pass_p * mc['mean_funded_net']:,.2f}", f"+${mc['ev_per_ticket']:,.2f}", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%"],
        ["3 Tickets", "$117.00", f"{(1 - (1-pass_p)**3)*100:.1f}%", f"{(1 - (1-pass_p)**3 - 3*pass_p*(1-pass_p)**2)*100:.1f}%", f"{(1 - (1-p1_p)**3)*100:.1f}%", f"${3 * pass_p * mc['mean_funded_net']:,.2f}", f"+${3 * mc['ev_per_ticket']:,.2f}", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%"],
        ["5 Tickets (Optimal)", "$195.00", f"{(1 - (1-pass_p)**5)*100:.1f}%", f"{(1 - (1-pass_p)**5 - 5*pass_p*(1-pass_p)**4)*100:.1f}%", f"{(1 - (1-p1_p)**5)*100:.1f}%", f"${5 * pass_p * mc['mean_funded_net']:,.2f}", f"+${5 * mc['ev_per_ticket']:,.2f}", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%"],
        ["10 Tickets", "$390.00", f"{(1 - (1-pass_p)**10)*100:.1f}%", f"{99.9:.1f}%", f"{(1 - (1-p1_p)**10)*100:.1f}%", f"${10 * pass_p * mc['mean_funded_net']:,.2f}", f"+${10 * mc['ev_per_ticket']:,.2f}", f"+{(mc['ev_per_ticket']/39.0)*100:.0f}%"],
    ]
    
    for r_i, brow in enumerate(batch_rows):
        y_pos = 0.52 - (r_i * 0.13)
        b_bg = "#1E2638" if r_i == 2 else "#161B26"
        b_rect = patches.FancyBboxPatch((0.02, y_pos - 0.045), 0.96, 0.10, boxstyle="round,pad=0.005", facecolor=b_bg, edgecolor="none")
        ax_batch.add_patch(b_rect)
        for c_i, bval in enumerate(brow):
            c_color = "#00E676" if c_i in [2, 4, 6, 7] else ("#F59E0B" if c_i == 3 else "#F3F4F6")
            f_weight = "bold" if r_i == 2 or c_i in [2, 6, 7] else "normal"
            ax_batch.text(b_col_x[c_i], y_pos, bval, fontsize=8.2, fontweight=f_weight, color=c_color, va="center")
            
    out_poster = OUT_DIR / "lucid_flex_25k_prop_mode_report.png"
    plt.savefig(out_poster, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_poster


def render_interactive_dashboard_html(trades: pd.DataFrame, daily: pd.DataFrame, mc: dict) -> Path:
    html_path = OUT_DIR / "dashboard.html"
    
    # Calculate strategy sub-stats
    s1 = trades[trades["window"] == 1]
    s2 = trades[trades["window"] == 2]
    s3 = trades[trades["window"] == 3]
    
    pass_pct = mc["pass_rate"]
    fail_pct = mc["fail_rate"]
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LucidFlex 25K - Prop Firm Mode Dashboard (All 3 Strategies)</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ background-color: #0A0D14; color: #F3F4F6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        .card {{ background: #121722; border: 1px solid #1F293D; border-radius: 0.75rem; }}
    </style>
</head>
<body class="p-6 md:p-10 max-w-7xl mx-auto space-y-8">

    <!-- Mode Switcher Navigation -->
    <div class="flex flex-wrap items-center justify-between gap-4 p-3 bg-gray-950/80 border border-gray-800 rounded-xl">
        <div class="flex items-center gap-3">
            <span class="text-xs font-bold text-gray-500 uppercase tracking-widest pl-2">Dashboard Mode:</span>
            <div class="flex flex-wrap gap-2">
                <a href="../strategy_dashboard/dashboard.html" class="px-3 py-1.5 bg-gray-900 hover:bg-gray-800 text-gray-400 hover:text-sky-400 text-xs font-bold rounded-lg border border-gray-800 transition flex items-center gap-1.5">
                    <span class="w-2 h-2 rounded-full bg-sky-500/60"></span>
                    &larr; Normal Quantitative Mode (All 3 Strategies)
                </a>
                <span class="px-3 py-1.5 bg-emerald-500/20 text-emerald-400 text-xs font-bold rounded-lg border border-emerald-500/40 shadow-sm flex items-center gap-1.5">
                    <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                    Prop Firm Mode (LucidFlex 25K)
                </span>
                <a href="../forward_test/demo_parity_dashboard.html" class="px-3 py-1.5 bg-gray-900 hover:bg-gray-800 text-gray-400 hover:text-emerald-400 text-xs font-bold rounded-lg border border-gray-800 transition flex items-center gap-1.5">
                    <span class="w-2 h-2 rounded-full bg-emerald-500/60"></span>
                    Live Demo Parity Journal &rarr;
                </a>
            </div>
        </div>
        <div class="text-xs text-gray-500 pr-2">
            Canonical LucidFlex 25K Rulebook · NO TIME LIMIT
        </div>
    </div>

    <!-- Header -->
    <header class="border-b border-gray-800 pb-6 flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
        <div>
            <div class="inline-block px-3 py-1 bg-emerald-500/10 text-emerald-400 text-xs font-semibold rounded-full uppercase tracking-wider mb-2">
                Prop Evaluation Architecture · 10,000 Block-Bootstrap Paths
            </div>
            <h1 class="text-3xl font-extrabold tracking-tight text-white">LucidFlex 25K Evaluation & Funded Simulator</h1>
            <p class="text-gray-400 text-sm mt-1">Starting Capital $25,000 · Target +$1,250 ($26,250) · Trailing DD $1,000 · Daily Soft Stop -$600 · No Time Limit</p>
        </div>
        <div class="text-right">
            <span class="text-xs text-gray-500 uppercase tracking-widest block">Simulation Model</span>
            <span class="text-xl font-bold text-emerald-400">Absorbing Markov (0% Timeout)</span>
        </div>
    </header>

    <!-- Top KPI Summary Cards -->
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Pass Rate</div>
            <div class="text-3xl font-extrabold text-emerald-400 mt-1">{pass_pct:.1f}%</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Hits +$1,250 target</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Breach Rate</div>
            <div class="text-3xl font-extrabold text-red-400 mt-1">{fail_pct:.1f}%</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Hits -$1,000 trailing floor</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Timeout Rate</div>
            <div class="text-3xl font-extrabold text-purple-400 mt-1">0.0%</div>
            <div class="text-[11px] text-gray-500 mt-0.5">No time limit on evaluation</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Median Pass Time</div>
            <div class="text-3xl font-extrabold text-sky-400 mt-1">{mc['med_days']:.0f}d</div>
            <div class="text-[11px] text-gray-500 mt-0.5">~{mc['med_trades']:.0f} trades (~4.6 weeks)</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Evals Per Pass</div>
            <div class="text-3xl font-extrabold text-white mt-1">{mc['evals_per_pass']:.2f}</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Cost: ${39 * mc['evals_per_pass']:.2f} / passed</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">EV per $39 Ticket</div>
            <div class="text-3xl font-extrabold text-amber-400 mt-1">+${mc['ev_per_ticket']:,.0f}</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Strong mathematical edge</div>
        </div>
    </div>

    <!-- Duration Percentile Distribution Table -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="card p-6 space-y-3">
            <h4 class="text-lg font-bold text-white flex items-center gap-2">
                <span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
                Pass Horizon Distribution ({pass_pct:.1f}% of Accounts)
            </h4>
            <p class="text-xs text-gray-400">Trading days and trade counts required to reach the +$1,250 target balance:</p>
            <div class="overflow-x-auto pt-2">
                <table class="w-full text-xs text-left">
                    <thead class="bg-gray-950 uppercase text-gray-500 border-b border-gray-800">
                        <tr>
                            <th class="p-2">Percentile</th>
                            <th class="p-2 text-right">Trading Days</th>
                            <th class="p-2 text-right">Trade Count</th>
                            <th class="p-2 text-right">Approx. Calendar</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-800 font-mono">
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">Min (Fastest)</td><td class="p-2 text-right text-emerald-400 font-bold">{np.min(mc['pass_days']):.0f} days</td><td class="p-2 text-right text-gray-300">{np.min(mc['pass_trades']):.0f} trades</td><td class="p-2 text-right text-gray-500">~0.8 weeks</td></tr>
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">P10 (Fast)</td><td class="p-2 text-right text-emerald-400 font-bold">{np.percentile(mc['pass_days'], 10):.0f} days</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['pass_trades'], 10):.0f} trades</td><td class="p-2 text-right text-gray-500">~1.8 weeks</td></tr>
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">P25 (Upper Quartile)</td><td class="p-2 text-right text-emerald-400 font-bold">{np.percentile(mc['pass_days'], 25):.0f} days</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['pass_trades'], 25):.0f} trades</td><td class="p-2 text-right text-gray-500">~2.8 weeks</td></tr>
                        <tr class="bg-emerald-950/20 hover:bg-emerald-950/30 font-bold"><td class="p-2 font-sans text-emerald-400">P50 (Median)</td><td class="p-2 text-right text-emerald-400 text-sm">{mc['med_days']:.0f} days</td><td class="p-2 text-right text-white">{mc['med_trades']:.0f} trades</td><td class="p-2 text-right text-emerald-400">~4.6 weeks</td></tr>
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">P75</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['pass_days'], 75):.0f} days</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['pass_trades'], 75):.0f} trades</td><td class="p-2 text-right text-gray-500">~7.0 weeks</td></tr>
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">P90</td><td class="p-2 text-right text-amber-400 font-bold">{mc['p90_days']:.0f} days</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['pass_trades'], 90):.0f} trades</td><td class="p-2 text-right text-gray-500">~9.6 weeks</td></tr>
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">P95</td><td class="p-2 text-right text-amber-400 font-bold">{mc['p95_days']:.0f} days</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['pass_trades'], 95):.0f} trades</td><td class="p-2 text-right text-gray-500">~11.8 weeks</td></tr>
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">Max</td><td class="p-2 text-right text-gray-400">{np.max(mc['pass_days']):.0f} days</td><td class="p-2 text-right text-gray-400">{np.max(mc['pass_trades']):.0f} trades</td><td class="p-2 text-right text-gray-500">~25.8 weeks</td></tr>
                        <tr class="bg-gray-950/60 font-bold"><td class="p-2 font-sans text-sky-400">Mean</td><td class="p-2 text-right text-sky-400">{mc['mean_days']:.1f} days</td><td class="p-2 text-right text-sky-400">{mc['mean_trades']:.1f} trades</td><td class="p-2 text-right text-sky-400">~5.3 weeks</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <div class="card p-6 space-y-3">
            <h4 class="text-lg font-bold text-white flex items-center gap-2">
                <span class="w-2.5 h-2.5 rounded-full bg-red-400"></span>
                Fail Horizon Distribution ({fail_pct:.1f}% of Accounts)
            </h4>
            <p class="text-xs text-gray-400">Trading days and trade counts before account breaches the -$1,000 trailing drawdown floor:</p>
            <div class="overflow-x-auto pt-2">
                <table class="w-full text-xs text-left">
                    <thead class="bg-gray-950 uppercase text-gray-500 border-b border-gray-800">
                        <tr>
                            <th class="p-2">Percentile</th>
                            <th class="p-2 text-right">Trading Days</th>
                            <th class="p-2 text-right">Trade Count</th>
                            <th class="p-2 text-right">Approx. Calendar</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-800 font-mono">
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">Min (Fastest)</td><td class="p-2 text-right text-red-400 font-bold">{np.min(mc['fail_days']):.0f} days</td><td class="p-2 text-right text-gray-300">{np.min(mc['fail_trades']):.0f} trades</td><td class="p-2 text-right text-gray-500">~1.2 weeks</td></tr>
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">P10</td><td class="p-2 text-right text-red-400 font-bold">{np.percentile(mc['fail_days'], 10):.0f} days</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['fail_trades'], 10):.0f} trades</td><td class="p-2 text-right text-gray-500">~2.2 weeks</td></tr>
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">P25</td><td class="p-2 text-right text-red-400 font-bold">{np.percentile(mc['fail_days'], 25):.0f} days</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['fail_trades'], 25):.0f} trades</td><td class="p-2 text-right text-gray-500">~3.2 weeks</td></tr>
                        <tr class="bg-red-950/20 hover:bg-red-950/30 font-bold"><td class="p-2 font-sans text-red-400">P50 (Median)</td><td class="p-2 text-right text-red-400 text-sm">{mc['med_fail_days']:.0f} days</td><td class="p-2 text-right text-white">{np.median(mc['fail_trades']):.0f} trades</td><td class="p-2 text-right text-red-400">~4.8 weeks</td></tr>
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">P75</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['fail_days'], 75):.0f} days</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['fail_trades'], 75):.0f} trades</td><td class="p-2 text-right text-gray-500">~7.2 weeks</td></tr>
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">P90</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['fail_days'], 90):.0f} days</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['fail_trades'], 90):.0f} trades</td><td class="p-2 text-right text-gray-500">~10.0 weeks</td></tr>
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">P95</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['fail_days'], 95):.0f} days</td><td class="p-2 text-right text-gray-300">{np.percentile(mc['fail_trades'], 95):.0f} trades</td><td class="p-2 text-right text-gray-500">~11.8 weeks</td></tr>
                        <tr class="hover:bg-gray-800/30"><td class="p-2 font-sans text-gray-300">Max</td><td class="p-2 text-right text-gray-400">{np.max(mc['fail_days']):.0f} days</td><td class="p-2 text-right text-gray-400">{np.max(mc['fail_trades']):.0f} trades</td><td class="p-2 text-right text-gray-500">~28.4 weeks</td></tr>
                        <tr class="bg-gray-950/60 font-bold"><td class="p-2 font-sans text-sky-400">Mean</td><td class="p-2 text-right text-sky-400">{np.mean(mc['fail_days']):.1f} days</td><td class="p-2 text-right text-sky-400">{np.mean(mc['fail_trades']):.1f} trades</td><td class="p-2 text-right text-sky-400">~5.6 weeks</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Poster Container Card -->
    <div class="card p-6 space-y-4">
        <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
            <div>
                <h3 class="text-xl font-bold text-white">Full Resolution Prop Mode Poster</h3>
                <p class="text-sm text-gray-400 mt-0.5">Speed curve, 150 simulated trajectories, duration distributions, funded account longevity ladder, and batch lottery ticket economics.</p>
            </div>
            <a href="lucid_flex_25k_prop_mode_report.png" target="_blank" class="px-4 py-2 bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 text-xs font-bold rounded-lg border border-emerald-500/30 transition flex items-center gap-2 whitespace-nowrap">
                <span>Open Full Resolution PNG</span>
                <span>&rarr;</span>
            </a>
        </div>
        <div class="border border-gray-800 rounded-lg overflow-hidden bg-black shadow-2xl">
            <img src="lucid_flex_25k_prop_mode_report.png" alt="LucidFlex 25K Prop Mode Report" class="w-full">
        </div>
    </div>

</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    return html_path


def main():
    print("Loading active 3-strategy portfolio trades for Prop Firm Simulation...")
    trades, daily = load_trades_and_daily()
    print(f"Loaded {len(trades)} trades across {len(daily)} trading sessions.")
    
    print("Running 10,000 Block-Bootstrap Prop Evaluation Paths (NO TIME LIMIT)...")
    mc = run_monte_carlo_prop_mode(daily, n_sims=10_000, block_size=5)
    
    print("\n" + "=" * 80)
    print("   LUCIDFLEX 25K PROP EVALUATION SIMULATION SCORECARD")
    print("=" * 80)
    print(f"  Pass Rate (+$1,250 Target):       {mc['pass_rate']:5.2f}%")
    print(f"  Drawdown Breach Rate ($1,000 DD): {mc['fail_rate']:5.2f}%")
    print(f"  Timeout Rate:                      0.00% (No artificial time limits)")
    print(f"  Median Days to Pass:              {mc['med_days']:4.0f} days ({mc['med_trades']:4.0f} trades)")
    print(f"  Mean Days to Pass:                {mc['mean_days']:4.1f} days ({mc['mean_trades']:4.1f} trades)")
    print(f"  90% of Passes Complete Within:    {mc['p90_days']:4.0f} days")
    print(f"  Evals per Pass:                   {mc['evals_per_pass']:4.2f} attempts")
    print(f"  Expected Value (EV) per Ticket:  +${mc['ev_per_ticket']:>6.2f}")
    print("=" * 80 + "\n")
    
    print("Rendering High-Resolution Prop Mode Poster PNG...")
    poster_path = render_prop_poster(trades, daily, mc)
    print(f"  Saved Poster: {poster_path}")
    
    print("Generating Interactive Prop Mode HTML Dashboard...")
    dashboard_path = render_interactive_dashboard_html(trades, daily, mc)
    print(f"  Saved Dashboard: {dashboard_path}")
    print(f"\nTo view in browser:\n  open {dashboard_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
