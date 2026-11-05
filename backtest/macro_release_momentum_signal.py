from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_MACRO_FEATURE_COLUMNS = (
    "spike_volume_mult",
    "spike_return_pct",
    "spike_range_points",
    "spike_close_location",
    "ovn_high",
    "ovn_low",
    "ovn_range_points",
)

DEFAULT_MACRO_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "break_state",
)


@dataclass(frozen=True)
class MacroReleaseMomentumConfig:
    min_volume_mult: float = 2.5
    min_long_close_location: float = 0.65
    max_short_close_location: float = 0.35
    allow_long: bool = True
    allow_short: bool = True
    min_stop_points: float = 20.0
    max_stop_points: float = 50.0
    reward_risk_ratio: float = 1.50
    ovn_start: str = "00:00"
    ovn_end: str = "08:29"
    spike_start: str = "08:30"
    spike_end: str = "08:34"
    signal_bar_time: str = "08:35"
    flatten_bar_time: str = "09:25"


@dataclass(frozen=True)
class Macro10amMomentumConfig:
    """Tier-1 10:00 AM ET Macro Release Window (ISM, JOLTS, UMich, Consumer Confidence)."""
    min_volume_mult: float = 2.0
    min_long_close_location: float = 0.65
    max_short_close_location: float = 0.35
    allow_long: bool = True
    allow_short: bool = True
    min_stop_points: float = 20.0
    max_stop_points: float = 50.0
    reward_risk_ratio: float = 1.50
    pre_start: str = "09:40"
    pre_end: str = "09:59"
    rth_prior_start: str = "09:30"
    rth_prior_end: str = "09:59"
    spike_start: str = "10:00"
    spike_end: str = "10:04"
    signal_bar_time: str = "10:05"
    flatten_bar_time: str = "10:35"


def _parse_hhmm(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _base_ohlcv_frame(data: pd.DataFrame) -> pd.DataFrame:
    required = {"time", "open", "high", "low", "close"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    df = data.copy()
    if not np.issubdtype(df["time"].dtype, np.datetime64):
        df["time"] = pd.to_datetime(df["time"])
    if "volume" not in df.columns:
        df["volume"] = 1.0

    return df.sort_values("time").reset_index(drop=True)


def build_macro_release_momentum_signal_export(
    data: pd.DataFrame,
    *,
    config: MacroReleaseMomentumConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_MACRO_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_MACRO_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_macro_release_momentum_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_macro_release_momentum_signal_frame(
    data: pd.DataFrame,
    *,
    config: MacroReleaseMomentumConfig | None = None,
) -> pd.DataFrame:
    cfg = config or MacroReleaseMomentumConfig()
    df = _base_ohlcv_frame(data)

    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    ovn_start_m = _parse_hhmm(cfg.ovn_start)
    ovn_end_m = _parse_hhmm(cfg.ovn_end)
    spike_start_m = _parse_hhmm(cfg.spike_start)
    spike_end_m = _parse_hhmm(cfg.spike_end)
    signal_m = _parse_hhmm(cfg.signal_bar_time)

    session = df["time"].dt.date

    # 1. Overnight Range (00:00 - 08:29 ET)
    ovn_mask = minutes.ge(ovn_start_m) & minutes.le(ovn_end_m)
    ovn_bars = df.loc[ovn_mask]
    ovn_stats = ovn_bars.groupby(ovn_bars["time"].dt.date, sort=True).agg(
        ovn_high=("high", "max"),
        ovn_low=("low", "min"),
        pre_5m_vol=("volume", lambda v: float(v.tail(30).mean() * 5.0) if len(v) >= 10 else 0.0),
    )
    ovn_high = session.map(ovn_stats["ovn_high"])
    ovn_low = session.map(ovn_stats["ovn_low"])
    ovn_range = ovn_high - ovn_low
    pre_vol_5m = session.map(ovn_stats["pre_5m_vol"]).replace(0.0, np.nan)

    # 2. Release Spike (08:30 - 08:34 ET)
    spike_mask = minutes.ge(spike_start_m) & minutes.le(spike_end_m)
    spike_bars = df.loc[spike_mask]
    spike_stats = spike_bars.groupby(spike_bars["time"].dt.date, sort=True).agg(
        spike_open=("open", "first"),
        spike_high=("high", "max"),
        spike_low=("low", "min"),
        spike_close=("close", "last"),
        spike_vol=("volume", "sum"),
    )
    spike_open = session.map(spike_stats["spike_open"])
    spike_high = session.map(spike_stats["spike_high"])
    spike_low = session.map(spike_stats["spike_low"])
    spike_close = session.map(spike_stats["spike_close"])
    spike_vol = session.map(spike_stats["spike_vol"])

    spike_range = (spike_high - spike_low).replace(0.0, np.nan)
    spike_close_loc = (spike_close - spike_low) / spike_range
    spike_ret_pts = spike_close - spike_open
    spike_ret_pct = spike_ret_pts / spike_open.replace(0.0, np.nan)
    spike_volume_mult = (spike_vol / pre_vol_5m).fillna(0.0)

    # Signal Evaluation Bar: exactly at signal_bar_time (08:35 ET)
    signal_time_mask = minutes.eq(signal_m)
    is_macro_volume_spike = spike_volume_mult.ge(float(cfg.min_volume_mult))

    long_qualifies = (
        bool(cfg.allow_long)
        & signal_time_mask
        & is_macro_volume_spike
        & ovn_high.notna()
        & spike_close.gt(ovn_high)
        & spike_close_loc.ge(float(cfg.min_long_close_location))
    )

    short_qualifies = (
        bool(cfg.allow_short)
        & signal_time_mask
        & is_macro_volume_spike
        & ovn_low.notna()
        & spike_close.lt(ovn_low)
        & spike_close_loc.le(float(cfg.max_short_close_location))
    )

    candidate_signal = pd.Series(0.0, index=df.index, dtype=float)
    candidate_signal.loc[long_qualifies] = 1.0
    candidate_signal.loc[short_qualifies] = -1.0

    direction = pd.Series("flat", index=df.index, dtype="object")
    direction.loc[candidate_signal > 0.0] = "long"
    direction.loc[candidate_signal < 0.0] = "short"

    break_state = pd.Series("inside_overnight", index=df.index, dtype="object")
    break_state.loc[spike_close > ovn_high] = "above_ovn_high"
    break_state.loc[spike_close < ovn_low] = "below_ovn_low"

    # Stop points: half of the spike range clamped between min/max stop points
    half_spike_range = (spike_range * 0.50).clip(
        lower=float(cfg.min_stop_points), upper=float(cfg.max_stop_points)
    ).fillna(float(cfg.min_stop_points))
    stop_points = pd.Series(0.0, index=df.index, dtype=float)
    stop_points.loc[candidate_signal.ne(0.0)] = half_spike_range.loc[candidate_signal.ne(0.0)]

    target_points = pd.Series(0.0, index=df.index, dtype=float)
    target_points.loc[candidate_signal.ne(0.0)] = (
        stop_points.loc[candidate_signal.ne(0.0)] * float(cfg.reward_risk_ratio)
    )

    out = df.copy()
    out["signal"] = candidate_signal
    out["candidate_signal"] = candidate_signal
    out["signal_type"] = np.where(candidate_signal.ne(0.0), "macro_release_momentum", "")
    out["direction"] = direction
    out["stop_points"] = stop_points
    out["target_points"] = target_points
    out["spike_volume_mult"] = spike_volume_mult
    out["spike_return_pct"] = spike_ret_pct.fillna(0.0)
    out["spike_range_points"] = spike_range.fillna(0.0)
    out["spike_close_location"] = spike_close_loc.fillna(0.5)
    out["ovn_high"] = ovn_high.fillna(0.0)
    out["ovn_low"] = ovn_low.fillna(0.0)
    out["ovn_range_points"] = ovn_range.fillna(0.0)
    out["break_state"] = break_state

    return out


def build_10am_macro_momentum_signal_frame(
    data: pd.DataFrame,
    *,
    config: Macro10amMomentumConfig | None = None,
) -> pd.DataFrame:
    """Builds signals for 10:00 AM ET Tier-1 Macro Catalyst Breakout on NQ."""
    cfg = config or Macro10amMomentumConfig()
    df = _base_ohlcv_frame(data)

    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    pre_start_m = _parse_hhmm(cfg.pre_start)
    pre_end_m = _parse_hhmm(cfg.pre_end)
    rth_prior_start_m = _parse_hhmm(cfg.rth_prior_start)
    rth_prior_end_m = _parse_hhmm(cfg.rth_prior_end)
    spike_start_m = _parse_hhmm(cfg.spike_start)
    spike_end_m = _parse_hhmm(cfg.spike_end)
    signal_m = _parse_hhmm(cfg.signal_bar_time)

    session = df["time"].dt.date

    # 1. Pre-Release Baseline Volume (09:40 - 09:59 ET, 20 mins)
    pre_mask = minutes.ge(pre_start_m) & minutes.le(pre_end_m)
    pre_bars = df.loc[pre_mask]
    pre_stats = pre_bars.groupby(pre_bars["time"].dt.date, sort=True).agg(
        pre_5m_vol=("volume", lambda v: float(v.mean() * 5.0) if len(v) >= 10 else 0.0),
    )
    pre_vol_5m = session.map(pre_stats["pre_5m_vol"]).replace(0.0, np.nan)

    # 2. Prior RTH Range (09:30 - 09:59 ET)
    rth_prior_mask = minutes.ge(rth_prior_start_m) & minutes.le(rth_prior_end_m)
    rth_bars = df.loc[rth_prior_mask]
    rth_stats = rth_bars.groupby(rth_bars["time"].dt.date, sort=True).agg(
        rth_high=("high", "max"),
        rth_low=("low", "min"),
    )
    rth_high = session.map(rth_stats["rth_high"])
    rth_low = session.map(rth_stats["rth_low"])

    # 3. Release Spike (10:00 - 10:04 ET)
    spike_mask = minutes.ge(spike_start_m) & minutes.le(spike_end_m)
    spike_bars = df.loc[spike_mask]
    spike_stats = spike_bars.groupby(spike_bars["time"].dt.date, sort=True).agg(
        spike_open=("open", "first"),
        spike_high=("high", "max"),
        spike_low=("low", "min"),
        spike_close=("close", "last"),
        spike_vol=("volume", "sum"),
    )
    spike_open = session.map(spike_stats["spike_open"])
    spike_high = session.map(spike_stats["spike_high"])
    spike_low = session.map(spike_stats["spike_low"])
    spike_close = session.map(spike_stats["spike_close"])
    spike_vol = session.map(spike_stats["spike_vol"])

    spike_range = (spike_high - spike_low).replace(0.0, np.nan)
    spike_close_loc = (spike_close - spike_low) / spike_range
    spike_volume_mult = (spike_vol / pre_vol_5m).fillna(0.0)

    # Signal Evaluation Bar: exactly at signal_bar_time (10:05 ET)
    signal_time_mask = minutes.eq(signal_m)
    is_macro_volume_spike = spike_volume_mult.ge(float(cfg.min_volume_mult))

    long_qualifies = (
        bool(cfg.allow_long)
        & signal_time_mask
        & is_macro_volume_spike
        & rth_high.notna()
        & spike_close.gt(rth_high)
        & spike_close_loc.ge(float(cfg.min_long_close_location))
    )

    short_qualifies = (
        bool(cfg.allow_short)
        & signal_time_mask
        & is_macro_volume_spike
        & rth_low.notna()
        & spike_close.lt(rth_low)
        & spike_close_loc.le(float(cfg.max_short_close_location))
    )

    candidate_signal = pd.Series(0.0, index=df.index, dtype=float)
    candidate_signal.loc[long_qualifies] = 1.0
    candidate_signal.loc[short_qualifies] = -1.0

    direction = pd.Series("flat", index=df.index, dtype="object")
    direction.loc[candidate_signal > 0.0] = "long"
    direction.loc[candidate_signal < 0.0] = "short"

    half_spike_range = (spike_range * 0.50).clip(
        lower=float(cfg.min_stop_points), upper=float(cfg.max_stop_points)
    ).fillna(float(cfg.min_stop_points))
    stop_points = pd.Series(0.0, index=df.index, dtype=float)
    stop_points.loc[candidate_signal.ne(0.0)] = half_spike_range.loc[candidate_signal.ne(0.0)]

    target_points = pd.Series(0.0, index=df.index, dtype=float)
    target_points.loc[candidate_signal.ne(0.0)] = (
        stop_points.loc[candidate_signal.ne(0.0)] * float(cfg.reward_risk_ratio)
    )

    out = df.copy()
    out["signal"] = candidate_signal
    out["candidate_signal"] = candidate_signal
    out["signal_type"] = np.where(candidate_signal.ne(0.0), "macro_10am_momentum", "")
    out["direction"] = direction
    out["stop_points"] = stop_points
    out["target_points"] = target_points
    out["spike_volume_mult"] = spike_volume_mult
    out["rth_high"] = rth_high.fillna(0.0)
    out["rth_low"] = rth_low.fillna(0.0)

    return out
