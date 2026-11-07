from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.portfolio import Portfolio
from backtest.heatmap import HeatmapPaths, plot_heatmap


Metric = Literal[
    "sharpe",
    "profit_factor",
    "bar_profit_factor",
    "bar_sharpe",
    "expectancy",
    "total_pnl",
    "return_pct",
    "max_drawdown",
]


@dataclass(frozen=True)
class SweepResult:
    x_param: str
    y_param: str
    metric: Metric
    matrix: pd.DataFrame
    heatmap: HeatmapPaths


def _resolve_max_drawdown_pct(params: dict[str, Any]) -> float | None:
    if not params.get("enable_circuit_breaker", False):
        return None
    value = params.get("max_drawdown_pct")
    if value is None:
        return None
    return float(value)


def _metric_value(results: dict[str, Any], metric: Metric) -> float:
    if "error" in results:
        return float("nan")
    if metric == "sharpe":
        return float(results.get("sharpe_ratio", 0.0))
    if metric == "profit_factor":
        return float(results.get("profit_factor", 0.0))
    if metric == "bar_profit_factor":
        return float(results.get("bar_profit_factor", 0.0))
    if metric == "bar_sharpe":
        return float(results.get("bar_sharpe_ratio", 0.0))
    if metric == "expectancy":
        return float(results.get("expectancy", 0.0))
    if metric == "total_pnl":
        return float(results.get("total_pnl", 0.0))
    if metric == "return_pct":
        return float(results.get("return_pct", 0.0))
    if metric == "max_drawdown":
        return float(results.get("max_drawdown", 0.0))
    raise ValueError(f"Unknown metric {metric}")


def run_2d_sweep(
    pre_df: pd.DataFrame,
    raw_data: pd.DataFrame | None,
    futures_specs: dict,
    base_params: dict,
    starting_capital: float,
    x_param: str,
    x_values: list[Any],
    y_param: str,
    y_values: list[Any],
    metric: Metric = "sharpe",
    min_trades: int = 30,
    artifact_name: str = "sweep",
    out_dir: Path | None = None,
) -> SweepResult:
    """
    Run a 2D grid sweep and return a metric matrix + saved heatmap.

    `pre_df` should be from BacktestEngine.preprocess() to avoid recomputing indicators.
    Keep swept params to non-indicator params for speed.
    """
    mat = np.full((len(y_values), len(x_values)), np.nan, dtype=float)

    for yi, yv in enumerate(y_values):
        for xi, xv in enumerate(x_values):
            overrides = {x_param: xv, y_param: yv}
            params = {**base_params, **overrides}
            max_dd_pct = _resolve_max_drawdown_pct(params)
            portfolio = Portfolio(starting_capital, futures_specs, max_drawdown_pct=max_dd_pct)
            engine = BacktestEngine(raw_data if raw_data is not None else pre_df, portfolio, futures_specs, params)
            results = engine.run_on_preprocessed(pre_df)
            if "error" not in results and int(results.get("total_trades", 0)) < min_trades:
                mat[yi, xi] = np.nan
            else:
                mat[yi, xi] = _metric_value(results, metric)

    matrix = pd.DataFrame(mat, index=y_values, columns=x_values)

    out_dir = (out_dir or (Path("results/sweeps") / artifact_name))
    filename_stem = f"{artifact_name}_{metric}_{y_param}_vs_{x_param}"
    heatmap = plot_heatmap(
        matrix,
        title=f"{metric} heatmap: {y_param} vs {x_param}",
        out_dir=out_dir,
        filename_stem=filename_stem,
        fmt=".2f",
    )

    return SweepResult(
        x_param=x_param,
        y_param=y_param,
        metric=metric,
        matrix=matrix,
        heatmap=heatmap,
    )
