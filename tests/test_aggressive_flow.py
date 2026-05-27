from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

import pandas as pd

from backtest.aggressive_flow import (
    aggregate_aggressive_flow_minute_stats,
    build_aggressive_flow_stats_from_source,
    normalize_trade_frame,
)


def _trade_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_recv": "2025-06-17T13:30:00.100000000Z",
                "ts_event": "2025-06-17T13:30:00.000000000Z",
                "instrument_id": 1,
                "action": "T",
                "side": "B",
                "price": 22000.25,
                "size": 3,
                "symbol": "NQM5",
            },
            {
                "ts_recv": "2025-06-17T13:30:20.100000000Z",
                "ts_event": "2025-06-17T13:30:20.000000000Z",
                "instrument_id": 1,
                "action": "T",
                "side": "A",
                "price": 21999.75,
                "size": 1,
                "symbol": "NQM5",
            },
            {
                "ts_recv": "2025-06-17T13:31:00.100000000Z",
                "ts_event": "2025-06-17T13:31:00.000000000Z",
                "instrument_id": 1,
                "action": "A",
                "side": "B",
                "price": 22001.00,
                "size": 9,
                "symbol": "NQM5",
            },
        ]
    )


class AggressiveFlowTests(unittest.TestCase):
    def test_normalize_trade_frame_filters_to_trades_and_rth(self) -> None:
        out = normalize_trade_frame(_trade_rows(), symbol_regex=r"^NQ[FGHJKMNQUVXZ]\d{1,2}$")

        self.assertEqual(len(out), 2)
        self.assertTrue(bool(out.loc[out.index[0], "rth_session"]))
        self.assertIn("minute", out.columns)

    def test_aggregate_aggressive_flow_minute_stats_keeps_raw_side_flow(self) -> None:
        normalized = normalize_trade_frame(_trade_rows())
        minute = aggregate_aggressive_flow_minute_stats(normalized)

        self.assertEqual(len(minute), 1)
        row = minute.iloc[0]
        self.assertEqual(row["symbol"], "NQM5")
        self.assertEqual(int(row["trade_count"]), 2)
        self.assertAlmostEqual(float(row["trade_size"]), 4.0)
        self.assertAlmostEqual(float(row["raw_b_side_trade_size"]), 3.0)
        self.assertAlmostEqual(float(row["raw_a_side_trade_size"]), 1.0)
        self.assertAlmostEqual(float(row["raw_b_minus_a_trade_size"]), 2.0)
        self.assertAlmostEqual(float(row["raw_b_minus_a_trade_size_share"]), 0.5)

    def test_build_aggressive_flow_stats_from_zip_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "trades.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("glbx-mdp3-20250617.trades.csv", _trade_rows().to_csv(index=False))

            stats = build_aggressive_flow_stats_from_source(archive, max_files=1, progress_every=0)

            self.assertEqual(len(stats.minute_stats), 1)
            self.assertEqual(len(stats.daily_stats), 1)
            self.assertEqual(stats.daily_stats.iloc[0]["symbol"], "NQM5")


if __name__ == "__main__":
    unittest.main()
