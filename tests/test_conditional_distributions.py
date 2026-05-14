from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from results.analysis import export_conditional_distribution_report, summarize_conditional_distributions


def _sample_trades() -> pd.DataFrame:
    rows = []
    for month in range(1, 5):
        base_time = pd.Timestamp(2024, month, 3, 10, 0)
        for idx, pnl in enumerate([30.0, 24.0, 18.0, -8.0]):
            rows.append(
                {
                    "entry_time": base_time + pd.Timedelta(minutes=idx * 10),
                    "exit_time": base_time + pd.Timedelta(minutes=idx * 10 + 5),
                    "direction": "long",
                    "signal_type": "mr",
                    "setup_tag": "mr_long",
                    "entry_markov_state_label": "low_vol",
                    "pnl": pnl,
                    "reason": "target" if pnl > 0 else "stop",
                }
            )
        for idx, pnl in enumerate([-18.0, -12.0, -10.0, 6.0]):
            rows.append(
                {
                    "entry_time": base_time + pd.Timedelta(minutes=60 + idx * 10),
                    "exit_time": base_time + pd.Timedelta(minutes=65 + idx * 10),
                    "direction": "short",
                    "signal_type": "trend",
                    "setup_tag": "trend_short",
                    "entry_markov_state_label": "high_vol",
                    "pnl": pnl,
                    "reason": "target" if pnl > 0 else "stop",
                }
            )
    return pd.DataFrame(rows)


class ConditionalDistributionTests(unittest.TestCase):
    def test_summary_separates_conditional_edges(self) -> None:
        summary, period_rows = summarize_conditional_distributions(
            _sample_trades(),
            conditioning_sets=[["setup_tag"], ["setup_tag", "entry_markov_state_label"]],
            min_trades=8,
            min_periods=3,
            period="M",
            n_bootstrap=100,
            random_seed=11,
        )

        self.assertFalse(summary.empty)
        self.assertFalse(period_rows.empty)

        by_key = summary.set_index(["conditioning_set", "conditioning_key"])
        positive = by_key.loc[("setup_tag", "mr_long")]
        negative = by_key.loc[("setup_tag", "trend_short")]

        self.assertEqual(positive["edge_flag"], "possible_positive_conditional_edge")
        self.assertEqual(negative["edge_flag"], "possible_negative_condition")
        self.assertGreater(float(positive["bootstrap_prob_expectancy_gt_0"]), 0.90)
        self.assertLess(float(negative["bootstrap_prob_expectancy_gt_0"]), 0.10)

    def test_export_writes_report_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            paths = export_conditional_distribution_report(
                _sample_trades(),
                out_dir,
                artifact_name="conditional",
                conditioning_sets=[["setup_tag"]],
                min_trades=8,
                min_periods=3,
                period="M",
                n_bootstrap=50,
            )

            self.assertTrue(paths.summary_csv.exists())
            self.assertTrue(paths.period_stability_csv.exists())
            self.assertTrue(paths.warnings_csv.exists())
            self.assertTrue(paths.report_md.exists())
            self.assertIn("Conditional Distribution Report", paths.report_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
