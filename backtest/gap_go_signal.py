from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_GAP_GO_FEATURE_COLUMNS = (
    "gap_go_score",
    "gap_points",
    "abs_gap_points",
    "gap_to_prior_range_ratio",
    "opening_range_points",
    "breakout_distance_points",
    "event_close_position",
    "session_vwap_distance_points",
)


DEFAULT_GAP_GO_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "gap_direction",
    "gap_hold_status",
    "opening_range_breakout_side",
    "gap_go_pattern",
)


@dataclass(frozen=True)
class GapGoSignalConfig:
    opening_range_minutes: int = 15
    min_abs_gap_points: float = 20.0
    min_gap_to_prior_range_ratio: float = 0.15
    gap_hold_tolerance_points: float = 2.0
    breakout_buffer_points: float = 0.25
    close_position_long_min: float = 0.70
    close_position_short_max: float = 0.30
    min_vwap_distance_points: float = 0.0
    trade_start: str = "09:45"
    trade_end: str = "11:00"
    rth_start: str = "09:30"
    rth_end: str = "16:00"


def build_gap_go_signal_export(
    data: pd.DataFrame,
    *,
    config: GapGoSignalConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_GAP_GO_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_GAP_GO_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_gap_go_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_gap_go_signal_frame(
    data: pd.DataFrame,
    *,
    config: GapGoSignalConfig | None = None,
) -> pd.DataFrame:
    cfg = config or GapGoSignalConfig()
    _validate_config(cfg)
    df = _base_ohlcv_frame(data)

    session = df["time"].dt.date
    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    rth_start_min = _parse_hhmm(cfg.rth_start)
    rth_end_min = _parse_hhmm(cfg.rth_end)
    opening_end_min = rth_start_min + int(cfg.opening_range_minutes)
    rth_mask = minutes.ge(rth_start_min) & minutes.le(rth_end_min)
    opening_mask = minutes.ge(rth_start_min) & minutes.lt(opening_end_min)

    rth = df.loc[rth_mask].copy()
    opening_rth = df.loc[rth_mask & opening_mask].copy()
    session_stats = _session_stats(rth, opening_rth)
    stats_by_date = session_stats.set_index("session")
    prior_stats = session_stats.shift(1).set_index(session_stats["session"])

    prior_close = session.map(prior_stats["prior_close"])
    prior_range = session.map(prior_stats["prior_range"])
    rth_open = session.map(stats_by_date["rth_open"])
    opening_high = session.map(stats_by_date["opening_high"])
    opening_low = session.map(stats_by_date["opening_low"])

    gap_points = rth_open - prior_close
    abs_gap_points = gap_points.abs()
    gap_to_prior_range = _safe_divide(abs_gap_points, prior_range)
    gap_up = gap_points.ge(cfg.min_abs_gap_points) & gap_to_prior_range.ge(cfg.min_gap_to_prior_range_ratio)
    gap_down = gap_points.le(-cfg.min_abs_gap_points) & gap_to_prior_range.ge(cfg.min_gap_to_prior_range_ratio)

    opening_held_up = opening_low.ge(prior_close - cfg.gap_hold_tolerance_points)
    opening_held_down = opening_high.le(prior_close + cfg.gap_hold_tolerance_points)
    opening_range_points = opening_high - opening_low
    bar_range = (df["high"] - df["low"]).clip(lower=0.0)
    close_position = _safe_divide(df["close"] - df["low"], bar_range).clip(lower=0.0, upper=1.0)
    vwap = _session_vwap(df)
    vwap_distance = df["close"] - vwap
    in_time = _time_window(df["time"], cfg.trade_start, cfg.trade_end)
    after_opening_range = minutes.ge(opening_end_min)

    break_up = df["high"].gt(opening_high + cfg.breakout_buffer_points)
    break_down = df["low"].lt(opening_low - cfg.breakout_buffer_points)
    long_candidate = (
        rth_mask
        & after_opening_range
        & in_time
        & gap_up.fillna(False)
        & opening_held_up.fillna(False)
        & break_up.fillna(False)
        & close_position.ge(cfg.close_position_long_min)
        & vwap_distance.ge(cfg.min_vwap_distance_points)
    )
    short_candidate = (
        rth_mask
        & after_opening_range
        & in_time
        & gap_down.fillna(False)
        & opening_held_down.fillna(False)
        & break_down.fillna(False)
        & close_position.le(cfg.close_position_short_max)
        & vwap_distance.le(-cfg.min_vwap_distance_points)
    )

    long_signal = _first_true_per_session(long_candidate, session)
    short_signal = _first_true_per_session(short_candidate, session)
    breakout_distance = np.where(
        long_signal,
        df["high"] - opening_high,
        np.where(short_signal, opening_low - df["low"], np.nan),
    )
    score = _gap_go_score(
        abs_gap_points=abs_gap_points,
        prior_range=prior_range,
        breakout_distance_points=breakout_distance,
        close_position=np.where(long_signal, close_position, 1.0 - close_position),
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
    out["signal_type"] = np.where(signal.ne(0), "gap_go", "")
    out["gap_go_score"] = signed_score.fillna(0.0)
    out["gap_points"] = gap_points
    out["abs_gap_points"] = abs_gap_points
    out["gap_to_prior_range_ratio"] = gap_to_prior_range
    out["opening_range_points"] = opening_range_points
    out["breakout_distance_points"] = breakout_distance
    out["event_close_position"] = close_position
    out["session_vwap_distance_points"] = vwap_distance
    out["vwap_side"] = np.where(vwap_distance.ge(0.0), "above_vwap", "below_vwap")
    out["gap_direction"] = np.where(gap_up, "gap_up", np.where(gap_down, "gap_down", "none"))
    out["gap_hold_status"] = np.where(
        gap_up & opening_held_up,
        "held_up_gap",
        np.where(gap_down & opening_held_down, "held_down_gap", "not_held_or_no_gap"),
    )
    out["opening_range_breakout_side"] = np.where(long_signal, "up_breakout", np.where(short_signal, "down_breakout", ""))
    out["gap_go_pattern"] = np.where(signal.ne(0), "gap_hold_opening_range_breakout", "")
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


def _session_stats(rth: pd.DataFrame, opening_rth: pd.DataFrame) -> pd.DataFrame:
    if rth.empty:
        return pd.DataFrame(
            columns=["session", "rth_open", "prior_close", "prior_range", "opening_high", "opening_low"]
        )
    session = rth["time"].dt.date
    grouped = rth.groupby(session, sort=True)
    stats = grouped.agg(
        rth_open=("open", "first"),
        prior_close=("close", "last"),
        session_high=("high", "max"),
        session_low=("low", "min"),
    ).reset_index(names="session")
    stats["prior_range"] = stats["session_high"] - stats["session_low"]
    return stats.loc[:, ["session", "rth_open", "prior_close", "prior_range"]].merge(
        _opening_range_stats(opening_rth),
        on="session",
        how="left",
    )


def _opening_range_stats(rth: pd.DataFrame) -> pd.DataFrame:
    session = rth["time"].dt.date
    return rth.groupby(session, sort=True).agg(
        opening_high=("high", "max"),
        opening_low=("low", "min"),
    ).reset_index(names="session")


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


def _first_true_per_session(mask: pd.Series, session: pd.Series) -> pd.Series:
    active = mask.fillna(False).astype(bool)
    counts = active.groupby(session).cumsum()
    return active & counts.eq(1)


def _gap_go_score(
    *,
    abs_gap_points: pd.Series,
    prior_range: pd.Series,
    breakout_distance_points: np.ndarray,
    close_position: np.ndarray,
    cfg: GapGoSignalConfig,
) -> pd.Series:
    gap_component = _safe_divide(abs_gap_points, prior_range).clip(lower=0.0).fillna(0.0)
    breakout_component = pd.Series(breakout_distance_points).clip(lower=0.0).fillna(0.0) / max(
        cfg.breakout_buffer_points,
        0.25,
    )
    close_component = pd.Series(close_position).clip(lower=0.0, upper=1.0).fillna(0.0)
    score = (gap_component + breakout_component + close_component) / 3.0
    return score.clip(lower=0.0)


def _validate_config(cfg: GapGoSignalConfig) -> None:
    if cfg.opening_range_minutes <= 0:
        raise ValueError("opening_range_minutes must be positive")
    if cfg.min_abs_gap_points <= 0:
        raise ValueError("min_abs_gap_points must be positive")
    if cfg.min_gap_to_prior_range_ratio <= 0:
        raise ValueError("min_gap_to_prior_range_ratio must be positive")
    if cfg.breakout_buffer_points <= 0:
        raise ValueError("breakout_buffer_points must be positive")
