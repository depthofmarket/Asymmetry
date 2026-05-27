from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.tbbo_execution_baseline import (
    build_tbbo_execution_baseline,
    write_tbbo_execution_baseline,
)


def _minute_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "NQH6",
                "minute": "2026-03-18 09:35:00",
                "trade_date": "2026-03-18",
                "rth_session": True,
                "rows": 100,
                "median_spread_points": 0.50,
                "p95_spread_points": 1.00,
                "mean_bid_size": 4,
                "mean_ask_size": 4,
                "trade_count": 80,
                "trade_size": 100,
                "p95_abs_trade_price_vs_mid": 0.25,
                "top_book_depth_exhausted_trade_count": 4,
                "top_book_depth_exhausted_trade_size": 10,
                "top_book_excess_trade_size": 2,
                "top_book_depth_exhausted_trade_pct": 0.05,
                "top_book_depth_exhausted_size_share": 0.10,
                "zero_impact_depth_supported_trade_count": 70,
                "zero_impact_depth_supported_trade_pct": 0.875,
                "median_trade_size_to_opposite_best_size": 0.50,
                "p95_trade_size_to_opposite_best_size": 1.00,
            },
            {
                "symbol": "NQH6",
                "minute": "2026-03-18 10:45:00",
                "trade_date": "2026-03-18",
                "rth_session": True,
                "rows": 90,
                "median_spread_points": 1.00,
                "p95_spread_points": 1.25,
                "mean_bid_size": 3,
                "mean_ask_size": 4,
                "trade_count": 70,
                "trade_size": 90,
                "p95_abs_trade_price_vs_mid": 0.50,
                "top_book_depth_exhausted_trade_count": 14,
                "top_book_depth_exhausted_trade_size": 30,
                "top_book_excess_trade_size": 6,
                "top_book_depth_exhausted_trade_pct": 0.20,
                "top_book_depth_exhausted_size_share": 0.333,
                "zero_impact_depth_supported_trade_count": 40,
                "zero_impact_depth_supported_trade_pct": 0.571,
                "median_trade_size_to_opposite_best_size": 0.90,
                "p95_trade_size_to_opposite_best_size": 1.50,
            },
            {
                "symbol": "NQH6",
                "minute": "2026-03-18 15:45:00",
                "trade_date": "2026-03-18",
                "rth_session": True,
                "rows": 80,
                "median_spread_points": 1.25,
                "p95_spread_points": 1.50,
                "mean_bid_size": 2,
                "mean_ask_size": 3,
                "trade_count": 60,
                "trade_size": 70,
                "p95_abs_trade_price_vs_mid": 0.90,
                "top_book_depth_exhausted_trade_count": 18,
                "top_book_depth_exhausted_trade_size": 35,
                "top_book_excess_trade_size": 8,
                "top_book_depth_exhausted_trade_pct": 0.30,
                "top_book_depth_exhausted_size_share": 0.50,
                "zero_impact_depth_supported_trade_count": 25,
                "zero_impact_depth_supported_trade_pct": 0.417,
                "median_trade_size_to_opposite_best_size": 1.10,
                "p95_trade_size_to_opposite_best_size": 2.00,
            },
            {
                "symbol": "NQZ6",
                "minute": "2026-05-07 14:25:00",
                "trade_date": "2026-05-07",
                "rth_session": True,
                "rows": 1,
                "median_spread_points": 35.75,
                "p95_spread_points": 35.75,
                "mean_bid_size": 2,
                "mean_ask_size": 2,
                "trade_count": 1,
                "trade_size": 1,
                "p95_abs_trade_price_vs_mid": 17.875,
                "top_book_depth_exhausted_trade_count": 1,
                "top_book_depth_exhausted_trade_size": 1,
                "top_book_excess_trade_size": 1,
                "top_book_depth_exhausted_trade_pct": 1.00,
                "top_book_depth_exhausted_size_share": 1.00,
                "zero_impact_depth_supported_trade_count": 0,
                "zero_impact_depth_supported_trade_pct": 0.00,
                "median_trade_size_to_opposite_best_size": 2.00,
                "p95_trade_size_to_opposite_best_size": 2.00,
            },
        ]
    )


class TbboExecutionBaselineTests(unittest.TestCase):
    def test_baseline_summarizes_costs_and_quality_flags(self) -> None:
        baseline = build_tbbo_execution_baseline(
            _minute_stats(),
            assumed_round_trip_cost_points=1.5,
            min_rows_per_minute=5,
            min_daily_minutes=2,
            wide_spread_points=10.0,
        )

        summary = baseline.summary.iloc[0]
        self.assertEqual(int(summary["minute_rows"]), 4)
        self.assertEqual(int(summary["trade_dates"]), 2)
        self.assertEqual(float(summary["median_rt_spread_cost_points"]), 1.125)
        self.assertAlmostEqual(float(summary["median_top_book_depth_exhausted_trade_pct"]), 0.25)
        self.assertAlmostEqual(float(summary["median_zero_impact_depth_supported_trade_pct"]), 0.494)
        self.assertEqual(
            summary["cost_model_verdict"],
            "assumed_cost_ok_for_typical_liquidity_but_too_low_for_tail_conditions",
        )

        flags = set(baseline.quality_flags["flag"])
        self.assertIn("sparse_date_symbol_group", flags)
        self.assertIn("wide_spread_date_symbol_group", flags)
        self.assertIn("tail_cost_gt_assumed_date_symbol_group", flags)

    def test_baseline_groups_by_session_and_hour(self) -> None:
        baseline = build_tbbo_execution_baseline(_minute_stats(), assumed_round_trip_cost_points=1.5)

        by_session = baseline.by_session.set_index("session_bucket")
        self.assertIn("rth_open", by_session.index)
        self.assertIn("rth_midday", by_session.index)
        self.assertIn("rth_close", by_session.index)
        self.assertAlmostEqual(float(by_session.loc["rth_open", "median_rt_spread_cost_points"]), 0.50)

        self.assertEqual(set(baseline.by_hour["hour"]), {9, 10, 14, 15})

    def test_write_baseline_outputs_csvs_and_markdown(self) -> None:
        baseline = build_tbbo_execution_baseline(_minute_stats(), assumed_round_trip_cost_points=1.5)
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_tbbo_execution_baseline(baseline, Path(tmp))

            self.assertTrue(paths.summary_csv.exists())
            self.assertTrue(paths.by_session_csv.exists())
            self.assertTrue(paths.by_hour_csv.exists())
            self.assertTrue(paths.by_date_csv.exists())
            self.assertTrue(paths.quality_flags_csv.exists())
            self.assertTrue(paths.report_md.exists())
            report = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("execution-realism report", report)
            self.assertIn("top-book depth-exhausted", report)


if __name__ == "__main__":
    unittest.main()
