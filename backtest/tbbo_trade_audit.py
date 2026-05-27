from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

from backtest.execution_cost_stress import (
    VolatilityConditionedCostStressConfig,
    add_volatility_conditioned_cost_stress,
)
from backtest.microstructure_diagnostics import build_microstructure_cost_state


DEFAULT_FUTURES_SPECS = {
    "contract_value": 20.0,
    "slippage_points": 0.75,
    "slippage_stop_points": 1.00,
    "slippage_limit_points": 0.25,
}
STOP_EXIT_REASONS = frozenset(
    {
        "stop_loss",
        "hard_stop",
        "managed_stop",
        "time_exit",
        "end_of_data",
        "hawkes_vol_exit",
    }
)
LIMIT_EXIT_REASONS = frozenset({"profit_target", "hard_target"})


@dataclass(frozen=True)
class TbboTradeAudit:
    audited_trades: pd.DataFrame
    summary: pd.DataFrame
    by_setup: pd.DataFrame


def read_trade_log(path: Path | str) -> pd.DataFrame:
    return pd.read_csv(path)


def read_tbbo_minute_stats(path: Path | str) -> pd.DataFrame:
    return pd.read_csv(path)


def build_tbbo_trade_audit(
    trades: pd.DataFrame,
    minute_stats: pd.DataFrame,
    *,
    futures_specs: Mapping[str, float] | None = None,
    volatility_state: pd.DataFrame | None = None,
    volatility_cost_config: VolatilityConditionedCostStressConfig | None = None,
    nearest_tolerance: str | pd.Timedelta = "1min",
) -> TbboTradeAudit:
    specs = dict(DEFAULT_FUTURES_SPECS)
    if futures_specs is not None:
        specs.update({k: float(v) for k, v in futures_specs.items() if k in specs})

    prepared_trades = _prepare_trades(trades)
    prepared_stats = _prepare_minute_stats(minute_stats)
    prepared_stats = _add_microstructure_cost_state_columns(prepared_stats)
    prepared_volatility = _prepare_volatility_state(volatility_state)
    active_symbol = _active_symbol_by_date(prepared_stats)

    audited = prepared_trades.copy()
    for event in ("entry", "exit"):
        audited = _attach_event_stats(
            audited,
            prepared_stats,
            active_symbol=active_symbol,
            event=event,
            nearest_tolerance=nearest_tolerance,
        )
        audited = _attach_event_volatility_context(
            audited,
            prepared_volatility,
            event=event,
            nearest_tolerance=nearest_tolerance,
        )

    audited = _add_cost_estimates(
        audited,
        futures_specs=specs,
        volatility_cost_config=volatility_cost_config,
    )
    summary = summarize_tbbo_trade_audit(audited)
    by_setup = summarize_tbbo_trade_audit_by_setup(audited)
    return TbboTradeAudit(audited_trades=audited, summary=summary, by_setup=by_setup)


def write_tbbo_trade_audit(
    audit: TbboTradeAudit,
    out_dir: Path | str,
    *,
    prefix: str = "trade_tbbo_execution",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "trades": out_path / f"{prefix}_audit.csv",
        "summary": out_path / f"{prefix}_summary.csv",
        "by_setup": out_path / f"{prefix}_by_setup.csv",
    }
    audit.audited_trades.to_csv(paths["trades"], index=False)
    audit.summary.to_csv(paths["summary"], index=False)
    audit.by_setup.to_csv(paths["by_setup"], index=False)
    return paths


def summarize_tbbo_trade_audit(audited: pd.DataFrame) -> pd.DataFrame:
    total = len(audited)
    in_window = audited["entry_active_symbol"].notna() | audited["exit_active_symbol"].notna()
    matched = audited["tbbo_entry_exit_matched"].fillna(False)
    matched_df = audited.loc[matched].copy()
    summary = {
        "total_trades": int(total),
        "tbbo_window_trades": int(in_window.sum()),
        "entry_matched_trades": int(audited["entry_tbbo_matched"].fillna(False).sum()),
        "exit_matched_trades": int(audited["exit_tbbo_matched"].fillna(False).sum()),
        "entry_exit_matched_trades": int(matched.sum()),
        "entry_exit_match_rate_in_window": _safe_ratio(matched.sum(), in_window.sum()),
    }
    numeric_cols = [
        "pnl",
        "pnl_with_tbbo_median_spread_cost",
        "pnl_with_tbbo_p95_spread_cost",
        "pnl_with_tbbo_p95_trade_vs_mid_cost",
        "pnl_with_tbbo_p95_trade_vs_mid_and_limit_opportunity_cost",
        "assumed_slippage_points",
        "limit_exit_opportunity_stress_points",
        "limit_exit_opportunity_stress_dollars",
        "tbbo_median_round_trip_spread_cost_points",
        "tbbo_p95_round_trip_spread_cost_points",
        "tbbo_p95_trade_vs_mid_round_trip_points",
        "tbbo_median_spread_cost_minus_assumed_points",
        "tbbo_p95_spread_cost_minus_assumed_points",
        "tbbo_p95_trade_vs_mid_cost_minus_assumed_points",
        "vol_conditioned_round_trip_cost_points",
        "vol_conditioned_round_trip_cost_dollars",
        "vol_conditioned_cost_minus_assumed_points",
        "vol_conditioned_max_slippage_multiplier",
        "pnl_with_vol_conditioned_cost",
        "pnl_with_vol_conditioned_cost_if_accepted",
    ]
    for col in numeric_cols:
        if col in matched_df.columns and not matched_df.empty:
            values = pd.to_numeric(matched_df[col], errors="coerce")
            summary[f"matched_sum_{col}"] = float(values.sum(skipna=True))
            summary[f"matched_median_{col}"] = float(values.median(skipna=True))
        else:
            summary[f"matched_sum_{col}"] = np.nan
            summary[f"matched_median_{col}"] = np.nan
    if "vol_conditioned_reject_fill" in matched_df.columns and not matched_df.empty:
        rejected = matched_df["vol_conditioned_reject_fill"].fillna(False).astype(bool)
        summary["matched_vol_conditioned_rejected_fills"] = int(rejected.sum())
        summary["matched_vol_conditioned_rejected_fill_pct"] = _safe_ratio(rejected.sum(), len(matched_df))
    else:
        summary["matched_vol_conditioned_rejected_fills"] = 0
        summary["matched_vol_conditioned_rejected_fill_pct"] = np.nan
    return pd.DataFrame([summary])


def summarize_tbbo_trade_audit_by_setup(audited: pd.DataFrame) -> pd.DataFrame:
    matched = audited.loc[audited["tbbo_entry_exit_matched"].fillna(False)].copy()
    if matched.empty:
        return pd.DataFrame(
            columns=[
                "setup_tag",
                "direction",
                "trades",
                "pnl",
                "pnl_with_tbbo_median_spread_cost",
                "pnl_with_tbbo_p95_spread_cost",
                "pnl_with_tbbo_p95_trade_vs_mid_cost",
                "pnl_with_tbbo_p95_trade_vs_mid_and_limit_opportunity_cost",
                "median_assumed_slippage_points",
                "median_tbbo_median_round_trip_spread_cost_points",
                "median_tbbo_p95_round_trip_spread_cost_points",
                "median_limit_exit_opportunity_stress_points",
                "median_vol_conditioned_round_trip_cost_points",
                "vol_conditioned_rejected_fills",
                "pnl_with_vol_conditioned_cost",
                "pnl_with_vol_conditioned_cost_if_accepted",
            ]
        )
    for col in ("setup_tag", "direction"):
        if col not in matched.columns:
            matched[col] = ""
    grouped = matched.groupby(["setup_tag", "direction"], dropna=False)
    return grouped.agg(
        trades=("pnl", "size"),
        pnl=("pnl", "sum"),
        pnl_with_tbbo_median_spread_cost=("pnl_with_tbbo_median_spread_cost", "sum"),
        pnl_with_tbbo_p95_spread_cost=("pnl_with_tbbo_p95_spread_cost", "sum"),
        pnl_with_tbbo_p95_trade_vs_mid_cost=("pnl_with_tbbo_p95_trade_vs_mid_cost", "sum"),
        pnl_with_tbbo_p95_trade_vs_mid_and_limit_opportunity_cost=(
            "pnl_with_tbbo_p95_trade_vs_mid_and_limit_opportunity_cost",
            "sum",
        ),
        median_assumed_slippage_points=("assumed_slippage_points", "median"),
        median_tbbo_median_round_trip_spread_cost_points=(
            "tbbo_median_round_trip_spread_cost_points",
            "median",
        ),
        median_tbbo_p95_round_trip_spread_cost_points=(
            "tbbo_p95_round_trip_spread_cost_points",
            "median",
        ),
        median_limit_exit_opportunity_stress_points=("limit_exit_opportunity_stress_points", "median"),
        median_vol_conditioned_round_trip_cost_points=("vol_conditioned_round_trip_cost_points", "median"),
        vol_conditioned_rejected_fills=("vol_conditioned_reject_fill", "sum"),
        pnl_with_vol_conditioned_cost=("pnl_with_vol_conditioned_cost", "sum"),
        pnl_with_vol_conditioned_cost_if_accepted=("pnl_with_vol_conditioned_cost_if_accepted", "sum"),
    ).reset_index()


def _prepare_trades(trades: pd.DataFrame) -> pd.DataFrame:
    required = {"entry_time", "exit_time", "pnl"}
    missing = required.difference(trades.columns)
    if missing:
        raise ValueError(f"trade log missing required columns: {sorted(missing)}")
    out = trades.copy().reset_index(drop=True)
    out.insert(0, "trade_id", np.arange(len(out)))
    for col in ("entry_time", "exit_time"):
        out[col] = pd.to_datetime(out[col], errors="coerce")
    if "contracts" not in out.columns:
        out["contracts"] = 1.0
    out["contracts"] = pd.to_numeric(out["contracts"], errors="coerce").fillna(1.0)
    out["pnl"] = pd.to_numeric(out["pnl"], errors="coerce")
    for col in ("reason", "setup_tag", "direction"):
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str)
    return out


def _prepare_minute_stats(minute_stats: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "minute", "trade_date"}
    missing = required.difference(minute_stats.columns)
    if missing:
        raise ValueError(f"TBBO minute stats missing required columns: {sorted(missing)}")
    out = minute_stats.copy()
    out["symbol"] = out["symbol"].fillna("").astype(str)
    out["minute"] = pd.to_datetime(out["minute"], errors="coerce")
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "trade_count" not in out.columns:
        out["trade_count"] = 0
    if "rth_session" in out.columns:
        if out["rth_session"].dtype != bool:
            out["rth_session"] = out["rth_session"].astype(str).str.lower().isin({"true", "1", "yes"})
    numeric_cols = [
        "rows",
        "median_mid_price",
        "median_spread_points",
        "p90_spread_points",
        "p95_spread_points",
        "median_spread_ticks",
        "p95_spread_ticks",
        "mean_bid_size",
        "mean_ask_size",
        "median_top_book_imbalance",
        "trade_count",
        "trade_size",
        "median_trade_size",
        "median_abs_trade_price_vs_mid",
        "p95_abs_trade_price_vs_mid",
        "mean_trade_price_vs_mid",
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
        "raw_b_side_count",
        "raw_a_side_count",
        "microstructure_cost_score",
        "spread_score",
        "tail_spread_score",
        "trade_vs_mid_score",
        "depth_exhaustion_score",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["symbol", "minute", "trade_date"]).sort_values(["symbol", "minute"])


def _add_microstructure_cost_state_columns(minute_stats: pd.DataFrame) -> pd.DataFrame:
    if minute_stats.empty:
        return minute_stats
    try:
        cost_state = build_microstructure_cost_state(minute_stats)
    except ValueError:
        return minute_stats
    if cost_state.empty:
        return minute_stats
    cols = [
        "symbol",
        "minute",
        "microstructure_cost_score",
        "microstructure_cost_state",
        "spread_score",
        "tail_spread_score",
        "trade_vs_mid_score",
        "depth_exhaustion_score",
    ]
    cols = [col for col in cols if col in cost_state.columns]
    if {"symbol", "minute"}.difference(cols):
        return minute_stats
    merged = minute_stats.merge(
        cost_state.loc[:, cols].drop_duplicates(subset=["symbol", "minute"], keep="last"),
        on=["symbol", "minute"],
        how="left",
        suffixes=("", "_cost_state"),
    )
    for col in cols:
        alt = f"{col}_cost_state"
        if alt in merged.columns:
            merged[col] = merged[col].where(merged[col].notna(), merged[alt])
            merged = merged.drop(columns=[alt])
    return merged


def _prepare_volatility_state(volatility_state: pd.DataFrame | None) -> pd.DataFrame:
    if volatility_state is None or volatility_state.empty:
        return pd.DataFrame()
    if "time" not in volatility_state.columns:
        raise ValueError("volatility_state must include a time column")
    out = volatility_state.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    if getattr(out["time"].dt, "tz", None) is not None:
        out["time"] = out["time"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    for col in ("realized_vol_ratio", "realized_vol_short", "realized_vol_long"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "volatility_jump_event" in out.columns and out["volatility_jump_event"].dtype != bool:
        out["volatility_jump_event"] = out["volatility_jump_event"].astype(str).str.lower().isin({"true", "1", "yes"})
    cols = [
        "time",
        "volatility_state",
        "volatility_compression_state",
        "volatility_vol_of_vol_state",
        "volatility_jump_event",
        "realized_vol_ratio",
        "realized_vol_short",
        "realized_vol_long",
    ]
    return out.loc[:, [col for col in cols if col in out.columns]].dropna(subset=["time"]).sort_values("time")


def _active_symbol_by_date(minute_stats: pd.DataFrame) -> pd.Series:
    daily = (
        minute_stats.groupby(["trade_date", "symbol"], sort=True)
        .agg(total_trades=("trade_count", "sum"), minutes=("minute", "size"))
        .reset_index()
        .sort_values(["trade_date", "total_trades", "minutes", "symbol"], ascending=[True, False, False, True])
    )
    if daily.empty:
        return pd.Series(dtype="string")
    return daily.drop_duplicates("trade_date").set_index("trade_date")["symbol"]


def _attach_event_stats(
    trades: pd.DataFrame,
    minute_stats: pd.DataFrame,
    *,
    active_symbol: pd.Series,
    event: str,
    nearest_tolerance: str | pd.Timedelta,
) -> pd.DataFrame:
    out = trades.copy()
    time_col = f"{event}_time"
    minute_col = f"{event}_minute"
    date_col = f"{event}_trade_date"
    active_col = f"{event}_active_symbol"
    matched_col = f"{event}_tbbo_matched"
    tbbo_minute_col = f"{event}_tbbo_minute"
    tbbo_symbol_col = f"{event}_tbbo_symbol"

    out[minute_col] = pd.to_datetime(out[time_col], errors="coerce").dt.floor("min")
    out[date_col] = pd.to_datetime(out[time_col], errors="coerce").dt.strftime("%Y-%m-%d")
    out[active_col] = out[date_col].map(active_symbol)

    stat_cols = [
        col
        for col in [
            "trade_date",
            "rth_session",
            "median_mid_price",
            "median_spread_points",
            "p90_spread_points",
            "p95_spread_points",
            "median_spread_ticks",
            "p95_spread_ticks",
            "mean_bid_size",
            "mean_ask_size",
            "median_top_book_imbalance",
            "trade_count",
            "trade_size",
            "median_trade_size",
            "median_abs_trade_price_vs_mid",
            "p95_abs_trade_price_vs_mid",
            "mean_trade_price_vs_mid",
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
            "raw_b_side_count",
            "raw_a_side_count",
            "microstructure_cost_score",
            "microstructure_cost_state",
            "spread_score",
            "tail_spread_score",
            "trade_vs_mid_score",
            "depth_exhaustion_score",
        ]
        if col in minute_stats.columns
    ]
    event_cols = [tbbo_minute_col, tbbo_symbol_col, f"{event}_tbbo_time_delta_seconds"] + [
        f"{event}_tbbo_{col}" for col in stat_cols
    ]
    for col in event_cols:
        if col not in out.columns:
            out[col] = pd.NA

    tolerance = pd.Timedelta(nearest_tolerance) if nearest_tolerance is not None else None
    merged_parts: list[pd.DataFrame] = []
    keyed = out.loc[out[active_col].notna() & out[minute_col].notna(), ["trade_id", minute_col, active_col]]
    for symbol, left in keyed.groupby(active_col, sort=True):
        right = minute_stats.loc[minute_stats["symbol"].eq(symbol), ["minute", *stat_cols]].copy()
        if right.empty:
            continue
        right = right.rename(columns={col: f"{event}_tbbo_{col}" for col in stat_cols})
        left = left.sort_values(minute_col)
        right = right.sort_values("minute")
        merged = pd.merge_asof(
            left,
            right,
            left_on=minute_col,
            right_on="minute",
            direction="nearest",
            tolerance=tolerance,
        ).rename(columns={"minute": tbbo_minute_col})
        merged[tbbo_symbol_col] = np.where(merged[tbbo_minute_col].notna(), str(symbol), pd.NA)
        merged[f"{event}_tbbo_time_delta_seconds"] = (
            (merged[minute_col] - merged[tbbo_minute_col]).abs().dt.total_seconds()
        )
        merged_parts.append(merged[["trade_id", *event_cols]])

    if merged_parts:
        merged_all = pd.concat(merged_parts, ignore_index=True).set_index("trade_id")
        out = out.set_index("trade_id")
        for col in event_cols:
            out.loc[merged_all.index, col] = merged_all[col]
        out = out.reset_index()

    out[matched_col] = pd.to_datetime(out[tbbo_minute_col], errors="coerce").notna()
    return out


def _attach_event_volatility_context(
    trades: pd.DataFrame,
    volatility_state: pd.DataFrame,
    *,
    event: str,
    nearest_tolerance: str | pd.Timedelta,
) -> pd.DataFrame:
    out = trades.copy()
    context_cols = [
        "volatility_state",
        "volatility_compression_state",
        "volatility_vol_of_vol_state",
        "volatility_jump_event",
        "realized_vol_ratio",
        "realized_vol_short",
        "realized_vol_long",
    ]
    event_cols = [f"{event}_{col}" for col in context_cols]
    for col in event_cols:
        if col not in out.columns:
            out[col] = pd.NA
    if volatility_state.empty:
        return out

    time_col = f"{event}_time"
    left = out.loc[:, ["trade_id", time_col]].copy()
    left[time_col] = pd.to_datetime(left[time_col], errors="coerce")
    left = left.dropna(subset=[time_col]).sort_values(time_col)
    if left.empty:
        return out

    right_cols = ["time", *[col for col in context_cols if col in volatility_state.columns]]
    right = volatility_state.loc[:, right_cols].dropna(subset=["time"]).sort_values("time")
    if right.empty:
        return out
    tolerance = pd.Timedelta(nearest_tolerance) if nearest_tolerance is not None else None
    merged = pd.merge_asof(
        left,
        right,
        left_on=time_col,
        right_on="time",
        direction="backward",
        tolerance=tolerance,
    ).set_index("trade_id")

    out = out.set_index("trade_id")
    for col in context_cols:
        event_col = f"{event}_{col}"
        if col in merged.columns:
            out.loc[merged.index, event_col] = merged[col]
    return out.reset_index()


def _add_cost_estimates(
    audited: pd.DataFrame,
    *,
    futures_specs: Mapping[str, float],
    volatility_cost_config: VolatilityConditionedCostStressConfig | None,
) -> pd.DataFrame:
    out = audited.copy()
    out["tbbo_entry_exit_matched"] = out["entry_tbbo_matched"].fillna(False) & out["exit_tbbo_matched"].fillna(False)
    for event in ("entry", "exit"):
        out[f"{event}_tbbo_median_half_spread_points"] = (
            pd.to_numeric(out.get(f"{event}_tbbo_median_spread_points"), errors="coerce") / 2.0
        )
        out[f"{event}_tbbo_p95_half_spread_points"] = (
            pd.to_numeric(out.get(f"{event}_tbbo_p95_spread_points"), errors="coerce") / 2.0
        )

    out["tbbo_median_round_trip_spread_cost_points"] = (
        out["entry_tbbo_median_half_spread_points"] + out["exit_tbbo_median_half_spread_points"]
    )
    out["tbbo_p95_round_trip_spread_cost_points"] = (
        out["entry_tbbo_p95_half_spread_points"] + out["exit_tbbo_p95_half_spread_points"]
    )
    out["tbbo_p95_trade_vs_mid_round_trip_points"] = (
        pd.to_numeric(out.get("entry_tbbo_p95_abs_trade_price_vs_mid"), errors="coerce")
        + pd.to_numeric(out.get("exit_tbbo_p95_abs_trade_price_vs_mid"), errors="coerce")
    )

    out["assumed_slippage_points"] = out["reason"].map(
        lambda reason: _assumed_slippage_points(str(reason), futures_specs)
    )
    contracts = pd.to_numeric(out["contracts"], errors="coerce").fillna(1.0)
    contract_value = float(futures_specs.get("contract_value", 20.0))
    out["assumed_slippage_dollars"] = out["assumed_slippage_points"] * contracts * contract_value
    for stem, points_col in [
        ("tbbo_median_spread", "tbbo_median_round_trip_spread_cost_points"),
        ("tbbo_p95_spread", "tbbo_p95_round_trip_spread_cost_points"),
        ("tbbo_p95_trade_vs_mid", "tbbo_p95_trade_vs_mid_round_trip_points"),
    ]:
        dollars_col = f"{stem}_cost_dollars"
        out[dollars_col] = out[points_col] * contracts * contract_value
        out[f"{stem}_cost_minus_assumed_points"] = out[points_col] - out["assumed_slippage_points"]
        out[f"pnl_with_{stem}_cost"] = out["pnl"] + out["assumed_slippage_dollars"] - out[dollars_col]

    exit_p95_trade_vs_mid = pd.to_numeric(out.get("exit_tbbo_p95_abs_trade_price_vs_mid"), errors="coerce")
    exit_half_spread = pd.to_numeric(out.get("exit_tbbo_median_half_spread_points"), errors="coerce")
    limit_opportunity = (exit_p95_trade_vs_mid - exit_half_spread).clip(lower=0.0)
    is_limit_exit = out["reason"].astype(str).isin(LIMIT_EXIT_REASONS)
    out["limit_exit_opportunity_stress_points"] = np.where(is_limit_exit, limit_opportunity, 0.0)
    out["limit_exit_opportunity_stress_dollars"] = (
        out["limit_exit_opportunity_stress_points"] * contracts * contract_value
    )
    out["pnl_with_tbbo_p95_trade_vs_mid_and_limit_opportunity_cost"] = (
        out["pnl_with_tbbo_p95_trade_vs_mid_cost"] - out["limit_exit_opportunity_stress_dollars"]
    )
    out = _add_volatility_conditioned_cost_estimates(
        out,
        futures_specs=futures_specs,
        volatility_cost_config=volatility_cost_config,
    )
    return out


def _add_volatility_conditioned_cost_estimates(
    audited: pd.DataFrame,
    *,
    futures_specs: Mapping[str, float],
    volatility_cost_config: VolatilityConditionedCostStressConfig | None,
) -> pd.DataFrame:
    out = audited.copy()
    contracts = pd.to_numeric(out["contracts"], errors="coerce").fillna(1.0)
    contract_value = float(futures_specs.get("contract_value", 20.0))
    assumed_event_slippage = pd.to_numeric(out["assumed_slippage_points"], errors="coerce").fillna(0.0) / 2.0

    event_cost_cols: list[str] = []
    reject_cols: list[str] = []
    multiplier_cols: list[str] = []
    for event in ("entry", "exit"):
        event_frame = pd.DataFrame(
            {
                "microstructure_cost_state": _series_or_na(out, f"{event}_tbbo_microstructure_cost_state"),
                "median_spread_points": _series_or_na(out, f"{event}_tbbo_median_spread_points"),
                "p95_spread_points": _series_or_na(out, f"{event}_tbbo_p95_spread_points"),
                "top_book_depth_exhausted_trade_pct": _series_or_na(
                    out,
                    f"{event}_tbbo_top_book_depth_exhausted_trade_pct",
                ),
                "realized_vol_ratio": _series_or_na(out, f"{event}_realized_vol_ratio"),
                "volatility_state": _series_or_na(out, f"{event}_volatility_state"),
                "volatility_compression_state": _series_or_na(out, f"{event}_volatility_compression_state"),
                "volatility_vol_of_vol_state": _series_or_na(out, f"{event}_volatility_vol_of_vol_state"),
                "volatility_jump_event": _series_or_na(out, f"{event}_volatility_jump_event"),
            },
            index=out.index,
        )
        stress = add_volatility_conditioned_cost_stress(event_frame, config=volatility_cost_config)
        for col in (
            "vol_conditioned_cost_state",
            "vol_conditioned_slippage_multiplier",
            "vol_conditioned_reject_fill",
            "vol_conditioned_allow_normal_assumptions",
            "vol_conditioned_high_realized_vol",
            "vol_conditioned_vol_shock",
            "vol_conditioned_wide_spread",
            "vol_conditioned_depth_exhausted",
            "vol_conditioned_reason",
        ):
            out[f"{event}_{col}"] = stress[col]

        event_base_cost = pd.concat(
            [
                pd.to_numeric(_series_or_na(out, f"{event}_tbbo_p95_abs_trade_price_vs_mid"), errors="coerce"),
                pd.to_numeric(_series_or_na(out, f"{event}_tbbo_p95_half_spread_points"), errors="coerce"),
                pd.to_numeric(_series_or_na(out, f"{event}_tbbo_median_half_spread_points"), errors="coerce"),
            ],
            axis=1,
        ).max(axis=1, skipna=True)
        multiplier = pd.to_numeric(stress["vol_conditioned_slippage_multiplier"], errors="coerce").fillna(1.0)
        normal_ok = stress["vol_conditioned_allow_normal_assumptions"].fillna(False).astype(bool)
        event_cost = (event_base_cost * multiplier).where(event_base_cost.notna(), assumed_event_slippage)
        event_cost = event_cost.where(~normal_ok, assumed_event_slippage)
        event_cost = np.maximum(pd.to_numeric(event_cost, errors="coerce").fillna(0.0), assumed_event_slippage)
        event_cost_col = f"{event}_vol_conditioned_cost_points"
        reject_col = f"{event}_vol_conditioned_reject_fill"
        multiplier_col = f"{event}_vol_conditioned_slippage_multiplier"
        out[event_cost_col] = event_cost
        event_cost_cols.append(event_cost_col)
        reject_cols.append(reject_col)
        multiplier_cols.append(multiplier_col)

    out["vol_conditioned_round_trip_cost_points"] = out[event_cost_cols].sum(axis=1, skipna=False)
    out["vol_conditioned_round_trip_cost_dollars"] = (
        out["vol_conditioned_round_trip_cost_points"] * contracts * contract_value
    )
    out["vol_conditioned_cost_minus_assumed_points"] = (
        out["vol_conditioned_round_trip_cost_points"] - out["assumed_slippage_points"]
    )
    out["vol_conditioned_reject_fill"] = out[reject_cols].fillna(False).any(axis=1)
    out["vol_conditioned_max_slippage_multiplier"] = out[multiplier_cols].max(axis=1, skipna=True)
    out["pnl_with_vol_conditioned_cost"] = (
        out["pnl"] + out["assumed_slippage_dollars"] - out["vol_conditioned_round_trip_cost_dollars"]
    )
    out["pnl_with_vol_conditioned_cost_if_accepted"] = out["pnl_with_vol_conditioned_cost"].where(
        ~out["vol_conditioned_reject_fill"],
        np.nan,
    )
    return out


def _assumed_slippage_points(reason: str, futures_specs: Mapping[str, float]) -> float:
    if reason in STOP_EXIT_REASONS:
        return float(futures_specs.get("slippage_stop_points", futures_specs["slippage_points"]))
    if reason in LIMIT_EXIT_REASONS:
        return float(futures_specs.get("slippage_limit_points", futures_specs["slippage_points"]))
    return float(futures_specs["slippage_points"])


def _series_or_na(frame: pd.DataFrame, col: str) -> pd.Series:
    if col in frame.columns:
        return frame[col]
    return pd.Series(np.nan, index=frame.index)


def _safe_ratio(numerator: float, denominator: float) -> float:
    if float(denominator) == 0.0:
        return np.nan
    return float(numerator) / float(denominator)
