from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

try:
    from scipy.ndimage import gaussian_filter1d as scipy_gaussian_filter1d
    from scipy.signal import find_peaks as scipy_find_peaks
    from scipy.signal import peak_prominences as scipy_peak_prominences
    from scipy.stats import gaussian_kde
except ModuleNotFoundError:  # pragma: no cover - depends on local env
    scipy_gaussian_filter1d = None
    scipy_find_peaks = None
    scipy_peak_prominences = None
    gaussian_kde = None


@dataclass(frozen=True)
class ProfileLevel:
    price: float
    prominence: float
    density: float


def _linear_time_weights(length: int, first_weight: float) -> np.ndarray:
    if length <= 0:
        return np.array([], dtype=float)
    weights = np.linspace(float(first_weight), 1.0, length, dtype=float)
    return np.maximum(weights, 0.0)


def _dedupe_levels(levels: list[ProfileLevel], min_distance_points: float, max_levels: int) -> list[ProfileLevel]:
    if not levels:
        return []

    chosen: list[ProfileLevel] = []
    for level in sorted(levels, key=lambda item: item.prominence, reverse=True):
        if all(abs(level.price - prior.price) >= min_distance_points for prior in chosen):
            chosen.append(level)
        if len(chosen) >= max_levels:
            break
    return sorted(chosen, key=lambda item: item.price)


def _gaussian_smooth(values: np.ndarray, sigma: float) -> np.ndarray:
    if scipy_gaussian_filter1d is not None:
        return scipy_gaussian_filter1d(values, sigma=sigma, mode="nearest")

    sigma = max(float(sigma), 0.5)
    radius = max(2, int(np.ceil(sigma * 4)))
    x = np.arange(-radius, radius + 1, dtype=float)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    kernel /= kernel.sum()
    padded = np.pad(values, radius, mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _find_prominent_peaks(density: np.ndarray, min_prominence: float) -> tuple[np.ndarray, np.ndarray]:
    if scipy_find_peaks is not None:
        peak_idx, props = scipy_find_peaks(density, prominence=min_prominence)
        prominences = props.get("prominences")
        if prominences is None and scipy_peak_prominences is not None:
            prominences = scipy_peak_prominences(density, peak_idx)[0]
        return peak_idx, np.asarray(prominences if prominences is not None else [], dtype=float)

    peaks: list[int] = []
    prominences: list[float] = []
    for idx in range(1, len(density) - 1):
        if density[idx] <= density[idx - 1] or density[idx] < density[idx + 1]:
            continue
        left_min = float(np.min(density[: idx + 1]))
        right_min = float(np.min(density[idx:]))
        prominence = float(density[idx] - max(left_min, right_min))
        if prominence >= min_prominence:
            peaks.append(idx)
            prominences.append(prominence)
    return np.asarray(peaks, dtype=int), np.asarray(prominences, dtype=float)


def find_market_profile_levels(
    closes: np.ndarray,
    current_atr: float,
    *,
    atr_multiplier: float = 3.0,
    first_weight: float = 1.0,
    prominence_threshold: float = 0.25,
    grid_size: int = 160,
    max_levels: int = 8,
    min_level_distance_points: float = 4.0,
    backend: str = "histogram",
) -> list[ProfileLevel]:
    """Find prominent support/resistance levels from a rolling market profile.

    The video uses KDE on logarithmic closing prices. `backend="kde"` follows
    that closely. `backend="histogram"` is a fast smoothed-density approximation
    for long full-history research runs.
    """

    prices = np.asarray(closes, dtype=float)
    prices = prices[np.isfinite(prices) & (prices > 0)]
    if len(prices) < 20:
        return []

    current_atr = float(current_atr)
    if not np.isfinite(current_atr) or current_atr <= 0:
        return []

    grid_size = max(40, int(grid_size))
    max_levels = max(1, int(max_levels))
    log_prices = np.log(prices)
    lo = float(np.nanmin(log_prices))
    hi = float(np.nanmax(log_prices))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return []

    current_price = float(prices[-1])
    log_bandwidth = max(np.log1p(current_atr / max(current_price, 1e-12)) * float(atr_multiplier), 1e-8)
    grid = np.linspace(lo, hi, grid_size)
    weights = _linear_time_weights(len(log_prices), first_weight)
    if weights.sum() <= 0:
        return []

    backend = str(backend).lower()
    if backend == "kde" and gaussian_kde is not None:
        std = float(np.std(log_prices))
        bw_method = log_bandwidth / std if std > 0 else None
        kernel = gaussian_kde(log_prices, bw_method=bw_method, weights=weights)
        density = kernel(grid)
    else:
        # A fast market-profile density: weighted time-at-price histogram plus
        # Gaussian smoothing in log-price space.
        hist, edges = np.histogram(log_prices, bins=grid_size, range=(lo, hi), weights=weights, density=False)
        density = hist.astype(float)
        grid = (edges[:-1] + edges[1:]) / 2.0
        grid_step = float(grid[1] - grid[0]) if len(grid) > 1 else log_bandwidth
        sigma_bins = max(log_bandwidth / max(grid_step, 1e-12), 0.5)
        density = _gaussian_smooth(density, sigma=sigma_bins)

    if len(density) < 3 or not np.isfinite(density).any():
        return []

    density = np.nan_to_num(density, nan=0.0, posinf=0.0, neginf=0.0)
    max_density = float(np.max(density))
    if max_density <= 0:
        return []

    min_prominence = max(0.0, float(prominence_threshold)) * max_density
    peak_idx, prominences = _find_prominent_peaks(density, min_prominence)
    if len(peak_idx) == 0:
        dominant_idx = int(np.argmax(density))
        dominant_prominence = float(density[dominant_idx] - np.min(density))
        if dominant_prominence < min_prominence:
            return []
        peak_idx = np.asarray([dominant_idx], dtype=int)
        prominences = np.asarray([dominant_prominence], dtype=float)

    levels = [
        ProfileLevel(
            price=float(np.exp(grid[int(idx)])),
            prominence=float(prom),
            density=float(density[int(idx)]),
        )
        for idx, prom in zip(peak_idx, prominences)
        if np.isfinite(grid[int(idx)]) and np.isfinite(prom)
    ]
    return _dedupe_levels(levels, float(min_level_distance_points), max_levels)


def add_market_profile_features(
    data: pd.DataFrame,
    *,
    lookback_bars: int = 390,
    atr_col: str = "atr",
    atr_multiplier: float = 3.0,
    first_weight: float = 1.0,
    prominence_threshold: float = 0.25,
    grid_size: int = 160,
    recompute_every_bars: int = 12,
    max_levels: int = 8,
    min_level_distance_points: float = 4.0,
    backend: str = "histogram",
) -> pd.DataFrame:
    """Append rolling market-profile support/resistance features.

    Levels at row `i` only use closes through row `i`. To keep full-history
    backtests practical, levels can be recomputed every N bars and reused until
    the next refresh.
    """

    required = {"close", "high", "low"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"market profile requires columns: {sorted(missing)}")

    df = data.reset_index(drop=True).copy()
    lookback_bars = max(20, int(lookback_bars))
    recompute_every_bars = max(1, int(recompute_every_bars))
    max_levels = max(1, int(max_levels))

    if atr_col in df.columns:
        atr = pd.to_numeric(df[atr_col], errors="coerce").to_numpy(dtype=float)
    else:
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(window=14, min_periods=14).mean().to_numpy(dtype=float)

    close = pd.to_numeric(df["close"], errors="coerce").to_numpy(dtype=float)
    n = len(df)

    feature_cols = {
        "mp_nearest_support": np.full(n, np.nan),
        "mp_nearest_resistance": np.full(n, np.nan),
        "mp_dist_to_support": np.full(n, np.nan),
        "mp_dist_to_resistance": np.full(n, np.nan),
        "mp_support_prominence": np.full(n, np.nan),
        "mp_resistance_prominence": np.full(n, np.nan),
        "mp_crossed_up_level": np.full(n, np.nan),
        "mp_crossed_down_level": np.full(n, np.nan),
        "mp_crossed_up_prominence": np.full(n, np.nan),
        "mp_crossed_down_prominence": np.full(n, np.nan),
        "mp_level_count": np.zeros(n, dtype=float),
        "mp_crossed_up": np.zeros(n, dtype=bool),
        "mp_crossed_down": np.zeros(n, dtype=bool),
        "mp_profile_stale_bars": np.full(n, np.nan),
    }
    for idx in range(max_levels):
        feature_cols[f"mp_level_{idx}_price"] = np.full(n, np.nan)
        feature_cols[f"mp_level_{idx}_prominence"] = np.full(n, np.nan)

    last_levels: list[ProfileLevel] = []
    last_refresh_idx = -1

    for refresh_idx in range(lookback_bars - 1, n, recompute_every_bars):
        start_idx = refresh_idx - lookback_bars + 1
        last_levels = find_market_profile_levels(
            close[start_idx : refresh_idx + 1],
            atr[refresh_idx],
            atr_multiplier=atr_multiplier,
            first_weight=first_weight,
            prominence_threshold=prominence_threshold,
            grid_size=grid_size,
            max_levels=max_levels,
            min_level_distance_points=min_level_distance_points,
            backend=backend,
        )
        last_refresh_idx = refresh_idx
        end_idx = min(n, refresh_idx + recompute_every_bars)

        if not last_levels:
            continue

        level_prices = np.array([level.price for level in last_levels], dtype=float)
        level_proms = np.array([level.prominence for level in last_levels], dtype=float)
        ranked = sorted(last_levels, key=lambda item: item.prominence, reverse=True)

        for row_idx in range(refresh_idx, end_idx):
            current_close = close[row_idx]
            if not np.isfinite(current_close):
                continue

            supports = np.where(level_prices < current_close)[0]
            resistances = np.where(level_prices > current_close)[0]

            if len(supports):
                support_idx = supports[np.argmax(level_prices[supports])]
                support = level_prices[support_idx]
                feature_cols["mp_nearest_support"][row_idx] = support
                feature_cols["mp_dist_to_support"][row_idx] = current_close - support
                feature_cols["mp_support_prominence"][row_idx] = level_proms[support_idx]

            if len(resistances):
                resistance_idx = resistances[np.argmin(level_prices[resistances])]
                resistance = level_prices[resistance_idx]
                feature_cols["mp_nearest_resistance"][row_idx] = resistance
                feature_cols["mp_dist_to_resistance"][row_idx] = resistance - current_close
                feature_cols["mp_resistance_prominence"][row_idx] = level_proms[resistance_idx]

            prior_close = close[row_idx - 1] if row_idx > 0 else np.nan
            if np.isfinite(prior_close):
                crossed_up = np.where((prior_close <= level_prices) & (current_close > level_prices))[0]
                crossed_down = np.where((prior_close >= level_prices) & (current_close < level_prices))[0]
                feature_cols["mp_crossed_up"][row_idx] = bool(len(crossed_up))
                feature_cols["mp_crossed_down"][row_idx] = bool(len(crossed_down))

                if len(crossed_up):
                    # Use the nearest broken level as the new support reference.
                    crossed_idx = crossed_up[np.argmax(level_prices[crossed_up])]
                    feature_cols["mp_crossed_up_level"][row_idx] = level_prices[crossed_idx]
                    feature_cols["mp_crossed_up_prominence"][row_idx] = level_proms[crossed_idx]

                if len(crossed_down):
                    # Use the nearest broken level as the new resistance reference.
                    crossed_idx = crossed_down[np.argmin(level_prices[crossed_down])]
                    feature_cols["mp_crossed_down_level"][row_idx] = level_prices[crossed_idx]
                    feature_cols["mp_crossed_down_prominence"][row_idx] = level_proms[crossed_idx]

            feature_cols["mp_level_count"][row_idx] = len(last_levels)
            feature_cols["mp_profile_stale_bars"][row_idx] = row_idx - last_refresh_idx
            for level_idx, level in enumerate(ranked[:max_levels]):
                feature_cols[f"mp_level_{level_idx}_price"][row_idx] = level.price
                feature_cols[f"mp_level_{level_idx}_prominence"][row_idx] = level.prominence

    for name, values in feature_cols.items():
        df[name] = values

    return df
