from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TradeSummaryPaths:
    by_setup_csv: Path
    by_setup_hour_csv: Path
    by_setup_reason_csv: Path


@dataclass(frozen=True)
class RobustnessReportPaths:
    quality_metrics_csv: Path
    period_summary_csv: Path
    setup_period_csv: Path
    context_summary_csv: Path
    day_of_week_csv: Path
    time_stability_csv: Path
    rolling_edge_csv: Path
    drawdown_periods_csv: Path
    tail_risk_csv: Path
    mae_mfe_csv: Path
    outlier_dependence_csv: Path
    dependency_csv: Path


@dataclass(frozen=True)
class ConditionalDistributionReportPaths:
    summary_csv: Path
    period_stability_csv: Path
    warnings_csv: Path
    report_md: Path


DEFAULT_CONDITIONING_SETS: tuple[tuple[str, ...], ...] = (
    ("setup_tag",),
    ("signal_type",),
    ("direction",),
    ("entry_hour",),
    ("entry_day_of_week",),
    ("entry_day_regime",),
    ("entry_vwap_side",),
    ("entry_vwap_side_prev",),
    ("entry_vwap_cross_direction",),
    ("entry_open_context",),
    ("entry_gap_inventory_alignment",),
    ("entry_overnight_inventory_direction",),
    ("entry_markov_state_label",),
    ("entry_markov_state",),
    ("entry_market_memory_state",),
    ("entry_market_memory_hurst_regime",),
    ("entry_market_memory_entropy_regime",),
    ("entry_market_memory_lz_regime",),
    ("entry_market_memory_tail_alpha_regime",),
    ("entry_hawkes_momentum_signal",),
    ("entry_vsa_absorption",),
    ("entry_vsa_thin_move",),
    ("entry_options_gex_regime",),
    ("entry_options_gamma_environment",),
    ("setup_tag", "entry_day_regime"),
    ("setup_tag", "entry_vwap_side"),
    ("setup_tag", "entry_vwap_cross_direction"),
    ("setup_tag", "entry_open_context"),
    ("setup_tag", "entry_markov_state_label"),
    ("setup_tag", "entry_market_memory_state"),
    ("setup_tag", "entry_market_memory_hurst_regime"),
    ("setup_tag", "entry_options_gex_regime"),
    ("setup_tag", "entry_options_gamma_environment"),
    ("signal_type", "entry_markov_state_label"),
    ("signal_type", "entry_market_memory_state"),
    ("signal_type", "entry_options_gex_regime"),
    ("signal_type", "entry_options_gamma_environment"),
    ("setup_tag", "entry_hour"),
    ("direction", "entry_day_regime"),
    ("direction", "entry_vwap_side"),
    ("direction", "entry_markov_state_label"),
    ("direction", "entry_market_memory_state"),
)


def _profit_factor_from_pnl(pnl: pd.Series) -> float:
    wins = float(pnl[pnl > 0].sum())
    losses = abs(float(pnl[pnl <= 0].sum()))
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def _summarize(grouped: pd.core.groupby.generic.DataFrameGroupBy) -> pd.DataFrame:
    summary = grouped.apply(
        lambda g: pd.Series(
            {
                "trades": int(len(g)),
                "wins": int((g["pnl"] > 0).sum()),
                "losses": int((g["pnl"] <= 0).sum()),
                "win_rate_pct": float((g["pnl"] > 0).mean() * 100.0),
                "total_pnl": float(g["pnl"].sum()),
                "avg_pnl": float(g["pnl"].mean()),
                "median_pnl": float(g["pnl"].median()),
                "avg_win": float(g.loc[g["pnl"] > 0, "pnl"].mean()) if (g["pnl"] > 0).any() else np.nan,
                "avg_loss": float(g.loc[g["pnl"] <= 0, "pnl"].mean()) if (g["pnl"] <= 0).any() else np.nan,
                "profit_factor": _profit_factor_from_pnl(g["pnl"]),
                "expectancy": float(g["pnl"].mean()),
                "avg_hold_minutes": float(g["hold_minutes"].mean()) if "hold_minutes" in g.columns else np.nan,
            }
        )
    )
    if isinstance(summary.index, pd.MultiIndex):
        summary = summary.reset_index()
    else:
        summary = summary.reset_index(names=[summary.index.name or "group"])
    return summary.sort_values(["total_pnl", "profit_factor"], ascending=[False, False])


def _prepare_trades(trades_df: pd.DataFrame) -> pd.DataFrame:
    df = trades_df.copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["pnl"] = df["pnl"].astype(float)
    df["entry_hour"] = df["entry_time"].dt.hour
    df["entry_date"] = df["entry_time"].dt.normalize()
    df["exit_date"] = df["exit_time"].dt.normalize()
    df["entry_year"] = df["entry_time"].dt.year
    df["entry_month"] = df["entry_time"].dt.to_period("M").dt.to_timestamp()
    df["entry_quarter"] = df["entry_time"].dt.to_period("Q").astype(str)
    df["entry_day_of_week"] = df["entry_time"].dt.day_name()
    df["entry_day_of_week_num"] = df["entry_time"].dt.dayofweek
    df["market_era"] = np.where(df["entry_year"] < 2020, "pre_2020", "post_2020")
    if "hold_minutes" not in df.columns:
        df["hold_minutes"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 60.0
    if "setup_tag" not in df.columns:
        df["setup_tag"] = "unknown"
    if "reason" not in df.columns:
        df["reason"] = "unknown"
    return df.sort_values("exit_time").reset_index(drop=True)


def _years_covered(df: pd.DataFrame) -> float:
    if df.empty:
        return 1.0
    span_days = (df["exit_time"].max() - df["entry_time"].min()).total_seconds() / (24 * 3600)
    return max(1.0 / 252.0, float(span_days / 365.25))


def _max_drawdown_from_equity(equity: pd.Series) -> tuple[float, float]:
    if equity.empty:
        return 0.0, 0.0
    peak = equity.cummax()
    dd_dollars = peak - equity
    dd_pct = np.where(peak > 0, dd_dollars / peak * 100.0, 0.0)
    return float(dd_dollars.max()), float(np.nanmax(dd_pct))


def _annualized_sharpe(returns: pd.Series) -> float:
    returns = returns.dropna()
    if len(returns) < 2 or returns.std() <= 0:
        return np.nan
    return float(returns.mean() / returns.std() * np.sqrt(252))


def _annualized_sortino(returns: pd.Series) -> float:
    returns = returns.dropna()
    downside = returns[returns < 0]
    if len(returns) < 2 or len(downside) < 2 or downside.std() <= 0:
        return np.nan
    return float(returns.mean() / downside.std() * np.sqrt(252))


def _ulcer_index_pct(equity: pd.Series) -> float:
    if equity.empty:
        return np.nan
    peak = equity.cummax()
    dd_pct = np.where(peak > 0, (equity - peak) / peak * 100.0, 0.0)
    return float(np.sqrt(np.mean(np.square(dd_pct))))


def _quality_metrics(df: pd.DataFrame, starting_capital: float) -> dict[str, float | int | str]:
    daily_pnl = df.groupby("exit_date")["pnl"].sum().sort_index()
    weekly_pnl = df.groupby(df["exit_time"].dt.to_period("W").dt.start_time)["pnl"].sum().sort_index()
    monthly_pnl = df.groupby("entry_month")["pnl"].sum().sort_index()
    yearly_pnl = df.groupby("entry_year")["pnl"].sum().sort_index()
    daily_equity = daily_pnl.cumsum() + float(starting_capital)
    daily_returns = daily_equity.pct_change().dropna()
    max_dd_dollars, max_dd_pct = _max_drawdown_from_equity(daily_equity)

    net_profit = float(df["pnl"].sum())
    final_equity = float(starting_capital + net_profit)
    years = _years_covered(df)
    cagr = ((final_equity / starting_capital) ** (1.0 / years) - 1.0) if starting_capital > 0 and final_equity > 0 else np.nan
    gross_win = float(df.loc[df["pnl"] > 0, "pnl"].sum())
    gross_loss = abs(float(df.loc[df["pnl"] <= 0, "pnl"].sum()))
    avg_win = float(df.loc[df["pnl"] > 0, "pnl"].mean()) if (df["pnl"] > 0).any() else np.nan
    avg_loss = float(df.loc[df["pnl"] <= 0, "pnl"].mean()) if (df["pnl"] <= 0).any() else np.nan
    avg_loss_abs = abs(avg_loss) if not np.isnan(avg_loss) else np.nan

    return {
        "first_entry": str(df["entry_time"].min()),
        "last_exit": str(df["exit_time"].max()),
        "years_covered": years,
        "trades": int(len(df)),
        "net_profit": net_profit,
        "final_equity": final_equity,
        "total_return_pct": (net_profit / starting_capital * 100.0) if starting_capital else np.nan,
        "cagr_pct": float(cagr * 100.0) if not np.isnan(cagr) else np.nan,
        "avg_trade": float(df["pnl"].mean()),
        "median_trade": float(df["pnl"].median()),
        "gross_win": gross_win,
        "gross_loss": gross_loss,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else np.nan,
        "win_rate_pct": float((df["pnl"] > 0).mean() * 100.0),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": (avg_win / avg_loss_abs) if avg_loss_abs and avg_loss_abs > 0 else np.nan,
        "net_profit_to_max_drawdown": (net_profit / max_dd_dollars) if max_dd_dollars > 0 else np.nan,
        "max_drawdown_dollars": max_dd_dollars,
        "max_drawdown_pct": max_dd_pct,
        "daily_sharpe": _annualized_sharpe(daily_returns),
        "daily_sortino": _annualized_sortino(daily_returns),
        "calmar": (float(cagr * 100.0) / max_dd_pct) if max_dd_pct > 0 and not np.isnan(cagr) else np.nan,
        "ulcer_index_pct": _ulcer_index_pct(daily_equity),
        "avg_daily_pnl": float(daily_pnl.mean()) if not daily_pnl.empty else np.nan,
        "avg_monthly_pnl": float(monthly_pnl.mean()) if not monthly_pnl.empty else np.nan,
        "avg_yearly_pnl": float(yearly_pnl.mean()) if not yearly_pnl.empty else np.nan,
        "worst_day_pnl": float(daily_pnl.min()) if not daily_pnl.empty else np.nan,
        "worst_week_pnl": float(weekly_pnl.min()) if not weekly_pnl.empty else np.nan,
        "worst_month_pnl": float(monthly_pnl.min()) if not monthly_pnl.empty else np.nan,
        "best_day_pnl": float(daily_pnl.max()) if not daily_pnl.empty else np.nan,
        "best_week_pnl": float(weekly_pnl.max()) if not weekly_pnl.empty else np.nan,
        "best_month_pnl": float(monthly_pnl.max()) if not monthly_pnl.empty else np.nan,
        "winning_years": int((yearly_pnl > 0).sum()),
        "losing_years": int((yearly_pnl <= 0).sum()),
        "pct_years_profitable": float((yearly_pnl > 0).mean() * 100.0) if not yearly_pnl.empty else np.nan,
    }


def _export_quality_metrics(df: pd.DataFrame, path: Path, starting_capital: float) -> None:
    if df.empty:
        pd.DataFrame().to_csv(path, index=False)
        return
    pd.DataFrame([_quality_metrics(df, starting_capital=starting_capital)]).to_csv(path, index=False)


def _summarize_period(df: pd.DataFrame, by: list[str], period_type: str) -> pd.DataFrame:
    summary = _summarize(df.groupby(by, dropna=False))
    summary.insert(0, "period_type", period_type)
    return summary


def _export_period_summaries(df: pd.DataFrame, path: Path) -> None:
    if df.empty:
        pd.DataFrame().to_csv(path, index=False)
        return

    pieces = [
        _summarize_period(df, ["entry_year"], "year").rename(columns={"entry_year": "period"}),
        _summarize_period(df, ["entry_quarter"], "quarter").rename(columns={"entry_quarter": "period"}),
        _summarize_period(df, ["market_era"], "market_era").rename(columns={"market_era": "period"}),
    ]
    out = pd.concat(pieces, ignore_index=True, sort=False)
    out.to_csv(path, index=False)


def _export_setup_period_summaries(df: pd.DataFrame, path: Path) -> None:
    if df.empty:
        pd.DataFrame().to_csv(path, index=False)
        return

    by_year = _summarize_period(df, ["setup_tag", "entry_year"], "setup_year").rename(
        columns={"entry_year": "period"}
    )
    by_era = _summarize_period(df, ["setup_tag", "market_era"], "setup_market_era").rename(
        columns={"market_era": "period"}
    )
    pd.concat([by_year, by_era], ignore_index=True, sort=False).to_csv(path, index=False)


def _export_context_summary(df: pd.DataFrame, path: Path) -> None:
    context_cols = [
        "entry_day_regime",
        "entry_vwap_side",
        "entry_vwap_side_prev",
        "entry_vwap_cross_direction",
        "entry_vwap_side_age_bars",
        "entry_open_context",
        "entry_gap_inventory_alignment",
        "entry_overnight_inventory_direction",
        "entry_vsa_absorption",
        "entry_vsa_thin_move",
        "entry_hawkes_vol_above_high",
        "entry_hawkes_vol_below_low",
        "entry_hawkes_momentum_signal",
        "entry_market_memory_state",
        "entry_market_memory_hurst_regime",
        "entry_market_memory_entropy_regime",
        "entry_market_memory_lz_regime",
        "entry_market_memory_tail_alpha_regime",
        "entry_market_memory_tail_event",
        "entry_options_gex_regime",
        "entry_options_gamma_environment",
        "entry_options_gamma_wall_role",
        "entry_options_call_wall_role",
        "entry_options_put_wall_role",
        "entry_options_gamma_wall_strike",
        "entry_options_call_wall_strike",
        "entry_options_put_wall_strike",
    ]
    available = [col for col in context_cols if col in df.columns]
    if df.empty or not available:
        pd.DataFrame().to_csv(path, index=False)
        return

    pieces = []
    for col in available:
        summary = _summarize(df.groupby(col, dropna=False))
        summary.insert(0, "context_type", col.replace("entry_", ""))
        summary = summary.rename(columns={col: "context_value"})
        pieces.append(summary)
    pd.concat(pieces, ignore_index=True, sort=False).to_csv(path, index=False)


def _export_time_stability(df: pd.DataFrame, path: Path) -> None:
    if df.empty:
        pd.DataFrame().to_csv(path, index=False)
        return

    out = _summarize(df.groupby(["setup_tag", "entry_hour", "entry_year"], dropna=False))
    out.to_csv(path, index=False)


def _export_day_of_week(df: pd.DataFrame, path: Path) -> None:
    if df.empty:
        pd.DataFrame().to_csv(path, index=False)
        return

    by_day = _summarize(df.groupby(["entry_day_of_week_num", "entry_day_of_week"], dropna=False))
    by_day.insert(0, "group_type", "day_of_week")
    by_setup_day = _summarize(
        df.groupby(["setup_tag", "entry_day_of_week_num", "entry_day_of_week"], dropna=False)
    )
    by_setup_day.insert(0, "group_type", "setup_day_of_week")
    pd.concat([by_day, by_setup_day], ignore_index=True, sort=False).sort_values(
        ["group_type", "entry_day_of_week_num", "total_pnl"],
        ascending=[True, True, False],
    ).to_csv(path, index=False)


def _export_rolling_edge(df: pd.DataFrame, path: Path) -> None:
    if df.empty:
        pd.DataFrame().to_csv(path, index=False)
        return

    monthly = df.groupby("entry_month", dropna=False).agg(
        trades=("pnl", "size"),
        total_pnl=("pnl", "sum"),
        avg_pnl=("pnl", "mean"),
        wins=("pnl", lambda s: int((s > 0).sum())),
        losses=("pnl", lambda s: int((s <= 0).sum())),
        gross_win=("pnl", lambda s: float(s[s > 0].sum())),
        gross_loss=("pnl", lambda s: abs(float(s[s <= 0].sum()))),
    )
    monthly = monthly.reset_index().sort_values("entry_month")
    monthly["win_rate_pct"] = np.where(monthly["trades"] > 0, monthly["wins"] / monthly["trades"] * 100.0, np.nan)
    monthly["profit_factor"] = np.where(
        monthly["gross_loss"] > 0,
        monthly["gross_win"] / monthly["gross_loss"],
        np.nan,
    )

    for window in (3, 6, 12):
        win_sum = monthly["gross_win"].rolling(window, min_periods=1).sum()
        loss_sum = monthly["gross_loss"].rolling(window, min_periods=1).sum()
        trade_sum = monthly["trades"].rolling(window, min_periods=1).sum()
        pnl_sum = monthly["total_pnl"].rolling(window, min_periods=1).sum()
        monthly[f"rolling_{window}m_trades"] = trade_sum
        monthly[f"rolling_{window}m_total_pnl"] = pnl_sum
        monthly[f"rolling_{window}m_profit_factor"] = np.where(loss_sum > 0, win_sum / loss_sum, np.nan)
        monthly[f"rolling_{window}m_avg_pnl"] = np.where(trade_sum > 0, pnl_sum / trade_sum, np.nan)

    monthly.to_csv(path, index=False)


def _daily_equity(df: pd.DataFrame, starting_capital: float) -> pd.Series:
    daily_pnl = df.groupby("exit_date")["pnl"].sum().sort_index()
    return daily_pnl.cumsum() + float(starting_capital)


def _export_drawdown_periods(df: pd.DataFrame, path: Path, starting_capital: float) -> None:
    if df.empty:
        pd.DataFrame().to_csv(path, index=False)
        return

    equity = _daily_equity(df, starting_capital)
    if equity.empty:
        pd.DataFrame().to_csv(path, index=False)
        return

    peaks = equity.cummax()
    drawdown = peaks - equity
    records: list[dict[str, object]] = []
    in_drawdown = False
    start_date = None
    peak_equity = 0.0
    trough_date = None
    trough_depth = 0.0
    trough_equity = 0.0

    for date, depth in drawdown.items():
        depth = float(depth)
        current_equity = float(equity.loc[date])
        if not in_drawdown and depth > 0:
            in_drawdown = True
            start_date = date
            peak_equity = float(peaks.loc[date])
            trough_date = date
            trough_depth = depth
            trough_equity = current_equity
            continue

        if not in_drawdown:
            continue

        if depth > trough_depth:
            trough_date = date
            trough_depth = depth
            trough_equity = current_equity

        if depth <= 0:
            records.append(
                {
                    "start_date": start_date,
                    "trough_date": trough_date,
                    "recovery_date": date,
                    "drawdown_dollars": trough_depth,
                    "drawdown_pct": (trough_depth / peak_equity * 100.0) if peak_equity > 0 else np.nan,
                    "peak_equity": peak_equity,
                    "trough_equity": trough_equity,
                    "calendar_days_to_trough": (trough_date - start_date).days if start_date is not None else np.nan,
                    "calendar_days_to_recovery": (date - start_date).days if start_date is not None else np.nan,
                    "recovered": True,
                }
            )
            in_drawdown = False

    if in_drawdown and start_date is not None and trough_date is not None:
        last_date = equity.index.max()
        records.append(
            {
                "start_date": start_date,
                "trough_date": trough_date,
                "recovery_date": pd.NaT,
                "drawdown_dollars": trough_depth,
                "drawdown_pct": (trough_depth / peak_equity * 100.0) if peak_equity > 0 else np.nan,
                "peak_equity": peak_equity,
                "trough_equity": trough_equity,
                "calendar_days_to_trough": (trough_date - start_date).days,
                "calendar_days_to_recovery": (last_date - start_date).days,
                "recovered": False,
            }
        )

    out = pd.DataFrame(records)
    if not out.empty:
        out = out.sort_values("drawdown_dollars", ascending=False).head(50)
    out.to_csv(path, index=False)


def _tail_row(sample_type: str, pnl: pd.Series) -> dict[str, float | str | int]:
    pnl = pnl.astype(float).dropna()
    if pnl.empty:
        return {"sample_type": sample_type, "observations": 0}

    p01, p05, p10 = np.percentile(pnl, [1, 5, 10])
    es05 = float(pnl[pnl <= p05].mean()) if (pnl <= p05).any() else np.nan
    es10 = float(pnl[pnl <= p10].mean()) if (pnl <= p10).any() else np.nan
    return {
        "sample_type": sample_type,
        "observations": int(len(pnl)),
        "mean_pnl": float(pnl.mean()),
        "median_pnl": float(pnl.median()),
        "std_pnl": float(pnl.std(ddof=0)),
        "best_pnl": float(pnl.max()),
        "worst_pnl": float(pnl.min()),
        "p01_pnl": float(p01),
        "p05_pnl": float(p05),
        "p10_pnl": float(p10),
        "expected_shortfall_5_pct": es05,
        "expected_shortfall_10_pct": es10,
        "win_rate_pct": float((pnl > 0).mean() * 100.0),
        "profit_factor": _profit_factor_from_pnl(pnl),
    }


def _export_tail_risk(df: pd.DataFrame, path: Path) -> None:
    if df.empty:
        pd.DataFrame().to_csv(path, index=False)
        return

    daily_pnl = df.groupby("exit_date")["pnl"].sum()
    monthly_pnl = df.groupby("entry_month")["pnl"].sum()
    rows = [
        _tail_row("trade", df["pnl"]),
        _tail_row("day", daily_pnl),
        _tail_row("month", monthly_pnl),
    ]
    pd.DataFrame(rows).to_csv(path, index=False)


def _export_mae_mfe(df: pd.DataFrame, path: Path) -> None:
    required = {"mfe_dollars", "mae_dollars"}
    if df.empty or not required.issubset(df.columns):
        pd.DataFrame().to_csv(path, index=False)
        return

    work = df.copy()
    work["mfe_dollars"] = work["mfe_dollars"].astype(float)
    work["mae_dollars"] = work["mae_dollars"].astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        work["capture_pct"] = np.where(work["mfe_dollars"] > 0, work["pnl"] / work["mfe_dollars"] * 100.0, np.nan)
    work["stopout"] = work["reason"].astype(str).str.contains("stop", case=False, na=False)

    out = work.groupby("setup_tag", dropna=False).apply(
        lambda g: pd.Series(
            {
                "trades": int(len(g)),
                "total_pnl": float(g["pnl"].sum()),
                "avg_pnl": float(g["pnl"].mean()),
                "profit_factor": _profit_factor_from_pnl(g["pnl"]),
                "avg_mfe_dollars": float(g["mfe_dollars"].mean()),
                "avg_mae_dollars": float(g["mae_dollars"].mean()),
                "median_mfe_dollars": float(g["mfe_dollars"].median()),
                "median_mae_dollars": float(g["mae_dollars"].median()),
                "winner_capture_pct": float(g.loc[g["pnl"] > 0, "capture_pct"].mean())
                if (g["pnl"] > 0).any()
                else np.nan,
                "all_trade_capture_pct": float(g["capture_pct"].mean()),
                "stopout_rate_pct": float(g["stopout"].mean() * 100.0),
                "avg_mfe_to_mae": float(g["mfe_dollars"].mean() / g["mae_dollars"].mean())
                if g["mae_dollars"].mean() > 0
                else np.nan,
            }
        )
    )
    out.reset_index().sort_values("total_pnl", ascending=False).to_csv(path, index=False)


def _outlier_scenario_metrics(
    label: str,
    scenario_df: pd.DataFrame,
    base_net_profit: float,
    starting_capital: float,
) -> dict[str, float | int | str]:
    if scenario_df.empty:
        return {
            "scenario": label,
            "trades": 0,
            "total_pnl": 0.0,
            "profit_factor": np.nan,
            "avg_trade": np.nan,
            "max_drawdown_dollars": 0.0,
            "max_drawdown_pct": 0.0,
            "net_profit_retained_pct": 0.0 if base_net_profit else np.nan,
        }

    daily_equity = _daily_equity(scenario_df, starting_capital)
    max_dd_dollars, max_dd_pct = _max_drawdown_from_equity(daily_equity)
    total_pnl = float(scenario_df["pnl"].sum())
    return {
        "scenario": label,
        "trades": int(len(scenario_df)),
        "total_pnl": total_pnl,
        "profit_factor": _profit_factor_from_pnl(scenario_df["pnl"]),
        "avg_trade": float(scenario_df["pnl"].mean()),
        "max_drawdown_dollars": max_dd_dollars,
        "max_drawdown_pct": max_dd_pct,
        "net_profit_retained_pct": (total_pnl / base_net_profit * 100.0) if base_net_profit else np.nan,
    }


def _export_outlier_dependence(df: pd.DataFrame, path: Path, starting_capital: float) -> None:
    if df.empty:
        pd.DataFrame().to_csv(path, index=False)
        return

    base_net_profit = float(df["pnl"].sum())
    rows = [_outlier_scenario_metrics("base", df, base_net_profit, starting_capital)]
    best_sorted = df.sort_values("pnl", ascending=False)
    worst_sorted = df.sort_values("pnl", ascending=True)

    scenarios = [
        ("remove_best_1_trade", best_sorted.head(1).index),
        ("remove_best_5_trades", best_sorted.head(5).index),
        ("remove_best_10_trades", best_sorted.head(10).index),
        ("remove_best_1_pct", best_sorted.head(max(1, int(np.ceil(len(df) * 0.01)))).index),
        ("remove_best_5_pct", best_sorted.head(max(1, int(np.ceil(len(df) * 0.05)))).index),
        ("remove_worst_5_trades", worst_sorted.head(5).index),
        ("remove_worst_1_pct", worst_sorted.head(max(1, int(np.ceil(len(df) * 0.01)))).index),
    ]

    for label, drop_idx in scenarios:
        scenario_df = df.drop(index=drop_idx).sort_values("exit_time").reset_index(drop=True)
        rows.append(_outlier_scenario_metrics(label, scenario_df, base_net_profit, starting_capital))

    top_1_pct_count = max(1, int(np.ceil(len(df) * 0.01)))
    top_5_pct_count = max(1, int(np.ceil(len(df) * 0.05)))
    rows.append(
        {
            "scenario": "concentration",
            "trades": int(len(df)),
            "total_pnl": base_net_profit,
            "profit_factor": _profit_factor_from_pnl(df["pnl"]),
            "avg_trade": float(df["pnl"].mean()),
            "max_drawdown_dollars": np.nan,
            "max_drawdown_pct": np.nan,
            "net_profit_retained_pct": 100.0,
            "top_1_pct_profit_share_pct": float(best_sorted.head(top_1_pct_count)["pnl"].sum() / base_net_profit * 100.0)
            if base_net_profit
            else np.nan,
            "top_5_pct_profit_share_pct": float(best_sorted.head(top_5_pct_count)["pnl"].sum() / base_net_profit * 100.0)
            if base_net_profit
            else np.nan,
        }
    )

    pd.DataFrame(rows).to_csv(path, index=False)


def _dependency_for_group(label: str, g: pd.DataFrame) -> dict[str, float | str | int]:
    pnl = g.sort_values("exit_time")["pnl"].astype(float).to_numpy()
    wins = pnl > 0
    if pnl.size < 2:
        return {"group": label, "trades": int(pnl.size)}

    prev_wins = wins[:-1]
    next_wins = wins[1:]
    prev_losses = ~prev_wins
    next_losses = ~next_wins
    pnl_series = pd.Series(pnl)
    return {
        "group": label,
        "trades": int(pnl.size),
        "lag1_pnl_autocorr": float(pnl_series.autocorr(lag=1)) if pnl.size > 2 else np.nan,
        "lag5_pnl_autocorr": float(pnl_series.autocorr(lag=5)) if pnl.size > 6 else np.nan,
        "next_win_after_win_pct": float(next_wins[prev_wins].mean() * 100.0) if prev_wins.any() else np.nan,
        "next_loss_after_loss_pct": float(next_losses[prev_losses].mean() * 100.0) if prev_losses.any() else np.nan,
        "avg_next_pnl_after_win": float(pnl[1:][prev_wins].mean()) if prev_wins.any() else np.nan,
        "avg_next_pnl_after_loss": float(pnl[1:][prev_losses].mean()) if prev_losses.any() else np.nan,
    }


def _export_dependency(df: pd.DataFrame, path: Path) -> None:
    if df.empty:
        pd.DataFrame().to_csv(path, index=False)
        return

    rows = [_dependency_for_group("all", df)]
    for setup_tag, group in df.groupby("setup_tag", dropna=False):
        rows.append(_dependency_for_group(f"setup:{setup_tag}", group))
    pd.DataFrame(rows).to_csv(path, index=False)


def _normalize_condition_series(series: pd.Series) -> pd.Series:
    out = series.astype("object").where(~pd.isna(series), "missing").astype(str)
    return out.replace({"": "missing", "nan": "missing", "NaT": "missing", "None": "missing"})


def _available_conditioning_sets(
    df: pd.DataFrame,
    conditioning_sets: list[list[str]] | list[tuple[str, ...]] | None = None,
) -> list[tuple[str, ...]]:
    requested = conditioning_sets if conditioning_sets is not None else list(DEFAULT_CONDITIONING_SETS)
    available: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for raw_cols in requested:
        cols = tuple(str(col) for col in raw_cols)
        if not cols or cols in seen or not set(cols).issubset(df.columns):
            continue
        if not all(_normalize_condition_series(df[col]).ne("missing").any() for col in cols):
            continue
        available.append(cols)
        seen.add(cols)
    return available


def _bootstrap_expectancy(
    pnl: np.ndarray,
    *,
    n_bootstrap: int,
    rng: np.random.Generator,
) -> tuple[float, float, float, float]:
    if pnl.size == 0 or n_bootstrap <= 0:
        return np.nan, np.nan, np.nan, np.nan
    draws = rng.integers(0, pnl.size, size=(int(n_bootstrap), pnl.size))
    means = pnl[draws].mean(axis=1)
    p05, p50, p95 = np.percentile(means, [5, 50, 95])
    return float(p05), float(p50), float(p95), float((means > 0).mean())


def _period_summary_row(
    conditioning_set: str,
    conditioning_key: str,
    period: str,
    group_cols: tuple[str, ...],
    group_values: tuple[object, ...],
    pnl: pd.Series,
) -> dict[str, object]:
    row: dict[str, object] = {
        "conditioning_set": conditioning_set,
        "conditioning_key": conditioning_key,
        "period": period,
        "trades": int(len(pnl)),
        "total_pnl": float(pnl.sum()),
        "avg_pnl": float(pnl.mean()) if len(pnl) else np.nan,
        "median_pnl": float(pnl.median()) if len(pnl) else np.nan,
        "win_rate_pct": float((pnl > 0).mean() * 100.0) if len(pnl) else np.nan,
        "profit_factor": _profit_factor_from_pnl(pnl),
    }
    for col, value in zip(group_cols, group_values, strict=False):
        row[col] = value
    return row


def _conditional_edge_flag(
    *,
    trades: int,
    min_trades: int,
    periods: int,
    min_periods: int,
    avg_pnl: float,
    profit_factor: float,
    bootstrap_prob_gt_zero: float,
    positive_period_ratio_pct: float,
) -> str:
    if trades < min_trades:
        return "under_sampled"
    if periods < min_periods:
        return "sample_ok_time_unconfirmed"
    pf = 0.0 if pd.isna(profit_factor) else float(profit_factor)
    prob = 0.0 if pd.isna(bootstrap_prob_gt_zero) else float(bootstrap_prob_gt_zero)
    period_ratio = 0.0 if pd.isna(positive_period_ratio_pct) else float(positive_period_ratio_pct)
    if avg_pnl > 0 and pf >= 1.10 and prob >= 0.60 and period_ratio >= 55.0:
        return "possible_positive_conditional_edge"
    if avg_pnl < 0 and (pf <= 0.90 or prob <= 0.40) and period_ratio <= 45.0:
        return "possible_negative_condition"
    if avg_pnl > 0 and (prob < 0.55 or period_ratio < 50.0):
        return "fragile_positive_mean"
    return "mixed_or_neutral"


def _conditional_summary_row(
    conditioning_set: str,
    conditioning_key: str,
    group_cols: tuple[str, ...],
    group_values: tuple[object, ...],
    group: pd.DataFrame,
    period_rows: pd.DataFrame,
    *,
    total_trades: int,
    total_pnl: float,
    min_trades: int,
    min_periods: int,
    n_bootstrap: int,
    rng: np.random.Generator,
) -> dict[str, object]:
    pnl = pd.to_numeric(group["pnl"], errors="coerce").dropna().astype(float)
    arr = pnl.to_numpy(dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    p05, p50, p95, p_gt_zero = _bootstrap_expectancy(arr, n_bootstrap=n_bootstrap, rng=rng)
    periods = int(len(period_rows))
    positive_period_ratio = (
        float((period_rows["avg_pnl"].astype(float) > 0).mean() * 100.0)
        if periods
        else np.nan
    )
    profitable_period_ratio = (
        float((period_rows["total_pnl"].astype(float) > 0).mean() * 100.0)
        if periods
        else np.nan
    )
    avg_pnl = float(pnl.mean()) if len(pnl) else np.nan
    profit_factor = _profit_factor_from_pnl(pnl)
    row: dict[str, object] = {
        "conditioning_set": conditioning_set,
        "conditioning_key": conditioning_key,
        "trades": int(len(pnl)),
        "sample_share_pct": (len(pnl) / total_trades * 100.0) if total_trades else np.nan,
        "total_pnl": float(pnl.sum()) if len(pnl) else 0.0,
        "pnl_share_pct": (float(pnl.sum()) / total_pnl * 100.0) if total_pnl else np.nan,
        "avg_pnl": avg_pnl,
        "median_pnl": float(pnl.median()) if len(pnl) else np.nan,
        "std_pnl": float(pnl.std(ddof=0)) if len(pnl) else np.nan,
        "p05_pnl": float(np.percentile(arr, 5)) if arr.size else np.nan,
        "p95_pnl": float(np.percentile(arr, 95)) if arr.size else np.nan,
        "win_rate_pct": float((pnl > 0).mean() * 100.0) if len(pnl) else np.nan,
        "profit_factor": profit_factor,
        "avg_win": float(wins.mean()) if len(wins) else np.nan,
        "avg_loss": float(losses.mean()) if len(losses) else np.nan,
        "bootstrap_expectancy_p05": p05,
        "bootstrap_expectancy_p50": p50,
        "bootstrap_expectancy_p95": p95,
        "bootstrap_prob_expectancy_gt_0": p_gt_zero,
        "periods_with_trades": periods,
        "positive_period_ratio_pct": positive_period_ratio,
        "profitable_period_ratio_pct": profitable_period_ratio,
        "period_avg_pnl_std": float(period_rows["avg_pnl"].astype(float).std(ddof=0)) if periods else np.nan,
        "period_min_trades": int(period_rows["trades"].min()) if periods else 0,
        "sample_ok": bool(len(pnl) >= min_trades),
    }
    row["edge_flag"] = _conditional_edge_flag(
        trades=int(len(pnl)),
        min_trades=min_trades,
        periods=periods,
        min_periods=min_periods,
        avg_pnl=avg_pnl,
        profit_factor=profit_factor,
        bootstrap_prob_gt_zero=p_gt_zero,
        positive_period_ratio_pct=positive_period_ratio,
    )
    for col, value in zip(group_cols, group_values, strict=False):
        row[col] = value
    return row


def _conditional_period_rows(
    work: pd.DataFrame,
    group_cols: tuple[str, ...],
    conditioning_set: str,
    period: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    period_col = "_conditional_period"
    grouped_cols = list(group_cols) + [period_col]
    for group_values, period_group in work.groupby(grouped_cols, dropna=False, sort=True):
        if not isinstance(group_values, tuple):
            group_values = (group_values,)
        value_tuple = tuple(group_values[:-1])
        period_value = str(group_values[-1])
        conditioning_key = " | ".join(str(value) for value in value_tuple)
        rows.append(
            _period_summary_row(
                conditioning_set,
                conditioning_key,
                period_value,
                group_cols,
                value_tuple,
                pd.to_numeric(period_group["pnl"], errors="coerce").dropna().astype(float),
            )
        )
    return pd.DataFrame(rows)


def summarize_conditional_distributions(
    trades_df: pd.DataFrame,
    *,
    conditioning_sets: list[list[str]] | list[tuple[str, ...]] | None = None,
    min_trades: int = 30,
    min_periods: int = 3,
    period: str = "Q",
    n_bootstrap: int = 300,
    random_seed: int = 7,
    max_groups_per_set: int = 80,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if trades_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = _prepare_trades(trades_df)
    df["_conditional_period"] = df["entry_time"].dt.to_period(period).astype(str)
    total_trades = int(len(df))
    total_pnl = float(df["pnl"].sum())
    rng = np.random.default_rng(random_seed)
    summary_rows: list[dict[str, object]] = []
    all_period_rows: list[pd.DataFrame] = []

    for group_cols in _available_conditioning_sets(df, conditioning_sets):
        work = df.copy()
        for col in group_cols:
            work[col] = _normalize_condition_series(work[col])
        group_counts = work.groupby(list(group_cols), dropna=False).size()
        if group_counts.empty or len(group_counts) > max_groups_per_set:
            continue

        conditioning_set = " | ".join(group_cols)
        period_rows = _conditional_period_rows(work, group_cols, conditioning_set, period)
        if not period_rows.empty:
            all_period_rows.append(period_rows)

        for group_values, group in work.groupby(list(group_cols), dropna=False, sort=True):
            if not isinstance(group_values, tuple):
                group_values = (group_values,)
            value_tuple = tuple(group_values)
            conditioning_key = " | ".join(str(value) for value in value_tuple)
            matching_periods = period_rows
            for col, value in zip(group_cols, value_tuple, strict=False):
                matching_periods = matching_periods[matching_periods[col].astype(str).eq(str(value))]
            summary_rows.append(
                _conditional_summary_row(
                    conditioning_set,
                    conditioning_key,
                    group_cols,
                    value_tuple,
                    group,
                    matching_periods,
                    total_trades=total_trades,
                    total_pnl=total_pnl,
                    min_trades=int(min_trades),
                    min_periods=int(min_periods),
                    n_bootstrap=int(n_bootstrap),
                    rng=rng,
                )
            )

    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary = summary.sort_values(
            ["edge_flag", "sample_ok", "bootstrap_prob_expectancy_gt_0", "avg_pnl", "trades"],
            ascending=[True, False, False, False, False],
        ).reset_index(drop=True)

    period_df = pd.concat(all_period_rows, ignore_index=True, sort=False) if all_period_rows else pd.DataFrame()
    return summary, period_df


def _aggregate_conditional_metrics(df: pd.DataFrame) -> dict[str, object]:
    pnl = pd.to_numeric(df["pnl"], errors="coerce").dropna().astype(float)
    return {
        "trades": int(len(pnl)),
        "total_pnl": float(pnl.sum()) if len(pnl) else 0.0,
        "avg_pnl": float(pnl.mean()) if len(pnl) else np.nan,
        "profit_factor": _profit_factor_from_pnl(pnl),
        "win_rate_pct": float((pnl > 0).mean() * 100.0) if len(pnl) else np.nan,
    }


def _build_conditional_warnings(
    summary: pd.DataFrame,
    aggregate: dict[str, object],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if summary.empty:
        return pd.DataFrame(rows)

    sample_ok = summary[summary["sample_ok"].astype(bool)]
    positive = sample_ok[sample_ok["edge_flag"].eq("possible_positive_conditional_edge")]
    negative = sample_ok[sample_ok["edge_flag"].eq("possible_negative_condition")]
    fragile = sample_ok[sample_ok["edge_flag"].eq("fragile_positive_mean")]
    under_sampled = summary[summary["edge_flag"].eq("under_sampled")]
    aggregate_avg = float(aggregate.get("avg_pnl", np.nan))

    if aggregate_avg > 0 and not negative.empty:
        rows.append(
            {
                "warning": "aggregate_positive_masks_negative_conditions",
                "severity": "review",
                "count": int(len(negative)),
                "detail": "Aggregate expectancy is positive, but sampled conditional slices are negative.",
            }
        )
    if not positive.empty:
        rows.append(
            {
                "warning": "conditional_edge_candidates",
                "severity": "hypothesis",
                "count": int(len(positive)),
                "detail": "Positive slices should be verified out of sample before becoming filters.",
            }
        )
    if not fragile.empty:
        rows.append(
            {
                "warning": "fragile_positive_means",
                "severity": "caution",
                "count": int(len(fragile)),
                "detail": "Some positive average PnL slices fail bootstrap or period-stability checks.",
            }
        )
    if len(under_sampled) > len(summary) * 0.5:
        rows.append(
            {
                "warning": "many_under_sampled_slices",
                "severity": "caution",
                "count": int(len(under_sampled)),
                "detail": "Most conditional buckets are exploratory and should not drive parameters.",
            }
        )
    return pd.DataFrame(rows)


def _fmt_metric(value: object, decimals: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(number):
        return "nan"
    return f"{number:.{decimals}f}"


def _markdown_table(df: pd.DataFrame, columns: list[str], *, max_rows: int = 10) -> list[str]:
    if df.empty:
        return ["No rows."]
    available = [col for col in columns if col in df.columns]
    if not available:
        return ["No display columns available."]
    lines = ["| " + " | ".join(available) + " |", "| " + " | ".join(["---"] * len(available)) + " |"]
    for _, row in df.loc[:, available].head(max_rows).iterrows():
        values = []
        for col in available:
            value = row[col]
            if isinstance(value, (float, np.floating)):
                values.append(_fmt_metric(value))
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def _write_conditional_markdown_report(
    path: Path,
    summary: pd.DataFrame,
    warnings: pd.DataFrame,
    aggregate: dict[str, object],
    *,
    min_trades: int,
    min_periods: int,
    period: str,
) -> None:
    positive = summary[summary["edge_flag"].eq("possible_positive_conditional_edge")] if not summary.empty else pd.DataFrame()
    negative = summary[summary["edge_flag"].eq("possible_negative_condition")] if not summary.empty else pd.DataFrame()
    fragile = summary[summary["edge_flag"].eq("fragile_positive_mean")] if not summary.empty else pd.DataFrame()
    columns = [
        "conditioning_set",
        "conditioning_key",
        "trades",
        "avg_pnl",
        "profit_factor",
        "bootstrap_prob_expectancy_gt_0",
        "positive_period_ratio_pct",
        "edge_flag",
    ]

    lines = [
        "# Conditional Distribution Report",
        "",
        "This report checks whether aggregate strategy PnL is mixing different conditional distributions.",
        "Treat any slice as a hypothesis until it survives walk-forward or other out-of-sample validation.",
        "",
        "## Settings",
        f"- Minimum trades per slice: {int(min_trades)}",
        f"- Minimum periods per slice: {int(min_periods)}",
        f"- Stability period: {period}",
        "",
        "## Aggregate",
        f"- Trades: {aggregate.get('trades', 0)}",
        f"- Total PnL: {_fmt_metric(aggregate.get('total_pnl'))}",
        f"- Avg PnL: {_fmt_metric(aggregate.get('avg_pnl'))}",
        f"- Profit factor: {_fmt_metric(aggregate.get('profit_factor'))}",
        f"- Win rate: {_fmt_metric(aggregate.get('win_rate_pct'))}%",
        "",
        "## Warnings",
    ]
    if warnings.empty:
        lines.append("No conditional warnings triggered.")
    else:
        lines.extend(_markdown_table(warnings, ["severity", "warning", "count", "detail"], max_rows=10))

    lines.extend(["", "## Possible Positive Conditional Edges"])
    lines.extend(
        _markdown_table(
            positive.sort_values(["bootstrap_prob_expectancy_gt_0", "avg_pnl"], ascending=[False, False]),
            columns,
            max_rows=10,
        )
    )
    lines.extend(["", "## Possible Negative Conditions"])
    lines.extend(
        _markdown_table(
            negative.sort_values(["avg_pnl", "profit_factor"], ascending=[True, True]),
            columns,
            max_rows=10,
        )
    )
    lines.extend(["", "## Fragile Positive Means"])
    lines.extend(
        _markdown_table(
            fragile.sort_values(["avg_pnl"], ascending=False),
            columns,
            max_rows=10,
        )
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_conditional_distribution_report(
    trades_df: pd.DataFrame,
    out_dir: Path | str,
    artifact_name: str = "conditional_distributions",
    *,
    conditioning_sets: list[list[str]] | list[tuple[str, ...]] | None = None,
    min_trades: int = 30,
    min_periods: int = 3,
    period: str = "Q",
    n_bootstrap: int = 300,
    random_seed: int = 7,
    max_groups_per_set: int = 80,
) -> ConditionalDistributionReportPaths:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_csv = out_dir / f"{artifact_name}_summary.csv"
    period_stability_csv = out_dir / f"{artifact_name}_period_stability.csv"
    warnings_csv = out_dir / f"{artifact_name}_warnings.csv"
    report_md = out_dir / f"{artifact_name}_report.md"

    if trades_df.empty:
        pd.DataFrame().to_csv(summary_csv, index=False)
        pd.DataFrame().to_csv(period_stability_csv, index=False)
        pd.DataFrame().to_csv(warnings_csv, index=False)
        report_md.write_text("# Conditional Distribution Report\n\nNo trades available.\n", encoding="utf-8")
        return ConditionalDistributionReportPaths(summary_csv, period_stability_csv, warnings_csv, report_md)

    prepared = _prepare_trades(trades_df)
    summary, period_df = summarize_conditional_distributions(
        prepared,
        conditioning_sets=conditioning_sets,
        min_trades=min_trades,
        min_periods=min_periods,
        period=period,
        n_bootstrap=n_bootstrap,
        random_seed=random_seed,
        max_groups_per_set=max_groups_per_set,
    )
    aggregate = _aggregate_conditional_metrics(prepared)
    warnings = _build_conditional_warnings(summary, aggregate)

    summary.to_csv(summary_csv, index=False)
    period_df.to_csv(period_stability_csv, index=False)
    warnings.to_csv(warnings_csv, index=False)
    _write_conditional_markdown_report(
        report_md,
        summary,
        warnings,
        aggregate,
        min_trades=min_trades,
        min_periods=min_periods,
        period=period,
    )
    return ConditionalDistributionReportPaths(summary_csv, period_stability_csv, warnings_csv, report_md)


def export_trade_summaries(
    trades_df: pd.DataFrame,
    out_dir: Path | str,
    artifact_name: str = "trade_summary",
) -> TradeSummaryPaths:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = trades_df.copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["entry_hour"] = df["entry_time"].dt.hour
    if "hold_minutes" not in df.columns:
        df["hold_minutes"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 60.0

    by_setup = _summarize(df.groupby("setup_tag", dropna=False))
    by_setup_hour = _summarize(df.groupby(["setup_tag", "entry_hour"], dropna=False))
    by_setup_reason = _summarize(df.groupby(["setup_tag", "reason"], dropna=False))

    by_setup_csv = out_dir / f"{artifact_name}_by_setup.csv"
    by_setup_hour_csv = out_dir / f"{artifact_name}_by_setup_hour.csv"
    by_setup_reason_csv = out_dir / f"{artifact_name}_by_setup_reason.csv"

    by_setup.to_csv(by_setup_csv, index=False)
    by_setup_hour.to_csv(by_setup_hour_csv, index=False)
    by_setup_reason.to_csv(by_setup_reason_csv, index=False)

    return TradeSummaryPaths(
        by_setup_csv=by_setup_csv,
        by_setup_hour_csv=by_setup_hour_csv,
        by_setup_reason_csv=by_setup_reason_csv,
    )


def export_robustness_reports(
    trades_df: pd.DataFrame,
    out_dir: Path | str,
    artifact_name: str = "robustness",
    starting_capital: float = 100000.0,
) -> RobustnessReportPaths:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = _prepare_trades(trades_df)

    quality_metrics_csv = out_dir / f"{artifact_name}_quality_metrics.csv"
    period_summary_csv = out_dir / f"{artifact_name}_period_summary.csv"
    setup_period_csv = out_dir / f"{artifact_name}_setup_period.csv"
    context_summary_csv = out_dir / f"{artifact_name}_context_summary.csv"
    day_of_week_csv = out_dir / f"{artifact_name}_day_of_week.csv"
    time_stability_csv = out_dir / f"{artifact_name}_time_stability.csv"
    rolling_edge_csv = out_dir / f"{artifact_name}_rolling_edge.csv"
    drawdown_periods_csv = out_dir / f"{artifact_name}_drawdown_periods.csv"
    tail_risk_csv = out_dir / f"{artifact_name}_tail_risk.csv"
    mae_mfe_csv = out_dir / f"{artifact_name}_mae_mfe.csv"
    outlier_dependence_csv = out_dir / f"{artifact_name}_outlier_dependence.csv"
    dependency_csv = out_dir / f"{artifact_name}_dependency.csv"

    _export_quality_metrics(df, quality_metrics_csv, starting_capital=starting_capital)
    _export_period_summaries(df, period_summary_csv)
    _export_setup_period_summaries(df, setup_period_csv)
    _export_context_summary(df, context_summary_csv)
    _export_day_of_week(df, day_of_week_csv)
    _export_time_stability(df, time_stability_csv)
    _export_rolling_edge(df, rolling_edge_csv)
    _export_drawdown_periods(df, drawdown_periods_csv, starting_capital=starting_capital)
    _export_tail_risk(df, tail_risk_csv)
    _export_mae_mfe(df, mae_mfe_csv)
    _export_outlier_dependence(df, outlier_dependence_csv, starting_capital=starting_capital)
    _export_dependency(df, dependency_csv)

    return RobustnessReportPaths(
        quality_metrics_csv=quality_metrics_csv,
        period_summary_csv=period_summary_csv,
        setup_period_csv=setup_period_csv,
        context_summary_csv=context_summary_csv,
        day_of_week_csv=day_of_week_csv,
        time_stability_csv=time_stability_csv,
        rolling_edge_csv=rolling_edge_csv,
        drawdown_periods_csv=drawdown_periods_csv,
        tail_risk_csv=tail_risk_csv,
        mae_mfe_csv=mae_mfe_csv,
        outlier_dependence_csv=outlier_dependence_csv,
        dependency_csv=dependency_csv,
    )
