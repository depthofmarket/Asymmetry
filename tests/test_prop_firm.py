from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from backtest.prop_firm import (
    evaluate_prop_firm_path,
    export_prop_firm_report,
    _evaluate_funded_path,
    _simulate_eval_arrays,
    _simulate_funded_arrays,
    _normalize_profile,
    _sample_eval_equity_paths,
    _daily_paths_from_trades,
    _trade_path_work_frame,
    _coerce_daily_paths,
)


class PropFirmAnalyticsTests(unittest.TestCase):
    def test_path_passes_after_profit_target(self) -> None:
        result = evaluate_prop_firm_path(
            [100.0, 100.0, 100.0],
            {
                "account_size": 50_000,
                "profit_target": 250,
                "max_drawdown": 2_500,
                "daily_loss_limit": 1_200,
                "min_trading_days": 1,
                "max_trading_days": 5,
            },
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["reason"], "profit_target")
        self.assertEqual(result["days"], 3)

    def test_path_min_trading_days_count_active_trade_days(self) -> None:
        result = evaluate_prop_firm_path(
            pd.DataFrame(
                [
                    {"net_pnl": 300.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 300.0, "trade_count": 1},
                    {"net_pnl": 0.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 0.0, "trade_count": 0},
                    {"net_pnl": 0.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 0.0, "trade_count": 0},
                ]
            ),
            {
                "account_size": 50_000,
                "profit_target": 250,
                "max_drawdown": 2_500,
                "daily_loss_limit": 1_200,
                "min_trading_days": 2,
                "max_trading_days": 3,
            },
        )

        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["days"], 3)
        self.assertEqual(result["trading_days"], 1)

    def test_daily_loss_uses_intraday_path_not_just_day_close(self) -> None:
        result = evaluate_prop_firm_path(
            pd.DataFrame(
                [
                    {
                        "net_pnl": 200.0,
                        "min_intraday_pnl": -600.0,
                        "max_intraday_pnl": 300.0,
                        "trade_count": 2,
                    }
                ]
            ),
            {
                "account_size": 50_000,
                "profit_target": 3_000,
                "max_drawdown": 2_500,
                "daily_loss_limit": 500,
                "min_trading_days": 1,
                "max_trading_days": 5,
            },
        )

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["reason"], "daily_loss_limit")

    def test_consistency_rule_can_delay_pass(self) -> None:
        result = evaluate_prop_firm_path(
            [1_000.0, 1_000.0, 500.0],
            {
                "account_size": 100_000,
                "profit_target": 2_000,
                "max_drawdown": 1_000,
                "daily_loss_limit": 0,
                "min_trading_days": 3,
                "max_trading_days": 5,
                "consistency_profit_limit_pct": 40,
                "drawdown_mode": "eod_trailing",
                "drawdown_check": "eod",
            },
        )

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["days"], 3)
        self.assertEqual(float(result["best_day_pct_of_total_profit"]), 40.0)

    def test_extension_threshold_can_end_eval_at_first_deadline(self) -> None:
        result = evaluate_prop_firm_path(
            [40.0, 40.0, 500.0],
            {
                "account_size": 100_000,
                "profit_target": 2_000,
                "max_drawdown": 1_000,
                "daily_loss_limit": 0,
                "min_trading_days": 1,
                "initial_max_trading_days": 2,
                "extension_trading_days": 2,
                "extension_threshold": 100,
                "drawdown_mode": "eod_trailing",
                "drawdown_check": "eod",
            },
        )

        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["reason"], "extension_threshold_not_met")
        self.assertEqual(result["days"], 2)

    def test_export_writes_summary_simulations_and_report(self) -> None:
        trades = pd.DataFrame(
            [
                {
                    "exit_time": pd.Timestamp("2024-01-02 10:00") + pd.Timedelta(days=day),
                    "pnl": 1_000.0,
                }
                for day in range(5)
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = export_prop_firm_report(
                trades,
                out_dir=Path(tmp),
                artifact_name="prop",
                profiles=[
                    {
                        "name": "unit_eval",
                        "account_size": 50_000,
                        "profit_target": 2_000,
                        "max_drawdown": 5_000,
                        "daily_loss_limit": 5_000,
                        "min_trading_days": 2,
                        "max_trading_days": 4,
                    }
                ],
                n_sims=25,
                seed=3,
            )

            self.assertTrue(paths.summary_csv.exists())
            self.assertTrue(paths.simulations_csv.exists())
            self.assertTrue(paths.funded_simulations_csv.exists())
            self.assertTrue(paths.risk_geometry_surface_csv.exists())
            self.assertTrue(paths.sizing_surface_csv.exists())
            self.assertTrue(paths.daily_rules_surface_csv.exists())
            self.assertTrue(paths.trade_geometry_csv.exists())
            self.assertTrue(paths.strategy_metrics_csv.exists())
            self.assertTrue(paths.random_walk_csv.exists())
            self.assertTrue(paths.random_walk_samples_csv.exists())
            self.assertTrue(paths.attempt_curve_csv.exists())
            self.assertTrue(paths.dashboard_png.exists())
            self.assertTrue(paths.overview_png.exists())
            self.assertTrue(paths.strategy_equity_png.exists())
            self.assertTrue(paths.monte_carlo_png.exists())
            self.assertTrue(paths.random_walk_png.exists())
            self.assertTrue(paths.payout_analysis_png.exists())
            self.assertTrue(paths.risk_geometry_png.exists())
            self.assertTrue(paths.sizing_png.exists())
            self.assertTrue(paths.daily_rules_png.exists())
            self.assertTrue(paths.trade_geometry_png.exists())
            self.assertTrue(paths.funded_payout_png.exists())
            self.assertTrue(paths.report_md.exists())

            summary = pd.read_csv(paths.summary_csv)
            self.assertEqual(summary.loc[0, "profile"], "unit_eval")
            self.assertEqual(summary.loc[0, "sample_scope"], "development_in_sample")
            self.assertEqual(summary.loc[0, "evidence_grade"], "research_only")
            self.assertEqual(summary.loc[0, "optimism_warning"], "in_sample_bootstrap_not_approval_evidence")
            self.assertEqual(float(summary.loc[0, "pass_probability_pct"]), 100.0)
            self.assertEqual(float(summary.loc[0, "median_days_to_pass"]), 2.0)
            self.assertEqual(float(summary.loc[0, "median_trading_days_to_pass"]), 2.0)
            self.assertEqual(int(summary.loc[0, "calendar_history_days"]), 5)
            self.assertEqual(int(summary.loc[0, "active_history_days"]), 5)
            report_text = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("Prop Firm Evaluation Report", report_text)
            self.assertIn("in-sample development bootstrap", report_text)
            self.assertIn("calendar-day paths", report_text)

    def test_prop_eval_samples_calendar_days_after_first_trade_not_active_days_only(self) -> None:
        trades = pd.DataFrame(
            [
                {"exit_time": pd.Timestamp("2024-01-02 10:00"), "pnl": 1_000.0},
                {"exit_time": pd.Timestamp("2024-01-12 10:00"), "pnl": 1_000.0},
            ]
        )
        daily_paths = _daily_paths_from_trades(trades)
        self.assertEqual(len(daily_paths), 11)
        self.assertEqual(int((daily_paths["trade_count"] > 0).sum()), 2)
        self.assertEqual(float(daily_paths["net_pnl"].sum()), 2_000.0)

        with tempfile.TemporaryDirectory() as tmp:
            paths = export_prop_firm_report(
                trades,
                out_dir=Path(tmp),
                artifact_name="sparse_prop",
                profiles=[
                    {
                        "name": "sparse_eval",
                        "account_size": 50_000,
                        "profit_target": 2_000,
                        "max_drawdown": 5_000,
                        "daily_loss_limit": 5_000,
                        "min_trading_days": 1,
                        "max_trading_days": 5,
                        "enable_surfaces": False,
                    }
                ],
                n_sims=20,
                seed=3,
                enable_surfaces=False,
            )

            summary = pd.read_csv(paths.summary_csv)
            self.assertEqual(float(summary.loc[0, "pass_probability_pct"]), 0.0)
            self.assertEqual(int(summary.loc[0, "calendar_history_days"]), 11)
            self.assertEqual(int(summary.loc[0, "active_history_days"]), 2)
            report_text = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("No-Pass State", report_text)
            self.assertIn("produced no passing eval simulations", report_text)

    def test_walkforward_export_marks_validation_scope(self) -> None:
        trades = pd.DataFrame(
            [
                {
                    "exit_time": pd.Timestamp("2024-01-02 10:00") + pd.Timedelta(days=day),
                    "pnl": 250.0,
                }
                for day in range(4)
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = export_prop_firm_report(
                trades,
                out_dir=Path(tmp),
                artifact_name="wf_prop",
                sample_scope="walkforward_oos",
                profiles=[
                    {
                        "name": "wf_eval",
                        "account_size": 50_000,
                        "profit_target": 500,
                        "max_drawdown": 5_000,
                        "daily_loss_limit": 5_000,
                        "min_trading_days": 2,
                        "max_trading_days": 4,
                    }
                ],
                n_sims=10,
                seed=3,
                enable_surfaces=False,
            )

            summary = pd.read_csv(paths.summary_csv)

            self.assertEqual(summary.loc[0, "sample_scope"], "walkforward_oos")
            self.assertEqual(summary.loc[0, "evidence_grade"], "validation_candidate")
            self.assertTrue(pd.isna(summary.loc[0, "optimism_warning"]) or summary.loc[0, "optimism_warning"] == "")

    def test_export_uses_trade_mae_for_daily_loss(self) -> None:
        trades = pd.DataFrame(
            [
                {
                    "exit_time": pd.Timestamp("2024-01-02 10:00"),
                    "pnl": 200.0,
                    "mae_dollars": 600.0,
                    "mfe_dollars": 300.0,
                }
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = export_prop_firm_report(
                trades,
                out_dir=Path(tmp),
                artifact_name="prop",
                profiles=[
                    {
                        "name": "mae_eval",
                        "account_size": 50_000,
                        "profit_target": 2_000,
                        "max_drawdown": 5_000,
                        "daily_loss_limit": 500,
                        "min_trading_days": 1,
                        "max_trading_days": 3,
                    }
                ],
                n_sims=5,
                seed=3,
            )

            summary = pd.read_csv(paths.summary_csv)
            self.assertEqual(float(summary.loc[0, "daily_loss_fail_probability_pct"]), 100.0)

    def test_export_includes_eval_cost_and_payout_metrics(self) -> None:
        trades = pd.DataFrame(
            [
                {
                    "exit_time": pd.Timestamp("2024-01-02 10:00") + pd.Timedelta(days=day),
                    "pnl": 1_000.0,
                }
                for day in range(5)
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = export_prop_firm_report(
                trades,
                out_dir=Path(tmp),
                artifact_name="prop",
                profiles=[
                    {
                        "name": "payout_eval",
                        "account_size": 100_000,
                        "eval_cost": 42,
                        "profit_target": 2_000,
                        "max_drawdown": 5_000,
                        "daily_loss_limit": 0,
                        "min_trading_days": 2,
                        "max_trading_days": 4,
                        "profit_split_pct": 80,
                        "funded_buffer_target": 1_000,
                        "minimum_payout": 200,
                        "funded_horizon_days": 3,
                    }
                ],
                n_sims=25,
                seed=3,
            )

            summary = pd.read_csv(paths.summary_csv)
            self.assertEqual(float(summary.loc[0, "expected_eval_cost_to_pass"]), 42.0)
            self.assertEqual(float(summary.loc[0, "first_payout_probability_pct"]), 100.0)
            self.assertEqual(float(summary.loc[0, "avg_gross_payout"]), 2_000.0)
            self.assertEqual(float(summary.loc[0, "avg_net_payout_after_split"]), 1_600.0)
            self.assertEqual(float(summary.loc[0, "avg_net_payout_when_positive"]), 1_600.0)
            self.assertAlmostEqual(float(summary.loc[0, "break_even_eval_to_first_payout_probability_pct"]), 2.625)
            self.assertAlmostEqual(float(summary.loc[0, "payoff_ratio_to_all_in_cost"]), 1600.0 / 42.0)
            self.assertEqual(float(summary.loc[0, "expected_net_payout_per_eval_attempt"]), 1_558.0)

    def test_export_includes_all_in_prop_costs_and_sample_warning(self) -> None:
        trades = pd.DataFrame(
            [
                {
                    "exit_time": pd.Timestamp("2024-01-02 10:00") + pd.Timedelta(days=day),
                    "pnl": 1_000.0,
                }
                for day in range(3)
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = export_prop_firm_report(
                trades,
                out_dir=Path(tmp),
                artifact_name="prop",
                profiles=[
                    {
                        "name": "all_in_eval",
                        "account_size": 100_000,
                        "eval_cost": 50,
                        "activation_fee": 100,
                        "monthly_fee": 10,
                        "profit_target": 1_000,
                        "max_drawdown": 5_000,
                        "daily_loss_limit": 0,
                        "min_trading_days": 1,
                        "max_trading_days": 3,
                        "profit_split_pct": 100,
                        "funded_buffer_target": 500,
                        "minimum_payout": 100,
                        "funded_horizon_days": 1,
                        "minimum_trade_sample": 10,
                        "portfolio_account_counts": "1,5",
                    }
                ],
                n_sims=10,
                seed=3,
                enable_surfaces=False,
            )

            summary = pd.read_csv(paths.summary_csv)
            self.assertEqual(float(summary.loc[0, "expected_eval_cost_to_pass"]), 50.0)
            self.assertEqual(float(summary.loc[0, "expected_all_in_cost_to_pass"]), 160.0)
            self.assertEqual(float(summary.loc[0, "expected_all_in_cost_per_eval_attempt"]), 160.0)
            self.assertEqual(float(summary.loc[0, "avg_net_payout_after_split"]), 500.0)
            self.assertEqual(float(summary.loc[0, "avg_net_payout_when_positive"]), 500.0)
            self.assertEqual(float(summary.loc[0, "break_even_eval_to_first_payout_probability_pct"]), 32.0)
            self.assertEqual(float(summary.loc[0, "expected_net_payout_per_eval_attempt"]), 340.0)
            self.assertEqual(int(summary.loc[0, "trade_sample_size"]), 3)
            self.assertEqual(int(summary.loc[0, "minimum_trade_sample"]), 10)
            self.assertEqual(summary.loc[0, "sample_size_warning"], "sample_below_minimum_10_trades")
            self.assertEqual(summary.loc[0, "portfolio_account_counts"], "1,5")

    def test_funded_payout_cap_and_cadence_limit_withdrawals(self) -> None:
        result = _evaluate_funded_path(
            [1_000.0, 1_000.0, 1_000.0],
            {
                "account_size": 50_000,
                "max_drawdown": 5_000,
                "daily_loss_limit": 0,
                "funded_buffer_target": 0,
                "minimum_payout": 100,
                "profit_split_pct": 100,
                "funded_horizon_days": 3,
                "payout_cap": 500,
                "payout_cadence_days": 2,
            },
        )

        self.assertEqual(float(result["gross_payout"]), 500.0)
        self.assertEqual(float(result["net_payout"]), 500.0)
        self.assertEqual(int(result["payout_count"]), 1)
        self.assertEqual(float(result["first_payout_day"]), 2.0)
    def test_lucid_flex_25k_eval_consistency_and_lock_floor(self) -> None:
        from config.backtest_config import RESEARCH_CONFIG
        profiles = {p["name"]: p for p in RESEARCH_CONFIG["prop_firm_profiles"]}
        self.assertIn("lucid_flex_25k", profiles)
        profile = profiles["lucid_flex_25k"]

        # Test 1: 40% consistency blocks 2-day pass when best day is > 40% of target
        # Target is 1,250. Day 1: 700 (56% of 1,250), Day 2: 550.
        blocked = evaluate_prop_firm_path([700.0, 550.0], profile)
        self.assertEqual(blocked["status"], "timeout")
        self.assertEqual(blocked["reason"], "consistency_pending")

        # Test 2: 3-day pass with no day > 40% (450 <= 500)
        passed = evaluate_prop_firm_path([450.0, 400.0, 400.0], profile)
        self.assertEqual(passed["status"], "pass")
        self.assertEqual(passed["days"], 3)

        # Test 3: Trailing floor locks at 25,100 once balance reaches 26,100+
        df_lock = pd.DataFrame([
            {"net_pnl": 1500.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 1500.0, "trade_count": 1},
            {"net_pnl": -100.0, "min_intraday_pnl": -100.0, "max_intraday_pnl": 0.0, "trade_count": 1},
        ])
        res = evaluate_prop_firm_path(df_lock, profile)
        # Equity was 26,500 on day 1 -> floor without cap would be 25,500, but capped at 25,100!
        self.assertEqual(float(res["drawdown_floor"]), 25_100.0)

    def test_lucid_flex_25k_funded_payout_qualifying_days_and_mll_lock(self) -> None:
        from config.backtest_config import RESEARCH_CONFIG
        profiles = {p["name"]: p for p in RESEARCH_CONFIG["prop_firm_profiles"]}
        profile = profiles["lucid_flex_25k"]

        # 5 days of +$200 = +$1,000 profit (equity = $26,000). All 5 days meet >= $100.
        # Cycle profit = $1,000. 50% payout = $500. 90/10 split = $450 net payout.
        # Remaining equity = $25,500. MLL locks at $25,100.
        five_days = pd.DataFrame([
            {"net_pnl": 200.0, "min_intraday_pnl": -50.0, "max_intraday_pnl": 250.0, "trade_count": 1}
            for _ in range(5)
        ])
        result = _evaluate_funded_path(five_days, profile)
        self.assertEqual(int(result["payout_count"]), 1)
        self.assertEqual(float(result["gross_payout"]), 500.0)
        self.assertEqual(float(result["net_payout"]), 450.0)
        self.assertEqual(float(result["final_equity"]), 25_500.0)
        self.assertEqual(float(result["drawdown_floor"]), 25_100.0)

        # If only 4 days meet >= $100 (e.g. day 5 made +$50), payout is not eligible yet
        four_days = pd.DataFrame([
            {"net_pnl": 250.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 250.0, "trade_count": 1},
            {"net_pnl": 250.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 250.0, "trade_count": 1},
            {"net_pnl": 250.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 250.0, "trade_count": 1},
            {"net_pnl": 250.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 250.0, "trade_count": 1},
            {"net_pnl": 50.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 50.0, "trade_count": 1},
        ])
        result_no_pay = _evaluate_funded_path(four_days, profile)
        self.assertEqual(int(result_no_pay["payout_count"]), 0)
        self.assertEqual(float(result_no_pay["gross_payout"]), 0.0)

    def test_export_includes_surface_rows(self) -> None:
        trades = pd.DataFrame(
            [
                {
                    "exit_time": pd.Timestamp("2024-01-02 10:00") + pd.Timedelta(days=day),
                    "direction": "long",
                    "signal_type": "trend",
                    "setup_tag": "trend_long",
                    "pnl": 500.0 if day % 2 == 0 else -200.0,
                    "mae_dollars": 200.0,
                    "mfe_dollars": 500.0,
                }
                for day in range(12)
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = export_prop_firm_report(
                trades,
                out_dir=Path(tmp),
                artifact_name="prop",
                profiles=[
                    {
                        "name": "surface_eval",
                        "account_size": 100_000,
                        "eval_cost": 42,
                        "profit_target": 1_000,
                        "max_drawdown": 1_000,
                        "daily_loss_limit": 0,
                        "min_trading_days": 2,
                        "max_trading_days": 10,
                        "profit_split_pct": 80,
                        "funded_buffer_target": 500,
                        "minimum_payout": 100,
                        "funded_horizon_days": 10,
                        "surface_n_sims": 20,
                        "sizing_multipliers": [0.5, 1.0],
                        "daily_loss_stops": [0, 250],
                        "daily_profit_locks": [0, 500],
                        "risk_geometry_reward_risk": [0.5, 1.0],
                        "risk_geometry_drawdown_risk_fracs": [0.2],
                    }
                ],
                n_sims=20,
                surface_n_sims=20,
                seed=5,
            )

            risk_surface = pd.read_csv(paths.risk_geometry_surface_csv)
            sizing_surface = pd.read_csv(paths.sizing_surface_csv)
            daily_surface = pd.read_csv(paths.daily_rules_surface_csv)
            trade_geometry = pd.read_csv(paths.trade_geometry_csv)

            self.assertFalse(risk_surface.empty)
            self.assertFalse(sizing_surface.empty)
            self.assertFalse(daily_surface.empty)
            self.assertFalse(trade_geometry.empty)
            self.assertIn("pass_probability_pct", risk_surface.columns)
            self.assertIn("tested_pnl_multiplier", sizing_surface.columns)
            self.assertIn("daily_loss_stop", daily_surface.columns)
            self.assertIn("reward_risk", trade_geometry.columns)
            self.assertTrue(paths.risk_geometry_png.exists())
            self.assertTrue(paths.daily_rules_png.exists())
            self.assertTrue(paths.funded_payout_png.exists())

    def test_sample_eval_equity_paths_do_not_pass_on_calendar_wait_only(self) -> None:
        daily_paths = pd.DataFrame(
            [
                {"net_pnl": 300.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 300.0, "trade_count": 1},
                {"net_pnl": 0.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 0.0, "trade_count": 0},
                {"net_pnl": 0.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 0.0, "trade_count": 0},
            ]
        )

        paths = _sample_eval_equity_paths(
            daily_paths,
            {
                "name": "chart_eval",
                "account_size": 50_000,
                "profit_target": 250,
                "max_drawdown": 2_500,
                "daily_loss_limit": 1_200,
                "min_trading_days": 2,
                "max_trading_days": 3,
            },
            n_paths=1,
            seed=1,
        )

        self.assertNotIn("pass", set(paths["status"]))


class PropFirmVectorizedSimulationTests(unittest.TestCase):
    """Tests for the vectorized numpy simulation functions."""

    def setUp(self):
        self.rng = np.random.default_rng(42)
        self.base_profile = _normalize_profile({
            "name": "test",
            "account_size": 50_000,
            "profit_target": 3_000,
            "max_drawdown": 2_500,
            "daily_loss_limit": 1_200,
            "min_trading_days": 5,
            "max_trading_days": 30,
        })

    def _make_arrays(self, days: int, n_sims: int = 100) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Utility to create sample daily arrays centered on zero."""
        net = self.rng.normal(100, 200, size=(n_sims, days))
        low = np.minimum(net, self.rng.normal(-50, 100, size=(n_sims, days)))
        high = np.maximum(net, self.rng.normal(50, 100, size=(n_sims, days)))
        return net, low, high

    def test_simulate_eval_all_pass_on_large_profit(self):
        """If every day is a huge gain, all sims should pass quickly."""
        n_sims, days = 10, 30
        net = np.full((n_sims, days), 2_000.0)
        low = np.full((n_sims, days), -500.0)
        high = np.full((n_sims, days), 2_500.0)

        result = _simulate_eval_arrays(net, low, high, self.base_profile)
        self.assertEqual(len(result), n_sims)
        self.assertTrue((result["status"] == "pass").all())
        # Should pass at min_trading_days (5) since profit target hit
        self.assertTrue((result["days"] == 5).all())
        self.assertTrue((result["reason"] == "profit_target").all())

    def test_simulate_eval_all_fail_on_daily_loss(self):
        """If every day hits the daily loss limit, all sims fail."""
        n_sims, days = 10, 30
        net = np.full((n_sims, days), 200.0)
        low = np.full((n_sims, days), -1_500.0)  # exceeds daily_loss_limit of 1,200
        high = np.full((n_sims, days), 300.0)

        result = _simulate_eval_arrays(net, low, high, self.base_profile)
        self.assertEqual(len(result), n_sims)
        self.assertTrue((result["status"] == "fail").all())
        self.assertTrue((result["reason"] == "daily_loss_limit").all())
        self.assertTrue((result["days"] == 1).all())

    def test_simulate_eval_all_timeout_on_zero_pnl(self):
        """Zero P&L across all days should timeout."""
        n_sims, days = 10, 30
        net = np.zeros((n_sims, days))
        low = np.zeros((n_sims, days))
        high = np.zeros((n_sims, days))

        result = _simulate_eval_arrays(net, low, high, self.base_profile)
        self.assertEqual(len(result), n_sims)
        self.assertTrue((result["status"] == "timeout").all())
        self.assertTrue((result["reason"] == "max_days_elapsed").all())

    def test_simulate_eval_drawdown_fail(self):
        """Large negative day that hits max drawdown without hitting daily loss."""
        profile = _normalize_profile({
            "name": "test",
            "account_size": 50_000,
            "profit_target": 10_000,
            "max_drawdown": 2_500,
            "daily_loss_limit": 5_000,
            "min_trading_days": 1,
            "max_trading_days": 30,
        })
        n_sims, days = 10, 30
        # Day 1: -2,000 PnL with -2,600 intraday low → exceeds max_drawdown (2,500)
        net = np.zeros((n_sims, days))
        low = np.zeros((n_sims, days))
        net[:, 0] = -2_000.0
        low[:, 0] = -3_000.0  # equity drops to 47,000, below 47,500 floor
        high = np.zeros((n_sims, days))

        result = _simulate_eval_arrays(net, low, high, profile)
        self.assertTrue((result["status"] == "fail").all())
        self.assertTrue((result["reason"] == "max_drawdown").all())

    def test_simulate_funded_survives_if_no_drawdown(self):
        """Funded sim with steady profit should survive and pay out."""
        profile = _normalize_profile({
            "name": "test_funded",
            "account_size": 50_000,
            "max_drawdown": 2_500,
            "daily_loss_limit": 1_200,
            "profit_split_pct": 80,
            "funded_buffer_target": 1_000,
            "minimum_payout": 200,
            "funded_horizon_days": 10,
        })
        n_sims, days = 10, 10
        # Each day gains $500 → reaches payout floor quickly
        net = np.full((n_sims, days), 500.0)
        low = np.full((n_sims, days), -100.0)
        high = np.full((n_sims, days), 600.0)

        result = _simulate_funded_arrays(net, low, high, profile)
        self.assertTrue((result["status"] == "survived").all())
        # Should have at least one payout since equity exceeds 51,000
        self.assertTrue((result["payout_count"] >= 1).all())

    def test_simulate_funded_fails_on_daily_loss(self):
        """Funded sim with daily loss should fail."""
        profile = _normalize_profile({
            "name": "test_funded_dl",
            "account_size": 50_000,
            "max_drawdown": 5_000,
            "daily_loss_limit": 1_200,
            "profit_split_pct": 80,
            "funded_buffer_target": 1_000,
            "minimum_payout": 200,
            "funded_horizon_days": 10,
        })
        n_sims, days = 10, 10
        net = np.full((n_sims, days), -100.0)
        low = np.full((n_sims, days), -1_500.0)  # exceeds daily_loss_limit
        high = np.full((n_sims, days), 50.0)

        result = _simulate_funded_arrays(net, low, high, profile)
        self.assertTrue((result["status"] == "fail").all())
        self.assertTrue((result["reason"] == "daily_loss_limit").all())

    def test_simulate_eval_handles_empty_output(self):
        """Empty array should produce valid output without crashing."""
        net = np.zeros((10, 0))
        low = np.zeros((10, 0))
        high = np.zeros((10, 0))

        result = _simulate_eval_arrays(net, low, high, self.base_profile)
        self.assertEqual(len(result), 10)
        self.assertTrue((result["status"] == "timeout").all())

    def test_simulate_funded_handles_empty_output(self):
        """Empty funded array should not crash."""
        profile = _normalize_profile({
            "name": "test_funded_empty",
            "account_size": 50_000,
            "max_drawdown": 2_500,
            "funded_horizon_days": 10,
        })
        net = np.zeros((10, 0))
        low = np.zeros((10, 0))
        high = np.zeros((10, 0))

        result = _simulate_funded_arrays(net, low, high, profile)
        self.assertEqual(len(result), 10)
        self.assertTrue((result["status"] == "survived").all())

    def test_normalize_profile_canonicalizes_drawdown_mode(self):
        """All drawdown mode variants should map to canonical values."""
        for variant in ("trailing", "trailing_eod", "eod_trailing_lock_at_initial", "eod_lock"):
            profile = _normalize_profile({"drawdown_mode": variant})
            self.assertEqual(profile["drawdown_mode"], "eod_trailing",
                             f"{variant} should normalize to eod_trailing")

        static_profile = _normalize_profile({"drawdown_mode": "static"})
        self.assertEqual(static_profile["drawdown_mode"], "static")


if __name__ == "__main__":
    unittest.main()
