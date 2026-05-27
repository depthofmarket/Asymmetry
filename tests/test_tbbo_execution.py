from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

import pandas as pd
import zstandard as zstd

from backtest.tbbo_dbn import build_tbbo_execution_stats_from_dbn, infer_dbn_symbol
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


def _dbn_record(
    *,
    ts_event: int,
    ts_recv: int,
    instrument_id: int = 42_008_411,
    price: float,
    size: int,
    side: bytes,
    bid_px: float,
    ask_px: float,
    bid_sz: int,
    ask_sz: int,
    bid_ct: int = 1,
    ask_ct: int = 1,
    sequence: int = 1,
) -> bytes:
    return struct.pack(
        "<BBHIQqIccccQiIqqIIII",
        20,
        1,
        1,
        instrument_id,
        ts_event,
        int(price * 1_000_000_000),
        size,
        b"T",
        side,
        b"\0",
        b"\0",
        ts_recv,
        1_000,
        sequence,
        int(bid_px * 1_000_000_000),
        int(ask_px * 1_000_000_000),
        bid_sz,
        ask_sz,
        bid_ct,
        ask_ct,
    )


def _write_synthetic_dbn(path: Path, records: list[bytes]) -> None:
    metadata = (
        b"GLBX.MDP3".ljust(16, b"\0")
        + struct.pack(
            "<HQQQBBB",
            3,
            pd.Timestamp("2024-12-18", tz="UTC").value,
            pd.Timestamp("2024-12-19", tz="UTC").value,
            0,
            255,
            255,
            0,
        )
        + b"\0" * 16
        + b"MNQ.v.0\0"
    )
    raw = b"DBN\x01" + struct.pack("<I", len(metadata)) + metadata + b"".join(records)
    path.write_bytes(zstd.ZstdCompressor().compress(raw))


class TbboExecutionTests(unittest.TestCase):
    def test_normalize_tbbo_frame_adds_execution_quality_columns(self) -> None:
        out = normalize_tbbo_frame(_tbbo_rows())

        self.assertIn("mid_price", out.columns)
        self.assertIn("spread_ticks", out.columns)
        self.assertIn("top_book_imbalance", out.columns)
        self.assertIn("trade_price_vs_mid", out.columns)
        self.assertIn("trade_size_to_opposite_best_size", out.columns)
        self.assertEqual(float(out.loc[0, "spread_ticks"]), 2.0)
        self.assertEqual(float(out.loc[0, "top_book_imbalance"]), 1.0 / 3.0)
        self.assertEqual(float(out.loc[0, "opposite_best_size"]), 2.0)
        self.assertEqual(float(out.loc[0, "same_side_best_size"]), 4.0)
        self.assertAlmostEqual(float(out.loc[0, "trade_size_to_opposite_best_size"]), 1.0)
        self.assertTrue(bool(out.loc[0, "top_book_depth_exhausted"]))
        self.assertFalse(bool(out.loc[0, "zero_impact_depth_supported"]))
        self.assertFalse(bool(out.loc[1, "top_book_depth_exhausted"]))
        self.assertTrue(bool(out.loc[1, "zero_impact_depth_supported"]))
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
        self.assertAlmostEqual(float(row["raw_b_side_trade_size"]), 2.0)
        self.assertAlmostEqual(float(row["raw_a_side_trade_size"]), 1.0)
        self.assertAlmostEqual(float(row["raw_b_minus_a_trade_size"]), 1.0)
        self.assertAlmostEqual(float(row["median_spread_points"]), 0.625)
        self.assertEqual(int(row["top_book_depth_exhausted_trade_count"]), 1)
        self.assertEqual(int(row["zero_impact_depth_supported_trade_count"]), 1)
        self.assertAlmostEqual(float(row["top_book_depth_exhausted_trade_pct"]), 0.5)
        self.assertAlmostEqual(float(row["top_book_depth_exhausted_size_share"]), 2.0 / 3.0)
        self.assertAlmostEqual(float(row["median_trade_size_to_opposite_best_size"]), (1.0 + (1.0 / 3.0)) / 2.0)

    def test_build_tbbo_execution_stats_from_zip_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "tbbo.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("glbx-mdp3-20260216.tbbo.csv", _tbbo_rows().to_csv(index=False))

            stats = build_tbbo_execution_stats_from_source(archive, max_files=1, progress_every=0)

            self.assertEqual(len(stats.minute_stats), 1)
            self.assertEqual(len(stats.daily_stats), 1)
            self.assertEqual(stats.daily_stats.iloc[0]["symbol"], "NQH6")

    def test_build_tbbo_execution_stats_from_dbn_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "tbbo.dbn"
            first = pd.Timestamp("2024-12-18T14:30:00Z").value
            second = pd.Timestamp("2024-12-18T14:30:20Z").value
            _write_synthetic_dbn(
                source,
                [
                    _dbn_record(
                        ts_event=first,
                        ts_recv=first + 1_000,
                        price=21970.25,
                        size=2,
                        side=b"B",
                        bid_px=21970.0,
                        ask_px=21970.25,
                        bid_sz=4,
                        ask_sz=2,
                    ),
                    _dbn_record(
                        ts_event=second,
                        ts_recv=second + 1_000,
                        price=21970.0,
                        size=1,
                        side=b"A",
                        bid_px=21969.75,
                        ask_px=21970.25,
                        bid_sz=3,
                        ask_sz=3,
                        sequence=2,
                    ),
                ],
            )

            stats = build_tbbo_execution_stats_from_dbn(
                source,
                chunk_records=1,
                progress_every=0,
                symbol_regex=r"^MNQ",
            )

            self.assertEqual(infer_dbn_symbol(source), "MNQ.v.0")
            self.assertEqual(len(stats.minute_stats), 1)
            row = stats.minute_stats.iloc[0]
            self.assertEqual(row["symbol"], "MNQ.v.0")
            self.assertEqual(int(row["trade_count"]), 2)
            self.assertAlmostEqual(float(row["median_spread_points"]), 0.375)
            self.assertAlmostEqual(float(row["raw_b_minus_a_trade_size"]), 1.0)
            self.assertEqual(len(stats.daily_stats), 1)


if __name__ == "__main__":
    unittest.main()
