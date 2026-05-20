from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

import pandas as pd

from backtest.tbbo_execution import (
    aggregate_tbbo_minute_stats,
    build_tbbo_execution_stats_from_source,
    normalize_tbbo_frame,
)


def _tbbo_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_recv": "2026-02-16T14:30:00.100000000Z",
                "ts_event": "2026-02-16T14:30:00.000000000Z",
                "instrument_id": 1,
                "action": "T",
                "side": "B",
                "price": 24832.25,
                "size": 2,
                "bid_px_00": 24831.75,
                "ask_px_00": 24832.25,
                "bid_sz_00": 4,
                "ask_sz_00": 2,
                "bid_ct_00": 3,
                "ask_ct_00": 1,
                "symbol": "NQH6",
            },
            {
                "ts_recv": "2026-02-16T14:30:20.100000000Z",
                "ts_event": "2026-02-16T14:30:20.000000000Z",
                "instrument_id": 1,
                "action": "T",
                "side": "A",
                "price": 24831.75,
                "size": 1,
                "bid_px_00": 24831.75,
                "ask_px_00": 24832.50,
                "bid_sz_00": 3,
                "ask_sz_00": 3,
                "bid_ct_00": 2,
                "ask_ct_00": 2,
                "symbol": "NQH6",
            },
        ]
    )


class TbboExecutionTests(unittest.TestCase):
    def test_normalize_tbbo_frame_adds_execution_quality_columns(self) -> None:
        out = normalize_tbbo_frame(_tbbo_rows())

        self.assertIn("mid_price", out.columns)
        self.assertIn("spread_ticks", out.columns)
        self.assertIn("top_book_imbalance", out.columns)
        self.assertIn("trade_price_vs_mid", out.columns)
        self.assertEqual(float(out.loc[0, "spread_ticks"]), 2.0)
        self.assertEqual(float(out.loc[0, "top_book_imbalance"]), 1.0 / 3.0)
        self.assertTrue(bool(out.loc[0, "rth_session"]))

    def test_normalize_tbbo_frame_filters_symbols(self) -> None:
        rows = pd.concat(
            [
                _tbbo_rows(),
                pd.DataFrame(
                    [
                        {
                            **_tbbo_rows().iloc[0].to_dict(),
                            "symbol": "NQH6-NQM6",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

        out = normalize_tbbo_frame(rows, symbol_regex=r"^NQ[FGHJKMNQUVXZ]\d{1,2}$")

        self.assertEqual(set(out["symbol"]), {"NQH6"})

    def test_aggregate_tbbo_minute_stats_counts_raw_sides_and_spread(self) -> None:
        normalized = normalize_tbbo_frame(_tbbo_rows())
        minute = aggregate_tbbo_minute_stats(normalized)

        self.assertEqual(len(minute), 1)
        row = minute.iloc[0]
        self.assertEqual(row["symbol"], "NQH6")
        self.assertEqual(int(row["trade_count"]), 2)
        self.assertEqual(int(row["raw_b_side_count"]), 1)
        self.assertEqual(int(row["raw_a_side_count"]), 1)
        self.assertAlmostEqual(float(row["median_spread_points"]), 0.625)

    def test_build_tbbo_execution_stats_from_zip_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "tbbo.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("glbx-mdp3-20260216.tbbo.csv", _tbbo_rows().to_csv(index=False))

            stats = build_tbbo_execution_stats_from_source(archive, max_files=1, progress_every=0)

            self.assertEqual(len(stats.minute_stats), 1)
            self.assertEqual(len(stats.daily_stats), 1)
            self.assertEqual(stats.daily_stats.iloc[0]["symbol"], "NQH6")


if __name__ == "__main__":
    unittest.main()
