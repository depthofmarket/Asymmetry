from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CusumEventStudyPaths:
    events_csv: Path
    summary_csv: Path
    frequency_sweep_csv: Path
    random_baseline_csv: Path


def _finite_positive(value: float, fallback: float) -> float:
    value = float(value)
    if np.isfinite(value) and value > 0:
        return value
    return float(fallback)


def add_cusum_event_features(
    data: pd.DataFrame,
    *,
    price_col: str = "close",
    atr_col: str = "atr",
    threshold_atr_multiple: float = 1.0,
    min_threshold_points: float = 0.25,
) -> pd.DataFrame:
    """
    Mark volatility-normalized CUSUM movement events.

    These are event-defining features, not trading signals. An up event means
    cumulative positive price movement exceeded the current ATR-scaled
    threshold; a down event means cumulative negative movement exceeded it.
    Buckets reset after either side fires so each event is a fresh decision
    point for later research.
    """
    missing = {price_col, atr_col}.difference(data.columns)
    if missing:
        raise ValueError(f"CUSUM event sampling requires columns: {sorted(missing)}")

    df = data.copy()
    threshold_atr_multiple = _finite_positive(threshold_atr_multiple, 1.0)
    min_threshold_points = max(0.0, float(min_threshold_points))

    close = pd.to_numeric(df[price_col], errors="coerce").to_numpy(dtype=float)
    atr = pd.to_numeric(df[atr_col], errors="coerce").to_numpy(dtype=float)
    n = len(df)

    pos_bucket = np.zeros(n, dtype=float)
    neg_bucket = np.zeros(n, dtype=float)
    threshold_arr = np.full(n, np.nan, dtype=float)
    event_direction = np.zeros(n, dtype=np.int8)
    event_move_points = np.full(n, np.nan, dtype=float)
    bars_since_event = np.full(n, np.nan, dtype=float)

    pos = 0.0
    neg = 0.0
    last_event_idx: int | None = None

    for idx in range(1, n):
        threshold = max(float(atr[idx]) * threshold_atr_multiple, min_threshold_points)
        if not np.isfinite(threshold) or threshold <= 0:
            threshold_arr[idx] = np.nan
            pos_bucket[idx] = pos
            neg_bucket[idx] = neg
            continue

        threshold_arr[idx] = threshold

        if not np.isfinite(close[idx]) or not np.isfinite(close[idx - 1]):
            pos_bucket[idx] = pos
            neg_bucket[idx] = neg
            continue

        change = close[idx] - close[idx - 1]
        pos = max(0.0, pos + change)
        neg = min(0.0, neg + change)

        if pos >= threshold:
            event_direction[idx] = 1
            event_move_points[idx] = pos
            pos = 0.0
            neg = 0.0
            last_event_idx = idx
        elif neg <= -threshold:
            event_direction[idx] = -1
            event_move_points[idx] = neg
            pos = 0.0
            neg = 0.0
            last_event_idx = idx

        pos_bucket[idx] = pos
        neg_bucket[idx] = neg
        if last_event_idx is not None:
            bars_since_event[idx] = float(idx - last_event_idx)

    event_triggered = event_direction != 0
    move_atr = event_move_points / np.where(np.isfinite(atr) & (atr != 0), atr, np.nan)

    df["cusum_pos_bucket"] = pos_bucket
    df["cusum_neg_bucket"] = neg_bucket
    df["cusum_threshold_points"] = threshold_arr
    df["cusum_event"] = event_triggered
    df["cusum_event_up"] = event_direction == 1
    df["cusum_event_down"] = event_direction == -1
    df["cusum_event_direction"] = event_direction
    df["cusum_event_move_points"] = event_move_points
    df["cusum_event_move_atr"] = move_atr
    df["cusum_bars_since_event"] = bars_since_event
    return df


def _years_covered(data: pd.DataFrame) -> float:
    if "time" not in data.columns or data.empty:
        return 1.0
    times = pd.to_datetime(data["time"], errors="coerce").dropna()
    if times.empty:
        return 1.0
    days = (times.max() - times.min()).total_seconds() / (24 * 3600)
    return max(days / 365.25, 1.0 / 365.25)


def _add_forward_outcomes(data: pd.DataFrame, horizons_bars: tuple[int, ...]) -> pd.DataFrame:
    df = data.copy()
    close = pd.to_numeric(df["close"], errors="coerce")
    atr = pd.to_numeric(df["atr"], errors="coerce") if "atr" in df.columns else pd.Series(np.nan, index=df.index)
    direction = pd.to_numeric(df.get("cusum_event_direction", 0), errors="coerce").fillna(0)

    for horizon in horizons_bars:
        horizon = int(horizon)
        if horizon <= 0:
            continue
        forward_points = close.shift(-horizon) - close
        forward_atr = forward_points / atr.replace(0, np.nan)
        directional_points = forward_points * direction

        df[f"fwd_points_{horizon}b"] = forward_points
        df[f"fwd_atr_{horizon}b"] = forward_atr
        df[f"directional_fwd_points_{horizon}b"] = directional_points
        df[f"directional_hit_{horizon}b"] = directional_points.gt(0)

    return df


def _summarize_events(events: pd.DataFrame, horizons_bars: tuple[int, ...]) -> pd.DataFrame:
    rows: list[dict] = []
    if events.empty:
        return pd.DataFrame(columns=[
            "group",
            "horizon_bars",
            "events",
            "mean_forward_points",
            "median_forward_points",
            "mean_forward_atr",
            "mean_directional_points",
            "median_directional_points",
            "directional_hit_rate",
        ])

    groups = {"all": events}
    if "cusum_event_direction" in events.columns:
        groups["up_event"] = events.loc[events["cusum_event_direction"].eq(1)]
        groups["down_event"] = events.loc[events["cusum_event_direction"].eq(-1)]

    if "hour_min" in events.columns:
        hour = events["hour_min"].astype(str).str.slice(0, 2)
        groups["rth"] = events.loc[hour.between("09", "15")]
        groups["overnight"] = events.loc[~hour.between("09", "15")]

    for group_name, group in groups.items():
        if group.empty:
            continue
        for horizon in horizons_bars:
            fwd = pd.to_numeric(group.get(f"fwd_points_{horizon}b"), errors="coerce")
            fwd_atr = pd.to_numeric(group.get(f"fwd_atr_{horizon}b"), errors="coerce")
            directional = pd.to_numeric(group.get(f"directional_fwd_points_{horizon}b"), errors="coerce")
            hit = pd.to_numeric(group.get(f"directional_hit_{horizon}b"), errors="coerce")
            valid = fwd.notna()
            rows.append({
                "group": group_name,
                "horizon_bars": int(horizon),
                "events": int(valid.sum()),
                "mean_forward_points": float(fwd[valid].mean()) if valid.any() else np.nan,
                "median_forward_points": float(fwd[valid].median()) if valid.any() else np.nan,
                "mean_forward_atr": float(fwd_atr[valid].mean()) if valid.any() else np.nan,
                "mean_directional_points": float(directional[valid].mean()) if valid.any() else np.nan,
                "median_directional_points": float(directional[valid].median()) if valid.any() else np.nan,
                "directional_hit_rate": float(hit[valid].mean()) if valid.any() else np.nan,
            })

    return pd.DataFrame(rows)


def _frequency_sweep(
    data: pd.DataFrame,
    *,
    threshold_values: tuple[float, ...],
    min_threshold_points: float,
) -> pd.DataFrame:
    rows: list[dict] = []
    years = _years_covered(data)
    for threshold in threshold_values:
        sampled = add_cusum_event_features(
            data,
            threshold_atr_multiple=float(threshold),
            min_threshold_points=min_threshold_points,
        )
        event_mask = sampled["cusum_event"].astype(bool)
        event_indices = np.flatnonzero(event_mask.to_numpy())
        if len(event_indices) > 1:
            median_bars_between = float(np.median(np.diff(event_indices)))
        else:
            median_bars_between = np.nan
        rows.append({
            "threshold_atr_multiple": float(threshold),
            "event_count": int(event_mask.sum()),
            "up_events": int(sampled["cusum_event_up"].sum()),
            "down_events": int(sampled["cusum_event_down"].sum()),
            "events_per_year": float(event_mask.sum() / years),
            "median_bars_between_events": median_bars_between,
            "mean_abs_event_move_points": float(sampled.loc[event_mask, "cusum_event_move_points"].abs().mean()),
        })
    return pd.DataFrame(rows)


def _random_baseline_summary(
    data: pd.DataFrame,
    *,
    event_count: int,
    horizons_bars: tuple[int, ...],
    n_samples: int,
    seed: int,
) -> pd.DataFrame:
    if event_count <= 0 or data.empty:
        return pd.DataFrame()

    max_horizon = max(horizons_bars) if horizons_bars else 0
    valid_indices = np.arange(max(0, len(data) - max_horizon), dtype=int)
    if len(valid_indices) == 0:
        return pd.DataFrame()

    rng = np.random.default_rng(int(seed))
    close = pd.to_numeric(data["close"], errors="coerce").to_numpy(dtype=float)
    atr = pd.to_numeric(data.get("atr", pd.Series(np.nan, index=data.index)), errors="coerce").to_numpy(dtype=float)
    sample_size = min(int(event_count), len(valid_indices))

    rows: list[dict] = []
    for sample_idx in range(max(1, int(n_samples))):
        picks = rng.choice(valid_indices, size=sample_size, replace=False)
        for horizon in horizons_bars:
            future = picks + int(horizon)
            forward_points = close[future] - close[picks]
            forward_atr = forward_points / np.where(np.isfinite(atr[picks]) & (atr[picks] != 0), atr[picks], np.nan)
            rows.append({
                "sample": sample_idx,
                "horizon_bars": int(horizon),
                "events": int(sample_size),
                "mean_forward_points": float(np.nanmean(forward_points)),
                "median_forward_points": float(np.nanmedian(forward_points)),
                "mean_forward_atr": float(np.nanmean(forward_atr)),
            })

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary

    return (
        summary.groupby("horizon_bars", as_index=False)
        .agg(
            samples=("sample", "nunique"),
            events_per_sample=("events", "median"),
            mean_forward_points_p05=("mean_forward_points", lambda s: float(np.nanpercentile(s, 5))),
            mean_forward_points_p50=("mean_forward_points", "median"),
            mean_forward_points_p95=("mean_forward_points", lambda s: float(np.nanpercentile(s, 95))),
            median_forward_points_p50=("median_forward_points", "median"),
            mean_forward_atr_p50=("mean_forward_atr", "median"),
        )
    )


def export_cusum_event_study(
    data: pd.DataFrame,
    *,
    out_dir: Path,
    artifact_name: str = "cusum_events",
    horizons_bars: tuple[int, ...] = (1, 3, 6, 12, 24),
    threshold_atr_multiple: float = 1.0,
    min_threshold_points: float = 0.25,
    frequency_thresholds: tuple[float, ...] = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0),
    random_baseline_samples: int = 200,
    random_seed: int = 7,
) -> CusumEventStudyPaths:
    """
    Export a candle-sampling research pack.

    The event CSV is the raw experiment universe. The summary compares forward
    outcomes after up/down events, while the random baseline helps spot whether
    observed outcomes are just drift/noise for the same sample size.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    horizons = tuple(sorted({int(h) for h in horizons_bars if int(h) > 0}))
    sampled = add_cusum_event_features(
        data,
        threshold_atr_multiple=threshold_atr_multiple,
        min_threshold_points=min_threshold_points,
    )
    studied = _add_forward_outcomes(sampled, horizons)
    events = studied.loc[studied["cusum_event"].astype(bool)].copy()

    context_cols = [
        "time",
        "hour_min",
        "date_str",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "atr",
        "vwap",
        "vwap_z",
        "day_regime",
        "open_context",
        "overnight_inventory_direction",
        "vp_poc",
        "vp_val",
        "vp_vah",
        "vsa_score",
        "vsa_absorption",
        "vsa_thin_move",
        "hawkes_vol",
        "hawkes_momentum_signal",
        "cusum_threshold_points",
        "cusum_event_direction",
        "cusum_event_move_points",
        "cusum_event_move_atr",
        "cusum_bars_since_event",
    ]
    outcome_cols: list[str] = []
    for horizon in horizons:
        outcome_cols.extend([
            f"fwd_points_{horizon}b",
            f"fwd_atr_{horizon}b",
            f"directional_fwd_points_{horizon}b",
            f"directional_hit_{horizon}b",
        ])
    export_cols = [col for col in context_cols + outcome_cols if col in events.columns]

    events_path = out_dir / f"{artifact_name}.csv"
    summary_path = out_dir / f"{artifact_name}_summary.csv"
    frequency_path = out_dir / f"{artifact_name}_frequency_sweep.csv"
    baseline_path = out_dir / f"{artifact_name}_random_baseline.csv"

    events.loc[:, export_cols].to_csv(events_path, index=False)
    _summarize_events(events, horizons).to_csv(summary_path, index=False)
    _frequency_sweep(
        data,
        threshold_values=frequency_thresholds,
        min_threshold_points=min_threshold_points,
    ).to_csv(frequency_path, index=False)
    _random_baseline_summary(
        studied,
        event_count=len(events),
        horizons_bars=horizons,
        n_samples=random_baseline_samples,
        seed=random_seed,
    ).to_csv(baseline_path, index=False)

    return CusumEventStudyPaths(
        events_csv=events_path,
        summary_csv=summary_path,
        frequency_sweep_csv=frequency_path,
        random_baseline_csv=baseline_path,
    )
