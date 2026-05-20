from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PropFirmReportPaths:
    summary_csv: Path
    simulations_csv: Path
    funded_simulations_csv: Path
    risk_geometry_surface_csv: Path
    sizing_surface_csv: Path
    daily_rules_surface_csv: Path
    trade_geometry_csv: Path
    strategy_metrics_csv: Path
    random_walk_csv: Path
    random_walk_samples_csv: Path
    attempt_curve_csv: Path
    charts_dir: Path
    dashboard_png: Path
    overview_png: Path
    strategy_equity_png: Path
    monte_carlo_png: Path
    random_walk_png: Path
    payout_analysis_png: Path
    risk_geometry_png: Path
    sizing_png: Path
    daily_rules_png: Path
    trade_geometry_png: Path
    funded_payout_png: Path
    report_md: Path


DEFAULT_PROFILE: dict[str, Any] = {
    "name": "generic_50k_eval",
    "account_size": 50_000.0,
    "profit_target": 3_000.0,
    "max_drawdown": 2_500.0,
    "daily_loss_limit": 1_200.0,
    "min_trading_days": 5,
    "max_trading_days": 30,
    "drawdown_mode": "static",  # static | eod_trailing
    "drawdown_check": "intraday",  # intraday | eod
    "trailing_drawdown_cap_at_initial": True,
    "stop_after_target_until_min_days": True,
    "pnl_multiplier": 1.0,
    "eval_cost": 0.0,
    "consistency_profit_limit_pct": 0.0,
    "initial_max_trading_days": 0,
    "extension_trading_days": 0,
    "extension_threshold": 0.0,
    "profit_split_pct": 100.0,
    "funded_buffer_target": 0.0,
    "minimum_payout": 0.0,
    "funded_horizon_days": 60,
    "enable_surfaces": True,
    "surface_n_sims": 1000,
    "sizing_multipliers": [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
    "daily_loss_stops": [0.0, 250.0, 400.0, 500.0, 750.0],
    "daily_profit_locks": [0.0, 250.0, 500.0, 750.0, 1000.0],
    "risk_geometry_reward_risk": [0.33, 0.5, 1.0, 2.0, 3.0, 4.0],
    "risk_geometry_drawdown_risk_fracs": [0.10, 0.20, 0.30, 0.40, 0.50],
    "risk_geometry_trades_per_day": 1,
    "random_walk_n_sims": 10_000,
    "attempt_curve_max_attempts": 10,
}


CHART_BG = "#080d14"
CHART_PANEL = "#111827"
CHART_GRID = "#2b3a4f"
CHART_TEXT = "#e5eefb"
CHART_MUTED = "#94a3b8"
CHART_SPINE = "#2b3a4f"
CHART_TABLE_HEADER = "#172033"
CHART_TABLE_ROW = "#111827"
CHART_GREEN = "#34d399"
CHART_RED = "#fb7185"
CHART_BLUE = "#60a5fa"
CHART_CYAN = "#22d3ee"
CHART_YELLOW = "#fbbf24"
CHART_ORANGE = "#fb923c"
CHART_PURPLE = "#a78bfa"


def _amount_from_profile(profile: dict[str, Any], amount_key: str, pct_key: str, account_size: float) -> float:
    if amount_key in profile and profile[amount_key] is not None:
        return float(profile[amount_key])
    if pct_key in profile and profile[pct_key] is not None:
        return account_size * float(profile[pct_key]) / 100.0
    return 0.0


def _ratio_from_pct(value: Any) -> float:
    if value is None:
        return 0.0
    ratio = float(value)
    if ratio > 1.0:
        ratio /= 100.0
    return max(0.0, ratio)


def _normalize_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(DEFAULT_PROFILE)
    if profile:
        normalized.update(profile)

    account_size = float(normalized.get("account_size", DEFAULT_PROFILE["account_size"]))
    normalized["account_size"] = account_size
    normalized["profit_target"] = _amount_from_profile(
        normalized,
        "profit_target",
        "profit_target_pct",
        account_size,
    )
    normalized["max_drawdown"] = _amount_from_profile(
        normalized,
        "max_drawdown",
        "max_drawdown_pct",
        account_size,
    )
    normalized["daily_loss_limit"] = _amount_from_profile(
        normalized,
        "daily_loss_limit",
        "daily_loss_limit_pct",
        account_size,
    )
    normalized["min_trading_days"] = max(1, int(normalized.get("min_trading_days", 1) or 1))
    normalized["max_trading_days"] = max(
        normalized["min_trading_days"],
        int(normalized.get("max_trading_days", normalized["min_trading_days"]) or normalized["min_trading_days"]),
    )
    raw_dd_mode = str(normalized.get("drawdown_mode", "static")).lower()
    # Canonicalize drawdown mode variants
    dd_mode_map = {
        "trailing": "eod_trailing",
        "trailing_eod": "eod_trailing",
        "eod_trailing_lock_at_initial": "eod_trailing",
        "eod_lock": "eod_trailing",
    }
    normalized["drawdown_mode"] = dd_mode_map.get(raw_dd_mode, raw_dd_mode)
    normalized["drawdown_check"] = str(normalized.get("drawdown_check", "intraday")).lower()
    normalized["trailing_drawdown_cap_at_initial"] = bool(
        normalized.get("trailing_drawdown_cap_at_initial", True)
    )
    normalized["stop_after_target_until_min_days"] = bool(
        normalized.get("stop_after_target_until_min_days", True)
    )
    normalized["pnl_multiplier"] = float(normalized.get("pnl_multiplier", 1.0) or 1.0)
    normalized["eval_cost"] = float(
        normalized.get("eval_cost", normalized.get("cost_per_eval", 0.0)) or 0.0
    )
    consistency_value = normalized.get(
        "consistency_profit_limit_pct",
        normalized.get("consistency_profit_limit", 0.0),
    )
    normalized["consistency_profit_limit"] = _ratio_from_pct(consistency_value)
    normalized["consistency_profit_limit_pct"] = normalized["consistency_profit_limit"] * 100.0
    initial_max_days = int(normalized.get("initial_max_trading_days", 0) or 0)
    extension_days = int(normalized.get("extension_trading_days", 0) or 0)
    if initial_max_days > 0:
        normalized["initial_max_trading_days"] = max(normalized["min_trading_days"], initial_max_days)
        normalized["extension_trading_days"] = max(0, extension_days)
        normalized["max_trading_days"] = max(
            normalized["max_trading_days"],
            normalized["initial_max_trading_days"] + normalized["extension_trading_days"],
        )
    else:
        normalized["initial_max_trading_days"] = 0
        normalized["extension_trading_days"] = 0
    extension_threshold = _amount_from_profile(
        normalized,
        "extension_threshold",
        "extension_threshold_pct",
        account_size,
    )
    if extension_threshold <= 0 and normalized.get("extension_threshold_pct_of_target") is not None:
        extension_threshold = float(normalized["profit_target"]) * float(
            normalized["extension_threshold_pct_of_target"]
        ) / 100.0
    normalized["extension_threshold"] = float(extension_threshold)
    normalized["profit_split_pct"] = float(normalized.get("profit_split_pct", 100.0) or 100.0)
    normalized["profit_split"] = _ratio_from_pct(normalized["profit_split_pct"])
    normalized["funded_buffer_target"] = _amount_from_profile(
        normalized,
        "funded_buffer_target",
        "funded_buffer_target_pct",
        account_size,
    )
    if normalized["funded_buffer_target"] <= 0:
        normalized["funded_buffer_target"] = _amount_from_profile(
            normalized,
            "funded_buffer",
            "funded_buffer_pct",
            account_size,
        )
    normalized["minimum_payout"] = _amount_from_profile(
        normalized,
        "minimum_payout",
        "minimum_payout_pct",
        account_size,
    )
    normalized["funded_horizon_days"] = max(1, int(normalized.get("funded_horizon_days", 60) or 60))
    normalized["enable_surfaces"] = bool(normalized.get("enable_surfaces", True))
    normalized["surface_n_sims"] = max(1, int(normalized.get("surface_n_sims", 1000) or 1000))
    normalized["sizing_multipliers"] = [
        float(v) for v in normalized.get("sizing_multipliers", DEFAULT_PROFILE["sizing_multipliers"])
    ]
    normalized["daily_loss_stops"] = [
        float(v) for v in normalized.get("daily_loss_stops", DEFAULT_PROFILE["daily_loss_stops"])
    ]
    normalized["daily_profit_locks"] = [
        float(v) for v in normalized.get("daily_profit_locks", DEFAULT_PROFILE["daily_profit_locks"])
    ]
    normalized["risk_geometry_reward_risk"] = [
        float(v) for v in normalized.get("risk_geometry_reward_risk", DEFAULT_PROFILE["risk_geometry_reward_risk"])
    ]
    normalized["risk_geometry_drawdown_risk_fracs"] = [
        float(v)
        for v in normalized.get(
            "risk_geometry_drawdown_risk_fracs",
            DEFAULT_PROFILE["risk_geometry_drawdown_risk_fracs"],
        )
    ]
    normalized["risk_geometry_trades_per_day"] = max(
        1,
        int(normalized.get("risk_geometry_trades_per_day", 1) or 1),
    )
    normalized["random_walk_n_sims"] = max(
        1,
        int(normalized.get("random_walk_n_sims", DEFAULT_PROFILE["random_walk_n_sims"]) or 1),
    )
    normalized["attempt_curve_max_attempts"] = max(
        1,
        int(normalized.get("attempt_curve_max_attempts", DEFAULT_PROFILE["attempt_curve_max_attempts"]) or 1),
    )
    normalized["name"] = str(normalized.get("name", "prop_eval"))
    return normalized


def _daily_pnl_from_trades(trades: pd.DataFrame) -> pd.Series:
    return _daily_paths_from_trades(trades)["net_pnl"]


def _empty_daily_path_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "net_pnl",
            "min_intraday_pnl",
            "max_intraday_pnl",
            "trade_count",
        ]
    ).astype(
        {
            "net_pnl": float,
            "min_intraday_pnl": float,
            "max_intraday_pnl": float,
            "trade_count": int,
        }
    )


def _trade_path_work_frame(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "pnl" not in trades.columns:
        return pd.DataFrame()

    time_col = "exit_time" if "exit_time" in trades.columns else "entry_time"
    if time_col not in trades.columns:
        dates = np.arange(len(trades))
        times = np.arange(len(trades))
    else:
        times = pd.to_datetime(trades[time_col], errors="coerce")
        dates = times.dt.date.to_numpy()
        times = times.to_numpy()

    work = pd.DataFrame({
        "date": dates,
        "time": times,
        "sequence": np.arange(len(trades)),
        "pnl": pd.to_numeric(trades["pnl"], errors="coerce").to_numpy(),
        "mae_dollars": (
            pd.to_numeric(trades["mae_dollars"], errors="coerce").to_numpy()
            if "mae_dollars" in trades.columns
            else 0.0
        ),
        "mfe_dollars": (
            pd.to_numeric(trades["mfe_dollars"], errors="coerce").to_numpy()
            if "mfe_dollars" in trades.columns
            else 0.0
        ),
    }).dropna(subset=["date", "pnl"])
    if work.empty:
        return pd.DataFrame()

    return work.sort_values(["date", "time", "sequence"], kind="mergesort").reset_index(drop=True)


def _daily_paths_from_work(work: pd.DataFrame) -> pd.DataFrame:
    if work.empty:
        return _empty_daily_path_frame()

    work = work.copy()
    work["mae_dollars"] = pd.to_numeric(work["mae_dollars"], errors="coerce").fillna(0.0).clip(lower=0.0)
    work["mfe_dollars"] = pd.to_numeric(work["mfe_dollars"], errors="coerce").fillna(0.0).clip(lower=0.0)
    work["cum_after_trade"] = work.groupby("date", sort=False)["pnl"].cumsum()
    work["cum_before_trade"] = work["cum_after_trade"] - work["pnl"]
    work["intraday_low_pnl"] = np.minimum(
        work["cum_after_trade"],
        work["cum_before_trade"] - work["mae_dollars"],
    )
    work["intraday_high_pnl"] = np.maximum(
        work["cum_after_trade"],
        work["cum_before_trade"] + work["mfe_dollars"],
    )
    daily_paths = work.groupby("date", sort=True).agg(
        net_pnl=("pnl", "sum"),
        min_intraday_pnl=("intraday_low_pnl", "min"),
        max_intraday_pnl=("intraday_high_pnl", "max"),
        trade_count=("pnl", "count"),
    )
    return daily_paths.astype(
        {
            "net_pnl": float,
            "min_intraday_pnl": float,
            "max_intraday_pnl": float,
            "trade_count": int,
        }
    )


def _calendarize_daily_paths(daily_paths: pd.DataFrame) -> pd.DataFrame:
    if daily_paths.empty:
        return _empty_daily_path_frame()

    paths = daily_paths.copy()
    dates = pd.to_datetime(paths.index, errors="coerce").normalize()
    keep = ~pd.isna(dates)
    if not keep.any():
        return paths

    paths = paths.loc[keep].copy()
    paths.index = dates[keep]
    full_index = pd.date_range(paths.index.min(), paths.index.max(), freq="D")
    paths = paths.reindex(full_index)
    for col in ("net_pnl", "min_intraday_pnl", "max_intraday_pnl"):
        paths[col] = pd.to_numeric(paths.get(col), errors="coerce").fillna(0.0)
    paths["trade_count"] = pd.to_numeric(paths.get("trade_count"), errors="coerce").fillna(0).astype(int)
    paths.index.name = "date"
    return paths.loc[:, ["net_pnl", "min_intraday_pnl", "max_intraday_pnl", "trade_count"]]


def _daily_paths_from_trades(
    trades: pd.DataFrame,
    *,
    daily_loss_stop: float = 0.0,
    daily_profit_lock: float = 0.0,
    calendarize: bool = True,
) -> pd.DataFrame:
    work = _trade_path_work_frame(trades)
    if work.empty:
        return _empty_daily_path_frame()
    if daily_loss_stop <= 0 and daily_profit_lock <= 0:
        daily_paths = _daily_paths_from_work(work)
        return _calendarize_daily_paths(daily_paths) if calendarize else daily_paths

    rows: list[dict[str, Any]] = []
    for date, group in work.groupby("date", sort=True):
        equity_pnl = 0.0
        min_pnl = 0.0
        max_pnl = 0.0
        trades_taken = 0
        for _, trade in group.iterrows():
            before = equity_pnl
            pnl = float(trade["pnl"])
            mae = max(0.0, float(trade.get("mae_dollars", 0.0) or 0.0))
            mfe = max(0.0, float(trade.get("mfe_dollars", 0.0) or 0.0))
            low = min(before + pnl, before - mae)
            high = max(before + pnl, before + mfe)
            trades_taken += 1

            loss_hit = daily_loss_stop > 0 and low <= -daily_loss_stop
            profit_hit = daily_profit_lock > 0 and high >= daily_profit_lock
            if loss_hit and profit_hit:
                # Without true intratrade sequencing, use the more conservative
                # assumption for daily-rule surfaces.
                equity_pnl = -daily_loss_stop
                min_pnl = min(min_pnl, -daily_loss_stop)
                max_pnl = max(max_pnl, high)
                break
            if loss_hit:
                equity_pnl = -daily_loss_stop
                min_pnl = min(min_pnl, -daily_loss_stop)
                max_pnl = max(max_pnl, high)
                break
            if profit_hit:
                equity_pnl = daily_profit_lock
                min_pnl = min(min_pnl, low)
                max_pnl = max(max_pnl, daily_profit_lock)
                break

            equity_pnl = before + pnl
            min_pnl = min(min_pnl, low, equity_pnl)
            max_pnl = max(max_pnl, high, equity_pnl)

        rows.append({
            "date": date,
            "net_pnl": equity_pnl,
            "min_intraday_pnl": min_pnl,
            "max_intraday_pnl": max_pnl,
            "trade_count": trades_taken,
        })

    if not rows:
        return _empty_daily_path_frame()
    daily_paths = pd.DataFrame(rows).set_index("date")
    daily_paths = daily_paths.astype(
        {
            "net_pnl": float,
            "min_intraday_pnl": float,
            "max_intraday_pnl": float,
            "trade_count": int,
        }
    )
    return _calendarize_daily_paths(daily_paths) if calendarize else daily_paths


def _coerce_daily_paths(daily_pnls: Any) -> pd.DataFrame:
    if isinstance(daily_pnls, pd.DataFrame):
        if daily_pnls.empty:
            return _empty_daily_path_frame()
        paths = daily_pnls.copy()
    elif isinstance(daily_pnls, pd.Series):
        paths = pd.DataFrame({"net_pnl": pd.to_numeric(daily_pnls, errors="coerce")})
    else:
        paths = pd.DataFrame({"net_pnl": pd.to_numeric(np.asarray(daily_pnls, dtype=float), errors="coerce")})

    paths["net_pnl"] = pd.to_numeric(paths.get("net_pnl"), errors="coerce").fillna(0.0)
    if "min_intraday_pnl" not in paths.columns:
        paths["min_intraday_pnl"] = np.minimum(paths["net_pnl"], 0.0)
    else:
        paths["min_intraday_pnl"] = pd.to_numeric(paths["min_intraday_pnl"], errors="coerce").fillna(
            np.minimum(paths["net_pnl"], 0.0)
        )
    if "max_intraday_pnl" not in paths.columns:
        paths["max_intraday_pnl"] = np.maximum(paths["net_pnl"], 0.0)
    else:
        paths["max_intraday_pnl"] = pd.to_numeric(paths["max_intraday_pnl"], errors="coerce").fillna(
            np.maximum(paths["net_pnl"], 0.0)
        )
    if "trade_count" not in paths.columns:
        paths["trade_count"] = 1

    return paths.loc[:, ["net_pnl", "min_intraday_pnl", "max_intraday_pnl", "trade_count"]].reset_index(drop=True)


def _scale_daily_paths(daily_paths: pd.DataFrame, multiplier: float) -> pd.DataFrame:
    if daily_paths.empty or multiplier == 1.0:
        return daily_paths.copy()
    scaled = daily_paths.copy()
    for col in ("net_pnl", "min_intraday_pnl", "max_intraday_pnl"):
        if col in scaled.columns:
            scaled[col] = scaled[col].astype(float) * multiplier
    return scaled


REASON_LABELS = {
    0: "max_days_elapsed",
    1: "profit_target",
    2: "daily_loss_limit",
    3: "max_drawdown",
    4: "extension_threshold_not_met",
    5: "no_daily_pnls",
    6: "horizon_elapsed",
}


def _sample_daily_arrays(
    daily_paths: pd.DataFrame,
    days: int,
    n_sims: int,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n_sims = max(1, int(n_sims))
    days = max(1, int(days))
    if daily_paths.empty:
        zeros = np.zeros((n_sims, days), dtype=float)
        counts = np.zeros((n_sims, days), dtype=int)
        return zeros, zeros.copy(), zeros.copy(), counts

    paths = _coerce_daily_paths(daily_paths)
    trade_counts_base = paths["trade_count"].to_numpy(dtype=int)
    active_starts = np.flatnonzero(trade_counts_base > 0)
    if active_starts.size == 0:
        active_starts = np.arange(len(paths))

    eligible_starts = active_starts[active_starts <= max(0, len(paths) - days)]
    if eligible_starts.size == 0:
        eligible_starts = active_starts

    starts = rng.choice(eligible_starts, size=n_sims, replace=True)
    idx = starts[:, None] + np.arange(days)[None, :]
    valid = idx < len(paths)
    safe_idx = np.minimum(idx, max(len(paths) - 1, 0))
    net = paths["net_pnl"].to_numpy(dtype=float)[safe_idx]
    low = paths["min_intraday_pnl"].to_numpy(dtype=float)[safe_idx]
    high = paths["max_intraday_pnl"].to_numpy(dtype=float)[safe_idx]
    trade_count = trade_counts_base[safe_idx]
    net = np.where(valid, net, 0.0)
    low = np.where(valid, low, 0.0)
    high = np.where(valid, high, 0.0)
    trade_count = np.where(valid, trade_count, 0)
    return net, low, high, trade_count


def _simulate_eval_arrays(
    net: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    profile: dict[str, Any],
    trade_count: np.ndarray | None = None,
) -> pd.DataFrame:
    rules = _normalize_profile(profile)
    n_sims, max_days = net.shape
    if trade_count is None:
        trade_count = np.ones_like(net, dtype=int)
    else:
        trade_count = np.asarray(trade_count, dtype=int)
    account_size = float(rules["account_size"])
    profit_target = float(rules["profit_target"])
    max_drawdown = float(rules["max_drawdown"])
    daily_loss_limit = float(rules["daily_loss_limit"])
    min_days = int(rules["min_trading_days"])
    stop_after_target = bool(rules["stop_after_target_until_min_days"])
    consistency_limit = float(rules["consistency_profit_limit"])
    drawdown_mode = str(rules["drawdown_mode"]).lower()
    drawdown_check = str(rules["drawdown_check"]).lower()
    cap_trailing_floor = bool(rules["trailing_drawdown_cap_at_initial"])
    initial_max_days = int(rules["initial_max_trading_days"])
    extension_threshold = float(rules["extension_threshold"])

    equity = np.full(n_sims, account_size, dtype=float)
    peak_equity = np.full(n_sims, account_size, dtype=float)
    eod_peak_equity = np.full(n_sims, account_size, dtype=float)
    static_floor = account_size - max_drawdown if max_drawdown > 0 else -np.inf
    drawdown_floor = np.full(n_sims, static_floor, dtype=float)
    min_equity = np.full(n_sims, account_size, dtype=float)
    max_drawdown_seen = np.zeros(n_sims, dtype=float)
    max_drawdown_pct_seen = np.zeros(n_sims, dtype=float)
    best_profit_day = np.zeros(n_sims, dtype=float)
    target_hit_day = np.full(n_sims, np.nan, dtype=float)
    consistency_blocked = np.zeros(n_sims, dtype=bool)
    status = np.zeros(n_sims, dtype=np.int8)  # 0 timeout/active, 1 pass, 2 fail
    reason = np.zeros(n_sims, dtype=np.int8)
    days_taken = np.zeros(n_sims, dtype=int)
    trading_days_taken = np.zeros(n_sims, dtype=int)

    if net.size == 0:
        reason[:] = 5
        return _eval_records_from_arrays(
            rules,
            status=np.zeros(n_sims, dtype=np.int8),
            reason=reason,
            days_taken=days_taken,
            trading_days_taken=trading_days_taken,
            target_hit_day=target_hit_day,
            equity=equity,
            max_drawdown_seen=max_drawdown_seen,
            max_drawdown_pct_seen=max_drawdown_pct_seen,
            drawdown_floor=drawdown_floor,
            min_equity=min_equity,
            peak_equity=peak_equity,
            best_profit_day=best_profit_day,
            consistency_blocked=consistency_blocked,
            extension_threshold=extension_threshold,
        )

    for day_idx in range(max_days):
        active = status == 0
        if not active.any():
            break

        hold_after_target = (
            np.isfinite(target_hit_day)
            & stop_after_target
            & ~consistency_blocked
            & ((equity - account_size) >= profit_target)
            & active
        )
        day_pnl = np.where(hold_after_target, 0.0, net[:, day_idx])
        min_intraday_pnl = np.where(hold_after_target, 0.0, low[:, day_idx])
        max_intraday_pnl = np.where(hold_after_target, 0.0, high[:, day_idx])
        active_trade_day = trade_count[:, day_idx] > 0

        day_start_equity = equity.copy()
        day_low_equity = day_start_equity + min_intraday_pnl
        day_high_equity = day_start_equity + max_intraday_pnl
        equity[active] += day_pnl[active]
        days_taken[active] = day_idx + 1
        trading_days_taken[active & active_trade_day] += 1
        best_profit_day[active] = np.maximum(best_profit_day[active], day_pnl[active])
        eod_peak_equity[active] = np.maximum(eod_peak_equity[active], equity[active])
        min_equity[active] = np.minimum.reduce([min_equity[active], day_low_equity[active], equity[active]])
        peak_equity[active] = np.maximum.reduce([peak_equity[active], day_high_equity[active], equity[active]])
        current_drawdown = peak_equity - np.minimum(day_low_equity, equity)
        max_drawdown_seen[active] = np.maximum(max_drawdown_seen[active], current_drawdown[active])
        valid_peak = peak_equity > 0
        max_drawdown_pct_seen[active & valid_peak] = np.maximum(
            max_drawdown_pct_seen[active & valid_peak],
            current_drawdown[active & valid_peak] / peak_equity[active & valid_peak] * 100.0,
        )

        if drawdown_mode in (
            "eod_trailing",
            "trailing",
            "trailing_eod",
            "eod_trailing_lock_at_initial",
            "eod_lock",
        ) and max_drawdown > 0:
            drawdown_floor = np.maximum(static_floor, eod_peak_equity - max_drawdown)
            if cap_trailing_floor:
                drawdown_floor = np.minimum(drawdown_floor, account_size)
        else:
            drawdown_floor = np.full(n_sims, static_floor, dtype=float)

        fail_daily = active & (daily_loss_limit > 0) & (min_intraday_pnl <= -daily_loss_limit)
        drawdown_test_equity = equity if drawdown_check == "eod" else np.minimum(day_low_equity, equity)
        fail_dd = active & ~fail_daily & (max_drawdown > 0) & (drawdown_test_equity <= drawdown_floor)
        status[fail_daily | fail_dd] = 2
        reason[fail_daily] = 2
        reason[fail_dd] = 3

        still_active = status == 0
        net_pnl = equity - account_size
        consistency_ok = np.ones(n_sims, dtype=bool)
        if consistency_limit > 0:
            positive = net_pnl > 0
            consistency_ok[positive] = best_profit_day[positive] <= net_pnl[positive] * consistency_limit

        target_reached = still_active & (profit_target > 0) & (net_pnl >= profit_target)
        newly_hit = target_reached & ~np.isfinite(target_hit_day)
        target_hit_day[newly_hit] = day_idx + 1
        pass_now = target_reached & (trading_days_taken >= min_days) & consistency_ok
        status[pass_now] = 1
        reason[pass_now] = 1
        consistency_blocked[target_reached & ~consistency_ok & ~pass_now] = True
        consistency_blocked[still_active & ~target_reached] = False

        still_active = status == 0
        if initial_max_days > 0 and extension_threshold > 0 and day_idx + 1 == initial_max_days:
            timeout_ext = still_active & (net_pnl < extension_threshold)
            reason[timeout_ext] = 4
            status[timeout_ext] = 2

    final_active = status == 0
    reason[final_active & (reason == 0)] = 0

    return _eval_records_from_arrays(
        rules,
        status=status,
        reason=reason,
        days_taken=days_taken,
        trading_days_taken=trading_days_taken,
        target_hit_day=target_hit_day,
        equity=equity,
        max_drawdown_seen=max_drawdown_seen,
        max_drawdown_pct_seen=max_drawdown_pct_seen,
        drawdown_floor=drawdown_floor,
        min_equity=min_equity,
        peak_equity=peak_equity,
        best_profit_day=best_profit_day,
        consistency_blocked=consistency_blocked,
        extension_threshold=extension_threshold,
    )


def _eval_records_from_arrays(
    rules: dict[str, Any],
    *,
    status: np.ndarray,
    reason: np.ndarray,
    days_taken: np.ndarray,
    target_hit_day: np.ndarray,
    equity: np.ndarray,
    max_drawdown_seen: np.ndarray,
    max_drawdown_pct_seen: np.ndarray,
    drawdown_floor: np.ndarray,
    min_equity: np.ndarray,
    peak_equity: np.ndarray,
    best_profit_day: np.ndarray,
    consistency_blocked: np.ndarray,
    extension_threshold: float,
    trading_days_taken: np.ndarray | None = None,
) -> pd.DataFrame:
    account_size = float(rules["account_size"])
    final_net_pnl = equity - account_size
    best_day_pct = np.zeros_like(final_net_pnl, dtype=float)
    np.divide(
        best_profit_day * 100.0,
        final_net_pnl,
        out=best_day_pct,
        where=final_net_pnl > 0,
    )
    consistency_limit = float(rules["consistency_profit_limit"])
    extra_profit_needed = np.zeros_like(final_net_pnl)
    if consistency_limit > 0:
        extra_profit_needed = np.where(
            final_net_pnl > 0,
            np.maximum(0.0, best_profit_day / consistency_limit - final_net_pnl),
            0.0,
        )

    status_labels = np.where(status == 1, "pass", np.where(status == 2, "fail", "timeout"))
    reason_labels = [REASON_LABELS.get(int(code), "unknown") for code in reason]
    if trading_days_taken is None:
        trading_days_taken = days_taken
    return pd.DataFrame({
        "status": status_labels,
        "reason": reason_labels,
        "days": days_taken.astype(int),
        "trading_days": np.asarray(trading_days_taken, dtype=int),
        "target_hit_day": target_hit_day,
        "final_equity": equity.astype(float),
        "net_pnl": final_net_pnl.astype(float),
        "max_drawdown_dollars": max_drawdown_seen.astype(float),
        "max_drawdown_pct": max_drawdown_pct_seen.astype(float),
        "drawdown_floor": drawdown_floor.astype(float),
        "min_equity": min_equity.astype(float),
        "peak_equity": peak_equity.astype(float),
        "best_profit_day": best_profit_day.astype(float),
        "best_day_pct_of_total_profit": best_day_pct.astype(float),
        "extra_profit_needed_for_consistency": extra_profit_needed.astype(float),
        "consistency_blocked": consistency_blocked.astype(bool),
        "extension_threshold": float(extension_threshold),
    })


def _simulate_funded_arrays(
    net: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    profile: dict[str, Any],
) -> pd.DataFrame:
    rules = _normalize_profile(profile)
    n_sims, horizon_days = net.shape
    account_size = float(rules["account_size"])
    max_drawdown = float(rules["max_drawdown"])
    daily_loss_limit = float(rules["daily_loss_limit"])
    drawdown_mode = str(rules["drawdown_mode"]).lower()
    drawdown_check = str(rules["drawdown_check"]).lower()
    cap_trailing_floor = bool(rules["trailing_drawdown_cap_at_initial"])
    funded_buffer = float(rules["funded_buffer_target"])
    minimum_payout = float(rules["minimum_payout"])
    profit_split = float(rules["profit_split"])

    equity = np.full(n_sims, account_size, dtype=float)
    peak_equity = np.full(n_sims, account_size, dtype=float)
    eod_peak_equity = np.full(n_sims, account_size, dtype=float)
    static_floor = account_size - max_drawdown if max_drawdown > 0 else -np.inf
    drawdown_floor = np.full(n_sims, static_floor, dtype=float)
    payout_floor = account_size + funded_buffer
    gross_payout = np.zeros(n_sims, dtype=float)
    net_payout = np.zeros(n_sims, dtype=float)
    payout_count = np.zeros(n_sims, dtype=int)
    first_payout_day = np.full(n_sims, np.nan, dtype=float)
    max_drawdown_seen = np.zeros(n_sims, dtype=float)
    min_equity = np.full(n_sims, account_size, dtype=float)
    status = np.zeros(n_sims, dtype=np.int8)  # 0 survived/active, 2 fail
    reason = np.full(n_sims, 6, dtype=np.int8)
    days_taken = np.zeros(n_sims, dtype=int)

    for day_idx in range(horizon_days):
        active = status == 0
        if not active.any():
            break

        day_pnl = net[:, day_idx]
        min_intraday_pnl = low[:, day_idx]
        max_intraday_pnl = high[:, day_idx]
        day_start_equity = equity.copy()
        day_low_equity = day_start_equity + min_intraday_pnl
        day_high_equity = day_start_equity + max_intraday_pnl
        equity[active] += day_pnl[active]
        days_taken[active] = day_idx + 1
        eod_peak_equity[active] = np.maximum(eod_peak_equity[active], equity[active])
        peak_equity[active] = np.maximum.reduce([peak_equity[active], day_high_equity[active], equity[active]])
        min_equity[active] = np.minimum.reduce([min_equity[active], day_low_equity[active], equity[active]])
        max_drawdown_seen[active] = np.maximum(
            max_drawdown_seen[active],
            (peak_equity - np.minimum(day_low_equity, equity))[active],
        )

        if drawdown_mode in (
            "eod_trailing",
            "trailing",
            "trailing_eod",
            "eod_trailing_lock_at_initial",
            "eod_lock",
        ) and max_drawdown > 0:
            drawdown_floor = np.maximum(static_floor, eod_peak_equity - max_drawdown)
            if cap_trailing_floor:
                drawdown_floor = np.minimum(drawdown_floor, account_size)
        else:
            drawdown_floor = np.full(n_sims, static_floor, dtype=float)

        fail_daily = active & (daily_loss_limit > 0) & (min_intraday_pnl <= -daily_loss_limit)
        drawdown_test_equity = equity if drawdown_check == "eod" else np.minimum(day_low_equity, equity)
        fail_dd = active & ~fail_daily & (max_drawdown > 0) & (drawdown_test_equity <= drawdown_floor)
        status[fail_daily | fail_dd] = 2
        reason[fail_daily] = 2
        reason[fail_dd] = 3

        active = status == 0
        withdrawable = equity - payout_floor
        can_pay = active & (withdrawable >= minimum_payout) & (withdrawable > 0)
        gross_payout[can_pay] += withdrawable[can_pay]
        net_payout[can_pay] += withdrawable[can_pay] * profit_split
        payout_count[can_pay] += 1
        first_time = can_pay & ~np.isfinite(first_payout_day)
        first_payout_day[first_time] = day_idx + 1
        equity[can_pay] -= withdrawable[can_pay]

    status_labels = np.where(status == 2, "fail", "survived")
    reason_labels = [REASON_LABELS.get(int(code), "unknown") for code in reason]
    return pd.DataFrame({
        "status": status_labels,
        "reason": reason_labels,
        "days": days_taken.astype(int),
        "final_equity": equity.astype(float),
        "net_pnl_after_payouts": (equity - account_size + gross_payout).astype(float),
        "gross_payout": gross_payout.astype(float),
        "net_payout": net_payout.astype(float),
        "payout_count": payout_count.astype(int),
        "first_payout_day": first_payout_day,
        "max_drawdown_dollars": max_drawdown_seen.astype(float),
        "drawdown_floor": drawdown_floor.astype(float),
        "min_equity": min_equity.astype(float),
        "peak_equity": peak_equity.astype(float),
    })


def _attach_eval_metadata(records: pd.DataFrame, rules: dict[str, Any]) -> pd.DataFrame:
    records = records.copy()
    if "sim_id" not in records.columns:
        records.insert(0, "sim_id", np.arange(len(records), dtype=int))
    if "profile" not in records.columns:
        records.insert(0, "profile", rules["name"])
    for key, value in {
        "account_size": float(rules["account_size"]),
        "profit_target": float(rules["profit_target"]),
        "max_drawdown": float(rules["max_drawdown"]),
        "daily_loss_limit": float(rules["daily_loss_limit"]),
        "min_trading_days": int(rules["min_trading_days"]),
        "max_trading_days": int(rules["max_trading_days"]),
        "initial_max_trading_days": int(rules["initial_max_trading_days"]),
        "extension_trading_days": int(rules["extension_trading_days"]),
        "consistency_profit_limit_pct": float(rules["consistency_profit_limit_pct"]),
        "drawdown_mode": rules["drawdown_mode"],
        "drawdown_check": rules["drawdown_check"],
        "pnl_multiplier": float(rules["pnl_multiplier"]),
        "eval_cost": float(rules["eval_cost"]),
        "profit_split_pct": float(rules["profit_split_pct"]),
        "funded_buffer_target": float(rules["funded_buffer_target"]),
        "minimum_payout": float(rules["minimum_payout"]),
        "funded_horizon_days": int(rules["funded_horizon_days"]),
    }.items():
        records[key] = value
    return records


def _attach_funded_metadata(records: pd.DataFrame, rules: dict[str, Any]) -> pd.DataFrame:
    records = records.copy()
    if "sim_id" not in records.columns:
        records.insert(0, "sim_id", np.arange(len(records), dtype=int))
    if "profile" not in records.columns:
        records.insert(0, "profile", rules["name"])
    for key, value in {
        "account_size": float(rules["account_size"]),
        "max_drawdown": float(rules["max_drawdown"]),
        "drawdown_mode": rules["drawdown_mode"],
        "drawdown_check": rules["drawdown_check"],
        "pnl_multiplier": float(rules["pnl_multiplier"]),
        "profit_split_pct": float(rules["profit_split_pct"]),
        "funded_buffer_target": float(rules["funded_buffer_target"]),
        "minimum_payout": float(rules["minimum_payout"]),
        "funded_horizon_days": int(rules["funded_horizon_days"]),
    }.items():
        records[key] = value
    return records


def evaluate_prop_firm_path(daily_pnls: Any, profile: dict[str, Any]) -> dict[str, Any]:
    rules = _normalize_profile(profile)
    account_size = float(rules["account_size"])
    profit_target = float(rules["profit_target"])
    max_drawdown = float(rules["max_drawdown"])
    daily_loss_limit = float(rules["daily_loss_limit"])
    min_days = int(rules["min_trading_days"])
    max_days = int(rules["max_trading_days"])
    drawdown_mode = str(rules["drawdown_mode"]).lower()
    drawdown_check = str(rules["drawdown_check"]).lower()
    cap_trailing_floor = bool(rules["trailing_drawdown_cap_at_initial"])
    stop_after_target = bool(rules["stop_after_target_until_min_days"])
    consistency_limit = float(rules["consistency_profit_limit"])
    initial_max_days = int(rules["initial_max_trading_days"])
    extension_threshold = float(rules["extension_threshold"])

    equity = account_size
    peak_equity = account_size
    eod_peak_equity = account_size
    static_floor = account_size - max_drawdown if max_drawdown > 0 else -np.inf
    drawdown_floor = static_floor
    max_drawdown_seen = 0.0
    max_drawdown_pct_seen = 0.0
    best_profit_day = 0.0
    target_hit_day: int | None = None
    consistency_blocked = False
    status = "timeout"
    reason = "max_days_elapsed"
    days_taken = 0
    trading_days_taken = 0

    daily_paths = _coerce_daily_paths(daily_pnls)
    if daily_paths.empty:
        return {
            "status": "timeout",
            "reason": "no_daily_pnls",
            "days": 0,
            "trading_days": 0,
            "target_hit_day": np.nan,
            "final_equity": equity,
            "net_pnl": 0.0,
            "max_drawdown_dollars": 0.0,
            "max_drawdown_pct": 0.0,
            "drawdown_floor": drawdown_floor,
            "min_equity": equity,
            "peak_equity": peak_equity,
            "best_profit_day": 0.0,
            "best_day_pct_of_total_profit": 0.0,
            "extra_profit_needed_for_consistency": 0.0,
            "consistency_blocked": False,
            "extension_threshold": extension_threshold,
        }

    min_equity = equity
    for day_idx in range(max_days):
        hold_after_target = (
            target_hit_day is not None
            and stop_after_target
            and not consistency_blocked
            and (equity - account_size) >= profit_target
        )
        if hold_after_target:
            day_pnl = 0.0
            min_intraday_pnl = 0.0
            max_intraday_pnl = 0.0
            trade_count = 0
        elif day_idx < len(daily_paths):
            day = daily_paths.iloc[day_idx]
            day_pnl = float(day["net_pnl"])
            min_intraday_pnl = float(day["min_intraday_pnl"])
            max_intraday_pnl = float(day["max_intraday_pnl"])
            trade_count = int(day.get("trade_count", 0) or 0)
        else:
            day_pnl = 0.0
            min_intraday_pnl = 0.0
            max_intraday_pnl = 0.0
            trade_count = 0

        days_taken = day_idx + 1
        if trade_count > 0:
            trading_days_taken += 1
        day_start_equity = equity
        day_low_equity = day_start_equity + min_intraday_pnl
        day_high_equity = day_start_equity + max_intraday_pnl
        equity += day_pnl
        best_profit_day = max(best_profit_day, day_pnl)
        eod_peak_equity = max(eod_peak_equity, equity)
        min_equity = min(min_equity, day_low_equity, equity)
        peak_equity = max(peak_equity, day_high_equity, equity)
        current_drawdown = peak_equity - min(day_low_equity, equity)
        max_drawdown_seen = max(max_drawdown_seen, current_drawdown)
        if peak_equity > 0:
            max_drawdown_pct_seen = max(max_drawdown_pct_seen, current_drawdown / peak_equity * 100.0)

        if drawdown_mode in (
            "eod_trailing",
            "trailing",
            "trailing_eod",
            "eod_trailing_lock_at_initial",
            "eod_lock",
        ) and max_drawdown > 0:
            drawdown_floor = max(static_floor, eod_peak_equity - max_drawdown)
            if cap_trailing_floor:
                drawdown_floor = min(drawdown_floor, account_size)
        else:
            drawdown_floor = static_floor

        if daily_loss_limit > 0 and min_intraday_pnl <= -daily_loss_limit:
            status = "fail"
            reason = "daily_loss_limit"
            break

        drawdown_test_equity = equity if drawdown_check == "eod" else min(day_low_equity, equity)
        if max_drawdown > 0 and drawdown_test_equity <= drawdown_floor:
            status = "fail"
            reason = "max_drawdown"
            break

        net_pnl = equity - account_size
        consistency_ok = True
        if consistency_limit > 0 and net_pnl > 0:
            consistency_ok = best_profit_day <= net_pnl * consistency_limit

        if profit_target > 0 and (equity - account_size) >= profit_target:
            if target_hit_day is None:
                target_hit_day = days_taken
            if trading_days_taken >= min_days and consistency_ok:
                status = "pass"
                reason = "profit_target"
                break
            if not consistency_ok:
                consistency_blocked = True
                reason = "consistency_pending"
        else:
            consistency_blocked = False

        if (
            initial_max_days > 0
            and extension_threshold > 0
            and days_taken == initial_max_days
            and status != "pass"
            and net_pnl < extension_threshold
        ):
            status = "timeout"
            reason = "extension_threshold_not_met"
            break

    final_net_pnl = equity - account_size
    best_day_pct = best_profit_day / final_net_pnl * 100.0 if final_net_pnl > 0 else 0.0
    extra_profit_needed = 0.0
    if consistency_limit > 0 and final_net_pnl > 0:
        extra_profit_needed = max(0.0, best_profit_day / consistency_limit - final_net_pnl)

    return {
        "status": status,
        "reason": reason,
        "days": days_taken,
        "trading_days": trading_days_taken,
        "target_hit_day": float(target_hit_day) if target_hit_day is not None else np.nan,
        "final_equity": float(equity),
        "net_pnl": float(equity - account_size),
        "max_drawdown_dollars": float(max_drawdown_seen),
        "max_drawdown_pct": float(max_drawdown_pct_seen),
        "drawdown_floor": float(drawdown_floor),
        "min_equity": float(min_equity),
        "peak_equity": float(peak_equity),
        "best_profit_day": float(best_profit_day),
        "best_day_pct_of_total_profit": float(best_day_pct),
        "extra_profit_needed_for_consistency": float(extra_profit_needed),
        "consistency_blocked": bool(consistency_blocked or reason == "consistency_pending"),
        "extension_threshold": extension_threshold,
    }


def _simulate_profile(
    daily_paths: pd.DataFrame,
    profile: dict[str, Any],
    *,
    n_sims: int,
    seed: int,
) -> pd.DataFrame:
    rules = _normalize_profile(profile)
    rng = np.random.default_rng(seed)
    max_days = int(rules["max_trading_days"])
    net, low, high, trade_count = _sample_daily_arrays(daily_paths, max_days, n_sims, rng)
    return _attach_eval_metadata(_simulate_eval_arrays(net, low, high, rules, trade_count), rules)


def _evaluate_funded_path(daily_pnls: Any, profile: dict[str, Any]) -> dict[str, Any]:
    rules = _normalize_profile(profile)
    account_size = float(rules["account_size"])
    max_drawdown = float(rules["max_drawdown"])
    daily_loss_limit = float(rules["daily_loss_limit"])
    drawdown_mode = str(rules["drawdown_mode"]).lower()
    drawdown_check = str(rules["drawdown_check"]).lower()
    cap_trailing_floor = bool(rules["trailing_drawdown_cap_at_initial"])
    funded_buffer = float(rules["funded_buffer_target"])
    minimum_payout = float(rules["minimum_payout"])
    profit_split = float(rules["profit_split"])
    horizon_days = int(rules["funded_horizon_days"])

    equity = account_size
    peak_equity = account_size
    eod_peak_equity = account_size
    static_floor = account_size - max_drawdown if max_drawdown > 0 else -np.inf
    drawdown_floor = static_floor
    payout_floor = account_size + funded_buffer
    gross_payout = 0.0
    net_payout = 0.0
    payout_count = 0
    first_payout_day: int | None = None
    max_drawdown_seen = 0.0
    min_equity = equity
    status = "survived"
    reason = "horizon_elapsed"
    daily_paths = _coerce_daily_paths(daily_pnls)

    for day_idx in range(horizon_days):
        if day_idx < len(daily_paths):
            day = daily_paths.iloc[day_idx]
            day_pnl = float(day["net_pnl"])
            min_intraday_pnl = float(day["min_intraday_pnl"])
            max_intraday_pnl = float(day["max_intraday_pnl"])
        else:
            day_pnl = 0.0
            min_intraday_pnl = 0.0
            max_intraday_pnl = 0.0

        day_start_equity = equity
        day_low_equity = day_start_equity + min_intraday_pnl
        day_high_equity = day_start_equity + max_intraday_pnl
        equity += day_pnl
        eod_peak_equity = max(eod_peak_equity, equity)
        peak_equity = max(peak_equity, day_high_equity, equity)
        min_equity = min(min_equity, day_low_equity, equity)
        max_drawdown_seen = max(max_drawdown_seen, peak_equity - min(day_low_equity, equity))

        if drawdown_mode in (
            "eod_trailing",
            "trailing",
            "trailing_eod",
            "eod_trailing_lock_at_initial",
            "eod_lock",
        ) and max_drawdown > 0:
            drawdown_floor = max(static_floor, eod_peak_equity - max_drawdown)
            if cap_trailing_floor:
                drawdown_floor = min(drawdown_floor, account_size)
        else:
            drawdown_floor = static_floor

        if daily_loss_limit > 0 and min_intraday_pnl <= -daily_loss_limit:
            status = "fail"
            reason = "daily_loss_limit"
            break

        drawdown_test_equity = equity if drawdown_check == "eod" else min(day_low_equity, equity)
        if max_drawdown > 0 and drawdown_test_equity <= drawdown_floor:
            status = "fail"
            reason = "max_drawdown"
            break

        withdrawable = equity - payout_floor
        if withdrawable >= minimum_payout and withdrawable > 0:
            gross_payout += withdrawable
            net_payout += withdrawable * profit_split
            payout_count += 1
            if first_payout_day is None:
                first_payout_day = day_idx + 1
            equity -= withdrawable

    return {
        "status": status,
        "reason": reason,
        "days": day_idx + 1 if horizon_days > 0 else 0,
        "final_equity": float(equity),
        "net_pnl_after_payouts": float(equity - account_size + gross_payout),
        "gross_payout": float(gross_payout),
        "net_payout": float(net_payout),
        "payout_count": payout_count,
        "first_payout_day": float(first_payout_day) if first_payout_day is not None else np.nan,
        "max_drawdown_dollars": float(max_drawdown_seen),
        "drawdown_floor": float(drawdown_floor),
        "min_equity": float(min_equity),
        "peak_equity": float(peak_equity),
    }


def _simulate_funded_profile(
    daily_paths: pd.DataFrame,
    profile: dict[str, Any],
    *,
    n_sims: int,
    seed: int,
) -> pd.DataFrame:
    rules = _normalize_profile(profile)
    rng = np.random.default_rng(seed)
    horizon_days = int(rules["funded_horizon_days"])
    net, low, high, _ = _sample_daily_arrays(daily_paths, horizon_days, n_sims, rng)
    return _attach_funded_metadata(_simulate_funded_arrays(net, low, high, rules), rules)


def _summarize_simulations(
    simulations: pd.DataFrame,
    daily_paths_by_profile: dict[str, pd.DataFrame],
    funded_simulations: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if simulations.empty:
        return pd.DataFrame(rows)

    for profile, group in simulations.groupby("profile", sort=False):
        daily_paths = daily_paths_by_profile.get(profile, _empty_daily_path_frame())
        net_daily = daily_paths["net_pnl"] if "net_pnl" in daily_paths.columns else pd.Series(dtype=float)
        intraday_lows = (
            daily_paths["min_intraday_pnl"] if "min_intraday_pnl" in daily_paths.columns else pd.Series(dtype=float)
        )
        trade_counts = (
            pd.to_numeric(daily_paths["trade_count"], errors="coerce").fillna(0)
            if "trade_count" in daily_paths.columns
            else pd.Series(1, index=daily_paths.index, dtype=int)
        )
        active_mask = trade_counts > 0
        calendar_days = int(len(net_daily))
        active_days = int(active_mask.sum())
        active_net_daily = net_daily.loc[active_mask] if active_days else pd.Series(dtype=float)
        active_intraday_lows = intraday_lows.loc[active_mask] if active_days else pd.Series(dtype=float)
        avg_daily = float(active_net_daily.mean()) if active_days else 0.0
        median_daily = float(active_net_daily.median()) if active_days else 0.0
        worst_daily = float(active_net_daily.min()) if active_days else 0.0
        best_daily = float(active_net_daily.max()) if active_days else 0.0
        daily_std = float(active_net_daily.std(ddof=1)) if active_days > 1 else 0.0
        worst_intraday = float(active_intraday_lows.min()) if active_days else 0.0
        avg_calendar_daily = float(net_daily.mean()) if calendar_days else 0.0
        median_calendar_daily = float(net_daily.median()) if calendar_days else 0.0
        active_day_pct = float(active_days / calendar_days * 100.0) if calendar_days else 0.0
        n = len(group)
        pass_mask = group["status"].eq("pass")
        fail_mask = group["status"].eq("fail")
        timeout_mask = group["status"].eq("timeout")
        passes = group.loc[pass_mask]
        pass_probability = float(pass_mask.mean()) if n else 0.0
        eval_cost = float(group["eval_cost"].iloc[0]) if "eval_cost" in group.columns else 0.0
        expected_attempts_to_pass = 1.0 / pass_probability if pass_probability > 0 else np.inf
        expected_eval_cost_to_pass = eval_cost / pass_probability if pass_probability > 0 else np.inf

        funded = (
            funded_simulations.loc[funded_simulations["profile"].eq(profile)]
            if funded_simulations is not None and not funded_simulations.empty
            else pd.DataFrame()
        )
        funded_survival_probability = float(funded["status"].eq("survived").mean()) if not funded.empty else np.nan
        first_payout_probability = (
            float(funded["first_payout_day"].notna().mean()) if not funded.empty else np.nan
        )
        avg_gross_payout = float(funded["gross_payout"].mean()) if not funded.empty else np.nan
        median_gross_payout = float(funded["gross_payout"].median()) if not funded.empty else np.nan
        avg_net_payout = float(funded["net_payout"].mean()) if not funded.empty else np.nan
        median_net_payout = float(funded["net_payout"].median()) if not funded.empty else np.nan
        median_days_to_first_payout = (
            float(funded["first_payout_day"].dropna().median())
            if not funded.empty and funded["first_payout_day"].notna().any()
            else np.nan
        )
        avg_days_to_first_payout = (
            float(funded["first_payout_day"].dropna().mean())
            if not funded.empty and funded["first_payout_day"].notna().any()
            else np.nan
        )
        probability_eval_to_first_payout = (
            pass_probability * first_payout_probability
            if not np.isnan(first_payout_probability)
            else np.nan
        )
        expected_eval_cost_to_first_payout = (
            eval_cost / probability_eval_to_first_payout
            if probability_eval_to_first_payout and probability_eval_to_first_payout > 0
            else np.inf
        )
        expected_net_payout_per_eval_attempt = (
            pass_probability * avg_net_payout - eval_cost
            if not np.isnan(avg_net_payout)
            else np.nan
        )

        rows.append({
            "profile": profile,
            "n_sims": n,
            "pass_probability_pct": float(pass_probability * 100.0),
            "fail_probability_pct": float(fail_mask.mean() * 100.0),
            "timeout_probability_pct": float(timeout_mask.mean() * 100.0),
            "daily_loss_fail_probability_pct": float(group["reason"].eq("daily_loss_limit").mean() * 100.0),
            "max_drawdown_fail_probability_pct": float(group["reason"].eq("max_drawdown").mean() * 100.0),
            "blown_probability_pct": float(group["reason"].isin(["daily_loss_limit", "max_drawdown"]).mean() * 100.0),
            "extension_threshold_fail_probability_pct": float(
                group["reason"].eq("extension_threshold_not_met").mean() * 100.0
            ),
            "consistency_block_probability_pct": float(group["consistency_blocked"].astype(bool).mean() * 100.0)
            if "consistency_blocked" in group.columns
                else 0.0,
            "avg_days_to_pass": float(passes["days"].mean()) if not passes.empty else np.nan,
            "median_days_to_pass": float(passes["days"].median()) if not passes.empty else np.nan,
            "p25_days_to_pass": float(passes["days"].quantile(0.25)) if not passes.empty else np.nan,
            "p75_days_to_pass": float(passes["days"].quantile(0.75)) if not passes.empty else np.nan,
            "avg_trading_days_to_pass": float(passes["trading_days"].mean())
            if not passes.empty and "trading_days" in passes.columns
            else np.nan,
            "median_trading_days_to_pass": float(passes["trading_days"].median())
            if not passes.empty and "trading_days" in passes.columns
            else np.nan,
            "avg_best_day_pct_of_total_profit": float(group["best_day_pct_of_total_profit"].mean())
            if "best_day_pct_of_total_profit" in group.columns
            else np.nan,
            "median_extra_profit_needed_for_consistency": float(
                group["extra_profit_needed_for_consistency"].median()
            )
            if "extra_profit_needed_for_consistency" in group.columns
            else np.nan,
            "median_final_equity": float(group["final_equity"].median()),
            "p05_final_equity": float(group["final_equity"].quantile(0.05)),
            "p95_final_equity": float(group["final_equity"].quantile(0.95)),
            "median_max_drawdown_dollars": float(group["max_drawdown_dollars"].median()),
            "p95_max_drawdown_dollars": float(group["max_drawdown_dollars"].quantile(0.95)),
            "eval_cost": eval_cost,
            "expected_attempts_to_pass": float(expected_attempts_to_pass),
            "expected_eval_cost_to_pass": float(expected_eval_cost_to_pass),
            "funded_horizon_days": int(group["funded_horizon_days"].iloc[0])
            if "funded_horizon_days" in group.columns
            else np.nan,
            "funded_survival_probability_pct": float(funded_survival_probability * 100.0)
            if not np.isnan(funded_survival_probability)
            else np.nan,
            "first_payout_probability_pct": float(first_payout_probability * 100.0)
            if not np.isnan(first_payout_probability)
            else np.nan,
            "payout_probability_if_eval_passed_pct": float(first_payout_probability * 100.0)
            if not np.isnan(first_payout_probability)
            else np.nan,
            "probability_eval_to_first_payout_pct": float(probability_eval_to_first_payout * 100.0)
            if not np.isnan(probability_eval_to_first_payout)
            else np.nan,
            "expected_eval_cost_to_first_payout": float(expected_eval_cost_to_first_payout),
            "avg_gross_payout": avg_gross_payout,
            "median_gross_payout": median_gross_payout,
            "avg_net_payout_after_split": avg_net_payout,
            "median_net_payout_after_split": median_net_payout,
            "expected_net_payout_per_eval_attempt": expected_net_payout_per_eval_attempt,
            "median_days_to_first_payout": median_days_to_first_payout,
            "avg_days_to_first_payout": avg_days_to_first_payout,
            "calendar_history_days": calendar_days,
            "active_history_days": active_days,
            "historical_active_day_pct": active_day_pct,
            "avg_historical_calendar_day_pnl": avg_calendar_daily,
            "median_historical_calendar_day_pnl": median_calendar_daily,
            "avg_historical_active_day_pnl": avg_daily,
            "median_historical_active_day_pnl": median_daily,
            "std_historical_active_day_pnl": daily_std,
            "worst_historical_active_day_pnl": worst_daily,
            "worst_historical_intraday_day_pnl": worst_intraday,
            "best_historical_active_day_pnl": best_daily,
            "account_size": float(group["account_size"].iloc[0]),
            "profit_target": float(group["profit_target"].iloc[0]),
            "max_drawdown": float(group["max_drawdown"].iloc[0]),
            "daily_loss_limit": float(group["daily_loss_limit"].iloc[0]),
            "min_trading_days": int(group["min_trading_days"].iloc[0]),
            "max_trading_days": int(group["max_trading_days"].iloc[0]),
            "initial_max_trading_days": int(group["initial_max_trading_days"].iloc[0])
            if "initial_max_trading_days" in group.columns
            else 0,
            "extension_trading_days": int(group["extension_trading_days"].iloc[0])
            if "extension_trading_days" in group.columns
            else 0,
            "consistency_profit_limit_pct": float(group["consistency_profit_limit_pct"].iloc[0])
            if "consistency_profit_limit_pct" in group.columns
            else 0.0,
            "drawdown_mode": str(group["drawdown_mode"].iloc[0]),
            "drawdown_check": str(group["drawdown_check"].iloc[0])
            if "drawdown_check" in group.columns
            else "intraday",
            "pnl_multiplier": float(group["pnl_multiplier"].iloc[0]) if "pnl_multiplier" in group.columns else 1.0,
            "profit_split_pct": float(group["profit_split_pct"].iloc[0])
            if "profit_split_pct" in group.columns
            else 100.0,
            "funded_buffer_target": float(group["funded_buffer_target"].iloc[0])
            if "funded_buffer_target" in group.columns
            else 0.0,
            "minimum_payout": float(group["minimum_payout"].iloc[0])
            if "minimum_payout" in group.columns
            else 0.0,
        })

    return pd.DataFrame(rows)


def _summary_row_from_records(
    eval_records: pd.DataFrame,
    funded_records: pd.DataFrame,
    daily_paths: pd.DataFrame,
) -> dict[str, Any]:
    if eval_records.empty:
        return {}
    profile = str(eval_records["profile"].iloc[0])
    summary = _summarize_simulations(
        eval_records,
        {profile: daily_paths},
        funded_records,
    )
    return summary.iloc[0].to_dict() if not summary.empty else {}


def _simulate_daily_surface(
    daily_paths: pd.DataFrame,
    profile: dict[str, Any],
    *,
    n_sims: int,
    seed: int,
) -> dict[str, Any]:
    rules = _normalize_profile(profile)
    eval_records = _simulate_profile(daily_paths, rules, n_sims=n_sims, seed=seed)
    funded_records = _simulate_funded_profile(daily_paths, rules, n_sims=n_sims, seed=seed + 500_009)
    return _summary_row_from_records(eval_records, funded_records, daily_paths)


def _scaled_trades(trades: pd.DataFrame, multiplier: float) -> pd.DataFrame:
    if multiplier == 1.0 or trades.empty:
        return trades.copy()
    scaled = trades.copy()
    for col in ("pnl", "mae_dollars", "mfe_dollars"):
        if col in scaled.columns:
            scaled[col] = pd.to_numeric(scaled[col], errors="coerce") * multiplier
    return scaled


def _trade_geometry_rows(trades: pd.DataFrame, profiles: list[dict[str, Any]]) -> pd.DataFrame:
    if trades.empty or "pnl" not in trades.columns:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    group_specs: list[tuple[str, pd.Series]] = [
        ("all", pd.Series(True, index=trades.index)),
    ]
    for col in ("direction", "signal_type", "setup_tag"):
        if col in trades.columns:
            for value in sorted(trades[col].dropna().astype(str).unique()):
                group_specs.append((f"{col}:{value}", trades[col].astype(str).eq(value)))

    for profile in profiles:
        rules = _normalize_profile(profile)
        multiplier = float(rules["pnl_multiplier"])
        for segment, mask in group_specs:
            group = trades.loc[mask].copy()
            if group.empty:
                continue
            pnl = pd.to_numeric(group["pnl"], errors="coerce").dropna() * multiplier
            if pnl.empty:
                continue
            wins = pnl[pnl > 0]
            losses = pnl[pnl < 0]
            avg_win = float(wins.mean()) if not wins.empty else 0.0
            avg_loss = float(losses.mean()) if not losses.empty else 0.0
            avg_loss_abs = abs(avg_loss)
            win_rate = float((pnl > 0).mean() * 100.0)
            reward_risk = avg_win / avg_loss_abs if avg_loss_abs > 0 else np.inf
            ev_per_trade = float(pnl.mean())
            std_trade = float(pnl.std(ddof=1)) if len(pnl) > 1 else 0.0
            breakeven_win_rate = 100.0 / (1.0 + reward_risk) if np.isfinite(reward_risk) else 0.0
            rows.append({
                "profile": rules["name"],
                "segment": segment,
                "trades": int(len(pnl)),
                "win_rate_pct": win_rate,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "reward_risk": reward_risk,
                "breakeven_win_rate_pct": breakeven_win_rate,
                "edge_vs_breakeven_win_rate_pct": win_rate - breakeven_win_rate,
                "expectancy_per_trade": ev_per_trade,
                "std_trade_pnl": std_trade,
                "return_volatility_to_drawdown": std_trade / float(rules["max_drawdown"])
                if float(rules["max_drawdown"]) > 0
                else np.nan,
            })

    return pd.DataFrame(rows)


def _risk_geometry_surface(profile: dict[str, Any], *, n_sims: int, seed: int) -> pd.DataFrame:
    rules = _normalize_profile(profile)
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    max_days = int(rules["max_trading_days"])
    horizon_days = int(rules["funded_horizon_days"])
    max_drawdown = float(rules["max_drawdown"])
    trades_per_day = int(rules["risk_geometry_trades_per_day"])

    for rr in rules["risk_geometry_reward_risk"]:
        if rr <= 0:
            continue
        win_prob = 1.0 / (1.0 + rr)
        for risk_frac in rules["risk_geometry_drawdown_risk_fracs"]:
            risk_dollars = max_drawdown * risk_frac
            if risk_dollars <= 0:
                continue

            def make_daily_arrays(days: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
                wins = rng.random((n_sims, days, trades_per_day)) < win_prob
                trade_pnl = np.where(wins, risk_dollars * rr, -risk_dollars)
                cum = trade_pnl.cumsum(axis=2)
                net = trade_pnl.sum(axis=2)
                low = np.minimum(0.0, cum.min(axis=2))
                high = np.maximum(0.0, cum.max(axis=2))
                trade_count = np.full((n_sims, days), trades_per_day, dtype=int)
                return net, low, high, trade_count

            eval_net, eval_low, eval_high, eval_trade_count = make_daily_arrays(max_days)
            funded_net, funded_low, funded_high, _ = make_daily_arrays(horizon_days)
            eval_records = _attach_eval_metadata(
                _simulate_eval_arrays(eval_net, eval_low, eval_high, rules, eval_trade_count),
                rules,
            )
            funded_records = _attach_funded_metadata(
                _simulate_funded_arrays(funded_net, funded_low, funded_high, rules),
                rules,
            )
            synthetic_daily = pd.DataFrame({
                "net_pnl": eval_net.reshape(-1),
                "min_intraday_pnl": eval_low.reshape(-1),
                "max_intraday_pnl": eval_high.reshape(-1),
                "trade_count": trades_per_day,
            })
            row = _summary_row_from_records(eval_records, funded_records, synthetic_daily)
            row.update({
                "surface": "risk_geometry_ev0",
                "reward_risk": rr,
                "ev0_win_rate_pct": win_prob * 100.0,
                "risk_dollars": risk_dollars,
                "risk_fraction_of_drawdown": risk_frac,
                "trades_per_day": trades_per_day,
                "toy_trade_expectancy": 0.0,
                "toy_trade_std": float(
                    np.sqrt(win_prob * (risk_dollars * rr) ** 2 + (1.0 - win_prob) * risk_dollars ** 2)
                ),
            })
            rows.append(row)

    return pd.DataFrame(rows)


def _sizing_surface(
    base_daily_paths: pd.DataFrame,
    profile: dict[str, Any],
    *,
    n_sims: int,
    seed: int,
) -> pd.DataFrame:
    rules = _normalize_profile(profile)
    rows: list[dict[str, Any]] = []
    for idx, multiplier in enumerate(rules["sizing_multipliers"]):
        surface_rules = dict(rules)
        surface_rules["pnl_multiplier"] = multiplier
        daily_paths = _scale_daily_paths(base_daily_paths, multiplier)
        row = _simulate_daily_surface(
            daily_paths,
            surface_rules,
            n_sims=n_sims,
            seed=seed + idx * 997,
        )
        row.update({
            "surface": "sizing",
            "tested_pnl_multiplier": multiplier,
            "relative_to_profile_multiplier": (
                multiplier / float(rules["pnl_multiplier"]) if float(rules["pnl_multiplier"]) else np.nan
            ),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def _daily_rules_surface(
    trades: pd.DataFrame,
    profile: dict[str, Any],
    *,
    n_sims: int,
    seed: int,
) -> pd.DataFrame:
    rules = _normalize_profile(profile)
    rows: list[dict[str, Any]] = []
    scaled_trades = _scaled_trades(trades, float(rules["pnl_multiplier"]))
    idx = 0
    for daily_loss_stop in rules["daily_loss_stops"]:
        for daily_profit_lock in rules["daily_profit_locks"]:
            daily_paths = _daily_paths_from_trades(
                scaled_trades,
                daily_loss_stop=float(daily_loss_stop),
                daily_profit_lock=float(daily_profit_lock),
            )
            row = _simulate_daily_surface(
                daily_paths,
                rules,
                n_sims=n_sims,
                seed=seed + idx * 997,
            )
            row.update({
                "surface": "daily_stop_profit_lock",
                "daily_loss_stop": float(daily_loss_stop),
                "daily_profit_lock": float(daily_profit_lock),
                "rule_active": bool(daily_loss_stop > 0 or daily_profit_lock > 0),
            })
            rows.append(row)
            idx += 1
    return pd.DataFrame(rows)


def _sort_trades_for_path(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    time_col = "exit_time" if "exit_time" in trades.columns else "entry_time"
    work = trades.copy()
    if time_col in work.columns:
        work["_path_time"] = pd.to_datetime(work[time_col], errors="coerce")
    else:
        work["_path_time"] = pd.NaT
    work["_path_seq"] = np.arange(len(work))
    return work.sort_values(["_path_time", "_path_seq"], kind="mergesort").drop(
        columns=["_path_seq"],
        errors="ignore",
    )


def _historical_trade_path(
    trades: pd.DataFrame,
    profile: dict[str, Any],
) -> pd.DataFrame:
    rules = _normalize_profile(profile)
    work = _sort_trades_for_path(trades)
    if work.empty or "pnl" not in work.columns:
        return pd.DataFrame()
    pnl = pd.to_numeric(work["pnl"], errors="coerce").fillna(0.0) * float(rules["pnl_multiplier"])
    time_col = "_path_time" if "_path_time" in work.columns else None
    times = pd.to_datetime(work[time_col], errors="coerce") if time_col else pd.Series(pd.NaT, index=work.index)
    equity = float(rules["account_size"]) + pnl.cumsum()
    running_peak = equity.cummax()
    drawdown = equity - running_peak
    out = pd.DataFrame({
        "profile": rules["name"],
        "trade_number": np.arange(1, len(work) + 1),
        "time": times.to_numpy(),
        "date": times.dt.date.to_numpy() if times.notna().any() else np.arange(len(work)),
        "pnl": pnl.to_numpy(dtype=float),
        "equity": equity.to_numpy(dtype=float),
        "drawdown": drawdown.to_numpy(dtype=float),
    })
    return out


def _max_drawdown_dollars_from_equity(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peaks = equity.cummax()
    return float((peaks - equity).max())


def _strategy_metrics_rows(trades: pd.DataFrame, profiles: list[dict[str, Any]]) -> pd.DataFrame:
    if trades.empty or "pnl" not in trades.columns:
        return pd.DataFrame()

    sorted_trades = _sort_trades_for_path(trades)
    raw_pnl = pd.to_numeric(sorted_trades["pnl"], errors="coerce").fillna(0.0)
    time_col = "_path_time" if "_path_time" in sorted_trades.columns else None
    times = pd.to_datetime(sorted_trades[time_col], errors="coerce") if time_col else pd.Series(pd.NaT, index=sorted_trades.index)
    valid_times = times.dropna()
    calendar_days = (
        max((valid_times.max() - valid_times.min()).total_seconds() / 86400.0, 1.0)
        if len(valid_times) >= 2
        else max(float(len(raw_pnl)), 1.0)
    )
    years = max(calendar_days / 365.25, 1.0 / 365.25)
    weeks = max(calendar_days / 7.0, 1.0 / 7.0)
    dates = times.dt.date if times.notna().any() else pd.Series(np.arange(len(raw_pnl)), index=sorted_trades.index)

    rows: list[dict[str, Any]] = []
    for profile in profiles:
        rules = _normalize_profile(profile)
        pnl = raw_pnl * float(rules["pnl_multiplier"])
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        gross_profit = float(wins.sum()) if not wins.empty else 0.0
        gross_loss = float(losses.sum()) if not losses.empty else 0.0
        avg_win = float(wins.mean()) if not wins.empty else 0.0
        avg_loss = float(losses.mean()) if not losses.empty else 0.0
        reward_risk = avg_win / abs(avg_loss) if avg_loss < 0 else np.inf
        profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else np.inf
        equity = float(rules["account_size"]) + pnl.cumsum()
        daily = pnl.groupby(dates, sort=True).sum()
        max_dd = _max_drawdown_dollars_from_equity(equity)
        daily_equity = float(rules["account_size"]) + daily.cumsum()
        daily_max_dd = _max_drawdown_dollars_from_equity(daily_equity)
        rows.append({
            "profile": rules["name"],
            "trades": int(len(pnl)),
            "active_trading_days": int(len(daily)),
            "calendar_days": float(calendar_days),
            "years": float(years),
            "win_rate_pct": float((pnl > 0).mean() * 100.0) if len(pnl) else 0.0,
            "reward_risk": float(reward_risk),
            "profit_factor": float(profit_factor),
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_trade": float(pnl.mean()) if len(pnl) else 0.0,
            "median_trade": float(pnl.median()) if len(pnl) else 0.0,
            "total_pnl": float(pnl.sum()),
            "annualized_pnl": float(pnl.sum() / years),
            "avg_daily_pnl": float(daily.mean()) if len(daily) else 0.0,
            "median_daily_pnl": float(daily.median()) if len(daily) else 0.0,
            "max_daily_loss": float(daily.min()) if len(daily) else 0.0,
            "best_daily_pnl": float(daily.max()) if len(daily) else 0.0,
            "max_drawdown_dollars": float(max_dd),
            "daily_max_drawdown_dollars": float(daily_max_dd),
            "max_drawdown_pct_of_account": float(max_dd / float(rules["account_size"]) * 100.0)
            if float(rules["account_size"]) > 0
            else np.nan,
            "daily_max_loss_pct_of_account": float(abs(min(float(daily.min()), 0.0)) / float(rules["account_size"]) * 100.0)
            if len(daily) and float(rules["account_size"]) > 0
            else 0.0,
            "trades_per_week": float(len(pnl) / weeks),
            "trades_per_active_day": float(len(pnl) / len(daily)) if len(daily) else 0.0,
            "expectancy_to_max_drawdown": float(pnl.sum() / max_dd) if max_dd > 0 else np.inf,
            "account_size": float(rules["account_size"]),
            "pnl_multiplier": float(rules["pnl_multiplier"]),
        })
    return pd.DataFrame(rows)


def _trade_sharpe(values: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    if values.size < 2:
        return 0.0
    std = float(np.std(values, ddof=1))
    if std <= 0:
        return 0.0
    return float(np.mean(values) / std * np.sqrt(values.size))


def _random_walk_sign_flip(
    trades: pd.DataFrame,
    profiles: list[dict[str, Any]],
    *,
    n_sims: int,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if trades.empty or "pnl" not in trades.columns:
        return pd.DataFrame(), pd.DataFrame()
    base_pnl = pd.to_numeric(_sort_trades_for_path(trades)["pnl"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    if base_pnl.size == 0:
        return pd.DataFrame(), pd.DataFrame()
    abs_pnl = np.abs(base_pnl)

    summary_rows: list[dict[str, Any]] = []
    sample_frames: list[pd.DataFrame] = []
    for profile_idx, profile in enumerate(profiles):
        rules = _normalize_profile(profile)
        profile_sims = max(1, int(min(n_sims, rules.get("random_walk_n_sims", n_sims))))
        rng = np.random.default_rng(seed + profile_idx * 10_007)
        signs = rng.choice(np.array([-1.0, 1.0]), size=(profile_sims, abs_pnl.size))
        samples = signs * abs_pnl[None, :] * float(rules["pnl_multiplier"])
        totals = samples.sum(axis=1)
        means = samples.mean(axis=1)
        stds = samples.std(axis=1, ddof=1) if samples.shape[1] > 1 else np.zeros(profile_sims)
        sharpes = np.divide(
            means,
            stds,
            out=np.zeros_like(means, dtype=float),
            where=stds > 0,
        ) * np.sqrt(samples.shape[1])
        real_pnl = base_pnl * float(rules["pnl_multiplier"])
        real_total = float(real_pnl.sum())
        real_sharpe = _trade_sharpe(real_pnl)
        pnl_p = float((totals >= real_total).mean()) if real_total >= 0 else float((totals <= real_total).mean())
        sharpe_p = float((sharpes >= real_sharpe).mean()) if real_sharpe >= 0 else float((sharpes <= real_sharpe).mean())
        summary_rows.append({
            "profile": rules["name"],
            "n_permutations": int(profile_sims),
            "trades": int(abs_pnl.size),
            "real_total_pnl": real_total,
            "random_mean_total_pnl": float(np.mean(totals)),
            "random_p05_total_pnl": float(np.quantile(totals, 0.05)),
            "random_p95_total_pnl": float(np.quantile(totals, 0.95)),
            "pnl_p_value": pnl_p,
            "pnl_pass_5pct": bool(pnl_p <= 0.05),
            "real_trade_sharpe": real_sharpe,
            "random_mean_trade_sharpe": float(np.mean(sharpes)),
            "random_p05_trade_sharpe": float(np.quantile(sharpes, 0.05)),
            "random_p95_trade_sharpe": float(np.quantile(sharpes, 0.95)),
            "sharpe_p_value": sharpe_p,
            "sharpe_pass_5pct": bool(sharpe_p <= 0.05),
        })
        sample_frames.append(pd.DataFrame({
            "profile": rules["name"],
            "sim_id": np.arange(profile_sims, dtype=int),
            "total_pnl": totals,
            "trade_sharpe": sharpes,
        }))

    return pd.DataFrame(summary_rows), pd.concat(sample_frames, ignore_index=True) if sample_frames else pd.DataFrame()


def _attempt_curve(summary: pd.DataFrame, funded_simulations: pd.DataFrame, profiles: list[dict[str, Any]]) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    profile_rules = {_normalize_profile(profile)["name"]: _normalize_profile(profile) for profile in profiles}
    for _, row in summary.iterrows():
        profile = str(row["profile"])
        rules = profile_rules.get(profile, _normalize_profile({}))
        max_attempts = int(rules.get("attempt_curve_max_attempts", 10))
        pass_probability = float(row.get("pass_probability_pct", 0.0)) / 100.0
        first_payout_cond = float(row.get("first_payout_probability_pct", 0.0)) / 100.0
        payout_probability = pass_probability * first_payout_cond
        funded = (
            funded_simulations.loc[funded_simulations["profile"].astype(str).eq(profile)]
            if not funded_simulations.empty and "profile" in funded_simulations.columns
            else pd.DataFrame()
        )
        achieved = (
            pd.to_numeric(funded.loc[pd.to_numeric(funded.get("net_payout", 0), errors="coerce") > 0, "net_payout"], errors="coerce")
            if not funded.empty and "net_payout" in funded.columns
            else pd.Series(dtype=float)
        )
        payout_when_achieved = (
            float(achieved.mean())
            if not achieved.empty
            else float(row.get("avg_net_payout_after_split", 0.0) or 0.0)
        )
        eval_cost = float(row.get("eval_cost", 0.0) or 0.0)
        for attempts in range(1, max_attempts + 1):
            if payout_probability > 0:
                success_by_attempt = 1.0 - (1.0 - payout_probability) ** attempts
                expected_attempts_paid = (1.0 - (1.0 - payout_probability) ** attempts) / payout_probability
            else:
                success_by_attempt = 0.0
                expected_attempts_paid = float(attempts)
            expected_payout = payout_when_achieved * success_by_attempt
            expected_cost = eval_cost * expected_attempts_paid
            rows.append({
                "profile": profile,
                "attempts": attempts,
                "payout_probability_by_attempt_pct": success_by_attempt * 100.0,
                "expected_attempts_paid": expected_attempts_paid,
                "expected_cost": expected_cost,
                "expected_payout": expected_payout,
                "expected_value": expected_payout - expected_cost,
                "payout_when_achieved": payout_when_achieved,
                "eval_cost": eval_cost,
            })
    return pd.DataFrame(rows)


def _sample_eval_equity_paths(
    daily_paths: pd.DataFrame,
    profile: dict[str, Any],
    *,
    n_paths: int,
    seed: int,
) -> pd.DataFrame:
    rules = _normalize_profile(profile)
    rng = np.random.default_rng(seed)
    max_days = int(rules["max_trading_days"])
    net, low, high, trade_count = _sample_daily_arrays(daily_paths, max_days, n_paths, rng)
    account_size = float(rules["account_size"])
    profit_target = float(rules["profit_target"])
    max_drawdown = float(rules["max_drawdown"])
    daily_loss_limit = float(rules["daily_loss_limit"])
    min_days = int(rules["min_trading_days"])
    stop_after_target = bool(rules["stop_after_target_until_min_days"])
    consistency_limit = float(rules["consistency_profit_limit"])
    drawdown_mode = str(rules["drawdown_mode"]).lower()
    drawdown_check = str(rules["drawdown_check"]).lower()
    cap_trailing_floor = bool(rules["trailing_drawdown_cap_at_initial"])

    rows: list[dict[str, Any]] = []
    for sim_id in range(n_paths):
        equity = account_size
        peak_equity = account_size
        eod_peak_equity = account_size
        static_floor = account_size - max_drawdown if max_drawdown > 0 else -np.inf
        drawdown_floor = static_floor
        status = "active"
        trading_days_taken = 0
        best_profit_day = 0.0
        target_hit_day: int | None = None
        consistency_blocked = False
        rows.append({
            "profile": rules["name"],
            "sim_id": sim_id,
            "day": 0,
            "equity": equity,
            "drawdown_floor": drawdown_floor,
            "status": status,
        })
        for day_idx in range(max_days):
            hold_after_target = (
                target_hit_day is not None
                and stop_after_target
                and not consistency_blocked
                and equity - account_size >= profit_target
            )
            if hold_after_target:
                day_net = 0.0
                day_low_offset = 0.0
                day_high_offset = 0.0
                day_trade_count = 0
            else:
                day_net = float(net[sim_id, day_idx])
                day_low_offset = float(low[sim_id, day_idx])
                day_high_offset = float(high[sim_id, day_idx])
                day_trade_count = int(trade_count[sim_id, day_idx])
            day_start = equity
            day_low = day_start + day_low_offset
            day_high = day_start + day_high_offset
            equity += day_net
            if day_trade_count > 0:
                trading_days_taken += 1
            best_profit_day = max(best_profit_day, day_net)
            peak_equity = max(peak_equity, day_high, equity)
            eod_peak_equity = max(eod_peak_equity, equity)
            if drawdown_mode in (
                "eod_trailing",
                "trailing",
                "trailing_eod",
                "eod_trailing_lock_at_initial",
                "eod_lock",
            ) and max_drawdown > 0:
                drawdown_floor = max(static_floor, eod_peak_equity - max_drawdown)
                if cap_trailing_floor:
                    drawdown_floor = min(drawdown_floor, account_size)
            else:
                drawdown_floor = static_floor
            drawdown_test_equity = equity if drawdown_check == "eod" else min(day_low, equity)
            if daily_loss_limit > 0 and day_low_offset <= -daily_loss_limit:
                status = "fail"
            elif max_drawdown > 0 and drawdown_test_equity <= drawdown_floor:
                status = "fail"
            else:
                net_pnl = equity - account_size
                consistency_ok = True
                if consistency_limit > 0 and net_pnl > 0:
                    consistency_ok = best_profit_day <= net_pnl * consistency_limit
                if profit_target > 0 and net_pnl >= profit_target:
                    if target_hit_day is None:
                        target_hit_day = day_idx + 1
                    if trading_days_taken >= min_days and consistency_ok:
                        status = "pass"
                    elif not consistency_ok:
                        consistency_blocked = True
                else:
                    consistency_blocked = False
            rows.append({
                "profile": rules["name"],
                "sim_id": sim_id,
                "day": day_idx + 1,
                "equity": float(equity),
                "drawdown_floor": float(drawdown_floor),
                "status": status,
            })
            if status != "active":
                break
    return pd.DataFrame(rows)


def _chart_modules():
    mpl_config_dir = Path("results/.mplconfig").resolve()
    mpl_config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_config_dir))

    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    return plt, FuncFormatter


def _style_chart_figure(fig: Any, title: str, *, y: float = 0.98, fontsize: int = 20) -> None:
    fig.patch.set_facecolor(CHART_BG)
    fig.suptitle(title, color=CHART_TEXT, fontsize=fontsize, fontweight="bold", y=y)


def _style_chart_axis(ax: Any, *, grid: bool = True) -> None:
    ax.set_facecolor(CHART_PANEL)
    ax.tick_params(colors=CHART_MUTED)
    ax.xaxis.label.set_color("#cbd5e1")
    ax.yaxis.label.set_color("#cbd5e1")
    ax.title.set_color(CHART_TEXT)
    for spine in ax.spines.values():
        spine.set_color(CHART_SPINE)
        spine.set_linewidth(0.9)
    if grid:
        ax.grid(True, color=CHART_GRID, alpha=0.45, linewidth=0.8)
    else:
        ax.grid(False)


def _style_chart_colorbar(cbar: Any) -> None:
    cbar.ax.tick_params(colors=CHART_MUTED)
    cbar.ax.yaxis.label.set_color("#cbd5e1")
    cbar.outline.set_edgecolor(CHART_SPINE)


def _style_chart_table(table: Any, *, font_color: str = CHART_TEXT) -> None:
    for (row_idx, _), cell in table.get_celld().items():
        cell.set_edgecolor(CHART_GRID)
        cell.set_linewidth(0.8)
        cell.set_facecolor(CHART_TABLE_HEADER if row_idx == 0 else CHART_TABLE_ROW)
        cell.get_text().set_color(font_color)
        if row_idx == 0:
            cell.get_text().set_fontweight("bold")


def _format_axis_label(value: Any, *, money: bool = False, pct: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if money:
        return f"${number:,.0f}"
    if pct:
        pct_value = number * 100.0 if abs(number) <= 1.0 else number
        return f"{pct_value:.0f}%"
    if abs(number) >= 100:
        return f"{number:.0f}"
    if abs(number) >= 10:
        return f"{number:.1f}"
    return f"{number:.2g}"


def _first_profile_slice(df: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    if df.empty or "profile" not in df.columns:
        return "profile", df.copy()
    profile = str(df["profile"].dropna().astype(str).iloc[0]) if df["profile"].notna().any() else "profile"
    return profile, df[df["profile"].astype(str).eq(profile)].copy()


def _metric_pivot(
    df: pd.DataFrame,
    *,
    index: str,
    columns: str,
    values: str,
) -> pd.DataFrame:
    required = {index, columns, values}
    if df.empty or not required.issubset(df.columns):
        return pd.DataFrame()
    work = df.loc[:, [index, columns, values]].copy()
    work[index] = pd.to_numeric(work[index], errors="coerce")
    work[columns] = pd.to_numeric(work[columns], errors="coerce")
    work[values] = pd.to_numeric(work[values], errors="coerce")
    work = work.dropna(subset=[index, columns, values])
    if work.empty:
        return pd.DataFrame()
    return (
        work.pivot_table(index=index, columns=columns, values=values, aggfunc="mean")
        .sort_index()
        .sort_index(axis=1)
    )


def _annotated_heatmap(
    ax: Any,
    pivot: pd.DataFrame,
    *,
    title: str,
    xlabel: str,
    ylabel: str,
    cbar_label: str,
    cmap: str = "RdYlGn",
    money: bool = False,
    x_money: bool = False,
    y_money: bool = False,
    pct_axes: bool = False,
    value_fmt: str = "{:.1f}",
    vmin: float | None = None,
    vmax: float | None = None,
) -> None:
    if pivot.empty:
        _style_chart_axis(ax, grid=False)
        ax.text(0.5, 0.5, "No data", ha="center", va="center", color=CHART_MUTED, transform=ax.transAxes)
        ax.set_title(title, color=CHART_TEXT)
        ax.set_axis_off()
        return

    data = pivot.to_numpy(dtype=float)
    masked = np.ma.masked_invalid(data)
    image = ax.imshow(masked, aspect="auto", cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_title(title, fontsize=13, fontweight="bold", color=CHART_TEXT)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_xticks(np.arange(len(pivot.columns)))
    ax.set_yticks(np.arange(len(pivot.index)))
    ax.set_xticklabels([_format_axis_label(v, money=x_money) for v in pivot.columns], rotation=0)
    ax.set_yticklabels([_format_axis_label(v, money=y_money, pct=pct_axes) for v in pivot.index])
    cbar = ax.figure.colorbar(image, ax=ax, fraction=0.045, pad=0.03, label=cbar_label)
    _style_chart_colorbar(cbar)
    _style_chart_axis(ax, grid=False)

    finite = data[np.isfinite(data)]
    center = float(np.nanmedian(finite)) if finite.size else 0.0
    for row_idx in range(data.shape[0]):
        for col_idx in range(data.shape[1]):
            value = data[row_idx, col_idx]
            if not np.isfinite(value):
                continue
            label = f"${value:,.0f}" if money else value_fmt.format(value)
            color = "#f8fafc" if value <= center else "#07101a"
            ax.text(col_idx, row_idx, label, ha="center", va="center", fontsize=9, color=color)


def _save_empty_chart(out_path: Path, title: str, message: str = "No chart data available.") -> None:
    plt, _ = _chart_modules()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    _style_chart_figure(fig, title)
    ax.set_facecolor(CHART_PANEL)
    ax.set_axis_off()
    ax.text(0.5, 0.52, message, ha="center", va="center", fontsize=11, color=CHART_MUTED)
    fig.tight_layout()
    fig.savefig(out_path, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)


def _plot_prop_firm_dashboard(
    summary: pd.DataFrame,
    simulations: pd.DataFrame,
    funded_simulations: pd.DataFrame,
    out_path: Path,
) -> None:
    plt, FuncFormatter = _chart_modules()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile, row_df = _first_profile_slice(summary)
    if row_df.empty:
        _save_empty_chart(out_path, "Prop Firm Dashboard")
        return
    row = row_df.iloc[0]
    sim = simulations[simulations["profile"].astype(str).eq(profile)] if "profile" in simulations.columns else simulations
    funded = (
        funded_simulations[funded_simulations["profile"].astype(str).eq(profile)]
        if "profile" in funded_simulations.columns
        else funded_simulations
    )

    fig, axes = plt.subplots(2, 2, figsize=(15.5, 9.2))
    _style_chart_figure(fig, f"Prop Firm Decision Dashboard - {profile}")

    ax = axes[0, 0]
    _style_chart_axis(ax, grid=False)
    ax.set_axis_off()
    ax.set_title("Decision KPIs", color=CHART_TEXT, fontweight="bold", loc="left", pad=10)
    cards = [
        ("Eval pass", f"{_coerce_finite(row.get('pass_probability_pct')):.1f}%", CHART_GREEN),
        ("First payout", f"{_coerce_finite(row.get('probability_eval_to_first_payout_pct')):.1f}%", CHART_CYAN),
        ("EV / eval", f"${_coerce_finite(row.get('expected_net_payout_per_eval_attempt')):,.0f}", CHART_BLUE),
        ("Median pass days", f"{_coerce_finite(row.get('median_days_to_pass')):.0f}d", CHART_YELLOW),
    ]
    for idx, (label, value, color) in enumerate(cards):
        x0 = 0.04 + (idx % 2) * 0.48
        y0 = 0.57 - (idx // 2) * 0.38
        ax.text(
            x0,
            y0 + 0.16,
            label,
            transform=ax.transAxes,
            color=CHART_MUTED,
            fontsize=10,
            fontweight="bold",
            ha="left",
            va="center",
        )
        ax.text(
            x0,
            y0,
            value,
            transform=ax.transAxes,
            color=color,
            fontsize=25,
            fontweight="bold",
            ha="left",
            va="center",
        )

    ax = axes[0, 1]
    driver_metrics = [
        ("DD fail", "max_drawdown_fail_probability_pct"),
        ("Timeout", "timeout_probability_pct"),
        ("Consistency", "consistency_block_probability_pct"),
        ("Extension", "extension_threshold_fail_probability_pct"),
        ("Daily loss", "daily_loss_fail_probability_pct"),
    ]
    labels = [label for label, col in driver_metrics if col in row.index]
    values = [_coerce_finite(row[col]) for _, col in driver_metrics if col in row.index]
    if values:
        ax.bar(labels, values, color=[CHART_RED, CHART_ORANGE, CHART_PURPLE, CHART_YELLOW, CHART_CYAN][: len(values)], alpha=0.86)
        for idx, value in enumerate(values):
            ax.text(idx, value + 1.2, f"{value:.1f}%", ha="center", color=CHART_TEXT, fontsize=9)
    ax.set_ylim(0, max(10, min(100, max(values) * 1.25 if values else 10)))
    ax.set_ylabel("Simulation share (%)")
    ax.set_title("Failure And Constraint Drivers", fontweight="bold")
    _style_chart_axis(ax)

    ax = axes[1, 0]
    money_metrics = [
        ("Cost / pass", "expected_eval_cost_to_pass"),
        ("Cost / payout", "expected_eval_cost_to_first_payout"),
        ("EV / eval", "expected_net_payout_per_eval_attempt"),
        ("Avg funded payout", "avg_net_payout_after_split"),
    ]
    labels = [label for label, col in money_metrics if col in row.index]
    values = [_coerce_finite(row[col]) for _, col in money_metrics if col in row.index]
    bar_colors = [CHART_GREEN if value >= 0 else CHART_RED for value in values]
    ax.bar(labels, values, color=bar_colors, alpha=0.86)
    ax.axhline(0, color=CHART_MUTED, linewidth=0.8)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value:,.0f}"))
    ax.set_title("Cost And Payout Economics", fontweight="bold")
    ax.tick_params(axis="x", rotation=10)
    for idx, value in enumerate(values):
        va = "bottom" if value >= 0 else "top"
        ax.text(idx, value, f"${value:,.0f}", ha="center", va=va, fontsize=9, color=CHART_TEXT)
    _style_chart_axis(ax)

    ax = axes[1, 1]
    payout_col = "net_payout" if "net_payout" in funded.columns else "gross_payout"
    payouts = pd.to_numeric(funded.get(payout_col, pd.Series(dtype=float)), errors="coerce").dropna()
    if not payouts.empty:
        bins = min(40, max(8, int(np.sqrt(len(payouts)))))
        ax.hist(payouts, bins=bins, color=CHART_GREEN, alpha=0.72, edgecolor=CHART_BG, linewidth=0.4)
        ax.axvline(payouts.median(), color=CHART_CYAN, linestyle="--", linewidth=1.2, label="Median")
        ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value:,.0f}"))
    ax.set_title("Funded Payout Distribution", fontweight="bold")
    ax.set_xlabel("Net payout")
    ax.set_ylabel("Simulations")
    _style_chart_axis(ax)

    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(out_path, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)


def _plot_risk_geometry_chart(surface: pd.DataFrame, out_path: Path) -> None:
    plt, _ = _chart_modules()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile, df = _first_profile_slice(surface)
    pass_pivot = _metric_pivot(
        df,
        index="risk_fraction_of_drawdown",
        columns="reward_risk",
        values="pass_probability_pct",
    )
    ev_pivot = _metric_pivot(
        df,
        index="risk_fraction_of_drawdown",
        columns="reward_risk",
        values="expected_net_payout_per_eval_attempt",
    )
    if pass_pivot.empty:
        _save_empty_chart(out_path, "Risk Geometry Surface")
        return

    fig = plt.figure(figsize=(16.5, 7.8))
    _style_chart_figure(fig, f"Prop Firm Risk Geometry - {profile}")
    ax3d = fig.add_subplot(1, 2, 1, projection="3d")
    ax_heat = fig.add_subplot(1, 2, 2)

    x = pass_pivot.columns.to_numpy(dtype=float)
    y = pass_pivot.index.to_numpy(dtype=float) * 100.0
    x_grid, y_grid = np.meshgrid(x, y)
    z_grid = pass_pivot.to_numpy(dtype=float)
    if z_grid.shape[0] >= 2 and z_grid.shape[1] >= 2:
        surface_plot = ax3d.plot_surface(
            x_grid,
            y_grid,
            z_grid,
            cmap="RdYlGn",
            vmin=0,
            vmax=100,
            linewidth=0.35,
            edgecolor="#64748b",
            alpha=0.92,
        )
        cbar = fig.colorbar(surface_plot, ax=ax3d, shrink=0.62, pad=0.08, label="Pass rate (%)")
        _style_chart_colorbar(cbar)
    else:
        ax3d.scatter(x_grid.ravel(), y_grid.ravel(), z_grid.ravel(), c=z_grid.ravel(), cmap="RdYlGn", s=80)
    ax3d.set_xlabel("Reward:risk")
    ax3d.set_ylabel("Risk / drawdown (%)")
    ax3d.set_zlabel("Pass rate (%)")
    ax3d.set_title("Challenge Pass Rate Surface", fontweight="bold")
    ax3d.view_init(elev=28, azim=-130)
    ax3d.set_facecolor(CHART_BG)
    ax3d.tick_params(colors=CHART_MUTED)
    ax3d.xaxis.label.set_color("#cbd5e1")
    ax3d.yaxis.label.set_color("#cbd5e1")
    ax3d.zaxis.label.set_color("#cbd5e1")
    ax3d.title.set_color(CHART_TEXT)
    for axis in (ax3d.xaxis, ax3d.yaxis, ax3d.zaxis):
        axis.pane.set_facecolor((0.04, 0.06, 0.09, 1.0))
        axis.pane.set_edgecolor(CHART_SPINE)

    heatmap = ev_pivot if not ev_pivot.empty else pass_pivot
    _annotated_heatmap(
        ax_heat,
        heatmap,
        title="Expected Net Per Eval Attempt",
        xlabel="Reward:risk",
        ylabel="Risk / drawdown",
        cbar_label="$ per eval attempt" if not ev_pivot.empty else "Pass rate (%)",
        cmap="RdYlGn",
        money=not ev_pivot.empty,
        pct_axes=True,
        value_fmt="{:.1f}",
    )

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_path, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)


def _plot_sizing_chart(surface: pd.DataFrame, out_path: Path) -> None:
    plt, FuncFormatter = _chart_modules()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile, df = _first_profile_slice(surface)
    if df.empty or "tested_pnl_multiplier" not in df.columns:
        _save_empty_chart(out_path, "Sizing Surface")
        return
    df = df.copy()
    df["tested_pnl_multiplier"] = pd.to_numeric(df["tested_pnl_multiplier"], errors="coerce")
    df = df.sort_values("tested_pnl_multiplier")

    fig, axes = plt.subplots(2, 2, figsize=(15.5, 9.0))
    _style_chart_figure(fig, f"Prop Firm Sizing Surface - {profile}")
    x = df["tested_pnl_multiplier"].to_numpy(dtype=float)

    panels = [
        (axes[0, 0], "pass_probability_pct", "Eval Pass Sensitivity", "Probability (%)", False, CHART_GREEN),
        (axes[0, 1], "expected_net_payout_per_eval_attempt", "Expected Net Per Eval", "$", True, CHART_BLUE),
        (axes[1, 0], "probability_eval_to_first_payout_pct", "First-Payout Sensitivity", "Probability (%)", False, CHART_PURPLE),
        (axes[1, 1], "max_drawdown_fail_probability_pct", "Drawdown Fail Sensitivity", "Probability (%)", False, CHART_RED),
    ]
    for ax, col, title, ylabel, money, color in panels:
        y = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float) if col in df.columns else np.full_like(x, np.nan)
        ax.plot(x, y, marker="o", linewidth=2.2, color=color)
        ax.set_title(title, fontweight="bold")
        ax.set_xlabel("PnL multiplier")
        ax.set_ylabel(ylabel)
        if money:
            ax.axhline(0, color=CHART_MUTED, linewidth=0.8)
            ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value:,.0f}"))
        else:
            ax.set_ylim(0, 100)
        for xi, yi in zip(x, y):
            if np.isfinite(yi):
                label = f"${yi:,.0f}" if money else f"{yi:.1f}%"
                ax.text(xi, yi, label, ha="center", va="bottom", fontsize=8, color=CHART_TEXT)
        _style_chart_axis(ax)

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_path, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)


def _plot_daily_rules_chart(surface: pd.DataFrame, out_path: Path) -> None:
    plt, _ = _chart_modules()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile, df = _first_profile_slice(surface)
    if df.empty:
        _save_empty_chart(out_path, "Daily Rules Surface")
        return

    fig, axes = plt.subplots(2, 2, figsize=(16.0, 10.0))
    _style_chart_figure(fig, f"Daily Stop / Profit Lock Surface - {profile}")
    panels = [
        ("pass_probability_pct", "Pass Rate (%)", "Eval Pass Sensitivity", False, "RdYlGn", 0.0, 100.0),
        ("expected_net_payout_per_eval_attempt", "$ per eval", "Expected Net Per Eval", True, "RdYlGn", None, None),
        ("max_drawdown_fail_probability_pct", "Failure (%)", "Drawdown Fail Probability", False, "RdYlGn_r", 0.0, 100.0),
        ("median_days_to_pass", "Days", "Median Days To Pass", False, "YlGnBu", None, None),
    ]
    for ax, (metric, cbar_label, title, money, cmap, vmin, vmax) in zip(axes.ravel(), panels):
        pivot = _metric_pivot(
            df,
            index="daily_loss_stop",
            columns="daily_profit_lock",
            values=metric,
        )
        _annotated_heatmap(
            ax,
            pivot,
            title=title,
            xlabel="Daily profit lock",
            ylabel="Daily loss stop",
            cbar_label=cbar_label,
            cmap=cmap,
            money=money,
            x_money=True,
            y_money=True,
            value_fmt="{:.1f}",
            vmin=vmin,
            vmax=vmax,
        )

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_path, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)


def _plot_trade_geometry_chart(trade_geometry: pd.DataFrame, out_path: Path) -> None:
    plt, _ = _chart_modules()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile, df = _first_profile_slice(trade_geometry)
    if df.empty:
        _save_empty_chart(out_path, "Trade Geometry")
        return
    df = df.copy()
    for col in ("reward_risk", "win_rate_pct", "expectancy_per_trade", "std_trade_pnl", "trades"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    finite = df[np.isfinite(df.get("reward_risk", np.nan)) & np.isfinite(df.get("win_rate_pct", np.nan))]

    fig, axes = plt.subplots(1, 2, figsize=(16.0, 7.2))
    _style_chart_figure(fig, f"Trade Return Geometry - {profile}")

    ax = axes[0]
    rr_curve = np.linspace(0.1, 5.0, 250)
    wr_curve = 100.0 / (1.0 + rr_curve)
    ax.fill_between(rr_curve, wr_curve, 100.0, color=CHART_GREEN, alpha=0.20, label="Positive EV zone")
    ax.fill_between(rr_curve, 0.0, wr_curve, color=CHART_RED, alpha=0.18, label="Negative EV zone")
    ax.plot(rr_curve, wr_curve, color=CHART_CYAN, linewidth=2.0, label="EV=0 breakeven")
    if not finite.empty:
        sizes = np.clip(finite.get("trades", pd.Series(40, index=finite.index)).fillna(40).to_numpy(dtype=float), 20, 280)
        colors = finite.get("edge_vs_breakeven_win_rate_pct", pd.Series(0.0, index=finite.index)).to_numpy(dtype=float)
        scatter = ax.scatter(
            finite["reward_risk"],
            finite["win_rate_pct"],
            c=colors,
            s=sizes,
            cmap="RdYlGn",
            edgecolor=CHART_BG,
            linewidth=0.7,
            alpha=0.92,
        )
        cbar = fig.colorbar(scatter, ax=ax, fraction=0.045, pad=0.03, label="Win rate edge vs EV=0")
        _style_chart_colorbar(cbar)
        for _, point in finite.head(12).iterrows():
            label = str(point.get("segment", ""))[:18]
            ax.annotate(
                label,
                (float(point["reward_risk"]), float(point["win_rate_pct"])),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=8,
                color=CHART_TEXT,
            )
    ax.set_xlim(0, max(5.0, float(finite["reward_risk"].max()) * 1.15 if not finite.empty else 5.0))
    ax.set_ylim(0, 100)
    ax.set_xlabel("Reward:risk")
    ax.set_ylabel("Win rate (%)")
    ax.set_title("Breakeven Curve And Strategy Segments", fontweight="bold")
    ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT, loc="upper right")
    _style_chart_axis(ax)

    ax = axes[1]
    finite_vol = df.dropna(subset=["std_trade_pnl", "expectancy_per_trade"])
    if not finite_vol.empty:
        sizes = np.clip(finite_vol.get("trades", pd.Series(40, index=finite_vol.index)).fillna(40).to_numpy(dtype=float), 20, 280)
        colors = finite_vol.get("reward_risk", pd.Series(1.0, index=finite_vol.index)).to_numpy(dtype=float)
        scatter = ax.scatter(
            finite_vol["std_trade_pnl"],
            finite_vol["expectancy_per_trade"],
            c=colors,
            s=sizes,
            cmap="viridis",
            edgecolor=CHART_BG,
            linewidth=0.7,
            alpha=0.9,
        )
        cbar = fig.colorbar(scatter, ax=ax, fraction=0.045, pad=0.03, label="Reward:risk")
        _style_chart_colorbar(cbar)
        for _, point in finite_vol.head(12).iterrows():
            label = str(point.get("segment", ""))[:18]
            ax.annotate(
                label,
                (float(point["std_trade_pnl"]), float(point["expectancy_per_trade"])),
                xytext=(5, 5),
                textcoords="offset points",
                fontsize=8,
                color=CHART_TEXT,
            )
    ax.axhline(0, color=CHART_MUTED, linewidth=1.0, linestyle="--")
    ax.set_xlabel("Std dev of trade PnL ($)")
    ax.set_ylabel("Expectancy per trade ($)")
    ax.set_title("Return Volatility Vs Expectancy", fontweight="bold")
    _style_chart_axis(ax)

    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out_path, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)


def _plot_funded_payout_chart(
    risk_geometry_surface: pd.DataFrame,
    sizing_surface: pd.DataFrame,
    out_path: Path,
) -> None:
    plt, FuncFormatter = _chart_modules()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile, risk_df = _first_profile_slice(risk_geometry_surface)
    _, sizing_df = _first_profile_slice(sizing_surface)

    if risk_df.empty and sizing_df.empty:
        _save_empty_chart(out_path, "Funded Payout Surface")
        return

    fig, axes = plt.subplots(1, 2, figsize=(16.0, 7.5))
    _style_chart_figure(fig, f"Funded Phase Payout Geometry - {profile}")

    payout_pivot = _metric_pivot(
        risk_df,
        index="risk_fraction_of_drawdown",
        columns="reward_risk",
        values="avg_net_payout_after_split",
    )
    _annotated_heatmap(
        axes[0],
        payout_pivot,
        title="Avg Funded Net Payout By Risk Geometry",
        xlabel="Reward:risk",
        ylabel="Risk / drawdown",
        cbar_label="Avg funded payout",
        cmap="YlGn",
        money=True,
        pct_axes=True,
    )

    ax = axes[1]
    if not sizing_df.empty and "tested_pnl_multiplier" in sizing_df.columns:
        sizing_df = sizing_df.copy()
        sizing_df["tested_pnl_multiplier"] = pd.to_numeric(sizing_df["tested_pnl_multiplier"], errors="coerce")
        sizing_df = sizing_df.sort_values("tested_pnl_multiplier")
        x = sizing_df["tested_pnl_multiplier"].to_numpy(dtype=float)
        payout = pd.to_numeric(sizing_df.get("avg_net_payout_after_split"), errors="coerce").to_numpy(dtype=float)
        ev = pd.to_numeric(sizing_df.get("expected_net_payout_per_eval_attempt"), errors="coerce").to_numpy(dtype=float)
        ax.plot(x, payout, marker="o", color=CHART_GREEN, linewidth=2.2, label="Avg funded payout")
        ax.plot(x, ev, marker="s", color=CHART_BLUE, linewidth=2.0, label="Expected net / eval")
        ax.axhline(0, color=CHART_MUTED, linewidth=0.8)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value:,.0f}"))
        for xi, yi in zip(x, payout):
            if np.isfinite(yi):
                ax.text(xi, yi, f"${yi:,.0f}", ha="center", va="bottom", fontsize=8, color=CHART_TEXT)
        ax.set_xlabel("PnL multiplier")
        ax.set_ylabel("$")
        ax.set_title("Funded Payout Vs Size", fontweight="bold")
        ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT)
        _style_chart_axis(ax)
    else:
        _style_chart_axis(ax, grid=False)
        ax.text(0.5, 0.5, "No sizing data", ha="center", va="center", color=CHART_MUTED, transform=ax.transAxes)
        ax.set_axis_off()

    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out_path, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)


def _style_dark_axis(ax: Any) -> None:
    _style_chart_axis(ax)


def _money_formatter(value: float, _: Any) -> str:
    return f"${value:,.0f}"


def _coerce_finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if np.isfinite(number) else default


def _plot_strategy_equity_chart(
    trades: pd.DataFrame,
    profiles: list[dict[str, Any]],
    out_path: Path,
) -> None:
    plt, FuncFormatter = _chart_modules()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not profiles:
        profiles = [DEFAULT_PROFILE]
    profile = _normalize_profile(profiles[0])
    path = _historical_trade_path(trades, profile)
    if path.empty:
        _save_empty_chart(out_path, "Strategy Equity Curve")
        return

    x_time = pd.to_datetime(path["time"], errors="coerce")
    use_time = x_time.notna().any()
    x = x_time if use_time else path["trade_number"]
    pnl = pd.to_numeric(path["pnl"], errors="coerce").fillna(0.0)
    equity = pd.to_numeric(path["equity"], errors="coerce").fillna(float(profile["account_size"]))
    drawdown = pd.to_numeric(path["drawdown"], errors="coerce").fillna(0.0)
    total_pnl = float(pnl.sum())
    max_dd = abs(float(drawdown.min()))
    win_rate = float((pnl > 0).mean() * 100.0) if len(pnl) else 0.0

    fig, axes = plt.subplots(
        3,
        1,
        figsize=(16.5, 13.5),
        gridspec_kw={"height_ratios": [4.6, 1.8, 1.8]},
    )
    fig.patch.set_facecolor(CHART_BG)
    fig.suptitle(
        f"{profile['name']} - Historical Equity Curve",
        color=CHART_TEXT,
        fontsize=21,
        fontweight="bold",
        y=0.98,
    )

    ax = axes[0]
    ax.plot(x, equity, color=CHART_BLUE, linewidth=1.7, label="Equity")
    ax.fill_between(x, float(profile["account_size"]), equity, where=equity >= float(profile["account_size"]), color="#1f7a45", alpha=0.28)
    ax.axhline(float(profile["account_size"]), color="#7c8798", linestyle="--", linewidth=1.1, label=f"Start ${profile['account_size']:,.0f}")
    ax.yaxis.set_major_formatter(FuncFormatter(_money_formatter))
    ax.set_ylabel("Equity ($)")
    ax.set_title(f"Total PnL: ${total_pnl:,.0f} | Final: ${equity.iloc[-1]:,.0f}", fontsize=16)
    ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT)
    _style_dark_axis(ax)

    ax = axes[1]
    ax.plot(x, drawdown, color=CHART_RED, linewidth=1.25)
    ax.fill_between(x, drawdown, 0, where=drawdown <= 0, color="#b43a35", alpha=0.55)
    ax.yaxis.set_major_formatter(FuncFormatter(_money_formatter))
    ax.set_ylabel("Drawdown ($)")
    ax.set_title(f"Max Drawdown: ${max_dd:,.0f} ({max_dd / float(profile['account_size']) * 100.0:.1f}%)", fontsize=14)
    _style_dark_axis(ax)

    ax = axes[2]
    colors = np.where(pnl.to_numpy(dtype=float) >= 0, CHART_GREEN, CHART_RED)
    ax.bar(path["trade_number"], pnl, color=colors, width=0.9, alpha=0.88)
    ax.axhline(0, color="#7c8798", linewidth=0.9)
    ax.yaxis.set_major_formatter(FuncFormatter(_money_formatter))
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Trade PnL ($)")
    ax.set_title(f"{len(path):,} Trades | WR: {win_rate:.1f}%", fontsize=14)
    _style_dark_axis(ax)

    fig.tight_layout(rect=(0, 0, 1, 0.955))
    fig.savefig(out_path, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)


def _plot_random_walk_chart(
    random_walk_summary: pd.DataFrame,
    random_walk_samples: pd.DataFrame,
    out_path: Path,
) -> None:
    plt, _ = _chart_modules()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile, samples = _first_profile_slice(random_walk_samples)
    _, summary = _first_profile_slice(random_walk_summary)
    if samples.empty or summary.empty:
        _save_empty_chart(out_path, "Random Walk Sign-Flip Test")
        return
    row = summary.iloc[0]

    fig, axes = plt.subplots(1, 2, figsize=(16.2, 6.2))
    fig.patch.set_facecolor(CHART_BG)
    fig.suptitle(
        f"{profile} - Random Walk Sign-Flip Test ({int(row['n_permutations']):,} permutations)",
        color=CHART_TEXT,
        fontsize=20,
        fontweight="bold",
        y=0.98,
    )
    panels = [
        (
            axes[0],
            "total_pnl",
            float(row["real_total_pnl"]),
            float(row["random_p95_total_pnl"]),
            float(row["pnl_p_value"]),
            "PnL",
            "Total PnL ($)",
        ),
        (
            axes[1],
            "trade_sharpe",
            float(row["real_trade_sharpe"]),
            float(row["random_p95_trade_sharpe"]),
            float(row["sharpe_p_value"]),
            "Sharpe",
            "Trade Sharpe",
        ),
    ]
    for ax, col, real_value, p95, p_value, title, xlabel in panels:
        vals = pd.to_numeric(samples[col], errors="coerce").dropna()
        ax.hist(vals, bins=min(70, max(15, int(np.sqrt(len(vals)) * 2))), color="#7c8798", alpha=0.75)
        ax.axvline(0, color=CHART_RED, linestyle="--", linewidth=1.2, alpha=0.9, label="Zero")
        ax.axvline(p95, color=CHART_YELLOW, linestyle=":", linewidth=1.6, label=f"95th pct: {p95:,.1f}")
        ax.axvline(real_value, color=CHART_GREEN, linewidth=2.4, label=f"Real: {real_value:,.1f}")
        ax.set_title(f"{title}: p-value = {p_value:.6f} {'PASS' if p_value <= 0.05 else 'FAIL'}", fontsize=15)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Count")
        ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT)
        _style_dark_axis(ax)

    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out_path, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)


def _plot_monte_carlo_chart(
    summary: pd.DataFrame,
    simulations: pd.DataFrame,
    daily_paths_by_profile: dict[str, pd.DataFrame] | None,
    profiles: list[dict[str, Any]],
    out_path: Path,
    *,
    seed: int,
) -> None:
    plt, FuncFormatter = _chart_modules()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile_name, sim = _first_profile_slice(simulations)
    _, summary_slice = _first_profile_slice(summary)
    if sim.empty or summary_slice.empty:
        _save_empty_chart(out_path, "Monte Carlo Prop-Firm Simulation")
        return
    profile_rules = {_normalize_profile(profile)["name"]: _normalize_profile(profile) for profile in profiles}
    profile = profile_rules.get(profile_name, _normalize_profile({}))
    daily_paths = (daily_paths_by_profile or {}).get(profile_name, pd.DataFrame())
    path_sample = (
        _sample_eval_equity_paths(daily_paths, profile, n_paths=250, seed=seed + 8_000_003)
        if daily_paths is not None and not daily_paths.empty
        else pd.DataFrame()
    )
    row = summary_slice.iloc[0]
    target = float(profile["account_size"]) + float(profile["profit_target"])
    final_equity = pd.to_numeric(sim["final_equity"], errors="coerce").dropna()
    passed = sim["status"].astype(str).eq("pass")
    pass_days = pd.to_numeric(sim.loc[passed, "days"], errors="coerce").dropna()

    fig, axes = plt.subplots(2, 2, figsize=(16.2, 12.0))
    fig.patch.set_facecolor(CHART_BG)
    fig.suptitle(
        f"{profile_name} - Monte Carlo Evaluation Simulation ({len(sim):,} paths)",
        color=CHART_TEXT,
        fontsize=20,
        fontweight="bold",
        y=0.98,
    )

    ax = axes[0, 0]
    if not path_sample.empty:
        for _, path_group in path_sample.groupby("sim_id", sort=False):
            status = str(path_group["status"].iloc[-1])
            color = CHART_GREEN if status == "pass" else CHART_RED if status == "fail" else CHART_MUTED
            ax.plot(path_group["day"], path_group["equity"], color=color, alpha=0.07, linewidth=0.8)
    ax.axhline(target, color=CHART_GREEN, linestyle="--", linewidth=1.4, label=f"Target ${target:,.0f}")
    ax.axhline(float(profile["account_size"]), color="#7c8798", linestyle=":", linewidth=1.1, label=f"Start ${profile['account_size']:,.0f}")
    ax.set_title("Sample Evaluation Paths", fontsize=15)
    ax.set_xlabel("Day")
    ax.set_ylabel("Equity ($)")
    ax.yaxis.set_major_formatter(FuncFormatter(_money_formatter))
    ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT)
    _style_dark_axis(ax)

    ax = axes[0, 1]
    ax.hist(final_equity, bins=min(70, max(15, int(np.sqrt(len(final_equity)) * 2))), color=CHART_BLUE, alpha=0.76)
    ax.axvline(target, color=CHART_GREEN, linestyle="--", linewidth=1.5, label="Target")
    if not final_equity.empty:
        ax.axvline(final_equity.median(), color=CHART_CYAN, linewidth=1.7, label=f"Median ${final_equity.median():,.0f}")
    ax.set_title("Final Equity Distribution", fontsize=15)
    ax.set_xlabel("Final equity ($)")
    ax.set_ylabel("Count")
    ax.xaxis.set_major_formatter(FuncFormatter(_money_formatter))
    ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT)
    _style_dark_axis(ax)

    ax = axes[1, 0]
    if not pass_days.empty:
        ax.hist(pass_days, bins=min(35, max(8, int(np.sqrt(len(pass_days)) * 2))), color=CHART_GREEN, alpha=0.82)
        ax.axvline(pass_days.median(), color=CHART_CYAN, linewidth=1.7, label=f"Median: {pass_days.median():.0f} days")
        ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT)
        ax.set_title(f"Avg: {pass_days.mean():.0f} days | Median: {pass_days.median():.0f} days", fontsize=15)
    else:
        ax.set_title("Days To Pass", fontsize=15)
    ax.set_xlabel("Days to pass")
    ax.set_ylabel("Count")
    _style_dark_axis(ax)

    ax = axes[1, 1]
    drawdowns = pd.to_numeric(sim.get("max_drawdown_dollars"), errors="coerce").dropna()
    if not drawdowns.empty:
        ax.hist(drawdowns, bins=min(45, max(10, int(np.sqrt(len(drawdowns)) * 2))), color=CHART_RED, alpha=0.76)
        ax.axvline(float(profile["max_drawdown"]), color=CHART_YELLOW, linestyle="--", linewidth=1.5, label="Eval max DD")
        ax.axvline(drawdowns.median(), color=CHART_CYAN, linewidth=1.7, label=f"Median ${drawdowns.median():,.0f}")
        ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT)
    ax.xaxis.set_major_formatter(FuncFormatter(_money_formatter))
    ax.set_title("Drawdown Usage Distribution", fontsize=15)
    ax.set_xlabel("Max drawdown ($)")
    ax.set_ylabel("Count")
    _style_dark_axis(ax)

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_path, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)


def _plot_payout_analysis_chart(
    summary: pd.DataFrame,
    funded_simulations: pd.DataFrame,
    attempt_curve: pd.DataFrame,
    out_path: Path,
) -> None:
    plt, FuncFormatter = _chart_modules()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    profile, row_df = _first_profile_slice(summary)
    _, funded = _first_profile_slice(funded_simulations)
    _, attempts = _first_profile_slice(attempt_curve)
    if row_df.empty:
        _save_empty_chart(out_path, "Eval + Payout Analysis")
        return
    row = row_df.iloc[0]
    payout_values = (
        pd.to_numeric(funded.loc[pd.to_numeric(funded.get("net_payout", 0), errors="coerce") > 0, "net_payout"], errors="coerce")
        if not funded.empty and "net_payout" in funded.columns
        else pd.Series(dtype=float)
    )
    first_payout_days = (
        pd.to_numeric(funded.loc[pd.to_numeric(funded.get("first_payout_day", np.nan), errors="coerce").notna(), "first_payout_day"], errors="coerce")
        if not funded.empty and "first_payout_day" in funded.columns
        else pd.Series(dtype=float)
    ).dropna()

    fig, axes = plt.subplots(2, 2, figsize=(16.2, 12.0))
    fig.patch.set_facecolor(CHART_BG)
    fig.suptitle(
        f"{profile} - Payout And Attempt Economics",
        color=CHART_TEXT,
        fontsize=20,
        fontweight="bold",
        y=0.98,
    )

    ax = axes[0, 0]
    if not payout_values.empty:
        ax.hist(payout_values, bins=min(55, max(10, int(np.sqrt(len(payout_values)) * 2))), color=CHART_GREEN, alpha=0.8)
        ax.axvline(payout_values.median(), color=CHART_CYAN, linewidth=1.8, label=f"Median: ${payout_values.median():,.0f}")
        min_payout = float(row.get("minimum_payout", 0.0) or 0.0)
        if min_payout > 0:
            ax.axvline(min_payout, color=CHART_YELLOW, linestyle="--", linewidth=1.5, label=f"Min payout ${min_payout:,.0f}")
        ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT)
    ax.xaxis.set_major_formatter(FuncFormatter(_money_formatter))
    ax.set_title(
        f"Payout Distribution | Avg: ${float(payout_values.mean()) if not payout_values.empty else 0:,.0f}",
        fontsize=15,
    )
    ax.set_xlabel("Payout amount ($)")
    ax.set_ylabel("Count")
    _style_dark_axis(ax)

    ax = axes[0, 1]
    if not attempts.empty:
        attempt_work = attempts.loc[:, ["attempts", "expected_value"]].copy()
        attempt_work["attempts"] = pd.to_numeric(attempt_work["attempts"], errors="coerce")
        attempt_work["expected_value"] = (
            pd.to_numeric(attempt_work["expected_value"], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
        )
        attempt_work = attempt_work.dropna(subset=["attempts", "expected_value"])
        if not attempt_work.empty:
            x = attempt_work["attempts"]
            y = attempt_work["expected_value"]
            ax.bar(x, y, color=np.where(y >= 0, CHART_GREEN, CHART_RED), alpha=0.88)
            ax.axhline(0, color="#7c8798", linewidth=0.9)
            ax.yaxis.set_major_formatter(FuncFormatter(_money_formatter))
            ev = (
                float(attempt_work.loc[attempt_work["attempts"].eq(1), "expected_value"].iloc[0])
                if attempt_work["attempts"].eq(1).any()
                else float(y.iloc[0])
            )
            positive = attempt_work.loc[attempt_work["expected_value"] >= 0, "attempts"]
            breakeven = int(positive.iloc[0]) if not positive.empty else np.nan
            ax.set_title(f"EV per Attempt: ${ev:,.0f} | Break-even: {breakeven} attempts", fontsize=15)
        else:
            ax.set_title("Expected Value By Attempts", fontsize=15)
    else:
        ax.set_title("Expected Value By Attempts", fontsize=15)
    ax.set_xlabel("# Attempts")
    ax.set_ylabel("Expected value ($)")
    _style_dark_axis(ax)

    ax = axes[1, 0]
    if not first_payout_days.empty:
        ax.hist(first_payout_days, bins=min(35, max(8, int(np.sqrt(len(first_payout_days)) * 2))), color=CHART_BLUE, alpha=0.78)
        ax.axvline(first_payout_days.median(), color=CHART_CYAN, linewidth=1.7, label=f"Median {first_payout_days.median():.0f}d")
        ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT)
    ax.set_title("Days To First Funded Payout", fontsize=15)
    ax.set_xlabel("Funded trading days")
    ax.set_ylabel("Count")
    _style_dark_axis(ax)

    ax = axes[1, 1]
    ax.set_axis_off()
    table_rows = [
        ("Avg Payout (when achieved)", f"${float(payout_values.mean()) if not payout_values.empty else 0:,.0f}"),
        ("Median Payout", f"${float(payout_values.median()) if not payout_values.empty else 0:,.0f}"),
        ("Challenge Cost", f"${_coerce_finite(row.get('eval_cost')):,.0f}"),
        ("EV per Eval Attempt", f"${_coerce_finite(row.get('expected_net_payout_per_eval_attempt')):,.0f}"),
        ("Expected Cost To First Payout", f"${_coerce_finite(row.get('expected_eval_cost_to_first_payout')):,.0f}"),
        ("Avg Days To First Payout", f"{_coerce_finite(row.get('avg_days_to_first_payout')):.1f}"),
    ]
    table = ax.table(
        cellText=table_rows,
        colLabels=["Metric", "Value"],
        cellLoc="center",
        colLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.0, 1.9)
    _style_chart_table(table)
    ax.set_title("Payout Economics Summary", color=CHART_TEXT, fontsize=15, pad=16)

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(out_path, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)


def _plot_overview_dashboard(
    summary: pd.DataFrame,
    simulations: pd.DataFrame,
    funded_simulations: pd.DataFrame,
    strategy_metrics: pd.DataFrame,
    trades: pd.DataFrame,
    profiles: list[dict[str, Any]],
    out_path: Path,
) -> None:
    plt, FuncFormatter = _chart_modules()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not profiles:
        profiles = [DEFAULT_PROFILE]
    profile = _normalize_profile(profiles[0])
    profile_name = profile["name"]
    path = _historical_trade_path(trades, profile)
    _, summary_slice = _first_profile_slice(summary)
    _, funded = _first_profile_slice(funded_simulations)
    _, metrics_slice = _first_profile_slice(strategy_metrics)
    if summary_slice.empty:
        _save_empty_chart(out_path, "Prop Firm Overview")
        return
    row = summary_slice.iloc[0]
    metric_row = metrics_slice.iloc[0] if not metrics_slice.empty else pd.Series(dtype=object)

    fig = plt.figure(figsize=(18.0, 12.5))
    fig.patch.set_facecolor(CHART_BG)
    gs = fig.add_gridspec(3, 3, height_ratios=[2.5, 2.0, 1.7], width_ratios=[2.1, 1.0, 1.0])
    fig.suptitle(f"PROP FIRM OPERATING OVERVIEW - {profile_name}", color="#f2f5f9", fontsize=20, fontweight="bold", y=0.98)

    ax = fig.add_subplot(gs[0, 0])
    if not path.empty:
        x = path["trade_number"]
        equity = pd.to_numeric(path["equity"], errors="coerce")
        ax.plot(x, equity, color="#00e083", linewidth=1.4)
        ax.fill_between(x, float(profile["account_size"]), equity, color="#00e083", alpha=0.12)
    ax.set_title("Equity Curve (per trade)", fontsize=12)
    ax.set_ylabel("Equity ($)")
    ax.yaxis.set_major_formatter(FuncFormatter(_money_formatter))
    _style_dark_axis(ax)

    ax = fig.add_subplot(gs[0, 1])
    if not path.empty:
        daily = pd.to_numeric(path["pnl"], errors="coerce").groupby(path["date"], sort=True).sum()
        wins = daily[daily > 0]
        losses = daily[daily < 0]
        if not wins.empty:
            ax.hist(wins, bins=25, color=CHART_GREEN, alpha=0.75, label=f"Win ({len(wins)})")
        if not losses.empty:
            ax.hist(losses, bins=25, color=CHART_RED, alpha=0.75, label=f"Loss ({len(losses)})")
        ax.axvline(0, color=CHART_MUTED, linewidth=0.8)
        ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT, fontsize=8)
    ax.set_title("Daily PnL Distribution", fontsize=12)
    _style_dark_axis(ax)

    ax = fig.add_subplot(gs[0, 2])
    if not path.empty:
        drawdown = pd.to_numeric(path["drawdown"], errors="coerce")
        ax.plot(path["trade_number"], drawdown, color=CHART_RED, linewidth=0.9)
        ax.fill_between(path["trade_number"], drawdown, 0, where=drawdown <= 0, color=CHART_RED, alpha=0.28)
    ax.yaxis.set_major_formatter(FuncFormatter(_money_formatter))
    ax.set_title("Drawdown Curve", fontsize=12)
    _style_dark_axis(ax)

    ax = fig.add_subplot(gs[1, 0])
    table_df = pd.DataFrame([{
        "Account": f"${float(row.get('account_size', 0)) / 1000:.0f}K",
        "Target": f"${float(row.get('profit_target', 0)):,.0f}",
        "Max DD": f"${float(row.get('max_drawdown', 0)):,.0f}",
        "Daily Loss": f"${float(row.get('daily_loss_limit', 0)):,.0f}",
        "Trading Days": f"{int(float(row.get('min_trading_days', 0)))}-{int(float(row.get('max_trading_days', 0)))}",
        "DD Mode": str(row.get("drawdown_mode", "")),
        "Check": str(row.get("drawdown_check", "")),
        "Multiplier": f"{float(row.get('pnl_multiplier', 1.0)):.2f}x",
        "Split": f"{float(row.get('profit_split_pct', 100.0)):.0f}%",
    }])
    ax.set_axis_off()
    table = ax.table(
        cellText=table_df.values,
        colLabels=table_df.columns,
        cellLoc="center",
        colLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1.0, 1.6)
    _style_chart_table(table, font_color="#f2f5f9")
    ax.set_title("Account Rules", color=CHART_TEXT, fontsize=12, pad=10)

    ax = fig.add_subplot(gs[1, 1])
    _style_chart_axis(ax, grid=False)
    ax.set_axis_off()
    ax.set_title("Strategy Quality Snapshot", fontsize=12, pad=10)
    quality_rows = [
        ("Win rate", f"{float(metric_row.get('win_rate_pct', 0)):.1f}%", "higher"),
        ("Profit factor", f"{float(metric_row.get('profit_factor', 0)):.2f}", ">= 1.10"),
        ("Reward:risk", f"{float(metric_row.get('reward_risk', 0)):.2f}", "context"),
        ("Avg win", f"${float(metric_row.get('avg_win', 0)):,.0f}", "gross"),
        ("Avg loss", f"${float(metric_row.get('avg_loss', 0)):,.0f}", "gross"),
    ]
    table = ax.table(
        cellText=quality_rows,
        colLabels=["Metric", "Value", "Reference"],
        cellLoc="left",
        loc="center",
        colWidths=[0.42, 0.26, 0.32],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1.0, 1.45)
    _style_chart_table(table)
    for row_idx in range(1, len(quality_rows) + 1):
        table[(row_idx, 1)].get_text().set_color(CHART_CYAN)
        table[(row_idx, 1)].get_text().set_fontweight("bold")

    ax = fig.add_subplot(gs[1, 2])
    payout_values = (
        pd.to_numeric(funded.loc[pd.to_numeric(funded.get("net_payout", 0), errors="coerce") > 0, "net_payout"], errors="coerce")
        if not funded.empty and "net_payout" in funded.columns
        else pd.Series(dtype=float)
    )
    if not payout_values.empty:
        ax.hist(payout_values, bins=30, color=CHART_GREEN, alpha=0.75)
        ax.axvline(payout_values.mean(), color=CHART_CYAN, linewidth=1.6, label=f"Avg ${payout_values.mean():,.0f}")
        ax.legend(facecolor=CHART_PANEL, edgecolor=CHART_SPINE, labelcolor=CHART_TEXT, fontsize=8)
    ax.xaxis.set_major_formatter(FuncFormatter(_money_formatter))
    ax.set_title("Payout Distribution", fontsize=12)
    _style_dark_axis(ax)

    ax = fig.add_subplot(gs[2, :2])
    if not path.empty:
        month = pd.to_datetime(path["date"], errors="coerce").dt.to_period("M").dt.to_timestamp()
        monthly = pd.to_numeric(path["pnl"], errors="coerce").groupby(month, sort=True).sum().dropna()
        if not monthly.empty:
            colors = np.where(monthly.to_numpy(dtype=float) >= 0, CHART_GREEN, CHART_RED)
            ax.bar(monthly.index, monthly.to_numpy(dtype=float), color=colors, width=20, alpha=0.82)
            ax.axhline(0, color=CHART_MUTED, linewidth=0.9)
            ax.yaxis.set_major_formatter(FuncFormatter(_money_formatter))
    ax.set_title("Historical Monthly PnL", fontsize=12)
    ax.set_xlabel("Month")
    ax.set_ylabel("PnL ($)")
    _style_dark_axis(ax)

    ax = fig.add_subplot(gs[2, 2])
    ax.set_axis_off()
    key_lines = [
        "KEY METRICS",
        "============================",
        f"Win Rate:        {float(metric_row.get('win_rate_pct', 0)):.1f}%",
        f"Reward:Risk:     {float(metric_row.get('reward_risk', 0)):.2f}",
        f"Profit Factor:   {float(metric_row.get('profit_factor', 0)):.2f}",
        f"Avg Win:         ${float(metric_row.get('avg_win', 0)):,.0f}",
        f"Avg Loss:        ${float(metric_row.get('avg_loss', 0)):,.0f}",
        f"Trades/Week:     {float(metric_row.get('trades_per_week', 0)):.1f}",
        "============================",
        f"Backtest PnL:    ${float(metric_row.get('total_pnl', 0)):,.0f}",
        f"Annualized:      ${float(metric_row.get('annualized_pnl', 0)):,.0f}",
        f"Avg Daily PnL:   ${float(metric_row.get('avg_daily_pnl', 0)):,.0f}",
        f"Max Drawdown:    ${float(metric_row.get('max_drawdown_dollars', 0)):,.0f}",
        f"Max Daily Loss:  ${float(metric_row.get('max_daily_loss', 0)):,.0f}",
        "============================",
        f"DD % of Acct:    {float(metric_row.get('max_drawdown_pct_of_account', 0)):.1f}%",
        f"Trading Days:    {int(float(metric_row.get('active_trading_days', 0)))}",
    ]
    ax.text(
        0.02,
        0.98,
        "\n".join(key_lines),
        transform=ax.transAxes,
        va="top",
        ha="left",
        family="monospace",
        fontsize=9,
        color="#00e083",
        bbox={"boxstyle": "round,pad=0.5", "facecolor": "#090d13", "edgecolor": "#243044", "alpha": 0.95},
    )

    fig.tight_layout(rect=(0, 0, 1, 0.955))
    fig.savefig(out_path, dpi=170, facecolor=fig.get_facecolor())
    plt.close(fig)


def write_prop_firm_charts(
    *,
    summary: pd.DataFrame,
    simulations: pd.DataFrame,
    funded_simulations: pd.DataFrame,
    risk_geometry_surface: pd.DataFrame,
    sizing_surface: pd.DataFrame,
    daily_rules_surface: pd.DataFrame,
    trade_geometry: pd.DataFrame,
    strategy_metrics: pd.DataFrame | None = None,
    random_walk_summary: pd.DataFrame | None = None,
    random_walk_samples: pd.DataFrame | None = None,
    attempt_curve: pd.DataFrame | None = None,
    trades: pd.DataFrame | None = None,
    daily_paths_by_profile: dict[str, pd.DataFrame] | None = None,
    profiles: list[dict[str, Any]] | None = None,
    out_dir: Path | str,
    artifact_name: str = "prop_firm",
    seed: int = 17,
) -> dict[str, Path]:
    charts_dir = Path(out_dir) / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    strategy_metrics = strategy_metrics if strategy_metrics is not None else pd.DataFrame()
    random_walk_summary = random_walk_summary if random_walk_summary is not None else pd.DataFrame()
    random_walk_samples = random_walk_samples if random_walk_samples is not None else pd.DataFrame()
    attempt_curve = attempt_curve if attempt_curve is not None else pd.DataFrame()
    trades = trades if trades is not None else pd.DataFrame()
    profiles = profiles or [DEFAULT_PROFILE]
    chart_paths = {
        "dashboard": charts_dir / f"{artifact_name}_dashboard.png",
        "overview": charts_dir / f"{artifact_name}_overview_dashboard.png",
        "strategy_equity": charts_dir / f"{artifact_name}_strategy_equity.png",
        "monte_carlo": charts_dir / f"{artifact_name}_monte_carlo.png",
        "random_walk": charts_dir / f"{artifact_name}_random_walk_sign_flip.png",
        "payout_analysis": charts_dir / f"{artifact_name}_payout_analysis.png",
        "risk_geometry": charts_dir / f"{artifact_name}_risk_geometry_surface.png",
        "sizing": charts_dir / f"{artifact_name}_sizing_surface.png",
        "daily_rules": charts_dir / f"{artifact_name}_daily_rules_surface.png",
        "trade_geometry": charts_dir / f"{artifact_name}_trade_geometry.png",
        "funded_payout": charts_dir / f"{artifact_name}_funded_payout_surface.png",
    }
    plotters = [
        ("dashboard", lambda path: _plot_prop_firm_dashboard(summary, simulations, funded_simulations, path)),
        ("overview", lambda path: _plot_overview_dashboard(summary, simulations, funded_simulations, strategy_metrics, trades, profiles, path)),
        ("strategy_equity", lambda path: _plot_strategy_equity_chart(trades, profiles, path)),
        ("monte_carlo", lambda path: _plot_monte_carlo_chart(summary, simulations, daily_paths_by_profile, profiles, path, seed=seed)),
        ("random_walk", lambda path: _plot_random_walk_chart(random_walk_summary, random_walk_samples, path)),
        ("payout_analysis", lambda path: _plot_payout_analysis_chart(summary, funded_simulations, attempt_curve, path)),
        ("risk_geometry", lambda path: _plot_risk_geometry_chart(risk_geometry_surface, path)),
        ("sizing", lambda path: _plot_sizing_chart(sizing_surface, path)),
        ("daily_rules", lambda path: _plot_daily_rules_chart(daily_rules_surface, path)),
        ("trade_geometry", lambda path: _plot_trade_geometry_chart(trade_geometry, path)),
        ("funded_payout", lambda path: _plot_funded_payout_chart(risk_geometry_surface, sizing_surface, path)),
    ]
    for name, plotter in plotters:
        path = chart_paths[name]
        try:
            plotter(path)
        except Exception as exc:  # pragma: no cover - defensive chart fallback
            _save_empty_chart(path, name.replace("_", " ").title(), f"Chart rendering failed: {exc}")
    return chart_paths


def _write_markdown_report(path: Path, summary: pd.DataFrame, chart_paths: dict[str, Path] | None = None) -> None:
    lines = [
        "# Prop Firm Evaluation Report",
        "",
        "This report uses a configurable, generic prop-firm rule model. It samples calendar-day paths that start on a historical active trading day, then includes zero-PnL no-trade days after that start. When timestamped trades are available, daily-loss and drawdown checks use each sampled day's worst intraday cumulative trade PnL, including trade MAE/MFE when present.",
        "",
    ]
    if summary.empty:
        lines.append("No prop-firm statistics were generated.")
    else:
        sample_scope = str(summary["sample_scope"].iloc[0]) if "sample_scope" in summary.columns else "unknown"
        evidence_grade = str(summary["evidence_grade"].iloc[0]) if "evidence_grade" in summary.columns else "unknown"
        if sample_scope == "development_in_sample":
            lines.extend(
                [
                    "**Evidence warning:** this is an in-sample development bootstrap. Pass rates and payout EV are for hypothesis generation only; they are not approval, lockbox, or forward evidence.",
                    "",
                ]
            )
        else:
            lines.extend([f"Evidence scope: `{sample_scope}` / `{evidence_grade}`.", ""])
        display_cols = [
            "sample_scope",
            "evidence_grade",
            "profile",
            "pass_probability_pct",
            "expected_eval_cost_to_pass",
            "probability_eval_to_first_payout_pct",
            "expected_eval_cost_to_first_payout",
            "avg_net_payout_after_split",
            "expected_net_payout_per_eval_attempt",
            "median_days_to_pass",
            "median_trading_days_to_pass",
            "calendar_history_days",
            "active_history_days",
            "historical_active_day_pct",
            "max_drawdown_fail_probability_pct",
            "consistency_block_probability_pct",
        ]
        lines.append("## Summary")
        lines.append("")
        lines.append(summary.loc[:, [c for c in display_cols if c in summary.columns]].to_string(index=False))
        lines.append("")
        lines.append("## Assumptions")
        lines.append("")
        for _, row in summary.iterrows():
            lines.append(
                f"- `{row['profile']}`: account=${row['account_size']:,.0f}, "
                f"target=${row['profit_target']:,.0f}, max drawdown=${row['max_drawdown']:,.0f}, "
                f"daily loss=${row['daily_loss_limit']:,.0f}, days={int(row['min_trading_days'])}-{int(row['max_trading_days'])}, "
                f"drawdown mode={row['drawdown_mode']}/{row.get('drawdown_check', 'intraday')}, "
                f"pnl multiplier={row.get('pnl_multiplier', 1.0):.2f}, eval cost=${row.get('eval_cost', 0.0):,.2f}, "
                f"profit split={row.get('profit_split_pct', 100.0):.0f}%."
            )
    if chart_paths:
        lines.extend(["", "## Charts", ""])
        labels = {
            "dashboard": "Dashboard",
            "overview": "Overview dashboard",
            "strategy_equity": "Strategy equity curve",
            "monte_carlo": "Monte Carlo simulation",
            "random_walk": "Random walk sign-flip test",
            "payout_analysis": "Eval and payout analysis",
            "risk_geometry": "Risk geometry surface",
            "sizing": "Sizing surface",
            "daily_rules": "Daily rules surface",
            "trade_geometry": "Trade geometry",
            "funded_payout": "Funded payout surface",
        }
        for key, chart_path in chart_paths.items():
            try:
                rel_path = chart_path.relative_to(path.parent)
            except ValueError:
                rel_path = chart_path
            lines.append(f"![{labels.get(key, key)}]({rel_path.as_posix()})")
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_prop_firm_report(
    trades: pd.DataFrame,
    *,
    out_dir: Path | str,
    artifact_name: str = "prop_firm",
    sample_scope: str = "development_in_sample",
    profiles: list[dict[str, Any]] | None = None,
    n_sims: int = 5000,
    seed: int = 17,
    enable_surfaces: bool | None = None,
    surface_n_sims: int | None = None,
) -> PropFirmReportPaths:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    daily_paths = _daily_paths_from_trades(trades)
    normalized_profiles = [_normalize_profile(profile) for profile in (profiles or [DEFAULT_PROFILE])]
    daily_paths_by_profile = {
        profile["name"]: _scale_daily_paths(daily_paths, float(profile["pnl_multiplier"]))
        for profile in normalized_profiles
    }

    simulation_frames = [
        _simulate_profile(
            daily_paths_by_profile[profile["name"]],
            profile,
            n_sims=n_sims,
            seed=seed + profile_idx * 10_007,
        )
        for profile_idx, profile in enumerate(normalized_profiles)
    ]
    simulations = pd.concat(simulation_frames, ignore_index=True) if simulation_frames else pd.DataFrame()
    funded_frames = [
        _simulate_funded_profile(
            daily_paths_by_profile[profile["name"]],
            profile,
            n_sims=n_sims,
            seed=seed + 500_009 + profile_idx * 10_007,
        )
        for profile_idx, profile in enumerate(normalized_profiles)
    ]
    funded_simulations = pd.concat(funded_frames, ignore_index=True) if funded_frames else pd.DataFrame()
    summary = _summarize_simulations(simulations, daily_paths_by_profile, funded_simulations)
    sample_scope = str(sample_scope or "development_in_sample")
    evidence_grade = "validation_candidate" if sample_scope in {"walkforward_oos", "lockbox"} else "research_only"
    if not summary.empty:
        summary.insert(1, "sample_scope", sample_scope)
        summary.insert(2, "evidence_grade", evidence_grade)
        summary.insert(
            3,
            "optimism_warning",
            (
                "in_sample_bootstrap_not_approval_evidence"
                if evidence_grade == "research_only"
                else ""
            ),
        )

    surface_enabled = (
        any(bool(profile.get("enable_surfaces", True)) for profile in normalized_profiles)
        if enable_surfaces is None
        else bool(enable_surfaces)
    )
    if surface_enabled:
        risk_frames = []
        sizing_frames = []
        daily_rule_frames = []
        for profile_idx, profile in enumerate(normalized_profiles):
            if not bool(profile.get("enable_surfaces", True)):
                continue
            surface_sims = int(surface_n_sims or profile.get("surface_n_sims", 1000))
            risk_frames.append(
                _risk_geometry_surface(
                    profile,
                    n_sims=surface_sims,
                    seed=seed + 1_000_003 + profile_idx * 10_007,
                )
            )
            sizing_frames.append(
                _sizing_surface(
                    daily_paths,
                    profile,
                    n_sims=surface_sims,
                    seed=seed + 2_000_003 + profile_idx * 10_007,
                )
            )
            daily_rule_frames.append(
                _daily_rules_surface(
                    trades,
                    profile,
                    n_sims=surface_sims,
                    seed=seed + 3_000_003 + profile_idx * 10_007,
                )
            )
        risk_geometry_surface = pd.concat(risk_frames, ignore_index=True) if risk_frames else pd.DataFrame()
        sizing_surface = pd.concat(sizing_frames, ignore_index=True) if sizing_frames else pd.DataFrame()
        daily_rules_surface = pd.concat(daily_rule_frames, ignore_index=True) if daily_rule_frames else pd.DataFrame()
        trade_geometry = _trade_geometry_rows(trades, normalized_profiles)
    else:
        risk_geometry_surface = pd.DataFrame()
        sizing_surface = pd.DataFrame()
        daily_rules_surface = pd.DataFrame()
        trade_geometry = pd.DataFrame()

    strategy_metrics = _strategy_metrics_rows(trades, normalized_profiles)
    random_walk_n = max(
        1,
        min(
            max(int(n_sims), 1),
            max(int(profile.get("random_walk_n_sims", 1)) for profile in normalized_profiles),
        ),
    )
    random_walk_summary, random_walk_samples = _random_walk_sign_flip(
        trades,
        normalized_profiles,
        n_sims=random_walk_n,
        seed=seed + 4_000_003,
    )
    attempt_curve = _attempt_curve(summary, funded_simulations, normalized_profiles)

    summary_csv = out_dir / f"{artifact_name}_summary.csv"
    simulations_csv = out_dir / f"{artifact_name}_simulations.csv"
    funded_simulations_csv = out_dir / f"{artifact_name}_funded_simulations.csv"
    risk_geometry_surface_csv = out_dir / f"{artifact_name}_risk_geometry_surface.csv"
    sizing_surface_csv = out_dir / f"{artifact_name}_sizing_surface.csv"
    daily_rules_surface_csv = out_dir / f"{artifact_name}_daily_rules_surface.csv"
    trade_geometry_csv = out_dir / f"{artifact_name}_trade_geometry.csv"
    strategy_metrics_csv = out_dir / f"{artifact_name}_strategy_metrics.csv"
    random_walk_csv = out_dir / f"{artifact_name}_random_walk.csv"
    random_walk_samples_csv = out_dir / f"{artifact_name}_random_walk_samples.csv"
    attempt_curve_csv = out_dir / f"{artifact_name}_attempt_curve.csv"
    report_md = out_dir / f"{artifact_name}_report.md"

    summary.to_csv(summary_csv, index=False)
    simulations.to_csv(simulations_csv, index=False)
    funded_simulations.to_csv(funded_simulations_csv, index=False)
    risk_geometry_surface.to_csv(risk_geometry_surface_csv, index=False)
    sizing_surface.to_csv(sizing_surface_csv, index=False)
    daily_rules_surface.to_csv(daily_rules_surface_csv, index=False)
    trade_geometry.to_csv(trade_geometry_csv, index=False)
    strategy_metrics.to_csv(strategy_metrics_csv, index=False)
    random_walk_summary.to_csv(random_walk_csv, index=False)
    random_walk_samples.to_csv(random_walk_samples_csv, index=False)
    attempt_curve.to_csv(attempt_curve_csv, index=False)
    chart_paths = write_prop_firm_charts(
        summary=summary,
        simulations=simulations,
        funded_simulations=funded_simulations,
        risk_geometry_surface=risk_geometry_surface,
        sizing_surface=sizing_surface,
        daily_rules_surface=daily_rules_surface,
        trade_geometry=trade_geometry,
        strategy_metrics=strategy_metrics,
        random_walk_summary=random_walk_summary,
        random_walk_samples=random_walk_samples,
        attempt_curve=attempt_curve,
        trades=trades,
        daily_paths_by_profile=daily_paths_by_profile,
        profiles=normalized_profiles,
        out_dir=out_dir,
        artifact_name=artifact_name,
        seed=seed,
    )
    _write_markdown_report(report_md, summary, chart_paths)

    return PropFirmReportPaths(
        summary_csv=summary_csv,
        simulations_csv=simulations_csv,
        funded_simulations_csv=funded_simulations_csv,
        risk_geometry_surface_csv=risk_geometry_surface_csv,
        sizing_surface_csv=sizing_surface_csv,
        daily_rules_surface_csv=daily_rules_surface_csv,
        trade_geometry_csv=trade_geometry_csv,
        strategy_metrics_csv=strategy_metrics_csv,
        random_walk_csv=random_walk_csv,
        random_walk_samples_csv=random_walk_samples_csv,
        attempt_curve_csv=attempt_curve_csv,
        charts_dir=out_dir / "charts",
        dashboard_png=chart_paths["dashboard"],
        overview_png=chart_paths["overview"],
        strategy_equity_png=chart_paths["strategy_equity"],
        monte_carlo_png=chart_paths["monte_carlo"],
        random_walk_png=chart_paths["random_walk"],
        payout_analysis_png=chart_paths["payout_analysis"],
        risk_geometry_png=chart_paths["risk_geometry"],
        sizing_png=chart_paths["sizing"],
        daily_rules_png=chart_paths["daily_rules"],
        trade_geometry_png=chart_paths["trade_geometry"],
        funded_payout_png=chart_paths["funded_payout"],
        report_md=report_md,
    )
