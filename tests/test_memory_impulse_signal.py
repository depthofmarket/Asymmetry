from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backtest.memory_impulse_signal import (
    MemoryImpulseSignalConfig,
    build_memory_impulse_signal_export,
    build_memory_impulse_signal_frame,
)


class MemoryImpulseSignalTests(unittest.TestCase):
    def test_builds_impulse_continuation_signals_without_time_filter(self) -> None:
        frame = build_memory_impulse_signal_frame(_trending_bars(), config=_loose_config())

        active = frame.loc[frame["signal"].ne(0)]
        self.assertFalse(active.empty)
        self.assertTrue(set(active["signal"].unique()).issubset({1.0}))
        self.assertEqual(active.iloc[0]["memory_impulse_pattern"], "persistent_memory_impulse_continuation")
        self.assertGreaterEqual(float(active.iloc[0]["prior_memory_persistence"]), 0.0)

    def test_event_filter_blocks_when_threshold_is_unreachable(self) -> None:
        frame = build_memory_impulse_signal_frame(
            _trending_bars(),
            config=MemoryImpulseSignalConfig(
                atr_lookback_bars=10,
                cusum_event_atr_multiple=0.25,
                cusum_min_threshold_points=0.05,
                min_event_move_atr=999.0,
                memory_window_bars=32,
                memory_min_bars=20,
                min_persistence=0.0,
                max_entropy=1.0,
                max_complexity=1.0,
                cooldown_bars=0,
            ),
        )

        self.assertEqual(int(frame["signal"].ne(0).sum()), 0)

    def test_future_rows_do_not_change_prior_signal(self) -> None:
        data = _trending_bars()
        base = build_memory_impulse_signal_frame(data, config=_loose_config())
        first_signal_idx = int(base.index[base["signal"].ne(0)][0])
        mutated = data.copy()
        mutated.loc[first_signal_idx + 1 :, "close"] = mutated.loc[first_signal_idx + 1 :, "close"] + 50.0

        changed = build_memory_impulse_signal_frame(mutated, config=_loose_config())

        pd.testing.assert_series_equal(base.loc[:first_signal_idx, "signal"], changed.loc[:first_signal_idx, "signal"])

    def test_export_includes_gate_columns(self) -> None:
        export = build_memory_impulse_signal_export(_trending_bars(), config=_loose_config())

        self.assertIn("candidate_signal", export.columns)
        self.assertIn("memory_impulse_score", export.columns)
        self.assertIn("prior_memory_state", export.columns)
        self.assertIn("memory_impulse_pattern", export.columns)
        self.assertTrue(export["candidate_signal"].ne(0).any())


def _loose_config() -> MemoryImpulseSignalConfig:
    return MemoryImpulseSignalConfig(
        atr_lookback_bars=10,
        cusum_event_atr_multiple=0.25,
        cusum_min_threshold_points=0.05,
        min_event_move_atr=0.10,
        memory_window_bars=32,
        memory_min_bars=20,
        min_persistence=0.0,
        max_entropy=1.0,
        max_complexity=1.0,
        cooldown_bars=0,
    )


def _trending_bars() -> pd.DataFrame:
    periods = 120
    times = pd.date_range("2024-01-03 00:00", periods=periods, freq="1min")
    increments = 0.10 + np.sin(np.arange(periods) / 7.0) * 0.01
    close = pd.Series(100.0 + np.cumsum(increments))
    return pd.DataFrame(
        {
            "time": times,
            "open": close.shift(1).fillna(close.iloc[0] - 0.10),
            "high": close + 0.08,
            "low": close - 0.08,
            "close": close,
            "volume": 1000,
        }
    )


if __name__ == "__main__":
    unittest.main()
