from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


DEFAULT_HORIZONS_MINUTES = (1, 5, 15)


@dataclass(frozen=True)
class SignalAdverseSelectionDiagnostics:
    events: pd.DataFrame
    summary: pd.DataFrame


@dataclass(frozen=True)
class TradeSignMemoryDiagnostics:
    autocorr: pd.DataFrame
    summary: pd.DataFrame


@dataclass(frozen=True)
class MicrostructureDiagnostics:
    depth_exhaustion_summary: pd.DataFrame
    microstructure_cost_state_summary: pd.DataFrame
    book_imbalance_summary: pd.DataFrame
    spread_reversion: pd.DataFrame
    trade_sign_autocorr: pd.DataFrame
    trade_sign_memory_summary: pd.DataFrame
    price_change_buckets: pd.DataFrame
    signal_adverse_selection_events: pd.DataFrame
    signal_adverse_selection_summary: pd.DataFrame
    signal_cost_state_summary: pd.DataFrame
    signal_options_context_summary: pd.DataFrame


@dataclass(frozen=True)
class MicrostructureDiagnosticPaths:
    depth_exhaustion_summary_csv: Path
    microstructure_cost_state_summary_csv: Path
    book_imbalance_summary_csv: Path
    spread_reversion_csv: Path
    trade_sign_autocorr_csv: Path
    trade_sign_memory_summary_csv: Path
    price_change_buckets_csv: Path
    signal_adverse_selection_events_csv: Path
    signal_adverse_selection_summary_csv: Path
    signal_cost_state_summary_csv: Path
    signal_options_context_summary_csv: Path
    report_md: Path


def book_imbalance(
    bid_size: float | pd.Series | np.ndarray,
    ask_size: float | pd.Series | np.ndarray,
) -> float | pd.Series | np.ndarray:
    """Top-book imbalance in [-1, 1], positive when displayed bid size dominates."""
    bid = pd.to_numeric(bid_size, errors="coerce") if isinstance(bid_size, pd.Series) else np.asarray(bid_size, dtype=float)
    ask = pd.to_numeric(ask_size, errors="coerce") if isinstance(ask_size, pd.Series) else np.asarray(ask_size, dtype=float)
    denom = bid + ask
    values = np.where(denom > 0.0, (bid - ask) / denom, np.nan)
    if isinstance(bid_size, pd.Series):
        return pd.Series(values, index=bid_size.index)
    if isinstance(ask_size, pd.Series):
        return pd.Series(values, index=ask_size.index)
    if np.ndim(values) == 0:
        return float(values)
    return values


def build_book_imbalance_summary(minute_stats: pd.DataFrame) -> pd.DataFrame:
    """Summarize top-book imbalance as execution context, not as alpha evidence."""
    work = _prepare_minute_stats(minute_stats)
    if work.empty:
        return pd.DataFrame()
    if "median_top_book_imbalance" not in work.columns:
        if {"mean_bid_size", "mean_ask_size"}.issubset(work.columns):
            work["median_top_book_imbalance"] = book_imbalance(work["mean_bid_size"], work["mean_ask_size"])
        else:
            raise ValueError("minute stats must include median_top_book_imbalance or mean_bid_size/mean_ask_size")

    imbalance = pd.to_numeric(work["median_top_book_imbalance"], errors="coerce")
    work = work.loc[imbalance.notna()].copy()
    if work.empty:
        return pd.DataFrame()
    work["imbalance_bucket"] = pd.cut(
        imbalance.loc[work.index],
        bins=[-np.inf, -0.50, -0.10, 0.10, 0.50, np.inf],
        labels=["ask_heavy_extreme", "ask_heavy", "balanced", "bid_heavy", "bid_heavy_extreme"],
    ).astype("string")
    flow_col = _resolve_flow_column(work, required=False)
    if flow_col is None:
        work["_signed_flow_for_summary"] = np.nan
        flow_col = "_signed_flow_for_summary"
    grouped = work.groupby("imbalance_bucket", observed=False, sort=False)
    out = grouped.agg(
        minutes=("minute", "size"),
        trade_dates=("trade_date", "nunique"),
        median_imbalance=("median_top_book_imbalance", "median"),
        mean_imbalance=("median_top_book_imbalance", "mean"),
        median_spread_points=("median_spread_points", "median"),
        p95_spread_points=("p95_spread_points", "median"),
        median_trade_count=("trade_count", "median"),
        median_signed_flow=(flow_col, "median"),
    ).reset_index()
    total = float(len(work))
    out["minutes_pct"] = np.where(total > 0.0, out["minutes"].astype(float) / total, np.nan)
    return out


def build_depth_exhaustion_summary(minute_stats: pd.DataFrame) -> pd.DataFrame:
    """Summarize trades that were large enough to exhaust displayed best-depth."""
    work = _active_contract_minute_stats(_prepare_minute_stats(minute_stats))
    required = {
        "top_book_depth_exhausted_trade_pct",
        "top_book_depth_exhausted_size_share",
        "zero_impact_depth_supported_trade_pct",
    }
    if work.empty or not required.issubset(work.columns):
        return pd.DataFrame()
    exhaustion = pd.to_numeric(work["top_book_depth_exhausted_trade_pct"], errors="coerce")
    work = work.loc[exhaustion.notna()].copy()
    if work.empty:
        return pd.DataFrame()
    work["depth_exhaustion_bucket"] = pd.cut(
        exhaustion.loc[work.index],
        bins=[-np.inf, 0.0, 0.10, 0.30, 0.60, np.inf],
        labels=["none", "low", "moderate", "high", "extreme"],
    ).astype("string")
    grouped = work.groupby("depth_exhaustion_bucket", observed=False, sort=False)
    out = grouped.agg(
        minutes=("minute", "size"),
        trade_dates=("trade_date", "nunique"),
        total_trades=("trade_count", "sum"),
        total_trade_size=("trade_size", "sum"),
        median_depth_exhausted_trade_pct=("top_book_depth_exhausted_trade_pct", "median"),
        median_depth_exhausted_size_share=("top_book_depth_exhausted_size_share", "median"),
        median_zero_impact_supported_trade_pct=("zero_impact_depth_supported_trade_pct", "median"),
        median_trade_size_to_opposite_best_size=("median_trade_size_to_opposite_best_size", "median"),
        p95_trade_size_to_opposite_best_size=("p95_trade_size_to_opposite_best_size", "median"),
        median_spread_points=("median_spread_points", "median"),
        p95_spread_points=("p95_spread_points", "median"),
    ).reset_index()
    total = float(len(work))
    out["minutes_pct"] = np.where(total > 0.0, out["minutes"].astype(float) / total, np.nan)
    return out


def build_microstructure_cost_state(
    minute_stats: pd.DataFrame,
    *,
    aggressive_flow_minute_stats: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a per-minute composite execution-cost state from top-book evidence."""
    market = _active_contract_minute_stats(_prepare_minute_stats(minute_stats))
    if market.empty:
        return pd.DataFrame()
    cols = [
        "symbol",
        "minute",
        "trade_date",
        "median_spread_points",
        "p95_spread_points",
        "p95_abs_trade_price_vs_mid",
        "median_top_book_imbalance",
        "trade_count",
        "top_book_depth_exhausted_trade_pct",
        "top_book_depth_exhausted_size_share",
        "zero_impact_depth_supported_trade_pct",
    ]
    state = market.loc[:, [col for col in cols if col in market.columns]].copy()
    if aggressive_flow_minute_stats is not None and not aggressive_flow_minute_stats.empty:
        flow = _active_contract_minute_stats(_prepare_minute_stats(aggressive_flow_minute_stats))
        flow_cols = [
            "symbol",
            "minute",
            "raw_b_minus_a_trade_size_share",
            "raw_b_minus_a_trade_size",
            "trade_size",
            "trade_price_change_points",
        ]
        flow = flow.loc[:, [col for col in flow_cols if col in flow.columns]].copy()
        if not flow.empty:
            state = state.merge(
                flow.rename(columns={"raw_b_minus_a_trade_size_share": "aggressive_flow_share"}),
                on=["symbol", "minute"],
                how="left",
                suffixes=("", "_flow"),
            )

    for col in (
        "median_spread_points",
        "p95_spread_points",
        "p95_abs_trade_price_vs_mid",
        "median_top_book_imbalance",
        "trade_count",
        "top_book_depth_exhausted_trade_pct",
        "top_book_depth_exhausted_size_share",
        "zero_impact_depth_supported_trade_pct",
        "aggressive_flow_share",
        "trade_price_change_points",
    ):
        if col not in state.columns:
            state[col] = np.nan
        state[col] = pd.to_numeric(state[col], errors="coerce")

    state["abs_top_book_imbalance"] = state["median_top_book_imbalance"].abs()
    state["abs_aggressive_flow_share"] = state["aggressive_flow_share"].abs()
    state["abs_trade_price_change_points"] = state["trade_price_change_points"].abs()

    score_inputs = {
        "spread_score": state["median_spread_points"],
        "tail_spread_score": state["p95_spread_points"],
        "trade_vs_mid_score": state["p95_abs_trade_price_vs_mid"],
        "imbalance_score": state["abs_top_book_imbalance"],
        "depth_exhaustion_score": state["top_book_depth_exhausted_trade_pct"],
        "aggressive_flow_score": state["abs_aggressive_flow_share"],
        "price_change_score": state["abs_trade_price_change_points"],
    }
    score_cols: list[str] = []
    for name, series in score_inputs.items():
        score = _percentile_rank(series)
        if score.notna().any():
            state[name] = score
            score_cols.append(name)
    trade_count_score = 1.0 - _percentile_rank(state["trade_count"])
    if trade_count_score.notna().any():
        state["trade_scarcity_score"] = trade_count_score
        score_cols.append("trade_scarcity_score")
    if not score_cols:
        return pd.DataFrame()

    state["microstructure_cost_score"] = state[score_cols].mean(axis=1, skipna=True)
    dislocated = (
        state["microstructure_cost_score"].ge(0.92)
        | (
            state.get("spread_score", pd.Series(np.nan, index=state.index)).ge(0.95)
            & (
                state.get("depth_exhaustion_score", pd.Series(np.nan, index=state.index)).ge(0.80)
                | state.get("trade_vs_mid_score", pd.Series(np.nan, index=state.index)).ge(0.80)
            )
        )
    )
    state["microstructure_cost_state"] = np.select(
        [
            dislocated,
            state["microstructure_cost_score"].ge(0.85),
            state["microstructure_cost_score"].ge(0.70),
            state["microstructure_cost_score"].ge(0.50),
        ],
        ["dislocated", "fragile", "stressed", "elevated"],
        default="normal",
    )
    return state.sort_values(["symbol", "minute"]).reset_index(drop=True)


def build_microstructure_cost_state_summary(cost_state: pd.DataFrame) -> pd.DataFrame:
    if cost_state.empty:
        return pd.DataFrame()
    grouped = cost_state.groupby("microstructure_cost_state", sort=False)
    out = grouped.agg(
        minutes=("minute", "size"),
        trade_dates=("trade_date", "nunique"),
        median_cost_score=("microstructure_cost_score", "median"),
        p90_cost_score=("microstructure_cost_score", lambda s: float(s.quantile(0.90))),
        median_spread_points=("median_spread_points", "median"),
        p95_spread_points=("p95_spread_points", "median"),
        median_p95_trade_vs_mid_points=("p95_abs_trade_price_vs_mid", "median"),
        median_abs_top_book_imbalance=("abs_top_book_imbalance", "median"),
        median_depth_exhausted_trade_pct=("top_book_depth_exhausted_trade_pct", "median"),
        median_aggressive_flow_abs_share=("abs_aggressive_flow_share", "median"),
        median_trade_count=("trade_count", "median"),
    ).reset_index()
    total = float(len(cost_state))
    out["minutes_pct"] = np.where(total > 0.0, out["minutes"].astype(float) / total, np.nan)
    return out


def build_spread_reversion_stats(
    minute_stats: pd.DataFrame,
    *,
    horizons_minutes: Iterable[int] = DEFAULT_HORIZONS_MINUTES,
    spread_col: str = "median_spread_points",
) -> pd.DataFrame:
    """Measure whether wide spreads narrow over exact future minute horizons."""
    work = _prepare_minute_stats(minute_stats)
    if work.empty:
        return pd.DataFrame()
    if spread_col not in work.columns:
        raise ValueError(f"minute stats missing spread column: {spread_col}")
    work[spread_col] = pd.to_numeric(work[spread_col], errors="coerce")
    work = work.dropna(subset=["symbol", "minute", spread_col]).copy()
    if work.empty:
        return pd.DataFrame()
    work["spread_bucket"] = _spread_bucket(work[spread_col])
    right = work.loc[:, ["symbol", "minute", spread_col]].rename(columns={spread_col: "future_spread_points"})
    rows: list[pd.DataFrame] = []
    for horizon in _clean_horizons(horizons_minutes):
        left = work.copy()
        left["future_minute"] = left["minute"] + pd.Timedelta(minutes=int(horizon))
        merged = left.merge(
            right,
            left_on=["symbol", "future_minute"],
            right_on=["symbol", "minute"],
            how="left",
            suffixes=("", "_future_key"),
        )
        merged["spread_change_points"] = merged["future_spread_points"] - merged[spread_col]
        valid = merged.dropna(subset=["future_spread_points", "spread_change_points"]).copy()
        if valid.empty:
            continue
        grouped = valid.groupby("spread_bucket", observed=False, sort=False)
        summary = grouped.agg(
            observations=("spread_change_points", "size"),
            current_median_spread_points=(spread_col, "median"),
            future_median_spread_points=("future_spread_points", "median"),
            median_spread_change_points=("spread_change_points", "median"),
            mean_spread_change_points=("spread_change_points", "mean"),
            pct_spread_narrows=("spread_change_points", lambda s: float((s < 0.0).mean())),
            pct_spread_widens=("spread_change_points", lambda s: float((s > 0.0).mean())),
        ).reset_index()
        summary.insert(0, "horizon_minutes", int(horizon))
        rows.append(summary)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def build_trade_sign_memory_diagnostics(
    minute_stats: pd.DataFrame,
    *,
    max_lag: int = 30,
    flow_col: str | None = None,
) -> TradeSignMemoryDiagnostics:
    """Estimate trade-sign autocorrelation and a rough long-memory slope from signed flow."""
    work = _prepare_minute_stats(minute_stats)
    if work.empty:
        empty = pd.DataFrame()
        return TradeSignMemoryDiagnostics(autocorr=empty, summary=empty)
    flow_name = flow_col or _resolve_flow_column(work)
    if flow_name not in work.columns:
        raise ValueError(f"minute stats missing flow column: {flow_name}")
    work[flow_name] = pd.to_numeric(work[flow_name], errors="coerce")
    work = work.dropna(subset=["symbol", "minute", flow_name]).sort_values(["symbol", "minute"]).copy()
    if work.empty:
        empty = pd.DataFrame()
        return TradeSignMemoryDiagnostics(autocorr=empty, summary=empty)

    rows: list[dict[str, object]] = []
    max_lag = max(1, int(max_lag))
    for symbol, group in work.groupby("symbol", sort=True):
        signs = np.sign(group[flow_name].astype(float)).replace(0.0, np.nan).dropna()
        for lag in range(1, max_lag + 1):
            observations = max(0, len(signs) - lag)
            if observations >= 2:
                x = signs.iloc[:-lag]
                y = signs.iloc[lag:]
                if x.nunique(dropna=True) > 1 and y.nunique(dropna=True) > 1:
                    corr = float(pd.Series(x.to_numpy()).corr(pd.Series(y.to_numpy())))
                else:
                    corr = np.nan
            else:
                corr = np.nan
            rows.append(
                {
                    "symbol": symbol,
                    "lag": lag,
                    "observations": int(observations),
                    "trade_sign_autocorr": corr,
                    "flow_column": flow_name,
                }
            )
    autocorr = pd.DataFrame(rows)
    summary = estimate_long_memory_from_autocorr(autocorr)
    return TradeSignMemoryDiagnostics(autocorr=autocorr, summary=summary)


def estimate_long_memory_from_autocorr(autocorr: pd.DataFrame, *, min_positive_lags: int = 3) -> pd.DataFrame:
    if autocorr.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for symbol, group in autocorr.groupby("symbol", sort=True):
        clean = group.loc[
            pd.to_numeric(group["trade_sign_autocorr"], errors="coerce").gt(0.0)
            & pd.to_numeric(group["lag"], errors="coerce").gt(0)
        ].copy()
        if len(clean) >= int(min_positive_lags):
            x = np.log(clean["lag"].astype(float).to_numpy())
            y = np.log(clean["trade_sign_autocorr"].astype(float).to_numpy())
            slope, intercept = np.polyfit(x, y, deg=1)
            alpha = -float(slope)
            hurst = 1.0 - alpha / 2.0
        else:
            slope = np.nan
            intercept = np.nan
            alpha = np.nan
            hurst = np.nan
        lag1 = group.loc[group["lag"].eq(1), "trade_sign_autocorr"]
        rows.append(
            {
                "symbol": symbol,
                "positive_lags": int(len(clean)),
                "lag1_autocorr": float(lag1.iloc[0]) if not lag1.empty and pd.notna(lag1.iloc[0]) else np.nan,
                "loglog_slope": float(slope) if pd.notna(slope) else np.nan,
                "alpha_estimate": alpha,
                "hurst_estimate": hurst,
                "interpretation": _long_memory_interpretation(hurst),
            }
        )
    return pd.DataFrame(rows)


def build_price_change_buckets(
    minute_stats: pd.DataFrame,
    *,
    tick_size: float = 0.25,
    price_change_col: str = "trade_price_change_points",
    flow_col: str | None = None,
    pressure_threshold: float = 0.25,
) -> pd.DataFrame:
    """Bucket minute-level signed flow by whether trade prices changed with it."""
    work = _prepare_minute_stats(minute_stats)
    if work.empty:
        return pd.DataFrame()
    if price_change_col not in work.columns:
        return pd.DataFrame()
    flow_name = flow_col or _resolve_flow_column(work)
    if flow_name not in work.columns:
        raise ValueError(f"minute stats missing flow column: {flow_name}")
    work[price_change_col] = pd.to_numeric(work[price_change_col], errors="coerce")
    work[flow_name] = pd.to_numeric(work[flow_name], errors="coerce")
    work = work.dropna(subset=[price_change_col, flow_name]).copy()
    if work.empty:
        return pd.DataFrame()

    threshold = abs(float(pressure_threshold))
    tick = abs(float(tick_size))
    work["flow_pressure_bucket"] = np.select(
        [work[flow_name] >= threshold, work[flow_name] <= -threshold],
        ["bid_pressure", "ask_pressure"],
        default="balanced",
    )
    work["price_change_bucket"] = np.select(
        [work[price_change_col] >= tick, work[price_change_col] <= -tick],
        ["up", "down"],
        default="flat",
    )
    flow_sign = np.sign(work[flow_name].astype(float))
    price_sign = np.sign(work[price_change_col].astype(float))
    work["price_changing"] = work["price_change_bucket"].ne("flat")
    work["same_direction_price_change"] = (flow_sign * price_sign).gt(0.0) & work["price_changing"]

    grouped = work.groupby(["flow_pressure_bucket", "price_change_bucket"], sort=True)
    out = grouped.agg(
        minutes=("minute", "size"),
        trade_dates=("trade_date", "nunique"),
        total_trades=("trade_count", "sum"),
        total_trade_size=("trade_size", "sum"),
        median_flow=(flow_name, "median"),
        median_price_change_points=(price_change_col, "median"),
        median_abs_price_change_points=(price_change_col, lambda s: float(s.abs().median())),
        price_changing_pct=("price_changing", "mean"),
        same_direction_price_change_pct=("same_direction_price_change", "mean"),
    ).reset_index()
    total = float(len(work))
    out["minutes_pct"] = np.where(total > 0.0, out["minutes"].astype(float) / total, np.nan)
    return out


def classify_price_changing_trades(
    trades: pd.DataFrame,
    *,
    tick_size: float = 0.25,
    time_col: str = "ts_event",
    symbol_col: str = "symbol",
    side_col: str = "side",
    mid_col: str = "mid_price",
    price_col: str = "price",
) -> pd.DataFrame:
    """Classify event-level trades when raw or normalized TBBO rows are available."""
    if trades.empty:
        return pd.DataFrame()
    required = {time_col, symbol_col, side_col}
    missing = required.difference(trades.columns)
    if missing:
        raise ValueError(f"trades missing required columns: {sorted(missing)}")
    if mid_col not in trades.columns and price_col not in trades.columns:
        raise ValueError(f"trades must include {mid_col!r} or {price_col!r}")
    out = trades.copy()
    if "action" in out.columns:
        out = out.loc[out["action"].astype(str).eq("T")].copy()
    out[time_col] = _coerce_time(out[time_col])
    out = out.dropna(subset=[time_col, symbol_col]).sort_values([symbol_col, time_col]).reset_index(drop=True)
    ref_col = mid_col if mid_col in out.columns else price_col
    out[ref_col] = pd.to_numeric(out[ref_col], errors="coerce")
    out["next_reference_price"] = out.groupby(symbol_col)[ref_col].shift(-1)
    out["next_price_change_points"] = out["next_reference_price"] - out[ref_col]
    tick = abs(float(tick_size))
    out["price_change_bucket"] = np.select(
        [out["next_price_change_points"] >= tick, out["next_price_change_points"] <= -tick],
        ["up", "down"],
        default="flat",
    )
    side_sign = _side_sign(out[side_col])
    out["side_aligned_next_price_change_points"] = side_sign * out["next_price_change_points"]
    out["price_changing"] = out["price_change_bucket"].ne("flat")
    out["adverse_to_aggressor"] = out["side_aligned_next_price_change_points"].lt(0.0) & out["price_changing"]
    return out


def build_signal_adverse_selection_diagnostics(
    signals: pd.DataFrame,
    tbbo_minute_stats: pd.DataFrame,
    *,
    aggressive_flow_minute_stats: pd.DataFrame | None = None,
    horizons_minutes: Iterable[int] = DEFAULT_HORIZONS_MINUTES,
    signal_time_col: str = "time",
    signal_col: str = "candidate_signal",
    direction_col: str = "direction",
    active_col: str = "signal_active",
) -> SignalAdverseSelectionDiagnostics:
    if signals.empty or tbbo_minute_stats.empty:
        empty = pd.DataFrame()
        return SignalAdverseSelectionDiagnostics(events=empty, summary=empty)
    prepared_signals = _prepare_signal_frame(
        signals,
        signal_time_col=signal_time_col,
        signal_col=signal_col,
        direction_col=direction_col,
        active_col=active_col,
    )
    if prepared_signals.empty:
        empty = pd.DataFrame()
        return SignalAdverseSelectionDiagnostics(events=empty, summary=empty)

    market = _active_contract_minute_stats(_prepare_minute_stats(tbbo_minute_stats))
    if market.empty:
        empty = pd.DataFrame()
        return SignalAdverseSelectionDiagnostics(events=empty, summary=empty)
    cost_state = build_microstructure_cost_state(
        tbbo_minute_stats,
        aggressive_flow_minute_stats=aggressive_flow_minute_stats,
    )
    current_cols = [
        "symbol",
        "minute",
        "median_mid_price",
        "median_spread_points",
        "p95_spread_points",
        "median_top_book_imbalance",
        "median_abs_trade_price_vs_mid",
        "p95_abs_trade_price_vs_mid",
        "raw_b_minus_a_trade_size_share",
        "trade_count",
    ]
    current_cols = [col for col in current_cols if col in market.columns]
    current = market.loc[:, current_cols].copy().rename(columns={"minute": "current_minute"})

    signal_keys = ["signal_minute"]
    market_keys = ["current_minute"]
    if "symbol" in prepared_signals.columns and "symbol" in current.columns:
        signal_keys.insert(0, "symbol")
        market_keys.insert(0, "symbol")
    merged = prepared_signals.merge(
        current,
        left_on=signal_keys,
        right_on=market_keys,
        how="left",
        suffixes=("", "_market"),
    )
    merged = merged.drop(columns=[col for col in ("current_minute",) if col in merged.columns])

    if not cost_state.empty:
        cost_cols = [
            "symbol",
            "minute",
            "microstructure_cost_score",
            "microstructure_cost_state",
            "spread_score",
            "trade_vs_mid_score",
            "depth_exhaustion_score",
            "aggressive_flow_score",
            "trade_scarcity_score",
        ]
        cost_cols = [col for col in cost_cols if col in cost_state.columns]
        cost = cost_state.loc[:, cost_cols].rename(columns={"minute": "cost_state_minute"})
        cost_keys_left = ["signal_minute"]
        cost_keys_right = ["cost_state_minute"]
        if "symbol" in prepared_signals.columns and "symbol" in cost.columns:
            cost_keys_left.insert(0, "symbol")
            cost_keys_right.insert(0, "symbol")
        merged = merged.merge(
            cost,
            left_on=cost_keys_left,
            right_on=cost_keys_right,
            how="left",
            suffixes=("", "_cost_state"),
        )
        merged = merged.drop(columns=[col for col in ("cost_state_minute",) if col in merged.columns])

    if aggressive_flow_minute_stats is not None and not aggressive_flow_minute_stats.empty:
        flow = _prepare_minute_stats(aggressive_flow_minute_stats)
        flow_cols = [
            "symbol",
            "minute",
            "trade_price_change_points",
            "raw_b_minus_a_trade_size_share",
            "raw_b_minus_a_trade_size",
            "trade_size",
        ]
        flow_cols = [col for col in flow_cols if col in flow.columns]
        flow = flow.loc[:, flow_cols].rename(
            columns={
                "minute": "flow_minute",
                "raw_b_minus_a_trade_size_share": "aggressive_flow_share",
                "raw_b_minus_a_trade_size": "aggressive_flow_size",
                "trade_size": "aggressive_trade_size",
            }
        )
        flow_keys_left = ["signal_minute"]
        flow_keys_right = ["flow_minute"]
        if "symbol" in prepared_signals.columns and "symbol" in flow.columns:
            flow_keys_left.insert(0, "symbol")
            flow_keys_right.insert(0, "symbol")
        merged = merged.merge(
            flow,
            left_on=flow_keys_left,
            right_on=flow_keys_right,
            how="left",
            suffixes=("", "_flow"),
        )
        merged = merged.drop(columns=[col for col in ("flow_minute",) if col in merged.columns])

    future = market.loc[:, ["symbol", "minute", "median_mid_price"]].rename(
        columns={"minute": "future_lookup_minute", "median_mid_price": "future_mid_price"}
    )
    clean_horizons = _clean_horizons(horizons_minutes)
    immediate_horizon = int(clean_horizons[0])
    immediate = market.loc[:, ["symbol", "minute", "median_mid_price"]].rename(
        columns={"minute": "immediate_lookup_minute", "median_mid_price": "immediate_mid_price"}
    )
    rows: list[pd.DataFrame] = []
    for horizon in clean_horizons:
        base = merged.copy()
        base["horizon_minutes"] = int(horizon)
        base["future_minute"] = base["signal_minute"] + pd.Timedelta(minutes=int(horizon))
        base["immediate_minute"] = base["signal_minute"] + pd.Timedelta(minutes=immediate_horizon)
        left_keys = ["future_minute"]
        right_keys = ["future_lookup_minute"]
        if "symbol" in base.columns and "symbol" in future.columns:
            left_keys.insert(0, "symbol")
            right_keys.insert(0, "symbol")
        event = base.merge(
            future,
            left_on=left_keys,
            right_on=right_keys,
            how="left",
            suffixes=("", "_future"),
        )
        event = event.drop(columns=[col for col in ("future_lookup_minute",) if col in event.columns])
        immediate_left = ["immediate_minute"]
        immediate_right = ["immediate_lookup_minute"]
        if "symbol" in event.columns and "symbol" in immediate.columns:
            immediate_left.insert(0, "symbol")
            immediate_right.insert(0, "symbol")
        event = event.merge(
            immediate,
            left_on=immediate_left,
            right_on=immediate_right,
            how="left",
            suffixes=("", "_immediate"),
        )
        event = event.drop(columns=[col for col in ("immediate_lookup_minute",) if col in event.columns])
        event["signed_mid_move_points"] = event["direction_sign"] * (
            pd.to_numeric(event["future_mid_price"], errors="coerce")
            - pd.to_numeric(event["median_mid_price"], errors="coerce")
        )
        event["immediate_signed_mid_move_points"] = event["direction_sign"] * (
            pd.to_numeric(event["immediate_mid_price"], errors="coerce")
            - pd.to_numeric(event["median_mid_price"], errors="coerce")
        )
        spread = pd.to_numeric(event.get("median_spread_points", np.nan), errors="coerce")
        event["entry_half_spread_points"] = spread / 2.0
        event["signed_mid_move_after_spread_points"] = event["signed_mid_move_points"] - spread
        event["post_immediate_signed_move_change_points"] = (
            event["signed_mid_move_points"] - event["immediate_signed_mid_move_points"]
        )
        event["temporary_overshoot_points"] = np.where(
            int(horizon) > immediate_horizon,
            np.maximum(
                pd.to_numeric(event["immediate_signed_mid_move_points"], errors="coerce")
                - pd.to_numeric(event["signed_mid_move_points"], errors="coerce"),
                0.0,
            ),
            0.0,
        )
        event["impact_reverted_after_immediate"] = (
            int(horizon) > immediate_horizon
        ) & pd.to_numeric(event["temporary_overshoot_points"], errors="coerce").gt(0.0)
        event["limit_wait_opportunity_cost_points"] = np.maximum(
            pd.to_numeric(event["signed_mid_move_points"], errors="coerce"),
            0.0,
        )
        event["opportunity_cost_minus_entry_half_spread_points"] = (
            event["limit_wait_opportunity_cost_points"] - event["entry_half_spread_points"]
        )
        event["adverse_mid_move"] = event["signed_mid_move_points"].lt(0.0)
        event["adverse_after_spread"] = event["signed_mid_move_after_spread_points"].lt(0.0)
        rows.append(event)
    events = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    summary = build_signal_adverse_selection_summary(events)
    return SignalAdverseSelectionDiagnostics(events=events, summary=summary)


def build_signal_adverse_selection_summary(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    valid = events.dropna(subset=["signed_mid_move_points"]).copy()
    if valid.empty:
        return pd.DataFrame()
    optional_numeric = [
        "median_spread_points",
        "p95_abs_trade_price_vs_mid",
        "median_top_book_imbalance",
        "aggressive_flow_share",
        "microstructure_cost_score",
        "entry_half_spread_points",
        "immediate_signed_mid_move_points",
        "post_immediate_signed_move_change_points",
        "temporary_overshoot_points",
        "limit_wait_opportunity_cost_points",
        "opportunity_cost_minus_entry_half_spread_points",
    ]
    for col in optional_numeric:
        if col not in valid.columns:
            valid[col] = np.nan
    if "impact_reverted_after_immediate" not in valid.columns:
        valid["impact_reverted_after_immediate"] = False
    group_cols = ["horizon_minutes"]
    for optional in ("direction", "setup_tag"):
        if optional in valid.columns:
            group_cols.append(optional)
    grouped = valid.groupby(group_cols, dropna=False, sort=True)
    return grouped.agg(
        signals=("signed_mid_move_points", "size"),
        median_signed_mid_move_points=("signed_mid_move_points", "median"),
        p25_signed_mid_move_points=("signed_mid_move_points", lambda s: float(s.quantile(0.25))),
        p75_signed_mid_move_points=("signed_mid_move_points", lambda s: float(s.quantile(0.75))),
        median_immediate_signed_mid_move_points=("immediate_signed_mid_move_points", "median"),
        median_post_immediate_signed_move_change_points=("post_immediate_signed_move_change_points", "median"),
        median_temporary_overshoot_points=("temporary_overshoot_points", "median"),
        overshoot_reversion_pct=("impact_reverted_after_immediate", "mean"),
        adverse_mid_move_pct=("adverse_mid_move", "mean"),
        median_signed_mid_move_after_spread_points=("signed_mid_move_after_spread_points", "median"),
        adverse_after_spread_pct=("adverse_after_spread", "mean"),
        median_limit_wait_opportunity_cost_points=("limit_wait_opportunity_cost_points", "median"),
        p75_limit_wait_opportunity_cost_points=(
            "limit_wait_opportunity_cost_points",
            lambda s: float(s.quantile(0.75)),
        ),
        median_opportunity_cost_minus_entry_half_spread_points=(
            "opportunity_cost_minus_entry_half_spread_points",
            "median",
        ),
        median_microstructure_cost_score=("microstructure_cost_score", "median"),
        median_current_spread_points=("median_spread_points", "median"),
        median_current_p95_trade_vs_mid_points=("p95_abs_trade_price_vs_mid", "median"),
        median_top_book_imbalance=("median_top_book_imbalance", "median"),
        median_aggressive_flow_share=("aggressive_flow_share", "median"),
    ).reset_index()


def build_signal_cost_state_summary(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty or "microstructure_cost_state" not in events.columns:
        return pd.DataFrame()
    valid = events.dropna(subset=["signed_mid_move_points", "microstructure_cost_state"]).copy()
    if valid.empty:
        return pd.DataFrame()
    if "microstructure_cost_score" not in valid.columns:
        valid["microstructure_cost_score"] = np.nan
    grouped = valid.groupby(["horizon_minutes", "microstructure_cost_state"], dropna=False, sort=True)
    return grouped.agg(
        signals=("signed_mid_move_points", "size"),
        median_microstructure_cost_score=("microstructure_cost_score", "median"),
        median_current_spread_points=("median_spread_points", "median"),
        median_signed_mid_move_after_spread_points=("signed_mid_move_after_spread_points", "median"),
        adverse_after_spread_pct=("adverse_after_spread", "mean"),
        median_temporary_overshoot_points=("temporary_overshoot_points", "median"),
        overshoot_reversion_pct=("impact_reverted_after_immediate", "mean"),
        median_limit_wait_opportunity_cost_points=("limit_wait_opportunity_cost_points", "median"),
    ).reset_index()


def build_signal_options_context_summary(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    valid = events.dropna(subset=["signed_mid_move_points"]).copy()
    if valid.empty:
        return pd.DataFrame()
    option_cols = [
        col
        for col in [
            "options_gamma_environment",
            "options_gex_regime",
            "options_gamma_wall_role",
            "options_call_wall_role",
            "options_put_wall_role",
            "options_gamma_wall_pattern",
            "gamma_wall_side",
        ]
        if col in valid.columns and valid[col].notna().any()
    ]
    if not option_cols:
        return pd.DataFrame()
    grouped = valid.groupby(["horizon_minutes", *option_cols], dropna=False, sort=True)
    return grouped.agg(
        signals=("signed_mid_move_points", "size"),
        median_current_spread_points=("median_spread_points", "median"),
        median_current_p95_trade_vs_mid_points=("p95_abs_trade_price_vs_mid", "median"),
        median_microstructure_cost_score=("microstructure_cost_score", "median"),
        median_signed_mid_move_after_spread_points=("signed_mid_move_after_spread_points", "median"),
        adverse_after_spread_pct=("adverse_after_spread", "mean"),
        median_temporary_overshoot_points=("temporary_overshoot_points", "median"),
        median_limit_wait_opportunity_cost_points=("limit_wait_opportunity_cost_points", "median"),
    ).reset_index()


def build_microstructure_diagnostics(
    tbbo_minute_stats: pd.DataFrame,
    *,
    aggressive_flow_minute_stats: pd.DataFrame | None = None,
    signals: pd.DataFrame | None = None,
    horizons_minutes: Iterable[int] = DEFAULT_HORIZONS_MINUTES,
    max_autocorr_lag: int = 30,
    tick_size: float = 0.25,
) -> MicrostructureDiagnostics:
    flow_source = aggressive_flow_minute_stats if aggressive_flow_minute_stats is not None else tbbo_minute_stats
    cost_state = build_microstructure_cost_state(
        tbbo_minute_stats,
        aggressive_flow_minute_stats=aggressive_flow_minute_stats,
    )
    memory = build_trade_sign_memory_diagnostics(flow_source, max_lag=max_autocorr_lag)
    price_buckets = (
        build_price_change_buckets(aggressive_flow_minute_stats, tick_size=tick_size)
        if aggressive_flow_minute_stats is not None and not aggressive_flow_minute_stats.empty
        else pd.DataFrame()
    )
    if signals is not None and not signals.empty:
        adverse = build_signal_adverse_selection_diagnostics(
            signals,
            tbbo_minute_stats,
            aggressive_flow_minute_stats=aggressive_flow_minute_stats,
            horizons_minutes=horizons_minutes,
        )
    else:
        adverse = SignalAdverseSelectionDiagnostics(events=pd.DataFrame(), summary=pd.DataFrame())
    return MicrostructureDiagnostics(
        depth_exhaustion_summary=build_depth_exhaustion_summary(tbbo_minute_stats),
        microstructure_cost_state_summary=build_microstructure_cost_state_summary(cost_state),
        book_imbalance_summary=build_book_imbalance_summary(tbbo_minute_stats),
        spread_reversion=build_spread_reversion_stats(tbbo_minute_stats, horizons_minutes=horizons_minutes),
        trade_sign_autocorr=memory.autocorr,
        trade_sign_memory_summary=memory.summary,
        price_change_buckets=price_buckets,
        signal_adverse_selection_events=adverse.events,
        signal_adverse_selection_summary=adverse.summary,
        signal_cost_state_summary=build_signal_cost_state_summary(adverse.events),
        signal_options_context_summary=build_signal_options_context_summary(adverse.events),
    )


def write_microstructure_diagnostics(
    diagnostics: MicrostructureDiagnostics,
    out_dir: Path | str,
    *,
    artifact_name: str = "microstructure_diagnostics",
) -> MicrostructureDiagnosticPaths:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _slugify(artifact_name) or "microstructure_diagnostics"
    paths = MicrostructureDiagnosticPaths(
        depth_exhaustion_summary_csv=output_dir / f"{safe_name}_depth_exhaustion_summary.csv",
        microstructure_cost_state_summary_csv=output_dir / f"{safe_name}_cost_state_summary.csv",
        book_imbalance_summary_csv=output_dir / f"{safe_name}_book_imbalance_summary.csv",
        spread_reversion_csv=output_dir / f"{safe_name}_spread_reversion.csv",
        trade_sign_autocorr_csv=output_dir / f"{safe_name}_trade_sign_autocorr.csv",
        trade_sign_memory_summary_csv=output_dir / f"{safe_name}_trade_sign_memory_summary.csv",
        price_change_buckets_csv=output_dir / f"{safe_name}_price_change_buckets.csv",
        signal_adverse_selection_events_csv=output_dir / f"{safe_name}_signal_adverse_selection_events.csv",
        signal_adverse_selection_summary_csv=output_dir / f"{safe_name}_signal_adverse_selection_summary.csv",
        signal_cost_state_summary_csv=output_dir / f"{safe_name}_signal_cost_state_summary.csv",
        signal_options_context_summary_csv=output_dir / f"{safe_name}_signal_options_context_summary.csv",
        report_md=output_dir / f"{safe_name}.md",
    )
    diagnostics.depth_exhaustion_summary.to_csv(paths.depth_exhaustion_summary_csv, index=False)
    diagnostics.microstructure_cost_state_summary.to_csv(paths.microstructure_cost_state_summary_csv, index=False)
    diagnostics.book_imbalance_summary.to_csv(paths.book_imbalance_summary_csv, index=False)
    diagnostics.spread_reversion.to_csv(paths.spread_reversion_csv, index=False)
    diagnostics.trade_sign_autocorr.to_csv(paths.trade_sign_autocorr_csv, index=False)
    diagnostics.trade_sign_memory_summary.to_csv(paths.trade_sign_memory_summary_csv, index=False)
    diagnostics.price_change_buckets.to_csv(paths.price_change_buckets_csv, index=False)
    diagnostics.signal_adverse_selection_events.to_csv(paths.signal_adverse_selection_events_csv, index=False)
    diagnostics.signal_adverse_selection_summary.to_csv(paths.signal_adverse_selection_summary_csv, index=False)
    diagnostics.signal_cost_state_summary.to_csv(paths.signal_cost_state_summary_csv, index=False)
    diagnostics.signal_options_context_summary.to_csv(paths.signal_options_context_summary_csv, index=False)
    paths.report_md.write_text(render_microstructure_diagnostics_markdown(diagnostics), encoding="utf-8")
    return paths


def render_microstructure_diagnostics_markdown(diagnostics: MicrostructureDiagnostics) -> str:
    lines = [
        "# Microstructure Diagnostics",
        "",
        "This report is an execution and data-quality audit. It is not signal evidence and should not be used to mine TBBO alpha from a small sample.",
        "",
        "## Top-Book Depth Exhaustion",
        "",
        _frame_to_markdown(diagnostics.depth_exhaustion_summary, max_rows=12),
        "",
        "## Composite Cost State",
        "",
        _frame_to_markdown(diagnostics.microstructure_cost_state_summary, max_rows=12),
        "",
        "## Book Imbalance",
        "",
        _frame_to_markdown(diagnostics.book_imbalance_summary, max_rows=12),
        "",
        "## Spread Reversion",
        "",
        _frame_to_markdown(diagnostics.spread_reversion, max_rows=20),
        "",
        "## Trade-Sign Memory",
        "",
        _frame_to_markdown(diagnostics.trade_sign_memory_summary, max_rows=20),
        "",
        "## Price-Changing Buckets",
        "",
        _frame_to_markdown(diagnostics.price_change_buckets, max_rows=20),
        "",
        "## Signal-Aligned Adverse Selection",
        "",
        _frame_to_markdown(diagnostics.signal_adverse_selection_summary, max_rows=30),
        "",
        "## Signal Cost State",
        "",
        _frame_to_markdown(diagnostics.signal_cost_state_summary, max_rows=30),
        "",
        "## Options Context Cost Stress",
        "",
        _frame_to_markdown(diagnostics.signal_options_context_summary, max_rows=30),
        "",
        "## Guardrails",
        "",
        "- Use depth exhaustion, cost state, book imbalance, spread reversion, and price-changing buckets to stress fill assumptions.",
        "- Use trade-sign memory as a data diagnostic before considering it as a feature.",
        "- Use signal-aligned adverse selection, overshoot/reversion, and passive-entry opportunity cost to reject fragile fills, not to tune entries on the same sample.",
        "- Treat options/gamma context rows as execution-risk context, not directional proof.",
        "- Keep TBBO-derived diagnostics separated from candidate feature search unless a later protocol explicitly approves it.",
    ]
    return "\n".join(lines) + "\n"


def _prepare_minute_stats(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    if "minute" not in frame.columns:
        raise ValueError("minute stats must include a minute column")
    out = frame.copy()
    out["minute"] = _coerce_time(out["minute"])
    if "trade_date" not in out.columns:
        out["trade_date"] = out["minute"].dt.date.astype("string")
    if "symbol" not in out.columns:
        out["symbol"] = ""
    numeric_cols = [
        "median_mid_price",
        "median_spread_points",
        "p95_spread_points",
        "median_top_book_imbalance",
        "median_abs_trade_price_vs_mid",
        "p95_abs_trade_price_vs_mid",
        "raw_b_minus_a_trade_size_share",
        "raw_b_minus_a_trade_size",
        "raw_b_minus_a_trade_count",
        "trade_count",
        "trade_size",
        "mean_bid_size",
        "mean_ask_size",
        "trade_price_change_points",
        "median_opposite_best_size",
        "p25_opposite_best_size",
        "median_trade_size_to_opposite_best_size",
        "p95_trade_size_to_opposite_best_size",
        "top_book_depth_exhausted_trade_count",
        "top_book_depth_exhausted_trade_size",
        "top_book_excess_trade_size",
        "top_book_depth_exhausted_trade_pct",
        "top_book_depth_exhausted_size_share",
        "zero_impact_depth_supported_trade_count",
        "zero_impact_depth_supported_trade_pct",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "raw_b_minus_a_trade_size" not in out.columns and {
        "raw_b_side_trade_size",
        "raw_a_side_trade_size",
    }.issubset(out.columns):
        out["raw_b_minus_a_trade_size"] = (
            pd.to_numeric(out["raw_b_side_trade_size"], errors="coerce").fillna(0.0)
            - pd.to_numeric(out["raw_a_side_trade_size"], errors="coerce").fillna(0.0)
        )
    if "raw_b_minus_a_trade_count" not in out.columns and {
        "raw_b_side_count",
        "raw_a_side_count",
    }.issubset(out.columns):
        out["raw_b_minus_a_trade_count"] = (
            pd.to_numeric(out["raw_b_side_count"], errors="coerce").fillna(0.0)
            - pd.to_numeric(out["raw_a_side_count"], errors="coerce").fillna(0.0)
        )
    if "raw_b_minus_a_trade_size_share" not in out.columns:
        if {"raw_b_minus_a_trade_size", "trade_size"}.issubset(out.columns):
            trade_size = pd.to_numeric(out["trade_size"], errors="coerce")
            out["raw_b_minus_a_trade_size_share"] = np.where(
                trade_size > 0.0,
                pd.to_numeric(out["raw_b_minus_a_trade_size"], errors="coerce") / trade_size,
                np.nan,
            )
        elif {"raw_b_minus_a_trade_count", "trade_count"}.issubset(out.columns):
            trade_count = pd.to_numeric(out["trade_count"], errors="coerce")
            out["raw_b_minus_a_trade_size_share"] = np.where(
                trade_count > 0.0,
                pd.to_numeric(out["raw_b_minus_a_trade_count"], errors="coerce") / trade_count,
                np.nan,
            )
    return out.dropna(subset=["minute"])


def _active_contract_minute_stats(minute_stats: pd.DataFrame) -> pd.DataFrame:
    if minute_stats.empty:
        return pd.DataFrame()
    work = minute_stats.copy()
    if work["symbol"].astype(str).eq("").all():
        return work.sort_values("minute").reset_index(drop=True)
    trade_col = "trade_count" if "trade_count" in work.columns else None
    if trade_col is None:
        work["_active_rank_value"] = 1.0
    else:
        work["_active_rank_value"] = pd.to_numeric(work[trade_col], errors="coerce").fillna(0.0)
    daily = (
        work.groupby(["trade_date", "symbol"], sort=True)["_active_rank_value"]
        .sum()
        .reset_index()
        .sort_values(["trade_date", "_active_rank_value", "symbol"], ascending=[True, False, True])
    )
    active = daily.drop_duplicates(subset=["trade_date"], keep="first").loc[:, ["trade_date", "symbol"]]
    out = work.merge(active.assign(_active_contract=True), on=["trade_date", "symbol"], how="left")
    out = out.loc[out["_active_contract"].fillna(False)].drop(columns=["_active_contract", "_active_rank_value"])
    return out.sort_values("minute").reset_index(drop=True)


def _prepare_signal_frame(
    signals: pd.DataFrame,
    *,
    signal_time_col: str,
    signal_col: str,
    direction_col: str,
    active_col: str,
) -> pd.DataFrame:
    if signal_time_col not in signals.columns:
        raise ValueError(f"signals missing time column: {signal_time_col}")
    out = signals.copy()
    out[signal_time_col] = _coerce_time(out[signal_time_col])
    out["signal_minute"] = out[signal_time_col].dt.floor("min")
    out["direction_sign"] = _signal_direction_sign(out, signal_col=signal_col, direction_col=direction_col)
    if active_col in out.columns:
        active = out[active_col].astype(bool)
    else:
        active = out["direction_sign"].ne(0)
    out = out.loc[active & out["direction_sign"].ne(0)].copy()
    if direction_col in out.columns:
        out["direction"] = out[direction_col].astype(str)
    else:
        out["direction"] = np.where(out["direction_sign"].gt(0), "long", "short")
    return out.dropna(subset=["signal_minute"])


def _signal_direction_sign(frame: pd.DataFrame, *, signal_col: str, direction_col: str) -> pd.Series:
    if direction_col in frame.columns:
        raw = frame[direction_col].astype(str).str.lower()
        sign = pd.Series(0, index=frame.index, dtype=int)
        sign.loc[raw.isin(["long", "buy", "b", "bull", "bullish"])] = 1
        sign.loc[raw.isin(["short", "sell", "s", "bear", "bearish"])] = -1
        if signal_col in frame.columns:
            numeric = pd.to_numeric(frame[signal_col], errors="coerce")
            sign.loc[sign.eq(0) & numeric.gt(0)] = 1
            sign.loc[sign.eq(0) & numeric.lt(0)] = -1
        return sign
    if signal_col not in frame.columns:
        raise ValueError(f"signals must include {direction_col!r} or {signal_col!r}")
    numeric = pd.to_numeric(frame[signal_col], errors="coerce").fillna(0.0)
    return pd.Series(np.sign(numeric).astype(int), index=frame.index)


def _resolve_flow_column(frame: pd.DataFrame, *, required: bool = True) -> str | None:
    if "raw_b_minus_a_trade_size_share" in frame.columns:
        return "raw_b_minus_a_trade_size_share"
    if "raw_b_minus_a_trade_size" in frame.columns:
        return "raw_b_minus_a_trade_size"
    if "raw_b_minus_a_trade_count" in frame.columns:
        return "raw_b_minus_a_trade_count"
    if required:
        raise ValueError(
            "minute stats must include raw_b_minus_a_trade_size_share, "
            "raw_b_minus_a_trade_size, or raw_b_minus_a_trade_count"
        )
    return None


def _side_sign(side: pd.Series) -> pd.Series:
    raw = side.astype(str).str.upper()
    sign = pd.Series(0.0, index=side.index)
    sign.loc[raw.eq("B")] = 1.0
    sign.loc[raw.eq("A") | raw.eq("S")] = -1.0
    return sign


def _spread_bucket(spread: pd.Series) -> pd.Series:
    clean = pd.to_numeric(spread, errors="coerce")
    finite = clean.replace([np.inf, -np.inf], np.nan).dropna()
    if finite.empty:
        return pd.Series("unknown", index=spread.index, dtype="string")
    q50 = float(finite.quantile(0.50))
    q75 = float(finite.quantile(0.75))
    q90 = float(finite.quantile(0.90))
    bucket = np.select(
        [clean <= q50, clean <= q75, clean <= q90],
        ["tight", "normal", "wide"],
        default="extreme",
    )
    return pd.Series(bucket, index=spread.index, dtype="string")


def _percentile_rank(series: pd.Series) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if clean.notna().sum() < 2:
        return pd.Series(np.nan, index=series.index)
    return clean.rank(method="average", pct=True)


def _long_memory_interpretation(hurst: float) -> str:
    if pd.isna(hurst):
        return "insufficient_positive_autocorrelation"
    if hurst >= 0.60:
        return "persistent_order_flow"
    if hurst <= 0.45:
        return "mean_reverting_or_weak_memory"
    return "weak_or_ambiguous_memory"


def _clean_horizons(horizons: Iterable[int]) -> list[int]:
    clean = sorted({int(value) for value in horizons if int(value) > 0})
    return clean or list(DEFAULT_HORIZONS_MINUTES)


def _coerce_time(series: pd.Series) -> pd.Series:
    out = pd.to_datetime(series, errors="coerce")
    if getattr(out.dt, "tz", None) is not None:
        out = out.dt.tz_convert("America/New_York").dt.tz_localize(None)
    return out


def _frame_to_markdown(frame: pd.DataFrame, *, max_rows: int) -> str:
    if frame.empty:
        return "_No rows._"
    preview = frame.head(max_rows).copy()
    headers = [str(col) for col in preview.columns]
    rows = [[_markdown_cell(value) for value in row] for row in preview.itertuples(index=False, name=None)]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _markdown_cell(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in str(value)).strip("_")
