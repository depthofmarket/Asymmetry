from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.live import (
    LiveBar,
    PaperTradingConfig,
    PaperTradingEngine,
    summarize_execution_observations,
)
from config.backtest_config import FUTURES_SPECS


def _minimal_params(**overrides):
    params = {
        "entry_mode": "next_bar_open",
        "entry_delay_bars": 0,
        "exit_mode": "atr_only",
        "position_sizing_mode": "fixed_contracts",
        "fixed_contracts": 1,
        "max_contracts": 1,
        "max_trades_per_day": 3,
        "max_hold_bars": 12,
        "atr_stop_multiplier": 1.0,
        "atr_target_multiplier": 1.0,
        "intrabar_exit_assumption": "conservative",
        "market_profile_target_enabled": False,
        "market_structure_stop_enabled": False,
    }
    params.update(overrides)
    return params


class StubSignalPaperEngine(PaperTradingEngine):
    signal_value = 1
    signal_type = "trend"

    def _build_signal_frame(self, *, as_of: pd.Timestamp):
        runtime_engine = self._utility_engine()
        signal_time = pd.Timestamp(as_of).floor("5min") - pd.Timedelta(minutes=5)
        signal_frame = pd.DataFrame(
            {
                "time": [signal_time],
                "open": [100.0],
                "high": [101.0],
                "low": [99.5],
                "close": [100.5],
                "volume": [1000],
                "atr": [1.0],
                "signal": [self.signal_value],
                "signal_type": [self.signal_type],
                "vwap": [100.25],
                "vwap_side": ["above_vwap"],
                "inside_ib": [False],
                "cusum_event": [True],
                "cusum_event_direction": [1 if self.signal_value > 0 else -1],
                "open_context": ["inside_prior_range"],
            }
        )
        self._last_signal_frame = signal_frame
        return runtime_engine, signal_frame


class ShortStubSignalPaperEngine(StubSignalPaperEngine):
    signal_value = -1
    signal_type = "trend"


class PaperTradingRuntimeTests(unittest.TestCase):
    def test_next_bar_open_signal_uses_prior_completed_signal_bar(self) -> None:
        engine = PaperTradingEngine(
            futures_specs=FUTURES_SPECS,
            strategy_params=_minimal_params(entry_mode="next_bar_open"),
            config=PaperTradingConfig(starting_capital=100000, warmup_1m_bars=0),
        )
        signal_frame = pd.DataFrame(
            {
                "time": [pd.Timestamp("2024-01-03 10:00")],
                "close": [100.5],
                "atr": [1.0],
                "signal": [1],
                "signal_type": ["trend"],
            }
        )
        entry_bar = LiveBar(
            time=pd.Timestamp("2024-01-03 10:05"),
            open=101.0,
            high=102.0,
            low=100.75,
            close=101.5,
            volume=100,
        )

        signal = engine._find_actionable_signal(signal_frame, entry_bar)

        self.assertIsNotNone(signal)
        self.assertEqual(signal.signal_time, pd.Timestamp("2024-01-03 10:00"))
        self.assertEqual(signal.entry_time, pd.Timestamp("2024-01-03 10:05"))
        self.assertEqual(signal.direction, "long")
        self.assertEqual(signal.signal_type, "trend")
        self.assertEqual(signal.entry_price, 101.0)

    def test_same_bar_close_signal_fills_at_completed_signal_close(self) -> None:
        engine = PaperTradingEngine(
            futures_specs=FUTURES_SPECS,
            strategy_params=_minimal_params(entry_mode="same_bar_close"),
            config=PaperTradingConfig(starting_capital=100000, warmup_1m_bars=0),
        )
        signal_frame = pd.DataFrame(
            {
                "time": [pd.Timestamp("2024-01-03 10:00")],
                "close": [100.5],
                "atr": [1.0],
                "signal": [-1],
                "signal_type": ["mr"],
            }
        )
        entry_bar = LiveBar(
            time=pd.Timestamp("2024-01-03 10:05"),
            open=101.0,
            high=101.25,
            low=99.5,
            close=100.0,
            volume=100,
        )

        signal = engine._find_actionable_signal(signal_frame, entry_bar)

        self.assertIsNotNone(signal)
        self.assertEqual(signal.entry_time, pd.Timestamp("2024-01-03 10:05"))
        self.assertEqual(signal.direction, "short")
        self.assertEqual(signal.setup_tag, "mr_short")
        self.assertEqual(signal.entry_price, 100.5)

    def test_on_bar_can_enter_and_exit_a_paper_trade(self) -> None:
        engine = StubSignalPaperEngine(
            futures_specs=FUTURES_SPECS,
            strategy_params=_minimal_params(entry_mode="next_bar_open"),
            config=PaperTradingConfig(starting_capital=100000, warmup_1m_bars=0),
        )
        entry_bar = LiveBar(
            time=pd.Timestamp("2024-01-03 10:05"),
            open=101.0,
            high=102.25,
            low=100.75,
            close=102.0,
            volume=100,
        )

        events = engine.on_bar(entry_bar)

        self.assertEqual([event.event_type for event in events], ["entry_filled", "exit_filled"])
        self.assertEqual(events[-1].reason, "profit_target")
        self.assertEqual(len(engine.portfolio.closed_trades), 1)
        self.assertEqual(engine.portfolio.closed_trades[0].setup_tag, "trend_long")

    def test_no_new_trades_after_blocks_entry(self) -> None:
        engine = StubSignalPaperEngine(
            futures_specs=FUTURES_SPECS,
            strategy_params=_minimal_params(entry_mode="next_bar_open"),
            config=PaperTradingConfig(
                starting_capital=100000,
                warmup_1m_bars=0,
                no_new_trades_after="10:00",
            ),
        )
        bar = LiveBar(
            time=pd.Timestamp("2024-01-03 10:05"),
            open=101.0,
            high=101.25,
            low=100.75,
            close=101.0,
            volume=100,
        )

        events = engine.on_bar(bar)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "entry_skipped")
        self.assertEqual(events[0].reason, "no_new_trades_after")
        self.assertEqual(len(engine.portfolio.positions), 0)

    def test_entry_skip_writes_execution_observation(self) -> None:
        engine = StubSignalPaperEngine(
            futures_specs=FUTURES_SPECS,
            strategy_params=_minimal_params(entry_mode="next_bar_open"),
            config=PaperTradingConfig(
                starting_capital=100000,
                warmup_1m_bars=0,
                no_new_trades_after="10:00",
            ),
        )

        engine.on_bar(
            LiveBar(
                time=pd.Timestamp("2024-01-03 10:05"),
                open=101.0,
                high=101.25,
                low=100.75,
                close=101.0,
                volume=100,
            )
        )

        observations = engine.execution_observation_log()
        self.assertEqual(len(observations), 1)
        row = observations.iloc[0]
        self.assertEqual(row["status"], "skipped")
        self.assertEqual(row["skip_reason"], "no_new_trades_after")
        self.assertEqual(row["setup_tag"], "trend_long")
        self.assertEqual(row["decision_timestamp"], pd.Timestamp("2024-01-03 10:05"))
        self.assertEqual(row["signal_timestamp"], pd.Timestamp("2024-01-03 10:00"))
        self.assertEqual(row["intended_order_side"], "BUY")
        self.assertEqual(row["volatility_proxy_points"], 1.0)
        self.assertEqual(row["volatility_bucket"], "tight")

    def test_entry_fill_writes_long_and_short_execution_observations(self) -> None:
        scenarios = [
            (StubSignalPaperEngine, "trend_long", "BUY"),
            (ShortStubSignalPaperEngine, "trend_short", "SELL"),
        ]
        for engine_cls, setup, side in scenarios:
            with self.subTest(setup=setup):
                engine = engine_cls(
                    futures_specs=FUTURES_SPECS,
                    strategy_params=_minimal_params(entry_mode="next_bar_open", max_hold_bars=0),
                    config=PaperTradingConfig(starting_capital=100000, warmup_1m_bars=0),
                )

                engine.on_bar(
                    LiveBar(
                        time=pd.Timestamp("2024-01-03 10:05"),
                        open=101.0,
                        high=101.25,
                        low=100.75,
                        close=101.0,
                        volume=100,
                    )
                )

                observations = engine.execution_observation_log()
                self.assertEqual(len(observations), 1)
                row = observations.iloc[0]
                self.assertEqual(row["status"], "filled")
                self.assertEqual(row["setup_tag"], setup)
                self.assertEqual(row["intended_order_side"], side)
                self.assertEqual(row["decision_price"], 101.0)
                self.assertEqual(row["assumed_fill_price"], 101.0)
                self.assertEqual(row["shortfall_points"], 0.0)
                self.assertEqual(row["shortfall_dollars_per_contract"], 0.0)
                self.assertEqual(row["contracts"], 1)
                self.assertEqual(row["volatility_bucket"], "tight")

    def test_execution_observation_summary_handles_empty_log(self) -> None:
        summary = summarize_execution_observations(pd.DataFrame())

        self.assertTrue(summary.empty)
        self.assertIn("group", summary.columns)
        self.assertIn("fill_rate_pct", summary.columns)

    def test_emergency_stop_file_flattens_open_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stop_path = Path(tmp) / "STOP_TRADING"
            stop_path.write_text("stop\n", encoding="utf-8")
            engine = PaperTradingEngine(
                futures_specs=FUTURES_SPECS,
                strategy_params=_minimal_params(entry_mode="next_bar_open"),
                config=PaperTradingConfig(
                    starting_capital=100000,
                    warmup_1m_bars=99,
                    emergency_stop_path=str(stop_path),
                ),
            )
            engine.portfolio.enter_position(
                100.0,
                1,
                pd.Timestamp("2024-01-03 10:00"),
                "long",
                setup_tag="manual_long",
            )

            events = engine.on_bar(
                LiveBar(
                    time=pd.Timestamp("2024-01-03 10:01"),
                    open=100.0,
                    high=100.25,
                    low=99.75,
                    close=99.9,
                    volume=100,
                )
            )

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "exit_filled")
            self.assertEqual(events[0].reason, "emergency_stop")
            self.assertEqual(len(engine.portfolio.positions), 0)

    def test_state_persistence_restores_open_position_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            engine = PaperTradingEngine(
                futures_specs=FUTURES_SPECS,
                strategy_params=_minimal_params(entry_mode="next_bar_open"),
                config=PaperTradingConfig(
                    starting_capital=100000,
                    warmup_1m_bars=99,
                    state_path=str(state_path),
                    persist_state=True,
                    resume_state=False,
                ),
            )
            engine.portfolio.enter_position(
                100.0,
                1,
                pd.Timestamp("2024-01-03 10:00"),
                "long",
                signal_type="trend",
                setup_tag="trend_long",
            )
            engine._daily_trade_count["2024-01-03"] = 1
            engine._processed_signal_keys.add(
                (
                    pd.Timestamp("2024-01-03 09:55"),
                    pd.Timestamp("2024-01-03 10:00"),
                    "long",
                    "trend",
                )
            )
            engine.save_state(state_path)

            restored = PaperTradingEngine(
                futures_specs=FUTURES_SPECS,
                strategy_params=_minimal_params(entry_mode="next_bar_open"),
                config=PaperTradingConfig(
                    starting_capital=100000,
                    warmup_1m_bars=99,
                    state_path=str(state_path),
                ),
            )

            self.assertEqual(len(restored.portfolio.positions), 1)
            self.assertEqual(restored.portfolio.positions[0].setup_tag, "trend_long")
            self.assertEqual(restored._daily_trade_count["2024-01-03"], 1)
            self.assertEqual(len(restored._processed_signal_keys), 1)


if __name__ == "__main__":
    unittest.main()
