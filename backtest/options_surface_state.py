from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


OPTIONS_SURFACE_STATE_COLUMNS = (
    "options_trade_date",
    "options_available_time",
    "options_dte_bucket",
    "options_surface_underlying_price",
    "options_surface_avg_iv",
    "options_surface_atm_strike",
    "options_surface_atm_distance_points",
    "options_surface_atm_iv",
    "options_surface_atm_call_iv",
    "options_surface_atm_put_iv",
    "options_surface_atm_put_call_iv_skew",
    "options_surface_put_call_iv_skew",
    "options_surface_iv_dispersion",
    "options_surface_smile_curvature",
    "options_surface_smile_quadratic_coef",
    "options_surface_iv_slope",
    "options_surface_strike_count",
    "options_surface_valid_iv_strikes",
    "options_surface_short_dte_bucket",
    "options_surface_long_dte_bucket",
    "options_surface_short_atm_iv",
    "options_surface_long_atm_iv",
    "options_surface_short_long_iv_spread",
    "options_surface_short_long_iv_ratio",
    "options_surface_trailing_realized_vol",
    "options_surface_iv_rv_premium",
    "options_surface_iv_rv_ratio",
    "options_surface_skew_state",
    "options_surface_smile_state",
    "options_surface_term_state",
    "options_surface_premium_state",
    "options_surface_state",
)


OPTIONS_SURFACE_FORECAST_DIAGNOSTIC_COLUMNS = (
    "options_trade_date",
    "options_available_time",
    "options_dte_bucket",
    "forecast_horizon_bars",
    "options_surface_atm_iv",
    "future_realized_vol",
    "options_surface_iv_forecast_bias",
    "options_surface_iv_forecast_bias_state",
)


@dataclass(frozen=True)
class OptionsSurfaceStateConfig:
    min_strikes_for_shape: int = 3
    min_forward_realized_bars: int = 3
    realized_vol_window_bars: int = 390
    realized_vol_min_bars: int = 120
    realized_vol_annualization_bars: float = 252.0 * 390.0
    short_dte_buckets: tuple[str, ...] = ("0dte", "1_7dte")
    long_dte_buckets: tuple[str, ...] = ("31_120dte", "8_30dte")
    skew_abs_threshold: float = 0.02
    smile_curvature_threshold: float = 0.02
    term_spread_threshold: float = 0.03
    rich_iv_premium_threshold: float = 0.05
    cheap_iv_premium_threshold: float = 0.0
    forecast_bias_threshold: float = 0.03


@dataclass(frozen=True)
class OptionsSurfaceForecastBiasDiagnostics:
    rows: pd.DataFrame
    summary: pd.DataFrame


def build_options_surface_state(
    dashboard: pd.DataFrame | Path | str,
    strike_surface: pd.DataFrame | Path | str,
    *,
    futures_bars: pd.DataFrame | None = None,
    config: OptionsSurfaceStateConfig | None = None,
) -> pd.DataFrame:
    """
    Summarize the existing options DTE/strike surface into ex-ante state rows.

    The output is one row per options snapshot and DTE bucket. Realized
    volatility, when futures bars are supplied, is merged with a backward as-of
    join from bars available at or before `options_available_time`.
    """
    cfg = config or OptionsSurfaceStateConfig()
    _validate_config(cfg)
    dash = _prepare_dashboard(_read_frame(dashboard))
    strikes = _prepare_strike_surface(_read_frame(strike_surface))
    if strikes.empty:
        return pd.DataFrame(columns=list(OPTIONS_SURFACE_STATE_COLUMNS))

    dashboard_lookup = _dashboard_lookup(dash)
    rows: list[dict[str, object]] = []
    for (available_time, bucket), group in strikes.groupby(["options_available_time", "options_dte_bucket"], sort=True):
        rows.append(_surface_bucket_row(group, dashboard_lookup.get((available_time, bucket), pd.Series(dtype=object)), cfg))

    state = pd.DataFrame(rows).sort_values(["options_available_time", "options_dte_bucket"]).reset_index(drop=True)
    state = _add_term_structure_state(state, cfg)
    if futures_bars is not None:
        state = _add_trailing_realized_vol(state, futures_bars, cfg)
    else:
        state["options_surface_trailing_realized_vol"] = np.nan
        state["options_surface_iv_rv_premium"] = np.nan
        state["options_surface_iv_rv_ratio"] = np.nan
    state["options_surface_skew_state"] = _label_skew_state(state["options_surface_put_call_iv_skew"], cfg)
    state["options_surface_smile_state"] = _label_smile_state(state["options_surface_smile_curvature"], cfg)
    state["options_surface_premium_state"] = _label_premium_state(state["options_surface_iv_rv_premium"], cfg)
    state["options_surface_state"] = _label_composite_surface_state(state)
    return state.loc[:, [col for col in OPTIONS_SURFACE_STATE_COLUMNS if col in state.columns]].reset_index(drop=True)


def add_options_surface_state_features(
    futures_bars: pd.DataFrame,
    surface_state: pd.DataFrame | Path | str,
    *,
    dte_bucket: str = "all",
) -> pd.DataFrame:
    """As-of merge a selected DTE-bucket surface state onto bar data."""
    if "time" not in futures_bars.columns:
        raise ValueError("futures bars must contain a time column")
    state = _read_frame(surface_state)
    if state.empty or "options_available_time" not in state.columns:
        return futures_bars.copy()
    if "options_dte_bucket" in state.columns:
        state = state.loc[state["options_dte_bucket"].astype(str).eq(str(dte_bucket))].copy()
    if state.empty:
        return futures_bars.copy()

    bars = futures_bars.copy()
    bars["time"] = _naive_datetime_ns(bars["time"])
    state["options_available_time"] = _naive_datetime_ns(state["options_available_time"])
    bars = bars.sort_values("time")
    state = state.dropna(subset=["options_available_time"]).sort_values("options_available_time")
    merged = pd.merge_asof(
        bars,
        state,
        left_on="time",
        right_on="options_available_time",
        direction="backward",
    )
    return merged.sort_values("time").reset_index(drop=True)


def build_options_surface_forecast_bias_diagnostics(
    surface_state: pd.DataFrame | Path | str,
    futures_bars: pd.DataFrame,
    *,
    horizons_bars: Iterable[int] = (390,),
    config: OptionsSurfaceStateConfig | None = None,
) -> OptionsSurfaceForecastBiasDiagnostics:
    """
    Compute ex-post IV forecast bias diagnostics.

    This function intentionally looks forward from each options snapshot and
    should not be used to build candidate signals.
    """
    cfg = config or OptionsSurfaceStateConfig()
    _validate_config(cfg)
    state = _read_frame(surface_state)
    if state.empty:
        empty = pd.DataFrame(columns=list(OPTIONS_SURFACE_FORECAST_DIAGNOSTIC_COLUMNS))
        return OptionsSurfaceForecastBiasDiagnostics(rows=empty, summary=pd.DataFrame())
    required = {"options_available_time", "options_dte_bucket", "options_surface_atm_iv"}
    missing = required.difference(state.columns)
    if missing:
        raise ValueError(f"surface state missing required columns: {sorted(missing)}")

    bars = _prepare_futures_bars(futures_bars)
    close = pd.to_numeric(bars["close"], errors="coerce")
    log_return = np.log(close).diff()
    times = bars["time"].to_numpy()
    returns = log_return.to_numpy(dtype=float)
    rows: list[dict[str, object]] = []
    clean_horizons = [int(item) for item in horizons_bars if int(item) > 1]
    if not clean_horizons:
        clean_horizons = [390]

    for row in state.itertuples(index=False):
        available_time = pd.Timestamp(getattr(row, "options_available_time"))
        bar_idx = int(np.searchsorted(times, np.datetime64(available_time), side="right") - 1)
        if bar_idx < 0:
            continue
        atm_iv = _finite_float(getattr(row, "options_surface_atm_iv", np.nan))
        for horizon in clean_horizons:
            start = bar_idx + 1
            stop = min(len(returns), bar_idx + 1 + int(horizon))
            window = pd.Series(returns[start:stop]).replace([np.inf, -np.inf], np.nan).dropna()
            future_rv = (
                float(window.std(ddof=0) * np.sqrt(float(cfg.realized_vol_annualization_bars)))
                if len(window) >= int(cfg.min_forward_realized_bars)
                else np.nan
            )
            bias = atm_iv - future_rv if np.isfinite(atm_iv) and np.isfinite(future_rv) else np.nan
            rows.append(
                {
                    "options_trade_date": getattr(row, "options_trade_date", ""),
                    "options_available_time": available_time,
                    "options_dte_bucket": getattr(row, "options_dte_bucket", ""),
                    "forecast_horizon_bars": int(horizon),
                    "options_surface_atm_iv": atm_iv,
                    "future_realized_vol": future_rv,
                    "options_surface_iv_forecast_bias": bias,
                    "options_surface_iv_forecast_bias_state": _forecast_bias_state(bias, cfg),
                }
            )

    diagnostics = pd.DataFrame(rows)
    summary = _forecast_bias_summary(diagnostics)
    return OptionsSurfaceForecastBiasDiagnostics(rows=diagnostics, summary=summary)


def _surface_bucket_row(
    group: pd.DataFrame,
    dashboard_row: pd.Series,
    cfg: OptionsSurfaceStateConfig,
) -> dict[str, object]:
    work = group.copy()
    underlying = _finite_median(work["options_underlying_price"])
    work["options_distance_from_underlying_points"] = pd.to_numeric(
        work.get("options_distance_from_underlying_points", work["options_strike"] - underlying),
        errors="coerce",
    )
    work["abs_distance"] = work["options_distance_from_underlying_points"].abs()
    work["surface_weight"] = pd.to_numeric(work.get("options_total_oi", np.nan), errors="coerce").fillna(0.0)
    if not work["surface_weight"].gt(0.0).any():
        work["surface_weight"] = 1.0
    work = work.sort_values(["abs_distance", "surface_weight"], ascending=[True, False])
    atm = work.iloc[0]

    avg_iv = _finite_float(dashboard_row.get("options_avg_iv", np.nan))
    if not np.isfinite(avg_iv):
        avg_iv = _weighted_average(work["options_avg_iv"], work["surface_weight"])
    put_skew = _weighted_average(work["options_put_avg_iv"], work["surface_weight"]) - _weighted_average(
        work["options_call_avg_iv"],
        work["surface_weight"],
    )
    atm_call_iv = _finite_float(atm.get("options_call_avg_iv", np.nan))
    atm_put_iv = _finite_float(atm.get("options_put_avg_iv", np.nan))
    atm_skew = atm_put_iv - atm_call_iv if np.isfinite(atm_put_iv) and np.isfinite(atm_call_iv) else np.nan
    shape = _surface_shape_metrics(work, underlying, _finite_float(atm["options_avg_iv"]), cfg)
    return {
        "options_trade_date": str(atm.get("options_trade_date", dashboard_row.get("options_trade_date", ""))),
        "options_available_time": pd.Timestamp(atm["options_available_time"]),
        "options_dte_bucket": str(atm.get("options_dte_bucket", "all")),
        "options_surface_underlying_price": underlying,
        "options_surface_avg_iv": avg_iv,
        "options_surface_atm_strike": _finite_float(atm["options_strike"]),
        "options_surface_atm_distance_points": _finite_float(atm["options_distance_from_underlying_points"]),
        "options_surface_atm_iv": _finite_float(atm["options_avg_iv"]),
        "options_surface_atm_call_iv": atm_call_iv,
        "options_surface_atm_put_iv": atm_put_iv,
        "options_surface_atm_put_call_iv_skew": atm_skew,
        "options_surface_put_call_iv_skew": put_skew,
        "options_surface_iv_dispersion": shape["iv_dispersion"],
        "options_surface_smile_curvature": shape["smile_curvature"],
        "options_surface_smile_quadratic_coef": shape["smile_quadratic_coef"],
        "options_surface_iv_slope": shape["iv_slope"],
        "options_surface_strike_count": int(len(work)),
        "options_surface_valid_iv_strikes": int(pd.to_numeric(work["options_avg_iv"], errors="coerce").notna().sum()),
    }


def _surface_shape_metrics(
    work: pd.DataFrame,
    underlying: float,
    atm_iv: float,
    cfg: OptionsSurfaceStateConfig,
) -> dict[str, float]:
    iv = pd.to_numeric(work["options_avg_iv"], errors="coerce")
    weight = pd.to_numeric(work["surface_weight"], errors="coerce").fillna(0.0)
    valid = iv.notna() & np.isfinite(underlying) & (underlying > 0.0)
    if not bool(valid.any()):
        return {
            "iv_dispersion": np.nan,
            "smile_curvature": np.nan,
            "smile_quadratic_coef": np.nan,
            "iv_slope": np.nan,
        }
    iv_valid = iv.loc[valid]
    weight_valid = weight.loc[valid]
    dispersion = _weighted_std(iv_valid, weight_valid)
    lower = valid & pd.to_numeric(work["options_distance_from_underlying_points"], errors="coerce").lt(0.0)
    upper = valid & pd.to_numeric(work["options_distance_from_underlying_points"], errors="coerce").gt(0.0)
    lower_iv = _weighted_average(iv.loc[lower], weight.loc[lower]) if bool(lower.any()) else np.nan
    upper_iv = _weighted_average(iv.loc[upper], weight.loc[upper]) if bool(upper.any()) else np.nan
    wing_iv = (lower_iv + upper_iv) / 2.0 if np.isfinite(lower_iv) and np.isfinite(upper_iv) else np.nan
    curvature = wing_iv - atm_iv if np.isfinite(wing_iv) and np.isfinite(atm_iv) else np.nan

    coef = np.nan
    slope = np.nan
    if int(valid.sum()) >= int(cfg.min_strikes_for_shape):
        x = (pd.to_numeric(work.loc[valid, "options_strike"], errors="coerce") / float(underlying) - 1.0).to_numpy(
            dtype=float
        )
        y = iv.loc[valid].to_numpy(dtype=float)
        w = weight_valid.to_numpy(dtype=float)
        clean = np.isfinite(x) & np.isfinite(y)
        if int(clean.sum()) >= int(cfg.min_strikes_for_shape) and np.nanmax(x[clean]) > np.nanmin(x[clean]):
            weights = np.sqrt(np.where(np.isfinite(w[clean]) & (w[clean] > 0.0), w[clean], 1.0))
            degree = 2 if int(clean.sum()) >= 3 else 1
            coefficients = np.polyfit(x[clean], y[clean], deg=degree, w=weights)
            if degree == 2:
                coef = float(coefficients[0])
                slope = float(coefficients[1])
            else:
                slope = float(coefficients[0])
    return {
        "iv_dispersion": dispersion,
        "smile_curvature": float(curvature) if np.isfinite(curvature) else np.nan,
        "smile_quadratic_coef": coef,
        "iv_slope": slope,
    }


def _add_term_structure_state(state: pd.DataFrame, cfg: OptionsSurfaceStateConfig) -> pd.DataFrame:
    out = state.copy()
    out["options_surface_short_dte_bucket"] = pd.Series("unknown", index=out.index, dtype=object)
    out["options_surface_long_dte_bucket"] = pd.Series("unknown", index=out.index, dtype=object)
    out["options_surface_short_atm_iv"] = np.nan
    out["options_surface_long_atm_iv"] = np.nan
    out["options_surface_short_long_iv_spread"] = np.nan
    out["options_surface_short_long_iv_ratio"] = np.nan
    out["options_surface_term_state"] = pd.Series("unknown", index=out.index, dtype=object)

    for available_time, group in out.groupby("options_available_time", sort=True):
        short_row = _first_bucket(group, cfg.short_dte_buckets)
        long_row = _first_bucket(group, cfg.long_dte_buckets)
        if short_row is None or long_row is None:
            continue
        short_iv = _finite_float(short_row["options_surface_atm_iv"])
        long_iv = _finite_float(long_row["options_surface_atm_iv"])
        spread = short_iv - long_iv if np.isfinite(short_iv) and np.isfinite(long_iv) else np.nan
        ratio = short_iv / long_iv if np.isfinite(short_iv) and np.isfinite(long_iv) and long_iv != 0 else np.nan
        idx = out["options_available_time"].eq(available_time)
        out.loc[idx, "options_surface_short_dte_bucket"] = str(short_row["options_dte_bucket"])
        out.loc[idx, "options_surface_long_dte_bucket"] = str(long_row["options_dte_bucket"])
        out.loc[idx, "options_surface_short_atm_iv"] = short_iv
        out.loc[idx, "options_surface_long_atm_iv"] = long_iv
        out.loc[idx, "options_surface_short_long_iv_spread"] = spread
        out.loc[idx, "options_surface_short_long_iv_ratio"] = ratio
        out.loc[idx, "options_surface_term_state"] = _term_state(spread, cfg)
    return out


def _add_trailing_realized_vol(
    state: pd.DataFrame,
    futures_bars: pd.DataFrame,
    cfg: OptionsSurfaceStateConfig,
) -> pd.DataFrame:
    bars = _prepare_futures_bars(futures_bars)
    close = pd.to_numeric(bars["close"], errors="coerce")
    log_return = np.log(close).diff()
    bars["options_surface_trailing_realized_vol"] = log_return.rolling(
        int(cfg.realized_vol_window_bars),
        min_periods=int(cfg.realized_vol_min_bars),
    ).std(ddof=0) * np.sqrt(float(cfg.realized_vol_annualization_bars))
    merged = pd.merge_asof(
        state.sort_values("options_available_time"),
        bars[["time", "options_surface_trailing_realized_vol"]].dropna(subset=["time"]).sort_values("time"),
        left_on="options_available_time",
        right_on="time",
        direction="backward",
    ).drop(columns=["time"], errors="ignore")
    merged["options_surface_iv_rv_premium"] = (
        pd.to_numeric(merged["options_surface_atm_iv"], errors="coerce")
        - pd.to_numeric(merged["options_surface_trailing_realized_vol"], errors="coerce")
    )
    merged["options_surface_iv_rv_ratio"] = _safe_divide(
        merged["options_surface_atm_iv"],
        merged["options_surface_trailing_realized_vol"],
    )
    return merged.sort_values(["options_available_time", "options_dte_bucket"]).reset_index(drop=True)


def _forecast_bias_summary(diagnostics: pd.DataFrame) -> pd.DataFrame:
    if diagnostics.empty:
        return pd.DataFrame()
    valid = diagnostics.dropna(subset=["options_surface_iv_forecast_bias"]).copy()
    if valid.empty:
        return pd.DataFrame()
    grouped = valid.groupby(["forecast_horizon_bars", "options_dte_bucket"], sort=True)
    return grouped.agg(
        observations=("options_surface_iv_forecast_bias", "size"),
        median_atm_iv=("options_surface_atm_iv", "median"),
        median_future_realized_vol=("future_realized_vol", "median"),
        median_iv_forecast_bias=("options_surface_iv_forecast_bias", "median"),
        mean_iv_forecast_bias=("options_surface_iv_forecast_bias", "mean"),
        iv_over_forecast_pct=(
            "options_surface_iv_forecast_bias",
            lambda s: float((pd.to_numeric(s, errors="coerce") > 0.0).mean()),
        ),
    ).reset_index()


def _prepare_dashboard(dashboard: pd.DataFrame) -> pd.DataFrame:
    if dashboard.empty:
        return dashboard.copy()
    required = {"options_available_time"}
    missing = required.difference(dashboard.columns)
    if missing:
        raise ValueError(f"dashboard missing required columns: {sorted(missing)}")
    out = dashboard.copy()
    out["options_available_time"] = _naive_datetime_ns(out["options_available_time"])
    if "options_dte_bucket" not in out.columns:
        out["options_dte_bucket"] = "all"
    if "options_trade_date" not in out.columns:
        out["options_trade_date"] = out["options_available_time"].dt.date.astype(str)
    for col in ("options_avg_iv", "options_underlying_price"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["options_available_time"]).reset_index(drop=True)


def _prepare_strike_surface(strike_surface: pd.DataFrame) -> pd.DataFrame:
    if strike_surface.empty:
        return strike_surface.copy()
    required = {"options_available_time", "options_underlying_price", "options_strike", "options_avg_iv"}
    missing = required.difference(strike_surface.columns)
    if missing:
        raise ValueError(f"strike surface missing required columns: {sorted(missing)}")
    out = strike_surface.copy()
    out["options_available_time"] = _naive_datetime_ns(out["options_available_time"])
    if "options_dte_bucket" not in out.columns:
        out["options_dte_bucket"] = "all"
    if "options_trade_date" not in out.columns:
        out["options_trade_date"] = out["options_available_time"].dt.date.astype(str)
    for col in (
        "options_underlying_price",
        "options_strike",
        "options_distance_from_underlying_points",
        "options_avg_iv",
        "options_call_avg_iv",
        "options_put_avg_iv",
        "options_total_oi",
    ):
        if col not in out.columns:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")
    distance = out["options_distance_from_underlying_points"]
    out["options_distance_from_underlying_points"] = distance.where(
        distance.notna(),
        out["options_strike"] - out["options_underlying_price"],
    )
    return out.dropna(subset=["options_available_time", "options_strike", "options_avg_iv"]).reset_index(drop=True)


def _prepare_futures_bars(futures_bars: pd.DataFrame) -> pd.DataFrame:
    required = {"time", "close"}
    missing = required.difference(futures_bars.columns)
    if missing:
        raise ValueError(f"futures bars missing required columns: {sorted(missing)}")
    out = futures_bars.loc[:, ["time", "close"]].copy()
    out["time"] = _naive_datetime_ns(out["time"])
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    return out.dropna(subset=["time", "close"]).sort_values("time").reset_index(drop=True)


def _dashboard_lookup(dashboard: pd.DataFrame) -> dict[tuple[pd.Timestamp, str], pd.Series]:
    lookup: dict[tuple[pd.Timestamp, str], pd.Series] = {}
    if dashboard.empty:
        return lookup
    for row in dashboard.itertuples(index=False):
        key = (pd.Timestamp(getattr(row, "options_available_time")), str(getattr(row, "options_dte_bucket", "all")))
        lookup[key] = pd.Series(row._asdict())
    return lookup


def _first_bucket(group: pd.DataFrame, buckets: tuple[str, ...]) -> pd.Series | None:
    for bucket in buckets:
        rows = group.loc[group["options_dte_bucket"].astype(str).eq(str(bucket))]
        if not rows.empty:
            return rows.iloc[0]
    return None


def _read_frame(value: pd.DataFrame | Path | str) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    path = Path(value)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _naive_datetime_ns(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce")
    if getattr(dt.dtype, "tz", None) is not None:
        dt = dt.dt.tz_convert("America/New_York").dt.tz_localize(None)
    return dt.astype("datetime64[ns]")


def _weighted_average(values: pd.Series, weights: pd.Series) -> float:
    numeric_values = pd.to_numeric(values, errors="coerce")
    numeric_weights = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    valid = numeric_values.notna() & numeric_weights.gt(0.0)
    if bool(valid.any()):
        return float(np.average(numeric_values.loc[valid], weights=numeric_weights.loc[valid]))
    return float(numeric_values.mean()) if bool(numeric_values.notna().any()) else np.nan


def _weighted_std(values: pd.Series, weights: pd.Series) -> float:
    numeric_values = pd.to_numeric(values, errors="coerce")
    numeric_weights = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    valid = numeric_values.notna() & numeric_weights.gt(0.0)
    if not bool(valid.any()):
        clean = numeric_values.dropna()
        return float(clean.std(ddof=0)) if len(clean) > 1 else np.nan
    vals = numeric_values.loc[valid].to_numpy(dtype=float)
    wts = numeric_weights.loc[valid].to_numpy(dtype=float)
    if vals.size <= 1:
        return 0.0
    avg = np.average(vals, weights=wts)
    return float(np.sqrt(np.average((vals - avg) ** 2, weights=wts)))


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    num = pd.to_numeric(numerator, errors="coerce")
    den = pd.to_numeric(denominator, errors="coerce").replace(0.0, np.nan)
    return (num / den).replace([np.inf, -np.inf], np.nan)


def _finite_float(value: object) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return np.nan
    return out if np.isfinite(out) else np.nan


def _finite_median(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return float(values.median()) if not values.empty else np.nan


def _label_skew_state(skew: pd.Series, cfg: OptionsSurfaceStateConfig) -> pd.Series:
    value = pd.to_numeric(skew, errors="coerce")
    state = pd.Series("unknown", index=value.index, dtype=object)
    state.loc[value.notna()] = "balanced_call_put_iv"
    state.loc[value.ge(float(cfg.skew_abs_threshold))] = "put_iv_rich"
    state.loc[value.le(-float(cfg.skew_abs_threshold))] = "call_iv_rich"
    return state


def _label_smile_state(curvature: pd.Series, cfg: OptionsSurfaceStateConfig) -> pd.Series:
    value = pd.to_numeric(curvature, errors="coerce")
    state = pd.Series("unknown", index=value.index, dtype=object)
    state.loc[value.notna()] = "flat_smile"
    state.loc[value.ge(float(cfg.smile_curvature_threshold))] = "convex_smile"
    state.loc[value.le(-float(cfg.smile_curvature_threshold))] = "inverted_smile"
    return state


def _label_premium_state(premium: pd.Series, cfg: OptionsSurfaceStateConfig) -> pd.Series:
    value = pd.to_numeric(premium, errors="coerce")
    state = pd.Series("unknown", index=value.index, dtype=object)
    state.loc[value.notna()] = "modest_iv_premium"
    state.loc[value.le(float(cfg.cheap_iv_premium_threshold))] = "iv_discount_to_trailing_rv"
    state.loc[value.ge(float(cfg.rich_iv_premium_threshold))] = "rich_iv_premium"
    return state


def _term_state(spread: float, cfg: OptionsSurfaceStateConfig) -> str:
    if not np.isfinite(spread):
        return "unknown"
    if spread >= float(cfg.term_spread_threshold):
        return "short_dte_iv_rich"
    if spread <= -float(cfg.term_spread_threshold):
        return "long_dte_iv_rich"
    return "flat_term_structure"


def _forecast_bias_state(bias: float, cfg: OptionsSurfaceStateConfig) -> str:
    if not np.isfinite(bias):
        return "unknown"
    if bias >= float(cfg.forecast_bias_threshold):
        return "iv_over_forecast_realized"
    if bias <= -float(cfg.forecast_bias_threshold):
        return "iv_under_forecast_realized"
    return "near_realized"


def _label_composite_surface_state(state: pd.DataFrame) -> pd.Series:
    out = pd.Series("normal_options_surface", index=state.index, dtype=object)
    out.loc[state["options_surface_skew_state"].eq("put_iv_rich")] = "put_skew_rich_options_surface"
    out.loc[state["options_surface_smile_state"].eq("convex_smile")] = "convex_smile_options_surface"
    out.loc[state["options_surface_term_state"].eq("short_dte_iv_rich")] = "short_dte_rich_options_surface"
    out.loc[state["options_surface_premium_state"].eq("rich_iv_premium")] = "rich_premium_options_surface"
    out.loc[state["options_surface_premium_state"].eq("iv_discount_to_trailing_rv")] = "cheap_options_surface"
    return out


def _validate_config(cfg: OptionsSurfaceStateConfig) -> None:
    if int(cfg.min_strikes_for_shape) <= 1:
        raise ValueError("min_strikes_for_shape must be greater than 1")
    if int(cfg.min_forward_realized_bars) <= 1:
        raise ValueError("min_forward_realized_bars must be greater than 1")
    if int(cfg.realized_vol_window_bars) <= 1:
        raise ValueError("realized_vol_window_bars must be greater than 1")
    if int(cfg.realized_vol_min_bars) <= 1:
        raise ValueError("realized_vol_min_bars must be greater than 1")
    if int(cfg.realized_vol_min_bars) > int(cfg.realized_vol_window_bars):
        raise ValueError("realized_vol_min_bars cannot exceed realized_vol_window_bars")
    if float(cfg.realized_vol_annualization_bars) <= 0.0:
        raise ValueError("realized_vol_annualization_bars must be positive")
