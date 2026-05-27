from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


MICROSTRUCTURE_COST_SEVERITY = {
    "normal": 0,
    "elevated": 1,
    "stressed": 2,
    "fragile": 3,
    "dislocated": 4,
}
SEVERITY_TO_COST_STATE = {value: key for key, value in MICROSTRUCTURE_COST_SEVERITY.items()}


@dataclass(frozen=True)
class VolatilityConditionedCostStressConfig:
    tight_spread_points: float = 0.75
    wide_spread_points: float = 1.50
    wide_p95_spread_points: float = 2.00
    high_realized_vol_ratio: float = 1.35
    low_realized_vol_ratio: float = 0.70
    depth_exhaustion_threshold: float = 0.30
    normal_slippage_multiplier: float = 1.00
    elevated_slippage_multiplier: float = 1.25
    stressed_slippage_multiplier: float = 1.75
    fragile_slippage_multiplier: float = 2.25
    dislocated_slippage_multiplier: float = 3.00


def add_volatility_conditioned_cost_stress(
    data: pd.DataFrame,
    *,
    config: VolatilityConditionedCostStressConfig | None = None,
) -> pd.DataFrame:
    """
    Classify execution-cost stress from volatility state plus top-book evidence.

    This is an execution-realism model. It does not create directional signals.
    """
    cfg = config or VolatilityConditionedCostStressConfig()
    _validate_config(cfg)
    out = data.copy()

    cost_state = _text(out, "microstructure_cost_state", default="normal")
    base_severity = cost_state.map(MICROSTRUCTURE_COST_SEVERITY).fillna(0).astype(int)
    median_spread = _num(out, "median_spread_points")
    p95_spread = _num(out, "p95_spread_points")
    depth_exhaustion = _num(out, "top_book_depth_exhausted_trade_pct")
    realized_vol_ratio = _num(out, "realized_vol_ratio")
    volatility_state = _text(out, "volatility_state")
    compression_state = _text(out, "volatility_compression_state")
    vol_of_vol_state = _text(out, "volatility_vol_of_vol_state")
    jump_event = _bool(out, "volatility_jump_event")

    tight_spread = median_spread.le(float(cfg.tight_spread_points))
    wide_spread = median_spread.ge(float(cfg.wide_spread_points)) | p95_spread.ge(float(cfg.wide_p95_spread_points))
    high_realized_vol = (
        realized_vol_ratio.ge(float(cfg.high_realized_vol_ratio))
        | volatility_state.isin({"expanded_volatility_context", "high_markov_volatility_context"})
        | compression_state.eq("expanded_volatility")
    )
    low_realized_vol = (
        realized_vol_ratio.le(float(cfg.low_realized_vol_ratio))
        | volatility_state.eq("compressed_volatility_context")
        | compression_state.eq("compressed_volatility")
    )
    vol_shock = (
        jump_event
        | volatility_state.isin({"jump_volatility_context", "unstable_volatility_context"})
        | vol_of_vol_state.eq("unstable_volatility_of_volatility")
    )
    depth_exhausted = depth_exhaustion.ge(float(cfg.depth_exhaustion_threshold))

    severity = base_severity.copy()
    severity = severity.where(~(high_realized_vol & wide_spread), np.maximum(severity, 2))
    severity = severity.where(~(wide_spread & depth_exhausted), np.maximum(severity, 3))
    severity = severity.where(~(vol_shock & depth_exhausted), np.maximum(severity, 4))
    normal_ok = low_realized_vol & tight_spread & ~depth_exhausted & severity.le(1)
    severity = severity.where(~normal_ok, 0).clip(lower=0, upper=4).astype(int)

    multiplier_map = {
        0: float(cfg.normal_slippage_multiplier),
        1: float(cfg.elevated_slippage_multiplier),
        2: float(cfg.stressed_slippage_multiplier),
        3: float(cfg.fragile_slippage_multiplier),
        4: float(cfg.dislocated_slippage_multiplier),
    }
    reasons = _stress_reasons(
        high_realized_vol=high_realized_vol,
        low_realized_vol=low_realized_vol,
        vol_shock=vol_shock,
        wide_spread=wide_spread,
        tight_spread=tight_spread,
        depth_exhausted=depth_exhausted,
        normal_ok=normal_ok,
    )

    out["vol_conditioned_cost_state"] = severity.map(SEVERITY_TO_COST_STATE).astype(str)
    out["vol_conditioned_slippage_multiplier"] = severity.map(multiplier_map).astype(float)
    out["vol_conditioned_reject_fill"] = (vol_shock & depth_exhausted) | severity.eq(4)
    out["vol_conditioned_allow_normal_assumptions"] = normal_ok
    out["vol_conditioned_high_realized_vol"] = high_realized_vol.fillna(False).astype(bool)
    out["vol_conditioned_vol_shock"] = vol_shock.fillna(False).astype(bool)
    out["vol_conditioned_wide_spread"] = wide_spread.fillna(False).astype(bool)
    out["vol_conditioned_depth_exhausted"] = depth_exhausted.fillna(False).astype(bool)
    out["vol_conditioned_reason"] = reasons
    return out


def _stress_reasons(
    *,
    high_realized_vol: pd.Series,
    low_realized_vol: pd.Series,
    vol_shock: pd.Series,
    wide_spread: pd.Series,
    tight_spread: pd.Series,
    depth_exhausted: pd.Series,
    normal_ok: pd.Series,
) -> pd.Series:
    reasons: list[str] = []
    for idx in high_realized_vol.index:
        row_reasons: list[str] = []
        if bool(normal_ok.loc[idx]):
            row_reasons.append("low_vol_tight_spread_normal_assumptions")
        if bool(high_realized_vol.loc[idx]) and bool(wide_spread.loc[idx]):
            row_reasons.append("high_realized_vol_wide_spread_harsher_slippage")
        if bool(vol_shock.loc[idx]) and bool(depth_exhausted.loc[idx]):
            row_reasons.append("vol_shock_depth_exhaustion_reject_fragile_fill")
        elif bool(wide_spread.loc[idx]) and bool(depth_exhausted.loc[idx]):
            row_reasons.append("wide_spread_depth_exhaustion_fragile")
        if not row_reasons:
            if bool(low_realized_vol.loc[idx]) and bool(tight_spread.loc[idx]):
                row_reasons.append("low_vol_tight_spread")
            else:
                row_reasons.append("microstructure_cost_state")
        reasons.append("|".join(row_reasons))
    return pd.Series(reasons, index=high_realized_vol.index, dtype=object)


def _num(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(frame[col], errors="coerce")


def _text(frame: pd.DataFrame, col: str, *, default: str = "") -> pd.Series:
    if col not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=object)
    return frame[col].fillna(default).astype(str).str.strip().str.lower()


def _bool(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(False, index=frame.index)
    series = frame[col]
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").fillna(0).ne(0)
    return series.fillna("").astype(str).str.strip().str.lower().isin({"true", "1", "yes", "y", "t"})


def _validate_config(cfg: VolatilityConditionedCostStressConfig) -> None:
    if cfg.tight_spread_points < 0 or cfg.wide_spread_points <= 0 or cfg.wide_p95_spread_points <= 0:
        raise ValueError("spread thresholds must be non-negative and wide thresholds must be positive")
    if cfg.low_realized_vol_ratio <= 0 or cfg.high_realized_vol_ratio <= 0:
        raise ValueError("realized-vol ratios must be positive")
    if cfg.low_realized_vol_ratio >= cfg.high_realized_vol_ratio:
        raise ValueError("low_realized_vol_ratio must be below high_realized_vol_ratio")
    if cfg.depth_exhaustion_threshold < 0:
        raise ValueError("depth_exhaustion_threshold must be non-negative")
    multipliers = [
        cfg.normal_slippage_multiplier,
        cfg.elevated_slippage_multiplier,
        cfg.stressed_slippage_multiplier,
        cfg.fragile_slippage_multiplier,
        cfg.dislocated_slippage_multiplier,
    ]
    if any(float(value) <= 0.0 for value in multipliers):
        raise ValueError("slippage multipliers must be positive")
