from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.l2_execution_comparison import compare_l2_vs_bar_execution, write_l2_execution_comparison


class L2ExecutionComparisonTests(unittest.TestCase):
    def test_compares_bar_and_l2_trade_groups(self) -> None:
        bar = pd.DataFrame(
            [
                {
                    "entry_time": "2024-01-02T14:30:00Z",
                    "exit_time": "2024-01-02T14:35:00Z",
                    "direction": "long",
                    "setup_tag": "unit",
                    "entry_price": 100.0,
                    "exit_price": 101.0,
                    "pnl": 20.0,
                }
            ]
        )
        l2 = pd.DataFrame(
            [
                {
                    "entry_time": "2024-01-02T14:30:01Z",
                    "exit_time": "2024-01-02T14:35:01Z",
                    "direction": "long",
                    "setup_tag": "unit",
                    "entry_price": 100.25,
                    "exit_price": 100.75,
                    "pnl": 10.0,
                }
            ]
        )

        artifacts = compare_l2_vs_bar_execution(bar, l2)
        comparison = artifacts.comparison

        self.assertEqual(len(comparison), 1)
        self.assertEqual(str(comparison.loc[0, "trade_date"]), "2024-01-02")
        self.assertAlmostEqual(float(comparison.loc[0, "net_pnl_delta"]), -10.0)
        self.assertAlmostEqual(float(comparison.loc[0, "entry_price_delta"]), 0.25)
        self.assertIn("not live-edge proof", artifacts.report_md)

    def test_writer_emits_comparison_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bar_csv = root / "bar.csv"
            l2_csv = root / "l2.csv"
            pd.DataFrame(
                [{"entry_time": "2024-01-02T14:30:00Z", "exit_time": "2024-01-02T14:31:00Z", "direction": "long", "setup_tag": "unit", "pnl": 20.0}]
            ).to_csv(bar_csv, index=False)
            pd.DataFrame(
                [{"entry_time": "2024-01-02T14:30:00Z", "exit_time": "2024-01-02T14:31:00Z", "direction": "long", "setup_tag": "unit", "pnl": 15.0}]
            ).to_csv(l2_csv, index=False)

            paths = write_l2_execution_comparison(bar_csv, l2_csv, root / "out", prefix="unit")

            self.assertTrue(paths.normalized_trades_csv.exists())
            self.assertTrue(paths.grouped_summary_csv.exists())
            self.assertTrue(paths.comparison_csv.exists())
            self.assertIn("does not run a backtest", paths.report_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
