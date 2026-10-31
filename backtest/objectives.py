from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def profit_factor_from_pnl(pnl: pd.Series | np.ndarray) -> float:
    values = pd.Series(pnl, dtype=float).replace([np.inf, -np.inf], np.nan).dropna()
    wins = float(values[values > 0].sum())
    losses = abs(float(values[values < 0].sum()))
    if losses <= 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def _max_drawdown_pct(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / peak
    return float(np.nanmax(dd) * 100.0)


def bar_objective_metrics(
    pre_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    futures_specs: dict[str, Any],
    starting_capital: float,
) -> dict[str, float]:
    """
    Estimate objective metrics from per-bar strategy PnL rather than trade PnL.

    This follows the development idea from permutation-testing workflows: objective
    functions get a denser sample when each bar contributes a strategy return.
    The trade engine remains authoritative for realized PnL; these are research
    metrics for optimization and overfit detection.
    """
    if len(pre_df) < 3 or len(trades_df) == 0:
        return {
            "bar_profit_factor": 0.0,
            "bar_sharpe_ratio": 0.0,
            "bar_total_pnl": 0.0,
            "bar_max_drawdown": 0.0,
            "bar_exposure_pct": 0.0,
            "bar_observations": 0.0,
            "bar_exposed_observations": 0.0,
        }

    if (
        pd.api.types.is_datetime64_any_dtype(pre_df["time"])
        and isinstance(pre_df.index, pd.RangeIndex)
        and pre_df.index.start == 0
        and pre_df.index.step == 1
        and pre_df["time"].is_monotonic_increasing
        and pre_df["time"].is_unique
    ):
        bars = pre_df
        bar_times = bars["time"].to_numpy(dtype="datetime64[ns]", copy=False)
        close = bars["close"].to_numpy(dtype=float, copy=False)
    else:
        bars = pre_df[["time", "close"]].copy()
        bars["time"] = pd.to_datetime(bars["time"])
        bars = bars.sort_values("time").drop_duplicates(subset="time", keep="first").reset_index(drop=True)
        bar_times = bars["time"].to_numpy(dtype="datetime64[ns]")
        close = bars["close"].astype(float).to_numpy()

    position_contracts = np.zeros(len(bars), dtype=float)
    trades = trades_df.copy()
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    trades["exit_time"] = pd.to_datetime(trades["exit_time"])

    for trade in trades.itertuples(index=False):
        entry_idx = int(bar_times.searchsorted(np.datetime64(trade.entry_time), side="left"))
        exit_idx = int(bar_times.searchsorted(np.datetime64(trade.exit_time), side="left"))
        if exit_idx <= entry_idx or entry_idx >= len(position_contracts):
            continue
        direction = 1.0 if str(trade.direction) == "long" else -1.0
        contracts = float(getattr(trade, "contracts", 1.0))
        position_contracts[entry_idx:min(exit_idx, len(position_contracts))] += direction * contracts

    close_diff = np.diff(close, prepend=close[0])
    # The position held during the interval ending at bar i is approximated by
    # the prior bar's active exposure.
    interval_position = np.roll(position_contracts, 1)
    interval_position[0] = 0.0
    bar_pnl = interval_position * close_diff * float(futures_specs["contract_value"])

    # Apply realized transaction costs on exit bars so the bar stream is net-ish.
    costs = np.zeros(len(bars), dtype=float)
    round_trip_cost_per_contract = (
        float(futures_specs.get("commission_per_round_trip", 0.0))
        + float(futures_specs.get("slippage_points", 0.0)) * float(futures_specs["contract_value"])
    )
    for trade in trades.itertuples(index=False):
        exit_idx = int(bar_times.searchsorted(np.datetime64(trade.exit_time), side="left"))
        if 0 <= exit_idx < len(costs):
            costs[exit_idx] += round_trip_cost_per_contract * float(getattr(trade, "contracts", 1.0))
    bar_pnl -= costs

    equity = float(starting_capital) + np.cumsum(bar_pnl)
    daily_pnl = pd.Series(bar_pnl, index=bars["time"]).groupby(pd.Grouper(freq="D")).sum()
    daily_equity = float(starting_capital) + daily_pnl.cumsum()
    daily_returns = daily_equity.pct_change().dropna()
    sharpe = (
        float(daily_returns.mean() / daily_returns.std() * np.sqrt(252))
        if len(daily_returns) > 1 and daily_returns.std() > 0
        else 0.0
    )

    exposed = np.abs(position_contracts) > 0
    nonzero_bar_pnl = pd.Series(bar_pnl[np.abs(bar_pnl) > 1e-9])
    return {
        "bar_profit_factor": profit_factor_from_pnl(nonzero_bar_pnl),
        "bar_sharpe_ratio": sharpe,
        "bar_total_pnl": float(np.nansum(bar_pnl)),
        "bar_max_drawdown": _max_drawdown_pct(equity),
        "bar_exposure_pct": float(exposed.mean() * 100.0),
        "bar_observations": float(len(bars)),
        "bar_exposed_observations": float(exposed.sum()),
    }


def execution_bar_objective_metrics(
    execution_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    futures_specs: dict[str, Any],
    starting_capital: float,
) -> dict[str, float]:
    """
    Estimate objective metrics from the execution-timeframe bar stream.

    This deliberately mirrors ``bar_objective_metrics`` but prefixes every
    metric with ``execution_``. The existing ``bar_*`` metrics remain the
    conservative signal-frame objective, usually 5-minute close-to-close. These
    metrics answer a different question: whether the saved trade log has
    favorable exposure on the same bar grid used for intrabar execution.
    """
    base = bar_objective_metrics(execution_df, trades_df, futures_specs, starting_capital)
    return {f"execution_{key}": value for key, value in base.items()}


def _infer_bar_regime(pre_df: pd.DataFrame) -> pd.Series:
    """
    Infer a (0=range, 1=trend) regime for each bar from the classifier
    columns the engine leaves on the preprocessed frame.
    """
    if "regime_trend_up_confirmed" in pre_df.columns and "regime_trend_down_confirmed" in pre_df.columns:
        trend = (
            pre_df["regime_trend_up_confirmed"].fillna(False).astype(bool)
            | pre_df["regime_trend_down_confirmed"].fillna(False).astype(bool)
        )
    elif "day_regime" in pre_df.columns:
        trend = pre_df["day_regime"].astype(str).str.startswith("trend")
    else:
        # Fallback: high EMA slope as trend proxy
        ema_slope = pd.to_numeric(pre_df.get("trend_ema_slope", pd.Series(0.0, index=pre_df.index)), errors="coerce")
        trend = ema_slope.abs() > 0.15
    return trend.fillna(False).astype(bool)


def regime_weighted_bar_metrics(
    pre_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    futures_specs: dict[str, Any],
    starting_capital: float,
    *,
    range_weight: float = 1.0,
    trend_weight: float = 1.5,
) -> dict[str, float]:
    """
    Bar-objective variant that weights bars differently by regime.

    The idea: trend bars may represent higher-vol / higher-conviction
    environments where the same PnL bar is more informative.  Weighting
    by regime lets walk-forward optimization prefer strategies that
    perform well in high-weight regimes.

    Parameters
    ----------
    range_weight : float
        Weight applied to bars classified as range/neutral.
    trend_weight : float
        Weight applied to bars classified as trending.

    Returns
    -------
    dict with keys prefixed ``regime_bar_*``.
    """
    base = bar_objective_metrics(pre_df, trades_df, futures_specs, starting_capital)
    if base.get("bar_observations", 0) < 3:
        return {f"regime_{k}": v for k, v in base.items()}

    if (
        pd.api.types.is_datetime64_any_dtype(pre_df["time"])
        and isinstance(pre_df.index, pd.RangeIndex)
        and pre_df.index.start == 0
        and pre_df.index.step == 1
        and pre_df["time"].is_monotonic_increasing
        and pre_df["time"].is_unique
    ):
        bars = pre_df
        bar_times = bars["time"].to_numpy(dtype="datetime64[ns]", copy=False)
        close = bars["close"].to_numpy(dtype=float, copy=False)
    else:
        bars = pre_df[["time", "close"]].copy()
        bars["time"] = pd.to_datetime(bars["time"])
        bars = bars.sort_values("time").drop_duplicates(subset="time", keep="first").reset_index(drop=True)
        bar_times = bars["time"].to_numpy(dtype="datetime64[ns]")
        close = bars["close"].astype(float).to_numpy()

    position_contracts = np.zeros(len(bars), dtype=float)
    trades = trades_df.copy()
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    trades["exit_time"] = pd.to_datetime(trades["exit_time"])

    for trade in trades.itertuples(index=False):
        entry_idx = int(bar_times.searchsorted(np.datetime64(trade.entry_time), side="left"))
        exit_idx = int(bar_times.searchsorted(np.datetime64(trade.exit_time), side="left"))
        if exit_idx <= entry_idx or entry_idx >= len(position_contracts):
            continue
        direction = 1.0 if str(trade.direction) == "long" else -1.0
        contracts = float(getattr(trade, "contracts", 1.0))
        position_contracts[entry_idx:min(exit_idx, len(position_contracts))] += direction * contracts

    close_diff = np.diff(close, prepend=close[0])
    interval_position = np.roll(position_contracts, 1)
    interval_position[0] = 0.0
    bar_pnl = interval_position * close_diff * float(futures_specs["contract_value"])

    # Costs
    costs = np.zeros(len(bars), dtype=float)
    round_trip_cost_per_contract = (
        float(futures_specs.get("commission_per_round_trip", 0.0))
        + float(futures_specs.get("slippage_points", 0.0)) * float(futures_specs["contract_value"])
    )
    for trade in trades.itertuples(index=False):
        exit_idx = int(bar_times.searchsorted(np.datetime64(trade.exit_time), side="left"))
        if 0 <= exit_idx < len(costs):
            costs[exit_idx] += round_trip_cost_per_contract * float(getattr(trade, "contracts", 1.0))
    bar_pnl -= costs

    # Regime weights per bar
    is_trend = _infer_bar_regime(pre_df)
    # Align regime labels: pre_df row i corresponds to bar row i (since we
    # only kept 'time' and 'close', the alignment is by position).
    if len(is_trend) > len(bars):
        is_trend = is_trend.iloc[: len(bars)]
    elif len(is_trend) < len(bars):
        is_trend = pd.concat([is_trend, pd.Series(False, index=bars.index[len(is_trend):])], ignore_index=False)

    weights = np.where(is_trend.to_numpy()[: len(bars)], float(trend_weight), float(range_weight))
    weighted_pnl = bar_pnl * weights

    # Weighted variance for sharpe-like metric
    weighted_mean = float(np.nanmean(weighted_pnl)) if len(weighted_pnl) else 0.0
    weighted_std = float(np.nanstd(weighted_pnl, ddof=1)) if len(weighted_pnl) > 1 else 0.0
    weighted_sharpe = weighted_mean / weighted_std * np.sqrt(252 * 13) if weighted_std > 0 else 0.0

    exposed = np.abs(position_contracts) > 0
    nonzero_weighted_pnl = pd.Series(weighted_pnl[np.abs(weighted_pnl) > 1e-9])
    weighted_equity = float(starting_capital) + np.cumsum(weighted_pnl)

    return {
        "regime_bar_weighted_profit_factor": profit_factor_from_pnl(nonzero_weighted_pnl),
        "regime_bar_weighted_sharpe": weighted_sharpe,
        "regime_bar_weighted_total_pnl": float(np.nansum(weighted_pnl)),
        "regime_bar_weighted_max_drawdown": _max_drawdown_pct(weighted_equity),
        "regime_bar_exposure_pct": float(exposed.mean() * 100.0),
        "regime_trend_fraction": float(is_trend[: len(bars)].mean()),
        "regime_bar_observations": float(len(bars)),
        "regime_bar_exposed_observations": float(exposed.sum()),
    }


def volatility_weighted_bar_metrics(
    pre_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    futures_specs: dict[str, Any],
    starting_capital: float,
    *,
    vol_lookback_bars: int = 20,
    inverse_weight: bool = True,
) -> dict[str, float]:
    """
    Bar-objective variant that weights bars by inverse volatility.

    Low-vol bars get higher weight (the signal-to-noise ratio is better).
    This can reduce overfitting to high-vol outlier bars during walk-forward
    optimization.

    Parameters
    ----------
    vol_lookback_bars : int
        Rolling window for estimating bar-level volatility.
    inverse_weight : bool
        If True, weight = 1 / rolling_std (prefers low-vol bars).
        If False, weight = rolling_std (prefers high-vol bars).

    Returns
    -------
    dict with keys prefixed ``vol_bar_*``.
    """
    base = bar_objective_metrics(pre_df, trades_df, futures_specs, starting_capital)
    if base.get("bar_observations", 0) < 3:
        return {f"vol_{k}": v for k, v in base.items()}

    if (
        pd.api.types.is_datetime64_any_dtype(pre_df["time"])
        and isinstance(pre_df.index, pd.RangeIndex)
        and pre_df.index.start == 0
        and pre_df.index.step == 1
        and pre_df["time"].is_monotonic_increasing
        and pre_df["time"].is_unique
    ):
        bars = pre_df
        bar_times = bars["time"].to_numpy(dtype="datetime64[ns]", copy=False)
        close = bars["close"].to_numpy(dtype=float, copy=False)
    else:
        bars = pre_df[["time", "close"]].copy()
        bars["time"] = pd.to_datetime(bars["time"])
        bars = bars.sort_values("time").drop_duplicates(subset="time", keep="first").reset_index(drop=True)
        bar_times = bars["time"].to_numpy(dtype="datetime64[ns]")
        close = bars["close"].astype(float).to_numpy()

    position_contracts = np.zeros(len(bars), dtype=float)
    trades = trades_df.copy()
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    trades["exit_time"] = pd.to_datetime(trades["exit_time"])

    for trade in trades.itertuples(index=False):
        entry_idx = int(bar_times.searchsorted(np.datetime64(trade.entry_time), side="left"))
        exit_idx = int(bar_times.searchsorted(np.datetime64(trade.exit_time), side="left"))
        if exit_idx <= entry_idx or entry_idx >= len(position_contracts):
            continue
        direction = 1.0 if str(trade.direction) == "long" else -1.0
        contracts = float(getattr(trade, "contracts", 1.0))
        position_contracts[entry_idx:min(exit_idx, len(position_contracts))] += direction * contracts

    close_diff = np.diff(close, prepend=close[0])
    interval_position = np.roll(position_contracts, 1)
    interval_position[0] = 0.0
    bar_pnl = interval_position * close_diff * float(futures_specs["contract_value"])

    # Costs
    costs = np.zeros(len(bars), dtype=float)
    round_trip_cost_per_contract = (
        float(futures_specs.get("commission_per_round_trip", 0.0))
        + float(futures_specs.get("slippage_points", 0.0)) * float(futures_specs["contract_value"])
    )
    for trade in trades.itertuples(index=False):
        exit_idx = int(bar_times.searchsorted(np.datetime64(trade.exit_time), side="left"))
        if 0 <= exit_idx < len(costs):
            costs[exit_idx] += round_trip_cost_per_contract * float(getattr(trade, "contracts", 1.0))
    bar_pnl -= costs

    # Volatility weights
    vol_lookback = max(2, int(vol_lookback_bars))
    raw_vol = pd.Series(bar_pnl).rolling(vol_lookback, min_periods=2).std()
    safe_vol = raw_vol.where(raw_vol.gt(1e-12)).fillna(1.0).to_numpy()
    weights = np.where(np.isfinite(safe_vol), 1.0 / safe_vol if inverse_weight else safe_vol, 1.0)
    weighted_pnl = bar_pnl * weights

    weighted_mean = float(np.nanmean(weighted_pnl)) if len(weighted_pnl) else 0.0
    weighted_std = float(np.nanstd(weighted_pnl, ddof=1)) if len(weighted_pnl) > 1 else 0.0
    weighted_sharpe = weighted_mean / weighted_std * np.sqrt(252 * 13) if weighted_std > 0 else 0.0

    exposed = np.abs(position_contracts) > 0
    nonzero_weighted_pnl = pd.Series(weighted_pnl[np.abs(weighted_pnl) > 1e-9])
    weighted_equity = float(starting_capital) + np.cumsum(weighted_pnl)

    return {
        "vol_bar_weighted_profit_factor": profit_factor_from_pnl(nonzero_weighted_pnl),
        "vol_bar_weighted_sharpe": weighted_sharpe,
        "vol_bar_weighted_total_pnl": float(np.nansum(weighted_pnl)),
        "vol_bar_weighted_max_drawdown": _max_drawdown_pct(weighted_equity),
        "vol_bar_exposure_pct": float(exposed.mean() * 100.0),
        "vol_bar_observations": float(len(bars)),
        "vol_bar_exposed_observations": float(exposed.sum()),
    }
