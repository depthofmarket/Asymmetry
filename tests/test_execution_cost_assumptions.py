from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.execution_cost_assumptions import (
    build_execution_cost_assumption_report,
    write_execution_cost_assumption_report,
)


def _quality_summary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": 20201201,
                "source_schemas": "semicolon_1col:200000",
                "usable_quote_rows": 24986,
                "usable_trade_rows": 90499,
                "quote_rows_per_depth_update": 0.267,
                "trade_rows_per_type1_event": 0.850,
                "minute_rows": 234,
            },
            {
                "date": 20210104,
                "source_schemas": "semicolon_1col:200000",
                "usable_quote_rows": 20471,
                "usable_trade_rows": 103781,
                "quote_rows_per_depth_update": 0.244,
                "trade_rows_per_type1_event": 0.893,
                "minute_rows": 151,
            },
            {
                "date": 20210601,
                "source_schemas": "semicolon_1col:200000",
                "usable_quote_rows": 21174,
                "usable_trade_rows": 81753,
                "quote_rows_per_depth_update": 0.198,
                "trade_rows_per_type1_event": 0.878,
                "minute_rows": 208,
            },
            {
                "date": 20220103,
                "source_schemas": "structured_5col:200000",
                "usable_quote_rows": 39,
                "usable_trade_rows": 344,
                "quote_rows_per_depth_update": 0.00037,
                "trade_rows_per_type1_event": 0.0035,
                "minute_rows": 1,
            },
        ]
    )


def _baseline_summary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": 20201201,
                "minute_rows": 234,
                "median_rt_spread_cost_points": 1.25,
                "median_rt_trade_vs_mid_cost_points": 2.00,
                "p95_rt_trade_vs_mid_cost_points": 3.039,
                "median_top_book_depth_exhausted_trade_pct": 0.518,
            },
            {
                "date": 20210104,
                "minute_rows": 151,
                "median_rt_spread_cost_points": 1.00,
                "median_rt_trade_vs_mid_cost_points": 1.25,
                "p95_rt_trade_vs_mid_cost_points": 2.425,
                "median_top_book_depth_exhausted_trade_pct": 0.319,
            },
            {
                "date": 20210601,
                "minute_rows": 208,
                "median_rt_spread_cost_points": 1.00,
                "median_rt_trade_vs_mid_cost_points": 1.50,
                "p95_rt_trade_vs_mid_cost_points": 2.00,
                "median_top_book_depth_exhausted_trade_pct": 0.397,
            },
            {
                "date": 20220103,
                "minute_rows": 1,
                "median_rt_spread_cost_points": 0.50,
                "median_rt_trade_vs_mid_cost_points": 1.50,
                "p95_rt_trade_vs_mid_cost_points": 1.50,
                "median_top_book_depth_exhausted_trade_pct": 0.468,
            },
        ]
    )


class ExecutionCostAssumptionTests(unittest.TestCase):
    def test_recommends_costs_from_accepted_l2_rows_only(self) -> None:
        report = build_execution_cost_assumption_report(_quality_summary(), _baseline_summary())

        evidence = report.evidence.set_index("date")
        self.assertEqual(evidence.loc[20201201, "cost_evidence_status"], "accepted")
        self.assertEqual(evidence.loc[20220103, "cost_evidence_status"], "rejected")
        self.assertIn("structured schema", evidence.loc[20220103, "cost_evidence_reason"])

        rec = report.recommendation.iloc[0]
        self.assertAlmostEqual(float(rec["slippage_points"]), 1.50)
        self.assertAlmostEqual(float(rec["slippage_stop_points"]), 2.50)
        self.assertAlmostEqual(float(rec["slippage_limit_points"]), 0.75)
        self.assertEqual(int(rec["accepted_dates"]), 3)
        self.assertEqual(int(rec["rejected_dates"]), 1)

    def test_writes_report_artifacts(self) -> None:
        report = build_execution_cost_assumption_report(_quality_summary(), _baseline_summary())
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = write_execution_cost_assumption_report(report, Path(tmp_dir))
            self.assertTrue(paths.evidence_csv.exists())
            self.assertTrue(paths.recommendation_csv.exists())
            self.assertIn("Execution Cost Assumptions", paths.report_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
