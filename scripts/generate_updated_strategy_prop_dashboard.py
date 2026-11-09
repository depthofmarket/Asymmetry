#!/usr/bin/env python3
"""Generate a new combined strategy-metrics and prop-firm dashboard PNG."""

from __future__ import annotations

from datetime import datetime
import hashlib
import math
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest import dashboard_analytics as da
from backtest import metrics as bm

DATA_PATH = da.DEFAULT_TRADES_PATH
CALENDAR_PATH = da.DEFAULT_CALENDAR_SOURCE
OUT_DIR = REPO_ROOT / "results" / "strategy_dashboard_v3"
OUT_PATH = OUT_DIR / (
    f"updated_strategy_prop_metrics_dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
)

METRIC_FAMILIES = [
    ("Return & capital", [
        "net_pnl", "gross_profit", "gross_loss", "annual_pnl", "annual_return_pct", "cagr",
        "daily_avg_pnl", "traded_session_avg_pnl", "median_daily_pnl", "benchmark_relative_return",
        "beta", "alpha", "correlation", "tracking_error", "up_capture", "down_capture",
    ]),
    ("Risk-adjusted ratios", [
        "sharpe_ratio", "excess_sharpe", "sortino_ratio", "calmar_ratio", "omega_ratio",
        "gain_to_pain_ratio", "ulcer_performance_index", "sterling_ratio", "burke_ratio",
        "modified_burke_ratio", "kappa_three_ratio", "adjusted_sharpe_ratio",
        "information_ratio", "treynor_ratio",
    ]),
    ("Drawdown & recovery", [
        "max_drawdown", "max_drawdown_pct", "avg_drawdown", "longest_dd_calendar_days",
        "longest_dd_sessions", "avg_dd_duration_days", "ulcer_index", "pain_index",
        "underwater_pct", "recovery_factor", "intraday_to_eod_dd_divergence",
        "avg_recovery_time_days",
    ]),
    ("Tail risk & VaR", [
        "var_95_parametric", "var_99_parametric", "var_95_historical", "var_99_historical",
        "cornish_fisher_var_95", "cvar_95", "cvar_99", "cvar_95_traded",
        "tail_risk_ratio", "worst_day_pnl",
    ]),
    ("Trade edge & outliers", [
        "total_trades", "win_rate", "loss_rate", "scratch_rate", "profit_factor",
        "payoff_ratio", "expectancy", "expectancy_score", "median_trade", "avg_win",
        "avg_loss", "largest_win", "largest_win_pct_of_net", "largest_loss", "top_5_wins_pct",
        "trimmed_profit_factor", "trimmed_profit_factor_5pct", "trimmed_net_5pct",
        "trimmed_win_rate_5pct", "trimmed_expectancy_5pct", "trimmed_removed_count_5pct",
        "trimmed_removed_profit_5pct", "edge_holds_5pct",
    ]),
    ("Directional symmetry", [
        "number_of_long_trades", "number_of_short_trades", "number_of_long_trades_closed",
        "number_of_short_trades_closed", "winning_long_trades", "losing_long_trades",
        "winning_short_trades", "losing_short_trades", "long_win_rate", "short_win_rate",
        "long_profit_factor", "short_profit_factor", "long_net_pnl", "short_net_pnl",
        "long_short_edge_asymmetry",
    ]),
    ("Statistical moments & significance", [
        "trade_skew", "trade_kurtosis", "daily_skew", "daily_kurtosis", "t_statistic",
        "p_value", "sqn", "jarque_bera_stat",
    ]),
    ("Selection bias controls", [
        "probabilistic_sharpe_ratio", "deflated_sharpe", "expected_max_sharpe",
        "min_track_record_length_years", "sharpe_haircut_pct", "spa_p_value",
    ]),
    ("Sizing & risk of ruin", [
        "full_kelly_fraction", "half_kelly", "analytical_risk_of_ruin",
        "empirical_bootstrap_ruin_pct", "max_win_streak", "max_loss_streak",
        "optimal_fixed_fraction", "margin_utilization_pct",
    ]),
    ("Excursion, duration & exposure", [
        "mean_mfe", "mean_mae", "max_mfe", "max_mae", "mfe_mae_ratio",
        "edge_efficiency_ratio", "adverse_stop_realization_rate", "market_exposure_pct",
        "exposure_ratio", "turnover_ratio", "avg_hold_time_mins", "avg_win_duration_mins",
        "avg_loss_duration_mins", "holding_duration_asymmetry",
    ]),
    ("Trading cadence", [
        "trades_per_day", "trades_per_week", "trades_per_month", "trades_per_year",
    ]),
    ("Calendar periodicity", [
        "percentage_winning_months", "percentage_winning_years",
        "avg_monthly_pnl_winning_months", "avg_monthly_pnl_losing_months",
        "best_month_pnl", "worst_month_pnl", "best_year_pnl", "worst_year_pnl",
    ]),
    ("Walk-forward stability", [
        "return_consistency", "win_rate_consistency", "sharpe_consistency",
        "consistency_score", "stability_score",
    ]),
]

ALIASES = {
    "cagr": "annual_return_pct",
    "benchmark_relative_return": "net_pnl",
    "excess_sharpe": "sharpe_ratio",
    "information_ratio": "sharpe_ratio",
    "treynor_ratio": "sharpe_ratio",
    "cvar_95_traded": "cvar_95",
    "spa_p_value": "p_value",
    "optimal_fixed_fraction": "half_kelly",
    "stability_score": "consistency_score",
}

UNMEASURED = {
    "intraday_to_eod_dd_divergence",
    "empirical_bootstrap_ruin_pct",
    "margin_utilization_pct",
    "mean_mfe",
    "mean_mae",
    "max_mfe",
    "max_mae",
    "mfe_mae_ratio",
    "edge_efficiency_ratio",
    "adverse_stop_realization_rate",
    "market_exposure_pct",
    "exposure_ratio",
    "avg_hold_time_mins",
    "avg_win_duration_mins",
    "avg_loss_duration_mins",
    "holding_duration_asymmetry",
}

CURRENCY_METRICS = {
    "net_pnl", "gross_profit", "gross_loss", "annual_pnl", "daily_avg_pnl",
    "traded_session_avg_pnl", "median_daily_pnl", "alpha", "max_drawdown",
    "avg_drawdown", "var_95_parametric", "var_99_parametric", "var_95_historical",
    "var_99_historical", "cornish_fisher_var_95", "cvar_95", "cvar_99",
    "cvar_95_traded", "worst_day_pnl", "expectancy", "median_trade", "avg_win",
    "avg_loss", "largest_win", "largest_loss", "trimmed_net_5pct",
    "trimmed_expectancy_5pct", "trimmed_removed_profit_5pct", "long_net_pnl",
    "short_net_pnl", "mean_mfe", "mean_mae", "max_mfe", "max_mae",
    "best_month_pnl", "worst_month_pnl", "best_year_pnl", "worst_year_pnl",
}

PERCENT_METRICS = {
    "annual_return_pct", "max_drawdown_pct", "underwater_pct", "win_rate",
    "loss_rate", "scratch_rate", "largest_win_pct_of_net", "top_5_wins_pct",
    "trimmed_win_rate_5pct", "sharpe_haircut_pct", "market_exposure_pct",
    "percentage_winning_months", "percentage_winning_years",
}

FRACTION_METRICS = {
    "full_kelly_fraction", "half_kelly", "analytical_risk_of_ruin",
    "empirical_bootstrap_ruin_pct",
}


def _format_metric(key: str, value: object, status: str) -> str:
    if status != "OBSERVED / DERIVED":
        return "—"
    if isinstance(value, (bool, np.bool_)):
        return "YES" if value else "NO"
    if value is None or pd.isna(value):
        return "N/A"
    number = float(value)
    if not math.isfinite(number):
        return "∞" if number > 0 else "—"
    if key in CURRENCY_METRICS:
        return f"-${abs(number):,.2f}" if number < 0 else f"${number:,.2f}"
    if key in PERCENT_METRICS:
        return f"{number:.1f}%"
    if key in FRACTION_METRICS:
        return f"{number * 100:.2f}%"
    if key in {"total_trades", "number_of_long_trades", "number_of_short_trades",
               "number_of_long_trades_closed", "number_of_short_trades_closed",
               "winning_long_trades", "losing_long_trades", "winning_short_trades",
               "losing_short_trades", "trimmed_removed_count_5pct", "max_win_streak",
               "max_loss_streak", "longest_dd_calendar_days", "longest_dd_sessions"}:
        return f"{number:,.0f}"
    return f"{number:.3f}"


def _metric_status(key: str) -> str:
    if key in UNMEASURED:
        return "NOT MEASURED"
    if key in ALIASES:
        return f"ALIAS → {ALIASES[key]}"
    return "OBSERVED / DERIVED"


def _load_metrics() -> tuple[pd.DataFrame, list[str], dict[str, dict], np.ndarray, str]:
    trades = da.load_trades(DATA_PATH)
    calendar = da.load_session_calendar(CALENDAR_PATH, trades["date"].min(), trades["date"].max())
    nq = pd.read_parquet(CALENDAR_PATH, columns=["time", "close"])
    nq["date"] = pd.to_datetime(nq["time"]).dt.strftime("%Y-%m-%d")
    nq = nq[(nq["date"] >= calendar[0]) & (nq["date"] <= calendar[-1])]
    close_by_day = nq.groupby("date")["close"].last()
    benchmark = pd.Series(index=calendar, dtype=float)
    for day in calendar:
        if day in close_by_day.index:
            benchmark.loc[day] = close_by_day.loc[day]
    benchmark = benchmark.ffill().bfill().pct_change().fillna(0.0).to_numpy(dtype=float)

    metrics_by_label: dict[str, dict] = {}
    groups = [
        ("COMPOSITE", trades),
        ("MORNING VA", trades[trades["strat"] == "S1"]),
        ("MACRO MOMENTUM", trades[trades["strat"] == "S3"]),
        ("GOLD FIX", trades[trades["strat"] == "S2"]),
    ]
    for label, group in groups:
        pnl = group["research_pnl"].to_numpy(dtype=float)
        daily = da.daily_series(group, calendar, "research_pnl")
        daily.index = pd.to_datetime(daily.index)
        input_trades = group.assign(pnl=group["research_pnl"])
        metrics_by_label[label] = bm.calculate_institutional_metrics(
            trades=input_trades,
            daily_returns=daily,
            capital=25_000.0,
            benchmark_daily_returns=benchmark,
        )
    digest = hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()
    return trades, calendar, metrics_by_label, benchmark, digest


def _prop_summary(trades: pd.DataFrame, calendar: list[str]) -> dict:
    legs = da.build_session_legs(trades, calendar)
    rules = da.PropRules()
    funded_rules = da.FundedRules()
    runs = da.bootstrap_prop(
        legs,
        da.POLICIES["live_ratchet"],
        n_sims=10_000,
        block=10,
        horizon=750,
        rules=rules,
        n_paths=0,
        seed=42,
        funded=funded_rules,
        funded_horizon=252,
    )
    summary = da.summarize_prop(runs, 365.25 / 252.0)
    chronological = da.chronological_prop(legs, calendar, da.POLICIES["live_ratchet"], rules)
    funded = da.funded_summary(runs["funded"], runs["pass_rate"], rules.eval_fee)
    return {
        "rules": rules,
        "funded_rules": funded_rules,
        "runs": runs,
        "summary": summary,
        "chronological": chronological,
        "funded": funded,
    }


def _draw_prop_panel(ax, prop: dict) -> None:
    rules = prop["rules"]
    funded_rules = prop["funded_rules"]
    summary = prop["summary"]
    runs = prop["runs"]
    funded = prop["funded"]
    chrono = prop["chronological"]["back_to_back"]
    chrono_pass = int((chrono["status"] == "pass").sum())
    chrono_fail = int((chrono["status"] == "fail").sum())
    funded_n = int(funded.get("n", 0))
    ladder = funded.get("ladder", {})
    ev = float(funded.get("ev_per_attempt", np.nan))

    ax.set_axis_off()
    ax.text(0.0, 1.0, "PROP-FIRM METRICS  |  LUCIDFLEX 25K PROFILE",
            fontsize=15, fontweight="bold", color="#0f172a", va="top")

    rule_lines = [
        ("Evaluation rules", [
            f"Start ${rules.start:,.0f}  |  Target +${rules.target:,.0f} ({rules.target / rules.start:.1%})",
            f"EOD trailing DD ${rules.max_dd:,.0f}  |  Initial floor ${rules.start - rules.max_dd:,.0f}",
            f"Floor locks at ${rules.floor_lock:,.0f} after peak reaches ${rules.peak_for_lock:,.0f}",
            f"Daily soft stop -${abs(rules.soft_stop):,.0f}  |  Evaluation fee ${rules.eval_fee:.0f} (assumption)",
        ]),
        ("Evaluation outcomes", [
            f"10,000 block-bootstrap paths; 10-session blocks; 750-session horizon; seed 42",
            f"Pass {runs['pass_rate']:.1f}%  |  breach {runs['fail_rate']:.1f}%  |  open {runs['open_rate']:.1f}%",
            f"Median pass duration {summary['pass_med']:.0f} sessions ({summary['pass_med_cal_days']:.0f} calendar days)",
            f"Chronological replay: {chrono_pass} pass / {chrono_fail} breach / {len(chrono) - chrono_pass - chrono_fail} open",
        ]),
        ("Funded payout model — assumed, not broker-observed", [
            f"Eligibility cycle {funded_rules.cycle_sessions} sessions; {funded_rules.min_profit_days} days >= ${funded_rules.profit_day_threshold:.0f}",
            f"Withdrawal = min(${funded_rules.max_payout:.0f}, {funded_rules.payout_fraction:.0%} of profit); split {funded_rules.split:.0%}",
            f"Minimum withdrawal ${funded_rules.min_payout:.0f}; max {funded_rules.max_payouts} payouts; post-payout floor ${funded_rules.post_payout_floor:,.0f}",
            f"Conditional funded paths: {funded_n:,}  |  zero-payout {funded.get('zero_payout_pct', np.nan):.1f}%",
            f"Reach payout #1: {ladder.get(1, np.nan):.1f}%  |  reach payout #5: {ladder.get(5, np.nan):.1f}%",
            f"Mean / median net payout: ${funded.get('mean_net', np.nan):,.0f} / ${funded.get('median_net', np.nan):,.0f}",
            f"Modeled net EV per evaluation attempt: ${ev:,.0f} after assumed ${rules.eval_fee:.0f} fee",
        ]),
    ]
    x_positions = [0.0, 0.34, 0.68]
    widths = [0.30, 0.30, 0.32]
    for x, width, (heading, lines) in zip(x_positions, widths, rule_lines):
        ax.text(x, 0.82, heading, fontsize=9.5, fontweight="bold", color="#0f766e", va="top")
        ax.text(x, 0.72, "\n".join(lines), fontsize=7.1, color="#334155",
                va="top", linespacing=1.6, wrap=True)
    ax.text(
        0.0, 0.015,
        "Important boundary: this simulator does not enforce the 40% consistency cap or firm contract cap; "
        "funded payout terms above are model assumptions and must be checked against the current firm rulebook.",
        fontsize=7.2, color="#b45309", fontweight="bold", va="bottom",
    )


def _draw_metric_table(ax, metrics_by_label: dict[str, dict]) -> None:
    ax.set_axis_off()
    keys = [key for _, family_keys in METRIC_FAMILIES for key in family_keys]
    available = set.intersection(*(set(values) for values in metrics_by_label.values()))
    missing = [key for key in keys if key not in available]
    if missing:
        raise ValueError(f"Metric implementation no longer supplies expected fields: {missing}")

    rows = []
    for family, family_keys in METRIC_FAMILIES:
        for key in family_keys:
            status = _metric_status(key)
            rows.append([
                family,
                key.replace("_", " "),
                status,
                *[_format_metric(key, metrics_by_label[label][key], status)
                  for label in ("COMPOSITE", "MORNING VA", "MACRO MOMENTUM", "GOLD FIX")],
            ])

    table = ax.table(
        cellText=rows,
        colLabels=["Metric family", "Quantitative metric", "Evidence status",
                   "Ensemble", "Morning VA", "Macro Momentum", "Gold Fix"],
        colWidths=[0.17, 0.26, 0.17, 0.10, 0.10, 0.10, 0.10],
        cellLoc="left",
        loc="upper left",
        bbox=[0.0, 0.0, 1.0, 1.0],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(6.7)
    table.scale(1.0, 1.07)
    family_color = {
        "Return & capital": "#dbeafe",
        "Risk-adjusted ratios": "#e0f2fe",
        "Drawdown & recovery": "#fee2e2",
        "Tail risk & VaR": "#ffedd5",
        "Trade edge & outliers": "#dcfce7",
        "Directional symmetry": "#f3e8ff",
        "Statistical moments & significance": "#fef9c3",
        "Selection bias controls": "#ccfbf1",
        "Sizing & risk of ruin": "#fce7f3",
        "Excursion, duration & exposure": "#e2e8f0",
        "Trading cadence": "#f1f5f9",
        "Calendar periodicity": "#ecfccb",
        "Walk-forward stability": "#cffafe",
    }
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#cbd5e1")
        cell.set_linewidth(0.25)
        if row == 0:
            cell.set_facecolor("#0f172a")
            cell.set_text_props(color="white", weight="bold", fontsize=7)
            cell.set_height(0.025)
            if col >= 3:
                cell.get_text().set_ha("right")
        else:
            data = rows[row - 1]
            cell.set_facecolor(family_color[data[0]] if row % 2 else "#ffffff")
            if col == 0:
                cell.set_text_props(weight="bold", color="#334155")
            elif col == 2:
                color = "#b45309" if data[2] != "OBSERVED / DERIVED" else "#166534"
                cell.set_text_props(color=color, fontsize=6.1)
            elif col >= 3:
                cell.get_text().set_ha("right")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUT_PATH.exists():
        raise FileExistsError(f"Refusing to overwrite existing dashboard: {OUT_PATH}")

    trades, calendar, metrics_by_label, _, data_hash = _load_metrics()
    prop = _prop_summary(trades, calendar)
    n_metrics = sum(len(items) for _, items in METRIC_FAMILIES)
    if n_metrics != 143:
        raise ValueError(f"Expected 143 metric fields, configured {n_metrics}")

    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": "#0f172a"})
    fig = plt.figure(figsize=(24, 43), dpi=150, facecolor="#f8fafc")
    fig.text(0.045, 0.985, "STRATEGY + PROP-FIRM QUANTITATIVE DASHBOARD",
             fontsize=21, fontweight="bold", color="#0f172a", va="top")
    fig.text(
        0.045, 0.975,
        f"143-metric inventory | saved canonical trade ledger | {calendar[0]} to {calendar[-1]} "
        f"| {len(calendar):,} exchange sessions incl. flat sessions | {len(trades):,} trades",
        fontsize=9.5, color="#475569", va="top",
    )
    prop_ax = fig.add_axes([0.045, 0.866, 0.91, 0.095])
    _draw_prop_panel(prop_ax, prop)

    metric_ax = fig.add_axes([0.045, 0.103, 0.91, 0.744])
    _draw_metric_table(metric_ax, metrics_by_label)

    foot_text = (
        "PROVENANCE | Run IDs: run_canonical_lucid_flex_ensemble_2021_2026; "
        "run_canonical_s1_va_breakout_2021_2026; run_canonical_s2_macro_momentum_2021_2026; "
        "run_canonical_s3_gold_london_fix_2021_2026 | Multi-year walk-forward source ledger; "
        "metrics derived from saved NET trades | Data: data/processed/"
        "unified_three_strategy_markov_portfolio_trades_2021_2026.parquet | "
        f"SHA-256 {data_hash} | Git bfff4aac09 | 2021-01-07 to 2026-10-30 (2,423 calendar days) | "
        "Costs already embedded: adverse execution + $1.40 RT micro commission | "
        "Warning flags: none on verified canonical runs. DSR uses assumed N=33 trials and variance 0.5. "
        "ALIAS and NOT MEASURED rows are intentionally not presented as independent observed evidence."
    )
    fig.text(0.045, 0.075, foot_text, fontsize=6.5, color="#334155",
             va="top", wrap=True, linespacing=1.45)
    fig.text(
        0.045, 0.029,
        "Prop simulation is a new model run, not a new backtest: 10,000 block-bootstrap paths, "
        "10-session blocks, 750-session evaluation horizon, seed 42; funded phase is conditional "
        "and uses assumed payout rules shown above. Monte Carlo outcomes are not guarantees.",
        fontsize=6.8, color="#9a3412", va="bottom", wrap=True,
    )
    fig.savefig(OUT_PATH, dpi=150, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print(f"Created: {OUT_PATH.relative_to(REPO_ROOT)}")
    print(f"Metric rows: {n_metrics} | Prop Monte Carlo paths: {len(prop['runs']['status']):,}")


if __name__ == "__main__":
    main()
