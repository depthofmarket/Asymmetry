from __future__ import annotations

import unittest

import pandas as pd

from backtest.strategy_runtime import extract_signal_events


class StrategyRuntimeTests(unittest.TestCase):
    def test_same_bar_close_event_uses_completed_bar_close(self) -> None:
        frame = pd.DataFrame(
            {
                "time": [pd.Timestamp("2024-01-03 10:00")],
                "open": [100.0],
                "close": [101.25],
                "signal": [1],
                "signal_type": ["trend"],
            }
        )

        events = extract_signal_events(frame, entry_mode="same_bar_close", entry_delay_bars=0)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].signal_time, pd.Timestamp("2024-01-03 10:00"))
        self.assertEqual(events[0].entry_time, pd.Timestamp("2024-01-03 10:05"))
        self.assertEqual(events[0].entry_reference_price, 101.25)

    def test_next_bar_open_event_uses_next_bar_open(self) -> None:
        frame = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=2, freq="5min"),
                "open": [100.0, 101.0],
                "close": [100.5, 101.5],
                "signal": [1, 0],
                "signal_type": ["trend", ""],
            }
        )

        events = extract_signal_events(frame, entry_mode="next_bar_open", entry_delay_bars=0)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].entry_time, pd.Timestamp("2024-01-03 10:05"))
        self.assertEqual(events[0].entry_reference_price, 101.0)


if __name__ == "__main__":
    unittest.main()
