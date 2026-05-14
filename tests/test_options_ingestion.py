from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

import pandas as pd

from backtest.options_ingestion import build_schema_sample, schema_members


class OptionsIngestionTests(unittest.TestCase):
    def test_schema_members_detects_zstd_csv_members_inside_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "statistics.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("metadata.json", "{}")
                zf.writestr("glbx-mdp3-20240102.statistics.csv.zst", b"not actually compressed")
                zf.writestr("glbx-mdp3-20240102.definition.csv.zst", b"not actually compressed")

            self.assertEqual(
                schema_members(archive, "statistics"),
                ["glbx-mdp3-20240102.statistics.csv.zst"],
            )

    def test_build_schema_sample_still_reads_plain_csv_zip_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "statistics.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr(
                    "glbx-mdp3-20240102.statistics.csv",
                    "ts_event,instrument_id,stat_type,price\n2024-01-02T00:00:00Z,1,42,7.5\n",
                )

            sample = build_schema_sample(archive, "statistics")

            self.assertEqual(len(sample), 1)
            self.assertEqual(sample.loc[0, "instrument_id"], 1)
            self.assertIsInstance(sample.loc[0, "ts_event"], pd.Timestamp)
            self.assertEqual(sample.loc[0, "stat_type"], 42)


if __name__ == "__main__":
    unittest.main()
