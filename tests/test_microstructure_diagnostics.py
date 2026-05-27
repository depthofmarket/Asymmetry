from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.microstructure_diagnostics import (
    book_imbalance,
    build_book_imbalance_summary,
    build_depth_exhaustion_summary,
    build_microstructure_diagnostics,
    build_microstructure_cost_state,
    build_price_change_buckets,
    build_signal_adverse_selection_diagnostics,
    build_spread_reversion_stats,
    build_trade_sign_memory_diagnostics,
    classify_price_changing_trades,
    write_microstructure_diagnostics,
)


def _tbbo_minute_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "NQH6",
                "minute": "2026-02-16 09:30:00",
                "trade_date": "2026-02-16",
                "median_mid_price": 100.00,
                "median_spread_points": 1.00,
                "p95_spread_points": 1.25,
                "median_top_book_imbalance": 0.40,
                "trade_count": 10,
                "trade_size": 20.0,
                "raw_b_side_count": 8,
                "raw_a_side_count": 2,
                "median_abs_trade_price_vs_mid": 0.25,
                "p95_abs_trade_price_vs_mid": 0.50,
                "median_opposite_best_size": 5.0,
                "p25_opposite_best_size": 4.0,
                "median_trade_size_to_opposite_best_size": 0.60,
                "p95_trade_size_to_opposite_best_size": 1.20,
                "top_book_depth_exhausted_trade_count": 1,
                "top_book_depth_exhausted_trade_size": 2.0,
                "top_book_excess_trade_size": 0.5,
                "top_book_depth_exhausted_trade_pct": 0.10,
                "top_book_depth_exhausted_size_share": 0.10,
                "zero_impact_depth_supported_trade_count": 8,
                "zero_impact_depth_supported_trade_pct": 0.80,
            },
            {
                "symbol": "NQH6",
                "minute": "2026-02-16 09:31:00",
                "trade_date": "2026-02-16",
                "median_mid_price": 100.50,
                "median_spread_points": 3.00,
                "p95_spread_points": 3.50,
                "median_top_book_imbalance": -0.35,
                "trade_count": 10,
                "trade_size": 20.0,
                "raw_b_side_count": 2,
                "raw_a_side_count": 8,
                "median_abs_trade_price_vs_mid": 0.50,
                "p95_abs_trade_price_vs_mid": 1.00,
                "median_opposite_best_size": 2.0,
                "p25_opposite_best_size": 1.0,
                "median_trade_size_to_opposite_best_size": 1.50,
                "p95_trade_size_to_opposite_best_size": 2.50,
                "top_book_depth_exhausted_trade_count": 7,
                "top_book_depth_exhausted_trade_size": 15.0,
                "top_book_excess_trade_size": 5.0,
                "top_book_depth_exhausted_trade_pct": 0.70,
                "top_book_depth_exhausted_size_share": 0.75,
                "zero_impact_depth_supported_trade_count": 1,
                "zero_impact_depth_supported_trade_pct": 0.10,
            },
            {
                "symbol": "NQH6",
                "minute": "2026-02-16 09:32:00",
                "trade_date": "2026-02-16",
                "median_mid_price": 100.25,
                "median_spread_points": 1.50,
                "p95_spread_points": 2.00,
                "median_top_book_imbalance": 0.00,
                "trade_count": 10,
                "trade_size": 20.0,
                "raw_b_side_count": 6,
                "raw_a_side_count": 4,
                "median_abs_trade_price_vs_mid": 0.25,
                "p95_abs_trade_price_vs_mid": 0.75,
                "median_opposite_best_size": 3.0,
                "p25_opposite_best_size": 2.0,
                "median_trade_size_to_opposite_best_size": 0.90,
                "p95_trade_size_to_opposite_best_size": 1.40,
                "top_book_depth_exhausted_trade_count": 2,
                "top_book_depth_exhausted_trade_size": 5.0,
                "top_book_excess_trade_size": 1.0,
                "top_book_depth_exhausted_trade_pct": 0.20,
                "top_book_depth_exhausted_size_share": 0.25,
                "zero_impact_depth_supported_trade_count": 6,
                "zero_impact_depth_supported_trade_pct": 0.60,
            },
            {
                "symbol": "NQH6",
                "minute": "2026-02-16 09:33:00",
                "trade_date": "2026-02-16",
                "median_mid_price": 100.75,
                "median_spread_points": 0.75,
                "p95_spread_points": 1.00,
                "median_top_book_imbalance": 0.65,
                "trade_count": 10,
                "trade_size": 20.0,
                "raw_b_side_count": 7,
                "raw_a_side_count": 3,
                "median_abs_trade_price_vs_mid": 0.25,
                "p95_abs_trade_price_vs_mid": 0.50,
                "median_opposite_best_size": 6.0,
                "p25_opposite_best_size": 5.0,
                "median_trade_size_to_opposite_best_size": 0.40,
                "p95_trade_size_to_opposite_best_size": 0.80,
                "top_book_depth_exhausted_trade_count": 0,
                "top_book_depth_exhausted_trade_size": 0.0,
                "top_book_excess_trade_size": 0.0,
                "top_book_depth_exhausted_trade_pct": 0.00,
                "top_book_depth_exhausted_size_share": 0.00,
                "zero_impact_depth_supported_trade_count": 9,
                "zero_impact_depth_supported_trade_pct": 0.90,
            },
        ]
    )


def _aggressive_flow_minute_stats() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["NQH6", "NQH6", "NQH6", "NQH6"],
            "minute": pd.date_range("2026-02-16 09:30", periods=4, freq="min"),
            "trade_date": ["2026-02-16"] * 4,
            "trade_count": [10, 10, 10, 10],
            "trade_size": [20.0, 20.0, 20.0, 20.0],
            "raw_b_minus_a_trade_size": [16.0, -14.0, 0.0, 10.0],
            "raw_b_minus_a_trade_size_share": [0.80, -0.70, 0.00, 0.50],
            "trade_price_change_points": [0.25, -0.50, 0.00, 0.50],
        }
    )


class MicrostructureDiagnosticsTests(unittest.TestCase):
    def test_book_imbalance_helper_and_summary(self) -> None:
        self.assertAlmostEqual(float(book_imbalance(4, 2)), 1.0 / 3.0)

        summary = build_book_imbalance_summary(_tbbo_minute_stats())

        self.assertIn("balanced", set(summary["imbalance_bucket"].astype(str)))
        self.assertIn("median_signed_flow", summary.columns)

    def test_spread_reversion_uses_exact_future_minutes(self) -> None:
        stats = build_spread_reversion_stats(_tbbo_minute_stats(), horizons_minutes=[1])

        self.assertEqual(set(stats["horizon_minutes"]), {1})
        self.assertIn("pct_spread_narrows", stats.columns)
        self.assertGreater(int(stats["observations"].sum()), 0)

    def test_depth_exhaustion_summary_buckets_zero_impact_implausibility(self) -> None:
        summary = build_depth_exhaustion_summary(_tbbo_minute_stats())

        self.assertIn("depth_exhaustion_bucket", summary.columns)
        self.assertIn("extreme", set(summary["depth_exhaustion_bucket"].astype(str)))
        self.assertIn("median_zero_impact_supported_trade_pct", summary.columns)

    def test_microstructure_cost_state_scores_minutes_as_execution_context(self) -> None:
        state = build_microstructure_cost_state(
            _tbbo_minute_stats(),
            aggressive_flow_minute_stats=_aggressive_flow_minute_stats(),
        )

        self.assertEqual(len(state), 4)
        self.assertIn("microstructure_cost_state", state.columns)
        self.assertTrue(state["microstructure_cost_score"].between(0.0, 1.0).all())

    def test_trade_sign_memory_diagnostics_emit_autocorr_and_summary(self) -> None:
        diagnostics = build_trade_sign_memory_diagnostics(_tbbo_minute_stats(), max_lag=2)

        self.assertEqual(set(diagnostics.autocorr["lag"]), {1, 2})
        self.assertIn("hurst_estimate", diagnostics.summary.columns)

    def test_price_change_buckets_track_flow_aligned_price_changes(self) -> None:
        buckets = build_price_change_buckets(_aggressive_flow_minute_stats(), tick_size=0.25)

        bid_up = buckets.loc[
            buckets["flow_pressure_bucket"].eq("bid_pressure")
            & buckets["price_change_bucket"].eq("up")
        ]
        self.assertFalse(bid_up.empty)
        self.assertGreater(float(bid_up["same_direction_price_change_pct"].iloc[0]), 0.0)

    def test_classify_price_changing_trades_when_event_rows_exist(self) -> None:
        trades = pd.DataFrame(
            {
                "ts_event": pd.date_range("2026-02-16 09:30", periods=3, freq="s"),
                "symbol": ["NQH6", "NQH6", "NQH6"],
                "side": ["B", "A", "B"],
                "mid_price": [100.00, 100.25, 100.25],
            }
        )

        out = classify_price_changing_trades(trades, tick_size=0.25)

        self.assertEqual(out.loc[0, "price_change_bucket"], "up")
        self.assertFalse(bool(out.loc[0, "adverse_to_aggressor"]))

    def test_signal_adverse_selection_aligns_future_mid_move_to_direction(self) -> None:
        signals = pd.DataFrame(
            {
                "time": ["2026-02-16 09:30:00", "2026-02-16 09:31:00"],
                "candidate_signal": [1.0, -1.0],
                "signal_active": [True, True],
                "direction": ["long", "short"],
                "setup_tag": ["trend_long", "mr_short"],
            }
        )

        diagnostics = build_signal_adverse_selection_diagnostics(
            signals,
            _tbbo_minute_stats(),
            aggressive_flow_minute_stats=_aggressive_flow_minute_stats(),
            horizons_minutes=[1],
        )

        self.assertEqual(len(diagnostics.events), 2)
        self.assertIn("temporary_overshoot_points", diagnostics.events.columns)
        self.assertIn("limit_wait_opportunity_cost_points", diagnostics.events.columns)
        self.assertIn("microstructure_cost_state", diagnostics.events.columns)
        self.assertIn("median_aggressive_flow_share", diagnostics.summary.columns)
        self.assertIn("median_limit_wait_opportunity_cost_points", diagnostics.summary.columns)
        self.assertIn("median_microstructure_cost_score", diagnostics.summary.columns)
        self.assertGreaterEqual(float(diagnostics.summary["signals"].sum()), 2.0)

    def test_write_microstructure_diagnostics_outputs_all_artifacts(self) -> None:
        diagnostics = build_microstructure_diagnostics(
            _tbbo_minute_stats(),
            aggressive_flow_minute_stats=_aggressive_flow_minute_stats(),
            signals=pd.DataFrame(
                {
                    "time": ["2026-02-16 09:30:00"],
                    "candidate_signal": [1.0],
                    "signal_active": [True],
                    "direction": ["long"],
                    "options_gamma_environment": ["pin_risk"],
                    "options_gex_regime": ["positive_gex"],
                }
            ),
            horizons_minutes=[1],
            max_autocorr_lag=2,
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_microstructure_diagnostics(diagnostics, Path(tmp), artifact_name="Test Diagnostics")

            self.assertTrue(paths.report_md.exists())
            self.assertTrue(paths.depth_exhaustion_summary_csv.exists())
            self.assertTrue(paths.microstructure_cost_state_summary_csv.exists())
            self.assertTrue(paths.book_imbalance_summary_csv.exists())
            self.assertTrue(paths.spread_reversion_csv.exists())
            self.assertTrue(paths.trade_sign_autocorr_csv.exists())
            self.assertTrue(paths.price_change_buckets_csv.exists())
            self.assertTrue(paths.signal_cost_state_summary_csv.exists())
            self.assertTrue(paths.signal_options_context_summary_csv.exists())
            self.assertIn("execution and data-quality audit", paths.report_md.read_text(encoding="utf-8"))
            self.assertIn("Composite Cost State", paths.report_md.read_text(encoding="utf-8"))
            self.assertFalse(diagnostics.signal_options_context_summary.empty)


if __name__ == "__main__":
    unittest.main()
