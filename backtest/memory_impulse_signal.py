from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.event_sampling import add_cusum_event_features
from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_MEMORY_IMPULSE_FEATURE_COLUMNS = (
    "memory_impulse_score",
    "prior_memory_persistence",
    "prior_memory_entropy",
    "prior_memory_complexity",
    "prior_memory_trend_direction",
    "cusum_event_move_atr",
    "cusum_event_move_points",
    "cusum_threshold_points",
    "atr",
)


DEFAULT_MEMORY_IMPULSE_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "memory_impulse_side",
    "memory_impulse_pattern",
    "prior_memory_state",
    "prior_memory_persistence_regime",
    "prior_memory_entropy_regime",
    "prior_memory_complexity_regime",
)


@dataclass(frozen=True)
class MemoryImpulseSignalConfig:
    atr_lookback_bars: int = 78
    cusum_event_atr_multiple: float = 1.0
    cusum_min_threshold_points: float = 1.0
    min_event_move_atr: float = 1.0
    memory_window_bars: int = 156
    memory_min_bars: int = 64
    min_persistence: float = 0.30
    max_entropy: float = 0.95
    max_complexity: float = 0.55
    cooldown_bars: int = 6


def build_memory_impulse_signal_export(
    data: pd.DataFrame,
    *,
    config: MemoryImpulseSignalConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_MEMORY_IMPULSE_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_MEMORY_IMPULSE_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_memory_impulse_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_memory_impulse_signal_frame(
    data: pd.DataFrame,
    *,
    config: MemoryImpulseSignalConfig | None = None,
) -> pd.DataFrame:
    cfg = config or MemoryImpulseSignalConfig()
    _validate_config(cfg)
    df = _base_ohlcv_frame(data)
    df["atr"] = _atr(df, cfg.atr_lookback_bars)
    df = add_cusum_event_features(
        df,
        threshold_atr_multiple=cfg.cusum_event_atr_multiple,
        min_threshold_points=cfg.cusum_min_threshold_points,
    )
    memory = _add_fast_prior_memory_features(df, cfg)

    event_direction = pd.to_numeric(df["cusum_event_direction"], errors="coerce").fillna(0).astype(int)
    event_move_atr = pd.to_numeric(df["cusum_event_move_atr"], errors="coerce")
    event_ready = (
        df["cusum_event"].fillna(False).astype(bool)
        & event_direction.ne(0)
        & event_move_atr.abs().ge(cfg.min_event_move_atr)
    )
    persistent_structured = (
        memory["prior_memory_persistence"].ge(cfg.min_persistence)
        & memory["prior_memory_entropy"].le(cfg.max_entropy)
        & memory["prior_memory_complexity"].le(cfg.max_complexity)
        & memory["prior_memory_trend_direction"].eq(event_direction)
    )
    raw_signal = pd.Series(0.0, index=df.index)
    raw_signal.loc[event_ready & persistent_structured & event_direction.gt(0)] = 1.0
    raw_signal.loc[event_ready & persistent_structured & event_direction.lt(0)] = -1.0
    signal = _apply_cooldown(raw_signal, cfg.cooldown_bars)

    score = _memory_impulse_score(
        event_move_atr=event_move_atr.abs(),
        prior_persistence=memory["prior_memory_persistence"],
        prior_entropy=memory["prior_memory_entropy"],
        prior_complexity=memory["prior_memory_complexity"],
        cfg=cfg,
    )
    signed_score = pd.Series(0.0, index=df.index)
    signed_score.loc[signal.gt(0)] = score.loc[signal.gt(0)]
    signed_score.loc[signal.lt(0)] = -score.loc[signal.lt(0)]

    out = df.copy()
    out["signal"] = signal
    out["signal_type"] = np.where(signal.ne(0), "memory_impulse", "")
    out["memory_impulse_score"] = signed_score.fillna(0.0)
    for col in memory.columns:
        out[col] = memory[col]
    out["memory_impulse_side"] = np.where(signal.gt(0), "up_impulse", np.where(signal.lt(0), "down_impulse", ""))
    out["memory_impulse_pattern"] = np.where(signal.ne(0), "persistent_memory_impulse_continuation", "")
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


def _atr(df: pd.DataFrame, lookback_bars: int) -> pd.Series:
    true_range = _true_range(df)
    return true_range.rolling(int(lookback_bars), min_periods=int(lookback_bars)).mean().shift(1)


def _add_fast_prior_memory_features(df: pd.DataFrame, cfg: MemoryImpulseSignalConfig) -> pd.DataFrame:
    close = pd.to_numeric(df["close"], errors="coerce")
    returns = close.diff()
    prior_returns = returns.shift(1)
    window = int(cfg.memory_window_bars)
    min_bars = int(cfg.memory_min_bars)

    path_length = prior_returns.abs().rolling(window, min_periods=min_bars).sum()
    net_move = close.shift(1) - close.shift(window + 1)
    persistence = (net_move.abs() / path_length.replace(0.0, np.nan)).clip(lower=0.0, upper=1.0)

    positive_share = prior_returns.gt(0).rolling(window, min_periods=min_bars).mean()
    entropy = _binary_entropy(positive_share)

    direction = np.sign(prior_returns).replace(0.0, np.nan).ffill()
    sign_change = direction.ne(direction.shift(1)) & direction.notna() & direction.shift(1).notna()
    complexity = sign_change.astype(float).rolling(window, min_periods=min_bars).mean().clip(lower=0.0, upper=1.0)
    trend_direction = np.sign(net_move).replace(0.0, np.nan)

    persistence_regime = pd.Series("unknown", index=df.index, dtype="object")
    persistence_regime.loc[persistence.notna()] = "neutral_memory"
    persistence_regime.loc[persistence.ge(cfg.min_persistence)] = "persistent_memory"

    entropy_regime = pd.Series("unknown", index=df.index, dtype="object")
    entropy_regime.loc[entropy.notna()] = "neutral_entropy"
    entropy_regime.loc[entropy.le(cfg.max_entropy)] = "structured_entropy"

    complexity_regime = pd.Series("unknown", index=df.index, dtype="object")
    complexity_regime.loc[complexity.notna()] = "neutral_complexity"
    complexity_regime.loc[complexity.le(cfg.max_complexity)] = "low_complexity"

    state = pd.Series("unknown", index=df.index, dtype="object")
    has_memory = persistence.notna() | entropy.notna() | complexity.notna()
    state.loc[has_memory] = "neutral_memory"
    state.loc[
        persistence.ge(cfg.min_persistence)
        & entropy.le(cfg.max_entropy)
        & complexity.le(cfg.max_complexity)
    ] = "persistent_structured_memory"

    return pd.DataFrame(
        {
            "prior_memory_persistence": persistence,
            "prior_memory_entropy": entropy,
            "prior_memory_complexity": complexity,
            "prior_memory_trend_direction": trend_direction,
            "prior_memory_state": state,
            "prior_memory_persistence_regime": persistence_regime,
            "prior_memory_entropy_regime": entropy_regime,
            "prior_memory_complexity_regime": complexity_regime,
        },
        index=df.index,
    )


def _binary_entropy(probability: pd.Series) -> pd.Series:
    p = pd.to_numeric(probability, errors="coerce").clip(lower=0.0, upper=1.0)
    q = 1.0 - p
    with np.errstate(divide="ignore", invalid="ignore"):
        entropy = -(p * np.log2(p) + q * np.log2(q))
    return entropy.replace([np.inf, -np.inf], np.nan).fillna(0.0).where(p.notna(), np.nan)


def _apply_cooldown(raw_signal: pd.Series, cooldown_bars: int) -> pd.Series:
    signal = pd.Series(0.0, index=raw_signal.index)
    cooldown_bars = max(0, int(cooldown_bars))
    last_signal_idx: int | None = None
    for idx, value in raw_signal.items():
        signed_value = float(value)
        if signed_value == 0.0:
            continue
        if last_signal_idx is not None and int(idx) - last_signal_idx <= cooldown_bars:
            continue
        signal.loc[idx] = signed_value
        last_signal_idx = int(idx)
    return signal


def _memory_impulse_score(
    *,
    event_move_atr: pd.Series,
    prior_persistence: pd.Series,
    prior_entropy: pd.Series,
    prior_complexity: pd.Series,
    cfg: MemoryImpulseSignalConfig,
) -> pd.Series:
    event_component = (event_move_atr / max(cfg.min_event_move_atr, 1e-9)).clip(lower=0.0, upper=3.0) / 3.0
    persistence_component = (
        (prior_persistence - cfg.min_persistence) / max(1.0 - cfg.min_persistence, 1e-9)
    ).clip(lower=0.0, upper=1.0)
    entropy_component = ((cfg.max_entropy - prior_entropy) / max(cfg.max_entropy, 1e-9)).clip(lower=0.0, upper=1.0)
    complexity_component = (
        (cfg.max_complexity - prior_complexity) / max(cfg.max_complexity, 1e-9)
    ).clip(lower=0.0, upper=1.0)
    score = (event_component + persistence_component + entropy_component + complexity_component) / 4.0
    return score.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def _validate_config(cfg: MemoryImpulseSignalConfig) -> None:
    if cfg.atr_lookback_bars <= 1:
        raise ValueError("atr_lookback_bars must be greater than 1")
    if cfg.cusum_event_atr_multiple <= 0:
        raise ValueError("cusum_event_atr_multiple must be positive")
    if cfg.cusum_min_threshold_points < 0:
        raise ValueError("cusum_min_threshold_points must be non-negative")
    if cfg.min_event_move_atr <= 0:
        raise ValueError("min_event_move_atr must be positive")
    if cfg.memory_window_bars <= 1 or cfg.memory_min_bars <= 1:
        raise ValueError("memory windows must be greater than 1")
    if cfg.memory_min_bars > cfg.memory_window_bars:
        raise ValueError("memory_min_bars must be <= memory_window_bars")
    if not 0.0 <= cfg.min_persistence <= 1.0:
        raise ValueError("min_persistence must be between 0 and 1")
    if not 0.0 <= cfg.max_entropy <= 1.0:
        raise ValueError("max_entropy must be between 0 and 1")
    if not 0.0 <= cfg.max_complexity <= 1.0:
        raise ValueError("max_complexity must be between 0 and 1")
    if cfg.cooldown_bars < 0:
        raise ValueError("cooldown_bars must be non-negative")
