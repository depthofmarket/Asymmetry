from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DEFAULT_HORIZONS_BARS = (1, 3, 6, 12, 24)
DEFAULT_EXCLUDED_SIGNAL_COLUMNS = {
    "time",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "vwap",
    "atr",
    "signal_active",
    "hour",
    "minute",
    "stop_points",
    "target_points",
}
MAX_MONTE_CARLO_DRAW_CELLS = 5_000_000


@dataclass(frozen=True)
class SignalResearchPaths:
    summary_csv: Path
    period_stability_csv: Path
    context_summary_csv: Path
    report_md: Path


def infer_signal_columns(
    data: pd.DataFrame,
    *,
    time_col: str = "time",
    price_col: str = "close",
    context_cols: Iterable[str] = (),
) -> list[str]:
    excluded = set(DEFAULT_EXCLUDED_SIGNAL_COLUMNS)
    excluded.add(time_col)
    excluded.add(price_col)
    excluded.update(context_cols)
    cols: list[str] = []
    for col in data.columns:
        if col in excluded:
            continue
        series = pd.to_numeric(data[col], errors="coerce")
        if series.notna().sum() > 0:
            cols.append(col)
    return cols


def run_signal_research_report(
    data: pd.DataFrame,
    *,
    out_dir: Path | str,
    artifact_name: str = "signal_research",
    signal_cols: Iterable[str] | None = None,
    context_cols: Iterable[str] = (),
    time_col: str = "time",
    price_col: str = "close",
    entry_price_col: str | None = None,
    exit_price_col: str | None = None,
    entry_lag_bars: int = 0,
    horizons_bars: Iterable[int] = DEFAULT_HORIZONS_BARS,
    period: str = "Q",
    round_trip_cost_points: float = 0.0,
    stress_round_trip_cost_points: Iterable[float] = (),
    min_obs: int = 100,
    min_active_obs: int = 30,
    min_abs_ic: float = 0.02,
    min_positive_period_pct: float = 55.0,
    min_event_hit_rate_pct: float = 52.0,
    min_event_bootstrap_ci_low_points: float = 0.0,
    min_event_placebo_edge_points: float = 0.0,
    max_event_placebo_p_value: float = 0.10,
    event_bootstrap_samples: int = 1000,
    event_placebo_samples: int = 1000,
    event_random_seed: int = 7,
) -> SignalResearchPaths:
    df = data.copy()
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if price_col not in df.columns:
        raise ValueError(f"price column not found: {price_col}")
    entry_col = entry_price_col or price_col
    exit_col = exit_price_col or price_col
    if entry_col not in df.columns:
        raise ValueError(f"entry price column not found: {entry_col}")
    if exit_col not in df.columns:
        raise ValueError(f"exit price column not found: {exit_col}")
    entry_lag = int(entry_lag_bars)
    if entry_lag < 0:
        raise ValueError("entry_lag_bars must be non-negative")

    context_cols = [col for col in context_cols if col in df.columns]
    selected_signals = list(signal_cols) if signal_cols is not None else infer_signal_columns(
        df,
        time_col=time_col,
        price_col=price_col,
        context_cols=context_cols,
    )
    missing = [col for col in selected_signals if col not in df.columns]
    if missing:
        raise ValueError(f"signal columns not found: {missing}")
    if not selected_signals:
        raise ValueError("no signal columns supplied or inferred")

    df[price_col] = pd.to_numeric(df[price_col], errors="coerce")
    df[entry_col] = pd.to_numeric(df[entry_col], errors="coerce")
    df[exit_col] = pd.to_numeric(df[exit_col], errors="coerce")
    if time_col in df.columns:
        times = pd.to_datetime(df[time_col], errors="coerce")
    else:
        times = pd.Series(pd.RangeIndex(len(df)), index=df.index)
    period_labels = _period_labels(times, period)

    summary_rows: list[dict[str, object]] = []
    period_rows: list[dict[str, object]] = []
    context_rows: list[dict[str, object]] = []
    rng = np.random.default_rng(int(event_random_seed))
    stress_costs = _normalize_stress_costs(
        primary_cost=float(round_trip_cost_points),
        stress_costs=stress_round_trip_cost_points,
    )

    for horizon in [int(item) for item in horizons_bars]:
        if horizon <= 0:
            continue
        if entry_lag > horizon:
            continue
        entry_price = df[entry_col].shift(-entry_lag)
        exit_price = df[exit_col].shift(-horizon)
        forward_return = exit_price - entry_price
        for signal_col in selected_signals:
            signal = pd.to_numeric(df[signal_col], errors="coerce")
            direction = np.sign(signal)
            active_mask = direction.ne(0) & signal.notna() & forward_return.notna()
            valid_mask = signal.notna() & forward_return.notna()
            signed_points = direction * forward_return
            signed_after_cost = signed_points - float(round_trip_cost_points)

            ic = _pearson(signal.loc[valid_mask], forward_return.loc[valid_mask])
            active_ic = _pearson(signal.loc[active_mask], forward_return.loc[active_mask])
            active_signed = signed_after_cost.loc[active_mask]
            active_raw = signed_points.loc[active_mask]
            active_forward = forward_return.loc[active_mask]
            hit_rate = float((active_raw > 0).mean() * 100.0) if not active_raw.empty else np.nan
            long_mask = active_mask & direction.gt(0)
            short_mask = active_mask & direction.lt(0)
            event_median_after_cost = _finite_median(active_signed)
            event_ci_low, event_ci_high = _bootstrap_mean_ci(
                active_signed,
                samples=int(event_bootstrap_samples),
                confidence=0.95,
                rng=rng,
            )
            placebo_pool, placebo_pool_mode, placebo_pool_obs = _select_placebo_return_pool(
                forward_return=forward_return,
                valid_mask=valid_mask,
                active_mask=active_mask,
                times=times,
            )
            placebo_mean, placebo_edge, placebo_p_value = _placebo_event_test(
                placebo_pool,
                direction.loc[active_mask],
                observed_mean=_finite_mean(active_signed),
                round_trip_cost_points=float(round_trip_cost_points),
                samples=int(event_placebo_samples),
                rng=rng,
            )
            excursion_metrics = _evaluate_excursions_and_barriers(
                df=df,
                active_mask=active_mask,
                direction=direction,
                entry_col=entry_col,
                exit_col=exit_col,
                entry_lag=entry_lag,
                horizon=horizon,
                round_trip_cost_points=float(round_trip_cost_points),
                bootstrap_samples=int(event_bootstrap_samples),
                rng=rng,
            )

            current_period_rows: list[dict[str, object]] = []
            for period_value, idx in active_mask.groupby(period_labels).groups.items():
                period_mask = active_mask.loc[idx]
                if not bool(period_mask.any()):
                    continue
                period_signal = signal.loc[idx]
                period_forward = forward_return.loc[idx]
                period_valid = period_signal.notna() & period_forward.notna()
                period_direction = direction.loc[idx]
                period_active = period_direction.ne(0) & period_valid
                period_raw_signed = (period_direction * period_forward).loc[period_active]
                period_signed = period_raw_signed - float(round_trip_cost_points)
                period_row = (
                    {
                        "signal": signal_col,
                        "horizon_bars": horizon,
                        "period": str(period_value),
                        "n_active": int(period_active.sum()),
                        "ic": _pearson(period_signal.loc[period_valid], period_forward.loc[period_valid]),
                        "active_ic": _pearson(period_signal.loc[period_active], period_forward.loc[period_active]),
                        "mean_signed_return_after_cost_points": _finite_mean(period_signed),
                        "hit_rate_pct": float(((period_direction * period_forward).loc[period_active] > 0).mean() * 100.0)
                        if int(period_active.sum()) > 0
                        else np.nan,
                    }
                )
                period_rows.append(period_row)
                current_period_rows.append(
                    {
                        **period_row,
                        "_raw_mean_signed_return_points": _finite_mean(period_raw_signed),
                    }
                )

            signal_periods = pd.DataFrame(current_period_rows)
            period_count = int(len(signal_periods))
            positive_ic_period_pct = (
                float((pd.to_numeric(signal_periods["ic"], errors="coerce") > 0).mean() * 100.0)
                if period_count
                else np.nan
            )
            positive_active_ic_period_pct = (
                float((pd.to_numeric(signal_periods["active_ic"], errors="coerce") > 0).mean() * 100.0)
                if period_count
                else np.nan
            )
            positive_signed_period_pct = (
                float(
                    (
                        pd.to_numeric(signal_periods["mean_signed_return_after_cost_points"], errors="coerce")
                        > 0
                    ).mean()
                    * 100.0
                )
                if period_count
                else np.nan
            )
            worst_period_signed = (
                float(pd.to_numeric(signal_periods["mean_signed_return_after_cost_points"], errors="coerce").min())
                if period_count
                else np.nan
            )

            long_mean = _finite_mean(forward_return.loc[long_mask])
            short_mean = _finite_mean((-forward_return).loc[short_mask])
            signed_mean_after_cost = _finite_mean(active_signed)
            stress_metrics = _cost_stress_metrics(
                active_raw,
                signal_periods,
                stress_costs=stress_costs,
                primary_cost=float(round_trip_cost_points),
                min_positive_period_pct=float(min_positive_period_pct),
                min_event_bootstrap_ci_low_points=float(min_event_bootstrap_ci_low_points),
                event_ci_low=event_ci_low,
            )
            active_pct_val = float(active_mask.mean() * 100.0)
            effective_abs_ic = abs(float(ic)) if np.isfinite(ic) else np.nan
            if active_pct_val < 10.0 and np.isfinite(active_ic):
                effective_abs_ic = (
                    max(effective_abs_ic, abs(float(active_ic)))
                    if np.isfinite(effective_abs_ic)
                    else abs(float(active_ic))
                )
            eligible = (
                int(valid_mask.sum()) >= int(min_obs)
                and int(active_mask.sum()) >= int(min_active_obs)
                and np.isfinite(effective_abs_ic)
                and float(effective_abs_ic) >= float(min_abs_ic)
                and np.isfinite(signed_mean_after_cost)
                and signed_mean_after_cost > 0
                and np.isfinite(positive_signed_period_pct)
                and positive_signed_period_pct >= float(min_positive_period_pct)
                and bool(stress_metrics["stress_cost_survives"])
            )
            event_eligible = (
                int(valid_mask.sum()) >= int(min_obs)
                and int(active_mask.sum()) >= int(min_active_obs)
                and np.isfinite(signed_mean_after_cost)
                and signed_mean_after_cost > 0
                and np.isfinite(hit_rate)
                and hit_rate >= float(min_event_hit_rate_pct)
                and np.isfinite(positive_signed_period_pct)
                and positive_signed_period_pct >= float(min_positive_period_pct)
                and np.isfinite(worst_period_signed)
                and np.isfinite(event_ci_low)
                and event_ci_low > float(min_event_bootstrap_ci_low_points)
                and np.isfinite(placebo_edge)
                and placebo_edge > float(min_event_placebo_edge_points)
                and np.isfinite(placebo_p_value)
                and placebo_p_value <= float(max_event_placebo_p_value)
                and bool(stress_metrics["stress_event_cost_survives"])
            )

            summary_row = {
                "signal": signal_col,
                "horizon_bars": horizon,
                "n_obs": int(valid_mask.sum()),
                "n_active": int(active_mask.sum()),
                "active_pct": active_pct_val,
                "ic": ic,
                "abs_ic": abs(ic) if np.isfinite(ic) else np.nan,
                "active_ic": active_ic,
                "abs_active_ic": abs(active_ic) if np.isfinite(active_ic) else np.nan,
                "ic_suspicious_gt_0_10": bool(np.isfinite(ic) and abs(ic) >= 0.10),
                "mean_forward_return_points": _finite_mean(active_forward),
                "mean_signed_return_points": _finite_mean(active_raw),
                "mean_signed_return_after_cost_points": signed_mean_after_cost,
                "median_signed_return_after_cost_points": event_median_after_cost,
                "hit_rate_pct": hit_rate,
                "long_n": int(long_mask.sum()),
                "long_mean_forward_return_points": long_mean,
                "short_n": int(short_mask.sum()),
                "short_mean_signed_forward_return_points": short_mean,
                "period_count": period_count,
                "positive_ic_period_pct": positive_ic_period_pct,
                "positive_active_ic_period_pct": positive_active_ic_period_pct,
                "positive_signed_period_pct": positive_signed_period_pct,
                "worst_period_signed_return_after_cost_points": worst_period_signed,
                "bootstrap_mean_ci_low_points": event_ci_low,
                "bootstrap_mean_ci_high_points": event_ci_high,
                "placebo_pool_mode": placebo_pool_mode,
                "placebo_pool_obs": placebo_pool_obs,
                "placebo_mean_signed_return_after_cost_points": placebo_mean,
                "placebo_edge_points": placebo_edge,
                "placebo_p_value": placebo_p_value,
                "eligible_for_candidate": bool(eligible),
                "event_eligible_for_candidate": bool(event_eligible),
            }
            summary_row.update(excursion_metrics)
            summary_row.update(stress_metrics)
            summary_rows.append(
                summary_row
            )

            for context_col in context_cols:
                context_values = df.loc[active_mask, context_col].fillna("unknown").astype(str)
                context_signed = signed_after_cost.loc[active_mask]
                context_hit = active_raw.loc[active_mask] > 0
                for value, idx in context_values.groupby(context_values).groups.items():
                    context_rows.append(
                        {
                            "signal": signal_col,
                            "horizon_bars": horizon,
                            "context": context_col,
                            "context_value": value,
                            "n_active": int(len(idx)),
                            "mean_signed_return_after_cost_points": _finite_mean(context_signed.loc[idx]),
                            "hit_rate_pct": float(context_hit.loc[idx].mean() * 100.0) if len(idx) else np.nan,
                        }
                    )

    summary = pd.DataFrame(summary_rows).sort_values(
        ["eligible_for_candidate", "event_eligible_for_candidate", "mean_signed_return_after_cost_points", "abs_ic"],
        ascending=[False, False, False, False],
    )
    period_stability = pd.DataFrame(period_rows)
    context_summary = pd.DataFrame(context_rows)

    summary_csv = out_path / f"{artifact_name}_summary.csv"
    period_csv = out_path / f"{artifact_name}_period_stability.csv"
    context_csv = out_path / f"{artifact_name}_context_summary.csv"
    report_md = out_path / f"{artifact_name}.md"

    summary.to_csv(summary_csv, index=False)
    period_stability.to_csv(period_csv, index=False)
    context_summary.to_csv(context_csv, index=False)
    _write_signal_research_report(
        report_md,
        summary,
        entry_price_col=entry_col,
        exit_price_col=exit_col,
        entry_lag_bars=entry_lag,
        round_trip_cost_points=round_trip_cost_points,
        stress_round_trip_cost_points=stress_costs,
        min_obs=min_obs,
        min_active_obs=min_active_obs,
        min_abs_ic=min_abs_ic,
        min_positive_period_pct=min_positive_period_pct,
        min_event_hit_rate_pct=min_event_hit_rate_pct,
        min_event_bootstrap_ci_low_points=min_event_bootstrap_ci_low_points,
        min_event_placebo_edge_points=min_event_placebo_edge_points,
        max_event_placebo_p_value=max_event_placebo_p_value,
        event_bootstrap_samples=event_bootstrap_samples,
        event_placebo_samples=event_placebo_samples,
    )
    return SignalResearchPaths(
        summary_csv=summary_csv,
        period_stability_csv=period_csv,
        context_summary_csv=context_csv,
        report_md=report_md,
    )


def _period_labels(times: pd.Series, period: str) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(times):
        return times.dt.to_period(period).astype(str).fillna("unknown")
    return pd.Series("all", index=times.index)


def _pearson(x: pd.Series, y: pd.Series) -> float:
    joined = pd.concat([pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")], axis=1).dropna()
    if len(joined) < 3:
        return np.nan
    if joined.iloc[:, 0].std(ddof=0) <= 0 or joined.iloc[:, 1].std(ddof=0) <= 0:
        return np.nan
    return float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))


def _finite_mean(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(values.mean()) if not values.empty else np.nan


def _finite_median(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(values.median()) if not values.empty else np.nan


def coerce_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").fillna(0).ne(0)
    normalized = series.fillna("").astype(str).str.strip().str.lower()
    return normalized.isin({"true", "1", "yes", "y", "t"})


def _normalize_stress_costs(*, primary_cost: float, stress_costs: Iterable[float]) -> tuple[float, ...]:
    cleaned: list[float] = []
    for raw in stress_costs:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(value):
            continue
        if value <= float(primary_cost):
            continue
        if value not in cleaned:
            cleaned.append(value)
    return tuple(sorted(cleaned))


def _cost_stress_metrics(
    active_raw_signed: pd.Series,
    signal_periods: pd.DataFrame,
    *,
    stress_costs: tuple[float, ...],
    primary_cost: float,
    min_positive_period_pct: float,
    min_event_bootstrap_ci_low_points: float,
    event_ci_low: float,
) -> dict[str, object]:
    if not stress_costs:
        return {
            "stress_round_trip_cost_points": "",
            "stress_max_round_trip_cost_points": np.nan,
            "stress_min_mean_signed_return_after_cost_points": np.nan,
            "stress_min_median_signed_return_after_cost_points": np.nan,
            "stress_min_positive_signed_period_pct": np.nan,
            "stress_min_worst_period_signed_return_after_cost_points": np.nan,
            "stress_min_bootstrap_mean_ci_low_points": np.nan,
            "stress_cost_survives": True,
            "stress_event_cost_survives": True,
            "stress_failure_reason": "",
        }

    active_raw = pd.to_numeric(active_raw_signed, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    raw_period_means = (
        pd.to_numeric(signal_periods.get("_raw_mean_signed_return_points", pd.Series(dtype=float)), errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
    )
    mean_values: list[float] = []
    median_values: list[float] = []
    positive_period_values: list[float] = []
    worst_period_values: list[float] = []
    ci_low_values: list[float] = []
    stress_cost_passes: list[bool] = []
    stress_event_passes: list[bool] = []
    failure_reasons: list[str] = []

    for cost in stress_costs:
        signed = active_raw - float(cost)
        mean_after_cost = _finite_mean(signed)
        median_after_cost = _finite_median(signed)
        if raw_period_means.empty:
            positive_period_pct = np.nan
            worst_period = np.nan
        else:
            period_after_cost = raw_period_means - float(cost)
            positive_period_pct = float(period_after_cost.gt(0.0).mean() * 100.0)
            worst_period = float(period_after_cost.min())
        ci_low = event_ci_low - (float(cost) - float(primary_cost)) if np.isfinite(event_ci_low) else np.nan

        mean_values.append(mean_after_cost)
        median_values.append(median_after_cost)
        positive_period_values.append(positive_period_pct)
        worst_period_values.append(worst_period)
        ci_low_values.append(ci_low)

        cost_pass = (
            np.isfinite(mean_after_cost)
            and mean_after_cost > 0.0
            and np.isfinite(positive_period_pct)
            and positive_period_pct >= float(min_positive_period_pct)
        )
        event_pass = cost_pass and np.isfinite(ci_low) and ci_low > float(min_event_bootstrap_ci_low_points)
        stress_cost_passes.append(bool(cost_pass))
        stress_event_passes.append(bool(event_pass))
        if not cost_pass:
            failure_reasons.append(f"{cost:g}pt_mean_or_period")
        elif not event_pass:
            failure_reasons.append(f"{cost:g}pt_bootstrap_ci")

    return {
        "stress_round_trip_cost_points": ",".join(f"{cost:g}" for cost in stress_costs),
        "stress_max_round_trip_cost_points": float(max(stress_costs)),
        "stress_min_mean_signed_return_after_cost_points": _finite_min(mean_values),
        "stress_min_median_signed_return_after_cost_points": _finite_min(median_values),
        "stress_min_positive_signed_period_pct": _finite_min(positive_period_values),
        "stress_min_worst_period_signed_return_after_cost_points": _finite_min(worst_period_values),
        "stress_min_bootstrap_mean_ci_low_points": _finite_min(ci_low_values),
        "stress_cost_survives": bool(all(stress_cost_passes)),
        "stress_event_cost_survives": bool(all(stress_event_passes)),
        "stress_failure_reason": ";".join(failure_reasons),
    }


def _finite_min(values: Iterable[float]) -> float:
    clean = pd.to_numeric(pd.Series(list(values)), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(clean.min()) if not clean.empty else np.nan


def _bootstrap_mean_ci(
    series: pd.Series,
    *,
    samples: int,
    confidence: float,
    rng: np.random.Generator,
) -> tuple[float, float]:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    if values.size == 0 or samples <= 0:
        return np.nan, np.nan
    sample_count = int(samples)
    chunk_size = max(1, min(sample_count, MAX_MONTE_CARLO_DRAW_CELLS // max(1, int(values.size))))
    means = np.empty(sample_count, dtype=float)
    offset = 0
    while offset < sample_count:
        chunk_count = min(chunk_size, sample_count - offset)
        draw_idx = rng.integers(0, values.size, size=(chunk_count, values.size))
        means[offset : offset + chunk_count] = values[draw_idx].mean(axis=1)
        offset += chunk_count
    alpha = max(0.0, min(1.0, 1.0 - float(confidence)))
    return (
        float(np.quantile(means, alpha / 2.0)),
        float(np.quantile(means, 1.0 - alpha / 2.0)),
    )


def _select_placebo_return_pool(
    *,
    forward_return: pd.Series,
    valid_mask: pd.Series,
    active_mask: pd.Series,
    times: pd.Series,
) -> tuple[pd.Series, str, int]:
    if pd.api.types.is_datetime64_any_dtype(times) and bool(active_mask.any()):
        minute_of_day = times.dt.hour * 60 + times.dt.minute
        if int(minute_of_day.loc[valid_mask].nunique()) > 1:
            active_minutes = set(minute_of_day.loc[active_mask].dropna().astype(int).unique())
            clock_mask = valid_mask & minute_of_day.isin(active_minutes)
            clock_obs = int(clock_mask.sum())
            if clock_obs >= max(30, int(active_mask.sum())):
                return forward_return.loc[clock_mask], "clock_matched", clock_obs
    full_obs = int(valid_mask.sum())
    return forward_return.loc[valid_mask], "full_sample", full_obs


def _evaluate_excursions_and_barriers(
    *,
    df: pd.DataFrame,
    active_mask: pd.Series,
    direction: pd.Series,
    entry_col: str,
    exit_col: str,
    entry_lag: int,
    horizon: int,
    round_trip_cost_points: float,
    bootstrap_samples: int,
    rng: np.random.Generator,
) -> dict[str, object]:
    empty_result: dict[str, object] = {
        "mean_mfe_points": np.nan,
        "mean_mae_points": np.nan,
        "barrier_mean_signed_return_after_cost_points": np.nan,
        "barrier_median_signed_return_after_cost_points": np.nan,
        "barrier_hit_rate_pct": np.nan,
        "barrier_target_hit_pct": np.nan,
        "barrier_stop_hit_pct": np.nan,
        "barrier_bootstrap_mean_ci_low_points": np.nan,
    }
    if "high" not in df.columns or "low" not in df.columns or not bool(active_mask.any()):
        return empty_result

    high_arr = pd.to_numeric(df["high"], errors="coerce").to_numpy(dtype=float)
    low_arr = pd.to_numeric(df["low"], errors="coerce").to_numpy(dtype=float)
    entry_arr = pd.to_numeric(df[entry_col], errors="coerce").to_numpy(dtype=float)
    exit_arr = pd.to_numeric(df[exit_col], errors="coerce").to_numpy(dtype=float)
    dir_arr = pd.to_numeric(direction, errors="coerce").to_numpy(dtype=float)

    has_stop = "stop_points" in df.columns
    has_target = "target_points" in df.columns
    stop_arr = pd.to_numeric(df["stop_points"], errors="coerce").to_numpy(dtype=float) if has_stop else None
    target_arr = pd.to_numeric(df["target_points"], errors="coerce").to_numpy(dtype=float) if has_target else None

    active_indices = np.flatnonzero(active_mask.to_numpy(dtype=bool))
    n_rows = len(df)
    mfe_list: list[float] = []
    mae_list: list[float] = []
    barrier_raw_returns: list[float] = []
    barrier_outcomes: list[str] = []

    for idx in active_indices:
        i_entry = int(idx) + int(entry_lag)
        i_exit = int(idx) + int(horizon)
        if i_entry >= n_rows or i_exit >= n_rows or i_entry > i_exit:
            continue
        p0 = entry_arr[i_entry]
        d = np.sign(dir_arr[idx])
        if not np.isfinite(p0) or d == 0.0:
            continue

        win_high = high_arr[i_entry : i_exit + 1]
        win_low = low_arr[i_entry : i_exit + 1]
        if win_high.size == 0 or np.all(np.isnan(win_high)) or np.all(np.isnan(win_low)):
            continue

        max_h = float(np.nanmax(win_high))
        min_l = float(np.nanmin(win_low))
        if d > 0:
            mfe = max(0.0, max_h - p0)
            mae = max(0.0, p0 - min_l)
        else:
            mfe = max(0.0, p0 - min_l)
            mae = max(0.0, max_h - p0)
        mfe_list.append(mfe)
        mae_list.append(mae)

        if has_stop or has_target:
            s_pts = float(stop_arr[idx]) if stop_arr is not None and np.isfinite(stop_arr[idx]) and stop_arr[idx] > 0 else np.nan
            t_pts = float(target_arr[idx]) if target_arr is not None and np.isfinite(target_arr[idx]) and target_arr[idx] > 0 else np.nan
            if np.isfinite(s_pts) or np.isfinite(t_pts):
                outcome = "timeout"
                realized_raw = float(d * (exit_arr[i_exit] - p0))
                for t_idx in range(i_entry, i_exit + 1):
                    bar_h = high_arr[t_idx]
                    bar_l = low_arr[t_idx]
                    if not np.isfinite(bar_h) or not np.isfinite(bar_l):
                        continue
                    stop_hit = False
                    target_hit = False
                    if np.isfinite(s_pts):
                        stop_hit = (bar_l <= p0 - s_pts) if d > 0 else (bar_h >= p0 + s_pts)
                    if np.isfinite(t_pts):
                        target_hit = (bar_h >= p0 + t_pts) if d > 0 else (bar_l <= p0 - t_pts)
                    # Conservative stop-first tie-breaker on same bar
                    if stop_hit:
                        outcome = "stop"
                        realized_raw = -s_pts
                        break
                    if target_hit:
                        outcome = "target"
                        realized_raw = t_pts
                        break
                barrier_raw_returns.append(realized_raw)
                barrier_outcomes.append(outcome)

    result = dict(empty_result)
    if mfe_list:
        result["mean_mfe_points"] = float(np.mean(mfe_list))
        result["mean_mae_points"] = float(np.mean(mae_list))
    if barrier_raw_returns:
        raw_s = pd.Series(barrier_raw_returns, dtype=float)
        after_cost_s = raw_s - float(round_trip_cost_points)
        outcomes_s = pd.Series(barrier_outcomes, dtype="object")
        ci_low, _ = _bootstrap_mean_ci(
            after_cost_s,
            samples=int(bootstrap_samples),
            confidence=0.95,
            rng=rng,
        )
        result["barrier_mean_signed_return_after_cost_points"] = _finite_mean(after_cost_s)
        result["barrier_median_signed_return_after_cost_points"] = _finite_median(after_cost_s)
        result["barrier_hit_rate_pct"] = float((raw_s > 0.0).mean() * 100.0)
        result["barrier_target_hit_pct"] = float(outcomes_s.eq("target").mean() * 100.0)
        result["barrier_stop_hit_pct"] = float(outcomes_s.eq("stop").mean() * 100.0)
        result["barrier_bootstrap_mean_ci_low_points"] = ci_low
    return result


def _placebo_event_test(
    forward_return: pd.Series,
    active_direction: pd.Series,
    *,
    observed_mean: float,
    round_trip_cost_points: float,
    samples: int,
    rng: np.random.Generator,
) -> tuple[float, float, float]:
    returns = pd.to_numeric(forward_return, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    directions = pd.to_numeric(active_direction, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    directions = np.sign(directions[directions != 0])
    if returns.size == 0 or directions.size == 0 or samples <= 0 or not np.isfinite(observed_mean):
        return np.nan, np.nan, np.nan

    n_active = int(directions.size)
    sample_count = int(samples)
    chunk_size = max(1, min(sample_count, MAX_MONTE_CARLO_DRAW_CELLS // max(1, n_active)))
    placebo_means = np.empty(sample_count, dtype=float)
    offset = 0
    while offset < sample_count:
        chunk_count = min(chunk_size, sample_count - offset)
        sampled_returns = returns[rng.integers(0, returns.size, size=(chunk_count, n_active))]
        placebo_means[offset : offset + chunk_count] = (
            sampled_returns * directions.reshape(1, -1) - float(round_trip_cost_points)
        ).mean(axis=1)
        offset += chunk_count
    placebo_mean = float(np.mean(placebo_means))
    edge = float(observed_mean - placebo_mean)
    p_value = float(np.mean(placebo_means >= float(observed_mean))) if float(observed_mean) > placebo_mean else 1.0
    return placebo_mean, edge, p_value


def _write_signal_research_report(
    path: Path,
    summary: pd.DataFrame,
    *,
    entry_price_col: str,
    exit_price_col: str,
    entry_lag_bars: int,
    round_trip_cost_points: float,
    stress_round_trip_cost_points: Iterable[float],
    min_obs: int,
    min_active_obs: int,
    min_abs_ic: float,
    min_positive_period_pct: float,
    min_event_hit_rate_pct: float,
    min_event_bootstrap_ci_low_points: float,
    min_event_placebo_edge_points: float,
    max_event_placebo_p_value: float,
    event_bootstrap_samples: int,
    event_placebo_samples: int,
) -> None:
    lines = [
        "# Signal Research Gate",
        "",
        "This is a pre-candidate report. It measures raw signal evidence before a signal is promoted into `CANDIDATE_CONFIGS`.",
        "",
        "## Gate",
        "",
        f"- Minimum observations: {min_obs}",
        f"- Minimum active observations: {min_active_obs}",
        f"- Minimum absolute IC: {min_abs_ic:.4f}",
        f"- Minimum positive signed-period share: {min_positive_period_pct:.1f}%",
        f"- Round-trip cost deducted from signed returns: {round_trip_cost_points:.4f} points",
        f"- Stress round-trip costs: {_format_stress_costs(stress_round_trip_cost_points)}",
        f"- Entry price: `{entry_price_col}` shifted {entry_lag_bars} bar(s) after the signal row",
        f"- Exit price: `{exit_price_col}` shifted by each horizon from the signal row",
        f"- Event gate minimum hit rate: {min_event_hit_rate_pct:.1f}%",
        f"- Event gate minimum bootstrap CI low: {min_event_bootstrap_ci_low_points:.4f} points",
        f"- Event gate minimum placebo edge (`signal_mean - placebo_mean`): {min_event_placebo_edge_points:.4f} points",
        f"- Event gate maximum placebo p-value: {max_event_placebo_p_value:.4f}",
        f"- Event bootstrap/placebo samples: {event_bootstrap_samples}/{event_placebo_samples}",
        "",
    ]
    if summary.empty:
        lines.extend(["## Verdict", "", "No signal rows were generated.", ""])
    else:
        eligible = summary.loc[coerce_bool_series(summary["eligible_for_candidate"])]
        lines.extend(["## Verdict", ""])
        if eligible.empty:
            lines.append("No signal passed the pre-candidate gate. Do not create a strategy candidate from this input.")
        else:
            lines.append("At least one signal passed the pre-candidate gate. Treat it as a hypothesis, not validation.")
        event_eligible = summary.loc[
            coerce_bool_series(summary.get("event_eligible_for_candidate", pd.Series(False, index=summary.index)))
        ]
        if stress_round_trip_cost_points:
            stress_survivors = summary.loc[
                coerce_bool_series(summary.get("stress_cost_survives", pd.Series(False, index=summary.index)))
            ]
            stress_event_survivors = summary.loc[
                coerce_bool_series(summary.get("stress_event_cost_survives", pd.Series(False, index=summary.index)))
            ]
            lines.extend(["", "## Cost Stress Verdict", ""])
            if stress_survivors.empty:
                lines.append("No signal survived all configured stress costs. Do not create a strategy candidate from base-cost evidence alone.")
            else:
                lines.append("At least one signal survived all configured stress costs. This is still hypothesis evidence, not validation.")
            if event_eligible.empty:
                lines.append("No event-gate row survived the base event gate.")
            elif stress_event_survivors.empty:
                lines.append("At least one row passed the base event gate, but no event-gate row survived all stress costs.")
            else:
                lines.append("At least one event-gate row survived all configured stress costs.")
        lines.extend(["", "## Event Gate Verdict", ""])
        if event_eligible.empty:
            lines.append("No signal passed the event-signal gate. Sparse event expectancy is not strong enough for candidate promotion.")
        else:
            lines.append("At least one signal passed the event-signal gate. Treat it as a candidate hypothesis, not validation.")
        lines.append("")
        suspicious = summary.loc[coerce_bool_series(summary["ic_suspicious_gt_0_10"])]
        if not suspicious.empty:
            lines.extend(
                [
                    "## Leakage Warning",
                    "",
                    "One or more signal/horizon pairs has absolute IC >= 0.10. For intraday NQ this is suspicious and should trigger point-in-time and alignment review before any candidate run.",
                    "",
                ]
            )
        display_cols = [
            "signal",
            "horizon_bars",
            "n_obs",
            "n_active",
            "active_pct",
            "ic",
            "active_ic",
            "mean_signed_return_after_cost_points",
            "median_signed_return_after_cost_points",
            "hit_rate_pct",
            "positive_signed_period_pct",
            "bootstrap_mean_ci_low_points",
            "mean_mfe_points",
            "mean_mae_points",
            "barrier_mean_signed_return_after_cost_points",
            "barrier_hit_rate_pct",
            "stress_round_trip_cost_points",
            "stress_min_mean_signed_return_after_cost_points",
            "stress_min_positive_signed_period_pct",
            "stress_min_bootstrap_mean_ci_low_points",
            "stress_cost_survives",
            "stress_event_cost_survives",
            "placebo_pool_mode",
            "placebo_edge_points",
            "placebo_p_value",
            "eligible_for_candidate",
            "event_eligible_for_candidate",
        ]
        lines.extend(["## Top Rows", ""])
        lines.append(summary.loc[:, [col for col in display_cols if col in summary.columns]].head(20).to_string(index=False))
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _format_stress_costs(stress_round_trip_cost_points: Iterable[float]) -> str:
    costs = list(stress_round_trip_cost_points)
    if not costs:
        return "none"
    return ", ".join(f"{float(cost):.4f} points" for cost in costs)
