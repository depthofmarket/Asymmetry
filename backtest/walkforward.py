from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.objectives import bar_objective_metrics, execution_bar_objective_metrics
from backtest.portfolio import Portfolio


@dataclass(frozen=True)
class WalkForwardFoldResult:
    fold_idx: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    best_overrides: dict[str, Any]
    train_metric: float
    test_results: dict[str, Any]
    train_neighbor_metric: float = float("nan")
    train_selection_metric: float = float("nan")
    selected_train_trades: int = 0
    planned_train_start: datetime | None = None
    planned_train_end: datetime | None = None
    window_mode: str = "rolling"
    purge_bars: int = 0
    embargo_bars: int = 0
    gap_bars: int = 0
    bar_interval_minutes: float = 5.0
    boundary_gap_minutes: float = 0.0
    train_rows: int = 0
    test_rows: int = 0
    purge_embargo_ok: bool = True


@dataclass(frozen=True)
class WalkForwardResult:
    folds: list[WalkForwardFoldResult]
    stitched_trades: pd.DataFrame
    stitched_results: dict[str, Any]
    fold_summary_csv: Path
    stitched_trades_csv: Path | None = None


def _resolve_max_drawdown_pct(params: dict[str, Any]) -> float | None:
    if not params.get("enable_circuit_breaker", False):
        return None
    value = params.get("max_drawdown_pct")
    if value is None:
        return None
    return float(value)


def _as_dt(x) -> pd.Series:
    return pd.to_datetime(x, errors="coerce")


def _date_mask(df: pd.DataFrame, start: datetime, end: datetime) -> pd.Series:
    t = _as_dt(df["time"])
    return (t >= start) & (t < end)


def _infer_bar_interval(df: pd.DataFrame) -> pd.Timedelta:
    if "time" not in df.columns or len(df) < 2:
        return pd.Timedelta(minutes=5)
    times = pd.to_datetime(df["time"], errors="coerce").dropna().sort_values()
    diffs = times.diff().dropna()
    diffs = diffs.loc[diffs > pd.Timedelta(0)]
    if diffs.empty:
        return pd.Timedelta(minutes=5)
    interval = diffs.median()
    if not isinstance(interval, pd.Timedelta) or interval <= pd.Timedelta(0):
        return pd.Timedelta(minutes=5)
    return interval


def _coerce_nonnegative_int(value: Any, *, name: str) -> int:
    if value is None:
        return 0
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}") from exc
    if result < 0:
        raise ValueError(f"{name} must be non-negative, got {result}")
    return result


def _max_int_setting(base_params: dict[str, Any], param_grid: dict[str, list[Any]], key: str, default: int = 0) -> int:
    values: list[int] = []
    if key in base_params:
        values.append(_coerce_nonnegative_int(base_params.get(key), name=key))
    if key in param_grid:
        for item in param_grid.get(key, []):
            values.append(_coerce_nonnegative_int(item, name=key))
    return max(values) if values else int(default)


def _infer_purge_bars(base_params: dict[str, Any], param_grid: dict[str, list[Any]]) -> int:
    max_hold_bars = _max_int_setting(base_params, param_grid, "max_hold_bars")
    entry_delay_bars = _max_int_setting(base_params, param_grid, "entry_delay_bars")
    if max_hold_bars <= 0 and entry_delay_bars <= 0:
        return 0
    return max_hold_bars + entry_delay_bars + 1


def _resolve_purge_bars(
    value: int | str | None,
    *,
    base_params: dict[str, Any],
    param_grid: dict[str, list[Any]],
) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        if value.lower().strip() == "auto":
            return _infer_purge_bars(base_params, param_grid)
        return _coerce_nonnegative_int(value, name="purge_bars")
    return _coerce_nonnegative_int(value, name="purge_bars")


def _grid_product(param_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    out: list[dict[str, Any]] = []
    for combo in product(*values):
        out.append({k: v for k, v in zip(keys, combo, strict=True)})
    return out


# Cap ratio-based metrics so that zero-loss flukes (PF=∞) don't dominate
# the walk-forward / permutation optimizer.
_MAX_RATIO_SCORE = 10.0


def _score_from_results(
    results: dict[str, Any],
    metric: str,
    min_trades: int = 30,
) -> float:
    if "error" in results:
        return float("-inf")
    if int(results.get("total_trades", 0)) < min_trades:
        return float("-inf")

    if metric == "sharpe":
        return float(results.get("sharpe_ratio", 0.0))
    if metric == "profit_factor":
        return min(float(results.get("profit_factor", 0.0)), _MAX_RATIO_SCORE)
    if metric == "expectancy":
        return float(results.get("expectancy", 0.0))
    if metric == "total_pnl":
        return float(results.get("total_pnl", 0.0))
    if metric == "bar_profit_factor":
        return min(float(results.get("bar_profit_factor", 0.0)), _MAX_RATIO_SCORE)
    if metric == "bar_sharpe":
        return float(results.get("bar_sharpe_ratio", 0.0))
    if metric == "execution_bar_profit_factor":
        return min(float(results.get("execution_bar_profit_factor", 0.0)), _MAX_RATIO_SCORE)
    if metric == "execution_bar_sharpe":
        return float(results.get("execution_bar_sharpe_ratio", 0.0))

    raise ValueError(f"Unknown metric: {metric}")


def _combo_neighbor_score(
    idx: int,
    rows: list[dict[str, Any]],
    param_grid: dict[str, list[Any]],
) -> float:
    combo = rows[idx]["overrides"]
    scores: list[float] = []
    for row in rows:
        other = row["overrides"]
        distance = 0
        comparable = True
        for key, values in param_grid.items():
            if key not in combo or key not in other:
                comparable = False
                break
            try:
                distance += abs(values.index(combo[key]) - values.index(other[key]))
            except ValueError:
                comparable = False
                break
        if comparable and distance <= 1 and np.isfinite(row["score"]):
            scores.append(float(row["score"]))
    if not scores:
        return float("-inf")
    return float(np.median(scores))


def _select_best_row(
    rows: list[dict[str, Any]],
    param_grid: dict[str, list[Any]],
    selection_mode: str,
) -> dict[str, Any]:
    finite_rows = [row for row in rows if np.isfinite(row["score"])]
    if not finite_rows:
        return rows[0]
    if selection_mode != "stable":
        return max(finite_rows, key=lambda row: row["score"])

    best_row = finite_rows[0]
    best_selection_score = float("-inf")
    for idx, row in enumerate(rows):
        if not np.isfinite(row["score"]):
            continue
        local_median = _combo_neighbor_score(idx, rows, param_grid)
        selection_score = 0.65 * float(row["score"]) + 0.35 * local_median
        if selection_score > best_selection_score:
            best_selection_score = selection_score
            best_row = row
    return best_row


def _row_selection_diagnostics(
    selected: dict[str, Any],
    rows: list[dict[str, Any]],
    param_grid: dict[str, list[Any]],
    selection_mode: str,
) -> tuple[float, float, int]:
    selected_idx = next((idx for idx, row in enumerate(rows) if row is selected), -1)
    if selected_idx < 0:
        return float("nan"), float("nan"), 0

    neighbor_metric = _combo_neighbor_score(selected_idx, rows, param_grid)
    raw_metric = float(selected.get("score", float("nan")))
    selection_metric = raw_metric
    if selection_mode == "stable":
        selection_metric = 0.65 * raw_metric + 0.35 * neighbor_metric
    selected_train_trades = int(selected.get("results", {}).get("total_trades", 0))
    return float(neighbor_metric), float(selection_metric), selected_train_trades


def _profit_factor_from_pnl(pnl: pd.Series) -> float:
    wins = float(pnl[pnl > 0].sum())
    losses = abs(float(pnl[pnl <= 0].sum()))
    if losses <= 0:
        return 0.0
    return wins / losses


def summarize_trades(
    trades_df: pd.DataFrame,
    starting_capital: float,
    pre_df: pd.DataFrame | None = None,
    futures_specs: dict[str, Any] | None = None,
    execution_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    Summarize an already-stitched trade dataframe without re-running the engine.
    """
    if len(trades_df) == 0:
        return {"error": "No trades generated"}

    df = trades_df.copy()
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df = df.sort_values("exit_time").reset_index(drop=True)
    df["cumulative_pnl"] = df["pnl"].cumsum()
    df["equity"] = float(starting_capital) + df["cumulative_pnl"]

    total_trades = int(len(df))
    wins = int((df["pnl"] > 0).sum())
    losses = int((df["pnl"] <= 0).sum())
    total_pnl = float(df["pnl"].sum())
    avg_win = float(df.loc[df["pnl"] > 0, "pnl"].mean()) if wins else 0.0
    avg_loss = float(df.loc[df["pnl"] <= 0, "pnl"].mean()) if losses else 0.0
    expectancy = float(df["pnl"].mean())

    equity = np.concatenate(([float(starting_capital)], df["equity"].to_numpy(dtype=float)))
    peak = np.maximum.accumulate(equity)
    max_drawdown = float(np.nanmax((peak - equity) / peak) * 100.0) if equity.size else 0.0

    daily_pnl = df.groupby(df["exit_time"].dt.normalize())["pnl"].sum()
    daily_equity = daily_pnl.cumsum() + float(starting_capital)
    daily_returns = daily_equity.pct_change().dropna()
    sharpe = (
        float(daily_returns.mean() / daily_returns.std() * np.sqrt(252))
        if len(daily_returns) > 1 and daily_returns.std() > 0
        else 0.0
    )

    out = {
        "total_trades": total_trades,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate": float(wins / total_trades * 100.0),
        "total_pnl": total_pnl,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": _profit_factor_from_pnl(df["pnl"]),
        "expectancy": expectancy,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_drawdown,
        "final_equity": float(float(starting_capital) + total_pnl),
        "return_pct": float(total_pnl / float(starting_capital) * 100.0),
        "trades": df,
    }
    if pre_df is not None and futures_specs is not None:
        out.update(bar_objective_metrics(pre_df, df, futures_specs, starting_capital))
    if execution_df is not None and futures_specs is not None:
        exec_frame = execution_df
        if "time" in exec_frame.columns:
            exec_time = pd.to_datetime(exec_frame["time"], errors="coerce")
            start_time = df["entry_time"].min()
            end_time = df["exit_time"].max()
            exec_frame = exec_frame.loc[(exec_time >= start_time) & (exec_time <= end_time)].reset_index(drop=True)
        out.update(execution_bar_objective_metrics(exec_frame, df, futures_specs, starting_capital))
    return out


def _run_segment(
    pre_df: pd.DataFrame,
    raw_data: pd.DataFrame | None,
    futures_specs: dict,
    base_params: dict,
    starting_capital: float,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = {**base_params, **(overrides or {})}
    max_dd_pct = _resolve_max_drawdown_pct(params)
    segment_raw = raw_data
    if raw_data is not None and "time" in raw_data.columns and "time" in pre_df.columns and not pre_df.empty:
        # Keep 1-minute execution inside the same train/test segment. Without
        # this, a fold-boundary trade could exit using future bars from the
        # next segment, leaking information into walk-forward/permutation tests.
        start_time = pd.to_datetime(pre_df["time"]).min()
        end_time = pd.to_datetime(pre_df["time"]).max() + pd.Timedelta(minutes=5)
        raw_time = pd.to_datetime(raw_data["time"])
        segment_raw = raw_data.loc[(raw_time >= start_time) & (raw_time < end_time)].reset_index(drop=True)
    portfolio = Portfolio(starting_capital, futures_specs, max_drawdown_pct=max_dd_pct)
    engine = BacktestEngine(segment_raw if segment_raw is not None else pre_df, portfolio, futures_specs, params)
    # We already have pre_df as 5-min; engine.preprocess() would resample again.
    # We bypass that by calling run_on_preprocessed directly.
    return engine.run_on_preprocessed(pre_df)


def run_walk_forward(
    pre_df: pd.DataFrame,
    raw_data: pd.DataFrame | None,
    futures_specs: dict,
    base_params: dict,
    starting_capital: float,
    train_years: int = 4,
    test_months: int = 6,
    step_months: int = 6,
    window_mode: str = "rolling",
    purge_bars: int | str | None = "auto",
    embargo_bars: int = 0,
    param_grid: dict[str, list[Any]] | None = None,
    metric: str = "sharpe",
    min_trades_train: int = 40,
    min_trades_test: int = 5,
    seed: int = 7,
    n_random_samples: int | None = 50,
    out_dir: Path | str = "results/walkforward",
    artifact_name: str = "walkforward",
    progress: bool = True,
    write_fold_csv: bool = True,
    selection_mode: str = "stable",
) -> WalkForwardResult:
    """
    Walk-forward process:
    - For each fold: select best params on TRAIN window (grid search) then trade TEST window.
    - Stitch OOS folds sequentially (capital carries forward).

    `pre_df` must be a 5-min dataframe produced by BacktestEngine.preprocess().
    Keep `param_grid` limited to non-indicator parameters for speed.

    `window_mode` is either "rolling" (fixed-width training window) or
    "anchored" (expanding training window from the first bar). `purge_bars`
    removes the final train bars before each test fold so train labels/trades
    cannot overlap the OOS period; "auto" resolves to max_hold_bars +
    entry_delay_bars + 1. `embargo_bars` adds an extra serial-correlation gap.
    """
    df = pre_df.copy()
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)

    rng = np.random.default_rng(seed)
    _ = rng  # reserved for future randomized search modes

    if param_grid is None:
        strategy_name = str(base_params.get("strategy_name", "orb"))
        if strategy_name == "vwap_regime":
            param_grid = {
                "mr_entry_z": [1.2, 1.5, 1.8],
                "mr_rsi_long_max": [40, 45, 50],
                "trend_vwap_distance_atr": [0.5, 0.6, 0.8],
                "trend_slope_threshold": [0.10, 0.15, 0.20],
                "atr_stop_multiplier": [0.8, 1.0, 1.2],
                "max_hold_bars": [10, 14, 18],
            }
        elif strategy_name == "volume_profile_regime":
            param_grid = {
                "breakeven_trigger_dollars": [100, 140, 180],
                "mr_long_trade_end": ["11:40", "11:55", "12:10"],
                "mr_short_trade_start": ["11:00", "11:15", "11:30"],
                "trend_long_trade_start": ["11:15", "11:30", "11:45"],
            }
        else:
            param_grid = {
                "breakout_buffer_points": [0.5, 1.0, 1.5],
                "breakout_close_min_strength": [0.40, 0.50, 0.60],
                "min_confirmations": [4, 5, 6],
                "atr_stop_multiplier": [0.8, 1.0, 1.2],
                "atr_target_multiplier": [0.9, 1.1, 1.3],
                "max_hold_bars": [10, 14, 18],
            }

    combos = _grid_product(param_grid)

    if n_random_samples is not None and len(combos) > n_random_samples:
        rng.shuffle(combos)
        combos = combos[:n_random_samples]

    window_mode = window_mode.lower().strip()
    if window_mode not in {"rolling", "anchored"}:
        raise ValueError(f"window_mode must be 'rolling' or 'anchored', got {window_mode!r}")

    bar_interval = _infer_bar_interval(df)
    resolved_purge_bars = _resolve_purge_bars(
        purge_bars,
        base_params=base_params,
        param_grid=param_grid,
    )
    resolved_embargo_bars = _coerce_nonnegative_int(embargo_bars, name="embargo_bars")
    gap_bars = resolved_purge_bars + resolved_embargo_bars
    gap_delta = bar_interval * gap_bars
    bar_interval_minutes = float(bar_interval / pd.Timedelta(minutes=1))

    start = df["time"].min().to_pydatetime()
    end = df["time"].max().to_pydatetime()

    # Fold boundaries using month arithmetic via pandas offsets
    t0 = pd.Timestamp(start).normalize()
    tf = pd.Timestamp(end).normalize()

    folds: list[WalkForwardFoldResult] = []
    stitched_trades: list[pd.DataFrame] = []
    current_capital = float(starting_capital)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fold_summary_csv = out_dir / f"{artifact_name}_folds.csv"
    stitched_trades_csv = out_dir / f"{artifact_name}_stitched_trades.csv"

    estimated_folds = 0
    probe_cursor = t0 + pd.DateOffset(years=train_years)
    while probe_cursor + pd.DateOffset(months=test_months) <= tf:
        estimated_folds += 1
        probe_cursor = probe_cursor + pd.DateOffset(months=step_months)

    if progress:
        print(
            f"   Walk-forward setup: {estimated_folds} folds, "
            f"{len(combos)} parameter samples per fold, metric={metric}, "
            f"selection={selection_mode}, window={window_mode}, "
            f"purge={resolved_purge_bars} bars, embargo={resolved_embargo_bars} bars"
        )

    fold_idx = 0
    cursor = t0 + pd.DateOffset(years=train_years)
    while cursor + pd.DateOffset(months=test_months) <= tf:
        planned_train_start_ts = t0 if window_mode == "anchored" else cursor - pd.DateOffset(years=train_years)
        planned_train_end_ts = cursor
        train_start = planned_train_start_ts.to_pydatetime()
        train_end = (planned_train_end_ts - gap_delta).to_pydatetime()
        test_start = cursor.to_pydatetime()
        test_end = (cursor + pd.DateOffset(months=test_months)).to_pydatetime()
        planned_train_start = planned_train_start_ts.to_pydatetime()
        planned_train_end = planned_train_end_ts.to_pydatetime()

        train_mask = _date_mask(df, train_start, train_end)
        test_mask = _date_mask(df, test_start, test_end)
        train_df = df.loc[train_mask].reset_index(drop=True)
        test_df = df.loc[test_mask].reset_index(drop=True)
        boundary_gap_minutes = float((pd.Timestamp(test_start) - pd.Timestamp(train_end)) / pd.Timedelta(minutes=1))
        purge_embargo_ok = boundary_gap_minutes + 1e-9 >= float(gap_delta / pd.Timedelta(minutes=1))

        if progress:
            print(
                f"   WF fold {fold_idx + 1}/{estimated_folds}: "
                f"train {train_start:%Y-%m-%d} -> {train_end:%Y-%m-%d} "
                f"(planned {planned_train_end:%Y-%m-%d}), "
                f"test {test_start:%Y-%m-%d} -> {test_end:%Y-%m-%d}"
            )

        best_score = float("-inf")
        best_overrides: dict[str, Any] = {}
        train_rows: list[dict[str, Any]] = []

        for combo_idx, overrides in enumerate(combos, start=1):
            train_results = _run_segment(
                train_df,
                raw_data=raw_data,
                futures_specs=futures_specs,
                base_params=base_params,
                starting_capital=starting_capital,
                overrides=overrides,
            )
            score = _score_from_results(train_results, metric=metric, min_trades=min_trades_train)
            train_rows.append({"overrides": dict(overrides), "score": score, "results": train_results})
            interim_best = _select_best_row(train_rows, param_grid, selection_mode)
            best_score = float(interim_best["score"])
            best_overrides = dict(interim_best["overrides"])
            if progress and (combo_idx == 1 or combo_idx == len(combos) or combo_idx % 5 == 0):
                print(
                    f"      sample {combo_idx}/{len(combos)} "
                    f"best_score={best_score:.4f}"
                )

        selected = _select_best_row(train_rows, param_grid, selection_mode)
        best_score = float(selected["score"])
        best_overrides = dict(selected["overrides"])
        train_neighbor_metric, train_selection_metric, selected_train_trades = _row_selection_diagnostics(
            selected,
            train_rows,
            param_grid,
            selection_mode,
        )

        # OOS test with capital carry-forward
        # Floor capital at 50% of starting to prevent nonsensical sizing
        oos_capital = max(current_capital, starting_capital * 0.5)
        test_results = _run_segment(
            test_df,
            raw_data=raw_data,
            futures_specs=futures_specs,
            base_params=base_params,
            starting_capital=oos_capital,
            overrides=best_overrides,
        )

        if "error" not in test_results:
            trades = test_results["trades"].copy()
            if len(trades) >= min_trades_test:
                stitched_trades.append(trades)
                current_capital = float(test_results.get("final_equity", current_capital))

        folds.append(
            WalkForwardFoldResult(
                fold_idx=fold_idx,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                best_overrides=dict(best_overrides),
                train_metric=float(best_score),
                test_results=test_results,
                train_neighbor_metric=train_neighbor_metric,
                train_selection_metric=train_selection_metric,
                selected_train_trades=selected_train_trades,
                planned_train_start=planned_train_start,
                planned_train_end=planned_train_end,
                window_mode=window_mode,
                purge_bars=resolved_purge_bars,
                embargo_bars=resolved_embargo_bars,
                gap_bars=gap_bars,
                bar_interval_minutes=bar_interval_minutes,
                boundary_gap_minutes=boundary_gap_minutes,
                train_rows=int(len(train_df)),
                test_rows=int(len(test_df)),
                purge_embargo_ok=bool(purge_embargo_ok),
            )
        )

        if write_fold_csv:
            fold_rows = []
            for f in folds:
                tr = f.test_results
                test_metric = _score_from_results(tr, metric=metric, min_trades=min_trades_test)
                train_neighbor_ratio = (
                    float(f.train_neighbor_metric) / float(f.train_metric)
                    if np.isfinite(f.train_neighbor_metric) and np.isfinite(f.train_metric) and float(f.train_metric) > 0
                    else np.nan
                )
                fold_rows.append(
                    {
                        "fold_idx": f.fold_idx,
                        "window_mode": f.window_mode,
                        "planned_train_start": f.planned_train_start,
                        "planned_train_end": f.planned_train_end,
                        "train_start": f.train_start,
                        "train_end": f.train_end,
                        "test_start": f.test_start,
                        "test_end": f.test_end,
                        "purge_bars": f.purge_bars,
                        "embargo_bars": f.embargo_bars,
                        "gap_bars": f.gap_bars,
                        "bar_interval_minutes": f.bar_interval_minutes,
                        "boundary_gap_minutes": f.boundary_gap_minutes,
                        "train_rows": f.train_rows,
                        "test_rows": f.test_rows,
                        "purge_embargo_ok": f.purge_embargo_ok,
                        "train_metric": f.train_metric,
                        "train_neighbor_metric": f.train_neighbor_metric,
                        "train_neighbor_ratio": train_neighbor_ratio,
                        "train_selection_metric": f.train_selection_metric,
                        "selected_train_trades": f.selected_train_trades,
                        "test_metric": test_metric,
                        "test_total_trades": tr.get("total_trades", 0),
                        "test_total_pnl": tr.get("total_pnl", 0.0),
                        "test_sharpe": tr.get("sharpe_ratio", 0.0),
                        "test_profit_factor": tr.get("profit_factor", 0.0),
                        "test_bar_profit_factor": tr.get("bar_profit_factor", 0.0),
                        "test_execution_bar_profit_factor": tr.get("execution_bar_profit_factor", 0.0),
                        "best_overrides": f.best_overrides,
                    }
                )
            pd.DataFrame(fold_rows).to_csv(fold_summary_csv, index=False)
            if progress:
                print(
                    f"      saved fold summary: {fold_summary_csv} "
                    f"(completed {fold_idx + 1}/{estimated_folds})"
                )

        fold_idx += 1
        cursor = cursor + pd.DateOffset(months=step_months)

    if len(stitched_trades) == 0:
        stitched_df = pd.DataFrame()
        stitched_results = {"error": "No stitched OOS folds produced any trades."}
    else:
        stitched_df = pd.concat(stitched_trades, ignore_index=True)
        stitched_df["entry_time"] = pd.to_datetime(stitched_df["entry_time"])
        stitched_df["exit_time"] = pd.to_datetime(stitched_df["exit_time"])
        stitched_df = stitched_df.sort_values("exit_time").reset_index(drop=True)

        stitched_results = summarize_trades(
            stitched_df,
            starting_capital=starting_capital,
            pre_df=df,
            futures_specs=futures_specs,
            execution_df=raw_data,
        )
        if write_fold_csv:
            stitched_df.to_csv(stitched_trades_csv, index=False)

    return WalkForwardResult(
        folds=folds,
        stitched_trades=stitched_df,
        stitched_results=stitched_results,
        fold_summary_csv=fold_summary_csv,
        stitched_trades_csv=stitched_trades_csv if write_fold_csv else None,
    )
