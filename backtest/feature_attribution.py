"""
Feature Attribution — decompose which contextual features drive strategy edge.

This module sits between the engine's signal generation and the feature
research lab.  It takes a signal frame (with signals already generated and
filtered) and measures the marginal contribution of each feature to the
conditional forward PnL.

Methodology
-----------
Permutation importance on the feature level:
    For each numeric/binable context feature, shuffle it across the signal
    population and measure the drop in mean directional forward PnL at
    configurable horizons.  The larger the drop, the more that feature
    contributes to the strategy's edge.

Additive decomposition via bucketed linear approximation:
    Bucket each feature, fit a linear model on one-hot bucketed features,
    and report coefficient + t-stat.  This gives a SHAP-like additive
    decomposition without requiring a black-box model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeatureAttributionPaths:
    importance_csv: Path
    decomposition_csv: Path
    leaderboard_csv: Path


# Features we know how to interpret from the engine's signal frame.
# These match the context columns the engine collects in entry_context_metadata.
NUMERIC_ATTRIBUTION_FEATURES = [
    "vwap_z",
    "vwap_dev_prev_points",
    "vwap_side_age_bars",
    "gap_points",
    "gap_atr",
    "gap_prior_range_pct",
    "open_location_prior_range",
    "overnight_inventory_points",
    "overnight_inventory_atr",
    "overnight_range_atr",
    "prior_rth_range_atr",
    "rth_range_so_far_atr",
    "ib_range_atr",
    "vsa_score",
    "vsa_residual",
    "vsa_rel_range",
    "vsa_rel_volume",
    "hawkes_norm_range",
    "hawkes_vol",
    "cusum_event_move_points",
    "cusum_event_move_atr",
    "cusum_bars_since_event",
    "markov_volatility",
    "markov_state_confidence",
    "market_memory_hurst",
    "market_memory_entropy",
    "market_memory_lz_complexity",
    "market_memory_tail_alpha",
    "options_net_gex",
    "options_abs_gex",
    "options_put_call_oi_ratio",
]

CATEGORICAL_ATTRIBUTION_FEATURES = [
    "day_regime",
    "open_context",
    "vwap_side",
    "vwap_side_prev",
    "vwap_cross_direction",
    "gap_inventory_alignment",
    "overnight_inventory_direction",
    "above_ib_high",
    "below_ib_low",
    "inside_ib",
    "vsa_absorption",
    "vsa_thin_move",
    "hawkes_vol_above_high",
    "hawkes_vol_below_low",
    "hawkes_momentum_signal",
    "cusum_event_direction",
    "markov_state_label",
    "market_memory_state",
    "market_memory_hurst_regime",
    "market_memory_entropy_regime",
    "market_memory_lz_regime",
    "market_memory_tail_alpha_regime",
    "options_gex_regime",
    "options_gamma_environment",
]

# Features that should be excluded from attribution because they are
# post-signal or part of the signal definition itself.
_EXCLUDED_COLS = {
    "signal", "signal_type", "time", "hour_min", "date_str", "close",
    "open", "high", "low", "volume", "atr", "trend_ema",
}


def _bucket_numeric(series: pd.Series, n_buckets: int = 5) -> pd.Series:
    """Discretize a numeric column into n_buckets quantile-based bins."""
    values = pd.to_numeric(series, errors="coerce")
    non_null = values.dropna()
    if non_null.nunique() < 3:
        return values.round(4).astype(str).where(values.notna(), "MISSING")
    actual_bins = min(int(n_buckets), int(non_null.nunique()))
    try:
        bucketed = pd.qcut(values, q=actual_bins, duplicates="drop", labels=False)
        # Convert to string with range labels for readability
        edges = pd.qcut(values, q=actual_bins, duplicates="drop", retbins=True)[1]
        labels = [
            f"[{edges[i]:.2f}, {edges[i+1]:.2f})" if i + 1 < len(edges) else f"[{edges[i]:.2f}, {edges[-1]:.2f}]"
            for i in range(len(edges) - 1)
        ]
        bucket_map = dict(enumerate(labels))
        bucketed = bucketed.map(bucket_map).astype(str)
    except (ValueError, IndexError):
        bucketed = values.round(4).astype(str)
    return bucketed.where(values.notna(), "MISSING")


def _directional_fwd_pnl(
    signal_frame: pd.DataFrame,
    horizon_bars: int,
    contract_value: float = 20.0,
) -> pd.Series:
    """
    Compute directional forward P&L at a given horizon for signal bars.

    Returns a Series aligned with signal_frame where signal != 0.
    Positive for correctly-directed moves after the signal.
    """
    close = pd.to_numeric(signal_frame["close"], errors="coerce").to_numpy(dtype=float)
    signal = pd.to_numeric(signal_frame.get("signal", 0), errors="coerce").fillna(0).to_numpy(dtype=int)
    active = signal != 0
    if not active.any():
        return pd.Series(dtype=float)

    direction = np.where(signal > 0, 1.0, -1.0)
    entry = close.copy()
    idx = np.arange(len(close), dtype=int)
    future_idx = idx + int(horizon_bars)
    valid = future_idx < len(close)

    fwd_move = np.full(len(close), np.nan, dtype=float)
    fwd_move[valid] = close[future_idx[valid]] - entry[valid]
    fwd_pnl = fwd_move * direction * float(contract_value)

    result = pd.Series(fwd_pnl, index=signal_frame.index)
    result[~active] = np.nan
    return result


def _baseline_edge(
    signal_frame: pd.DataFrame,
    horizon_bars: int,
    contract_value: float,
) -> float:
    """Mean directional forward PnL across all active signals."""
    fwd = _directional_fwd_pnl(signal_frame, horizon_bars, contract_value)
    valid = fwd.dropna()
    return float(valid.mean()) if len(valid) > 0 else 0.0


def _permutation_importance(
    signal_frame: pd.DataFrame,
    feature: str,
    horizon_bars: int,
    contract_value: float,
    baseline: float,
    rng: np.random.Generator,
    n_shuffles: int = 50,
) -> dict[str, float]:
    """
    Shuffle *feature* across signals and measure the drop in mean forward PnL.

    Returns
    -------
    dict with keys:
        baseline_mean     : original mean forward PnL
        shuffled_mean     : mean across all shuffles
        importance_drop   : baseline - shuffled_mean (positive = feature contributes)
        relative_importance : drop / |baseline| (infinity-safe)
    """
    fwd = _directional_fwd_pnl(signal_frame, horizon_bars, contract_value)
    valid_mask = fwd.notna()
    valid_pnl = fwd[valid_mask]

    if len(valid_pnl) < 10:
        return {
            "baseline_mean": baseline,
            "shuffled_mean": baseline,
            "importance_drop": 0.0,
            "relative_importance": 0.0,
            "n_valid_signals": int(valid_pnl.sum()),
        }

    # Only shuffle within the active-signal population
    active_idx = np.flatnonzero(valid_mask.to_numpy())
    feature_arr = signal_frame[feature].to_numpy()

    shuffled_means = np.empty(max(1, int(n_shuffles)), dtype=float)
    for shuffle_idx in range(len(shuffled_means)):
        shuffled = feature_arr.copy()
        shuffled[active_idx] = rng.permutation(shuffled[active_idx])
        # Group by shuffled value and compute mean PnL per group, then
        # re-weight by original group size to keep population distribution.
        work = signal_frame[[feature]].copy()
        work["_fwd_pnl"] = fwd
        work["_shuffled"] = shuffled
        group_map = work.loc[valid_mask].groupby("_shuffled")["_fwd_pnl"].mean()
        # Map back using original feature values for the active signals
        mapped_pnl = work.loc[valid_mask, "_shuffled"].map(group_map)
        shuffled_means[shuffle_idx] = float(mapped_pnl.mean()) if len(mapped_pnl) > 0 else baseline

    shuffled_mean = float(np.nanmean(shuffled_means)) if len(shuffled_means) else baseline
    drop = baseline - shuffled_mean
    abs_baseline = abs(baseline) if abs(baseline) > 1e-12 else 1e-12
    relative = drop / abs_baseline

    return {
        "baseline_mean": baseline,
        "shuffled_mean": shuffled_mean,
        "importance_drop": drop,
        "relative_importance": relative,
        "n_valid_signals": int(valid_pnl.sum()),
    }


def _additive_decomposition(
    signal_frame: pd.DataFrame,
    feature: str,
    horizon_bars: int,
    contract_value: float,
    min_observations: int = 10,
) -> dict[str, Any]:
    """
    Bucket *feature*, fit a one-hot linear regression against forward PnL,
    and report the coefficient range + bucket-level edge.

    This is intentionally simple: no interaction terms, no regularization.
    It's a diagnostic, not a production model.
    """
    fwd = _directional_fwd_pnl(signal_frame, horizon_bars, contract_value)
    valid_mask = fwd.notna() & signal_frame[feature].notna()
    if valid_mask.sum() < min_observations:
        return {
            "feature": feature,
            "horizon_bars": int(horizon_bars),
            "n_valid": int(valid_mask.sum()),
            "bucket_count": 0,
            "coefficient_range": 0.0,
            "max_coefficient": 0.0,
            "max_coef_bucket": "",
            "min_coefficient": 0.0,
            "min_coef_bucket": "",
        }

    # Bucket the feature
    if feature in NUMERIC_ATTRIBUTION_FEATURES:
        bucketed = _bucket_numeric(signal_frame[feature])
    else:
        bucketed = signal_frame[feature].astype(str).fillna("MISSING")

    # Per-bucket mean forward PnL
    bucket_means = fwd[valid_mask].groupby(bucketed[valid_mask]).mean()
    bucket_counts = fwd[valid_mask].groupby(bucketed[valid_mask]).count()

    valid_buckets = bucket_counts[bucket_counts >= min_observations].index
    if len(valid_buckets) < 2:
        return {
            "feature": feature,
            "horizon_bars": int(horizon_bars),
            "n_valid": int(valid_mask.sum()),
            "bucket_count": int(len(valid_buckets)),
            "coefficient_range": 0.0,
            "max_coefficient": 0.0,
            "max_coef_bucket": "",
            "min_coefficient": 0.0,
            "min_coef_bucket": "",
        }

    # Use the most-frequent bucket as the reference level
    ref_bucket = bucket_counts.idxmax()
    bucket_effects = bucket_means - bucket_means[ref_bucket]

    coefficients = bucket_effects.drop(ref_bucket, errors="ignore")
    if len(coefficients) == 0:
        return {
            "feature": feature,
            "horizon_bars": int(horizon_bars),
            "n_valid": int(valid_mask.sum()),
            "bucket_count": int(len(valid_buckets)),
            "coefficient_range": 0.0,
            "max_coefficient": 0.0,
            "max_coef_bucket": "",
            "min_coefficient": 0.0,
            "min_coef_bucket": "",
        }

    return {
        "feature": feature,
        "horizon_bars": int(horizon_bars),
        "n_valid": int(valid_mask.sum()),
        "bucket_count": int(len(valid_buckets)),
        "coefficient_range": float(coefficients.max() - coefficients.min()),
        "max_coefficient": float(coefficients.max()),
        "max_coef_bucket": str(coefficients.idxmax()),
        "min_coefficient": float(coefficients.min()),
        "min_coef_bucket": str(coefficients.idxmin()),
        "ref_bucket": str(ref_bucket),
        "baseline_mean": float(fwd[valid_mask].mean()),
        "best_bucket_mean": float(bucket_means.max()),
        "worst_bucket_mean": float(bucket_means.min()),
    }


def _available_features(signal_frame: pd.DataFrame) -> list[str]:
    """Return the subset of known features present in the signal frame."""
    available: list[str] = []
    for feature in NUMERIC_ATTRIBUTION_FEATURES + CATEGORICAL_ATTRIBUTION_FEATURES:
        if feature in signal_frame.columns and feature not in _EXCLUDED_COLS:
            available.append(feature)
    return available


def run_feature_attribution(
    signal_frame: pd.DataFrame,
    *,
    horizons_bars: tuple[int, ...] = (3, 6, 12, 24),
    contract_value: float = 20.0,
    n_permutation_shuffles: int = 50,
    random_seed: int = 7,
    min_observations: int = 10,
    out_dir: str | Path = "results/feature_attribution",
    artifact_name: str = "feature_attribution",
) -> FeatureAttributionPaths:
    """
    Run permutation importance + additive decomposition on all available
    features in the signal frame.

    Parameters
    ----------
    signal_frame : pd.DataFrame
        Must contain 'signal', 'close', and any context features to evaluate.
        This is typically the output of ``build_signal_frame()``.
    horizons_bars : tuple of int
        Forward horizons (in 5-min bars) to evaluate.
    contract_value : float
        NQ point multiplier for PnL calculation.
    n_permutation_shuffles : int
        How many shuffles per feature for permutation importance.
    random_seed : int
        RNG seed for reproducibility.
    min_observations : int
        Minimum bucket observations for decomposition.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = signal_frame.copy()
    if "signal" not in df.columns:
        raise ValueError("signal_frame must contain a 'signal' column.")

    features = _available_features(df)
    if not features:
        raise ValueError("No known features found in signal_frame.")

    horizons = tuple(sorted({int(h) for h in horizons_bars if int(h) > 0}))
    rng = np.random.default_rng(int(random_seed))

    importance_rows: list[dict[str, Any]] = []
    decomposition_rows: list[dict[str, Any]] = []

    for horizon in horizons:
        baseline = _baseline_edge(df, horizon, contract_value)

        for feature in features:
            # Permutation importance
            imp = _permutation_importance(
                df, feature, horizon, contract_value,
                baseline=baseline, rng=rng, n_shuffles=n_permutation_shuffles,
            )
            importance_rows.append({
                "horizon_bars": int(horizon),
                "feature": feature,
                "feature_type": "numeric" if feature in NUMERIC_ATTRIBUTION_FEATURES else "categorical",
                **imp,
            })

            # Additive decomposition
            decomp = _additive_decomposition(
                df, feature, horizon, contract_value,
                min_observations=min_observations,
            )
            decomposition_rows.append(decomp)

    importance_df = pd.DataFrame(importance_rows)
    decomposition_df = pd.DataFrame(decomposition_rows)

    # Leaderboard: rank features by relative importance across horizons
    if not importance_df.empty:
        leaderboard = (
            importance_df.groupby("feature", as_index=False)
            .agg(
                n_horizons=("horizon_bars", "nunique"),
                mean_relative_importance=("relative_importance", "mean"),
                max_relative_importance=("relative_importance", "max"),
                mean_importance_drop=("importance_drop", "mean"),
            )
            .sort_values("mean_relative_importance", ascending=False)
        )
    else:
        leaderboard = pd.DataFrame()

    importance_csv = out_dir / f"{artifact_name}_permutation_importance.csv"
    decomposition_csv = out_dir / f"{artifact_name}_additive_decomposition.csv"
    leaderboard_csv = out_dir / f"{artifact_name}_leaderboard.csv"

    importance_df.to_csv(importance_csv, index=False)
    decomposition_df.to_csv(decomposition_csv, index=False)
    leaderboard.to_csv(leaderboard_csv, index=False)

    return FeatureAttributionPaths(
        importance_csv=importance_csv,
        decomposition_csv=decomposition_csv,
        leaderboard_csv=leaderboard_csv,
    )