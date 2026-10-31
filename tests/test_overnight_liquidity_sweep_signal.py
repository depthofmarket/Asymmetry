import unittest
import pandas as pd

from backtest.overnight_liquidity_sweep_signal import (
    OvernightLiquiditySweepConfig,
    build_overnight_liquidity_sweep_signal_frame,
)


class OvernightLiquiditySweepSignalTests(unittest.TestCase):
    def test_overnight_high_sweep_and_rejection_emits_short_signal(self) -> None:
        rows = [
            # Overnight session: ONH = 15000.0, ONL = 14900.0
            {"time": pd.Timestamp("2024-01-02 20:00:00"), "open": 14950.0, "high": 15000.0, "low": 14920.0, "close": 14960.0, "volume": 100},
            {"time": pd.Timestamp("2024-01-03 04:00:00"), "open": 14960.0, "high": 14980.0, "low": 14900.0, "close": 14920.0, "volume": 100},
            # RTH open at 09:30
            {"time": pd.Timestamp("2024-01-03 09:30:00"), "open": 14930.0, "high": 14950.0, "low": 14925.0, "close": 14940.0, "volume": 1000},
            # Bar at 09:40 sweeps ONH (15000.0) up to 15008.0 (+8 pts sweep), closes at 14995.0 with low at 14990.0 (close_loc = 5/18 = 0.28 <= 0.45)
            {"time": pd.Timestamp("2024-01-03 09:40:00"), "open": 14992.0, "high": 15008.0, "low": 14990.0, "close": 14995.0, "volume": 500},
            # Next bar at 09:41
            {"time": pd.Timestamp("2024-01-03 09:41:00"), "open": 14995.0, "high": 14997.0, "low": 14980.0, "close": 14982.0, "volume": 300},
        ]
        df = pd.DataFrame(rows)
        res = build_overnight_liquidity_sweep_signal_frame(df, config=OvernightLiquiditySweepConfig())
        
        sig_0940 = res.loc[res["time"] == pd.Timestamp("2024-01-03 09:40:00"), "candidate_signal"].iloc[0]
        setup_tag_0940 = res.loc[res["time"] == pd.Timestamp("2024-01-03 09:40:00"), "setup_tag"].iloc[0]
        sweep_depth_0940 = res.loc[res["time"] == pd.Timestamp("2024-01-03 09:40:00"), "sweep_depth_points"].iloc[0]
        
        self.assertEqual(float(sig_0940), -1.0)
        self.assertEqual(str(setup_tag_0940), "onh_sweep_short")
        self.assertAlmostEqual(float(sweep_depth_0940), 8.0)

    def test_overnight_low_sweep_and_rejection_emits_long_signal(self) -> None:
        rows = [
            # Overnight session: ONH = 15000.0, ONL = 14900.0
            {"time": pd.Timestamp("2024-01-02 20:00:00"), "open": 14950.0, "high": 15000.0, "low": 14920.0, "close": 14960.0, "volume": 100},
            {"time": pd.Timestamp("2024-01-03 04:00:00"), "open": 14960.0, "high": 14980.0, "low": 14900.0, "close": 14920.0, "volume": 100},
            # RTH open at 09:30
            {"time": pd.Timestamp("2024-01-03 09:30:00"), "open": 14950.0, "high": 14960.0, "low": 14940.0, "close": 14945.0, "volume": 1000},
            # Bar at 09:45 sweeps ONL (14900.0) down to 14892.0 (-8 pts sweep), closes at 14906.0 with high at 14910.0 (close_loc = 14/18 = 0.78 >= 0.55)
            {"time": pd.Timestamp("2024-01-03 09:45:00"), "open": 14905.0, "high": 14910.0, "low": 14892.0, "close": 14906.0, "volume": 500},
        ]
        df = pd.DataFrame(rows)
        res = build_overnight_liquidity_sweep_signal_frame(df, config=OvernightLiquiditySweepConfig())
        
        sig_0945 = res.loc[res["time"] == pd.Timestamp("2024-01-03 09:45:00"), "candidate_signal"].iloc[0]
        setup_tag_0945 = res.loc[res["time"] == pd.Timestamp("2024-01-03 09:45:00"), "setup_tag"].iloc[0]
        sweep_depth_0945 = res.loc[res["time"] == pd.Timestamp("2024-01-03 09:45:00"), "sweep_depth_points"].iloc[0]
        
        self.assertEqual(float(sig_0945), 1.0)
        self.assertEqual(str(setup_tag_0945), "onl_sweep_long")
        self.assertAlmostEqual(float(sweep_depth_0945), 8.0)


if __name__ == "__main__":
    unittest.main()
