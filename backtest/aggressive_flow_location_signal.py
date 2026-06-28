from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_AGGRESSIVE_FLOW_LOCATION_FEATURE_COLUMNS = (
    "aggressive_flow_location_score",
    "abs_aggressive_flow_share",
    "bar_price_change_points",
    "context_age_seconds",
    "profile_room_up_points",
    "profile_room_down_points",
    "location_score_multiplier",
    "volume_spike_ratio",
)

DEFAULT_AGGRESSIVE_FLOW_LOCATION_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "profile_acceptance_state",
    "orderflow_state",
    "flow_price_state",
    "location_context_fresh",
    "source_bar_time",
)


@dataclass(frozen=True)
class AggressiveFlowLocationSignalConfig:
    min_abs_flow_share: float = 0.35
    min_price_change_points: float = 1.0
    min_score: float = 1.0
    value_acceptance_buffer_points: float = 0.5
    profile_acceptance_buffer_points: float = 0.5
    max_context_age: str = "5min"
    trade_start: str = "09:35"
    trade_end: str = "15:45"
    score_price_scale_points: float = 2.0
    score_cap: float = 4.0
    require_profile_acceptance: bool = True
    require_context_fresh: bool = True


def build_aggressive_flow_location_signal_export(
    bars: pd.DataFrame,
    location_context: pd.DataFrame | str | Path,
    *,
    config: AggressiveFlowLocationSignalConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_AGGRESSIVE_FLOW_LOCATION_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_AGGRESSIVE_FLOW_LOCATION_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_aggressive_flow_location_signal_frame(
        bars,
        location_context,
        config=config,
    )
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_aggressive_flow_location_signal_frame(
    bars: pd.DataFrame,
    location_context: pd.DataFrame | str | Path,
    *,
    config: AggressiveFlowLocationSignalConfig | None = None,
) -> pd.DataFrame:
    cfg = config or AggressiveFlowLocationSignalConfig()
    _validate_config(cfg)
    base = _normalize_bars(bars)
    context = _normalize_location_context(_read_frame(location_context))
    merged = _merge_context(base, context)

    context_time = _datetime_col(merged, "context_available_time")
    if context_time.isna().all():
        context_time = _datetime_col(merged, "time_context")
    age = pd.to_datetime(merged["time"], errors="coerce") - context_time
    max_age = pd.Timedelta(cfg.max_context_age)
    context_fresh = context_time.notna() & age.ge(pd.Timedelta(0)) & age.le(max_age)

    flow_share = _numeric_col(merged, "orderflow_bid_ask_dominance")
    abs_flow = flow_share.abs()
    price_change = pd.to_numeric(merged["close"], errors="coerce") - pd.to_numeric(merged["open"], errors="coerce")
    price_direction = pd.Series(0, index=merged.index, dtype=int)
    price_direction.loc[price_change.ge(float(cfg.min_price_change_points))] = 1
    price_direction.loc[price_change.le(-float(cfg.min_price_change_points))] = -1

    profile_state = _profile_acceptance_state(merged, cfg)
    location_direction = pd.Series(0, index=merged.index, dtype=int)
    location_direction.loc[profile_state.str.startswith("accepted_above")] = 1
    location_direction.loc[profile_state.str.startswith("accepted_below")] = -1

    flow_component = (abs_flow / max(float(cfg.min_abs_flow_share), 1e-9)).clip(lower=0.0, upper=float(cfg.score_cap))
    price_component = (
        price_change.abs() / max(float(cfg.score_price_scale_points), 1e-9)
    ).clip(lower=0.0, upper=float(cfg.score_cap))
    location_multiplier = _location_multiplier(profile_state)
    score_location_multiplier = (
        location_multiplier.mask(location_multiplier.eq(0.0), 1.0)
        if not cfg.require_profile_acceptance
        else location_multiplier
    )
    volume_multiplier = _volume_multiplier(merged)
    signed_score = (
        price_direction.astype(float)
        * flow_component.fillna(0.0)
        * price_component.fillna(0.0)
        * score_location_multiplier
        * volume_multiplier
    )

    in_time = _time_window(merged["time"], cfg.trade_start, cfg.trade_end)
    fresh_gate = context_fresh if cfg.require_context_fresh else pd.Series(True, index=merged.index)
    location_gate = location_direction.eq(price_direction) if cfg.require_profile_acceptance else price_direction.ne(0)
    strong_flow = abs_flow.ge(float(cfg.min_abs_flow_share))
    strong_score = signed_score.abs().ge(float(cfg.min_score))
    active = fresh_gate & in_time & strong_flow & price_direction.ne(0) & location_gate & strong_score

    signal = pd.Series(0.0, index=merged.index)
    signal.loc[active & price_direction.eq(1)] = 1.0
    signal.loc[active & price_direction.eq(-1)] = -1.0

    out = base.copy()
    out["signal"] = signal
    out["signal_type"] = np.where(signal.ne(0), "aggressive_flow_location", "")
    out["aggressive_flow_location_score"] = signed_score.fillna(0.0)
    out["abs_aggressive_flow_share"] = abs_flow
    out["bar_price_change_points"] = price_change
    out["context_age_seconds"] = age.dt.total_seconds()
    out["profile_acceptance_state"] = profile_state
    out["orderflow_state"] = _orderflow_state(flow_share, cfg)
    out["flow_price_state"] = _flow_price_state(signal, price_direction, profile_state)
    out["location_context_fresh"] = context_fresh
    out["location_score_multiplier"] = score_location_multiplier
    out["volume_spike_ratio"] = _numeric_col(merged, "volume_spike_ratio")
    out["profile_room_up_points"] = _numeric_col(merged, "profile_upper") - out["close"]
    out["profile_room_down_points"] = out["close"] - _numeric_col(merged, "profile_lower")
    out["source_bar_time"] = _datetime_col(merged, "source_bar_time")
    if "vwap_side" not in out.columns:
        out["vwap_side"] = ""
    return out


def _read_frame(frame_or_path: pd.DataFrame | str | Path) -> pd.DataFrame:
    if isinstance(frame_or_path, pd.DataFrame):
        return frame_or_path.copy()
    path = Path(frame_or_path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def _normalize_bars(bars: pd.DataFrame) -> pd.DataFrame:
    required = ["time", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in bars.columns]
    if missing:
        raise ValueError(f"bar data missing required columns: {missing}")
    out = bars.loc[:, required].copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=required)
    return out.sort_values("time", kind="stable").reset_index(drop=True)


def _normalize_location_context(context: pd.DataFrame) -> pd.DataFrame:
    if "time" not in context.columns:
        raise ValueError("location context must contain a time column")
    out = context.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    out = out.dropna(subset=["time"]).sort_values("time", kind="stable")
    keep = [col for col in out.columns if col not in {"open", "high", "low", "close", "volume"}]
    return out.loc[:, keep].reset_index(drop=True)


def _merge_context(base: pd.DataFrame, context: pd.DataFrame) -> pd.DataFrame:
    return pd.merge_asof(
        base.sort_values("time", kind="stable"),
        context.sort_values("time", kind="stable"),
        on="time",
        direction="backward",
        suffixes=("", "_context"),
    ).reset_index(drop=True)


def _profile_acceptance_state(frame: pd.DataFrame, cfg: AggressiveFlowLocationSignalConfig) -> pd.Series:
    close = _numeric_col(frame, "close")
    profile_upper = _numeric_col(frame, "profile_upper")
    profile_lower = _numeric_col(frame, "profile_lower")
    vp_vah = _numeric_col(frame, "vp_vah")
    vp_val = _numeric_col(frame, "vp_val")
    state = pd.Series("unknown", index=frame.index, dtype="object")

    inside_value = vp_val.notna() & vp_vah.notna() & close.ge(vp_val) & close.le(vp_vah)
    state.loc[inside_value] = "inside_value"

    above_value = vp_vah.notna() & close.ge(vp_vah + float(cfg.value_acceptance_buffer_points))
    below_value = vp_val.notna() & close.le(vp_val - float(cfg.value_acceptance_buffer_points))
    state.loc[above_value] = "accepted_above_value"
    state.loc[below_value] = "accepted_below_value"

    above_profile = profile_upper.notna() & close.ge(profile_upper + float(cfg.profile_acceptance_buffer_points))
    below_profile = profile_lower.notna() & close.le(profile_lower - float(cfg.profile_acceptance_buffer_points))
    state.loc[above_profile] = "accepted_above_profile"
    state.loc[below_profile] = "accepted_below_profile"
    return state


def _location_multiplier(profile_state: pd.Series) -> pd.Series:
    multiplier = pd.Series(0.0, index=profile_state.index)
    multiplier.loc[profile_state.isin(["accepted_above_value", "accepted_below_value"])] = 1.0
    multiplier.loc[profile_state.isin(["accepted_above_profile", "accepted_below_profile"])] = 1.25
    return multiplier


def _volume_multiplier(frame: pd.DataFrame) -> pd.Series:
    ratio = _numeric_col(frame, "volume_spike_ratio")
    if ratio.isna().all():
        return pd.Series(1.0, index=frame.index)
    return ratio.fillna(1.0).clip(lower=0.75, upper=2.0)


def _orderflow_state(flow_share: pd.Series, cfg: AggressiveFlowLocationSignalConfig) -> pd.Series:
    threshold = float(cfg.min_abs_flow_share)
    state = pd.Series("unknown", index=flow_share.index, dtype="object")
    state.loc[flow_share.notna() & flow_share.abs().lt(threshold)] = "two_sided_flow"
    state.loc[flow_share.ge(threshold)] = "raw_b_side_dominant"
    state.loc[flow_share.le(-threshold)] = "raw_a_side_dominant"
    return state


def _flow_price_state(signal: pd.Series, price_direction: pd.Series, profile_state: pd.Series) -> pd.Series:
    state = pd.Series("inactive", index=signal.index, dtype="object")
    state.loc[price_direction.gt(0)] = "up_expansion"
    state.loc[price_direction.lt(0)] = "down_expansion"
    state.loc[signal.gt(0)] = "long_flow_location_acceptance"
    state.loc[signal.lt(0)] = "short_flow_location_acceptance"
    state.loc[profile_state.eq("inside_value") & signal.eq(0)] = "inside_value_no_signal"
    return state


def _time_window(times: pd.Series, start: str, end: str) -> pd.Series:
    minutes = pd.to_datetime(times).dt.hour * 60 + pd.to_datetime(times).dt.minute
    start_min = _parse_hhmm(start)
    end_min = _parse_hhmm(end)
    if start_min <= end_min:
        return minutes.ge(start_min) & minutes.le(end_min)
    return minutes.ge(start_min) | minutes.le(end_min)


def _parse_hhmm(value: str) -> int:
    hour, minute = str(value).split(":", 1)
    return int(hour) * 60 + int(minute)


def _numeric_col(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _datetime_col(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    return pd.to_datetime(frame[column], errors="coerce")


def _validate_config(cfg: AggressiveFlowLocationSignalConfig) -> None:
    if cfg.min_abs_flow_share < 0.0:
        raise ValueError("min_abs_flow_share must be non-negative")
    if cfg.min_price_change_points < 0.0:
        raise ValueError("min_price_change_points must be non-negative")
    if cfg.min_score < 0.0:
        raise ValueError("min_score must be non-negative")
    if pd.Timedelta(cfg.max_context_age) < pd.Timedelta(0):
        raise ValueError("max_context_age must be non-negative")
    if cfg.score_price_scale_points <= 0.0:
        raise ValueError("score_price_scale_points must be positive")
    if cfg.score_cap <= 0.0:
        raise ValueError("score_cap must be positive")


__all__ = [
    "AggressiveFlowLocationSignalConfig",
    "DEFAULT_AGGRESSIVE_FLOW_LOCATION_CONTEXT_COLUMNS",
    "DEFAULT_AGGRESSIVE_FLOW_LOCATION_FEATURE_COLUMNS",
    "build_aggressive_flow_location_signal_export",
    "build_aggressive_flow_location_signal_frame",
]
