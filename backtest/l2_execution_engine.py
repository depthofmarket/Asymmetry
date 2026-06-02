from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

import numpy as np
import pandas as pd


L2OrderSide = Literal["buy", "sell"]
L2OrderType = Literal["market", "limit", "stop_market"]
L2OrderStatus = Literal[
    "scheduled",
    "accepted",
    "active",
    "filled",
    "partial_cancelled",
    "cancelled",
    "rejected",
    "open",
]
L2LimitFillModel = Literal["trade_through", "queue", "touch"]


@dataclass(frozen=True)
class L2ExecutionConfig:
    tick_size: float = 0.25
    contract_value: float = 20.0
    latency: str | pd.Timedelta = "0ms"
    allow_partial_fills: bool = True
    reject_crossed_books: bool = True
    reject_non_topbook_limits: bool = True
    limit_fill_model: L2LimitFillModel = "trade_through"
    queue_ahead_multiplier: float = 1.0


@dataclass
class L2Order:
    side: L2OrderSide
    quantity: float
    order_type: L2OrderType = "market"
    order_id: str = ""
    submit_time: pd.Timestamp | str | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "gtc"
    post_only: bool = False
    tag: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    status: L2OrderStatus = "scheduled"
    filled_quantity: float = 0.0
    avg_fill_price: float = np.nan
    reject_reason: str = ""
    cancel_reason: str = ""
    active_after_time: pd.Timestamp | None = None
    active_after_event_seq: int = 0
    queue_ahead: float = np.nan
    first_active_event_seq: int | None = None
    created_from_event_seq: int | None = None

    @property
    def remaining_quantity(self) -> float:
        return max(float(self.quantity) - float(self.filled_quantity), 0.0)


@dataclass(frozen=True)
class L2MarketEvent:
    event_seq: int
    ts_event: pd.Timestamp
    action: str
    side: str
    price: float
    size: float
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    spread_points: float
    row: pd.Series

    @property
    def is_quote(self) -> bool:
        return self.action == "Q"

    @property
    def is_trade(self) -> bool:
        return self.action == "T"


@dataclass(frozen=True)
class L2Fill:
    order_id: str
    side: L2OrderSide
    order_type: L2OrderType
    fill_time: pd.Timestamp
    event_seq: int
    quantity: float
    price: float
    liquidity: str
    reason: str
    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    spread_points: float
    queue_ahead_before: float = np.nan
    depth_exhausted: bool = False
    tag: str = ""


@dataclass(frozen=True)
class L2ExecutionResult:
    orders: pd.DataFrame
    fills: pd.DataFrame
    summary: pd.DataFrame
    report_md: str


class L2ExecutionBroker:
    def __init__(self, engine: "L2ExecutionEngine") -> None:
        self._engine = engine

    def submit_order(self, order: L2Order) -> str:
        return self._engine.submit_order(order)

    def submit_market(
        self,
        side: L2OrderSide,
        quantity: float,
        *,
        tag: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self.submit_order(
            L2Order(
                side=side,
                quantity=float(quantity),
                order_type="market",
                time_in_force="ioc",
                tag=tag,
                metadata=dict(metadata or {}),
            )
        )

    def submit_limit(
        self,
        side: L2OrderSide,
        quantity: float,
        limit_price: float,
        *,
        post_only: bool = False,
        tag: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self.submit_order(
            L2Order(
                side=side,
                quantity=float(quantity),
                order_type="limit",
                limit_price=float(limit_price),
                post_only=bool(post_only),
                tag=tag,
                metadata=dict(metadata or {}),
            )
        )

    def submit_stop_market(
        self,
        side: L2OrderSide,
        quantity: float,
        stop_price: float,
        *,
        tag: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self.submit_order(
            L2Order(
                side=side,
                quantity=float(quantity),
                order_type="stop_market",
                stop_price=float(stop_price),
                tag=tag,
                metadata=dict(metadata or {}),
            )
        )


class L2ExecutionEngine:
    """
    Event-driven top-book execution simulator for decoded L2 quote/trade rows.

    The engine intentionally consumes guarded top-book rows, not OHLCV bars. It
    supports orderflow strategies through a callback that sees one market event
    at a time and submits orders through L2ExecutionBroker. Orders submitted by
    the callback cannot fill on the same event that created them.
    """

    def __init__(
        self,
        topbook_events: pd.DataFrame,
        *,
        config: L2ExecutionConfig | None = None,
    ) -> None:
        self.config = config or L2ExecutionConfig()
        self.events = prepare_l2_execution_events(topbook_events, tick_size=self.config.tick_size)
        self.broker = L2ExecutionBroker(self)
        self.orders: dict[str, L2Order] = {}
        self.fills: list[L2Fill] = []
        self._scheduled_orders: list[L2Order] = []
        self._current_event: L2MarketEvent | None = None
        self._next_order_number = 1
        self._is_running = False

    def submit_order(self, order: L2Order) -> str:
        order_id = self._assign_order_id(order)
        _validate_order(order)
        if not self._is_running or self._current_event is None:
            order.status = "scheduled"
            self._scheduled_orders.append(order)
            return order_id

        current = self._current_event
        order.submit_time = current.ts_event
        order.created_from_event_seq = current.event_seq
        self._accept_order(order, active_after_event_seq=current.event_seq + 1)
        return order_id

    def run(
        self,
        *,
        strategy: Callable[[L2MarketEvent, L2ExecutionBroker], None] | None = None,
        orders: Iterable[L2Order] | None = None,
    ) -> L2ExecutionResult:
        for order in orders or ():
            self.submit_order(order)

        self._is_running = True
        scheduled = sorted(self._scheduled_orders, key=lambda item: _timestamp_or_min(item.submit_time))
        self._scheduled_orders = []
        schedule_idx = 0

        for row in self.events.itertuples(index=False):
            event = _market_event_from_row(row)
            self._current_event = event

            while schedule_idx < len(scheduled):
                candidate = scheduled[schedule_idx]
                submit_time = _timestamp_or_min(candidate.submit_time)
                if submit_time > event.ts_event:
                    break
                active_event_seq = event.event_seq if submit_time < event.ts_event else event.event_seq + 1
                self._accept_order(candidate, active_after_event_seq=active_event_seq)
                schedule_idx += 1

            self._process_active_orders(event)
            if strategy is not None:
                strategy(event, self.broker)

        self._is_running = False
        self._current_event = None

        for order in self.orders.values():
            if order.status in {"accepted", "active"}:
                order.status = "open"

        orders_frame = orders_to_frame(self.orders.values())
        fills_frame = fills_to_frame(self.fills)
        summary = summarize_l2_execution(orders_frame, fills_frame)
        return L2ExecutionResult(
            orders=orders_frame,
            fills=fills_frame,
            summary=summary,
            report_md=render_l2_execution_report(summary, orders_frame, fills_frame),
        )

    def _assign_order_id(self, order: L2Order) -> str:
        if order.order_id:
            if order.order_id in self.orders or any(item.order_id == order.order_id for item in self._scheduled_orders):
                raise ValueError(f"Duplicate L2 order_id: {order.order_id}")
            return order.order_id
        order.order_id = f"L2O{self._next_order_number:06d}"
        self._next_order_number += 1
        return order.order_id

    def _accept_order(self, order: L2Order, *, active_after_event_seq: int) -> None:
        latency = pd.Timedelta(self.config.latency)
        if order.submit_time is None and self._current_event is not None:
            order.submit_time = self._current_event.ts_event
        submit_time = _to_utc_timestamp(order.submit_time)
        order.submit_time = submit_time
        order.active_after_time = submit_time + latency
        order.active_after_event_seq = int(active_after_event_seq)
        order.status = "accepted"
        self.orders[order.order_id] = order

    def _process_active_orders(self, event: L2MarketEvent) -> None:
        for order in list(self.orders.values()):
            if order.status not in {"accepted", "active"}:
                continue
            if order.active_after_time is not None and event.ts_event < order.active_after_time:
                continue
            if event.event_seq < int(order.active_after_event_seq):
                continue
            if order.status == "accepted":
                order.status = "active"
                order.first_active_event_seq = event.event_seq
                self._initialize_passive_queue(order, event)
                if order.status == "rejected":
                    continue

            if order.order_type == "market":
                self._fill_taking_order(order, event, reason="market_order")
            elif order.order_type == "limit":
                self._process_limit_order(order, event)
            elif order.order_type == "stop_market":
                self._process_stop_market_order(order, event)
            else:  # pragma: no cover - guarded by _validate_order
                raise ValueError(f"Unsupported L2 order type: {order.order_type}")

    def _initialize_passive_queue(self, order: L2Order, event: L2MarketEvent) -> None:
        if order.order_type != "limit" or order.limit_price is None:
            return
        limit = float(order.limit_price)
        if order.side == "buy":
            if _valid_price(event.ask_price) and limit >= event.ask_price:
                if order.post_only:
                    _reject_order(order, "post_only_order_would_cross")
                return
            if self.config.reject_non_topbook_limits and _valid_price(event.bid_price) and limit < event.bid_price:
                _reject_order(order, "non_topbook_limit_price")
                return
            order.queue_ahead = float(event.bid_size) * float(self.config.queue_ahead_multiplier) if np.isclose(limit, event.bid_price) else 0.0
        else:
            if _valid_price(event.bid_price) and limit <= event.bid_price:
                if order.post_only:
                    _reject_order(order, "post_only_order_would_cross")
                return
            if self.config.reject_non_topbook_limits and _valid_price(event.ask_price) and limit > event.ask_price:
                _reject_order(order, "non_topbook_limit_price")
                return
            order.queue_ahead = float(event.ask_size) * float(self.config.queue_ahead_multiplier) if np.isclose(limit, event.ask_price) else 0.0

    def _process_limit_order(self, order: L2Order, event: L2MarketEvent) -> None:
        if order.limit_price is None or order.remaining_quantity <= 0.0:
            return
        limit = float(order.limit_price)
        if order.side == "buy" and _valid_price(event.ask_price) and limit >= event.ask_price:
            self._fill_taking_order(order, event, reason="marketable_limit")
            return
        if order.side == "sell" and _valid_price(event.bid_price) and limit <= event.bid_price:
            self._fill_taking_order(order, event, reason="marketable_limit")
            return
        if not event.is_trade or not _valid_price(event.price) or event.size <= 0.0:
            return

        if order.side == "buy":
            if event.side != "A" or event.price > limit:
                return
            trade_through = event.price < limit
        else:
            if event.side != "B" or event.price < limit:
                return
            trade_through = event.price > limit

        if self.config.limit_fill_model == "trade_through":
            if trade_through:
                self._record_fill(order, event, order.remaining_quantity, limit, liquidity="passive", reason="limit_trade_through")
            return

        if self.config.limit_fill_model == "touch":
            self._record_fill(order, event, order.remaining_quantity, limit, liquidity="passive", reason="limit_touch")
            return

        if self.config.limit_fill_model != "queue":
            raise ValueError(f"Unsupported limit_fill_model: {self.config.limit_fill_model}")
        if trade_through:
            self._record_fill(order, event, order.remaining_quantity, limit, liquidity="passive", reason="limit_trade_through")
            return

        queue_before = 0.0 if not np.isfinite(order.queue_ahead) else max(float(order.queue_ahead), 0.0)
        fillable = max(float(event.size) - queue_before, 0.0)
        order.queue_ahead = max(queue_before - float(event.size), 0.0)
        if fillable > 0.0:
            self._record_fill(
                order,
                event,
                min(order.remaining_quantity, fillable),
                limit,
                liquidity="passive",
                reason="limit_queue_depleted",
                queue_ahead_before=queue_before,
            )

    def _process_stop_market_order(self, order: L2Order, event: L2MarketEvent) -> None:
        if order.stop_price is None:
            return
        stop = float(order.stop_price)
        if order.side == "buy":
            triggered = (_valid_price(event.ask_price) and event.ask_price >= stop) or (
                event.is_trade and _valid_price(event.price) and event.price >= stop
            )
        else:
            triggered = (_valid_price(event.bid_price) and event.bid_price <= stop) or (
                event.is_trade and _valid_price(event.price) and event.price <= stop
            )
        if triggered:
            self._fill_taking_order(order, event, reason="stop_market_triggered")

    def _fill_taking_order(self, order: L2Order, event: L2MarketEvent, *, reason: str) -> None:
        if self.config.reject_crossed_books and _book_crossed_or_locked(event):
            _reject_order(order, "crossed_or_locked_book")
            return
        price = event.ask_price if order.side == "buy" else event.bid_price
        displayed_size = event.ask_size if order.side == "buy" else event.bid_size
        if not _valid_price(price) or not np.isfinite(displayed_size) or displayed_size <= 0.0:
            _reject_order(order, "no_valid_topbook_depth")
            return
        requested = order.remaining_quantity
        fill_quantity = min(requested, float(displayed_size))
        if fill_quantity < requested and not self.config.allow_partial_fills:
            _reject_order(order, "insufficient_topbook_depth")
            return
        if fill_quantity > 0.0:
            self._record_fill(
                order,
                event,
                fill_quantity,
                float(price),
                liquidity="taking",
                reason=reason,
                depth_exhausted=fill_quantity >= float(displayed_size),
            )
        if order.remaining_quantity > 0.0 and order.order_type in {"market", "stop_market"}:
            order.status = "partial_cancelled" if order.filled_quantity > 0.0 else "cancelled"
            order.cancel_reason = "insufficient_topbook_depth"

    def _record_fill(
        self,
        order: L2Order,
        event: L2MarketEvent,
        quantity: float,
        price: float,
        *,
        liquidity: str,
        reason: str,
        queue_ahead_before: float = np.nan,
        depth_exhausted: bool = False,
    ) -> None:
        quantity = min(float(quantity), order.remaining_quantity)
        if quantity <= 0.0:
            return
        previous_qty = float(order.filled_quantity)
        previous_notional = 0.0 if not np.isfinite(order.avg_fill_price) else previous_qty * float(order.avg_fill_price)
        order.filled_quantity = previous_qty + quantity
        order.avg_fill_price = (previous_notional + quantity * float(price)) / order.filled_quantity
        if order.remaining_quantity <= 1e-12:
            order.status = "filled"
        self.fills.append(
            L2Fill(
                order_id=order.order_id,
                side=order.side,
                order_type=order.order_type,
                fill_time=event.ts_event,
                event_seq=event.event_seq,
                quantity=float(quantity),
                price=float(price),
                liquidity=liquidity,
                reason=reason,
                bid_price=event.bid_price,
                ask_price=event.ask_price,
                bid_size=event.bid_size,
                ask_size=event.ask_size,
                spread_points=event.spread_points,
                queue_ahead_before=queue_ahead_before,
                depth_exhausted=bool(depth_exhausted),
                tag=order.tag,
            )
        )


def prepare_l2_execution_events(topbook_events: pd.DataFrame, *, tick_size: float = 0.25) -> pd.DataFrame:
    if topbook_events.empty:
        return pd.DataFrame()
    required = ["ts_event", "action", "bid_px_00", "ask_px_00", "bid_sz_00", "ask_sz_00"]
    missing = [col for col in required if col not in topbook_events.columns]
    if missing:
        raise ValueError(f"L2 top-book events are missing required column(s): {', '.join(missing)}")
    out = topbook_events.copy()
    out["ts_event"] = pd.to_datetime(out["ts_event"], utc=True, errors="coerce")
    out = out.dropna(subset=["ts_event"]).sort_values("ts_event", kind="stable").reset_index(drop=True)
    out["event_seq"] = np.arange(len(out), dtype=int)
    for col in ("price", "size", "bid_px_00", "ask_px_00", "bid_sz_00", "ask_sz_00"):
        if col not in out.columns:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["action"] = out["action"].astype("string").fillna("")
    out["side"] = out.get("side", pd.Series("", index=out.index)).astype("string").fillna("").str.upper()
    out["spread_points"] = pd.to_numeric(out.get("spread_points"), errors="coerce")
    out["spread_points"] = out["spread_points"].where(out["spread_points"].notna(), out["ask_px_00"] - out["bid_px_00"])
    out["spread_ticks"] = out["spread_points"] / float(tick_size)
    return out


def simulate_l2_execution(
    topbook_events: pd.DataFrame,
    orders: Iterable[L2Order],
    *,
    config: L2ExecutionConfig | None = None,
) -> L2ExecutionResult:
    return L2ExecutionEngine(topbook_events, config=config).run(orders=orders)


def read_l2_order_schedule(path: Path | str) -> list[L2Order]:
    frame = pd.read_csv(path)
    orders: list[L2Order] = []
    for idx, row in frame.iterrows():
        order_type = str(row.get("order_type", "market") or "market")
        orders.append(
            L2Order(
                order_id=str(row.get("order_id", "") or ""),
                submit_time=row.get("submit_time"),
                side=str(row["side"]).lower(),  # type: ignore[arg-type]
                order_type=order_type,  # type: ignore[arg-type]
                quantity=float(row["quantity"]),
                limit_price=_optional_float(row.get("limit_price")),
                stop_price=_optional_float(row.get("stop_price")),
                time_in_force=str(row.get("time_in_force", "gtc") or "gtc"),
                post_only=bool(row.get("post_only", False)),
                tag=str(row.get("tag", f"order_{idx}") or ""),
            )
        )
    return orders


def write_l2_execution_result(
    result: L2ExecutionResult,
    out_dir: Path | str,
    *,
    prefix: str = "l2_execution",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "orders_csv": out_path / f"{prefix}_orders.csv",
        "fills_csv": out_path / f"{prefix}_fills.csv",
        "summary_csv": out_path / f"{prefix}_summary.csv",
        "report_md": out_path / f"{prefix}_report.md",
    }
    result.orders.to_csv(paths["orders_csv"], index=False)
    result.fills.to_csv(paths["fills_csv"], index=False)
    result.summary.to_csv(paths["summary_csv"], index=False)
    paths["report_md"].write_text(result.report_md, encoding="utf-8")
    return paths


def orders_to_frame(orders: Iterable[L2Order]) -> pd.DataFrame:
    rows = []
    for order in orders:
        rows.append(
            {
                "order_id": order.order_id,
                "side": order.side,
                "order_type": order.order_type,
                "quantity": float(order.quantity),
                "filled_quantity": float(order.filled_quantity),
                "remaining_quantity": float(order.remaining_quantity),
                "avg_fill_price": order.avg_fill_price,
                "submit_time": order.submit_time,
                "active_after_time": order.active_after_time,
                "active_after_event_seq": order.active_after_event_seq,
                "first_active_event_seq": order.first_active_event_seq,
                "limit_price": order.limit_price,
                "stop_price": order.stop_price,
                "time_in_force": order.time_in_force,
                "post_only": order.post_only,
                "status": order.status,
                "reject_reason": order.reject_reason,
                "cancel_reason": order.cancel_reason,
                "queue_ahead": order.queue_ahead,
                "tag": order.tag,
            }
        )
    return pd.DataFrame(rows)


def fills_to_frame(fills: Iterable[L2Fill]) -> pd.DataFrame:
    return pd.DataFrame([fill.__dict__ for fill in fills])


def summarize_l2_execution(orders: pd.DataFrame, fills: pd.DataFrame) -> pd.DataFrame:
    if orders.empty:
        return pd.DataFrame(
            [
                {
                    "orders": 0,
                    "fills": 0,
                    "filled_orders": 0,
                    "rejected_orders": 0,
                    "cancelled_orders": 0,
                    "open_orders": 0,
                    "net_position": 0.0,
                    "taking_fill_qty": 0.0,
                    "passive_fill_qty": 0.0,
                    "depth_exhausted_fills": 0,
                }
            ]
        )
    status = orders["status"].astype(str)
    if fills.empty:
        net_position = taking_qty = passive_qty = 0.0
        depth_exhausted = 0
    else:
        side_sign = fills["side"].astype(str).map({"buy": 1.0, "sell": -1.0}).fillna(0.0)
        qty = pd.to_numeric(fills["quantity"], errors="coerce").fillna(0.0)
        net_position = float((side_sign * qty).sum())
        taking_qty = float(qty.where(fills["liquidity"].astype(str).eq("taking"), 0.0).sum())
        passive_qty = float(qty.where(fills["liquidity"].astype(str).eq("passive"), 0.0).sum())
        depth_exhausted = int(fills["depth_exhausted"].fillna(False).astype(bool).sum())
    return pd.DataFrame(
        [
            {
                "orders": int(len(orders)),
                "fills": int(len(fills)),
                "filled_orders": int(status.eq("filled").sum()),
                "rejected_orders": int(status.eq("rejected").sum()),
                "cancelled_orders": int(status.isin(["cancelled", "partial_cancelled"]).sum()),
                "open_orders": int(status.eq("open").sum()),
                "net_position": net_position,
                "taking_fill_qty": taking_qty,
                "passive_fill_qty": passive_qty,
                "depth_exhausted_fills": depth_exhausted,
            }
        ]
    )


def render_l2_execution_report(summary: pd.DataFrame, orders: pd.DataFrame, fills: pd.DataFrame) -> str:
    lines = [
        "# L2 Execution Simulation",
        "",
        "This is an event-driven execution simulation over guarded L2 top-book rows. It does not run the OHLCV bar backtest.",
        "",
    ]
    if summary.empty:
        lines.extend(["No execution summary was produced.", ""])
        return "\n".join(lines)
    row = summary.iloc[0]
    lines.extend(
        [
            "## Summary",
            "",
            f"- Orders: {int(row['orders']):,}",
            f"- Fills: {int(row['fills']):,}",
            f"- Filled orders: {int(row['filled_orders']):,}",
            f"- Rejected orders: {int(row['rejected_orders']):,}",
            f"- Cancelled/partial-cancelled orders: {int(row['cancelled_orders']):,}",
            f"- Open orders after replay: {int(row['open_orders']):,}",
            f"- Net position: {float(row['net_position']):.4g}",
            f"- Taking fill quantity: {float(row['taking_fill_qty']):.4g}",
            f"- Passive fill quantity: {float(row['passive_fill_qty']):.4g}",
            f"- Depth-exhausted taking fills: {int(row['depth_exhausted_fills']):,}",
            "",
            "## Guardrails",
            "",
            "- Orders submitted by a strategy callback are not eligible on the same event that created them.",
            "- Market and stop-market fills are constrained by displayed top-book depth.",
            "- Passive limit fills default to trade-through confirmation unless configured otherwise.",
            "- Non-top-book passive limits are rejected by default because the current replay layer has not accepted full-depth semantics yet.",
            "",
        ]
    )
    if not orders.empty:
        lines.extend(["## Order Status Counts", "", _counts_table(orders["status"]), ""])
    if not fills.empty:
        lines.extend(["## Fill Liquidity Counts", "", _counts_table(fills["liquidity"]), ""])
    return "\n".join(lines)


def _market_event_from_row(row: Any) -> L2MarketEvent:
    bid = _safe_row_float(row.bid_px_00)
    ask = _safe_row_float(row.ask_px_00)
    raw_spread = _safe_row_float(row.spread_points)
    spread = raw_spread if np.isfinite(raw_spread) else ask - bid
    return L2MarketEvent(
        event_seq=int(row.event_seq),
        ts_event=pd.Timestamp(row.ts_event),
        action=str(row.action),
        side=str(row.side),
        price=_safe_row_float(row.price),
        size=_safe_row_float(row.size),
        bid_price=bid,
        ask_price=ask,
        bid_size=_safe_row_float(row.bid_sz_00),
        ask_size=_safe_row_float(row.ask_sz_00),
        spread_points=spread,
        row=pd.Series(row._asdict()),
    )


def _validate_order(order: L2Order) -> None:
    if order.side not in {"buy", "sell"}:
        raise ValueError(f"Unsupported L2 order side: {order.side}")
    if order.order_type not in {"market", "limit", "stop_market"}:
        raise ValueError(f"Unsupported L2 order type: {order.order_type}")
    if float(order.quantity) <= 0.0:
        raise ValueError("L2 order quantity must be positive")
    if order.order_type == "limit" and order.limit_price is None:
        raise ValueError("Limit orders require limit_price")
    if order.order_type == "stop_market" and order.stop_price is None:
        raise ValueError("Stop-market orders require stop_price")
    if order.order_type == "market":
        order.time_in_force = "ioc"


def _reject_order(order: L2Order, reason: str) -> None:
    order.status = "rejected"
    order.reject_reason = reason


def _valid_price(value: float) -> bool:
    return bool(np.isfinite(value) and value > 0.0)


def _book_crossed_or_locked(event: L2MarketEvent) -> bool:
    return bool(_valid_price(event.bid_price) and _valid_price(event.ask_price) and event.ask_price <= event.bid_price)


def _to_utc_timestamp(value: pd.Timestamp | str | None) -> pd.Timestamp:
    if value is None or pd.isna(value):
        raise ValueError("L2 order submit_time is required outside a running strategy callback")
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _timestamp_or_min(value: pd.Timestamp | str | None) -> pd.Timestamp:
    if value is None or pd.isna(value):
        return pd.Timestamp.min.tz_localize("UTC")
    return _to_utc_timestamp(value)


def _optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value) or value == "":
        return None
    return float(value)


def _safe_row_float(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return np.nan
    return out if np.isfinite(out) else np.nan


def _counts_table(series: pd.Series) -> str:
    counts = series.astype(str).value_counts(dropna=False).sort_index()
    lines = ["| value | count |", "| --- | --- |"]
    for key, value in counts.items():
        lines.append(f"| {key} | {int(value)} |")
    return "\n".join(lines)
