from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from backtest.l2_archive_inventory import (
    create_semester_folder_skeleton,
    inspect_l2_zip_archive,
    semester_folder_for_date,
)


class L2ArchiveInventoryTests(unittest.TestCase):
    def test_semester_folder_for_date(self) -> None:
        self.assertEqual(semester_folder_for_date("20210101"), "2021_1st_semester_Jan-Jun")
        self.assertEqual(semester_folder_for_date("20210630"), "2021_1st_semester_Jan-Jun")
        self.assertEqual(semester_folder_for_date("20210701"), "2021_2nd_semester_Jul-Dec")
        self.assertEqual(semester_folder_for_date("20211231"), "2021_2nd_semester_Jul-Dec")

    def test_inspect_zip_assigns_single_semester_from_member_dates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "drive-download.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("202101/20210101.parquet", b"one")
                zf.writestr("202105/20210531.parquet", b"two")

            out = inspect_l2_zip_archive(archive)

            self.assertEqual(out.status, "ok")
            self.assertEqual(out.parquet_file_count, 2)
            self.assertEqual(out.first_date, "20210101")
            self.assertEqual(out.last_date, "20210531")
            self.assertEqual(out.assigned_folder, "2021_1st_semester_Jan-Jun")

    def test_inspect_zip_flags_mixed_semester_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "mixed.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("202106/20210630.parquet", b"one")
                zf.writestr("202107/20210701.parquet", b"two")

            out = inspect_l2_zip_archive(archive)

            self.assertEqual(out.status, "ok")
            self.assertEqual(out.assigned_folder, "mixed_semesters_review")
            self.assertIn("2021_1st_semester_Jan-Jun", out.semesters)
            self.assertIn("2021_2nd_semester_Jul-Dec", out.semesters)

    def test_create_semester_folder_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folders = create_semester_folder_skeleton(Path(tmp), start_year=2021, end_year=2021)

            self.assertTrue((Path(tmp) / "2021_1st_semester_Jan-Jun").is_dir())
            self.assertTrue((Path(tmp) / "2021_2nd_semester_Jul-Dec").is_dir())
            self.assertTrue((Path(tmp) / "mixed_semesters_review").is_dir())
            self.assertEqual(len(folders), 4)


if __name__ == "__main__":
    unittest.main()
