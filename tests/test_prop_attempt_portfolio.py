from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.prop_attempt_portfolio import (
    build_prop_attempt_portfolio,
    export_prop_attempt_portfolio_report,
)


class PropAttemptPortfolioTests(unittest.TestCase):
    def test_build_portfolio_clamps_accounts_and_includes_all_fees(self) -> None:
        summary = pd.DataFrame(
            [
                {
                    "profile": "unit_prop",
                    "sample_scope": "walkforward_oos",
                    "evidence_grade": "validation_candidate",
                    "trading_objective": "prop_eval_flip",
                    "fill_model": "prop_demo_fill_assumption",
                    "pass_probability_pct": 100.0,
                    "first_payout_probability_pct": 100.0,
                    "avg_net_payout_after_split": 1_000.0,
                    "eval_cost": 10.0,
                    "activation_fee": 100.0,
                    "reset_fee": 5.0,
                    "max_resets_per_account": 1,
                    "monthly_fee": 0.0,
                    "account_bundle_cost": 20.0,
                    "max_accounts": 3,
                    "payout_cap": 0.0,
                    "portfolio_account_counts": "1,5",
                    "trade_sample_size": 100,
                    "minimum_trade_sample": 500,
                    "sample_size_warning": "sample_below_minimum_500_trades",
                }
            ]
        )

        portfolio, samples = build_prop_attempt_portfolio(summary, bankroll=1_000, n_sims=10, seed=1)

        self.assertEqual(len(portfolio), 2)
        one_account = portfolio.loc[portfolio["requested_account_count"].eq(1)].iloc[0]
        capped_accounts = portfolio.loc[portfolio["requested_account_count"].eq(5)].iloc[0]
        self.assertEqual(int(one_account["account_count"]), 1)
        self.assertEqual(int(capped_accounts["account_count"]), 3)
        self.assertEqual(float(one_account["expected_total_cost"]), 130.0)
        self.assertEqual(float(one_account["expected_total_payout"]), 1_000.0)
        self.assertEqual(float(one_account["expected_net_value"]), 870.0)
        self.assertAlmostEqual(float(one_account["kelly_cost_basis"]), 110.0)
        self.assertAlmostEqual(float(one_account["kelly_payoff_ratio"]), 1_000.0 / 110.0)
        self.assertAlmostEqual(float(one_account["kelly_break_even_probability_pct"]), 11.0)
        self.assertAlmostEqual(float(one_account["kelly_fraction_pct"]), 100.0)
        self.assertEqual(int(one_account["kelly_active_accounts"]), 9)
        self.assertEqual(float(capped_accounts["expected_total_cost"]), 350.0)
        self.assertEqual(float(capped_accounts["expected_total_payout"]), 3_000.0)
        self.assertEqual(float(capped_accounts["expected_net_value"]), 2_650.0)
        self.assertEqual(int(capped_accounts["kelly_account_gap"]), -6)
        self.assertEqual(len(samples), 20)

    def test_export_writes_portfolio_artifacts(self) -> None:
        summary = pd.DataFrame(
            [
                {
                    "profile": "unit_prop",
                    "pass_probability_pct": 0.0,
                    "first_payout_probability_pct": 0.0,
                    "avg_net_payout_after_split": 0.0,
                    "eval_cost": 50.0,
                    "activation_fee": 100.0,
                    "max_accounts": 2,
                    "portfolio_account_counts": "1,2",
                }
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = export_prop_attempt_portfolio_report(
                summary,
                out_dir=Path(tmp),
                artifact_name="portfolio",
                n_sims=5,
                seed=1,
            )

            self.assertTrue(paths.summary_csv.exists())
            self.assertTrue(paths.samples_csv.exists())
            self.assertTrue(paths.report_md.exists())
            report_text = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("Prop Attempt Portfolio", report_text)
            self.assertIn("does not run a backtest", report_text)


if __name__ == "__main__":
    unittest.main()
