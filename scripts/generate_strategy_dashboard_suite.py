#!/usr/bin/env python3
"""Generate three distinct strategy, robustness, and prop-risk dashboard sheets."""

from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import generate_visual_strategy_validation_dashboard as source

REPO_ROOT = source.REPO_ROOT
OUT_DIR = REPO_ROOT / "results" / "strategy_dashboard_v5"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
PAPER = source.PAPER
NAVY = source.NAVY
INK = source.INK
MUTED = source.MUTED
GRID = source.GRID
TEAL = source.TEAL
BLUE = source.BLUE
ORANGE = source.ORANGE
RED = source.RED

STRATEGY_LABELS = {
    "S1": "Morning VA",
    "S2": "Macro Momentum",
    "S3": "Gold Fix",
}


def _new_figure(title: str, subtitle: str, *, figsize: tuple[float, float]) -> plt.Figure:
    fig = plt.figure(figsize=figsize, dpi=170, facecolor=PAPER)
    fig.text(0.04, 0.975, title, fontsize=22, fontweight="bold", color=NAVY, va="top")
    fig.text(0.04, 0.943, subtitle, fontsize=9, color=MUTED, va="top")
    return fig


def _add_footer(fig: plt.Figure, data: dict, note: str) -> None:
    record = data["canonical"]
    footer = (
        f"PROVENANCE | {record.run_id} | {record.strategy_id} | {record.methodology} | "
        f"{record.date_start} to {record.date_end} ({record.days_count} calendar days) | "
        f"{record.data_path} SHA-256 {data['data_hash']} | "
        f"Git {record.git_commit} | {record.slippage_model} + {record.commission_model} "
        f"[{'NET' if record.is_net else 'GROSS'}] | Warnings: "
        f"{', '.join(record.warnings) if record.warnings else 'None'}"
    )
    fig.text(0.04, 0.046, footer, fontsize=6.2, color=MUTED, va="bottom", wrap=True)
    fig.text(0.04, 0.020, note, fontsize=6.2, color="#9a4f15", va="bottom", wrap=True)


def _draw_equity(ax: plt.Axes, data: dict) -> None:
    source._style_ax(ax, "Equity path vs NQ")
    daily = data["daily"]
    strategy_equity = 25_000 + daily.cumsum()
    benchmark_returns = data["benchmark_close"].pct_change().fillna(0.0)
    benchmark_equity = 25_000 * (1 + benchmark_returns).cumprod()
    ax.plot(daily.index, strategy_equity, color=BLUE, linewidth=2.0, label="Strategy · $25k base")
    ax.plot(pd.to_datetime(benchmark_equity.index), benchmark_equity, color="#64748b",
            linewidth=1.2, label="NQ buy & hold · rebased")
    ax.axhline(25_000, color=INK, linewidth=0.8, linestyle="--")
    ax.set_ylabel("Equity ($)", color=MUTED)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"${value / 1000:.0f}k"))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(frameon=False, loc="upper left", fontsize=8)


def _draw_drawdown(ax: plt.Axes, data: dict) -> None:
    source._style_ax(ax, "")
    equity = 25_000 + data["daily"].cumsum()
    drawdown = equity - equity.cummax()
    ax.fill_between(drawdown.index, drawdown.to_numpy(), 0, color=RED, alpha=0.16)
    ax.plot(drawdown.index, drawdown, color=RED, linewidth=1.0)
    ax.set_ylabel("Drawdown ($)", fontsize=7)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"${value:,.0f}"))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.tick_params(axis="both", labelsize=7)


def _add_kpis(fig: plt.Figure, data: dict) -> None:
    record = data["canonical"]
    values = [
        ("NET P&L", f"${record.net_profit:+,.0f}"),
        ("PROFIT FACTOR", f"{record.profit_factor:.2f}"),
        ("MAX DRAWDOWN", f"-${abs(record.max_drawdown):,.0f}"),
        ("CLOSED TRADES", f"{record.total_trades:,}"),
    ]
    for index, (label, value) in enumerate(values):
        x = 0.055 + index * 0.232
        fig.patches.append(plt.Rectangle(
            (x, 0.875), 0.205, 0.044, transform=fig.transFigure,
            facecolor="white", edgecolor=GRID, linewidth=0.8, zorder=-1,
        ))
        fig.text(x + 0.012, 0.908, label, fontsize=7, fontweight="bold", color=MUTED, va="top")
        fig.text(x + 0.012, 0.889, value, fontsize=13, fontweight="bold", color=TEAL, va="top")


def _draw_holdout(ax: plt.Axes, data: dict) -> None:
    source._style_ax(ax, "Development vs temporal holdout")
    metrics = [data["dev"], data["holdout"]]
    labels = ["DEV\n2021–24", "HOLDOUT\n2025–26"]
    x = np.arange(2)
    bars = ax.bar(x, [metric["pf"] for metric in metrics], color=[BLUE, TEAL], width=0.56)
    ax.axhline(1.0, color=RED, linestyle="--", linewidth=1, label="PF breakeven")
    ax.set_xticks(x, labels)
    ax.set_ylabel("Profit factor")
    ax.set_ylim(0, max(metric["pf"] for metric in metrics) * 1.48)
    for bar, metric in zip(bars, metrics):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.04,
                f"PF {metric['pf']:.2f}", ha="center", color=INK, fontweight="bold")
        ax.text(bar.get_x() + bar.get_width() / 2, 0.06,
                f"{metric['trades']} trades\n{metric['win_rate']:.1f}% WR\n"
                f"${metric['net']:+,.0f} net",
                ha="center", va="bottom", fontsize=8, color=INK)
    ax.legend(frameon=False, fontsize=7, loc="upper right")
    ax.text(0.5, -0.18,
            "Temporal split only; individual walk-forward fold exports are unavailable.",
            transform=ax.transAxes, ha="center", va="top", fontsize=7, color=ORANGE)


def _draw_annual(ax: plt.Axes, data: dict) -> None:
    source._style_ax(ax, "Calendar-year net P&L · chronological context")
    annual = data["annual"]
    colors = [TEAL if value >= 0 else RED for value in annual["net"]]
    bars = ax.bar(annual["year"].astype(str), annual["net"], color=colors, width=0.68)
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.set_ylabel("Net P&L ($)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"${value / 1000:.0f}k"))
    for bar, row in zip(bars, annual.itertuples()):
        value = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, value + (65 if value >= 0 else -90),
                f"PF {row.pf:.2f}\n{row.trades} trades", ha="center",
                va="bottom" if value >= 0 else "top", fontsize=7, color=INK)


def _draw_strategy_comparison(ax: plt.Axes, data: dict) -> None:
    source._style_ax(ax, "Canonical component strategies")
    keys = ["S1", "S2", "S3"]
    records = [data["records"][key] for key in keys]
    x = np.arange(len(keys))
    bars = ax.bar(x, [record.net_profit for record in records],
                  color=[BLUE, TEAL, ORANGE], width=0.62)
    ax.set_xticks(x, [STRATEGY_LABELS[key] for key in keys])
    ax.set_ylabel("Net P&L ($)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"${value / 1000:.0f}k"))
    for bar, record in zip(bars, records):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 100,
                f"${record.net_profit:,.0f}\nPF {record.profit_factor:.2f} · "
                f"{record.total_trades} trades", ha="center", va="bottom", fontsize=7.5, color=INK)


def _render_performance(data: dict) -> Path:
    record = data["canonical"]
    fig = _new_figure(
        "01  STRATEGY PERFORMANCE",
        f"Portfolio and component results · {record.date_start} to {record.date_end} · "
        "canonical NET provenance",
        figsize=(16, 11),
    )
    _add_kpis(fig, data)
    grid = fig.add_gridspec(2, 2, left=0.055, right=0.97, top=0.83, bottom=0.12,
                            hspace=0.54, wspace=0.28)
    equity_grid = grid[0, 0].subgridspec(2, 1, height_ratios=[3, 0.8], hspace=0.08)
    _draw_equity(fig.add_subplot(equity_grid[0]), data)
    _draw_drawdown(fig.add_subplot(equity_grid[1]), data)
    _draw_holdout(fig.add_subplot(grid[0, 1]), data)
    _draw_annual(fig.add_subplot(grid[1, 0]), data)
    _draw_strategy_comparison(fig.add_subplot(grid[1, 1]), data)
    _add_footer(
        fig, data,
        "Walk-forward fold-level exports are not saved; temporal holdout and yearly slices are context, "
        "not independent fold evidence.",
    )
    return _save(fig, "01_strategy_performance")


def _draw_slippage_and_outlier(ax: plt.Axes, data: dict, trim: dict) -> None:
    ax.set_axis_off()
    ax.text(0, 1.03, "Execution friction & outlier dependence", transform=ax.transAxes,
            fontsize=12, fontweight="bold", color=NAVY, va="bottom")
    slip = source.da.slippage_curve(data["trades"], "research_pnl", ticks=range(0, 9))
    slip_ax = ax.inset_axes([0.03, 0.12, 0.57, 0.80])
    trim_ax = ax.inset_axes([0.66, 0.12, 0.31, 0.80])
    source._style_ax(slip_ax, "Extra adverse ticks")
    slip_ax.plot(slip["ticks"], slip["pf"], color=BLUE, marker="o", linewidth=2)
    slip_ax.axhline(1, color=RED, linestyle="--", linewidth=1, label="PF breakeven")
    slip_ax.set_xlabel("Ticks / side")
    slip_ax.set_ylabel("Profit factor")
    slip_ax.legend(frameon=False, fontsize=7)
    source._style_ax(trim_ax, "Top-win removal")
    bars = trim_ax.bar([0, 1], [trim["base_net"], trim["trimmed_net"]],
                       color=[TEAL, ORANGE], width=0.62)
    trim_ax.set_xticks([0, 1], ["All trades", "Top 5%\nremoved"])
    trim_ax.set_ylabel("Net P&L ($)")
    trim_ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"${value / 1000:.0f}k"))
    for bar, value in zip(bars, [trim["base_net"], trim["trimmed_net"]]):
        trim_ax.text(bar.get_x() + bar.get_width() / 2, value + 150, f"${value:,.0f}",
                     ha="center", fontsize=7, color=INK)
    trim_ax.text(0.5, -0.20, f"Trimmed PF {trim['trimmed_pf']:.2f}",
                 transform=trim_ax.transAxes, ha="center", fontsize=7, color=INK)


def _draw_mc(ax: plt.Axes, data: dict, samples: np.ndarray) -> None:
    source._style_ax(ax, "Trade-order Monte Carlo drawdown")
    observed = source.da.max_drawdown(data["trades"]["research_pnl"].cumsum().to_numpy())
    q05, q50, q95 = np.percentile(samples, [5, 50, 95])
    ax.hist(samples, bins=34, color="#8db7d2", edgecolor="white", linewidth=0.5)
    ax.axvline(observed, color=TEAL, linewidth=2, label=f"Observed order {observed:,.0f}")
    ax.axvline(q05, color=RED, linestyle="--", label=f"5th percentile {q05:,.0f}")
    ax.axvline(q50, color=NAVY, linestyle=":", label=f"Median {q50:,.0f}")
    ax.set_xlabel("Maximum drawdown ($)")
    ax.set_ylabel("Reshuffles")
    ax.legend(frameon=False, fontsize=7)
    ax.text(0.98, 0.98, f"{len(samples):,} random trade-order reshuffles",
            transform=ax.transAxes, ha="right", va="top", fontsize=7, color=MUTED)
    ax.text(0.98, 0.88, f"95th percentile: {q95:,.0f}",
            transform=ax.transAxes, ha="right", va="top", fontsize=7, color=MUTED)


def _render_robustness(data: dict, dd_samples: np.ndarray, trim: dict) -> Path:
    record = data["canonical"]
    fig = _new_figure(
        "02  ROBUSTNESS & STRESS TESTS",
        f"Parameter, sequence, execution, outlier, and volatility-regime checks · "
        f"{record.date_start} to {record.date_end}",
        figsize=(16, 13),
    )
    fig.text(0.055, 0.905,
             "Evidence boundary: canonical methodology is walk-forward, but fold exports and "
             "walk-forward permutation/placebo reports are not saved.",
             fontsize=8, color=ORANGE, va="top")
    grid = fig.add_gridspec(3, 2, left=0.08, right=0.95, top=0.85, bottom=0.11,
                            hspace=0.48, wspace=0.31,
                            height_ratios=[1.55, 1.0, 1.0])
    parameter_ax = fig.add_subplot(grid[0, :])
    source._draw_parameter_heatmap(parameter_ax, data)
    parameter_ax.set_title("Parameter plateau · profit factor across ±25%", loc="left",
                           fontsize=12, fontweight="bold", color=NAVY, pad=11)
    _draw_mc(fig.add_subplot(grid[1, 0]), data, dd_samples)
    _draw_slippage_and_outlier(fig.add_subplot(grid[1, 1]), data, trim)
    regime_ax = fig.add_subplot(grid[2, :])
    source._draw_regimes(regime_ax, data)
    regime_ax.set_title("Markov volatility regime outcomes", loc="left",
                        fontsize=12, fontweight="bold", color=NAVY, pad=11)
    _add_footer(
        fig, data,
        "The parameter sweep and reshuffles are saved/model-derived evidence; they do not substitute "
        "for missing fold-level or permutation/placebo artifacts.",
    )
    return _save(fig, "02_robustness_stress")


def _draw_prop_sensitivity(ax: plt.Axes, prop: dict) -> None:
    source._style_ax(ax, "Evaluation pass rate under added adverse slippage")
    x = np.arange(len(prop["slip_ticks"]))
    rates = prop["pass_by_slip"]
    ax.plot(x, rates, color=BLUE, marker="o", linewidth=2)
    ax.fill_between(x, rates, alpha=0.10, color=BLUE)
    ax.set_xticks(x, [f"{ticks} ticks" for ticks in prop["slip_ticks"]])
    ax.set_ylabel("Modeled pass rate")
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0f}%"))
    for xi, rate in zip(x, rates):
        ax.annotate(f"{rate:.0f}%", (xi, rate), xytext=(0, 7), textcoords="offset points",
                    ha="center", fontsize=8, color=INK)


def _draw_prop_outcomes(ax: plt.Axes, prop: dict) -> None:
    source._style_ax(ax, "Evaluation outcomes · mutually exclusive")
    sim = prop["sim"]
    values = [sim["pass_rate"], sim["fail_rate"], sim["open_rate"]]
    labels = ["Pass", "Rule breach", "Still open"]
    colors = [TEAL, RED, "#a9b5c3"]
    left = 0.0
    for value, label, color in zip(values, labels, colors):
        ax.barh([0], [value], left=left, color=color, height=0.45, label=f"{label} · {value:.1f}%")
        if value > 5:
            ax.text(left + value / 2, 0, f"{value:.1f}%", ha="center", va="center",
                    color="white", fontsize=8, fontweight="bold")
        left += value
    ax.set_xlim(0, 100)
    ax.set_yticks([])
    ax.set_xlabel("Share of simulated evaluation paths")
    ax.legend(frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.35), fontsize=8)


def _draw_prop_duration(ax: plt.Axes, prop: dict) -> None:
    source._style_ax(ax, "Sessions to pass or breach")
    sim = prop["sim"]
    statuses, sessions = sim["status"], sim["sessions"]
    pass_sessions = sessions[statuses == "pass"]
    fail_sessions = sessions[statuses == "fail"]
    bins = np.linspace(0, max(float(np.max(sessions)), 1), 26)
    if pass_sessions.size:
        ax.hist(pass_sessions, bins=bins, color=TEAL, alpha=0.75, label="Pass")
    if fail_sessions.size:
        ax.hist(fail_sessions, bins=bins, color=RED, alpha=0.65, label="Rule breach")
    ax.set_xlabel("Trading sessions from evaluation start")
    ax.set_ylabel("Path count")
    ax.legend(frameon=False, fontsize=8)
    summary = prop["summary"]
    ax.text(0.98, 0.98,
            f"Pass duration median {summary['pass_med']:.0f} sessions\n"
            f"P10–P90 {summary['pass_p10']:.0f}–{summary['pass_p90']:.0f}",
            transform=ax.transAxes, ha="right", va="top", fontsize=8, color=INK)


def _draw_payouts(ax: plt.Axes, prop: dict) -> None:
    source._style_ax(ax, "Funded payout model · conditional on evaluation pass")
    funded = prop["funded"]
    ladder = funded.get("ladder", {})
    payout_numbers = np.arange(1, 6)
    rates = [ladder.get(int(number), np.nan) for number in payout_numbers]
    bars = ax.bar(payout_numbers, rates, color=TEAL, width=0.62)
    ax.set_xticks(payout_numbers, [f"#{number}" for number in payout_numbers])
    ax.set_ylabel("Funded paths reaching payout")
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0f}%"))
    for bar, rate in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, rate + 2, f"{rate:.0f}%",
                ha="center", fontsize=8, color=INK)
    ax.text(0.98, 0.98,
            f"Conditional median net payout: ${funded.get('median_net', math.nan):,.0f}\n"
            f"Zero-payout paths: {funded.get('zero_payout_pct', math.nan):.1f}%\n"
            f"Modeled net EV / attempt: ${funded.get('ev_per_attempt', math.nan):,.0f}",
            transform=ax.transAxes, ha="right", va="top", fontsize=8, color=INK)


def _render_prop(data: dict, prop: dict) -> Path:
    rules = prop["rules"]
    funded_rules = prop["funded_rules"]
    sim = prop["sim"]
    fig = _new_figure(
        "03  PROP-FIRM ACCOUNT RISK",
        "Scenario model for the configured 25K evaluation profile · not a live pass probability",
        figsize=(16, 13),
    )
    fig.text(
        0.055, 0.912,
        f"Rules modeled: ${rules.start:,.0f} start · +${rules.target:,.0f} target · "
        f"${rules.max_dd:,.0f} EOD trailing drawdown · ${abs(rules.soft_stop or 0):,.0f} daily stop · "
        f"${rules.eval_fee:.0f} assumed fee",
        fontsize=8.5, color=INK, va="top",
    )
    fig.text(
        0.055, 0.889,
        f"{len(sim['status']):,} block-bootstrap paths · 10-session blocks · "
        f"750-session horizon · seed 42 · funded model {funded_rules.min_profit_days} qualifying "
        f"days per {funded_rules.cycle_sessions}-session cycle",
        fontsize=8, color=MUTED, va="top",
    )
    grid = fig.add_gridspec(2, 2, left=0.08, right=0.95, top=0.83, bottom=0.13,
                            hspace=0.50, wspace=0.28)
    _draw_prop_sensitivity(fig.add_subplot(grid[0, 0]), prop)
    _draw_prop_outcomes(fig.add_subplot(grid[0, 1]), prop)
    _draw_prop_duration(fig.add_subplot(grid[1, 0]), prop)
    _draw_payouts(fig.add_subplot(grid[1, 1]), prop)
    _add_footer(
        fig, data,
        "Modeled only: payout rules are assumptions; simulator omits consistency and contract caps. "
        "Verify current firm rules before relying on these scenarios.",
    )
    return _save(fig, "03_prop_firm_risk")


def _save(fig: plt.Figure, stem: str) -> Path:
    path = OUT_DIR / f"{stem}_{TIMESTAMP}.png"
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing dashboard: {path}")
    fig.savefig(path, dpi=170, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    return path


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = source._load_inputs()
    trades = data["trades"]
    prop = source._run_prop_stress(trades, data["calendar"])
    dd_samples = source.da.reshuffled_max_drawdowns(
        trades["research_pnl"].to_numpy(dtype=float), n=3000, seed=42
    )
    wins = trades[trades["research_pnl"] > 0]
    remove_count = max(1, int(math.ceil(0.05 * len(wins))))
    trimmed = trades.drop(index=wins.nlargest(remove_count, "research_pnl").index)
    trim = {
        "base_net": float(trades["research_pnl"].sum()),
        "trimmed_net": float(trimmed["research_pnl"].sum()),
        "trimmed_pf": source.da.profit_factor(trimmed["research_pnl"].to_numpy(dtype=float)),
    }

    outputs = [
        _render_performance(data),
        _render_robustness(data, dd_samples, trim),
        _render_prop(data, prop),
    ]
    for output in outputs:
        print(f"Created: {output.relative_to(REPO_ROOT)}")
    print("Sheets: strategy performance; robustness and stress; prop-firm account risk")


if __name__ == "__main__":
    main()
