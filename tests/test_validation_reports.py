from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.validation import (
    export_development_report,
    export_multiple_testing_debt_report,
    export_optimization_stability_report,
    export_research_discipline_report,
)


class ValidationReportTests(unittest.TestCase):
    def test_development_report_includes_combined_mild_stress_hard_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "research"
            stress_csv = Path(tmp) / "stress_trade_stress_tests.csv"
            pd.DataFrame(
                [
                    {"scenario": "base", "profit_factor": 1.4, "total_pnl": 1000.0},
                    {"scenario": "combined_mild", "profit_factor": 0.91, "total_pnl": -250.0},
                ]
            ).to_csv(stress_csv, index=False)

            paths = export_development_report(
                results={
                    "profit_factor": 1.3,
                    "bar_profit_factor": 1.1,
                    "execution_bar_profit_factor": 1.4,
                    "total_trades": 50,
                    "win_rate": 48.0,
                },
                years=1.0,
                out_dir=out_dir,
                validation_config={
                    "min_in_sample_profit_factor": 1.1,
                    "min_in_sample_bar_profit_factor": 1.05,
                    "min_walk_forward_profit_factor": 1.05,
                    "min_walk_forward_bar_profit_factor": 1.0,
                    "min_walk_forward_total_pnl": 0.0,
                    "min_trades_per_year": 20.0,
                    "max_suspicious_win_rate_pct": 75.0,
                    "max_suspicious_profit_factor": 3.0,
                    "max_in_sample_permutation_p": 0.01,
                    "max_walk_forward_permutation_p": 0.05,
                    "min_combined_mild_profit_factor": 1.05,
                    "min_combined_mild_total_pnl": 0.0,
                },
                stress_summary_csv=stress_csv,
            )

            report = pd.read_csv(paths.csv_path)
            stress_rows = report[report["step"].eq("5_stress_hard_warnings")]
            execution_row = report[report["check"].eq("execution_bar_profit_factor")]

            self.assertEqual(stress_rows["status"].tolist(), ["FAIL", "FAIL"])
            self.assertIn("combined_mild_profit_factor", stress_rows["check"].tolist())
            self.assertIn("combined_mild_total_pnl", stress_rows["check"].tolist())
            self.assertEqual(execution_row.iloc[0]["status"], "SKIP")
            self.assertEqual(float(execution_row.iloc[0]["value"]), 1.4)

    def test_optimization_stability_report_flags_sharp_train_optimum_and_oos_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wf = SimpleNamespace(
                folds=[
                    SimpleNamespace(
                        fold_idx=0,
                        train_start=pd.Timestamp("2021-01-01"),
                        train_end=pd.Timestamp("2024-01-01"),
                        test_start=pd.Timestamp("2024-01-01"),
                        test_end=pd.Timestamp("2024-07-01"),
                        best_overrides={"entry_delay_bars": 1},
                        train_metric=2.0,
                        train_neighbor_metric=0.5,
                        test_results={
                            "total_trades": 12,
                            "total_pnl": -100.0,
                            "profit_factor": 0.9,
                            "bar_profit_factor": 0.8,
                        },
                    )
                ]
            )

            paths = export_optimization_stability_report(
                wf,
                out_dir=Path(tmp),
                validation_config={
                    "min_walk_forward_neighbor_metric_ratio": 0.75,
                    "min_walk_forward_bar_profit_factor": 1.0,
                    "min_walk_forward_total_pnl": 0.0,
                },
                metric="bar_profit_factor",
            )

            report = pd.read_csv(paths.csv_path)

            self.assertEqual(report.loc[0, "status"], "FAIL")
            self.assertIn("sharp_train_optimum", report.loc[0, "notes"])
            self.assertIn("oos_metric_failed", report.loc[0, "notes"])
            self.assertIn("oos_pnl_failed", report.loc[0, "notes"])

    def test_multiple_testing_debt_report_tracks_family_and_saved_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            root.mkdir()
            (root / "20260101_120000_alpha_one_long_short_next_bar_open_hybrid").mkdir()
            (root / "20260102_120000_alpha_two_long_short_next_bar_open_hybrid").mkdir()

            paths = export_multiple_testing_debt_report(
                candidate_name="alpha_two",
                candidate_configs={"alpha_one": {}, "alpha_two": {}, "beta_one": {}},
                out_dir=Path(tmp) / "research",
                research_config={
                    "candidate_research_families": {"alpha": ["alpha_one", "alpha_two"]},
                    "next_validation_candidates": ["alpha_one", "alpha_two"],
                    "max_candidate_family_runs_before_holdout": 4,
                    "candidate_family_run_count_floors": {"alpha": 5},
                },
                results_root=root,
            )

            report = pd.read_csv(paths.csv_path)

            self.assertEqual(set(report["candidate"]), {"alpha_one", "alpha_two"})
            self.assertEqual(int(report["saved_run_count"].sum()), 2)
            self.assertEqual(int(report["effective_family_run_count"].max()), 5)
            current = report[report["is_current"]]
            self.assertEqual(current.iloc[0]["candidate"], "alpha_two")

    def test_research_discipline_report_rejects_rejected_candidate_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "20260103_120000_alpha_one_long_short_next_bar_open_hybrid"
            (run_dir / "research").mkdir(parents=True)

            paths = export_research_discipline_report(
                run_dir=run_dir,
                research_config={
                    "candidate_research_families": {"alpha": ["alpha_one", "alpha_two"]},
                    "rejected_research_families": {
                        "alpha": {
                            "status": "rejected",
                            "decision_date": "2026-05-20",
                            "reason": "failed strict validation",
                        }
                    },
                },
            )

            report = pd.read_csv(paths.csv_path)
            family_row = report.loc[report["check"].eq("candidate_family_not_rejected")].iloc[0]
            summary = report.loc[report["check"].eq("promotion_eligible")].iloc[0]

            self.assertEqual(family_row["status"], "FAIL")
            self.assertEqual(family_row["value"], "alpha")
            self.assertIn("failed strict validation", family_row["notes"])
            self.assertEqual(summary["status"], "FAIL")

    def test_research_discipline_report_passes_only_complete_oos_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            research = run_dir / "research"
            (research / "bar_exposure_audit").mkdir(parents=True)
            (research / "execution_realism").mkdir(parents=True)
            (research / "walkforward" / "prop_firm").mkdir(parents=True)

            pd.DataFrame(
                [
                    {"step": "1_in_sample_excellence", "check": "trade_profit_factor", "status": "PASS", "value": 1.3, "threshold": ">= 1.1"},
                    {"step": "1_in_sample_excellence", "check": "bar_profit_factor", "status": "PASS", "value": 1.1, "threshold": ">= 1.05"},
                    {"step": "1_in_sample_excellence", "check": "obvious_overfit_smell", "status": "PASS", "value": "ok", "threshold": "below suspicious limits"},
                    {"step": "1_in_sample_excellence", "check": "sharpe_overfit_smell", "status": "PASS", "value": 1.2, "threshold": "abs <= 3"},
                    {"step": "2_in_sample_permutation", "check": "p_value_smoothed", "status": "PASS", "value": 0.005, "threshold": "<= 0.01"},
                    {"step": "3_walk_forward", "check": "stitched_oos_profit_factor", "status": "PASS", "value": 1.12, "threshold": ">= 1.05"},
                    {"step": "3_walk_forward", "check": "stitched_oos_bar_profit_factor", "status": "PASS", "value": 1.05, "threshold": ">= 1.0"},
                    {"step": "3_walk_forward", "check": "stitched_oos_total_pnl", "status": "PASS", "value": 100.0, "threshold": ">= 0"},
                    {"step": "3_walk_forward", "check": "stitched_oos_trades_per_year", "status": "PASS", "value": 30.0, "threshold": ">= 20"},
                    {"step": "3_walk_forward", "check": "selected_param_neighborhood_ratio", "status": "PASS", "value": 0.9, "threshold": ">= 0.75"},
                    {"step": "4_walk_forward_permutation", "check": "p_value_smoothed", "status": "PASS", "value": 0.03, "threshold": "<= 0.05"},
                    {"step": "5_stress_hard_warnings", "check": "combined_mild_profit_factor", "status": "PASS", "value": 1.08, "threshold": ">= 1.05"},
                    {"step": "5_stress_hard_warnings", "check": "combined_mild_total_pnl", "status": "PASS", "value": 50.0, "threshold": "> 0"},
                ]
            ).to_csv(research / "development_report.csv", index=False)
            pd.DataFrame(
                [
                    {"candidate": "alpha", "saved_run_count": 1, "configured_family_candidates": 2},
                    {"candidate": "alpha_delay_1", "saved_run_count": 1, "configured_family_candidates": 2},
                ]
            ).to_csv(research / "multiple_testing_debt.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "decision": "inconclusive_or_candidate_survives",
                        "bar_pf_mismatch": False,
                    }
                ]
            ).to_csv(research / "bar_exposure_audit" / "bar_exposure_audit_summary.csv", index=False)
            pd.DataFrame(
                [
                    {"scenario": "target_default_slippage", "profit_factor": 1.02},
                    {"scenario": "target_stop_like_slippage", "profit_factor": 1.01},
                ]
            ).to_csv(research / "execution_realism" / "execution_realism_summary.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "sample_scope": "walkforward_oos",
                        "expected_net_payout_per_eval_attempt": 10.0,
                        "trading_objective": "prop_eval_flip",
                        "fill_model": "prop_demo_fill_assumption",
                        "trade_sample_size": 20,
                        "minimum_trade_sample": 500,
                        "sample_size_warning": "sample_below_minimum_500_trades",
                    }
                ]
            ).to_csv(research / "walkforward" / "prop_firm" / "walkforward_stitched_summary.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "pnl_pass_5pct": True,
                        "sharpe_pass_5pct": True,
                        "pnl_p_value": 0.01,
                        "sharpe_p_value": 0.02,
                    }
                ]
            ).to_csv(research / "walkforward" / "prop_firm" / "walkforward_stitched_random_walk.csv", index=False)

            paths = export_research_discipline_report(
                run_dir=run_dir,
                validation_config={
                    "research_discipline_require_permutation": True,
                    "research_discipline_require_bar_exposure_audit": True,
                    "research_discipline_require_execution_realism": True,
                    "max_in_sample_to_walk_forward_profit_factor_ratio": 2.5,
                    "min_execution_realism_profit_factor": 1.0,
                },
                research_config={"max_candidate_family_runs_before_holdout": 4},
            )

            report = pd.read_csv(paths.csv_path)
            summary = report.loc[report["check"].eq("promotion_eligible")].iloc[0]
            objective = report.loc[report["check"].eq("prop_trading_objective_declared")].iloc[0]
            fill_model = report.loc[report["check"].eq("prop_fill_model_declared")].iloc[0]
            sample_size = report.loc[report["check"].eq("prop_trade_sample_size")].iloc[0]
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(objective["status"], "WARN")
            self.assertEqual(fill_model["status"], "WARN")
            self.assertEqual(sample_size["status"], "WARN")

    def test_research_discipline_report_rejects_missing_defenses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            research = run_dir / "research"
            research.mkdir(parents=True)
            pd.DataFrame(
                [
                    {"step": "1_in_sample_excellence", "check": "trade_profit_factor", "status": "PASS", "value": 2.0, "threshold": ">= 1.1"},
                    {"step": "1_in_sample_excellence", "check": "bar_profit_factor", "status": "PASS", "value": 1.2, "threshold": ">= 1.05"},
                    {"step": "1_in_sample_excellence", "check": "obvious_overfit_smell", "status": "PASS", "value": "ok", "threshold": "below suspicious limits"},
                    {"step": "2_in_sample_permutation", "check": "p_value", "status": "SKIP", "value": "", "threshold": "<= 0.01"},
                    {"step": "3_walk_forward", "check": "stitched_oos_profit_factor", "status": "PASS", "value": 0.8, "threshold": ">= 1.05"},
                    {"step": "3_walk_forward", "check": "stitched_oos_bar_profit_factor", "status": "FAIL", "value": 0.7, "threshold": ">= 1.0"},
                    {"step": "3_walk_forward", "check": "stitched_oos_total_pnl", "status": "FAIL", "value": -100.0, "threshold": ">= 0"},
                    {"step": "3_walk_forward", "check": "stitched_oos_trades_per_year", "status": "PASS", "value": 30.0, "threshold": ">= 20"},
                    {"step": "3_walk_forward", "check": "selected_param_neighborhood_ratio", "status": "FAIL", "value": 0.2, "threshold": ">= 0.75"},
                    {"step": "5_stress_hard_warnings", "check": "combined_mild_profit_factor", "status": "FAIL", "value": 0.6, "threshold": ">= 1.05"},
                    {"step": "5_stress_hard_warnings", "check": "combined_mild_total_pnl", "status": "FAIL", "value": -500.0, "threshold": "> 0"},
                ]
            ).to_csv(research / "development_report.csv", index=False)

            paths = export_research_discipline_report(
                run_dir=run_dir,
                validation_config={"research_discipline_require_permutation": True},
                research_config={"max_candidate_family_runs_before_holdout": 4},
            )

            report = pd.read_csv(paths.csv_path)
            summary = report.loc[report["check"].eq("promotion_eligible")].iloc[0]
            self.assertEqual(summary["status"], "FAIL")
            self.assertGreater(int(summary["value"]), 0)


if __name__ == "__main__":
    unittest.main()
