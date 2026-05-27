from __future__ import annotations

import unittest

import pandas as pd

from backtest.execution_cost_stress import add_volatility_conditioned_cost_stress


class VolatilityConditionedCostStressTests(unittest.TestCase):
    def test_high_realized_vol_and_wide_spread_harsher_slippage(self) -> None:
        frame = pd.DataFrame(
            {
                "microstructure_cost_state": ["normal"],
                "median_spread_points": [2.0],
                "p95_spread_points": [2.5],
                "top_book_depth_exhausted_trade_pct": [0.05],
                "realized_vol_ratio": [1.8],
                "volatility_state": ["expanded_volatility_context"],
            }
        )

        out = add_volatility_conditioned_cost_stress(frame)

        self.assertEqual(out.loc[0, "vol_conditioned_cost_state"], "stressed")
        self.assertGreater(float(out.loc[0, "vol_conditioned_slippage_multiplier"]), 1.0)
        self.assertFalse(bool(out.loc[0, "vol_conditioned_reject_fill"]))
        self.assertIn("high_realized_vol_wide_spread", out.loc[0, "vol_conditioned_reason"])

    def test_vol_shock_and_depth_exhaustion_rejects_fragile_fill(self) -> None:
        frame = pd.DataFrame(
            {
                "microstructure_cost_state": ["elevated"],
                "median_spread_points": [1.0],
                "p95_spread_points": [1.5],
                "top_book_depth_exhausted_trade_pct": [0.70],
                "realized_vol_ratio": [1.1],
                "volatility_state": ["jump_volatility_context"],
                "volatility_jump_event": [True],
            }
        )

        out = add_volatility_conditioned_cost_stress(frame)

        self.assertEqual(out.loc[0, "vol_conditioned_cost_state"], "dislocated")
        self.assertTrue(bool(out.loc[0, "vol_conditioned_reject_fill"]))
        self.assertIn("vol_shock_depth_exhaustion", out.loc[0, "vol_conditioned_reason"])

    def test_low_vol_and_tight_spread_allows_normal_assumptions(self) -> None:
        frame = pd.DataFrame(
            {
                "microstructure_cost_state": ["elevated"],
                "median_spread_points": [0.25],
                "p95_spread_points": [0.50],
                "top_book_depth_exhausted_trade_pct": [0.0],
                "realized_vol_ratio": [0.55],
                "volatility_state": ["compressed_volatility_context"],
            }
        )

        out = add_volatility_conditioned_cost_stress(frame)

        self.assertEqual(out.loc[0, "vol_conditioned_cost_state"], "normal")
        self.assertEqual(float(out.loc[0, "vol_conditioned_slippage_multiplier"]), 1.0)
        self.assertTrue(bool(out.loc[0, "vol_conditioned_allow_normal_assumptions"]))
        self.assertFalse(bool(out.loc[0, "vol_conditioned_reject_fill"]))


if __name__ == "__main__":
    unittest.main()
