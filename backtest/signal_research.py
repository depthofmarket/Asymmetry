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
}


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
    horizons_bars: Iterable[int] = DEFAULT_HORIZONS_BARS,
    period: str = "Q",
    round_trip_cost_points: float = 0.0,
    min_obs: int = 100,
    min_active_obs: int = 30,
    min_abs_ic: float = 0.02,
    min_positive_period_pct: float = 55.0,
) -> SignalResearchPaths:
    df = data.copy()
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if price_col not in df.columns:
        raise ValueError(f"price column not found: {price_col}")

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
    if time_col in df.columns:
        times = pd.to_datetime(df[time_col], errors="coerce")
    else:
        times = pd.Series(pd.RangeIndex(len(df)), index=df.index)
    period_labels = _period_labels(times, period)

    summary_rows: list[dict[str, object]] = []
    period_rows: list[dict[str, object]] = []
    context_rows: list[dict[str, object]] = []

    for horizon in [int(item) for item in horizons_bars]:
        if horizon <= 0:
            continue
        forward_return = df[price_col].shift(-horizon) - df[price_col]
        for signal_col in selected_signals:
            signal = pd.to_numeric(df[signal_col], errors="coerce")
            direction = np.sign(signal)
            active_mask = direction.ne(0) & signal.notna() & forward_return.notna()
            valid_mask = signal.notna() & forward_return.notna()
            signed_points = direction * forward_return
            signed_after_cost = signed_points - float(round_trip_cost_points)

            ic = _pearson(signal.loc[valid_mask], forward_return.loc[valid_mask])
            active_signed = signed_after_cost.loc[active_mask]
            active_raw = signed_points.loc[active_mask]
            active_forward = forward_return.loc[active_mask]
            hit_rate = float((active_raw > 0).mean() * 100.0) if not active_raw.empty else np.nan
            long_mask = active_mask & direction.gt(0)
            short_mask = active_mask & direction.lt(0)

            for period_value, idx in active_mask.groupby(period_labels).groups.items():
                period_mask = active_mask.loc[idx]
                if not bool(period_mask.any()):
                    continue
                period_signal = signal.loc[idx]
                period_forward = forward_return.loc[idx]
                period_valid = period_signal.notna() & period_forward.notna()
                period_direction = direction.loc[idx]
                period_active = period_direction.ne(0) & period_valid
                period_signed = (period_direction * period_forward - float(round_trip_cost_points)).loc[period_active]
                period_rows.append(
                    {
                        "signal": signal_col,
                        "horizon_bars": horizon,
                        "period": str(period_value),
                        "n_active": int(period_active.sum()),
                        "ic": _pearson(period_signal.loc[period_valid], period_forward.loc[period_valid]),
                        "mean_signed_return_after_cost_points": _finite_mean(period_signed),
                        "hit_rate_pct": float(((period_direction * period_forward).loc[period_active] > 0).mean() * 100.0)
                        if int(period_active.sum()) > 0
                        else np.nan,
                    }
                )

            signal_periods = pd.DataFrame([row for row in period_rows if row["signal"] == signal_col and row["horizon_bars"] == horizon])
            period_count = int(len(signal_periods))
            positive_ic_period_pct = (
                float((pd.to_numeric(signal_periods["ic"], errors="coerce") > 0).mean() * 100.0)
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
            eligible = (
                int(valid_mask.sum()) >= int(min_obs)
                and int(active_mask.sum()) >= int(min_active_obs)
                and np.isfinite(ic)
                and abs(float(ic)) >= float(min_abs_ic)
                and np.isfinite(signed_mean_after_cost)
                and signed_mean_after_cost > 0
                and np.isfinite(positive_signed_period_pct)
                and positive_signed_period_pct >= float(min_positive_period_pct)
            )

            summary_rows.append(
                {
                    "signal": signal_col,
                    "horizon_bars": horizon,
                    "n_obs": int(valid_mask.sum()),
                    "n_active": int(active_mask.sum()),
                    "active_pct": float(active_mask.mean() * 100.0),
                    "ic": ic,
                    "abs_ic": abs(ic) if np.isfinite(ic) else np.nan,
                    "ic_suspicious_gt_0_10": bool(np.isfinite(ic) and abs(ic) >= 0.10),
                    "mean_forward_return_points": _finite_mean(active_forward),
                    "mean_signed_return_points": _finite_mean(active_raw),
                    "mean_signed_return_after_cost_points": signed_mean_after_cost,
                    "hit_rate_pct": hit_rate,
                    "long_n": int(long_mask.sum()),
                    "long_mean_forward_return_points": long_mean,
                    "short_n": int(short_mask.sum()),
                    "short_mean_signed_forward_return_points": short_mean,
                    "period_count": period_count,
                    "positive_ic_period_pct": positive_ic_period_pct,
                    "positive_signed_period_pct": positive_signed_period_pct,
                    "worst_period_signed_return_after_cost_points": worst_period_signed,
                    "eligible_for_candidate": bool(eligible),
                }
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
        ["eligible_for_candidate", "mean_signed_return_after_cost_points", "abs_ic"],
        ascending=[False, False, False],
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
        round_trip_cost_points=round_trip_cost_points,
        min_obs=min_obs,
        min_active_obs=min_active_obs,
        min_abs_ic=min_abs_ic,
        min_positive_period_pct=min_positive_period_pct,
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


def _write_signal_research_report(
    path: Path,
    summary: pd.DataFrame,
    *,
    round_trip_cost_points: float,
    min_obs: int,
    min_active_obs: int,
    min_abs_ic: float,
    min_positive_period_pct: float,
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
        "",
    ]
    if summary.empty:
        lines.extend(["## Verdict", "", "No signal rows were generated.", ""])
    else:
        eligible = summary.loc[summary["eligible_for_candidate"].astype(bool)]
        lines.extend(["## Verdict", ""])
        if eligible.empty:
            lines.append("No signal passed the pre-candidate gate. Do not create a strategy candidate from this input.")
        else:
            lines.append("At least one signal passed the pre-candidate gate. Treat it as a hypothesis, not validation.")
        lines.append("")
        suspicious = summary.loc[summary["ic_suspicious_gt_0_10"].astype(bool)]
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
            "mean_signed_return_after_cost_points",
            "hit_rate_pct",
            "positive_signed_period_pct",
            "eligible_for_candidate",
        ]
        lines.extend(["## Top Rows", ""])
        lines.append(summary.loc[:, [col for col in display_cols if col in summary.columns]].head(20).to_string(index=False))
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
