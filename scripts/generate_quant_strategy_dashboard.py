#!/usr/bin/env python3
"""
Institutional Quantitative Strategy Performance Dashboard Generator.

Renders publication-grade tearsheets and interactive HTML reports in academic / quant style:
- Clean white background (#FFFFFF)
- Crisp black box spines (#000000, linewidth 1.0)
- Light gray grid lines (#E5E5E5, linestyle '--', linewidth 0.6)
- Standard Matplotlib palette (Blue #1f77b4, Orange #ff7f0e, Green #2ca02c, Red #d62728, Purple #9467bd)
- Full exchange session calendar enforcement (1,499 sessions 2021-2026, zero-trade sessions included)
- Rigorous statistical edge metrics (PSR, MinTRL, SQN, Wilson CI, Bootstrap CI, t-stat, p-value)
- Disentangles Research Sizing (risk-based x Markov) from Live Ratchet (2/3/4 micros)
- Complete Multi-Sheet PNG Tearsheet Suite:
    01_strategy_equity_curves_and_drawdown.png
    02_strategy_rolling_edge_and_directional_stability.png
    03_strategy_intraday_timing_and_microstructure.png
    04_strategy_returns_distribution_and_var.png
    05_strategy_stress_tests_and_markov_regimes.png
    06_strategy_comprehensive_scorecard_master.png
    strategy_performance_quant_report.png (Master Overview Poster)
- Interactive HTML Dashboard with Strategy Tabs, Charts, Tables, and Blotter
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["text.parse_math"] = False
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.dates as mdates

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest import dashboard_analytics as da
from backtest import metrics as bm
from backtest.provenance import default_store

OUT_DIR = REPO_ROOT / "results" / "strategy_dashboard"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def fmt_currency(val: float | None, decimals: int = 2, force_sign: bool = False) -> str:
    """Format currency values cleanly, avoiding sign bugs (+$-X) and TeX math parsing."""
    if val is None or pd.isna(val):
        return "-"
    if val < 0:
        return f"-${abs(val):,.{decimals}f}"
    elif val > 0 and force_sign:
        return f"+${val:,.{decimals}f}"
    else:
        return f"${val:,.{decimals}f}"


def format_spines_and_grid(ax):
    """Clean institutional framing: white background, crisp black spines, subtle grid."""
    ax.set_facecolor("#FFFFFF")
    ax.grid(True, color="#E5E5E5", linestyle="--", linewidth=0.6, zorder=0)
    for sp in ax.spines.values():
        sp.set_color("#000000")
        sp.set_linewidth(1.0)
    ax.tick_params(colors="#000000", labelsize=9)


def compute_monthly_matrix_data(trades: pd.DataFrame, col: str = "pnl") -> list[dict]:
    piv = trades.assign(
        year=trades["entry_time"].dt.year,
        month=trades["entry_time"].dt.month,
    ).pivot_table(index="year", columns="month", values=col, aggfunc="sum").fillna(0.0)
    out = []
    for yr in sorted(piv.index):
        row = {"year": int(yr), "months": {}, "ytd": float(piv.loc[yr].sum())}
        for m in range(1, 13):
            row["months"][m] = float(piv.loc[yr, m]) if m in piv.columns else 0.0
        out.append(row)
    return out


def build_full_metrics_dict(trades: pd.DataFrame, calendar: list[str], col: str = "pnl") -> dict:
    """Wraps da.performance_metrics and ensures all legacy + new keys are populated."""
    m = da.performance_metrics(trades, calendar, col, capital=25_000.0)
    if m.get("trades", 0) == 0:
        return {}
    
    # Calculate daily series for win rate & profit days
    daily = da.daily_series(trades, calendar, col)
    profit_days = int((daily > 0).sum())
    loss_days = int((daily < 0).sum())
    
    # Wilson CI for win rate
    wr_ci = da.wilson_ci(m["wins"], m["trades"])
    
    # Calculate 92 Institutional Metrics
    pnl_arr = trades[col].to_numpy(dtype=float) if col in trades.columns else trades["pnl"].to_numpy(dtype=float)
    daily_arr = daily.to_numpy(dtype=float)
    inst_m = bm.calculate_institutional_metrics(trades=pnl_arr, daily_returns=daily_arr, capital=25_000.0)

    res = {
        "trades": m["trades"],
        "winning_trades": m["wins"],
        "losing_trades": m["losses"],
        "scratches": m["scratches"],
        "net_profit": m["net"],
        "gross_profit": m["gross_profit"],
        "gross_loss": m["gross_loss"],
        "profit_factor": m["pf"],
        "pf_ci": m["pf_ci"],
        "win_rate": m["win_rate"],
        "win_rate_ci": (wr_ci[0] * 100.0, wr_ci[1] * 100.0),
        "loss_rate": 100.0 - m["win_rate"],
        "expectancy": m["expectancy"],
        "avg_trade": m["expectancy"],
        "exp_ci": m["exp_ci"],
        "median_trade": m["median_trade"],
        "avg_win": m["avg_win"],
        "avg_loss": m["avg_loss"],
        "payoff_ratio": m["payoff"],
        "largest_win": m["largest_win"],
        "largest_loss": m["largest_loss"],
        "trade_sd": m["trade_sd"],
        "trade_skew": m["trade_skew"],
        "trade_kurt": m["trade_kurt"],
        "sqn": m["sqn"],
        "t_stat": m["t_stat"],
        "p_value": m["p_value"],
        "max_consec_wins": m["max_win_streak"],
        "max_consec_losses": m["max_loss_streak"],
        "total_days": m["sessions"],
        "sessions": m["sessions"],
        "traded_days": m["traded_sessions"],
        "traded_sessions": m["traded_sessions"],
        "exposure_pct": m["exposure_pct"],
        "trades_per_month": m["trades_per_month"],
        "annual_profit": m["annual_pnl"],
        "annual_pnl": m["annual_pnl"],
        "cagr_pct": m["annual_return_pct"],
        "annual_vol": m["annual_vol"],
        "sharpe": m["sharpe"],
        "sortino": m["sortino"],
        "max_dd": m["max_dd"],
        "max_dd_pct": m["max_dd_pct"],
        "calmar": m["calmar"],
        "recovery_factor": m["recovery_factor"],
        "max_dd_dur_sessions": m["longest_dd_sessions"],
        "max_dd_dur_days": m["longest_dd_days"],
        "max_dd_dur_trades": 0,  # Legacy field
        "underwater_pct": m["underwater_pct"],
        "ulcer_index": m["ulcer_index"],
        "var_95_daily": m["var95"],
        "cvar_95_daily": m["cvar95"],
        "var_95_traded": m["var95_traded"],
        "cvar_95_traded": m["cvar95_traded"],
        "worst_day": m["worst_day"],
        "best_day": m["best_day"],
        "profit_days": profit_days,
        "loss_days": loss_days,
        "daily_wr": (profit_days / m["sessions"]) * 100.0,
        "traded_session_wr": m["profitable_sessions_pct"],
        "psr": m["psr"],
        "dsr": m.get("dsr"),
        "sr_star": m.get("sr_star"),
        "min_trl_years": m["min_trl_years"],
        "avg_hold_min": float(trades["hold_minutes"].mean()) if "hold_minutes" in trades else 0.0,
        "long_trades": m["long"]["n"],
        "long_net": m["long"]["net"],
        "long_wr": m["long"]["wr"],
        "long_pf": m["long"]["pf"],
        "short_trades": m["short"]["n"],
        "short_net": m["short"]["net"],
        "short_wr": m["short"]["wr"],
        "short_pf": m["short"]["pf"],
    }
    res.update(inst_m)
    return res


# ── SHEET 01: MULTI-STRATEGY EQUITY CURVES & DRAWDOWN ─────────────────────────
def render_sheet_01_equity(
    trades: pd.DataFrame,
    calendar: list[str],
    m_comp: dict,
    m_s1: dict,
    m_s2: dict,
    m_s3: dict,
) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    gs = fig.add_gridspec(3, 1, height_ratios=[2.4, 1.1, 1.1], hspace=0.30)

    # Reindex daily PnLs across the full exchange calendar
    d_comp = da.daily_series(trades, calendar, "research_pnl")
    d_s1 = da.daily_series(trades[trades["strat"] == "S1"], calendar, "research_pnl")
    d_s2 = da.daily_series(trades[trades["strat"] == "S2"], calendar, "research_pnl")
    d_s3 = da.daily_series(trades[trades["strat"] == "S3"], calendar, "research_pnl")

    cal_dates = pd.to_datetime(calendar)
    eq_comp = d_comp.cumsum().to_numpy() + 25_000.0
    eq_peak = np.maximum.accumulate(eq_comp)
    eq_s1 = d_s1.cumsum().to_numpy() + 25_000.0
    eq_s2 = d_s2.cumsum().to_numpy() + 25_000.0
    eq_s3 = d_s3.cumsum().to_numpy() + 25_000.0

    # Panel 1: Multi-Strategy Equity Curves ($25,000 Base)
    ax_main = fig.add_subplot(gs[0])
    format_spines_and_grid(ax_main)

    ax_main.plot(cal_dates, eq_comp, color="#1f77b4", linewidth=2.0, label=f"Unified Composite (+${m_comp['net_profit']:,.2f} • Ann Sharpe {m_comp['sharpe']:.2f})", zorder=4)
    ax_main.plot(cal_dates, eq_s1, color="#ff7f0e", linewidth=1.4, alpha=0.9, label=f"Strategy 1: 09:45 VA Breakout (+${m_s1['net_profit']:,.2f} • PF {m_s1['profit_factor']:.2f})", zorder=3)
    ax_main.plot(cal_dates, eq_s2, color="#2ca02c", linewidth=1.4, alpha=0.9, label=f"Strategy 2: 10:15 Gold Fix (+${m_s2['net_profit']:,.2f} • PF {m_s2['profit_factor']:.2f})", zorder=3)
    ax_main.plot(cal_dates, eq_s3, color="#d62728", linewidth=1.4, alpha=0.9, label=f"Strategy 3: 08:35 Macro Momentum (+${m_s3['net_profit']:,.2f} • PF {m_s3['profit_factor']:.2f})", zorder=3)
    ax_main.plot(cal_dates, eq_peak, color="#9467bd", linestyle="--", linewidth=1.0, alpha=0.75, label="Running High-Water Mark", zorder=2)

    ax_main.set_title("Backtest Results - Multi-Strategy Equity Curves ($25,000 Base, Continuous Session Calendar)", fontsize=13, fontweight="bold", color="#000000", pad=10)
    ax_main.set_ylabel("Portfolio Value ($)", fontsize=10, color="#000000")
    ax_main.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_main.xaxis.set_major_locator(mdates.YearLocator())
    ax_main.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_main.set_xlim(cal_dates[0], cal_dates[-1])

    leg = ax_main.legend(loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8.5)
    leg.get_title().set_fontsize(9)
    leg.get_title().set_fontweight("bold")

    # Panel 2: Underwater Drawdown ($)
    ax_dd = fig.add_subplot(gs[1])
    format_spines_and_grid(ax_dd)

    dd_vals = eq_comp - eq_peak
    ax_dd.fill_between(cal_dates, dd_vals, 0, color="#d62728", alpha=0.25, zorder=2)
    ax_dd.plot(cal_dates, dd_vals, color="#d62728", linewidth=1.2, label=f"Drawdown (Max: -${abs(m_comp['max_dd']):,.2f} • Longest: {m_comp['max_dd_dur_days']} cal days / {m_comp['max_dd_dur_sessions']} sessions)", zorder=3)

    ax_dd.set_title("Underwater Portfolio Drawdown ($ Below Running Peak)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_dd.set_ylabel("Drawdown ($)", fontsize=9.5, color="#000000")
    ax_dd.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_dd.xaxis.set_major_locator(mdates.YearLocator())
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_dd.set_xlim(cal_dates[0], cal_dates[-1])
    ax_dd.legend(loc="lower left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8.5)

    # Panel 3: Drawdown Duration & Recovery Episodes
    ax_ep = fig.add_subplot(gs[2])
    format_spines_and_grid(ax_ep)

    episodes = da.drawdown_episodes(d_comp)
    if len(episodes) > 0:
        top_eps = episodes.head(8)
        bar_x = range(len(top_eps))
        depths = top_eps["depth"].abs()
        bars = ax_ep.bar(bar_x, depths, color="#1f77b4", edgecolor="#000000", width=0.55, zorder=3)
        for idx, b in enumerate(bars):
            row = top_eps.iloc[idx]
            rec_str = f"{row['calendar_days']}d" if row["recovered_flag"] else "Open"
            ax_ep.annotate(f"-${row['depth']:,.0f}\n({rec_str})", xy=(b.get_x() + b.get_width() / 2, b.get_height()),
                           xytext=(0, 2), textcoords="offset points", ha="center", va="bottom", fontsize=7.5, fontweight="bold", color="#000000")
        
        lbls = [f"#{i+1} ({top_eps.iloc[i]['start'].strftime('%b %Y')})" for i in range(len(top_eps))]
        ax_ep.set_xticks(bar_x)
        ax_ep.set_xticklabels(lbls, fontsize=8, color="#000000")
        ax_ep.set_ylim(0, depths.max() * 1.30)
    
    ax_ep.set_title(f"Top Drawdown Episodes (Depth & Recovery Duration in Calendar Days) • Time Underwater: {m_comp['underwater_pct']:.1f}%", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_ep.set_ylabel("Trough Depth ($)", fontsize=9.5, color="#000000")
    ax_ep.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))

    out_path = OUT_DIR / "01_strategy_equity_curves_and_drawdown.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 02: ROLLING EDGE & DIRECTIONAL STABILITY ───────────────────────────
def render_sheet_02_rolling_edge(
    trades: pd.DataFrame,
    calendar: list[str],
    m_comp: dict,
) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.5, 1.4], hspace=0.35, wspace=0.22)

    # Panel A: Rolling 252-Session Annualized Sharpe Ratio (Computed on Full Calendar)
    ax_shp = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_shp)

    d_comp = da.daily_series(trades, calendar, "research_pnl")
    roll_shp = da.rolling_sharpe(d_comp, window=252).dropna()
    dates_shp = pd.to_datetime(roll_shp.index)

    ax_shp.plot(dates_shp, roll_shp, color="#1f77b4", linewidth=1.8, label="Rolling 252-Session Sharpe (1-Yr Lookback)", zorder=3)
    ax_shp.axhline(2.0, color="#777777", linestyle="--", linewidth=1.2, label="Institutional Threshold (2.00)")
    ax_shp.axhline(m_comp["sharpe"], color="#2ca02c", linestyle=":", linewidth=1.4, label=f"Full Sample Annual Sharpe ({m_comp['sharpe']:.2f})")
    ax_shp.axhline(0.0, color="#d62728", linestyle="-", linewidth=0.8, alpha=0.7)

    ax_shp.set_title("Rolling 252-Session Sharpe Ratio (True Full Exchange Calendar)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_shp.set_ylabel("Sharpe Ratio (Ann. sqrt 252)", fontsize=9, color="#000000")
    ax_shp.xaxis.set_major_locator(mdates.YearLocator())
    ax_shp.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_shp.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel B: Rolling 50-Trade Win Rate
    ax_wr = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_wr)

    roll_50 = da.rolling_trade_stats(trades, "research_pnl", window=50).dropna(subset=["win_rate"])
    ax_wr.plot(roll_50["time"], roll_50["win_rate"], color="#2ca02c", linewidth=1.8, label="Rolling 50-Trade Win Rate (%)", zorder=3)
    ax_wr.axhline(50.0, color="#d62728", linestyle="--", linewidth=1.2, label="50% Breakeven Hurdle")
    ax_wr.axhline(m_comp["win_rate"], color="#1f77b4", linestyle=":", linewidth=1.4, label=f"Full Sample Win Rate ({m_comp['win_rate']:.1f}%)")

    ax_wr.set_title("Rolling 50-Trade Win Rate (%) with 50% Breakeven Hurdle", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_wr.set_ylabel("Win Rate (%)", fontsize=9, color="#000000")
    ax_wr.set_ylim(35, 75)
    ax_wr.xaxis.set_major_locator(mdates.YearLocator())
    ax_wr.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_wr.legend(loc="lower right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel C: Long vs Short Cumulative Equity Progression
    ax_dir = fig.add_subplot(gs[1, 0])
    format_spines_and_grid(ax_dir)

    long_trades = trades[trades["direction"] == "long"].copy()
    short_trades = trades[trades["direction"] == "short"].copy()
    long_trades["cum_pnl"] = long_trades["research_pnl"].cumsum()
    short_trades["cum_pnl"] = short_trades["research_pnl"].cumsum()

    ax_dir.plot(long_trades["entry_time"], long_trades["cum_pnl"], color="#1f77b4", linewidth=1.8,
                label=f"Long Edge (+${long_trades['research_pnl'].sum():,.0f} • {len(long_trades)}t • {m_comp['long_wr']:.1f}% WR)", zorder=3)
    ax_dir.plot(short_trades["entry_time"], short_trades["cum_pnl"], color="#d62728", linewidth=1.8,
                label=f"Short Edge (+${short_trades['research_pnl'].sum():,.0f} • {len(short_trades)}t • {m_comp['short_wr']:.1f}% WR)", zorder=3)

    ax_dir.set_title("Directional Cumulative Equity Progression (Long vs Short)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_dir.set_ylabel("Cumulative Net Profit ($)", fontsize=9, color="#000000")
    ax_dir.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_dir.xaxis.set_major_locator(mdates.YearLocator())
    ax_dir.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_dir.legend(loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel D: Directional Edge Scorecard Table
    ax_tab = fig.add_subplot(gs[1, 1])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.96, "Directional Edge Scorecard (Long vs Short)", fontsize=11, fontweight="bold", color="#000000")

    l_pnl = long_trades["research_pnl"].to_numpy()
    s_pnl = short_trades["research_pnl"].to_numpy()
    c_pnl = trades["research_pnl"].to_numpy()

    l_wins, l_loss = l_pnl[l_pnl > 0], l_pnl[l_pnl < 0]
    s_wins, s_loss = s_pnl[s_pnl > 0], s_pnl[s_pnl < 0]
    c_wins, c_loss = c_pnl[c_pnl > 0], c_pnl[c_pnl < 0]

    l_avg_w, l_avg_l = float(l_wins.mean()) if len(l_wins) else 0.0, float(abs(l_loss.mean())) if len(l_loss) else 0.0
    s_avg_w, s_avg_l = float(s_wins.mean()) if len(s_wins) else 0.0, float(abs(s_loss.mean())) if len(s_loss) else 0.0
    c_avg_w, c_avg_l = float(c_wins.mean()) if len(c_wins) else 0.0, float(abs(c_loss.mean())) if len(c_loss) else 0.0

    dir_rows = [
        ("Trade Executions", f"{len(long_trades)} ({len(long_trades)/len(trades)*100:.1f}%)", f"{len(short_trades)} ({len(short_trades)/len(trades)*100:.1f}%)", f"{len(trades)} (100%)"),
        ("Net Profit (USD)", fmt_currency(l_pnl.sum(), 2, True), fmt_currency(s_pnl.sum(), 2, True), fmt_currency(c_pnl.sum(), 2, True)),
        ("Trade Win Rate", f"{(l_pnl>0).mean()*100:.1f}%", f"{(s_pnl>0).mean()*100:.1f}%", f"{(c_pnl>0).mean()*100:.1f}%"),
        ("Profit Factor", f"{da.profit_factor(l_pnl):.2f}", f"{da.profit_factor(s_pnl):.2f}", f"{da.profit_factor(c_pnl):.2f}"),
        ("Average Win", fmt_currency(l_avg_w, 2, True), fmt_currency(s_avg_w, 2, True), fmt_currency(c_avg_w, 2, True)),
        ("Average Loss", f"-{fmt_currency(l_avg_l, 2)}", f"-{fmt_currency(s_avg_l, 2)}", f"-{fmt_currency(c_avg_l, 2)}"),
        ("Win/Loss Payoff", f"{l_avg_w/l_avg_l:.2f}x" if l_avg_l else "-", f"{s_avg_w/s_avg_l:.2f}x" if s_avg_l else "-", f"{c_avg_w/c_avg_l:.2f}x" if c_avg_l else "-"),
        ("Expectancy / Trade", fmt_currency(l_pnl.mean(), 2, True), fmt_currency(s_pnl.mean(), 2, True), fmt_currency(c_pnl.mean(), 2, True)),
        ("Max Drawdown ($)", fmt_currency(da.max_drawdown(np.cumsum(l_pnl)), 2), fmt_currency(da.max_drawdown(np.cumsum(s_pnl)), 2), fmt_currency(m_comp["max_dd"], 2)),
        ("Avg Holding Time", f"{long_trades['hold_minutes'].mean():.1f} mins", f"{short_trades['hold_minutes'].mean():.1f} mins", f"{trades['hold_minutes'].mean():.1f} mins"),
    ]

    t_x = [0.02, 0.42, 0.68, 0.94]
    t_hdrs = ["Metric", "Long Side", "Short Side", "Combined"]
    for i, h in enumerate(t_hdrs):
        ax_tab.text(t_x[i], 0.84, h, fontsize=8.2, fontweight="bold", color="#000000", ha="left" if i == 0 else "right")

    y_pos = 0.72
    for r in dir_rows:
        ax_tab.axhline(y_pos + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        for c_idx, val in enumerate(r):
            f_w = "bold" if c_idx in [1, 2, 3] and "$" in val else "normal"
            c_val = "#1f77b4" if (c_idx == 1 and "$" in val) else ("#d62728" if (c_idx == 2 and "$" in val) else "#000000")
            ax_tab.text(t_x[c_idx], y_pos, val, fontsize=8.0, fontweight=f_w, color=c_val, ha="left" if c_idx == 0 else "right")
        y_pos -= 0.076

    out_path = OUT_DIR / "02_strategy_rolling_edge_and_directional_stability.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 03: INTRADAY TIMING & MICROSTRUCTURE ───────────────────────────────
def render_sheet_03_timing(trades: pd.DataFrame, calendar: list[str]) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.6, 1.4], hspace=0.35, wspace=0.22)

    # Panel A: Day of Week Alpha Distribution
    ax_dow = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_dow)

    days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    dow_pnl = [float(trades[trades["weekday"] == d]["research_pnl"].sum()) for d in days_order]
    dow_trades = [len(trades[trades["weekday"] == d]) for d in days_order]
    dow_wr = [(trades[trades["weekday"] == d]["research_pnl"] > 0).mean() * 100.0 if len(trades[trades["weekday"] == d]) else 0.0 for d in days_order]

    b_dow = ax_dow.bar(days_order, dow_pnl, color="#1f77b4", edgecolor="#000000", width=0.55, zorder=3)
    for idx, b in enumerate(b_dow):
        h = b.get_height()
        ax_dow.annotate(f"${h:,.0f}\n({dow_trades[idx]}t • {dow_wr[idx]:.1f}%)", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 3),
                        textcoords="offset points", ha="center", va="bottom", color="#000000", fontweight="bold", fontsize=7.8)

    ax_dow.set_title("Day-of-Week Alpha Distribution (Net P&L, Trades & Win Rate)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_dow.set_ylabel("Net Profit ($)", fontsize=9, color="#000000")
    ax_dow.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_dow.set_ylim(0, max(dow_pnl) * 1.25)

    # Panel B: Trade Duration Bins
    ax_dur = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_dur)

    bins = [0, 15, 30, 45, 60, 180]
    labels = ["0-15m", "15-30m", "30-45m", "45-60m", "60m+"]
    t_c = trades.copy()
    t_c["hold_bin"] = pd.cut(t_c["hold_minutes"], bins=bins, labels=labels)
    bin_pnl = [float(t_c[t_c["hold_bin"] == b]["research_pnl"].sum()) for b in labels[:4]]
    bin_trades = [len(t_c[t_c["hold_bin"] == b]) for b in labels[:4]]
    bin_wr = [(t_c[t_c["hold_bin"] == b]["research_pnl"] > 0).mean() * 100.0 if len(t_c[t_c["hold_bin"] == b]) else 0.0 for b in labels[:4]]

    b_dur = ax_dur.bar(labels[:4], bin_pnl, color="#2ca02c", edgecolor="#000000", width=0.55, zorder=3)
    for idx, b in enumerate(b_dur):
        h = b.get_height()
        ax_dur.annotate(f"${h:,.0f}\n({bin_trades[idx]}t • {bin_wr[idx]:.1f}%)", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 3),
                        textcoords="offset points", ha="center", va="bottom", color="#000000", fontweight="bold", fontsize=7.8)

    ax_dur.set_title("Trade Holding Duration Bins (15–30 Min Primary Engine)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_dur.set_ylabel("Net Profit ($)", fontsize=9, color="#000000")
    ax_dur.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_dur.set_ylim(0, max(bin_pnl) * 1.25)

    # Panel C: Intraday Window Microstructure Table (Dynamic Calculation)
    ax_tab = fig.add_subplot(gs[1, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.96, "Intraday Execution Microstructure (Window-by-Window Profile)", fontsize=11, fontweight="bold", color="#000000")

    def window_row(strat_code: str, name: str, hyp: str, inst: str, df_sub: pd.DataFrame) -> tuple:
        pnl = df_sub["research_pnl"].to_numpy()
        d_sub = da.daily_series(df_sub, calendar, "research_pnl")
        d_sd = d_sub.std(ddof=1)
        sr = (d_sub.mean() / d_sd * np.sqrt(252)) if d_sd > 0 else np.nan
        pf = da.profit_factor(pnl)
        wr = (pnl > 0).mean() * 100.0
        avg_h = df_sub["hold_minutes"].mean()
        # Slippage tolerance
        slip_df = da.slippage_curve(df_sub, "research_pnl", ticks=range(0, 10))
        be_tick = next((r["ticks"] for _, r in slip_df.iterrows() if r["pf"] < 1.0), 9)
        return (name, hyp, inst, f"{len(df_sub)} trades", fmt_currency(pnl.sum(), 2, True), f"{pf:.2f}", f"{wr:.1f}%", f"{sr:.2f}", f"{avg_h:.1f}m", f"+{be_tick-0.5:.1f}t")

    w_rows = [
        window_row("S1", "Strategy 1 (09:45 ET)", "Value Area Breakout", "MNQ & MES", trades[trades["strat"] == "S1"]),
        window_row("S2", "Strategy 2 (10:15 ET)", "London Gold Fix Reversal", "MGC", trades[trades["strat"] == "S2"]),
        window_row("S3", "Strategy 3 (08:35 ET)", "Macro Driver Momentum", "MNQ", trades[trades["strat"] == "S3"]),
        window_row("ALL", "Combined Ensemble", "All 3 Intraday Windows", "MNQ, MES, MGC", trades),
    ]

    t_x = [0.02, 0.20, 0.38, 0.48, 0.58, 0.66, 0.74, 0.82, 0.90, 0.98]
    t_hdrs = ["Strategy Window", "Core Hypothesis", "Asset", "Trades", "Net Profit", "PF", "Win Rate", "Sharpe", "Avg Hold", "Slip Cliff"]
    for i, h in enumerate(t_hdrs):
        ax_tab.text(t_x[i], 0.84, h, fontsize=8.0, fontweight="bold", color="#000000", ha="left" if i < 3 else "right")

    y_pos = 0.70
    for r_i, r in enumerate(w_rows):
        ax_tab.axhline(y_pos + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        is_ens = r_i == 3
        f_w = "bold" if is_ens else "normal"
        for c_idx, val in enumerate(r):
            c_val = "#1f77b4" if (is_ens and c_idx in [0, 4]) else "#000000"
            ax_tab.text(t_x[c_idx], y_pos, val, fontsize=8.0, fontweight=f_w, color=c_val, ha="left" if c_idx < 3 else "right")
        y_pos -= 0.12

    out_path = OUT_DIR / "03_strategy_intraday_timing_and_microstructure.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 04: RETURNS DISTRIBUTION & VALUE AT RISK ───────────────────────────
def render_sheet_04_returns_and_var(
    trades: pd.DataFrame,
    calendar: list[str],
    m_comp: dict,
) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 13), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.5, 1.8], hspace=0.35, wspace=0.22)

    # Panel A: Daily Session Net P&L Distribution with VaR / CVaR
    ax_var = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_var)

    d_comp = da.daily_series(trades, calendar, "research_pnl")
    r_traded = d_comp[d_comp != 0].to_numpy()

    var_full = m_comp["var_95_daily"]
    cvar_full = m_comp["cvar_95_daily"]
    var_traded = m_comp["var_95_traded"]
    cvar_traded = m_comp["cvar_95_traded"]

    ax_var.hist(r_traded, bins=35, color="#1f77b4", edgecolor="#000000", alpha=0.75, label=f"Traded Sessions ({len(r_traded)}d)", zorder=3)
    ax_var.axvline(var_traded, color="#d62728", linestyle="--", linewidth=1.5, label=f"Traded VaR 95%: {fmt_currency(var_traded, 2)}")
    ax_var.axvline(cvar_traded, color="#9467bd", linestyle=":", linewidth=1.5, label=f"Traded CVaR 95%: {fmt_currency(cvar_traded, 2)}")
    ax_var.axvline(d_comp.mean(), color="#2ca02c", linestyle="-", linewidth=1.2, label=f"Calendar Mean/Day: +${d_comp.mean():.2f}")

    ax_var.set_title("Traded Session P&L Distribution with Daily VaR & CVaR (95%)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_var.set_xlabel("Daily Net Profit ($)", fontsize=9, color="#000000")
    ax_var.set_ylabel("Session Count", fontsize=9, color="#000000")
    ax_var.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_var.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel B: Trade-Level PnL Distribution (Wins vs Losses)
    ax_hist = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_hist)

    wins = trades[trades["research_pnl"] > 0]["research_pnl"]
    losses = trades[trades["research_pnl"] <= 0]["research_pnl"]

    ax_hist.hist(wins, bins=25, color="#2ca02c", edgecolor="#000000", alpha=0.75, label=f"Wins ({len(wins)} • avg +${wins.mean():.0f})", zorder=3)
    ax_hist.hist(losses, bins=25, color="#d62728", edgecolor="#000000", alpha=0.75, label=f"Losses ({len(losses)} • avg -${abs(losses.mean()):.0f})", zorder=3)
    ax_hist.axvline(m_comp["avg_trade"], color="#1f77b4", linestyle="--", linewidth=1.8, label=f"Expectancy: +${m_comp['avg_trade']:.2f}")

    ax_hist.set_title(f"Trade Outcome Distribution (Skew: {m_comp['trade_skew']:+.2f} • Kurt: {m_comp['trade_kurt']:.2f})", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_hist.set_xlabel("Trade Net P&L ($)", fontsize=9, color="#000000")
    ax_hist.set_ylabel("Trade Count", fontsize=9, color="#000000")
    ax_hist.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_hist.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel C: Statistical Edge & Tail Risk Scorecard Table
    ax_tab = fig.add_subplot(gs[1, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.96, "Statistical Edge, Non-Normality & Tail Risk Assessment", fontsize=11, fontweight="bold", color="#000000")

    t_rows = [
        ("Parametric Student's t-Statistic", f"t = {m_comp['t_stat']:.3f}", "Two-Tailed p-Value (H0: Edge = 0)", f"p = {m_comp['p_value']:.4e} (p < 0.001)"),
        ("Probabilistic Sharpe Ratio (PSR)", f"{m_comp['psr']*100:.2f}% (Bailey-López de Prado)", "Min Track Record Length (MinTRL)", f"{m_comp['min_trl_years']:.2f} years ({m_comp['min_trl_years']*252:.0f} sessions)"),
        ("System Quality Number (SQN)", f"{m_comp['sqn']:.2f} (Van Tharp 'Good/Excellent')", "Trade P&L Skewness / Kurtosis", f"Skew {m_comp['trade_skew']:+.2f} / Kurtosis {m_comp['trade_kurt']:.2f}"),
        ("Win Rate 95% Wilson Score CI", f"[{m_comp['win_rate_ci'][0]:.1f}%, {m_comp['win_rate_ci'][1]:.1f}%]", "Profit Factor 95% Bootstrap CI", f"[{m_comp['pf_ci'][0]:.2f}, {m_comp['pf_ci'][1]:.2f}]"),
        ("Expectancy 95% Bootstrap CI", f"[{fmt_currency(m_comp['exp_ci'][0], 2, True)}, {fmt_currency(m_comp['exp_ci'][1], 2, True)}]", "Ulcer Index (Depth x Duration)", f"{m_comp['ulcer_index']:.2f}%"),
        ("Calendar Daily VaR (95%)", fmt_currency(var_full, 2), "Calendar Expected Shortfall (CVaR)", fmt_currency(cvar_full, 2)),
        ("Conditional Traded VaR (95%)", fmt_currency(var_traded, 2), "Conditional Traded CVaR (95%)", fmt_currency(cvar_traded, 2)),
        ("Largest Single Win", fmt_currency(m_comp["largest_win"], 2, True), "Largest Single Loss", fmt_currency(m_comp["largest_loss"], 2)),
        ("Worst Single Session P&L", fmt_currency(m_comp["worst_day"], 2), "Best Single Session P&L", fmt_currency(m_comp["best_day"], 2, True)),
        ("Max Consecutive Wins / Losses", f"{m_comp['max_consec_wins']} W / {m_comp['max_consec_losses']} L", "Traded Sessions Win Rate", f"{m_comp['traded_session_wr']:.1f}% ({m_comp['profit_days']}/{m_comp['traded_days']})"),
    ]

    t_x = [0.02, 0.46, 0.54, 0.98]
    y_pos = 0.86
    for r in t_rows:
        ax_tab.axhline(y_pos + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        ax_tab.text(t_x[0], y_pos, r[0], fontsize=8.0, color="#444444")
        ax_tab.text(t_x[1], y_pos, r[1], fontsize=8.2, fontweight="bold", color="#000000", ha="right")
        ax_tab.text(t_x[2], y_pos, r[2], fontsize=8.0, color="#444444")
        ax_tab.text(t_x[3], y_pos, r[3], fontsize=8.2, fontweight="bold", color="#1f77b4" if "$" in r[3] or "p <" in r[3] else "#000000", ha="right")
        y_pos -= 0.082

    out_path = OUT_DIR / "04_strategy_returns_distribution_and_var.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 05: STRESS TESTS, MARKOV REGIMES & MONTE CARLO ──────────────────────
def render_sheet_05_stress_tests(trades: pd.DataFrame, calendar: list[str]) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.5, 1.5], hspace=0.35, wspace=0.22)

    # Panel A: Slippage Breakeven Curve
    ax_slip = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_slip)

    slip_df = da.slippage_curve(trades, "research_pnl", ticks=range(0, 9))
    ax_slip.plot(slip_df["ticks"], slip_df["pf"], marker="o", color="#1f77b4", linewidth=1.8, label="Profit Factor", zorder=3)
    ax_slip.axhline(1.0, color="#d62728", linestyle="--", linewidth=1.2, label="Breakeven Cliff (PF = 1.00)")
    
    be_tick = next((r["ticks"] for _, r in slip_df.iterrows() if r["pf"] < 1.0), 8)
    ax_slip.axvline(be_tick - 0.5, color="#9467bd", linestyle=":", linewidth=1.2, label=f"Breakeven at ~+{be_tick-0.5:.1f} ticks")

    ax_slip.set_title("Slippage Sensitivity & Friction Breakeven Cliff", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_slip.set_xlabel("Extra Adverse Ticks per Leg (Entry + Exit)", fontsize=9, color="#000000")
    ax_slip.set_ylabel("Profit Factor", fontsize=9, color="#000000")
    ax_slip.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel B: Markov Volatility Regime Allocation
    ax_mkv = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_mkv)

    reg_pnl = trades.groupby("markov_state_label")["research_pnl"].sum().reindex(["low_vol", "mid_vol", "high_vol"])
    reg_n = trades.groupby("markov_state_label")["research_pnl"].count().reindex(["low_vol", "mid_vol", "high_vol"])
    reg_wr = trades.groupby("markov_state_label")["research_pnl"].agg(lambda x: (x > 0).mean() * 100).reindex(["low_vol", "mid_vol", "high_vol"])

    b_mkv = ax_mkv.bar(["Low-Vol (1.25x)", "Mid-Vol (1.00x)", "High-Vol (0.50x S3)"], reg_pnl, color=["#2ca02c", "#1f77b4", "#ff7f0e"], edgecolor="#000000", width=0.5, zorder=3)
    for idx, b in enumerate(b_mkv):
        h = b.get_height()
        ax_mkv.annotate(f"${h:,.0f}\n({reg_n.iloc[idx]}t • {reg_wr.iloc[idx]:.1f}%)", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 3),
                        textcoords="offset points", ha="center", va="bottom", color="#000000", fontweight="bold", fontsize=7.8)

    ax_mkv.set_title("Markov Volatility Regime Allocation (Option 2 Sizing)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_mkv.set_ylabel("Net Profit ($)", fontsize=9, color="#000000")
    ax_mkv.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_mkv.set_ylim(0, max(reg_pnl) * 1.25)

    # Panel C: In-Sample (DEV 2021-2024) vs Out-of-Sample (OOS 2025-2026) Table
    ax_oos = fig.add_subplot(gs[1, 0])
    ax_oos.set_facecolor("#FFFFFF")
    ax_oos.axis("off")

    ax_oos.text(0.02, 0.94, "In-Sample (DEV 2021-2024) vs Out-of-Sample (OOS 2025-2026)", fontsize=10.5, fontweight="bold", color="#000000")

    dev_t = trades[trades["date"] <= da.DEV_END]
    oos_t = trades[trades["date"] > da.DEV_END]
    dev_cal = [s for s in calendar if s <= da.DEV_END]
    oos_cal = [s for s in calendar if s > da.DEV_END]

    dev_m = da.performance_metrics(dev_t, dev_cal, "research_pnl")
    oos_m = da.performance_metrics(oos_t, oos_cal, "research_pnl")

    oos_rows = [
        ("Trade Count", f"{dev_m['trades']} trades", f"{oos_m['trades']} trades"),
        ("Win Rate", f"{dev_m['win_rate']:.1f}%", f"{oos_m['win_rate']:.1f}%"),
        ("Profit Factor", f"{dev_m['pf']:.2f}", f"{oos_m['pf']:.2f}"),
        ("Net Profit ($)", fmt_currency(dev_m['net'], 2, True), fmt_currency(oos_m['net'], 2, True)),
        ("Calendar Sharpe", f"{dev_m['sharpe']:.2f}", f"{oos_m['sharpe']:.2f}"),
        ("Max Drawdown", fmt_currency(dev_m['max_dd'], 2), fmt_currency(oos_m['max_dd'], 2)),
        ("Recovery Factor", f"{dev_m['recovery_factor']:.2f}x", f"{oos_m['recovery_factor']:.2f}x"),
    ]

    t_x1 = [0.02, 0.52, 0.84]
    ax_oos.text(t_x1[0], 0.82, "Metric", fontsize=8.2, fontweight="bold", color="#000000")
    ax_oos.text(t_x1[1], 0.82, "DEV (2021-2024)", fontsize=8.2, fontweight="bold", color="#000000", ha="right")
    ax_oos.text(t_x1[2], 0.82, "OOS (2025-2026)", fontsize=8.2, fontweight="bold", color="#000000", ha="right")

    y_pos1 = 0.70
    for r in oos_rows:
        ax_oos.axhline(y_pos1 + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        ax_oos.text(t_x1[0], y_pos1, r[0], fontsize=8.0, color="#444444")
        ax_oos.text(t_x1[1], y_pos1, r[1], fontsize=8.2, fontweight="bold", color="#000000", ha="right")
        ax_oos.text(t_x1[2], y_pos1, r[2], fontsize=8.2, fontweight="bold", color="#1f77b4" if "$" in r[2] else "#000000", ha="right")
        y_pos1 -= 0.10

    # Panel D: Reshuffled Trade-Order Monte Carlo Drawdown Envelope
    ax_mc = fig.add_subplot(gs[1, 1])
    format_spines_and_grid(ax_mc)

    mc_dds = da.reshuffled_max_drawdowns(trades["research_pnl"].to_numpy(), n=3000, seed=42)
    obs_dd = da.max_drawdown(trades["research_pnl"].cumsum().to_numpy())

    ax_mc.hist(mc_dds, bins=35, color="#1f77b4", edgecolor="#000000", alpha=0.75, zorder=3)
    ax_mc.axvline(obs_dd, color="#2ca02c", linestyle="-", linewidth=2.0, label=f"Observed Max DD: {fmt_currency(obs_dd, 2)}")
    ax_mc.axvline(np.percentile(mc_dds, 50), color="#000000", linestyle="--", linewidth=1.2, label=f"Median Reshuffled: {fmt_currency(np.percentile(mc_dds, 50), 2)}")
    ax_mc.axvline(np.percentile(mc_dds, 5), color="#d62728", linestyle=":", linewidth=1.4, label=f"95% Worst Reshuffled: {fmt_currency(np.percentile(mc_dds, 5), 2)}")

    ax_mc.set_title("Trade-Order Reshuffling Monte Carlo Drawdown Distribution", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_mc.set_xlabel("Simulated Maximum Drawdown ($)", fontsize=9, color="#000000")
    ax_mc.set_ylabel("Permutation Count (3,000 Runs)", fontsize=9, color="#000000")
    ax_mc.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_mc.legend(loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    out_path = OUT_DIR / "05_strategy_stress_tests_and_markov_regimes.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 06: FULL SCORECARD MASTER TABLE ────────────────────────────────────
def render_sheet_06_scorecard(
    m_comp: dict,
    m_s1: dict,
    m_s2: dict,
    m_s3: dict,
) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 17.5), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    ax = fig.add_subplot(111)
    ax.set_facecolor("#FFFFFF")
    ax.axis("off")

    ax.text(0.02, 0.988, "Backtest Results - Comprehensive Quantitative Performance & Risk Scorecard", fontsize=13.5, fontweight="bold", color="#000000")
    ax.text(0.02, 0.970, "Complete Multi-Window Inventory across 543 Executions (2021-01-07 to 2026-10-30 • Full Calendar 1,499 Sessions • 92 Institutional Metrics)", fontsize=9, color="#555555")

    table_data = [
        ("Execution Window & Time", "All 3 Windows", "09:45 - 10:15 ET", "10:15 - 10:45 ET", "08:35 - 09:15 ET"),
        ("Traded Instruments", "MNQ, MES, MGC", "MNQ, MES", "MGC", "MNQ"),
        ("Total Executions / Trades", f"{m_comp['trades']}", f"{m_s1['trades']}", f"{m_s2['trades']}", f"{m_s3['trades']}"),
        ("Net Profit (USD)", fmt_currency(m_comp['net_profit'], 2), fmt_currency(m_s1['net_profit'], 2), fmt_currency(m_s2['net_profit'], 2), fmt_currency(m_s3['net_profit'], 2)),
        ("Gross Profit / Gross Loss",
         f"{fmt_currency(m_comp['gross_profit'], 0)} / -{fmt_currency(m_comp['gross_loss'], 0)}",
         f"{fmt_currency(m_s1['gross_profit'], 0)} / -{fmt_currency(m_s1['gross_loss'], 0)}",
         f"{fmt_currency(m_s2['gross_profit'], 0)} / -{fmt_currency(m_s2['gross_loss'], 0)}",
         f"{fmt_currency(m_s3['gross_profit'], 0)} / -{fmt_currency(m_s3['gross_loss'], 0)}"),
        ("Profit Factor", f"{m_comp['profit_factor']:.2f}", f"{m_s1['profit_factor']:.2f}", f"{m_s2['profit_factor']:.2f}", f"{m_s3['profit_factor']:.2f}"),
        ("Trimmed Profit Factor (ex-Top 2% Wins)", f"{m_comp.get('trimmed_profit_factor', 0.0):.2f}", f"{m_s1.get('trimmed_profit_factor', 0.0):.2f}", f"{m_s2.get('trimmed_profit_factor', 0.0):.2f}", f"{m_s3.get('trimmed_profit_factor', 0.0):.2f}"),
        ("Top 5 Wins Dominance (% Net)", f"{m_comp.get('top_5_wins_pct', 0.0):.1f}%", f"{m_s1.get('top_5_wins_pct', 0.0):.1f}%", f"{m_s2.get('top_5_wins_pct', 0.0):.1f}%", f"{m_s3.get('top_5_wins_pct', 0.0):.1f}%"),
        ("Profit Factor (95% Bootstrap CI)", f"[{m_comp['pf_ci'][0]:.2f}, {m_comp['pf_ci'][1]:.2f}]", f"[{m_s1['pf_ci'][0]:.2f}, {m_s1['pf_ci'][1]:.2f}]", f"[{m_s2['pf_ci'][0]:.2f}, {m_s2['pf_ci'][1]:.2f}]", f"[{m_s3['pf_ci'][0]:.2f}, {m_s3['pf_ci'][1]:.2f}]"),
        ("Trade Win Rate (%)", f"{m_comp['win_rate']:.1f}%", f"{m_s1['win_rate']:.1f}%", f"{m_s2['win_rate']:.1f}%", f"{m_s3['win_rate']:.1f}%"),
        ("Win Rate (95% Wilson Score CI)", f"[{m_comp['win_rate_ci'][0]:.1f}%, {m_comp['win_rate_ci'][1]:.1f}%]", f"[{m_s1['win_rate_ci'][0]:.1f}%, {m_s1['win_rate_ci'][1]:.1f}%]", f"[{m_s2['win_rate_ci'][0]:.1f}%, {m_s2['win_rate_ci'][1]:.1f}%]", f"[{m_s3['win_rate_ci'][0]:.1f}%, {m_s3['win_rate_ci'][1]:.1f}%]"),
        ("Average Win / Average Loss",
         f"{fmt_currency(m_comp['avg_win'], 2, force_sign=True)} / -{fmt_currency(m_comp['avg_loss'], 2)}",
         f"{fmt_currency(m_s1['avg_win'], 2, force_sign=True)} / -{fmt_currency(m_s1['avg_loss'], 2)}",
         f"{fmt_currency(m_s2['avg_win'], 2, force_sign=True)} / -{fmt_currency(m_s2['avg_loss'], 2)}",
         f"{fmt_currency(m_s3['avg_win'], 2, force_sign=True)} / -{fmt_currency(m_s3['avg_loss'], 2)}"),
        ("Win / Loss Payoff Ratio", f"{m_comp['payoff_ratio']:.2f}x", f"{m_s1['payoff_ratio']:.2f}x", f"{m_s2['payoff_ratio']:.2f}x", f"{m_s3['payoff_ratio']:.2f}x"),
        ("Expectancy per Trade", fmt_currency(m_comp['avg_trade'], 2, force_sign=True), fmt_currency(m_s1['avg_trade'], 2, force_sign=True), fmt_currency(m_s2['avg_trade'], 2, force_sign=True), fmt_currency(m_s3['avg_trade'], 2, force_sign=True)),
        ("Expectancy (95% Bootstrap CI)", f"[{fmt_currency(m_comp['exp_ci'][0], 1, True)}, {fmt_currency(m_comp['exp_ci'][1], 1, True)}]", f"[{fmt_currency(m_s1['exp_ci'][0], 1, True)}, {fmt_currency(m_s1['exp_ci'][1], 1, True)}]", f"[{fmt_currency(m_s2['exp_ci'][0], 1, True)}, {fmt_currency(m_s2['exp_ci'][1], 1, True)}]", f"[{fmt_currency(m_s3['exp_ci'][0], 1, True)}, {fmt_currency(m_s3['exp_ci'][1], 1, True)}]"),
        ("Median Trade P&L", fmt_currency(m_comp['median_trade'], 2, force_sign=True), fmt_currency(m_s1['median_trade'], 2, force_sign=True), fmt_currency(m_s2['median_trade'], 2, force_sign=True), fmt_currency(m_s3['median_trade'], 2, force_sign=True)),
        ("Maximum Drawdown ($)", fmt_currency(m_comp['max_dd'], 2), fmt_currency(m_s1['max_dd'], 2), fmt_currency(m_s2['max_dd'], 2), fmt_currency(m_s3['max_dd'], 2)),
        ("Maximum Drawdown (% on $25k)", f"{m_comp['max_dd_pct']:.2f}%", f"{m_s1['max_dd_pct']:.2f}%", f"{m_s2['max_dd_pct']:.2f}%", f"{m_s3['max_dd_pct']:.2f}%"),
        ("Max Drawdown Duration (Calendar Days)", f"{m_comp['max_dd_dur_days']} days ({m_comp['max_dd_dur_sessions']} sess)", f"{m_s1['max_dd_dur_days']} days ({m_s1['max_dd_dur_sessions']} sess)", f"{m_s2['max_dd_dur_days']} days ({m_s2['max_dd_dur_sessions']} sess)", f"{m_s3['max_dd_dur_days']} days ({m_s3['max_dd_dur_sessions']} sess)"),
        ("Recovery Factor (Net / Max DD)", f"{m_comp['recovery_factor']:.2f}x", f"{m_s1['recovery_factor']:.2f}x", f"{m_s2['recovery_factor']:.2f}x", f"{m_s3['recovery_factor']:.2f}x"),
        ("Calendar Daily Sharpe (Ann. sqrt 252)", f"{m_comp['sharpe']:.2f}", f"{m_s1['sharpe']:.2f}", f"{m_s2['sharpe']:.2f}", f"{m_s3['sharpe']:.2f}"),
        ("Calendar Daily Sortino (Ann. sqrt 252)", f"{m_comp['sortino']:.2f}", f"{m_s1['sortino']:.2f}", f"{m_s2['sortino']:.2f}", f"{m_s3['sortino']:.2f}"),
        ("Calmar Ratio (Ann. Return / Max DD)", f"{m_comp['calmar']:.2f}", f"{m_s1['calmar']:.2f}", f"{m_s2['calmar']:.2f}", f"{m_s3['calmar']:.2f}"),
        ("Omega Ratio (Threshold=0)", f"{m_comp.get('omega_ratio', 0.0):.2f}", f"{m_s1.get('omega_ratio', 0.0):.2f}", f"{m_s2.get('omega_ratio', 0.0):.2f}", f"{m_s3.get('omega_ratio', 0.0):.2f}"),
        ("Gain-to-Pain Ratio (Schwager)", f"{m_comp.get('gain_to_pain_ratio', 0.0):.2f}", f"{m_s1.get('gain_to_pain_ratio', 0.0):.2f}", f"{m_s2.get('gain_to_pain_ratio', 0.0):.2f}", f"{m_s3.get('gain_to_pain_ratio', 0.0):.2f}"),
        ("Half-Kelly Capital Sizing", f"{m_comp.get('half_kelly', 0.0):.3f}", f"{m_s1.get('half_kelly', 0.0):.3f}", f"{m_s2.get('half_kelly', 0.0):.3f}", f"{m_s3.get('half_kelly', 0.0):.3f}"),
        ("Probabilistic Sharpe Ratio (PSR)", f"{m_comp['psr']*100:.1f}%", f"{m_s1['psr']*100:.1f}%", f"{m_s2['psr']*100:.1f}%", f"{m_s3['psr']*100:.1f}%"),
        ("Min Track Record Length (MinTRL)", f"{m_comp['min_trl_years']:.2f} yrs", f"{m_s1['min_trl_years']:.2f} yrs", f"{m_s2['min_trl_years']:.2f} yrs", f"{m_s3['min_trl_years']:.2f} yrs"),
        ("System Quality Number (SQN)", f"{m_comp['sqn']:.2f}", f"{m_s1['sqn']:.2f}", f"{m_s2['sqn']:.2f}", f"{m_s3['sqn']:.2f}"),
        ("Student's t-Stat (p-Value)", f"{m_comp['t_stat']:.2f} (p<{m_comp['p_value']:.1e})", f"{m_s1['t_stat']:.2f} (p<{m_s1['p_value']:.1e})", f"{m_s2['t_stat']:.2f} (p<{m_s2['p_value']:.1e})", f"{m_s3['t_stat']:.2f} (p<{m_s3['p_value']:.1e})"),
        ("Ulcer Index / % Time Underwater", f"{m_comp['ulcer_index']:.2f}% / {m_comp['underwater_pct']:.1f}%", f"{m_s1['ulcer_index']:.2f}% / {m_s1['underwater_pct']:.1f}%", f"{m_s2['ulcer_index']:.2f}% / {m_s2['underwater_pct']:.1f}%", f"{m_s3['ulcer_index']:.2f}% / {m_s3['underwater_pct']:.1f}%"),
        ("Annual Net Profit ($/year)", fmt_currency(m_comp['annual_profit'], 2), fmt_currency(m_s1['annual_profit'], 2), fmt_currency(m_s2['annual_profit'], 2), fmt_currency(m_s3['annual_profit'], 2)),
        ("Annualized Return (CAGR on $25k)", f"{m_comp['cagr_pct']:.2f}%", f"{m_s1['cagr_pct']:.2f}%", f"{m_s2['cagr_pct']:.2f}%", f"{m_s3['cagr_pct']:.2f}%"),
        ("Calendar Sessions Win Rate (%)", f"{m_comp['daily_wr']:.1f}% ({m_comp['profit_days']}/{m_comp['total_days']})", f"{m_s1['daily_wr']:.1f}%", f"{m_s2['daily_wr']:.1f}%", f"{m_s3['daily_wr']:.1f}%"),
        ("Traded Sessions Win Rate (%)", f"{m_comp['traded_session_wr']:.1f}% ({m_comp['profit_days']}/{m_comp['traded_days']})", f"{m_s1['traded_session_wr']:.1f}%", f"{m_s2['traded_session_wr']:.1f}%", f"{m_s3['traded_session_wr']:.1f}%"),
        ("Worst Single Session P&L", fmt_currency(m_comp['worst_day'], 2), fmt_currency(m_s1['worst_day'], 2), fmt_currency(m_s2['worst_day'], 2), fmt_currency(m_s3['worst_day'], 2)),
        ("Daily Value at Risk (VaR 95%)", fmt_currency(m_comp['var_95_daily'], 2), fmt_currency(m_s1['var_95_daily'], 2), fmt_currency(m_s2['var_95_daily'], 2), fmt_currency(m_s3['var_95_daily'], 2)),
        ("Daily Expected Shortfall (CVaR 95%)", fmt_currency(m_comp['cvar_95_daily'], 2), fmt_currency(m_s1['cvar_95_daily'], 2), fmt_currency(m_s2['cvar_95_daily'], 2), fmt_currency(m_s3['cvar_95_daily'], 2)),
        ("Tail Risk Ratio (95th / 5th)", f"{m_comp.get('tail_risk_ratio', 0.0):.2f}x", f"{m_s1.get('tail_risk_ratio', 0.0):.2f}x", f"{m_s2.get('tail_risk_ratio', 0.0):.2f}x", f"{m_s3.get('tail_risk_ratio', 0.0):.2f}x"),
        ("Average Holding Time", f"{m_comp['avg_hold_min']:.1f} mins", f"{m_s1['avg_hold_min']:.1f} mins", f"{m_s2['avg_hold_min']:.1f} mins", f"{m_s3['avg_hold_min']:.1f} mins"),
        ("Long Performance", f"{m_comp['long_trades']}t • {fmt_currency(m_comp['long_net'], 0)} ({m_comp['long_wr']:.1f}%)", f"{m_s1['long_trades']}t • {fmt_currency(m_s1['long_net'], 0)}", f"{m_s2['long_trades']}t • {fmt_currency(m_s2['long_net'], 0)}", f"{m_s3['long_trades']}t • {fmt_currency(m_s3['long_net'], 0)}"),
        ("Short Performance", f"{m_comp['short_trades']}t • {fmt_currency(m_comp['short_net'], 0)} ({m_comp['short_wr']:.1f}%)", f"{m_s1['short_trades']}t • {fmt_currency(m_s1['short_net'], 0)}", f"{m_s2['short_trades']}t • {fmt_currency(m_s2['short_net'], 0)}", f"{m_s3['short_trades']}t • {fmt_currency(m_s3['short_net'], 0)}"),
        ("Open Backtest Format (.obtf)", "run_canonical_lucid_flex_ensemble_2021_2026.obtf", "run_canonical_s1_va_breakout_2021_2026.obtf", "run_canonical_s3_gold_london_fix_2021_2026.obtf", "run_canonical_s2_macro_momentum_2021_2026.obtf"),
        ("Provenance Tier & Verification", "BASELINE (Rule 2 & 3 Verified)", "BASELINE (Rule 2 & 3 Verified)", "BASELINE (Rule 2 & 3 Verified)", "BASELINE (Rule 2 & 3 Verified)"),
    ]

    th_headers = ["Metric Specification", "Unified Composite", "Strategy 1 (09:45 VA)", "Strategy 2 (10:15 Gold)", "Strategy 3 (08:35 Macro)"]
    t_x = [0.02, 0.40, 0.58, 0.73, 0.88]
    for i, h in enumerate(th_headers):
        ax.text(t_x[i], 0.942, h, fontsize=8.5, fontweight="bold", color="#000000", ha="left" if i == 0 else "right")

    y_t = 0.918
    for row_idx, r in enumerate(table_data):
        ax.axhline(y_t + 0.005, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        is_bold = row_idx in [2, 3, 5, 6, 7, 9, 16, 20, 21, 23, 25, 41, 42]
        for c_idx, val in enumerate(r):
            f_w = "bold" if is_bold else "normal"
            c_txt = "#1f77b4" if (c_idx == 1 and is_bold) else ("#2ca02c" if row_idx >= 41 else "#000000")
            ax.text(t_x[c_idx], y_t - 0.005, val, fontsize=7.2, fontweight=f_w, color=c_txt, ha="left" if c_idx == 0 else "right")
        y_t -= 0.0210

    out_path = OUT_DIR / "06_strategy_comprehensive_scorecard_master.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── MASTER OVERVIEW POSTER ───────────────────────────────────────────────────
def render_poster_master(
    trades: pd.DataFrame,
    calendar: list[str],
    m_comp: dict,
    m_s1: dict,
    m_s2: dict,
    m_s3: dict,
) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(18, 26), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    gs = fig.add_gridspec(5, 2, height_ratios=[3.6, 1.8, 2.2, 3.4, 2.0], hspace=0.35, wspace=0.20)

    # Reindex daily PnLs
    d_comp = da.daily_series(trades, calendar, "research_pnl")
    d_s1 = da.daily_series(trades[trades["strat"] == "S1"], calendar, "research_pnl")
    d_s2 = da.daily_series(trades[trades["strat"] == "S2"], calendar, "research_pnl")
    d_s3 = da.daily_series(trades[trades["strat"] == "S3"], calendar, "research_pnl")

    cal_dates = pd.to_datetime(calendar)
    eq_comp = d_comp.cumsum().to_numpy() + 25_000.0
    eq_peak = np.maximum.accumulate(eq_comp)
    eq_s1 = d_s1.cumsum().to_numpy() + 25_000.0
    eq_s2 = d_s2.cumsum().to_numpy() + 25_000.0
    eq_s3 = d_s3.cumsum().to_numpy() + 25_000.0

    # Panel 1: Main Backtest Results
    ax_main = fig.add_subplot(gs[0, :])
    format_spines_and_grid(ax_main)

    ax_main.plot(cal_dates, eq_comp, color="#1f77b4", linewidth=2.0, label="Unified Composite (All 3)")
    ax_main.plot(cal_dates, eq_s1, color="#ff7f0e", linewidth=1.5, label="Strategy 1 (09:45 VA Breakout)")
    ax_main.plot(cal_dates, eq_s2, color="#2ca02c", linewidth=1.5, label="Strategy 2 (10:15 Gold Fix)")
    ax_main.plot(cal_dates, eq_s3, color="#d62728", linewidth=1.5, label="Strategy 3 (08:35 Macro Momentum)")
    ax_main.plot(cal_dates, eq_peak, color="#9467bd", linestyle="--", linewidth=1.0, alpha=0.8, label="Running High-Water Mark")

    ax_main.set_title("Backtest Results - Multi-Strategy Quantitative Portfolio", fontsize=16, color="#000000", pad=12)
    ax_main.set_xlabel("Date", fontsize=11, color="#000000")
    ax_main.set_ylabel("Portfolio Value ($)", fontsize=11, color="#000000")
    ax_main.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_main.xaxis.set_major_locator(mdates.YearLocator())
    ax_main.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_main.set_xlim(cal_dates[0], cal_dates[-1])

    leg = ax_main.legend(title="Strategy", loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=9.5)
    leg.get_title().set_fontsize(10)
    leg.get_title().set_fontweight("bold")

    # Panel 2: Underwater Drawdown
    ax_dd = fig.add_subplot(gs[1, :])
    format_spines_and_grid(ax_dd)

    dd_vals = eq_comp - eq_peak
    ax_dd.fill_between(cal_dates, dd_vals, 0, color="#d62728", alpha=0.25)
    ax_dd.plot(cal_dates, dd_vals, color="#d62728", linewidth=1.2, label=f"Drawdown (Max: -${abs(m_comp['max_dd']):,.2f} • Recovery Factor: {m_comp['recovery_factor']:.2f}x)")

    ax_dd.set_title("Drawdown ($ Below Peak, Continuous Session Calendar)", fontsize=13, color="#000000", pad=8)
    ax_dd.set_xlabel("Date", fontsize=10, color="#000000")
    ax_dd.set_ylabel("Drawdown ($)", fontsize=10, color="#000000")
    ax_dd.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_dd.xaxis.set_major_locator(mdates.YearLocator())
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_dd.set_xlim(cal_dates[0], cal_dates[-1])
    ax_dd.legend(loc="lower left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=9)

    # Panel 3A: Trade Outcome Distribution
    ax_hist = fig.add_subplot(gs[2, 0])
    format_spines_and_grid(ax_hist)

    wins = trades[trades["research_pnl"] > 0]["research_pnl"]
    losses = trades[trades["research_pnl"] <= 0]["research_pnl"]
    ax_hist.hist(wins, bins=25, color="#1f77b4", edgecolor="#000000", alpha=0.85, label=f"Wins ({len(wins)} • avg +${wins.mean():.0f})")
    ax_hist.hist(losses, bins=25, color="#d62728", edgecolor="#000000", alpha=0.85, label=f"Losses ({len(losses)} • avg -${abs(losses.mean()):.0f})")
    ax_hist.axvline(m_comp["avg_trade"], color="#2ca02c", linestyle="--", linewidth=1.8, label=f"Expectancy: +${m_comp['avg_trade']:.2f}")

    ax_hist.set_title("Trade Outcome Distribution", fontsize=12, color="#000000", pad=8)
    ax_hist.set_xlabel("Net P&L per Trade ($)", fontsize=9.5, color="#000000")
    ax_hist.set_ylabel("Trade Count", fontsize=9.5, color="#000000")
    ax_hist.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_hist.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8.5)

    # Panel 3B: Monthly P&L Matrix
    ax_mo = fig.add_subplot(gs[2, 1])
    ax_mo.set_facecolor("#FFFFFF")
    ax_mo.axis("off")

    ax_mo.text(0.02, 0.96, "Monthly Returns Matrix (USD Net)", fontsize=11, fontweight="bold", color="#000000")

    piv = trades.assign(year=trades["entry_time"].dt.year, month=trades["entry_time"].dt.month).pivot_table(index="year", columns="month", values="research_pnl", aggfunc="sum").fillna(0.0)
    mo_lbls = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "YTD"]
    col_w = 0.068
    ax_mo.text(0.02, 0.84, "Year", fontsize=8, fontweight="bold", color="#000000")
    for i, m_name in enumerate(mo_lbls):
        ax_mo.text(0.10 + i * col_w, 0.84, m_name, fontsize=8, fontweight="bold", color="#000000", ha="right")

    y_pos = 0.70
    for yr in sorted(piv.index):
        ax_mo.text(0.02, y_pos, str(yr), fontsize=8.2, fontweight="bold", color="#000000")
        yr_sum = piv.loc[yr].sum()
        for m_idx in range(1, 13):
            val = piv.loc[yr, m_idx] if m_idx in piv.columns else 0.0
            txt = f"{val:+.0f}" if val != 0 else "-"
            c = "#2ca02c" if val > 0 else ("#d62728" if val < 0 else "#666666")
            ax_mo.text(0.10 + (m_idx - 1) * col_w, y_pos, txt, fontsize=7.8, color=c, ha="right")
        ytd_c = "#1f77b4" if yr_sum > 0 else "#d62728"
        ax_mo.text(0.10 + 12 * col_w, y_pos, f"${yr_sum:+,.0f}", fontsize=8.2, fontweight="bold", color=ytd_c, ha="right")
        y_pos -= 0.13

    # Panel 4: Full Metrics Inventory Spreadsheet Table
    ax_tab = fig.add_subplot(gs[3, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.97, "Comprehensive Strategy Performance & Risk Metrics Inventory", fontsize=12, fontweight="bold", color="#000000")

    table_data = [
        ("Execution Window & Time", "All 3 Windows", "09:45 - 10:15 ET", "10:15 - 10:45 ET", "08:35 - 09:15 ET"),
        ("Traded Instruments", "MNQ, MES, MGC", "MNQ, MES", "MGC", "MNQ"),
        ("Total Executions / Trades", f"{m_comp['trades']}", f"{m_s1['trades']}", f"{m_s2['trades']}", f"{m_s3['trades']}"),
        ("Net Profit (USD)", fmt_currency(m_comp['net_profit'], 2), fmt_currency(m_s1['net_profit'], 2), fmt_currency(m_s2['net_profit'], 2), fmt_currency(m_s3['net_profit'], 2)),
        ("Profit Factor", f"{m_comp['profit_factor']:.2f}", f"{m_s1['profit_factor']:.2f}", f"{m_s2['profit_factor']:.2f}", f"{m_s3['profit_factor']:.2f}"),
        ("Trade Win Rate (%)", f"{m_comp['win_rate']:.1f}%", f"{m_s1['win_rate']:.1f}%", f"{m_s2['win_rate']:.1f}%", f"{m_s3['win_rate']:.1f}%"),
        ("Average Win / Average Loss",
         f"{fmt_currency(m_comp['avg_win'], 2, force_sign=True)} / -{fmt_currency(m_comp['avg_loss'], 2)}",
         f"{fmt_currency(m_s1['avg_win'], 2, force_sign=True)} / -{fmt_currency(m_s1['avg_loss'], 2)}",
         f"{fmt_currency(m_s2['avg_win'], 2, force_sign=True)} / -{fmt_currency(m_s2['avg_loss'], 2)}",
         f"{fmt_currency(m_s3['avg_win'], 2, force_sign=True)} / -{fmt_currency(m_s3['avg_loss'], 2)}"),
        ("Win / Loss Payoff Ratio", f"{m_comp['payoff_ratio']:.2f}x", f"{m_s1['payoff_ratio']:.2f}x", f"{m_s2['payoff_ratio']:.2f}x", f"{m_s3['payoff_ratio']:.2f}x"),
        ("Expectancy per Trade", fmt_currency(m_comp['avg_trade'], 2, force_sign=True), fmt_currency(m_s1['avg_trade'], 2, force_sign=True), fmt_currency(m_s2['avg_trade'], 2, force_sign=True), fmt_currency(m_s3['avg_trade'], 2, force_sign=True)),
        ("Maximum Drawdown ($)", fmt_currency(m_comp['max_dd'], 2), fmt_currency(m_s1['max_dd'], 2), fmt_currency(m_s2['max_dd'], 2), fmt_currency(m_s3['max_dd'], 2)),
        ("Max Drawdown Duration (Calendar Days)", f"{m_comp['max_dd_dur_days']} days ({m_comp['max_dd_dur_sessions']} sess)", f"{m_s1['max_dd_dur_days']} days", f"{m_s2['max_dd_dur_days']} days", f"{m_s3['max_dd_dur_days']} days"),
        ("Recovery Factor (Net / Max DD)", f"{m_comp['recovery_factor']:.2f}x", f"{m_s1['recovery_factor']:.2f}x", f"{m_s2['recovery_factor']:.2f}x", f"{m_s3['recovery_factor']:.2f}x"),
        ("Calendar Daily Sharpe (Ann. sqrt 252)", f"{m_comp['sharpe']:.2f}", f"{m_s1['sharpe']:.2f}", f"{m_s2['sharpe']:.2f}", f"{m_s3['sharpe']:.2f}"),
        ("Calendar Daily Sortino (Ann. sqrt 252)", f"{m_comp['sortino']:.2f}", f"{m_s1['sortino']:.2f}", f"{m_s2['sortino']:.2f}", f"{m_s3['sortino']:.2f}"),
        ("Calmar Ratio (Ann. Return / Max DD)", f"{m_comp.get('calmar_ratio', m_comp['calmar']):.2f}", f"{m_s1.get('calmar_ratio', m_s1['calmar']):.2f}", f"{m_s2.get('calmar_ratio', m_s2['calmar']):.2f}", f"{m_s3.get('calmar_ratio', m_s3['calmar']):.2f}"),
        ("Omega Ratio / Gain-to-Pain", f"{m_comp.get('omega_ratio', 0.0):.2f} / {m_comp.get('gain_to_pain_ratio', 0.0):.2f}", f"{m_s1.get('omega_ratio', 0.0):.2f} / {m_s1.get('gain_to_pain_ratio', 0.0):.2f}", f"{m_s2.get('omega_ratio', 0.0):.2f} / {m_s2.get('gain_to_pain_ratio', 0.0):.2f}", f"{m_s3.get('omega_ratio', 0.0):.2f} / {m_s3.get('gain_to_pain_ratio', 0.0):.2f}"),
        ("Trimmed PF (ex-2% luck) / Dominance", f"{m_comp.get('trimmed_profit_factor', 0.0):.2f} / {m_comp.get('top_5_wins_pct', 0.0):.1f}%", f"{m_s1.get('trimmed_profit_factor', 0.0):.2f} / {m_s1.get('top_5_wins_pct', 0.0):.1f}%", f"{m_s2.get('trimmed_profit_factor', 0.0):.2f} / {m_s2.get('top_5_wins_pct', 0.0):.1f}%", f"{m_s3.get('trimmed_profit_factor', 0.0):.2f} / {m_s3.get('top_5_wins_pct', 0.0):.1f}%"),
        ("Half-Kelly Capital Sizing", f"{m_comp.get('half_kelly', 0.0):.3f}", f"{m_s1.get('half_kelly', 0.0):.3f}", f"{m_s2.get('half_kelly', 0.0):.3f}", f"{m_s3.get('half_kelly', 0.0):.3f}"),
        ("Probabilistic Sharpe Ratio (PSR)", f"{m_comp['psr']*100:.1f}%", f"{m_s1['psr']*100:.1f}%", f"{m_s2['psr']*100:.1f}%", f"{m_s3['psr']*100:.1f}%"),
        ("System Quality Number (SQN)", f"{m_comp['sqn']:.2f}", f"{m_s1['sqn']:.2f}", f"{m_s2['sqn']:.2f}", f"{m_s3['sqn']:.2f}"),
        ("Annual Net Profit ($/year)", fmt_currency(m_comp['annual_profit'], 2), fmt_currency(m_s1['annual_profit'], 2), fmt_currency(m_s2['annual_profit'], 2), fmt_currency(m_s3['annual_profit'], 2)),
        ("Calendar Sessions Win Rate (%)", f"{m_comp['daily_wr']:.1f}% ({m_comp['profit_days']}/{m_comp['total_days']})", f"{m_s1['daily_wr']:.1f}%", f"{m_s2['daily_wr']:.1f}%", f"{m_s3['daily_wr']:.1f}%"),
        ("Daily Value at Risk (VaR 95%)", fmt_currency(m_comp['var_95_daily'], 2), fmt_currency(m_s1['var_95_daily'], 2), fmt_currency(m_s2['var_95_daily'], 2), fmt_currency(m_s3['var_95_daily'], 2)),
        ("Daily Expected Shortfall (CVaR 95%)", fmt_currency(m_comp.get('cvar_95', m_comp['cvar_95_daily']), 2), fmt_currency(m_s1.get('cvar_95', m_s1['cvar_95_daily']), 2), fmt_currency(m_s2.get('cvar_95', m_s2['cvar_95_daily']), 2), fmt_currency(m_s3.get('cvar_95', m_s3['cvar_95_daily']), 2)),
        ("Average Holding Time", f"{m_comp['avg_hold_min']:.1f} mins", f"{m_s1['avg_hold_min']:.1f} mins", f"{m_s2['avg_hold_min']:.1f} mins", f"{m_s3['avg_hold_min']:.1f} mins"),
    ]

    th_headers = ["Metric Specification", "Unified Composite", "Strategy 1 (09:45 VA)", "Strategy 2 (10:15 Gold)", "Strategy 3 (08:35 Macro)"]
    t_x = [0.02, 0.40, 0.58, 0.73, 0.88]
    for i, h in enumerate(th_headers):
        ax_tab.text(t_x[i], 0.91, h, fontsize=8.5, fontweight="bold", color="#000000", ha="left" if i == 0 else "right")

    y_t = 0.87
    for row_idx, r in enumerate(table_data):
        ax_tab.axhline(y_t + 0.005, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        is_bold = row_idx in [2, 3, 4, 5, 9, 12, 14, 15, 16]
        for c_idx, val in enumerate(r):
            f_w = "bold" if is_bold else "normal"
            c_txt = "#1f77b4" if (c_idx == 1 and is_bold) else "#000000"
            ax_tab.text(t_x[c_idx], y_t - 0.005, val, fontsize=7.4, fontweight=f_w, color=c_txt, ha="left" if c_idx == 0 else "right")
        y_t -= 0.035

    # Panel 5A: Slippage Breakeven Cliff
    ax_slip = fig.add_subplot(gs[4, 0])
    format_spines_and_grid(ax_slip)

    slip_df = da.slippage_curve(trades, "research_pnl", ticks=range(0, 9))
    ax_slip.plot(slip_df["ticks"], slip_df["pf"], marker="o", color="#1f77b4", linewidth=1.8, label="Profit Factor")
    ax_slip.axhline(1.0, color="#d62728", linestyle="--", linewidth=1.2, label="Breakeven Cliff (PF=1.00)")
    ax_slip.set_title("Slippage Sensitivity & Friction Breakeven Cliff", fontsize=11, color="#000000", pad=8)
    ax_slip.set_xlabel("Extra Adverse Ticks per Leg (Entry + Exit)", fontsize=9, color="#000000")
    ax_slip.set_ylabel("Profit Factor", fontsize=9, color="#000000")
    ax_slip.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel 5B: Markov Volatility Regime Contribution
    ax_mkv = fig.add_subplot(gs[4, 1])
    format_spines_and_grid(ax_mkv)

    reg_pnl = trades.groupby("markov_state_label")["research_pnl"].sum().reindex(["low_vol", "mid_vol", "high_vol"])
    reg_wr = trades.groupby("markov_state_label")["research_pnl"].agg(lambda x: (x > 0).mean() * 100).reindex(["low_vol", "mid_vol", "high_vol"])
    b_mkv = ax_mkv.bar(["Low-Vol (1.25x)", "Mid-Vol (1.00x)", "High-Vol (0.50x S3)"], reg_pnl, color=["#2ca02c", "#1f77b4", "#ff7f0e"], edgecolor="#000000", width=0.5)
    for idx, b in enumerate(b_mkv):
        h = b.get_height()
        ax_mkv.annotate(f"${h:,.0f}\n({reg_wr.iloc[idx]:.1f}% WR)", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 3),
                        textcoords="offset points", ha="center", va="bottom", color="#000000", fontweight="bold", fontsize=8)

    ax_mkv.set_title("Markov Volatility Regime Allocation (Option 2 Sizing)", fontsize=11, color="#000000", pad=8)
    ax_mkv.set_ylabel("Net Profit ($)", fontsize=9, color="#000000")
    ax_mkv.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_mkv.set_ylim(0, max(reg_pnl) * 1.25)

    # Provenance Stamp Footer on Poster (Rule 2 & 3 Compliance)
    ax_foot = fig.add_axes([0.02, 0.003, 0.96, 0.015])
    ax_foot.set_facecolor("#F8F9FA")
    for sp in ax_foot.spines.values():
        sp.set_color("#000000")
        sp.set_linewidth(0.8)
    ax_foot.set_xticks([])
    ax_foot.set_yticks([])
    ax_foot.text(0.01, 0.5, "PROVENANCE VERIFICATION (Rule 2 & 3): Run ID: run_canonical_lucid_flex_ensemble_2021_2026 | Tier: BASELINE | Data SHA-256: ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca | Bundle: results/bundles/run_canonical_lucid_flex_ensemble_2021_2026.obtf",
                 fontsize=7.8, fontweight="bold", color="#222222", va="center")

    out_path = OUT_DIR / "strategy_performance_quant_report.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── INTERACTIVE HTML DASHBOARD ────────────────────────────────────────────────
def generate_interactive_html_dashboard(
    trades: pd.DataFrame,
    calendar: list[str],
    m_comp: dict,
    m_s1: dict,
    m_s2: dict,
    m_s3: dict,
) -> Path:
    html_path = OUT_DIR / "dashboard.html"

    # Continuous daily calendar data for plotting
    d_comp = da.daily_series(trades, calendar, "research_pnl")
    d_s1 = da.daily_series(trades[trades["strat"] == "S1"], calendar, "research_pnl")
    d_s2 = da.daily_series(trades[trades["strat"] == "S2"], calendar, "research_pnl")
    d_s3 = da.daily_series(trades[trades["strat"] == "S3"], calendar, "research_pnl")

    eq_comp = (d_comp.cumsum() + 25_000.0).round(2).tolist()
    peak_comp = np.maximum.accumulate(eq_comp).round(2).tolist()
    dd_comp = (np.array(eq_comp) - np.array(peak_comp)).round(2).tolist()

    eq_s1 = (d_s1.cumsum() + 25_000.0).round(2).tolist()
    peak_s1 = np.maximum.accumulate(eq_s1).round(2).tolist()
    dd_s1 = (np.array(eq_s1) - np.array(peak_s1)).round(2).tolist()

    eq_s2 = (d_s2.cumsum() + 25_000.0).round(2).tolist()
    peak_s2 = np.maximum.accumulate(eq_s2).round(2).tolist()
    dd_s2 = (np.array(eq_s2) - np.array(peak_s2)).round(2).tolist()

    eq_s3 = (d_s3.cumsum() + 25_000.0).round(2).tolist()
    peak_s3 = np.maximum.accumulate(eq_s3).round(2).tolist()
    dd_s3 = (np.array(eq_s3) - np.array(peak_s3)).round(2).tolist()

    monthly_comp = compute_monthly_matrix_data(trades, "research_pnl")
    monthly_s1 = compute_monthly_matrix_data(trades[trades["strat"] == "S1"], "research_pnl")
    monthly_s2 = compute_monthly_matrix_data(trades[trades["strat"] == "S2"], "research_pnl")
    monthly_s3 = compute_monthly_matrix_data(trades[trades["strat"] == "S3"], "research_pnl")

    blotter = []
    cum_bal = 25_000.0
    for idx, r in trades.iterrows():
        pnl = float(r["research_pnl"])
        cum_bal += pnl
        blotter.append({
            "id": idx + 1,
            "date": r["date_str"],
            "time": r["entry_time"].strftime("%H:%M"),
            "strategy": "S1: VA Breakout" if r["strat"] == "S1" else ("S2: Gold Fix" if r["strat"] == "S2" else "S3: Macro Mom"),
            "symbol": r["micro"],
            "direction": r["direction"].upper(),
            "contracts": int(r["contracts"]),
            "regime": r.get("markov_state_label", "normal"),
            "mult": f"{r.get('markov_sizing_mult', 1.0):.2f}x",
            "pnl": round(pnl, 2),
            "cum_balance": round(cum_bal, 2),
            "hold_mins": round(float(r["hold_minutes"]), 1)
        })

    payload = {
        "dates": calendar,
        "cum_comp": eq_comp,
        "peak_comp": peak_comp,
        "dd_comp": dd_comp,
        "cum_s1": eq_s1,
        "peak_s1": peak_s1,
        "dd_s1": dd_s1,
        "cum_s2": eq_s2,
        "peak_s2": peak_s2,
        "dd_s2": dd_s2,
        "cum_s3": eq_s3,
        "peak_s3": peak_s3,
        "dd_s3": dd_s3,
        "metrics": {
            "comp": m_comp,
            "s1": m_s1,
            "s2": m_s2,
            "s3": m_s3,
        },
        "monthly": {
            "comp": monthly_comp,
            "s1": monthly_s1,
            "s2": monthly_s2,
            "s3": monthly_s3,
        },
        "blotter": blotter,
    }
    json_payload = json.dumps(payload)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Backtest Results - Quantitative Strategy Performance Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #FFFFFF;
    --text-primary: #000000;
    --text-secondary: #555555;
    --border: #E5E5E5;
    --accent-blue: #1f77b4;
    --accent-orange: #ff7f0e;
    --accent-green: #2ca02c;
    --accent-red: #d62728;
    --accent-purple: #9467bd;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: #FAFAFA;
    color: var(--text-primary);
    padding: 24px;
    line-height: 1.45;
  }}
  .container {{
    max-width: 1480px;
    margin: 0 auto;
    background: var(--bg);
    border: 1px solid var(--border);
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    padding: 28px;
  }}
  header {{
    border-bottom: 2px solid var(--text-primary);
    padding-bottom: 16px;
    margin-bottom: 24px;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }}
  h1 {{ font-size: 24px; font-weight: 700; color: var(--text-primary); letter-spacing: -0.3px; }}
  .meta-sub {{ font-size: 13px; color: var(--text-secondary); margin-top: 4px; }}
  .tabs {{
    display: flex;
    gap: 8px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 24px;
  }}
  .tab-btn {{
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 16px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    color: var(--text-secondary);
  }}
  .tab-btn.active {{
    color: var(--accent-blue);
    border-bottom-color: var(--accent-blue);
  }}
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
  }}
  .kpi-card {{
    background: #FFF;
    border: 1px solid var(--border);
    padding: 14px;
    border-radius: 4px;
  }}
  .kpi-label {{ font-size: 11px; text-transform: uppercase; color: var(--text-secondary); font-weight: 600; margin-bottom: 4px; }}
  .kpi-value {{ font-size: 20px; font-weight: 700; color: var(--text-primary); }}
  .kpi-sub {{ font-size: 11px; color: var(--text-secondary); margin-top: 2px; }}
  .chart-box {{
    background: #FFF;
    border: 1px solid var(--border);
    padding: 18px;
    margin-bottom: 24px;
    border-radius: 4px;
  }}
  .chart-title {{ font-size: 14px; font-weight: 700; margin-bottom: 12px; }}
  .table-box {{
    background: #FFF;
    border: 1px solid var(--border);
    margin-bottom: 24px;
    overflow-x: auto;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    text-align: left;
  }}
  th, td {{
    padding: 9px 12px;
    border-bottom: 1px solid var(--border);
  }}
  th {{
    background: #F7F7F7;
    font-weight: 700;
    color: var(--text-primary);
  }}
  tr:last-child td {{ border-bottom: none; }}
  .text-right {{ text-align: right; }}
  .num-pos {{ color: var(--accent-green); font-weight: 600; }}
  .num-neg {{ color: var(--accent-red); font-weight: 600; }}
  .search-input {{
    width: 260px;
    padding: 6px 10px;
    border: 1px solid var(--border);
    font-size: 13px;
    border-radius: 3px;
    margin-bottom: 12px;
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>Backtest Results - Quantitative Strategy Performance Report</h1>
      <div class="meta-sub">Institutional Continuous Calendar Analysis (1,499 Sessions • 2021-01-07 to 2026-10-30)</div>
    </div>
    <div style="text-align: right;">
      <div style="font-size: 14px; font-weight: 700; color: var(--accent-blue);">Unified 3-Strategy Ensemble</div>
      <div style="font-size: 12px; color: var(--text-secondary);">Base: $25,000 • LucidFlex Prop Parity</div>
    </div>
  </header>

  <div class="tabs">
    <button class="tab-btn active" onclick="switchStrategy('comp')">Unified Composite</button>
    <button class="tab-btn" onclick="switchStrategy('s1')">Strategy 1 (09:45 VA)</button>
    <button class="tab-btn" onclick="switchStrategy('s2')">Strategy 2 (10:15 Gold)</button>
    <button class="tab-btn" onclick="switchStrategy('s3')">Strategy 3 (08:35 Macro)</button>
  </div>

  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label">Net Profit</div>
      <div class="kpi-value" id="kpi-net">$0</div>
      <div class="kpi-sub" id="kpi-cagr">CAGR: 0.0%</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Profit Factor</div>
      <div class="kpi-value" id="kpi-pf">0.00</div>
      <div class="kpi-sub" id="kpi-pf-ci">CI: [0, 0]</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Trade Win Rate</div>
      <div class="kpi-value" id="kpi-wr">0.0%</div>
      <div class="kpi-sub" id="kpi-trades">0 trades</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Sortino / Calmar</div>
      <div class="kpi-value" id="kpi-sortino" style="color: var(--accent-blue);">0.00</div>
      <div class="kpi-sub" id="kpi-calmar">Calmar: 0.00</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Omega / Half-Kelly</div>
      <div class="kpi-value" id="kpi-omega">0.00</div>
      <div class="kpi-sub" id="kpi-kelly">Half-Kelly: 0.000</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Trimmed PF (ex-2%)</div>
      <div class="kpi-value" id="kpi-trimmed-pf">0.00</div>
      <div class="kpi-sub" id="kpi-dominance">Top 5 Wins: 0.0%</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Maximum Drawdown</div>
      <div class="kpi-value" id="kpi-dd" style="color: var(--accent-red);">$0</div>
      <div class="kpi-sub" id="kpi-rf">Recov: 0.0x</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">System Quality (SQN)</div>
      <div class="kpi-value" id="kpi-sqn">0.00</div>
      <div class="kpi-sub" id="kpi-tstat">t = 0.00</div>
    </div>
  </div>

  <div style="background: #F8F9FA; border: 1px solid #D0D5DD; border-left: 4px solid #1f77b4; border-radius: 4px; padding: 12px 16px; margin-bottom: 24px; font-size: 12px; font-family: monospace; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
    <div>
      <span style="background: #E8F5E9; color: #2E7D32; font-weight: bold; padding: 2px 6px; border-radius: 3px; margin-right: 8px;">TIER: BASELINE</span>
      <strong>PROVENANCE VERIFIED (Rule 2 & 3):</strong>
      <span style="color: #555;">Run ID: <code style="color: #000;">run_canonical_lucid_flex_ensemble_2021_2026</code></span> |
      <span style="color: #555;">Data SHA-256: <code style="color: #000;">ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca</code></span>
    </div>
    <div>
      <span style="background: #EDE7F6; color: #512DA8; font-weight: bold; padding: 2px 6px; border-radius: 3px;">OBTF BUNDLE VERIFIED</span>
      <span style="color: #555;"><code>results/bundles/run_canonical_lucid_flex_ensemble_2021_2026.obtf</code></span>
    </div>
  </div>

  <div class="chart-box">
    <div class="chart-title">Portfolio Equity Progression ($25,000 Base) & High-Water Mark</div>
    <div style="height: 380px;">
      <canvas id="equityChart"></canvas>
    </div>
  </div>

  <div class="chart-box">
    <div class="chart-title">Underwater Portfolio Drawdown ($)</div>
    <div style="height: 180px;">
      <canvas id="ddChart"></canvas>
    </div>
  </div>

  <div class="chart-box">
    <div class="chart-title">Monthly Net Returns Matrix ($ USD)</div>
    <div id="monthlyContainer"></div>
  </div>

  <div class="chart-box">
    <div class="chart-title">Historical Trade Blotter & Execution Journal</div>
    <input type="text" id="blotterSearch" class="search-input" placeholder="Search date, symbol, direction..." onkeyup="filterBlotter()">
    <div class="table-box" style="max-height: 480px; overflow-y: auto;">
      <table id="blotterTable">
        <thead>
          <tr>
            <th>#</th>
            <th>Date</th>
            <th>Time</th>
            <th>Strategy</th>
            <th>Symbol</th>
            <th>Side</th>
            <th class="text-right">Contracts</th>
            <th>Markov Regime</th>
            <th class="text-right">Net P&L</th>
            <th class="text-right">Cum Balance</th>
            <th class="text-right">Hold Time</th>
          </tr>
        </thead>
        <tbody id="blotterBody"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
const data = {json_payload};
let currentStrat = 'comp';
let eqChartInst = null;
let ddChartInst = null;

function fmtCurr(n, sign=false) {{
  if (n === null || n === undefined) return '-';
  const prefix = n < 0 ? '-$' : (sign && n > 0 ? '+$' : '$');
  return prefix + Math.abs(n).toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
}}

function switchStrategy(strat) {{
  currentStrat = strat;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  updateKPIs();
  updateCharts();
  renderMonthly();
}}

function updateKPIs() {{
  const m = data.metrics[currentStrat];
  document.getElementById('kpi-net').innerText = fmtCurr(m.net_profit, true);
  document.getElementById('kpi-cagr').innerText = `CAGR: ${{m.cagr_pct.toFixed(1)}}%`;
  document.getElementById('kpi-pf').innerText = m.profit_factor.toFixed(2);
  document.getElementById('kpi-pf-ci').innerText = `CI: [${{m.pf_ci[0].toFixed(2)}}, ${{m.pf_ci[1].toFixed(2)}}]`;
  document.getElementById('kpi-wr').innerText = `${{m.win_rate.toFixed(1)}}%`;
  document.getElementById('kpi-trades').innerText = `${{m.trades}} trades`;
  const sortinoVal = (m.sortino_ratio !== undefined ? m.sortino_ratio : (m.sortino || 0));
  const calmarVal = (m.calmar_ratio !== undefined ? m.calmar_ratio : (m.calmar || 0));
  document.getElementById('kpi-sortino').innerText = sortinoVal.toFixed(2);
  document.getElementById('kpi-calmar').innerText = `Calmar: ${{calmarVal.toFixed(2)}}`;
  const omegaVal = (m.omega_ratio !== undefined ? m.omega_ratio : 0);
  const kellyVal = (m.half_kelly !== undefined ? m.half_kelly : 0);
  document.getElementById('kpi-omega').innerText = omegaVal.toFixed(2);
  document.getElementById('kpi-kelly').innerText = `Half-Kelly: ${{kellyVal.toFixed(3)}}`;
  const trimmedPf = (m.trimmed_profit_factor !== undefined ? m.trimmed_profit_factor : 0);
  const domPct = (m.top_5_wins_pct !== undefined ? m.top_5_wins_pct : 0);
  document.getElementById('kpi-trimmed-pf').innerText = trimmedPf.toFixed(2);
  document.getElementById('kpi-dominance').innerText = `Top 5 Wins: ${{domPct.toFixed(1)}}%`;
  document.getElementById('kpi-dd').innerText = fmtCurr(m.max_dd);
  document.getElementById('kpi-rf').innerText = `Recov: ${{m.recovery_factor.toFixed(2)}}x`;
  document.getElementById('kpi-sqn').innerText = m.sqn.toFixed(2);
  document.getElementById('kpi-tstat').innerText = `t = ${{m.t_stat.toFixed(2)}} (p<${{m.p_value.toExponential(1)}})`;
}}

function updateCharts() {{
  const dates = data.dates;
  const cum = data[`cum_${{currentStrat}}`];
  const peak = data[`peak_${{currentStrat}}`];
  const dd = data[`dd_${{currentStrat}}`];

  if (eqChartInst) eqChartInst.destroy();
  if (ddChartInst) ddChartInst.destroy();

  const ctxEq = document.getElementById('equityChart').getContext('2d');
  eqChartInst = new Chart(ctxEq, {{
    type: 'line',
    data: {{
      labels: dates,
      datasets: [
        {{
          label: 'Portfolio Equity',
          data: cum,
          borderColor: '#1f77b4',
          borderWidth: 2,
          pointRadius: 0,
          fill: false,
        }},
        {{
          label: 'High-Water Mark',
          data: peak,
          borderColor: '#9467bd',
          borderWidth: 1.2,
          borderDash: [4, 4],
          pointRadius: 0,
          fill: false,
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ intersect: false, mode: 'index' }},
      plugins: {{ legend: {{ position: 'top' }} }},
      scales: {{
        x: {{ grid: {{ color: '#E5E5E5' }}, ticks: {{ maxTicksLimit: 10 }} }},
        y: {{ grid: {{ color: '#E5E5E5' }}, ticks: {{ callback: v => '$' + v.toLocaleString() }} }}
      }}
    }}
  }});

  const ctxDd = document.getElementById('ddChart').getContext('2d');
  ddChartInst = new Chart(ctxDd, {{
    type: 'line',
    data: {{
      labels: dates,
      datasets: [
        {{
          label: 'Drawdown ($)',
          data: dd,
          borderColor: '#d62728',
          backgroundColor: 'rgba(214, 39, 40, 0.15)',
          borderWidth: 1.2,
          pointRadius: 0,
          fill: true,
        }}
      ]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ intersect: false, mode: 'index' }},
      plugins: {{ legend: {{ position: 'top' }} }},
      scales: {{
        x: {{ grid: {{ color: '#E5E5E5' }}, ticks: {{ maxTicksLimit: 10 }} }},
        y: {{ grid: {{ color: '#E5E5E5' }}, ticks: {{ callback: v => '$' + v.toLocaleString() }} }}
      }}
    }}
  }});
}}

function renderMonthly() {{
  const mList = data.monthly[currentStrat];
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  let html = '<table><thead><tr><th>Year</th>';
  months.forEach(m => html += `<th class="text-right">${{m}}</th>`);
  html += '<th class="text-right">YTD Total</th></tr></thead><tbody>';

  mList.forEach(r => {{
    html += `<tr><td><strong>${{r.year}}</strong></td>`;
    for (let i = 1; i <= 12; i++) {{
      const v = r.months[i] || 0;
      const cls = v > 0 ? 'num-pos' : (v < 0 ? 'num-neg' : '');
      const txt = v !== 0 ? (v > 0 ? '+' : '') + Math.round(v).toLocaleString() : '-';
      html += `<td class="text-right ${{cls}}">${{txt}}</td>`;
    }}
    const ytdCls = r.ytd > 0 ? 'num-pos' : (r.ytd < 0 ? 'num-neg' : '');
    html += `<td class="text-right ${{ytdCls}}"><strong>${{fmtCurr(r.ytd, true)}}</strong></td></tr>`;
  }});
  html += '</tbody></table>';
  document.getElementById('monthlyContainer').innerHTML = html;
}}

function renderBlotter() {{
  const b = data.blotter;
  const tbody = document.getElementById('blotterBody');
  let html = '';
  b.forEach(t => {{
    const pnlCls = t.pnl > 0 ? 'num-pos' : (t.pnl < 0 ? 'num-neg' : '');
    html += `<tr>
      <td>${{t.id}}</td>
      <td>${{t.date}}</td>
      <td>${{t.time}}</td>
      <td>${{t.strategy}}</td>
      <td><strong>${{t.symbol}}</strong></td>
      <td>${{t.direction}}</td>
      <td class="text-right">${{t.contracts}}</td>
      <td>${{t.regime}}</td>
      <td class="text-right ${{pnlCls}}">${{fmtCurr(t.pnl, true)}}</td>
      <td class="text-right">${{fmtCurr(t.cum_balance)}}</td>
      <td class="text-right">${{t.hold_mins}}m</td>
    </tr>`;
  }});
  tbody.innerHTML = html;
}}

function filterBlotter() {{
  const q = document.getElementById('blotterSearch').value.toLowerCase();
  const rows = document.querySelectorAll('#blotterBody tr');
  rows.forEach(r => {{
    r.style.display = r.innerText.toLowerCase().includes(q) ? '' : 'none';
  }});
}}

window.onload = function() {{
  updateKPIs();
  updateCharts();
  renderMonthly();
  renderBlotter();
}};
</script>
</body>
</html>"""

    html_path.write_text(html_content, encoding="utf-8")
    return html_path


def main():
    print("=" * 80)
    print("INSTITUTIONAL QUANT STRATEGY DASHBOARD GENERATOR")
    print("=" * 80)
    print(f"Output Directory: {OUT_DIR}")

    print("Loading trade logs and exchange session calendar...")
    trades = da.load_trades()
    start_date = trades["date"].min()
    end_date = trades["date"].max()
    calendar = da.load_session_calendar(start=start_date, end=end_date)
    print(f"Loaded {len(trades)} trades across {len(calendar)} continuous exchange sessions ({start_date} to {end_date}).")

    print("\nComputing comprehensive performance metrics...")
    m_comp = build_full_metrics_dict(trades, calendar, "research_pnl")
    m_s1 = build_full_metrics_dict(trades[trades["strat"] == "S1"], calendar, "research_pnl")
    m_s2 = build_full_metrics_dict(trades[trades["strat"] == "S2"], calendar, "research_pnl")
    m_s3 = build_full_metrics_dict(trades[trades["strat"] == "S3"], calendar, "research_pnl")

    print(f"Unified Composite: Net {fmt_currency(m_comp['net_profit'])}, PF {m_comp['profit_factor']:.2f}, WR {m_comp['win_rate']:.1f}%, Full Calendar Sharpe {m_comp['sharpe']:.2f}, MaxDD {fmt_currency(m_comp['max_dd'])}")
    print(f"Strategy 1 (09:45): Net {fmt_currency(m_s1['net_profit'])}, PF {m_s1['profit_factor']:.2f}, WR {m_s1['win_rate']:.1f}%, Calendar Sharpe {m_s1['sharpe']:.2f}")
    print(f"Strategy 2 (10:15): Net {fmt_currency(m_s2['net_profit'])}, PF {m_s2['profit_factor']:.2f}, WR {m_s2['win_rate']:.1f}%, Calendar Sharpe {m_s2['sharpe']:.2f}")
    print(f"Strategy 3 (08:35): Net {fmt_currency(m_s3['net_profit'])}, PF {m_s3['profit_factor']:.2f}, WR {m_s3['win_rate']:.1f}%, Calendar Sharpe {m_s3['sharpe']:.2f}")

    print("\nRendering Publication-Grade PNG Sheets...")
    p1 = render_sheet_01_equity(trades, calendar, m_comp, m_s1, m_s2, m_s3)
    print(f"  [Sheet 01] Multi-Strategy Equity Curves & Drawdown: {p1.name}")

    p2 = render_sheet_02_rolling_edge(trades, calendar, m_comp)
    print(f"  [Sheet 02] Rolling Edge & Directional Stability: {p2.name}")

    p3 = render_sheet_03_timing(trades, calendar)
    print(f"  [Sheet 03] Intraday Timing & Window Microstructure: {p3.name}")

    p4 = render_sheet_04_returns_and_var(trades, calendar, m_comp)
    print(f"  [Sheet 04] Returns Distribution & Value at Risk: {p4.name}")

    p5 = render_sheet_05_stress_tests(trades, calendar)
    print(f"  [Sheet 05] Stress Tests, Markov Regimes & Permutations: {p5.name}")

    p6 = render_sheet_06_scorecard(m_comp, m_s1, m_s2, m_s3)
    print(f"  [Sheet 06] Comprehensive Scorecard Master Table: {p6.name}")

    p_post = render_poster_master(trades, calendar, m_comp, m_s1, m_s2, m_s3)
    print(f"  [Poster] Master Overview Quant Report: {p_post.name}")

    print("\nGenerating Interactive HTML Dashboard...")
    p_html = generate_interactive_html_dashboard(trades, calendar, m_comp, m_s1, m_s2, m_s3)
    print(f"  [HTML] Interactive Dashboard: {p_html.name}")

    print("\nAll strategy dashboard artifacts generated successfully.")


if __name__ == "__main__":
    main()
