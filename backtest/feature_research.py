from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeatureResearchLabPaths:
    events_csv: Path
    event_summary_csv: Path
    barrier_summary_csv: Path
    context_summary_csv: Path
    feature_leaderboard_csv: Path


DEFAULT_HORIZONS_BARS = (1, 3, 6, 12, 24)

NUMERIC_CONTEXT_FEATURES = [
    "atr",
    "vwap_z",
    "gap_atr",
    "gap_prior_range_pct",
    "open_location_prior_range",
    "overnight_inventory_atr",
    "overnight_range_atr",
    "prior_rth_range_atr",
    "rth_range_so_far_atr",
    "ib_range_atr",
    "vsa_score",
    "vsa_rel_range",
    "vsa_rel_volume",
    "hawkes_norm_range",
    "hawkes_vol",
    "cusum_event_move_atr",
    "mp_dist_to_support",
    "mp_dist_to_resistance",
    "mp_crossed_up_prominence",
    "mp_crossed_down_prominence",
    "vp_width",
    "profile_range_multiple",
]

CATEGORICAL_CONTEXT_FEATURES = [
    "hour",
    "session_bucket",
    "weekday",
    "day_regime",
    "open_context",
    "vwap_side",
    "profile_value_location",
    "prior_range_location",
    "overnight_inventory_direction",
    "gap_inventory_alignment",
    "above_ib_high",
    "below_ib_low",
    "inside_ib",
    "vsa_absorption",
    "vsa_thin_move",
    "hawkes_vol_above_high",
    "hawkes_vol_below_low",
    "hawkes_momentum_signal",
]


def _as_bool(data: pd.DataFrame, col: str) -> pd.Series:
    if col not in data.columns:
        return pd.Series(False, index=data.index)
    return data[col].fillna(False).astype(bool)


def _num(data: pd.DataFrame, col: str) -> pd.Series:
    if col not in data.columns:
        return pd.Series(np.nan, index=data.index)
    return pd.to_numeric(data[col], errors="coerce")


def _cross_above(close: pd.Series, level: pd.Series) -> pd.Series:
    return close.gt(level) & close.shift(1).le(level) & level.notna()


def _cross_below(close: pd.Series, level: pd.Series) -> pd.Series:
    return close.lt(level) & close.shift(1).ge(level) & level.notna()


def _signed_candle_direction(data: pd.DataFrame) -> pd.Series:
    direction = np.sign(_num(data, "close") - _num(data, "open"))
    direction = direction.replace(0, np.nan).ffill().fillna(0)
    return direction.astype(int)


def _append_event(
    pieces: list[pd.DataFrame],
    data: pd.DataFrame,
    mask: pd.Series,
    *,
    event_type: str,
    event_family: str,
    direction,
    level_col: str | None = None,
    strength_col: str | None = None,
) -> None:
    mask = mask.fillna(False).astype(bool)
    if not mask.any():
        return

    idx = np.flatnonzero(mask.to_numpy())
    if isinstance(direction, pd.Series):
        direction_arr = pd.to_numeric(direction.iloc[idx], errors="coerce").fillna(0).astype(int).to_numpy()
    else:
        direction_arr = np.full(len(idx), int(direction), dtype=int)

    event_level = np.full(len(idx), np.nan, dtype=float)
    if level_col is not None and level_col in data.columns:
        event_level = pd.to_numeric(data[level_col].iloc[idx], errors="coerce").to_numpy(dtype=float)

    event_strength = np.full(len(idx), np.nan, dtype=float)
    if strength_col is not None and strength_col in data.columns:
        event_strength = pd.to_numeric(data[strength_col].iloc[idx], errors="coerce").to_numpy(dtype=float)

    close = _num(data, "close").iloc[idx].to_numpy(dtype=float)
    time = data["time"].iloc[idx].to_numpy() if "time" in data.columns else idx

    piece = pd.DataFrame(
        {
            "row_idx": idx,
            "time": time,
            "event_type": event_type,
            "event_family": event_family,
            "event_direction": direction_arr,
            "event_level": event_level,
            "event_strength": event_strength,
            "event_close": close,
        }
    )
    piece = piece.loc[piece["event_direction"].ne(0)].copy()
    if not piece.empty:
        piece["event_direction_label"] = np.where(piece["event_direction"].gt(0), "long", "short")
        pieces.append(piece)


def _add_research_context_columns(data: pd.DataFrame) -> pd.DataFrame:
    df = data.copy()
    time = pd.to_datetime(df["time"], errors="coerce") if "time" in df.columns else pd.Series(pd.NaT, index=df.index)
    df["hour"] = time.dt.hour
    df["weekday"] = time.dt.day_name()

    hour = df["hour"]
    df["session_bucket"] = "overnight"
    df.loc[hour.between(8, 9, inclusive="left"), "session_bucket"] = "premarket"
    df.loc[hour.eq(9), "session_bucket"] = "rth_open"
    df.loc[hour.between(10, 11, inclusive="both"), "session_bucket"] = "mid_morning"
    df.loc[hour.between(12, 13, inclusive="both"), "session_bucket"] = "lunch"
    df.loc[hour.between(14, 15, inclusive="both"), "session_bucket"] = "afternoon"
    df.loc[hour.ge(16), "session_bucket"] = "post_rth"

    close = _num(df, "close")
    if "vwap" in df.columns:
        df["vwap_side"] = np.where(close.ge(_num(df, "vwap")), "above_vwap", "below_vwap")
    else:
        df["vwap_side"] = "unknown"

    if {"vp_val", "vp_vah"}.issubset(df.columns):
        val = _num(df, "vp_val")
        vah = _num(df, "vp_vah")
        df["profile_value_location"] = "inside_value"
        df.loc[close.lt(val), "profile_value_location"] = "below_value"
        df.loc[close.gt(vah), "profile_value_location"] = "above_value"
        df.loc[val.isna() | vah.isna(), "profile_value_location"] = "unknown"
    else:
        df["profile_value_location"] = "unknown"

    if {"prior_rth_low", "prior_rth_high"}.issubset(df.columns):
        prior_low = _num(df, "prior_rth_low")
        prior_high = _num(df, "prior_rth_high")
        df["prior_range_location"] = "inside_prior_range"
        df.loc[close.lt(prior_low), "prior_range_location"] = "below_prior_low"
        df.loc[close.gt(prior_high), "prior_range_location"] = "above_prior_high"
        df.loc[prior_low.isna() | prior_high.isna(), "prior_range_location"] = "unknown"
    else:
        df["prior_range_location"] = "unknown"

    return df


def define_research_events(data: pd.DataFrame) -> pd.DataFrame:
    """
    Build the experiment universe from event-defining features.

    Multiple events can occur on the same timestamp; each remains a separate
    hypothesis row so we can later ask which event type actually has edge.
    """
    df = _add_research_context_columns(data)
    close = _num(df, "close")
    high = _num(df, "high")
    low = _num(df, "low")
    signed_candle = _signed_candle_direction(df)
    pieces: list[pd.DataFrame] = []

    _append_event(
        pieces,
        df,
        _as_bool(df, "cusum_event_up"),
        event_type="cusum_up",
        event_family="movement",
        direction=1,
        strength_col="cusum_event_move_atr",
    )
    _append_event(
        pieces,
        df,
        _as_bool(df, "cusum_event_down"),
        event_type="cusum_down",
        event_family="movement",
        direction=-1,
        strength_col="cusum_event_move_atr",
    )

    if "vwap" in df.columns:
        _append_event(pieces, df, _cross_above(close, _num(df, "vwap")), event_type="vwap_cross_up", event_family="vwap", direction=1, level_col="vwap", strength_col="vwap_z")
        _append_event(pieces, df, _cross_below(close, _num(df, "vwap")), event_type="vwap_cross_down", event_family="vwap", direction=-1, level_col="vwap", strength_col="vwap_z")

    for level_col in ("vp_poc", "vp_val", "vp_vah"):
        if level_col not in df.columns:
            continue
        level_name = level_col.replace("vp_", "profile_")
        _append_event(pieces, df, _cross_above(close, _num(df, level_col)), event_type=f"{level_name}_cross_up", event_family="opening_profile", direction=1, level_col=level_col)
        _append_event(pieces, df, _cross_below(close, _num(df, level_col)), event_type=f"{level_name}_cross_down", event_family="opening_profile", direction=-1, level_col=level_col)

    if {"vp_vah", "vp_val"}.issubset(df.columns):
        _append_event(
            pieces,
            df,
            high.ge(_num(df, "vp_vah")) & close.lt(_num(df, "vp_vah")),
            event_type="profile_vah_reject_down",
            event_family="opening_profile",
            direction=-1,
            level_col="vp_vah",
        )
        _append_event(
            pieces,
            df,
            low.le(_num(df, "vp_val")) & close.gt(_num(df, "vp_val")),
            event_type="profile_val_reject_up",
            event_family="opening_profile",
            direction=1,
            level_col="vp_val",
        )

    if {"prior_rth_high", "prior_rth_low"}.issubset(df.columns):
        _append_event(
            pieces,
            df,
            high.gt(_num(df, "prior_rth_high")) & close.lt(_num(df, "prior_rth_high")),
            event_type="prior_high_sweep_reject_down",
            event_family="prior_session",
            direction=-1,
            level_col="prior_rth_high",
        )
        _append_event(
            pieces,
            df,
            low.lt(_num(df, "prior_rth_low")) & close.gt(_num(df, "prior_rth_low")),
            event_type="prior_low_sweep_reject_up",
            event_family="prior_session",
            direction=1,
            level_col="prior_rth_low",
        )
        _append_event(
            pieces,
            df,
            _cross_above(close, _num(df, "prior_rth_high")),
            event_type="prior_high_breakout_up",
            event_family="prior_session",
            direction=1,
            level_col="prior_rth_high",
        )
        _append_event(
            pieces,
            df,
            _cross_below(close, _num(df, "prior_rth_low")),
            event_type="prior_low_breakdown_down",
            event_family="prior_session",
            direction=-1,
            level_col="prior_rth_low",
        )

    if {"ib_high", "ib_low"}.issubset(df.columns):
        _append_event(pieces, df, _cross_above(close, _num(df, "ib_high")), event_type="ib_high_breakout_up", event_family="initial_balance", direction=1, level_col="ib_high")
        _append_event(pieces, df, _cross_below(close, _num(df, "ib_low")), event_type="ib_low_breakdown_down", event_family="initial_balance", direction=-1, level_col="ib_low")

    _append_event(
        pieces,
        df,
        _as_bool(df, "mp_crossed_up"),
        event_type="rolling_profile_cross_up",
        event_family="rolling_profile",
        direction=1,
        level_col="mp_crossed_up_level",
        strength_col="mp_crossed_up_prominence",
    )
    _append_event(
        pieces,
        df,
        _as_bool(df, "mp_crossed_down"),
        event_type="rolling_profile_cross_down",
        event_family="rolling_profile",
        direction=-1,
        level_col="mp_crossed_down_level",
        strength_col="mp_crossed_down_prominence",
    )

    if "vsa_absorption" in df.columns:
        prior_move = close - close.shift(3)
        _append_event(
            pieces,
            df,
            _as_bool(df, "vsa_absorption") & prior_move.gt(_num(df, "atr") * 0.25),
            event_type="vsa_absorption_after_up",
            event_family="volume_spread",
            direction=-1,
            strength_col="vsa_score",
        )
        _append_event(
            pieces,
            df,
            _as_bool(df, "vsa_absorption") & prior_move.lt(_num(df, "atr") * -0.25),
            event_type="vsa_absorption_after_down",
            event_family="volume_spread",
            direction=1,
            strength_col="vsa_score",
        )

    if "vsa_thin_move" in df.columns:
        _append_event(
            pieces,
            df,
            _as_bool(df, "vsa_thin_move") & signed_candle.gt(0),
            event_type="vsa_thin_move_up",
            event_family="volume_spread",
            direction=1,
            strength_col="vsa_score",
        )
        _append_event(
            pieces,
            df,
            _as_bool(df, "vsa_thin_move") & signed_candle.lt(0),
            event_type="vsa_thin_move_down",
            event_family="volume_spread",
            direction=-1,
            strength_col="vsa_score",
        )

    if {"hawkes_vol_cross_above_high", "hawkes_momentum_signal"}.issubset(df.columns):
        hawkes_direction = _num(df, "hawkes_momentum_signal").fillna(0).astype(int)
        _append_event(
            pieces,
            df,
            _as_bool(df, "hawkes_vol_cross_above_high") & hawkes_direction.eq(1),
            event_type="hawkes_vol_expansion_up",
            event_family="volatility",
            direction=1,
            strength_col="hawkes_vol",
        )
        _append_event(
            pieces,
            df,
            _as_bool(df, "hawkes_vol_cross_above_high") & hawkes_direction.eq(-1),
            event_type="hawkes_vol_expansion_down",
            event_family="volatility",
            direction=-1,
            strength_col="hawkes_vol",
        )

    if not pieces:
        return pd.DataFrame(columns=["row_idx", "time", "event_type", "event_family", "event_direction"])

    events = pd.concat(pieces, ignore_index=True, sort=False)
    events = events.sort_values(["row_idx", "event_type"]).reset_index(drop=True)

    context_cols = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        *NUMERIC_CONTEXT_FEATURES,
        *CATEGORICAL_CONTEXT_FEATURES,
    ]
    present_context = [col for col in context_cols if col in df.columns and col not in events.columns]
    if present_context:
        context = df.iloc[events["row_idx"].to_numpy()][present_context].reset_index(drop=True)
        events = pd.concat([events.reset_index(drop=True), context], axis=1)

    return events


def add_forward_outcomes(events: pd.DataFrame, data: pd.DataFrame, horizons_bars: tuple[int, ...]) -> pd.DataFrame:
    if events.empty:
        return events.copy()

    out = events.copy()
    horizons = tuple(sorted({int(h) for h in horizons_bars if int(h) > 0}))
    close = _num(data, "close").to_numpy(dtype=float)
    atr = _num(data, "atr").to_numpy(dtype=float)
    idx = pd.to_numeric(out["row_idx"], errors="coerce").to_numpy(dtype=int)
    direction = pd.to_numeric(out["event_direction"], errors="coerce").fillna(0).to_numpy(dtype=float)
    entry = close[idx]

    for horizon in horizons:
        future_idx = idx + horizon
        valid = future_idx < len(close)
        fwd = np.full(len(out), np.nan, dtype=float)
        fwd[valid] = close[future_idx[valid]] - entry[valid]
        fwd_atr = fwd / np.where(np.isfinite(atr[idx]) & (atr[idx] != 0), atr[idx], np.nan)
        directional = fwd * direction
        out[f"fwd_points_{horizon}b"] = fwd
        out[f"fwd_atr_{horizon}b"] = fwd_atr
        out[f"directional_fwd_points_{horizon}b"] = directional
        out[f"directional_hit_{horizon}b"] = directional > 0

    return out


def add_double_barrier_outcomes(
    events: pd.DataFrame,
    data: pd.DataFrame,
    *,
    target_atr_multiple: float = 1.0,
    stop_atr_multiple: float = 1.0,
    max_hold_bars: int = 24,
    tie_breaker: str = "stop",
) -> pd.DataFrame:
    if events.empty:
        return events.copy()

    out = events.copy()
    close = _num(data, "close").to_numpy(dtype=float)
    high = _num(data, "high").to_numpy(dtype=float)
    low = _num(data, "low").to_numpy(dtype=float)
    atr = _num(data, "atr").to_numpy(dtype=float)
    idx = pd.to_numeric(out["row_idx"], errors="coerce").to_numpy(dtype=int)
    direction = pd.to_numeric(out["event_direction"], errors="coerce").fillna(0).to_numpy(dtype=int)
    max_hold_bars = max(1, int(max_hold_bars))
    target_atr_multiple = max(1e-9, float(target_atr_multiple))
    stop_atr_multiple = max(1e-9, float(stop_atr_multiple))
    tie_breaker = str(tie_breaker).lower()

    outcomes: list[str] = []
    bars_to_outcome = np.full(len(out), np.nan, dtype=float)
    barrier_points = np.full(len(out), np.nan, dtype=float)
    barrier_r = np.full(len(out), np.nan, dtype=float)
    mfe_points = np.full(len(out), np.nan, dtype=float)
    mae_points = np.full(len(out), np.nan, dtype=float)
    target_points = np.full(len(out), np.nan, dtype=float)
    stop_points = np.full(len(out), np.nan, dtype=float)

    for row_pos, event_idx in enumerate(idx):
        event_direction = int(direction[row_pos])
        if event_idx < 0 or event_idx >= len(close) - 1 or event_direction == 0:
            outcomes.append("invalid")
            continue
        entry = close[event_idx]
        event_atr = atr[event_idx]
        if not np.isfinite(entry) or not np.isfinite(event_atr) or event_atr <= 0:
            outcomes.append("invalid")
            continue

        target_dist = event_atr * target_atr_multiple
        stop_dist = event_atr * stop_atr_multiple
        target_points[row_pos] = target_dist
        stop_points[row_pos] = stop_dist

        end_idx = min(len(close) - 1, event_idx + max_hold_bars)
        if end_idx <= event_idx:
            outcomes.append("end_of_data")
            continue

        future_slice = slice(event_idx + 1, end_idx + 1)
        if event_direction > 0:
            favorable = high[future_slice] - entry
            adverse = entry - low[future_slice]
        else:
            favorable = entry - low[future_slice]
            adverse = high[future_slice] - entry
        mfe_points[row_pos] = float(np.nanmax(favorable)) if len(favorable) else np.nan
        mae_points[row_pos] = float(np.nanmax(adverse)) if len(adverse) else np.nan

        outcome = "timeout"
        exit_points = event_direction * (close[end_idx] - entry)
        outcome_bars = end_idx - event_idx

        for future_idx in range(event_idx + 1, end_idx + 1):
            if event_direction > 0:
                target_hit = high[future_idx] >= entry + target_dist
                stop_hit = low[future_idx] <= entry - stop_dist
            else:
                target_hit = low[future_idx] <= entry - target_dist
                stop_hit = high[future_idx] >= entry + stop_dist

            if target_hit and stop_hit:
                if tie_breaker == "target":
                    outcome = "target_first"
                    exit_points = target_dist
                else:
                    outcome = "stop_first"
                    exit_points = -stop_dist
                outcome_bars = future_idx - event_idx
                break
            if target_hit:
                outcome = "target_first"
                exit_points = target_dist
                outcome_bars = future_idx - event_idx
                break
            if stop_hit:
                outcome = "stop_first"
                exit_points = -stop_dist
                outcome_bars = future_idx - event_idx
                break

        outcomes.append(outcome)
        bars_to_outcome[row_pos] = float(outcome_bars)
        barrier_points[row_pos] = float(exit_points)
        barrier_r[row_pos] = float(exit_points / stop_dist) if stop_dist > 0 else np.nan

    out["barrier_outcome"] = outcomes
    out["barrier_bars_to_outcome"] = bars_to_outcome
    out["barrier_points"] = barrier_points
    out["barrier_r"] = barrier_r
    out["barrier_mfe_points"] = mfe_points
    out["barrier_mae_points"] = mae_points
    out["barrier_target_points"] = target_points
    out["barrier_stop_points"] = stop_points
    return out


def _bootstrap_ci(values: pd.Series, n_samples: int, seed: int) -> tuple[float, float]:
    arr = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    if len(arr) < 2:
        value = float(arr[0]) if len(arr) else np.nan
        return value, value
    rng = np.random.default_rng(int(seed))
    n_samples = max(1, int(n_samples))
    sample_means = np.empty(n_samples, dtype=float)
    for idx in range(n_samples):
        sample_means[idx] = float(np.mean(rng.choice(arr, size=len(arr), replace=True)))
    return float(np.percentile(sample_means, 5)), float(np.percentile(sample_means, 95))


def _metric_summary(
    group: pd.DataFrame,
    metric_col: str,
    *,
    bootstrap_samples: int,
    seed: int,
) -> dict:
    metric = pd.to_numeric(group[metric_col], errors="coerce")
    valid = metric.dropna()
    ci_low, ci_high = _bootstrap_ci(valid, bootstrap_samples, seed)
    std = float(valid.std(ddof=1)) if len(valid) > 1 else np.nan
    mean = float(valid.mean()) if len(valid) else np.nan
    t_stat = mean / (std / np.sqrt(len(valid))) if len(valid) > 1 and std > 0 else np.nan
    return {
        "events": int(len(valid)),
        "mean": mean,
        "median": float(valid.median()) if len(valid) else np.nan,
        "p25": float(valid.quantile(0.25)) if len(valid) else np.nan,
        "p75": float(valid.quantile(0.75)) if len(valid) else np.nan,
        "hit_rate": float((valid > 0).mean()) if len(valid) else np.nan,
        "bootstrap_mean_p05": ci_low,
        "bootstrap_mean_p95": ci_high,
        "t_stat": float(t_stat) if np.isfinite(t_stat) else np.nan,
    }


def summarize_events(
    events: pd.DataFrame,
    *,
    horizons_bars: tuple[int, ...],
    bootstrap_samples: int,
    min_events: int,
    seed: int,
) -> pd.DataFrame:
    rows: list[dict] = []
    if events.empty:
        return pd.DataFrame()

    grouping_sets = [
        ("event_type", ["event_type"]),
        ("event_family", ["event_family"]),
        ("event_family_direction", ["event_family", "event_direction_label"]),
    ]
    for group_name, group_cols in grouping_sets:
        for keys, group in events.groupby(group_cols, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            if len(group) < min_events:
                continue
            base = {"grouping": group_name}
            for col, value in zip(group_cols, keys):
                base[col] = value
            for horizon in horizons_bars:
                metric_col = f"directional_fwd_points_{horizon}b"
                if metric_col not in group.columns:
                    continue
                stats = _metric_summary(group, metric_col, bootstrap_samples=bootstrap_samples, seed=seed + int(horizon))
                if stats["events"] < min_events:
                    continue
                rows.append({**base, "horizon_bars": int(horizon), "metric": metric_col, **stats})

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["horizon_bars", "mean"], ascending=[True, False])
    return out


def summarize_barriers(events: pd.DataFrame, *, min_events: int) -> pd.DataFrame:
    rows: list[dict] = []
    if events.empty or "barrier_outcome" not in events.columns:
        return pd.DataFrame()

    for keys, group in events.groupby(["event_type", "event_family", "event_direction_label"], dropna=False):
        if len(group) < min_events:
            continue
        outcome = group["barrier_outcome"].astype(str)
        valid = outcome.isin(["target_first", "stop_first", "timeout"])
        valid_group = group.loc[valid]
        if len(valid_group) < min_events:
            continue
        rows.append({
            "event_type": keys[0],
            "event_family": keys[1],
            "event_direction_label": keys[2],
            "events": int(len(valid_group)),
            "target_rate": float((valid_group["barrier_outcome"] == "target_first").mean()),
            "stop_rate": float((valid_group["barrier_outcome"] == "stop_first").mean()),
            "timeout_rate": float((valid_group["barrier_outcome"] == "timeout").mean()),
            "mean_barrier_r": float(pd.to_numeric(valid_group["barrier_r"], errors="coerce").mean()),
            "median_barrier_r": float(pd.to_numeric(valid_group["barrier_r"], errors="coerce").median()),
            "mean_barrier_points": float(pd.to_numeric(valid_group["barrier_points"], errors="coerce").mean()),
            "mean_bars_to_outcome": float(pd.to_numeric(valid_group["barrier_bars_to_outcome"], errors="coerce").mean()),
            "mean_mfe_points": float(pd.to_numeric(valid_group["barrier_mfe_points"], errors="coerce").mean()),
            "mean_mae_points": float(pd.to_numeric(valid_group["barrier_mae_points"], errors="coerce").mean()),
        })

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values(["mean_barrier_r", "target_rate"], ascending=[False, False])
    return out


def _bucket_numeric(series: pd.Series, bins: int = 4) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    non_null = values.dropna()
    if non_null.nunique() < 3:
        return values.round(4).astype(str).where(values.notna(), "missing")
    bucket_count = min(int(bins), int(non_null.nunique()))
    try:
        bucketed = pd.qcut(values, q=bucket_count, duplicates="drop")
        return bucketed.astype(str).where(values.notna(), "missing")
    except ValueError:
        return values.round(4).astype(str).where(values.notna(), "missing")


def summarize_contexts(
    events: pd.DataFrame,
    *,
    horizons_bars: tuple[int, ...],
    bootstrap_samples: int,
    min_events: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    context_rows: list[dict] = []
    leaderboard_rows: list[dict] = []
    if events.empty:
        return pd.DataFrame(), pd.DataFrame()

    context_features = [
        col for col in CATEGORICAL_CONTEXT_FEATURES + NUMERIC_CONTEXT_FEATURES if col in events.columns
    ]
    for event_type, event_group in events.groupby("event_type", dropna=False):
        if len(event_group) < min_events:
            continue
        for feature in context_features:
            if feature in NUMERIC_CONTEXT_FEATURES:
                bucket_series = _bucket_numeric(event_group[feature])
            else:
                bucket_series = event_group[feature].astype(str).fillna("missing")
            work = event_group.copy()
            work["_feature_bucket"] = bucket_series.to_numpy()
            for horizon in horizons_bars:
                metric_col = f"directional_fwd_points_{horizon}b"
                if metric_col not in work.columns:
                    continue
                bucket_means: list[tuple[str, int, float]] = []
                for bucket, bucket_group in work.groupby("_feature_bucket", dropna=False):
                    stats = _metric_summary(
                        bucket_group,
                        metric_col,
                        bootstrap_samples=bootstrap_samples,
                        seed=seed + int(horizon),
                    )
                    if stats["events"] < min_events:
                        continue
                    context_rows.append({
                        "event_type": event_type,
                        "context_feature": feature,
                        "context_bucket": bucket,
                        "horizon_bars": int(horizon),
                        "metric": metric_col,
                        **stats,
                    })
                    bucket_means.append((str(bucket), int(stats["events"]), float(stats["mean"])))

                if len(bucket_means) < 2:
                    continue
                bucket_means = [item for item in bucket_means if np.isfinite(item[2])]
                if len(bucket_means) < 2:
                    continue
                best = max(bucket_means, key=lambda item: item[2])
                worst = min(bucket_means, key=lambda item: item[2])
                leaderboard_rows.append({
                    "event_type": event_type,
                    "context_feature": feature,
                    "horizon_bars": int(horizon),
                    "bucket_count": int(len(bucket_means)),
                    "best_bucket": best[0],
                    "best_bucket_events": best[1],
                    "best_bucket_mean": best[2],
                    "worst_bucket": worst[0],
                    "worst_bucket_events": worst[1],
                    "worst_bucket_mean": worst[2],
                    "mean_spread": float(best[2] - worst[2]),
                    "abs_mean_spread": float(abs(best[2] - worst[2])),
                })

    context_summary = pd.DataFrame(context_rows)
    leaderboard = pd.DataFrame(leaderboard_rows)
    if not context_summary.empty:
        context_summary = context_summary.sort_values(["horizon_bars", "mean"], ascending=[True, False])
    if not leaderboard.empty:
        leaderboard = leaderboard.sort_values(["abs_mean_spread", "bucket_count"], ascending=[False, False])
    return context_summary, leaderboard


def run_feature_research_lab(
    data: pd.DataFrame,
    *,
    out_dir: Path | str,
    artifact_name: str = "feature_research",
    horizons_bars: tuple[int, ...] = DEFAULT_HORIZONS_BARS,
    target_atr_multiple: float = 1.0,
    stop_atr_multiple: float = 1.0,
    max_hold_bars: int = 24,
    bootstrap_samples: int = 300,
    min_events: int = 30,
    random_seed: int = 7,
) -> FeatureResearchLabPaths:
    """
    Export a feature-first research lab.

    This is the "quant process" layer: define events, attach context, label
    outcomes, and summarize where the conditional edge appears to be.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    horizons = tuple(sorted({int(h) for h in horizons_bars if int(h) > 0}))

    events = define_research_events(data)
    events = add_forward_outcomes(events, data, horizons)
    events = add_double_barrier_outcomes(
        events,
        data,
        target_atr_multiple=target_atr_multiple,
        stop_atr_multiple=stop_atr_multiple,
        max_hold_bars=max_hold_bars,
        tie_breaker="stop",
    )

    event_summary = summarize_events(
        events,
        horizons_bars=horizons,
        bootstrap_samples=bootstrap_samples,
        min_events=min_events,
        seed=random_seed,
    )
    barrier_summary = summarize_barriers(events, min_events=min_events)
    context_summary, leaderboard = summarize_contexts(
        events,
        horizons_bars=horizons,
        bootstrap_samples=max(25, min(bootstrap_samples, 150)),
        min_events=min_events,
        seed=random_seed,
    )

    events_csv = out_dir / f"{artifact_name}_events.csv"
    event_summary_csv = out_dir / f"{artifact_name}_event_summary.csv"
    barrier_summary_csv = out_dir / f"{artifact_name}_barrier_summary.csv"
    context_summary_csv = out_dir / f"{artifact_name}_context_summary.csv"
    feature_leaderboard_csv = out_dir / f"{artifact_name}_feature_leaderboard.csv"

    events.to_csv(events_csv, index=False)
    event_summary.to_csv(event_summary_csv, index=False)
    barrier_summary.to_csv(barrier_summary_csv, index=False)
    context_summary.to_csv(context_summary_csv, index=False)
    leaderboard.to_csv(feature_leaderboard_csv, index=False)

    return FeatureResearchLabPaths(
        events_csv=events_csv,
        event_summary_csv=event_summary_csv,
        barrier_summary_csv=barrier_summary_csv,
        context_summary_csv=context_summary_csv,
        feature_leaderboard_csv=feature_leaderboard_csv,
    )
