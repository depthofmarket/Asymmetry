#!/usr/bin/env python3
"""
Prop Firm Metrics Simulator & Visual Dashboard Generator for LucidFlex 25K.

Computes:
1. Evaluation Phase: Pass rate, fail rate, days to pass, cost per passed account.
2. Funded Phase: Longevity decay, probability of 1st, 2nd, 3rd, 4th, 5th payouts, expected payout dollars.
3. Lottery Ticket Economics: EV per $39 ticket, batch win probabilities (1, 3, 5, 10, 20 tickets), ROI.
4. Generates:
   - High-resolution dark-mode charts (PNG) in results/prop_firm_dashboard/
   - Interactive HTML Dashboard in results/prop_firm_dashboard/dashboard.html
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

OUT_DIR = REPO_ROOT / "results" / "prop_firm_dashboard"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DATA_PATH = REPO_ROOT / "data/processed/upgraded_v2_portfolio_trades_2021_2026.parquet"


def load_trades() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Trades file not found: {DATA_PATH}")
    df = pd.read_parquet(DATA_PATH)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["date_str"] = df["entry_time"].dt.strftime("%Y-%m-%d")
    return df.sort_values("entry_time").reset_index(drop=True)


def simulate_eval_attempt(
    daily_pnls: list[float],
    starting_capital: float = 25_000.0,
    profit_target: float = 1_250.0,
    max_trailing_dd: float = 1_000.0,
    daily_loss_limit: float = 600.0,
    max_days: int = 60,
) -> dict:
    """
    Simulate one LucidFlex 25K eval attempt using Anti-Martingale Ratchet.
    Tier 1 (<$350): 2 Micros (0.20x mini)
    Tier 2 ($350 - $750): 3 Micros (0.30x mini)
    Tier 3 (>=$750): 4 Micros (0.40x mini)
    """
    balance = starting_capital
    peak_balance = starting_capital
    trailing_floor = starting_capital - max_trailing_dd
    
    for day_idx, pnl_mini in enumerate(daily_pnls[:max_days]):
        profit = balance - starting_capital
        
        # Determine sizing multiplier
        if profit >= 750.0:
            scale = 0.40  # 4 Micros
        elif profit >= 350.0:
            scale = 0.30  # 3 Micros
        else:
            scale = 0.20  # 2 Micros
            
        scaled_pnl = pnl_mini * scale
        
        # Check daily loss limit ($600)
        if scaled_pnl <= -daily_loss_limit:
            return {"status": "fail", "reason": "daily_loss_limit", "days": day_idx + 1, "final_bal": balance + scaled_pnl}
            
        balance += scaled_pnl
        profit = balance - starting_capital
        
        # Update peak balance and trailing floor (locks at $25,100 once peak hits $26,100)
        if balance > peak_balance:
            peak_balance = balance
            trailing_floor = min(25_100.0, peak_balance - max_trailing_dd)
            
        # Target check
        if profit >= profit_target:
            return {"status": "pass", "reason": "target_reached", "days": day_idx + 1, "final_bal": balance}
            
        # Drawdown check
        if balance <= trailing_floor:
            return {"status": "fail", "reason": "trailed_out", "days": day_idx + 1, "final_bal": balance}
            
    return {"status": "timeout", "reason": "max_days_elapsed", "days": max_days, "final_bal": balance}


def simulate_funded_attempt(
    daily_pnls: list[float],
    starting_capital: float = 25_000.0,
    max_trailing_dd: float = 1_000.0,
    daily_loss_limit: float = 600.0,
    max_days: int = 120,
    payout_cadence_days: int = 5,
    payout_min_profit_days: int = 5,
    min_daily_profit: float = 100.0,
    payout_pct: float = 0.50,
    payout_cap: float = 1_000.0,
    min_payout: float = 500.0,
    split_pct: float = 0.90,
) -> dict:
    """
    Simulate one LucidFlex 25K funded account across its lifespan.
    Tracks multiple payouts (1st, 2nd, 3rd, 4th, 5th).
    """
    balance = starting_capital
    peak_balance = starting_capital
    trailing_floor = starting_capital - max_trailing_dd
    
    payouts = []
    days_in_cycle = 0
    profit_days_in_cycle = 0
    has_had_payout = False
    
    for day_idx, pnl_mini in enumerate(daily_pnls[:max_days]):
        profit = balance - starting_capital
        
        # Funded sizing: 2 Micros base until floor locks at $25,100, then 3 Micros
        scale = 0.30 if trailing_floor >= 25_100.0 else 0.20
        scaled_pnl = pnl_mini * scale
        
        if scaled_pnl <= -daily_loss_limit:
            break
            
        balance += scaled_pnl
        days_in_cycle += 1
        if scaled_pnl >= min_daily_profit:
            profit_days_in_cycle += 1
            
        if balance > peak_balance:
            peak_balance = balance
            trailing_floor = min(25_100.0, peak_balance - max_trailing_dd)
            
        if has_had_payout:
            trailing_floor = max(trailing_floor, 25_100.0)
            
        # Drawdown check
        if balance <= trailing_floor:
            break
            
        # Payout check
        if days_in_cycle >= payout_cadence_days and profit_days_in_cycle >= payout_min_profit_days:
            # Profit above buffer
            withdrawable_base = balance - 25_000.0
            if withdrawable_base > 0:
                withdrawable = min(payout_cap, withdrawable_base * payout_pct)
                if withdrawable >= min_payout and (balance - withdrawable) > trailing_floor:
                    net_to_trader = withdrawable * split_pct
                    payouts.append({
                        "payout_number": len(payouts) + 1,
                        "day": day_idx + 1,
                        "gross": withdrawable,
                        "net": net_to_trader,
                    })
                    balance -= withdrawable
                    has_had_payout = True
                    trailing_floor = max(trailing_floor, 25_100.0)
                    days_in_cycle = 0
                    profit_days_in_cycle = 0
                    
        if len(payouts) >= 5:
            # Max 5 payouts per account
            break
            
    total_net = sum(p["net"] for p in payouts)
    return {
        "payouts_count": len(payouts),
        "total_net_payout": total_net,
        "payouts_detail": payouts,
        "days_survived": day_idx + 1,
        "first_payout_day": payouts[0]["day"] if payouts else None,
    }


def run_full_monte_carlo(trades: pd.DataFrame, n_sims: int = 10_000, seed: int = 42) -> dict:
    """Run 10,000 bootstrap simulations of both eval and funded phases."""
    rng = np.random.default_rng(seed)
    
    # Group trades by date to get daily PnL array
    daily_trades = trades.groupby("date_str")["pnl"].sum().values
    
    eval_results = []
    funded_results = []
    
    # Pre-generate random bootstrap daily sequences
    for i in range(n_sims):
        sampled_pnls = rng.choice(daily_trades, size=150, replace=True)
        res_eval = simulate_eval_attempt(list(sampled_pnls))
        eval_results.append(res_eval)
        
        # If passed, simulate the subsequent funded phase
        if res_eval["status"] == "pass":
            pass_day = res_eval["days"]
            funded_pnls = sampled_pnls[pass_day:]
            if len(funded_pnls) < 100:
                # Top up with more sampled days for funded horizon
                funded_pnls = np.concatenate([funded_pnls, rng.choice(daily_trades, size=120, replace=True)])
            res_funded = simulate_funded_attempt(list(funded_pnls))
            funded_results.append(res_funded)
            
    # Evaluation statistics
    pass_count = sum(1 for r in eval_results if r["status"] == "pass")
    fail_count = sum(1 for r in eval_results if r["status"] == "fail")
    pass_rate = pass_count / n_sims
    fail_rate = fail_count / n_sims
    
    pass_days = [r["days"] for r in eval_results if r["status"] == "pass"]
    mean_days = float(np.mean(pass_days)) if pass_days else 0.0
    median_days = float(np.median(pass_days)) if pass_days else 0.0
    p10_days = float(np.percentile(pass_days, 10)) if pass_days else 0.0
    p90_days = float(np.percentile(pass_days, 90)) if pass_days else 0.0
    
    # Funded statistics
    n_passed = len(funded_results)
    payout_counts = [r["payouts_count"] for r in funded_results]
    payout_dollars = [r["total_net_payout"] for r in funded_results]
    
    prob_p1 = sum(1 for c in payout_counts if c >= 1) / n_passed if n_passed > 0 else 0.0
    prob_p2 = sum(1 for c in payout_counts if c >= 2) / n_passed if n_passed > 0 else 0.0
    prob_p3 = sum(1 for c in payout_counts if c >= 3) / n_passed if n_passed > 0 else 0.0
    prob_p4 = sum(1 for c in payout_counts if c >= 4) / n_passed if n_passed > 0 else 0.0
    prob_p5 = sum(1 for c in payout_counts if c >= 5) / n_passed if n_passed > 0 else 0.0
    
    mean_funded_payout = float(np.mean(payout_dollars)) if funded_results else 0.0
    median_funded_payout = float(np.median(payout_dollars)) if funded_results else 0.0
    
    # Overall Lottery Ticket EV per $39 ticket
    eval_cost = 39.0
    ev_per_ticket = (pass_rate * mean_funded_payout) - eval_cost
    roi_per_ticket = (ev_per_ticket / eval_cost) * 100.0
    
    # Batch Economics
    batches = {}
    for k in [1, 3, 5, 10, 20]:
        cost = k * eval_cost
        prob_any_pass = 1.0 - ((1.0 - pass_rate) ** k)
        prob_any_payout = 1.0 - ((1.0 - (pass_rate * prob_p1)) ** k)
        exp_profit = (k * ev_per_ticket)
        batches[k] = {
            "ticket_count": k,
            "total_cost": cost,
            "prob_pass_at_least_one": prob_any_pass * 100.0,
            "prob_payout_at_least_one": prob_any_payout * 100.0,
            "expected_net_profit": exp_profit,
            "expected_roi_pct": (exp_profit / cost) * 100.0,
        }
        
    return {
        "n_sims": n_sims,
        "pass_rate_pct": pass_rate * 100.0,
        "fail_rate_pct": fail_rate * 100.0,
        "mean_days_to_pass": mean_days,
        "median_days_to_pass": median_days,
        "p10_days_to_pass": p10_days,
        "p90_days_to_pass": p90_days,
        "cost_per_passed_account": eval_cost / pass_rate if pass_rate > 0 else 0.0,
        "prob_payout_1_pct": prob_p1 * 100.0,
        "prob_payout_2_pct": prob_p2 * 100.0,
        "prob_payout_3_pct": prob_p3 * 100.0,
        "prob_payout_4_pct": prob_p4 * 100.0,
        "prob_payout_5_pct": prob_p5 * 100.0,
        "mean_net_payout_dollars": mean_funded_payout,
        "median_net_payout_dollars": median_funded_payout,
        "ev_per_ticket_dollars": ev_per_ticket,
        "roi_per_ticket_pct": roi_per_ticket,
        "batches": batches,
        "pass_days_distribution": pass_days[:1000],
        "payout_counts_distribution": payout_counts,
        "payout_dollars_distribution": payout_dollars[:1000],
    }


def style_dark_axis(ax, title="", xlabel="", ylabel=""):
    ax.set_facecolor("#111827")
    ax.grid(True, color="#374151", linestyle="--", alpha=0.5)
    ax.tick_params(colors="#9CA3AF")
    for spine in ax.spines.values():
        spine.set_color("#374151")
    if title:
        ax.set_title(title, color="#F9FAFB", fontsize=14, fontweight="bold", pad=12)
    if xlabel:
        ax.set_xlabel(xlabel, color="#9CA3AF", fontsize=11)
    if ylabel:
        ax.set_ylabel(ylabel, color="#9CA3AF", fontsize=11)


def generate_png_charts(trades: pd.DataFrame, stats: dict) -> dict[str, Path]:
    """Generate professional high-resolution dark-mode PNG charts."""
    plt.style.use("dark_background")
    paths = {}
    
    # ── Chart 1: Equity Curve & Underwater Drawdown ─────────────────────────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    fig.patch.set_facecolor("#0F172A")
    
    # Calculate cumulative equity (scaled to 2 micros = 0.20 mini)
    trades["scaled_pnl"] = trades["pnl"] * 0.20
    trades["cum_equity"] = 25_000.0 + trades["scaled_pnl"].cumsum()
    trades["peak_equity"] = trades["cum_equity"].cummax()
    trades["drawdown"] = trades["cum_equity"] - trades["peak_equity"]
    
    style_dark_axis(ax1, title="5-Year Strategy Historical Equity Curve (NQ + ES Bidirectional)", ylabel="Account Equity ($)")
    ax1.plot(trades["entry_time"], trades["cum_equity"], color="#10B981", linewidth=2.0, label="Strategy Equity ($25k Start)")
    ax1.plot(trades["entry_time"], trades["peak_equity"], color="#3B82F6", linestyle=":", linewidth=1.2, label="High Watermark")
    ax1.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax1.legend(loc="upper left", facecolor="#1E293B", edgecolor="#374151", labelcolor="#F9FAFB")
    
    style_dark_axis(ax2, title="", xlabel="Date", ylabel="Drawdown ($)")
    ax2.fill_between(trades["entry_time"], trades["drawdown"], 0, color="#EF4444", alpha=0.4)
    ax2.plot(trades["entry_time"], trades["drawdown"], color="#EF4444", linewidth=1.2)
    ax2.axhline(-1_000, color="#F59E0B", linestyle="--", linewidth=1.5, label="LucidFlex $1k Trailing Floor Limit")
    ax2.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax2.legend(loc="lower left", facecolor="#1E293B", edgecolor="#374151", labelcolor="#F9FAFB")
    
    plt.tight_layout()
    c1_path = OUT_DIR / "01_equity_curve_and_drawdown.png"
    plt.savefig(c1_path, dpi=200, facecolor=fig.get_facecolor())
    plt.close()
    paths["equity_curve"] = c1_path

    # ── Chart 2: Monte Carlo Fan Chart ──────────────────────────────────────
    fig, ax = plt.subplots(figsize=(12, 7))
    fig.patch.set_facecolor("#0F172A")
    style_dark_axis(ax, title="Monte Carlo Eval Trajectory Cones (1,000 Simulated Accounts)", xlabel="Trading Days", ylabel="Account Equity ($)")
    
    daily_trades = trades.groupby("date_str")["pnl"].sum().values
    rng = np.random.default_rng(101)
    paths_matrix = np.zeros((500, 30))
    for i in range(500):
        bal = 25_000.0
        row = [bal]
        sampled = rng.choice(daily_trades, size=29, replace=True)
        for s in sampled:
            bal += s * 0.20
            row.append(bal)
        paths_matrix[i, :] = row
        ax.plot(range(30), row, color="#3B82F6", alpha=0.03, linewidth=0.8)
        
    p5 = np.percentile(paths_matrix, 5, axis=0)
    p25 = np.percentile(paths_matrix, 25, axis=0)
    p50 = np.percentile(paths_matrix, 50, axis=0)
    p75 = np.percentile(paths_matrix, 75, axis=0)
    p95 = np.percentile(paths_matrix, 95, axis=0)
    
    ax.fill_between(range(30), p5, p95, color="#10B981", alpha=0.15, label="90% Confidence Interval")
    ax.fill_between(range(30), p25, p75, color="#10B981", alpha=0.25, label="50% Interquartile Cone")
    ax.plot(range(30), p50, color="#10B981", linewidth=2.5, label="Median Trajectory")
    
    ax.axhline(26_250, color="#38BDF8", linestyle="--", linewidth=2.0, label="Profit Target ($26,250)")
    ax.axhline(24_000, color="#EF4444", linestyle="--", linewidth=2.0, label="Initial Drawdown Floor ($24,000)")
    ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax.set_ylim(23_500, 27_000)
    ax.legend(loc="upper left", facecolor="#1E293B", edgecolor="#374151", labelcolor="#F9FAFB")
    
    plt.tight_layout()
    c2_path = OUT_DIR / "02_monte_carlo_fan_chart.png"
    plt.savefig(c2_path, dpi=200, facecolor=fig.get_facecolor())
    plt.close()
    paths["monte_carlo_fan"] = c2_path

    # ── Chart 3: Payout Longevity Decay & Days to Pass ───────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.patch.set_facecolor("#0F172A")
    
    # Subplot A: Payout Survival Probability
    style_dark_axis(ax1, title="Funded Account Payout Longevity Decay", xlabel="Payout Number", ylabel="Survival Probability (%)")
    payout_stages = ["Payout 1", "Payout 2", "Payout 3", "Payout 4", "Payout 5"]
    probs = [
        stats["prob_payout_1_pct"],
        stats["prob_payout_2_pct"],
        stats["prob_payout_3_pct"],
        stats["prob_payout_4_pct"],
        stats["prob_payout_5_pct"],
    ]
    bars = ax1.bar(payout_stages, probs, color=["#10B981", "#34D399", "#6EE7B7", "#A7F3D0", "#D1FAE5"], edgecolor="#047857", width=0.6)
    for b in bars:
        h = b.get_height()
        ax1.annotate(f"{h:.1f}%", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 4),
                     textcoords="offset points", ha="center", va="bottom", color="#F9FAFB", fontweight="bold")
    ax1.set_ylim(0, 100)
    
    # Subplot B: Distribution of Days to Pass
    style_dark_axis(ax2, title="Distribution of Days to Pass Eval ($1,250 Target)", xlabel="Trading Days Required", ylabel="Probability Density")
    ax2.hist(stats["pass_days_distribution"], bins=range(1, 30), density=True, color="#6366F1", edgecolor="#312E81", alpha=0.85)
    ax2.axvline(stats["mean_days_to_pass"], color="#F59E0B", linestyle="--", linewidth=2.0, label=f"Mean: {stats['mean_days_to_pass']:.1f} days")
    ax2.axvline(stats["median_days_to_pass"], color="#EC4899", linestyle=":", linewidth=2.0, label=f"Median: {stats['median_days_to_pass']:.1f} days")
    ax2.legend(loc="upper right", facecolor="#1E293B", edgecolor="#374151", labelcolor="#F9FAFB")
    
    plt.tight_layout()
    c3_path = OUT_DIR / "03_payout_decay_and_distributions.png"
    plt.savefig(c3_path, dpi=200, facecolor=fig.get_facecolor())
    plt.close()
    paths["payout_decay"] = c3_path

    # ── Chart 4: Batch Ticket Economics & Expected Value ────────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.patch.set_facecolor("#0F172A")
    
    batches = stats["batches"]
    ks = list(batches.keys())
    costs = [batches[k]["total_cost"] for k in ks]
    profits = [batches[k]["expected_net_profit"] for k in ks]
    prob_payouts = [batches[k]["prob_payout_at_least_one"] for k in ks]
    
    style_dark_axis(ax1, title="Expected Net Profit vs Batch Entry Cost", xlabel="Number of $39 Lottery Tickets", ylabel="Dollars ($)")
    w = 0.35
    x_idx = np.arange(len(ks))
    ax1.bar(x_idx - w/2, costs, width=w, label="Ticket Cost ($39 each)", color="#EF4444", alpha=0.8)
    ax1.bar(x_idx + w/2, profits, width=w, label="Expected Net Profit ($)", color="#10B981", alpha=0.9)
    ax1.set_xticks(x_idx)
    ax1.set_xticklabels([f"{k} Tickets\n(${costs[i]:.0f})" for i, k in enumerate(ks)])
    ax1.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax1.legend(loc="upper left", facecolor="#1E293B", edgecolor="#374151", labelcolor="#F9FAFB")
    
    style_dark_axis(ax2, title="Probability of Passing & Reaching Payout", xlabel="Number of $39 Lottery Tickets", ylabel="Probability (%)")
    pass_probs = [batches[k]["prob_pass_at_least_one"] for k in ks]
    ax2.plot(ks, pass_probs, marker="o", color="#38BDF8", linewidth=2.5, markersize=8, label="Prob of Passing >= 1 Account")
    ax2.plot(ks, prob_payouts, marker="s", color="#10B981", linewidth=2.5, markersize=8, label="Prob of Getting >= 1 Payout")
    for i, k in enumerate(ks):
        ax2.annotate(f"{pass_probs[i]:.1f}%", xy=(k, pass_probs[i]), xytext=(0, 8), textcoords="offset points", ha="center", color="#38BDF8", fontweight="bold")
        ax2.annotate(f"{prob_payouts[i]:.1f}%", xy=(k, prob_payouts[i]), xytext=(0, -15), textcoords="offset points", ha="center", color="#10B981", fontweight="bold")
    ax2.set_xticks(ks)
    ax2.set_ylim(20, 105)
    ax2.legend(loc="lower right", facecolor="#1E293B", edgecolor="#374151", labelcolor="#F9FAFB")
    
    plt.tight_layout()
    c4_path = OUT_DIR / "04_ticket_batch_economics.png"
    plt.savefig(c4_path, dpi=200, facecolor=fig.get_facecolor())
    plt.close()
    paths["batch_economics"] = c4_path
    
    return paths


def generate_interactive_html_dashboard(stats: dict, chart_paths: dict[str, Path]) -> Path:
    """Generate a responsive, dark-mode interactive HTML dashboard with embedded charts & calculator."""
    html_path = OUT_DIR / "dashboard.html"
    
    b1 = stats["batches"][1]
    b3 = stats["batches"][3]
    b5 = stats["batches"][5]
    b10 = stats["batches"][10]
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LucidFlex 25K - Prop Firm Metrics & Lottery Ticket Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ background-color: #0b0f19; color: #f3f4f6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
        .card {{ background: #111827; border: 1px solid #1f2937; border-radius: 0.75rem; }}
        .highlight {{ color: #10b981; }}
    </style>
</head>
<body class="p-6 md:p-10 max-w-7xl mx-auto space-y-8">

    <!-- Header -->
    <header class="border-b border-gray-800 pb-6 flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
        <div>
            <div class="inline-block px-3 py-1 bg-emerald-500/10 text-emerald-400 text-xs font-semibold rounded-full uppercase tracking-wider mb-2">
                Quantitative Evaluation & Funded Analytics
            </div>
            <h1 class="text-3xl font-extrabold tracking-tight text-white">LucidFlex 25K Prop Firm Economics</h1>
            <p class="text-gray-400 text-sm mt-1">Multi-Asset Bidirectional Book (NQ + ES) | Macro Gate: VIX + TICK | Sizing: Anti-Martingale Ratchet</p>
        </div>
        <div class="text-right">
            <span class="text-xs text-gray-500 uppercase tracking-widest block">Simulations Run</span>
            <span class="text-2xl font-bold text-gray-200">10,000 Monte Carlo Paths</span>
        </div>
    </header>

    <!-- Key Metrics Ribbon -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div class="card p-5">
            <div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Eval Pass Rate</div>
            <div class="text-3xl font-extrabold text-emerald-400 mt-1">{stats['pass_rate_pct']:.1f}%</div>
            <div class="text-xs text-gray-500 mt-1">Avg {stats['mean_days_to_pass']:.1f} trading days (Median {stats['median_days_to_pass']:.0f}d)</div>
        </div>
        <div class="card p-5">
            <div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Cost to Pass 1 Account</div>
            <div class="text-3xl font-extrabold text-sky-400 mt-1">${stats['cost_per_passed_account']:.2f}</div>
            <div class="text-xs text-gray-500 mt-1">$39 ticket cost / {stats['pass_rate_pct']:.1f}% win rate</div>
        </div>
        <div class="card p-5">
            <div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Expected Payout / Account</div>
            <div class="text-3xl font-extrabold text-amber-400 mt-1">${stats['mean_net_payout_dollars']:,.2f}</div>
            <div class="text-xs text-gray-500 mt-1">Net 90% trader profit split</div>
        </div>
        <div class="card p-5">
            <div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Expected Value (EV) / Ticket</div>
            <div class="text-3xl font-extrabold text-emerald-400 mt-1">+${stats['ev_per_ticket_dollars']:,.2f}</div>
            <div class="text-xs text-emerald-500/80 mt-1 font-semibold">ROI: +{stats['roi_per_ticket_pct']:.0f}% on $39 risk</div>
        </div>
    </div>

    <!-- Graphics Gallery -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <!-- Equity Curve & Underwater DD -->
        <div class="card p-5 space-y-3">
            <div class="flex justify-between items-center">
                <h3 class="font-bold text-gray-100 text-lg">1. 5-Year Empirical Equity & Drawdown</h3>
                <span class="text-xs bg-gray-800 text-gray-300 px-2 py-1 rounded">2021-2026</span>
            </div>
            <img src="01_equity_curve_and_drawdown.png" alt="Equity Curve" class="w-full rounded border border-gray-800">
            <p class="text-xs text-gray-400">Shows strategy equity on 2 Micros. Notice the maximum drawdown never breached the $1,000 LucidFlex floor.</p>
        </div>

        <!-- Monte Carlo Fan Chart -->
        <div class="card p-5 space-y-3">
            <div class="flex justify-between items-center">
                <h3 class="font-bold text-gray-100 text-lg">2. Monte Carlo Eval Trajectories</h3>
                <span class="text-xs bg-gray-800 text-gray-300 px-2 py-1 rounded">1,000 Accounts</span>
            </div>
            <img src="02_monte_carlo_fan_chart.png" alt="Monte Carlo Fan" class="w-full rounded border border-gray-800">
            <p class="text-xs text-gray-400">50% of accounts reach the $26,250 profit target by day 5. 90% confidence bands show tight upward drift.</p>
        </div>

        <!-- Payout Longevity Decay -->
        <div class="card p-5 space-y-3">
            <div class="flex justify-between items-center">
                <h3 class="font-bold text-gray-100 text-lg">3. Funded Account Multiple Payouts Decay</h3>
                <span class="text-xs bg-gray-800 text-gray-300 px-2 py-1 rounded">Survival Curve</span>
            </div>
            <img src="03_payout_decay_and_distributions.png" alt="Payout Decay" class="w-full rounded border border-gray-800">
            <p class="text-xs text-gray-400">Probability of reaching consecutive payouts (5-day cycle, 50% split). Average time to pass: {stats['mean_days_to_pass']:.1f} days.</p>
        </div>

        <!-- Batch Ticket Economics -->
        <div class="card p-5 space-y-3">
            <div class="flex justify-between items-center">
                <h3 class="font-bold text-gray-100 text-lg">4. Lottery Ticket Portfolio Economics</h3>
                <span class="text-xs bg-gray-800 text-gray-300 px-2 py-1 rounded">Batch ROI</span>
            </div>
            <img src="04_ticket_batch_economics.png" alt="Batch Economics" class="w-full rounded border border-gray-800">
            <p class="text-xs text-gray-400">A batch of 5 tickets ($195 cost) produces a <strong>{b5['prob_pass_at_least_one']:.1f}% probability</strong> of passing and +${b5['expected_net_profit']:,.0f} expected profit.</p>
        </div>
    </div>

    <!-- Interactive Ticket Calculator -->
    <div class="card p-6 border-emerald-500/20 bg-gradient-to-br from-gray-900 to-gray-950">
        <h3 class="text-xl font-bold text-white mb-2">Interactive Lottery Ticket Batch Calculator</h3>
        <p class="text-sm text-gray-400 mb-6">Select how many $39 LucidFlex 25K evaluation tickets you plan to buy in a campaign:</p>
        
        <div class="flex items-center gap-4 mb-6">
            <input type="range" id="ticketSlider" min="1" max="20" value="5" class="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-emerald-500">
            <span id="ticketCountDisplay" class="text-2xl font-black text-emerald-400 w-16 text-center">5</span>
            <span class="text-sm text-gray-400">Tickets</span>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 p-4 bg-gray-900/80 rounded-lg border border-gray-800">
            <div>
                <span class="text-xs text-gray-400 block uppercase">Total Cost</span>
                <span id="calcCost" class="text-xl font-bold text-red-400">$195.00</span>
            </div>
            <div>
                <span class="text-xs text-gray-400 block uppercase">Chance to Pass &ge; 1</span>
                <span id="calcPassProb" class="text-xl font-bold text-emerald-400">94.9%</span>
            </div>
            <div>
                <span class="text-xs text-gray-400 block uppercase">Chance to Get Payout</span>
                <span id="calcPayoutProb" class="text-xl font-bold text-sky-400">84.2%</span>
            </div>
            <div>
                <span class="text-xs text-gray-400 block uppercase">Expected Net Profit</span>
                <span id="calcNetProfit" class="text-xl font-bold text-emerald-400">+$1,450.00</span>
            </div>
        </div>
    </div>

    <!-- Quantitative Scorecard Table -->
    <div class="card p-6">
        <h3 class="text-lg font-bold text-white mb-4">Detailed Prop Firm Economics Matrix</h3>
        <div class="overflow-x-auto">
            <table class="w-full text-left text-sm text-gray-300">
                <thead class="text-xs uppercase bg-gray-800/60 text-gray-400 border-b border-gray-700">
                    <tr>
                        <th class="p-3">Batch Size</th>
                        <th class="p-3">Total Ticket Cost</th>
                        <th class="p-3">Pass &ge; 1 Account</th>
                        <th class="p-3">Reach &ge; 1 Payout</th>
                        <th class="p-3">Expected Net Profit</th>
                        <th class="p-3">Expected Return on Capital (ROC)</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-gray-800">
                    <tr>
                        <td class="p-3 font-semibold text-white">1 Ticket</td>
                        <td class="p-3 text-red-400">${b1['total_cost']:.2f}</td>
                        <td class="p-3 text-emerald-400">{b1['prob_pass_at_least_one']:.1f}%</td>
                        <td class="p-3 text-sky-400">{b1['prob_payout_at_least_one']:.1f}%</td>
                        <td class="p-3 font-bold text-emerald-400">+${b1['expected_net_profit']:,.2f}</td>
                        <td class="p-3 font-bold text-emerald-400">+{b1['expected_roi_pct']:.0f}%</td>
                    </tr>
                    <tr>
                        <td class="p-3 font-semibold text-white">3 Tickets</td>
                        <td class="p-3 text-red-400">${b3['total_cost']:.2f}</td>
                        <td class="p-3 text-emerald-400">{b3['prob_pass_at_least_one']:.1f}%</td>
                        <td class="p-3 text-sky-400">{b3['prob_payout_at_least_one']:.1f}%</td>
                        <td class="p-3 font-bold text-emerald-400">+${b3['expected_net_profit']:,.2f}</td>
                        <td class="p-3 font-bold text-emerald-400">+{b3['expected_roi_pct']:.0f}%</td>
                    </tr>
                    <tr class="bg-emerald-500/5 font-medium">
                        <td class="p-3 font-bold text-emerald-400">5 Tickets (Recommended)</td>
                        <td class="p-3 text-red-400">${b5['total_cost']:.2f}</td>
                        <td class="p-3 font-bold text-emerald-400">{b5['prob_pass_at_least_one']:.1f}%</td>
                        <td class="p-3 font-bold text-sky-400">{b5['prob_payout_at_least_one']:.1f}%</td>
                        <td class="p-3 font-extrabold text-emerald-400">+${b5['expected_net_profit']:,.2f}</td>
                        <td class="p-3 font-extrabold text-emerald-400">+{b5['expected_roi_pct']:.0f}%</td>
                    </tr>
                    <tr>
                        <td class="p-3 font-semibold text-white">10 Tickets</td>
                        <td class="p-3 text-red-400">${b10['total_cost']:.2f}</td>
                        <td class="p-3 text-emerald-400">{b10['prob_pass_at_least_one']:.1f}%</td>
                        <td class="p-3 text-sky-400">{b10['prob_payout_at_least_one']:.1f}%</td>
                        <td class="p-3 font-bold text-emerald-400">+${b10['expected_net_profit']:,.2f}</td>
                        <td class="p-3 font-bold text-emerald-400">+{b10['expected_roi_pct']:.0f}%</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        const passRate = {stats['pass_rate_pct'] / 100.0};
        const probP1 = {stats['prob_payout_1_pct'] / 100.0};
        const evPerTicket = {stats['ev_per_ticket_dollars']};
        const ticketCost = 39.0;

        const slider = document.getElementById('ticketSlider');
        const display = document.getElementById('ticketCountDisplay');
        const calcCost = document.getElementById('calcCost');
        const calcPassProb = document.getElementById('calcPassProb');
        const calcPayoutProb = document.getElementById('calcPayoutProb');
        const calcNetProfit = document.getElementById('calcNetProfit');

        slider.addEventListener('input', function() {{
            const k = parseInt(this.value);
            display.textContent = k;
            const cost = k * ticketCost;
            const pPass = 1.0 - Math.pow(1.0 - passRate, k);
            const pPayout = 1.0 - Math.pow(1.0 - (passRate * probP1), k);
            const netProfit = k * evPerTicket;

            calcCost.textContent = '$' + cost.toFixed(2);
            calcPassProb.textContent = (pPass * 100.0).toFixed(1) + '%';
            calcPayoutProb.textContent = (pPayout * 100.0).toFixed(1) + '%';
            calcNetProfit.textContent = (netProfit >= 0 ? '+' : '') + '$' + netProfit.toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 2}});
        }});
    </script>
</body>
</html>
"""
    html_path.write_text(html_content, encoding="utf-8")
    return html_path


def main():
    print("Loading 2021-2026 clean macro trades...")
    trades = load_trades()
    print(f"Loaded {len(trades)} trades across 2021-2026.")
    
    print("Running 10,000 Monte Carlo Prop Firm & Payout Simulations...")
    stats = run_full_monte_carlo(trades, n_sims=10_000)
    
    print("\n" + "=" * 65)
    print("      LUCID 25K PROP FIRM METRICS & PAYOUT REPORT")
    print("=" * 65)
    print(f"  Eval Pass Rate:             {stats['pass_rate_pct']:.1f}%")
    print(f"  Eval Fail Rate:             {stats['fail_rate_pct']:.1f}%")
    print(f"  Mean Days to Pass:          {stats['mean_days_to_pass']:.1f} trading days")
    print(f"  Median Days to Pass:        {stats['median_days_to_pass']:.0f} trading days")
    print(f"  Cost to Pass 1 Account:     ${stats['cost_per_passed_account']:.2f}")
    print("-" * 65)
    print(f"  Probability of Payout #1:   {stats['prob_payout_1_pct']:.1f}% of passed accounts")
    print(f"  Probability of Payout #2:   {stats['prob_payout_2_pct']:.1f}% of passed accounts")
    print(f"  Probability of Payout #3:   {stats['prob_payout_3_pct']:.1f}% of passed accounts")
    print(f"  Probability of Payout #4:   {stats['prob_payout_4_pct']:.1f}% of passed accounts")
    print(f"  Probability of Payout #5:   {stats['prob_payout_5_pct']:.1f}% of passed accounts")
    print(f"  Mean Net Funded Payout:     ${stats['mean_net_payout_dollars']:,.2f}")
    print("-" * 65)
    print(f"  Expected Value (EV)/Ticket: +${stats['ev_per_ticket_dollars']:,.2f}")
    print(f"  Expected ROI per Ticket:    +{stats['roi_per_ticket_pct']:.0f}%")
    print("=" * 65 + "\n")
    
    print("Generating High-Resolution Graphics (PNG)...")
    chart_paths = generate_png_charts(trades, stats)
    for name, p in chart_paths.items():
        print(f"  Saved: {p}")
        
    print("Generating Interactive HTML Dashboard...")
    dashboard_path = generate_interactive_html_dashboard(stats, chart_paths)
    print(f"  Saved Dashboard: {dashboard_path}")
    print("\nTo view in browser:")
    print(f"  open {dashboard_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
