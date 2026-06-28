from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

import pandas as pd

from backtest.l2_mbp import (
    L2ParquetSourceRef,
    decode_l2_mbp_parquet,
    parse_l2_mbp_markettick_parquet_frame,
    parse_l2_mbp_structured_frame,
    parse_l2_mbp_records,
    select_l2_parquet_sources,
    summarize_l2_mbp_events,
)


try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = None
    pq = None


class L2MbpTests(unittest.TestCase):
    def test_parse_l2_mbp_records_labels_depth_rows_without_overlabeling_trades(self) -> None:
        rows = [
            "20201201050000200729;2;1;12374.75;11;1;0",
            "20201201050000204259;2;0;12373.5;5;1;0",
            "20201201050000461825;1;0;12373.75;1",
            "20201201050000471825;1;2;12373.75;1",
            "20201201050001195670;1;3;0;27552",
        ]

        out = parse_l2_mbp_records(rows, source_label="sample")

        self.assertEqual(list(out["event_family"]), ["depth_update", "depth_update", "l1_quote", "trade_or_market_event", "l1_stat"])
        self.assertEqual(list(out.loc[:1, "book_side"]), ["ask", "bid"])
        self.assertEqual(set(out["source_schema"]), {"semicolon_1col"})
        self.assertEqual(list(out.loc[:1, "action_code_source"]), ["raw", "raw"])
        self.assertTrue(pd.Timestamp(out.loc[0, "event_time_utc"]).tzinfo is not None)
        self.assertEqual(str(out.loc[0, "event_time_ny"]), "2020-12-01 00:00:00.200729")
        self.assertTrue(pd.isna(out.loc[2, "level"]))
        self.assertTrue(pd.isna(out.loc[2, "action_code"]))
        self.assertEqual(out.loc[2, "l1_side"], "bid")
        self.assertEqual(int(out.loc[3, "type_code"]), 2)

    def test_parse_l2_mbp_structured_frame_infers_price_key_depth_actions(self) -> None:
        frame = pd.DataFrame(
            {
                "raw_timestamp": ["20220103050000000001", "20220103050000000002", "20220103050000100000"],
                "msg_type": [2, 1, 1],
                "book_level": [1, 0, 2],
                "price": [100.25, 100.00, 100.25],
                "size": [0, 4, 2],
            }
        )

        out = parse_l2_mbp_structured_frame(frame, source_label="structured")

        self.assertEqual(list(out["event_family"]), ["depth_update", "l1_quote", "trade_or_market_event"])
        self.assertEqual(out.loc[0, "book_side"], "ask")
        self.assertEqual(out.loc[1, "l1_side"], "bid")
        self.assertEqual(set(out["source_schema"]), {"structured_5col"})
        self.assertEqual(str(out.loc[0, "action_code_source"]), "synthetic_size_rule")
        self.assertEqual(int(out.loc[0, "action_code"]), 2)
        self.assertTrue(pd.isna(out.loc[0, "level"]))

    def test_parse_l2_mbp_markettick_parquet_frame_uses_corrected_side_semantics(self) -> None:
        frame = pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    [
                        "2020-12-01 05:00:00.000200",
                        "2020-12-01 05:00:00.000204",
                        "2020-12-01 05:00:00.000332",
                        "2020-12-01 05:00:00.000400",
                    ]
                ),
                "side": [2, 2, 1, 1],
                "level": [1, 0, 1, 2],
                "price": [12374.75, 12373.50, 12374.25, 12373.75],
                "size": [11, 5, 1, 2],
                "order_count": [1.0, 1.0, pd.NA, pd.NA],
                "implied_flag": [0.0, 1.0, pd.NA, pd.NA],
            }
        )

        out = parse_l2_mbp_markettick_parquet_frame(frame, source_label="markettick")

        self.assertEqual(list(out["event_family"]), ["depth_update", "depth_update", "l1_quote", "trade_or_market_event"])
        self.assertEqual(list(out.loc[:1, "book_side"]), ["ask", "bid"])
        self.assertEqual(set(out["source_schema"]), {"markettick_7col"})
        self.assertEqual(list(out.loc[:1, "action_code_source"]), ["raw", "raw"])
        self.assertEqual(int(out.loc[0, "level"]), 1)
        self.assertEqual(int(out.loc[1, "action_code"]), 1)
        self.assertEqual(out.loc[2, "l1_side"], "ask")
        self.assertTrue(pd.Timestamp(out.loc[0, "event_time_utc"]).tzinfo is not None)
        self.assertEqual(str(out.loc[0, "event_time_ny"]), "2020-12-01 00:00:00.000200")

    def test_summarize_l2_mbp_events_counts_shapes(self) -> None:
        out = parse_l2_mbp_records(
            [
                "20201201050000200729;2;1;12374.75;11;1;0",
                "20201201050000204259;2;0;12373.5;5;1;0",
                "20201201050000461825;1;0;12373.75;1",
                "20201201050000471825;1;2;12373.75;1",
            ],
            source_label="sample",
        )

        summary = summarize_l2_mbp_events(out)

        self.assertEqual(int(summary.loc[0, "decoded_rows"]), 4)
        self.assertEqual(int(summary.loc[0, "depth_rows"]), 2)
        self.assertEqual(int(summary.loc[0, "l1_quote_rows"]), 1)
        self.assertEqual(int(summary.loc[0, "trade_or_market_rows"]), 1)
        self.assertIn("1:2", summary.loc[0, "event_type_codes"])
        self.assertIn("2:2", summary.loc[0, "event_type_codes"])
        self.assertIn("trade_or_market_event:1", summary.loc[0, "event_families"])

    @unittest.skipIf(pa is None or pq is None, "pyarrow is required")
    def test_decode_l2_mbp_parquet_includes_column_name_as_first_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.parquet"
            first_record = "20201201050000200729;2;1;12374.75;11;1;0"
            table = pa.table({first_record: ["20201201050000204259;2;0;12373.5;5;1;0"]})
            pq.write_table(table, path)

            out = decode_l2_mbp_parquet(L2ParquetSourceRef(source_path=path, label="sample"), max_rows=2)

            self.assertEqual(len(out), 2)
            self.assertEqual(out.loc[0, "raw_record"], first_record)
            self.assertEqual(out.loc[1, "book_side"], "bid")

    def test_decode_l2_csv_accepts_zero_max_rows_as_unbounded_selected_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.csv"
            path.write_text(
                "\n".join(
                    [
                        "20201201050000200729;2;1;12374.75;11;1;0",
                        "20201201050000204259;2;0;12373.5;5;1;0",
                        "20201201050000471825;1;2;12373.75;1",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            out = decode_l2_mbp_parquet(L2ParquetSourceRef(source_path=path, label="sample"), max_rows=0)

            self.assertEqual(len(out), 3)
            self.assertEqual(int(out["event_family"].eq("depth_update").sum()), 2)
            self.assertEqual(int(out["event_family"].eq("trade_or_market_event").sum()), 1)

    @unittest.skipIf(pa is None or pq is None, "pyarrow is required")
    def test_decode_l2_mbp_parquet_handles_structured_five_column_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "structured.parquet"
            table = pa.table(
                {
                    "raw_timestamp": ["20220103050000000001", "20220103050000000002"],
                    "msg_type": [2, 1],
                    "book_level": [1, 2],
                    "price": [100.25, 100.25],
                    "size": [4, 2],
                }
            )
            pq.write_table(table, path)

            out = decode_l2_mbp_parquet(L2ParquetSourceRef(source_path=path, label="structured"), max_rows=2)

            self.assertEqual(len(out), 2)
            self.assertEqual(set(out["source_schema"]), {"structured_5col"})
            self.assertEqual(out.loc[0, "event_family"], "depth_update")
            self.assertEqual(out.loc[1, "event_family"], "trade_or_market_event")
            self.assertEqual(int(out.loc[0, "parquet_num_rows"]), 2)

    @unittest.skipIf(pa is None or pq is None, "pyarrow is required")
    def test_decode_l2_mbp_parquet_handles_markettick_seven_column_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "markettick.parquet"
            table = pa.table(
                {
                    "timestamp": [
                        pd.Timestamp("2020-12-01 05:00:00.000200"),
                        pd.Timestamp("2020-12-01 05:00:00.000204"),
                    ],
                    "side": [2, 1],
                    "level": [1, 2],
                    "price": [12374.75, 12373.75],
                    "size": [11, 2],
                    "order_count": [1.0, None],
                    "implied_flag": [0.0, None],
                }
            )
            pq.write_table(table, path)

            out = decode_l2_mbp_parquet(L2ParquetSourceRef(source_path=path, label="markettick"), max_rows=2)

            self.assertEqual(len(out), 2)
            self.assertEqual(set(out["source_schema"]), {"markettick_7col"})
            self.assertEqual(out.loc[0, "event_family"], "depth_update")
            self.assertEqual(out.loc[1, "event_family"], "trade_or_market_event")
            self.assertEqual(out.loc[0, "book_side"], "ask")
            self.assertEqual(int(out.loc[0, "parquet_num_rows"]), 2)

    @unittest.skipIf(pa is None or pq is None, "pyarrow is required")
    def test_decode_l2_mbp_parquet_can_start_at_later_row_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "structured.parquet"
            table = pa.table(
                {
                    "raw_timestamp": [
                        "20220103050000000001",
                        "20220103050000000002",
                        "20220103050000000003",
                    ],
                    "msg_type": [2, 2, 1],
                    "book_level": [1, 0, 1],
                    "price": [100.25, 100.00, 100.25],
                    "size": [4, 5, 1],
                }
            )
            pq.write_table(table, path, row_group_size=1)

            out = decode_l2_mbp_parquet(
                L2ParquetSourceRef(source_path=path, label="structured"),
                max_rows=1,
                start_row_group=1,
            )

            self.assertEqual(len(out), 1)
            self.assertEqual(out.loc[0, "ts_raw"], "20220103050000000002")
            self.assertEqual(int(out.loc[0, "sample_start_row_group"]), 1)

    @unittest.skipIf(pa is None or pq is None, "pyarrow is required")
    def test_select_l2_parquet_sources_can_target_zip_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parquet_path = Path(tmp) / "sample.parquet"
            archive = Path(tmp) / "sample.zip"
            table = pa.table({"20201201050000200729;2;1;12374.75;11;1;0": []})
            pq.write_table(table, parquet_path)
            with zipfile.ZipFile(archive, "w") as zf:
                zf.write(parquet_path, "202012/sample.parquet")

            refs = select_l2_parquet_sources(archive, members=["202012/sample.parquet"])

            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0].zip_member, "202012/sample.parquet")


if __name__ == "__main__":
    unittest.main()
