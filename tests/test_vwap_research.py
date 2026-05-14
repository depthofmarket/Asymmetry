from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.vwap_research import (
    build_vwap_repricing_events,
    export_vwap_repricing_report,
    summarize_vwap_repricing_by_side,
    summarize_vwap_repricing_by_time,
)


def _sample_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.to_datetime(
                [
                    "2024-01-02 09:30",
                    "2024-01-02 09:35",
                    "2024-01-02 09:40",
                    "2024-01-02 12:00",
                    "2024-01-02 16:00",
                    "2024-01-03 09:30",
                    "2024-01-03 09:35",
                    "2024-01-03 09:40",
                ]
            ),
            "close": [100.0, 102.0, 104.0, 103.0, 108.0, 100.0, 98.0, 96.0],
            "vwap": [100.0, 101.0, 102.0, 103.5, 104.0, 100.0, 99.0, 98.0],
            "volume": [10, 20, 30, 40, 50, 10, 20, 30],
        }
    )


class VwapResearchTests(unittest.TestCase):
    def test_repricing_uses_previous_completed_bar_side(self) -> None:
        events = build_vwap_repricing_events(_sample_bars())

        first = events.iloc[0]
        self.assertEqual(first["time"], pd.Timestamp("2024-01-02 09:40"))
        self.assertEqual(first["prior_vwap_side"], "above_vwap")
        self.assertEqual(float(first["bar_return_points"]), 2.0)
        self.assertEqual(float(first["directional_return_points"]), 2.0)

        below = events.loc[events["prior_vwap_side"].eq("below_vwap")].iloc[0]
        self.assertEqual(below["time"], pd.Timestamp("2024-01-03 09:40"))
        self.assertEqual(float(below["bar_return_points"]), -2.0)
        self.assertEqual(float(below["directional_return_points"]), 2.0)

        self.assertNotIn(pd.Timestamp("2024-01-02 16:00"), set(events["time"]))

    def test_summaries_and_export(self) -> None:
        events = build_vwap_repricing_events(_sample_bars())
        side = summarize_vwap_repricing_by_side(events)
        tod = summarize_vwap_repricing_by_time(events)

        self.assertFalse(side.empty)
        self.assertFalse(tod.empty)
        self.assertIn("directional_profit_factor", side.columns)
        self.assertIn("cumulative_directional_points", tod.columns)

        with tempfile.TemporaryDirectory() as tmp:
            paths = export_vwap_repricing_report(_sample_bars(), Path(tmp), artifact_name="vwap")
            self.assertTrue(paths.events_csv.exists())
            self.assertTrue(paths.side_summary_csv.exists())
            self.assertTrue(paths.time_of_day_csv.exists())
            self.assertTrue(paths.period_summary_csv.exists())
            self.assertTrue(paths.warnings_csv.exists())
            self.assertTrue(paths.report_md.exists())
            self.assertIn("VWAP Repricing Report", paths.report_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
