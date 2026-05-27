from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backtest.power_hour_signal import (
    PowerHourSignalConfig,
    build_power_hour_signal_export,
    build_power_hour_signal_frame,
)


class PowerHourSignalTests(unittest.TestCase):
    def test_builds_long_signal_on_late_day_accepted_uptrend(self) -> None:
        data = _trend_day(up=True)
        signal_idx = _index_at(data, "2024-01-03 15:00")

        frame = build_power_hour_signal_frame(data, config=_test_config())

        self.assertEqual(float(frame.loc[signal_idx, "signal"]), 1.0)
        self.assertEqual(frame.loc[signal_idx, "closing_flow_side"], "accepted_up")
        self.assertEqual(frame.loc[signal_idx, "close_location"], "near_session_high")
        self.assertEqual(frame.loc[signal_idx, "momentum_state"], "aligned_up")
        self.assertGreater(float(frame.loc[signal_idx, "power_hour_score"]), 0.0)

    def test_builds_short_signal_on_late_day_accepted_downtrend(self) -> None:
        data = _trend_day(up=False)
        signal_idx = _index_at(data, "2024-01-03 15:00")

        frame = build_power_hour_signal_frame(data, config=_test_config())

        self.assertEqual(float(frame.loc[signal_idx, "signal"]), -1.0)
        self.assertEqual(frame.loc[signal_idx, "closing_flow_side"], "accepted_down")
        self.assertEqual(frame.loc[signal_idx, "close_location"], "near_session_low")
        self.assertEqual(frame.loc[signal_idx, "momentum_state"], "aligned_down")
        self.assertLess(float(frame.loc[signal_idx, "power_hour_score"]), 0.0)

    def test_future_rows_do_not_change_prior_signal(self) -> None:
        data = _trend_day(up=True)
        signal_idx = _index_at(data, "2024-01-03 15:00")
        mutated = data.copy()
        mutated.loc[signal_idx + 1 :, "close"] = mutated.loc[signal_idx + 1 :, "close"] - 100.0

        frame = build_power_hour_signal_frame(data, config=_test_config())
        changed = build_power_hour_signal_frame(mutated, config=_test_config())

        pd.testing.assert_series_equal(frame.loc[:signal_idx, "signal"], changed.loc[:signal_idx, "signal"])

    def test_export_includes_gate_columns(self) -> None:
        data = _trend_day(up=True)
        signal_idx = _index_at(data, "2024-01-03 15:00")

        export = build_power_hour_signal_export(data, config=_test_config())

        self.assertIn("candidate_signal", export.columns)
        self.assertIn("power_hour_score", export.columns)
        self.assertIn("closing_flow_side", export.columns)
        self.assertIn("power_hour_pattern", export.columns)
        self.assertEqual(export.loc[signal_idx, "closing_flow_side"], "accepted_up")
        self.assertEqual(export.loc[signal_idx, "power_hour_pattern"], "late_day_accepted_trend_continuation")


def _test_config() -> PowerHourSignalConfig:
    return PowerHourSignalConfig(
        signal_start="15:00",
        signal_end="15:30",
        momentum_lookback_bars=10,
        min_session_move_points=10.0,
        min_session_move_to_range_ratio=0.40,
        min_momentum_points=0.8,
        close_position_long_min=0.80,
        close_position_short_max=0.20,
        min_vwap_distance_points=1.0,
    )


def _trend_day(*, up: bool) -> pd.DataFrame:
    times = pd.date_range("2024-01-03 09:30", periods=390, freq="min")
    step = np.linspace(0.0, 35.0, len(times))
    close = 100.0 + step if up else 135.0 - step
    return pd.DataFrame(
        {
            "time": times,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000,
        }
    )


def _index_at(data: pd.DataFrame, timestamp: str) -> int:
    matches = data.index[data["time"].eq(pd.Timestamp(timestamp))]
    if len(matches) != 1:
        raise AssertionError(f"missing timestamp {timestamp}")
    return int(matches[0])


if __name__ == "__main__":
    unittest.main()
