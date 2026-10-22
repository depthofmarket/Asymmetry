import unittest
import pandas as pd

from backtest.first30min_momentum_signal import (
    First30MinMomentumConfig,
    build_first30min_momentum_signal_frame,
)


class First30MinMomentumSignalTests(unittest.TestCase):
    def test_first15_momentum_triggers_at_0944_in_return_direction(self) -> None:
        rows = [
            # Day 1: prior session to populate prior ATR
            {"time": pd.Timestamp("2024-01-02 09:30:00"), "open": 1000.0, "high": 1005.0, "low": 995.0, "close": 1002.0, "volume": 100},
            {"time": pd.Timestamp("2024-01-02 09:44:00"), "open": 1002.0, "high": 1006.0, "low": 998.0, "close": 1001.0, "volume": 100},
            # Day 2: +0.5% move from 09:30 open (1000) to 09:44 close (1005) -> LONG (+1)
            {"time": pd.Timestamp("2024-01-03 09:30:00"), "open": 1000.0, "high": 1002.0, "low": 999.0, "close": 1001.0, "volume": 100},
            {"time": pd.Timestamp("2024-01-03 09:44:00"), "open": 1003.0, "high": 1006.0, "low": 1002.0, "close": 1005.0, "volume": 100},
            # Day 3: -0.5% move from 09:30 open (1000) to 09:44 close (995) -> SHORT (-1)
            {"time": pd.Timestamp("2024-01-04 09:30:00"), "open": 1000.0, "high": 1001.0, "low": 998.0, "close": 999.0, "volume": 100},
            {"time": pd.Timestamp("2024-01-04 09:44:00"), "open": 997.0, "high": 998.0, "low": 994.0, "close": 995.0, "volume": 100},
        ]
        df = pd.DataFrame(rows)
        res = build_first30min_momentum_signal_frame(df, config=First30MinMomentumConfig(min_abs_return_pct=0.001))
        d2 = res.loc[res["time"] == pd.Timestamp("2024-01-03 09:44:00"), "candidate_signal"].iloc[0]
        d3 = res.loc[res["time"] == pd.Timestamp("2024-01-04 09:44:00"), "candidate_signal"].iloc[0]
        self.assertEqual(float(d2), 1.0)
        self.assertEqual(float(d3), -1.0)


if __name__ == "__main__":
    unittest.main()
