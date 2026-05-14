from __future__ import annotations

import numpy as np
import pandas as pd


def add_volume_spread_features(
    data: pd.DataFrame,
    *,
    lookback_bars: int = 390,
    atr_col: str = "atr",
    volume_col: str = "volume",
    min_r2: float = 0.10,
    min_slope: float = 0.0,
    score_scale: float = 1.0,
    extreme_threshold: float = 0.65,
) -> pd.DataFrame:
    """
    Add volume-spread-analysis features.

    The indicator compares current candle range to the range expected from
    current volume. The rolling regression is fit on prior bars only, so the
    current candle does not leak into its own model.

    Positive residual: range larger than expected for volume, often a thin move.
    Negative residual: range smaller than expected for volume, often absorption.
    """
    required = {"high", "low", volume_col}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"volume spread analysis requires columns: {sorted(missing)}")

    df = data.copy()
    lookback_bars = max(20, int(lookback_bars))
    min_periods = max(20, lookback_bars // 2)
    score_scale = max(float(score_scale), 1e-9)

    candle_range = (pd.to_numeric(df["high"], errors="coerce") - pd.to_numeric(df["low"], errors="coerce")).abs()
    volume = pd.to_numeric(df[volume_col], errors="coerce")

    if atr_col in df.columns:
        atr = pd.to_numeric(df[atr_col], errors="coerce")
    else:
        close = pd.to_numeric(df["close"], errors="coerce")
        prev_close = close.shift(1)
        atr = pd.concat(
            [
                candle_range,
                (pd.to_numeric(df["high"], errors="coerce") - prev_close).abs(),
                (pd.to_numeric(df["low"], errors="coerce") - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1).rolling(window=14, min_periods=14).mean()

    volume_median = volume.rolling(window=lookback_bars, min_periods=min_periods).median()
    rel_range = candle_range / atr.replace(0, np.nan)
    rel_volume = volume / volume_median.replace(0, np.nan)

    # Fit y = slope * x + intercept using prior bars only.
    x = rel_volume.shift(1)
    y = rel_range.shift(1)
    valid = x.notna() & y.notna() & np.isfinite(x) & np.isfinite(y)
    valid_f = valid.astype(float)
    x0 = x.where(valid, 0.0)
    y0 = y.where(valid, 0.0)

    n = valid_f.rolling(window=lookback_bars, min_periods=min_periods).sum()
    sum_x = x0.rolling(window=lookback_bars, min_periods=min_periods).sum()
    sum_y = y0.rolling(window=lookback_bars, min_periods=min_periods).sum()
    sum_xx = (x0 * x0).rolling(window=lookback_bars, min_periods=min_periods).sum()
    sum_yy = (y0 * y0).rolling(window=lookback_bars, min_periods=min_periods).sum()
    sum_xy = (x0 * y0).rolling(window=lookback_bars, min_periods=min_periods).sum()

    denom = n * sum_xx - sum_x * sum_x
    slope = (n * sum_xy - sum_x * sum_y) / denom.replace(0, np.nan)
    intercept = (sum_y - slope * sum_x) / n.replace(0, np.nan)

    corr_denom = (n * sum_xx - sum_x * sum_x) * (n * sum_yy - sum_y * sum_y)
    r2 = ((n * sum_xy - sum_x * sum_y) ** 2) / corr_denom.replace(0, np.nan)
    predicted = slope * rel_volume + intercept
    residual_raw = rel_range - predicted

    model_ok = (
        n.ge(min_periods)
        & slope.ge(float(min_slope))
        & r2.ge(float(min_r2))
        & residual_raw.notna()
        & np.isfinite(residual_raw)
    )
    residual = residual_raw.where(model_ok, 0.0)
    score = np.tanh(residual / score_scale)
    threshold = abs(float(extreme_threshold))

    df["vsa_candle_range"] = candle_range
    df["vsa_rel_range"] = rel_range
    df["vsa_rel_volume"] = rel_volume
    df["vsa_pred_rel_range"] = predicted
    df["vsa_residual_raw"] = residual_raw
    df["vsa_residual"] = residual
    df["vsa_score"] = score
    df["vsa_model_r2"] = r2
    df["vsa_model_slope"] = slope
    df["vsa_model_valid"] = model_ok.fillna(False)
    df["vsa_absorption"] = df["vsa_model_valid"] & df["vsa_score"].le(-threshold)
    df["vsa_thin_move"] = df["vsa_model_valid"] & df["vsa_score"].ge(threshold)
    return df
