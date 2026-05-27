from __future__ import annotations

import unittest

from backtest.prop_volatility import (
    PROP_VOLATILITY_NOT_LIVE_EDGE_NOTE,
    PropVolatilityControlConfig,
    evaluate_prop_volatility_control,
)


class PropVolatilityControlTests(unittest.TestCase):
    def test_high_vol_opportunity_day_raises_trade_budget_without_live_edge_claim(self) -> None:
        decision = evaluate_prop_volatility_control(
            {"realized_vol_ratio": 1.5, "volatility_state": "expanded_volatility_context"},
            config=PropVolatilityControlConfig(
                enabled=True,
                normal_max_trades_per_day=1,
                high_vol_opportunity_max_trades_per_day=2,
            ),
            daily_pnl=100.0,
            daily_loss_stop=300.0,
        )

        self.assertEqual(decision.state, "high_vol_opportunity_day")
        self.assertEqual(decision.max_trades_today, 2)
        self.assertFalse(decision.block_new_entries)
        self.assertFalse(decision.flatten_open_position)
        self.assertEqual(decision.not_live_edge_note, PROP_VOLATILITY_NOT_LIVE_EDGE_NOTE)

    def test_jump_or_unstable_volatility_triggers_kill_switch_and_cooldown(self) -> None:
        decision = evaluate_prop_volatility_control(
            {
                "volatility_jump_event": True,
                "volatility_state": "jump_volatility_context",
            },
            config=PropVolatilityControlConfig(enabled=True, post_shock_cooldown_bars=2),
            daily_pnl=0.0,
            daily_loss_stop=300.0,
        )

        self.assertEqual(decision.state, "high_vol_kill_switch_day")
        self.assertEqual(decision.reason, "volatility_shock")
        self.assertTrue(decision.block_new_entries)
        self.assertTrue(decision.flatten_open_position)
        self.assertEqual(decision.cooldown_bars_remaining, 2)

    def test_post_shock_cooldown_blocks_entries_after_shock_bar(self) -> None:
        decision = evaluate_prop_volatility_control(
            {"realized_vol_ratio": 1.0, "volatility_state": "normal_volatility_context"},
            config=PropVolatilityControlConfig(enabled=True, post_shock_cooldown_bars=3),
            current_cooldown_bars=3,
            daily_pnl=0.0,
            daily_loss_stop=300.0,
        )

        self.assertEqual(decision.state, "post_shock_cooldown")
        self.assertEqual(decision.cooldown_bars_remaining, 2)
        self.assertTrue(decision.block_new_entries)
        self.assertFalse(decision.flatten_open_position)

    def test_high_vol_daily_loss_acceleration_becomes_kill_switch(self) -> None:
        decision = evaluate_prop_volatility_control(
            {"realized_vol_ratio": 1.5},
            config=PropVolatilityControlConfig(
                enabled=True,
                high_vol_daily_loss_kill_fraction=0.50,
            ),
            daily_pnl=-180.0,
            daily_loss_stop=300.0,
        )

        self.assertEqual(decision.state, "high_vol_kill_switch_day")
        self.assertEqual(decision.reason, "high_volatility_daily_loss_acceleration")
        self.assertAlmostEqual(decision.daily_loss_fraction, 0.60)

    def test_volatility_adjusted_max_trades_blocks_after_budget(self) -> None:
        decision = evaluate_prop_volatility_control(
            {"realized_vol_ratio": 1.0},
            config=PropVolatilityControlConfig(
                enabled=True,
                normal_max_trades_per_day=1,
            ),
            daily_pnl=0.0,
            daily_loss_stop=300.0,
            daily_entry_count=1,
        )

        self.assertEqual(decision.state, "normal")
        self.assertEqual(decision.max_trades_today, 1)
        self.assertTrue(decision.max_trades_reached)
        self.assertTrue(decision.block_new_entries)


if __name__ == "__main__":
    unittest.main()
