import unittest
import pandas as pd

from backtest.afternoon_vwap_pullback_signal import (
    AfternoonVwapPullbackConfig,
    build_afternoon_vwap_pullback_signal_frame,
)


class AfternoonVwapPullbackSignalTests(unittest.TestCase):
    def test_uptrend_vwap_pullback_and_breakout_emits_long_signal(self) -> None:
        times = [
            pd.Timestamp("2024-01-03 09:30:00") + pd.Timedelta(minutes=i)
            for i in range(300)  # 09:30 to 14:29
        ]
        rows = []
        for idx, t in enumerate(times):
            m = t.hour * 60 + t.minute
            if idx == 0:
                # Open at 15000
                rows.append({"time": t, "open": 15000.0, "high": 15005.0, "low": 14998.0, "close": 15002.0, "volume": 1000.0})
            elif m <= 10 * 60 + 30:
                # Initial balance 15000..15030 (IB mid ~ 15014)
                rows.append({"time": t, "open": 15010.0, "high": 15025.0, "low": 15005.0, "close": 15020.0, "volume": 1000.0})
            elif m < 13 * 60 + 30:
                # Morning uptrend around 15035..15055 so VWAP ~ 15032, std ~ 12
                rows.append({"time": t, "open": 15040.0, "high": 15050.0, "low": 15035.0, "close": 15045.0, "volume": 1000.0})
            elif m == 13 * 60 + 35:
                # Pullback bar testing near VWAP (~15033)
                rows.append({"time": t, "open": 15038.0, "high": 15039.0, "low": 15032.0, "close": 15034.0, "volume": 1000.0})
            elif m == 13 * 60 + 36:
                # Resumption bar: breaks above prior high (15039.0), closes at 15044.0 (>0.15% from 15000), close_loc = 9/10 = 0.90
                rows.append({"time": t, "open": 15035.0, "high": 15045.0, "low": 15035.0, "close": 15044.0, "volume": 1500.0})
            else:
                rows.append({"time": t, "open": 15040.0, "high": 15045.0, "low": 15038.0, "close": 15042.0, "volume": 800.0})

        df = pd.DataFrame(rows)
        res = build_afternoon_vwap_pullback_signal_frame(df, config=AfternoonVwapPullbackConfig())
        target_time = pd.Timestamp("2024-01-03 13:36:00")
        sig = res.loc[res["time"] == target_time, "candidate_signal"].iloc[0]
        setup_tag = res.loc[res["time"] == target_time, "setup_tag"].iloc[0]

        self.assertEqual(float(sig), 1.0)
        self.assertEqual(str(setup_tag), "afternoon_vwap_pullback_long")


if __name__ == "__main__":
    unittest.main()
