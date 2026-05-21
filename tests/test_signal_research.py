from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from backtest.signal_research import infer_signal_columns, run_signal_research_report


class SignalResearchReportTests(unittest.TestCase):
    def test_report_marks_predictive_signal_eligible(self) -> None:
        rng = np.random.default_rng(7)
        returns = rng.normal(0.0, 1.0, 160)
        close = 100.0 + np.cumsum(returns)
        data = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-01", periods=len(close), freq="D"),
                "close": close,
                "future_leak_signal_for_test": pd.Series(close).shift(-1) - pd.Series(close),
                "session_bucket": np.where(np.arange(len(close)) % 2 == 0, "open", "midday"),
            }
        ).dropna().reset_index(drop=True)

        with tempfile.TemporaryDirectory() as tmp:
            paths = run_signal_research_report(
                data,
                out_dir=Path(tmp),
                signal_cols=["future_leak_signal_for_test"],
                context_cols=["session_bucket"],
                horizons_bars=[1],
                min_obs=50,
                min_active_obs=30,
                min_abs_ic=0.02,
                min_positive_period_pct=50.0,
            )

            summary = pd.read_csv(paths.summary_csv)
            self.assertTrue(bool(summary.loc[0, "eligible_for_candidate"]))
            self.assertGreater(float(summary.loc[0, "ic"]), 0.90)
            self.assertTrue(bool(summary.loc[0, "ic_suspicious_gt_0_10"]))
            self.assertTrue(paths.period_stability_csv.exists())
            context = pd.read_csv(paths.context_summary_csv)
            self.assertEqual(set(context["context"].unique()), {"session_bucket"})
            report = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("Leakage Warning", report)

    def test_flat_signal_does_not_pass_gate(self) -> None:
        close = np.linspace(100.0, 120.0, 80)
        data = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-01", periods=len(close), freq="D"),
                "close": close,
                "flat_signal": 0.0,
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = run_signal_research_report(
                data,
                out_dir=Path(tmp),
                signal_cols=["flat_signal"],
                horizons_bars=[1],
                min_obs=20,
                min_active_obs=10,
            )

            summary = pd.read_csv(paths.summary_csv)
            self.assertFalse(bool(summary.loc[0, "eligible_for_candidate"]))
            self.assertEqual(int(summary.loc[0, "n_active"]), 0)
            report = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("No signal passed the pre-candidate gate", report)

    def test_infer_signal_columns_excludes_price_and_context(self) -> None:
        data = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-01", periods=3),
                "close": [1.0, 2.0, 3.0],
                "volume": [10, 20, 30],
                "session_bucket": ["a", "b", "c"],
                "candidate_signal": [0.1, -0.2, 0.3],
            }
        )

        self.assertEqual(
            infer_signal_columns(data, context_cols=["session_bucket"]),
            ["candidate_signal"],
        )


if __name__ == "__main__":
    unittest.main()
