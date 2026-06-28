from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.motivewave_context import (
    MotiveWaveContextConfig,
    build_motivewave_context,
    write_motivewave_context_artifacts,
)


class MotiveWaveContextTests(unittest.TestCase):
    def test_normalizes_orderflow_export_into_directional_triggers(self) -> None:
        export = pd.DataFrame(
            {
                "Date Time": ["2021-01-04 09:29:00", "2021-01-04 09:30:00"],
                "Buy-side Absorption": [0, 1],
                "Sell-side Absorption": [1, 0],
                "Sell-side Aggression": [0, 1],
                "Extreme Delta Signal": ["", "Extreme Negative Delta"],
                "Window Delta": [12, -30],
                "Tape Dominance": ["Ask Dominant 2", "Bid Dominant 3"],
            }
        )

        artifacts = build_motivewave_context(
            export,
            config=MotiveWaveContextConfig(time_col="Date Time", timezone="America/New_York"),
        )

        frame = artifacts.frame
        self.assertEqual(len(frame), 2)
        self.assertTrue(bool(frame.loc[0, "mw_absorption_long_trigger"]))
        self.assertTrue(bool(frame.loc[0, "mw_orderflow_long_trigger"]))
        self.assertFalse(bool(frame.loc[0, "mw_any_short_trigger"]))
        self.assertTrue(bool(frame.loc[1, "mw_absorption_short_trigger"]))
        self.assertTrue(bool(frame.loc[1, "mw_initiative_short_trigger"]))
        self.assertTrue(bool(frame.loc[1, "mw_orderflow_short_trigger"]))
        self.assertEqual(int(frame.loc[0, "mw_tape_ask_dominance_tier"]), 2)
        self.assertEqual(int(frame.loc[1, "mw_tape_bid_dominance_tier"]), 3)
        self.assertAlmostEqual(float(frame.loc[1, "mw_window_delta"]), -30.0)
        self.assertIn("Sell-side Absorption", artifacts.column_map["mw_sell_absorption"])

    def test_rejects_result_like_columns_by_default(self) -> None:
        export = pd.DataFrame(
            {
                "time": ["2021-01-04 09:30:00"],
                "Buy-side Absorption": [1],
                "realized_pnl": [125.0],
            }
        )

        with self.assertRaises(ValueError):
            build_motivewave_context(export)

    def test_writes_context_artifacts(self) -> None:
        export = pd.DataFrame(
            {
                "time": ["2021-01-04 09:30:00"],
                "Sell-side Initiation": [1],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = build_motivewave_context(export)
            paths = write_motivewave_context_artifacts(artifacts, Path(tmp))

            self.assertTrue(paths["csv"].exists())
            self.assertTrue(paths["report_md"].exists())
            self.assertIn("MotiveWave Context", paths["report_md"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
