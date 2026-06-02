from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.l2_parquet_audit import discover_parquet_files, infer_l2_column_map, sample_l2_quality


class L2ParquetAuditTests(unittest.TestCase):
    def test_infer_l2_column_map_handles_databento_tbbo_names(self) -> None:
        column_map = infer_l2_column_map(
            [
                "ts_event",
                "symbol",
                "bid_px_00",
                "ask_px_00",
                "bid_sz_00",
                "ask_sz_00",
                "bid_px_01",
                "ask_px_01",
            ]
        )

        self.assertEqual(column_map.timestamp, "ts_event")
        self.assertEqual(column_map.symbol, "symbol")
        self.assertEqual(column_map.bid_price, "bid_px_00")
        self.assertEqual(column_map.ask_price, "ask_px_00")
        self.assertEqual(column_map.bid_size, "bid_sz_00")
        self.assertEqual(column_map.ask_size, "ask_sz_00")
        self.assertEqual(column_map.bid_price_levels, ("bid_px_00", "bid_px_01"))
        self.assertEqual(column_map.ask_price_levels, ("ask_px_00", "ask_px_01"))

    def test_sample_l2_quality_flags_bad_spreads(self) -> None:
        sample = pd.DataFrame(
            [
                {
                    "timestamp": "2026-01-02T14:30:00Z",
                    "symbol": "NQH6",
                    "bid_price_1": 20000.00,
                    "ask_price_1": 20000.25,
                    "bid_size_1": 4,
                    "ask_size_1": 5,
                },
                {
                    "timestamp": "2026-01-02T14:30:01Z",
                    "symbol": "NQH6",
                    "bid_price_1": 20000.50,
                    "ask_price_1": 20000.25,
                    "bid_size_1": 4,
                    "ask_size_1": 5,
                },
            ]
        )

        row = sample_l2_quality(sample, path="sample.parquet")

        self.assertEqual(row["timestamp_col"], "timestamp")
        self.assertEqual(row["bid_price_col"], "bid_price_1")
        self.assertEqual(row["ask_price_col"], "ask_price_1")
        self.assertEqual(row["sample_rows"], 2)
        self.assertIn("negative_spreads", row["warnings"])
        self.assertEqual(float(row["negative_spread_pct"]), 0.5)

    def test_discover_parquet_files_is_bounded_and_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.parquet").write_text("", encoding="utf-8")
            (root / "a.parquet").write_text("", encoding="utf-8")
            (root / "ignore.csv").write_text("", encoding="utf-8")

            files = discover_parquet_files(root, max_files=1)

            self.assertEqual([path.name for path in files], ["a.parquet"])


if __name__ == "__main__":
    unittest.main()
