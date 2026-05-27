from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.live import PaperTradingEvent
from backtest.live_prop_rules import LivePropRuleConfig, LivePropRuleGuard, validate_prop_research_gate
from backtest.prop_volatility import PROP_VOLATILITY_NOT_LIVE_EDGE_NOTE, PropVolatilityControlConfig


def _profile(**overrides):
    profile = {
        "name": "test_eval",
        "account_size": 100_000,
        "profit_target": 500,
        "max_drawdown": 1_000,
        "daily_loss_limit": 300,
        "min_trading_days": 1,
        "max_trading_days": 10,
        "drawdown_mode": "eod_trailing",
        "drawdown_check": "eod",
        "trailing_drawdown_cap_at_initial": True,
        "consistency_profit_limit_pct": 0,
        "pnl_multiplier": 0.5,
        "eval_cost": 42,
        "profit_split_pct": 80,
        "funded_buffer_target": 1_000,
        "minimum_payout": 200,
    }
    profile.update(overrides)
    return profile


class LivePropRuleGuardTests(unittest.TestCase):
    def test_eval_guard_locks_after_target_and_exports_ledger(self) -> None:
        guard = LivePropRuleGuard(
            LivePropRuleConfig(
                profile=_profile(),
                candidate="edge_vp_mr_trend_failed_auction_quality_probe",
                phase="eval",
            )
        )
        entry = PaperTradingEvent(
            event_type="entry_filled",
            timestamp=pd.Timestamp("2024-01-03 10:05"),
            message="entry",
            direction="long",
            setup_tag="trend_long",
            price=100.0,
            contracts=1,
        )

        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:05"),
            equity=100_000,
            daily_pnl=0,
            has_open_position=False,
        )
        guard.record_event(entry, equity=100_000)
        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:10"),
            equity=100_650,
            daily_pnl=650,
            has_open_position=True,
        )

        self.assertEqual(guard.status, "pass")
        self.assertEqual(guard.exit_reason(has_open_position=True), "prop_eval_complete")
        self.assertEqual(guard.entry_block_reason().reason, "prop_eval_complete")
        ledger = guard.ledger_frame()
        self.assertIn("eval_cost", ledger.columns)
        self.assertIn("drawdown_floor", ledger.columns)
        self.assertEqual(ledger.iloc[-1]["status"], "pass")

    def test_eval_min_trading_days_count_active_trade_days_not_calendar_days(self) -> None:
        guard = LivePropRuleGuard(
            LivePropRuleConfig(
                profile=_profile(min_trading_days=2, max_trading_days=10),
                candidate="candidate",
                phase="eval",
            )
        )

        guard.record_event(
            PaperTradingEvent(
                event_type="entry_filled",
                timestamp=pd.Timestamp("2024-01-03 10:05"),
                message="entry",
                direction="long",
                contracts=1,
            ),
            equity=100_000,
        )
        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:10"),
            equity=100_650,
            daily_pnl=650,
            has_open_position=False,
        )
        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-04 10:10"),
            equity=100_650,
            daily_pnl=0,
            has_open_position=False,
        )

        self.assertEqual(guard.status, "active")
        self.assertEqual(guard.day_count, 2)
        self.assertEqual(guard.trading_day_count, 1)

        guard.record_event(
            PaperTradingEvent(
                event_type="entry_filled",
                timestamp=pd.Timestamp("2024-01-05 10:05"),
                message="entry",
                direction="long",
                contracts=1,
            ),
            equity=100_650,
        )

        self.assertEqual(guard.status, "pass")
        self.assertEqual(guard.day_count, 3)
        self.assertEqual(guard.trading_day_count, 2)

    def test_eval_max_days_count_calendar_days_after_first_trade(self) -> None:
        guard = LivePropRuleGuard(
            LivePropRuleConfig(
                profile=_profile(profit_target=2_000, max_trading_days=2),
                candidate="candidate",
                phase="eval",
            )
        )

        guard.record_event(
            PaperTradingEvent(
                event_type="entry_filled",
                timestamp=pd.Timestamp("2024-01-03 10:05"),
                message="entry",
                direction="long",
                contracts=1,
            ),
            equity=100_000,
        )
        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:10"),
            equity=100_100,
            daily_pnl=100,
            has_open_position=False,
        )
        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-04 10:10"),
            equity=100_100,
            daily_pnl=0,
            has_open_position=False,
        )
        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-05 10:10"),
            equity=100_100,
            daily_pnl=0,
            has_open_position=False,
        )

        self.assertEqual(guard.status, "timeout")
        self.assertEqual(guard.kill_reason, "max_days_elapsed")
        self.assertEqual(guard.day_count, 3)
        self.assertEqual(guard.trading_day_count, 1)

    def test_daily_profit_lock_blocks_entries_before_eval_pass(self) -> None:
        guard = LivePropRuleGuard(
            LivePropRuleConfig(
                profile=_profile(profit_target=2_000),
                candidate="candidate",
                phase="eval",
                daily_profit_lock=250,
            )
        )
        guard.record_event(
            PaperTradingEvent(
                event_type="entry_filled",
                timestamp=pd.Timestamp("2024-01-03 10:05"),
                message="entry",
                direction="long",
                contracts=1,
            ),
            equity=100_000,
        )
        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:10"),
            equity=100_300,
            daily_pnl=300,
            has_open_position=False,
        )

        decision = guard.entry_block_reason()

        self.assertIsNotNone(decision)
        self.assertEqual(decision.reason, "prop_daily_profit_lock")

    def test_funded_guard_locks_when_payout_is_available(self) -> None:
        guard = LivePropRuleGuard(
            LivePropRuleConfig(
                profile=_profile(funded_buffer_target=1_000, minimum_payout=200),
                candidate="candidate",
                phase="funded",
            )
        )
        guard.record_event(
            PaperTradingEvent(
                event_type="entry_filled",
                timestamp=pd.Timestamp("2024-01-03 10:05"),
                message="entry",
                direction="long",
                contracts=1,
            ),
            equity=100_000,
        )
        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:10"),
            equity=101_250,
            daily_pnl=1_250,
            has_open_position=True,
        )

        self.assertEqual(guard.status, "payout_ready")
        self.assertEqual(guard.exit_reason(has_open_position=True), "prop_payout_lockout")
        self.assertTrue(guard.snapshot()["payout_eligible"])

    def test_volatility_opportunity_day_sets_adjusted_trade_budget_without_blocking(self) -> None:
        guard = LivePropRuleGuard(
            LivePropRuleConfig(
                profile=_profile(),
                candidate="candidate",
                phase="eval",
                volatility_control=PropVolatilityControlConfig(
                    enabled=True,
                    normal_max_trades_per_day=1,
                    high_vol_opportunity_max_trades_per_day=2,
                ),
            )
        )

        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:05"),
            equity=100_100,
            daily_pnl=100,
            has_open_position=False,
            volatility_context={"realized_vol_ratio": 1.5, "volatility_state": "expanded_volatility_context"},
        )

        self.assertEqual(guard.prop_volatility_state, "high_vol_opportunity_day")
        self.assertEqual(guard.prop_volatility_adjusted_max_trades, 2)
        self.assertIsNone(guard.entry_block_reason())
        snapshot = guard.snapshot()
        self.assertEqual(snapshot["prop_volatility_not_live_edge"], PROP_VOLATILITY_NOT_LIVE_EDGE_NOTE)

    def test_volatility_kill_switch_blocks_entries_and_forces_exit(self) -> None:
        guard = LivePropRuleGuard(
            LivePropRuleConfig(
                profile=_profile(),
                candidate="candidate",
                phase="eval",
                volatility_control=PropVolatilityControlConfig(enabled=True, post_shock_cooldown_bars=2),
            )
        )

        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:05"),
            equity=100_000,
            daily_pnl=0,
            has_open_position=True,
            volatility_context={"volatility_jump_event": True, "volatility_state": "jump_volatility_context"},
        )

        self.assertEqual(guard.prop_volatility_state, "high_vol_kill_switch_day")
        self.assertEqual(guard.entry_block_reason().reason, "prop_volatility_kill_switch")
        self.assertEqual(guard.exit_reason(has_open_position=True), "prop_volatility_kill_switch")
        self.assertEqual(guard.prop_volatility_cooldown_bars_remaining, 2)

    def test_post_shock_cooldown_blocks_next_entries_without_flattening(self) -> None:
        guard = LivePropRuleGuard(
            LivePropRuleConfig(
                profile=_profile(),
                candidate="candidate",
                phase="eval",
                volatility_control=PropVolatilityControlConfig(enabled=True, post_shock_cooldown_bars=2),
            )
        )
        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:05"),
            equity=100_000,
            daily_pnl=0,
            has_open_position=False,
            volatility_context={"volatility_jump_event": True},
        )

        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:06"),
            equity=100_000,
            daily_pnl=0,
            has_open_position=False,
            volatility_context={"realized_vol_ratio": 1.0},
        )

        self.assertEqual(guard.prop_volatility_state, "post_shock_cooldown")
        self.assertEqual(guard.prop_volatility_cooldown_bars_remaining, 1)
        self.assertEqual(guard.entry_block_reason().reason, "prop_volatility_cooldown")
        self.assertIsNone(guard.exit_reason(has_open_position=True))

    def test_volatility_adjusted_max_trades_uses_daily_entry_count(self) -> None:
        guard = LivePropRuleGuard(
            LivePropRuleConfig(
                profile=_profile(),
                candidate="candidate",
                phase="eval",
                volatility_control=PropVolatilityControlConfig(
                    enabled=True,
                    normal_max_trades_per_day=1,
                ),
            )
        )
        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:05"),
            equity=100_000,
            daily_pnl=0,
            has_open_position=False,
            volatility_context={"realized_vol_ratio": 1.0},
        )
        guard.record_event(
            PaperTradingEvent(
                event_type="entry_filled",
                timestamp=pd.Timestamp("2024-01-03 10:05"),
                message="entry",
                direction="long",
                contracts=1,
            ),
            equity=100_000,
        )
        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:06"),
            equity=100_000,
            daily_pnl=0,
            has_open_position=False,
            volatility_context={"realized_vol_ratio": 1.0},
        )

        self.assertEqual(guard.daily_entry_count, 1)
        self.assertTrue(guard.prop_volatility_max_trades_reached)
        self.assertEqual(guard.entry_block_reason().reason, "prop_volatility_max_trades")

    def test_volatility_guard_state_persists_cooldown_and_trade_count(self) -> None:
        config = LivePropRuleConfig(
            profile=_profile(),
            candidate="candidate",
            phase="eval",
            volatility_control=PropVolatilityControlConfig(enabled=True, post_shock_cooldown_bars=2),
        )
        guard = LivePropRuleGuard(config)
        guard.on_bar(
            timestamp=pd.Timestamp("2024-01-03 10:05"),
            equity=100_000,
            daily_pnl=0,
            has_open_position=False,
            volatility_context={"volatility_jump_event": True},
        )
        guard.record_event(
            PaperTradingEvent(
                event_type="entry_filled",
                timestamp=pd.Timestamp("2024-01-03 10:05"),
                message="entry",
                direction="long",
                contracts=1,
            ),
            equity=100_000,
        )

        restored = LivePropRuleGuard(config)
        restored.load_state(guard.to_state())

        self.assertEqual(restored.daily_entry_count, 1)
        self.assertEqual(restored.prop_volatility_state, "high_vol_kill_switch_day")
        self.assertEqual(restored.prop_volatility_cooldown_bars_remaining, 2)
        self.assertEqual(restored.entry_block_reason().reason, "prop_volatility_kill_switch")


class PropResearchGateTests(unittest.TestCase):
    def test_validate_prop_research_gate_passes_saved_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            wf_dir = run_dir / "research" / "walkforward" / "prop_firm"
            sim_dir = run_dir / "simulations"
            wf_dir.mkdir(parents=True)
            sim_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "sample_scope": "walkforward_oos",
                        "expected_net_payout_per_eval_attempt": 10.0,
                        "probability_eval_to_first_payout_pct": 5.0,
                    }
                ]
            ).to_csv(wf_dir / "walkforward_stitched_summary.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "pnl_pass_5pct": True,
                        "sharpe_pass_5pct": True,
                        "pnl_p_value": 0.01,
                        "sharpe_p_value": 0.01,
                    }
                ]
            ).to_csv(wf_dir / "walkforward_stitched_random_walk.csv", index=False)
            pd.DataFrame(
                [
                    {"scenario": "combined_mild", "profit_factor": 1.08, "total_pnl": 100.0}
                ]
            ).to_csv(sim_dir / "stress_trade_stress_tests.csv", index=False)

            report = validate_prop_research_gate(run_dir)

            self.assertTrue(report.passed, report.summary())

    def test_validate_prop_research_gate_fails_fragile_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            wf_dir = run_dir / "research" / "walkforward" / "prop_firm"
            sim_dir = run_dir / "simulations"
            wf_dir.mkdir(parents=True)
            sim_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "expected_net_payout_per_eval_attempt": 72.0,
                        "probability_eval_to_first_payout_pct": 14.0,
                    }
                ]
            ).to_csv(wf_dir / "walkforward_stitched_summary.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "pnl_pass_5pct": False,
                        "sharpe_pass_5pct": False,
                        "pnl_p_value": 0.3,
                        "sharpe_p_value": 0.3,
                    }
                ]
            ).to_csv(wf_dir / "walkforward_stitched_random_walk.csv", index=False)
            pd.DataFrame(
                [
                    {"scenario": "combined_mild", "profit_factor": 0.91, "total_pnl": -100.0}
                ]
            ).to_csv(sim_dir / "stress_trade_stress_tests.csv", index=False)

            report = validate_prop_research_gate(run_dir)

            self.assertFalse(report.passed)

    def test_validate_prop_research_gate_rejects_in_sample_prop_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            wf_dir = run_dir / "research" / "walkforward" / "prop_firm"
            sim_dir = run_dir / "simulations"
            wf_dir.mkdir(parents=True)
            sim_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    {
                        "sample_scope": "development_in_sample",
                        "expected_net_payout_per_eval_attempt": 10.0,
                        "probability_eval_to_first_payout_pct": 5.0,
                    }
                ]
            ).to_csv(wf_dir / "walkforward_stitched_summary.csv", index=False)
            pd.DataFrame(
                [
                    {
                        "pnl_pass_5pct": True,
                        "sharpe_pass_5pct": True,
                        "pnl_p_value": 0.01,
                        "sharpe_p_value": 0.01,
                    }
                ]
            ).to_csv(wf_dir / "walkforward_stitched_random_walk.csv", index=False)
            pd.DataFrame(
                [
                    {"scenario": "combined_mild", "profit_factor": 1.08, "total_pnl": 100.0}
                ]
            ).to_csv(sim_dir / "stress_trade_stress_tests.csv", index=False)

            report = validate_prop_research_gate(run_dir)

            self.assertFalse(report.passed)
            failed_names = {check.name for check in report.checks if not check.passed}
            self.assertIn("wf_sample_scope", failed_names)


if __name__ == "__main__":
    unittest.main()
