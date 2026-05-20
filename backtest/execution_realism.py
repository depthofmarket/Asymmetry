from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd


TARGET_EXIT_REASONS = frozenset({"profit_target", "hard_target"})
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


@dataclass(frozen=True)
class ExecutionRealismReportPaths:
    summary_csv: Path
    by_reason_csv: Path
    markdown_path: Path


@dataclass(frozen=True)
class FillAssumptionAuditPaths:
    summary_csv: Path
    by_trade_csv: Path
    by_reason_csv: Path
    markdown_path: Path


def build_execution_realism_summary(
    trades: pd.DataFrame,
    *,
    futures_specs: Mapping[str, Any],
    strategy_params: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = _prepare_trades(trades)
    specs = dict(futures_specs)
    params = dict(strategy_params or {})
    current_limit_slippage = float(specs.get("slippage_limit_points", specs.get("slippage_points", 0.0)))
    default_slippage = float(specs.get("slippage_points", current_limit_slippage))
    stop_slippage = float(specs.get("slippage_stop_points", default_slippage))

    scenarios = [
        {
            "scenario": "current",
            "target_slippage_points": current_limit_slippage,
            "notes": "Saved trade log PnL; target exits keep current configured limit slippage.",
        },
        {
            "scenario": "target_default_slippage",
            "target_slippage_points": default_slippage,
            "notes": "Target exits pay the default slippage instead of the optimistic limit-fill slippage.",
        },
        {
            "scenario": "target_stop_like_slippage",
            "target_slippage_points": stop_slippage,
            "notes": "Target exits pay stop-like slippage; useful as a harsh fill-realism bound.",
        },
    ]

    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        scenario_trades = _apply_target_slippage_scenario(
            work,
            current_target_slippage=current_limit_slippage,
            scenario_target_slippage=float(scenario["target_slippage_points"]),
            contract_value=float(specs.get("contract_value", 20.0)),
        )
        rows.append(
            {
                "scenario": scenario["scenario"],
                "target_fill_mode": str(params.get("target_fill_mode", "touch")),
                "target_fill_trade_through_ticks": params.get("target_fill_trade_through_ticks", 0),
                "target_fill_trade_through_points": params.get("target_fill_trade_through_points"),
                "target_slippage_points": float(scenario["target_slippage_points"]),
                "total_trades": int(len(scenario_trades)),
                "target_trades": int(scenario_trades["is_target_exit"].sum()),
                "target_trade_pct": _safe_pct(scenario_trades["is_target_exit"].sum(), len(scenario_trades)),
                "total_pnl": float(scenario_trades["scenario_pnl"].sum()),
                "pnl_delta_vs_current": float(scenario_trades["scenario_pnl"].sum() - work["pnl"].sum()),
                "profit_factor": _profit_factor(scenario_trades["scenario_pnl"]),
                "win_rate_pct": _safe_pct((scenario_trades["scenario_pnl"] > 0).sum(), len(scenario_trades)),
                "target_pnl": float(scenario_trades.loc[scenario_trades["is_target_exit"], "scenario_pnl"].sum()),
                "target_pnl_delta_vs_current": float(
                    scenario_trades.loc[scenario_trades["is_target_exit"], "scenario_pnl"].sum()
                    - work.loc[work["is_target_exit"], "pnl"].sum()
                ),
                "avg_target_pnl_delta": _safe_ratio(
                    scenario_trades.loc[scenario_trades["is_target_exit"], "scenario_pnl"].sum()
                    - work.loc[work["is_target_exit"], "pnl"].sum(),
                    scenario_trades["is_target_exit"].sum(),
                ),
                "notes": scenario["notes"],
            }
        )

    by_reason = (
        work.groupby("reason", dropna=False)
        .agg(
            trades=("pnl", "size"),
            pnl=("pnl", "sum"),
            median_pnl=("pnl", "median"),
            is_target_exit=("is_target_exit", "sum"),
            contracts=("contracts", "sum"),
        )
        .reset_index()
        .rename(columns={"is_target_exit": "target_exit_trades"})
        .sort_values(["pnl", "trades"], ascending=[True, False])
    )
    return pd.DataFrame(rows), by_reason


def build_fill_assumption_audit(
    trades: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    futures_specs: Mapping[str, Any],
    strategy_params: Mapping[str, Any] | None = None,
    trade_through_ticks: tuple[int, ...] = (1, 2),
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = _prepare_trades_for_fill_audit(trades)
    bars_work = _prepare_bars_for_fill_audit(bars)
    specs = dict(futures_specs)
    params = dict(strategy_params or {})
    ticks = tuple(sorted({int(tick) for tick in trade_through_ticks if int(tick) >= 0}))
    if not ticks:
        ticks = (1,)
    tick_size = _tick_size(params)
    bar_times = bars_work["time"].to_numpy(dtype="datetime64[ns]") if not bars_work.empty else np.array([], dtype="datetime64[ns]")

    rows: list[dict[str, Any]] = []
    for trade_id, trade in enumerate(work.itertuples(index=False)):
        row = _fill_assumption_row(
            trade_id=trade_id,
            trade=trade,
            bars=bars_work,
            bar_times=bar_times,
            futures_specs=specs,
            strategy_params=params,
            tick_size=tick_size,
            trade_through_ticks=ticks,
        )
        rows.append(row)

    by_trade = pd.DataFrame(rows)
    summary = _fill_assumption_summary(by_trade, work)
    by_reason = _fill_assumption_by_reason(by_trade)
    return summary, by_trade, by_reason


def export_fill_assumption_audit(
    trades: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    out_dir: Path | str,
    futures_specs: Mapping[str, Any],
    strategy_params: Mapping[str, Any] | None = None,
    artifact_name: str = "fill_assumption",
    trade_through_ticks: tuple[int, ...] = (1, 2),
) -> FillAssumptionAuditPaths:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    summary, by_trade, by_reason = build_fill_assumption_audit(
        trades,
        bars,
        futures_specs=futures_specs,
        strategy_params=strategy_params,
        trade_through_ticks=trade_through_ticks,
    )
    summary_csv = out_path / f"{artifact_name}_summary.csv"
    by_trade_csv = out_path / f"{artifact_name}_by_trade.csv"
    by_reason_csv = out_path / f"{artifact_name}_by_reason.csv"
    markdown_path = out_path / f"{artifact_name}_audit.md"
    summary.to_csv(summary_csv, index=False)
    by_trade.to_csv(by_trade_csv, index=False)
    by_reason.to_csv(by_reason_csv, index=False)
    markdown_path.write_text(_fill_assumption_markdown(summary, by_reason), encoding="utf-8")
    return FillAssumptionAuditPaths(
        summary_csv=summary_csv,
        by_trade_csv=by_trade_csv,
        by_reason_csv=by_reason_csv,
        markdown_path=markdown_path,
    )


def export_execution_realism_report(
    trades: pd.DataFrame,
    *,
    out_dir: Path | str,
    futures_specs: Mapping[str, Any],
    strategy_params: Mapping[str, Any] | None = None,
    artifact_name: str = "execution_realism",
) -> ExecutionRealismReportPaths:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    summary, by_reason = build_execution_realism_summary(
        trades,
        futures_specs=futures_specs,
        strategy_params=strategy_params,
    )
    summary_csv = out_path / f"{artifact_name}_summary.csv"
    by_reason_csv = out_path / f"{artifact_name}_by_reason.csv"
    markdown_path = out_path / f"{artifact_name}.md"
    summary.to_csv(summary_csv, index=False)
    by_reason.to_csv(by_reason_csv, index=False)
    markdown_path.write_text(_markdown(summary, by_reason), encoding="utf-8")
    return ExecutionRealismReportPaths(
        summary_csv=summary_csv,
        by_reason_csv=by_reason_csv,
        markdown_path=markdown_path,
    )


def _prepare_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        out = trades.copy()
        for col in ("pnl", "contracts", "reason", "is_target_exit"):
            out[col] = []
        return out
    required = {"pnl", "reason"}
    missing = required.difference(trades.columns)
    if missing:
        raise ValueError(f"trade log missing required columns: {sorted(missing)}")
    out = trades.copy()
    out["pnl"] = pd.to_numeric(out["pnl"], errors="coerce").fillna(0.0)
    if "contracts" not in out.columns:
        out["contracts"] = 1.0
    out["contracts"] = pd.to_numeric(out["contracts"], errors="coerce").fillna(1.0)
    out["reason"] = out["reason"].fillna("").astype(str)
    out["is_target_exit"] = out["reason"].isin(TARGET_EXIT_REASONS)
    return out


def _prepare_trades_for_fill_audit(trades: pd.DataFrame) -> pd.DataFrame:
    out = _prepare_trades(trades)
    required = {"entry_time", "exit_time", "direction", "entry_price", "exit_price"}
    missing = required.difference(out.columns)
    if missing:
        raise ValueError(f"trade log missing required columns for fill audit: {sorted(missing)}")
    out["entry_time"] = pd.to_datetime(out["entry_time"], errors="coerce")
    out["exit_time"] = pd.to_datetime(out["exit_time"], errors="coerce")
    out["direction"] = out["direction"].fillna("").astype(str).str.lower()
    out["entry_price"] = pd.to_numeric(out["entry_price"], errors="coerce")
    out["exit_price"] = pd.to_numeric(out["exit_price"], errors="coerce")
    out["signal_type"] = out.get("signal_type", "").fillna("").astype(str) if "signal_type" in out.columns else ""
    out["setup_tag"] = out.get("setup_tag", "").fillna("").astype(str) if "setup_tag" in out.columns else ""
    return out.dropna(subset=["entry_time", "exit_time", "entry_price", "exit_price"]).reset_index(drop=True)


def _prepare_bars_for_fill_audit(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"time", "open", "high", "low", "close"}
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"bars missing required columns for fill audit: {sorted(missing)}")
    out = bars.loc[:, ["time", "open", "high", "low", "close"]].copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time").drop_duplicates("time").reset_index(drop=True)


def _fill_assumption_row(
    *,
    trade_id: int,
    trade,
    bars: pd.DataFrame,
    bar_times: np.ndarray,
    futures_specs: Mapping[str, Any],
    strategy_params: Mapping[str, Any],
    tick_size: float,
    trade_through_ticks: tuple[int, ...],
) -> dict[str, Any]:
    entry_time = pd.Timestamp(trade.entry_time)
    exit_time = pd.Timestamp(trade.exit_time)
    entry_price = float(trade.entry_price)
    exit_price = float(trade.exit_price)
    direction = str(trade.direction).lower()
    reason = str(trade.reason)
    contracts = float(getattr(trade, "contracts", 1.0))
    realized_pnl = float(getattr(trade, "pnl", 0.0))
    target_exit = reason in TARGET_EXIT_REASONS
    stop_exit = reason in STOP_EXIT_REASONS
    hold_minutes = float((exit_time - entry_time).total_seconds() / 60.0)

    entry_idx = _bar_index(bar_times, entry_time, side="left")
    exit_idx = _bar_index(bar_times, exit_time, side="left")
    matched = 0 <= entry_idx < len(bars) and 0 <= exit_idx < len(bars) and exit_idx >= entry_idx
    exit_bar_matched = 0 <= exit_idx < len(bars)
    exit_bar = bars.iloc[exit_idx] if exit_bar_matched else None
    window = bars.iloc[entry_idx:exit_idx + 1] if matched else pd.DataFrame()

    same_minute_exit = bool(entry_time.floor("min") == exit_time.floor("min") or hold_minutes <= 0)
    target_touch_confirmed = False
    exit_bar_crossed_entry_adverse = False
    exit_bar_crossed_entry_favorable = False
    exit_bar_range_points = float("nan")
    exit_bar_close_pnl = float("nan")
    if exit_bar is not None:
        high = float(exit_bar["high"])
        low = float(exit_bar["low"])
        close = float(exit_bar["close"])
        exit_bar_range_points = high - low
        target_touch_confirmed = bool(target_exit and _favorable_price_hit(direction, exit_price, high, low, through_points=0.0))
        exit_bar_crossed_entry_adverse = bool(_adverse_entry_cross(direction, entry_price, high, low))
        exit_bar_crossed_entry_favorable = bool(_favorable_entry_cross(direction, entry_price, high, low))
        exit_bar_close_pnl = _pnl_at_exit_price(
            direction=direction,
            entry_price=entry_price,
            exit_price=close,
            contracts=contracts,
            futures_specs=futures_specs,
        )

    hard_stop_price = _hard_stop_price(direction, entry_price, contracts, trade, futures_specs, strategy_params)
    hard_target_price = _hard_target_price(direction, entry_price, contracts, trade, futures_specs, strategy_params)
    exit_bar_touched_hard_stop = False
    exit_bar_touched_hard_target = False
    if exit_bar is not None:
        high = float(exit_bar["high"])
        low = float(exit_bar["low"])
        if hard_stop_price is not None:
            exit_bar_touched_hard_stop = _adverse_price_hit(direction, float(hard_stop_price), high, low)
        if hard_target_price is not None:
            exit_bar_touched_hard_target = _favorable_price_hit(direction, float(hard_target_price), high, low, through_points=0.0)

    known_hard_bracket_ambiguous = bool(exit_bar_touched_hard_stop and exit_bar_touched_hard_target)
    realized_exit_with_known_opposite_hard_hit = bool(
        (target_exit and exit_bar_touched_hard_stop)
        or (stop_exit and exit_bar_touched_hard_target)
    )
    entry_cross_ordering_ambiguous = bool(
        (target_exit and exit_bar_crossed_entry_adverse)
        or (stop_exit and exit_bar_crossed_entry_favorable)
    )

    row: dict[str, Any] = {
        "trade_id": trade_id,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "direction": direction,
        "signal_type": str(getattr(trade, "signal_type", "")),
        "setup_tag": str(getattr(trade, "setup_tag", "")),
        "reason": reason,
        "contracts": contracts,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "realized_pnl": realized_pnl,
        "hold_minutes": hold_minutes,
        "same_minute_exit": same_minute_exit,
        "matched_execution_bars": int(len(window)),
        "exit_bar_matched": bool(exit_bar_matched),
        "target_exit": bool(target_exit),
        "stop_or_time_exit": bool(stop_exit),
        "target_touch_confirmed": bool(target_touch_confirmed),
        "exit_bar_range_points": exit_bar_range_points,
        "exit_bar_crossed_entry_adverse": exit_bar_crossed_entry_adverse,
        "exit_bar_crossed_entry_favorable": exit_bar_crossed_entry_favorable,
        "entry_cross_ordering_ambiguous": entry_cross_ordering_ambiguous,
        "hard_stop_price": hard_stop_price if hard_stop_price is not None else np.nan,
        "hard_target_price": hard_target_price if hard_target_price is not None else np.nan,
        "exit_bar_touched_hard_stop": bool(exit_bar_touched_hard_stop),
        "exit_bar_touched_hard_target": bool(exit_bar_touched_hard_target),
        "known_hard_bracket_ambiguous": known_hard_bracket_ambiguous,
        "realized_exit_with_known_opposite_hard_hit": realized_exit_with_known_opposite_hard_hit,
        "exit_bar_close_pnl": exit_bar_close_pnl,
    }
    for ticks in trade_through_ticks:
        through = float(ticks) * tick_size
        passed = bool(
            target_exit
            and exit_bar is not None
            and _favorable_price_hit(
                direction,
                exit_price,
                float(exit_bar["high"]),
                float(exit_bar["low"]),
                through_points=through,
            )
        )
        touch_only = bool(target_exit and target_touch_confirmed and not passed)
        row[f"target_trade_through_{ticks}tick"] = passed
        row[f"target_touch_only_{ticks}tick"] = touch_only
        row[f"target_fail_to_exit_bar_close_delta_{ticks}tick"] = (
            float(exit_bar_close_pnl - realized_pnl)
            if touch_only and np.isfinite(exit_bar_close_pnl)
            else 0.0
        )
    return row


def _bar_index(bar_times: np.ndarray, timestamp: pd.Timestamp, *, side: str) -> int:
    if bar_times.size == 0:
        return -1
    return int(bar_times.searchsorted(np.datetime64(timestamp), side=side))


def _favorable_price_hit(direction: str, price: float, high: float, low: float, *, through_points: float = 0.0) -> bool:
    if direction == "long":
        return high >= float(price) + float(through_points)
    return low <= float(price) - float(through_points)


def _adverse_price_hit(direction: str, price: float, high: float, low: float) -> bool:
    if direction == "long":
        return low <= float(price)
    return high >= float(price)


def _adverse_entry_cross(direction: str, entry_price: float, high: float, low: float) -> bool:
    return _adverse_price_hit(direction, entry_price, high, low)


def _favorable_entry_cross(direction: str, entry_price: float, high: float, low: float) -> bool:
    return _favorable_price_hit(direction, entry_price, high, low, through_points=0.0)


def _get_signal_param(params: Mapping[str, Any], trade, key: str, default: Any) -> Any:
    signal_type = str(getattr(trade, "signal_type", "") or "")
    direction = str(getattr(trade, "direction", "") or "")
    if signal_type:
        signal_directional_key = f"{signal_type}_{direction}_{key}"
        if signal_directional_key in params:
            return params[signal_directional_key]
        signal_key = f"{signal_type}_{key}"
        if signal_key in params:
            return params[signal_key]
    directional_key = f"{direction}_{key}"
    if directional_key in params:
        return params[directional_key]
    return params.get(key, default)


def _hard_stop_price(
    direction: str,
    entry_price: float,
    contracts: float,
    trade,
    futures_specs: Mapping[str, Any],
    strategy_params: Mapping[str, Any],
) -> float | None:
    if str(strategy_params.get("exit_mode", "hybrid")) not in {"hard_only", "hybrid"}:
        return None
    max_loss_dollars = float(_get_signal_param(strategy_params, trade, "max_loss_per_trade_dollars", strategy_params.get("max_loss_per_trade_dollars", 0.0)) or 0.0)
    cv = float(futures_specs.get("contract_value", 20.0))
    commission = float(futures_specs.get("commission_per_round_trip", 0.0)) * contracts
    slippage = float(futures_specs.get("slippage_points", 0.0)) * cv * contracts
    net_move_dollars = max(0.0, max_loss_dollars - commission - slippage)
    price_move = net_move_dollars / (contracts * cv) if contracts > 0 and cv > 0 else 0.0
    return float(entry_price - price_move) if direction == "long" else float(entry_price + price_move)


def _hard_target_price(
    direction: str,
    entry_price: float,
    contracts: float,
    trade,
    futures_specs: Mapping[str, Any],
    strategy_params: Mapping[str, Any],
) -> float | None:
    if str(strategy_params.get("exit_mode", "hybrid")) not in {"hard_only", "hybrid"}:
        return None
    max_profit_dollars = float(_get_signal_param(strategy_params, trade, "max_profit_per_trade_dollars", strategy_params.get("max_profit_per_trade_dollars", 0.0)) or 0.0)
    cv = float(futures_specs.get("contract_value", 20.0))
    commission = float(futures_specs.get("commission_per_round_trip", 0.0)) * contracts
    slippage = float(futures_specs.get("slippage_points", 0.0)) * cv * contracts
    net_target_dollars = max_profit_dollars + commission + slippage
    price_move = net_target_dollars / (contracts * cv) if contracts > 0 and cv > 0 else 0.0
    return float(entry_price + price_move) if direction == "long" else float(entry_price - price_move)


def _pnl_at_exit_price(
    *,
    direction: str,
    entry_price: float,
    exit_price: float,
    contracts: float,
    futures_specs: Mapping[str, Any],
) -> float:
    direction_sign = 1.0 if direction == "long" else -1.0
    cv = float(futures_specs.get("contract_value", 20.0))
    gross = (float(exit_price) - float(entry_price)) * direction_sign * float(contracts) * cv
    costs = (
        float(futures_specs.get("commission_per_round_trip", 0.0)) * float(contracts)
        + float(futures_specs.get("slippage_points", 0.0)) * cv * float(contracts)
    )
    return gross - costs


def _tick_size(params: Mapping[str, Any]) -> float:
    value = params.get("tick_size", params.get("vp_tick_size", 0.25))
    try:
        return max(1e-12, float(value))
    except (TypeError, ValueError):
        return 0.25


def _apply_target_slippage_scenario(
    trades: pd.DataFrame,
    *,
    current_target_slippage: float,
    scenario_target_slippage: float,
    contract_value: float,
) -> pd.DataFrame:
    out = trades.copy()
    delta_points = float(scenario_target_slippage) - float(current_target_slippage)
    delta_dollars = np.where(
        out["is_target_exit"],
        delta_points * out["contracts"].astype(float) * float(contract_value),
        0.0,
    )
    out["scenario_pnl"] = out["pnl"].astype(float) - delta_dollars
    return out


def _fill_assumption_summary(by_trade: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    total_trades = int(len(by_trade))
    trade_total_pnl = float(pd.to_numeric(trades.get("pnl", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum())
    target_trades = int(by_trade["target_exit"].sum()) if not by_trade.empty else 0
    same_minute = by_trade["same_minute_exit"].astype(bool) if not by_trade.empty else pd.Series(dtype=bool)
    touch_only_1 = (
        by_trade["target_touch_only_1tick"].astype(bool)
        if "target_touch_only_1tick" in by_trade.columns
        else pd.Series(False, index=by_trade.index)
    )
    touch_only_2 = (
        by_trade["target_touch_only_2tick"].astype(bool)
        if "target_touch_only_2tick" in by_trade.columns
        else pd.Series(False, index=by_trade.index)
    )
    target_through_1 = (
        by_trade["target_trade_through_1tick"].astype(bool)
        if "target_trade_through_1tick" in by_trade.columns
        else pd.Series(False, index=by_trade.index)
    )
    target_through_2 = (
        by_trade["target_trade_through_2tick"].astype(bool)
        if "target_trade_through_2tick" in by_trade.columns
        else pd.Series(False, index=by_trade.index)
    )
    known_hard_ambiguous = by_trade["known_hard_bracket_ambiguous"].astype(bool) if not by_trade.empty else pd.Series(dtype=bool)
    opposite_hard = by_trade["realized_exit_with_known_opposite_hard_hit"].astype(bool) if not by_trade.empty else pd.Series(dtype=bool)
    entry_cross = by_trade["entry_cross_ordering_ambiguous"].astype(bool) if not by_trade.empty else pd.Series(dtype=bool)
    unmatched = ~by_trade["exit_bar_matched"].astype(bool) if not by_trade.empty else pd.Series(dtype=bool)

    one_tick_delta = (
        float(by_trade["target_fail_to_exit_bar_close_delta_1tick"].sum())
        if "target_fail_to_exit_bar_close_delta_1tick" in by_trade.columns
        else 0.0
    )
    two_tick_delta = (
        float(by_trade["target_fail_to_exit_bar_close_delta_2tick"].sum())
        if "target_fail_to_exit_bar_close_delta_2tick" in by_trade.columns
        else 0.0
    )
    verdict = _fill_assumption_verdict(
        target_trades=target_trades,
        touch_only_1=int(touch_only_1.sum()),
        same_minute=int(same_minute.sum()) if len(same_minute) else 0,
        known_hard_ambiguous=int(known_hard_ambiguous.sum()) if len(known_hard_ambiguous) else 0,
        unmatched=int(unmatched.sum()) if len(unmatched) else 0,
    )

    return pd.DataFrame(
        [
            {
                "verdict": verdict,
                "total_trades": total_trades,
                "trade_total_pnl": trade_total_pnl,
                "target_trades": target_trades,
                "target_trade_pct": _safe_pct(target_trades, total_trades),
                "target_trade_through_1tick_trades": int(target_through_1.sum()),
                "target_trade_through_1tick_pct_of_targets": _safe_pct(int(target_through_1.sum()), target_trades),
                "target_touch_only_1tick_trades": int(touch_only_1.sum()),
                "target_touch_only_1tick_pnl": _sum_mask(by_trade, touch_only_1, "realized_pnl"),
                "target_fail_to_exit_bar_close_delta_1tick": one_tick_delta,
                "stressed_total_pnl_if_1tick_target_fails_to_exit_bar_close": trade_total_pnl + one_tick_delta,
                "target_trade_through_2tick_trades": int(target_through_2.sum()),
                "target_trade_through_2tick_pct_of_targets": _safe_pct(int(target_through_2.sum()), target_trades),
                "target_touch_only_2tick_trades": int(touch_only_2.sum()),
                "target_touch_only_2tick_pnl": _sum_mask(by_trade, touch_only_2, "realized_pnl"),
                "target_fail_to_exit_bar_close_delta_2tick": two_tick_delta,
                "stressed_total_pnl_if_2tick_target_fails_to_exit_bar_close": trade_total_pnl + two_tick_delta,
                "same_minute_exits": int(same_minute.sum()) if len(same_minute) else 0,
                "same_minute_exit_pnl": _sum_mask(by_trade, same_minute, "realized_pnl"),
                "same_minute_target_exits": int((same_minute & by_trade.get("target_exit", False)).sum()) if not by_trade.empty else 0,
                "known_hard_bracket_ambiguous_trades": int(known_hard_ambiguous.sum()) if len(known_hard_ambiguous) else 0,
                "known_hard_bracket_ambiguous_pnl": _sum_mask(by_trade, known_hard_ambiguous, "realized_pnl"),
                "realized_exit_with_known_opposite_hard_hit_trades": int(opposite_hard.sum()) if len(opposite_hard) else 0,
                "realized_exit_with_known_opposite_hard_hit_pnl": _sum_mask(by_trade, opposite_hard, "realized_pnl"),
                "entry_cross_ordering_ambiguous_trades": int(entry_cross.sum()) if len(entry_cross) else 0,
                "entry_cross_ordering_ambiguous_pnl": _sum_mask(by_trade, entry_cross, "realized_pnl"),
                "unmatched_exit_bar_trades": int(unmatched.sum()) if len(unmatched) else 0,
            }
        ]
    )


def _fill_assumption_by_reason(by_trade: pd.DataFrame) -> pd.DataFrame:
    if by_trade.empty:
        return pd.DataFrame()
    agg = {
        "trades": ("trade_id", "count"),
        "pnl": ("realized_pnl", "sum"),
        "median_pnl": ("realized_pnl", "median"),
        "same_minute_exits": ("same_minute_exit", "sum"),
        "target_exits": ("target_exit", "sum"),
        "target_touch_only_1tick": ("target_touch_only_1tick", "sum"),
        "target_touch_only_2tick": ("target_touch_only_2tick", "sum"),
        "known_hard_bracket_ambiguous": ("known_hard_bracket_ambiguous", "sum"),
        "realized_exit_with_known_opposite_hard_hit": ("realized_exit_with_known_opposite_hard_hit", "sum"),
        "entry_cross_ordering_ambiguous": ("entry_cross_ordering_ambiguous", "sum"),
        "one_tick_target_fail_delta": ("target_fail_to_exit_bar_close_delta_1tick", "sum"),
        "two_tick_target_fail_delta": ("target_fail_to_exit_bar_close_delta_2tick", "sum"),
    }
    return (
        by_trade.groupby("reason", dropna=False)
        .agg(**agg)
        .reset_index()
        .sort_values(["pnl", "trades"], ascending=[True, False])
    )


def _fill_assumption_verdict(
    *,
    target_trades: int,
    touch_only_1: int,
    same_minute: int,
    known_hard_ambiguous: int,
    unmatched: int,
) -> str:
    if unmatched > 0:
        return "audit_data_alignment_issue"
    if target_trades > 0 and touch_only_1 / max(1, target_trades) >= 0.25:
        return "trade_through_target_validation_required"
    if same_minute > 0 or known_hard_ambiguous > 0:
        return "intrabar_ordering_validation_required"
    return "no_major_fill_assumption_warning"


def _sum_mask(frame: pd.DataFrame, mask: pd.Series, column: str) -> float:
    if frame.empty or column not in frame.columns or len(mask) == 0:
        return 0.0
    aligned = mask.reindex(frame.index, fill_value=False).astype(bool)
    return float(pd.to_numeric(frame.loc[aligned, column], errors="coerce").fillna(0.0).sum())


def _profit_factor(pnl: pd.Series) -> float:
    values = pd.to_numeric(pnl, errors="coerce").dropna()
    wins = values[values > 0].sum()
    losses = values[values < 0].sum()
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / abs(losses))


def _safe_pct(numerator: float, denominator: float) -> float:
    if float(denominator) == 0.0:
        return 0.0
    return float(numerator) / float(denominator) * 100.0


def _safe_ratio(numerator: float, denominator: float) -> float:
    if float(denominator) == 0.0:
        return 0.0
    return float(numerator) / float(denominator)


def _fmt_money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_float(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "n/a"


def _markdown(summary: pd.DataFrame, by_reason: pd.DataFrame) -> str:
    lines = [
        "# Execution Realism Report",
        "",
        "This report does not prove fill quality. It highlights sensitivity to the easiest optimistic fill assumption: target exits filled as cheap resting limits.",
        "",
        "## Target-Fill Cost Sensitivity",
        "",
        "| Scenario | Target Slippage | Total PnL | Delta | PF | Target Trades | Avg Target Delta |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in summary.iterrows():
        lines.append(
            "| "
            f"{row['scenario']} | "
            f"{_fmt_float(row['target_slippage_points'])} pts | "
            f"{_fmt_money(row['total_pnl'])} | "
            f"{_fmt_money(row['pnl_delta_vs_current'])} | "
            f"{_fmt_float(row['profit_factor'])} | "
            f"{int(row['target_trades'])} | "
            f"{_fmt_money(row['avg_target_pnl_delta'])} |"
        )

    lines.extend(
        [
            "",
            "## Exit Reason Mix",
            "",
            "| Reason | Trades | PnL | Median PnL | Target Exits |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for _, row in by_reason.iterrows():
        lines.append(
            "| "
            f"{row['reason']} | "
            f"{int(row['trades'])} | "
            f"{_fmt_money(row['pnl'])} | "
            f"{_fmt_money(row['median_pnl'])} | "
            f"{int(row['target_exit_trades'])} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- If a candidate only survives with cheap target fills, it is not ready for prop-firm evaluation.",
            "- A stronger candidate should remain acceptable after target exits pay at least default slippage, and ideally after a trade-through target-fill run.",
        ]
    )
    return "\n".join(lines) + "\n"


def _fill_assumption_markdown(summary: pd.DataFrame, by_reason: pd.DataFrame) -> str:
    row = summary.iloc[0] if not summary.empty else pd.Series(dtype=object)
    lines = [
        "# Fill Assumption Audit",
        "",
        "This report joins a saved trade log to execution bars. It does not replay strategy logic.",
        "",
        "## Summary",
        "",
        f"- Verdict: `{row.get('verdict', 'unknown')}`",
        f"- Trades: `{int(row.get('total_trades', 0))}`",
        f"- Trade PnL: `{_fmt_money(row.get('trade_total_pnl'))}`",
        f"- Target exits: `{int(row.get('target_trades', 0))}`",
        f"- 1-tick trade-through target pass rate: `{_fmt_float(row.get('target_trade_through_1tick_pct_of_targets'))}%`",
        f"- 1-tick touch-only targets: `{int(row.get('target_touch_only_1tick_trades', 0))}` "
        f"({ _fmt_money(row.get('target_touch_only_1tick_pnl')) } PnL)",
        f"- Same-minute exits: `{int(row.get('same_minute_exits', 0))}` "
        f"({ _fmt_money(row.get('same_minute_exit_pnl')) } PnL)",
        f"- Known hard-bracket ambiguous exits: `{int(row.get('known_hard_bracket_ambiguous_trades', 0))}`",
        f"- Entry-cross ordering ambiguous exits: `{int(row.get('entry_cross_ordering_ambiguous_trades', 0))}`",
        f"- 1-tick target-fail exit-bar-close stressed PnL: "
        f"`{_fmt_money(row.get('stressed_total_pnl_if_1tick_target_fails_to_exit_bar_close'))}`",
        "",
        "## Exit Reason Breakdown",
        "",
        "| Reason | Trades | PnL | Same-Minute | Targets | Touch-Only 1t | Hard-Bracket Ambig | Entry-Cross Ambig |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, reason_row in by_reason.iterrows():
        lines.append(
            "| "
            f"{reason_row['reason']} | "
            f"{int(reason_row['trades'])} | "
            f"{_fmt_money(reason_row['pnl'])} | "
            f"{int(reason_row['same_minute_exits'])} | "
            f"{int(reason_row['target_exits'])} | "
            f"{int(reason_row['target_touch_only_1tick'])} | "
            f"{int(reason_row['known_hard_bracket_ambiguous'])} | "
            f"{int(reason_row['entry_cross_ordering_ambiguous'])} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Touch-only target exits are fragile because a one-tick trade-through rule would not fill them.",
            "- Same-minute exits and entry-cross ambiguous exits indicate sequencing risk inside a single OHLC bar.",
            "- Known hard-bracket ambiguity is a lower-bound check using only hard stop/target levels that can be inferred from saved config.",
            "- This audit is a filter for what deserves a stricter rerun or TBBO review; it is not approval evidence.",
        ]
    )
    return "\n".join(lines) + "\n"
