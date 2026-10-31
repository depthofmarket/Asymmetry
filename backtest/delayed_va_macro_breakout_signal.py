"""
Delayed Value-Area Escape & 10:00 ET Macro Impulse Breakout Signal (H9).

Pre-registered in docs/research_hypotheses/2026-10-30_delayed_va_macro_breakout_h9.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.poc_rejection_signal import _compute_prior_session_profiles
from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_DELAYED_VA_BREAKOUT_FEATURE_COLUMNS = (
    "delayed_va_breakout_score",
    "or35_return_pct",
    "or35_return_points",
    "wave2_return_pct",
    "or35_range_points",
    "or35_close_location",
    "prior_rth_poc",
    "prior_rth_vah",
    "prior_rth_val",
)

DEFAULT_DELAYED_VA_BREAKOUT_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "breakout_type",
    "or15_va_regime",
    "gap_alignment",
)


@dataclass(frozen=True)
class DelayedVaMacroBreakoutConfig:
    min_abs_return_pct: float = 0.0010  # 0.10% (inherited from Strategy 1)
    min_long_close_location: float = 0.65
    max_short_close_location: float = 0.35
    require_outside_prior_va: bool = True
    require_or15_breakout: bool = True
    require_h4_inactive: bool = True
    require_with_gap: bool = False
    allow_long: bool = True
    allow_short: bool = True
    min_stop_points: float = 15.0
    max_stop_points: float = 60.0
    reward_risk_ratio: float = 1.5
    profile_bin_size: float = 1.0
    value_area_pct: float = 0.70
    rth_start: str = "09:30"
    or15_end: str = "09:44"
    signal_bar_time: str = "10:04"
    rth_end: str = "16:00"


def build_delayed_va_macro_breakout_signal_export(
    data: pd.DataFrame,
    *,
    config: DelayedVaMacroBreakoutConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_DELAYED_VA_BREAKOUT_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_DELAYED_VA_BREAKOUT_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_delayed_va_macro_breakout_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_delayed_va_macro_breakout_signal_frame(
    data: pd.DataFrame,
    *,
    config: DelayedVaMacroBreakoutConfig | None = None,
) -> pd.DataFrame:
    cfg = config or DelayedVaMacroBreakoutConfig()
    df = _base_ohlcv_frame(data)

    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    rth_start_min = _parse_hhmm(cfg.rth_start)
    or15_end_min = _parse_hhmm(cfg.or15_end)
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
    or15_open = session.map(or15_stats["or15_open"])
    or15_high = session.map(or15_stats["or15_high"])
    or15_low = session.map(or15_stats["or15_low"])
    or15_close = session.map(or15_stats["or15_close"])

    or15_range = (or15_high - or15_low).replace(0.0, np.nan)
    or15_close_loc = (or15_close - or15_low) / or15_range
    or15_ret_pct = (or15_close - or15_open) / or15_open.replace(0.0, np.nan)
    gap_pts = or15_open - prior_close

    # Check if frozen Strategy 1 (H4) triggered at 09:44 ET on this session
    h4_long_session = (
        prior_vah.notna()
        & or15_ret_pct.ge(float(cfg.min_abs_return_pct))
        & or15_close_loc.ge(float(cfg.min_long_close_location))
        & (or15_close > prior_vah)
        & (gap_pts > 0.0)
    )
    h4_short_session = (
        prior_val.notna()
        & or15_ret_pct.le(-float(cfg.min_abs_return_pct))
        & or15_close_loc.le(float(cfg.max_short_close_location))
        & (or15_close < prior_val)
        & (gap_pts < 0.0)
    )
    h4_active_session = h4_long_session | h4_short_session

    # 3. Compute 09:30..10:04 (first 35-min opening + macro window) stats per session
    or35_mask = minutes.ge(rth_start_min) & minutes.le(signal_min)
    or35_bars = df.loc[or35_mask]
    or35_stats = (
        or35_bars.groupby(or35_bars["time"].dt.date, sort=True)
        .agg(
            or35_open=("open", "first"),
            or35_high=("high", "max"),
            or35_low=("low", "min"),
            or35_close=("close", "last"),
        )
    )
    or35_open = session.map(or35_stats["or35_open"])
    or35_high = session.map(or35_stats["or35_high"])
    or35_low = session.map(or35_stats["or35_low"])
    or35_close = session.map(or35_stats["or35_close"])

    or35_range = (or35_high - or35_low).replace(0.0, np.nan)
    or35_close_loc = (or35_close - or35_low) / or35_range
    or35_ret_points = or35_close - or35_open
    or35_ret_pct = or35_ret_points / or35_open.replace(0.0, np.nan)
    abs_or35_ret_pct = or35_ret_pct.abs()

    wave2_ret_points = or35_close - or15_close
    wave2_ret_pct = wave2_ret_points / or15_close.replace(0.0, np.nan)

    signal_time_mask = minutes.eq(signal_min)

    # 4. Structural Value Area escape & OR15 breakout conditions at 10:04 ET
    h4_gate_ok = (~h4_active_session) if bool(cfg.require_h4_inactive) else pd.Series(True, index=df.index)

    long_va_ok = (or35_close > prior_vah) if bool(cfg.require_outside_prior_va) else pd.Series(True, index=df.index)
    short_va_ok = (or35_close < prior_val) if bool(cfg.require_outside_prior_va) else pd.Series(True, index=df.index)

    long_or15_ok = (or35_close > or15_high) if bool(cfg.require_or15_breakout) else pd.Series(True, index=df.index)
    short_or15_ok = (or35_close < or15_low) if bool(cfg.require_or15_breakout) else pd.Series(True, index=df.index)

    long_gap_ok = (gap_pts > 0.0) if bool(cfg.require_with_gap) else pd.Series(True, index=df.index)
    short_gap_ok = (gap_pts < 0.0) if bool(cfg.require_with_gap) else pd.Series(True, index=df.index)

    long_qualifies = (
        bool(cfg.allow_long)
        & signal_time_mask
        & h4_gate_ok
        & prior_vah.notna()
        & or15_high.notna()
        & or35_ret_pct.ge(float(cfg.min_abs_return_pct))
        & wave2_ret_pct.gt(0.0)
        & or35_close_loc.ge(float(cfg.min_long_close_location))
        & long_va_ok
        & long_or15_ok
        & long_gap_ok
    )
    short_qualifies = (
        bool(cfg.allow_short)
        & signal_time_mask
        & h4_gate_ok
        & prior_val.notna()
        & or15_low.notna()
        & or35_ret_pct.le(-float(cfg.min_abs_return_pct))
        & wave2_ret_pct.lt(0.0)
        & or35_close_loc.le(float(cfg.max_short_close_location))
        & short_va_ok
        & short_or15_ok
        & short_gap_ok
    )

    candidate_signal = pd.Series(0.0, index=df.index, dtype=float)
    candidate_signal.loc[long_qualifies] = 1.0
    candidate_signal.loc[short_qualifies] = -1.0

    direction = pd.Series("flat", index=df.index, dtype="object")
    direction.loc[candidate_signal > 0.0] = "long"
    direction.loc[candidate_signal < 0.0] = "short"

    or15_in_va = (or15_close >= prior_val) & (or15_close <= prior_vah)
    or15_va_regime = pd.Series("none", index=df.index, dtype="object")
    or15_va_regime.loc[signal_time_mask & or15_in_va] = "or15_inside_va"
    or15_va_regime.loc[signal_time_mask & ~or15_in_va] = "or15_outside_va_coiled"

    breakout_type = pd.Series("none", index=df.index, dtype="object")
    breakout_type.loc[long_qualifies & or15_in_va] = "inside_va_to_above_vah"
    breakout_type.loc[long_qualifies & ~or15_in_va] = "coiled_outside_va_up"
    breakout_type.loc[short_qualifies & or15_in_va] = "inside_va_to_below_val"
    breakout_type.loc[short_qualifies & ~or15_in_va] = "coiled_outside_va_down"

    gap_alignment = pd.Series("none", index=df.index, dtype="object")
    gap_alignment.loc[(candidate_signal > 0) & (gap_pts > 0)] = "with_gap"
    gap_alignment.loc[(candidate_signal < 0) & (gap_pts < 0)] = "with_gap"
    gap_alignment.loc[(candidate_signal > 0) & (gap_pts <= 0)] = "against_gap"
    gap_alignment.loc[(candidate_signal < 0) & (gap_pts >= 0)] = "against_gap"

    active_idx = candidate_signal.ne(0.0)
    delayed_va_breakout_score = pd.Series(0.0, index=df.index, dtype=float)
    delayed_va_breakout_score.loc[active_idx] = (
        candidate_signal.loc[active_idx]
        * abs_or35_ret_pct.loc[active_idx]
        * 100.0
        * np.where(
            candidate_signal.loc[active_idx] > 0,
            or35_close_loc.loc[active_idx],
            1.0 - or35_close_loc.loc[active_idx],
        )
    )

    stop_points = pd.Series(np.nan, index=df.index, dtype=float)
    target_points = pd.Series(np.nan, index=df.index, dtype=float)
    clipped_stop = or35_range.loc[active_idx].clip(
        lower=float(cfg.min_stop_points),
        upper=float(cfg.max_stop_points),
    )
    stop_points.loc[active_idx] = clipped_stop
    target_points.loc[active_idx] = clipped_stop * float(cfg.reward_risk_ratio)

    out = df.copy()
    out["signal"] = candidate_signal
    out["signal_type"] = np.where(active_idx, "delayed_va_macro_breakout", "")
    out["candidate_signal"] = candidate_signal
    out["direction"] = direction
    out["delayed_va_breakout_score"] = delayed_va_breakout_score
    out["or35_return_pct"] = np.where(signal_time_mask, or35_ret_pct, np.nan)
    out["or35_return_points"] = np.where(signal_time_mask, or35_ret_points, np.nan)
    out["wave2_return_pct"] = np.where(signal_time_mask, wave2_ret_pct, np.nan)
    out["or35_range_points"] = np.where(signal_time_mask, or35_range, np.nan)
    out["or35_close_location"] = np.where(signal_time_mask, or35_close_loc, np.nan)
    out["prior_rth_poc"] = prior_poc
    out["prior_rth_vah"] = prior_vah
    out["prior_rth_val"] = prior_val
    out["stop_points"] = stop_points
    out["target_points"] = target_points
    out["breakout_type"] = breakout_type
    out["or15_va_regime"] = or15_va_regime
    out["gap_alignment"] = gap_alignment
    out["session_bucket"] = "rth_morning_macro"
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
