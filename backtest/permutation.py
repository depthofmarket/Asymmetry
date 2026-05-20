from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

_mpl_config_dir = Path("results/.mplconfig").resolve()
_mpl_config_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_mpl_config_dir))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.portfolio import Portfolio
from backtest.walkforward import (
    WalkForwardResult,
    _grid_product,
    _resolve_max_drawdown_pct,
    _run_segment,
    _score_from_results,
    _select_best_row,
    run_walk_forward,
)

CHART_BG = "#080d14"
CHART_PANEL = "#111827"
CHART_GRID = "#2b3a4f"
CHART_TEXT = "#e5eefb"
CHART_MUTED = "#94a3b8"
CHART_GREEN = "#34d399"
CHART_BLUE = "#60a5fa"
CHART_AMBER = "#fbbf24"


@dataclass(frozen=True)
class PermutationTestResult:
    test_name: str
    metric: str
    n_permutations: int
    real_metric: float
    better_or_equal_count: int
    p_value: float
    p_value_smoothed: float
    metrics_csv: Path
    summary_csv: Path
    histogram_png: Path


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _style_dark_axis(ax) -> None:
    ax.set_facecolor(CHART_PANEL)
    ax.tick_params(colors=CHART_MUTED)
    ax.xaxis.label.set_color(CHART_TEXT)
    ax.yaxis.label.set_color(CHART_TEXT)
    ax.title.set_color(CHART_TEXT)
    for spine in ax.spines.values():
        spine.set_edgecolor(CHART_GRID)
    ax.grid(True, color=CHART_GRID, alpha=0.28, linewidth=0.75)


def _plot_metric_histogram(
    metrics: list[float],
    real_metric: float,
    metric: str,
    title: str,
    out_path: Path,
) -> None:
    vals = np.asarray([x for x in metrics if np.isfinite(x)], dtype=float)
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    fig.patch.set_facecolor(CHART_BG)
    if vals.size:
        bins = min(60, max(10, int(np.sqrt(vals.size) * 2)))
        ax.hist(vals, bins=bins, color=CHART_GREEN, alpha=0.82, edgecolor="#182032", linewidth=0.5)
    if np.isfinite(real_metric):
        ax.axvline(real_metric, color=CHART_AMBER, linestyle="--", linewidth=1.6, alpha=0.95)
    ax.set_title(title, fontsize=16, fontweight="bold")
    ax.set_xlabel(metric)
    ax.set_ylabel("Count")
    _style_dark_axis(ax)
    if np.isfinite(real_metric):
        ymin, ymax = ax.get_ylim()
        ax.text(
            real_metric,
            ymax - (ymax - ymin) * 0.08,
            f"real {metric}: {real_metric:.4f}",
            rotation=90,
            va="top",
            ha="right",
            color=CHART_AMBER,
            fontsize=9,
            fontweight="bold",
        )
    plt.tight_layout()
    plt.savefig(out_path, dpi=160, facecolor=fig.get_facecolor())
    plt.close()


def permute_ohlcv(
    data: pd.DataFrame,
    start_index: int = 0,
    seed: int | None = None,
) -> pd.DataFrame:
    """
    Build a price-path permutation that preserves the timestamp and volume schedule.

    The first bar at start_index is unchanged. Each following bar is rebuilt from
    independently shuffled close-to-open gaps and intrabar OHLC shapes.
    """
    required = ["time", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in data.columns]
    if missing:
        raise ValueError(f"Missing required OHLCV columns: {missing}")

    df = data[required].copy()
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").drop_duplicates(subset="time", keep="first").reset_index(drop=True)

    if len(df) < 3:
        return df

    start_index = int(np.clip(start_index, 0, len(df) - 2))
    ohlc = df[["open", "high", "low", "close"]].astype(float).to_numpy()
    if np.any(ohlc <= 0):
        raise ValueError("OHLC prices must be positive for log-price permutation.")

    log_ohlc = np.log(ohlc)
    m = len(df) - start_index - 1
    if m <= 0:
        return df

    gaps = log_ohlc[start_index + 1 :, 0] - log_ohlc[start_index : -1, 3]
    intrabar = np.column_stack(
        [
            log_ohlc[start_index + 1 :, 1] - log_ohlc[start_index + 1 :, 0],
            log_ohlc[start_index + 1 :, 2] - log_ohlc[start_index + 1 :, 0],
            log_ohlc[start_index + 1 :, 3] - log_ohlc[start_index + 1 :, 0],
        ]
    )

    rng = np.random.default_rng(seed)
    gap_order = rng.permutation(m)
    intrabar_order = rng.permutation(m)

    out = log_ohlc.copy()
    for j in range(m):
        i = start_index + 1 + j
        open_log = out[i - 1, 3] + gaps[gap_order[j]]
        shape = intrabar[intrabar_order[j]]
        out[i, 0] = open_log
        out[i, 1] = open_log + shape[0]
        out[i, 2] = open_log + shape[1]
        out[i, 3] = open_log + shape[2]

    prices = np.exp(out)
    # Protect against any malformed source bar where high/low relationships were odd.
    high = np.maximum.reduce([prices[:, 0], prices[:, 1], prices[:, 3]])
    low = np.minimum.reduce([prices[:, 0], prices[:, 2], prices[:, 3]])
    df["open"] = prices[:, 0]
    df["high"] = high
    df["low"] = low
    df["close"] = prices[:, 3]
    return df


def permutation_start_index(data: pd.DataFrame, start_time: pd.Timestamp) -> int:
    times = pd.to_datetime(data["time"]).sort_values().reset_index(drop=True)
    return int(times.searchsorted(pd.Timestamp(start_time), side="left"))


def _preprocess_raw(
    raw_data: pd.DataFrame,
    futures_specs: dict,
    base_params: dict,
    starting_capital: float,
) -> pd.DataFrame:
    max_dd_pct = _resolve_max_drawdown_pct(base_params)
    portfolio = Portfolio(starting_capital, futures_specs, max_drawdown_pct=max_dd_pct)
    engine = BacktestEngine(raw_data, portfolio, futures_specs, base_params)
    return engine.preprocess()


def _sample_combos(
    param_grid: dict[str, list[Any]],
    n_random_samples: int | None,
    seed: int,
) -> list[dict[str, Any]]:
    combos = _grid_product(param_grid)
    if n_random_samples is not None and len(combos) > n_random_samples:
        rng = np.random.default_rng(seed)
        rng.shuffle(combos)
        combos = combos[:n_random_samples]
    return combos


def _optimize_segment(
    pre_df: pd.DataFrame,
    raw_data: pd.DataFrame,
    futures_specs: dict,
    base_params: dict,
    starting_capital: float,
    combos: list[dict[str, Any]],
    param_grid: dict[str, list[Any]],
    metric: str,
    min_trades: int,
    selection_mode: str,
) -> tuple[float, dict[str, Any], dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for overrides in combos:
        results = _run_segment(
            pre_df,
            raw_data=raw_data,
            futures_specs=futures_specs,
            base_params=base_params,
            starting_capital=starting_capital,
            overrides=overrides,
        )
        score = _score_from_results(results, metric=metric, min_trades=min_trades)
        rows.append({"overrides": dict(overrides), "score": score, "results": results})

    if not rows:
        return float("-inf"), {}, {"error": "No parameter sets were supplied."}

    selected = _select_best_row(rows, param_grid, selection_mode)
    return float(selected["score"]), dict(selected["overrides"]), selected["results"]


def _write_outputs(
    rows: list[dict[str, Any]],
    test_name: str,
    metric: str,
    out_dir: Path,
    artifact_name: str,
) -> PermutationTestResult:
    _ensure_dir(out_dir)
    metrics_csv = out_dir / f"{artifact_name}_metrics.csv"
    summary_csv = out_dir / f"{artifact_name}_summary.csv"
    histogram_png = out_dir / f"{artifact_name}_histogram.png"

    df = pd.DataFrame(rows)
    df.to_csv(metrics_csv, index=False)

    real_rows = df[df["sample_type"] == "real"]
    if real_rows.empty:
        raise ValueError("Permutation result rows must include one real sample.")

    real_metric = float(real_rows.iloc[0]["metric_value"])
    perm_metrics = df.loc[df["sample_type"] == "permutation", "metric_value"].astype(float).tolist()
    better_or_equal = int(sum(x >= real_metric for x in perm_metrics if np.isfinite(x)))
    n = len(perm_metrics)
    p_value = float(better_or_equal / n) if n else float("nan")
    p_value_smoothed = float((better_or_equal + 1) / (n + 1)) if n else float("nan")

    summary = pd.DataFrame(
        [
            {
                "test_name": test_name,
                "metric": metric,
                "n_permutations": n,
                "real_metric": real_metric,
                "better_or_equal_count": better_or_equal,
                "p_value": p_value,
                "p_value_smoothed": p_value_smoothed,
            }
        ]
    )
    summary.to_csv(summary_csv, index=False)
    _plot_metric_histogram(
        perm_metrics,
        real_metric=real_metric,
        metric=metric,
        title=f"{test_name}: permutation {metric}",
        out_path=histogram_png,
    )

    return PermutationTestResult(
        test_name=test_name,
        metric=metric,
        n_permutations=n,
        real_metric=real_metric,
        better_or_equal_count=better_or_equal,
        p_value=p_value,
        p_value_smoothed=p_value_smoothed,
        metrics_csv=metrics_csv,
        summary_csv=summary_csv,
        histogram_png=histogram_png,
    )


def run_in_sample_permutation_test(
    raw_data: pd.DataFrame,
    futures_specs: dict,
    base_params: dict,
    starting_capital: float,
    param_grid: dict[str, list[Any]],
    metric: str = "profit_factor",
    min_trades: int = 40,
    n_permutations: int = 100,
    seed: int = 7,
    n_random_samples: int | None = 50,
    out_dir: Path | str = "results/research/permutation",
    artifact_name: str = "insample_permutation",
    progress: bool = True,
    selection_mode: str = "stable",
) -> PermutationTestResult:
    combos = _sample_combos(param_grid, n_random_samples=n_random_samples, seed=seed)
    out_dir = Path(out_dir)

    real_pre = _preprocess_raw(raw_data, futures_specs, base_params, starting_capital)
    real_score, real_overrides, real_results = _optimize_segment(
        real_pre,
        raw_data=raw_data,
        futures_specs=futures_specs,
        base_params=base_params,
        starting_capital=starting_capital,
        combos=combos,
        param_grid=param_grid,
        metric=metric,
        min_trades=min_trades,
        selection_mode=selection_mode,
    )

    rows: list[dict[str, Any]] = [
        {
            "sample_type": "real",
            "permutation_idx": -1,
            "metric_value": real_score,
            "total_trades": real_results.get("total_trades", 0),
            "total_pnl": real_results.get("total_pnl", 0.0),
            "profit_factor": real_results.get("profit_factor", 0.0),
            "sharpe_ratio": real_results.get("sharpe_ratio", 0.0),
            "bar_profit_factor": real_results.get("bar_profit_factor", 0.0),
            "bar_sharpe_ratio": real_results.get("bar_sharpe_ratio", 0.0),
            "best_overrides": real_overrides,
        }
    ]

    for i in range(n_permutations):
        if progress and (i == 0 or (i + 1) == n_permutations or (i + 1) % max(1, n_permutations // 10) == 0):
            print(f"      in-sample permutation {i + 1}/{n_permutations}")
        perm_raw = permute_ohlcv(raw_data, start_index=0, seed=seed + i + 1)
        perm_pre = _preprocess_raw(perm_raw, futures_specs, base_params, starting_capital)
        score, overrides, results = _optimize_segment(
            perm_pre,
            raw_data=perm_raw,
            futures_specs=futures_specs,
            base_params=base_params,
            starting_capital=starting_capital,
            combos=combos,
            param_grid=param_grid,
            metric=metric,
            min_trades=min_trades,
            selection_mode=selection_mode,
        )
        rows.append(
            {
                "sample_type": "permutation",
                "permutation_idx": i,
                "metric_value": score,
                "total_trades": results.get("total_trades", 0),
                "total_pnl": results.get("total_pnl", 0.0),
                "profit_factor": results.get("profit_factor", 0.0),
                "sharpe_ratio": results.get("sharpe_ratio", 0.0),
                "bar_profit_factor": results.get("bar_profit_factor", 0.0),
                "bar_sharpe_ratio": results.get("bar_sharpe_ratio", 0.0),
                "best_overrides": overrides,
            }
        )

    return _write_outputs(
        rows,
        test_name="in_sample",
        metric=metric,
        out_dir=out_dir,
        artifact_name=artifact_name,
    )


def run_walk_forward_permutation_test(
    raw_data: pd.DataFrame,
    pre_df: pd.DataFrame,
    futures_specs: dict,
    base_params: dict,
    starting_capital: float,
    param_grid: dict[str, list[Any]],
    real_walk_forward: WalkForwardResult | None = None,
    train_years: int = 4,
    test_months: int = 6,
    step_months: int = 6,
    window_mode: str = "rolling",
    purge_bars: int | str | None = "auto",
    embargo_bars: int = 0,
    metric: str = "profit_factor",
    min_trades_train: int = 40,
    min_trades_test: int = 5,
    min_trades_total: int = 30,
    n_permutations: int = 100,
    seed: int = 7,
    n_random_samples: int | None = 50,
    out_dir: Path | str = "results/research/permutation",
    artifact_name: str = "walkforward_permutation",
    progress: bool = True,
    selection_mode: str = "stable",
) -> PermutationTestResult:
    out_dir = Path(out_dir)

    if real_walk_forward is None:
        real_walk_forward = run_walk_forward(
            pre_df=pre_df,
            raw_data=raw_data,
            futures_specs=futures_specs,
            base_params=base_params,
            starting_capital=starting_capital,
            train_years=train_years,
            test_months=test_months,
            step_months=step_months,
            window_mode=window_mode,
            purge_bars=purge_bars,
            embargo_bars=embargo_bars,
            param_grid=param_grid,
            metric=metric,
            min_trades_train=min_trades_train,
            min_trades_test=min_trades_test,
            seed=seed,
            n_random_samples=n_random_samples,
            out_dir=out_dir / "real_walkforward",
            artifact_name="real_walkforward",
            progress=False,
            write_fold_csv=False,
            selection_mode=selection_mode,
        )

    real_score = _score_from_results(
        real_walk_forward.stitched_results,
        metric=metric,
        min_trades=min_trades_total,
    )
    rows: list[dict[str, Any]] = [
        {
            "sample_type": "real",
            "permutation_idx": -1,
            "metric_value": real_score,
            "total_trades": real_walk_forward.stitched_results.get("total_trades", 0),
            "total_pnl": real_walk_forward.stitched_results.get("total_pnl", 0.0),
            "profit_factor": real_walk_forward.stitched_results.get("profit_factor", 0.0),
            "sharpe_ratio": real_walk_forward.stitched_results.get("sharpe_ratio", 0.0),
            "bar_profit_factor": real_walk_forward.stitched_results.get("bar_profit_factor", 0.0),
            "bar_sharpe_ratio": real_walk_forward.stitched_results.get("bar_sharpe_ratio", 0.0),
            "best_overrides": "",
        }
    ]

    t0 = pd.Timestamp(pre_df["time"].min()).normalize()
    first_train_end = t0 + pd.DateOffset(years=train_years)
    start_index = permutation_start_index(raw_data, first_train_end)

    for i in range(n_permutations):
        if progress and (i == 0 or (i + 1) == n_permutations or (i + 1) % max(1, n_permutations // 10) == 0):
            print(f"      walk-forward permutation {i + 1}/{n_permutations}")
        perm_raw = permute_ohlcv(raw_data, start_index=start_index, seed=seed + i + 1)
        perm_pre = _preprocess_raw(perm_raw, futures_specs, base_params, starting_capital)
        wf = run_walk_forward(
            pre_df=perm_pre,
            raw_data=perm_raw,
            futures_specs=futures_specs,
            base_params=base_params,
            starting_capital=starting_capital,
            train_years=train_years,
            test_months=test_months,
            step_months=step_months,
            window_mode=window_mode,
            purge_bars=purge_bars,
            embargo_bars=embargo_bars,
            param_grid=param_grid,
            metric=metric,
            min_trades_train=min_trades_train,
            min_trades_test=min_trades_test,
            seed=seed,
            n_random_samples=n_random_samples,
            out_dir=out_dir / "permuted_walkforward",
            artifact_name=f"permutation_{i:04d}",
            progress=False,
            write_fold_csv=False,
            selection_mode=selection_mode,
        )
        score = _score_from_results(wf.stitched_results, metric=metric, min_trades=min_trades_total)
        rows.append(
            {
                "sample_type": "permutation",
                "permutation_idx": i,
                "metric_value": score,
                "total_trades": wf.stitched_results.get("total_trades", 0),
                "total_pnl": wf.stitched_results.get("total_pnl", 0.0),
                "profit_factor": wf.stitched_results.get("profit_factor", 0.0),
                "sharpe_ratio": wf.stitched_results.get("sharpe_ratio", 0.0),
                "bar_profit_factor": wf.stitched_results.get("bar_profit_factor", 0.0),
                "bar_sharpe_ratio": wf.stitched_results.get("bar_sharpe_ratio", 0.0),
                "best_overrides": "",
            }
        )

    return _write_outputs(
        rows,
        test_name="walk_forward",
        metric=metric,
        out_dir=out_dir,
        artifact_name=artifact_name,
    )
