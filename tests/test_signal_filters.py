from __future__ import annotations

import unittest

import pandas as pd

from backtest.engine import BacktestEngine
from backtest.portfolio import Portfolio


class SignalFilterTests(unittest.TestCase):
    def test_allowed_entry_context_uses_last_completed_context_before_entry(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=4, freq="5min"),
                "signal": [-1, 0, -1, 0],
                "signal_type": ["trend", "", "trend", ""],
                "vwap_side": ["below_vwap", "above_vwap", "above_vwap", "below_vwap"],
                "inside_ib": [False, True, False, False],
                "cusum_event_direction": [0, -1, -1, 0],
            }
        )
        engine = BacktestEngine(
            df,
            portfolio=object(),
            futures_specs={"contract_value": 20},
            strategy_params={
                "entry_mode": "next_bar_open",
                "allowed_setup_tags": ["trend_short"],
                "allowed_entry_context": {
                    "trend_short": {
                        "vwap_side": ["below_vwap"],
                        "inside_ib": [False],
                        "cusum_event_direction": [-1, 0],
                    },
                },
            },
        )

        out = engine.apply_signal_filters(df)

        self.assertEqual(int(out.loc[0, "signal"]), -1)
        self.assertEqual(int(out.loc[2, "signal"]), 0)

    def test_blocked_entry_context_does_not_use_next_bar_future_context(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=4, freq="5min"),
                "signal": [-1, 0, -1, 0],
                "signal_type": ["trend", "", "trend", ""],
                "vwap_cross_direction": ["none", "cross_up", "cross_down", "none"],
            }
        )
        engine = BacktestEngine(
            df,
            portfolio=object(),
            futures_specs={"contract_value": 20},
            strategy_params={
                "entry_mode": "next_bar_open",
                "blocked_entry_context": {
                    "trend": {
                        "vwap_cross_direction": ["cross_up", "cross_down"],
                    },
                },
            },
        )

        out = engine.apply_signal_filters(df)

        self.assertEqual(int(out.loc[0, "signal"]), -1)
        self.assertEqual(int(out.loc[2, "signal"]), 0)

    def test_blocked_entry_context_respects_entry_delay(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=5, freq="5min"),
                "signal": [-1, 0, -1, 0, 0],
                "signal_type": ["trend", "", "", "trend", ""],
                "vwap_cross_direction": ["none", "cross_down", "none", "none", "cross_down"],
            }
        )
        engine = BacktestEngine(
            df,
            portfolio=object(),
            futures_specs={"contract_value": 20},
            strategy_params={
                "entry_mode": "next_bar_open",
                "entry_delay_bars": 1,
                "blocked_entry_context": {
                    "trend": {
                        "vwap_cross_direction": ["cross_up", "cross_down"],
                    },
                },
            },
        )

        out = engine.apply_signal_filters(df)

        self.assertEqual(int(out.loc[0, "signal"]), 0)
        self.assertEqual(int(out.loc[2, "signal"]), -1)

    def test_blocked_entry_context_can_target_setup_direction(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=4, freq="5min"),
                "signal": [1, 0, -1, 0],
                "signal_type": ["trend", "", "trend", ""],
                "cusum_event_direction": [-1, 0, 0, -1],
            }
        )
        engine = BacktestEngine(
            df,
            portfolio=object(),
            futures_specs={"contract_value": 20},
            strategy_params={
                "entry_mode": "next_bar_open",
                "blocked_entry_context": {
                    "trend_long": {
                        "cusum_event_direction": [-1],
                    },
                },
            },
        )

        out = engine.apply_signal_filters(df)

        self.assertEqual(int(out.loc[0, "signal"]), 0)
        self.assertEqual(int(out.loc[2, "signal"]), -1)

    def test_blocked_entry_context_can_target_trade_direction(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=6, freq="5min"),
                "signal": [1, 0, 1, 0, -1, 0],
                "signal_type": ["trend", "", "trend", "", "trend", ""],
                "inside_ib": [True, False, False, True, True, False],
                "cusum_event": [False, False, False, True, False, False],
            }
        )
        engine = BacktestEngine(
            df,
            portfolio=object(),
            futures_specs={"contract_value": 20},
            strategy_params={
                "entry_mode": "next_bar_open",
                "blocked_entry_context": {
                    "long": {
                        "inside_ib": [True],
                        "cusum_event": [False],
                    },
                    "short": {
                        "inside_ib": [True],
                        "cusum_event": [False],
                    },
                },
            },
        )

        out = engine.apply_signal_filters(df)

        self.assertEqual(int(out.loc[0, "signal"]), 0)
        self.assertEqual(int(out.loc[2, "signal"]), 1)
        self.assertEqual(int(out.loc[4, "signal"]), 0)

    def test_next_bar_open_execution_uses_last_completed_context_for_metadata(self) -> None:
        raw = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=15, freq="1min"),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 10,
            }
        )
        pre_df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=3, freq="5min"),
                "open": [100.0, 100.0, 100.0],
                "high": [101.0, 101.0, 101.0],
                "low": [99.0, 99.0, 99.0],
                "close": [100.0, 100.0, 100.0],
                "volume": [50, 50, 50],
                "atr": [2.0, 2.0, 99.0],
                "vwap": [100.0, 999.0, 100.0],
                "vwap_side": ["warmup", "signal_context", "future_entry_bar"],
                "signal": [0, 1, 0],
                "signal_type": ["", "trend", ""],
            }
        )
        specs = {
            "contract_value": 20.0,
            "commission_per_round_trip": 0.0,
            "slippage_points": 0.0,
        }
        params = {
            "entry_mode": "next_bar_open",
            "entry_delay_bars": 0,
            "execution_timeframe": "1min",
            "position_sizing_mode": "fixed_contracts",
            "fixed_contracts": 1,
            "max_contracts": 1,
            "max_trades_per_day": 10,
            "max_hold_bars": 1,
            "atr_stop_multiplier": 1.0,
            "atr_target_multiplier": 2.0,
            "exit_mode": "atr_only",
            "intrabar_exit_assumption": "conservative",
        }
        engine = BacktestEngine(raw, Portfolio(100_000, specs), specs, params)
        engine.generate_signals = lambda frame: frame.copy()

        results = engine.run_on_preprocessed(pre_df)

        self.assertNotIn("error", results)
        trades = results["trades"]
        self.assertEqual(pd.Timestamp(trades.loc[0, "entry_time"]), pd.Timestamp("2024-01-03 10:10"))
        self.assertEqual(trades.loc[0, "entry_vwap_side"], "signal_context")

    def test_1min_execution_is_clipped_to_preprocessed_segment(self) -> None:
        raw = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=20, freq="1min"),
                "open": 100.0,
                "high": 100.5,
                "low": 99.5,
                "close": 100.0,
                "volume": 10,
            }
        )
        raw.loc[raw["time"].eq(pd.Timestamp("2024-01-03 10:16")), "high"] = 103.0
        pre_df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=3, freq="5min"),
                "open": [100.0, 100.0, 100.0],
                "high": [100.5, 100.5, 100.5],
                "low": [99.5, 99.5, 99.5],
                "close": [100.0, 100.0, 100.0],
                "volume": [50, 50, 50],
                "atr": [1.0, 1.0, 1.0],
                "vwap": [100.0, 100.0, 100.0],
                "signal": [0, 1, 0],
                "signal_type": ["", "trend", ""],
            }
        )
        specs = {
            "contract_value": 20.0,
            "commission_per_round_trip": 0.0,
            "slippage_points": 0.0,
        }
        params = {
            "entry_mode": "next_bar_open",
            "entry_delay_bars": 0,
            "execution_timeframe": "1min",
            "position_sizing_mode": "fixed_contracts",
            "fixed_contracts": 1,
            "max_contracts": 1,
            "max_trades_per_day": 10,
            "max_hold_bars": 20,
            "atr_stop_multiplier": 1.0,
            "atr_target_multiplier": 2.0,
            "exit_mode": "atr_only",
            "intrabar_exit_assumption": "conservative",
        }
        engine = BacktestEngine(raw, Portfolio(100_000, specs), specs, params)
        engine.generate_signals = lambda frame: frame.copy()

        results = engine.run_on_preprocessed(pre_df)

        self.assertNotIn("error", results)
        trades = results["trades"]
        self.assertEqual(trades.loc[0, "reason"], "end_of_data")
        self.assertLess(pd.Timestamp(trades.loc[0, "exit_time"]), pd.Timestamp("2024-01-03 10:15"))


if __name__ == "__main__":
    unittest.main()
