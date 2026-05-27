from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backtest.gap_go_signal import GapGoSignalConfig, build_gap_go_signal_export, build_gap_go_signal_frame


class GapGoSignalTests(unittest.TestCase):
    def test_builds_long_signal_after_gap_holds_and_breaks_opening_range(self) -> None:
        data = _two_session_bars()
        day2 = data["time"].dt.date == pd.Timestamp("2024-01-03").date()
        day2_idx = data.index[day2]
        data.loc[day2_idx[:15], ["open", "high", "low", "close", "volume"]] = [122.0, 123.0, 121.0, 122.5, 1200]
        signal_idx = day2_idx[15]
        data.loc[signal_idx, ["open", "high", "low", "close", "volume"]] = [122.5, 125.0, 122.0, 124.8, 2500]

        frame = build_gap_go_signal_frame(data, config=_test_config())

        self.assertEqual(float(frame.loc[signal_idx, "signal"]), 1.0)
        self.assertEqual(frame.loc[signal_idx, "gap_direction"], "gap_up")
        self.assertEqual(frame.loc[signal_idx, "gap_hold_status"], "held_up_gap")
        self.assertEqual(frame.loc[signal_idx, "opening_range_breakout_side"], "up_breakout")
        self.assertGreater(float(frame.loc[signal_idx, "gap_go_score"]), 0.0)

    def test_builds_short_signal_after_gap_down_holds_and_breaks_opening_range(self) -> None:
        data = _two_session_bars()
        day2 = data["time"].dt.date == pd.Timestamp("2024-01-03").date()
        day2_idx = data.index[day2]
        data.loc[day2_idx[:15], ["open", "high", "low", "close", "volume"]] = [78.0, 79.0, 77.0, 77.5, 1200]
        signal_idx = day2_idx[15]
        data.loc[signal_idx, ["open", "high", "low", "close", "volume"]] = [77.5, 78.0, 75.0, 75.2, 2500]

        frame = build_gap_go_signal_frame(data, config=_test_config())

        self.assertEqual(float(frame.loc[signal_idx, "signal"]), -1.0)
        self.assertEqual(frame.loc[signal_idx, "gap_direction"], "gap_down")
        self.assertEqual(frame.loc[signal_idx, "gap_hold_status"], "held_down_gap")
        self.assertEqual(frame.loc[signal_idx, "opening_range_breakout_side"], "down_breakout")
        self.assertLess(float(frame.loc[signal_idx, "gap_go_score"]), 0.0)

    def test_future_rows_do_not_change_prior_signal(self) -> None:
        data = _two_session_bars()
        day2 = data["time"].dt.date == pd.Timestamp("2024-01-03").date()
        day2_idx = data.index[day2]
        data.loc[day2_idx[:15], ["open", "high", "low", "close", "volume"]] = [122.0, 123.0, 121.0, 122.5, 1200]
        signal_idx = day2_idx[15]
        data.loc[signal_idx, ["open", "high", "low", "close", "volume"]] = [122.5, 125.0, 122.0, 124.8, 2500]
        mutated = data.copy()
        mutated.loc[signal_idx + 1 :, "close"] = mutated.loc[signal_idx + 1 :, "close"] - 50.0

        frame = build_gap_go_signal_frame(data, config=_test_config())
        changed = build_gap_go_signal_frame(mutated, config=_test_config())

        pd.testing.assert_series_equal(frame.loc[:signal_idx, "signal"], changed.loc[:signal_idx, "signal"])

    def test_export_includes_gate_columns(self) -> None:
        data = _two_session_bars()
        day2 = data["time"].dt.date == pd.Timestamp("2024-01-03").date()
        day2_idx = data.index[day2]
        data.loc[day2_idx[:15], ["open", "high", "low", "close", "volume"]] = [122.0, 123.0, 121.0, 122.5, 1200]
        signal_idx = day2_idx[15]
        data.loc[signal_idx, ["open", "high", "low", "close", "volume"]] = [122.5, 125.0, 122.0, 124.8, 2500]

        export = build_gap_go_signal_export(data, config=_test_config())

        self.assertIn("candidate_signal", export.columns)
        self.assertIn("gap_go_score", export.columns)
        self.assertIn("gap_direction", export.columns)
        self.assertIn("gap_hold_status", export.columns)
        self.assertEqual(export.loc[signal_idx, "opening_range_breakout_side"], "up_breakout")
        self.assertEqual(export.loc[signal_idx, "gap_go_pattern"], "gap_hold_opening_range_breakout")


def _test_config() -> GapGoSignalConfig:
    return GapGoSignalConfig(
        opening_range_minutes=15,
        min_abs_gap_points=10.0,
        min_gap_to_prior_range_ratio=0.1,
        gap_hold_tolerance_points=1.0,
        breakout_buffer_points=0.25,
        close_position_long_min=0.70,
        close_position_short_max=0.30,
        trade_start="09:45",
        trade_end="11:00",
    )


def _two_session_bars() -> pd.DataFrame:
    frames = []
    for day in ["2024-01-02", "2024-01-03"]:
        times = pd.date_range(f"{day} 09:30", periods=120, freq="min")
        close = pd.Series(100.0 + np.sin(np.arange(len(times)) / 12.0) * 0.5)
        frames.append(
            pd.DataFrame(
                {
                    "time": times,
                    "open": close,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "volume": 1000,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    unittest.main()
