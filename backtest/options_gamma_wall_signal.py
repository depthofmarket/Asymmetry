from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.options_flow import add_options_flow_features
from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_OPTIONS_GAMMA_WALL_FEATURE_COLUMNS = (
    "options_gamma_wall_score",
    "options_gamma_wall_current_distance_points",
    "options_gamma_wall_abs_distance_points",
    "options_flow_age_hours",
    "options_gamma_wall_strike",
    "options_net_gex",
    "options_abs_gex",
    "options_total_oi",
    "options_call_wall_distance_current_points",
    "options_put_wall_distance_current_points",
)


DEFAULT_OPTIONS_GAMMA_WALL_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "options_gamma_environment",
    "options_gex_regime",
    "options_gamma_wall_role",
    "options_call_wall_role",
    "options_put_wall_role",
    "options_flow_age_bucket",
    "gamma_wall_side",
    "options_gamma_wall_pattern",
)


@dataclass(frozen=True)
class OptionsGammaWallSignalConfig:
    min_abs_wall_distance_points: float = 10.0
    max_abs_wall_distance_points: float = 100.0
    max_options_age_days: float = 120.0
    cooldown_bars: int = 15


def build_options_gamma_wall_signal_export(
    data: pd.DataFrame,
    options_flow_features: pd.DataFrame | str,
    *,
    config: OptionsGammaWallSignalConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_OPTIONS_GAMMA_WALL_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_OPTIONS_GAMMA_WALL_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_options_gamma_wall_signal_frame(
        data,
        options_flow_features,
        config=config,
    )
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_options_gamma_wall_signal_frame(
    data: pd.DataFrame,
    options_flow_features: pd.DataFrame | str,
    *,
    config: OptionsGammaWallSignalConfig | None = None,
) -> pd.DataFrame:
    cfg = config or OptionsGammaWallSignalConfig()
    _validate_config(cfg)
    df = _base_ohlcv_frame(data)
    df = add_options_flow_features(df, options_flow_features)

    close = pd.to_numeric(df["close"], errors="coerce")
    gamma_wall = _numeric_col(df, "options_gamma_wall_strike")
    call_wall = _numeric_col(df, "options_call_wall_strike")
    put_wall = _numeric_col(df, "options_put_wall_strike")

    current_distance = gamma_wall - close
    abs_distance = current_distance.abs()
    call_wall_current_distance = call_wall - close
    put_wall_current_distance = close - put_wall

    age_hours = _options_flow_age_hours(df)
    positive_gamma = _string_col(df, "options_gamma_environment").eq("positive_gamma")
    pinning_wall = _string_col(df, "options_gamma_wall_role").eq("pinning_wall")
    fresh_enough = age_hours.le(float(cfg.max_options_age_days) * 24.0)
    in_distance_band = (
        abs_distance.ge(float(cfg.min_abs_wall_distance_points))
        & abs_distance.le(float(cfg.max_abs_wall_distance_points))
    )

    raw_signal = pd.Series(0.0, index=df.index)
    raw_signal.loc[
        positive_gamma
        & pinning_wall
        & fresh_enough
        & in_distance_band
        & current_distance.gt(0.0)
    ] = 1.0
    raw_signal.loc[
        positive_gamma
        & pinning_wall
        & fresh_enough
        & in_distance_band
        & current_distance.lt(0.0)
    ] = -1.0
    signal = _apply_cooldown(raw_signal, cfg.cooldown_bars)

    distance_score = (abs_distance / float(cfg.max_abs_wall_distance_points)).clip(lower=0.0, upper=1.0)
    signed_score = pd.Series(0.0, index=df.index)
    signed_score.loc[signal.gt(0)] = distance_score.loc[signal.gt(0)]
    signed_score.loc[signal.lt(0)] = -distance_score.loc[signal.lt(0)]

    out = df.copy()
    out["signal"] = signal
    out["signal_type"] = np.where(signal.ne(0), "options_gamma_wall_reversion", "")
    out["options_gamma_wall_score"] = signed_score.fillna(0.0)
    out["options_gamma_wall_current_distance_points"] = current_distance
    out["options_gamma_wall_abs_distance_points"] = abs_distance
    out["options_call_wall_distance_current_points"] = call_wall_current_distance
    out["options_put_wall_distance_current_points"] = put_wall_current_distance
    out["options_flow_age_hours"] = age_hours
    out["options_flow_age_bucket"] = _age_bucket(age_hours)
    out["gamma_wall_side"] = np.select(
        [
            current_distance.gt(0.0),
            current_distance.lt(0.0),
            current_distance.eq(0.0),
        ],
        ["below_wall", "above_wall", "at_wall"],
        default="unknown",
    )
    out["options_gamma_wall_pattern"] = np.where(
        signal.ne(0),
        "positive_gamma_pin_reversion",
        "",
    )
    out["vwap_side"] = _vwap_side(out)
    _ensure_default_columns(out)
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


def _numeric_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(np.nan, index=df.index, dtype="float64")


def _string_col(df: pd.DataFrame, col: str) -> pd.Series:
    if col in df.columns:
        return df[col].fillna("").astype(str)
    return pd.Series("", index=df.index, dtype="object")


def _options_flow_age_hours(df: pd.DataFrame) -> pd.Series:
    if "options_available_time" not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype="float64")
    available = pd.to_datetime(df["options_available_time"], errors="coerce")
    bar_time = pd.to_datetime(df["time"], errors="coerce")
    age = (bar_time - available).dt.total_seconds() / 3600.0
    return pd.to_numeric(age, errors="coerce")


def _age_bucket(age_hours: pd.Series) -> pd.Series:
    age = pd.to_numeric(age_hours, errors="coerce")
    buckets = np.select(
        [
            age.le(24.0),
            age.le(7.0 * 24.0),
            age.le(30.0 * 24.0),
            age.le(120.0 * 24.0),
            age.gt(120.0 * 24.0),
        ],
        ["age_0_1d", "age_1_7d", "age_7_30d", "age_30_120d", "age_gt_120d"],
        default="unknown",
    )
    return pd.Series(buckets, index=age_hours.index)


def _vwap_side(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    dollar_volume = typical * df["volume"]
    session = pd.to_datetime(df["time"]).dt.date
    cum_dollar = dollar_volume.groupby(session).cumsum()
    cum_volume = df["volume"].groupby(session).cumsum().replace(0.0, np.nan)
    vwap = (cum_dollar / cum_volume).replace([np.inf, -np.inf], np.nan).fillna(df["close"])
    return pd.Series(np.where(df["close"].ge(vwap), "above_vwap", "below_vwap"), index=df.index)


def _apply_cooldown(raw_signal: pd.Series, cooldown_bars: int) -> pd.Series:
    signal = pd.Series(0.0, index=raw_signal.index)
    cooldown = max(0, int(cooldown_bars))
    last_index: int | None = None
    last_direction = 0.0
    for pos, value in enumerate(pd.to_numeric(raw_signal, errors="coerce").fillna(0.0).to_numpy()):
        if value == 0.0:
            continue
        direction_changed = value != last_direction
        cooled_down = last_index is None or (pos - last_index) > cooldown
        if direction_changed or cooled_down:
            signal.iloc[pos] = value
            last_index = pos
            last_direction = value
    return signal


def _ensure_default_columns(df: pd.DataFrame) -> None:
    for col in DEFAULT_OPTIONS_GAMMA_WALL_FEATURE_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    for col in DEFAULT_OPTIONS_GAMMA_WALL_CONTEXT_COLUMNS:
        if col not in df.columns:
            df[col] = ""


def _validate_config(cfg: OptionsGammaWallSignalConfig) -> None:
    if cfg.min_abs_wall_distance_points <= 0:
        raise ValueError("min_abs_wall_distance_points must be positive")
    if cfg.max_abs_wall_distance_points <= cfg.min_abs_wall_distance_points:
        raise ValueError("max_abs_wall_distance_points must exceed min_abs_wall_distance_points")
    if cfg.max_options_age_days <= 0:
        raise ValueError("max_options_age_days must be positive")
    if cfg.cooldown_bars < 0:
        raise ValueError("cooldown_bars must be non-negative")
