from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from backtest.l2_warm_state_matrix import (
    L2WarmStateWindowSpec,
    build_l2_warm_state_execution_matrix,
    parse_window_spec,
    write_l2_warm_state_execution_matrix,
)


try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = None
    pq = None


class L2WarmStateMatrixTests(unittest.TestCase):
    def test_parse_window_spec_accepts_equals_and_dash(self) -> None:
        spec = parse_window_spec("rth_open=09:30:00-09:31:00")

        self.assertEqual(spec.name, "rth_open")
        self.assertEqual(spec.start_time, "09:30:00")
        self.assertEqual(spec.end_time, "09:31:00")

    def test_build_matrix_dry_run_records_window_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "batch.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("202201/20220103.parquet", b"not-used")

            result = build_l2_warm_state_execution_matrix(
                root,
                target_dates=("20220103", "20230104"),
                windows=(L2WarmStateWindowSpec("open", "09:30:00", "09:31:00"),),
                dry_run=True,
                out_dir=root / "out",
            )

            self.assertEqual(list(result.targets["date"]), ["20220103", "20230104"])
            self.assertEqual(list(result.targets["status"]), ["found", "missing"])
            self.assertTrue(result.warm_state_summary.empty)
            self.assertIn("Warm-State Execution Matrix", result.report_md)

    @unittest.skipIf(pa is None or pq is None, "pyarrow is required")
    def test_build_matrix_processes_structured_cell_and_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parquet = root / "20220103.parquet"
            archive = root / "batch.zip"
            table = pa.table(
                {
                    "raw_timestamp": [
                        "20220103142950000000",
                        "20220103142951000000",
                        "20220103143000000000",
                        "20220103143001000000",
                    ],
                    "msg_type": [2, 2, 1, 1],
                    "book_level": [1, 0, 2, 2],
                    "price": [100.25, 100.00, 100.25, 100.00],
                    "size": [4, 5, 1, 1],
                }
            )
            pq.write_table(table, parquet, row_group_size=2)
            with zipfile.ZipFile(archive, "w") as zf:
                zf.write(parquet, "202201/20220103.parquet")

            result = build_l2_warm_state_execution_matrix(
                root,
                target_dates=("20220103",),
                windows=(L2WarmStateWindowSpec("open", "09:30:00", "09:31:00"),),
                out_dir=root / "out",
                write_baselines=False,
            )
            paths = write_l2_warm_state_execution_matrix(result, root / "out")

            self.assertEqual(result.targets.loc[0, "status"], "processed")
            self.assertFalse(result.warm_state_summary.empty)
            self.assertTrue(bool(result.warm_state_summary.loc[0, "warm_start_valid_top_book"]))
            self.assertEqual(int(result.warm_state_summary.loc[0, "trade_rows"]), 2)
            self.assertTrue(paths["report_md"].exists())
            self.assertIn("Warm-State Coverage", result.report_md)


if __name__ == "__main__":
    unittest.main()
