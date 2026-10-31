import unittest
import pandas as pd
import numpy as np

from backtest.midday_vwap_mean_reversion_signal import (
    MiddayVwapMeanReversionConfig,
    build_midday_vwap_mean_reversion_signal_frame,
)


class MiddayVwapMeanReversionSignalTests(unittest.TestCase):
    def test_upper_band_stretch_and_rejection_emits_short_signal(self) -> None:
        times = [
            pd.Timestamp("2024-01-03 09:30:00") + pd.Timedelta(minutes=i)
            for i in range(240) # 09:30 to 13:30
        ]
        rows = []
        # Normal morning bars with volatility: baseline around 15000, std ~20 pts
        for t in times:
            m = t.hour * 60 + t.minute
            if m < 11 * 60 + 30: # before 11:30
                rows.append({"time": t, "open": 15000.0, "high": 15020.0, "low": 14980.0, "close": 15000.0, "volume": 1000.0})
            elif m == 11 * 60 + 40: # 11:40 ET: bar spikes to 15060 (above upper band ~15004) and closes back at 15002 with low 15001
                rows.append({"time": t, "open": 15003.0, "high": 15060.0, "low": 15001.0, "close": 15002.0, "volume": 1500.0})
            else:
                rows.append({"time": t, "open": 15000.0, "high": 15010.0, "low": 14990.0, "close": 15000.0, "volume": 500.0})

        df = pd.DataFrame(rows)
        cfg = MiddayVwapMeanReversionConfig(num_std=1.5, min_std_points=2.0)
        res = build_midday_vwap_mean_reversion_signal_frame(df, config=cfg)

        target_time = pd.Timestamp("2024-01-03 11:40:00")
        sig = res.loc[res["time"] == target_time, "candidate_signal"].iloc[0]
        setup_tag = res.loc[res["time"] == target_time, "setup_tag"].iloc[0]

        self.assertEqual(float(sig), -1.0)
        self.assertEqual(str(setup_tag), "midday_vwap_upper_short")

    def test_lower_band_stretch_and_rejection_emits_long_signal(self) -> None:
        times = [
            pd.Timestamp("2024-01-03 09:30:00") + pd.Timedelta(minutes=i)
            for i in range(240) # 09:30 to 13:30
        ]
        rows = []
        for t in times:
            m = t.hour * 60 + t.minute
            if m < 11 * 60 + 30:
                rows.append({"time": t, "open": 15000.0, "high": 15020.0, "low": 14980.0, "close": 15000.0, "volume": 1000.0})
            elif m == 11 * 60 + 40: # 11:40 ET: bar dumps to 14940 (below lower band ~14996) and closes back at 14998 with high 14999
                rows.append({"time": t, "open": 14997.0, "high": 14999.0, "low": 14940.0, "close": 14998.0, "volume": 1500.0})
            else:
                rows.append({"time": t, "open": 15000.0, "high": 15010.0, "low": 14990.0, "close": 15000.0, "volume": 500.0})

        df = pd.DataFrame(rows)
        cfg = MiddayVwapMeanReversionConfig(num_std=1.5, min_std_points=2.0)
        res = build_midday_vwap_mean_reversion_signal_frame(df, config=cfg)

        target_time = pd.Timestamp("2024-01-03 11:40:00")
        sig = res.loc[res["time"] == target_time, "candidate_signal"].iloc[0]
        setup_tag = res.loc[res["time"] == target_time, "setup_tag"].iloc[0]

        self.assertEqual(float(sig), 1.0)
        self.assertEqual(str(setup_tag), "midday_vwap_lower_long")


if __name__ == "__main__":
    unittest.main()
