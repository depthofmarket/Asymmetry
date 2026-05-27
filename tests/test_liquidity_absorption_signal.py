from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backtest.liquidity_absorption_signal import (
    LiquidityAbsorptionSignalConfig,
    build_liquidity_absorption_signal_export,
    build_liquidity_absorption_signal_frame,
)


class LiquidityAbsorptionSignalTests(unittest.TestCase):
    def test_builds_short_signal_after_failed_up_sweep(self) -> None:
        data = _base_bars()
        data.loc[60, ["open", "high", "low", "close", "volume"]] = [100.0, 108.0, 99.5, 101.0, 4000]
        data.loc[61, ["open", "high", "low", "close", "volume"]] = [101.0, 106.0, 100.5, 103.0, 1300]
        data.loc[62, ["open", "high", "low", "close", "volume"]] = [103.0, 106.5, 100.0, 106.0, 1300]

        frame = build_liquidity_absorption_signal_frame(data, config=_test_config())

        self.assertEqual(float(frame.loc[62, "signal"]), -1.0)
        self.assertEqual(frame.loc[62, "liquidity_expansion_side"], "up_sweep")
        self.assertLess(float(frame.loc[62, "absorption_score"]), 0.0)

    def test_builds_long_signal_after_failed_down_sweep(self) -> None:
        data = _base_bars()
        data.loc[60, ["open", "high", "low", "close", "volume"]] = [100.0, 100.5, 92.0, 99.0, 4000]
        data.loc[61, ["open", "high", "low", "close", "volume"]] = [99.0, 99.5, 94.0, 97.0, 1300]
        data.loc[62, ["open", "high", "low", "close", "volume"]] = [97.0, 100.0, 94.5, 94.0, 1300]

        frame = build_liquidity_absorption_signal_frame(data, config=_test_config())

        self.assertEqual(float(frame.loc[62, "signal"]), 1.0)
        self.assertEqual(frame.loc[62, "liquidity_expansion_side"], "down_sweep")
        self.assertGreater(float(frame.loc[62, "absorption_score"]), 0.0)

    def test_future_rows_do_not_change_prior_signal(self) -> None:
        data = _base_bars()
        data.loc[60, ["open", "high", "low", "close", "volume"]] = [100.0, 108.0, 99.5, 101.0, 4000]
        data.loc[61, ["open", "high", "low", "close", "volume"]] = [101.0, 106.0, 100.5, 103.0, 1300]
        data.loc[62, ["open", "high", "low", "close", "volume"]] = [103.0, 106.5, 100.0, 106.0, 1300]
        mutated = data.copy()
        mutated.loc[63:, "close"] = mutated.loc[63:, "close"] + 50.0

        frame = build_liquidity_absorption_signal_frame(data, config=_test_config())
        changed = build_liquidity_absorption_signal_frame(mutated, config=_test_config())

        pd.testing.assert_series_equal(frame.loc[:62, "signal"], changed.loc[:62, "signal"])

    def test_export_includes_gate_columns(self) -> None:
        data = _base_bars()
        data.loc[60, ["open", "high", "low", "close", "volume"]] = [100.0, 108.0, 99.5, 101.0, 4000]
        data.loc[61, ["open", "high", "low", "close", "volume"]] = [101.0, 106.0, 100.5, 103.0, 1300]
        data.loc[62, ["open", "high", "low", "close", "volume"]] = [103.0, 106.5, 100.0, 106.0, 1300]
        export = build_liquidity_absorption_signal_export(data, config=_test_config())

        self.assertIn("candidate_signal", export.columns)
        self.assertIn("absorption_score", export.columns)
        self.assertIn("liquidity_expansion_side", export.columns)
        self.assertIn("absorption_pattern", export.columns)
        self.assertEqual(export.loc[62, "liquidity_expansion_side"], "up_sweep")
        self.assertEqual(export.loc[62, "absorption_pattern"], "failed_continuation")


def _test_config() -> LiquidityAbsorptionSignalConfig:
    return LiquidityAbsorptionSignalConfig(
        sweep_lookback_bars=10,
        range_lookback_bars=10,
        volume_lookback_bars=10,
        confirmation_bars=2,
        expansion_range_multiple=2.0,
        expansion_volume_multiple=1.5,
        sweep_buffer_points=0.25,
        failure_reentry_points=1.0,
        followthrough_tolerance_points=0.5,
        event_close_position_short_max=0.55,
        event_close_position_long_min=0.45,
        trade_start="09:30",
        trade_end="12:00",
    )


def _base_bars() -> pd.DataFrame:
    times = pd.date_range("2024-01-03 09:30", periods=80, freq="1min")
    close = pd.Series(100.0 + np.sin(np.arange(80) / 6.0) * 0.5)
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
