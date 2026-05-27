from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backtest.compression_breakout_signal import (
    CompressionBreakoutSignalConfig,
    build_compression_breakout_signal_export,
    build_compression_breakout_signal_frame,
)


class CompressionBreakoutSignalTests(unittest.TestCase):
    def test_builds_long_signal_after_compression_up_breakout(self) -> None:
        data = _base_bars()
        data.loc[60, ["open", "high", "low", "close", "volume"]] = [100.0, 104.0, 99.8, 103.8, 3500]

        frame = build_compression_breakout_signal_frame(data, config=_test_config())

        self.assertEqual(float(frame.loc[60, "signal"]), 1.0)
        self.assertEqual(frame.loc[60, "compression_breakout_side"], "up_breakout")
        self.assertGreater(float(frame.loc[60, "compression_breakout_score"]), 0.0)

    def test_builds_short_signal_after_compression_down_breakout(self) -> None:
        data = _base_bars()
        data.loc[60, ["open", "high", "low", "close", "volume"]] = [100.0, 100.2, 96.0, 96.2, 3500]

        frame = build_compression_breakout_signal_frame(data, config=_test_config())

        self.assertEqual(float(frame.loc[60, "signal"]), -1.0)
        self.assertEqual(frame.loc[60, "compression_breakout_side"], "down_breakout")
        self.assertLess(float(frame.loc[60, "compression_breakout_score"]), 0.0)

    def test_future_rows_do_not_change_prior_signal(self) -> None:
        data = _base_bars()
        data.loc[60, ["open", "high", "low", "close", "volume"]] = [100.0, 104.0, 99.8, 103.8, 3500]
        mutated = data.copy()
        mutated.loc[61:, "close"] = mutated.loc[61:, "close"] - 50.0

        frame = build_compression_breakout_signal_frame(data, config=_test_config())
        changed = build_compression_breakout_signal_frame(mutated, config=_test_config())

        pd.testing.assert_series_equal(frame.loc[:60, "signal"], changed.loc[:60, "signal"])

    def test_export_includes_gate_columns(self) -> None:
        data = _base_bars()
        data.loc[60, ["open", "high", "low", "close", "volume"]] = [100.0, 104.0, 99.8, 103.8, 3500]

        export = build_compression_breakout_signal_export(data, config=_test_config())

        self.assertIn("candidate_signal", export.columns)
        self.assertIn("compression_breakout_score", export.columns)
        self.assertIn("compression_breakout_side", export.columns)
        self.assertIn("compression_pattern", export.columns)
        self.assertEqual(export.loc[60, "compression_breakout_side"], "up_breakout")
        self.assertEqual(export.loc[60, "compression_pattern"], "compressed_expansion_breakout")


def _test_config() -> CompressionBreakoutSignalConfig:
    return CompressionBreakoutSignalConfig(
        compression_lookback_bars=10,
        range_lookback_bars=20,
        volume_lookback_bars=20,
        max_compression_range_ratio=1.2,
        expansion_range_multiple=2.0,
        expansion_volume_multiple=1.5,
        breakout_buffer_points=0.25,
        close_position_long_min=0.75,
        close_position_short_max=0.25,
        trade_start="09:30",
        trade_end="12:00",
    )


def _base_bars() -> pd.DataFrame:
    times = pd.date_range("2024-01-03 09:30", periods=80, freq="min")
    close = pd.Series(100.0 + np.sin(np.arange(80) / 6.0) * 0.1)
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


if __name__ == "__main__":
    unittest.main()
