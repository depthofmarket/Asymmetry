#!/usr/bin/env python3
"""
10,000-Path Monte Carlo Bootstrap Corridor & Forward Test Overlay (Step 08).

Implements Step 08 of the Belfort Systematic Trading Framework (2026):
1. Bootstrap 10,000 equity paths from canonical backtest trade returns (543 trades, 2021-2026).
2. Compute 5th, 25th, 50th, 75th, and 95th percentile equity corridors across trades 0..30.
3. Overlay actual forward test equity trajectory on top of the corridor.
4. Evaluate regime adherence:
   - >= 25th percentile: Normal Expectancy (Confirmed Edge)
   - 5th - 25th percentile: Tail Variance (Warning)
   - < 5th percentile: Structural Regime Shift (Stop Trading)
5. Save high-resolution dark-mode visualization to results/forward_test/live_vs_monte_carlo_corridor.png.
"""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_TRADES_PATH = REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"
FORWARD_TRADES_PATH = REPO_ROOT / "results/forward_test/demo_trades_ledger.csv"
OUTPUT_DIR = REPO_ROOT / "results/forward_test"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def run_monte_carlo_bootstrap(
    n_sims: int = 10000,
    n_trades: int = 30,
    starting_capital: float = 25000.0,
    profit_target: float = 1250.0,
    max_trailing_dd: float = 1000.0,
    floor_lock: float = 25100.0,
    seed: int = 42,
) -> dict:
    if not CANONICAL_TRADES_PATH.exists():
        raise FileNotFoundError(f"Canonical trades parquet not found at {CANONICAL_TRADES_PATH}")

    df_hist = pd.read_parquet(CANONICAL_TRADES_PATH)
    # Per-micro PnL = net_dollars_micro / contracts
    per_contract_pnl = (df_hist["net_dollars_micro"] / df_hist["contracts"].clip(lower=1)).to_numpy(float)
    n_hist = len(per_contract_pnl)

    rng = np.random.default_rng(seed)
    sampled_indices = rng.integers(0, n_hist, size=(n_sims, n_trades))
    sampled_per_micro = per_contract_pnl[sampled_indices]

    # Trajectories
    balances = np.zeros((n_sims, n_trades + 1), dtype=float)
    balances[:, 0] = starting_capital
    peak_balances = np.full(n_sims, starting_capital, dtype=float)
    trailing_floors = np.full(n_sims, starting_capital - max_trailing_dd, dtype=float)

    is_passed = np.zeros(n_sims, dtype=bool)
    is_failed = np.zeros(n_sims, dtype=bool)
    pass_trade_idx = np.full(n_sims, -1, dtype=int)
    fail_trade_idx = np.full(n_sims, -1, dtype=int)

    for t in range(n_trades):
        active_mask = (~is_passed) & (~is_failed)
        if not np.any(active_mask):
            balances[:, t + 1 :] = balances[:, t : t + 1]
            break

        current_bal = balances[:, t]
        profit = current_bal - starting_capital

        # Ratchet sizing: Tier 1 (<$200) -> 2 micros, Tier 2 ($200-$500) -> 3 micros, Tier 3 (>=$500) -> 4 micros
        micros = np.where(profit >= 500.0, 4, np.where(profit >= 200.0, 3, 2))

        # Safe CPPI de-levering: if cushion < 400, cut to 1 micro
        cushion = current_bal - trailing_floors
        micros = np.where(cushion < 400.0, 1, micros)

        trade_pnl = sampled_per_micro[:, t] * micros
        next_bal = current_bal.copy()
        next_bal[active_mask] += trade_pnl[active_mask]

        # Update peaks and trailing floors
        peak_balances = np.maximum(peak_balances, next_bal)
        new_floors = np.minimum(floor_lock, peak_balances - max_trailing_dd)
        trailing_floors = np.maximum(trailing_floors, new_floors)

        # Check pass
        passed_now = active_mask & ((next_bal - starting_capital) >= profit_target)
        is_passed[passed_now] = True
        pass_trade_idx[passed_now] = t + 1

        # Check fail
        failed_now = active_mask & (~passed_now) & (next_bal <= trailing_floors)
        is_failed[failed_now] = True
        fail_trade_idx[failed_now] = t + 1

        # Freeze passed/failed balances
        balances[:, t + 1] = next_bal

    # Compute percentile corridors across trades 0..n_trades
    percentiles = {
        "p05": np.percentile(balances, 5, axis=0).tolist(),
        "p25": np.percentile(balances, 25, axis=0).tolist(),
        "p50": np.percentile(balances, 50, axis=0).tolist(),
        "p75": np.percentile(balances, 75, axis=0).tolist(),
        "p95": np.percentile(balances, 95, axis=0).tolist(),
        "mean": np.mean(balances, axis=0).tolist(),
    }

    # Cumulative pass/fail probabilities
    pass_prob = [float(np.mean(is_passed & (pass_trade_idx <= t) & (pass_trade_idx > 0))) for t in range(n_trades + 1)]
    fail_prob = [float(np.mean(is_failed & (fail_trade_idx <= t) & (fail_trade_idx > 0))) for t in range(n_trades + 1)]

    # Load live forward test trades
    live_equity = [starting_capital]
    live_ranks = [50.0]
    live_dates = ["Start"]
    if FORWARD_TRADES_PATH.exists():
        df_live = pd.read_csv(FORWARD_TRADES_PATH)
        if not df_live.empty and "account_balance_after" in df_live.columns:
            for idx_live, row in df_live.iterrows():
                bal = float(row["account_balance_after"])
                live_equity.append(bal)
                t_step = len(live_equity) - 1
                if t_step <= n_trades:
                    rank = float((balances[:, t_step] < bal).mean() * 100.0)
                    live_ranks.append(rank)
                live_dates.append(str(row["date"]))

    # Current regime diagnosis
    curr_t = len(live_equity) - 1
    curr_bal = live_equity[-1]
    curr_rank = live_ranks[-1]

    if curr_t > 0 and curr_t <= n_trades:
        p05_val = percentiles["p05"][curr_t]
        p25_val = percentiles["p25"][curr_t]
        p75_val = percentiles["p75"][curr_t]
        if curr_bal >= p25_val:
            regime_status = "NORMAL_EXPECTANCY_CONFIRMED"
            regime_color = "#10B981"  # Emerald
            regime_verdict = f"Live equity (${curr_bal:,.2f}) is at the {curr_rank:.1f}th percentile (>= 25th percentile). Strategy edge is operating within normal expected distribution."
        elif curr_bal >= p05_val:
            regime_status = "TAIL_VARIANCE_WARNING"
            regime_color = "#F59E0B"  # Amber
            regime_verdict = f"Live equity (${curr_bal:,.2f}) is at the {curr_rank:.1f}th percentile (between 5th and 25th percentile). Edge intact but experiencing tail friction."
        else:
            regime_status = "STRUCTURAL_REGIME_SHIFT_HALT"
            regime_color = "#EF4444"  # Red
            regime_verdict = f"CRITICAL: Live equity (${curr_bal:,.2f}) has dropped below 5th percentile corridor (${p05_val:,.2f}). Per Belfort Step 08, halt trading immediately."
    else:
        regime_status = "STANDING_BY"
        regime_color = "#38BDF8"
        regime_verdict = "Standing by for live forward test trades."

    return {
        "n_sims": n_sims,
        "n_trades": n_trades,
        "percentiles": percentiles,
        "pass_prob": pass_prob,
        "fail_prob": fail_prob,
        "live_equity": live_equity,
        "live_ranks": live_ranks,
        "live_dates": live_dates,
        "current_balance": curr_bal,
        "current_rank": curr_rank,
        "regime_status": regime_status,
        "regime_color": regime_color,
        "regime_verdict": regime_verdict,
        "overall_pass_rate": float(is_passed.mean() * 100.0),
        "overall_fail_rate": float(is_failed.mean() * 100.0),
    }


def plot_corridor(mc_data: dict, output_path: Path | None = None) -> Path:
    if output_path is None:
        output_path = OUTPUT_DIR / "live_vs_monte_carlo_corridor.png"

    pcts = mc_data["percentiles"]
    n_trades = mc_data["n_trades"]
    x = np.arange(n_trades + 1)

    p05 = np.array(pcts["p05"])
    p25 = np.array(pcts["p25"])
    p50 = np.array(pcts["p50"])
    p75 = np.array(pcts["p75"])
    p95 = np.array(pcts["p95"])

    live_eq = mc_data["live_equity"]
    live_x = np.arange(len(live_eq))

    # Institutional Clean White Theme
    plt.style.use("default")
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(13, 8.5), dpi=300, gridspec_kw={"height_ratios": [3.2, 1.0]}, sharex=True
    )
    fig.patch.set_facecolor("#FFFFFF")
    ax1.set_facecolor("#FFFFFF")
    ax2.set_facecolor("#FFFFFF")

    # Multi-layer Corridor fills (Institutional Ribbons)
    ax1.fill_between(x, p05, p95, color="#BAE6FD", alpha=0.45, label="5th – 95th Percentile Corridor (90% Conf)")
    ax1.fill_between(x, p25, p75, color="#38BDF8", alpha=0.45, label="25th – 75th Percentile (Interquartile Core)")
    ax1.plot(x, p50, color="#0F172A", linestyle="--", linewidth=1.8, label="50th Percentile (Median Path)")

    # Prop Firm Targets & Floors
    ax1.axhline(26250.0, color="#059669", linestyle="--", linewidth=1.6, alpha=0.9, label="Profit Target (+$1,250 / $26,250)")
    ax1.axhline(25000.0, color="#64748B", linestyle=":", linewidth=1.0, alpha=0.7, label="Starting Capital ($25,000)")
    ax1.axhline(24000.0, color="#DC2626", linestyle="--", linewidth=1.6, alpha=0.9, label="Initial Trailing Floor ($24,000)")
    ax1.axhline(25100.0, color="#7C3AED", linestyle=":", linewidth=1.2, alpha=0.9, label="Trailing Floor Lock ($25,100)")

    # Live Equity Trajectory Overlay
    if len(live_eq) > 1:
        ax1.plot(live_x, live_eq, color="#0F172A", linewidth=2.6, zorder=5)
        ax1.scatter(live_x, live_eq, color="#2563EB", edgecolors="#0F172A", s=65, linewidth=1.5, zorder=6, label=f"Live Forward Test (Trade {len(live_eq)-1}: ${live_eq[-1]:,.2f} | Rank {mc_data['current_rank']:.1f}%)")
        # Annotate latest trade
        last_x, last_y = live_x[-1], live_eq[-1]
        ax1.annotate(
            f"LIVE: ${last_y:,.2f}\nRank: {mc_data['current_rank']:.1f}%\nStatus: {mc_data['regime_status'].replace('_', ' ')}",
            xy=(last_x, last_y),
            xytext=(last_x + 1.2, last_y + 80),
            arrowprops=dict(facecolor="#2563EB", edgecolor="#2563EB", arrowstyle="->", lw=1.5),
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#F8FAFC", edgecolor="#2563EB", alpha=0.95),
            fontsize=8.5,
            fontfamily="monospace",
            color="#0F172A",
            fontweight="bold",
        )
    else:
        ax1.scatter([0], [25000.0], color="#0F172A", s=50, zorder=6, label="Live Starting Equity ($25,000)")

    ax1.set_ylabel("Account Balance ($)", fontsize=10.5, fontweight="bold", color="#0F172A")
    ax1.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax1.set_ylim(23700, 26600)
    ax1.grid(True, linestyle="--", alpha=0.4, color="#E2E8F0")
    leg1 = ax1.legend(loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1", fontsize=8.5)
    leg1.get_frame().set_linewidth(0.8)

    # Title & Subtitle
    ax1.set_title(
        "BELFORT STEP 08: 10,000-PATH MONTE CARLO CORRIDOR & LIVE FORWARD TEST OVERLAY\n"
        f"Status: {mc_data['regime_status']} • Overall Bootstrap Pass Rate: {mc_data['overall_pass_rate']:.1f}% • Fail Rate: {mc_data['overall_fail_rate']:.1f}%",
        fontsize=11.5,
        fontweight="bold",
        color="#0F172A",
        pad=12,
    )

    # Bottom subplot: Cumulative Pass / Fail Probability Curve
    pass_prob = np.array(mc_data["pass_prob"]) * 100.0
    fail_prob = np.array(mc_data["fail_prob"]) * 100.0

    ax2.plot(x, pass_prob, color="#059669", linewidth=2.0, label="Cumulative Pass Probability %")
    ax2.plot(x, fail_prob, color="#DC2626", linewidth=2.0, linestyle="--", label="Cumulative Fail (Trailed Out) %")
    if len(live_x) > 1:
        ax2.axvline(live_x[-1], color="#0F172A", linestyle=":", linewidth=1.5, alpha=0.8, label=f"Current Horizon (T={live_x[-1]})")

    ax2.set_xlabel("Completed Trade Number (t)", fontsize=9.5, fontweight="bold", color="#0F172A")
    ax2.set_ylabel("Probability (%)", fontsize=9.5, fontweight="bold", color="#0F172A")
    ax2.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:.0f}%"))
    ax2.set_ylim(0, 100)
    ax2.set_xlim(-0.5, n_trades + 0.5)
    ax2.grid(True, linestyle="--", alpha=0.4, color="#E2E8F0")
    leg2 = ax2.legend(loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1", fontsize=8.5)
    leg2.get_frame().set_linewidth(0.8)

    for ax in (ax1, ax2):
        for spine in ax.spines.values():
            spine.set_color("#CBD5E1")
            spine.set_linewidth(0.8)
        ax.tick_params(colors="#475569", labelsize=8.5)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()

    # Also save JSON metadata
    json_path = OUTPUT_DIR / "live_vs_monte_carlo_corridor.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(mc_data, f, indent=2)

    return output_path


if __name__ == "__main__":
    print("Running 10,000-Path Monte Carlo Bootstrap Simulation...")
    data = run_monte_carlo_bootstrap(n_sims=10000, n_trades=30)
    out_img = plot_corridor(data)
    print(f"✅ Monte Carlo Corridor generated successfully: {out_img}")
    print(f"📊 Regime Status: {data['regime_status']}")
    print(f"🎯 Live Equity: ${data['current_balance']:,.2f} (Percentile Rank: {data['current_rank']:.1f}%)")
    print(f"🏆 Overall Pass Rate: {data['overall_pass_rate']:.1f}% | Fail Rate: {data['overall_fail_rate']:.1f}%")
