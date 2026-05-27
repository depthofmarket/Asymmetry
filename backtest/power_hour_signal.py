from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_POWER_HOUR_FEATURE_COLUMNS = (
    "power_hour_score",
    "session_move_points",
    "abs_session_move_points",
    "session_move_to_range_ratio",
    "session_range_points",
    "event_close_position",
    "momentum_points",
    "session_vwap_distance_points",
)


DEFAULT_POWER_HOUR_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "closing_flow_side",
    "close_location",
    "momentum_state",
    "power_hour_pattern",
)


@dataclass(frozen=True)
class PowerHourSignalConfig:
    signal_start: str = "15:00"
    signal_end: str = "15:30"
    rth_start: str = "09:30"
    rth_end: str = "16:00"
    momentum_lookback_bars: int = 30
    min_session_move_points: float = 20.0
    min_session_move_to_range_ratio: float = 0.45
    min_momentum_points: float = 8.0
    close_position_long_min: float = 0.80
    close_position_short_max: float = 0.20
    min_vwap_distance_points: float = 3.0


def build_power_hour_signal_export(
    data: pd.DataFrame,
    *,
    config: PowerHourSignalConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_POWER_HOUR_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_POWER_HOUR_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_power_hour_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_power_hour_signal_frame(
    data: pd.DataFrame,
    *,
    config: PowerHourSignalConfig | None = None,
) -> pd.DataFrame:
    cfg = config or PowerHourSignalConfig()
    _validate_config(cfg)
    df = _base_ohlcv_frame(data)

    session = df["time"].dt.date
    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    rth_start_min = _parse_hhmm(cfg.rth_start)
    rth_end_min = _parse_hhmm(cfg.rth_end)
    rth_mask = minutes.ge(rth_start_min) & minutes.le(rth_end_min)
    signal_time = rth_mask & _time_window(df["time"], cfg.signal_start, cfg.signal_end)

    rth = df.loc[rth_mask].copy()
    rth_session = rth["time"].dt.date
    rth_open_by_session = rth.groupby(rth_session, sort=True)["open"].first()

    rth_open = session.map(rth_open_by_session)
    session_high = pd.Series(np.nan, index=df.index)
    session_low = pd.Series(np.nan, index=df.index)
    session_high.loc[rth.index] = rth["high"].groupby(rth_session).cummax()
    session_low.loc[rth.index] = rth["low"].groupby(rth_session).cummin()

    session_range = (session_high - session_low).clip(lower=0.0)
    session_move = df["close"] - rth_open
    abs_session_move = session_move.abs()
    session_move_to_range = _safe_divide(abs_session_move, session_range)
    close_position = _safe_divide(df["close"] - session_low, session_range).clip(lower=0.0, upper=1.0)
    vwap = _rth_session_vwap(df, rth_mask)
    vwap_distance = df["close"] - vwap
    momentum = df["close"] - df["close"].groupby(session).shift(cfg.momentum_lookback_bars)

    accepted_move = (
        abs_session_move.ge(cfg.min_session_move_points)
        & session_move_to_range.ge(cfg.min_session_move_to_range_ratio)
    )
    long_signal_raw = (
        signal_time
        & accepted_move
        & session_move.gt(0.0)
        & close_position.ge(cfg.close_position_long_min)
        & momentum.ge(cfg.min_momentum_points)
        & vwap_distance.ge(cfg.min_vwap_distance_points)
    )
    short_signal_raw = (
        signal_time
        & accepted_move
        & session_move.lt(0.0)
        & close_position.le(cfg.close_position_short_max)
        & momentum.le(-cfg.min_momentum_points)
        & vwap_distance.le(-cfg.min_vwap_distance_points)
    )

    long_signal = _first_true_per_session(long_signal_raw, session)
    short_signal = _first_true_per_session(short_signal_raw, session)
    score = _power_hour_score(
        session_move_to_range=session_move_to_range,
        abs_vwap_distance=vwap_distance.abs(),
        abs_momentum=momentum.abs(),
        directional_close_position=np.where(long_signal, close_position, 1.0 - close_position),
        cfg=cfg,
    )

    signal = pd.Series(0.0, index=df.index)
    signal.loc[long_signal] = 1.0
    signal.loc[short_signal] = -1.0
    signed_score = pd.Series(0.0, index=df.index)
    signed_score.loc[long_signal] = score.loc[long_signal]
    signed_score.loc[short_signal] = -score.loc[short_signal]

    out = df.copy()
    out["signal"] = signal
    out["signal_type"] = np.where(signal.ne(0), "power_hour", "")
    out["power_hour_score"] = signed_score.fillna(0.0)
    out["session_move_points"] = session_move
    out["abs_session_move_points"] = abs_session_move
    out["session_move_to_range_ratio"] = session_move_to_range
    out["session_range_points"] = session_range
    out["event_close_position"] = close_position
    out["momentum_points"] = momentum
    out["session_vwap_distance_points"] = vwap_distance
    out["vwap_side"] = np.where(vwap_distance.ge(0.0), "above_vwap", "below_vwap")
    out["closing_flow_side"] = np.where(long_signal, "accepted_up", np.where(short_signal, "accepted_down", ""))
    out["close_location"] = np.where(
        close_position.ge(cfg.close_position_long_min),
        "near_session_high",
        np.where(close_position.le(cfg.close_position_short_max), "near_session_low", "middle"),
    )
    out["momentum_state"] = np.where(
        momentum.ge(cfg.min_momentum_points),
        "aligned_up",
        np.where(momentum.le(-cfg.min_momentum_points), "aligned_down", "not_aligned"),
    )
    out["power_hour_pattern"] = np.where(signal.ne(0), "late_day_accepted_trend_continuation", "")
    return out


def _base_ohlcv_frame(data: pd.DataFrame) -> pd.DataFrame:
    required = ["time", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in data.columns]
    if missing:
        raise ValueError(f"bar data missing required columns: {missing}")
    df = data.loc[:, required].copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time", "open", "high", "low", "close", "volume"])
    return df.sort_values("time").reset_index(drop=True)


def _rth_session_vwap(df: pd.DataFrame, rth_mask: pd.Series) -> pd.Series:
    vwap = pd.Series(np.nan, index=df.index)
    rth = df.loc[rth_mask]
    typical = (rth["high"] + rth["low"] + rth["close"]) / 3.0
    dollar_volume = typical * rth["volume"]
    session = rth["time"].dt.date
    cum_dollar = dollar_volume.groupby(session).cumsum()
    cum_volume = rth["volume"].groupby(session).cumsum()
    vwap.loc[rth.index] = _safe_divide(cum_dollar, cum_volume)
    return vwap


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


def _safe_divide(numerator: pd.Series | np.ndarray, denominator: pd.Series | np.ndarray) -> pd.Series:
    num = pd.Series(numerator)
    den = pd.Series(denominator)
    result = num / den.replace(0.0, np.nan)
    return result.replace([np.inf, -np.inf], np.nan)


def _first_true_per_session(mask: pd.Series, session: pd.Series) -> pd.Series:
    active = mask.fillna(False).astype(bool)
    counts = active.groupby(session).cumsum()
    return active & counts.eq(1)


def _power_hour_score(
    *,
    session_move_to_range: pd.Series,
    abs_vwap_distance: pd.Series,
    abs_momentum: pd.Series,
    directional_close_position: np.ndarray,
    cfg: PowerHourSignalConfig,
) -> pd.Series:
    move_component = session_move_to_range.clip(lower=0.0).fillna(0.0)
    vwap_component = abs_vwap_distance.clip(lower=0.0).fillna(0.0) / max(cfg.min_vwap_distance_points, 1.0)
    momentum_component = abs_momentum.clip(lower=0.0).fillna(0.0) / max(cfg.min_momentum_points, 1.0)
    close_component = pd.Series(directional_close_position).clip(lower=0.0, upper=1.0).fillna(0.0)
    score = (move_component + vwap_component + momentum_component + close_component) / 4.0
    return score.clip(lower=0.0)


def _validate_config(cfg: PowerHourSignalConfig) -> None:
    if cfg.momentum_lookback_bars <= 0:
        raise ValueError("momentum_lookback_bars must be positive")
    if cfg.min_session_move_points <= 0:
        raise ValueError("min_session_move_points must be positive")
    if cfg.min_session_move_to_range_ratio <= 0:
        raise ValueError("min_session_move_to_range_ratio must be positive")
    if cfg.min_momentum_points <= 0:
        raise ValueError("min_momentum_points must be positive")
    if cfg.close_position_long_min <= cfg.close_position_short_max:
        raise ValueError("long close-position threshold must be above short threshold")
