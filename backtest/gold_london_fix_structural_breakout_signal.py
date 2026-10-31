from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.poc_rejection_signal import _compute_prior_session_profiles
from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_GOLD_LONDON_FIX_FEATURE_COLUMNS = (
    "fix_breakout_score",
    "fix_return_pct",
    "fix_return_points",
    "fix_range_points",
    "fix_close_location",
    "ib60_high",
    "ib60_low",
    "lon_high",
    "lon_low",
    "prior_rth_poc",
    "prior_rth_vah",
    "prior_rth_val",
)

DEFAULT_GOLD_LONDON_FIX_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "va_location",
    "london_break_state",
)


@dataclass(frozen=True)
class GoldLondonFixBreakoutConfig:
    min_abs_return_pct: float = 0.001125  # 0.1125% (0.75 * 0.0015)
    min_long_close_location: float = 0.70
    max_short_close_location: float = 0.30
    require_outside_prior_va: bool = True
    require_outside_london_range: bool = True
    allow_long: bool = True
    allow_short: bool = False
    min_stop_points: float = 3.0
    max_stop_points: float = 18.0
    reward_risk_ratio: float = 1.50
    profile_bin_size: float = 0.50
    value_area_pct: float = 0.70
    lon_start: str = "03:00"
    lon_end: str = "08:19"
    rth_start: str = "08:20"
    ib60_end: str = "09:19"
    fix_start: str = "10:00"
    signal_bar_time: str = "10:14"
    rth_end: str = "13:30"


def build_gold_london_fix_breakout_signal_export(
    data: pd.DataFrame,
    *,
    config: GoldLondonFixBreakoutConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_GOLD_LONDON_FIX_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_GOLD_LONDON_FIX_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_gold_london_fix_breakout_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_gold_london_fix_breakout_signal_frame(
    data: pd.DataFrame,
    *,
    config: GoldLondonFixBreakoutConfig | None = None,
) -> pd.DataFrame:
    cfg = config or GoldLondonFixBreakoutConfig()
    df = _base_ohlcv_frame(data)

    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    lon_start_m = _parse_hhmm(cfg.lon_start)
    lon_end_m = _parse_hhmm(cfg.lon_end)
    rth_start_m = _parse_hhmm(cfg.rth_start)
    ib60_end_m = _parse_hhmm(cfg.ib60_end)
    fix_start_m = _parse_hhmm(cfg.fix_start)
    signal_m = _parse_hhmm(cfg.signal_bar_time)
    rth_end_m = _parse_hhmm(cfg.rth_end)

    session = df["time"].dt.date

    # 1. Exact 1-minute Prior Session COMEX RTH (08:20-13:30 ET) Volume Profile
    rth_mask = minutes.ge(rth_start_m) & minutes.le(rth_end_m)
    rth = df.loc[rth_mask].copy()
    prior_profiles = _compute_prior_session_profiles(
        rth,
        bin_size=float(cfg.profile_bin_size),
        value_area_pct=float(cfg.value_area_pct),
    )
    prof_by_session = prior_profiles.set_index("session")
    prior_poc = session.map(prof_by_session["prior_poc"])
    prior_vah = session.map(prof_by_session["prior_vah"])
    prior_val = session.map(prof_by_session["prior_val"])

    # 2. London Session Range (03:00..08:19 ET)
    lon_mask = minutes.ge(lon_start_m) & minutes.le(lon_end_m)
    lon_bars = df.loc[lon_mask]
    lon_stats = lon_bars.groupby(lon_bars["time"].dt.date, sort=True).agg(
        lon_high=("high", "max"),
        lon_low=("low", "min"),
    )
    lon_high = session.map(lon_stats["lon_high"])
    lon_low = session.map(lon_stats["lon_low"])

    # 3. COMEX 60-Minute Initial Balance (08:20..09:19 ET)
    ib_mask = minutes.ge(rth_start_m) & minutes.le(ib60_end_m)
    ib_bars = df.loc[ib_mask]
    ib_stats = ib_bars.groupby(ib_bars["time"].dt.date, sort=True).agg(
        ib60_high=("high", "max"),
        ib60_low=("low", "min"),
    )
    ib60_high = session.map(ib_stats["ib60_high"])
    ib60_low = session.map(ib_stats["ib60_low"])

    # 4. LBMA PM Fix Window (10:00..10:14 ET)
    fix_mask = minutes.ge(fix_start_m) & minutes.le(signal_m)
    fix_bars = df.loc[fix_mask]
    fix_stats = fix_bars.groupby(fix_bars["time"].dt.date, sort=True).agg(
        fix_open=("open", "first"),
        fix_high=("high", "max"),
        fix_low=("low", "min"),
        fix_close=("close", "last"),
    )
    fix_open = session.map(fix_stats["fix_open"])
    fix_high = session.map(fix_stats["fix_high"])
    fix_low = session.map(fix_stats["fix_low"])
    fix_close = session.map(fix_stats["fix_close"])

    fix_range = (fix_high - fix_low).replace(0.0, np.nan)
    fix_close_loc = (fix_close - fix_low) / fix_range
    fix_ret_pts = fix_close - fix_open
    fix_ret_pct = fix_ret_pts / fix_open.replace(0.0, np.nan)

    signal_time_mask = minutes.eq(signal_m)

    long_va_ok = (fix_close > prior_vah) if bool(cfg.require_outside_prior_va) else pd.Series(True, index=df.index)
    short_va_ok = (fix_close < prior_val) if bool(cfg.require_outside_prior_va) else pd.Series(True, index=df.index)

    long_lon_ok = (fix_close > lon_high) if bool(cfg.require_outside_london_range) else pd.Series(True, index=df.index)
    short_lon_ok = (fix_close < lon_low) if bool(cfg.require_outside_london_range) else pd.Series(True, index=df.index)

    long_qualifies = (
        bool(cfg.allow_long)
        & signal_time_mask
        & prior_vah.notna()
        & ib60_high.notna()
        & lon_high.notna()
        & fix_ret_pct.ge(float(cfg.min_abs_return_pct))
        & fix_close_loc.ge(float(cfg.min_long_close_location))
        & fix_close.gt(ib60_high)
        & long_va_ok
        & long_lon_ok
    )
    short_qualifies = (
        bool(cfg.allow_short)
        & signal_time_mask
        & prior_val.notna()
        & ib60_low.notna()
        & lon_low.notna()
        & fix_ret_pct.le(-float(cfg.min_abs_return_pct))
        & fix_close_loc.le(float(cfg.max_short_close_location))
        & fix_close.lt(ib60_low)
        & short_va_ok
        & short_lon_ok
    )

    candidate_signal = pd.Series(0.0, index=df.index, dtype=float)
    candidate_signal.loc[long_qualifies] = 1.0
    candidate_signal.loc[short_qualifies] = -1.0

    direction = pd.Series("flat", index=df.index, dtype="object")
    direction.loc[candidate_signal > 0.0] = "long"
    direction.loc[candidate_signal < 0.0] = "short"

    va_location = pd.Series("inside_va", index=df.index, dtype="object")
    va_location.loc[fix_close > prior_vah] = "above_vah"
    va_location.loc[fix_close < prior_val] = "below_val"

    london_break_state = pd.Series("inside_london", index=df.index, dtype="object")
    london_break_state.loc[fix_close > lon_high] = "above_london_high"
    london_break_state.loc[fix_close < lon_low] = "below_london_low"

    active_idx = candidate_signal.ne(0.0)
    fix_breakout_score = pd.Series(0.0, index=df.index, dtype=float)
    fix_breakout_score.loc[active_idx] = (
        candidate_signal.loc[active_idx]
        * fix_ret_pct.abs().loc[active_idx]
        * 100.0
        * np.where(
            candidate_signal.loc[active_idx] > 0,
            fix_close_loc.loc[active_idx],
            1.0 - fix_close_loc.loc[active_idx],
        )
    )

    stop_points = pd.Series(np.nan, index=df.index, dtype=float)
    target_points = pd.Series(np.nan, index=df.index, dtype=float)
    clipped_stop = fix_range.loc[active_idx].clip(
        lower=float(cfg.min_stop_points),
        upper=float(cfg.max_stop_points),
    )
    stop_points.loc[active_idx] = clipped_stop
    target_points.loc[active_idx] = clipped_stop * float(cfg.reward_risk_ratio)

    out = df.copy()
    out["signal"] = candidate_signal
    out["signal_type"] = np.where(active_idx, "gold_london_fix_breakout", "")
    out["candidate_signal"] = candidate_signal
    out["direction"] = direction
    out["fix_breakout_score"] = fix_breakout_score
    out["fix_return_pct"] = np.where(signal_time_mask, fix_ret_pct, np.nan)
    out["fix_return_points"] = np.where(signal_time_mask, fix_ret_pts, np.nan)
    out["fix_range_points"] = np.where(signal_time_mask, fix_range, np.nan)
    out["fix_close_location"] = np.where(signal_time_mask, fix_close_loc, np.nan)
    out["ib60_high"] = ib60_high
    out["ib60_low"] = ib60_low
    out["lon_high"] = lon_high
    out["lon_low"] = lon_low
    out["prior_rth_poc"] = prior_poc
    out["prior_rth_vah"] = prior_vah
    out["prior_rth_val"] = prior_val
    out["stop_points"] = stop_points
    out["target_points"] = target_points
    out["va_location"] = va_location
    out["london_break_state"] = london_break_state
    out["session_bucket"] = "london_pm_fix"
    return out


def _base_ohlcv_frame(data: pd.DataFrame) -> pd.DataFrame:
    required = ["time", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in data.columns]
    if missing:
        raise ValueError(f"Missing required OHLCV columns: {missing}")
    df = data.loc[:, required].copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time", kind="stable").reset_index(drop=True)
    return df


def _parse_hhmm(value: str) -> int:
    hour, minute = str(value).split(":", 1)
    return int(hour) * 60 + int(minute)
