import unittest

import numpy as np
import pandas as pd

from backtest.study_chart_replay import (
    OOS_START,
    ReplaySpec,
    _walk_exit,
    assert_insample_bars,
    replay_macro_0835,
)


def _bars(start: str, minutes: int, close: float) -> pd.DataFrame:
    times = pd.date_range(start, periods=minutes, freq="min")
    return pd.DataFrame({
        "time": times,
        "open": close,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 100.0,
    })


class TestStudyChartReplay(unittest.TestCase):
    def test_protected_period_bars_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assert_insample_bars(pd.Series([OOS_START]))

    def test_duplicate_timestamps_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assert_insample_bars(pd.Series(pd.to_datetime(["2024-01-02 09:30", "2024-01-02 09:30"])))

    def test_chart_tracker_takes_the_target_before_the_stop_on_the_same_later_bar(self) -> None:
        spec = ReplaySpec("macro_momentum_s2", "MNQ", 2.0, 0.25, "test")
        times = np.array(pd.to_datetime(["2024-06-03 08:35", "2024-06-03 08:36"]), dtype="datetime64[ns]")
        row = _walk_exit(
            spec, "long", 0, 100.0, 80.0, 130.0, 1, None,
            times, np.array([101.0, 140.0]), np.array([99.0, 70.0]), np.array([100.0, 90.0]),
        )
        self.assertEqual(row["exit_reason"], "target")
        self.assertEqual(row["exit_price"], 130.0)
        self.assertEqual(row["commission_usd"], 0.0)
        self.assertEqual(row["slippage_usd"], 0.0)
        self.assertEqual(row["net_pnl"], row["gross_pnl"])

    def test_macro_replay_does_not_emit_a_ten_am_trade(self) -> None:
        # 08:35 has no overnight break. 10:05 would be a large break of the morning range.
        morning = _bars("2024-06-03 00:00", 8 * 60 + 40, 100.0)
        ten = _bars("2024-06-03 10:00", 10, 100.0)
        ten.loc[ten.index[:5], ["open", "high", "low", "close"]] = [100.0, 130.0, 100.0, 129.0]
        ten.loc[ten.index[5], ["open", "high", "low", "close"]] = [129.0, 131.0, 128.0, 130.0]
        frame = pd.concat([morning, ten], ignore_index=True)
        trades = replay_macro_0835(frame, ReplaySpec("macro_momentum_s2", "MNQ", 2.0, 0.25, "test"))
        self.assertTrue(trades.empty)
