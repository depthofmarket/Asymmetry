from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.live_prop_rules import LivePropRuleGuard
from backtest.portfolio import Portfolio, Trade
from backtest.strategy_runtime import direction_from_signal, setup_tag


@dataclass(frozen=True)
class LiveBar:
    """A completed 1-minute OHLCV bar supplied to the paper runtime."""

    time: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    @classmethod
    def from_record(cls, record: Any) -> "LiveBar":
        if isinstance(record, cls):
            return record
        if isinstance(record, pd.Series):
            record = record.to_dict()
        return cls(
            time=pd.Timestamp(record["time"]),
            open=float(record["open"]),
            high=float(record["high"]),
            low=float(record["low"]),
            close=float(record["close"]),
            volume=float(record.get("volume", 0.0) or 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": pd.Timestamp(self.time),
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": float(self.volume),
        }


@dataclass(frozen=True)
class ActionableSignal:
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    direction: str
    signal_type: str
    setup_tag: str
    entry_price: float
    signal_row: pd.Series

    @property
    def key(self) -> tuple[pd.Timestamp, pd.Timestamp, str, str]:
        return (
            pd.Timestamp(self.signal_time),
            pd.Timestamp(self.entry_time),
            self.direction,
            self.signal_type,
        )


@dataclass(frozen=True)
class PaperTradingEvent:
    event_type: str
    timestamp: pd.Timestamp
    message: str
    direction: str = ""
    signal_type: str = ""
    setup_tag: str = ""
    price: float | None = None
    contracts: int | None = None
    pnl: float | None = None
    reason: str = ""
    signal_time: pd.Timestamp | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        row = {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "message": self.message,
            "direction": self.direction,
            "signal_type": self.signal_type,
            "setup_tag": self.setup_tag,
            "price": self.price,
            "contracts": self.contracts,
            "pnl": self.pnl,
            "reason": self.reason,
            "signal_time": self.signal_time,
        }
        for key, value in self.metadata.items():
            row[f"meta_{key}"] = value
        return row


@dataclass(frozen=True)
class PaperTradingConfig:
    starting_capital: float
    max_drawdown_pct: float | None = None
    warmup_1m_bars: int = 100
    max_history_1m_bars: int | None = None
    one_position_at_a_time: bool = True
    max_daily_loss_dollars: float = 0.0
    no_new_trades_after: str | None = None
    flatten_at: str | None = None
    emergency_stop_path: str | None = None
    flatten_on_emergency_stop: bool = True
    state_path: str | None = None
    persist_state: bool = True
    resume_state: bool = True
    prop_guard: LivePropRuleGuard | None = None


class PaperTradingEngine:
    """
    Bar-driven paper execution runtime.

    The runtime expects completed 1-minute bars. At each 5-minute boundary it
    builds the strategy signal frame from bars strictly before the current bar,
    so entry decisions use completed 5-minute signal bars. Fills are simulated
    locally through Portfolio; no broker orders are submitted here.
    """

    def __init__(
        self,
        *,
        futures_specs: dict,
        strategy_params: dict,
        config: PaperTradingConfig,
        portfolio: Portfolio | None = None,
    ):
        self.futures_specs = dict(futures_specs)
        self.strategy_params = dict(strategy_params)
        self.config = config
        self.portfolio = portfolio or Portfolio(
            config.starting_capital,
            self.futures_specs,
            max_drawdown_pct=config.max_drawdown_pct,
        )
        self._bars: list[LiveBar] = []
        self._processed_signal_keys: set[tuple[pd.Timestamp, pd.Timestamp, str, str]] = set()
        self._daily_trade_count: dict[str, int] = {}
        self._daily_start_equity: dict[str, float] = {}
        self._exit_levels: dict[str, float | None] = {}
        self._last_signal_frame = pd.DataFrame()
        self._last_bar_time: pd.Timestamp | None = None
        self._last_bar_close: float | None = None
        self.events: list[PaperTradingEvent] = []
        self.prop_guard = config.prop_guard
        if config.resume_state and config.state_path:
            state_path = Path(config.state_path)
            if state_path.exists():
                self.load_state(state_path)

    @property
    def open_position(self) -> Trade | None:
        return self.portfolio.positions[0] if self.portfolio.positions else None

    @property
    def last_signal_frame(self) -> pd.DataFrame:
        return self._last_signal_frame.copy()

    def bars_dataframe(self, *, before: pd.Timestamp | None = None) -> pd.DataFrame:
        rows = [bar.to_dict() for bar in self._bars]
        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
        if df.empty:
            return df
        df["time"] = pd.to_datetime(df["time"])
        if before is not None:
            df = df.loc[df["time"].lt(pd.Timestamp(before))]
        return df.sort_values("time").reset_index(drop=True)

    def trade_log(self) -> pd.DataFrame:
        return self.portfolio.get_trade_log()

    def event_log(self) -> pd.DataFrame:
        return pd.DataFrame([event.to_record() for event in self.events])

    def on_bar(self, record: LiveBar | pd.Series | dict[str, Any]) -> list[PaperTradingEvent]:
        bar = LiveBar.from_record(record)
        self._append_bar(bar)
        self._last_bar_time = pd.Timestamp(bar.time)
        self._last_bar_close = float(bar.close)
        self._ensure_daily_start_equity(bar)
        if self.prop_guard is not None:
            self.prop_guard.on_bar(
                timestamp=pd.Timestamp(bar.time),
                equity=self.mark_to_market_equity(float(bar.close)),
                daily_pnl=self._daily_pnl(bar),
                has_open_position=self.open_position is not None,
            )

        emitted: list[PaperTradingEvent] = []
        signal_frame: pd.DataFrame | None = None
        signal_engine: BacktestEngine | None = None

        if self._is_entry_boundary(bar.time) and len(self._bars) >= self.config.warmup_1m_bars:
            signal_engine, signal_frame = self._build_signal_frame(as_of=bar.time)

        utility_engine = self._utility_engine()
        emitted.extend(
            self._manage_open_position(
                bar,
                utility_engine,
                signal_engine=signal_engine,
                signal_frame=signal_frame,
            )
        )
        emitted.extend(self._forced_exit_if_needed(bar))

        if (
            self.open_position is None
            and signal_frame is not None
            and signal_engine is not None
        ):
            signal = self._find_actionable_signal(signal_frame, bar)
            if signal is not None:
                emitted.extend(self._enter_from_signal(signal, bar, signal_engine))
                if self.open_position is not None:
                    emitted.extend(
                        self._manage_open_position(
                            bar,
                            utility_engine,
                            signal_engine=signal_engine,
                            signal_frame=signal_frame,
                        )
                    )

        self._record_prop_events(emitted)
        self.events.extend(emitted)
        self._autosave_state()
        return emitted

    def mark_to_market_equity(self, current_price: float | None = None) -> float:
        return self.portfolio.get_mark_to_market_equity(current_price)

    def status_snapshot(
        self,
        *,
        current_price: float | None = None,
        timestamp: pd.Timestamp | None = None,
    ) -> dict[str, Any]:
        if current_price is None:
            current_price = self._last_bar_close
        if timestamp is None:
            timestamp = self._last_bar_time
        open_position = self.open_position
        latest_day = pd.Timestamp(timestamp).strftime("%Y-%m-%d") if timestamp is not None else ""
        daily_start = self._daily_start_equity.get(latest_day)
        mtm_equity = self.mark_to_market_equity(current_price)
        daily_pnl = mtm_equity - daily_start if daily_start is not None else None
        return {
            "timestamp": timestamp,
            "last_price": current_price,
            "equity": mtm_equity,
            "cash_equity": self.portfolio.get_equity(),
            "daily_pnl": daily_pnl,
            "open_position": open_position is not None,
            "open_direction": open_position.direction if open_position is not None else "",
            "open_contracts": open_position.contracts if open_position is not None else 0,
            "open_entry_time": open_position.entry_time if open_position is not None else None,
            "open_entry_price": open_position.entry_price if open_position is not None else None,
            "trades_today": self._daily_trade_count.get(latest_day, 0),
            "closed_trades": len(self.portfolio.closed_trades),
            "events": len(self.events),
            "emergency_stop": self._emergency_stop_active(),
            "prop_guard": self.prop_guard.snapshot() if self.prop_guard is not None else None,
        }

    def save_state(self, path: str | Path | None = None) -> None:
        path_value = path or self.config.state_path
        if not path_value:
            return
        state_path = Path(path_value)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "portfolio": {
                "initial_capital": self.portfolio.initial_capital,
                "current_capital": self.portfolio.current_capital,
                "peak_equity": self.portfolio.peak_equity,
                "circuit_breaker_triggered": self.portfolio.circuit_breaker_triggered,
                "positions": [_trade_to_record(trade) for trade in self.portfolio.positions],
                "closed_trades": [_trade_to_record(trade) for trade in self.portfolio.closed_trades],
                "equity_history": list(self.portfolio.equity_history),
            },
            "daily_trade_count": dict(self._daily_trade_count),
            "daily_start_equity": dict(self._daily_start_equity),
            "processed_signal_keys": [
                [
                    pd.Timestamp(signal_time).isoformat(),
                    pd.Timestamp(entry_time).isoformat(),
                    direction,
                    signal_type,
                ]
                for signal_time, entry_time, direction, signal_type in self._processed_signal_keys
            ],
            "exit_levels": _json_safe(self._exit_levels),
            "last_bar_time": self._last_bar_time.isoformat() if self._last_bar_time is not None else None,
            "last_bar_close": self._last_bar_close,
            "events": [_json_safe(event.to_record()) for event in self.events],
        }
        if self.prop_guard is not None:
            state["prop_guard"] = _json_safe(self.prop_guard.to_state())
        state_path.write_text(json.dumps(_json_safe(state), indent=2, sort_keys=True), encoding="utf-8")

    def load_state(self, path: str | Path) -> None:
        state_path = Path(path)
        if not state_path.exists():
            return
        state = json.loads(state_path.read_text(encoding="utf-8"))
        portfolio_state = state.get("portfolio", {})
        self.portfolio.current_capital = float(portfolio_state.get("current_capital", self.portfolio.current_capital))
        self.portfolio.peak_equity = float(portfolio_state.get("peak_equity", self.portfolio.peak_equity))
        self.portfolio.circuit_breaker_triggered = bool(
            portfolio_state.get("circuit_breaker_triggered", self.portfolio.circuit_breaker_triggered)
        )
        self.portfolio.positions = [
            _trade_from_record(record) for record in portfolio_state.get("positions", [])
        ]
        self.portfolio.closed_trades = [
            _trade_from_record(record) for record in portfolio_state.get("closed_trades", [])
        ]
        self.portfolio.equity_history = [
            float(value) for value in portfolio_state.get("equity_history", self.portfolio.equity_history)
        ]
        self._daily_trade_count = {
            str(key): int(value) for key, value in state.get("daily_trade_count", {}).items()
        }
        self._daily_start_equity = {
            str(key): float(value) for key, value in state.get("daily_start_equity", {}).items()
        }
        self._processed_signal_keys = {
            (
                pd.Timestamp(item[0]),
                pd.Timestamp(item[1]),
                str(item[2]),
                str(item[3]),
            )
            for item in state.get("processed_signal_keys", [])
            if len(item) == 4
        }
        self._exit_levels = {
            str(key): (None if value is None else float(value))
            for key, value in state.get("exit_levels", {}).items()
        }
        last_bar_time = state.get("last_bar_time")
        self._last_bar_time = pd.Timestamp(last_bar_time) if last_bar_time else None
        last_bar_close = state.get("last_bar_close")
        self._last_bar_close = None if last_bar_close is None else float(last_bar_close)
        self.events = [
            PaperTradingEvent(
                event_type=str(record.get("event_type", "")),
                timestamp=pd.Timestamp(record["timestamp"]),
                message=str(record.get("message", "")),
                direction=str(record.get("direction", "")),
                signal_type=str(record.get("signal_type", "")),
                setup_tag=str(record.get("setup_tag", "")),
                price=_none_or_float(record.get("price")),
                contracts=_none_or_int(record.get("contracts")),
                pnl=_none_or_float(record.get("pnl")),
                reason=str(record.get("reason", "")),
                signal_time=pd.Timestamp(record["signal_time"]) if record.get("signal_time") else None,
                metadata={
                    key.removeprefix("meta_"): value
                    for key, value in record.items()
                    if str(key).startswith("meta_")
                },
            )
            for record in state.get("events", [])
            if record.get("timestamp")
        ]
        if self.prop_guard is not None and isinstance(state.get("prop_guard"), dict):
            self.prop_guard.load_state(state["prop_guard"])

    def _append_bar(self, bar: LiveBar) -> None:
        if self._bars:
            last_time = pd.Timestamp(self._bars[-1].time)
            if pd.Timestamp(bar.time) < last_time:
                raise ValueError("live bars must arrive in chronological order")
            if pd.Timestamp(bar.time) == last_time:
                self._bars[-1] = bar
            else:
                self._bars.append(bar)
        else:
            self._bars.append(bar)

        max_bars = self.config.max_history_1m_bars
        if max_bars is not None and max_bars > 0 and len(self._bars) > max_bars:
            self._bars = self._bars[-max_bars:]

    def _autosave_state(self) -> None:
        if self.config.persist_state and self.config.state_path:
            self.save_state(self.config.state_path)

    def _ensure_daily_start_equity(self, bar: LiveBar) -> None:
        trade_date = pd.Timestamp(bar.time).strftime("%Y-%m-%d")
        if trade_date not in self._daily_start_equity:
            self._daily_start_equity[trade_date] = float(self.mark_to_market_equity(float(bar.close)))

    def _emergency_stop_active(self) -> bool:
        path = self.config.emergency_stop_path
        return bool(path and Path(path).exists())

    def _clock_reached(self, timestamp: pd.Timestamp, clock: str | None) -> bool:
        if not clock:
            return False
        hour, minute = [int(part) for part in str(clock).split(":", 1)]
        ts = pd.Timestamp(timestamp)
        return (ts.hour > hour) or (ts.hour == hour and ts.minute >= minute)

    def _daily_pnl(self, bar: LiveBar) -> float:
        trade_date = pd.Timestamp(bar.time).strftime("%Y-%m-%d")
        start_equity = self._daily_start_equity.get(trade_date)
        if start_equity is None:
            self._ensure_daily_start_equity(bar)
            start_equity = self._daily_start_equity[trade_date]
        return float(self.mark_to_market_equity(float(bar.close)) - start_equity)

    def _entry_block_reason(self, bar: LiveBar) -> tuple[str, str] | None:
        if self._emergency_stop_active():
            return "emergency_stop", "Signal skipped because emergency stop file is present."
        max_daily_loss = float(self.config.max_daily_loss_dollars or 0.0)
        if max_daily_loss > 0 and self._daily_pnl(bar) <= -max_daily_loss:
            return "daily_loss_limit", "Signal skipped because the daily loss limit is reached."
        if self._clock_reached(pd.Timestamp(bar.time), self.config.flatten_at):
            return "flatten_time_reached", "Signal skipped because flatten_at time has passed."
        if self._clock_reached(pd.Timestamp(bar.time), self.config.no_new_trades_after):
            return "no_new_trades_after", "Signal skipped because no_new_trades_after time has passed."
        if self.prop_guard is not None:
            decision = self.prop_guard.entry_block_reason()
            if decision is not None:
                return decision.reason, decision.message
        return None

    def _forced_exit_if_needed(self, bar: LiveBar) -> list[PaperTradingEvent]:
        if self.open_position is None:
            return []
        if self._emergency_stop_active() and self.config.flatten_on_emergency_stop:
            return self._exit_open_position(bar, float(bar.close), "emergency_stop")
        max_daily_loss = float(self.config.max_daily_loss_dollars or 0.0)
        if max_daily_loss > 0 and self._daily_pnl(bar) <= -max_daily_loss:
            return self._exit_open_position(bar, float(bar.close), "daily_loss_limit")
        if self._clock_reached(pd.Timestamp(bar.time), self.config.flatten_at):
            return self._exit_open_position(bar, float(bar.close), "scheduled_flatten")
        if self.prop_guard is not None:
            reason = self.prop_guard.exit_reason(has_open_position=self.open_position is not None)
            if reason:
                return self._exit_open_position(bar, float(bar.close), reason)
        return []

    def _record_prop_events(self, events: list[PaperTradingEvent]) -> None:
        if self.prop_guard is None:
            return
        equity = self.mark_to_market_equity(self._last_bar_close)
        for event in events:
            self.prop_guard.record_event(event, equity=equity)

    def _utility_engine(self) -> BacktestEngine:
        return BacktestEngine(
            self.bars_dataframe(),
            self.portfolio,
            self.futures_specs,
            self.strategy_params,
        )

    def _build_signal_frame(self, *, as_of: pd.Timestamp) -> tuple[BacktestEngine, pd.DataFrame]:
        data = self.bars_dataframe(before=as_of)
        engine = BacktestEngine(
            data,
            self.portfolio,
            self.futures_specs,
            self.strategy_params,
        )
        if data.empty:
            signal_frame = pd.DataFrame()
        else:
            try:
                signal_frame = engine.build_signal_frame()
            except Exception:
                # Not enough data for indicators during live warmup.
                signal_frame = pd.DataFrame()
        self._last_signal_frame = signal_frame
        return engine, signal_frame

    def _is_entry_boundary(self, timestamp: pd.Timestamp) -> bool:
        ts = pd.Timestamp(timestamp)
        return ts.second == 0 and ts.microsecond == 0 and ts.minute % 5 == 0

    def _find_actionable_signal(
        self,
        signal_frame: pd.DataFrame,
        entry_bar: LiveBar,
    ) -> ActionableSignal | None:
        if signal_frame.empty or "signal" not in signal_frame.columns or "time" not in signal_frame.columns:
            return None

        entry_time = pd.Timestamp(entry_bar.time).floor("5min")
        entry_mode = str(self.strategy_params.get("entry_mode", "next_bar_open"))
        entry_delay_bars = max(0, int(self.strategy_params.get("entry_delay_bars", 0) or 0))
        if entry_mode == "next_bar_open":
            signal_offset = 1 + entry_delay_bars
        else:
            signal_offset = 1 if entry_delay_bars == 0 else entry_delay_bars
        signal_time = entry_time - pd.Timedelta(minutes=5 * signal_offset)

        frame = signal_frame.copy()
        frame["time"] = pd.to_datetime(frame["time"])
        signal_rows = frame.loc[frame["time"].eq(signal_time)]
        if signal_rows.empty:
            return None

        signal_row = signal_rows.iloc[-1]
        signal_value = int(signal_row.get("signal", 0) or 0)
        direction = direction_from_signal(signal_value)
        if not direction:
            return None

        signal_type = str(signal_row.get("signal_type", "") or "")
        tag = setup_tag(signal_type, direction)
        if entry_mode == "same_bar_close" and entry_delay_bars == 0:
            entry_price = float(signal_row.get("close", np.nan))
        else:
            entry_price = float(entry_bar.open)
        if not np.isfinite(entry_price):
            return None

        signal = ActionableSignal(
            signal_time=signal_time,
            entry_time=entry_time,
            direction=direction,
            signal_type=signal_type,
            setup_tag=tag,
            entry_price=entry_price,
            signal_row=signal_row,
        )
        if signal.key in self._processed_signal_keys:
            return None
        return signal

    def _enter_from_signal(
        self,
        signal: ActionableSignal,
        bar: LiveBar,
        engine: BacktestEngine,
    ) -> list[PaperTradingEvent]:
        entry_block = self._entry_block_reason(bar)
        if entry_block is not None:
            reason, message = entry_block
            self._processed_signal_keys.add(signal.key)
            return [
                PaperTradingEvent(
                    event_type="entry_skipped",
                    timestamp=pd.Timestamp(bar.time),
                    message=message,
                    direction=signal.direction,
                    signal_type=signal.signal_type,
                    setup_tag=signal.setup_tag,
                    signal_time=signal.signal_time,
                    reason=reason,
                )
            ]

        if self.config.one_position_at_a_time and self.open_position is not None:
            return [
                PaperTradingEvent(
                    event_type="entry_skipped",
                    timestamp=pd.Timestamp(bar.time),
                    message="Signal skipped because a position is already open.",
                    direction=signal.direction,
                    signal_type=signal.signal_type,
                    setup_tag=signal.setup_tag,
                    signal_time=signal.signal_time,
                    reason="position_open",
                )
            ]

        trade_date = pd.Timestamp(signal.entry_time).strftime("%Y-%m-%d")
        self._daily_trade_count[trade_date] = self._daily_trade_count.get(trade_date, 0)
        max_trades = int(self.strategy_params.get("max_trades_per_day", 0) or 0)
        if max_trades > 0 and self._daily_trade_count[trade_date] >= max_trades:
            self._processed_signal_keys.add(signal.key)
            return [
                PaperTradingEvent(
                    event_type="entry_skipped",
                    timestamp=pd.Timestamp(bar.time),
                    message="Signal skipped because max_trades_per_day is reached.",
                    direction=signal.direction,
                    signal_type=signal.signal_type,
                    setup_tag=signal.setup_tag,
                    signal_time=signal.signal_time,
                    reason="daily_trade_limit",
                )
            ]

        atr = float(signal.signal_row.get("atr", np.nan))
        if not np.isfinite(atr):
            self._processed_signal_keys.add(signal.key)
            return [
                PaperTradingEvent(
                    event_type="entry_skipped",
                    timestamp=pd.Timestamp(bar.time),
                    message="Signal skipped because ATR is unavailable.",
                    direction=signal.direction,
                    signal_type=signal.signal_type,
                    setup_tag=signal.setup_tag,
                    signal_time=signal.signal_time,
                    reason="missing_atr",
                )
            ]

        contracts = engine.calculate_contracts(atr, signal.direction, signal.signal_type)
        if contracts <= 0:
            self._processed_signal_keys.add(signal.key)
            return [
                PaperTradingEvent(
                    event_type="entry_skipped",
                    timestamp=pd.Timestamp(bar.time),
                    message="Signal skipped because position sizing returned zero contracts.",
                    direction=signal.direction,
                    signal_type=signal.signal_type,
                    setup_tag=signal.setup_tag,
                    signal_time=signal.signal_time,
                    reason="zero_contracts",
                )
            ]

        trade = self.portfolio.enter_position(
            signal.entry_price,
            contracts,
            signal.entry_time,
            signal.direction,
            signal_type=signal.signal_type,
            setup_tag=signal.setup_tag,
            metadata=engine.entry_context_metadata(signal.signal_row),
            current_price=signal.entry_price,
        )
        self._processed_signal_keys.add(signal.key)
        if trade is None:
            return [
                PaperTradingEvent(
                    event_type="entry_skipped",
                    timestamp=pd.Timestamp(bar.time),
                    message="Signal skipped by portfolio risk controls.",
                    direction=signal.direction,
                    signal_type=signal.signal_type,
                    setup_tag=signal.setup_tag,
                    signal_time=signal.signal_time,
                    reason="risk_control",
                )
            ]

        vwap_target = None
        target_price = None
        if signal.signal_type == "mr":
            if engine.use_volume_profile_mr_target() and "vp_poc" in signal.signal_row.index:
                target_price = signal.signal_row.get("vp_poc")
            else:
                vwap_target = signal.signal_row.get("vwap")

        self._exit_levels = engine.build_exit_levels(
            signal.direction,
            signal.entry_price,
            contracts,
            atr,
            vwap_target=vwap_target,
            target_price=target_price,
            signal_type=signal.signal_type,
            entry_row=signal.signal_row,
        )
        self._daily_trade_count[trade_date] += 1

        return [
            PaperTradingEvent(
                event_type="entry_filled",
                timestamp=pd.Timestamp(signal.entry_time),
                message="Paper entry filled.",
                direction=signal.direction,
                signal_type=signal.signal_type,
                setup_tag=signal.setup_tag,
                price=signal.entry_price,
                contracts=contracts,
                signal_time=signal.signal_time,
                metadata={
                    "stop_loss": self._exit_levels.get("stop_loss"),
                    "profit_target": self._exit_levels.get("profit_target"),
                    "hard_stop": self._exit_levels.get("hard_stop"),
                    "hard_target": self._exit_levels.get("hard_target"),
                },
            )
        ]

    def _manage_open_position(
        self,
        bar: LiveBar,
        engine: BacktestEngine,
        *,
        signal_engine: BacktestEngine | None = None,
        signal_frame: pd.DataFrame | None = None,
    ) -> list[PaperTradingEvent]:
        trade = self.open_position
        if trade is None:
            return []

        engine.update_trade_excursions(trade, float(bar.high), float(bar.low))
        bars_held = max(
            0,
            int((pd.Timestamp(bar.time) - pd.Timestamp(trade.entry_time)).total_seconds() // 300),
        )
        active_levels = engine.apply_trade_management(
            trade,
            self._exit_levels,
            bars_held=bars_held,
        )

        exit_flag, exit_reason, exit_price = engine.resolve_intrabar_exit(
            trade.direction,
            float(bar.open),
            float(bar.high),
            float(bar.low),
            active_levels,
        )

        if not exit_flag and signal_engine is not None and signal_frame is not None:
            if self._hawkes_exit_due(signal_engine, signal_frame, trade, pd.Timestamp(bar.time)):
                exit_flag = True
                exit_reason = "hawkes_vol_exit"
                exit_price = float(bar.open)

        max_hold_bars = int(self.strategy_params.get("max_hold_bars", 0) or 0)
        if not exit_flag and max_hold_bars > 0:
            deadline = pd.Timestamp(trade.entry_time) + pd.Timedelta(minutes=max_hold_bars * 5)
            if pd.Timestamp(bar.time) >= deadline:
                exit_flag = True
                exit_reason = "time_exit"
                exit_price = float(bar.close)

        if not exit_flag:
            return []

        return self._exit_open_position(bar, float(exit_price), exit_reason)

    def _exit_open_position(
        self,
        bar: LiveBar,
        exit_price: float,
        exit_reason: str,
    ) -> list[PaperTradingEvent]:
        trade = self.open_position
        if trade is None:
            return []

        trade.reason = exit_reason
        before_count = len(self.portfolio.closed_trades)
        self.portfolio.exit_position(float(exit_price), pd.Timestamp(bar.time), 0, exit_reason=exit_reason)
        self._exit_levels = {}
        closed_trade = self.portfolio.closed_trades[-1] if len(self.portfolio.closed_trades) > before_count else trade

        return [
            PaperTradingEvent(
                event_type="exit_filled",
                timestamp=pd.Timestamp(bar.time),
                message="Paper exit filled.",
                direction=closed_trade.direction,
                signal_type=closed_trade.signal_type,
                setup_tag=closed_trade.setup_tag,
                price=float(exit_price),
                contracts=int(closed_trade.contracts),
                pnl=float(closed_trade.pnl),
                reason=exit_reason,
                metadata={
                    "entry_time": closed_trade.entry_time,
                    "entry_price": closed_trade.entry_price,
                    "equity": self.portfolio.get_equity(),
                },
            )
        ]

    def _hawkes_exit_due(
        self,
        engine: BacktestEngine,
        signal_frame: pd.DataFrame,
        trade: Trade,
        bar_time: pd.Timestamp,
    ) -> bool:
        if not bool(self.strategy_params.get("hawkes_exit_enabled", False)):
            return False
        if signal_frame.empty or "time" not in signal_frame.columns:
            return False
        completed_signal_time = pd.Timestamp(bar_time).floor("5min") - pd.Timedelta(minutes=5)
        frame = signal_frame.copy()
        frame["time"] = pd.to_datetime(frame["time"])
        rows = frame.loc[frame["time"].eq(completed_signal_time)]
        if rows.empty:
            return False
        bars_held = max(0, int((pd.Timestamp(bar_time) - pd.Timestamp(trade.entry_time)).total_seconds() // 300))
        return engine.should_hawkes_exit(trade, rows.iloc[-1], bars_held=bars_held)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    try:
        if value is not None and pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _trade_to_record(trade: Trade) -> dict[str, Any]:
    return _json_safe(
        {
            "entry_time": pd.Timestamp(trade.entry_time).isoformat(),
            "entry_price": trade.entry_price,
            "contracts": trade.contracts,
            "direction": trade.direction,
            "signal_type": trade.signal_type,
            "setup_tag": trade.setup_tag,
            "exit_time": pd.Timestamp(trade.exit_time).isoformat() if trade.exit_time is not None else None,
            "exit_price": trade.exit_price,
            "pnl": trade.pnl,
            "reason": trade.reason,
            "max_favorable_excursion_points": trade.max_favorable_excursion_points,
            "max_adverse_excursion_points": trade.max_adverse_excursion_points,
            "metadata": trade.metadata,
        }
    )


def _trade_from_record(record: dict[str, Any]) -> Trade:
    return Trade(
        entry_time=pd.Timestamp(record["entry_time"]),
        entry_price=float(record["entry_price"]),
        contracts=float(record["contracts"]),
        direction=str(record["direction"]),
        signal_type=str(record.get("signal_type", "")),
        setup_tag=str(record.get("setup_tag", "")),
        exit_time=pd.Timestamp(record["exit_time"]) if record.get("exit_time") else None,
        exit_price=_none_or_float(record.get("exit_price")),
        pnl=float(record.get("pnl", 0.0) or 0.0),
        reason=str(record.get("reason", "open")),
        max_favorable_excursion_points=float(record.get("max_favorable_excursion_points", 0.0) or 0.0),
        max_adverse_excursion_points=float(record.get("max_adverse_excursion_points", 0.0) or 0.0),
        metadata=dict(record.get("metadata", {}) or {}),
    )


def _none_or_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _none_or_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
