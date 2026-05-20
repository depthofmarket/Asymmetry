from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.research_freeze import DEFAULT_FREEZE_CANDIDATE, verify_freeze, write_manifest


class ResearchFreezeTests(unittest.TestCase):
    def test_lockbox_freeze_passes_with_matching_manifest_and_saved_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "research_freeze.json"
            run_dir = root / f"20260101_120000_{DEFAULT_FREEZE_CANDIDATE}_long_short_next_bar_open_hybrid"
            trade_dir = run_dir / "trades"
            sim_dir = run_dir / "simulations"
            trade_dir.mkdir(parents=True)
            sim_dir.mkdir(parents=True)
            write_manifest(manifest_path, DEFAULT_FREEZE_CANDIDATE)
            pd.DataFrame(
                [
                    {"pnl": 100.0},
                    {"pnl": -30.0},
                    {"pnl": 50.0},
                    {"pnl": -20.0},
                    {"pnl": 80.0},
                ]
            ).to_csv(trade_dir / "trade_log.csv", index=False)
            pd.DataFrame(
                [
                    {"scenario": "combined_mild", "profit_factor": 1.2, "total_pnl": 100.0}
                ]
            ).to_csv(sim_dir / "stress_trade_stress_tests.csv", index=False)

            report = verify_freeze(manifest_path, run_dir=run_dir, phase="lockbox")

            self.assertTrue(report.passed, report.summary())

    def test_development_freeze_fails_when_required_report_checks_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "research_freeze.json"
            run_dir = root / f"20260101_120000_{DEFAULT_FREEZE_CANDIDATE}_long_short_next_bar_open_hybrid"
            research_dir = run_dir / "research"
            prop_dir = research_dir / "walkforward" / "prop_firm"
            sim_dir = run_dir / "simulations"
            research_dir.mkdir(parents=True)
            prop_dir.mkdir(parents=True)
            sim_dir.mkdir(parents=True)
            write_manifest(manifest_path, DEFAULT_FREEZE_CANDIDATE)
            pd.DataFrame(
                [
                    {"check": "trade_profit_factor", "status": "PASS", "value": 1.2, "threshold": ">= 1.1"},
                    {"check": "bar_profit_factor", "status": "FAIL", "value": 0.8, "threshold": ">= 1.05"},
                ]
            ).to_csv(research_dir / "development_report.csv", index=False)
            pd.DataFrame(
                [{"fold_idx": 0, "status": "PASS"}]
            ).to_csv(research_dir / "optimization_stability.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "expected_net_payout_per_eval_attempt": 1.0,
                        "probability_eval_to_first_payout_pct": 1.0,
                    }
                ]
            ).to_csv(prop_dir / "walkforward_stitched_summary.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "pnl_pass_5pct": True,
                        "sharpe_pass_5pct": True,
                        "pnl_p_value": 0.01,
                        "sharpe_p_value": 0.01,
                    }
                ]
            ).to_csv(prop_dir / "walkforward_stitched_random_walk.csv", index=False)
            pd.DataFrame(
                [
                    {"scenario": "combined_mild", "profit_factor": 1.2, "total_pnl": 100.0}
                ]
            ).to_csv(sim_dir / "stress_trade_stress_tests.csv", index=False)

            report = verify_freeze(manifest_path, run_dir=run_dir, phase="development")

            self.assertFalse(report.passed)
            failed_names = {check.name for check in report.checks if not check.passed}
            self.assertIn("development_report:bar_profit_factor", failed_names)


if __name__ == "__main__":
    unittest.main()
