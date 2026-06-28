from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from pathlib import Path
from typing import Any, Callable, Protocol

import numpy as np
import pandas as pd

from backtest.l2_execution_engine import (
    L2ExecutionBroker,
    L2ExecutionConfig,
    L2ExecutionEngine,
    L2ExecutionResult,
    L2Fill,
    L2MarketEvent,
    L2Order,
)


class L2OrderFlowStrategy(Protocol):
    name: str

    def on_event(self, event: L2MarketEvent, context: "L2OrderFlowContext") -> None:
        ...


@dataclass(frozen=True)
class L2OrderFlowReplayConfig:
    execution_config: L2ExecutionConfig = field(default_factory=L2ExecutionConfig)
    strategy_name: str = "custom"
    contract_value: float = 20.0


@dataclass(frozen=True)
class L2OrderFlowReplayResult:
    execution: L2ExecutionResult
    replay_summary: pd.DataFrame
    strategy_events: pd.DataFrame
    report_md: str


class L2OrderFlowContext:
    """
    Runtime context exposed to event-driven L2 strategies.

    The context updates position from fills that occurred before the current
    strategy callback. Orders submitted by the strategy still inherit the lower
    layer's same-event fill guard.
    """

    def __init__(
        self,
        *,
        engine: L2ExecutionEngine,
        broker: L2ExecutionBroker,
        strategy_name: str,
    ) -> None:
        self._engine = engine
        self._broker = broker
        self.strategy_name = str(strategy_name)
        self.current_event: L2MarketEvent | None = None
        self._fill_cursor = 0
        self._position = 0.0
        self._strategy_events: list[dict[str, object]] = []

    @property
    def position(self) -> float:
        return float(self._position)

    @property
    def flat(self) -> bool:
        return abs(self._position) <= 1e-12

    @property
    def orders(self) -> dict[str, L2Order]:
        return self._engine.orders

    @property
    def fills(self) -> list[L2Fill]:
        return self._engine.fills

    @property
    def active_order_count(self) -> int:
        return sum(1 for order in self.orders.values() if order.status in {"accepted", "active"})

    @property
    def tick_size(self) -> float:
        return float(self._engine.config.tick_size)

    @property
    def strategy_events(self) -> pd.DataFrame:
        return pd.DataFrame(self._strategy_events)

    def submit_order(self, order: L2Order) -> str:
        return self._broker.submit_order(order)

    def submit_market(
        self,
        side: str,
        quantity: float,
        *,
        tag: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self._broker.submit_market(side, quantity, tag=tag, metadata=metadata)

    def submit_limit(
        self,
        side: str,
        quantity: float,
        limit_price: float,
        *,
        post_only: bool = False,
        tag: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self._broker.submit_limit(
            side,
            quantity,
            limit_price,
            post_only=post_only,
            tag=tag,
            metadata=metadata,
        )

    def submit_stop_market(
        self,
        side: str,
        quantity: float,
        stop_price: float,
        *,
        tag: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self._broker.submit_stop_market(side, quantity, stop_price, tag=tag, metadata=metadata)

    def log(self, event_type: str, **fields: object) -> None:
        event = self.current_event
        row: dict[str, object] = {
            "strategy_name": self.strategy_name,
            "event_type": str(event_type),
            "position": float(self.position),
        }
        if event is not None:
            row.update(
                {
                    "event_seq": int(event.event_seq),
                    "ts_event": event.ts_event,
                    "action": event.action,
                    "bid_price": event.bid_price,
                    "ask_price": event.ask_price,
                    "bid_size": event.bid_size,
                    "ask_size": event.ask_size,
                    "spread_points": event.spread_points,
                }
            )
        row.update(fields)
        self._strategy_events.append(row)

    def _before_strategy_event(self, event: L2MarketEvent) -> None:
        self.current_event = event
        self._sync_new_fills()

    def _after_replay(self) -> None:
        self._sync_new_fills()

    def _sync_new_fills(self) -> None:
        while self._fill_cursor < len(self._engine.fills):
            fill = self._engine.fills[self._fill_cursor]
            sign = 1.0 if fill.side == "buy" else -1.0
            self._position += sign * float(fill.quantity)
            self._fill_cursor += 1


class L2NoOpStrategy:
    name = "noop"

    def on_event(self, event: L2MarketEvent, context: L2OrderFlowContext) -> None:
        return None


@dataclass
class L2TopBookImbalanceSmokeStrategy:
    """
    Minimal top-book imbalance strategy for replay plumbing tests.

    This is intentionally a smoke harness, not a candidate strategy. It exists
    to verify event ordering, market-order submission, fills, and flattening.
    """

    threshold: float = 0.75
    exit_threshold: float = 0.10
    quantity: float = 1.0
    max_position: float = 1.0
    min_spread_ticks: float = 1.0
    max_spread_ticks: float = 8.0
    cooldown: str | pd.Timedelta = "1s"
    name: str = "topbook_imbalance_smoke"
    _next_action_time: pd.Timestamp = field(
        default_factory=lambda: pd.Timestamp.min.tz_localize("UTC"),
        init=False,
        repr=False,
    )

    def on_event(self, event: L2MarketEvent, context: L2OrderFlowContext) -> None:
        if event.action != "Q":
            return
        if event.ts_event < self._next_action_time:
            return
        if context.active_order_count > 0:
            return

        imbalance = _topbook_imbalance(event)
        spread_ticks = event.spread_points / context.tick_size
        if not np.isfinite(imbalance) or not np.isfinite(spread_ticks):
            return
        if spread_ticks < float(self.min_spread_ticks) or spread_ticks > float(self.max_spread_ticks):
            return

        position = context.position
        if abs(position) > 0.0:
            self._maybe_exit_position(event, context, imbalance)
            return

        if imbalance >= float(self.threshold):
            self._submit_action(event, context, "buy", "imbalance_long_entry", imbalance)
        elif imbalance <= -float(self.threshold):
            self._submit_action(event, context, "sell", "imbalance_short_entry", imbalance)

    def _maybe_exit_position(
        self,
        event: L2MarketEvent,
        context: L2OrderFlowContext,
        imbalance: float,
    ) -> None:
        position = context.position
        if position > 0.0 and (imbalance <= -float(self.threshold) or abs(imbalance) <= float(self.exit_threshold)):
            self._submit_action(event, context, "sell", "imbalance_long_exit", imbalance, quantity=abs(position))
        elif position < 0.0 and (imbalance >= float(self.threshold) or abs(imbalance) <= float(self.exit_threshold)):
            self._submit_action(event, context, "buy", "imbalance_short_exit", imbalance, quantity=abs(position))

    def _submit_action(
        self,
        event: L2MarketEvent,
        context: L2OrderFlowContext,
        side: str,
        tag: str,
        imbalance: float,
        *,
        quantity: float | None = None,
    ) -> None:
        order_qty = min(float(quantity if quantity is not None else self.quantity), float(self.max_position))
        if order_qty <= 0.0:
            return
        order_id = context.submit_market(
            side,
            order_qty,
            tag=tag,
            metadata={"strategy": self.name, "imbalance": float(imbalance)},
        )
        context.log(
            "order_submitted",
            order_id=order_id,
            side=side,
            quantity=order_qty,
            tag=tag,
            imbalance=float(imbalance),
        )
        self._next_action_time = event.ts_event + pd.Timedelta(self.cooldown)


class _CallableL2OrderFlowStrategy:
    def __init__(self, func: Callable[[L2MarketEvent, L2OrderFlowContext], None], *, name: str) -> None:
        self._func = func
        self.name = name

    def on_event(self, event: L2MarketEvent, context: L2OrderFlowContext) -> None:
        self._func(event, context)


def run_l2_orderflow_replay(
    topbook_events: pd.DataFrame,
    strategy: L2OrderFlowStrategy | Callable[[L2MarketEvent, L2OrderFlowContext], None] | None = None,
    *,
    config: L2OrderFlowReplayConfig | None = None,
) -> L2OrderFlowReplayResult:
    cfg = config or L2OrderFlowReplayConfig()
    strategy_obj = _normalize_strategy(strategy)
    strategy_name = _strategy_name(strategy_obj, fallback=cfg.strategy_name)
    engine = L2ExecutionEngine(topbook_events, config=cfg.execution_config)
    context = L2OrderFlowContext(engine=engine, broker=engine.broker, strategy_name=strategy_name)

    _call_optional(strategy_obj, "on_start", context)

    def callback(event: L2MarketEvent, _broker: L2ExecutionBroker) -> None:
        context._before_strategy_event(event)
        strategy_obj.on_event(event, context)

    execution = engine.run(strategy=callback)
    context._after_replay()
    _call_optional(strategy_obj, "on_finish", context, execution)

    replay_summary = summarize_l2_orderflow_replay(
        engine.events,
        execution,
        strategy_name=strategy_name,
        contract_value=float(cfg.contract_value),
    )
    strategy_events = context.strategy_events
    return L2OrderFlowReplayResult(
        execution=execution,
        replay_summary=replay_summary,
        strategy_events=strategy_events,
        report_md=render_l2_orderflow_replay_report(replay_summary, execution, strategy_events),
    )


def filter_l2_events_by_ny_window(
    events: pd.DataFrame,
    *,
    start_ny: str = "",
    end_ny: str = "",
    timezone: str = "America/New_York",
    time_col: str = "ts_event",
) -> pd.DataFrame:
    """
    Filter replay events by New York clock or timestamp.

    `start_ny` is inclusive and `end_ny` is exclusive. Clock values such as
    `09:30` apply to every local date. Timestamp values such as
    `2021-01-04 09:30` are interpreted in `timezone` when naive.
    """

    start = str(start_ny or "").strip()
    end = str(end_ny or "").strip()
    if not start and not end:
        return events.copy()
    if time_col not in events.columns:
        raise ValueError(f"L2 event frame missing required time column: {time_col}")
    if events.empty:
        return events.copy()

    out = events.copy()
    local_time = pd.to_datetime(out[time_col], utc=True, errors="coerce").dt.tz_convert(str(timezone))
    valid = local_time.notna()
    mask = valid.copy()

    start_bound = _parse_ny_window_bound(start, timezone=timezone)
    end_bound = _parse_ny_window_bound(end, timezone=timezone)
    if _is_clock_bound(start_bound) or _is_clock_bound(end_bound):
        if start_bound and not _is_clock_bound(start_bound):
            raise ValueError("Use either clock bounds or timestamp bounds, not a mix")
        if end_bound and not _is_clock_bound(end_bound):
            raise ValueError("Use either clock bounds or timestamp bounds, not a mix")
        clock = local_time.dt.strftime("%H:%M:%S")
        if start_bound and end_bound:
            start_clock = str(start_bound[1])
            end_clock = str(end_bound[1])
            if start_clock <= end_clock:
                mask &= clock.ge(start_clock) & clock.lt(end_clock)
            else:
                mask &= clock.ge(start_clock) | clock.lt(end_clock)
        elif start_bound:
            mask &= clock.ge(str(start_bound[1]))
        elif end_bound:
            mask &= clock.lt(str(end_bound[1]))
    else:
        if start_bound:
            mask &= local_time.ge(start_bound[1])
        if end_bound:
            mask &= local_time.lt(end_bound[1])

    return out.loc[mask.fillna(False)].sort_values(time_col, kind="stable").reset_index(drop=True)


def summarize_l2_orderflow_replay(
    prepared_events: pd.DataFrame,
    execution: L2ExecutionResult,
    *,
    strategy_name: str,
    contract_value: float = 20.0,
) -> pd.DataFrame:
    if prepared_events.empty:
        event_row = {
            "strategy_name": strategy_name,
            "events": 0,
            "quote_events": 0,
            "trade_events": 0,
            "start_time": "",
            "end_time": "",
            "last_mid_price": np.nan,
        }
    else:
        bid = pd.to_numeric(prepared_events["bid_px_00"], errors="coerce")
        ask = pd.to_numeric(prepared_events["ask_px_00"], errors="coerce")
        mid = (bid + ask) / 2.0
        action = prepared_events["action"].astype(str)
        event_row = {
            "strategy_name": strategy_name,
            "events": int(len(prepared_events)),
            "quote_events": int(action.eq("Q").sum()),
            "trade_events": int(action.eq("T").sum()),
            "start_time": str(prepared_events["ts_event"].iloc[0]),
            "end_time": str(prepared_events["ts_event"].iloc[-1]),
            "last_mid_price": _last_finite(mid),
        }

    pnl = _fifo_fill_pnl(
        execution.fills,
        last_mid_price=float(event_row["last_mid_price"]),
        contract_value=float(contract_value),
    )
    execution_summary = execution.summary.iloc[0].to_dict() if not execution.summary.empty else {}
    row = {**event_row, **execution_summary, **pnl}
    return pd.DataFrame([row])


def write_l2_orderflow_replay_result(
    result: L2OrderFlowReplayResult,
    out_dir: Path | str,
    *,
    prefix: str = "l2_orderflow_replay",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "orders_csv": out_path / f"{prefix}_orders.csv",
        "fills_csv": out_path / f"{prefix}_fills.csv",
        "replay_summary_csv": out_path / f"{prefix}_replay_summary.csv",
        "strategy_events_csv": out_path / f"{prefix}_strategy_events.csv",
        "report_md": out_path / f"{prefix}_report.md",
    }
    result.execution.orders.to_csv(paths["orders_csv"], index=False)
    result.execution.fills.to_csv(paths["fills_csv"], index=False)
    result.replay_summary.to_csv(paths["replay_summary_csv"], index=False)
    result.strategy_events.to_csv(paths["strategy_events_csv"], index=False)
    paths["report_md"].write_text(result.report_md, encoding="utf-8")
    return paths


def render_l2_orderflow_replay_report(
    replay_summary: pd.DataFrame,
    execution: L2ExecutionResult,
    strategy_events: pd.DataFrame,
) -> str:
    lines = [
        "# L2 Orderflow Replay",
        "",
        "This is an event-driven replay over guarded L2 rows. It does not use OHLCV bars.",
        "",
    ]
    if replay_summary.empty:
        lines.extend(["No replay summary was produced.", ""])
        return "\n".join(lines)
    row = replay_summary.iloc[0]
    lines.extend(
        [
            "## Summary",
            "",
            f"- Strategy: `{row.get('strategy_name', '')}`",
            f"- Events: {int(row.get('events', 0)):,}",
            f"- Quote events: {int(row.get('quote_events', 0)):,}",
            f"- Trade events: {int(row.get('trade_events', 0)):,}",
            f"- Orders: {int(row.get('orders', 0)):,}",
            f"- Fills: {int(row.get('fills', 0)):,}",
            f"- Net position: {float(row.get('net_position', 0.0)):.4g}",
            f"- Realized PnL: {float(row.get('realized_pnl_points', 0.0)):.4g} points / ${float(row.get('realized_pnl_dollars', 0.0)):.2f}",
            f"- Unrealized PnL at final mid: {float(row.get('unrealized_pnl_points', 0.0)):.4g} points / ${float(row.get('unrealized_pnl_dollars', 0.0)):.2f}",
            "",
            "## Guardrails",
            "",
            "- This runner consumes L2 events directly; it is not the existing OHLCV backtest path.",
            "- Full-depth mode still depends on an accepted depth-semantics proof.",
            "- Built-in smoke strategies are plumbing tests, not edge evidence or candidates.",
            "- Orders submitted from `on_event` cannot fill on the same market event.",
            "",
        ]
    )
    if not strategy_events.empty:
        lines.extend(["## Strategy Event Counts", "", _counts_table(strategy_events["event_type"]), ""])
    if not execution.summary.empty:
        lines.extend(["## Execution Summary", "", _frame_markdown_table(execution.summary), ""])
    return "\n".join(lines)


def load_l2_orderflow_strategy(spec: str, kwargs: dict[str, Any] | None = None) -> L2OrderFlowStrategy:
    kwargs = dict(kwargs or {})
    name = (spec or "noop").strip()
    if name == "noop":
        return L2NoOpStrategy()
    if name == "topbook_imbalance":
        return L2TopBookImbalanceSmokeStrategy(**kwargs)
    if name == "tape_read_orderflow":
        from backtest.l2_tape_read_orderflow import L2TapeReadOrderFlowStrategy

        return L2TapeReadOrderFlowStrategy(**kwargs)
    if name == "bar_signal_csv":
        from backtest.l2_bar_signal_adapter import L2BarSignalAdapterStrategy

        return L2BarSignalAdapterStrategy(**kwargs)
    if ":" not in name:
        raise ValueError(
            "Unknown L2 orderflow strategy. Use `noop`, `topbook_imbalance`, "
            "`tape_read_orderflow`, `bar_signal_csv`, or `module:function`."
        )
    module_name, factory_name = name.split(":", 1)
    factory = getattr(importlib.import_module(module_name), factory_name)
    obj = factory(**kwargs)
    return _normalize_strategy(obj)


def _normalize_strategy(
    strategy: L2OrderFlowStrategy | Callable[[L2MarketEvent, L2OrderFlowContext], None] | None,
) -> L2OrderFlowStrategy:
    if strategy is None:
        return L2NoOpStrategy()
    if hasattr(strategy, "on_event"):
        return strategy  # type: ignore[return-value]
    if callable(strategy):
        return _CallableL2OrderFlowStrategy(strategy, name=getattr(strategy, "__name__", "callable_strategy"))
    raise TypeError("L2 strategy must expose on_event(event, context) or be a callable.")


def _strategy_name(strategy: L2OrderFlowStrategy, *, fallback: str = "custom") -> str:
    name = getattr(strategy, "name", "")
    return str(name or fallback)


def _call_optional(obj: object, name: str, *args: object) -> None:
    func = getattr(obj, name, None)
    if callable(func):
        func(*args)


def _topbook_imbalance(event: L2MarketEvent) -> float:
    denom = float(event.bid_size) + float(event.ask_size)
    if denom <= 0.0:
        return np.nan
    return (float(event.bid_size) - float(event.ask_size)) / denom


def _fifo_fill_pnl(
    fills: pd.DataFrame,
    *,
    last_mid_price: float,
    contract_value: float,
) -> dict[str, float]:
    realized_points = 0.0
    lots: list[tuple[float, float, float]] = []
    if not fills.empty:
        ordered = fills.sort_values(["fill_time", "event_seq"], kind="stable")
        for _, row in ordered.iterrows():
            sign = 1.0 if str(row["side"]) == "buy" else -1.0
            qty = float(row["quantity"])
            price = float(row["price"])
            while qty > 1e-12 and lots and lots[0][0] != sign:
                lot_sign, lot_qty, lot_price = lots[0]
                close_qty = min(qty, lot_qty)
                if lot_sign > 0.0:
                    realized_points += (price - lot_price) * close_qty
                else:
                    realized_points += (lot_price - price) * close_qty
                qty -= close_qty
                lot_qty -= close_qty
                if lot_qty <= 1e-12:
                    lots.pop(0)
                else:
                    lots[0] = (lot_sign, lot_qty, lot_price)
            if qty > 1e-12:
                lots.append((sign, qty, price))

    open_position = float(sum(sign * qty for sign, qty, _price in lots))
    open_abs_qty = abs(open_position)
    open_avg_price = (
        float(sum(qty * price for _sign, qty, price in lots) / sum(qty for _sign, qty, _price in lots))
        if lots
        else np.nan
    )
    unrealized_points = 0.0
    if np.isfinite(last_mid_price):
        for sign, qty, price in lots:
            unrealized_points += (last_mid_price - price) * qty if sign > 0.0 else (price - last_mid_price) * qty
    else:
        unrealized_points = np.nan if lots else 0.0

    total_points = realized_points + (float(unrealized_points) if np.isfinite(unrealized_points) else 0.0)
    return {
        "realized_pnl_points": float(realized_points),
        "realized_pnl_dollars": float(realized_points * contract_value),
        "unrealized_pnl_points": float(unrealized_points),
        "unrealized_pnl_dollars": float(unrealized_points * contract_value),
        "total_pnl_points": float(total_points),
        "total_pnl_dollars": float(total_points * contract_value),
        "open_position": float(open_position),
        "open_abs_quantity": float(open_abs_qty),
        "open_avg_price": float(open_avg_price),
    }


def _last_finite(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.iloc[-1]) if not clean.empty else np.nan


def _counts_table(series: pd.Series) -> str:
    counts = series.astype(str).value_counts(dropna=False).sort_index()
    lines = ["| value | count |", "| --- | --- |"]
    for key, value in counts.items():
        lines.append(f"| {key} | {int(value)} |")
    return "\n".join(lines)


def _frame_markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    columns = [str(col) for col in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(_fmt_cell(row[col]) for col in frame.columns) + " |")
    return "\n".join(lines)


def _fmt_cell(value: object) -> str:
    if isinstance(value, float):
        if not np.isfinite(value):
            return "nan"
        return f"{value:.6g}"
    return str(value)


def _parse_ny_window_bound(value: str, *, timezone: str) -> tuple[str, object] | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if _looks_like_clock(raw):
        return "clock", _normalize_clock_bound(raw)
    timestamp = pd.Timestamp(raw)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(str(timezone))
    else:
        timestamp = timestamp.tz_convert(str(timezone))
    return "timestamp", timestamp


def _is_clock_bound(value: tuple[str, object] | None) -> bool:
    return value is not None and value[0] == "clock"


def _looks_like_clock(value: str) -> bool:
    parts = str(value).strip().split(":")
    if len(parts) not in {2, 3}:
        return False
    if not all(part.isdigit() for part in parts):
        return False
    hour = int(parts[0])
    minute = int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    return 0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59


def _normalize_clock_bound(value: str) -> str:
    parts = [int(part) for part in str(value).strip().split(":")]
    hour, minute = parts[0], parts[1]
    second = parts[2] if len(parts) == 3 else 0
    return f"{hour:02d}:{minute:02d}:{second:02d}"


__all__ = [
    "L2NoOpStrategy",
    "L2OrderFlowContext",
    "L2OrderFlowReplayConfig",
    "L2OrderFlowReplayResult",
    "L2OrderFlowStrategy",
    "L2TopBookImbalanceSmokeStrategy",
    "filter_l2_events_by_ny_window",
    "load_l2_orderflow_strategy",
    "run_l2_orderflow_replay",
    "summarize_l2_orderflow_replay",
    "write_l2_orderflow_replay_result",
]
