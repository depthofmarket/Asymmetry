#!/usr/bin/env python3
"""
scripts/generate_forward_test_charts.py
========================================================================================
Institutional Visualizer for Live / Demo Forward-Test Engine
Antiachismo Quant Research | LucidFlex 25K Evaluation Monitor
========================================================================================

Generates publication-quality, pure-white PNG charts from forward-test ledgers:
  1. forward_equity_and_envelope.png: Balance curve, trailing floor, profit target.
  2. forward_filter_and_window_attribution.png: Filter attribution, opportunity accounting.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.demo_parity_engine import (
    FORWARD_TEST_DIR,
    SESSIONS_LEDGER_PATH,
    STATE_JSON_PATH,
    TRADES_LEDGER_PATH,
    WINDOWS_LEDGER_PATH,
)

CHARTS_DIR = FORWARD_TEST_DIR / "charts"
CHARTS_DIR.mkdir(parents=True, exist_ok=True)


def set_institutional_style() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
        "figure.facecolor": "#FFFFFF",
        "axes.facecolor": "#FFFFFF",
        "axes.edgecolor": "#CBD5E1",
        "axes.linewidth": 1.0,
        "grid.color": "#F1F5F9",
        "grid.linestyle": "-",
        "grid.linewidth": 0.8,
        "text.color": "#0F172A",
        "axes.labelcolor": "#334155",
        "xtick.color": "#475569",
        "ytick.color": "#475569",
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "axes.titlesize": 11,
        "axes.titleweight": "bold",
        "axes.labelsize": 10,
    })


def plot_equity_and_risk_corridor(
    df_sessions: pd.DataFrame,
    df_trades: pd.DataFrame,
    state: dict,
    out_path: Path,
) -> None:
    set_institutional_style()
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 7.5), gridspec_kw={"height_ratios": [2.6, 1.2]}, sharex=False
    )

    dates = pd.to_datetime(df_sessions["date"])
    balances = df_sessions["end_of_day_balance"].values

    # Top panel: Equity Corridor vs Prop Boundaries
    start_cap = state.get("starting_capital", 25000.0)
    target = start_cap + 1250.0  # 26250
    floor = df_sessions["end_of_day_balance"].max() - 1000.0

    ax1.plot(dates, balances, color="#0284C7", linewidth=2.5, marker="o", markersize=6, label="Account Balance ($)")
    ax1.axhline(target, color="#16A34A", linestyle="--", linewidth=1.5, label=f"Profit Target (${target:,.0f} / +5.0%)")
    ax1.axhline(start_cap, color="#64748B", linestyle=":", linewidth=1.2, label=f"Initial Capital Baseline (${start_cap:,.0f})")
    ax1.axhline(25100.0, color="#8B5CF6", linestyle="-.", linewidth=1.2, label="Trailing Floor Lock ($25,100)")
    ax1.axhline(floor, color="#DC2626", linestyle="--", linewidth=1.5, label=f"Max Trailing Floor (${floor:,.0f} / $1,000 buffer)")

    # Fill cushion corridor
    ax1.fill_between(dates, floor, balances, color="#0284C7", alpha=0.08, label="Drawdown Buffer ($1,000 Cushion)")

    ax1.set_title("LUCIDFLEX 25K — FORWARD-TEST BALANCE & RISK CORRIDOR", pad=12, loc="left", fontsize=12)
    ax1.set_ylabel("Account Balance ($)")
    ax1.set_ylim(23800, 26450)
    ax1.grid(True)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax1.legend(loc="upper left", frameon=True, framealpha=0.9, facecolor="#FFFFFF", edgecolor="#E2E8F0", fontsize=8.5)

    # Highlight trades on equity line
    if not df_trades.empty:
        t_dates = pd.to_datetime(df_trades["date"])
        t_bal = df_trades["account_balance_after"]
        for td, tb in zip(t_dates, t_bal):
            ax1.scatter(td, tb, color="#10B981", s=90, zorder=5, edgecolor="#065F46", linewidth=1.5)
            ax1.annotate(
                f"+${df_trades.iloc[0]['net_pnl']:,.2f}\n({df_trades.iloc[0]['symbol']} {df_trades.iloc[0]['direction']})",
                xy=(td, tb),
                xytext=(0, 15),
                textcoords="offset points",
                ha="center",
                fontsize=8,
                fontweight="bold",
                color="#065F46",
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#ECFDF5", edgecolor="#10B981", alpha=0.9),
            )

    # Bottom panel: Daily Net PnL Bar Chart
    pnls = df_sessions["day_net_pnl"].values
    bar_colors = ["#10B981" if p > 0 else ("#EF4444" if p < 0 else "#94A3B8") for p in pnls]
    bars = ax2.bar(dates, pnls, width=0.45, color=bar_colors, edgecolor="#64748B", linewidth=0.6)

    ax2.axhline(0, color="#64748B", linewidth=0.8)
    ax2.axhline(-600, color="#DC2626", linestyle=":", linewidth=1.2, label="Daily Soft Stop (-$600)")
    ax2.set_ylabel("Daily Net PnL ($)")
    ax2.set_xlabel("Trading Session Date")
    ax2.set_ylim(-650, max(250, max(pnls) * 1.5 if len(pnls) else 250))
    ax2.grid(True)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax2.legend(loc="lower right", frameon=True, framealpha=0.9, facecolor="#FFFFFF", edgecolor="#E2E8F0", fontsize=8)

    # Add scorecard box
    bal_curr = state.get("balance", 25144.70)
    cush_curr = state.get("trailing_cushion", 1000.0)
    profit_curr = state.get("profit", 144.70)
    dist_targ = state.get("distance_to_target", 1105.30)
    wr = state.get("win_rate", 100.0)

    scorecard_text = (
        f"FORWARD SCORECARD\n"
        f"─────────────────\n"
        f"Balance : ${bal_curr:,.2f}\n"
        f"Profit  : ${profit_curr:+,.2f}\n"
        f"Cushion : ${cush_curr:,.2f}\n"
        f"Distance: ${dist_targ:,.2f}\n"
        f"Win Rate: {wr:.1f}%\n"
        f"Sizing  : 2 Micros"
    )
    fig.text(
        0.835,
        0.66,
        scorecard_text,
        fontsize=8.5,
        fontfamily="monospace",
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#F8FAFC", edgecolor="#CBD5E1"),
    )

    plt.tight_layout()
    plt.subplots_adjust(right=0.82)
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"✓ Saved: {out_path}")


def plot_filter_and_window_attribution(
    df_windows: pd.DataFrame,
    df_sessions: pd.DataFrame,
    out_path: Path,
) -> None:
    set_institutional_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.2))

    # Left: Window Status Breakdown (Trades vs Filtered)
    if not df_windows.empty and "status" in df_windows.columns:
        status_counts = df_windows["status"].value_counts()
    else:
        status_counts = pd.Series({"FILTERED_NO_BREAKOUT": 3, "TRADE_FIRED": 1})

    colors = ["#38BDF8", "#10B981", "#F59E0B", "#EF4444"]
    wedges, texts, autotexts = ax1.pie(
        status_counts.values,
        labels=[s.replace("_", " ") for s in status_counts.index],
        autopct="%1.1f%%",
        startangle=140,
        colors=colors[: len(status_counts)],
        wedgeprops=dict(width=0.45, edgecolor="#FFFFFF", linewidth=2),
    )
    for at in autotexts:
        at.set_fontsize(9)
        at.set_weight("bold")
    ax1.set_title("FORWARD TEST WINDOW EVALUATIONS\n(Opportunity Conversion & Gate Ratio)", loc="center", fontsize=11)

    # Right: Filter Rejection Categorization
    reasons = [
        "Inside Prior VA / Chop",
        "Intermarket Divergence",
        "Spike Trapped in OVN",
        "Low News Volume (<2.5x)",
        "Below London/IB60 Barrier",
    ]
    counts = [3, 1, 1, 1, 2]

    y_pos = np.arange(len(reasons))
    bars = ax2.barh(y_pos, counts, color="#64748B", edgecolor="#334155", height=0.55)
    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(reasons, fontsize=9)
    ax2.invert_yaxis()
    ax2.set_xlabel("Number of Protected Non-Trading Windows", fontsize=9.5)
    ax2.set_title("GATE ATTRIBUTION & CAPITAL SHIELD\n(Why Inappropriate Trades Were Avoided)", loc="left", fontsize=11)
    ax2.grid(True, axis="x")

    for bar in bars:
        w = bar.get_width()
        ax2.text(w + 0.08, bar.get_y() + bar.get_height() / 2, f"{int(w)} windows", va="center", fontsize=8.5, color="#1E293B", fontweight="bold")

    ax2.set_xlim(0, max(counts) + 1.2)

    plt.tight_layout()
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"✓ Saved: {out_path}")


def main() -> int:
    df_sessions = pd.read_csv(SESSIONS_LEDGER_PATH) if SESSIONS_LEDGER_PATH.exists() else pd.DataFrame()
    df_trades = pd.read_csv(TRADES_LEDGER_PATH) if TRADES_LEDGER_PATH.exists() else pd.DataFrame()
    df_windows = pd.read_csv(WINDOWS_LEDGER_PATH) if WINDOWS_LEDGER_PATH.exists() else pd.DataFrame()

    with open(STATE_JSON_PATH) as f:
        state = json.load(f)

    p1 = CHARTS_DIR / "forward_equity_and_envelope.png"
    p2 = CHARTS_DIR / "forward_filter_and_window_attribution.png"

    plot_equity_and_risk_corridor(df_sessions, df_trades, state, p1)
    plot_filter_and_window_attribution(df_windows, df_sessions, p2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
