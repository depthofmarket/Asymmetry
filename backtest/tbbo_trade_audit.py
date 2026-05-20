from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd


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
    nearest_tolerance: str | pd.Timedelta = "1min",
) -> TbboTradeAudit:
    specs = dict(DEFAULT_FUTURES_SPECS)
    if futures_specs is not None:
        specs.update({k: float(v) for k, v in futures_specs.items() if k in specs})

    prepared_trades = _prepare_trades(trades)
    prepared_stats = _prepare_minute_stats(minute_stats)
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

    audited = _add_cost_estimates(audited, futures_specs=specs)
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
        "assumed_slippage_points",
        "tbbo_median_round_trip_spread_cost_points",
        "tbbo_p95_round_trip_spread_cost_points",
        "tbbo_p95_trade_vs_mid_round_trip_points",
        "tbbo_median_spread_cost_minus_assumed_points",
        "tbbo_p95_spread_cost_minus_assumed_points",
        "tbbo_p95_trade_vs_mid_cost_minus_assumed_points",
    ]
    for col in numeric_cols:
        if col in matched_df.columns and not matched_df.empty:
            values = pd.to_numeric(matched_df[col], errors="coerce")
            summary[f"matched_sum_{col}"] = float(values.sum(skipna=True))
            summary[f"matched_median_{col}"] = float(values.median(skipna=True))
        else:
            summary[f"matched_sum_{col}"] = np.nan
            summary[f"matched_median_{col}"] = np.nan
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
                "median_assumed_slippage_points",
                "median_tbbo_median_round_trip_spread_cost_points",
                "median_tbbo_p95_round_trip_spread_cost_points",
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
        median_assumed_slippage_points=("assumed_slippage_points", "median"),
        median_tbbo_median_round_trip_spread_cost_points=(
            "tbbo_median_round_trip_spread_cost_points",
            "median",
        ),
        median_tbbo_p95_round_trip_spread_cost_points=(
            "tbbo_p95_round_trip_spread_cost_points",
            "median",
        ),
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
        "raw_b_side_count",
        "raw_a_side_count",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["symbol", "minute", "trade_date"]).sort_values(["symbol", "minute"])


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
            "raw_b_side_count",
            "raw_a_side_count",
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


def _add_cost_estimates(audited: pd.DataFrame, *, futures_specs: Mapping[str, float]) -> pd.DataFrame:
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
    return out


def _assumed_slippage_points(reason: str, futures_specs: Mapping[str, float]) -> float:
    if reason in STOP_EXIT_REASONS:
        return float(futures_specs.get("slippage_stop_points", futures_specs["slippage_points"]))
    if reason in LIMIT_EXIT_REASONS:
        return float(futures_specs.get("slippage_limit_points", futures_specs["slippage_points"]))
    return float(futures_specs["slippage_points"])


def _safe_ratio(numerator: float, denominator: float) -> float:
    if float(denominator) == 0.0:
        return np.nan
    return float(numerator) / float(denominator)
