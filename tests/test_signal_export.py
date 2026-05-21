from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.signal_export import prepare_signal_export_frame, write_prepared_signal_export


class PreparedSignalExportTests(unittest.TestCase):
    def test_prepare_signal_export_frame_adds_signed_signal_and_context(self) -> None:
        signal_frame = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 09:30", periods=3, freq="5min"),
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "volume": [1000, 1100, 1200],
                "signal": [1, -1, 0],
                "signal_type": ["trend", "mr", ""],
                "vwap_side": ["above_vwap", "below_vwap", "above_vwap"],
                "vwap_z": [0.4, -1.2, 0.1],
            }
        )

        export = prepare_signal_export_frame(
            signal_frame,
            feature_cols=["vwap_z"],
            context_cols=["vwap_side", "missing_context"],
        )

        self.assertEqual(export["candidate_signal"].tolist(), [1.0, -1.0, 0.0])
        self.assertEqual(export["direction"].tolist(), ["long", "short", "flat"])
        self.assertEqual(export["setup_tag"].tolist(), ["trend_long", "mr_short", ""])
        self.assertEqual(export["session_bucket"].tolist(), ["rth_open", "rth_open", "rth_open"])
        self.assertIn("vwap_side", export.columns)
        self.assertIn("vwap_z", export.columns)
        self.assertNotIn("missing_context", export.columns)

    def test_prepare_signal_export_frame_rejects_missing_feature(self) -> None:
        signal_frame = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03", periods=1),
                "close": [100.0],
                "signal": [1],
            }
        )

        with self.assertRaises(ValueError):
            prepare_signal_export_frame(signal_frame, feature_cols=["not_present"])

    def test_write_prepared_signal_export_outputs_csv_and_manifest(self) -> None:
        frame = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03", periods=2),
                "close": [100.0, 101.0],
                "candidate_signal": [1.0, 0.0],
                "signal_active": [True, False],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = write_prepared_signal_export(
                frame,
                out_dir=Path(tmp),
                artifact_name="Example Signal Export",
                metadata={"candidate": "example_candidate"},
            )

            self.assertTrue(paths.signals_csv.exists())
            self.assertTrue(paths.manifest_md.exists())
            saved = pd.read_csv(paths.signals_csv)
            self.assertEqual(len(saved), 2)
            manifest = paths.manifest_md.read_text(encoding="utf-8")
            self.assertIn("Prepared Signal Export", manifest)
            self.assertIn("example_candidate", manifest)


if __name__ == "__main__":
    unittest.main()
