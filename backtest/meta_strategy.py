"""
Meta-Strategy — dynamically select between candidate configs based on recent
regime performance, then stitch a single equity curve.

The core idea: different candidates perform in different regimes.  A meta-
strategy that picks the right candidate for the current regime should
outperform any single candidate over the full history.

Architecture
------------
1. Define a *selector* that measures each candidate's recent performance.
2. On each evaluation window, pick the best candidate.
3. Trade the chosen candidate until the next evaluation.
4. Stitch all trades into a single equity curve.

The selector is intentionally simple at first — median profit factor over
the trailing N trades — so the meta-strategy results are interpretable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MetaStrategyPaths:
    stitched_trades_csv: Path
    selection_history_csv: Path
    candidate_performance_csv: Path
    summary_csv: Path


@dataclass(frozen=True)
class MetaSelection:
    eval_time: pd.Timestamp
    selected_candidate: str
    candidate_scores: dict[str, float]


SelectorFn = Callable[
    [dict[str, pd.DataFrame], pd.Timestamp, int],
    dict[str, float],
]


def _rolling_profit_factor_selector(
    candidate_trades: dict[str, pd.DataFrame],
    current_time: pd.Timestamp,
    trailing_trades: int,
) -> dict[str, float]:
    """
    Score each candidate by the profit factor of its *most recent* N trades
    as of *current_time*.  Candidates with fewer than min_trades get -inf.
    """
    scores: dict[str, float] = {}
    min_trades = max(5, int(trailing_trades))
    for name, trades in candidate_trades.items():
        if trades.empty or "pnl" not in trades.columns or "exit_time" not in trades.columns:
            scores[name] = float("-inf")
            continue

        work = trades.copy()
        work["exit_time"] = pd.to_datetime(work["exit_time"])
        recent = work.loc[work["exit_time"] <= current_time].sort_values("exit_time", ascending=False)

        if len(recent) < min_trades:
            scores[name] = float("-inf")
            continue

        recent_pnl = recent.head(min_trades)["pnl"].astype(float)
        wins = float(recent_pnl[recent_pnl > 0].sum())
        losses = abs(float(recent_pnl[recent_pnl <= 0].sum()))
        scores[name] = wins / losses if losses > 0 else (float("inf") if wins > 0 else 0.0)

    return scores


def _get_selector(name: str, trailing_trades: int) -> SelectorFn:
    if name == "rolling_profit_factor":
        return lambda c, t, _: _rolling_profit_factor_selector(c, t, trailing_trades)
    if name == "rolling_expectancy":
        return lambda c, t, _: {
            k: float(v.loc[v["exit_time"] <= t, "pnl"].tail(trailing_trades).mean())
            if not v.empty and "pnl" in v.columns and "exit_time" in v.columns
            else float("-inf")
            for k, v in c.items()
        }
    raise ValueError(f"Unknown selector: {name}")


@dataclass
class MetaStrategyResult:
    stitched_trades: pd.DataFrame
    selection_history: list[MetaSelection]
    candidate_trade_map: dict[str, pd.DataFrame]
    params: dict[str, Any]


def run_meta_strategy(
    candidate_results: dict[str, dict[str, Any]],
    *,
    selector: str = "rolling_profit_factor",
    trailing_trades: int = 20,
    min_trades_per_candidate: int = 5,
    eval_frequency_bars: int = 12,
    starting_capital: float = 100000.0,
    futures_specs: dict[str, Any] | None = None,
    out_dir: str | Path = "results/meta_strategy",
    artifact_name: str = "meta_strategy",
) -> MetaStrategyPaths:
    """
    Run a meta-strategy over a set of candidate backtest results.

    Parameters
    ----------
    candidate_results : dict of {name: results_dict}
        Each results dict must contain a 'trades' DataFrame with at least
        'pnl', 'exit_time' columns.
    selector : str
        Selection function name ('rolling_profit_factor' or 'rolling_expectancy').
    trailing_trades : int
        Number of recent trades to evaluate for selection.
    min_trades_per_candidate : int
        Minimum trades before a candidate can be selected.
    eval_frequency_bars : int
        How many 5-min bars between re-evaluations.
    starting_capital : float
        Starting capital for stitched equity curve.
    futures_specs : dict or None
        If provided, used for cost calculation in stitched trades.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Validate candidates
    valid_candidates: dict[str, pd.DataFrame] = {}
    for name, results in candidate_results.items():
        trades = results.get("trades")
        if isinstance(trades, pd.DataFrame) and not trades.empty and "pnl" in trades.columns:
            valid_candidates[name] = trades.copy()
        else:
            print(f"   ⚠️ Meta-strategy: skipping '{name}' — no valid trades found.")

    if len(valid_candidates) < 2:
        raise ValueError("Meta-strategy requires at least 2 valid candidates.")

    selector_fn = _get_selector(selector, trailing_trades)
    all_times = pd.concat([
        trades["exit_time"] for trades in valid_candidates.values()
    ]).dropna().unique()
    all_times = pd.Series(sorted(pd.to_datetime(all_times)))

    if all_times.empty:
        raise ValueError("No trade timestamps found across candidates.")

    # Build candidate trade maps by exit_time
    candidate_trade_map: dict[str, pd.DataFrame] = {}
    for name, trades in valid_candidates.items():
        df = trades.copy()
        df["exit_time"] = pd.to_datetime(df["exit_time"])
        candidate_trade_map[name] = df.sort_values("exit_time").reset_index(drop=True)

    selection_history: list[MetaSelection] = []
    stitched_trades: list[pd.DataFrame] = []
    current_capital = float(starting_capital)

    selected_name: str | None = None
    active_trades_since_eval: list[pd.DataFrame] = []

    # Partial evaluation: every eval_frequency_bars bars (approximate 5-min bars)
    eval_indices = list(range(0, len(all_times), max(1, int(eval_frequency_bars))))

    for eval_pos in range(len(all_times)):
        current_time = pd.to_datetime(all_times.iloc[eval_pos])

        # Re-evaluate at specified intervals
        if eval_pos in eval_indices or selected_name is None:
            scores = selector_fn(candidate_trade_map, current_time, trailing_trades)
            best_candidate = max(scores, key=scores.get)

            if selected_name is not None and best_candidate != selected_name:
                # Close any active trades from the prior candidate (flush)
                active_trades_since_eval = []

            selected_name = best_candidate
            selection_history.append(MetaSelection(
                eval_time=current_time,
                selected_candidate=selected_name,
                candidate_scores=scores,
            ))

        # Get trades from the selected candidate that occurred after the last
        # selection. This is a simplified approach: we take the candidate's
        # trades that we haven't yet stitched.
        if selected_name is not None:
            cand_trades = candidate_trade_map[selected_name]
            last_stitched_time = (
                pd.Timestamp(stitched_trades[-1]["exit_time"].max())
                if stitched_trades
                else pd.Timestamp.min
            )
            new_trades = cand_trades.loc[
                (cand_trades["exit_time"] > last_stitched_time)
                & (cand_trades["exit_time"] <= current_time)
            ].copy()

            if not new_trades.empty:
                # Scale PnL to current capital
                cand_start = float(candidate_results[selected_name].get("starting_capital", starting_capital))
                scale_factor = current_capital / max(cand_start, 1.0)
                new_trades["pnl"] = new_trades["pnl"].astype(float) * scale_factor
                new_trades["equity"] = current_capital + new_trades["pnl"].cumsum()
                stitched_trades.append(new_trades)
                current_capital = float(new_trades["equity"].iloc[-1])

    if not stitched_trades:
        raise ValueError("Meta-strategy produced no stitched trades.")

    stitched_df = pd.concat(stitched_trades, ignore_index=True)
    stitched_df = stitched_df.sort_values("exit_time").reset_index(drop=True)

    # Selection history to DataFrame
    selection_df = pd.DataFrame([
        {
            "eval_time": s.eval_time,
            "selected_candidate": s.selected_candidate,
            **{f"score_{k}": v for k, v in s.candidate_scores.items()},
        }
        for s in selection_history
    ])

    # Candidate performance summary
    perf_rows = []
    for name, trades in candidate_trade_map.items():
        pnl = trades["pnl"].astype(float)
        wins = pnl > 0
        perf_rows.append({
            "candidate": name,
            "trades": int(len(trades)),
            "total_pnl": float(pnl.sum()),
            "profit_factor": float(pnl[pnl > 0].sum() / max(abs(float(pnl[pnl <= 0].sum())), 1e-12)),
            "win_rate": float(wins.mean() * 100.0),
            "avg_trade": float(pnl.mean()),
            "selection_count": int((selection_df["selected_candidate"] == name).sum()) if "selected_candidate" in selection_df.columns else 0,
        })
    perf_df = pd.DataFrame(perf_rows)

    # Summary
    stitched_pnl = stitched_df["pnl"].astype(float)
    summary = {
        "strategy": "meta_strategy",
        "selector": selector,
        "trailing_trades": int(trailing_trades),
        "eval_frequency_bars": int(eval_frequency_bars),
        "candidates": len(valid_candidates),
        "total_stitched_trades": int(len(stitched_df)),
        "total_pnl": float(stitched_pnl.sum()),
        "final_equity": float(starting_capital + stitched_pnl.sum()),
        "profit_factor": float(
            stitched_pnl[stitched_pnl > 0].sum()
            / max(abs(float(stitched_pnl[stitched_pnl <= 0].sum())), 1e-12)
        ),
        "win_rate": float((stitched_pnl > 0).mean() * 100.0),
        "avg_trade": float(stitched_pnl.mean()),
    }
    summary_df = pd.DataFrame([summary])

    stitched_csv = out_dir / f"{artifact_name}_stitched_trades.csv"
    selection_csv = out_dir / f"{artifact_name}_selection_history.csv"
    candidate_csv = out_dir / f"{artifact_name}_candidate_performance.csv"
    summary_csv = out_dir / f"{artifact_name}_summary.csv"

    stitched_df.to_csv(stitched_csv, index=False)
    selection_df.to_csv(selection_csv, index=False)
    perf_df.to_csv(candidate_csv, index=False)
    summary_df.to_csv(summary_csv, index=False)

    return MetaStrategyPaths(
        stitched_trades_csv=stitched_csv,
        selection_history_csv=selection_csv,
        candidate_performance_csv=candidate_csv,
        summary_csv=summary_csv,
    )