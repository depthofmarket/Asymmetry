from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from backtest.l2_topbook_validation_matrix import (
    build_l2_topbook_validation_matrix,
    discover_l2_date_members,
)


class L2TopBookValidationMatrixTests(unittest.TestCase):
    def test_discover_l2_date_members_finds_dates_inside_nested_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "batch.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("202101/20210104.parquet", b"not-used")
                zf.writestr("202201/20220103.parquet", b"not-used")

            found = discover_l2_date_members(root, target_dates=("20210104", "20220103", "20230104"))

            self.assertEqual(found["20210104"].member, "202101/20210104.parquet")
            self.assertEqual(found["20220103"].source_path, str(archive))
            self.assertNotIn("20230104", found)

    def test_build_matrix_dry_run_records_found_and_missing_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "batch.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("202101/20210104.parquet", b"not-used")

            result = build_l2_topbook_validation_matrix(
                root,
                target_dates=("20210104", "20230104"),
                dry_run=True,
                out_dir=root / "out",
            )

            self.assertEqual(list(result.targets["date"]), ["20210104", "20230104"])
            self.assertEqual(list(result.targets["status"]), ["found", "missing"])
            self.assertTrue(result.quality_summary.empty)
            self.assertIn("Dry run", result.report_md)


if __name__ == "__main__":
    unittest.main()
