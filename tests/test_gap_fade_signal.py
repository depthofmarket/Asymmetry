import unittest
import numpy as np
import pandas as pd

from backtest.gap_fade_signal import (
    GapFadeSignalConfig,
    build_gap_fade_signal_frame,
    _daily_rth_stats,
)


class GapFadeSignalTests(unittest.TestCase):
    def test_daily_rth_stats_shifts_strictly_by_one_day(self) -> None:
        # Create 3 days of RTH bars
        times = [
            # Day 1: 2024-01-02
            pd.Timestamp("2024-01-02 09:30:00"),
            pd.Timestamp("2024-01-02 16:00:00"),
            # Day 2: 2024-01-03
            pd.Timestamp("2024-01-03 09:30:00"),
            pd.Timestamp("2024-01-03 16:00:00"),
            # Day 3: 2024-01-04
            pd.Timestamp("2024-01-04 09:30:00"),
            pd.Timestamp("2024-01-04 16:00:00"),
        ]
        rth = pd.DataFrame(
            {
                "time": times,
                "open": [100.0, 105.0, 110.0, 115.0, 120.0, 125.0],
                "high": [106.0, 108.0, 116.0, 118.0, 126.0, 128.0],
                "low": [99.0, 104.0, 109.0, 114.0, 119.0, 124.0],
                "close": [105.0, 107.0, 115.0, 117.0, 125.0, 127.0],
                "volume": [10, 10, 10, 10, 10, 10],
            }
        )

        daily = _daily_rth_stats(rth, atr_window=2)
        # Day 1 prior_close should be NaN
        self.assertTrue(pd.isna(daily.loc[0, "prior_close"]))
        # Day 2 prior_close must be Day 1 close (107.0)
        self.assertEqual(daily.loc[1, "prior_close"], 107.0)
        # Day 3 prior_close must be Day 2 close (117.0)
        self.assertEqual(daily.loc[2, "prior_close"], 117.0)

    def test_build_gap_fade_signal_fades_gap_up_and_down(self) -> None:
        # Day 1: close 100.0, range 10
        # Day 2: opens 102.0 (+2% gap up) -> should trigger SHORT
        # Day 3: opens 98.0 (-2% gap down) -> should trigger LONG
        times = [
            # Day 1
            pd.Timestamp("2024-01-02 09:30:00"),
            pd.Timestamp("2024-01-02 16:00:00"),
            # Day 2 (gap up)
            pd.Timestamp("2024-01-03 09:30:00"),
            pd.Timestamp("2024-01-03 16:00:00"),
            # Day 3 (gap down)
            pd.Timestamp("2024-01-04 09:30:00"),
            pd.Timestamp("2024-01-04 16:00:00"),
        ]
        df = pd.DataFrame(
            {
                "time": times,
                "open": [100.0, 100.0, 102.0, 102.0, 98.0, 98.0],
                "high": [105.0, 105.0, 105.0, 105.0, 100.0, 100.0],
                "low": [95.0, 95.0, 100.0, 100.0, 95.0, 95.0],
                "close": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
                "volume": [10, 10, 10, 10, 10, 10],
            }
        )

        cfg = GapFadeSignalConfig(min_gap_pct=0.01, min_gap_to_atr_ratio=0.1, atr_window_days=1)
        res = build_gap_fade_signal_frame(df, config=cfg)

        # Day 2 09:30 should be Short (-1.0)
        day2_signal = res.loc[res["time"] == pd.Timestamp("2024-01-03 09:30:00"), "candidate_signal"].iloc[0]
        self.assertEqual(day2_signal, -1.0)

        # Day 3 09:30 should be Long (+1.0)
        day3_signal = res.loc[res["time"] == pd.Timestamp("2024-01-04 09:30:00"), "candidate_signal"].iloc[0]
        self.assertEqual(day3_signal, 1.0)


if __name__ == "__main__":
    unittest.main()
