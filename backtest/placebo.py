from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.portfolio import Portfolio


LEVEL_PRICE_RE = re.compile(r"^mp_level_(\d+)_price$")


@dataclass(frozen=True)
class PlaceboTestResult:
    summary_csv: Path
    actual_total_pnl: float
    actual_profit_factor: float
    placebo_total_pnl_p_value: float
    placebo_profit_factor_p_value: float
    n_placebos: int


def _resolve_max_drawdown_pct(params: dict[str, Any]) -> float | None:
    if not params.get("enable_circuit_breaker", False):
        return None
    value = params.get("max_drawdown_pct")
    return None if value is None else float(value)


def _level_price_columns(df: pd.DataFrame) -> list[str]:
    pairs: list[tuple[int, str]] = []
    for col in df.columns:
        match = LEVEL_PRICE_RE.match(col)
        if match:
            pairs.append((int(match.group(1)), col))
    return [col for _, col in sorted(pairs)]


def _profit_factor_from_pnl(pnl: pd.Series) -> float:
    wins = float(pnl[pnl > 0].sum())
    losses = abs(float(pnl[pnl <= 0].sum()))
    if losses <= 0:
        return np.nan
    return wins / losses


def _result_row(label: str, seed: int | None, results: dict[str, Any]) -> dict[str, Any]:
    if "error" in results:
        return {
            "simulation": label,
            "seed": seed,
            "error": results["error"],
            "trades": 0,
            "total_pnl": np.nan,
            "profit_factor": np.nan,
            "avg_trade": np.nan,
            "max_drawdown": np.nan,
        }
    return {
        "simulation": label,
        "seed": seed,
        "error": "",
        "trades": int(results.get("total_trades", 0)),
        "total_pnl": float(results.get("total_pnl", np.nan)),
        "profit_factor": float(results.get("profit_factor", np.nan)),
        "avg_trade": float(results.get("expectancy", np.nan)),
        "max_drawdown": float(results.get("max_drawdown", np.nan)),
    }


def _execute_on_preprocessed(
    pre_df: pd.DataFrame,
    raw_data: pd.DataFrame,
    futures_specs: dict[str, Any],
    params: dict[str, Any],
    starting_capital: float,
) -> dict[str, Any]:
    portfolio = Portfolio(
        starting_capital,
        futures_specs,
        max_drawdown_pct=_resolve_max_drawdown_pct(params),
    )
    engine = BacktestEngine(raw_data, portfolio, futures_specs, params)
    return engine.run_on_preprocessed(pre_df)


def _assign_placebo_levels_by_refresh_block(
    df: pd.DataFrame,
    level_cols: list[str],
    rng: np.random.Generator,
    min_offset_points: float,
    max_offset_points: float,
) -> pd.DataFrame:
    out = df.copy()
    if "mp_profile_stale_bars" in out.columns:
        refresh = out["mp_profile_stale_bars"].fillna(-1).eq(0) & out["mp_level_count"].fillna(0).gt(0)
        block_id = refresh.cumsum()
        block_id = block_id.where(block_id.gt(0), np.nan)
    elif "date_str" in out.columns:
        block_id = out["date_str"].astype("category").cat.codes.replace(-1, np.nan)
    else:
        block_id = pd.Series(1, index=out.index)

    min_offset_points = abs(float(min_offset_points))
    max_offset_points = max(min_offset_points, abs(float(max_offset_points)))

    codes, uniques = pd.factorize(block_id, sort=False)
    valid_codes = codes >= 0
    if len(uniques) == 0 or not valid_codes.any():
        return out

    offsets = rng.uniform(min_offset_points, max_offset_points, size=(len(uniques), len(level_cols)))
    offsets *= rng.choice([-1.0, 1.0], size=(len(uniques), len(level_cols)))

    levels = out[level_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float).copy()
    levels[valid_codes] = levels[valid_codes] + offsets[codes[valid_codes]]
    out.loc[:, level_cols] = levels
    return out


def recompute_market_profile_relation_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    level_cols = _level_price_columns(out)
    if not level_cols:
        return out

    n = len(out)
    for col in (
        "mp_nearest_support",
        "mp_nearest_resistance",
        "mp_dist_to_support",
        "mp_dist_to_resistance",
        "mp_support_prominence",
        "mp_resistance_prominence",
        "mp_crossed_up_level",
        "mp_crossed_down_level",
        "mp_crossed_up_prominence",
        "mp_crossed_down_prominence",
    ):
        out[col] = np.nan
    out["mp_crossed_up"] = False
    out["mp_crossed_down"] = False
    close = pd.to_numeric(out["close"], errors="coerce").to_numpy(dtype=float)
    levels_matrix = out[level_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    prominence_matrix = np.full_like(levels_matrix, np.nan, dtype=float)
    for idx, price_col in enumerate(level_cols):
        prom_col = price_col.replace("_price", "_prominence")
        if prom_col in out.columns:
            prominence_matrix[:, idx] = pd.to_numeric(out[prom_col], errors="coerce").to_numpy(dtype=float)

    valid_levels = np.isfinite(levels_matrix)
    out["mp_level_count"] = valid_levels.sum(axis=1).astype(float)
    close_2d = close[:, None]

    support_mask = valid_levels & np.isfinite(close_2d) & (levels_matrix < close_2d)
    support_dist = np.where(support_mask, close_2d - levels_matrix, np.inf)
    support_idx = np.argmin(support_dist, axis=1)
    row_idx = np.arange(n)
    has_support = np.isfinite(support_dist[row_idx, support_idx])
    support_values = levels_matrix[row_idx, support_idx]
    support_proms = prominence_matrix[row_idx, support_idx]
    out.loc[has_support, "mp_nearest_support"] = support_values[has_support]
    out.loc[has_support, "mp_dist_to_support"] = support_dist[row_idx, support_idx][has_support]
    out.loc[has_support, "mp_support_prominence"] = support_proms[has_support]

    resistance_mask = valid_levels & np.isfinite(close_2d) & (levels_matrix > close_2d)
    resistance_dist = np.where(resistance_mask, levels_matrix - close_2d, np.inf)
    resistance_idx = np.argmin(resistance_dist, axis=1)
    has_resistance = np.isfinite(resistance_dist[row_idx, resistance_idx])
    resistance_values = levels_matrix[row_idx, resistance_idx]
    resistance_proms = prominence_matrix[row_idx, resistance_idx]
    out.loc[has_resistance, "mp_nearest_resistance"] = resistance_values[has_resistance]
    out.loc[has_resistance, "mp_dist_to_resistance"] = resistance_dist[row_idx, resistance_idx][has_resistance]
    out.loc[has_resistance, "mp_resistance_prominence"] = resistance_proms[has_resistance]

    prior_close = np.empty_like(close)
    prior_close[0] = np.nan
    prior_close[1:] = close[:-1]
    prior_2d = prior_close[:, None]

    crossed_up_mask = valid_levels & np.isfinite(prior_2d) & np.isfinite(close_2d) & (prior_2d <= levels_matrix) & (close_2d > levels_matrix)
    crossed_up_levels = np.where(crossed_up_mask, levels_matrix, -np.inf)
    crossed_up_idx = np.argmax(crossed_up_levels, axis=1)
    crossed_up_value = crossed_up_levels[row_idx, crossed_up_idx]
    has_crossed_up = np.isfinite(crossed_up_value)
    crossed_up_proms = prominence_matrix[row_idx, crossed_up_idx]
    out.loc[has_crossed_up, "mp_crossed_up"] = True
    out.loc[has_crossed_up, "mp_crossed_up_level"] = crossed_up_value[has_crossed_up]
    out.loc[has_crossed_up, "mp_crossed_up_prominence"] = crossed_up_proms[has_crossed_up]

    crossed_down_mask = valid_levels & np.isfinite(prior_2d) & np.isfinite(close_2d) & (prior_2d >= levels_matrix) & (close_2d < levels_matrix)
    crossed_down_levels = np.where(crossed_down_mask, levels_matrix, np.inf)
    crossed_down_idx = np.argmin(crossed_down_levels, axis=1)
    crossed_down_value = crossed_down_levels[row_idx, crossed_down_idx]
    has_crossed_down = np.isfinite(crossed_down_value)
    crossed_down_proms = prominence_matrix[row_idx, crossed_down_idx]
    out.loc[has_crossed_down, "mp_crossed_down"] = True
    out.loc[has_crossed_down, "mp_crossed_down_level"] = crossed_down_value[has_crossed_down]
    out.loc[has_crossed_down, "mp_crossed_down_prominence"] = crossed_down_proms[has_crossed_down]
    return out


def apply_market_profile_placebo(
    pre_df: pd.DataFrame,
    *,
    seed: int,
    min_offset_points: float = 4.0,
    max_offset_points: float = 40.0,
) -> pd.DataFrame:
    level_cols = _level_price_columns(pre_df)
    if not level_cols:
        raise ValueError("No mp_level_*_price columns found. Run market-profile preprocessing first.")
    rng = np.random.default_rng(seed)
    shifted = _assign_placebo_levels_by_refresh_block(
        pre_df,
        level_cols=level_cols,
        rng=rng,
        min_offset_points=min_offset_points,
        max_offset_points=max_offset_points,
    )
    return recompute_market_profile_relation_columns(shifted)


def run_market_profile_placebo_test(
    *,
    pre_df: pd.DataFrame,
    raw_data: pd.DataFrame,
    futures_specs: dict[str, Any],
    params: dict[str, Any],
    starting_capital: float,
    out_dir: Path | str,
    artifact_name: str = "market_profile_placebo",
    n_placebos: int = 25,
    seed: int = 7,
    min_offset_points: float = 4.0,
    max_offset_points: float = 40.0,
    verbose: bool = True,
) -> PlaceboTestResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = out_dir / f"{artifact_name}_summary.csv"

    def write_partial_summary() -> None:
        pd.DataFrame(rows).to_csv(summary_csv, index=False)

    rows: list[dict[str, Any]] = []
    if verbose:
        print("Placebo test: running actual strategy on unshifted market-profile levels...", flush=True)
    actual_results = _execute_on_preprocessed(pre_df, raw_data, futures_specs, params, starting_capital)
    rows.append(_result_row("actual", None, actual_results))
    write_partial_summary()

    for idx in range(int(n_placebos)):
        placebo_seed = int(seed + idx)
        if verbose:
            print(
                f"Placebo test: {idx + 1}/{int(n_placebos)} seed={placebo_seed} "
                "shifting levels and rerunning strategy...",
                flush=True,
            )
        placebo_df = apply_market_profile_placebo(
            pre_df,
            seed=placebo_seed,
            min_offset_points=min_offset_points,
            max_offset_points=max_offset_points,
        )
        placebo_results = _execute_on_preprocessed(placebo_df, raw_data, futures_specs, params, starting_capital)
        rows.append(_result_row("placebo", placebo_seed, placebo_results))
        write_partial_summary()

    summary = pd.DataFrame(rows)
    actual = summary.loc[summary["simulation"].eq("actual")].iloc[0]
    placebos = summary.loc[summary["simulation"].eq("placebo")].copy()

    actual_total = float(actual["total_pnl"])
    actual_pf = float(actual["profit_factor"])
    placebo_total_p = float((1 + (placebos["total_pnl"] >= actual_total).sum()) / (len(placebos) + 1))
    placebo_pf_p = float((1 + (placebos["profit_factor"] >= actual_pf).sum()) / (len(placebos) + 1))

    summary["actual_total_pnl"] = actual_total
    summary["actual_profit_factor"] = actual_pf
    summary["placebo_total_pnl_p_value"] = placebo_total_p
    summary["placebo_profit_factor_p_value"] = placebo_pf_p

    summary.to_csv(summary_csv, index=False)

    return PlaceboTestResult(
        summary_csv=summary_csv,
        actual_total_pnl=actual_total,
        actual_profit_factor=actual_pf,
        placebo_total_pnl_p_value=placebo_total_p,
        placebo_profit_factor_p_value=placebo_pf_p,
        n_placebos=int(n_placebos),
    )
