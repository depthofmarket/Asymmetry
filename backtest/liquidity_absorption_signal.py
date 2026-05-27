from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_ABSORPTION_FEATURE_COLUMNS = (
    "absorption_score",
    "event_range_multiple",
    "event_volume_multiple",
    "event_close_position",
    "post_event_extension_points",
    "failed_reentry_points",
    "session_vwap_distance_points",
)


DEFAULT_ABSORPTION_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "liquidity_expansion_side",
    "absorption_pattern",
)


@dataclass(frozen=True)
class LiquidityAbsorptionSignalConfig:
    sweep_lookback_bars: int = 30
    range_lookback_bars: int = 50
    volume_lookback_bars: int = 50
    confirmation_bars: int = 2
    expansion_range_multiple: float = 1.6
    expansion_volume_multiple: float = 1.2
    sweep_buffer_points: float = 0.25
    failure_reentry_points: float = 1.0
    followthrough_tolerance_points: float = 0.5
    event_close_position_short_max: float = 0.55
    event_close_position_long_min: float = 0.45
    min_vwap_distance_points: float = 0.0
    trade_start: str = "09:35"
    trade_end: str = "11:45"


def build_liquidity_absorption_signal_export(
    data: pd.DataFrame,
    *,
    config: LiquidityAbsorptionSignalConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_ABSORPTION_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_ABSORPTION_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_liquidity_absorption_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_liquidity_absorption_signal_frame(
    data: pd.DataFrame,
    *,
    config: LiquidityAbsorptionSignalConfig | None = None,
) -> pd.DataFrame:
    cfg = config or LiquidityAbsorptionSignalConfig()
    _validate_config(cfg)
    df = _base_ohlcv_frame(data)

    bar_range = (df["high"] - df["low"]).clip(lower=0.0)
    true_range = _true_range(df)
    range_ref = true_range.rolling(cfg.range_lookback_bars, min_periods=cfg.range_lookback_bars).median().shift(1)
    volume_ref = df["volume"].rolling(cfg.volume_lookback_bars, min_periods=cfg.volume_lookback_bars).median().shift(1)
    prior_high = df["high"].rolling(cfg.sweep_lookback_bars, min_periods=cfg.sweep_lookback_bars).max().shift(1)
    prior_low = df["low"].rolling(cfg.sweep_lookback_bars, min_periods=cfg.sweep_lookback_bars).min().shift(1)

    range_multiple = _safe_divide(true_range, range_ref)
    volume_multiple = _safe_divide(df["volume"], volume_ref)
    close_position = _safe_divide(df["close"] - df["low"], bar_range).clip(lower=0.0, upper=1.0)

    expansion = (
        range_ref.notna()
        & volume_ref.notna()
        & range_multiple.ge(cfg.expansion_range_multiple)
        & volume_multiple.ge(cfg.expansion_volume_multiple)
    )
    up_sweep = expansion & df["high"].gt(prior_high + cfg.sweep_buffer_points)
    down_sweep = expansion & df["low"].lt(prior_low - cfg.sweep_buffer_points)

    event_up = up_sweep.shift(cfg.confirmation_bars, fill_value=False).astype(bool)
    event_down = down_sweep.shift(cfg.confirmation_bars, fill_value=False).astype(bool)
    event_high = df["high"].shift(cfg.confirmation_bars)
    event_low = df["low"].shift(cfg.confirmation_bars)
    event_close_position = close_position.shift(cfg.confirmation_bars)
    event_range_multiple = range_multiple.shift(cfg.confirmation_bars)
    event_volume_multiple = volume_multiple.shift(cfg.confirmation_bars)

    post_high = df["high"].rolling(cfg.confirmation_bars, min_periods=cfg.confirmation_bars).max()
    post_low = df["low"].rolling(cfg.confirmation_bars, min_periods=cfg.confirmation_bars).min()
    post_extension_up = post_high - event_high
    post_extension_down = event_low - post_low
    reentry_from_high = event_high - df["close"]
    reentry_from_low = df["close"] - event_low

    vwap = _session_vwap(df)
    vwap_distance = df["close"] - vwap
    in_time = _time_window(df["time"], cfg.trade_start, cfg.trade_end)

    short_signal = (
        event_up
        & in_time
        & post_extension_up.le(cfg.followthrough_tolerance_points)
        & reentry_from_high.ge(cfg.failure_reentry_points)
        & event_close_position.le(cfg.event_close_position_short_max)
        & vwap_distance.ge(cfg.min_vwap_distance_points)
    )
    long_signal = (
        event_down
        & in_time
        & post_extension_down.le(cfg.followthrough_tolerance_points)
        & reentry_from_low.ge(cfg.failure_reentry_points)
        & event_close_position.ge(cfg.event_close_position_long_min)
        & vwap_distance.le(-cfg.min_vwap_distance_points)
    )

    score = _absorption_score(
        event_range_multiple=event_range_multiple,
        event_volume_multiple=event_volume_multiple,
        reentry_points=np.where(short_signal, reentry_from_high, reentry_from_low),
        post_extension_points=np.where(short_signal, post_extension_up, post_extension_down),
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
    out["signal_type"] = np.where(signal.ne(0), "liquidity_absorption", "")
    out["absorption_score"] = signed_score.fillna(0.0)
    out["liquidity_expansion_side"] = np.where(long_signal, "down_sweep", np.where(short_signal, "up_sweep", ""))
    out["absorption_pattern"] = np.where(signal.ne(0), "failed_continuation", "")
    out["event_range_multiple"] = event_range_multiple
    out["event_volume_multiple"] = event_volume_multiple
    out["event_close_position"] = event_close_position
    out["post_event_extension_points"] = np.where(short_signal, post_extension_up, np.where(long_signal, post_extension_down, np.nan))
    out["failed_reentry_points"] = np.where(short_signal, reentry_from_high, np.where(long_signal, reentry_from_low, np.nan))
    out["session_vwap_distance_points"] = vwap_distance
    out["vwap_side"] = np.where(vwap_distance.ge(0.0), "above_vwap", "below_vwap")
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


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    parts = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return parts.max(axis=1).clip(lower=0.0)


def _session_vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    dollar_volume = typical * df["volume"]
    session = df["time"].dt.date
    cum_dollar = dollar_volume.groupby(session).cumsum()
    cum_volume = df["volume"].groupby(session).cumsum()
    return _safe_divide(cum_dollar, cum_volume).fillna(df["close"])


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


def _absorption_score(
    *,
    event_range_multiple: pd.Series,
    event_volume_multiple: pd.Series,
    reentry_points: np.ndarray,
    post_extension_points: np.ndarray,
    cfg: LiquidityAbsorptionSignalConfig,
) -> pd.Series:
    range_component = event_range_multiple.clip(lower=0.0).fillna(0.0)
    volume_component = event_volume_multiple.clip(lower=0.0).fillna(0.0)
    reentry_component = pd.Series(reentry_points).clip(lower=0.0).fillna(0.0) / max(cfg.failure_reentry_points, 0.25)
    extension_penalty = pd.Series(post_extension_points).clip(lower=0.0).fillna(0.0) / max(cfg.followthrough_tolerance_points, 0.25)
    score = (range_component + volume_component + reentry_component) / 3.0 - 0.25 * extension_penalty
    return score.clip(lower=0.0)


def _validate_config(cfg: LiquidityAbsorptionSignalConfig) -> None:
    if cfg.sweep_lookback_bars <= 0:
        raise ValueError("sweep_lookback_bars must be positive")
    if cfg.range_lookback_bars <= 0:
        raise ValueError("range_lookback_bars must be positive")
    if cfg.volume_lookback_bars <= 0:
        raise ValueError("volume_lookback_bars must be positive")
    if cfg.confirmation_bars <= 0:
        raise ValueError("confirmation_bars must be positive")
    if cfg.expansion_range_multiple <= 0:
        raise ValueError("expansion_range_multiple must be positive")
    if cfg.expansion_volume_multiple <= 0:
        raise ValueError("expansion_volume_multiple must be positive")
