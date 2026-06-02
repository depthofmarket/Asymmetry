from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.l2_prop_bridge import (
    build_l2_daily_prop_path,
    build_l2_trade_log_from_fills,
    write_l2_prop_bridge_artifacts,
)


class L2PropBridgeTests(unittest.TestCase):
    def test_fifo_trade_log_builds_long_and_daily_path(self) -> None:
        fills = pd.DataFrame(
            [
                {
                    "order_id": "entry",
                    "side": "buy",
                    "fill_time": "2024-01-02T14:30:00Z",
                    "event_seq": 1,
                    "quantity": 1,
                    "price": 100.25,
                    "tag": "bar_signal_entry:20240102T142500_0_long:unit_long",
                },
                {
                    "order_id": "exit",
                    "side": "sell",
                    "fill_time": "2024-01-02T14:31:00Z",
                    "event_seq": 2,
                    "quantity": 1,
                    "price": 101.00,
                    "tag": "bar_signal_exit:max_hold:20240102T142500_0_long",
                },
            ]
        )

        trades = build_l2_trade_log_from_fills(fills, contract_value=20.0)
        daily = build_l2_daily_prop_path(trades)

        self.assertEqual(len(trades), 1)
        self.assertEqual(str(trades.loc[0, "direction"]), "long")
        self.assertAlmostEqual(float(trades.loc[0, "pnl_points"]), 0.75)
        self.assertAlmostEqual(float(trades.loc[0, "pnl"]), 15.0)
        self.assertEqual(str(trades.loc[0, "signal_id"]), "20240102T142500_0_long")
        self.assertEqual(str(trades.loc[0, "setup_tag"]), "unit_long")
        self.assertEqual(str(daily.loc[0, "trade_date"]), "2024-01-02")
        self.assertAlmostEqual(float(daily.loc[0, "net_pnl"]), 15.0)

    def test_fifo_trade_log_builds_short_trade(self) -> None:
        fills = pd.DataFrame(
            [
                {"order_id": "entry", "side": "sell", "fill_time": "2024-01-02T14:30:00Z", "event_seq": 1, "quantity": 2, "price": 100.00, "tag": "short_entry"},
                {"order_id": "exit", "side": "buy", "fill_time": "2024-01-02T14:31:00Z", "event_seq": 2, "quantity": 2, "price": 99.50, "tag": "short_exit"},
            ]
        )

        trades = build_l2_trade_log_from_fills(fills, contract_value=20.0)

        self.assertEqual(len(trades), 1)
        self.assertEqual(str(trades.loc[0, "direction"]), "short")
        self.assertAlmostEqual(float(trades.loc[0, "pnl_points"]), 1.0)
        self.assertAlmostEqual(float(trades.loc[0, "pnl"]), 20.0)

    def test_writer_emits_prop_bridge_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fills_csv = root / "fills.csv"
            pd.DataFrame(
                [
                    {"order_id": "entry", "side": "buy", "fill_time": "2024-01-02T14:30:00Z", "event_seq": 1, "quantity": 1, "price": 100.00, "tag": "entry"},
                    {"order_id": "exit", "side": "sell", "fill_time": "2024-01-02T14:31:00Z", "event_seq": 2, "quantity": 1, "price": 100.50, "tag": "exit"},
                ]
            ).to_csv(fills_csv, index=False)

            paths = write_l2_prop_bridge_artifacts(fills_csv, root / "out", prefix="unit")

            self.assertTrue(paths.trade_log_csv.exists())
            self.assertTrue(paths.daily_prop_path_csv.exists())
            self.assertTrue(paths.summary_csv.exists())
            self.assertIn("does not run a backtest", paths.report_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
