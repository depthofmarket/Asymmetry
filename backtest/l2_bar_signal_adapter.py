from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from backtest.l2_execution_engine import L2MarketEvent

if TYPE_CHECKING:
    from backtest.l2_orderflow_replay import L2OrderFlowContext


@dataclass(frozen=True)
class L2BarSignalAdapterConfig:
    signals_csv: str = ""
    signal_col: str = "candidate_signal"
    time_col: str = "time"
    quantity: float = 1.0
    quantity_col: str = ""
    entry_mode: str = "next_bar_open"
    entry_delay_bars: int = 0
    bar_minutes: int = 5
    signal_timezone: str = "America/New_York"
    max_signals: int | None = None
    one_position_at_a_time: bool = True
    allow_long: bool = True
    allow_short: bool = True
    stop_loss_points: float = 0.0
    profit_target_points: float = 0.0
    max_hold: str = ""
    max_hold_bars: int = 0
    flatten_at_time: str = ""
    name: str = "bar_signal_csv"


@dataclass(frozen=True)
class L2ScheduledBarSignal:
    signal_id: str
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    direction: str
    side: str
    quantity: float
    signal_value: float
    signal_type: str
    setup_tag: str
    source_row: int


@dataclass
class _OpenL2SignalTrade:
    direction: str
    quantity: float
    entry_price: float
    entry_time: pd.Timestamp
    signal_time: pd.Timestamp
    signal_id: str
    setup_tag: str


class L2BarSignalAdapterStrategy:
    """
    Convert point-in-time bar signals into L2 market orders.

    This is an execution adapter. It does not rebuild or optimize the signal.
    It consumes an existing prepared signal CSV, schedules entries according to
    the bar-engine timing rule, then lets the L2 replay layer own fills.
    """

    def __init__(self, **kwargs: Any) -> None:
        cfg = L2BarSignalAdapterConfig(**kwargs)
        if not cfg.signals_csv:
            raise ValueError("bar_signal_csv strategy requires signals_csv")
        self.config = cfg
        self.name = cfg.name
        frame = pd.read_csv(cfg.signals_csv)
        self.signals = build_l2_scheduled_bar_signals(frame, config=cfg)
        self._next_signal_idx = 0
        self._fill_cursor = 0
        self._open_trade: _OpenL2SignalTrade | None = None
        self._entry_accumulators: dict[str, dict[str, Any]] = {}

    def on_start(self, context: L2OrderFlowContext) -> None:
        context.log(
            "bar_signal_adapter_loaded",
            signals_csv=self.config.signals_csv,
            scheduled_signals=len(self.signals),
            signal_col=self.config.signal_col,
            entry_mode=self.config.entry_mode,
        )

    def on_event(self, event: L2MarketEvent, context: L2OrderFlowContext) -> None:
        self._sync_fills(context)
        self._submit_due_entries(event, context)
        self._submit_due_exit(event, context)

    def on_finish(self, context: L2OrderFlowContext, _execution) -> None:
        self._sync_fills(context)
        context.log(
            "bar_signal_adapter_finished",
            scheduled_signals=len(self.signals),
            submitted_signals=self._next_signal_idx,
            final_position=context.position,
        )

    def _submit_due_entries(self, event: L2MarketEvent, context: L2OrderFlowContext) -> None:
        while self._next_signal_idx < len(self.signals):
            signal = self.signals[self._next_signal_idx]
            if signal.entry_time > event.ts_event:
                break
            self._next_signal_idx += 1

            if signal.direction == "long" and not self.config.allow_long:
                context.log("bar_signal_skipped", signal_id=signal.signal_id, reason="long_disabled")
                continue
            if signal.direction == "short" and not self.config.allow_short:
                context.log("bar_signal_skipped", signal_id=signal.signal_id, reason="short_disabled")
                continue
            if self.config.one_position_at_a_time and (not context.flat or context.active_order_count > 0):
                context.log(
                    "bar_signal_skipped",
                    signal_id=signal.signal_id,
                    reason="position_or_order_open",
                    direction=signal.direction,
                )
                continue

            order_id = context.submit_market(
                signal.side,
                signal.quantity,
                tag=f"bar_signal_entry:{signal.signal_id}:{signal.setup_tag}",
                metadata={
                    "adapter": self.name,
                    "signal_id": signal.signal_id,
                    "signal_time": signal.signal_time.isoformat(),
                    "entry_time": signal.entry_time.isoformat(),
                    "direction": signal.direction,
                    "signal_type": signal.signal_type,
                    "setup_tag": signal.setup_tag,
                    "source_row": signal.source_row,
                },
            )
            context.log(
                "bar_signal_entry_submitted",
                order_id=order_id,
                signal_id=signal.signal_id,
                signal_time=signal.signal_time,
                entry_time=signal.entry_time,
                direction=signal.direction,
                side=signal.side,
                quantity=signal.quantity,
                setup_tag=signal.setup_tag,
            )

    def _submit_due_exit(self, event: L2MarketEvent, context: L2OrderFlowContext) -> None:
        if self._open_trade is None or context.flat or context.active_order_count > 0:
            return
        reason = self._exit_reason(event)
        if not reason:
            return

        side = "sell" if context.position > 0.0 else "buy"
        quantity = abs(float(context.position))
        order_id = context.submit_market(
            side,
            quantity,
            tag=f"bar_signal_exit:{reason}:{self._open_trade.signal_id}",
            metadata={
                "adapter": self.name,
                "exit_reason": reason,
                "entry_signal_id": self._open_trade.signal_id,
                "entry_time": self._open_trade.entry_time.isoformat(),
                "entry_price": self._open_trade.entry_price,
            },
        )
        context.log(
            "bar_signal_exit_submitted",
            order_id=order_id,
            reason=reason,
            side=side,
            quantity=quantity,
            entry_signal_id=self._open_trade.signal_id,
            entry_price=self._open_trade.entry_price,
        )

    def _exit_reason(self, event: L2MarketEvent) -> str:
        trade = self._open_trade
        if trade is None:
            return ""

        if self.config.flatten_at_time:
            event_ny = event.ts_event.tz_convert("America/New_York")
            if event_ny.strftime("%H:%M") >= self.config.flatten_at_time:
                return "flatten_at_time"

        max_hold = _max_hold_delta(self.config)
        if max_hold is not None and event.ts_event >= trade.entry_time + max_hold:
            return "max_hold"

        stop = float(self.config.stop_loss_points or 0.0)
        target = float(self.config.profit_target_points or 0.0)
        if trade.direction == "long":
            if stop > 0.0 and np.isfinite(event.bid_price) and event.bid_price <= trade.entry_price - stop:
                return "stop_loss"
            if target > 0.0 and np.isfinite(event.bid_price) and event.bid_price >= trade.entry_price + target:
                return "profit_target"
        else:
            if stop > 0.0 and np.isfinite(event.ask_price) and event.ask_price >= trade.entry_price + stop:
                return "stop_loss"
            if target > 0.0 and np.isfinite(event.ask_price) and event.ask_price <= trade.entry_price - target:
                return "profit_target"
        return ""

    def _sync_fills(self, context: L2OrderFlowContext) -> None:
        while self._fill_cursor < len(context.fills):
            fill = context.fills[self._fill_cursor]
            self._fill_cursor += 1
            tag = str(fill.tag or "")
            if tag.startswith("bar_signal_entry:"):
                self._record_entry_fill(fill, context)
            elif tag.startswith("bar_signal_exit:") and context.flat:
                self._open_trade = None

        if context.flat:
            self._open_trade = None

    def _record_entry_fill(self, fill, context: L2OrderFlowContext) -> None:
        parts = str(fill.tag).split(":")
        signal_id = parts[1] if len(parts) > 1 else fill.order_id
        setup_tag = parts[2] if len(parts) > 2 else ""
        accumulator = self._entry_accumulators.setdefault(
            fill.order_id,
            {
                "quantity": 0.0,
                "notional": 0.0,
                "side": fill.side,
                "signal_id": signal_id,
                "setup_tag": setup_tag,
                "entry_time": fill.fill_time,
            },
        )
        quantity = float(fill.quantity)
        accumulator["quantity"] += quantity
        accumulator["notional"] += quantity * float(fill.price)
        accumulator["entry_time"] = fill.fill_time
        avg_price = accumulator["notional"] / accumulator["quantity"]
        direction = "long" if str(accumulator["side"]) == "buy" else "short"
        signal_time = _signal_time_from_id(signal_id, fallback=fill.fill_time)
        self._open_trade = _OpenL2SignalTrade(
            direction=direction,
            quantity=abs(float(context.position)),
            entry_price=float(avg_price),
            entry_time=pd.Timestamp(fill.fill_time),
            signal_time=signal_time,
            signal_id=signal_id,
            setup_tag=str(accumulator["setup_tag"]),
        )


def build_l2_scheduled_bar_signals(
    frame: pd.DataFrame,
    *,
    config: L2BarSignalAdapterConfig | None = None,
) -> list[L2ScheduledBarSignal]:
    cfg = config or L2BarSignalAdapterConfig()
    if frame.empty:
        return []
    if cfg.time_col not in frame.columns:
        raise ValueError(f"signal CSV is missing time column: {cfg.time_col}")
    signal_col = cfg.signal_col if cfg.signal_col in frame.columns else "signal"
    if signal_col not in frame.columns:
        raise ValueError(f"signal CSV is missing signal column: {cfg.signal_col}")

    df = frame.copy().reset_index(drop=True)
    df["_signal_time"] = pd.to_datetime(df[cfg.time_col], errors="coerce")
    df["_signal_value"] = pd.to_numeric(df[signal_col], errors="coerce").fillna(0.0)
    df = df.dropna(subset=["_signal_time"]).reset_index(drop=True)
    active_indices = list(df.index[df["_signal_value"].ne(0.0)])
    if cfg.max_signals is not None:
        active_indices = active_indices[: max(0, int(cfg.max_signals))]

    signals: list[L2ScheduledBarSignal] = []
    for idx in active_indices:
        entry_idx, entry_time = _entry_time_for_row(df, idx, config=cfg)
        if entry_time is None:
            continue
        direction = _direction_for_row(df.iloc[idx], signal_value=float(df.at[idx, "_signal_value"]))
        if not direction:
            continue
        quantity = _quantity_for_row(df.iloc[idx], config=cfg)
        if quantity <= 0.0:
            continue
        signal_type = str(df.at[idx, "signal_type"]) if "signal_type" in df.columns else ""
        setup_tag = str(df.at[idx, "setup_tag"]) if "setup_tag" in df.columns else _setup_tag(signal_type, direction)
        signal_time_utc = _timestamp_to_utc(df.at[idx, "_signal_time"], timezone=cfg.signal_timezone)
        entry_time_utc = _timestamp_to_utc(entry_time, timezone=cfg.signal_timezone)
        signal_id = f"{signal_time_utc.strftime('%Y%m%dT%H%M%S')}_{idx}_{direction}"
        signals.append(
            L2ScheduledBarSignal(
                signal_id=signal_id,
                signal_time=signal_time_utc,
                entry_time=entry_time_utc,
                direction=direction,
                side="buy" if direction == "long" else "sell",
                quantity=quantity,
                signal_value=float(df.at[idx, "_signal_value"]),
                signal_type=signal_type,
                setup_tag=setup_tag,
                source_row=int(idx),
            )
        )
        _ = entry_idx
    return sorted(signals, key=lambda item: (item.entry_time, item.signal_id))


def _entry_time_for_row(
    df: pd.DataFrame,
    idx: int,
    *,
    config: L2BarSignalAdapterConfig,
) -> tuple[int, pd.Timestamp | None]:
    delay = max(0, int(config.entry_delay_bars or 0))
    mode = str(config.entry_mode or "next_bar_open")
    if mode == "next_bar_open":
        entry_idx = idx + 1 + delay
        if entry_idx >= len(df):
            return entry_idx, None
        return entry_idx, pd.Timestamp(df.at[entry_idx, "_signal_time"])
    if mode == "same_bar_close":
        if delay > 0:
            entry_idx = idx + delay
            if entry_idx >= len(df):
                return entry_idx, None
            return entry_idx, pd.Timestamp(df.at[entry_idx, "_signal_time"])
        return idx, pd.Timestamp(df.at[idx, "_signal_time"]) + pd.Timedelta(minutes=int(config.bar_minutes))
    raise ValueError(f"unsupported entry_mode for L2 bar signal adapter: {mode}")


def _direction_for_row(row: pd.Series, *, signal_value: float) -> str:
    raw_direction = str(row.get("direction", "") or "").lower()
    if raw_direction in {"long", "buy"}:
        return "long"
    if raw_direction in {"short", "sell"}:
        return "short"
    if signal_value > 0.0:
        return "long"
    if signal_value < 0.0:
        return "short"
    return ""


def _quantity_for_row(row: pd.Series, *, config: L2BarSignalAdapterConfig) -> float:
    if config.quantity_col and config.quantity_col in row.index:
        try:
            value = float(row[config.quantity_col])
        except (TypeError, ValueError):
            value = np.nan
        if np.isfinite(value) and value > 0.0:
            return value
    return float(config.quantity)


def _timestamp_to_utc(value: pd.Timestamp | str, *, timezone: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(timezone).tz_convert("UTC")
    return ts.tz_convert("UTC")


def _max_hold_delta(config: L2BarSignalAdapterConfig) -> pd.Timedelta | None:
    if config.max_hold:
        return pd.Timedelta(config.max_hold)
    if int(config.max_hold_bars or 0) > 0:
        return pd.Timedelta(minutes=int(config.max_hold_bars) * int(config.bar_minutes))
    return None


def _signal_time_from_id(signal_id: str, *, fallback: pd.Timestamp) -> pd.Timestamp:
    raw = str(signal_id).split("_", 1)[0]
    try:
        return pd.to_datetime(raw, format="%Y%m%dT%H%M%S").tz_localize("UTC")
    except Exception:
        return pd.Timestamp(fallback)


def _setup_tag(signal_type: str, direction: str) -> str:
    return f"{signal_type}_{direction}" if signal_type else direction


__all__ = [
    "L2BarSignalAdapterConfig",
    "L2BarSignalAdapterStrategy",
    "L2ScheduledBarSignal",
    "build_l2_scheduled_bar_signals",
]
