from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from backtest.l2_execution_engine import L2MarketEvent

if TYPE_CHECKING:
    from backtest.l2_orderflow_replay import L2OrderFlowContext


@dataclass(frozen=True)
class L2TapeReadOrderFlowConfig:
    """
    Conservative event-driven orderflow scaffold.

    The defaults are intentionally guard-heavy. Treat them as a starting shape
    for encoding a discretionary process, not as a validated strategy.
    """

    quantity: float = 1.0
    allow_long: bool = True
    allow_short: bool = True
    trade_start: str = "09:30"
    trade_end: str = "16:00"
    flatten_at_time: str = "15:55"
    window: str = "3s"
    cooldown: str = "10s"
    max_trades_per_day: int = 3
    min_trade_events: int = 5
    min_trade_size: float = 20.0
    min_aggressive_delta: float = 0.55
    min_topbook_imbalance: float = 0.35
    min_price_momentum_points: float = 0.0
    max_spread_ticks: float = 4.0
    stop_loss_points: float = 3.0
    profit_target_points: float = 5.0
    max_hold: str = "45s"
    exit_on_opposite_flow: bool = True
    opposite_delta: float = 0.35
    opposite_imbalance: float = 0.20
    one_position_at_a_time: bool = True
    location_context_csv: str = ""
    location_time_col: str = "time"
    location_timezone: str = "America/New_York"
    location_mode: str = "off"
    location_max_age: str = "1D"
    location_proximity_points: float = 4.0
    gex_wall_proximity_points: float = 10.0
    trend_breakout_buffer_points: float = 2.0
    allow_location_trend_trades: bool = True
    profile_lower_col: str = "profile_lower"
    profile_upper_col: str = "profile_upper"
    profile_poc_col: str = "profile_poc"
    gex_wall_col: str = "options_gamma_wall_strike"
    gamma_environment_col: str = "options_gamma_environment"
    trigger_context_csv: str = ""
    trigger_time_col: str = "time"
    trigger_timezone: str = "America/New_York"
    trigger_mode: str = "off"
    trigger_max_age: str = "5min"
    long_trigger_col: str = "mw_any_long_trigger"
    short_trigger_col: str = "mw_any_short_trigger"
    name: str = "tape_read_orderflow"


@dataclass(frozen=True)
class _TradePrint:
    ts_event: pd.Timestamp
    side: str
    size: float
    price: float


@dataclass(frozen=True)
class _FlowSnapshot:
    trade_count: int
    total_size: float
    buy_size: float
    sell_size: float
    aggressive_delta: float
    price_change_points: float
    topbook_imbalance: float
    spread_ticks: float


@dataclass(frozen=True)
class _LocationSnapshot:
    is_available: bool
    is_fresh: bool
    context_time: pd.Timestamp | None
    age: pd.Timedelta | None
    mid_price: float
    lower_level: float
    upper_level: float
    poc_level: float
    gex_wall: float
    gamma_environment: str
    near_lower: bool
    near_upper: bool
    above_upper: bool
    below_lower: bool

    @property
    def active(self) -> bool:
        return self.is_available and self.is_fresh

    def as_log_fields(self) -> dict[str, object]:
        return {
            "location_available": self.is_available,
            "location_fresh": self.is_fresh,
            "location_context_time": self.context_time,
            "location_age_seconds": self.age.total_seconds() if self.age is not None else np.nan,
            "location_mid_price": self.mid_price,
            "location_lower_level": self.lower_level,
            "location_upper_level": self.upper_level,
            "location_poc_level": self.poc_level,
            "location_gex_wall": self.gex_wall,
            "location_gamma_environment": self.gamma_environment,
            "location_near_lower": self.near_lower,
            "location_near_upper": self.near_upper,
            "location_above_upper": self.above_upper,
            "location_below_lower": self.below_lower,
        }


@dataclass(frozen=True)
class _TriggerSnapshot:
    is_available: bool
    is_fresh: bool
    context_time: pd.Timestamp | None
    age: pd.Timedelta | None
    mode: str
    long_ok: bool
    short_ok: bool
    long_trigger_col: str
    short_trigger_col: str

    @property
    def active(self) -> bool:
        return self.is_available and self.is_fresh

    def as_log_fields(self) -> dict[str, object]:
        return {
            "trigger_available": self.is_available,
            "trigger_fresh": self.is_fresh,
            "trigger_context_time": self.context_time,
            "trigger_age_seconds": self.age.total_seconds() if self.age is not None else np.nan,
            "trigger_mode": self.mode,
            "trigger_long_ok": self.long_ok,
            "trigger_short_ok": self.short_ok,
            "trigger_long_col": self.long_trigger_col,
            "trigger_short_col": self.short_trigger_col,
        }


@dataclass
class _OpenTapeTrade:
    direction: str
    quantity: float
    entry_price: float
    entry_time: pd.Timestamp
    order_id: str


class L2TapeReadOrderFlowStrategy:
    """
    Encode a discretionary tape-read idea as deterministic L2 rules.

    Entry requires aggressive trade imbalance and same-direction top-book
    imbalance inside a recent event window. Exits are explicit: stop, target,
    max hold, opposite flow, or end-of-session flatten.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.config = L2TapeReadOrderFlowConfig(**kwargs)
        if self.config.location_mode not in {"off", "mean_reversion", "mean_reversion_or_trend"}:
            raise ValueError("location_mode must be one of: off, mean_reversion, mean_reversion_or_trend")
        if self.config.trigger_mode not in {"off", "any", "orderflow", "absorption", "initiative", "configured"}:
            raise ValueError("trigger_mode must be one of: off, any, orderflow, absorption, initiative, configured")
        self.name = self.config.name
        self._location_context = _LocationContext(self.config)
        self._trigger_context = _TriggerContext(self.config)
        self._trades: deque[_TradePrint] = deque()
        self._fill_cursor = 0
        self._open_trade: _OpenTapeTrade | None = None
        self._entry_accumulators: dict[str, dict[str, Any]] = {}
        self._next_action_time = pd.Timestamp.min.tz_localize("UTC")
        self._current_trade_date: object | None = None
        self._day_entry_count = 0
        self._entry_number = 0

    def on_start(self, context: L2OrderFlowContext) -> None:
        context.log(
            "tape_read_loaded",
            window=self.config.window,
            min_trade_events=self.config.min_trade_events,
            min_trade_size=self.config.min_trade_size,
            min_aggressive_delta=self.config.min_aggressive_delta,
            min_topbook_imbalance=self.config.min_topbook_imbalance,
            max_spread_ticks=self.config.max_spread_ticks,
            location_mode=self.config.location_mode,
            location_context_csv=self.config.location_context_csv,
            location_rows=len(self._location_context),
            trigger_mode=self.config.trigger_mode,
            trigger_context_csv=self.config.trigger_context_csv,
            trigger_rows=len(self._trigger_context),
        )

    def on_event(self, event: L2MarketEvent, context: L2OrderFlowContext) -> None:
        self._reset_day_if_needed(event)
        self._sync_fills(context)
        self._record_event(event, context)
        snapshot = self._flow_snapshot(event, context)
        location = self._location_context.snapshot(event, self.config)
        trigger = self._trigger_context.snapshot(event, self.config)
        self._submit_due_exit(event, context, snapshot, location)
        self._submit_due_entry(event, context, snapshot, location, trigger)

    def on_finish(self, context: L2OrderFlowContext, _execution: object) -> None:
        self._sync_fills(context)
        context.log(
            "tape_read_finished",
            final_position=context.position,
            open_trade=self._open_trade is not None,
            day_entry_count=self._day_entry_count,
        )

    def _submit_due_entry(
        self,
        event: L2MarketEvent,
        context: L2OrderFlowContext,
        snapshot: _FlowSnapshot,
        location: _LocationSnapshot,
        trigger: _TriggerSnapshot,
    ) -> None:
        if not self._entry_gate(event, context, snapshot, location, trigger):
            return

        side = ""
        direction = ""
        setup_type = ""
        if self.config.allow_long and self._long_setup(snapshot, location, trigger):
            side = "buy"
            direction = "long"
            setup_type = self._location_setup_type("long", location)
        elif self.config.allow_short and self._short_setup(snapshot, location, trigger):
            side = "sell"
            direction = "short"
            setup_type = self._location_setup_type("short", location)
        else:
            return

        self._entry_number += 1
        order_id = context.submit_market(
            side,
            float(self.config.quantity),
            tag=f"tape_read_entry:{direction}:{self._entry_number}",
            metadata={
                "strategy": self.name,
                "direction": direction,
                "aggressive_delta": snapshot.aggressive_delta,
                "topbook_imbalance": snapshot.topbook_imbalance,
                "price_change_points": snapshot.price_change_points,
                "trade_count": snapshot.trade_count,
                "total_trade_size": snapshot.total_size,
                "setup_type": setup_type,
                **location.as_log_fields(),
                **trigger.as_log_fields(),
            },
        )
        self._day_entry_count += 1
        self._next_action_time = event.ts_event + pd.Timedelta(self.config.cooldown)
        context.log(
            "tape_read_entry_submitted",
            order_id=order_id,
            side=side,
            direction=direction,
            quantity=float(self.config.quantity),
            aggressive_delta=snapshot.aggressive_delta,
            topbook_imbalance=snapshot.topbook_imbalance,
            price_change_points=snapshot.price_change_points,
            trade_count=snapshot.trade_count,
            total_trade_size=snapshot.total_size,
            setup_type=setup_type,
            **location.as_log_fields(),
            **trigger.as_log_fields(),
        )

    def _submit_due_exit(
        self,
        event: L2MarketEvent,
        context: L2OrderFlowContext,
        snapshot: _FlowSnapshot,
        location: _LocationSnapshot,
    ) -> None:
        if self._open_trade is None or context.flat or context.active_order_count > 0:
            return
        reason = self._exit_reason(event, snapshot)
        if not reason:
            return

        side = "sell" if context.position > 0.0 else "buy"
        quantity = abs(float(context.position))
        order_id = context.submit_market(
            side,
            quantity,
            tag=f"tape_read_exit:{reason}:{self._open_trade.order_id}",
            metadata={
                "strategy": self.name,
                "exit_reason": reason,
                "entry_order_id": self._open_trade.order_id,
                "entry_price": self._open_trade.entry_price,
                "entry_time": self._open_trade.entry_time.isoformat(),
                **location.as_log_fields(),
            },
        )
        self._next_action_time = event.ts_event + pd.Timedelta(self.config.cooldown)
        context.log(
            "tape_read_exit_submitted",
            order_id=order_id,
            side=side,
            quantity=quantity,
            reason=reason,
            entry_order_id=self._open_trade.order_id,
            entry_price=self._open_trade.entry_price,
            aggressive_delta=snapshot.aggressive_delta,
            topbook_imbalance=snapshot.topbook_imbalance,
            **location.as_log_fields(),
        )

    def _entry_gate(
        self,
        event: L2MarketEvent,
        context: L2OrderFlowContext,
        snapshot: _FlowSnapshot,
        location: _LocationSnapshot,
        trigger: _TriggerSnapshot,
    ) -> bool:
        if event.ts_event < self._next_action_time:
            return False
        if self.config.one_position_at_a_time and (not context.flat or context.active_order_count > 0):
            return False
        if int(self.config.max_trades_per_day) > 0 and self._day_entry_count >= int(self.config.max_trades_per_day):
            return False
        if not _within_session(event, self.config.trade_start, self.config.trade_end):
            return False
        if not np.isfinite(snapshot.spread_ticks) or snapshot.spread_ticks > float(self.config.max_spread_ticks):
            return False
        if snapshot.trade_count < int(self.config.min_trade_events):
            return False
        if snapshot.total_size < float(self.config.min_trade_size):
            return False
        if self.config.location_mode != "off" and not location.active:
            return False
        if self.config.trigger_mode != "off" and not trigger.active:
            return False
        return True

    def _long_setup(self, snapshot: _FlowSnapshot, location: _LocationSnapshot, trigger: _TriggerSnapshot) -> bool:
        flow_ok = (
            snapshot.aggressive_delta >= float(self.config.min_aggressive_delta)
            and snapshot.topbook_imbalance >= float(self.config.min_topbook_imbalance)
            and snapshot.price_change_points >= float(self.config.min_price_momentum_points)
        )
        if not flow_ok:
            return False
        if not self._trigger_allows("long", trigger):
            return False
        if self.config.location_mode == "off":
            return True
        if location.near_lower:
            return True
        return self._location_trend_enabled() and location.above_upper

    def _short_setup(self, snapshot: _FlowSnapshot, location: _LocationSnapshot, trigger: _TriggerSnapshot) -> bool:
        flow_ok = (
            snapshot.aggressive_delta <= -float(self.config.min_aggressive_delta)
            and snapshot.topbook_imbalance <= -float(self.config.min_topbook_imbalance)
            and snapshot.price_change_points <= -float(self.config.min_price_momentum_points)
        )
        if not flow_ok:
            return False
        if not self._trigger_allows("short", trigger):
            return False
        if self.config.location_mode == "off":
            return True
        if location.near_upper:
            return True
        return self._location_trend_enabled() and location.below_lower

    def _trigger_allows(self, direction: str, trigger: _TriggerSnapshot) -> bool:
        if self.config.trigger_mode == "off":
            return True
        if not trigger.active:
            return False
        if direction == "long":
            return bool(trigger.long_ok)
        return bool(trigger.short_ok)

    def _location_trend_enabled(self) -> bool:
        return bool(self.config.allow_location_trend_trades) and self.config.location_mode == "mean_reversion_or_trend"

    def _location_setup_type(self, direction: str, location: _LocationSnapshot) -> str:
        if self.config.location_mode == "off":
            return "flow_only"
        if direction == "long" and location.near_lower:
            return "profile_gex_mean_reversion_long"
        if direction == "short" and location.near_upper:
            return "profile_gex_mean_reversion_short"
        if direction == "long" and location.above_upper:
            return "profile_gex_trend_long"
        if direction == "short" and location.below_lower:
            return "profile_gex_trend_short"
        return "location_unknown"

    def _exit_reason(self, event: L2MarketEvent, snapshot: _FlowSnapshot) -> str:
        trade = self._open_trade
        if trade is None:
            return ""

        if self.config.flatten_at_time and _at_or_after_time(event, self.config.flatten_at_time):
            return "flatten_at_time"

        max_hold = _timedelta_or_none(self.config.max_hold)
        if max_hold is not None and event.ts_event >= trade.entry_time + max_hold:
            return "max_hold"

        stop = float(self.config.stop_loss_points or 0.0)
        target = float(self.config.profit_target_points or 0.0)
        if trade.direction == "long":
            if stop > 0.0 and np.isfinite(event.bid_price) and event.bid_price <= trade.entry_price - stop:
                return "stop_loss"
            if target > 0.0 and np.isfinite(event.bid_price) and event.bid_price >= trade.entry_price + target:
                return "profit_target"
            if self._opposite_short_flow(snapshot):
                return "opposite_flow"
        else:
            if stop > 0.0 and np.isfinite(event.ask_price) and event.ask_price >= trade.entry_price + stop:
                return "stop_loss"
            if target > 0.0 and np.isfinite(event.ask_price) and event.ask_price <= trade.entry_price - target:
                return "profit_target"
            if self._opposite_long_flow(snapshot):
                return "opposite_flow"
        return ""

    def _opposite_short_flow(self, snapshot: _FlowSnapshot) -> bool:
        return bool(self.config.exit_on_opposite_flow) and (
            snapshot.aggressive_delta <= -float(self.config.opposite_delta)
            and snapshot.topbook_imbalance <= -float(self.config.opposite_imbalance)
        )

    def _opposite_long_flow(self, snapshot: _FlowSnapshot) -> bool:
        return bool(self.config.exit_on_opposite_flow) and (
            snapshot.aggressive_delta >= float(self.config.opposite_delta)
            and snapshot.topbook_imbalance >= float(self.config.opposite_imbalance)
        )

    def _record_event(self, event: L2MarketEvent, context: L2OrderFlowContext) -> None:
        if event.is_trade and np.isfinite(event.price) and event.size > 0.0:
            side = str(event.side).upper()
            spread_ticks = event.spread_points / context.tick_size if context.tick_size > 0 else np.nan
            if side in {"B", "A", "S"} and np.isfinite(spread_ticks) and spread_ticks <= float(self.config.max_spread_ticks):
                self._trades.append(
                    _TradePrint(
                        ts_event=event.ts_event,
                        side="B" if side == "B" else "A",
                        size=float(event.size),
                        price=float(event.price),
                    )
                )

        cutoff = event.ts_event - pd.Timedelta(self.config.window)
        while self._trades and self._trades[0].ts_event < cutoff:
            self._trades.popleft()

    def _flow_snapshot(self, event: L2MarketEvent, context: L2OrderFlowContext) -> _FlowSnapshot:
        buy_size = sum(item.size for item in self._trades if item.side == "B")
        sell_size = sum(item.size for item in self._trades if item.side == "A")
        total_size = buy_size + sell_size
        aggressive_delta = (buy_size - sell_size) / total_size if total_size > 0.0 else np.nan
        if len(self._trades) >= 2:
            price_change = self._trades[-1].price - self._trades[0].price
        else:
            price_change = 0.0
        spread_ticks = event.spread_points / context.tick_size if context.tick_size > 0 else np.nan
        return _FlowSnapshot(
            trade_count=len(self._trades),
            total_size=float(total_size),
            buy_size=float(buy_size),
            sell_size=float(sell_size),
            aggressive_delta=float(aggressive_delta),
            price_change_points=float(price_change),
            topbook_imbalance=float(_topbook_imbalance(event)),
            spread_ticks=float(spread_ticks),
        )

    def _sync_fills(self, context: L2OrderFlowContext) -> None:
        while self._fill_cursor < len(context.fills):
            fill = context.fills[self._fill_cursor]
            self._fill_cursor += 1
            tag = str(fill.tag or "")
            if tag.startswith("tape_read_entry:"):
                self._record_entry_fill(fill)
            elif tag.startswith("tape_read_exit:") and context.flat:
                self._open_trade = None
                self._trades.clear()

        if context.flat:
            self._open_trade = None

    def _record_entry_fill(self, fill: Any) -> None:
        accumulator = self._entry_accumulators.setdefault(
            str(fill.order_id),
            {
                "quantity": 0.0,
                "notional": 0.0,
                "side": str(fill.side),
                "entry_time": fill.fill_time,
            },
        )
        quantity = float(fill.quantity)
        accumulator["quantity"] += quantity
        accumulator["notional"] += quantity * float(fill.price)
        avg_price = accumulator["notional"] / accumulator["quantity"]
        direction = "long" if str(accumulator["side"]) == "buy" else "short"
        self._open_trade = _OpenTapeTrade(
            direction=direction,
            quantity=float(accumulator["quantity"]),
            entry_price=float(avg_price),
            entry_time=pd.Timestamp(accumulator["entry_time"]),
            order_id=str(fill.order_id),
        )

    def _reset_day_if_needed(self, event: L2MarketEvent) -> None:
        trade_date = event.ts_event.tz_convert("America/New_York").date()
        if self._current_trade_date != trade_date:
            self._current_trade_date = trade_date
            self._day_entry_count = 0


def build_strategy(**kwargs: Any) -> L2TapeReadOrderFlowStrategy:
    return L2TapeReadOrderFlowStrategy(**kwargs)


class _LocationContext:
    def __init__(self, config: L2TapeReadOrderFlowConfig) -> None:
        self.frame = self._load(config)
        self.times = (
            pd.DatetimeIndex(self.frame["_context_time"]) if not self.frame.empty else pd.DatetimeIndex([], tz="UTC")
        )

    def __len__(self) -> int:
        return int(len(self.frame))

    def snapshot(self, event: L2MarketEvent, config: L2TapeReadOrderFlowConfig) -> _LocationSnapshot:
        mid = _event_mid(event)
        empty = _empty_location_snapshot(mid)
        if self.frame.empty:
            return empty

        idx = int(self.times.searchsorted(event.ts_event, side="right")) - 1
        if idx < 0:
            return empty

        row = self.frame.iloc[idx]
        context_time = pd.Timestamp(row["_context_time"])
        age = event.ts_event - context_time
        max_age = _timedelta_or_none(config.location_max_age)
        is_fresh = max_age is None or age <= max_age

        lower = _numeric_alias(
            row,
            config.profile_lower_col,
            (
                "vp_val",
                "val",
                "value_area_low",
                "value_area_lower",
                "profile_val",
                "tpo_val",
                "mp_nearest_support",
                "support",
                "nearest_support",
                "options_put_wall_strike",
            ),
        )
        upper = _numeric_alias(
            row,
            config.profile_upper_col,
            (
                "vp_vah",
                "vah",
                "value_area_high",
                "value_area_upper",
                "profile_vah",
                "tpo_vah",
                "mp_nearest_resistance",
                "resistance",
                "nearest_resistance",
                "options_call_wall_strike",
            ),
        )
        poc = _numeric_alias(row, config.profile_poc_col, ("vp_poc", "poc", "tpo_poc", "mp_poc"))
        gex_wall = _numeric_alias(row, config.gex_wall_col, ("gamma_wall", "gex_wall", "options_gamma_wall"))
        gamma_environment = _string_alias(
            row,
            config.gamma_environment_col,
            ("options_gex_regime", "gamma_environment", "gex_regime"),
        )

        proximity = float(config.location_proximity_points)
        gex_proximity = float(config.gex_wall_proximity_points)
        breakout_buffer = float(config.trend_breakout_buffer_points)
        near_lower = bool(np.isfinite(lower) and np.isfinite(mid) and abs(mid - lower) <= proximity)
        near_upper = bool(np.isfinite(upper) and np.isfinite(mid) and abs(mid - upper) <= proximity)
        if np.isfinite(gex_wall) and np.isfinite(mid) and abs(mid - gex_wall) <= gex_proximity:
            if gex_wall <= mid:
                near_lower = True
            if gex_wall >= mid:
                near_upper = True
        above_upper = bool(np.isfinite(upper) and np.isfinite(mid) and mid >= upper + breakout_buffer)
        below_lower = bool(np.isfinite(lower) and np.isfinite(mid) and mid <= lower - breakout_buffer)
        has_any_level = any(np.isfinite(value) for value in (lower, upper, poc, gex_wall))
        return _LocationSnapshot(
            is_available=bool(has_any_level),
            is_fresh=bool(is_fresh),
            context_time=context_time,
            age=age,
            mid_price=float(mid),
            lower_level=float(lower),
            upper_level=float(upper),
            poc_level=float(poc),
            gex_wall=float(gex_wall),
            gamma_environment=gamma_environment,
            near_lower=near_lower,
            near_upper=near_upper,
            above_upper=above_upper,
            below_lower=below_lower,
        )

    def _load(self, config: L2TapeReadOrderFlowConfig) -> pd.DataFrame:
        raw_path = str(config.location_context_csv or "").strip()
        if not raw_path:
            return pd.DataFrame()
        path = Path(raw_path)
        frame = pd.read_csv(path)
        if config.location_time_col not in frame.columns:
            raise ValueError(f"location context is missing time column: {config.location_time_col}")
        out = frame.copy()
        out["_context_time"] = _to_utc_time(out[config.location_time_col], config.location_timezone)
        out = out.dropna(subset=["_context_time"]).sort_values("_context_time", kind="stable").reset_index(drop=True)
        return out


class _TriggerContext:
    def __init__(self, config: L2TapeReadOrderFlowConfig) -> None:
        self.frame = self._load(config)
        self.times = (
            pd.DatetimeIndex(self.frame["_context_time"]) if not self.frame.empty else pd.DatetimeIndex([], tz="UTC")
        )

    def __len__(self) -> int:
        return int(len(self.frame))

    def snapshot(self, event: L2MarketEvent, config: L2TapeReadOrderFlowConfig) -> _TriggerSnapshot:
        mode = str(config.trigger_mode)
        long_col, short_col = _trigger_columns_for_mode(config)
        empty = _empty_trigger_snapshot(mode=mode, long_col=long_col, short_col=short_col)
        if mode == "off":
            return _TriggerSnapshot(
                is_available=True,
                is_fresh=True,
                context_time=None,
                age=None,
                mode=mode,
                long_ok=True,
                short_ok=True,
                long_trigger_col=long_col,
                short_trigger_col=short_col,
            )
        if self.frame.empty:
            return empty

        idx = int(self.times.searchsorted(event.ts_event, side="right")) - 1
        if idx < 0:
            return empty

        row = self.frame.iloc[idx]
        context_time = pd.Timestamp(row["_context_time"])
        age = event.ts_event - context_time
        max_age = _timedelta_or_none(config.trigger_max_age)
        is_fresh = max_age is None or age <= max_age
        long_aliases, short_aliases = _trigger_aliases_for_mode(config)
        is_available = _row_has_any(row, (long_col, short_col, *long_aliases, *short_aliases))
        long_ok = _bool_alias(row, long_col, long_aliases)
        short_ok = _bool_alias(row, short_col, short_aliases)
        return _TriggerSnapshot(
            is_available=bool(is_available),
            is_fresh=bool(is_fresh),
            context_time=context_time,
            age=age,
            mode=mode,
            long_ok=bool(long_ok),
            short_ok=bool(short_ok),
            long_trigger_col=long_col,
            short_trigger_col=short_col,
        )

    def _load(self, config: L2TapeReadOrderFlowConfig) -> pd.DataFrame:
        raw_path = str(config.trigger_context_csv or "").strip()
        if not raw_path or config.trigger_mode == "off":
            return pd.DataFrame()
        path = Path(raw_path)
        frame = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
        if config.trigger_time_col not in frame.columns:
            raise ValueError(f"trigger context is missing time column: {config.trigger_time_col}")
        out = frame.copy()
        out["_context_time"] = _to_utc_time(out[config.trigger_time_col], config.trigger_timezone)
        out = out.dropna(subset=["_context_time"]).sort_values("_context_time", kind="stable").reset_index(drop=True)
        return out


def _topbook_imbalance(event: L2MarketEvent) -> float:
    denom = float(event.bid_size) + float(event.ask_size)
    if denom <= 0.0:
        return np.nan
    return (float(event.bid_size) - float(event.ask_size)) / denom


def _event_mid(event: L2MarketEvent) -> float:
    if np.isfinite(event.bid_price) and np.isfinite(event.ask_price):
        return (float(event.bid_price) + float(event.ask_price)) / 2.0
    return np.nan


def _empty_location_snapshot(mid: float) -> _LocationSnapshot:
    return _LocationSnapshot(
        is_available=False,
        is_fresh=False,
        context_time=None,
        age=None,
        mid_price=float(mid),
        lower_level=np.nan,
        upper_level=np.nan,
        poc_level=np.nan,
        gex_wall=np.nan,
        gamma_environment="",
        near_lower=False,
        near_upper=False,
        above_upper=False,
        below_lower=False,
    )


def _empty_trigger_snapshot(*, mode: str, long_col: str, short_col: str) -> _TriggerSnapshot:
    return _TriggerSnapshot(
        is_available=False,
        is_fresh=False,
        context_time=None,
        age=None,
        mode=mode,
        long_ok=False,
        short_ok=False,
        long_trigger_col=long_col,
        short_trigger_col=short_col,
    )


def _trigger_columns_for_mode(config: L2TapeReadOrderFlowConfig) -> tuple[str, str]:
    mode = str(config.trigger_mode)
    if mode == "orderflow":
        return "mw_orderflow_long_trigger", "mw_orderflow_short_trigger"
    if mode == "absorption":
        return "mw_absorption_long_trigger", "mw_absorption_short_trigger"
    if mode == "initiative":
        return "mw_initiative_long_trigger", "mw_initiative_short_trigger"
    return str(config.long_trigger_col), str(config.short_trigger_col)


def _trigger_aliases_for_mode(config: L2TapeReadOrderFlowConfig) -> tuple[tuple[str, ...], tuple[str, ...]]:
    mode = str(config.trigger_mode)
    if mode == "orderflow":
        return ("orderflow_long_trigger",), ("orderflow_short_trigger",)
    if mode == "absorption":
        return ("absorption_long_trigger", "buy_absorption"), ("absorption_short_trigger", "sell_absorption")
    if mode == "initiative":
        return ("initiative_long_trigger", "buy_initiation"), ("initiative_short_trigger", "sell_initiation")
    if mode == "configured":
        return (), ()
    return (
        "mw_any_long_trigger",
        "any_long_trigger",
        "long_trigger",
        "buy_trigger",
    ), (
        "mw_any_short_trigger",
        "any_short_trigger",
        "short_trigger",
        "sell_trigger",
    )


def _row_has_any(row: pd.Series, columns: tuple[str, ...]) -> bool:
    return any(col in row.index for col in columns if str(col or "").strip())


def _bool_alias(row: pd.Series, primary: str, aliases: tuple[str, ...]) -> bool:
    result = False
    for col in (primary, *aliases):
        if col not in row.index:
            continue
        result = result or _truthy_value(row[col])
    return bool(result)


def _truthy_value(value: object) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.notna(numeric):
        return bool(float(numeric) != 0.0)
    text = str(value or "").strip().lower()
    return text in {
        "true",
        "t",
        "yes",
        "y",
        "on",
        "1",
        "signal",
        "trigger",
        "buy",
        "sell",
        "bid",
        "ask",
        "positive",
        "negative",
        "red tower",
        "blue tower",
    }


def _numeric_alias(row: pd.Series, primary: str, aliases: tuple[str, ...]) -> float:
    for col in (primary, *aliases):
        if col not in row.index:
            continue
        value = pd.to_numeric(pd.Series([row[col]]), errors="coerce").iloc[0]
        if np.isfinite(value):
            return float(value)
    return np.nan


def _string_alias(row: pd.Series, primary: str, aliases: tuple[str, ...]) -> str:
    for col in (primary, *aliases):
        if col not in row.index:
            continue
        value = str(row[col] or "").strip()
        if value and value.lower() != "nan":
            return value
    return ""


def _to_utc_time(values: pd.Series, timezone: str) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(str(timezone), ambiguous="NaT", nonexistent="shift_forward")
    return parsed.dt.tz_convert("UTC")


def _timedelta_or_none(value: str) -> pd.Timedelta | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return pd.Timedelta(raw)


def _within_session(event: L2MarketEvent, start: str, end: str) -> bool:
    clock = event.ts_event.tz_convert("America/New_York").strftime("%H:%M")
    if start and clock < start:
        return False
    if end and clock >= end:
        return False
    return True


def _at_or_after_time(event: L2MarketEvent, clock_time: str) -> bool:
    return event.ts_event.tz_convert("America/New_York").strftime("%H:%M") >= str(clock_time)


__all__ = [
    "L2TapeReadOrderFlowConfig",
    "L2TapeReadOrderFlowStrategy",
    "build_strategy",
]
