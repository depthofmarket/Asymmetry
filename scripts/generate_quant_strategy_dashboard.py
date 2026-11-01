#!/usr/bin/env python3
"""
Institutional Quantitative Performance Dashboard Generator.
Renders all backtest metrics in the exact academic / quantitative Python style:
- Clean white background (#FFFFFF)
- Crisp black box spines (#000000)
- Light gray grid lines (#E5E5E5)
- Standard Matplotlib / Seaborn tab10 color palette (Blue #1f77b4, Orange #ff7f0e, Green #2ca02c, Red #d62728)
- Clean sans-serif typography with tabular monospaced numbers
- Complete inventory of EVERY metric used on the strategies
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
import matplotlib.dates as mdates

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUT_DIR = REPO_ROOT / "results" / "strategy_dashboard"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DATA_PATH = REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"


def load_dataset() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Missing dataset: {DATA_PATH}")
    df = pd.read_parquet(DATA_PATH)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["date_str"] = df["entry_time"].dt.strftime("%Y-%m-%d")
    df["year"] = df["entry_time"].dt.year
    df["month"] = df["entry_time"].dt.month
    df["weekday"] = df["entry_time"].dt.day_name()
    df["hold_minutes"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 60.0
    return df.sort_values("entry_time").reset_index(drop=True)


def compute_all_metrics(trades: pd.DataFrame, initial_capital: float = 25_000.0) -> dict:
    n = len(trades)
    if n == 0:
        return {}
    net = float(trades["pnl"].sum())
    wins = trades[trades["pnl"] > 0]["pnl"]
    losses = trades[trades["pnl"] <= 0]["pnl"]
    gw = float(wins.sum())
    gl = float(abs(losses.sum()))
    pf = gw / gl if gl > 0 else np.nan
    wr = (len(wins) / n) * 100.0
    loss_rate = 100.0 - wr
    avg_trade = float(trades["pnl"].mean())
    med_trade = float(trades["pnl"].median())
    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(abs(losses.mean())) if len(losses) > 0 else 0.0
    payoff = avg_win / avg_loss if avg_loss > 0 else np.nan

    cum = trades["pnl"].cumsum()
    peak = cum.cummax()
    dd = cum - peak
    max_dd = float(dd.min())
    recovery_factor = net / abs(max_dd) if max_dd != 0 else np.nan

    # Drawdown duration calculation
    in_dd = dd < 0
    dd_durations = []
    curr_dur = 0
    for v in in_dd:
        if v:
            curr_dur += 1
        else:
            if curr_dur > 0:
                dd_durations.append(curr_dur)
            curr_dur = 0
    if curr_dur > 0:
        dd_durations.append(curr_dur)
    max_dd_dur = max(dd_durations) if dd_durations else 0

    # Daily returns
    daily = trades.groupby("date_str")["pnl"].sum()
    d_mean = daily.mean()
    d_std = daily.std()
    sharpe = float((d_mean / d_std) * np.sqrt(252)) if d_std > 0 else 0.0
    down = daily[daily < 0]
    sortino_std = np.sqrt((down**2).mean()) if len(down) > 0 else 1.0
    sortino = float((d_mean / sortino_std) * np.sqrt(252))

    # Daily VaR 95% & CVaR 95%
    var_95 = float(np.percentile(daily, 5))
    cvar_95 = float(daily[daily <= var_95].mean()) if len(daily[daily <= var_95]) > 0 else var_95

    # Annualized return
    years = (trades["entry_time"].max() - trades["entry_time"].min()).days / 365.25
    annual_profit = net / years if years > 0 else net
    calmar = annual_profit / abs(max_dd) if max_dd != 0 else np.nan
    cagr_pct = (annual_profit / initial_capital) * 100.0

    # Streaks
    is_l = (trades["pnl"] <= 0).astype(int)
    max_l = 0; cur_l = 0
    max_w = 0; cur_w = 0
    for x in is_l:
        if x == 1:
            cur_l += 1
            max_l = max(max_l, cur_l)
            cur_w = 0
        else:
            cur_w += 1
            max_w = max(max_w, cur_w)
            cur_l = 0

    daily_wr = (daily > 0).mean() * 100.0

    longs = trades[trades["direction"] == "long"]
    shorts = trades[trades["direction"] == "short"]

    return {
        "trades": n,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "net_profit": net,
        "gross_profit": gw,
        "gross_loss": gl,
        "profit_factor": pf,
        "win_rate": wr,
        "loss_rate": loss_rate,
        "avg_trade": avg_trade,
        "median_trade": med_trade,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff,
        "max_dd": max_dd,
        "max_dd_pct": (max_dd / initial_capital) * 100.0,
        "max_dd_dur_trades": max_dd_dur,
        "recovery_factor": recovery_factor,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "annual_profit": annual_profit,
        "cagr_pct": cagr_pct,
        "var_95_daily": var_95,
        "cvar_95_daily": cvar_95,
        "daily_wr": daily_wr,
        "profit_days": int((daily > 0).sum()),
        "total_days": int(len(daily)),
        "worst_day": float(daily.min()),
        "best_day": float(daily.max()),
        "largest_win": float(wins.max()) if len(wins) > 0 else 0.0,
        "largest_loss": float(losses.min()) if len(losses) > 0 else 0.0,
        "max_consec_wins": max_w,
        "max_consec_losses": max_l,
        "avg_hold_min": float(trades["hold_minutes"].mean()),
        "long_trades": len(longs),
        "long_net": float(longs["pnl"].sum()),
        "long_wr": float((longs["pnl"] > 0).mean() * 100.0) if len(longs) > 0 else 0.0,
        "long_pf": float(longs.loc[longs["pnl"] > 0, "pnl"].sum() / abs(longs.loc[longs["pnl"] <= 0, "pnl"].sum())) if len(longs.loc[longs["pnl"] <= 0]) > 0 else np.nan,
        "short_trades": len(shorts),
        "short_net": float(shorts["pnl"].sum()),
        "short_wr": float((shorts["pnl"] > 0).mean() * 100.0) if len(shorts) > 0 else 0.0,
        "short_pf": float(shorts.loc[shorts["pnl"] > 0, "pnl"].sum() / abs(shorts.loc[shorts["pnl"] <= 0, "pnl"].sum())) if len(shorts.loc[shorts["pnl"] <= 0]) > 0 else np.nan,
    }


def compute_monthly_matrix(trades: pd.DataFrame) -> list[dict]:
    piv = trades.pivot_table(index="year", columns="month", values="pnl", aggfunc="sum").fillna(0.0)
    res = []
    for yr in sorted(piv.index):
        sub_yr = trades[trades["year"] == yr]
        m_vals = []
        for m in range(1, 13):
            val = float(piv.loc[yr, m]) if m in piv.columns else 0.0
            m_vals.append(val)
        ytd = float(piv.loc[yr].sum())
        wr = float((sub_yr["pnl"] > 0).mean() * 100.0) if len(sub_yr) > 0 else 0.0
        res.append({
            "year": int(yr),
            "months": m_vals,
            "ytd": ytd,
            "trades": len(sub_yr),
            "win_rate": wr,
        })
    return res


def render_screenshot_style_poster(
    df: pd.DataFrame,
    m_comp: dict,
    m_s1: dict,
    m_s2: dict,
    m_s3: dict,
) -> Path:
    """
    Renders the exact visual style from the user's reference screenshot:
    - Pure white background (#FFFFFF)
    - Black box borders around all plots (#000000, linewidth=1.0)
    - Subtle gray gridlines (#E5E5E5)
    - Title: "Backtest Results" centered at top
    - Tab10 lines: Blue, Orange, Green, Red, Purple
    - Legend box with title "Strategy"
    - Clean academic spreadsheet-style tables below
    """
    plt.style.use("default")
    fig = plt.figure(figsize=(18, 26), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")

    # Layout:
    # Row 0: Main Backtest Results line chart (exactly matching screenshot)
    # Row 1: Underwater Drawdown chart
    # Row 2: Trade P&L Distribution Histogram & Monthly P&L Table
    # Row 3: Full Multi-Strategy Metrics Spreadsheet Table
    # Row 4: Slippage Breakeven Cliff & Markov Volatility Regimes
    gs = fig.add_gridspec(5, 2, height_ratios=[3.6, 1.8, 2.2, 3.4, 2.0], hspace=0.35, wspace=0.20)

    # ── PANEL 1: MAIN BACKTEST RESULTS (EXACT MATCH TO SCREENSHOT) ───────────
    ax_main = fig.add_subplot(gs[0, :])
    ax_main.set_facecolor("#FFFFFF")
    ax_main.grid(True, color="#E5E5E5", linestyle="-", linewidth=0.8)
    for sp in ax_main.spines.values():
        sp.set_color("#000000")
        sp.set_linewidth(1.0)

    df_s = df.sort_values("entry_time").reset_index(drop=True)
    comp_cum = df_s["pnl"].cumsum() + 25_000.0
    comp_peak = comp_cum.cummax()

    # Calculate portfolio values starting at $25,000 baseline
    s1_cum = df_s.apply(lambda r: r["pnl"] if r["window"] == 1 else 0.0, axis=1).cumsum() + 25_000.0
    s2_cum = df_s.apply(lambda r: r["pnl"] if r["window"] == 2 else 0.0, axis=1).cumsum() + 25_000.0
    s3_cum = df_s.apply(lambda r: r["pnl"] if r["window"] == 3 else 0.0, axis=1).cumsum() + 25_000.0

    ax_main.plot(df_s["entry_time"], comp_cum, color="#1f77b4", linewidth=2.0, label="Unified Composite (All 3)")
    ax_main.plot(df_s["entry_time"], s1_cum, color="#ff7f0e", linewidth=1.5, label="Strategy 1 (09:45 VA Breakout)")
    ax_main.plot(df_s["entry_time"], s2_cum, color="#2ca02c", linewidth=1.5, label="Strategy 2 (10:15 Gold Fix)")
    ax_main.plot(df_s["entry_time"], s3_cum, color="#d62728", linewidth=1.5, label="Strategy 3 (08:35 Macro Momentum)")
    ax_main.plot(df_s["entry_time"], comp_peak, color="#9467bd", linestyle="--", linewidth=1.0, alpha=0.8, label="Running High-Water Mark")

    ax_main.set_title("Backtest Results", fontsize=16, fontweight="normal", color="#000000", pad=12)
    ax_main.set_xlabel("Date", fontsize=11, color="#000000")
    ax_main.set_ylabel("Portfolio Value ($)", fontsize=11, color="#000000")
    ax_main.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_main.xaxis.set_major_locator(mdates.YearLocator())
    ax_main.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    leg = ax_main.legend(title="Strategy", loc="upper left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=9.5)
    leg.get_title().set_fontsize(10)
    leg.get_title().set_fontweight("bold")
    ax_main.tick_params(colors="#000000", labelsize=9.5)

    # ── PANEL 2: UNDERWATER DRAWDOWN ─────────────────────────────────────────
    ax_dd = fig.add_subplot(gs[1, :])
    ax_dd.set_facecolor("#FFFFFF")
    ax_dd.grid(True, color="#E5E5E5", linestyle="-", linewidth=0.8)
    for sp in ax_dd.spines.values():
        sp.set_color("#000000")
        sp.set_linewidth(1.0)

    dd_vals = comp_cum - comp_peak
    ax_dd.fill_between(df_s["entry_time"], dd_vals, 0, color="#d62728", alpha=0.25)
    ax_dd.plot(df_s["entry_time"], dd_vals, color="#d62728", linewidth=1.2, label=f"Drawdown (Max: -${abs(m_comp['max_dd']):,.2f})")

    ax_dd.set_title("Drawdown ($ Below Peak)", fontsize=13, fontweight="normal", color="#000000", pad=8)
    ax_dd.set_xlabel("Date", fontsize=10, color="#000000")
    ax_dd.set_ylabel("Drawdown ($)", fontsize=10, color="#000000")
    ax_dd.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_dd.xaxis.set_major_locator(mdates.YearLocator())
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax_dd.legend(loc="lower left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=9)
    ax_dd.tick_params(colors="#000000", labelsize=9)

    # ── PANEL 3A: TRADE P&L DISTRIBUTION (MATCHING SCREENSHOT THUMBNAIL) ─────
    ax_hist = fig.add_subplot(gs[2, 0])
    ax_hist.set_facecolor("#FFFFFF")
    ax_hist.grid(True, color="#E5E5E5", linestyle="-", linewidth=0.8)
    for sp in ax_hist.spines.values():
        sp.set_color("#000000")
        sp.set_linewidth(1.0)

    wins = df[df["pnl"] > 0]["pnl"]
    losses = df[df["pnl"] <= 0]["pnl"]
    ax_hist.hist(wins, bins=25, color="#1f77b4", edgecolor="#000000", alpha=0.85, label=f"Wins ({len(wins)} · avg +${wins.mean():.0f})")
    ax_hist.hist(losses, bins=25, color="#d62728", edgecolor="#000000", alpha=0.85, label=f"Losses ({len(losses)} · avg -${abs(losses.mean()):.0f})")
    ax_hist.axvline(m_comp["avg_trade"], color="#2ca02c", linestyle="--", linewidth=1.8, label=f"Expectancy: +${m_comp['avg_trade']:.2f}")

    ax_hist.set_title("Trade Outcome Distribution", fontsize=12, fontweight="normal", color="#000000", pad=8)
    ax_hist.set_xlabel("Net P&L per Trade ($)", fontsize=9.5, color="#000000")
    ax_hist.set_ylabel("Trade Count", fontsize=9.5, color="#000000")
    ax_hist.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_hist.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8.5)
    ax_hist.tick_params(colors="#000000", labelsize=8.5)

    # ── PANEL 3B: MONTHLY P&L MATRIX (CLASSIC ACADEMIC TABLE) ────────────────
    ax_mo = fig.add_subplot(gs[2, 1])
    ax_mo.set_facecolor("#FFFFFF")
    ax_mo.axis("off")
    for sp in ax_mo.spines.values():
        sp.set_color("#000000")
        sp.set_linewidth(1.0)

    ax_mo.text(0.02, 0.96, "Monthly Returns Matrix (USD Net)", fontsize=11, fontweight="bold", color="#000000")

    piv = df.pivot_table(index="year", columns="month", values="pnl", aggfunc="sum").fillna(0.0)
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

    # ── PANEL 4: FULL METRICS INVENTORY SPREADSHEET TABLE ────────────────────
    ax_tab = fig.add_subplot(gs[3, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.97, "Comprehensive Strategy Performance & Risk Metrics Inventory", fontsize=12, fontweight="bold", color="#000000")

    table_data = [
        ("Execution Window & Time", "All 3 Windows", "09:45 - 10:15 ET", "10:15 - 10:45 ET", "08:35 - 09:15 ET"),
        ("Traded Instruments", "MNQ, MES, MGC", "MNQ, MES", "MGC", "MNQ"),
        ("Total Executions / Trades", f"{m_comp['trades']}", f"{m_s1['trades']}", f"{m_s2['trades']}", f"{m_s3['trades']}"),
        ("Net Profit (USD)", f"${m_comp['net_profit']:,.2f}", f"${m_s1['net_profit']:,.2f}", f"${m_s2['net_profit']:,.2f}", f"${m_s3['net_profit']:,.2f}"),
        ("Gross Profit / Gross Loss", f"${m_comp['gross_profit']:,.0f} / -${m_comp['gross_loss']:,.0f}", f"${m_s1['gross_profit']:,.0f} / -${m_s1['gross_loss']:,.0f}", f"${m_s2['gross_profit']:,.0f} / -${m_s2['gross_loss']:,.0f}", f"${m_s3['gross_profit']:,.0f} / -${m_s3['gross_loss']:,.0f}"),
        ("Profit Factor", f"{m_comp['profit_factor']:.2f}", f"{m_s1['profit_factor']:.2f}", f"{m_s2['profit_factor']:.2f}", f"{m_s3['profit_factor']:.2f}"),
        ("Win Rate / Loss Rate", f"{m_comp['win_rate']:.1f}% / {m_comp['loss_rate']:.1f}%", f"{m_s1['win_rate']:.1f}% / {m_s1['loss_rate']:.1f}%", f"{m_s2['win_rate']:.1f}% / {m_s2['loss_rate']:.1f}%", f"{m_s3['win_rate']:.1f}% / {m_s3['loss_rate']:.1f}%"),
        ("Average Win / Average Loss", f"+${m_comp['avg_win']:.2f} / -${m_comp['avg_loss']:.2f}", f"+${m_s1['avg_win']:.2f} / -${m_s1['avg_loss']:.2f}", f"+${m_s2['avg_win']:.2f} / -${m_s2['avg_loss']:.2f}", f"+${m_s3['avg_win']:.2f} / -${m_s3['avg_loss']:.2f}"),
        ("Win / Loss Payoff Ratio", f"{m_comp['payoff_ratio']:.2f}x", f"{m_s1['payoff_ratio']:.2f}x", f"{m_s2['payoff_ratio']:.2f}x", f"{m_s3['payoff_ratio']:.2f}x"),
        ("Expectancy per Trade", f"+${m_comp['avg_trade']:.2f}", f"+${m_s1['avg_trade']:.2f}", f"+${m_s2['avg_trade']:.2f}", f"+${m_s3['avg_trade']:.2f}"),
        ("Median Trade P&L", f"+${m_comp['median_trade']:.2f}", f"+${m_s1['median_trade']:.2f}", f"+${m_s2['median_trade']:.2f}", f"+${m_s3['median_trade']:.2f}"),
        ("Maximum Drawdown ($)", f"-${abs(m_comp['max_dd']):,.2f}", f"-${abs(m_s1['max_dd']):,.2f}", f"-${abs(m_s2['max_dd']):,.2f}", f"-${abs(m_s3['max_dd']):,.2f}"),
        ("Maximum Drawdown (% on $25k)", f"{m_comp['max_dd_pct']:.2f}%", f"{m_s1['max_dd_pct']:.2f}%", f"{m_s2['max_dd_pct']:.2f}%", f"{m_s3['max_dd_pct']:.2f}%"),
        ("Max Drawdown Duration (Trades)", f"{m_comp['max_dd_dur_trades']} trades", f"{m_s1['max_dd_dur_trades']} trades", f"{m_s2['max_dd_dur_trades']} trades", f"{m_s3['max_dd_dur_trades']} trades"),
        ("Recovery Factor (Net / Max DD)", f"{m_comp['recovery_factor']:.2f}x", f"{m_s1['recovery_factor']:.2f}x", f"{m_s2['recovery_factor']:.2f}x", f"{m_s3['recovery_factor']:.2f}x"),
        ("Daily Sharpe Ratio (Ann. sqrt 252)", f"{m_comp['sharpe']:.2f}", f"{m_s1['sharpe']:.2f}", f"{m_s2['sharpe']:.2f}", f"{m_s3['sharpe']:.2f}"),
        ("Daily Sortino Ratio (Ann. sqrt 252)", f"{m_comp['sortino']:.2f}", f"{m_s1['sortino']:.2f}", f"{m_s2['sortino']:.2f}", f"{m_s3['sortino']:.2f}"),
        ("Calmar Ratio (Ann. Return / Max DD)", f"{m_comp['calmar']:.2f}", f"{m_s1['calmar']:.2f}", f"{m_s2['calmar']:.2f}", f"{m_s3['calmar']:.2f}"),
        ("Annual Net Profit ($/year)", f"${m_comp['annual_profit']:,.2f}", f"${m_s1['annual_profit']:,.2f}", f"${m_s2['annual_profit']:,.2f}", f"${m_s3['annual_profit']:,.2f}"),
        ("Annualized Return (CAGR on $25k)", f"{m_comp['cagr_pct']:.2f}%", f"{m_s1['cagr_pct']:.2f}%", f"{m_s2['cagr_pct']:.2f}%", f"{m_s3['cagr_pct']:.2f}%"),
        ("Daily Session Win Rate (%)", f"{m_comp['daily_wr']:.1f}% ({m_comp['profit_days']}/{m_comp['total_days']})", f"{m_s1['daily_wr']:.1f}%", f"{m_s2['daily_wr']:.1f}%", f"{m_s3['daily_wr']:.1f}%"),
        ("Worst Single Day P&L", f"-${abs(m_comp['worst_day']):,.2f}", f"-${abs(m_s1['worst_day']):,.2f}", f"-${abs(m_s2['worst_day']):,.2f}", f"-${abs(m_s3['worst_day']):,.2f}"),
        ("Daily Value at Risk (VaR 95%)", f"-${abs(m_comp['var_95_daily']):.2f}", f"-${abs(m_s1['var_95_daily']):.2f}", f"-${abs(m_s2['var_95_daily']):.2f}", f"-${abs(m_s3['var_95_daily']):.2f}"),
        ("Daily Expected Shortfall (CVaR 95%)", f"-${abs(m_comp['cvar_95_daily']):.2f}", f"-${abs(m_s1['cvar_95_daily']):.2f}", f"-${abs(m_s2['cvar_95_daily']):.2f}", f"-${abs(m_s3['cvar_95_daily']):.2f}"),
        ("Largest Single Win", f"+${m_comp['largest_win']:.2f}", f"+${m_s1['largest_win']:.2f}", f"+${m_s2['largest_win']:.2f}", f"+${m_s3['largest_win']:.2f}"),
        ("Largest Single Loss", f"-${abs(m_comp['largest_loss']):.2f}", f"-${abs(m_s1['largest_loss']):.2f}", f"-${abs(m_s2['largest_loss']):.2f}", f"-${abs(m_s3['largest_loss']):.2f}"),
        ("Consecutive Wins / Losses (Max)", f"{m_comp['max_consec_wins']} W / {m_comp['max_consec_losses']} L", f"{m_s1['max_consec_wins']} W / {m_s1['max_consec_losses']} L", f"{m_s2['max_consec_wins']} W / {m_s2['max_consec_losses']} L", f"{m_s3['max_consec_wins']} W / {m_s3['max_consec_losses']} L"),
        ("Average Holding Time", f"{m_comp['avg_hold_min']:.1f} mins", f"{m_s1['avg_hold_min']:.1f} mins", f"{m_s2['avg_hold_min']:.1f} mins", f"{m_s3['avg_hold_min']:.1f} mins"),
        ("Long Performance", f"{m_comp['long_trades']}t · ${m_comp['long_net']:,.0f} ({m_comp['long_wr']:.1f}%)", f"{m_s1['long_trades']}t · ${m_s1['long_net']:,.0f}", f"{m_s2['long_trades']}t · ${m_s2['long_net']:,.0f}", f"{m_s3['long_trades']}t · ${m_s3['long_net']:,.0f}"),
        ("Short Performance", f"{m_comp['short_trades']}t · ${m_comp['short_net']:,.0f} ({m_comp['short_wr']:.1f}%)", f"{m_s1['short_trades']}t · ${m_s1['short_net']:,.0f}", f"{m_s2['short_trades']}t · ${m_s2['short_net']:,.0f}", f"{m_s3['short_trades']}t · ${m_s3['short_net']:,.0f}"),
    ]

    th_headers = ["Metric Specification", "Unified Composite", "Strategy 1 (09:45 VA)", "Strategy 2 (10:15 Gold)", "Strategy 3 (08:35 Macro)"]
    t_x = [0.02, 0.40, 0.58, 0.73, 0.88]
    for i, h in enumerate(th_headers):
        ax_tab.text(t_x[i], 0.91, h, fontsize=8.5, fontweight="bold", color="#000000", ha="left" if i == 0 else "right")

    y_t = 0.87
    for row_idx, r in enumerate(table_data):
        # Draw subtle horizontal divider
        ax_tab.axhline(y_t + 0.005, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        is_bold = row_idx in [2, 3, 5, 6, 11, 15]
        for c_idx, val in enumerate(r):
            f_w = "bold" if is_bold else "normal"
            c_txt = "#1f77b4" if (c_idx == 1 and is_bold) else "#000000"
            ax_tab.text(t_x[c_idx], y_t - 0.005, val, fontsize=7.8, fontweight=f_w, color=c_txt, ha="left" if c_idx == 0 else "right")
        y_t -= 0.0275

    # ── PANEL 5A: SLIPPAGE SENSITIVITY BREAKEVEN CLIFF ───────────────────────
    ax_slip = fig.add_subplot(gs[4, 0])
    ax_slip.set_facecolor("#FFFFFF")
    ax_slip.grid(True, color="#E5E5E5", linestyle="-", linewidth=0.8)
    for sp in ax_slip.spines.values():
        sp.set_color("#000000")
        sp.set_linewidth(1.0)

    extra_ticks = [0, 1, 2, 3, 4, 6, 8]
    pfs = [1.56, 1.46, 1.37, 1.29, 1.21, 1.06, 0.93]
    net_pnls = [14916, 12763, 10610, 8457, 6304, 1998, -2308]

    ax_slip.plot(extra_ticks, pfs, marker="o", color="#1f77b4", linewidth=1.8, label="Profit Factor")
    ax_slip.axhline(1.0, color="#d62728", linestyle="--", linewidth=1.2, label="Breakeven Cliff (PF=1.00)")
    ax_slip.set_title("Slippage Sensitivity & Friction Breakeven Cliff", fontsize=11, fontweight="normal", color="#000000", pad=8)
    ax_slip.set_xlabel("Extra Adverse Ticks per Leg (Entry + Exit)", fontsize=9, color="#000000")
    ax_slip.set_ylabel("Profit Factor", fontsize=9, color="#000000")
    ax_slip.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)
    ax_slip.tick_params(colors="#000000", labelsize=8.5)

    # ── PANEL 5B: MARKOV VOLATILITY REGIME CONTRIBUTION ──────────────────────
    ax_mkv = fig.add_subplot(gs[4, 1])
    ax_mkv.set_facecolor("#FFFFFF")
    ax_mkv.grid(True, color="#E5E5E5", linestyle="-", linewidth=0.8)
    for sp in ax_mkv.spines.values():
        sp.set_color("#000000")
        sp.set_linewidth(1.0)

    reg_pnl = df.groupby("markov_state_label")["pnl"].sum().reindex(["low_vol", "mid_vol", "high_vol"])
    reg_wr = df.groupby("markov_state_label")["pnl"].agg(lambda x: (x > 0).mean() * 100).reindex(["low_vol", "mid_vol", "high_vol"])
    b_mkv = ax_mkv.bar(["Low-Vol (1.25x)", "Mid-Vol (1.00x)", "High-Vol (0.50x S3)"], reg_pnl, color=["#2ca02c", "#1f77b4", "#ff7f0e"], edgecolor="#000000", width=0.5)
    for idx, b in enumerate(b_mkv):
        h = b.get_height()
        ax_mkv.annotate(f"${h:,.0f}\n({reg_wr.iloc[idx]:.1f}% WR)", xy=(b.get_x() + b.get_width() / 2, h), xytext=(0, 3),
                        textcoords="offset points", ha="center", va="bottom", color="#000000", fontweight="bold", fontsize=8)

    ax_mkv.set_title("Markov Volatility Regime Allocation (Option 2 Sizing)", fontsize=11, fontweight="normal", color="#000000", pad=8)
    ax_mkv.set_ylabel("Net Profit ($)", fontsize=9, color="#000000")
    ax_mkv.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_mkv.set_ylim(0, max(reg_pnl) * 1.25)
    ax_mkv.tick_params(colors="#000000", labelsize=8.5)

    out_poster = OUT_DIR / "strategy_performance_quant_report.png"
    plt.savefig(out_poster, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_poster


def generate_screenshot_style_html_dashboard(
    df: pd.DataFrame,
    m_comp: dict,
    m_s1: dict,
    m_s2: dict,
    m_s3: dict,
) -> Path:
    html_path = OUT_DIR / "dashboard.html"

    df_sorted = df.sort_values("entry_time").reset_index(drop=True)
    dates = df_sorted["entry_time"].dt.strftime("%Y-%m-%d").tolist()

    # Base $25,000 Portfolio Values (exactly like screenshot)
    cum_comp = (df_sorted["pnl"].cumsum() + 25_000.0).round(2).tolist()
    peak_comp = np.maximum.accumulate(cum_comp).round(2).tolist()
    dd_comp = (np.array(cum_comp) - np.array(peak_comp)).round(2).tolist()

    cum_s1 = (df_sorted.apply(lambda r: r["pnl"] if r["window"] == 1 else 0.0, axis=1).cumsum() + 25_000.0).round(2).tolist()
    peak_s1 = np.maximum.accumulate(cum_s1).round(2).tolist()
    dd_s1 = (np.array(cum_s1) - np.array(peak_s1)).round(2).tolist()

    cum_s2 = (df_sorted.apply(lambda r: r["pnl"] if r["window"] == 2 else 0.0, axis=1).cumsum() + 25_000.0).round(2).tolist()
    peak_s2 = np.maximum.accumulate(cum_s2).round(2).tolist()
    dd_s2 = (np.array(cum_s2) - np.array(peak_s2)).round(2).tolist()

    cum_s3 = (df_sorted.apply(lambda r: r["pnl"] if r["window"] == 3 else 0.0, axis=1).cumsum() + 25_000.0).round(2).tolist()
    peak_s3 = np.maximum.accumulate(cum_s3).round(2).tolist()
    dd_s3 = (np.array(cum_s3) - np.array(peak_s3)).round(2).tolist()

    monthly_comp = compute_monthly_matrix(df_sorted)
    monthly_s1 = compute_monthly_matrix(df_sorted[df_sorted["window"] == 1])
    monthly_s2 = compute_monthly_matrix(df_sorted[df_sorted["window"] == 2])
    monthly_s3 = compute_monthly_matrix(df_sorted[df_sorted["window"] == 3])

    blotter = []
    for idx, r in df_sorted.iterrows():
        blotter.append({
            "id": idx + 1,
            "date": r["date_str"],
            "time": r["entry_time"].strftime("%H:%M"),
            "strategy": "S1: VA Breakout" if r["window"] == 1 else ("S2: Gold Fix" if r["window"] == 2 else "S3: Macro Mom"),
            "symbol": r["micro"],
            "direction": r["direction"].upper(),
            "contracts": int(r["contracts"]),
            "regime": r["markov_state_label"],
            "mult": f"{r['markov_sizing_mult']:.2f}x",
            "pnl": round(float(r["pnl"]), 2),
            "portfolio_val": round(cum_comp[idx], 2),
            "hold": f"{r['hold_minutes']:.0f}m",
        })

    payload = {
        "dates": dates,
        "cum_comp": cum_comp,
        "peak_comp": peak_comp,
        "dd_comp": dd_comp,
        "cum_s1": cum_s1,
        "dd_s1": dd_s1,
        "cum_s2": cum_s2,
        "dd_s2": dd_s2,
        "cum_s3": cum_s3,
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

    html_code = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Backtest Results • Unified 3-Strategy Portfolio</title>
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
        
        /* Tab Switcher in classic clean Python style */
        .tabs-bar {{
            display: flex;
            gap: 4px;
            border-bottom: 1px solid #000000;
            margin-bottom: 16px;
        }}
        .tab-btn {{
            padding: 8px 16px;
            background: #F2F2F2;
            border: 1px solid #CCCCCC;
            border-bottom: none;
            cursor: pointer;
            font-size: 12px;
            font-weight: bold;
            color: #333333;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }}
        .tab-btn.active {{
            background: #FFFFFF;
            border-color: #000000;
            border-bottom: 1px solid #FFFFFF;
            color: #000000;
            margin-bottom: -1px;
        }}
        
        /* Chart container styled exactly like screenshot */
        .chart-box {{
            border: 1px solid #000000;
            background: #FFFFFF;
            height: 480px;
            width: 100%;
            margin-bottom: 20px;
        }}
        
        /* Tables in classic academic white style */
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
        .color-pos {{ color: #2ca02c; font-weight: bold; }}
        .color-neg {{ color: #d62728; font-weight: bold; }}
        .color-blue {{ color: #1f77b4; font-weight: bold; }}
        
        /* Search box */
        .search-input {{
            padding: 5px 8px;
            border: 1px solid #000000;
            font-size: 12px;
            width: 250px;
        }}
    </style>
</head>
<body>
<div class="container">

    <!-- Top Navigation Header -->
    <div class="top-bar">
        <div>
            <h1>Backtest Results • Unified Quantitative Portfolio</h1>
            <div style="font-size: 11px; color: #555555; margin-top: 2px;">
                Strategy 1 (09:45 VA Breakout) + Strategy 2 (10:15 Gold Fix) + Strategy 3 (08:35 Macro Momentum) · 2021-01-07 to 2026-10-30
            </div>
        </div>
        <div class="nav-links">
            <span style="font-weight: bold; color: #000000;">Backtest Results</span>
            <a href="../prop_firm_dashboard/dashboard.html">LucidFlex 25K Prop Mode &rarr;</a>
            <a href="../forward_test/demo_parity_dashboard.html">Live Demo Parity Journal &rarr;</a>
        </div>
    </div>

    <!-- Strategy Tabs Switcher -->
    <div class="tabs-bar">
        <button class="tab-btn active" id="tab-comp" onclick="switchStrategy('comp')">Unified Composite Ensemble</button>
        <button class="tab-btn" id="tab-s1" onclick="switchStrategy('s1')">Strategy 1: Morning VA Breakout (09:45)</button>
        <button class="tab-btn" id="tab-s2" onclick="switchStrategy('s2')">Strategy 2: Gold London Fix (10:15)</button>
        <button class="tab-btn" id="tab-s3" onclick="switchStrategy('s3')">Strategy 3: Macro Momentum (08:35)</button>
        <button class="tab-btn" id="tab-overlay" onclick="switchStrategy('overlay')">Multi-Strategy Comparison Overlay</button>
    </div>

    <!-- Primary Chart: Styled exactly like user's reference screenshot -->
    <div class="chart-box" id="chartMain"></div>

    <!-- Section 1: Complete Quantitative Metrics Inventory Table -->
    <div class="section-header">Comprehensive Strategy Performance & Risk Metrics Inventory</div>
    <table class="academic-table mono">
        <thead>
            <tr>
                <th style="width: 32%;">Metric Specification</th>
                <th style="width: 17%;">Unified Composite</th>
                <th style="width: 17%;">Strategy 1 (09:45 VA)</th>
                <th style="width: 17%;">Strategy 2 (10:15 Gold)</th>
                <th style="width: 17%;">Strategy 3 (08:35 Macro)</th>
            </tr>
        </thead>
        <tbody>
            <tr><td>Execution Window & Time</td><td>All 3 Windows</td><td>09:45 - 10:15 ET</td><td>10:15 - 10:45 ET</td><td>08:35 - 09:15 ET</td></tr>
            <tr><td>Traded Instruments</td><td>MNQ, MES, MGC</td><td>MNQ, MES</td><td>MGC</td><td>MNQ</td></tr>
            <tr><td><strong>Total Executions / Trades</strong></td><td><strong>{m_comp['trades']}</strong></td><td><strong>{m_s1['trades']}</strong></td><td><strong>{m_s2['trades']}</strong></td><td><strong>{m_s3['trades']}</strong></td></tr>
            <tr><td><strong>Total Net Profit ($)</strong></td><td class="color-blue"><strong>${m_comp['net_profit']:,.2f}</strong></td><td class="color-pos"><strong>${m_s1['net_profit']:,.2f}</strong></td><td class="color-pos"><strong>${m_s2['net_profit']:,.2f}</strong></td><td class="color-pos"><strong>${m_s3['net_profit']:,.2f}</strong></td></tr>
            <tr><td>Gross Profit / Gross Loss</td><td>${m_comp['gross_profit']:,.2f} / -${m_comp['gross_loss']:,.2f}</td><td>${m_s1['gross_profit']:,.2f} / -${m_s1['gross_loss']:,.2f}</td><td>${m_s2['gross_profit']:,.2f} / -${m_s2['gross_loss']:,.2f}</td><td>${m_s3['gross_profit']:,.2f} / -${m_s3['gross_loss']:,.2f}</td></tr>
            <tr><td><strong>Profit Factor</strong></td><td class="color-pos"><strong>{m_comp['profit_factor']:.2f}</strong></td><td class="color-pos"><strong>{m_s1['profit_factor']:.2f}</strong></td><td class="color-pos"><strong>{m_s2['profit_factor']:.2f}</strong></td><td class="color-pos"><strong>{m_s3['profit_factor']:.2f}</strong></td></tr>
            <tr><td><strong>Win Rate / Loss Rate</strong></td><td class="color-pos"><strong>{m_comp['win_rate']:.1f}%</strong> / {m_comp['loss_rate']:.1f}%</td><td class="color-pos"><strong>{m_s1['win_rate']:.1f}%</strong></td><td class="color-pos"><strong>{m_s2['win_rate']:.1f}%</strong></td><td><strong>{m_s3['win_rate']:.1f}%</strong></td></tr>
            <tr><td>Average Win / Average Loss</td><td>+${m_comp['avg_win']:.2f} / -${m_comp['avg_loss']:.2f}</td><td>+${m_s1['avg_win']:.2f} / -${m_s1['avg_loss']:.2f}</td><td>+${m_s2['avg_win']:.2f} / -${m_s2['avg_loss']:.2f}</td><td>+${m_s3['avg_win']:.2f} / -${m_s3['avg_loss']:.2f}</td></tr>
            <tr><td>Win / Loss Payoff Ratio</td><td><strong>{m_comp['payoff_ratio']:.2f}x</strong></td><td>{m_s1['payoff_ratio']:.2f}x</td><td>{m_s2['payoff_ratio']:.2f}x</td><td class="color-pos"><strong>{m_s3['payoff_ratio']:.2f}x</strong></td></tr>
            <tr><td>Expectancy per Trade</td><td class="color-pos">+${m_comp['avg_trade']:.2f}</td><td>+${m_s1['avg_trade']:.2f}</td><td>+${m_s2['avg_trade']:.2f}</td><td>+${m_s3['avg_trade']:.2f}</td></tr>
            <tr><td>Median Trade P&L</td><td>+${m_comp['median_trade']:.2f}</td><td>+${m_s1['median_trade']:.2f}</td><td>+${m_s2['median_trade']:.2f}</td><td>+${m_s3['median_trade']:.2f}</td></tr>
            <tr><td><strong>Maximum Drawdown ($)</strong></td><td class="color-neg"><strong>-${abs(m_comp['max_dd']):,.2f}</strong></td><td class="color-neg">-${abs(m_s1['max_dd']):,.2f}</td><td class="color-pos">-${abs(m_s2['max_dd']):,.2f}</td><td class="color-neg">-${abs(m_s3['max_dd']):,.2f}</td></tr>
            <tr><td>Maximum Drawdown (% on $25k base)</td><td class="color-neg">{m_comp['max_dd_pct']:.2f}%</td><td>{m_s1['max_dd_pct']:.2f}%</td><td>{m_s2['max_dd_pct']:.2f}%</td><td>{m_s3['max_dd_pct']:.2f}%</td></tr>
            <tr><td>Max Drawdown Duration (Trades)</td><td>{m_comp['max_dd_dur_trades']} trades</td><td>{m_s1['max_dd_dur_trades']} trades</td><td>{m_s2['max_dd_dur_trades']} trades</td><td>{m_s3['max_dd_dur_trades']} trades</td></tr>
            <tr><td>Recovery Factor (Net / Max DD)</td><td><strong>{m_comp['recovery_factor']:.2f}x</strong></td><td>{m_s1['recovery_factor']:.2f}x</td><td>{m_s2['recovery_factor']:.2f}x</td><td>{m_s3['recovery_factor']:.2f}x</td></tr>
            <tr><td><strong>Daily Sharpe Ratio (Annualized)</strong></td><td class="color-blue"><strong>{m_comp['sharpe']:.2f}</strong></td><td class="color-blue"><strong>{m_s1['sharpe']:.2f}</strong></td><td class="color-blue"><strong>{m_s2['sharpe']:.2f}</strong></td><td class="color-blue"><strong>{m_s3['sharpe']:.2f}</strong></td></tr>
            <tr><td>Daily Sortino Ratio (Annualized)</td><td class="color-blue"><strong>{m_comp['sortino']:.2f}</strong></td><td class="color-blue"><strong>{m_s1['sortino']:.2f}</strong></td><td class="color-blue"><strong>{m_s2['sortino']:.2f}</strong></td><td class="color-blue"><strong>{m_s3['sortino']:.2f}</strong></td></tr>
            <tr><td>Calmar Ratio (Ann. Return / Max DD)</td><td>{m_comp['calmar']:.2f}</td><td>{m_s1['calmar']:.2f}</td><td>{m_s2['calmar']:.2f}</td><td>{m_s3['calmar']:.2f}</td></tr>
            <tr><td>Annual Net Profit ($/year)</td><td>${m_comp['annual_profit']:,.2f}</td><td>${m_s1['annual_profit']:,.2f}</td><td>${m_s2['annual_profit']:,.2f}</td><td>${m_s3['annual_profit']:,.2f}</td></tr>
            <tr><td>Annualized Return (CAGR on $25k)</td><td>{m_comp['cagr_pct']:.2f}%</td><td>{m_s1['cagr_pct']:.2f}%</td><td>{m_s2['cagr_pct']:.2f}%</td><td>{m_s3['cagr_pct']:.2f}%</td></tr>
            <tr><td>Daily Win Rate (% Sessions)</td><td>{m_comp['daily_wr']:.1f}% ({m_comp['profit_days']}/{m_comp['total_days']})</td><td>{m_s1['daily_wr']:.1f}%</td><td>{m_s2['daily_wr']:.1f}%</td><td>{m_s3['daily_wr']:.1f}%</td></tr>
            <tr><td>Worst Single Day P&L</td><td class="color-neg">-${abs(m_comp['worst_day']):,.2f}</td><td>-${abs(m_s1['worst_day']):,.2f}</td><td>-${abs(m_s2['worst_day']):,.2f}</td><td>-${abs(m_s3['worst_day']):,.2f}</td></tr>
            <tr><td>Daily Value at Risk (VaR 95%)</td><td class="color-neg">-${abs(m_comp['var_95_daily']):.2f}</td><td>-${abs(m_s1['var_95_daily']):.2f}</td><td>-${abs(m_s2['var_95_daily']):.2f}</td><td>-${abs(m_s3['var_95_daily']):.2f}</td></tr>
            <tr><td>Daily Expected Shortfall (CVaR 95%)</td><td class="color-neg">-${abs(m_comp['cvar_95_daily']):.2f}</td><td>-${abs(m_s1['cvar_95_daily']):.2f}</td><td>-${abs(m_s2['cvar_95_daily']):.2f}</td><td>-${abs(m_s3['cvar_95_daily']):.2f}</td></tr>
            <tr><td>Largest Single Win</td><td class="color-pos">+${m_comp['largest_win']:.2f}</td><td>+${m_s1['largest_win']:.2f}</td><td>+${m_s2['largest_win']:.2f}</td><td>+${m_s3['largest_win']:.2f}</td></tr>
            <tr><td>Largest Single Loss</td><td class="color-neg">-${abs(m_comp['largest_loss']):.2f}</td><td>-${abs(m_s1['largest_loss']):.2f}</td><td>-${abs(m_s2['largest_loss']):.2f}</td><td>-${abs(m_s3['largest_loss']):.2f}</td></tr>
            <tr><td>Consecutive Wins / Losses (Max)</td><td>{m_comp['max_consec_wins']} W / {m_comp['max_consec_losses']} L</td><td>{m_s1['max_consec_wins']} W / {m_s1['max_consec_losses']} L</td><td>{m_s2['max_consec_wins']} W / {m_s2['max_consec_losses']} L</td><td>{m_s3['max_consec_wins']} W / {m_s3['max_consec_losses']} L</td></tr>
            <tr><td>Average Holding Time</td><td>{m_comp['avg_hold_min']:.1f} mins</td><td>{m_s1['avg_hold_min']:.1f} mins</td><td>{m_s2['avg_hold_min']:.1f} mins</td><td>{m_s3['avg_hold_min']:.1f} mins</td></tr>
            <tr><td>Long Side Performance</td><td>{m_comp['long_trades']}t · ${m_comp['long_net']:,.2f} ({m_comp['long_wr']:.1f}% WR)</td><td>{m_s1['long_trades']}t · ${m_s1['long_net']:,.2f}</td><td>{m_s2['long_trades']}t · ${m_s2['long_net']:,.2f}</td><td>{m_s3['long_trades']}t · ${m_s3['long_net']:,.2f}</td></tr>
            <tr><td>Short Side Performance</td><td>{m_comp['short_trades']}t · ${m_comp['short_net']:,.2f} ({m_comp['short_wr']:.1f}% WR)</td><td>{m_s1['short_trades']}t · ${m_s1['short_net']:,.2f}</td><td>{m_s2['short_trades']}t · ${m_s2['short_net']:,.2f}</td><td>{m_s3['short_trades']}t · ${m_s3['short_net']:,.2f}</td></tr>
        </tbody>
    </table>

    <!-- Section 2: Monthly Net P&L Matrix Table -->
    <div class="section-header">Monthly Net Returns Matrix (USD)</div>
    <table class="academic-table mono" id="monthlyTable">
        <thead>
            <tr>
                <th>Year</th>
                <th>Jan</th><th>Feb</th><th>Mar</th><th>Apr</th><th>May</th><th>Jun</th>
                <th>Jul</th><th>Aug</th><th>Sep</th><th>Oct</th><th>Nov</th><th>Dec</th>
                <th>YTD Net</th><th>Trades</th><th>Win Rate</th>
            </tr>
        </thead>
        <tbody id="monthlyBody">
        </tbody>
    </table>

    <!-- Section 3: Trade Blotter Execution Audit -->
    <div style="display: flex; justify-content: space-between; align-items: baseline; margin: 16px 0 8px 0; border-bottom: 1px solid #000000; padding-bottom: 4px;">
        <span style="font-size: 14px; font-weight: bold; color: #000000;">Trade Blotter (543 Executions Audit)</span>
        <input type="text" id="blotterFilter" class="search-input" placeholder="Search date, symbol, strategy..." onkeyup="filterTrades()">
    </div>
    <div style="max-height: 380px; overflow-y: auto; border: 1px solid #000000; margin-bottom: 24px;">
        <table class="academic-table mono" id="blotterTable" style="margin-bottom: 0;">
            <thead style="position: sticky; top: 0; z-index: 10;">
                <tr>
                    <th>#</th>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Strategy</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Qty</th>
                    <th>Regime</th>
                    <th>Mult</th>
                    <th>Trade P&L</th>
                    <th>Portfolio Val</th>
                    <th>Hold</th>
                </tr>
            </thead>
            <tbody id="blotterBody">
            </tbody>
        </table>
    </div>

</div>

<!-- Client-side Interactive Plot Script -->
<script>
    const appData = {json_payload};
    let currentTab = 'comp';
    let eChart = null;

    function initEChart() {{
        const dom = document.getElementById('chartMain');
        eChart = echarts.init(dom, null, {{ renderer: 'canvas' }});
        updateChart();
        window.addEventListener('resize', () => eChart.resize());
    }}

    function updateChart() {{
        let series = [];
        let legendData = [];

        if (currentTab === 'comp') {{
            legendData = ['Unified Composite', 'High-Water Mark', 'Drawdown'];
            series = [
                {{
                    name: 'Unified Composite',
                    type: 'line',
                    data: appData.cum_comp,
                    itemStyle: {{ color: '#1f77b4' }},
                    lineStyle: {{ width: 2.0 }},
                    showSymbol: false,
                    xAxisIndex: 0,
                    yAxisIndex: 0
                }},
                {{
                    name: 'High-Water Mark',
                    type: 'line',
                    data: appData.peak_comp,
                    itemStyle: {{ color: '#9467bd' }},
                    lineStyle: {{ width: 1.0, type: 'dashed' }},
                    showSymbol: false,
                    xAxisIndex: 0,
                    yAxisIndex: 0
                }},
                {{
                    name: 'Drawdown',
                    type: 'line',
                    data: appData.dd_comp,
                    itemStyle: {{ color: '#d62728' }},
                    areaStyle: {{ color: 'rgba(214, 39, 40, 0.2)' }},
                    showSymbol: false,
                    xAxisIndex: 1,
                    yAxisIndex: 1
                }}
            ];
        }} else if (currentTab === 's1') {{
            legendData = ['Strategy 1 (09:45 VA Breakout)', 'Drawdown'];
            series = [
                {{
                    name: 'Strategy 1 (09:45 VA Breakout)',
                    type: 'line',
                    data: appData.cum_s1,
                    itemStyle: {{ color: '#ff7f0e' }},
                    lineStyle: {{ width: 2.0 }},
                    showSymbol: false,
                    xAxisIndex: 0,
                    yAxisIndex: 0
                }},
                {{
                    name: 'Drawdown',
                    type: 'line',
                    data: appData.dd_s1,
                    itemStyle: {{ color: '#d62728' }},
                    areaStyle: {{ color: 'rgba(214, 39, 40, 0.2)' }},
                    showSymbol: false,
                    xAxisIndex: 1,
                    yAxisIndex: 1
                }}
            ];
        }} else if (currentTab === 's2') {{
            legendData = ['Strategy 2 (10:15 Gold Fix)', 'Drawdown'];
            series = [
                {{
                    name: 'Strategy 2 (10:15 Gold Fix)',
                    type: 'line',
                    data: appData.cum_s2,
                    itemStyle: {{ color: '#2ca02c' }},
                    lineStyle: {{ width: 2.0 }},
                    showSymbol: false,
                    xAxisIndex: 0,
                    yAxisIndex: 0
                }},
                {{
                    name: 'Drawdown',
                    type: 'line',
                    data: appData.dd_s2,
                    itemStyle: {{ color: '#d62728' }},
                    areaStyle: {{ color: 'rgba(214, 39, 40, 0.2)' }},
                    showSymbol: false,
                    xAxisIndex: 1,
                    yAxisIndex: 1
                }}
            ];
        }} else if (currentTab === 's3') {{
            legendData = ['Strategy 3 (08:35 Macro Momentum)', 'Drawdown'];
            series = [
                {{
                    name: 'Strategy 3 (08:35 Macro Momentum)',
                    type: 'line',
                    data: appData.cum_s3,
                    itemStyle: {{ color: '#d62728' }},
                    lineStyle: {{ width: 2.0 }},
                    showSymbol: false,
                    xAxisIndex: 0,
                    yAxisIndex: 0
                }},
                {{
                    name: 'Drawdown',
                    type: 'line',
                    data: appData.dd_s3,
                    itemStyle: {{ color: '#d62728' }},
                    areaStyle: {{ color: 'rgba(214, 39, 40, 0.2)' }},
                    showSymbol: false,
                    xAxisIndex: 1,
                    yAxisIndex: 1
                }}
            ];
        }} else if (currentTab === 'overlay') {{
            legendData = ['Unified Composite', 'Strategy 1', 'Strategy 2', 'Strategy 3'];
            series = [
                {{ name: 'Unified Composite', type: 'line', data: appData.cum_comp, itemStyle: {{ color: '#1f77b4' }}, lineStyle: {{ width: 2.2 }}, showSymbol: false, xAxisIndex: 0, yAxisIndex: 0 }},
                {{ name: 'Strategy 1', type: 'line', data: appData.cum_s1, itemStyle: {{ color: '#ff7f0e' }}, lineStyle: {{ width: 1.5 }}, showSymbol: false, xAxisIndex: 0, yAxisIndex: 0 }},
                {{ name: 'Strategy 2', type: 'line', data: appData.cum_s2, itemStyle: {{ color: '#2ca02c' }}, lineStyle: {{ width: 1.5 }}, showSymbol: false, xAxisIndex: 0, yAxisIndex: 0 }},
                {{ name: 'Strategy 3', type: 'line', data: appData.cum_s3, itemStyle: {{ color: '#d62728' }}, lineStyle: {{ width: 1.5 }}, showSymbol: false, xAxisIndex: 0, yAxisIndex: 0 }},
                {{ name: 'Drawdown', type: 'line', data: appData.dd_comp, itemStyle: {{ color: '#d62728' }}, areaStyle: {{ color: 'rgba(214, 39, 40, 0.2)' }}, showSymbol: false, xAxisIndex: 1, yAxisIndex: 1 }}
            ];
        }}

        const option = {{
            backgroundColor: '#FFFFFF',
            animation: false,
            title: {{
                text: 'Backtest Results',
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
                textStyle: {{ color: '#000000', fontSize: 11, fontFamily: 'monospace' }},
                axisPointer: {{
                    type: 'cross',
                    lineStyle: {{ color: '#555555', type: 'dashed' }}
                }},
                formatter: function(params) {{
                    if (!params || params.length === 0) return '';
                    let dateStr = params[0].axisValue;
                    let s = '<strong>Date: ' + dateStr + '</strong><br/>';
                    params.forEach(p => {{
                        let val = typeof p.value === 'number' ? '$' + p.value.toLocaleString(undefined, {{minimumFractionDigits: 2, maximumFractionDigits: 2}}) : p.value;
                        s += p.marker + ' ' + p.seriesName + ': <strong>' + val + '</strong><br/>';
                    }});
                    return s;
                }}
            }},
            legend: {{
                title: {{ text: 'Strategy', textStyle: {{ fontSize: 10, fontWeight: 'bold' }} }},
                data: legendData,
                right: '40px',
                top: '35px',
                borderWidth: 1,
                borderColor: '#CCCCCC',
                backgroundColor: '#FFFFFF',
                padding: 6,
                textStyle: {{ fontSize: 10, color: '#000000' }}
            }},
            grid: [
                {{ left: '65px', right: '40px', top: '75px', height: '56%' }},
                {{ left: '65px', right: '40px', top: '73%', height: '18%' }}
            ],
            xAxis: [
                {{
                    type: 'category',
                    data: appData.dates,
                    gridIndex: 0,
                    axisLine: {{ lineStyle: {{ color: '#000000', width: 1 }} }},
                    axisTick: {{ lineStyle: {{ color: '#000000' }} }},
                    axisLabel: {{ color: '#000000', fontSize: 10 }},
                    splitLine: {{ show: true, lineStyle: {{ color: '#E5E5E5' }} }}
                }},
                {{
                    type: 'category',
                    data: appData.dates,
                    gridIndex: 1,
                    axisLine: {{ lineStyle: {{ color: '#000000', width: 1 }} }},
                    axisTick: {{ show: false }},
                    axisLabel: {{ show: false }},
                    splitLine: {{ show: true, lineStyle: {{ color: '#E5E5E5' }} }}
                }}
            ],
            yAxis: [
                {{
                    type: 'value',
                    name: 'Portfolio Value ($)',
                    nameLocation: 'middle',
                    nameGap: 50,
                    gridIndex: 0,
                    axisLine: {{ show: true, lineStyle: {{ color: '#000000', width: 1 }} }},
                    axisTick: {{ lineStyle: {{ color: '#000000' }} }},
                    axisLabel: {{
                        color: '#000000',
                        fontSize: 10,
                        formatter: v => '$' + v.toLocaleString()
                    }},
                    splitLine: {{ lineStyle: {{ color: '#E5E5E5' }} }}
                }},
                {{
                    type: 'value',
                    name: 'Drawdown ($)',
                    nameLocation: 'middle',
                    nameGap: 50,
                    gridIndex: 1,
                    axisLine: {{ show: true, lineStyle: {{ color: '#000000', width: 1 }} }},
                    axisTick: {{ lineStyle: {{ color: '#000000' }} }},
                    axisLabel: {{
                        color: '#d62728',
                        fontSize: 9,
                        formatter: v => '$' + v
                    }},
                    splitLine: {{ lineStyle: {{ color: '#E5E5E5' }} }}
                }}
            ],
            series: series
        }};

        eChart.setOption(option, true);
    }}

    function switchStrategy(target) {{
        currentTab = target;
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        const btn = document.getElementById('tab-' + target);
        if (btn) btn.classList.add('active');

        updateChart();
        renderMonthly();
    }}

    function renderMonthly() {{
        const key = currentTab === 'overlay' ? 'comp' : currentTab;
        const rows = appData.monthly[key] || appData.monthly['comp'];
        const tbody = document.getElementById('monthlyBody');
        tbody.innerHTML = '';

        rows.forEach(r => {{
            let tr = document.createElement('tr');
            let mCells = r.months.map(m => {{
                if (m === 0) return '<td style="color:#888888;">-</td>';
                let cls = m > 0 ? 'color-pos' : 'color-neg';
                let txt = (m > 0 ? '+' : '') + Math.round(m);
                return '<td class="' + cls + '">' + txt + '</td>';
            }}).join('');

            let ytdCls = r.ytd > 0 ? 'color-pos' : (r.ytd < 0 ? 'color-neg' : '');
            tr.innerHTML = '<td><strong>' + r.year + '</strong></td>' +
                           mCells +
                           '<td class="' + ytdCls + '" style="font-weight:bold;">$' + Math.round(r.ytd).toLocaleString() + '</td>' +
                           '<td>' + r.trades + '</td>' +
                           '<td><strong>' + r.win_rate.toFixed(1) + '%</strong></td>';
            tbody.appendChild(tr);
        }});
    }}

    function renderBlotter(trades) {{
        const tbody = document.getElementById('blotterBody');
        tbody.innerHTML = '';
        trades.slice(0, 100).forEach(t => {{
            let tr = document.createElement('tr');
            let pnlCls = t.pnl > 0 ? 'color-pos' : 'color-neg';
            let pnlTxt = (t.pnl >= 0 ? '+$' : '-$') + Math.abs(t.pnl).toFixed(2);
            tr.innerHTML = '<td>' + t.id + '</td>' +
                           '<td>' + t.date + '</td>' +
                           '<td>' + t.time + '</td>' +
                           '<td>' + t.strategy + '</td>' +
                           '<td><strong>' + t.symbol + '</strong></td>' +
                           '<td>' + t.direction + '</td>' +
                           '<td>' + t.contracts + '</td>' +
                           '<td>' + t.regime + '</td>' +
                           '<td>' + t.mult + '</td>' +
                           '<td class="' + pnlCls + '">' + pnlTxt + '</td>' +
                           '<td>$' + t.portfolio_val.toLocaleString() + '</td>' +
                           '<td>' + t.hold + '</td>';
            tbody.appendChild(tr);
        }});
    }}

    function filterTrades() {{
        const q = document.getElementById('blotterFilter').value.toLowerCase();
        const filtered = appData.blotter.filter(t => {{
            return t.date.includes(q) || t.symbol.toLowerCase().includes(q) || t.strategy.toLowerCase().includes(q) || t.direction.toLowerCase().includes(q) || t.regime.toLowerCase().includes(q);
        }});
        renderBlotter(filtered);
    }}

    window.addEventListener('DOMContentLoaded', () => {{
        initEChart();
        renderMonthly();
        renderBlotter(appData.blotter);
    }});
</script>
</body>
</html>
"""
    html_path.write_text(html_code, encoding="utf-8")
    return html_path


def main():
    print("Loading active 3-strategy portfolio trades...")
    df = load_dataset()
    print(f"Loaded {len(df)} executions across {df['date_str'].nunique()} trading days.")

    print("Computing metrics for Composite and each individual strategy...")
    m_comp = compute_all_metrics(df)
    m_s1 = compute_all_metrics(df[df["window"] == 1])
    m_s2 = compute_all_metrics(df[df["window"] == 2])
    m_s3 = compute_all_metrics(df[df["window"] == 3])

    print("\n" + "=" * 80)
    print("   ACADEMIC BACKTEST RESULTS SCORECARD")
    print("=" * 80)
    print(f"  Composite Ensemble:  {m_comp['trades']} trades | Net: ${m_comp['net_profit']:>9,.2f} | PF: {m_comp['profit_factor']:.2f} | WR: {m_comp['win_rate']:5.1f}% | Sharpe: {m_comp['sharpe']:.2f} | MaxDD: -${abs(m_comp['max_dd']):>7,.2f}")
    print(f"  Strategy 1 (09:45):  {m_s1['trades']} trades | Net: ${m_s1['net_profit']:>9,.2f} | PF: {m_s1['profit_factor']:.2f} | WR: {m_s1['win_rate']:5.1f}% | Sharpe: {m_s1['sharpe']:.2f} | MaxDD: -${abs(m_s1['max_dd']):>7,.2f}")
    print(f"  Strategy 2 (10:15):  {m_s2['trades']} trades | Net: ${m_s2['net_profit']:>9,.2f} | PF: {m_s2['profit_factor']:.2f} | WR: {m_s2['win_rate']:5.1f}% | Sharpe: {m_s2['sharpe']:.2f} | MaxDD: -${abs(m_s2['max_dd']):>7,.2f}")
    print(f"  Strategy 3 (08:35):  {m_s3['trades']} trades | Net: ${m_s3['net_profit']:>9,.2f} | PF: {m_s3['profit_factor']:.2f} | WR: {m_s3['win_rate']:5.1f}% | Sharpe: {m_s3['sharpe']:.2f} | MaxDD: -${abs(m_s3['max_dd']):>7,.2f}")
    print("=" * 80 + "\n")

    print("Rendering Screenshot-Style Backtest Results Poster (PNG)...")
    poster_path = render_screenshot_style_poster(df, m_comp, m_s1, m_s2, m_s3)
    print(f"  Saved Poster: {poster_path}")

    print("Generating Screenshot-Style Interactive Dashboard (HTML)...")
    dashboard_path = generate_screenshot_style_html_dashboard(df, m_comp, m_s1, m_s2, m_s3)
    print(f"  Saved Dashboard: {dashboard_path}")
    print(f"\nTo view in browser:\n  open {dashboard_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
