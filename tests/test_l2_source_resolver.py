from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from backtest.l2_dataset_qa import build_l2_dataset_qa, write_l2_dataset_qa_artifacts
from backtest.l2_source_resolver import decode_l2_source_selection, resolve_l2_source_index


class L2SourceResolverTests(unittest.TestCase):
    def test_resolve_source_index_and_decode_zip_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = _write_source_index(
                root,
                {
                    "202401/20240102.csv": (
                        "20240102050000010000;2;0;100.00;5;1;0\n"
                        "20240102050000020000;2;1;100.25;4;1;0\n"
                        "20240102050000030000;1;0;100.00;1\n"
                    )
                },
                start_date="20240102",
                end_date="20240102",
            )

            selection = resolve_l2_source_index(index_path, trade_dates=["20240102"])
            decoded = decode_l2_source_selection(selection, max_rows_per_source=2)

            self.assertEqual(len(selection.resolved_sources), 1)
            self.assertEqual(selection.resolved_sources[0].trade_date, "20240102")
            self.assertEqual(selection.resolved_sources[0].zip_member, "202401/20240102.csv")
            self.assertEqual(len(decoded.events), 2)
            self.assertEqual(list(decoded.events["book_side"]), ["bid", "ask"])
            self.assertIn("20240102", decoded.events.loc[0, "source_label"])

    def test_missing_requested_date_fails_unless_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = _write_source_index(
                root,
                {"202401/20240102.csv": "20240102050000010000;1;0;100.00;1\n"},
                start_date="20240102",
                end_date="20240103",
            )

            with self.assertRaisesRegex(ValueError, "no source for requested date"):
                resolve_l2_source_index(index_path, trade_dates=["20240103"])

            selection = resolve_l2_source_index(index_path, trade_dates=["20240103"], allow_missing_dates=True)

            self.assertEqual(selection.missing_dates, ("20240103",))
            self.assertEqual(selection.resolved_sources, ())

    def test_duplicate_dates_fail_unless_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archives = root / "csv_archives" / "2025_1st_semester_Jan-Jun"
            archives.mkdir(parents=True)
            with zipfile.ZipFile(archives / "a.zip", "w") as zf:
                zf.writestr("202501/20250102.csv", "20250102050000010000;1;0;100.00;1\n")
            with zipfile.ZipFile(archives / "b.zip", "w") as zf:
                zf.writestr("202501/20250102.csv", "20250102050000020000;1;1;100.25;1\n")
            qa = build_l2_dataset_qa(archives.parent, start_date="20250102", end_date="20250102")
            index_path = write_l2_dataset_qa_artifacts(qa, root / "manifests")["source_index_csv"]

            with self.assertRaisesRegex(ValueError, "duplicate source rows"):
                resolve_l2_source_index(index_path, trade_dates=["20250102"])

            selection = resolve_l2_source_index(index_path, trade_dates=["20250102"], allow_duplicate_dates=True)

            self.assertEqual(len(selection.resolved_sources), 2)

    def test_range_selection_can_be_capped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path = _write_source_index(
                root,
                {
                    "202401/20240102.csv": "20240102050000010000;1;0;100.00;1\n",
                    "202401/20240103.csv": "20240103050000010000;1;0;100.00;1\n",
                },
                start_date="20240102",
                end_date="20240103",
            )

            selection = resolve_l2_source_index(index_path, start_date="20240102", end_date="20240103", max_dates=1)

            self.assertEqual(selection.requested_dates, ("20240102",))
            self.assertEqual(selection.resolved_dates, ("20240102",))


def _write_source_index(root: Path, members: dict[str, str], *, start_date: str, end_date: str) -> Path:
    archives = root / "csv_archives" / "2024_1st_semester_Jan-Jun"
    archives.mkdir(parents=True)
    with zipfile.ZipFile(archives / "sample.zip", "w") as zf:
        for member, text in members.items():
            zf.writestr(member, text)
    qa = build_l2_dataset_qa(archives.parent, start_date=start_date, end_date=end_date)
    return write_l2_dataset_qa_artifacts(qa, root / "manifests")["source_index_csv"]


if __name__ == "__main__":
    unittest.main()
