from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backtest.market_memory import estimate_hurst_rs
from backtest.markov_regime import add_markov_regime_features


VOLATILITY_STATE_FEATURE_COLUMNS = [
    "volatility_return_points",
    "volatility_log_return",
    "volatility_abs_log_return",
    "volatility_true_range_points",
    "volatility_true_range_pct",
    "realized_vol_short",
    "realized_vol_long",
    "realized_vol_ratio",
    "volatility_atr_short_points",
    "volatility_atr_long_points",
    "volatility_range_ratio",
    "volatility_compression_state",
    "volatility_vol_of_vol",
    "volatility_vol_of_vol_ratio",
    "volatility_vol_of_vol_state",
    "volatility_jump_threshold",
    "volatility_range_jump_threshold",
    "volatility_jump_score",
    "volatility_jump_event",
    "volatility_roughness_hurst",
    "volatility_roughness_state",
    "volatility_state",
]


@dataclass(frozen=True)
class VolatilityStateConfig:
    short_window_bars: int = 20
    long_window_bars: int = 78
    min_short_bars: int = 10
    min_long_bars: int = 30
    compression_ratio_threshold: float = 0.70
    expansion_ratio_threshold: float = 1.35
    vol_of_vol_window_bars: int = 78
    vol_of_vol_reference_bars: int = 156
    vol_of_vol_high_ratio: float = 1.50
    jump_window_bars: int = 156
    jump_min_bars: int = 50
    jump_quantile: float = 0.99
    jump_score_threshold: float = 1.0
    roughness_window_bars: int = 156
    roughness_min_bars: int = 64
    roughness_recompute_every_bars: int = 6
    rough_hurst_threshold: float = 0.35
    persistent_hurst_threshold: float = 0.60
    include_markov_regime: bool = True
    markov_n_states: int = 3
    markov_calibration_bars: int = 78
    markov_min_calibration_bars: int = 30
    markov_refit_every_bars: int = 12
    markov_transition_smoothing: float = 0.1
    markov_min_std: float = 1e-8
    markov_min_state_observations: int = 3
    markov_volatility_method: str = "range_close"
    markov_initial_prob_mode: str = "uniform"


def add_volatility_state_features(
    data: pd.DataFrame,
    *,
    config: VolatilityStateConfig | None = None,
) -> pd.DataFrame:
    """
    Append point-in-time volatility context features.

    Each row uses only completed bars up to and including that row. A strategy
    that enters on the next bar can consume these columns without seeing future
    volatility. Jump thresholds are stricter: they are estimated from prior rows
    only, then compared with the current completed bar.
    """

    cfg = config or VolatilityStateConfig()
    _validate_config(cfg)
    out = _base_ohlcv_frame(data)

    close = pd.to_numeric(out["close"], errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        log_close = np.log(close.replace(0.0, np.nan))
    log_return = log_close.diff().replace([np.inf, -np.inf], np.nan)
    return_points = close.diff()
    true_range = _true_range(out)
    true_range_pct = (true_range / close.abs().replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)

    out["volatility_return_points"] = return_points
    out["volatility_log_return"] = log_return
    out["volatility_abs_log_return"] = log_return.abs()
    out["volatility_true_range_points"] = true_range
    out["volatility_true_range_pct"] = true_range_pct

    out["realized_vol_short"] = _rolling_std(log_return, cfg.short_window_bars, cfg.min_short_bars)
    out["realized_vol_long"] = _rolling_std(log_return, cfg.long_window_bars, cfg.min_long_bars)
    out["realized_vol_ratio"] = _safe_divide(out["realized_vol_short"], out["realized_vol_long"])
    out["volatility_atr_short_points"] = true_range.rolling(
        int(cfg.short_window_bars),
        min_periods=int(cfg.min_short_bars),
    ).mean()
    out["volatility_atr_long_points"] = true_range.rolling(
        int(cfg.long_window_bars),
        min_periods=int(cfg.min_long_bars),
    ).mean()
    out["volatility_range_ratio"] = _safe_divide(out["volatility_atr_short_points"], out["volatility_atr_long_points"])
    out["volatility_compression_state"] = _label_compression_state(
        out["realized_vol_ratio"],
        out["volatility_range_ratio"],
        cfg,
    )

    out["volatility_vol_of_vol"] = pd.to_numeric(out["realized_vol_short"], errors="coerce").rolling(
        int(cfg.vol_of_vol_window_bars),
        min_periods=max(3, min(int(cfg.vol_of_vol_window_bars), int(cfg.min_long_bars))),
    ).std()
    vol_of_vol_ref = out["volatility_vol_of_vol"].rolling(
        int(cfg.vol_of_vol_reference_bars),
        min_periods=max(3, min(int(cfg.vol_of_vol_reference_bars), int(cfg.min_long_bars))),
    ).median()
    out["volatility_vol_of_vol_ratio"] = _safe_divide(out["volatility_vol_of_vol"], vol_of_vol_ref)
    out["volatility_vol_of_vol_state"] = _label_vol_of_vol_state(out["volatility_vol_of_vol_ratio"], cfg)

    prior_abs_return = pd.to_numeric(out["volatility_abs_log_return"], errors="coerce").shift(1)
    prior_range_pct = pd.to_numeric(out["volatility_true_range_pct"], errors="coerce").shift(1)
    out["volatility_jump_threshold"] = prior_abs_return.rolling(
        int(cfg.jump_window_bars),
        min_periods=int(cfg.jump_min_bars),
    ).quantile(float(cfg.jump_quantile))
    out["volatility_range_jump_threshold"] = prior_range_pct.rolling(
        int(cfg.jump_window_bars),
        min_periods=int(cfg.jump_min_bars),
    ).quantile(float(cfg.jump_quantile))
    return_jump_score = _safe_divide(out["volatility_abs_log_return"], out["volatility_jump_threshold"])
    range_jump_score = _safe_divide(out["volatility_true_range_pct"], out["volatility_range_jump_threshold"])
    out["volatility_jump_score"] = pd.concat([return_jump_score, range_jump_score], axis=1).max(axis=1, skipna=True)
    out["volatility_jump_event"] = (
        pd.to_numeric(out["volatility_jump_score"], errors="coerce").ge(float(cfg.jump_score_threshold))
        & out["volatility_jump_threshold"].notna()
    )

    out["volatility_roughness_hurst"] = _rolling_sparse(
        pd.to_numeric(out["volatility_abs_log_return"], errors="coerce").to_numpy(dtype=float),
        window=cfg.roughness_window_bars,
        min_bars=cfg.roughness_min_bars,
        recompute_every=cfg.roughness_recompute_every_bars,
        func=estimate_hurst_rs,
    ).to_numpy()
    out["volatility_roughness_state"] = _label_roughness_state(out["volatility_roughness_hurst"], cfg)

    if cfg.include_markov_regime and "markov_state_label" not in out.columns:
        out = add_markov_regime_features(
            out,
            n_states=cfg.markov_n_states,
            calibration_bars=cfg.markov_calibration_bars,
            min_calibration_bars=cfg.markov_min_calibration_bars,
            refit_every_bars=cfg.markov_refit_every_bars,
            smoothing=cfg.markov_transition_smoothing,
            min_std=cfg.markov_min_std,
            min_state_observations=cfg.markov_min_state_observations,
            volatility_method=cfg.markov_volatility_method,
            initial_prob_mode=cfg.markov_initial_prob_mode,
        )

    out["volatility_state"] = _label_composite_state(out)
    return out


def _base_ohlcv_frame(data: pd.DataFrame) -> pd.DataFrame:
    required = ["time", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in data.columns]
    if missing:
        raise ValueError(f"volatility state requires columns: {missing}")
    df = data.loc[:, [col for col in data.columns]].copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time", "open", "high", "low", "close", "volume"])
    return df.sort_values("time").reset_index(drop=True)


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = pd.to_numeric(df["close"], errors="coerce").shift(1)
    parts = pd.concat(
        [
            pd.to_numeric(df["high"], errors="coerce") - pd.to_numeric(df["low"], errors="coerce"),
            (pd.to_numeric(df["high"], errors="coerce") - prev_close).abs(),
            (pd.to_numeric(df["low"], errors="coerce") - prev_close).abs(),
        ],
        axis=1,
    )
    return parts.max(axis=1).clip(lower=0.0)


def _rolling_std(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rolling(int(window), min_periods=int(min_periods)).std()


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce")
    den = pd.to_numeric(denominator, errors="coerce")
    with np.errstate(divide="ignore", invalid="ignore"):
        out = num / den.replace(0.0, np.nan)
    return out.replace([np.inf, -np.inf], np.nan)


def _label_compression_state(
    realized_ratio: pd.Series,
    range_ratio: pd.Series,
    cfg: VolatilityStateConfig,
) -> pd.Series:
    rv = pd.to_numeric(realized_ratio, errors="coerce")
    rr = pd.to_numeric(range_ratio, errors="coerce")
    state = pd.Series("unknown", index=rv.index, dtype="object")
    known = rv.notna() | rr.notna()
    compressed = rv.le(cfg.compression_ratio_threshold) & rr.le(cfg.compression_ratio_threshold)
    expanded = rv.ge(cfg.expansion_ratio_threshold) | rr.ge(cfg.expansion_ratio_threshold)
    state.loc[known] = "normal_volatility"
    state.loc[compressed] = "compressed_volatility"
    state.loc[expanded] = "expanded_volatility"
    return state


def _label_vol_of_vol_state(ratio: pd.Series, cfg: VolatilityStateConfig) -> pd.Series:
    value = pd.to_numeric(ratio, errors="coerce")
    state = pd.Series("unknown", index=value.index, dtype="object")
    state.loc[value.notna()] = "stable_volatility_of_volatility"
    state.loc[value.ge(float(cfg.vol_of_vol_high_ratio))] = "unstable_volatility_of_volatility"
    return state


def _label_roughness_state(hurst: pd.Series, cfg: VolatilityStateConfig) -> pd.Series:
    value = pd.to_numeric(hurst, errors="coerce")
    state = pd.Series("unknown", index=value.index, dtype="object")
    state.loc[value.notna()] = "neutral_volatility_memory"
    state.loc[value.le(float(cfg.rough_hurst_threshold))] = "rough_volatility_memory"
    state.loc[value.ge(float(cfg.persistent_hurst_threshold))] = "persistent_volatility_memory"
    return state


def _label_composite_state(df: pd.DataFrame) -> pd.Series:
    state = pd.Series("unknown", index=df.index, dtype="object")
    known = (
        df["volatility_compression_state"].ne("unknown")
        | df["volatility_vol_of_vol_state"].ne("unknown")
        | df["volatility_roughness_state"].ne("unknown")
    )
    state.loc[known] = "normal_volatility_context"
    state.loc[df["volatility_compression_state"].eq("compressed_volatility")] = "compressed_volatility_context"
    state.loc[df["volatility_compression_state"].eq("expanded_volatility")] = "expanded_volatility_context"
    if "markov_state_label" in df.columns:
        state.loc[df["markov_state_label"].eq("high_vol")] = "high_markov_volatility_context"
    state.loc[df["volatility_vol_of_vol_state"].eq("unstable_volatility_of_volatility")] = "unstable_volatility_context"
    state.loc[df["volatility_roughness_state"].eq("rough_volatility_memory")] = "rough_volatility_context"
    state.loc[df["volatility_jump_event"].fillna(False)] = "jump_volatility_context"
    return state


def _rolling_sparse(
    values: np.ndarray,
    *,
    window: int,
    min_bars: int,
    recompute_every: int,
    func,
) -> pd.Series:
    arr = np.asarray(values, dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)
    last_value = np.nan
    recompute_every = max(1, int(recompute_every))
    for idx in range(len(arr)):
        if idx + 1 < int(min_bars):
            continue
        if (idx + 1 - int(min_bars)) % recompute_every == 0 or not np.isfinite(last_value):
            start = max(0, idx + 1 - int(window))
            sample = arr[start : idx + 1]
            last_value = float(func(sample))
        out[idx] = last_value
    return pd.Series(out)


def _validate_config(cfg: VolatilityStateConfig) -> None:
    if cfg.short_window_bars <= 1 or cfg.long_window_bars <= 1:
        raise ValueError("volatility windows must be greater than 1")
    if cfg.short_window_bars >= cfg.long_window_bars:
        raise ValueError("short_window_bars must be less than long_window_bars")
    if cfg.min_short_bars <= 1 or cfg.min_long_bars <= 1:
        raise ValueError("minimum volatility windows must be greater than 1")
    if cfg.min_short_bars > cfg.short_window_bars:
        raise ValueError("min_short_bars must be <= short_window_bars")
    if cfg.min_long_bars > cfg.long_window_bars:
        raise ValueError("min_long_bars must be <= long_window_bars")
    if cfg.compression_ratio_threshold <= 0.0:
        raise ValueError("compression_ratio_threshold must be positive")
    if cfg.expansion_ratio_threshold <= cfg.compression_ratio_threshold:
        raise ValueError("expansion_ratio_threshold must exceed compression_ratio_threshold")
    if cfg.vol_of_vol_window_bars <= 1 or cfg.vol_of_vol_reference_bars <= 1:
        raise ValueError("vol-of-vol windows must be greater than 1")
    if cfg.vol_of_vol_high_ratio <= 0.0:
        raise ValueError("vol_of_vol_high_ratio must be positive")
    if cfg.jump_window_bars <= 1 or cfg.jump_min_bars <= 1:
        raise ValueError("jump windows must be greater than 1")
    if cfg.jump_min_bars > cfg.jump_window_bars:
        raise ValueError("jump_min_bars must be <= jump_window_bars")
    if not 0.0 < cfg.jump_quantile < 1.0:
        raise ValueError("jump_quantile must be between 0 and 1")
    if cfg.jump_score_threshold <= 0.0:
        raise ValueError("jump_score_threshold must be positive")
    if cfg.roughness_window_bars <= 1 or cfg.roughness_min_bars <= 1:
        raise ValueError("roughness windows must be greater than 1")
    if cfg.roughness_min_bars > cfg.roughness_window_bars:
        raise ValueError("roughness_min_bars must be <= roughness_window_bars")
    if cfg.roughness_recompute_every_bars <= 0:
        raise ValueError("roughness_recompute_every_bars must be positive")
    if not 0.0 <= cfg.rough_hurst_threshold <= 1.0:
        raise ValueError("rough_hurst_threshold must be between 0 and 1")
    if not 0.0 <= cfg.persistent_hurst_threshold <= 1.0:
        raise ValueError("persistent_hurst_threshold must be between 0 and 1")
    if cfg.rough_hurst_threshold >= cfg.persistent_hurst_threshold:
        raise ValueError("rough_hurst_threshold must be less than persistent_hurst_threshold")
    if cfg.markov_n_states < 2:
        raise ValueError("markov_n_states must be at least 2")
