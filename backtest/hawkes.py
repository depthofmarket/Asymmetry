from __future__ import annotations

import numpy as np
import pandas as pd


def hawkes_process(data: pd.Series, kappa: float) -> pd.Series:
    """Compute the exponentially decaying Hawkes-style process from a series."""
    kappa = float(kappa)
    if kappa <= 0.0:
        raise ValueError("kappa must be positive")

    alpha = np.exp(-kappa)
    arr = pd.to_numeric(data, errors="coerce").to_numpy(dtype=float)
    out = np.full(len(arr), np.nan, dtype=float)

    for idx in range(1, len(arr)):
        value = arr[idx]
        if not np.isfinite(value):
            continue
        if not np.isfinite(out[idx - 1]):
            out[idx] = value
        else:
            out[idx] = out[idx - 1] * alpha + value

    return pd.Series(out * kappa, index=data.index)


def _log_atr(data: pd.DataFrame, lookback_bars: int, min_periods: int) -> pd.Series:
    high = np.log(pd.to_numeric(data["high"], errors="coerce"))
    low = np.log(pd.to_numeric(data["low"], errors="coerce"))
    close = np.log(pd.to_numeric(data["close"], errors="coerce"))
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(window=lookback_bars, min_periods=min_periods).mean()


def _hawkes_momentum_signal(close: pd.Series, hawkes_vol: pd.Series, q_low: pd.Series, q_high: pd.Series) -> pd.Series:
    signal = np.zeros(len(close), dtype=float)
    close_arr = pd.to_numeric(close, errors="coerce").to_numpy(dtype=float)
    vol = pd.to_numeric(hawkes_vol, errors="coerce").to_numpy(dtype=float)
    low = pd.to_numeric(q_low, errors="coerce").to_numpy(dtype=float)
    high = pd.to_numeric(q_high, errors="coerce").to_numpy(dtype=float)

    last_below = -1
    current_signal = 0.0
    for idx in range(1, len(signal)):
        if np.isfinite(vol[idx]) and np.isfinite(low[idx]) and vol[idx] < low[idx]:
            last_below = idx
            current_signal = 0.0

        crossed_high = (
            np.isfinite(vol[idx])
            and np.isfinite(high[idx])
            and np.isfinite(vol[idx - 1])
            and np.isfinite(high[idx - 1])
            and vol[idx] > high[idx]
            and vol[idx - 1] <= high[idx - 1]
        )
        if crossed_high and last_below > 0 and np.isfinite(close_arr[idx]) and np.isfinite(close_arr[last_below]):
            current_signal = 1.0 if close_arr[idx] > close_arr[last_below] else -1.0

        signal[idx] = current_signal

    return pd.Series(signal, index=close.index)


def add_hawkes_volatility_features(
    data: pd.DataFrame,
    *,
    norm_lookback_bars: int = 390,
    threshold_lookback_bars: int = 390,
    kappa: float = 0.10,
    low_quantile: float = 0.05,
    high_quantile: float = 0.95,
) -> pd.DataFrame:
    """
    Add Hawkes-process volatility-cluster features.

    `hawkes_vol_below_low` is useful as a momentum-exit context: volatility
    clustering has decayed back below its lower rolling threshold.
    """
    required = {"high", "low", "close"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"hawkes volatility requires columns: {sorted(missing)}")

    df = data.copy()
    norm_lookback_bars = max(20, int(norm_lookback_bars))
    threshold_lookback_bars = max(20, int(threshold_lookback_bars))
    norm_min_periods = max(20, norm_lookback_bars // 2)
    threshold_min_periods = max(20, threshold_lookback_bars // 2)

    log_high = np.log(pd.to_numeric(df["high"], errors="coerce"))
    log_low = np.log(pd.to_numeric(df["low"], errors="coerce"))
    log_range = log_high - log_low
    log_atr = _log_atr(df, norm_lookback_bars, norm_min_periods)
    norm_range = log_range / log_atr.replace(0, np.nan)
    hawkes_vol = hawkes_process(norm_range, kappa=float(kappa))

    # Use prior Hawkes values for thresholds to avoid including the current bar
    # in the threshold it is judged against.
    threshold_source = hawkes_vol.shift(1)
    q_low = threshold_source.rolling(window=threshold_lookback_bars, min_periods=threshold_min_periods).quantile(float(low_quantile))
    q_high = threshold_source.rolling(window=threshold_lookback_bars, min_periods=threshold_min_periods).quantile(float(high_quantile))

    above_high = hawkes_vol.gt(q_high)
    below_low = hawkes_vol.lt(q_low)
    prior_vol = hawkes_vol.shift(1)
    cross_above = above_high & prior_vol.le(q_high.shift(1))
    cross_below = below_low & prior_vol.ge(q_low.shift(1))
    momentum_signal = _hawkes_momentum_signal(df["close"], hawkes_vol, q_low, q_high)

    df["hawkes_log_atr"] = log_atr
    df["hawkes_norm_range"] = norm_range
    df["hawkes_vol"] = hawkes_vol
    df["hawkes_q_low"] = q_low
    df["hawkes_q_high"] = q_high
    df["hawkes_vol_above_high"] = above_high.fillna(False)
    df["hawkes_vol_below_low"] = below_low.fillna(False)
    df["hawkes_vol_cross_above_high"] = cross_above.fillna(False)
    df["hawkes_vol_cross_below_low"] = cross_below.fillna(False)
    df["hawkes_momentum_signal"] = momentum_signal
    return df
