import unittest
import pandas as pd

from backtest.poc_rejection_signal import (
    PocRejectionSignalConfig,
    build_poc_rejection_signal_frame,
)


class PocRejectionSignalTests(unittest.TestCase):
    def test_poc_touch_and_reject_emits_fade_signal_on_confirmation_bar(self) -> None:
        rows = [
            # Day 1: heavy volume at 1000.0 (POC = 1000.0), range = 40.0
            {"time": pd.Timestamp("2024-01-02 09:30:00"), "open": 1000.0, "high": 1001.0, "low": 999.0, "close": 1000.0, "volume": 5000},
            {"time": pd.Timestamp("2024-01-02 10:00:00"), "open": 1015.0, "high": 1020.0, "low": 980.0, "close": 1010.0, "volume": 100},
            # Day 2: opens at 990 (below POC 1000), rallies to touch 1000 at 09:35, rejects at 09:36 (< 1000) -> SHORT (-1) at 09:36
            {"time": pd.Timestamp("2024-01-03 09:30:00"), "open": 990.0, "high": 992.0, "low": 989.0, "close": 991.0, "volume": 100},
            {"time": pd.Timestamp("2024-01-03 09:35:00"), "open": 996.0, "high": 1001.0, "low": 995.0, "close": 999.5, "volume": 100},
            {"time": pd.Timestamp("2024-01-03 09:36:00"), "open": 999.5, "high": 1000.0, "low": 997.0, "close": 998.0, "volume": 100},
            {"time": pd.Timestamp("2024-01-03 09:37:00"), "open": 998.0, "high": 999.0, "low": 993.0, "close": 994.0, "volume": 100},
        ]
        df = pd.DataFrame(rows)
        res = build_poc_rejection_signal_frame(df, config=PocRejectionSignalConfig())
        sig_0936 = res.loc[res["time"] == pd.Timestamp("2024-01-03 09:36:00"), "candidate_signal"].iloc[0]
        lvl_type = res.loc[res["time"] == pd.Timestamp("2024-01-03 09:36:00"), "reference_level_type"].iloc[0]
        self.assertEqual(float(sig_0936), -1.0)
        self.assertEqual(str(lvl_type), "POC")


if __name__ == "__main__":
    unittest.main()
