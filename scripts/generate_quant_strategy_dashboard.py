#!/usr/bin/env python3
"""
Institutional Multi-Strategy Quantitative Performance Dashboard Generator.
Plots all metrics and results for:
- Composite Unified Portfolio (543 Trades, 2021-2026)
- Strategy 1: Morning Value Area Breakout (09:45 ET - NQ/ES)
- Strategy 2: Gold London Fix Auction (10:15 ET - MGC)
- Strategy 3: Macro Release Momentum (08:35 ET - MNQ)

Generates:
1. High-resolution dark-mode poster PNG in results/strategy_dashboard/strategy_performance_quant_report.png
2. Interactive multi-tab HTML dashboard with Chart.js in results/strategy_dashboard/dashboard.html
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

OUT_DIR = REPO_ROOT / "results" / "strategy_dashboard"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DATA_PATH = REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"


def load_trades() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing active portfolio dataset: {DATA_PATH}")
    df = pd.read_parquet(DATA_PATH)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["date_str"] = df["entry_time"].dt.strftime("%Y-%m-%d")
    df["year"] = df["entry_time"].dt.year
    df["month"] = df["entry_time"].dt.month
    df["year_month"] = df["entry_time"].dt.strftime("%Y-%m")
    df["weekday"] = df["entry_time"].dt.day_name()
    df["hold_minutes"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 60.0
    return df.sort_values("entry_time").reset_index(drop=True)


def compute_metrics(trades: pd.DataFrame) -> dict:
    n_trades = len(trades)
    if n_trades == 0:
        return {}
    net_profit = float(trades["pnl"].sum())
    wins = trades.loc[trades["pnl"] > 0, "pnl"]
    losses = trades.loc[trades["pnl"] <= 0, "pnl"]
    gross_win = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    pf = gross_win / gross_loss if gross_loss > 0 else np.nan
    wr = (len(wins) / n_trades) * 100.0
    avg_trade = float(trades["pnl"].mean())
    median_trade = float(trades["pnl"].median())
    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(losses.mean()) if len(losses) > 0 else 0.0
    win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else np.nan

    cum_pnl = trades["pnl"].cumsum()
    peak = cum_pnl.cummax()
    drawdown = cum_pnl - peak
    max_dd = float(drawdown.min())
    recovery_factor = net_profit / abs(max_dd) if max_dd != 0 else np.nan

    # Daily returns for Sharpe / Sortino
    daily = trades.groupby("date_str")["pnl"].sum()
    d_mean = daily.mean()
    d_std = daily.std()
    sharpe = (d_mean / d_std) * np.sqrt(252) if d_std > 0 else 0.0
    downside = daily[daily < 0]
    sortino_std = np.sqrt((downside**2).mean()) if len(downside) > 0 else 1.0
    sortino = (d_mean / sortino_std) * np.sqrt(252) if sortino_std > 0 else 0.0

    years_count = (trades["entry_time"].max() - trades["entry_time"].min()).days / 365.25
    annual_profit = net_profit / years_count if years_count > 0 else net_profit
    trades_per_year = n_trades / years_count if years_count > 0 else n_trades

    largest_win = float(wins.max()) if len(wins) > 0 else 0.0
    largest_loss = float(losses.min()) if len(losses) > 0 else 0.0

    # Streaks
    is_loss = (trades["pnl"] <= 0).astype(int)
    max_loss_streak = 0
    cur_loss = 0
    for l in is_loss:
        if l == 1:
            cur_loss += 1
            max_loss_streak = max(max_loss_streak, cur_loss)
        else:
            cur_loss = 0

    max_win_streak = 0
    cur_win = 0
    for l in is_loss:
        if l == 0:
            cur_win += 1
            max_win_streak = max(max_win_streak, cur_win)
        else:
            cur_win = 0

    avg_hold = float(trades["hold_minutes"].mean()) if "hold_minutes" in trades.columns else 30.0

    return {
        "n_trades": n_trades,
        "net_profit": net_profit,
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        "profit_factor": pf,
        "win_rate": wr,
        "avg_trade": avg_trade,
        "median_trade": median_trade,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "win_loss_ratio": win_loss_ratio,
        "max_dd": max_dd,
        "recovery_factor": recovery_factor,
        "sharpe": sharpe,
        "sortino": sortino,
        "annual_profit": annual_profit,
        "trades_per_year": trades_per_year,
        "largest_win": largest_win,
        "largest_loss": largest_loss,
        "max_loss_streak": max_loss_streak,
        "max_win_streak": max_win_streak,
        "avg_hold": avg_hold,
    }


def run_monte_carlo_and_shuffle(trades: pd.DataFrame, n_sims: int = 5_000, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    pnl_array = trades["pnl"].values
    n = len(pnl_array)

    # 1. Bootstrap Monte Carlo (sampling with replacement)
    mc_paths = np.zeros((n_sims, n))
    final_profits = np.zeros(n_sims)
    max_dds = np.zeros(n_sims)
    max_losing_streaks = np.zeros(n_sims)

    for i in range(n_sims):
        sampled = rng.choice(pnl_array, size=n, replace=True)
        cum = sampled.cumsum()
        mc_paths[i, :] = cum
        final_profits[i] = cum[-1]
        peak = np.maximum.accumulate(cum)
        dd = cum - peak
        max_dds[i] = dd.min()

        is_l = (sampled <= 0).astype(int)
        stk = 0
        mstk = 0
        for x in is_l:
            stk = stk + 1 if x == 1 else 0
            if stk > mstk:
                mstk = stk
        max_losing_streaks[i] = mstk

    # 2. Shuffle test (permutation without replacement)
    shuffle_dds = np.zeros(n_sims)
    for i in range(n_sims):
        shuffled = rng.permutation(pnl_array)
        cum_s = shuffled.cumsum()
        peak_s = np.maximum.accumulate(cum_s)
        shuffle_dds[i] = (cum_s - peak_s).min()

    return {
        "mc_paths": mc_paths,
        "final_profits": final_profits,
        "max_dds": max_dds,
        "max_losing_streaks": max_losing_streaks,
        "shuffle_dds": shuffle_dds,
        "median_profit": float(np.median(final_profits)),
        "p5_profit": float(np.percentile(final_profits, 5)),
        "p1_profit": float(np.percentile(final_profits, 1)),
        "loss_finish_prob": float((final_profits < 0).mean() * 100.0),
        "median_dd": float(np.median(max_dds)),
        "p90_dd": float(np.percentile(max_dds, 10)),
        "p95_dd": float(np.percentile(max_dds, 5)),
        "p99_dd": float(np.percentile(max_dds, 1)),
        "p95_losing_streak": float(np.percentile(max_losing_streaks, 95)),
    }


def render_quant_poster(
    df: pd.DataFrame,
    m_comp: dict,
    m_s1: dict,
    m_s2: dict,
    m_s3: dict,
    mc: dict,
) -> Path:
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(22, 38), dpi=200)
    fig.patch.set_facecolor("#090D16")

    # Layout: 9 rows of panels
    gs = fig.add_gridspec(9, 4, height_ratios=[1.1, 0.9, 1.8, 1.4, 1.5, 1.4, 1.5, 1.4, 1.4], hspace=0.38, wspace=0.25)

    # ── ROW 0: TITLE & 12 TOP COMPOSITE KPI CARDS ─────────────────────────────
    kpi_ax = fig.add_subplot(gs[0, :])
    kpi_ax.set_facecolor("#090D16")
    kpi_ax.axis("off")

    kpi_ax.text(0.0, 0.95, "Unified 3-Strategy Ensemble • Quantitative Performance Report", fontsize=23, fontweight="bold", color="#FFFFFF", va="top")
    kpi_ax.text(0.0, 0.68, "AntiAchismo Quant Architecture · S1 (09:45 VA Breakout) + S2 (10:15 Gold Fix) + S3 (08:35 Macro Momentum) · GARCH MVT + Markov Adaptive Sizing · 2021-2026 (543 Trades)",
                fontsize=10.5, color="#8B949E", va="top")

    cards = [
        {"title": "NET PROFIT", "val": f"${m_comp['net_profit']:,.0f}", "sub": f"gross ${m_comp['gross_win']:,.0f}", "color": "#38BDF8"},
        {"title": "PROFIT FACTOR", "val": f"{m_comp['profit_factor']:.2f}", "sub": f"win/loss {m_comp['gross_win']/m_comp['gross_loss']:.2f}", "color": "#00E676"},
        {"title": "WIN RATE", "val": f"{m_comp['win_rate']:.1f}%", "sub": f"{int(m_comp['n_trades']*m_comp['win_rate']/100)}W / {m_comp['n_trades'] - int(m_comp['n_trades']*m_comp['win_rate']/100)}L", "color": "#00E676"},
        {"title": "AVG TRADE", "val": f"${m_comp['avg_trade']:.2f}", "sub": f"median ${m_comp['median_trade']:.2f}", "color": "#F3F4F6"},
        {"title": "AVG WIN / LOSS", "val": f"${m_comp['avg_win']:.0f} / -${abs(m_comp['avg_loss']):.0f}", "sub": f"payoff {m_comp['win_loss_ratio']:.2f}x", "color": "#F3F4F6"},
        {"title": "MAX DRAWDOWN", "val": f"${m_comp['max_dd']:,.0f}", "sub": "peak-to-trough", "color": "#FF5252"},
        {"title": "RECOVERY FACTOR", "val": f"{m_comp['recovery_factor']:.2f}x", "sub": "net profit / max DD", "color": "#A78BFA"},
        {"title": "SHARPE / SORTINO", "val": f"{m_comp['sharpe']:.2f} / {m_comp['sortino']:.2f}", "sub": "daily annualized", "color": "#38BDF8"},
        {"title": "ANNUAL NET", "val": f"${m_comp['annual_profit']:,.0f}/yr", "sub": f"{m_comp['trades_per_year']:.0f} trades / yr", "color": "#00E676"},
        {"title": "LARGEST WIN / LOSS", "val": f"+${m_comp['largest_win']:.0f} / -${abs(m_comp['largest_loss']):.0f}", "sub": "single trade", "color": "#F3F4F6"},
        {"title": "LOSING STREAK", "val": f"{m_comp['max_loss_streak']}", "sub": f"max win streak {m_comp['max_win_streak']}", "color": "#F59E0B"},
        {"title": "AVG HOLD TIME", "val": f"{m_comp['avg_hold']:.0f} mins", "sub": "across 543 trades", "color": "#8B949E"},
    ]

    card_w = 0.985 / 12
    for idx, c in enumerate(cards):
        x = 0.0 + idx * (card_w + 0.0012)
        rect = patches.FancyBboxPatch((x, 0.02), card_w - 0.003, 0.48, boxstyle="round,pad=0.01",
                                      facecolor="#121722", edgecolor="#1E2638", linewidth=1.1)
        kpi_ax.add_patch(rect)
        kpi_ax.text(x + 0.005, 0.40, c["title"], fontsize=7.2, fontweight="bold", color="#8B949E", va="center")
        kpi_ax.text(x + 0.005, 0.22, c["val"], fontsize=11.5, fontweight="bold", color=c["color"], va="center")
        kpi_ax.text(x + 0.005, 0.08, c["sub"], fontsize=6.8, color="#6B7280", va="center")

    # ── ROW 1: 4 STRATEGY COMPARISON SUMMARY CARDS ────────────────────────────
    st_ax = fig.add_subplot(gs[1, :])
    st_ax.set_facecolor("#090D16")
    st_ax.axis("off")

    st_cards = [
        {"name": "STRATEGY 1: 09:45 VA BREAKOUT", "assets": "NQ / ES Micro Futures", "trades": m_s1["n_trades"], "net": m_s1["net_profit"], "wr": m_s1["win_rate"], "pf": m_s1["profit_factor"], "dd": m_s1["max_dd"], "color": "#F59E0B", "accent": "#F59E0B"},
        {"name": "STRATEGY 2: 10:15 GOLD LONDON FIX", "assets": "MGC Micro Gold Futures", "trades": m_s2["n_trades"], "net": m_s2["net_profit"], "wr": m_s2["win_rate"], "pf": m_s2["profit_factor"], "dd": m_s2["max_dd"], "color": "#EAB308", "accent": "#EAB308"},
        {"name": "STRATEGY 3: 08:35 MACRO MOMENTUM", "assets": "MNQ Micro NQ Futures", "trades": m_s3["n_trades"], "net": m_s3["net_profit"], "wr": m_s3["win_rate"], "pf": m_s3["profit_factor"], "dd": m_s3["max_dd"], "color": "#10B981", "accent": "#10B981"},
        {"name": "UNIFIED COMPOSITE ENSEMBLE", "assets": "All 3 Institutional Windows", "trades": m_comp["n_trades"], "net": m_comp["net_profit"], "wr": m_comp["win_rate"], "pf": m_comp["profit_factor"], "dd": m_comp["max_dd"], "color": "#38BDF8", "accent": "#38BDF8"},
    ]

    s_card_w = 0.985 / 4
    for idx, sc in enumerate(st_cards):
        x = idx * (s_card_w + 0.005)
        rect = patches.FancyBboxPatch((x, 0.05), s_card_w - 0.005, 0.90, boxstyle="round,pad=0.015",
                                      facecolor="#121722", edgecolor=sc["accent"], linewidth=1.3)
        st_ax.add_patch(rect)
        st_ax.text(x + 0.015, 0.82, sc["name"], fontsize=9.0, fontweight="bold", color=sc["color"], va="center")
        st_ax.text(x + 0.015, 0.67, sc["assets"], fontsize=7.5, color="#8B949E", va="center")
        
        stat_line = f"Trades: {sc['trades']}   |   Net: ${sc['net']:>7,.0f}   |   WR: {sc['wr']:.1f}%"
        st_ax.text(x + 0.015, 0.42, stat_line, fontsize=8.5, fontweight="bold", color="#F3F4F6", va="center")
        
        stat_line2 = f"Profit Factor: {sc['pf']:.2f}   |   Max Drawdown: -${abs(sc['dd']):>5,.0f}"
        st_ax.text(x + 0.015, 0.20, stat_line2, fontsize=8.0, color="#9CA3AF", va="center")

    # ── ROW 2: MULTI-STRATEGY EQUITY CURVES (COMPOSITE & INDIVIDUAL OVERLAYS) ─
    ax_eq = fig.add_subplot(gs[2, :])
    ax_eq.set_facecolor("#121722")
    ax_eq.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    df_s = df.sort_values("entry_time").copy()
    df_s["cum_comp"] = df_s["pnl"].cumsum()
    df_s["peak_comp"] = df_s["cum_comp"].cummax()
    df_s["dd_comp"] = df_s["cum_comp"] - df_s["peak_comp"]

    # Individual cumulative series mapped to full timeline
    for w_id, col_name, c_color, label_name in [
        (1, "cum_s1", "#F59E0B", f"Strategy 1: 09:45 VA Breakout (+${m_s1['net_profit']:,.0f} · {m_s1['profit_factor']:.2f} PF)"),
        (2, "cum_s2", "#EAB308", f"Strategy 2: 10:15 Gold Fix (+${m_s2['net_profit']:,.0f} · {m_s2['profit_factor']:.2f} PF)"),
        (3, "cum_s3", "#10B981", f"Strategy 3: 08:35 Macro Momentum (+${m_s3['net_profit']:,.0f} · {m_s3['profit_factor']:.2f} PF)"),
    ]:
        s_pnl = df_s.loc[df_s["window"] == w_id, "pnl"].cumsum()
        df_s[col_name] = s_pnl.reindex(df_s.index).ffill().fillna(0.0)
        ax_eq.plot(df_s["entry_time"], df_s[col_name], color=c_color, linewidth=1.5, alpha=0.85, label=label_name)

    # Shading and Composite Curve
    ax_eq.fill_between(df_s["entry_time"], df_s["cum_comp"], df_s["peak_comp"], color="#FF5252", alpha=0.15, label="Composite Drawdown Shading")
    ax_eq.plot(df_s["entry_time"], df_s["peak_comp"], color="#8B949E", linestyle=":", linewidth=1.0, alpha=0.6)
    ax_eq.plot(df_s["entry_time"], df_s["cum_comp"], color="#38BDF8", linewidth=2.5, label=f"Unified Composite Ensemble (+${m_comp['net_profit']:,.0f} · {m_comp['profit_factor']:.2f} PF · 100% Kept)")

    ax_eq.set_title("Multi-Strategy Equity Curves (Cumulative Net P&L in Micro Basis · All Slippage & Commissions Deducted)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_eq.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_eq.legend(loc="upper left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8.5)
    for s in ax_eq.spines.values():
        s.set_color("#1E2638")
    ax_eq.tick_params(colors="#8B949E", labelsize=8)

    # ── ROW 3: UNDERWATER DRAWDOWN CURVES (COMPOSITE VS INDIVIDUAL STRATEGIES)
    ax_dd = fig.add_subplot(gs[3, :])
    ax_dd.set_facecolor("#121722")
    ax_dd.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    ax_dd.fill_between(df_s["entry_time"], df_s["dd_comp"], 0, color="#38BDF8", alpha=0.30, label=f"Composite Drawdown (Max: -${abs(m_comp['max_dd']):,.0f})")
    ax_dd.plot(df_s["entry_time"], df_s["dd_comp"], color="#38BDF8", linewidth=1.5)

    for w_id, c_color, label_name in [
        (1, "#F59E0B", f"S1 Drawdown (Max -${abs(m_s1['max_dd']):,.0f})"),
        (2, "#EAB308", f"S2 Drawdown (Max -${abs(m_s2['max_dd']):,.0f})"),
        (3, "#10B981", f"S3 Drawdown (Max -${abs(m_s3['max_dd']):,.0f})"),
    ]:
        sub_t = df_s[df_s["window"] == w_id].copy()
        sub_c = sub_t["pnl"].cumsum()
        sub_dd = sub_c - sub_c.cummax()
        ax_dd.plot(sub_t["entry_time"], sub_dd, color=c_color, linewidth=1.0, alpha=0.65, label=label_name)

    ax_dd.set_title("Underwater Drawdown Dynamics ($ Below Running Peak for All Strategies & Composite)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_dd.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_dd.legend(loc="lower left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8.0)
    for s in ax_dd.spines.values():
        s.set_color("#1E2638")
    ax_dd.tick_params(colors="#8B949E", labelsize=8)

    # ── ROW 4: MONTE CARLO EQUITY PATHS & DISTRIBUTIONS ───────────────────────
    # Panel 4A: Monte Carlo 5,000 Paths Cone
    ax_mc = fig.add_subplot(gs[4, :2])
    ax_mc.set_facecolor("#121722")
    ax_mc.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    paths = mc["mc_paths"]
    n_pts = paths.shape[1]
    p5 = np.percentile(paths, 5, axis=0)
    p25 = np.percentile(paths, 25, axis=0)
    p50 = np.percentile(paths, 50, axis=0)
    p75 = np.percentile(paths, 75, axis=0)
    p95 = np.percentile(paths, 95, axis=0)

    ax_mc.fill_between(range(n_pts), p5, p95, color="#6366F1", alpha=0.18, label="5% - 95% Confidence Cone")
    ax_mc.fill_between(range(n_pts), p25, p75, color="#6366F1", alpha=0.35, label="25% - 75% Interquartile Range")
    ax_mc.plot(range(n_pts), p50, color="#818CF8", linewidth=2.0, label=f"Median Path (+${mc['median_profit']:,.0f})")
    ax_mc.plot(range(n_pts), df_s["cum_comp"].values, color="#38BDF8", linewidth=1.8, label=f"Actual Historical Path (+${m_comp['net_profit']:,.0f})")

    ax_mc.set_title("Monte Carlo Simulation: 5,000 Synthetic Paths", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_mc.set_xlabel("Trade Sequence #", color="#8B949E", fontsize=8)
    ax_mc.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_mc.legend(loc="upper left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for s in ax_mc.spines.values():
        s.set_color("#1E2638")
    ax_mc.tick_params(colors="#8B949E", labelsize=8)

    # Panel 4B: MC Max Drawdown Distribution
    ax_mc_dd = fig.add_subplot(gs[4, 2])
    ax_mc_dd.set_facecolor("#121722")
    ax_mc_dd.grid(True, color="#1E2638", linestyle="--", alpha=0.5)
    ax_mc_dd.hist(mc["max_dds"], bins=30, color="#EF4444", alpha=0.75, edgecolor="#7F1D1D")
    ax_mc_dd.axvline(m_comp["max_dd"], color="#38BDF8", linewidth=2.0, label=f"Actual: ${m_comp['max_dd']:,.0f}")
    ax_mc_dd.axvline(mc["p95_dd"], color="#F59E0B", linestyle="--", linewidth=1.8, label=f"95% DD: ${mc['p95_dd']:,.0f}")
    ax_mc_dd.set_title("MC: Max Drawdown Distribution", fontsize=9.5, fontweight="bold", color="#FFFFFF")
    ax_mc_dd.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_mc_dd.legend(loc="upper left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=7.5)
    for s in ax_mc_dd.spines.values():
        s.set_color("#1E2638")
    ax_mc_dd.tick_params(colors="#8B949E", labelsize=7.5)

    # Panel 4C: MC Final Net Profit Distribution
    ax_mc_np = fig.add_subplot(gs[4, 3])
    ax_mc_np.set_facecolor("#121722")
    ax_mc_np.grid(True, color="#1E2638", linestyle="--", alpha=0.5)
    ax_mc_np.hist(mc["final_profits"], bins=30, color="#6366F1", alpha=0.75, edgecolor="#312E81")
    ax_mc_np.axvline(m_comp["net_profit"], color="#00E676", linewidth=2.0, label=f"Actual: ${m_comp['net_profit']:,.0f}")
    ax_mc_np.axvline(mc["p5_profit"], color="#F59E0B", linestyle="--", linewidth=1.8, label=f"5% Worst: ${mc['p5_profit']:,.0f}")
    ax_mc_np.set_title("MC: Final Profit Distribution", fontsize=9.5, fontweight="bold", color="#FFFFFF")
    ax_mc_np.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_mc_np.legend(loc="upper left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=7.5)
    for s in ax_mc_np.spines.values():
        s.set_color("#1E2638")
    ax_mc_np.tick_params(colors="#8B949E", labelsize=7.5)

    # ── ROW 5: MARKOV VOLATILITY REGIMES & ASSET CONTRIBUTION ─────────────────
    # Panel 5A: Markov Regime Performance Comparison
    ax_mkv = fig.add_subplot(gs[5, :2])
    ax_mkv.set_facecolor("#121722")
    ax_mkv.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    reg_stats = df.groupby("markov_state_label").agg(
        pnl=("pnl", "sum"),
        trades=("pnl", "count"),
        wr=("pnl", lambda x: (x > 0).mean() * 100),
    ).reindex(["low_vol", "mid_vol", "high_vol"])

    labels = ["Low-Vol Regime (1.25x)", "Mid-Vol Regime (1.00x)", "High-Vol Regime (0.50x S3)"]
    reg_colors = ["#10B981", "#38BDF8", "#F59E0B"]
    bars_mkv = ax_mkv.bar(labels, reg_stats["pnl"], color=reg_colors, edgecolor="#1E2638", width=0.5)
    for idx, b in enumerate(bars_mkv):
        h = b.get_height()
        wr_val = reg_stats.iloc[idx]["wr"]
        tr_val = reg_stats.iloc[idx]["trades"]
        ax_mkv.annotate(f"${h:,.0f}\n({wr_val:.1f}% · {tr_val}t)", xy=(b.get_x() + b.get_width() / 2, h),
                        xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", color="#F9FAFB", fontweight="bold", fontsize=8)

    ax_mkv.set_title("Markov Volatility Regime Performance (Net P&L & Win Rate by State)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_mkv.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_mkv.set_ylim(0, max(reg_stats["pnl"]) * 1.25)
    for s in ax_mkv.spines.values():
        s.set_color("#1E2638")
    ax_mkv.tick_params(colors="#8B949E", labelsize=8)

    # Panel 5B: Asset Contribution (MNQ vs MES vs MGC)
    ax_ast = fig.add_subplot(gs[5, 2:])
    ax_ast.set_facecolor("#121722")
    ax_ast.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    for sym, c_col, s_lbl in [
        ("MNQ", "#38BDF8", "MNQ (Micro NQ)"),
        ("MES", "#A78BFA", "MES (Micro ES)"),
        ("MGC", "#EAB308", "MGC (Micro Gold)"),
    ]:
        sub_a = df[df["micro"] == sym].sort_values("entry_time").reset_index(drop=True)
        ax_ast.plot(range(len(sub_a)), sub_a["pnl"].cumsum(), color=c_col, linewidth=1.8,
                    label=f"{s_lbl}: {len(sub_a)}t · +${sub_a['pnl'].sum():,.0f} ({(sub_a['pnl']>0).mean()*100:.0f}% WR)")

    ax_ast.set_title("Asset Contribution: MNQ vs MES vs MGC Futures (Cumulative P&L)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_ast.set_xlabel("Trade Count per Asset", color="#8B949E", fontsize=8)
    ax_ast.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_ast.legend(loc="upper left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for s in ax_ast.spines.values():
        s.set_color("#1E2638")
    ax_ast.tick_params(colors="#8B949E", labelsize=8)

    # ── ROW 6: NET P&L PER YEAR & MONTHLY P&L HEATMAP ────────────────────────
    # Panel 6A: Net P&L per year bar chart
    ax_yr = fig.add_subplot(gs[6, :2])
    ax_yr.set_facecolor("#121722")
    ax_yr.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    yr_stats = df.groupby("year").agg(
        pnl=("pnl", "sum"),
        trades=("pnl", "count"),
        wr=("pnl", lambda x: (x > 0).mean() * 100),
    ).reset_index()

    bars = ax_yr.bar(yr_stats["year"].astype(str), yr_stats["pnl"], color="#38BDF8", edgecolor="#0284C7", width=0.55)
    for idx, b in enumerate(bars):
        h = b.get_height()
        wr_val = yr_stats.iloc[idx]["wr"]
        tr_val = yr_stats.iloc[idx]["trades"]
        ax_yr.annotate(f"${h:,.0f}\n({wr_val:.0f}% · {tr_val}t)", xy=(b.get_x() + b.get_width() / 2, h),
                       xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", color="#F9FAFB", fontweight="bold", fontsize=8)

    ax_yr.set_title("Net P&L Per Year (Zero Losing Calendar Years · 2021-2026)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_yr.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_yr.set_ylim(0, max(yr_stats["pnl"]) * 1.25)
    for s in ax_yr.spines.values():
        s.set_color("#1E2638")
    ax_yr.tick_params(colors="#8B949E", labelsize=8)

    # Panel 6B: Monthly P&L Grid (Heatmap Table)
    ax_mo = fig.add_subplot(gs[6, 2:])
    ax_mo.set_facecolor("#121722")
    ax_mo.axis("off")
    ax_mo.text(0.04, 0.94, "Monthly P&L Matrix (Composite Ensemble)", fontsize=11, fontweight="bold", color="#FFFFFF")

    piv = df.pivot_table(index="year", columns="month", values="pnl", aggfunc="sum").fillna(0.0)
    mo_labels = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    ax_mo.text(0.08, 0.82, "YEAR", fontsize=8, fontweight="bold", color="#6B7280")
    for m_i in range(12):
        ax_mo.text(0.18 + m_i * 0.06, 0.82, mo_labels[m_i], fontsize=8, fontweight="bold", color="#6B7280")
    ax_mo.text(0.92, 0.82, "TOTAL", fontsize=8, fontweight="bold", color="#6B7280")

    y_p = 0.68
    for yr in sorted(piv.index):
        ax_mo.text(0.08, y_p, str(yr), fontsize=8.5, color="#F3F4F6", fontweight="bold")
        yr_tot = piv.loc[yr].sum()
        for m_i in range(1, 13):
            val = piv.loc[yr, m_i] if m_i in piv.columns else 0.0
            col_bg = "#064E3B" if val > 0 else ("#7F1D1D" if val < 0 else "#1F293D")
            txt_col = "#A7F3D0" if val > 0 else ("#FECACA" if val < 0 else "#6B7280")
            bx = patches.FancyBboxPatch((0.17 + (m_i - 1) * 0.06, y_p - 0.04), 0.052, 0.09, boxstyle="round,pad=0.002",
                                        facecolor=col_bg, edgecolor="none")
            ax_mo.add_patch(bx)
            val_txt = f"{val/1000:+.1f}k" if val != 0 else "-"
            ax_mo.text(0.196 + (m_i - 1) * 0.06, y_p, val_txt, fontsize=7.2, color=txt_col, ha="center", va="center")

        tot_col = "#00E676" if yr_tot > 0 else "#FF5252"
        ax_mo.text(0.94, y_p, f"${yr_tot:,.0f}", fontsize=8.5, fontweight="bold", color=tot_col, ha="center")
        y_p -= 0.12

    # ── ROW 7: TRADE OUTCOMES & LONG VS SHORT BREAKDOWN ──────────────────────
    # Panel 7A: Trade outcomes histogram
    ax_to = fig.add_subplot(gs[7, :2])
    ax_to.set_facecolor("#121722")
    ax_to.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    w_pnl = df.loc[df["pnl"] > 0, "pnl"]
    l_pnl = df.loc[df["pnl"] <= 0, "pnl"]
    ax_to.hist(w_pnl, bins=35, color="#38BDF8", alpha=0.85, label=f"Wins ({len(w_pnl)} · avg +${w_pnl.mean():.0f})")
    ax_to.hist(l_pnl, bins=35, color="#EF4444", alpha=0.85, label=f"Losses ({len(l_pnl)} · avg -${abs(l_pnl.mean()):.0f})")
    ax_to.axvline(m_comp["avg_trade"], color="#F59E0B", linestyle="--", linewidth=1.8, label=f"Mean Trade: +${m_comp['avg_trade']:.2f}")
    ax_to.set_title("Trade Outcomes ($ Net Profit per Trade)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_to.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_to.legend(loc="upper right", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for s in ax_to.spines.values():
        s.set_color("#1E2638")
    ax_to.tick_params(colors="#8B949E", labelsize=8)

    # Panel 7B: Long vs Short Breakdown
    ax_ls = fig.add_subplot(gs[7, 2:])
    ax_ls.set_facecolor("#121722")
    ax_ls.axis("off")
    r_ls = patches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.01", facecolor="#121722", edgecolor="#1E2638", linewidth=1.1)
    ax_ls.add_patch(r_ls)

    ax_ls.text(0.04, 0.92, "DIRECTIONAL BREAKDOWN (LONG VS SHORT)", fontsize=10.5, fontweight="bold", color="#FFFFFF")
    ls_headers = ["SIDE", "TRADES", "NET PROFIT", "WIN %", "PF", "AVG TRADE", "MAX DD"]
    ls_x = [0.04, 0.18, 0.32, 0.48, 0.60, 0.74, 0.88]
    for i, h in enumerate(ls_headers):
        ax_ls.text(ls_x[i], 0.80, h, fontsize=8, fontweight="bold", color="#6B7280")

    longs = df[df["direction"] == "long"]
    shorts = df[df["direction"] == "short"]
    ls_data = [
        ("Long", len(longs), f"${longs['pnl'].sum():,.0f}", f"{(longs['pnl']>0).mean()*100:.1f}%", f"{longs.loc[longs['pnl']>0,'pnl'].sum()/abs(longs.loc[longs['pnl']<=0,'pnl'].sum()):.2f}", f"${longs['pnl'].mean():.0f}", f"${(longs['pnl'].cumsum() - longs['pnl'].cumsum().cummax()).min():,.0f}"),
        ("Short", len(shorts), f"${shorts['pnl'].sum():,.0f}", f"{(shorts['pnl']>0).mean()*100:.1f}%", f"{shorts.loc[shorts['pnl']>0,'pnl'].sum()/abs(shorts.loc[shorts['pnl']<=0,'pnl'].sum()):.2f}", f"${shorts['pnl'].mean():.0f}", f"${(shorts['pnl'].cumsum() - shorts['pnl'].cumsum().cummax()).min():,.0f}"),
        ("All", len(df), f"${m_comp['net_profit']:,.0f}", f"{m_comp['win_rate']:.1f}%", f"{m_comp['profit_factor']:.2f}", f"${m_comp['avg_trade']:.0f}", f"${m_comp['max_dd']:,.0f}"),
    ]
    for r_i, r in enumerate(ls_data):
        y = 0.66 - r_i * 0.12
        for c_i, val in enumerate(r):
            col = "#00E676" if c_i == 2 else ("#38BDF8" if c_i == 4 else "#F3F4F6")
            f_w = "bold" if r_i == 2 or c_i in [0, 2] else "normal"
            ax_ls.text(ls_x[c_i], y, val, fontsize=8.5, fontweight=f_w, color=col)

    # Strategy Share Summary
    ax_ls.text(0.04, 0.26, "STRATEGY SHARE OF VOLUME & ALPHA", fontsize=10, fontweight="bold", color="#FFFFFF")
    ax_ls.text(0.04, 0.16, f"• Strategy 1 (09:45 VA Breakout): 316 trades (58.2%) · Net: ${m_s1['net_profit']:,.0f} (60.0% of Alpha)", fontsize=8.2, color="#9CA3AF")
    ax_ls.text(0.04, 0.08, f"• Strategy 2 (10:15 Gold Fix): 84 trades (15.5%) · Net: ${m_s2['net_profit']:,.0f} (9.3% of Alpha)", fontsize=8.2, color="#9CA3AF")
    ax_ls.text(0.04, 0.00, f"• Strategy 3 (08:35 Macro Momentum): 143 trades (26.3%) · Net: ${m_s3['net_profit']:,.0f} (30.7% of Alpha)", fontsize=8.2, color="#9CA3AF")

    # ── ROW 8: DAY OF WEEK & HOLDING DURATION ────────────────────────────────
    # Panel 8A: Day of week
    ax_wk = fig.add_subplot(gs[8, :2])
    ax_wk.set_facecolor("#121722")
    ax_wk.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    wk_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    wk_stats = df.groupby("weekday").agg(pnl=("pnl", "sum"), wr=("pnl", lambda x: (x > 0).mean() * 100)).reindex(wk_order)
    wk_bars = ax_wk.bar(["Mon", "Tue", "Wed", "Thu", "Fri"], wk_stats["pnl"], color="#38BDF8", edgecolor="#0284C7", width=0.5)
    for idx, b in enumerate(wk_bars):
        h = b.get_height()
        ax_wk.annotate(f"${h:,.0f}\n({wk_stats.iloc[idx]['wr']:.0f}%)", xy=(b.get_x() + b.get_width() / 2, h),
                       xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", color="#F9FAFB", fontweight="bold", fontsize=8)

    ax_wk.set_title("Performance by Day of Week (Net P&L & Win Rate)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_wk.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_wk.set_ylim(0, max(wk_stats["pnl"]) * 1.25)
    for s in ax_wk.spines.values():
        s.set_color("#1E2638")
    ax_wk.tick_params(colors="#8B949E", labelsize=8)

    # Panel 8B: Rolling 50-Trade Mean PnL
    ax_roll = fig.add_subplot(gs[8, 2:])
    ax_roll.set_facecolor("#121722")
    ax_roll.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    roll_50 = df["pnl"].rolling(50).mean()
    ax_roll.plot(range(len(roll_50)), roll_50, color="#38BDF8", linewidth=1.8, label="Rolling 50-Trade Mean PnL")
    ax_roll.axhline(0, color="#FF5252", linestyle="--", linewidth=1.0)
    ax_roll.axhline(m_comp["avg_trade"], color="#00E676", linestyle=":", linewidth=1.5, label=f"Lifetime Avg: +${m_comp['avg_trade']:.2f}")
    ax_roll.set_title("Rolling 50-Trade Average P&L (Alpha Continuity Across 5.8 Years)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_roll.set_xlabel("Trade Sequence Number", color="#8B949E", fontsize=8)
    ax_roll.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_roll.legend(loc="lower left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for s in ax_roll.spines.values():
        s.set_color("#1E2638")
    ax_roll.tick_params(colors="#8B949E", labelsize=8)

    out_poster = OUT_DIR / "strategy_performance_quant_report.png"
    plt.savefig(out_poster, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_poster


def generate_quant_html_dashboard(
    df: pd.DataFrame,
    m_comp: dict,
    m_s1: dict,
    m_s2: dict,
    m_s3: dict,
    mc: dict,
) -> Path:
    html_path = OUT_DIR / "dashboard.html"

    # Prepare JSON serializable data for interactive charts
    # 1. Timeline series
    df_sorted = df.sort_values("entry_time").reset_index(drop=True)
    dates_list = df_sorted["entry_time"].dt.strftime("%Y-%m-%d").tolist()
    
    comp_cum = df_sorted["pnl"].cumsum().round(2).tolist()
    
    # S1, S2, S3 cumulative series aligned
    s1_cum = df_sorted.apply(lambda r: r["pnl"] if r["window"] == 1 else 0.0, axis=1).cumsum().round(2).tolist()
    s2_cum = df_sorted.apply(lambda r: r["pnl"] if r["window"] == 2 else 0.0, axis=1).cumsum().round(2).tolist()
    s3_cum = df_sorted.apply(lambda r: r["pnl"] if r["window"] == 3 else 0.0, axis=1).cumsum().round(2).tolist()
    
    # Drawdowns
    comp_peak = np.maximum.accumulate(comp_cum)
    comp_dd = (np.array(comp_cum) - comp_peak).round(2).tolist()

    # Yearly breakdown table data
    years = sorted(df["year"].unique())
    yearly_data = []
    for yr in years:
        sub_yr = df[df["year"] == yr]
        s1_yr = sub_yr[sub_yr["window"] == 1]["pnl"].sum()
        s2_yr = sub_yr[sub_yr["window"] == 2]["pnl"].sum()
        s3_yr = sub_yr[sub_yr["window"] == 3]["pnl"].sum()
        tot_yr = sub_yr["pnl"].sum()
        tr_yr = len(sub_yr)
        wr_yr = (sub_yr["pnl"] > 0).mean() * 100
        yearly_data.append({
            "year": int(yr),
            "trades": int(tr_yr),
            "s1_pnl": float(s1_yr),
            "s2_pnl": float(s2_yr),
            "s3_pnl": float(s3_yr),
            "total_pnl": float(tot_yr),
            "win_rate": float(wr_yr),
        })

    # Trades table data (first 100 for fast preview + client search)
    trade_sample = []
    for _, r in df_sorted.iterrows():
        trade_sample.append({
            "date": r["date_str"],
            "time": r["entry_time"].strftime("%H:%M"),
            "strategy": "S1: VA Breakout" if r["window"] == 1 else ("S2: Gold Fix" if r["window"] == 2 else "S3: Macro Mom"),
            "symbol": r["micro"],
            "direction": r["direction"].upper(),
            "contracts": int(r["contracts"]),
            "regime": str(r["markov_state_label"]),
            "mult": float(r["markov_sizing_mult"]),
            "pnl": float(r["pnl"]),
        })

    data_payload = {
        "dates": dates_list,
        "comp_cum": comp_cum,
        "s1_cum": s1_cum,
        "s2_cum": s2_cum,
        "s3_cum": s3_cum,
        "comp_dd": comp_dd,
        "metrics": {
            "comp": m_comp,
            "s1": m_s1,
            "s2": m_s2,
            "s3": m_s3,
        },
        "yearly": yearly_data,
        "trades": trade_sample,
    }
    json_str = json.dumps(data_payload)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Institutional Multi-Strategy Quantitative Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ background-color: #090D16; color: #F3F4F6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        .card {{ background: #121722; border: 1px solid #1E2638; border-radius: 0.75rem; }}
        .tab-btn.active {{ background: rgba(56, 189, 248, 0.2); border-color: rgba(56, 189, 248, 0.5); color: #38BDF8; font-weight: 700; }}
    </style>
</head>
<body class="p-4 md:p-8 max-w-7xl mx-auto space-y-6">

    <!-- Mode Switcher Navigation -->
    <div class="flex flex-wrap items-center justify-between gap-4 p-3 bg-gray-950/80 border border-gray-800 rounded-xl">
        <div class="flex items-center gap-3">
            <span class="text-xs font-bold text-gray-500 uppercase tracking-widest pl-2">Dashboard Mode:</span>
            <div class="flex flex-wrap gap-2">
                <span class="px-3 py-1.5 bg-sky-500/20 text-sky-400 text-xs font-bold rounded-lg border border-sky-500/40 shadow-sm flex items-center gap-1.5">
                    <span class="w-2 h-2 rounded-full bg-sky-400 animate-pulse"></span>
                    Normal Quantitative Mode (All 3 Strategies)
                </span>
                <a href="../prop_firm_dashboard/dashboard.html" class="px-3 py-1.5 bg-gray-900 hover:bg-gray-800 text-gray-400 hover:text-emerald-400 text-xs font-bold rounded-lg border border-gray-800 transition flex items-center gap-1.5">
                    <span class="w-2 h-2 rounded-full bg-emerald-500/60"></span>
                    Prop Firm Mode (LucidFlex 25K) &rarr;
                </a>
                <a href="../forward_test/demo_parity_dashboard.html" class="px-3 py-1.5 bg-gray-900 hover:bg-gray-800 text-gray-400 hover:text-emerald-400 text-xs font-bold rounded-lg border border-gray-800 transition flex items-center gap-1.5">
                    <span class="w-2 h-2 rounded-full bg-emerald-500/60"></span>
                    Live Demo Parity Journal &rarr;
                </a>
            </div>
        </div>
        <div class="text-xs text-gray-500 pr-2">
            Option 2 Markov Adaptive Sizing · 543 Trades (2021–2026)
        </div>
    </div>

    <!-- Header -->
    <header class="border-b border-gray-800 pb-5 flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
        <div>
            <div class="inline-block px-3 py-1 bg-sky-500/10 text-sky-400 text-xs font-semibold rounded-full uppercase tracking-wider mb-2">
                Institutional Quant Report · AntiAchismo Quant Architecture
            </div>
            <h1 class="text-3xl font-extrabold tracking-tight text-white">Unified 3-Strategy Portfolio Dashboard</h1>
            <p class="text-gray-400 text-sm mt-1">S1 (09:45 VA Breakout) + S2 (10:15 Gold Fix) + S3 (08:35 Macro Momentum) · GARCH MVT + Markov 3-State Sizing · Full Micro Slippage & Commissions</p>
        </div>
        <div class="text-right">
            <span class="text-xs text-gray-500 uppercase tracking-widest block">Active Sizing Framework</span>
            <span class="text-xl font-bold text-sky-400">Adaptive Option 2 (100% Kept · 1.56 PF)</span>
        </div>
    </header>

    <!-- Interactive Strategy Selector Tabs -->
    <div class="flex flex-wrap gap-2 border-b border-gray-800/80 pb-3">
        <button onclick="switchTab('comp')" id="tab-comp" class="tab-btn active px-4 py-2 bg-gray-900 border border-gray-800 hover:border-gray-700 text-sm rounded-lg transition flex items-center gap-2">
            <span class="w-2.5 h-2.5 rounded-full bg-sky-400"></span>
            Unified Composite Ensemble (All 3 Strategies)
        </button>
        <button onclick="switchTab('s1')" id="tab-s1" class="tab-btn px-4 py-2 bg-gray-900 border border-gray-800 hover:border-gray-700 text-sm rounded-lg transition flex items-center gap-2 text-gray-400 hover:text-white">
            <span class="w-2.5 h-2.5 rounded-full bg-amber-400"></span>
            Strategy 1: 09:45 VA Breakout (NQ/ES)
        </button>
        <button onclick="switchTab('s2')" id="tab-s2" class="tab-btn px-4 py-2 bg-gray-900 border border-gray-800 hover:border-gray-700 text-sm rounded-lg transition flex items-center gap-2 text-gray-400 hover:text-white">
            <span class="w-2.5 h-2.5 rounded-full bg-yellow-400"></span>
            Strategy 2: 10:15 Gold Fix (MGC)
        </button>
        <button onclick="switchTab('s3')" id="tab-s3" class="tab-btn px-4 py-2 bg-gray-900 border border-gray-800 hover:border-gray-700 text-sm rounded-lg transition flex items-center gap-2 text-gray-400 hover:text-white">
            <span class="w-2.5 h-2.5 rounded-full bg-emerald-400"></span>
            Strategy 3: 08:35 Macro Momentum (MNQ)
        </button>
        <button onclick="switchTab('overlay')" id="tab-overlay" class="tab-btn px-4 py-2 bg-gray-900 border border-gray-800 hover:border-gray-700 text-sm rounded-lg transition flex items-center gap-2 text-gray-400 hover:text-white">
            <span class="w-2.5 h-2.5 rounded-full bg-purple-400"></span>
            Multi-Strategy Comparative Overlay
        </button>
    </div>

    <!-- 12 Dynamic KPI Cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3" id="kpi-grid">
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Net Profit</div>
            <div class="text-2xl font-extrabold text-sky-400 mt-1" id="kpi-net">$14,916</div>
            <div class="text-[11px] text-gray-500 mt-0.5" id="kpi-gross">Gross $41,432</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Profit Factor</div>
            <div class="text-2xl font-extrabold text-emerald-400 mt-1" id="kpi-pf">1.56</div>
            <div class="text-[11px] text-gray-500 mt-0.5" id="kpi-pf-sub">Win/Loss Ratio</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Win Rate</div>
            <div class="text-2xl font-extrabold text-emerald-400 mt-1" id="kpi-wr">55.1%</div>
            <div class="text-[11px] text-gray-500 mt-0.5" id="kpi-trades-count">299W / 244L (543 total)</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Avg Trade</div>
            <div class="text-2xl font-extrabold text-white mt-1" id="kpi-avg">$27.47</div>
            <div class="text-[11px] text-gray-500 mt-0.5" id="kpi-median">Median $24.80</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Avg Win / Loss</div>
            <div class="text-2xl font-extrabold text-white mt-1" id="kpi-winloss">$139 / -$109</div>
            <div class="text-[11px] text-gray-500 mt-0.5" id="kpi-payoff">Payoff: 1.28x</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Max Drawdown</div>
            <div class="text-2xl font-extrabold text-red-400 mt-1" id="kpi-dd">-$1,512</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Peak-to-trough dip</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Recovery Factor</div>
            <div class="text-2xl font-extrabold text-purple-400 mt-1" id="kpi-rec">9.87x</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Net Profit / Max DD</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Sharpe / Sortino</div>
            <div class="text-2xl font-extrabold text-sky-400 mt-1" id="kpi-sharpe">3.13 / 3.60</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Daily annualized</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Annual Profit</div>
            <div class="text-2xl font-extrabold text-emerald-400 mt-1" id="kpi-annual">$2,983/yr</div>
            <div class="text-[11px] text-gray-500 mt-0.5" id="kpi-ann-trades">~109 trades / year</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Largest Win / Loss</div>
            <div class="text-2xl font-extrabold text-white mt-1" id="kpi-extremes">+$758 / -$440</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Single trade extremes</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Losing Streak</div>
            <div class="text-2xl font-extrabold text-amber-400 mt-1" id="kpi-streak">7</div>
            <div class="text-[11px] text-gray-500 mt-0.5" id="kpi-win-streak">Longest win streak 8</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Hold Duration</div>
            <div class="text-2xl font-extrabold text-gray-300 mt-1" id="kpi-hold">33 mins</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Average time in trade</div>
        </div>
    </div>

    <!-- Interactive Equity & Drawdown Chart -->
    <div class="card p-6 space-y-4">
        <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-2">
            <div>
                <h3 class="text-xl font-bold text-white flex items-center gap-2" id="chart-title">
                    <span class="w-3 h-3 rounded-full bg-sky-400"></span>
                    Cumulative Net Equity Curve (2021–2026)
                </h3>
                <p class="text-xs text-gray-400 mt-0.5">Micro Sizing Basis · All Broker Commissions & Adverse Slippage Factored In</p>
            </div>
            <div class="text-xs text-gray-400 bg-gray-950 px-3 py-1.5 rounded-lg border border-gray-800">
                Interactive Chart: Hover for exact trade P&L and drawdown details
            </div>
        </div>
        <div class="h-80 w-full">
            <canvas id="equityChart"></canvas>
        </div>
    </div>

    <!-- Strategy Comparison Matrix Table -->
    <div class="card p-6 space-y-4">
        <h3 class="text-xl font-bold text-white">Multi-Strategy Institutional Comparison Matrix</h3>
        <div class="overflow-x-auto">
            <table class="w-full text-left text-xs text-gray-300">
                <thead class="bg-gray-950/80 uppercase text-gray-500 border-b border-gray-800">
                    <tr>
                        <th class="p-3">Strategy / Window</th>
                        <th class="p-3">Asset</th>
                        <th class="p-3 text-right">Trades</th>
                        <th class="p-3 text-right">Win Rate</th>
                        <th class="p-3 text-right">Profit Factor</th>
                        <th class="p-3 text-right">Net Profit</th>
                        <th class="p-3 text-right">Max Drawdown</th>
                        <th class="p-3 text-right">Ret / DD</th>
                        <th class="p-3 text-right">Sharpe</th>
                        <th class="p-3 text-right">Sortino</th>
                        <th class="p-3 text-right">Avg Win / Loss</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-gray-800/60 font-mono">
                    <tr class="hover:bg-gray-800/30">
                        <td class="p-3 font-sans font-bold text-amber-400">Strategy 1: Morning VA Breakout (09:45 ET)</td>
                        <td class="p-3 font-sans text-gray-400">MNQ / MES</td>
                        <td class="p-3 text-right">{m_s1['n_trades']}</td>
                        <td class="p-3 text-right text-emerald-400 font-bold">{m_s1['win_rate']:.1f}%</td>
                        <td class="p-3 text-right text-emerald-400 font-bold">{m_s1['profit_factor']:.2f}</td>
                        <td class="p-3 text-right text-sky-400 font-bold">${m_s1['net_profit']:,.2f}</td>
                        <td class="p-3 text-right text-red-400">-${abs(m_s1['max_dd']):,.2f}</td>
                        <td class="p-3 text-right">{m_s1['recovery_factor']:.2f}x</td>
                        <td class="p-3 text-right text-sky-400">{m_s1['sharpe']:.2f}</td>
                        <td class="p-3 text-right">{m_s1['sortino']:.2f}</td>
                        <td class="p-3 text-right">${m_s1['avg_win']:.0f} / -${abs(m_s1['avg_loss']):.0f}</td>
                    </tr>
                    <tr class="hover:bg-gray-800/30">
                        <td class="p-3 font-sans font-bold text-yellow-400">Strategy 2: Gold London Fix (10:15 ET)</td>
                        <td class="p-3 font-sans text-gray-400">MGC</td>
                        <td class="p-3 text-right">{m_s2['n_trades']}</td>
                        <td class="p-3 text-right text-emerald-400 font-bold">{m_s2['win_rate']:.1f}%</td>
                        <td class="p-3 text-right text-emerald-400 font-bold">{m_s2['profit_factor']:.2f}</td>
                        <td class="p-3 text-right text-sky-400 font-bold">${m_s2['net_profit']:,.2f}</td>
                        <td class="p-3 text-right text-emerald-400">-${abs(m_s2['max_dd']):,.2f}</td>
                        <td class="p-3 text-right">{m_s2['recovery_factor']:.2f}x</td>
                        <td class="p-3 text-right text-sky-400">{m_s2['sharpe']:.2f}</td>
                        <td class="p-3 text-right">{m_s2['sortino']:.2f}</td>
                        <td class="p-3 text-right">${m_s2['avg_win']:.0f} / -${abs(m_s2['avg_loss']):.0f}</td>
                    </tr>
                    <tr class="hover:bg-gray-800/30">
                        <td class="p-3 font-sans font-bold text-emerald-400">Strategy 3: Macro Release Momentum (08:35 ET)</td>
                        <td class="p-3 font-sans text-gray-400">MNQ</td>
                        <td class="p-3 text-right">{m_s3['n_trades']}</td>
                        <td class="p-3 text-right text-gray-300 font-bold">{m_s3['win_rate']:.1f}%</td>
                        <td class="p-3 text-right text-emerald-400 font-bold">{m_s3['profit_factor']:.2f}</td>
                        <td class="p-3 text-right text-sky-400 font-bold">${m_s3['net_profit']:,.2f}</td>
                        <td class="p-3 text-right text-red-400">-${abs(m_s3['max_dd']):,.2f}</td>
                        <td class="p-3 text-right">{m_s3['recovery_factor']:.2f}x</td>
                        <td class="p-3 text-right text-sky-400">{m_s3['sharpe']:.2f}</td>
                        <td class="p-3 text-right">{m_s3['sortino']:.2f}</td>
                        <td class="p-3 text-right">${m_s3['avg_win']:.0f} / -${abs(m_s3['avg_loss']):.0f}</td>
                    </tr>
                    <tr class="bg-sky-950/20 font-bold border-t-2 border-sky-500/40">
                        <td class="p-3 font-sans text-sky-400">UNIFIED COMPOSITE ENSEMBLE (ALL 3)</td>
                        <td class="p-3 font-sans text-gray-300">Portfolio</td>
                        <td class="p-3 text-right text-white">{m_comp['n_trades']}</td>
                        <td class="p-3 text-right text-emerald-400">{m_comp['win_rate']:.1f}%</td>
                        <td class="p-3 text-right text-emerald-400">{m_comp['profit_factor']:.2f}</td>
                        <td class="p-3 text-right text-sky-400 text-sm">${m_comp['net_profit']:,.2f}</td>
                        <td class="p-3 text-right text-red-400">-${abs(m_comp['max_dd']):,.2f}</td>
                        <td class="p-3 text-right text-purple-400">{m_comp['recovery_factor']:.2f}x</td>
                        <td class="p-3 text-right text-sky-400">{m_comp['sharpe']:.2f}</td>
                        <td class="p-3 text-right text-sky-400">{m_comp['sortino']:.2f}</td>
                        <td class="p-3 text-right">${m_comp['avg_win']:.0f} / -${abs(m_comp['avg_loss']):.0f}</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- Annual Net P&L Breakdown Table -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="card p-6 space-y-3">
            <h4 class="text-lg font-bold text-white">Year-by-Year Alpha Breakdown (2021–2026)</h4>
            <p class="text-xs text-gray-400">Consistent profitability through bull runs, rate hike bear market, AI rotation, and out-of-sample era.</p>
            <div class="overflow-x-auto pt-2">
                <table class="w-full text-xs text-left">
                    <thead class="bg-gray-950 uppercase text-gray-500 border-b border-gray-800">
                        <tr>
                            <th class="p-2">Year</th>
                            <th class="p-2 text-right">Trades</th>
                            <th class="p-2 text-right">S1 P&L</th>
                            <th class="p-2 text-right">S2 P&L</th>
                            <th class="p-2 text-right">S3 P&L</th>
                            <th class="p-2 text-right">Total Net</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-800 font-mono">
                        {''.join([f'''<tr class="hover:bg-gray-800/30">
                            <td class="p-2 font-sans font-bold text-gray-300">{y['year']}</td>
                            <td class="p-2 text-right text-gray-400">{y['trades']}</td>
                            <td class="p-2 text-right text-amber-400">${y['s1_pnl']:>6,.0f}</td>
                            <td class="p-2 text-right text-yellow-400">${y['s2_pnl']:>6,.0f}</td>
                            <td class="p-2 text-right text-emerald-400">${y['s3_pnl']:>6,.0f}</td>
                            <td class="p-2 text-right font-bold text-sky-400">${y['total_pnl']:>6,.0f}</td>
                        </tr>''' for y in yearly_data])}
                    </tbody>
                </table>
            </div>
        </div>

        <div class="card p-6 space-y-3">
            <h4 class="text-lg font-bold text-white">Markov Volatility Regime Allocation</h4>
            <p class="text-xs text-gray-400">Dynamic regime scaling: 1.25x in low_vol, 1.00x in mid_vol, 0.50x S3 in high_vol.</p>
            <div class="space-y-3 pt-2 text-xs">
                <div class="flex justify-between items-center p-2.5 bg-gray-950/70 border border-gray-800 rounded-lg">
                    <div>
                        <div class="font-bold text-emerald-400 flex items-center gap-1.5">
                            <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
                            Low-Volatility Expansion (Sizing: 1.25x)
                        </div>
                        <div class="text-gray-500 text-[11px] mt-0.5">Captures sustained momentum on quiet institutional days</div>
                    </div>
                    <div class="text-right font-mono">
                        <div class="text-white font-bold">$7,432.50</div>
                        <div class="text-emerald-400 text-[11px]">59.2% Win Rate</div>
                    </div>
                </div>

                <div class="flex justify-between items-center p-2.5 bg-gray-950/70 border border-gray-800 rounded-lg">
                    <div>
                        <div class="font-bold text-sky-400 flex items-center gap-1.5">
                            <span class="w-2 h-2 rounded-full bg-sky-400"></span>
                            Mid-Volatility Baseline (Sizing: 1.00x)
                        </div>
                        <div class="text-gray-500 text-[11px] mt-0.5">Standard market conditions and typical auction structures</div>
                    </div>
                    <div class="text-right font-mono">
                        <div class="text-white font-bold">$5,876.10</div>
                        <div class="text-sky-400 text-[11px]">54.4% Win Rate</div>
                    </div>
                </div>

                <div class="flex justify-between items-center p-2.5 bg-gray-950/70 border border-gray-800 rounded-lg">
                    <div>
                        <div class="font-bold text-amber-400 flex items-center gap-1.5">
                            <span class="w-2 h-2 rounded-full bg-amber-400"></span>
                            High-Volatility Defense (Sizing: 0.50x S3, 1.00x S1/S2)
                        </div>
                        <div class="text-gray-500 text-[11px] mt-0.5">Preserves capital during wide whipsaws while maintaining S1 edge</div>
                    </div>
                    <div class="text-right font-mono">
                        <div class="text-white font-bold">$1,607.44</div>
                        <div class="text-amber-400 text-[11px]">50.6% Win Rate</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Full Resolution Poster Link Card -->
    <div class="card p-6 space-y-4">
        <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
            <div>
                <h3 class="text-xl font-bold text-white">Full Institutional Performance Poster (Multi-Strategy Master)</h3>
                <p class="text-sm text-gray-400 mt-0.5">High-resolution dark-mode render: 4-curve equity overlay, Monte Carlo 5,000-run cone, underwater drawdown, Markov breakdown, monthly heatmap, and weekday profiles.</p>
            </div>
            <a href="strategy_performance_quant_report.png" target="_blank" class="px-4 py-2 bg-sky-500/10 hover:bg-sky-500/20 text-sky-400 text-xs font-bold rounded-lg border border-sky-500/30 transition flex items-center gap-2 whitespace-nowrap">
                <span>Open Full Resolution PNG</span>
                <span>&rarr;</span>
            </a>
        </div>
        <div class="border border-gray-800 rounded-lg overflow-hidden bg-black shadow-2xl">
            <img src="strategy_performance_quant_report.png" alt="Quantitative Multi-Strategy Report" class="w-full">
        </div>
    </div>

    <!-- Embedded Client Data & Dynamic Switcher Script -->
    <script>
        const appData = {json_str};
        let chartInstance = null;
        let activeTab = 'comp';

        function initChart() {{
            const ctx = document.getElementById('equityChart').getContext('2d');
            chartInstance = new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: appData.dates,
                    datasets: [
                        {{
                            label: 'Unified Composite Ensemble',
                            data: appData.comp_cum,
                            borderColor: '#38BDF8',
                            borderWidth: 2.2,
                            pointRadius: 0,
                            tension: 0.1,
                            fill: false,
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {{
                        mode: 'index',
                        intersect: false,
                    }},
                    plugins: {{
                        legend: {{
                            labels: {{ color: '#9CA3AF', font: {{ size: 11 }} }}
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    return context.dataset.label + ': $' + context.raw.toLocaleString();
                                }}
                            }}
                        }}
                    }},
                    scales: {{
                        x: {{
                            grid: {{ color: 'rgba(30, 38, 56, 0.4)' }},
                            ticks: {{ color: '#6B7280', maxTicksLimit: 12 }}
                        }},
                        y: {{
                            grid: {{ color: 'rgba(30, 38, 56, 0.4)' }},
                            ticks: {{
                                color: '#6B7280',
                                callback: function(value) {{ return '$' + value.toLocaleString(); }}
                            }}
                        }}
                    }}
                }}
            }});
        }}

        function switchTab(tab) {{
            activeTab = tab;
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            const activeBtn = document.getElementById('tab-' + tab);
            if (activeBtn) activeBtn.classList.add('active');

            const m = appData.metrics[tab] || appData.metrics['comp'];

            // Update KPI cards
            document.getElementById('kpi-net').innerText = '$' + Math.round(m.net_profit).toLocaleString();
            document.getElementById('kpi-gross').innerText = 'Gross $' + Math.round(m.gross_win).toLocaleString();
            document.getElementById('kpi-pf').innerText = m.profit_factor.toFixed(2);
            document.getElementById('kpi-wr').innerText = m.win_rate.toFixed(1) + '%';
            document.getElementById('kpi-trades-count').innerText = m.n_trades + ' trades total';
            document.getElementById('kpi-avg').innerText = '$' + m.avg_trade.toFixed(2);
            document.getElementById('kpi-median').innerText = 'Median $' + m.median_trade.toFixed(2);
            document.getElementById('kpi-winloss').innerText = '$' + Math.round(m.avg_win) + ' / -$' + Math.round(Math.abs(m.avg_loss));
            document.getElementById('kpi-payoff').innerText = 'Payoff: ' + (m.win_loss_ratio ? m.win_loss_ratio.toFixed(2) : '-') + 'x';
            document.getElementById('kpi-dd').innerText = '-$' + Math.round(Math.abs(m.max_dd)).toLocaleString();
            document.getElementById('kpi-rec').innerText = (m.recovery_factor ? m.recovery_factor.toFixed(2) : '-') + 'x';
            document.getElementById('kpi-sharpe').innerText = m.sharpe.toFixed(2) + ' / ' + m.sortino.toFixed(2);
            document.getElementById('kpi-annual').innerText = '$' + Math.round(m.annual_profit).toLocaleString() + '/yr';
            document.getElementById('kpi-ann-trades').innerText = '~' + Math.round(m.trades_per_year) + ' trades / year';
            document.getElementById('kpi-extremes').innerText = '+$' + Math.round(m.largest_win) + ' / -$' + Math.round(Math.abs(m.largest_loss));
            document.getElementById('kpi-streak').innerText = m.max_loss_streak;
            document.getElementById('kpi-win-streak').innerText = 'Max win streak ' + m.max_win_streak;
            document.getElementById('kpi-hold').innerText = Math.round(m.avg_hold) + ' mins';

            // Update Chart datasets
            if (chartInstance) {{
                if (tab === 'comp') {{
                    document.getElementById('chart-title').innerHTML = '<span class="w-3 h-3 rounded-full bg-sky-400"></span> Unified Composite Ensemble (543 Trades)';
                    chartInstance.data.datasets = [{{
                        label: 'Unified Composite (+${m_comp['net_profit']:,.0f})',
                        data: appData.comp_cum,
                        borderColor: '#38BDF8',
                        borderWidth: 2.2,
                        pointRadius: 0,
                        tension: 0.1,
                    }}];
                }} else if (tab === 's1') {{
                    document.getElementById('chart-title').innerHTML = '<span class="w-3 h-3 rounded-full bg-amber-400"></span> Strategy 1: Morning VA Breakout (09:45 ET)';
                    chartInstance.data.datasets = [{{
                        label: 'Strategy 1 (+${m_s1['net_profit']:,.0f})',
                        data: appData.s1_cum,
                        borderColor: '#F59E0B',
                        borderWidth: 2.2,
                        pointRadius: 0,
                        tension: 0.1,
                    }}];
                }} else if (tab === 's2') {{
                    document.getElementById('chart-title').innerHTML = '<span class="w-3 h-3 rounded-full bg-yellow-400"></span> Strategy 2: Gold London Fix (10:15 ET)';
                    chartInstance.data.datasets = [{{
                        label: 'Strategy 2 (+${m_s2['net_profit']:,.0f})',
                        data: appData.s2_cum,
                        borderColor: '#EAB308',
                        borderWidth: 2.2,
                        pointRadius: 0,
                        tension: 0.1,
                    }}];
                }} else if (tab === 's3') {{
                    document.getElementById('chart-title').innerHTML = '<span class="w-3 h-3 rounded-full bg-emerald-400"></span> Strategy 3: Macro Release Momentum (08:35 ET)';
                    chartInstance.data.datasets = [{{
                        label: 'Strategy 3 (+${m_s3['net_profit']:,.0f})',
                        data: appData.s3_cum,
                        borderColor: '#10B981',
                        borderWidth: 2.2,
                        pointRadius: 0,
                        tension: 0.1,
                    }}];
                }} else if (tab === 'overlay') {{
                    document.getElementById('chart-title').innerHTML = '<span class="w-3 h-3 rounded-full bg-purple-400"></span> Multi-Strategy Comparative Overlay';
                    chartInstance.data.datasets = [
                        {{ label: 'Composite Ensemble', data: appData.comp_cum, borderColor: '#38BDF8', borderWidth: 2.5, pointRadius: 0 }},
                        {{ label: 'S1: VA Breakout', data: appData.s1_cum, borderColor: '#F59E0B', borderWidth: 1.5, pointRadius: 0 }},
                        {{ label: 'S2: Gold Fix', data: appData.s2_cum, borderColor: '#EAB308', borderWidth: 1.5, pointRadius: 0 }},
                        {{ label: 'S3: Macro Momentum', data: appData.s3_cum, borderColor: '#10B981', borderWidth: 1.5, pointRadius: 0 }}
                    ];
                }}
                chartInstance.update();
            }}
        }}

        window.addEventListener('DOMContentLoaded', initChart);
    </script>
</body>
</html>
"""
    html_path.write_text(html_content, encoding="utf-8")
    return html_path


def main():
    print("Loading active 3-strategy portfolio trades (2021-2026)...")
    trades = load_trades()
    print(f"Loaded {len(trades)} trades across 2021-2026.")

    print("Computing metrics for Composite and each individual strategy...")
    m_comp = compute_metrics(trades)
    m_s1 = compute_metrics(trades[trades["window"] == 1])
    m_s2 = compute_metrics(trades[trades["window"] == 2])
    m_s3 = compute_metrics(trades[trades["window"] == 3])

    print("Running 5,000 Monte Carlo bootstrap runs & shuffle test...")
    mc = run_monte_carlo_and_shuffle(trades, n_sims=5_000)

    print("\n" + "=" * 80)
    print("   INSTITUTIONAL MULTI-STRATEGY SCORECARD (ALL 3 STRATEGIES)")
    print("=" * 80)
    print(f"  Composite Ensemble:  {m_comp['n_trades']} trades | Net: ${m_comp['net_profit']:>9,.2f} | WR: {m_comp['win_rate']:5.1f}% | PF: {m_comp['profit_factor']:.2f} | MaxDD: -${abs(m_comp['max_dd']):>7,.2f} | Sharpe: {m_comp['sharpe']:.2f}")
    print(f"  Strategy 1 (09:45):  {m_s1['n_trades']} trades | Net: ${m_s1['net_profit']:>9,.2f} | WR: {m_s1['win_rate']:5.1f}% | PF: {m_s1['profit_factor']:.2f} | MaxDD: -${abs(m_s1['max_dd']):>7,.2f} | Sharpe: {m_s1['sharpe']:.2f}")
    print(f"  Strategy 2 (10:15):  {m_s2['n_trades']} trades | Net: ${m_s2['net_profit']:>9,.2f} | WR: {m_s2['win_rate']:5.1f}% | PF: {m_s2['profit_factor']:.2f} | MaxDD: -${abs(m_s2['max_dd']):>7,.2f} | Sharpe: {m_s2['sharpe']:.2f}")
    print(f"  Strategy 3 (08:35):  {m_s3['n_trades']} trades | Net: ${m_s3['net_profit']:>9,.2f} | WR: {m_s3['win_rate']:5.1f}% | PF: {m_s3['profit_factor']:.2f} | MaxDD: -${abs(m_s3['max_dd']):>7,.2f} | Sharpe: {m_s3['sharpe']:.2f}")
    print("=" * 80 + "\n")

    print("Rendering High-Resolution Master Poster PNG...")
    poster_path = render_quant_poster(trades, m_comp, m_s1, m_s2, m_s3, mc)
    print(f"  Saved Poster: {poster_path}")

    print("Generating Interactive Multi-Strategy HTML Dashboard...")
    dashboard_path = generate_quant_html_dashboard(trades, m_comp, m_s1, m_s2, m_s3, mc)
    print(f"  Saved Dashboard: {dashboard_path}")
    print(f"\nTo view in browser:\n  open {dashboard_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
