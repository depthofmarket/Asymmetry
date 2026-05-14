from __future__ import annotations

import unittest

import pandas as pd

from backtest.engine import BacktestEngine


class SignalFilterTests(unittest.TestCase):
    def test_allowed_entry_context_uses_next_bar_entry_context(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=4, freq="5min"),
                "signal": [-1, 0, -1, 0],
                "signal_type": ["trend", "", "trend", ""],
                "vwap_side": ["below_vwap", "below_vwap", "below_vwap", "above_vwap"],
                "inside_ib": [True, False, False, False],
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

    def test_blocked_entry_context_uses_next_bar_entry_context(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=4, freq="5min"),
                "signal": [-1, 0, -1, 0],
                "signal_type": ["trend", "", "trend", ""],
                "vwap_cross_direction": ["none", "cross_up", "none", "none"],
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

        self.assertEqual(int(out.loc[0, "signal"]), 0)
        self.assertEqual(int(out.loc[2, "signal"]), -1)

    def test_blocked_entry_context_respects_entry_delay(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=5, freq="5min"),
                "signal": [-1, 0, 0, -1, 0],
                "signal_type": ["trend", "", "", "trend", ""],
                "vwap_cross_direction": ["none", "none", "cross_down", "none", "none"],
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
        self.assertEqual(int(out.loc[3, "signal"]), -1)

    def test_blocked_entry_context_can_target_setup_direction(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=4, freq="5min"),
                "signal": [1, 0, -1, 0],
                "signal_type": ["trend", "", "trend", ""],
                "cusum_event_direction": [0, -1, 0, -1],
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


if __name__ == "__main__":
    unittest.main()
