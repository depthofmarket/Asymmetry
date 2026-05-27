from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from backtest.temporal_signal_research import (
    _temporal_event_eligibility,
    _temporal_eligibility,
    parse_temporal_splits,
    run_temporal_signal_research_report,
)


class TemporalSignalResearchTests(unittest.TestCase):
    def test_parse_temporal_splits(self) -> None:
        splits = parse_temporal_splits("legacy:2010-01-01:2015-12-31,recent:2021-01-01:")

        self.assertEqual(splits[0], ("legacy", "2010-01-01", "2015-12-31"))
        self.assertEqual(splits[1], ("recent", "2021-01-01", None))

    def test_temporal_report_marks_primary_pass(self) -> None:
        data = pd.concat(
            [
                _split_frame("2016-01-01", periods=80, signal_scale=1.0),
                _split_frame("2021-01-01", periods=80, signal_scale=1.0),
            ],
            ignore_index=True,
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = run_temporal_signal_research_report(
                data,
                out_dir=Path(tmp),
                artifact_name="temporal_test",
                splits=(("transition", "2016-01-01", "2016-12-31"), ("recent_development", "2021-01-01", "2021-12-31")),
                primary_split="recent_development",
                supporting_splits=("transition",),
                signal_cols=["candidate_signal"],
                horizons_bars=[1],
                min_obs=30,
                min_active_obs=30,
                min_abs_ic=0.02,
                min_positive_period_pct=50.0,
            )

            combined = pd.read_csv(paths.combined_summary_csv)
            self.assertTrue(bool(combined["temporal_eligible_for_candidate"].any()))
            report = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("At least one signal/horizon pair passed", report)

    def test_primary_failure_blocks_temporal_pass(self) -> None:
        data = pd.concat(
            [
                _split_frame("2016-01-01", periods=80, signal_scale=1.0),
                _split_frame("2021-01-01", periods=80, signal_scale=0.0),
            ],
            ignore_index=True,
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = run_temporal_signal_research_report(
                data,
                out_dir=Path(tmp),
                artifact_name="temporal_test",
                splits=(("transition", "2016-01-01", "2016-12-31"), ("recent_development", "2021-01-01", "2021-12-31")),
                primary_split="recent_development",
                supporting_splits=("transition",),
                signal_cols=["candidate_signal"],
                horizons_bars=[1],
                min_obs=30,
                min_active_obs=30,
                min_abs_ic=0.02,
                min_positive_period_pct=50.0,
            )

            combined = pd.read_csv(paths.combined_summary_csv)
            self.assertFalse(bool(combined["temporal_eligible_for_candidate"].any()))

    def test_sparse_event_temporal_gate_can_pass_without_ic_gate(self) -> None:
        data = pd.concat(
            [
                _sparse_event_frame("2016-01-01", periods=240),
                _sparse_event_frame("2021-01-01", periods=240),
            ],
            ignore_index=True,
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = run_temporal_signal_research_report(
                data,
                out_dir=Path(tmp),
                artifact_name="temporal_event_test",
                splits=(("transition", "2016-01-01", "2016-12-31"), ("recent_development", "2021-01-01", "2021-12-31")),
                primary_split="recent_development",
                supporting_splits=("transition",),
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

            combined = pd.read_csv(paths.combined_summary_csv)
            self.assertFalse(bool(combined["temporal_eligible_for_candidate"].any()))
            self.assertTrue(bool(combined["temporal_event_eligible_for_candidate"].any()))
            report = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("At least one signal/horizon pair passed the temporal event-signal gate", report)

    def test_stress_cost_blocks_temporal_candidate_pass(self) -> None:
        data = pd.concat(
            [
                _low_edge_split_frame("2016-01-01", periods=120),
                _low_edge_split_frame("2021-01-01", periods=120),
            ],
            ignore_index=True,
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = run_temporal_signal_research_report(
                data,
                out_dir=Path(tmp),
                artifact_name="temporal_stress_test",
                splits=(("transition", "2016-01-01", "2016-12-31"), ("recent_development", "2021-01-01", "2021-12-31")),
                primary_split="recent_development",
                supporting_splits=("transition",),
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

            combined = pd.read_csv(paths.combined_summary_csv)
            self.assertFalse(bool(combined["temporal_eligible_for_candidate"].any()))
            self.assertFalse(bool(combined["stress_cost_survives"].any()))
            report = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("Cost Stress Verdict", report)
            self.assertIn("No split row survived all configured stress costs", report)

    def test_string_false_does_not_become_truthy_in_temporal_gates(self) -> None:
        combined = pd.DataFrame(
            [
                {
                    "split": "recent_development",
                    "signal": "candidate_signal",
                    "horizon_bars": 1,
                    "eligible_for_candidate": "False",
                    "event_eligible_for_candidate": "False",
                    "n_active": 100,
                    "ic": 0.5,
                    "mean_signed_return_after_cost_points": 2.0,
                },
                {
                    "split": "transition",
                    "signal": "candidate_signal",
                    "horizon_bars": 1,
                    "eligible_for_candidate": "True",
                    "event_eligible_for_candidate": "True",
                    "n_active": 100,
                    "ic": 0.5,
                    "mean_signed_return_after_cost_points": 2.0,
                },
            ]
        )

        ic_gate = _temporal_eligibility(
            combined,
            primary_split="recent_development",
            supporting_splits=["transition"],
            min_active_obs=30,
            min_abs_ic=0.02,
        )
        event_gate = _temporal_event_eligibility(
            combined,
            primary_split="recent_development",
            supporting_splits=["transition"],
        )

        self.assertFalse(bool(ic_gate.any()))
        self.assertFalse(bool(event_gate.any()))


def _split_frame(start: str, *, periods: int, signal_scale: float) -> pd.DataFrame:
    returns = np.sin(np.arange(periods + 1) / 3.0)
    close = 100.0 + np.cumsum(returns[:-1])
    future_return = pd.Series(close).shift(-1) - pd.Series(close)
    signal = np.sign(future_return.fillna(0.0)) * float(signal_scale)
    return pd.DataFrame(
        {
            "time": pd.date_range(start, periods=periods, freq="D"),
            "open": close,
            "close": close,
            "candidate_signal": signal,
            "session_bucket": "daily",
        }
    )


def _low_edge_split_frame(start: str, *, periods: int) -> pd.DataFrame:
    forward = np.tile([1.0, 2.0], int(np.ceil(periods / 2)))[:periods]
    close = 100.0 + np.cumsum(np.r_[0.0, forward])[:-1]
    future_return = pd.Series(close).shift(-1) - pd.Series(close)
    return pd.DataFrame(
        {
            "time": pd.date_range(start, periods=periods, freq="D"),
            "open": close,
            "close": close,
            "candidate_signal": future_return,
            "session_bucket": "daily",
        }
    ).dropna().reset_index(drop=True)


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
            "open": close,
            "close": close,
            "candidate_signal": signal,
            "session_bucket": "daily",
        }
    )


if __name__ == "__main__":
    unittest.main()
