from __future__ import annotations

import unittest

import pandas as pd

from backtest.live_parity import compare_trade_logs


class LiveParityTests(unittest.TestCase):
    def test_compare_trade_logs_passes_for_matching_rows(self) -> None:
        trades = pd.DataFrame(
            {
                "entry_time": [pd.Timestamp("2024-01-03 10:00")],
                "exit_time": [pd.Timestamp("2024-01-03 10:05")],
                "direction": ["long"],
                "signal_type": ["trend"],
                "setup_tag": ["trend_long"],
                "entry_price": [100.0],
                "exit_price": [102.0],
                "contracts": [1],
                "reason": ["profit_target"],
            }
        )

        report = compare_trade_logs(trades, trades.copy())

        self.assertTrue(report.passed)
        self.assertEqual(report.backtest_trades, 1)
        self.assertEqual(len(report.mismatches), 0)

    def test_compare_trade_logs_reports_field_mismatch(self) -> None:
        backtest = pd.DataFrame(
            {
                "entry_time": [pd.Timestamp("2024-01-03 10:00")],
                "exit_time": [pd.Timestamp("2024-01-03 10:05")],
                "direction": ["long"],
                "signal_type": ["trend"],
                "setup_tag": ["trend_long"],
                "entry_price": [100.0],
                "exit_price": [102.0],
                "contracts": [1],
                "reason": ["profit_target"],
            }
        )
        paper = backtest.copy()
        paper.loc[0, "reason"] = "time_exit"

        report = compare_trade_logs(backtest, paper)

        self.assertFalse(report.passed)
        self.assertEqual(report.mismatches[0].field, "reason")


if __name__ == "__main__":
    unittest.main()
