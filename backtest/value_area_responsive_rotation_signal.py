"""
Prior Session Value Area Responsive Rotation Signal (H5).

Pre-registered in docs/research_hypotheses/2026-10-29_value_area_responsive_rotation_h5.md.

Thesis:
On days where 09:30-09:44 Opening Range closes INSIDE prior session Value Area
(Strategy 1 outputs NO TRADE), the market is proven to be in balance.
Between 10:00 and 11:30 ET, probes toward prior VAH or VAL face responsive absorption
and mean-revert toward prior POC.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.poc_rejection_signal import _compute_prior_session_profiles
from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_VA_RESPONSIVE_ROTATION_FEATURE_COLUMNS = (
    "rotation_score",
    "dist_to_poc_points",
    "level_sweep_points",
    "rejection_wick_ratio",
    "or15_close",
    "prior_rth_poc",
    "prior_rth_vah",
    "prior_rth_val",
)

DEFAULT_VA_RESPONSIVE_ROTATION_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "level_tested",
    "rotation_target",
    "or15_regime",
)


@dataclass(frozen=True)
class ValueAreaResponsiveRotationConfig:
    rth_start: str = "09:30"
    or15_end: str = "09:44"
    signal_window_start: str = "10:00"
    signal_window_end: str = "11:30"
    rth_end: str = "16:00"
    touch_tolerance_points: float = 5.0
    max_overshoot_points: float = 25.0
    max_short_close_location: float = 0.45
    min_long_close_location: float = 0.55
    min_stop_points: float = 15.0
    max_stop_points: float = 45.0
    stop_buffer_points: float = 8.0
    min_target_points: float = 10.0
    profile_bin_size: float = 1.0
    value_area_pct: float = 0.70
    allow_long: bool = True
    allow_short: bool = True


def build_value_area_responsive_rotation_signal_export(
    data: pd.DataFrame,
    *,
    config: ValueAreaResponsiveRotationConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_VA_RESPONSIVE_ROTATION_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_VA_RESPONSIVE_ROTATION_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_value_area_responsive_rotation_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_value_area_responsive_rotation_signal_frame(
    data: pd.DataFrame,
    *,
    config: ValueAreaResponsiveRotationConfig | None = None,
) -> pd.DataFrame:
    cfg = config or ValueAreaResponsiveRotationConfig()
    df = _base_ohlcv_frame(data)

    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    rth_start_min = _parse_hhmm(cfg.rth_start)
    or15_end_min = _parse_hhmm(cfg.or15_end)
    sig_start_min = _parse_hhmm(cfg.signal_window_start)
    sig_end_min = _parse_hhmm(cfg.signal_window_end)
    rth_end_min = _parse_hhmm(cfg.rth_end)

    rth_mask = minutes.ge(rth_start_min) & minutes.le(rth_end_min)
    rth = df.loc[rth_mask].copy()
    session = df["time"].dt.date

    # 1. Prior completed RTH session Volume Profile
    prior_profiles = _compute_prior_session_profiles(
        rth,
        bin_size=float(cfg.profile_bin_size),
        value_area_pct=float(cfg.value_area_pct),
    )
    prof_by_session = prior_profiles.set_index("session")
    prior_poc = session.map(prof_by_session["prior_poc"])
    prior_vah = session.map(prof_by_session["prior_vah"])
    prior_val = session.map(prof_by_session["prior_val"])

    # 2. 09:30..09:44 Opening Range stats per session
    or15_mask = minutes.ge(rth_start_min) & minutes.le(or15_end_min)
    or15_bars = df.loc[or15_mask]
    or15_stats = (
        or15_bars.groupby(or15_bars["time"].dt.date, sort=True)
        .agg(
            or15_open=("open", "first"),
            or15_high=("high", "max"),
            or15_low=("low", "min"),
            or15_close=("close", "last"),
        )
    )
    or15_close = session.map(or15_stats["or15_close"])

    # Regime Gate: Must close INSIDE prior Value Area
    # (Strategy 1 outputs NO TRADE on these days!)
    is_in_balance = (or15_close >= prior_val) & (or15_close <= prior_vah)

    n = len(df)
    candidate_signal = np.zeros(n, dtype=float)
    rotation_score = np.zeros(n, dtype=float)
    dist_to_poc_pts = np.zeros(n, dtype=float)
    level_sweep_pts = np.zeros(n, dtype=float)
    rejection_wick_ratio = np.zeros(n, dtype=float)
    stop_pts = np.zeros(n, dtype=float)
    target_pts = np.zeros(n, dtype=float)
    level_tested = np.array([""] * n, dtype=object)

    open_arr = df["open"].to_numpy(dtype=float)
    high_arr = df["high"].to_numpy(dtype=float)
    low_arr = df["low"].to_numpy(dtype=float)
    close_arr = df["close"].to_numpy(dtype=float)
    min_arr = minutes.to_numpy(dtype=int)
    in_balance_arr = is_in_balance.to_numpy(dtype=bool)

    poc_arr = prior_poc.to_numpy(dtype=float)
    vah_arr = prior_vah.to_numpy(dtype=float)
    val_arr = prior_val.to_numpy(dtype=float)

    session_ids = session.to_numpy()
    unique_sessions = np.unique(session_ids)

    tol = float(cfg.touch_tolerance_points)
    overshoot = float(cfg.max_overshoot_points)
    max_short_loc = float(cfg.max_short_close_location)
    min_long_loc = float(cfg.min_long_close_location)
    stop_buffer = float(cfg.stop_buffer_points)
    min_stop = float(cfg.min_stop_points)
    max_stop = float(cfg.max_stop_points)
    min_target = float(cfg.min_target_points)

    for sess in unique_sessions:
        sess_mask = (session_ids == sess)
        indices = np.where(sess_mask)[0]
        if len(indices) < 2:
            continue

        first_idx = indices[0]
        if not in_balance_arr[first_idx]:
            # Day was not in-balance (Strategy 1 breakout day) -> skip
            continue

        p_poc = poc_arr[first_idx]
        p_vah = vah_arr[first_idx]
        p_val = val_arr[first_idx]

        if np.isnan(p_poc) or np.isnan(p_vah) or np.isnan(p_val):
            continue

        trade_fired = False

        for i in indices:
            m = min_arr[i]
            if m < sig_start_min or m > sig_end_min:
                continue

            h = high_arr[i]
            l = low_arr[i]
            c = close_arr[i]
            rng = h - l
            if rng <= 0.0:
                continue

            close_loc = (c - l) / rng

            # 1. Short Setup: Test VAH perimeter & reject back down
            if cfg.allow_short and not trade_fired:
                vah_probed = (h >= p_vah - tol) and (h <= p_vah + overshoot)
                vah_rejected = (c < p_vah) and (close_loc <= max_short_loc)

                if vah_probed and vah_rejected:
                    # Signal fires on confirmation bar close (i)
                    candidate_signal[i] = -1.0
                    sweep = max(0.0, h - p_vah)
                    dist_poc = max(min_target, c - p_poc)
                    risk = min(max_stop, max(min_stop, (h - c) + stop_buffer))

                    rotation_score[i] = -1.0 * (sweep + dist_poc)
                    dist_to_poc_pts[i] = dist_poc
                    level_sweep_pts[i] = sweep
                    rejection_wick_ratio[i] = 1.0 - close_loc
                    stop_pts[i] = risk
                    target_pts[i] = max(min_target, dist_poc)
                    level_tested[i] = "vah"
                    trade_fired = True
                    break

            # 2. Long Setup: Test VAL perimeter & reject back up
            if cfg.allow_long and not trade_fired:
                val_probed = (l <= p_val + tol) and (l >= p_val - overshoot)
                val_rejected = (c > p_val) and (close_loc >= min_long_loc)

                if val_probed and val_rejected:
                    # Signal fires on confirmation bar close (i)
                    candidate_signal[i] = 1.0
                    sweep = max(0.0, p_val - l)
                    dist_poc = max(min_target, p_poc - c)
                    risk = min(max_stop, max(min_stop, (c - l) + stop_buffer))

                    rotation_score[i] = 1.0 * (sweep + dist_poc)
                    dist_to_poc_pts[i] = dist_poc
                    level_sweep_pts[i] = sweep
                    rejection_wick_ratio[i] = close_loc
                    stop_pts[i] = risk
                    target_pts[i] = max(min_target, dist_poc)
                    level_tested[i] = "val"
                    trade_fired = True
                    break

    direction = pd.Series("flat", index=df.index, dtype="object")
    direction.loc[candidate_signal > 0.0] = "long"
    direction.loc[candidate_signal < 0.0] = "short"

    out = df.copy()
    out["signal"] = candidate_signal
    out["signal_type"] = np.where(candidate_signal != 0.0, "va_responsive_rotation", "")
    out["candidate_signal"] = candidate_signal
    out["direction"] = direction
    out["rotation_score"] = rotation_score
    out["dist_to_poc_points"] = dist_to_poc_pts
    out["level_sweep_points"] = level_sweep_pts
    out["rejection_wick_ratio"] = rejection_wick_ratio
    out["or15_close"] = or15_close
    out["prior_rth_poc"] = prior_poc
    out["prior_rth_vah"] = prior_vah
    out["prior_rth_val"] = prior_val
    out["stop_points"] = stop_pts
    out["target_points"] = target_pts
    out["level_tested"] = level_tested
    out["rotation_target"] = np.where(candidate_signal != 0.0, "prior_poc", "")
    out["or15_regime"] = np.where(is_in_balance, "inside_va", "outside_va")
    out["session_bucket"] = "mid_morning"
    out["setup_tag"] = np.where(
        candidate_signal > 0.0,
        "val_responsive_long",
        np.where(candidate_signal < 0.0, "vah_responsive_short", ""),
    )
    return out


def _base_ohlcv_frame(data: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "time"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"input data missing required columns: {sorted(missing)}")
    df = data.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    if "volume" not in df.columns:
        df["volume"] = 1.0
    return df


def _parse_hhmm(value: str) -> int:
    parts = str(value).split(":")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM time string, got {value!r}")
    return int(parts[0]) * 60 + int(parts[1])
