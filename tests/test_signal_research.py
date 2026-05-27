from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from backtest.signal_research import coerce_bool_series, infer_signal_columns, run_signal_research_report


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

    def test_next_bar_open_entry_uses_entry_lag(self) -> None:
        data = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-01 09:30", periods=5, freq="min"),
                "open": [100.0, 101.0, 120.0, 110.0, 108.0],
                "close": [100.0, 120.0, 110.0, 108.0, 107.0],
                "candidate_signal": [1.0, 0.0, 0.0, 0.0, 0.0],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = run_signal_research_report(
                data,
                out_dir=Path(tmp),
                signal_cols=["candidate_signal"],
                entry_price_col="open",
                exit_price_col="close",
                entry_lag_bars=1,
                horizons_bars=[1],
                min_obs=1,
                min_active_obs=1,
                min_abs_ic=0.0,
                min_positive_period_pct=0.0,
            )

            summary = pd.read_csv(paths.summary_csv)
            self.assertEqual(float(summary.loc[0, "mean_signed_return_points"]), 19.0)
            report = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("Entry price: `open` shifted 1 bar(s)", report)

    def test_sparse_event_signal_can_pass_event_gate_without_ic_gate(self) -> None:
        data = _sparse_event_frame("2024-01-01", periods=240)

        with tempfile.TemporaryDirectory() as tmp:
            paths = run_signal_research_report(
                data,
                out_dir=Path(tmp),
                signal_cols=["candidate_signal"],
                horizons_bars=[1],
                round_trip_cost_points=1.0,
                min_obs=100,
                min_active_obs=10,
                min_abs_ic=1.01,
                min_positive_period_pct=50.0,
                min_event_hit_rate_pct=80.0,
                max_event_placebo_p_value=0.05,
                event_bootstrap_samples=200,
                event_placebo_samples=200,
            )

            summary = pd.read_csv(paths.summary_csv)
            self.assertFalse(bool(summary.loc[0, "eligible_for_candidate"]))
            self.assertTrue(bool(summary.loc[0, "event_eligible_for_candidate"]))
            self.assertGreater(float(summary.loc[0, "bootstrap_mean_ci_low_points"]), 0.0)
            self.assertGreater(float(summary.loc[0, "placebo_edge_points"]), 0.0)
            self.assertLessEqual(float(summary.loc[0, "placebo_p_value"]), 0.05)
            report = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("Event Gate Verdict", report)
            self.assertIn("At least one signal passed the event-signal gate", report)

    def test_stress_cost_blocks_base_cost_candidate_pass(self) -> None:
        forward = np.tile([1.0, 2.0], 80)
        close = 100.0 + np.cumsum(np.r_[0.0, forward])[:-1]
        future_return = pd.Series(close).shift(-1) - pd.Series(close)
        data = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-01", periods=len(close), freq="D"),
                "close": close,
                "candidate_signal": future_return,
            }
        ).dropna().reset_index(drop=True)

        with tempfile.TemporaryDirectory() as tmp:
            paths = run_signal_research_report(
                data,
                out_dir=Path(tmp),
                signal_cols=["candidate_signal"],
                horizons_bars=[1],
                round_trip_cost_points=0.25,
                stress_round_trip_cost_points=[2.0],
                min_obs=50,
                min_active_obs=30,
                min_abs_ic=0.02,
                min_positive_period_pct=50.0,
                event_bootstrap_samples=100,
                event_placebo_samples=100,
            )

            summary = pd.read_csv(paths.summary_csv)
            self.assertFalse(bool(summary.loc[0, "eligible_for_candidate"]))
            self.assertFalse(bool(summary.loc[0, "event_eligible_for_candidate"]))
            self.assertFalse(bool(summary.loc[0, "stress_cost_survives"]))
            self.assertLess(float(summary.loc[0, "stress_min_mean_signed_return_after_cost_points"]), 0.0)
            report = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("Cost Stress Verdict", report)
            self.assertIn("No signal survived all configured stress costs", report)

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

    def test_coerce_bool_series_handles_string_false(self) -> None:
        values = pd.Series(["True", "False", "1", "0", True, False, np.nan, "yes", "no"])

        self.assertEqual(
            coerce_bool_series(values).tolist(),
            [True, False, True, False, True, False, False, True, False],
        )


def _sparse_event_frame(start: str, *, periods: int) -> pd.DataFrame:
    returns = np.zeros(periods)
    active_idx = np.arange(10, periods - 2, 10)
    returns[active_idx + 1] = 4.0
    close = 100.0 + np.cumsum(returns)
    signal = np.zeros(periods)
    signal[active_idx] = 1.0
    return pd.DataFrame(
        {
            "time": pd.date_range(start, periods=periods, freq="D"),
            "close": close,
            "candidate_signal": signal,
            "session_bucket": "daily",
        }
    )


if __name__ == "__main__":
    unittest.main()
