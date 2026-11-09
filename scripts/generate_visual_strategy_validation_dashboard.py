#!/usr/bin/env python3
"""Render a visual strategy validation and prop-firm stress dashboard."""

from __future__ import annotations

from datetime import datetime
import hashlib
import math
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest import dashboard_analytics as da
from backtest.provenance import default_store

OUT_DIR = REPO_ROOT / "results" / "strategy_dashboard_v4"
OUT_PATH = OUT_DIR / (
    f"visual_validation_dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
)
CANONICAL_RUN_ID = "run_canonical_lucid_flex_ensemble_2021_2026"
STRATEGY_RUN_IDS = {
    "S1": "run_canonical_s1_va_breakout_2021_2026",
    "S2": "run_canonical_s2_macro_momentum_2021_2026",
    "S3": "run_canonical_s3_gold_london_fix_2021_2026",
}

NAVY = "#122033"
INK = "#26364b"
MUTED = "#65758b"
GRID = "#dbe3ec"
TEAL = "#07877e"
BLUE = "#2878b5"
ORANGE = "#e28b2e"
RED = "#cf5145"
GREEN = "#3b936a"
PURPLE = "#7764a8"
PAPER = "#f4f7fb"


def _style_ax(ax: plt.Axes, title: str) -> None:
    ax.set_facecolor("white")
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=NAVY, pad=11)
    ax.grid(axis="y", color=GRID, linewidth=0.7, zorder=0)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    for spine in ax.spines.values():
        spine.set_color(GRID)
        spine.set_linewidth(0.7)


def _metrics(trades: pd.DataFrame, calendar: list[str], col: str) -> dict:
    return da.performance_metrics(trades, calendar, col, n_boot=1000, seed=7)


def _load_inputs() -> dict:
    store = default_store
    canonical = store.get_run(CANONICAL_RUN_ID)
    if canonical is None:
        raise RuntimeError(f"Missing canonical provenance record: {CANONICAL_RUN_ID}")
    records = {key: store.get_run(run_id) for key, run_id in STRATEGY_RUN_IDS.items()}
    if any(record is None for record in records.values()):
        raise RuntimeError("One or more canonical strategy provenance records are missing")

    data_path = REPO_ROOT / canonical.data_path
    data_hash = store.compute_data_hash(canonical.data_path)
    if data_hash != canonical.data_hash:
        raise ValueError("Canonical trade ledger SHA-256 does not match the provenance record")
    trades = da.load_trades(data_path)
    calendar = da.load_session_calendar(
        da.DEFAULT_CALENDAR_SOURCE, trades["date"].min(), trades["date"].max()
    )
    daily = da.daily_series(trades, calendar, "research_pnl")
    daily.index = pd.to_datetime(daily.index)

    benchmark_frame = pd.read_parquet(da.DEFAULT_CALENDAR_SOURCE, columns=["time", "close"])
    benchmark_frame["date"] = pd.to_datetime(benchmark_frame["time"]).dt.strftime("%Y-%m-%d")
    close_by_day = benchmark_frame.groupby("date")["close"].last()
    benchmark_close = pd.Series(index=calendar, dtype=float)
    for day in calendar:
        if day in close_by_day.index:
            benchmark_close.loc[day] = close_by_day.loc[day]
    benchmark_close = benchmark_close.ffill().bfill()
    nq_sha = hashlib.sha256(da.DEFAULT_CALENDAR_SOURCE.read_bytes()).hexdigest()

    plateau_path = REPO_ROOT / "results/parameter_plateau_sweep/parameter_plateau_sweep_results.csv"
    if not plateau_path.exists():
        raise FileNotFoundError(f"Missing saved parameter plateau evidence: {plateau_path}")
    plateau = pd.read_csv(plateau_path)
    if len(plateau) != 45:
        raise ValueError(f"Expected 45 saved plateau evaluations; found {len(plateau)}")
    plateau_sha = hashlib.sha256(plateau_path.read_bytes()).hexdigest()

    dev_cutoff = da.DEV_END
    dev_trades = trades[trades["date"] <= dev_cutoff]
    holdout_trades = trades[trades["date"] > dev_cutoff]
    dev_calendar = [day for day in calendar if day <= dev_cutoff]
    holdout_calendar = [day for day in calendar if day > dev_cutoff]
    dev = _metrics(dev_trades, dev_calendar, "research_pnl")
    holdout = _metrics(holdout_trades, holdout_calendar, "research_pnl")

    annual_rows = []
    for year, group in trades.groupby(trades["entry_time"].dt.year):
        pnl = group["research_pnl"].to_numpy(dtype=float)
        annual_rows.append({
            "year": int(year),
            "net": float(pnl.sum()),
            "pf": da.profit_factor(pnl),
            "trades": int(len(group)),
        })
    annual = pd.DataFrame(annual_rows).sort_values("year")

    regimes = trades.groupby("markov_state_label", dropna=False).agg(
        net=("research_pnl", "sum"),
        trades=("research_pnl", "size"),
    ).reset_index()
    regime_pf = trades.groupby("markov_state_label")["research_pnl"].apply(
        lambda values: da.profit_factor(values.to_numpy())
    )
    regimes["pf"] = regimes["markov_state_label"].map(regime_pf)
    regimes["sort_order"] = regimes["markov_state_label"].astype(str).str.lower().str.replace(
        "_", " ", regex=False
    ).map({
        "low vol": 0,
        "mid vol": 1,
        "high vol": 2,
    }).fillna(3)
    return {
        "store": store,
        "canonical": canonical,
        "records": records,
        "trades": trades,
        "calendar": calendar,
        "daily": daily,
        "benchmark_close": benchmark_close,
        "benchmark_sha": nq_sha,
        "data_hash": data_hash,
        "plateau": plateau,
        "plateau_sha": plateau_sha,
        "dev": dev,
        "holdout": holdout,
        "annual": annual,
        "regimes": regimes.sort_values("sort_order").drop(columns="sort_order"),
    }


def _run_prop_stress(trades: pd.DataFrame, calendar: list[str]) -> dict:
    legs = da.build_session_legs(trades, calendar)
    rules = da.PropRules()
    funded_rules = da.FundedRules()
    sim = da.bootstrap_prop(
        legs,
        da.POLICIES["live_ratchet"],
        n_sims=10_000,
        block=10,
        horizon=750,
        rules=rules,
        seed=42,
        funded=funded_rules,
        funded_horizon=252,
    )
    slip_ticks = [0, 1, 2, 3, 4, 6]
    pass_by_slip = []
    for ticks in slip_ticks:
        run = da.bootstrap_prop(
            legs,
            da.POLICIES["live_ratchet"],
            n_sims=2_500,
            block=10,
            horizon=750,
            rules=rules,
            extra_ticks=ticks,
            seed=42,
        )
        pass_by_slip.append(run["pass_rate"])
    summary = da.summarize_prop(sim, 365.25 / 252.0)
    return {
        "sim": sim,
        "summary": summary,
        "funded": da.funded_summary(sim["funded"], sim["pass_rate"], rules.eval_fee),
        "rules": rules,
        "funded_rules": funded_rules,
        "slip_ticks": slip_ticks,
        "pass_by_slip": pass_by_slip,
    }


def _draw_header(fig: plt.Figure, data: dict, prop: dict) -> None:
    record = data["canonical"]
    oos = data["holdout"]
    plateau = data["plateau"]
    min_plateau_pf = float(plateau["profit_factor"].min())
    values = [
        ("NET RETURN", f"+${record.net_profit:,.0f}", "multi-year WF · net costs"),
        ("PROFIT FACTOR", f"{record.profit_factor:.2f}", f"{record.total_trades:,} trades · verified"),
        ("HOLDOUT PF", f"{oos['pf']:.2f}", "2025–26 temporal holdout"),
        ("PLATEAU FLOOR", f"{min_plateau_pf:.2f}", "minimum PF · 45 settings"),
        ("PROP PASS MODEL", f"{prop['sim']['pass_rate']:.1f}%", "10k block-bootstrap paths"),
    ]
    fig.text(0.035, 0.977, "STRATEGY VALIDATION  /  RISK & PROP-FIRM STRESS",
             fontsize=21, fontweight="bold", color=NAVY, va="top")
    fig.text(
        0.035, 0.951,
        f"Visual evidence summary · {record.date_start} to {record.date_end} · "
        f"{record.days_count:,} calendar days · {record.data_path}",
        fontsize=8.5, color=MUTED, va="top",
    )
    x0, width, gap = 0.035, 0.178, 0.012
    for i, (label, value, note) in enumerate(values):
        x = x0 + i * (width + gap)
        fig.patches.append(plt.Rectangle(
            (x, 0.885), width, 0.047,
            transform=fig.transFigure, facecolor="white", edgecolor=GRID, linewidth=0.8,
            zorder=-1,
        ))
        fig.text(x + 0.009, 0.920, label, fontsize=7.1, fontweight="bold", color=MUTED, va="top")
        fig.text(x + 0.009, 0.902, value, fontsize=15, fontweight="bold",
                 color=TEAL if i != 4 else BLUE, va="top")
        fig.text(x + 0.009, 0.889, note, fontsize=6.2, color=MUTED, va="top")


def _draw_equity(ax: plt.Axes, data: dict) -> None:
    _style_ax(ax, "1  |  Equity path & drawdown · strategy vs NQ")
    daily = data["daily"]
    dates = daily.index
    strategy_eq = 25_000 + daily.cumsum()
    benchmark = data["benchmark_close"]
    benchmark_returns = benchmark.pct_change().fillna(0.0)
    benchmark_eq = 25_000 * (1 + benchmark_returns).cumprod()
    ax.plot(dates, strategy_eq, color=BLUE, linewidth=2.2, label="Strategy · $25k base", zorder=4)
    ax.plot(pd.to_datetime(benchmark.index), benchmark_eq, color="#64748b",
            linewidth=1.25, alpha=0.8, label="NQ buy & hold · rebased", zorder=3)
    ax.axhline(25_000, color=INK, linewidth=0.8, linestyle="--", alpha=0.8)
    ax.fill_between(dates, strategy_eq.to_numpy(), 25_000,
                    where=(strategy_eq.to_numpy() >= 25_000), color=TEAL, alpha=0.09)
    ax.fill_between(dates, strategy_eq.to_numpy(), 25_000,
                    where=(strategy_eq.to_numpy() < 25_000), color=RED, alpha=0.08)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.set_xlim(dates.min(), dates.max())
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x / 1000:.0f}k"))
    ax.set_ylabel("Growth of $25,000", color=MUTED, fontsize=8)
    ax.tick_params(axis="x", labelbottom=False)
    ax.legend(loc="upper left", frameon=False, ncol=2, fontsize=8)
    ax.set_xlabel("")


def _draw_drawdown(ax: plt.Axes, data: dict) -> None:
    _style_ax(ax, "")
    equity = 25_000 + data["daily"].cumsum()
    drawdown = equity - equity.cummax()
    dates = drawdown.index
    ax.fill_between(dates, drawdown.to_numpy(), 0, color=RED, alpha=0.18)
    ax.plot(dates, drawdown, color=RED, linewidth=1.0)
    ax.axhline(-1_000, color=ORANGE, linestyle="--", linewidth=1.0)
    ax.text(0.99, 0.82, f"Max {drawdown.min():,.0f}  ·  prop trail reference -$1,000",
            transform=ax.transAxes, ha="right", va="top", fontsize=6.4, color=RED)
    ax.set_xlim(dates.min(), dates.max())
    ax.set_ylim(min(float(drawdown.min()) * 1.08, -1_000), 0)
    ax.set_ylabel("Drawdown ($)", color=MUTED, fontsize=6.5)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"${value:,.0f}"))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.tick_params(axis="both", labelsize=6)
    ax.set_xlabel("")


def _draw_oos(ax: plt.Axes, data: dict) -> None:
    _style_ax(ax, "2  |  Walk-forward record & temporal holdout")
    dev, oos = data["dev"], data["holdout"]
    ax.axhline(1.0, color=RED, linestyle="--", linewidth=1.1, label="PF breakeven")
    xs = np.array([0, 1])
    pfs = [dev["pf"], oos["pf"]]
    colors = [BLUE, TEAL]
    ax.bar(xs, pfs, color=colors, width=0.52, zorder=3)
    ax.set_xticks(xs, ["DEV\n2021–24", "HOLDOUT\n2025–26"])
    ax.set_ylabel("Profit factor", color=MUTED, fontsize=8)
    ax.set_ylim(0, max(pfs) * 1.35)
    for x, pf, metric, color in zip(xs, pfs, [dev, oos], colors):
        ax.text(x, pf + 0.04, f"{pf:.2f}", ha="center", va="bottom",
                fontsize=11, fontweight="bold", color=color)
        ax.text(x, 0.08, f"{metric['trades']} trades\n{metric['win_rate']:.1f}% WR\n"
                f"{metric['net']:+,.0f} net", ha="center", va="bottom",
                fontsize=7.2, color=INK)
    ax.text(
        0.5, 0.98,
        "Verified run methodology: MULTI_YEAR_WALKFORWARD",
        transform=ax.transAxes, ha="center", va="top", fontsize=7.1,
        color=TEAL, fontweight="bold",
    )
    ax.text(
        0.5, -0.23,
        "Fold-level CSV not saved: bars show the documented temporal split, not individual WF folds.",
        transform=ax.transAxes, ha="center", va="top", fontsize=6.8, color=ORANGE,
        wrap=True,
    )


def _draw_yearly(ax: plt.Axes, data: dict) -> None:
    _style_ax(ax, "3  |  Walk-forward context · calendar-year slices")
    annual = data["annual"]
    colors = [TEAL if value >= 0 else RED for value in annual["net"]]
    bars = ax.bar(annual["year"].astype(str), annual["net"], color=colors, width=0.68, zorder=3)
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.set_ylabel("Net P&L · USD", color=MUTED, fontsize=8)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x / 1000:.0f}k"))
    ax.tick_params(axis="x", rotation=0)
    for bar, row in zip(bars, annual.itertuples()):
        y = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2,
                y + (70 if y >= 0 else -100),
                f"PF {row.pf:.2f}\n{row.trades} trades",
                ha="center", va="bottom" if y >= 0 else "top", fontsize=6.6, color=INK)


def _draw_parameter_heatmap(ax: plt.Axes, data: dict) -> None:
    _style_ax(ax, "4  |  Parameter plateau · profit factor across ±25%")
    frame = data["plateau"].copy()
    frame["strategy_short"] = frame["strategy"].map({
        "morning_va_breakout_s1": "S1",
        "macro_momentum_s2": "S2",
        "gold_london_fix_s3": "S3",
    })
    frame["row_name"] = frame["strategy_short"] + " · " + frame["param"]
    rows = frame[["strategy_short", "param", "row_name"]].drop_duplicates()
    matrix = frame.pivot(index="row_name", columns="delta", values="profit_factor")
    order = rows["row_name"].tolist()
    matrix = matrix.reindex(order)
    norm = TwoSlopeNorm(
        vmin=min(0.9, float(matrix.min().min())),
        vcenter=1.0,
        vmax=max(1.1, float(matrix.max().max())),
    )
    image = ax.imshow(matrix.to_numpy(), cmap="RdYlGn", norm=norm, aspect="auto")
    ax.set_yticks(np.arange(len(matrix)), matrix.index, fontsize=6.6)
    shifts = matrix.columns.to_numpy(dtype=float) * 100
    ax.set_xticks(np.arange(len(shifts)), [f"{value:+g}%" if value else "base" for value in shifts])
    ax.tick_params(axis="x", labelsize=7)
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            value = matrix.iloc[i, j]
            color = "white" if abs(value - 1.0) > 0.6 else NAVY
            ax.text(j, i, f"{value:.2f}", ha="center", va="center",
                    fontsize=6.3, color=color, fontweight="bold")
    ax.set_xlabel("Parameter perturbation around baseline", color=MUTED, fontsize=7)
    ax.axvline(2.5, color="white", linewidth=1.5)
    cbar = ax.figure.colorbar(image, ax=ax, fraction=0.035, pad=0.025)
    cbar.set_label("Profit factor · 1.0 = breakeven", fontsize=7, color=MUTED)
    cbar.ax.tick_params(labelsize=6, colors=MUTED)


def _draw_monte_carlo(ax: plt.Axes, data: dict, dd_samples: np.ndarray) -> None:
    _style_ax(ax, "5  |  Monte Carlo · trade-order drawdown risk")
    observed = da.max_drawdown(data["trades"]["research_pnl"].cumsum().to_numpy())
    q05, q50, q95 = np.percentile(dd_samples, [5, 50, 95])
    ax.hist(dd_samples, bins=32, color="#8db7d2", edgecolor="white", linewidth=0.5, zorder=2)
    ax.axvline(observed, color=TEAL, linewidth=2, label=f"Observed order  {observed:,.0f}")
    ax.axvline(q05, color=RED, linestyle="--", linewidth=1.5, label=f"Worst 5%  {q05:,.0f}")
    ax.axvline(q50, color=NAVY, linestyle=":", linewidth=1.5, label=f"Median  {q50:,.0f}")
    ax.set_xlabel("Maximum drawdown · USD (negative = loss from peak)", color=MUTED, fontsize=7)
    ax.set_ylabel("Permutation count", color=MUTED, fontsize=7)
    ax.legend(frameon=False, fontsize=6.5, loc="upper left")
    ax.text(0.98, 0.98, f"3,000 reshuffles · fixed trade P&L · q95 {q95:,.0f}",
            transform=ax.transAxes, ha="right", va="top", fontsize=6.4, color=MUTED)


def _draw_execution_stress(ax: plt.Axes, data: dict, trim: dict) -> None:
    ax.set_axis_off()
    ax.text(0.0, 1.04, "6  |  Execution & outlier stress",
            transform=ax.transAxes, fontsize=12, fontweight="bold", color=NAVY, va="bottom")
    slip = da.slippage_curve(data["trades"], "research_pnl", ticks=range(0, 9))
    slip_ax = ax.inset_axes([0.02, 0.16, 0.58, 0.72])
    trim_ax = ax.inset_axes([0.65, 0.16, 0.33, 0.72])
    _style_ax(slip_ax, "Fill friction")
    _style_ax(trim_ax, "Winner truncation")
    slip_ax.set_title("Fill friction", loc="left", fontsize=8.5, color=NAVY, pad=5)
    trim_ax.set_title("Winner truncation", loc="left", fontsize=8.5, color=NAVY, pad=5)
    slip_ax.plot(slip["ticks"], slip["pf"], marker="o", color=BLUE,
                 linewidth=2, markersize=3.5)
    slip_ax.axhline(1, color=RED, linestyle="--", linewidth=1.1, label="PF breakeven")
    break_even = slip.loc[slip["pf"] <= 1, "ticks"]
    if not break_even.empty:
        slip_ax.axvline(float(break_even.iloc[0]), color=ORANGE, linestyle=":", linewidth=1.2)
    slip_ax.set_xlabel("Extra ticks / side", color=MUTED, fontsize=6.5)
    slip_ax.set_ylabel("Profit factor", color=MUTED, fontsize=6.5)
    slip_ax.tick_params(labelsize=6)
    slip_ax.legend(frameon=False, loc="upper right", fontsize=5.8)
    nets = [trim["base_net"], trim["trimmed_net"]]
    bars = trim_ax.bar([0, 1], nets, width=0.62, color=[TEAL, ORANGE], alpha=0.85)
    trim_ax.set_xticks([0, 1], ["All", "Ex-top\n5%"], fontsize=6)
    trim_ax.set_ylabel("Net P&L", color=MUTED, fontsize=6.2)
    trim_ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"${value / 1000:.0f}k"))
    trim_ax.tick_params(axis="y", labelsize=5.8)
    for bar, value in zip(bars, nets):
        trim_ax.text(bar.get_x() + bar.get_width() / 2, value + 180,
                     f"${value:,.0f}", ha="center", fontsize=5.8, color=INK)
    trim_ax.text(
        0.5, -0.24,
        f"Delete {trim['removed_count']} wins · PF {trim['trimmed_pf']:.2f}",
        transform=trim_ax.transAxes, ha="center", fontsize=5.7, color=INK,
    )


def _draw_regimes(ax: plt.Axes, data: dict) -> None:
    _style_ax(ax, "7  |  Regime robustness · Markov volatility states")
    regimes = data["regimes"]
    labels = [str(value).replace("_", " ").title() for value in regimes["markov_state_label"]]
    colors = [TEAL if pf >= 1 else RED for pf in regimes["pf"]]
    bars = ax.bar(labels, regimes["net"], color=colors, width=0.58, zorder=3)
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.set_ylabel("Net P&L · USD", color=MUTED, fontsize=7)
    ax.tick_params(axis="x", rotation=12, labelsize=6.8)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x / 1000:.0f}k"))
    for bar, row in zip(bars, regimes.itertuples()):
        value = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2,
                value + (60 if value >= 0 else -100),
                f"PF {row.pf:.2f}\n{row.trades} trades",
                ha="center", va="bottom" if value >= 0 else "top", fontsize=6.4, color=INK)
    ax.text(0.98, 0.98, "Historical trade outcomes grouped by saved regime label",
            transform=ax.transAxes, ha="right", va="top", fontsize=6.1, color=MUTED)


def _draw_prop(ax: plt.Axes, prop: dict) -> None:
    _style_ax(ax, "8  |  Prop-firm Monte Carlo · evaluation + payout")
    x = np.arange(len(prop["slip_ticks"]))
    rates = prop["pass_by_slip"]
    ax.plot(x, rates, marker="o", color=BLUE, linewidth=2, markersize=4,
            label="Evaluation pass rate")
    ax.axhline(50, color=GRID, linewidth=1, linestyle=":")
    ax.set_xticks(x, [f"{ticks}t" for ticks in prop["slip_ticks"]])
    ax.set_xlabel("Additional adverse ticks per leg", color=MUTED, fontsize=7)
    ax.set_ylabel("Evaluation pass rate", color=MUTED, fontsize=7)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda value, _: f"{value:.0f}%"))
    ax.set_ylim(0, 100)

    ladder = prop["funded"].get("ladder", {})
    payout_x = np.arange(1, 6)
    payout_rates = [ladder.get(i, np.nan) for i in payout_x]
    # Compact payout ladder inset keeps evaluation-cost stress and funded survival together.
    inset = ax.inset_axes([0.59, 0.18, 0.36, 0.52])
    inset.bar(payout_x, payout_rates, color=TEAL, width=0.62)
    inset.set_ylim(0, 100)
    inset.set_xticks(payout_x, [f"#{i}" for i in payout_x], fontsize=6)
    inset.tick_params(axis="y", labelsize=5.8, colors=MUTED, length=0)
    inset.grid(axis="y", color=GRID, linewidth=0.5)
    inset.set_title("Payout ladder", fontsize=7, color=INK, pad=3)
    inset.set_ylabel("% funded paths", fontsize=5.7, color=MUTED)
    for i, rate in enumerate(payout_rates):
        inset.text(i + 1, rate + 2, f"{rate:.0f}%", ha="center", fontsize=5.4, color=INK)

    sim = prop["sim"]
    summary = prop["summary"]
    funded = prop["funded"]
    for xi, rate in zip(x, rates):
        ax.annotate(f"{rate:.0f}%", (xi, rate), xytext=(0, 5), textcoords="offset points",
                    ha="center", fontsize=5.8, color=INK)
    ax.text(
        0.02, 0.98,
        f"${prop['rules'].start / 1000:.0f}k start · +${prop['rules'].target:,.0f} target · "
        f"${prop['rules'].max_dd:,.0f} EOD trail · ${abs(prop['rules'].soft_stop):,.0f} daily stop",
        transform=ax.transAxes, va="top", fontsize=5.9, color=INK,
    )
    ax.text(
        0.02, 0.89,
        f"10k paths · 10-session blocks · 750-session horizon\n"
        f"Base: {sim['pass_rate']:.1f}% pass / {sim['fail_rate']:.1f}% breach / "
        f"{sim['open_rate']:.1f}% open · median pass {summary['pass_med']:.0f} sessions",
        transform=ax.transAxes, va="top", fontsize=5.9, color=INK,
    )
    ax.text(
        0.02, -0.24,
        f"Funded ladder: {prop['funded_rules'].min_profit_days} qualifying days / "
        f"{prop['funded_rules'].cycle_sessions}-session cycle; payout rules assumed. "
        "Not live probabilities. Simulator omits consistency and contract caps; verify current firm terms.",
        transform=ax.transAxes, ha="left", va="top", fontsize=5.9, color=ORANGE, wrap=True,
    )


def _draw_coverage(fig: plt.Figure, data: dict, prop: dict) -> None:
    canonical = data["canonical"]
    footer = (
        f"PROVENANCE | {canonical.run_id} | {canonical.strategy_id} | {canonical.methodology} | "
        f"{canonical.date_start} to {canonical.date_end} ({canonical.days_count} calendar days) | "
        f"{canonical.data_path} SHA-256 {data['data_hash']} | "
        f"NQ benchmark SHA-256 {data['benchmark_sha']} | "
        f"parameter sweep CSV SHA-256 {data['plateau_sha']} | Git {canonical.git_commit} | "
        f"{canonical.slippage_model} + {canonical.commission_model} [NET] | "
        f"Warning flags: {', '.join(canonical.warnings) if canonical.warnings else 'None'}"
    )
    fig.text(0.035, 0.046, footer, fontsize=6.1, color=MUTED, va="top", wrap=True)
    fig.text(
        0.035, 0.021,
        "Read carefully: the canonical provenance record is multi-year walk-forward, but fold exports are absent; "
        "the year bars and DEV/HOLDOUT split are not labeled as individual walk-forward folds. "
        "All resampling/stress outputs are conditional model evidence, not guarantees.",
        fontsize=6.2, color="#9a4f15", va="top", wrap=True,
    )


def main() -> None:
    if OUT_PATH.exists():
        raise FileExistsError(f"Refusing to overwrite existing dashboard: {OUT_PATH}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = _load_inputs()
    trades = data["trades"]
    prop = _run_prop_stress(trades, data["calendar"])

    # These diagnostics operate on the saved canonical NET ledger; no strategy is re-run.
    dd_samples = da.reshuffled_max_drawdowns(
        trades["research_pnl"].to_numpy(dtype=float), n=3000, seed=42
    )
    wins = trades[trades["research_pnl"] > 0]
    remove_count = max(1, int(math.ceil(0.05 * len(wins))))
    remove_indices = wins.nlargest(remove_count, "research_pnl").index
    trimmed = trades.drop(index=remove_indices)
    trimmed_pnl = trimmed["research_pnl"].to_numpy(dtype=float)
    trim = {
        "removed_count": remove_count,
        "base_net": float(trades["research_pnl"].sum()),
        "trimmed_net": float(trimmed_pnl.sum()),
        "trimmed_pf": da.profit_factor(trimmed_pnl),
    }

    fig = plt.figure(figsize=(24, 21), dpi=160, facecolor=PAPER)
    _draw_header(fig, data, prop)
    gs = fig.add_gridspec(
        4, 3,
        left=0.035, right=0.965, top=0.865, bottom=0.135,
        hspace=0.52, wspace=0.28,
        height_ratios=[1.35, 1.0, 1.0, 1.02],
    )
    equity_grid = gs[0, :2].subgridspec(2, 1, height_ratios=[3.2, 0.85], hspace=0.08)
    _draw_equity(fig.add_subplot(equity_grid[0]), data)
    _draw_drawdown(fig.add_subplot(equity_grid[1]), data)
    _draw_oos(fig.add_subplot(gs[0, 2]), data)
    _draw_yearly(fig.add_subplot(gs[1, 0]), data)
    _draw_parameter_heatmap(fig.add_subplot(gs[1, 1]), data)
    _draw_monte_carlo(fig.add_subplot(gs[1, 2]), data, dd_samples)
    _draw_execution_stress(fig.add_subplot(gs[2, 0]), data, trim)
    _draw_regimes(fig.add_subplot(gs[2, 1]), data)
    _draw_prop(fig.add_subplot(gs[2, 2]), prop)

    # The last row is a visual validation checklist, not another metric table.
    coverage_ax = fig.add_subplot(gs[3, :])
    coverage_ax.set_axis_off()
    coverage_ax.text(0.01, 0.88, "EVIDENCE MAP", fontsize=12, color=NAVY, fontweight="bold")
    cards = [
        ("GENERALIZATION", "Verified walk-forward baseline\nDEV vs 2025–26 holdout\nAnnual chronological slices"),
        ("PARAMETER ROBUSTNESS", "45 saved evaluations\n9 parameters × 5 perturbations\nPF heatmap vs breakeven"),
        ("ADVERSARIAL / EXECUTION", "Top 5% winners removed\nExtra adverse tick sensitivity\nMarkov regime stress"),
        ("SEQUENCE / ACCOUNT RISK", "3,000 trade-order reshuffles\n10,000 prop evaluation paths\nConditional payout ladder"),
        ("EVIDENCE GAPS", "No fold-level CSV saved\nNo canonical WF permutation /\nplacebo report in results"),
    ]
    card_x = [0.01, 0.21, 0.41, 0.61, 0.81]
    for x, (heading, detail) in zip(card_x, cards):
        coverage_ax.add_patch(plt.Rectangle(
            (x, 0.18), 0.18, 0.56, transform=coverage_ax.transAxes,
            facecolor="white", edgecolor=GRID, linewidth=0.8,
        ))
        coverage_ax.text(x + 0.012, 0.64, heading, transform=coverage_ax.transAxes,
                         fontsize=8, fontweight="bold", color=TEAL, va="top")
        coverage_ax.text(x + 0.012, 0.49, detail, transform=coverage_ax.transAxes,
                         fontsize=7, color=INK, va="top", linespacing=1.5)

    _draw_coverage(fig, data, prop)
    fig.savefig(OUT_PATH, dpi=160, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print(f"Created: {OUT_PATH.relative_to(REPO_ROOT)}")
    print("Evidence panels: equity/drawdown, DEV-holdout, annual slices, parameter plateau, "
          "trade-order Monte Carlo, execution/outlier stress, Markov regimes, prop bootstrap/payouts")


if __name__ == "__main__":
    main()
