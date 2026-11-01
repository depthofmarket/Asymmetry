"""
Unit tests for GARCH volatility engine & MVT band calculation.
"""

from __future__ import annotations
import unittest
import numpy as np
import pandas as pd

from backtest.garch_volatility import (
    RecursiveGarchEngine,
    compute_mvt_envelope_at_bar,
    evaluate_garch_mvt_filter,
)


class TestGarchVolatility(unittest.TestCase):
    def test_recursive_garch_engine(self) -> None:
        engine = RecursiveGarchEngine(omega=0.05, alpha=0.08, beta=0.88)
        self.assertGreater(engine.current_var, 0.0)

        # Update with small returns -> variance should remain reasonable
        for r in [0.1, -0.2, 0.05, 0.15, -0.1]:
            sig = engine.update(r)
            self.assertGreater(sig, 0.0)
            self.assertTrue(np.isfinite(sig))

        # Update with a volatility shock -> variance should increase
        sig_before = engine.forecast_horizon(1)
        engine.update(-2.5)  # large return shock
        sig_after = engine.forecast_horizon(1)
        self.assertGreater(sig_after, sig_before)

    def test_mvt_envelope_calculation(self) -> None:
        bars = pd.DataFrame({
            "close": [18000.0, 18010.0, 18020.0, 18030.0],
            "volume": [100, 200, 300, 400],
        })
        mvt = compute_mvt_envelope_at_bar(bars, cond_daily_vol_pct=1.5, intraday_window_minutes=15.0)

        self.assertIn("mvt_0", mvt)
        self.assertIn("sigma_intraday_pts", mvt)
        self.assertGreater(mvt["dp_pos_1"], mvt["mvt_0"])
        self.assertGreater(mvt["dp_pos_2"], mvt["dp_pos_1"])
        self.assertGreater(mvt["dp_pos_3"], mvt["dp_pos_2"])
        self.assertLess(mvt["dp_neg_1"], mvt["mvt_0"])
        self.assertLess(mvt["dp_neg_2"], mvt["dp_neg_1"])
        self.assertLess(mvt["dp_neg_3"], mvt["dp_neg_2"])

    def test_evaluate_garch_mvt_filter(self) -> None:
        bars = pd.DataFrame({
            "close": [18000.0, 18000.0],
            "volume": [100, 100],
        })
        mvt = compute_mvt_envelope_at_bar(bars, cond_daily_vol_pct=1.0, intraday_window_minutes=15.0)
        sigma = mvt["sigma_intraday_pts"]

        # Long in sweet spot: price is 1.0 sigma above VWAP
        eval_sweet = evaluate_garch_mvt_filter(mvt["mvt_0"] + 1.0 * sigma, mvt, direction=1)
        self.assertTrue(eval_sweet["is_sweet_spot"])
        self.assertFalse(eval_sweet["is_exhausted"])
        self.assertEqual(eval_sweet["status"], "SWEET_SPOT")

        # Long exhausted: price is 3.0 sigma above VWAP
        eval_exh = evaluate_garch_mvt_filter(mvt["mvt_0"] + 3.0 * sigma, mvt, direction=1)
        self.assertFalse(eval_exh["is_sweet_spot"])
        self.assertTrue(eval_exh["is_exhausted"])
        self.assertEqual(eval_exh["status"], "EXHAUSTED")

        # Short exhausted: price is 3.0 sigma below VWAP
        eval_short_exh = evaluate_garch_mvt_filter(mvt["mvt_0"] - 3.0 * sigma, mvt, direction=-1)
        self.assertFalse(eval_short_exh["is_sweet_spot"])
        self.assertTrue(eval_short_exh["is_exhausted"])
        self.assertEqual(eval_short_exh["status"], "EXHAUSTED")


if __name__ == "__main__":
    unittest.main()
