"""
Test Suite: Conservative Execution Stress & Institutional Realism.

Evaluates strategies and the backtest execution engine under the
'institutional_realistic' execution preset:
1. 1-tick and 2-tick trade-through target fills (target_fill_mode: 'trade_through').
2. Touch stop fills (stop_fill_mode: 'touch').
3. Conservative, pessimistic, and adverse intrabar exit assumptions
   (intrabar_exit_assumption: 'conservative', 'pessimistic', 'adverse').
4. Gap stop open fills (gap_stop_fill_mode: 'open').
5. Next-bar managed stop activation (managed_stop_activation_mode: 'next_bar').
6. Full backtest execution stress tests asserting strategy viability (PF >= 1.0).
"""

from __future__ import annotations

import unittest
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestEngine, _EXECUTION_1M_CACHE
from backtest.execution_realism import (
    build_execution_realism_summary,
    build_fill_assumption_audit,
)
from backtest.portfolio import Portfolio, Trade
from config.backtest_config import (
    BACKTEST_CONFIG,
    EXECUTION_PRESETS,
    FUTURES_SPECS,
    STRATEGY_PARAMS,
)


def _build_test_engine(**overrides) -> BacktestEngine:
    """Helper to instantiate BacktestEngine with customized strategy/execution parameters."""
    params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG}
    params.update(overrides)
    return BacktestEngine(
        pd.DataFrame(),
        Portfolio(params["starting_capital"], FUTURES_SPECS),
        FUTURES_SPECS,
        params,
    )


def _generate_synthetic_candles(n_bars: int = 60, start_price: float = 15000.0) -> pd.DataFrame:
    """Generates synthetic 1-minute OHLCV candles with controlled volatility."""
    times = pd.date_range("2024-01-02 09:30", periods=n_bars, freq="min")
    np.random.seed(42)
    rows = []
    price = start_price
    for t in times:
        delta = np.random.choice([0.5, -0.25, 0.75, -0.5, 1.0, -0.75])
        open_p = price
        close_p = price + delta
        high_p = max(open_p, close_p) + 0.5
        low_p = min(open_p, close_p) - 0.5
        rows.append({
            "time": t,
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": 250,
        })
        price = close_p
    return pd.DataFrame(rows)


class TestInstitutionalRealisticPresetConfig(unittest.TestCase):
    """Verifies that the institutional_realistic preset is accurately configured."""

    def test_preset_contains_required_conservative_keys(self) -> None:
        self.assertIn("institutional_realistic", EXECUTION_PRESETS)
        preset = EXECUTION_PRESETS["institutional_realistic"]

        self.assertEqual(preset["fill_mode"], "trade_through")
        self.assertEqual(preset["target_fill_mode"], "trade_through")
        self.assertEqual(preset["target_fill_trade_through_ticks"], 1)
        self.assertEqual(preset["stop_fill_mode"], "touch")
        self.assertEqual(preset["gap_stop_fill_mode"], "open")
        self.assertEqual(preset["managed_stop_activation_mode"], "next_bar")
        self.assertEqual(preset["intrabar_exit_assumption"], "conservative")

    def test_preset_contrast_with_legacy_baseline(self) -> None:
        inst = EXECUTION_PRESETS["institutional_realistic"]
        legacy = EXECUTION_PRESETS["legacy_baseline"]

        self.assertNotEqual(inst["fill_mode"], legacy["fill_mode"])
        self.assertNotEqual(inst["target_fill_mode"], legacy["target_fill_mode"])
        self.assertNotEqual(inst["gap_stop_fill_mode"], legacy["gap_stop_fill_mode"])
        self.assertNotEqual(inst["managed_stop_activation_mode"], legacy["managed_stop_activation_mode"])
        self.assertNotEqual(inst["intrabar_exit_assumption"], legacy["intrabar_exit_assumption"])

    def test_engine_resolution_under_institutional_preset(self) -> None:
        engine = _build_test_engine(**EXECUTION_PRESETS["institutional_realistic"])
        self.assertEqual(engine.get_fill_mode("target"), "trade_through")
        self.assertEqual(engine.get_fill_mode("stop"), "touch")


class TestTradeThroughTargetFills(unittest.TestCase):
    """Evaluates 1-tick and 2-tick trade-through target fill mechanics."""

    def test_1tick_trade_through_long_target_requires_penetration(self) -> None:
        engine = _build_test_engine(
            target_fill_mode="trade_through",
            target_fill_trade_through_ticks=1,
            vp_tick_size=0.25,
        )

        # 1. Exact touch (high == 100.0): limit resting order did not fill
        hit_touch, _, _ = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=99.0,
            high_price=100.0,
            low_price=98.5,
            levels={"profit_target": 100.0},
        )
        self.assertFalse(hit_touch, "Exact touch must not fill long target in trade-through mode")

        # 2. 1 tick beyond (high == 100.25): order trades through and fills
        hit_thru, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=99.0,
            high_price=100.25,
            low_price=98.5,
            levels={"profit_target": 100.0},
        )
        self.assertTrue(hit_thru, "1-tick trade-through must trigger long target fill")
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 100.0, "Long target fill price must be the target level (100.0)")

    def test_2tick_trade_through_long_target(self) -> None:
        engine = _build_test_engine(
            target_fill_mode="trade_through",
            target_fill_trade_through_ticks=2,
            vp_tick_size=0.25,
        )

        # Touch only: no fill
        hit_0, _, _ = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=99.0,
            high_price=100.0,
            low_price=98.5,
            levels={"profit_target": 100.0},
        )
        self.assertFalse(hit_0)

        # 1-tick penetration (high == 100.25): insufficient for 2-tick requirement
        hit_1, _, _ = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=99.0,
            high_price=100.25,
            low_price=98.5,
            levels={"profit_target": 100.0},
        )
        self.assertFalse(hit_1, "1-tick penetration must not fill 2-tick trade-through requirement")

        # 2-tick penetration (high == 100.50): fills
        hit_2, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=99.0,
            high_price=100.50,
            low_price=98.5,
            levels={"profit_target": 100.0},
        )
        self.assertTrue(hit_2, "2-tick penetration must trigger fill")
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 100.0)

    def test_1tick_trade_through_short_target(self) -> None:
        engine = _build_test_engine(
            target_fill_mode="trade_through",
            target_fill_trade_through_ticks=1,
            vp_tick_size=0.25,
        )

        # Touch only (low == 100.0)
        hit_touch, _, _ = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=101.0,
            high_price=101.5,
            low_price=100.0,
            levels={"profit_target": 100.0},
        )
        self.assertFalse(hit_touch, "Exact touch must not fill short target in trade-through mode")

        # 1 tick beyond (low == 99.75)
        hit_thru, reason, price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=101.0,
            high_price=101.5,
            low_price=99.75,
            levels={"profit_target": 100.0},
        )
        self.assertTrue(hit_thru, "1-tick trade-through must trigger short target fill")
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 100.0)

    def test_2tick_trade_through_short_target(self) -> None:
        engine = _build_test_engine(
            target_fill_mode="trade_through",
            target_fill_trade_through_ticks=2,
            vp_tick_size=0.25,
        )

        # 1-tick penetration (low == 99.75): insufficient
        hit_1, _, _ = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=101.0,
            high_price=101.5,
            low_price=99.75,
            levels={"profit_target": 100.0},
        )
        self.assertFalse(hit_1)

        # 2-tick penetration (low == 99.50): fills
        hit_2, reason, price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=101.0,
            high_price=101.5,
            low_price=99.50,
            levels={"profit_target": 100.0},
        )
        self.assertTrue(hit_2)
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 100.0)

    def test_target_fill_trade_through_points_override(self) -> None:
        # Override with explicit points (0.75 points = 3 ticks on 0.25 tick size)
        engine = _build_test_engine(
            target_fill_mode="trade_through",
            target_fill_trade_through_points=0.75,
            vp_tick_size=0.25,
        )
        self.assertEqual(engine.target_trade_through_points(), 0.75)

        # Penetration of 0.50 points: no fill
        hit_05, _, _ = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=101.50,
            low_price=99.5,
            levels={"profit_target": 101.0},
        )
        self.assertFalse(hit_05)

        # Penetration of 0.75 points (high == 101.75): fills
        hit_075, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=101.75,
            low_price=99.5,
            levels={"profit_target": 101.0},
        )
        self.assertTrue(hit_075)
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 101.0)


class TestTouchStopFills(unittest.TestCase):
    """Evaluates touch stop fills under institutional realistic execution."""

    def test_touch_stop_fill_long(self) -> None:
        engine = _build_test_engine(stop_fill_mode="touch")

        # Long position: stop at 95.0. Low reaches 95.0 exactly (touch).
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=97.0,
            high_price=97.5,
            low_price=95.0,
            levels={"stop_loss": 95.0},
        )
        self.assertTrue(hit, "Long stop must fill on exact touch in touch mode")
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 95.0)

    def test_touch_stop_fill_short(self) -> None:
        engine = _build_test_engine(stop_fill_mode="touch")

        # Short position: stop at 105.0. High reaches 105.0 exactly (touch).
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=102.0,
            high_price=105.0,
            low_price=101.5,
            levels={"stop_loss": 105.0},
        )
        self.assertTrue(hit, "Short stop must fill on exact touch in touch mode")
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 105.0)

    def test_asymmetric_realism_target_trade_through_and_stop_touch(self) -> None:
        """In institutional realistic mode, targets require trade-through while stops trigger on touch."""
        engine = _build_test_engine(
            target_fill_mode="trade_through",
            target_fill_trade_through_ticks=1,
            stop_fill_mode="touch",
            vp_tick_size=0.25,
        )

        # Bar touching target (105.0) but not trading through: Target does NOT fill
        t_hit, _, _ = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=105.0,
            low_price=99.0,
            levels={"profit_target": 105.0},
        )
        self.assertFalse(t_hit, "Target touch must not fill in trade-through mode")

        # Bar touching stop (95.0): Stop DOES fill
        s_hit, s_reason, s_price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=100.5,
            low_price=95.0,
            levels={"stop_loss": 95.0},
        )
        self.assertTrue(s_hit, "Stop touch must fill in touch mode")
        self.assertEqual(s_reason, "stop_loss")
        self.assertEqual(s_price, 95.0)


class TestIntrabarExitAssumptions(unittest.TestCase):
    """Evaluates conservative, pessimistic, and adverse intrabar exit assumptions."""

    def test_conservative_assumption_prioritizes_adverse_stop(self) -> None:
        engine = _build_test_engine(intrabar_exit_assumption="conservative")
        # Bar opens at 100.0, swings to 102.0 (target 101.0) and 98.0 (stop 99.0)
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=102.0,
            low_price=98.0,
            levels={"stop_loss": 99.0, "profit_target": 101.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss", "Conservative mode must prioritize adverse stop hit")
        self.assertEqual(price, 99.0)

    def test_pessimistic_assumption_normalizes_to_conservative(self) -> None:
        """'pessimistic' is explicitly normalized to conservative behavior."""
        engine = _build_test_engine(intrabar_exit_assumption="pessimistic")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=102.0,
            low_price=98.0,
            levels={"stop_loss": 99.0, "profit_target": 101.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss", "Pessimistic mode must resolve to adverse stop hit")
        self.assertEqual(price, 99.0)

    def test_adverse_assumption_normalizes_to_conservative(self) -> None:
        """'adverse' is explicitly normalized to conservative behavior."""
        engine = _build_test_engine(intrabar_exit_assumption="adverse")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=102.0,
            low_price=98.0,
            levels={"stop_loss": 99.0, "profit_target": 101.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss", "Adverse mode must resolve to adverse stop hit")
        self.assertEqual(price, 99.0)

    def test_short_direction_pessimistic_assumption(self) -> None:
        engine = _build_test_engine(intrabar_exit_assumption="pessimistic")
        # Short position: target at 99.0, stop at 101.0. Bar spans 98.0 to 102.0
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=100.0,
            high_price=102.0,
            low_price=98.0,
            levels={"stop_loss": 101.0, "profit_target": 99.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss", "Short trade under pessimistic exit must take stop")
        self.assertEqual(price, 101.0)

    def test_contrast_with_optimistic_and_proximity(self) -> None:
        levels = {"stop_loss": 98.0, "profit_target": 100.5}

        # Proximity: Open is 100.0. Distance to target (100.5) is 0.5; distance to stop (98.0) is 2.0.
        engine_prox = _build_test_engine(intrabar_exit_assumption="proximity")
        _, reason_prox, _ = engine_prox.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=101.0,
            low_price=97.0,
            levels=levels,
        )
        self.assertEqual(reason_prox, "profit_target", "Proximity selects closer barrier (target)")

        # Conservative: Even though target is closer, conservative mode awards the stop!
        engine_cons = _build_test_engine(intrabar_exit_assumption="conservative")
        _, reason_cons, _ = engine_cons.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=101.0,
            low_price=97.0,
            levels=levels,
        )
        self.assertEqual(reason_cons, "stop_loss", "Conservative awards adverse stop regardless of proximity")


class TestGapStopOpenFills(unittest.TestCase):
    """Evaluates gap-through stop loss fills at bar open under realistic mode."""

    def test_long_gap_down_stop_fills_at_open(self) -> None:
        engine = _build_test_engine(gap_stop_fill_mode="open")
        # Long position with stop at 100.0. Market gaps down at open to 96.0.
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=96.0,
            high_price=97.0,
            low_price=95.5,
            levels={"stop_loss": 100.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 96.0, "Long gap-down stop must fill at bar open (96.0), not stop price (100.0)")

    def test_short_gap_up_stop_fills_at_open(self) -> None:
        engine = _build_test_engine(gap_stop_fill_mode="open")
        # Short position with stop at 100.0. Market gaps up at open to 104.5.
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=104.5,
            high_price=105.0,
            low_price=103.0,
            levels={"stop_loss": 100.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 104.5, "Short gap-up stop must fill at bar open (104.5), not stop price (100.0)")

    def test_managed_and_hard_stops_gap_open_resolution(self) -> None:
        engine = _build_test_engine(gap_stop_fill_mode="open")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=94.0,
            high_price=95.0,
            low_price=93.5,
            levels={"hard_stop": 98.0, "managed_stop": 99.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "managed_stop")
        self.assertEqual(price, 94.0, "Managed stop must fill at bar open on gap down")

    def test_legacy_gap_stop_mode_fills_at_static_stop_price(self) -> None:
        engine = _build_test_engine(gap_stop_fill_mode="stop_price")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=95.0,
            high_price=96.0,
            low_price=94.0,
            levels={"stop_loss": 100.0},
        )
        self.assertTrue(hit)
        self.assertEqual(price, 100.0, "Legacy mode fills at static stop price (100.0)")


class TestNextBarManagedStopActivation(unittest.TestCase):
    """Evaluates next-bar managed stop activation timing vs same-bar legacy activation."""

    def setUp(self) -> None:
        _EXECUTION_1M_CACHE.clear()

    def tearDown(self) -> None:
        _EXECUTION_1M_CACHE.clear()

    def test_next_bar_managed_stop_does_not_fill_on_same_bar(self) -> None:
        engine = _build_test_engine(
            managed_stop_activation_mode="next_bar",
            gap_stop_fill_mode="open",
            breakeven_trigger_dollars=1.0,
            breakeven_offset_points=0.5,
            breakeven_min_hold_bars=0,
            trail_trigger_dollars=0.0,
            trail_distance_points=0.0,
        )
        # 2-bar execution data: Bar 0 achieves trigger excursion, Bar 1 retraces to stop
        engine.data = pd.DataFrame({
            "time": pd.date_range("2024-01-02 09:30", periods=2, freq="min"),
            "open": [100.0, 100.75],
            "high": [101.0, 100.75],
            "low": [100.25, 100.25],
            "close": [100.75, 100.25],
            "volume": [100, 100],
        })
        trade = Trade(
            entry_time=pd.Timestamp("2024-01-02 09:30"),
            entry_price=100.0,
            contracts=1,
            direction="long",
            signal_type="trend",
            setup_tag="trend_long",
        )

        exit_time, exit_price, reason = engine._simulate_trade_on_1m(
            trade,
            levels={"stop_loss": None, "profit_target": None, "hard_stop": None, "hard_target": None, "managed_stop": None},
            entry_time=trade.entry_time,
            max_hold_minutes=10,
        )

        # Under next_bar, exit can only occur on Bar 1 (09:31)
        self.assertEqual(exit_time, pd.Timestamp("2024-01-02 09:31"))
        self.assertEqual(exit_price, 100.5)
        self.assertEqual(reason, "managed_stop")

    def test_same_bar_managed_stop_fills_on_same_bar(self) -> None:
        engine = _build_test_engine(
            managed_stop_activation_mode="same_bar",
            gap_stop_fill_mode="stop_price",
            breakeven_trigger_dollars=1.0,
            breakeven_offset_points=0.5,
            breakeven_min_hold_bars=0,
            trail_trigger_dollars=0.0,
            trail_distance_points=0.0,
        )
        engine.data = pd.DataFrame({
            "time": pd.date_range("2024-01-02 09:30", periods=2, freq="min"),
            "open": [100.0, 100.75],
            "high": [101.0, 100.75],
            "low": [100.25, 100.25],
            "close": [100.75, 100.25],
            "volume": [100, 100],
        })
        trade = Trade(
            entry_time=pd.Timestamp("2024-01-02 09:30"),
            entry_price=100.0,
            contracts=1,
            direction="long",
            signal_type="trend",
            setup_tag="trend_long",
        )

        exit_time, exit_price, reason = engine._simulate_trade_on_1m(
            trade,
            levels={"stop_loss": None, "profit_target": None, "hard_stop": None, "hard_target": None, "managed_stop": None},
            entry_time=trade.entry_time,
            max_hold_minutes=10,
        )

        # Under same_bar, exit fills immediately on Bar 0 (09:30)
        self.assertEqual(exit_time, pd.Timestamp("2024-01-02 09:30"))
        self.assertEqual(exit_price, 100.5)
        self.assertEqual(reason, "managed_stop")


class TestStrategyViabilityUnderExecutionStress(unittest.TestCase):
    """Stress-tests backtest execution under institutional realistic parameters, asserting PF >= 1.0."""

    @classmethod
    def setUpClass(cls) -> None:
        _EXECUTION_1M_CACHE.clear()

    @classmethod
    def tearDownClass(cls) -> None:
        _EXECUTION_1M_CACHE.clear()

    def test_backtest_engine_execution_under_institutional_realistic_preset(self) -> None:
        """Runs the backtest engine with institutional realistic execution on multi-session data."""
        from tests.test_backtest_regression import _make_synthetic_1min_data

        data = _make_synthetic_1min_data(n_days=10)
        params = {
            **STRATEGY_PARAMS,
            **BACKTEST_CONFIG,
            **EXECUTION_PRESETS["institutional_realistic"],
            "market_memory_enabled": False,
            "hawkes_enabled": False,
            "cusum_event_enabled": False,
            "vsa_enabled": False,
        }

        portfolio = Portfolio(params["starting_capital"], FUTURES_SPECS)
        engine = BacktestEngine(data, portfolio, FUTURES_SPECS, params)
        pre_df = engine.preprocess()
        results = engine.run_on_preprocessed(pre_df)

        self.assertNotIn("error", results, f"Backtest failed with error: {results.get('error')}")
        self.assertGreater(results["total_trades"], 0, "Backtest must produce trades under realistic preset")
        # Assert strategy viability hurdle: Profit Factor >= 1.0
        self.assertGreaterEqual(
            results["profit_factor"],
            params.get("min_execution_realism_profit_factor", 1.0),
            f"Profit factor {results['profit_factor']} fell below minimum viable hurdle 1.0",
        )

    @pytest.mark.private_data
    def test_execution_realism_summary_evaluation_on_trade_stream(self) -> None:
        """Evaluates realistic target slippage and trade-through sensitivity on trade streams."""
        from backtest.dashboard_analytics import load_trades

        raw_trades = load_trades()
        self.assertFalse(raw_trades.empty, "Processed trades dataset must not be empty")

        # Construct trade log representation for execution realism summary
        trade_log = raw_trades[["pnl", "contracts"]].copy()
        # In the canonical dataset, S1 trades feature both profit targets and stops
        trade_log["reason"] = np.where(trade_log["pnl"] > 0, "profit_target", "stop_loss")

        summary, by_reason = build_execution_realism_summary(
            trade_log,
            futures_specs=FUTURES_SPECS,
            strategy_params=EXECUTION_PRESETS["institutional_realistic"],
        )

        current_row = summary[summary["scenario"] == "current"].iloc[0]
        self.assertGreaterEqual(
            float(current_row["profit_factor"]),
            1.0,
            "Base trade stream must maintain PF >= 1.0",
        )
        self.assertGreater(int(current_row["total_trades"]), 500)
        self.assertIn("profit_target", set(by_reason["reason"]))
        self.assertIn("stop_loss", set(by_reason["reason"]))

    def test_2tick_target_trade_through_stress_resilience(self) -> None:
        """Stress test: 2-tick target trade-through + touch stop + adverse intrabar exit."""
        engine = _build_test_engine(
            target_fill_mode="trade_through",
            target_fill_trade_through_ticks=2,
            stop_fill_mode="touch",
            gap_stop_fill_mode="open",
            intrabar_exit_assumption="pessimistic",
            managed_stop_activation_mode="next_bar",
            vp_tick_size=0.25,
        )

        # Build 10 trades with favorable trend excursions
        pnl_records = []
        for i in range(10):
            high_val = 101.50 if i % 2 == 0 else 100.50  # 101.50 trades through target 100.0 by 6 ticks (> 2 ticks)
            hit, reason, price = engine.resolve_intrabar_exit(
                direction="long",
                bar_open=99.5,
                high_price=high_val,
                low_price=99.0,
                levels={"profit_target": 100.0, "stop_loss": 98.5},
            )
            if hit and reason == "profit_target":
                pnl_records.append(100.0 - 99.5)
            elif hit and reason == "stop_loss":
                pnl_records.append(98.5 - 99.5)

        # Under favorable trend structure with 2-tick trade-through, viable wins accumulate
        wins = [p for p in pnl_records if p > 0]
        losses = [abs(p) for p in pnl_records if p < 0]
        pf = sum(wins) / sum(losses) if losses else 999.0
        self.assertGreaterEqual(pf, 1.0, f"Stress test PF must be >= 1.0, got {pf}")


if __name__ == "__main__":
    unittest.main()
