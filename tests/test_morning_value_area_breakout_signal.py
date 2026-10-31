import unittest
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.morning_value_area_breakout_signal import (
    MorningValueAreaBreakoutConfig,
    build_morning_value_area_breakout_signal_frame,
)
from backtest.portfolio import Portfolio
from config.backtest_config import CANDIDATE_CONFIGS, FUTURES_SPECS, STRATEGY_PARAMS


class MorningValueAreaBreakoutSignalTests(unittest.TestCase):
    def test_va_breakout_emits_long_above_vah_and_short_below_val(self) -> None:
        rows = [
            # Day 1: RTH profile centered tightly around 1000 (POC=1000, VAH=1001, VAL=999, close=1000)
            {"time": pd.Timestamp("2024-01-02 09:30:00"), "open": 1000.0, "high": 1001.0, "low": 999.0, "close": 1000.0, "volume": 5000},
            {"time": pd.Timestamp("2024-01-02 10:00:00"), "open": 1000.0, "high": 1002.0, "low": 998.0, "close": 1000.0, "volume": 100},
            # Day 2: gaps up at 1000.5 (> prior close 1000.0), rallies to close at 1015 at 09:44 -> LONG (+1)
            {"time": pd.Timestamp("2024-01-03 09:30:00"), "open": 1000.5, "high": 1005.0, "low": 1000.0, "close": 1015.0, "volume": 100},
            {"time": pd.Timestamp("2024-01-03 09:44:00"), "open": 1010.0, "high": 1016.0, "low": 1009.0, "close": 1015.0, "volume": 100},
            # Day 3: gaps down at 1014.0 (< prior close 1015.0), sells off to close at 985 at 09:44 -> SHORT (-1)
            {"time": pd.Timestamp("2024-01-04 09:30:00"), "open": 1014.0, "high": 1014.0, "low": 995.0, "close": 996.0, "volume": 100},
            {"time": pd.Timestamp("2024-01-04 09:44:00"), "open": 990.0, "high": 991.0, "low": 984.0, "close": 985.0, "volume": 100},
        ]
        df = pd.DataFrame(rows)
        res = build_morning_value_area_breakout_signal_frame(df, config=MorningValueAreaBreakoutConfig())
        d2 = res.loc[res["time"] == pd.Timestamp("2024-01-03 09:44:00"), "candidate_signal"].iloc[0]
        d3 = res.loc[res["time"] == pd.Timestamp("2024-01-04 09:44:00"), "candidate_signal"].iloc[0]
        self.assertEqual(float(d2), 1.0)
        self.assertEqual(float(d3), -1.0)

    def test_backtest_engine_morning_va_breakout_triggers_at_0940_5m_bar(self) -> None:
        rows = []
        # Day 1: 60 minutes of RTH bars around 1000.0
        for m in range(60):
            ts = pd.Timestamp("2024-01-02 09:30:00") + pd.Timedelta(minutes=m)
            rows.append({"time": ts, "open": 1000.0, "high": 1001.0, "low": 999.0, "close": 1000.0, "volume": 200})
        # Day 2: gap up open at 1002.0, steady rise through 09:44 to 1018.0, then rally through 10:15
        for m in range(60):
            ts = pd.Timestamp("2024-01-03 09:30:00") + pd.Timedelta(minutes=m)
            px = 1002.0 + m * 1.0
            rows.append({"time": ts, "open": px, "high": px + 1.5, "low": px - 0.5, "close": px + 1.0, "volume": 200})
        df = pd.DataFrame(rows)
        params = dict(STRATEGY_PARAMS)
        params.update(CANDIDATE_CONFIGS["morning_va_breakout_with_gap"])
        portfolio = Portfolio(100000, FUTURES_SPECS)
        engine = BacktestEngine(df, portfolio, FUTURES_SPECS, params)
        sig_df = engine.build_signal_frame()
        sig_0940 = sig_df.loc[sig_df["time"] == pd.Timestamp("2024-01-03 09:40:00"), "signal"].iloc[0]
        self.assertEqual(int(sig_0940), 1)
        # Ensure earlier bars (09:30, 09:35) have masked or15_close and 0 signal
        sig_0935 = sig_df.loc[sig_df["time"] == pd.Timestamp("2024-01-03 09:35:00"), "signal"].iloc[0]
        self.assertEqual(int(sig_0935), 0)
        self.assertTrue(pd.isna(sig_df.loc[sig_df["time"] == pd.Timestamp("2024-01-03 09:35:00"), "or15_close"].iloc[0]))

    def test_backtest_engine_continuation_signal_triggers_on_break_above_morning_high(self) -> None:
        rows = []
        for m in range(60):
            ts = pd.Timestamp("2024-01-02 09:30:00") + pd.Timedelta(minutes=m)
            rows.append({"time": ts, "open": 1000.0, "high": 1001.0, "low": 999.0, "close": 1000.0, "volume": 200})
        for m in range(180):
            ts = pd.Timestamp("2024-01-03 09:30:00") + pd.Timedelta(minutes=m)
            if m <= 45:
                px = 1002.0 + m * 0.5
            elif m <= 60:
                px = 1020.0
            else:
                px = 1022.0 + (m - 60) * 0.5
            rows.append({"time": ts, "open": px, "high": px + 1.0, "low": px - 0.5, "close": px + 0.5, "volume": 200})
        df = pd.DataFrame(rows)
        params = dict(STRATEGY_PARAMS)
        params.update(CANDIDATE_CONFIGS["morning_va_breakout_with_gap_continuation_long_only_time_exit"])
        portfolio = Portfolio(100000, FUTURES_SPECS)
        engine = BacktestEngine(df, portfolio, FUTURES_SPECS, params)
        sig_df = engine.build_signal_frame()
        self.assertIn("va_continuation", sig_df["signal_type"].values)


if __name__ == "__main__":
    unittest.main()
