from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd

from backtest.objectives import profit_factor_from_pnl


DEFAULT_ABS_PF_TOLERANCE = 0.05
DEFAULT_REL_PF_TOLERANCE = 0.05

CONTEXT_COLUMNS = [
    "setup_tag",
    "direction",
    "reason",
    "entry_hour",
    "entry_month",
    "entry_quarter",
    "entry_open_context",
    "entry_inside_ib",
    "entry_cusum_event",
    "entry_vwap_side",
    "entry_market_memory_state",
]

OUTRIGHT_NQ_SYMBOL_RE = re.compile(r"^NQ[FGHJKMNQUVXZ]\d{1,2}$")
BAR_TIME_COLUMN_ALIASES = ("time", "ts_event", "timestamp et", "timestamp", "datetime")
BAR_CLOSE_COLUMN_ALIASES = ("close",)
BAR_LOAD_COLUMNS = set(BAR_TIME_COLUMN_ALIASES) | {"open", "high", "low", "close", "volume", "symbol"}


@dataclass(frozen=True)
class BarExposureAuditPaths:
    summary_csv: Path
    by_trade_csv: Path
    by_slice_csv: Path
    report_md: Path
    execution_by_trade_csv: Path | None = None
    execution_by_slice_csv: Path | None = None


def export_bar_exposure_audit(
    *,
    bars: pd.DataFrame,
    execution_bars: pd.DataFrame | None = None,
    trades: pd.DataFrame,
    futures_specs: dict[str, Any],
    starting_capital: float,
    out_dir: Path | str,
    development_report_csv: Path | str | None = None,
    abs_pf_tolerance: float = DEFAULT_ABS_PF_TOLERANCE,
    rel_pf_tolerance: float = DEFAULT_REL_PF_TOLERANCE,
) -> BarExposureAuditPaths:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    bar_frame = reconstruct_bar_pnl_frame(
        bars=bars,
        trades=trades,
        futures_specs=futures_specs,
        starting_capital=starting_capital,
    )
    by_trade = build_trade_exposure_audit(
        bars=bars,
        trades=trades,
        futures_specs=futures_specs,
    )
    by_slice = build_slice_exposure_audit(by_trade)
    execution_bar_frame = None
    execution_by_trade = None
    execution_by_slice = None
    if execution_bars is not None:
        execution_bar_frame = reconstruct_bar_pnl_frame(
            bars=execution_bars,
            trades=trades,
            futures_specs=futures_specs,
            starting_capital=starting_capital,
        )
        execution_by_trade = build_trade_exposure_audit(
            bars=execution_bars,
            trades=trades,
            futures_specs=futures_specs,
        )
        execution_by_slice = build_slice_exposure_audit(execution_by_trade)
    summary = build_bar_exposure_summary(
        bar_frame=bar_frame,
        trades=trades,
        by_trade=by_trade,
        by_slice=by_slice,
        execution_bar_frame=execution_bar_frame,
        execution_by_trade=execution_by_trade,
        execution_by_slice=execution_by_slice,
        development_report_csv=development_report_csv,
        abs_pf_tolerance=abs_pf_tolerance,
        rel_pf_tolerance=rel_pf_tolerance,
    )

    summary_csv = out_path / "bar_exposure_audit_summary.csv"
    by_trade_csv = out_path / "bar_exposure_by_trade.csv"
    by_slice_csv = out_path / "bar_exposure_by_slice.csv"
    execution_by_trade_csv = out_path / "execution_bar_exposure_by_trade.csv"
    execution_by_slice_csv = out_path / "execution_bar_exposure_by_slice.csv"
    report_md = out_path / "bar_exposure_audit.md"

    summary.to_csv(summary_csv, index=False)
    by_trade.to_csv(by_trade_csv, index=False)
    by_slice.to_csv(by_slice_csv, index=False)
    if execution_by_trade is not None:
        execution_by_trade.to_csv(execution_by_trade_csv, index=False)
    else:
        execution_by_trade_csv = None
    if execution_by_slice is not None:
        execution_by_slice.to_csv(execution_by_slice_csv, index=False)
    else:
        execution_by_slice_csv = None
    _write_report(report_md, summary, by_slice, execution_by_slice)

    return BarExposureAuditPaths(
        summary_csv=summary_csv,
        by_trade_csv=by_trade_csv,
        by_slice_csv=by_slice_csv,
        report_md=report_md,
        execution_by_trade_csv=execution_by_trade_csv,
        execution_by_slice_csv=execution_by_slice_csv,
    )


def reconstruct_bar_pnl_frame(
    *,
    bars: pd.DataFrame,
    trades: pd.DataFrame,
    futures_specs: dict[str, Any],
    starting_capital: float,
) -> pd.DataFrame:
    bars_work = _prepare_bars(bars)
    if bars_work.empty:
        return pd.DataFrame(
            columns=[
                "time",
                "close",
                "close_diff",
                "position_contracts",
                "interval_position",
                "bar_pnl_gross",
                "transaction_cost",
                "bar_pnl",
                "equity",
                "exposed",
            ]
        )

    bar_times = bars_work["time"].to_numpy(dtype="datetime64[ns]")
    close = bars_work["close"].astype(float).to_numpy()
    trades_work = _prepare_trades(trades)
    position_contracts = np.zeros(len(bars_work), dtype=float)

    for trade in trades_work.itertuples(index=False):
        entry_idx, exit_idx = _trade_interval_indices(bar_times, trade.entry_time, trade.exit_time)
        if exit_idx <= entry_idx or entry_idx >= len(position_contracts):
            continue
        position_contracts[entry_idx:min(exit_idx, len(position_contracts))] += _trade_signed_contracts(trade)

    close_diff = np.diff(close, prepend=close[0])
    interval_position = np.roll(position_contracts, 1)
    interval_position[0] = 0.0
    gross_pnl = interval_position * close_diff * float(futures_specs["contract_value"])
    costs = _exit_costs(bar_times, trades_work, futures_specs)
    bar_pnl = gross_pnl - costs
    equity = float(starting_capital) + np.cumsum(bar_pnl)

    out = bars_work.loc[:, ["time", "close"]].copy()
    out["close_diff"] = close_diff
    out["position_contracts"] = position_contracts
    out["interval_position"] = interval_position
    out["bar_pnl_gross"] = gross_pnl
    out["transaction_cost"] = costs
    out["bar_pnl"] = bar_pnl
    out["equity"] = equity
    out["exposed"] = np.abs(position_contracts) > 0
    return out


def build_trade_exposure_audit(
    *,
    bars: pd.DataFrame,
    trades: pd.DataFrame,
    futures_specs: dict[str, Any],
) -> pd.DataFrame:
    bars_work = _prepare_bars(bars)
    trades_work = _prepare_trades(trades)
    if trades_work.empty:
        return pd.DataFrame(columns=_by_trade_columns())

    bar_times = bars_work["time"].to_numpy(dtype="datetime64[ns]") if not bars_work.empty else np.array([], dtype="datetime64[ns]")
    close = bars_work["close"].astype(float).to_numpy() if not bars_work.empty else np.array([], dtype=float)
    close_diff = np.diff(close, prepend=close[0]) if close.size else np.array([], dtype=float)
    rows: list[dict[str, Any]] = []
    cost_per_contract = _round_trip_cost_per_contract(futures_specs)

    for idx, trade in enumerate(trades_work.itertuples(index=False)):
        entry_idx, exit_idx = _trade_interval_indices(bar_times, trade.entry_time, trade.exit_time) if bar_times.size else (0, 0)
        signed_contracts = _trade_signed_contracts(trade)
        interval_start = max(entry_idx + 1, 0)
        interval_end = min(exit_idx, len(close_diff) - 1)
        if exit_idx <= entry_idx or interval_start > interval_end:
            path_gross_pnl = 0.0
            favorable_bars = 0
            adverse_bars = 0
            gross_positive_bar_pnl = 0.0
            gross_negative_bar_pnl = 0.0
            exposed_bars = 0
            zero_duration = True
        else:
            trade_bar_pnl = signed_contracts * close_diff[interval_start:interval_end + 1] * float(futures_specs["contract_value"])
            path_gross_pnl = float(np.nansum(trade_bar_pnl))
            favorable_bars = int(np.sum(trade_bar_pnl > 1e-9))
            adverse_bars = int(np.sum(trade_bar_pnl < -1e-9))
            gross_positive_bar_pnl = float(np.nansum(trade_bar_pnl[trade_bar_pnl > 1e-9]))
            gross_negative_bar_pnl = float(np.nansum(trade_bar_pnl[trade_bar_pnl < -1e-9]))
            exposed_bars = int(len(trade_bar_pnl))
            zero_duration = False

        contracts = float(getattr(trade, "contracts", 1.0))
        transaction_cost = cost_per_contract * contracts
        path_net_pnl = path_gross_pnl - transaction_cost
        realized_pnl = _finite_float(getattr(trade, "pnl", 0.0))

        row = {
            "trade_id": idx,
            "entry_time": trade.entry_time,
            "exit_time": trade.exit_time,
            "direction": str(getattr(trade, "direction", "")),
            "signal_type": str(getattr(trade, "signal_type", "")),
            "setup_tag": str(getattr(trade, "setup_tag", "")),
            "reason": str(getattr(trade, "reason", "")),
            "contracts": contracts,
            "realized_pnl": realized_pnl,
            "path_gross_pnl": path_gross_pnl,
            "transaction_cost": transaction_cost,
            "path_net_pnl": path_net_pnl,
            "execution_exit_delta": realized_pnl - path_net_pnl,
            "favorable_bars": favorable_bars,
            "adverse_bars": adverse_bars,
            "gross_positive_bar_pnl": gross_positive_bar_pnl,
            "gross_negative_bar_pnl": gross_negative_bar_pnl,
            "exposed_bars": exposed_bars,
            "zero_duration_or_unmatched": zero_duration,
            "hold_minutes": _hold_minutes(trade.entry_time, trade.exit_time),
            "entry_hour": pd.Timestamp(trade.entry_time).hour if pd.notna(trade.entry_time) else np.nan,
            "entry_month": pd.Timestamp(trade.entry_time).strftime("%Y-%m") if pd.notna(trade.entry_time) else "",
            "entry_quarter": _quarter_label(trade.entry_time),
        }
        for col in CONTEXT_COLUMNS:
            if col in row:
                continue
            row[col] = getattr(trade, col, "")
        rows.append(row)

    return pd.DataFrame(rows, columns=_by_trade_columns())


def build_slice_exposure_audit(by_trade: pd.DataFrame) -> pd.DataFrame:
    if by_trade.empty:
        return pd.DataFrame(columns=_by_slice_columns())

    rows: list[pd.DataFrame] = []
    total_negative = abs(float(by_trade["gross_negative_bar_pnl"].sum()))
    for col in CONTEXT_COLUMNS:
        if col not in by_trade.columns:
            continue
        work = by_trade.copy()
        work["slice_value"] = work[col].fillna("").astype(str).replace("", "missing")
        grouped = work.groupby("slice_value", dropna=False).agg(
            trades=("trade_id", "count"),
            realized_pnl=("realized_pnl", "sum"),
            path_net_pnl=("path_net_pnl", "sum"),
            execution_exit_delta=("execution_exit_delta", "sum"),
            favorable_bars=("favorable_bars", "sum"),
            adverse_bars=("adverse_bars", "sum"),
            gross_positive_bar_pnl=("gross_positive_bar_pnl", "sum"),
            gross_negative_bar_pnl=("gross_negative_bar_pnl", "sum"),
            exposed_bars=("exposed_bars", "sum"),
        ).reset_index()
        grouped.insert(0, "slice", col)
        rows.append(grouped)

    if not rows:
        return pd.DataFrame(columns=_by_slice_columns())
    out = pd.concat(rows, ignore_index=True)
    out["path_profit_factor"] = [
        profit_factor_from_pnl(pd.Series([pos, neg]))
        for pos, neg in zip(out["gross_positive_bar_pnl"], out["gross_negative_bar_pnl"], strict=False)
    ]
    out["share_of_negative_bar_pnl"] = np.where(
        total_negative > 0.0,
        out["gross_negative_bar_pnl"].abs() / total_negative,
        0.0,
    )
    return out.loc[:, _by_slice_columns()].sort_values(
        ["share_of_negative_bar_pnl", "trades"],
        ascending=[False, False],
    ).reset_index(drop=True)


def build_bar_exposure_summary(
    *,
    bar_frame: pd.DataFrame,
    trades: pd.DataFrame,
    by_trade: pd.DataFrame,
    by_slice: pd.DataFrame,
    execution_bar_frame: pd.DataFrame | None = None,
    execution_by_trade: pd.DataFrame | None = None,
    execution_by_slice: pd.DataFrame | None = None,
    development_report_csv: Path | str | None,
    abs_pf_tolerance: float = DEFAULT_ABS_PF_TOLERANCE,
    rel_pf_tolerance: float = DEFAULT_REL_PF_TOLERANCE,
) -> pd.DataFrame:
    bar_pnl = pd.Series(bar_frame.get("bar_pnl", pd.Series(dtype=float)), dtype=float)
    reconstructed_bar_pf = profit_factor_from_pnl(bar_pnl[np.abs(bar_pnl) > 1e-9])
    saved_bar_pf = _saved_development_value(development_report_csv, "bar_profit_factor")
    saved_trade_pf = _saved_development_value(development_report_csv, "trade_profit_factor")
    trade_pnl = pd.to_numeric(trades.get("pnl", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    trade_pf = profit_factor_from_pnl(trade_pnl)
    abs_diff, rel_diff, mismatch = _pf_mismatch(
        saved=saved_bar_pf,
        reconstructed=reconstructed_bar_pf,
        abs_tolerance=abs_pf_tolerance,
        rel_tolerance=rel_pf_tolerance,
    )
    top_negative = (
        by_slice.sort_values("share_of_negative_bar_pnl", ascending=False).head(1)
        if not by_slice.empty
        else pd.DataFrame()
    )
    top_negative_share = float(top_negative["share_of_negative_bar_pnl"].iloc[0]) if not top_negative.empty else 0.0
    top_negative_slice = str(top_negative["slice"].iloc[0]) if not top_negative.empty else ""
    top_negative_value = str(top_negative["slice_value"].iloc[0]) if not top_negative.empty else ""
    decision = _decision(
        mismatch=mismatch,
        reconstructed_bar_pf=reconstructed_bar_pf,
        top_negative_share=top_negative_share,
    )

    exposed = pd.Series(bar_frame.get("exposed", pd.Series(dtype=bool))).astype(bool)
    execution_stats = _execution_summary_stats(
        execution_bar_frame=execution_bar_frame,
        trades=trades,
        execution_by_trade=execution_by_trade,
        execution_by_slice=execution_by_slice,
    )
    row = {
        "decision": decision,
        "saved_bar_profit_factor": saved_bar_pf,
        "reconstructed_bar_profit_factor": reconstructed_bar_pf,
        "bar_pf_abs_diff": abs_diff,
        "bar_pf_rel_diff": rel_diff,
        "bar_pf_mismatch": bool(mismatch),
        "saved_trade_profit_factor": saved_trade_pf,
        "trade_profit_factor": trade_pf,
        "reconstructed_bar_total_pnl": float(bar_pnl.sum()),
        "trade_total_pnl": float(trade_pnl.sum()),
        "execution_exit_delta_total": float(trade_pnl.sum() - bar_pnl.sum()),
        "bar_exposure_pct": float(exposed.mean() * 100.0) if len(exposed) else 0.0,
        "bar_observations": int(len(bar_frame)),
        "bar_exposed_observations": int(exposed.sum()) if len(exposed) else 0,
        "trades": int(len(trades)),
        "zero_duration_or_unmatched_trades": int(
            by_trade.get("zero_duration_or_unmatched", pd.Series(dtype=bool)).astype(bool).sum()
        ) if not by_trade.empty else 0,
        "top_negative_slice": top_negative_slice,
        "top_negative_slice_value": top_negative_value,
        "top_negative_share_of_loss": top_negative_share,
        **execution_stats,
    }
    return pd.DataFrame([row])


def _execution_summary_stats(
    *,
    execution_bar_frame: pd.DataFrame | None,
    trades: pd.DataFrame,
    execution_by_trade: pd.DataFrame | None,
    execution_by_slice: pd.DataFrame | None,
) -> dict[str, Any]:
    if execution_bar_frame is None:
        return {
            "execution_bar_profit_factor": float("nan"),
            "execution_bar_total_pnl": float("nan"),
            "execution_vs_trade_delta_total": float("nan"),
            "execution_bar_exposure_pct": float("nan"),
            "execution_bar_observations": 0,
            "execution_bar_exposed_observations": 0,
            "execution_zero_duration_or_unmatched_trades": 0,
            "execution_top_negative_slice": "",
            "execution_top_negative_slice_value": "",
            "execution_top_negative_share_of_loss": 0.0,
        }

    execution_pnl = pd.Series(execution_bar_frame.get("bar_pnl", pd.Series(dtype=float)), dtype=float)
    execution_pf = profit_factor_from_pnl(execution_pnl[np.abs(execution_pnl) > 1e-9])
    trade_pnl = pd.to_numeric(trades.get("pnl", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    exposed = pd.Series(execution_bar_frame.get("exposed", pd.Series(dtype=bool))).astype(bool)
    zero_duration = (
        int(execution_by_trade.get("zero_duration_or_unmatched", pd.Series(dtype=bool)).astype(bool).sum())
        if execution_by_trade is not None and not execution_by_trade.empty
        else 0
    )
    top_negative = (
        execution_by_slice.sort_values("share_of_negative_bar_pnl", ascending=False).head(1)
        if execution_by_slice is not None and not execution_by_slice.empty
        else pd.DataFrame()
    )
    top_negative_share = float(top_negative["share_of_negative_bar_pnl"].iloc[0]) if not top_negative.empty else 0.0
    top_negative_slice = str(top_negative["slice"].iloc[0]) if not top_negative.empty else ""
    top_negative_value = str(top_negative["slice_value"].iloc[0]) if not top_negative.empty else ""

    return {
        "execution_bar_profit_factor": execution_pf,
        "execution_bar_total_pnl": float(execution_pnl.sum()),
        "execution_vs_trade_delta_total": float(trade_pnl.sum() - execution_pnl.sum()),
        "execution_bar_exposure_pct": float(exposed.mean() * 100.0) if len(exposed) else 0.0,
        "execution_bar_observations": int(len(execution_bar_frame)),
        "execution_bar_exposed_observations": int(exposed.sum()) if len(exposed) else 0,
        "execution_zero_duration_or_unmatched_trades": zero_duration,
        "execution_top_negative_slice": top_negative_slice,
        "execution_top_negative_slice_value": top_negative_value,
        "execution_top_negative_share_of_loss": top_negative_share,
    }


def load_bars_csv(
    path: Path | str,
    *,
    continuous_contract_method: str | None = None,
    bar_timeframe: str | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    raw = pd.read_csv(
        path,
        low_memory=False,
        usecols=lambda col: str(col).strip().lower() in BAR_LOAD_COLUMNS,
    )
    bars = _normalize_loaded_bars(raw, continuous_contract_method=continuous_contract_method)
    bars = _filter_bar_window(bars, start=start, end=end)
    if bar_timeframe:
        bars = resample_bars(bars, rule=bar_timeframe)
    return bars


def load_trades_csv(path: Path | str) -> pd.DataFrame:
    return pd.read_csv(path)


def resolve_run_dir(run_dir: Path | str | None = None) -> Path:
    if run_dir is not None:
        return Path(run_dir)
    latest_path = Path("results/latest.txt")
    if not latest_path.exists():
        raise FileNotFoundError("results/latest.txt is missing; pass --run-dir")
    label = latest_path.read_text(encoding="utf-8").strip()
    if not label:
        raise ValueError("results/latest.txt is empty; pass --run-dir")
    return Path("results/runs") / label


def _prepare_bars(bars: pd.DataFrame) -> pd.DataFrame:
    bars = _normalize_bar_columns(bars)
    required = {"time", "close"}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"bars are missing required columns: {sorted(missing)}")
    out = bars.loc[:, ["time", "close"]].copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    return out.dropna(subset=["time", "close"]).sort_values("time").drop_duplicates(subset="time", keep="first").reset_index(drop=True)


def _normalize_loaded_bars(
    bars: pd.DataFrame,
    *,
    continuous_contract_method: str | None = None,
) -> pd.DataFrame:
    out = bars.copy()
    lower_to_col = {str(col).strip().lower(): col for col in out.columns}

    if "ts_event" in lower_to_col:
        out["time"] = pd.to_datetime(out[lower_to_col["ts_event"]], utc=True, errors="coerce")
        out["time"] = out["time"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    else:
        time_col = next((lower_to_col[alias] for alias in BAR_TIME_COLUMN_ALIASES if alias in lower_to_col), None)
        if time_col is not None:
            out["time"] = pd.to_datetime(out[time_col], errors="coerce")

    for canonical in ("open", "high", "low", "close", "volume", "symbol"):
        source = lower_to_col.get(canonical)
        if source is not None and source != canonical and canonical not in out.columns:
            out = out.rename(columns={source: canonical})

    if "symbol" in out.columns and "volume" in out.columns and "time" in out.columns:
        out = _select_continuous_outright_contract(
            out,
            method=continuous_contract_method or "prior_session_volume",
        )

    keep = [col for col in ("time", "open", "high", "low", "close", "volume") if col in out.columns]
    return out.loc[:, keep].copy() if keep else out


def _normalize_bar_columns(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    if "time" not in out.columns:
        for alias in BAR_TIME_COLUMN_ALIASES:
            if alias in out.columns:
                out = out.rename(columns={alias: "time"})
                break
    if "close" not in out.columns:
        for alias in BAR_CLOSE_COLUMN_ALIASES:
            if alias in out.columns:
                out = out.rename(columns={alias: "close"})
                break
    return out


def _clock_ge(times: pd.Series, hour_min: str) -> pd.Series:
    dt = pd.to_datetime(times)
    hour, minute = [int(part) for part in hour_min.split(":", 1)]
    return (dt.dt.hour > hour) | ((dt.dt.hour == hour) & (dt.dt.minute >= minute))


def _futures_session_key(times: pd.Series) -> pd.Series:
    dt = pd.to_datetime(times)
    session = dt.dt.normalize()
    return session.mask(_clock_ge(dt, "18:00"), session + pd.Timedelta(days=1))


def _select_continuous_outright_contract(df: pd.DataFrame, method: str = "prior_session_volume") -> pd.DataFrame:
    work = df.copy()
    symbol = work["symbol"].astype(str)
    work = work.loc[symbol.str.match(OUTRIGHT_NQ_SYMBOL_RE)].copy()
    if work.empty:
        return work

    method = str(method or "prior_session_volume").lower()

    def timestamp_volume_selection(frame: pd.DataFrame) -> pd.DataFrame:
        return (
            frame.sort_values(["time", "volume"], ascending=[True, False])
            .drop_duplicates(subset="time", keep="first")
            .reset_index(drop=True)
        )

    if method in ("timestamp_volume", "minute_volume", "per_timestamp"):
        return timestamp_volume_selection(work)

    if method in ("daily_volume", "prior_daily_volume", "previous_daily_volume"):
        work["_contract_bucket"] = pd.to_datetime(work["time"]).dt.normalize()
    else:
        work["_contract_bucket"] = _futures_session_key(work["time"])

    by_contract = (
        work.groupby(["_contract_bucket", "symbol"], sort=True)["volume"]
        .sum()
        .reset_index()
        .sort_values(["_contract_bucket", "volume", "symbol"], ascending=[True, False, True])
    )

    use_prior_bucket = method in (
        "prior_session_volume",
        "previous_session_volume",
        "prior_daily_volume",
        "previous_daily_volume",
    )
    if use_prior_bucket:
        ranked_symbols = {
            bucket: group["symbol"].astype(str).tolist()
            for bucket, group in by_contract.groupby("_contract_bucket", sort=True)
        }
        available_symbols = {
            bucket: set(group["symbol"].astype(str))
            for bucket, group in work.groupby("_contract_bucket", sort=True)
        }
        first_timestamp_fallback = (
            work.sort_values(["_contract_bucket", "time", "volume", "symbol"], ascending=[True, True, False, True])
            .drop_duplicates(subset="_contract_bucket", keep="first")
            .set_index("_contract_bucket")["symbol"]
            .astype(str)
            .to_dict()
        )

        selected_rows: list[dict[str, object]] = []
        buckets = list(ranked_symbols)
        for idx, bucket in enumerate(buckets):
            selected_symbol = None
            if idx > 0:
                prior_bucket = buckets[idx - 1]
                current_available = available_symbols.get(bucket, set())
                for candidate in ranked_symbols.get(prior_bucket, []):
                    if candidate in current_available:
                        selected_symbol = candidate
                        break
            if selected_symbol is None:
                selected_symbol = first_timestamp_fallback.get(bucket)
            if selected_symbol is not None:
                selected_rows.append({"_contract_bucket": bucket, "_selected_symbol": selected_symbol})
        selected = pd.DataFrame(selected_rows)
    else:
        selected = by_contract.drop_duplicates(subset="_contract_bucket", keep="first")
        selected = selected.rename(columns={"symbol": "_selected_symbol"})[["_contract_bucket", "_selected_symbol"]]

    if selected.empty:
        return timestamp_volume_selection(work.drop(columns=["_contract_bucket"], errors="ignore"))

    work = work.merge(selected, on="_contract_bucket", how="left")
    work = work.loc[work["symbol"].eq(work["_selected_symbol"])].copy()
    return (
        work.drop(columns=["_contract_bucket", "_selected_symbol"], errors="ignore")
        .sort_values(["time", "volume"], ascending=[True, False])
        .drop_duplicates(subset="time", keep="first")
        .reset_index(drop=True)
    )


def _filter_bar_window(
    bars: pd.DataFrame,
    *,
    start: str | pd.Timestamp | None,
    end: str | pd.Timestamp | None,
) -> pd.DataFrame:
    if "time" not in bars.columns:
        return bars
    out = bars.copy()
    if start is not None:
        out = out.loc[pd.to_datetime(out["time"]).ge(pd.Timestamp(start))]
    if end is not None:
        end_ts = pd.Timestamp(end)
        if end_ts == end_ts.normalize():
            end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        out = out.loc[pd.to_datetime(out["time"]).le(end_ts)]
    return out.reset_index(drop=True)


def resample_bars(bars: pd.DataFrame, *, rule: str) -> pd.DataFrame:
    if "time" not in bars.columns or "close" not in bars.columns or bars.empty:
        return bars
    work = bars.copy()
    work["time"] = pd.to_datetime(work["time"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=["time", "close"]).sort_values("time").set_index("time")
    agg: dict[str, str] = {"close": "last"}
    if "open" in work.columns:
        agg["open"] = "first"
    if "high" in work.columns:
        agg["high"] = "max"
    if "low" in work.columns:
        agg["low"] = "min"
    if "volume" in work.columns:
        agg["volume"] = "sum"
    return work.resample(rule).agg(agg).dropna(subset=["close"]).reset_index()


def _prepare_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    required = {"entry_time", "exit_time", "direction"}
    missing = required - set(trades.columns)
    if missing:
        raise ValueError(f"trades are missing required columns: {sorted(missing)}")
    out = trades.copy()
    out["entry_time"] = pd.to_datetime(out["entry_time"], errors="coerce")
    out["exit_time"] = pd.to_datetime(out["exit_time"], errors="coerce")
    out["contracts"] = pd.to_numeric(out.get("contracts", 1.0), errors="coerce").fillna(1.0)
    if "pnl" in out.columns:
        out["pnl"] = pd.to_numeric(out["pnl"], errors="coerce").fillna(0.0)
    return out.dropna(subset=["entry_time", "exit_time"]).reset_index(drop=True)


def _trade_interval_indices(bar_times: np.ndarray, entry_time: pd.Timestamp, exit_time: pd.Timestamp) -> tuple[int, int]:
    entry_idx = int(bar_times.searchsorted(np.datetime64(entry_time), side="left"))
    exit_idx = int(bar_times.searchsorted(np.datetime64(exit_time), side="left"))
    return entry_idx, exit_idx


def _trade_signed_contracts(trade: Any) -> float:
    direction = 1.0 if str(getattr(trade, "direction", "")).lower() == "long" else -1.0
    return direction * float(getattr(trade, "contracts", 1.0))


def _round_trip_cost_per_contract(futures_specs: dict[str, Any]) -> float:
    return float(futures_specs.get("commission_per_round_trip", 0.0)) + (
        float(futures_specs.get("slippage_points", 0.0)) * float(futures_specs["contract_value"])
    )


def _exit_costs(bar_times: np.ndarray, trades: pd.DataFrame, futures_specs: dict[str, Any]) -> np.ndarray:
    costs = np.zeros(len(bar_times), dtype=float)
    cost_per_contract = _round_trip_cost_per_contract(futures_specs)
    for trade in trades.itertuples(index=False):
        exit_idx = int(bar_times.searchsorted(np.datetime64(trade.exit_time), side="left"))
        if 0 <= exit_idx < len(costs):
            costs[exit_idx] += cost_per_contract * float(getattr(trade, "contracts", 1.0))
    return costs


def _saved_development_value(path: Path | str | None, check_name: str) -> float:
    if path is None:
        return float("nan")
    report_path = Path(path)
    if not report_path.exists():
        return float("nan")
    report = pd.read_csv(report_path)
    if "check" not in report.columns or "value" not in report.columns:
        return float("nan")
    row = report.loc[report["check"].eq(check_name)].head(1)
    if row.empty:
        return float("nan")
    return _finite_float(row.iloc[0]["value"])


def _pf_mismatch(
    *,
    saved: float,
    reconstructed: float,
    abs_tolerance: float,
    rel_tolerance: float,
) -> tuple[float, float, bool]:
    if not np.isfinite(saved) or not np.isfinite(reconstructed):
        return float("nan"), float("nan"), False
    abs_diff = abs(reconstructed - saved)
    rel_diff = abs_diff / abs(saved) if abs(saved) > 1e-12 else float("inf")
    return abs_diff, rel_diff, bool(abs_diff > abs_tolerance or rel_diff > rel_tolerance)


def _decision(*, mismatch: bool, reconstructed_bar_pf: float, top_negative_share: float) -> str:
    if mismatch:
        return "metric_code_audit_required"
    if np.isfinite(reconstructed_bar_pf) and reconstructed_bar_pf < 1.0 and top_negative_share >= 0.60:
        return "hypothesis_only_dominant_slice"
    if np.isfinite(reconstructed_bar_pf) and reconstructed_bar_pf < 1.0:
        return "branch_rejected_broad_bar_exposure_failure"
    return "inconclusive_no_bar_exposure_rejection"


def _write_report(
    path: Path,
    summary: pd.DataFrame,
    by_slice: pd.DataFrame,
    execution_by_slice: pd.DataFrame | None = None,
) -> None:
    row = summary.iloc[0] if not summary.empty else pd.Series(dtype=object)
    lines = [
        "# Bar Exposure Audit",
        "",
        f"Verdict: `{row.get('decision', 'unknown')}`",
        "",
        "## Summary",
        "",
        f"- Saved bar PF: `{_format_float(row.get('saved_bar_profit_factor'))}`",
        f"- Reconstructed bar PF: `{_format_float(row.get('reconstructed_bar_profit_factor'))}`",
        f"- Execution-bar PF: `{_format_float(row.get('execution_bar_profit_factor'))}`",
        f"- Trade PF: `{_format_float(row.get('trade_profit_factor'))}`",
        f"- Bar PF mismatch: `{bool(row.get('bar_pf_mismatch', False))}`",
        f"- Top negative slice: `{row.get('top_negative_slice', '')}={row.get('top_negative_slice_value', '')}` "
        f"({float(row.get('top_negative_share_of_loss', 0.0)):.1%} of negative bar PnL)",
        f"- Execution top negative slice: `{row.get('execution_top_negative_slice', '')}="
        f"{row.get('execution_top_negative_slice_value', '')}` "
        f"({float(row.get('execution_top_negative_share_of_loss', 0.0)):.1%} of negative execution-bar PnL)",
        "",
        "## Decision Rules",
        "",
        "- Metric/code audit required if reconstructed bar PF differs from saved bar PF by more than 0.05 absolute or 5% relative.",
        "- Branch rejected if bar PF matches and losses are broad across slices.",
        "- Dominant-slice findings are hypotheses only; do not create another candidate from this same sample.",
        "",
    ]
    if not by_slice.empty:
        cols = [
            "slice",
            "slice_value",
            "trades",
            "path_net_pnl",
            "gross_negative_bar_pnl",
            "share_of_negative_bar_pnl",
            "path_profit_factor",
        ]
        top = by_slice.loc[:, cols].head(12)
        lines.extend(["## Top Negative Bar-PnL Slices", "", "```text", top.to_string(index=False), "```", ""])
    if execution_by_slice is not None and not execution_by_slice.empty:
        cols = [
            "slice",
            "slice_value",
            "trades",
            "path_net_pnl",
            "gross_negative_bar_pnl",
            "share_of_negative_bar_pnl",
            "path_profit_factor",
        ]
        top = execution_by_slice.loc[:, cols].head(12)
        lines.extend(["## Top Negative Execution-Bar Slices", "", "```text", top.to_string(index=False), "```", ""])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _format_float(value: Any) -> str:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return "nan"
    return f"{result:.6g}" if np.isfinite(result) else str(result)


def _finite_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result if np.isfinite(result) else float("nan")


def _hold_minutes(entry_time: pd.Timestamp, exit_time: pd.Timestamp) -> float:
    if pd.isna(entry_time) or pd.isna(exit_time):
        return float("nan")
    return float((pd.Timestamp(exit_time) - pd.Timestamp(entry_time)).total_seconds() / 60.0)


def _quarter_label(timestamp: Any) -> str:
    if pd.isna(timestamp):
        return ""
    ts = pd.Timestamp(timestamp)
    return f"{ts.year}Q{ts.quarter}"


def _by_trade_columns() -> list[str]:
    extras = [col for col in CONTEXT_COLUMNS if col not in {"setup_tag", "direction", "reason"}]
    return [
        "trade_id",
        "entry_time",
        "exit_time",
        "direction",
        "signal_type",
        "setup_tag",
        "reason",
        "contracts",
        "realized_pnl",
        "path_gross_pnl",
        "transaction_cost",
        "path_net_pnl",
        "execution_exit_delta",
        "favorable_bars",
        "adverse_bars",
        "gross_positive_bar_pnl",
        "gross_negative_bar_pnl",
        "exposed_bars",
        "zero_duration_or_unmatched",
        "hold_minutes",
        *extras,
    ]


def _by_slice_columns() -> list[str]:
    return [
        "slice",
        "slice_value",
        "trades",
        "realized_pnl",
        "path_net_pnl",
        "execution_exit_delta",
        "favorable_bars",
        "adverse_bars",
        "gross_positive_bar_pnl",
        "gross_negative_bar_pnl",
        "exposed_bars",
        "path_profit_factor",
        "share_of_negative_bar_pnl",
    ]
