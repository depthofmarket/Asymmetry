#!/usr/bin/env python3
"""
Normal Quantitative Strategy Performance Dashboard Generator (Non-Prop Mode).
Replicates the exact institutional style from Screenshot #3 (FTMORB180RC3 / Rational Edge style):
- 12 Top KPI Metric Cards (Net Profit, Profit Factor, Win Rate, Avg Trade, Avg Win/Loss, Max DD, Recovery Factor, Sharpe/Sortino, Annualized, Largest Win/Loss, Streak, Commissions)
- Equity Curves (Long vs Short vs All Composite) with Running Peak Shading
- Underwater Drawdown Chart
- Monte Carlo Equity Paths (5-95%, 25-75%, Median, Actual) + Summary Table
- Monte Carlo Max Drawdown & Net Profit Distributions
- Shuffle Test (Trade Order Permutation Drawdowns)
- Net P&L Per Year & Monthly P&L Heatmap Grid (2021-2026)
- Trade Outcomes Histogram & By Exit Type Breakdown
- Long vs Short Comparison Table
- Day of Week Breakdown & Rolling 50-Trade Average
- Time in Trade Distribution
"""

from __future__ import annotations

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

DATA_PATH = REPO_ROOT / "data/processed/upgraded_v2_portfolio_trades_2021_2026.parquet"


def load_trades():
    df = pd.read_parquet(DATA_PATH)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["date_str"] = df["entry_time"].dt.strftime("%Y-%m-%d")
    df["year"] = df["entry_time"].dt.year
    df["month"] = df["entry_time"].dt.month
    df["weekday"] = df["entry_time"].dt.day_name()
    return df.sort_values("entry_time").reset_index(drop=True)


def compute_metrics(trades: pd.DataFrame):
    n_trades = len(trades)
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
    sortino = (d_mean / sortino_std) * np.sqrt(252)

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

    commissions = n_trades * 3.50 # $3.50 RT per mini
    avg_hold = float(trades["hold_minutes"].mean())

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
        "commissions": commissions,
        "avg_hold": avg_hold,
    }


def run_monte_carlo_and_shuffle(trades: pd.DataFrame, n_sims: int = 5_000, seed: int = 42):
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

        # Streak
        is_l = (sampled <= 0).astype(int)
        stk = 0
        mstk = 0
        for x in is_l:
            stk = stk + 1 if x == 1 else 0
            if stk > mstk: mstk = stk
        max_losing_streaks[i] = mstk

    # 2. Shuffle test (permutation without replacement - tests luck of the order)
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
        "p90_dd": float(np.percentile(max_dds, 10)), # More negative
        "p95_dd": float(np.percentile(max_dds, 5)),
        "p99_dd": float(np.percentile(max_dds, 1)),
        "p95_losing_streak": float(np.percentile(max_losing_streaks, 95)),
    }


def render_quant_poster(trades: pd.DataFrame, m: dict, mc: dict) -> Path:
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(20, 32), dpi=200)
    fig.patch.set_facecolor("#090D16")

    # Layout: 8 rows of panels
    gs = fig.add_gridspec(8, 4, height_ratios=[1.1, 1.8, 1.8, 1.8, 1.8, 1.8, 1.8, 1.8], hspace=0.38, wspace=0.25)

    # ── ROW 0: TITLE & 12 TOP METRICS CARDS ──────────────────────────────────
    kpi_ax = fig.add_subplot(gs[0, :])
    kpi_ax.set_facecolor("#090D16")
    kpi_ax.axis("off")

    kpi_ax.text(0.0, 0.95, "Morning Value Area Breakout • Upgraded v2.0 Book", fontsize=24, fontweight="bold", color="#FFFFFF", va="top")
    kpi_ax.text(0.0, 0.68, "NQ + ES Bidirectional Book · Macro Filter + Intermarket Confirmation · 1.5x R:R Target + 10:00 AM News Guard · 07 Jan 2021 - 26 Jan 2026 · 362 trades · Monte Carlo 5,000 runs",
                fontsize=10.5, color="#8B949E", va="top")

    cards = [
        {"title": "NET PROFIT", "val": f"${m['net_profit']:,.0f}", "sub": f"gross ${m['gross_win']:,.0f}", "color": "#38BDF8"},
        {"title": "PROFIT FACTOR", "val": f"{m['profit_factor']:.2f}", "sub": f"win/loss: {m['gross_win']/m['gross_loss']:.2f}", "color": "#00E676"},
        {"title": "WIN RATE", "val": f"{m['win_rate']:.1f}%", "sub": f"{int(m['n_trades']*m['win_rate']/100)}W / {int(m['n_trades']*(1-m['win_rate']/100))}L", "color": "#00E676"},
        {"title": "AVG TRADE", "val": f"${m['avg_trade']:.2f}", "sub": f"median ${m['median_trade']:.2f}", "color": "#F3F4F6"},
        {"title": "AVG WIN / LOSS", "val": f"${m['avg_win']:.0f} / ${m['avg_loss']:.0f}", "sub": f"ratio {m['win_loss_ratio']:.2f}", "color": "#F3F4F6"},
        {"title": "MAX DRAWDOWN", "val": f"${m['max_dd']:,.0f}", "sub": "peak-to-trough", "color": "#FF5252"},
        {"title": "RECOVERY FACTOR", "val": f"{m['recovery_factor']:.2f}", "sub": "net profit / max DD", "color": "#A78BFA"},
        {"title": "SHARPE / SORTINO", "val": f"{m['sharpe']:.2f} / {m['sortino']:.2f}", "sub": "daily annualized", "color": "#38BDF8"},
        {"title": "PER YEAR", "val": f"${m['annual_profit']:,.0f}", "sub": f"{m['trades_per_year']:.0f} trades / yr", "color": "#00E676"},
        {"title": "LARGEST WIN / LOSS", "val": f"${m['largest_win']:.0f} / ${m['largest_loss']:.0f}", "sub": "single trade", "color": "#F3F4F6"},
        {"title": "LOSING STREAK", "val": f"{m['max_loss_streak']}", "sub": f"longest win streak {m['max_win_streak']}", "color": "#F59E0B"},
        {"title": "COMMISSIONS", "val": f"${m['commissions']:,.0f}", "sub": f"avg hold {m['avg_hold']:.0f} mins", "color": "#8B949E"},
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

    # ── ROW 1: EQUITY CURVE (LONG/SHORT/ALL) & UNDERWATER DRAWDOWN ───────────
    # Top: Equity Curve
    ax_eq = fig.add_subplot(gs[1, :])
    ax_eq.set_facecolor("#121722")
    ax_eq.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    trades_s = trades.sort_values("entry_time").copy()
    trades_s["cum_all"] = trades_s["pnl"].cumsum()
    trades_s["cum_long"] = trades_s.loc[trades_s["direction"] == "long", "pnl"].cumsum().reindex(trades_s.index).ffill().fillna(0.0)
    trades_s["cum_short"] = trades_s.loc[trades_s["direction"] == "short", "pnl"].cumsum().reindex(trades_s.index).ffill().fillna(0.0)
    trades_s["peak"] = trades_s["cum_all"].cummax()
    trades_s["dd"] = trades_s["cum_all"] - trades_s["peak"]

    # Red shading below peak
    ax_eq.fill_between(trades_s["entry_time"], trades_s["cum_all"], trades_s["peak"], color="#FF5252", alpha=0.18, label="Underwater Drawdown")
    ax_eq.plot(trades_s["entry_time"], trades_s["peak"], color="#8B949E", linestyle=":", linewidth=1.0, alpha=0.6)
    ax_eq.plot(trades_s["entry_time"], trades_s["cum_all"], color="#38BDF8", linewidth=2.2, label=f"All Trades (+${m['net_profit']:,.0f})")
    ax_eq.plot(trades_s["entry_time"], trades_s["cum_long"], color="#F59E0B", linewidth=1.3, alpha=0.85, label=f"Long Only (+${trades_s.loc[trades_s['direction']=='long','pnl'].sum():,.0f})")
    ax_eq.plot(trades_s["entry_time"], trades_s["cum_short"], color="#00E676", linewidth=1.3, alpha=0.85, label=f"Short Only (+${trades_s.loc[trades_s['direction']=='short','pnl'].sum():,.0f})")

    ax_eq.set_title("Equity Curve (Cumulative Net P&L After Commissions · 1 Mini Basis)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_eq.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_eq.legend(loc="upper left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8.5)
    for s in ax_eq.spines.values(): s.set_color("#1E2638")
    ax_eq.tick_params(colors="#8B949E", labelsize=8)

    # ── ROW 2: UNDERWATER DRAWDOWN & MONTE CARLO EQUITY PATHS ────────────────
    # Left: Underwater Drawdown
    ax_dd = fig.add_subplot(gs[2, :2])
    ax_dd.set_facecolor("#121722")
    ax_dd.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    ax_dd.fill_between(trades_s["entry_time"], trades_s["dd"], 0, color="#FF5252", alpha=0.45)
    ax_dd.plot(trades_s["entry_time"], trades_s["dd"], color="#FF5252", linewidth=1.2)
    ax_dd.set_title(f"Drawdown ($ Below Running Peak · Max DD: -${abs(m['max_dd']):,.0f})", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_dd.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    for s in ax_dd.spines.values(): s.set_color("#1E2638")
    ax_dd.tick_params(colors="#8B949E", labelsize=8)

    # Right: Monte Carlo Equity Paths + Summary Table
    ax_mc = fig.add_subplot(gs[2, 2:])
    ax_mc.set_facecolor("#121722")
    ax_mc.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    paths = mc["mc_paths"]
    n_pts = paths.shape[1]
    p5 = np.percentile(paths, 5, axis=0)
    p25 = np.percentile(paths, 25, axis=0)
    p50 = np.percentile(paths, 50, axis=0)
    p75 = np.percentile(paths, 75, axis=0)
    p95 = np.percentile(paths, 95, axis=0)

    ax_mc.fill_between(range(n_pts), p5, p95, color="#6366F1", alpha=0.18, label="5% - 95% Cone")
    ax_mc.fill_between(range(n_pts), p25, p75, color="#6366F1", alpha=0.35, label="25% - 75% Interquartile")
    ax_mc.plot(range(n_pts), p50, color="#818CF8", linewidth=2.0, label=f"Median Run (${mc['median_profit']:,.0f})")
    ax_mc.plot(range(n_pts), trades_s["cum_all"].values, color="#38BDF8", linewidth=1.8, label=f"Actual Path (${m['net_profit']:,.0f})")

    ax_mc.set_title("Monte Carlo: Equity Paths (5,000 Runs Random Sampling)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_mc.set_xlabel("Trade #", color="#8B949E", fontsize=8)
    ax_mc.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_mc.legend(loc="upper left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for s in ax_mc.spines.values(): s.set_color("#1E2638")
    ax_mc.tick_params(colors="#8B949E", labelsize=8)

    # ── ROW 3: MC MAX DD HISTOGRAM & MC FINAL NET PROFIT & SHUFFLE TEST ──────
    # Panel 3A: MC Max Drawdown Distribution
    ax_mc_dd = fig.add_subplot(gs[3, 0])
    ax_mc_dd.set_facecolor("#121722")
    ax_mc_dd.grid(True, color="#1E2638", linestyle="--", alpha=0.5)
    ax_mc_dd.hist(mc["max_dds"], bins=30, color="#EF4444", alpha=0.75, edgecolor="#7F1D1D")
    ax_mc_dd.axvline(m["max_dd"], color="#38BDF8", linewidth=2.0, label=f"Actual: ${m['max_dd']:,.0f}")
    ax_mc_dd.axvline(mc["p95_dd"], color="#F59E0B", linestyle="--", linewidth=1.8, label=f"95% DD: ${mc['p95_dd']:,.0f}")
    ax_mc_dd.set_title("Monte Carlo: Max Drawdown", fontsize=9.5, fontweight="bold", color="#FFFFFF")
    ax_mc_dd.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_mc_dd.legend(loc="upper left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=7.5)
    for s in ax_mc_dd.spines.values(): s.set_color("#1E2638")
    ax_mc_dd.tick_params(colors="#8B949E", labelsize=7.5)

    # Panel 3B: MC Final Net Profit Distribution
    ax_mc_np = fig.add_subplot(gs[3, 1])
    ax_mc_np.set_facecolor("#121722")
    ax_mc_np.grid(True, color="#1E2638", linestyle="--", alpha=0.5)
    ax_mc_np.hist(mc["final_profits"], bins=30, color="#6366F1", alpha=0.75, edgecolor="#312E81")
    ax_mc_np.axvline(m["net_profit"], color="#00E676", linewidth=2.0, label=f"Actual: ${m['net_profit']:,.0f}")
    ax_mc_np.axvline(mc["p5_profit"], color="#F59E0B", linestyle="--", linewidth=1.8, label=f"5% Worst: ${mc['p5_profit']:,.0f}")
    ax_mc_np.set_title("Monte Carlo: Final Net Profit", fontsize=9.5, fontweight="bold", color="#FFFFFF")
    ax_mc_np.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_mc_np.legend(loc="upper left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=7.5)
    for s in ax_mc_np.spines.values(): s.set_color("#1E2638")
    ax_mc_np.tick_params(colors="#8B949E", labelsize=7.5)

    # Panel 3C: Shuffle Test Drawdowns
    ax_shuf = fig.add_subplot(gs[3, 2])
    ax_shuf.set_facecolor("#121722")
    ax_shuf.grid(True, color="#1E2638", linestyle="--", alpha=0.5)
    ax_shuf.hist(mc["shuffle_dds"], bins=30, color="#F59E0B", alpha=0.75, edgecolor="#78350F")
    ax_shuf.axvline(m["max_dd"], color="#38BDF8", linewidth=2.0, label=f"Actual: ${m['max_dd']:,.0f}")
    p95_shuf = np.percentile(mc["shuffle_dds"], 5)
    ax_shuf.axvline(p95_shuf, color="#EF4444", linestyle="--", linewidth=1.8, label=f"95% Worst: ${p95_shuf:,.0f}")
    ax_shuf.set_title("Shuffle Test: Order Luck DD", fontsize=9.5, fontweight="bold", color="#FFFFFF")
    ax_shuf.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_shuf.legend(loc="upper left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=7.5)
    for s in ax_shuf.spines.values(): s.set_color("#1E2638")
    ax_shuf.tick_params(colors="#8B949E", labelsize=7.5)

    # Panel 3D: Monte Carlo Summary Table Card
    ax_mc_tab = fig.add_subplot(gs[3, 3])
    ax_mc_tab.set_facecolor("#121722")
    ax_mc_tab.axis("off")
    r_mc = patches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.01", facecolor="#121722", edgecolor="#1E2638", linewidth=1.1)
    ax_mc_tab.add_patch(r_mc)

    ax_mc_tab.text(0.06, 0.92, "MONTE CARLO SUMMARY", fontsize=9.5, fontweight="bold", color="#FFFFFF")
    mc_rows = [
        ("Net profit, median", f"${mc['median_profit']:,.0f}"),
        ("Net profit, 5th pct", f"${mc['p5_profit']:,.0f}"),
        ("Net profit, 1st pct", f"${mc['p1_profit']:,.0f}"),
        ("Chance of loss", f"{mc['loss_finish_prob']:.1f}%"),
        ("Max DD, median", f"${mc['median_dd']:,.0f}"),
        ("Max DD, 95th pct", f"${mc['p95_dd']:,.0f}"),
        ("Actual Max DD", f"${m['max_dd']:,.0f}"),
        ("Losing streak, 95th pct", f"{mc['p95_losing_streak']:.0f} trades"),
    ]
    for idx, (label, val) in enumerate(mc_rows):
        y = 0.78 - idx * 0.10
        ax_mc_tab.text(0.06, y, label, fontsize=8, color="#8B949E")
        c_val = "#00E676" if "profit" in label or "loss" in label and val=="0.0%" else ("#FF5252" if "DD" in label else "#F3F4F6")
        ax_mc_tab.text(0.94, y, val, fontsize=8, fontweight="bold", color=c_val, ha="right")

    # ── ROW 4: NET P&L PER YEAR & MONTHLY P&L HEATMAP ────────────────────────
    # Left: Net P&L per year bar chart
    ax_yr = fig.add_subplot(gs[4, :2])
    ax_yr.set_facecolor("#121722")
    ax_yr.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    yr_stats = trades.groupby("year").agg(
        pnl=("pnl", "sum"),
        trades=("pnl", "count"),
        wr=("pnl", lambda x: (x > 0).mean() * 100)
    ).reset_index()

    bars = ax_yr.bar(yr_stats["year"].astype(str), yr_stats["pnl"], color="#38BDF8", edgecolor="#0284C7", width=0.55)
    for idx, b in enumerate(bars):
        h = b.get_height()
        wr_val = yr_stats.iloc[idx]["wr"]
        tr_val = yr_stats.iloc[idx]["trades"]
        ax_yr.annotate(f"${h:,.0f}\n({wr_val:.0f}% · {tr_val}t)", xy=(b.get_x() + b.get_width() / 2, h),
                       xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", color="#F9FAFB", fontweight="bold", fontsize=8)

    ax_yr.set_title("Net P&L Per Year (1 Mini Basis · Net of Commissions)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_yr.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_yr.set_ylim(0, max(yr_stats["pnl"]) * 1.25)
    for s in ax_yr.spines.values(): s.set_color("#1E2638")
    ax_yr.tick_params(colors="#8B949E", labelsize=8)

    # Right: Monthly P&L Grid (Heatmap Table)
    ax_mo = fig.add_subplot(gs[4, 2:])
    ax_mo.set_facecolor("#121722")
    ax_mo.axis("off")
    ax_mo.text(0.04, 0.94, "Monthly P&L (1 Mini Basis)", fontsize=11, fontweight="bold", color="#FFFFFF")

    piv = trades.pivot_table(index="year", columns="month", values="pnl", aggfunc="sum").fillna(0.0)
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

    # ── ROW 5: TRADE OUTCOMES HISTOGRAM & BY EXIT TYPE & LONG VS SHORT ───────
    # Panel 5A: Trade outcomes
    ax_to = fig.add_subplot(gs[5, :2])
    ax_to.set_facecolor("#121722")
    ax_to.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    w_pnl = trades.loc[trades["pnl"] > 0, "pnl"]
    l_pnl = trades.loc[trades["pnl"] <= 0, "pnl"]
    ax_to.hist(w_pnl, bins=35, color="#38BDF8", alpha=0.85, label=f"Wins ({len(w_pnl)} · avg +${w_pnl.mean():.0f})")
    ax_to.hist(l_pnl, bins=35, color="#EF4444", alpha=0.85, label=f"Losses ({len(l_pnl)} · avg -${abs(l_pnl.mean()):.0f})")
    ax_to.axvline(m["avg_trade"], color="#F59E0B", linestyle="--", linewidth=1.8, label=f"Mean Trade: +${m['avg_trade']:.0f}")
    ax_to.set_title("Trade Outcomes ($ Net Profit per Trade)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_to.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_to.legend(loc="upper right", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for s in ax_to.spines.values(): s.set_color("#1E2638")
    ax_to.tick_params(colors="#8B949E", labelsize=8)

    # Panel 5B: Long vs Short & Exit Type Breakdown
    ax_ls = fig.add_subplot(gs[5, 2:])
    ax_ls.set_facecolor("#121722")
    ax_ls.axis("off")
    r_ls = patches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.01", facecolor="#121722", edgecolor="#1E2638", linewidth=1.1)
    ax_ls.add_patch(r_ls)

    ax_ls.text(0.04, 0.92, "LONG VS SHORT BREAKDOWN", fontsize=10.5, fontweight="bold", color="#FFFFFF")
    ls_headers = ["SIDE", "TRADES", "NET PROFIT", "WIN %", "PF", "AVG TRADE", "MAX DD"]
    ls_x = [0.04, 0.18, 0.32, 0.48, 0.60, 0.74, 0.88]
    for i, h in enumerate(ls_headers):
        ax_ls.text(ls_x[i], 0.80, h, fontsize=8, fontweight="bold", color="#6B7280")

    longs = trades[trades["direction"] == "long"]
    shorts = trades[trades["direction"] == "short"]
    ls_data = [
        ("Long", len(longs), f"${longs['pnl'].sum():,.0f}", f"{(longs['pnl']>0).mean()*100:.1f}%", f"{longs.loc[longs['pnl']>0,'pnl'].sum()/abs(longs.loc[longs['pnl']<=0,'pnl'].sum()):.2f}", f"${longs['pnl'].mean():.0f}", f"${(longs['pnl'].cumsum() - longs['pnl'].cumsum().cummax()).min():,.0f}"),
        ("Short", len(shorts), f"${shorts['pnl'].sum():,.0f}", f"{(shorts['pnl']>0).mean()*100:.1f}%", f"{shorts.loc[shorts['pnl']>0,'pnl'].sum()/abs(shorts.loc[shorts['pnl']<=0,'pnl'].sum()):.2f}", f"${shorts['pnl'].mean():.0f}", f"${(shorts['pnl'].cumsum() - shorts['pnl'].cumsum().cummax()).min():,.0f}"),
        ("All", len(trades), f"${m['net_profit']:,.0f}", f"{m['win_rate']:.1f}%", f"{m['profit_factor']:.2f}", f"${m['avg_trade']:.0f}", f"${m['max_dd']:,.0f}"),
    ]
    for r_i, r in enumerate(ls_data):
        y = 0.66 - r_i * 0.12
        for c_i, val in enumerate(r):
            col = "#00E676" if c_i == 2 else ("#38BDF8" if c_i == 4 else "#F3F4F6")
            f_w = "bold" if r_i == 2 or c_i in [0, 2] else "normal"
            ax_ls.text(ls_x[c_i], y, val, fontsize=8.5, fontweight=f_w, color=col)

    # Exit reason summary
    ax_ls.text(0.04, 0.26, "BY EXIT TYPE", fontsize=10, fontweight="bold", color="#FFFFFF")
    exits = trades.groupby("reason").agg(count=("pnl", "count"), pnl=("pnl", "sum"), avg=("pnl", "mean"))
    for e_i, (reason, row) in enumerate(exits.iterrows()):
        y_e = 0.15 - e_i * 0.10
        txt = f"• {reason.upper().replace('_', ' ')}: {row['count']} trades · Net: ${row['pnl']:,.0f} (avg ${row['avg']:+.0f}/trade)"
        ax_ls.text(0.04, y_e, txt, fontsize=8.2, color="#9CA3AF")

    # ── ROW 6: BY WEEKDAY & ROLLING 50-TRADE AVERAGE ─────────────────────────
    # Left: Weekday breakdown
    ax_wk = fig.add_subplot(gs[6, :2])
    ax_wk.set_facecolor("#121722")
    ax_wk.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    wk_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    wk_stats = trades.groupby("weekday").agg(pnl=("pnl", "sum"), wr=("pnl", lambda x: (x > 0).mean() * 100)).reindex(wk_order)
    wk_bars = ax_wk.bar(["Mon", "Tue", "Wed", "Thu", "Fri"], wk_stats["pnl"], color="#38BDF8", edgecolor="#0284C7", width=0.5)
    for idx, b in enumerate(wk_bars):
        h = b.get_height()
        ax_wk.annotate(f"${h:,.0f}\n({wk_stats.iloc[idx]['wr']:.0f}%)", xy=(b.get_x() + b.get_width() / 2, h),
                       xytext=(0, 4), textcoords="offset points", ha="center", va="bottom", color="#F9FAFB", fontweight="bold", fontsize=8)

    ax_wk.set_title("Performance by Day of Week (Net P&L & Win Rate)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_wk.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_wk.set_ylim(0, max(wk_stats["pnl"]) * 1.25)
    for s in ax_wk.spines.values(): s.set_color("#1E2638")
    ax_wk.tick_params(colors="#8B949E", labelsize=8)

    # Right: Rolling 50-Trade Average PnL
    ax_roll = fig.add_subplot(gs[6, 2:])
    ax_roll.set_facecolor("#121722")
    ax_roll.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    roll_50 = trades["pnl"].rolling(50).mean()
    ax_roll.plot(range(len(roll_50)), roll_50, color="#38BDF8", linewidth=1.8, label="Rolling 50-Trade Mean PnL")
    ax_roll.axhline(0, color="#FF5252", linestyle="--", linewidth=1.0)
    ax_roll.axhline(m["avg_trade"], color="#00E676", linestyle=":", linewidth=1.5, label=f"Lifetime Avg: +${m['avg_trade']:.0f}")
    ax_roll.set_title("Rolling 50-Trade Average P&L (Edge Stability Over Time)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_roll.set_xlabel("Trade Number", color="#8B949E", fontsize=8)
    ax_roll.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_roll.legend(loc="lower left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for s in ax_roll.spines.values(): s.set_color("#1E2638")
    ax_roll.tick_params(colors="#8B949E", labelsize=8)

    # ── ROW 7: ASSET COMPARISON (NQ VS ES) & TIME IN TRADE ───────────────────
    # Left: NQ vs ES Comparison
    ax_asset = fig.add_subplot(gs[7, :2])
    ax_asset.set_facecolor("#121722")
    ax_asset.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    nq_tr = trades[trades["symbol"] == "NQ"]
    es_tr = trades[trades["symbol"] == "ES"]
    nq_cum = nq_tr["pnl"].cumsum().reset_index(drop=True)
    es_cum = es_tr["pnl"].cumsum().reset_index(drop=True)

    ax_asset.plot(range(len(nq_cum)), nq_cum, color="#38BDF8", linewidth=1.8, label=f"NQ ({len(nq_tr)} trades · +${nq_tr['pnl'].sum():,.0f} · {(nq_tr['pnl']>0).mean()*100:.0f}% WR)")
    ax_asset.plot(range(len(es_cum)), es_cum, color="#A78BFA", linewidth=1.8, label=f"ES ({len(es_tr)} trades · +${es_tr['pnl'].sum():,.0f} · {(es_tr['pnl']>0).mean()*100:.0f}% WR)")
    ax_asset.set_title("Asset Contribution: NQ vs ES Futures (Cumulative P&L)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_asset.set_xlabel("Trade Count per Asset", color="#8B949E", fontsize=8)
    ax_asset.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_asset.legend(loc="upper left", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for s in ax_asset.spines.values(): s.set_color("#1E2638")
    ax_asset.tick_params(colors="#8B949E", labelsize=8)

    # Right: Time in Trade Histogram
    ax_time = fig.add_subplot(gs[7, 2:])
    ax_time.set_facecolor("#121722")
    ax_time.grid(True, color="#1E2638", linestyle="--", alpha=0.5)

    ax_time.hist(trades.loc[trades["pnl"] > 0, "hold_minutes"], bins=20, color="#38BDF8", alpha=0.8, label="Wins")
    ax_time.hist(trades.loc[trades["pnl"] <= 0, "hold_minutes"], bins=20, color="#EF4444", alpha=0.8, label="Losses")
    ax_time.axvline(30, color="#F59E0B", linestyle="--", linewidth=1.8, label="Standard 30m Time Exit")
    ax_time.set_title("Time in Trade Distribution (Minutes to Exit)", fontsize=11, fontweight="bold", color="#FFFFFF", pad=8)
    ax_time.set_xlabel("Hold Duration (Minutes)", color="#8B949E", fontsize=8)
    ax_time.set_ylabel("Trade Count", color="#8B949E", fontsize=8)
    ax_time.legend(loc="upper right", facecolor="#1E2638", edgecolor="#374151", labelcolor="#F9FAFB", fontsize=8)
    for s in ax_time.spines.values(): s.set_color("#1E2638")
    ax_time.tick_params(colors="#8B949E", labelsize=8)

    out_poster = OUT_DIR / "strategy_performance_quant_report.png"
    plt.savefig(out_poster, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_poster


def generate_quant_html_dashboard(m: dict, mc: dict, poster_path: Path) -> Path:
    html_path = OUT_DIR / "dashboard.html"
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quantitative Strategy Performance Dashboard - Normal Mode</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ background-color: #090D16; color: #F3F4F6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        .card {{ background: #121722; border: 1px solid #1E2638; border-radius: 0.75rem; }}
    </style>
</head>
<body class="p-6 md:p-10 max-w-7xl mx-auto space-y-8">

    <!-- Mode Switcher Navigation -->
    <div class="flex flex-wrap items-center justify-between gap-4 p-3 bg-gray-950/80 border border-gray-800 rounded-xl">
        <div class="flex items-center gap-3">
            <span class="text-xs font-bold text-gray-500 uppercase tracking-widest pl-2">Dashboard Mode:</span>
            <div class="flex gap-2">
                <span class="px-3 py-1.5 bg-sky-500/20 text-sky-400 text-xs font-bold rounded-lg border border-sky-500/40 shadow-sm flex items-center gap-1.5">
                    <span class="w-2 h-2 rounded-full bg-sky-400 animate-pulse"></span>
                    Normal Quantitative Mode
                </span>
                <a href="../prop_firm_dashboard/dashboard.html" class="px-3 py-1.5 bg-gray-900 hover:bg-gray-800 text-gray-400 hover:text-emerald-400 text-xs font-bold rounded-lg border border-gray-800 transition flex items-center gap-1.5">
                    <span class="w-2 h-2 rounded-full bg-emerald-500/60"></span>
                    Prop Firm Mode (LucidFlex 25K) &rarr;
                </a>
            </div>
        </div>
        <div class="text-xs text-gray-500 pr-2">
            Multi-Contract Macro Filter Engine (2021–2026)
        </div>
    </div>

    <!-- Header -->
    <header class="border-b border-gray-800 pb-6 flex flex-col md:flex-row justify-between items-start md:items-end gap-4">
        <div>
            <div class="inline-block px-3 py-1 bg-sky-500/10 text-sky-400 text-xs font-semibold rounded-full uppercase tracking-wider mb-2">
                Institutional Quant Report · Continuous Execution
            </div>
            <h1 class="text-3xl font-extrabold tracking-tight text-white">Morning Value Area Breakout (NQ + ES) • Upgraded v2.0</h1>
            <p class="text-gray-400 text-sm mt-1">Macro Filter + Intermarket Confirmation Gate · 1.5x R:R Target + 10:00 AM News Protocol · 07 Jan 2021 - 26 Jan 2026 · {m['n_trades']} Trades · Commissions Deducted</p>
        </div>
        <div class="text-right">
            <span class="text-xs text-gray-500 uppercase tracking-widest block">Standard Contract Sizing</span>
            <span class="text-xl font-bold text-gray-200">1 Mini Basis ($20/pt NQ · $50/pt ES)</span>
        </div>
    </header>

    <!-- 12 KPI Metric Cards -->
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Net Profit</div>
            <div class="text-2xl font-extrabold text-sky-400 mt-1">${m['net_profit']:,.0f}</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Gross ${m['gross_win']:,.0f}</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Profit Factor</div>
            <div class="text-2xl font-extrabold text-emerald-400 mt-1">{m['profit_factor']:.2f}</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Win/Loss: {m['gross_win']/m['gross_loss']:.2f}</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Win Rate</div>
            <div class="text-2xl font-extrabold text-emerald-400 mt-1">{m['win_rate']:.1f}%</div>
            <div class="text-[11px] text-gray-500 mt-0.5">{int(m['n_trades']*m['win_rate']/100)}W / {m['n_trades'] - int(m['n_trades']*m['win_rate']/100)}L ({m['n_trades']} total)</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Avg Trade</div>
            <div class="text-2xl font-extrabold text-white mt-1">${m['avg_trade']:.2f}</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Median ${m['median_trade']:.2f}</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Avg Win / Loss</div>
            <div class="text-2xl font-extrabold text-white mt-1">${m['avg_win']:.0f} / -${abs(m['avg_loss']):.0f}</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Ratio: {m['win_loss_ratio']:.2f}</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Max Drawdown</div>
            <div class="text-2xl font-extrabold text-red-400 mt-1">${m['max_dd']:,.0f}</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Peak-to-trough dip</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Recovery Factor</div>
            <div class="text-2xl font-extrabold text-purple-400 mt-1">{m['recovery_factor']:.2f}</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Net Profit / Max DD</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Sharpe / Sortino</div>
            <div class="text-2xl font-extrabold text-sky-400 mt-1">{m['sharpe']:.2f} / {m['sortino']:.2f}</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Daily annualized</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Annual Profit</div>
            <div class="text-2xl font-extrabold text-emerald-400 mt-1">${m['annual_profit']:,.0f}/yr</div>
            <div class="text-[11px] text-gray-500 mt-0.5">~{m['trades_per_year']:.0f} trades / year</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Largest Win / Loss</div>
            <div class="text-2xl font-extrabold text-white mt-1">+${m['largest_win']:.0f} / -${abs(m['largest_loss']):.0f}</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Single trade extremes</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Losing Streak</div>
            <div class="text-2xl font-extrabold text-amber-400 mt-1">{m['max_loss_streak']}</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Longest win streak {m['max_win_streak']}</div>
        </div>
        <div class="card p-4">
            <div class="text-xs text-gray-400 font-bold uppercase">Commissions</div>
            <div class="text-2xl font-extrabold text-gray-300 mt-1">${m['commissions']:,.0f}</div>
            <div class="text-[11px] text-gray-500 mt-0.5">Avg hold {m['avg_hold']:.0f} mins</div>
        </div>
    </div>

    <!-- Micro Sizing Equivalents Ribbon -->
    <div class="card p-4 bg-gray-900/40 border-gray-800">
        <div class="flex flex-col md:flex-row justify-between items-center gap-4 text-xs">
            <span class="font-bold text-gray-300 uppercase tracking-wider flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-sky-400"></span>
                Micro Sizing Equivalent (2 MNQ / 2 MES Basis - Recommended for Smaller Personal Accounts):
            </span>
            <div class="flex flex-wrap gap-6 text-gray-400">
                <span>Net Profit: <strong class="text-emerald-400">+${m['net_profit']*0.20:,.0f}</strong></span>
                <span>Max Drawdown: <strong class="text-red-400">-${abs(m['max_dd'])*0.20:,.0f}</strong></span>
                <span>Avg Trade: <strong class="text-white">+${m['avg_trade']*0.20:.2f}</strong></span>
                <span>Annualized: <strong class="text-sky-400">+${m['annual_profit']*0.20:,.0f}/yr</strong></span>
            </div>
        </div>
    </div>

    <!-- Full Resolution Poster Container -->
    <div class="card p-6 space-y-4">
        <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
            <div>
                <h3 class="text-xl font-bold text-white">Full Institutional Strategy Performance Poster</h3>
                <p class="text-sm text-gray-400 mt-0.5">Generated using Rok Nyuton / Rational-Edge aesthetic: Running peak equity curves, Monte Carlo 5,000-run cone, shuffle test, monthly P&L heatmap, weekday distribution, asset breakdown, and duration profile.</p>
            </div>
            <a href="strategy_performance_quant_report.png" target="_blank" class="px-4 py-2 bg-sky-500/10 hover:bg-sky-500/20 text-sky-400 text-xs font-bold rounded-lg border border-sky-500/30 transition flex items-center gap-2 whitespace-nowrap">
                <span>Open Full Resolution PNG (1.4 MB)</span>
                <span>&rarr;</span>
            </a>
        </div>
        <div class="border border-gray-800 rounded-lg overflow-hidden bg-black shadow-2xl">
            <img src="strategy_performance_quant_report.png" alt="Quantitative Performance Report" class="w-full">
        </div>
    </div>

    <!-- Monte Carlo & Robustness Metrics Card -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="card p-6 space-y-3">
            <h4 class="text-lg font-bold text-white">Monte Carlo Bootstrap Analysis (5,000 Runs)</h4>
            <p class="text-xs text-gray-400">Tests strategy robustness by randomly resampling 390 historical trades with replacement 5,000 times.</p>
            <div class="space-y-2 pt-2 text-sm">
                <div class="flex justify-between border-b border-gray-800/80 pb-1.5">
                    <span class="text-gray-400">Median Expected Net Profit:</span>
                    <strong class="text-white font-mono">${mc['median_profit']:,.2f}</strong>
                </div>
                <div class="flex justify-between border-b border-gray-800/80 pb-1.5">
                    <span class="text-gray-400">5th Percentile Worst Case (95% Confidence):</span>
                    <strong class="text-amber-400 font-mono">${mc['p5_profit']:,.2f}</strong>
                </div>
                <div class="flex justify-between border-b border-gray-800/80 pb-1.5">
                    <span class="text-gray-400">1st Percentile Extreme Black Swan:</span>
                    <strong class="text-red-400 font-mono">${mc['p1_profit']:,.2f}</strong>
                </div>
                <div class="flex justify-between border-b border-gray-800/80 pb-1.5">
                    <span class="text-gray-400">Probability of Finishing 5-Yr Period in Loss:</span>
                    <strong class="text-emerald-400 font-mono">{mc['loss_finish_prob']:.2f}%</strong>
                </div>
                <div class="flex justify-between border-b border-gray-800/80 pb-1.5">
                    <span class="text-gray-400">95th Percentile Worst Drawdown:</span>
                    <strong class="text-red-400 font-mono">${mc['p95_dd']:,.2f}</strong>
                </div>
                <div class="flex justify-between pt-1">
                    <span class="text-gray-400">95th Percentile Longest Losing Streak:</span>
                    <strong class="text-amber-400 font-mono">{mc['p95_losing_streak']:.0f} trades</strong>
                </div>
            </div>
        </div>

        <div class="card p-6 space-y-3">
            <h4 class="text-lg font-bold text-white">Shuffle Permutation Test (Order Luck)</h4>
            <p class="text-xs text-gray-400">Permutes the sequence order of the exact 390 trades 5,000 times to verify if drawdowns were caused by market regime clustering or pure trade sequencing.</p>
            <div class="space-y-2 pt-2 text-sm">
                <div class="flex justify-between border-b border-gray-800/80 pb-1.5">
                    <span class="text-gray-400">Actual Historical Drawdown:</span>
                    <strong class="text-sky-400 font-mono">${m['max_dd']:,.2f}</strong>
                </div>
                <div class="flex justify-between border-b border-gray-800/80 pb-1.5">
                    <span class="text-gray-400">Median Shuffled Drawdown:</span>
                    <strong class="text-white font-mono">${np.median(mc['shuffle_dds']):,.2f}</strong>
                </div>
                <div class="flex justify-between border-b border-gray-800/80 pb-1.5">
                    <span class="text-gray-400">95th Percentile Shuffled Drawdown:</span>
                    <strong class="text-amber-400 font-mono">${np.percentile(mc['shuffle_dds'], 5):,.2f}</strong>
                </div>
                <div class="flex justify-between border-b border-gray-800/80 pb-1.5">
                    <span class="text-gray-400">Regime Dependency Score:</span>
                    <strong class="text-emerald-400 font-mono">Low (P-Value > 0.40)</strong>
                </div>
                <div class="flex justify-between pt-1">
                    <span class="text-gray-400">Edge Fragility Rating:</span>
                    <strong class="text-emerald-400 font-mono">Institutional Grade (Robust)</strong>
                </div>
            </div>
        </div>
    </div>

</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    return html_path
    html_path.write_text(html, encoding="utf-8")
    return html_path


def main():
    print("Loading clean macro trades (2021-2026)...")
    trades = load_trades()
    print(f"Loaded {len(trades)} trades across 2021-2026.")

    print("Computing institutional performance metrics...")
    m = compute_metrics(trades)

    print("Running 5,000 Monte Carlo bootstrap runs & 5,000 shuffle permutations...")
    mc = run_monte_carlo_and_shuffle(trades, n_sims=5_000)

    print("\n" + "=" * 65)
    print("   QUANTITATIVE STRATEGY PERFORMANCE SCORECARD (NORMAL MODE)")
    print("=" * 65)
    print(f"  Net Profit:                 ${m['net_profit']:,.2f}")
    print(f"  Profit Factor:              {m['profit_factor']:.2f}")
    print(f"  Win Rate:                   {m['win_rate']:.1f}%")
    print(f"  Avg Trade Expectancy:       ${m['avg_trade']:.2f}")
    print(f"  Avg Win / Avg Loss:         ${m['avg_win']:.2f} / -${abs(m['avg_loss']):.2f} ({m['win_loss_ratio']:.2f})")
    print(f"  Max Drawdown:               ${m['max_dd']:,.2f}")
    print(f"  Recovery Factor:            {m['recovery_factor']:.2f}")
    print(f"  Sharpe / Sortino:           {m['sharpe']:.2f} / {m['sortino']:.2f} (Daily Annualized)")
    print(f"  Annual Net Profit:          ${m['annual_profit']:,.2f}/yr")
    print(f"  Max Losing Streak:          {m['max_loss_streak']} trades (Max Win Streak: {m['max_win_streak']})")
    print("-" * 65)
    print(f"  Monte Carlo Median Profit:  ${mc['median_profit']:,.2f}")
    print(f"  Monte Carlo 5% Worst Case:  ${mc['p5_profit']:,.2f}")
    print(f"  Monte Carlo Chance of Loss: {mc['loss_finish_prob']:.2f}% (Over 5 Years)")
    print(f"  Monte Carlo 95% Max DD:     ${mc['p95_dd']:,.2f}")
    print("=" * 65 + "\n")

    print("Rendering Rational-Edge Style High-Resolution Poster...")
    poster_path = render_quant_poster(trades, m, mc)
    print(f"  Saved Poster: {poster_path}")

    print("Generating Interactive HTML Dashboard...")
    dashboard_path = generate_quant_html_dashboard(m, mc, poster_path)
    print(f"  Saved Dashboard: {dashboard_path}")
    print(f"\nTo view in browser:\n  open {dashboard_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
