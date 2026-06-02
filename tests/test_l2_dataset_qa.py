from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from backtest.l2_dataset_qa import (
    build_l2_dataset_qa,
    classify_missing_day,
    parse_yyyymmdd,
    write_l2_dataset_qa_artifacts,
)


class L2DatasetQaTests(unittest.TestCase):
    def test_build_source_index_and_missing_day_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "csv_archives"
            folder = root / "2024_1st_semester_Jan-Jun"
            folder.mkdir(parents=True)
            with zipfile.ZipFile(folder / "sample.zip", "w") as zf:
                zf.writestr("202401/20240102.csv", "20240102050000010000;1;0;100;1\n")
                zf.writestr("202401/20240104.csv", "20240104050000010000;1;1;101;1\n")

            qa = build_l2_dataset_qa(root, start_date="20240102", end_date="20240104")

            self.assertEqual(len(qa.source_index), 2)
            self.assertEqual(qa.source_index[0].trade_date, "20240102")
            self.assertEqual(qa.source_index[0].archive_folder, "2024_1st_semester_Jan-Jun")
            self.assertEqual(qa.source_index[0].duplicate_status, "unique")
            self.assertEqual(len(qa.missing_days), 1)
            self.assertEqual(qa.missing_days[0].trade_date, "20240103")
            self.assertEqual(qa.missing_days[0].missing_class, "source_gap_review")
            self.assertEqual(qa.month_coverage[0].present_unique_days, 2)
            self.assertEqual(qa.month_coverage[0].source_gap_review_days, 1)

    def test_duplicate_dates_are_marked_on_each_source_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "csv_archives"
            folder = root / "2025_1st_semester_Jan-Jun"
            folder.mkdir(parents=True)
            with zipfile.ZipFile(folder / "a.zip", "w") as zf:
                zf.writestr("202501/20250102.csv", "one\n")
            with zipfile.ZipFile(folder / "b.zip", "w") as zf:
                zf.writestr("202501/20250102.csv", "two\n")

            qa = build_l2_dataset_qa(root, start_date="20250102", end_date="20250102")

            self.assertEqual(len(qa.source_index), 2)
            self.assertEqual({row.duplicate_status for row in qa.source_index}, {"duplicate"})
            self.assertEqual({row.duplicate_count_for_date for row in qa.source_index}, {2})
            self.assertEqual(qa.month_coverage[0].duplicate_dates, 1)

    def test_missing_day_classification_separates_expected_and_review_dates(self) -> None:
        weekend = classify_missing_day(parse_yyyymmdd("20250104"))
        holiday = classify_missing_day(parse_yyyymmdd("20240115"))
        source_gap = classify_missing_day(parse_yyyymmdd("20240719"))

        self.assertEqual(weekend.missing_class, "weekend")
        self.assertTrue(weekend.expected_absence)
        self.assertEqual(holiday.missing_class, "expected_market_closure")
        self.assertTrue(holiday.expected_absence)
        self.assertEqual(source_gap.missing_class, "source_gap_review")
        self.assertFalse(source_gap.expected_absence)

    def test_write_artifacts_creates_csvs_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "csv_archives"
            folder = root / "2025_2nd_semester_Jul-Nov"
            folder.mkdir(parents=True)
            with zipfile.ZipFile(folder / "sample.zip", "w") as zf:
                zf.writestr("202507/20250701.csv", "20250701040000200073;2;1;22880.25;1;1;0\n")
            qa = build_l2_dataset_qa(root, start_date="20250701", end_date="20250702")

            paths = write_l2_dataset_qa_artifacts(qa, Path(tmp) / "out")

            self.assertTrue(paths["source_index_csv"].exists())
            self.assertTrue(paths["missing_days_csv"].exists())
            self.assertTrue(paths["month_coverage_csv"].exists())
            self.assertTrue(paths["archive_errors_csv"].exists())
            report = paths["report_md"].read_text(encoding="utf-8")
            self.assertIn("L2 Dataset QA Report", report)
            self.assertIn("Source gaps requiring review", report)


if __name__ == "__main__":
    unittest.main()
