from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_research import DEFAULT_HORIZONS_BARS, coerce_bool_series, run_signal_research_report


DEFAULT_TEMPORAL_SPLITS = (
    ("legacy_context", "2010-01-01", "2015-12-31"),
    ("transition", "2016-01-01", "2020-12-31"),
    ("recent_development", "2021-01-01", "2024-12-31"),
)


@dataclass(frozen=True)
class TemporalSignalResearchPaths:
    combined_summary_csv: Path
    report_md: Path
    split_report_paths: tuple[Path, ...]


def run_temporal_signal_research_report(
    data: pd.DataFrame,
    *,
    out_dir: Path | str,
    artifact_name: str = "temporal_signal_research",
    splits: Iterable[tuple[str, str, str | None]] = DEFAULT_TEMPORAL_SPLITS,
    primary_split: str = "recent_development",
    supporting_splits: Iterable[str] = ("transition",),
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
) -> TemporalSignalResearchPaths:
    df = data.copy()
    if time_col not in df.columns:
        raise ValueError(f"time column not found: {time_col}")
    times = pd.to_datetime(df[time_col], errors="coerce")
    if times.isna().all():
        raise ValueError(f"time column has no parseable timestamps: {time_col}")
    df[time_col] = times

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    split_rows: list[pd.DataFrame] = []
    split_report_paths: list[Path] = []
    normalized_splits = list(splits)
    if not normalized_splits:
        raise ValueError("at least one temporal split is required")

    for split_name, start, end in normalized_splits:
        mask = _date_mask(df[time_col], start, end)
        split_df = df.loc[mask].copy()
        split_artifact = f"{artifact_name}_{_safe_slug(split_name)}"
        paths = run_signal_research_report(
            split_df,
            out_dir=out_path,
            artifact_name=split_artifact,
            signal_cols=signal_cols,
            context_cols=context_cols,
            time_col=time_col,
            price_col=price_col,
            entry_price_col=entry_price_col,
            exit_price_col=exit_price_col,
            entry_lag_bars=entry_lag_bars,
            horizons_bars=horizons_bars,
            period=period,
            round_trip_cost_points=round_trip_cost_points,
            stress_round_trip_cost_points=stress_round_trip_cost_points,
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
            event_random_seed=event_random_seed,
        )
        split_report_paths.append(paths.report_md)
        summary = pd.read_csv(paths.summary_csv)
        summary.insert(0, "split", split_name)
        summary.insert(1, "split_start", start)
        summary.insert(2, "split_end", end or "")
        summary.insert(3, "split_rows", int(len(split_df)))
        split_rows.append(summary)

    combined = pd.concat(split_rows, ignore_index=True) if split_rows else pd.DataFrame()
    combined["temporal_eligible_for_candidate"] = _temporal_eligibility(
        combined,
        primary_split=primary_split,
        supporting_splits=list(supporting_splits),
        min_active_obs=min_active_obs,
        min_abs_ic=min_abs_ic,
    )
    combined["temporal_event_eligible_for_candidate"] = _temporal_event_eligibility(
        combined,
        primary_split=primary_split,
        supporting_splits=list(supporting_splits),
    )

    combined_csv = out_path / f"{artifact_name}_temporal_summary.csv"
    report_md = out_path / f"{artifact_name}_temporal.md"
    combined.to_csv(combined_csv, index=False)
    _write_temporal_report(
        report_md,
        combined,
        splits=normalized_splits,
        primary_split=primary_split,
        supporting_splits=list(supporting_splits),
        split_report_paths=split_report_paths,
        round_trip_cost_points=round_trip_cost_points,
        stress_round_trip_cost_points=stress_round_trip_cost_points,
        min_active_obs=min_active_obs,
        min_abs_ic=min_abs_ic,
        min_positive_period_pct=min_positive_period_pct,
        min_event_hit_rate_pct=min_event_hit_rate_pct,
        min_event_bootstrap_ci_low_points=min_event_bootstrap_ci_low_points,
        min_event_placebo_edge_points=min_event_placebo_edge_points,
        max_event_placebo_p_value=max_event_placebo_p_value,
    )
    return TemporalSignalResearchPaths(
        combined_summary_csv=combined_csv,
        report_md=report_md,
        split_report_paths=tuple(split_report_paths),
    )


def parse_temporal_splits(value: str) -> tuple[tuple[str, str, str | None], ...]:
    splits: list[tuple[str, str, str | None]] = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) not in (2, 3):
            raise ValueError(f"invalid split spec {item!r}; expected name:start[:end]")
        name = parts[0].strip()
        start = parts[1].strip()
        end = parts[2].strip() if len(parts) == 3 and parts[2].strip() else None
        if not name or not start:
            raise ValueError(f"invalid split spec {item!r}; name and start are required")
        splits.append((name, start, end))
    if not splits:
        raise ValueError("no temporal splits supplied")
    return tuple(splits)


def _date_mask(times: pd.Series, start: str, end: str | None) -> pd.Series:
    start_ts = pd.Timestamp(start)
    mask = times.ge(start_ts)
    if end:
        end_ts = pd.Timestamp(end)
        if end_ts == end_ts.normalize():
            end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        mask &= times.le(end_ts)
    return mask.fillna(False)


def _temporal_eligibility(
    combined: pd.DataFrame,
    *,
    primary_split: str,
    supporting_splits: list[str],
    min_active_obs: int,
    min_abs_ic: float,
) -> pd.Series:
    if combined.empty:
        return pd.Series(dtype=bool)
    keys = ["signal", "horizon_bars"]
    result = pd.Series(False, index=combined.index)
    grouped = combined.groupby(keys, dropna=False)
    for _, group in grouped:
        primary = group.loc[group["split"].astype(str).eq(primary_split)]
        if primary.empty:
            continue
        primary_pass = bool(coerce_bool_series(primary["eligible_for_candidate"]).any())
        if not primary_pass:
            continue
        support_ok = True
        for split_name in supporting_splits:
            support = group.loc[group["split"].astype(str).eq(split_name)]
            if support.empty:
                support_ok = False
                break
            support_row = support.iloc[0]
            support_ok = bool(
                int(support_row.get("n_active", 0)) >= int(min_active_obs)
                and np.isfinite(float(support_row.get("ic", np.nan)))
                and abs(float(support_row.get("ic", np.nan))) >= float(min_abs_ic)
                and float(support_row.get("mean_signed_return_after_cost_points", np.nan)) > 0
                and _support_stress_survives(support_row)
            )
            if not support_ok:
                break
        if support_ok:
            result.loc[group.index] = True
    return result


def _temporal_event_eligibility(
    combined: pd.DataFrame,
    *,
    primary_split: str,
    supporting_splits: list[str],
) -> pd.Series:
    if combined.empty or "event_eligible_for_candidate" not in combined.columns:
        return pd.Series(False, index=combined.index)
    keys = ["signal", "horizon_bars"]
    result = pd.Series(False, index=combined.index)
    grouped = combined.groupby(keys, dropna=False)
    for _, group in grouped:
        primary = group.loc[group["split"].astype(str).eq(primary_split)]
        if primary.empty or not bool(coerce_bool_series(primary["event_eligible_for_candidate"]).any()):
            continue
        support_ok = True
        for split_name in supporting_splits:
            support = group.loc[group["split"].astype(str).eq(split_name)]
            if support.empty or not bool(coerce_bool_series(support["event_eligible_for_candidate"]).any()):
                support_ok = False
                break
        if support_ok:
            result.loc[group.index] = True
    return result


def _write_temporal_report(
    path: Path,
    combined: pd.DataFrame,
    *,
    splits: list[tuple[str, str, str | None]],
    primary_split: str,
    supporting_splits: list[str],
    split_report_paths: list[Path],
    round_trip_cost_points: float,
    stress_round_trip_cost_points: Iterable[float],
    min_active_obs: int,
    min_abs_ic: float,
    min_positive_period_pct: float,
    min_event_hit_rate_pct: float,
    min_event_bootstrap_ci_low_points: float,
    min_event_placebo_edge_points: float,
    max_event_placebo_p_value: float,
) -> None:
    lines = [
        "# Temporal Signal Research Gate",
        "",
        "This report compares pre-candidate signal evidence across fixed calendar eras before any strategy candidate is created.",
        "",
        "## Splits",
        "",
    ]
    for name, start, end in splits:
        suffix = end or "open"
        role = "primary" if name == primary_split else "supporting" if name in supporting_splits else "context"
        lines.append(f"- `{name}` ({role}): {start} to {suffix}")
    lines.extend(
        [
            "",
            "## Gate",
            "",
            f"- Primary split: `{primary_split}`",
            f"- Supporting splits: `{','.join(supporting_splits) if supporting_splits else 'none'}`",
            f"- Minimum active observations per required split: {min_active_obs}",
            f"- Minimum absolute IC per required split: {min_abs_ic:.4f}",
            f"- Minimum positive signed-period share in split reports: {min_positive_period_pct:.1f}%",
            f"- Round-trip cost deducted from signed returns: {round_trip_cost_points:.4f} points",
            f"- Stress round-trip costs: {_format_stress_costs(stress_round_trip_cost_points)}",
            f"- Event gate minimum hit rate: {min_event_hit_rate_pct:.1f}%",
            f"- Event gate minimum bootstrap CI low: {min_event_bootstrap_ci_low_points:.4f} points",
            f"- Event gate minimum placebo edge: {min_event_placebo_edge_points:.4f} points",
            f"- Event gate maximum placebo p-value: {max_event_placebo_p_value:.4f}",
            "",
            "## Verdict",
            "",
        ]
    )
    temporal_ic_pass = (not combined.empty) and bool(coerce_bool_series(combined["temporal_eligible_for_candidate"]).any())
    temporal_event_pass = (
        (not combined.empty)
        and "temporal_event_eligible_for_candidate" in combined.columns
        and bool(coerce_bool_series(combined["temporal_event_eligible_for_candidate"]).any())
    )
    if not temporal_ic_pass:
        lines.append("No signal/horizon pair passed the temporal pre-candidate gate. Do not create a strategy candidate from this input.")
    else:
        lines.append("At least one signal/horizon pair passed the temporal pre-candidate gate. Treat it as a hypothesis, not validation.")
    lines.extend(["", "## Event Gate Verdict", ""])
    if not temporal_event_pass:
        lines.append("No signal/horizon pair passed the temporal event-signal gate. Sparse event evidence is not strong enough for candidate promotion.")
    else:
        lines.append("At least one signal/horizon pair passed the temporal event-signal gate. Treat it as a candidate hypothesis, not validation.")
    if list(stress_round_trip_cost_points):
        split_stress_pass = (
            (not combined.empty)
            and "stress_cost_survives" in combined.columns
            and bool(coerce_bool_series(combined["stress_cost_survives"]).any())
        )
        split_event_stress_pass = (
            (not combined.empty)
            and "stress_event_cost_survives" in combined.columns
            and bool(coerce_bool_series(combined["stress_event_cost_survives"]).any())
        )
        lines.extend(["", "## Cost Stress Verdict", ""])
        if not split_stress_pass:
            lines.append("No split row survived all configured stress costs. Base-cost evidence is not enough for candidate promotion.")
        elif not temporal_ic_pass:
            lines.append("At least one split row survived stress costs, but no signal/horizon pair passed temporal IC eligibility.")
        else:
            lines.append("At least one temporal IC-eligible signal/horizon pair survived the configured stress costs.")
        if not split_event_stress_pass:
            lines.append("No split event-gate row survived all configured stress costs.")
        elif temporal_event_pass:
            lines.append("At least one temporal event-gate row survived all configured stress costs.")
        else:
            lines.append("At least one split event-gate row survived stress costs, but temporal event eligibility still failed.")
    lines.extend(["", "## Top Rows", ""])
    display_cols = [
        "split",
        "signal",
        "horizon_bars",
        "n_active",
        "ic",
        "mean_signed_return_after_cost_points",
        "positive_signed_period_pct",
        "bootstrap_mean_ci_low_points",
        "stress_round_trip_cost_points",
        "stress_min_mean_signed_return_after_cost_points",
        "stress_min_positive_signed_period_pct",
        "stress_min_bootstrap_mean_ci_low_points",
        "stress_cost_survives",
        "stress_event_cost_survives",
        "placebo_edge_points",
        "placebo_p_value",
        "eligible_for_candidate",
        "event_eligible_for_candidate",
        "temporal_eligible_for_candidate",
        "temporal_event_eligible_for_candidate",
    ]
    if combined.empty:
        lines.append("No rows.")
    else:
        ranked = combined.copy()
        ranked["_temporal_eligible_rank"] = coerce_bool_series(ranked["temporal_eligible_for_candidate"])
        ranked["_temporal_event_eligible_rank"] = coerce_bool_series(ranked["temporal_event_eligible_for_candidate"])
        ranked = ranked.sort_values(
            [
                "_temporal_eligible_rank",
                "_temporal_event_eligible_rank",
                "split",
                "mean_signed_return_after_cost_points",
                "abs_ic",
            ],
            ascending=[False, False, True, False, False],
        )
        lines.append(ranked.loc[:, [col for col in display_cols if col in ranked.columns]].head(40).to_string(index=False))
    lines.extend(["", "## Split Reports", ""])
    for report_path in split_report_paths:
        lines.append(f"- `{report_path}`")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _safe_slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in str(value)).strip("_")


def _support_stress_survives(row: pd.Series) -> bool:
    if "stress_cost_survives" not in row.index:
        return True
    return bool(coerce_bool_series(pd.Series([row.get("stress_cost_survives")])).iloc[0])


def _format_stress_costs(stress_round_trip_cost_points: Iterable[float]) -> str:
    costs = list(stress_round_trip_cost_points)
    if not costs:
        return "none"
    return ", ".join(f"{float(cost):.4f} points" for cost in costs)
