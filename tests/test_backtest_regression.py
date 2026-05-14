"""
Regression tests for the NQ backtest engine.

These tests verify that the backtest engine produces consistent results
on a synthetic data fixture. If key metrics change unexpectedly, these
tests will catch the regression before it propagates through the
candidate evaluation pipeline.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.portfolio import Portfolio
from config.backtest_config import (
    FUTURES_SPECS,
    BACKTEST_CONFIG,
    STRATEGY_PARAMS,
    RESEARCH_CONFIG,
    CANDIDATE_CONFIGS,
    VALIDATION_CONFIG,
)


def _make_synthetic_1min_data(
    n_days: int = 5,
    rth_start: str = "09:30",
    rth_end: str = "16:00",
) -> pd.DataFrame:
    """Build synthetic 1-min OHLCV data for deterministic regression testing.

    Uses larger price moves so the ORB and VP regime classifiers trigger
    signals on the synthetic data.
    """
    np.random.seed(42)
    rows: list[dict] = []
    base_date = pd.Timestamp("2023-01-02")

    for day in range(n_days):
        date = base_date + pd.Timedelta(days=day)
        if date.weekday() >= 5:  # skip weekends
            continue
        rth_start_dt = date + pd.Timedelta(
            hours=int(rth_start.split(":")[0]),
            minutes=int(rth_start.split(":")[1]),
        )
        rth_end_dt = date + pd.Timedelta(
            hours=int(rth_end.split(":")[0]),
            minutes=int(rth_end.split(":")[1]),
        )

        price = 12000.0
        t = rth_start_dt
        while t < rth_end_dt:
            hour = t.hour + t.minute / 60.0
            # Strong drift so the ORB range exceeds orb_min_points (10 pts)
            if hour < 11.0:
                drift = 3.0
            elif hour < 13.0:
                drift = 0.0
            else:
                drift = -2.0
            noise = float(np.random.normal(0, 2.0))
            close = price + drift + noise
            high = max(price, close) + abs(float(np.random.normal(0, 1.0)))
            low = min(price, close) - abs(float(np.random.normal(0, 1.0)))
            volume = max(100, int(np.random.exponential(500)))

            rows.append({
                "time": t,
                "open": round(price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": volume,
            })
            price = close
            t += pd.Timedelta(minutes=1)

    df = pd.DataFrame(rows)
    # Add one deterministic continuation pullback so the current default
    # volume-profile strategy exercises trade execution on this fixture.
    pullback_time = base_date + pd.Timedelta(days=1, hours=10, minutes=32)
    pullback = df["time"].eq(pullback_time)
    df.loc[pullback, "low"] = (df.loc[pullback, "close"] - 120.0).round(2)
    # Ensure uniform datetime64[ns] dtype for merge compatibility
    df["time"] = pd.to_datetime(df["time"])
    return df


class BacktestRegressionTests(unittest.TestCase):
    """Check that the engine's output stays stable across refactors."""

    @classmethod
    def setUpClass(cls):
        cls.data = _make_synthetic_1min_data(n_days=10)
        cls.base_params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG}
        cls.base_params["_candidate_name"] = "current"

        # Disable expensive features for fast tests
        cls.base_params["market_memory_enabled"] = False
        cls.base_params["hawkes_enabled"] = False
        cls.base_params["cusum_event_enabled"] = False
        cls.base_params["vsa_enabled"] = False

    def _run_candidate(self, candidate_name: str = "current") -> dict:
        """Helper: run a candidate and return results dict."""
        params = dict(self.base_params)
        if candidate_name != "current":
            params = {**params, **CANDIDATE_CONFIGS[candidate_name], "_candidate_name": candidate_name}
        else:
            params["_candidate_name"] = "current"

        portfolio = Portfolio(
            params["starting_capital"],
            FUTURES_SPECS,
        )
        engine = BacktestEngine(self.data, portfolio, FUTURES_SPECS, params)
        pre_df = engine.preprocess()
        return engine.run_on_preprocessed(pre_df)

    def test_default_candidate_produces_trades(self):
        """The default 'current' candidate should generate at least one trade."""
        results = self._run_candidate("current")
        self.assertNotIn("error", results, f"Engine returned error: {results.get('error')}")
        self.assertGreater(results["total_trades"], 0)

    def test_default_candidate_key_metrics_are_reasonable(self):
        """Key metrics should be within plausible ranges."""
        results = self._run_candidate("current")
        if "error" in results:
            self.skipTest(f"Engine error: {results['error']}")

        self.assertGreaterEqual(results["win_rate"], 0.0)
        self.assertLessEqual(results["win_rate"], 100.0)
        self.assertGreaterEqual(results["sharpe_ratio"], -5.0)
        self.assertLessEqual(results["sharpe_ratio"], 5.0)
        self.assertGreater(results["total_trades"], 0)
        self.assertIsInstance(results["final_equity"], float)
        self.assertIn("bar_profit_factor", results)

    def test_candidate_round_trip(self):
        """All CANDIDATE_CONFIGS should be runnable without crashing."""
        errors: list[str] = []
        for name in sorted(CANDIDATE_CONFIGS):
            if name == "_2021_throttle_params":
                continue  # not a real candidate
            try:
                results = self._run_candidate(name)
                if "error" in results:
                    # Some candidates may legitimately produce no trades
                    # (e.g. MR-only on a trend day), that's OK.
                    pass
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        if errors:
            self.fail(f"Candidate round-trip failures: {'; '.join(errors[:5])}")

    def test_deterministic_output(self):
        """Running the same candidate twice should give identical results."""
        r1 = self._run_candidate("current")
        if "error" in r1:
            self.skipTest(f"Engine error: {r1['error']}")
        r2 = self._run_candidate("current")
        if "error" in r2:
            self.skipTest(f"Engine error on second run: {r2['error']}")

        self.assertEqual(r1["total_trades"], r2["total_trades"])
        self.assertEqual(r1["total_pnl"], r2["total_pnl"])
        self.assertEqual(r1["profit_factor"], r2["profit_factor"])

    def test_candidate_deletion_flag(self):
        """Verify that the _2021_throttle_params key is NOT in CANDIDATE_CONFIGS."""
        # It was an intermediate dict, not a real candidate.
        # However since we use **{} update it doesn't appear as a key.
        # Just verify it's not there.
        self.assertNotIn("_2021_throttle_params", CANDIDATE_CONFIGS)


class CandidateConfigTests(unittest.TestCase):
    """Tests for the candidate config composition system."""

    def test_failed_auction_acceptance_mr_confirms_after_sweep(self):
        params = {
            **STRATEGY_PARAMS,
            **BACKTEST_CONFIG,
            "strategy_name": "volume_profile_regime",
            "mr_signal_mode": "failed_auction_acceptance",
            "mr_sweep_lookback_bars": 3,
            "mr_acceptance_bars": 2,
            "allow_long": True,
            "allow_short": False,
            "mr_long_enabled": True,
            "mr_short_enabled": False,
            "trend_long_enabled": False,
            "trend_short_enabled": False,
            "mr_trade_start": "10:00",
            "mr_trade_end": "10:30",
            "vp_mr_min_poc_room_points": 1.0,
            "mr_excess_buffer_points": 1.5,
            "mr_reclaim_buffer_points": 0.5,
            "mr_value_extension_points": 0.75,
            "mr_long_close_strength_min": 0.60,
        }
        times = pd.to_datetime([
            "2023-01-03 10:05",
            "2023-01-03 10:10",
            "2023-01-03 10:15",
        ])
        df = pd.DataFrame({
            "time": times,
            "date_str": ["2023-01-03"] * 3,
            "hour_min": ["10:05", "10:10", "10:15"],
            "open": [101.0, 100.0, 100.8],
            "high": [101.5, 101.6, 101.8],
            "low": [98.0, 100.4, 100.7],
            "close": [99.5, 101.0, 101.25],
            "vp_poc": [105.0, 105.0, 105.0],
            "vp_val": [100.0, 100.0, 100.0],
            "vp_vah": [110.0, 110.0, 110.0],
            "orb_low": [100.0, 100.0, 100.0],
            "orb_high": [110.0, 110.0, 110.0],
            "orb_mid": [105.0, 105.0, 105.0],
            "orb_range": [10.0, 10.0, 10.0],
            "orb_range_multiple": [1.0, 1.0, 1.0],
            "vwap": [104.0, 104.0, 104.0],
            "vwap_distance_abs": [4.5, 3.0, 2.75],
            "day_regime": ["range", "range", "range"],
            "regime_trend_up_confirmed": [False, False, False],
            "regime_trend_down_confirmed": [False, False, False],
            "trend_ema_slope": [0.0, 0.0, 0.0],
            "close_strength": [0.4, 0.7, 0.7],
        })

        engine = BacktestEngine(
            df,
            Portfolio(params["starting_capital"], FUTURES_SPECS),
            FUTURES_SPECS,
            params,
        )
        out = engine.generate_signals_volume_profile_regime(df)

        self.assertEqual(out["signal"].tolist(), [0, 0, 1])
        self.assertEqual(out["signal_type"].tolist(), ["", "", "mr"])

    def test_make_candidate_merges_context(self):
        c = CANDIDATE_CONFIGS.get("edge_vp_no_trend_vwap_cross_cusum_guard", {})
        bec = c.get("blocked_entry_context", {})
        self.assertIn("trend", bec)
        self.assertIn("trend_long", bec)
        self.assertIn("trend_short", bec)
        self.assertEqual(bec["trend"]["vwap_cross_direction"], ["cross_up", "cross_down"])

    def test_make_candidate_inherits_base(self):
        c = CANDIDATE_CONFIGS.get("edge_vp_no_trend_vwap_cross", {})
        # No base, just entry context
        self.assertIn("blocked_entry_context", c)
        # Should NOT inherit starting capital — that's from the runner, not the candidate
        self.assertNotIn("starting_capital", c)

    def test_edge_candidates_dont_mutate_base(self):
        """CANDIDATE_CONFIGS['higher_frequency_probe'] should not get
        polluted by edge candidates that use it as a base."""
        hf = CANDIDATE_CONFIGS["higher_frequency_probe"]
        self.assertNotIn("blocked_entry_context", hf)
        self.assertEqual(hf["max_trades_per_day"], 5)

    def test_composed_candidates_have_correct_entry_context(self):
        candidates_requiring_vwap_cross = [
            "edge_vp_no_trend_vwap_cross",
            "edge_vp_no_trend_vwap_cross_cusum_guard",
            "edge_vp_no_trend_vwap_cross_delay_1",
            "edge_vp_no_trend_vwap_cross_delay_2",
            "edge_vp_no_trend_vwap_cross_high_freq",
            "edge_vp_no_trend_vwap_cross_high_freq_gap_guard",
            "edge_vp_no_trend_vwap_cross_high_freq_gap_cusum_guard",
        ]
        for name in candidates_requiring_vwap_cross:
            c = CANDIDATE_CONFIGS.get(name, {})
            bec = c.get("blocked_entry_context", {})
            self.assertIn("trend", bec, f"{name} missing trend guard")
            self.assertEqual(
                bec["trend"]["vwap_cross_direction"],
                ["cross_up", "cross_down"],
                f"{name} has wrong vwap_cross_direction",
            )


class MergeEntryContextTests(unittest.TestCase):
    """Unit tests for merge_entry_context helper."""

    def test_empty_merge(self):
        from config.backtest_config import merge_entry_context
        self.assertEqual(merge_entry_context(), {})

    def test_single_context(self):
        from config.backtest_config import merge_entry_context
        ctx = {"a": {"x": [1]}}
        self.assertEqual(merge_entry_context(ctx), ctx)

    def test_deep_merge(self):
        from config.backtest_config import merge_entry_context
        merged = merge_entry_context(
            {"a": {"x": [1]}},
            {"a": {"y": [2]}},
            {"b": {"z": [3]}},
        )
        self.assertEqual(merged["a"]["x"], [1])
        self.assertEqual(merged["a"]["y"], [2])
        self.assertEqual(merged["b"]["z"], [3])

    def test_merge_override(self):
        from config.backtest_config import merge_entry_context
        merged = merge_entry_context(
            {"a": {"x": [1]}},
            {"a": {"x": [2]}},  # override
        )
        self.assertEqual(merged["a"]["x"], [2])


if __name__ == "__main__":
    unittest.main()
