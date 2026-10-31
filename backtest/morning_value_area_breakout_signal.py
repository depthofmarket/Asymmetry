from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.poc_rejection_signal import _compute_prior_session_profiles
from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_MORNING_VA_BREAKOUT_FEATURE_COLUMNS = (
    "va_breakout_score",
    "first15_return_pct",
    "first15_return_points",
    "or15_range_points",
    "or15_close_location",
    "prior_rth_poc",
    "prior_rth_vah",
    "prior_rth_val",
)

DEFAULT_MORNING_VA_BREAKOUT_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "breakout_type",
    "va_location",
    "gap_alignment",
)


@dataclass(frozen=True)
class MorningValueAreaBreakoutConfig:
    min_abs_return_pct: float = 0.0010  # 0.10%
    min_long_close_location: float = 0.65
    max_short_close_location: float = 0.35
    require_outside_prior_va: bool = True
    require_with_gap: bool = True
    allow_long: bool = True
    allow_short: bool = True
    min_stop_points: float = 15.0
    max_stop_points: float = 60.0
    reward_risk_ratio: float = 1.5
    profile_bin_size: float = 1.0
    value_area_pct: float = 0.70
    rth_start: str = "09:30"
    signal_bar_time: str = "09:44"
    rth_end: str = "16:00"


def build_morning_value_area_breakout_signal_export(
    data: pd.DataFrame,
    *,
    config: MorningValueAreaBreakoutConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_MORNING_VA_BREAKOUT_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_MORNING_VA_BREAKOUT_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_morning_value_area_breakout_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_morning_value_area_breakout_signal_frame(
    data: pd.DataFrame,
    *,
    config: MorningValueAreaBreakoutConfig | None = None,
) -> pd.DataFrame:
    cfg = config or MorningValueAreaBreakoutConfig()
    df = _base_ohlcv_frame(data)

    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    rth_start_min = _parse_hhmm(cfg.rth_start)
    signal_min = _parse_hhmm(cfg.signal_bar_time)
    rth_end_min = _parse_hhmm(cfg.rth_end)

    rth_mask = minutes.ge(rth_start_min) & minutes.le(rth_end_min)
    rth = df.loc[rth_mask].copy()
    session = df["time"].dt.date

    # 1. Prior completed RTH session Volume Profile + prior close
    prior_profiles = _compute_prior_session_profiles(
        rth,
        bin_size=float(cfg.profile_bin_size),
        value_area_pct=float(cfg.value_area_pct),
    )
    prior_close_by_session = rth.groupby(rth["time"].dt.date, sort=True)["close"].last().shift(1)

    prof_by_session = prior_profiles.set_index("session")
    prior_poc = session.map(prof_by_session["prior_poc"])
    prior_vah = session.map(prof_by_session["prior_vah"])
    prior_val = session.map(prof_by_session["prior_val"])
    prior_close = session.map(prior_close_by_session)

    # 2. Compute 09:30..09:44 (first 15-min opening range) stats per session
    or15_mask = minutes.ge(rth_start_min) & minutes.le(signal_min)
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
    or15_open = session.map(or15_stats["or15_open"])
    or15_high = session.map(or15_stats["or15_high"])
    or15_low = session.map(or15_stats["or15_low"])
    or15_close = session.map(or15_stats["or15_close"])

    or15_range = (or15_high - or15_low).replace(0.0, np.nan)
    or15_close_loc = (or15_close - or15_low) / or15_range
    ret_points = or15_close - or15_open
    ret_pct = ret_points / or15_open.replace(0.0, np.nan)
    abs_ret_pct = ret_pct.abs()

    signal_time_mask = minutes.eq(signal_min)

    # 3. Structural Value Area acceptance / level breakout conditions at 09:44
    long_above_vah = or15_close > prior_vah
    long_poc_break = (or15_low <= prior_poc) & (or15_close > prior_poc)
    long_val_break = (or15_low <= prior_val) & (or15_close > prior_val)
    long_struct_ok = (
        long_above_vah
        if bool(cfg.require_outside_prior_va)
        else (long_above_vah | long_poc_break | long_val_break)
    )

    short_below_val = or15_close < prior_val
    short_poc_break = (or15_high >= prior_poc) & (or15_close < prior_poc)
    short_vah_break = (or15_high >= prior_vah) & (or15_close < prior_vah)
    short_struct_ok = (
        short_below_val
        if bool(cfg.require_outside_prior_va)
        else (short_below_val | short_poc_break | short_vah_break)
    )

    gap_pts = or15_open - prior_close
    long_gap_ok = (gap_pts > 0) if bool(cfg.require_with_gap) else pd.Series(True, index=df.index)
    short_gap_ok = (gap_pts < 0) if bool(cfg.require_with_gap) else pd.Series(True, index=df.index)

    long_qualifies = (
        bool(cfg.allow_long)
        & signal_time_mask
        & prior_vah.notna()
        & ret_pct.ge(float(cfg.min_abs_return_pct))
        & or15_close_loc.ge(float(cfg.min_long_close_location))
        & long_struct_ok
        & long_gap_ok
    )
    short_qualifies = (
        bool(cfg.allow_short)
        & signal_time_mask
        & prior_val.notna()
        & ret_pct.le(-float(cfg.min_abs_return_pct))
        & or15_close_loc.le(float(cfg.max_short_close_location))
        & short_struct_ok
        & short_gap_ok
    )

    candidate_signal = pd.Series(0.0, index=df.index, dtype=float)
    candidate_signal.loc[long_qualifies] = 1.0
    candidate_signal.loc[short_qualifies] = -1.0

    direction = pd.Series("flat", index=df.index, dtype="object")
    direction.loc[candidate_signal > 0.0] = "long"
    direction.loc[candidate_signal < 0.0] = "short"

    # Context tags
    breakout_type = pd.Series("none", index=df.index, dtype="object")
    breakout_type.loc[long_qualifies & long_above_vah] = "outside_va_up"
    breakout_type.loc[long_qualifies & ~long_above_vah] = "inside_va_level_break_up"
    breakout_type.loc[short_qualifies & short_below_val] = "outside_va_down"
    breakout_type.loc[short_qualifies & ~short_below_val] = "inside_va_level_break_down"

    va_location = pd.Series("inside_va", index=df.index, dtype="object")
    va_location.loc[or15_close > prior_vah] = "above_vah"
    va_location.loc[or15_close < prior_val] = "below_val"

    gap_alignment = pd.Series("none", index=df.index, dtype="object")
    gap_alignment.loc[(candidate_signal > 0) & (gap_pts > 0)] = "with_gap"
    gap_alignment.loc[(candidate_signal < 0) & (gap_pts < 0)] = "with_gap"
    gap_alignment.loc[(candidate_signal > 0) & (gap_pts <= 0)] = "against_gap"
    gap_alignment.loc[(candidate_signal < 0) & (gap_pts >= 0)] = "against_gap"

    active_idx = candidate_signal.ne(0.0)
    va_breakout_score = pd.Series(0.0, index=df.index, dtype=float)
    va_breakout_score.loc[active_idx] = (
        candidate_signal.loc[active_idx]
        * abs_ret_pct.loc[active_idx]
        * 100.0
        * np.where(
            candidate_signal.loc[active_idx] > 0,
            or15_close_loc.loc[active_idx],
            1.0 - or15_close_loc.loc[active_idx],
        )
    )

    stop_points = pd.Series(np.nan, index=df.index, dtype=float)
    target_points = pd.Series(np.nan, index=df.index, dtype=float)
    clipped_stop = or15_range.loc[active_idx].clip(
        lower=float(cfg.min_stop_points),
        upper=float(cfg.max_stop_points),
    )
    stop_points.loc[active_idx] = clipped_stop
    target_points.loc[active_idx] = clipped_stop * float(cfg.reward_risk_ratio)

    out = df.copy()
    out["signal"] = candidate_signal
    out["signal_type"] = np.where(active_idx, "morning_va_breakout", "")
    out["candidate_signal"] = candidate_signal
    out["direction"] = direction
    out["va_breakout_score"] = va_breakout_score
    out["first15_return_pct"] = np.where(signal_time_mask, ret_pct, np.nan)
    out["first15_return_points"] = np.where(signal_time_mask, ret_points, np.nan)
    out["or15_range_points"] = np.where(signal_time_mask, or15_range, np.nan)
    out["or15_close_location"] = np.where(signal_time_mask, or15_close_loc, np.nan)
    out["prior_rth_poc"] = prior_poc
    out["prior_rth_vah"] = prior_vah
    out["prior_rth_val"] = prior_val
    out["stop_points"] = stop_points
    out["target_points"] = target_points
    out["breakout_type"] = breakout_type
    out["va_location"] = va_location
    out["gap_alignment"] = gap_alignment
    out["session_bucket"] = "rth_open"
    return out


def _base_ohlcv_frame(data: pd.DataFrame) -> pd.DataFrame:
    required = ["time", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in data.columns]
    if missing:
        raise ValueError(f"Missing required OHLCV columns: {missing}")

    work = data.copy()
    if "symbol" in work.columns:
        from main_backtest import select_continuous_outright_contract

        work = select_continuous_outright_contract(work, method="prior_session_volume")

    df = work.loc[:, required].copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time", kind="stable").reset_index(drop=True)
    return df


def _parse_hhmm(value: str) -> int:
    hour, minute = str(value).split(":", 1)
    return int(hour) * 60 + int(minute)
