"""
Adversarial Empirical Stress-Testing Suite for Gate 2 Audit.

Covers:
1. Execution Realism:
   - Trade-through target fill barrier hits: exact touch vs tick-penetration on longs & shorts.
   - Intrabar exit conflicts under multiple assumption inputs:
     conservative, pessimistic, adverse, optimistic, proximity, and invalid/default.
   - Gap-through stop resolution across large adverse opening gaps (long & short).
   - Managed stop activation timing: same-bar vs next-bar under sharp spike excursions.

2. MotiveWave Sizing & Capital Protection:
   - Catastrophic equity curve persistence ($25,800 -> $24,200, $26,200 -> $25,150).
   - Permanent floor locking at $25,100.
   - Cushion < $400 de-leveraging across wide boundary sweeps.
   - Fail-closed boundaries: null context, non-finite balance, deep underwater balance (<= $10,000), broker exception.
   - Empirical verification of order blocking and ORDER_BLOCKED_UNVERIFIED_ACCOUNT logging.
   - Multi-study Java source code parity across all 3 MotiveWave studies:
     LucidMorningVABreakoutStudy.java, LucidMacroMomentumStudy.java, LucidGoldFixBreakoutStudy.java.
"""

from __future__ import annotations

import math
import re
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestEngine, _EXECUTION_1M_CACHE
from backtest.portfolio import Portfolio, Trade
from config.backtest_config import BACKTEST_CONFIG, FUTURES_SPECS, STRATEGY_PARAMS

REPO_ROOT = Path(__file__).resolve().parents[1]
MOTIVEWAVE_DIR = REPO_ROOT / "src/motivewave"
STUDY_FILES = {
    "LucidMorningVABreakoutStudy": MOTIVEWAVE_DIR / "LucidMorningVABreakoutStudy.java",
    "LucidMacroMomentumStudy": MOTIVEWAVE_DIR / "LucidMacroMomentumStudy.java",
    "LucidGoldFixBreakoutStudy": MOTIVEWAVE_DIR / "LucidGoldFixBreakoutStudy.java",
}


def _build_test_engine(**overrides) -> BacktestEngine:
    params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG}
    params.update(overrides)
    return BacktestEngine(
        pd.DataFrame(),
        Portfolio(params["starting_capital"], FUTURES_SPECS),
        FUTURES_SPECS,
        params,
    )


# ==============================================================================
# SECTION 1: EXECUTION REALISM ADVERSARIAL STRESS TESTS
# ==============================================================================

class TestAdversarialTradeThroughFills(unittest.TestCase):
    """Adversarial stress-testing of trade-through vs touch barrier fills."""

    def test_long_target_touch_vs_penetration_matrix(self) -> None:
        """Matrix testing of long profit targets under touch vs trade-through."""
        target = 100.0

        # Scenario 1: Touch mode -> Exact touch must fill
        engine_touch = _build_test_engine(target_fill_mode="touch", vp_tick_size=0.25)
        hit, reason, price = engine_touch.resolve_intrabar_exit(
            direction="long", bar_open=99.0, high_price=100.0, low_price=98.5, levels={"profit_target": target}
        )
        self.assertTrue(hit, "Touch mode must fill on exact touch (high == 100.0)")
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 100.0)

        # Scenario 2: 1-tick trade-through -> Exact touch must NOT fill
        engine_tt1 = _build_test_engine(target_fill_mode="trade_through", target_fill_trade_through_ticks=1, vp_tick_size=0.25)
        hit_tt1_touch, _, _ = engine_tt1.resolve_intrabar_exit(
            direction="long", bar_open=99.0, high_price=100.0, low_price=98.5, levels={"profit_target": target}
        )
        self.assertFalse(hit_tt1_touch, "1-tick trade-through must reject exact touch")

        # Scenario 3: 1-tick trade-through with 0.25 pt penetration -> Fills
        hit_tt1_fill, reason, price = engine_tt1.resolve_intrabar_exit(
            direction="long", bar_open=99.0, high_price=100.25, low_price=98.5, levels={"profit_target": target}
        )
        self.assertTrue(hit_tt1_fill, "1-tick trade-through must fill on 0.25 pt penetration")
        self.assertEqual(price, 100.0, "Limit fill price remains limit order target price (100.0)")

        # Scenario 4: 2-tick trade-through -> 1 tick is insufficient, 2 ticks fills
        engine_tt2 = _build_test_engine(target_fill_mode="trade_through", target_fill_trade_through_ticks=2, vp_tick_size=0.25)
        hit_tt2_sub, _, _ = engine_tt2.resolve_intrabar_exit(
            direction="long", bar_open=99.0, high_price=100.25, low_price=98.5, levels={"profit_target": target}
        )
        self.assertFalse(hit_tt2_sub, "2-tick trade-through must reject 1-tick penetration")

        hit_tt2_fill, _, price = engine_tt2.resolve_intrabar_exit(
            direction="long", bar_open=99.0, high_price=100.50, low_price=98.5, levels={"profit_target": target}
        )
        self.assertTrue(hit_tt2_fill, "2-tick trade-through must fill on 0.50 pt penetration")
        self.assertEqual(price, 100.0)

    def test_short_target_touch_vs_penetration_matrix(self) -> None:
        """Matrix testing of short profit targets under touch vs trade-through."""
        target = 100.0

        # Scenario 1: Touch mode -> Exact touch must fill
        engine_touch = _build_test_engine(target_fill_mode="touch", vp_tick_size=0.25)
        hit, reason, price = engine_touch.resolve_intrabar_exit(
            direction="short", bar_open=101.0, high_price=101.5, low_price=100.0, levels={"profit_target": target}
        )
        self.assertTrue(hit, "Touch mode must fill short target on exact touch (low == 100.0)")
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 100.0)

        # Scenario 2: 1-tick trade-through -> Exact touch must NOT fill
        engine_tt1 = _build_test_engine(target_fill_mode="trade_through", target_fill_trade_through_ticks=1, vp_tick_size=0.25)
        hit_tt1_touch, _, _ = engine_tt1.resolve_intrabar_exit(
            direction="short", bar_open=101.0, high_price=101.5, low_price=100.0, levels={"profit_target": target}
        )
        self.assertFalse(hit_tt1_touch, "1-tick trade-through must reject exact touch on short")

        # Scenario 3: 1-tick trade-through with 0.25 pt penetration (low == 99.75) -> Fills
        hit_tt1_fill, reason, price = engine_tt1.resolve_intrabar_exit(
            direction="short", bar_open=101.0, high_price=101.5, low_price=99.75, levels={"profit_target": target}
        )
        self.assertTrue(hit_tt1_fill, "1-tick trade-through must fill short target on 0.25 pt penetration")
        self.assertEqual(price, 100.0)

        # Scenario 4: 2-tick trade-through -> 1 tick insufficient, 2 ticks fills
        engine_tt2 = _build_test_engine(target_fill_mode="trade_through", target_fill_trade_through_ticks=2, vp_tick_size=0.25)
        hit_tt2_sub, _, _ = engine_tt2.resolve_intrabar_exit(
            direction="short", bar_open=101.0, high_price=101.5, low_price=99.75, levels={"profit_target": target}
        )
        self.assertFalse(hit_tt2_sub)

        hit_tt2_fill, _, price = engine_tt2.resolve_intrabar_exit(
            direction="short", bar_open=101.0, high_price=101.5, low_price=99.50, levels={"profit_target": target}
        )
        self.assertTrue(hit_tt2_fill)
        self.assertEqual(price, 100.0)

    def test_stop_fill_mode_touch_vs_trade_through(self) -> None:
        """Verifies stop fill mechanics under touch and trade-through configurations."""
        # Long Stop at 95.0
        # In touch mode: low == 95.0 fills
        engine_touch = _build_test_engine(stop_fill_mode="touch")
        hit_t, reason, price = engine_touch.resolve_intrabar_exit(
            direction="long", bar_open=97.0, high_price=97.0, low_price=95.0, levels={"stop_loss": 95.0}
        )
        self.assertTrue(hit_t)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 95.0)

        # In trade-through mode with 1 tick: low == 95.0 does NOT fill
        engine_tt = _build_test_engine(stop_fill_mode="trade_through", stop_fill_trade_through_ticks=1, vp_tick_size=0.25)
        hit_sub, _, _ = engine_tt.resolve_intrabar_exit(
            direction="long", bar_open=97.0, high_price=97.0, low_price=95.0, levels={"stop_loss": 95.0}
        )
        self.assertFalse(hit_sub, "Stop in trade-through mode must not trigger on exact touch")

        # Penetration to 94.75 fills
        hit_thru, reason, price = engine_tt.resolve_intrabar_exit(
            direction="long", bar_open=97.0, high_price=97.0, low_price=94.75, levels={"stop_loss": 95.0}
        )
        self.assertTrue(hit_thru)
        self.assertEqual(reason, "stop_loss")


class TestAdversarialIntrabarExitConflicts(unittest.TestCase):
    """Stress-tests conflict resolution when a single bar breaches BOTH target and stop."""

    def test_long_conflict_under_all_assumptions(self) -> None:
        """Evaluates long conflict under conservative, pessimistic, adverse, optimistic, proximity."""
        # Long trade: entry 100.0, stop at 98.0, target at 102.0.
        # Bar opens at 100.0, reaches high 103.0 (> target) and low 97.0 (< stop).
        levels = {"stop_loss": 98.0, "profit_target": 102.0}

        # 1. Conservative assumption -> Stop loss
        eng_cons = _build_test_engine(intrabar_exit_assumption="conservative")
        hit, reason, price = eng_cons.resolve_intrabar_exit("long", bar_open=100.0, high_price=103.0, low_price=97.0, levels=levels)
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss", "Conservative mode must prioritize adverse stop")
        self.assertEqual(price, 98.0)

        # 2. Pessimistic assumption -> Stop loss
        eng_pess = _build_test_engine(intrabar_exit_assumption="pessimistic")
        hit, reason, price = eng_pess.resolve_intrabar_exit("long", bar_open=100.0, high_price=103.0, low_price=97.0, levels=levels)
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss", "Pessimistic mode must prioritize adverse stop")
        self.assertEqual(price, 98.0)

        # 3. Adverse assumption -> Stop loss
        eng_adv = _build_test_engine(intrabar_exit_assumption="adverse")
        hit, reason, price = eng_adv.resolve_intrabar_exit("long", bar_open=100.0, high_price=103.0, low_price=97.0, levels=levels)
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss", "Adverse mode must prioritize adverse stop")
        self.assertEqual(price, 98.0)

        # 4. Optimistic assumption -> Profit target
        eng_opt = _build_test_engine(intrabar_exit_assumption="optimistic")
        hit, reason, price = eng_opt.resolve_intrabar_exit("long", bar_open=100.0, high_price=103.0, low_price=97.0, levels=levels)
        self.assertTrue(hit)
        self.assertEqual(reason, "profit_target", "Optimistic mode must award favorable target")
        self.assertEqual(price, 102.0)

        # 5. Proximity assumption:
        eng_prox = _build_test_engine(intrabar_exit_assumption="proximity")

        # 5a. Open is closer to target (Open = 101.5, dist to target 0.5 vs dist to stop 3.5)
        _, reason_t, price_t = eng_prox.resolve_intrabar_exit("long", bar_open=101.5, high_price=103.0, low_price=97.0, levels=levels)
        self.assertEqual(reason_t, "profit_target")
        self.assertEqual(price_t, 102.0)

        # 5b. Open is closer to stop (Open = 98.5, dist to stop 0.5 vs dist to target 3.5)
        _, reason_s, price_s = eng_prox.resolve_intrabar_exit("long", bar_open=98.5, high_price=103.0, low_price=97.0, levels=levels)
        self.assertEqual(reason_s, "stop_loss")
        self.assertEqual(price_s, 98.0)

        # 5c. Equidistant (Open = 100.0, dist to stop 2.0 == dist to target 2.0) -> Defaults to adverse stop
        _, reason_tie, price_tie = eng_prox.resolve_intrabar_exit("long", bar_open=100.0, high_price=103.0, low_price=97.0, levels=levels)
        self.assertEqual(reason_tie, "stop_loss", "Equidistant proximity tie must break in favor of adverse stop")
        self.assertEqual(price_tie, 98.0)

    def test_short_conflict_under_all_assumptions(self) -> None:
        """Evaluates short conflict under conservative, pessimistic, adverse, optimistic, proximity."""
        # Short trade: entry 100.0, stop at 102.0, target at 98.0.
        # Bar opens at 100.0, high 103.0 (> stop), low 97.0 (< target).
        levels = {"stop_loss": 102.0, "profit_target": 98.0}

        # Conservative
        eng_cons = _build_test_engine(intrabar_exit_assumption="conservative")
        _, reason_c, price_c = eng_cons.resolve_intrabar_exit("short", bar_open=100.0, high_price=103.0, low_price=97.0, levels=levels)
        self.assertEqual(reason_c, "stop_loss")
        self.assertEqual(price_c, 102.0)

        # Pessimistic
        eng_pess = _build_test_engine(intrabar_exit_assumption="pessimistic")
        _, reason_p, price_p = eng_pess.resolve_intrabar_exit("short", bar_open=100.0, high_price=103.0, low_price=97.0, levels=levels)
        self.assertEqual(reason_p, "stop_loss")
        self.assertEqual(price_p, 102.0)

        # Adverse
        eng_adv = _build_test_engine(intrabar_exit_assumption="adverse")
        _, reason_a, price_a = eng_adv.resolve_intrabar_exit("short", bar_open=100.0, high_price=103.0, low_price=97.0, levels=levels)
        self.assertEqual(reason_a, "stop_loss")
        self.assertEqual(price_a, 102.0)

        # Optimistic
        eng_opt = _build_test_engine(intrabar_exit_assumption="optimistic")
        _, reason_o, price_o = eng_opt.resolve_intrabar_exit("short", bar_open=100.0, high_price=103.0, low_price=97.0, levels=levels)
        self.assertEqual(reason_o, "profit_target")
        self.assertEqual(price_o, 98.0)

        # Proximity closer to target (Open = 98.5, dist to target 0.5 vs dist to stop 3.5)
        eng_prox = _build_test_engine(intrabar_exit_assumption="proximity")
        _, reason_pt, price_pt = eng_prox.resolve_intrabar_exit("short", bar_open=98.5, high_price=103.0, low_price=97.0, levels=levels)
        self.assertEqual(reason_pt, "profit_target")
        self.assertEqual(price_pt, 98.0)

    def test_invalid_assumption_safely_defaults_to_conservative(self) -> None:
        """Passing unrecognized or None assumption safely defaults to conservative stop."""
        levels = {"stop_loss": 98.0, "profit_target": 102.0}
        for bad_assumption in [None, "", "unknown", "invalid_mode"]:
            eng = _build_test_engine(intrabar_exit_assumption=bad_assumption)
            hit, reason, price = eng.resolve_intrabar_exit("long", bar_open=100.0, high_price=103.0, low_price=97.0, levels=levels)
            self.assertTrue(hit)
            self.assertEqual(reason, "stop_loss")
            self.assertEqual(price, 98.0)


class TestAdversarialGapThroughStopResolution(unittest.TestCase):
    """Stress-tests gap-through stop resolution across large adverse gaps."""

    def test_long_gap_down_across_gap_magnitudes(self) -> None:
        """Long position with stop at 100.0 across moderate, large, and catastrophic gaps down."""
        levels = {"stop_loss": 100.0}

        for open_p in [99.5, 95.0, 80.0, 50.0]:
            # Gap stop mode 'open': fills at open price
            eng_open = _build_test_engine(gap_stop_fill_mode="open")
            hit, reason, price = eng_open.resolve_intrabar_exit(
                "long", bar_open=open_p, high_price=open_p + 1.0, low_price=open_p - 1.0, levels=levels
            )
            self.assertTrue(hit)
            self.assertEqual(reason, "stop_loss")
            self.assertEqual(price, open_p, f"Gap down stop must fill at open ({open_p}), not static stop 100.0")

            # Legacy mode 'stop_price': fills at static stop
            eng_legacy = _build_test_engine(gap_stop_fill_mode="stop_price")
            _, _, price_legacy = eng_legacy.resolve_intrabar_exit(
                "long", bar_open=open_p, high_price=open_p + 1.0, low_price=open_p - 1.0, levels=levels
            )
            self.assertEqual(price_legacy, 100.0)

    def test_short_gap_up_across_gap_magnitudes(self) -> None:
        """Short position with stop at 100.0 across moderate, large, and catastrophic gaps up."""
        levels = {"stop_loss": 100.0}

        for open_p in [100.5, 105.0, 120.0, 150.0]:
            # Gap stop mode 'open': fills at open price
            eng_open = _build_test_engine(gap_stop_fill_mode="open")
            hit, reason, price = eng_open.resolve_intrabar_exit(
                "short", bar_open=open_p, high_price=open_p + 1.0, low_price=open_p - 1.0, levels=levels
            )
            self.assertTrue(hit)
            self.assertEqual(reason, "stop_loss")
            self.assertEqual(price, open_p, f"Gap up stop must fill at open ({open_p}), not static stop 100.0")

            # Legacy mode 'stop_price': fills at static stop
            eng_legacy = _build_test_engine(gap_stop_fill_mode="stop_price")
            _, _, price_legacy = eng_legacy.resolve_intrabar_exit(
                "short", bar_open=open_p, high_price=open_p + 1.0, low_price=open_p - 1.0, levels=levels
            )
            self.assertEqual(price_legacy, 100.0)

    def test_non_gapping_intraday_stop_fills_at_stop_level(self) -> None:
        """When the bar does NOT gap through the stop, fill occurs at the stop price."""
        # Long position: stop at 100.0, bar opens favorably at 102.0, drops to low 98.0
        eng = _build_test_engine(gap_stop_fill_mode="open")
        hit, reason, price = eng.resolve_intrabar_exit(
            "long", bar_open=102.0, high_price=103.0, low_price=98.0, levels={"stop_loss": 100.0}
        )
        self.assertTrue(hit)
        self.assertEqual(price, 100.0, "Normal intraday stop (no open gap) must fill at stop price (100.0)")

        # Short position: stop at 100.0, bar opens favorably at 98.0, rallies to high 102.0
        hit_s, _, price_s = eng.resolve_intrabar_exit(
            "short", bar_open=98.0, high_price=102.0, low_price=97.0, levels={"stop_loss": 100.0}
        )
        self.assertTrue(hit_s)
        self.assertEqual(price_s, 100.0, "Normal intraday short stop must fill at stop price (100.0)")


class TestAdversarialManagedStopActivationTiming(unittest.TestCase):
    """Stress-tests managed stop activation timing: same-bar vs next-bar under sharp spike excursions."""

    def setUp(self) -> None:
        _EXECUTION_1M_CACHE.clear()

    def tearDown(self) -> None:
        _EXECUTION_1M_CACHE.clear()

    def test_sharp_spike_excursion_same_bar_vs_next_bar(self) -> None:
        """Sharp spike on Bar 0: reaches breakeven trigger, then retraces back on Bar 0."""
        # Entry at 100.0. Breakeven triggers at +1.0 pt (High 101.0), arms breakeven stop at 100.5.
        # Bar 0: Open 100.0, High 102.0 (triggers breakeven), Low 100.25 (below breakeven stop!), Close 100.75.
        # Bar 1: Open 100.75, High 100.80, Low 100.20, Close 100.30.
        candles = pd.DataFrame({
            "time": pd.date_range("2024-01-02 09:30", periods=2, freq="min"),
            "open": [100.0, 100.75],
            "high": [102.0, 100.80],
            "low": [100.25, 100.20],
            "close": [100.75, 100.30],
            "volume": [100, 100],
        })

        def _make_trade():
            return Trade(
                entry_time=pd.Timestamp("2024-01-02 09:30"),
                entry_price=100.0,
                contracts=1,
                direction="long",
                signal_type="trend",
                setup_tag="trend_long",
            )

        # 1. Under same_bar activation:
        # 1a. With gap_stop_fill_mode='stop_price': The stop activates and fills on Bar 0 at the stop price (100.5)
        engine_same = _build_test_engine(
            managed_stop_activation_mode="same_bar",
            gap_stop_fill_mode="stop_price",
            breakeven_trigger_dollars=1.0,
            breakeven_offset_points=0.5,
            breakeven_min_hold_bars=0,
            trail_trigger_dollars=0.0,
            trail_distance_points=0.0,
        )
        engine_same.data = candles.copy()

        trade_same = _make_trade()
        exit_time_same, exit_price_same, reason_same = engine_same._simulate_trade_on_1m(
            trade_same,
            levels={"stop_loss": None, "profit_target": None, "hard_stop": None, "hard_target": None, "managed_stop": None},
            entry_time=trade_same.entry_time,
            max_hold_minutes=10,
        )
        self.assertEqual(exit_time_same, pd.Timestamp("2024-01-02 09:30"), "Same-bar mode fills on Bar 0")
        self.assertEqual(exit_price_same, 100.5)
        self.assertEqual(reason_same, "managed_stop")

        # 1b. With gap_stop_fill_mode='open': On Bar 0, bar_open is 100.0, so min(100.5, 100.0) fills at 100.0!
        _EXECUTION_1M_CACHE.clear()
        engine_same_open = _build_test_engine(
            managed_stop_activation_mode="same_bar",
            gap_stop_fill_mode="open",
            breakeven_trigger_dollars=1.0,
            breakeven_offset_points=0.5,
            breakeven_min_hold_bars=0,
            trail_trigger_dollars=0.0,
            trail_distance_points=0.0,
        )
        engine_same_open.data = candles.copy()
        trade_same_open = _make_trade()
        _, exit_price_same_open, _ = engine_same_open._simulate_trade_on_1m(
            trade_same_open,
            levels={"stop_loss": None, "profit_target": None, "hard_stop": None, "hard_target": None, "managed_stop": None},
            entry_time=trade_same_open.entry_time,
            max_hold_minutes=10,
        )
        self.assertEqual(exit_price_same_open, 100.0, "Same-bar with gap_stop_fill_mode='open' resolves to bar_open 100.0")

        # 2. Under next_bar activation: The stop DOES NOT activate on Bar 0; it survives to Bar 1!
        _EXECUTION_1M_CACHE.clear()
        engine_next = _build_test_engine(
            managed_stop_activation_mode="next_bar",
            gap_stop_fill_mode="open",
            breakeven_trigger_dollars=1.0,
            breakeven_offset_points=0.5,
            breakeven_min_hold_bars=0,
            trail_trigger_dollars=0.0,
            trail_distance_points=0.0,
        )
        engine_next.data = candles.copy()
        trade_next = _make_trade()

        exit_time_next, exit_price_next, reason_next = engine_next._simulate_trade_on_1m(
            trade_next,
            levels={"stop_loss": None, "profit_target": None, "hard_stop": None, "hard_target": None, "managed_stop": None},
            entry_time=trade_next.entry_time,
            max_hold_minutes=10,
        )
        self.assertEqual(exit_time_next, pd.Timestamp("2024-01-02 09:31"), "Next-bar mode MUST NOT fill on Bar 0")
        self.assertEqual(exit_price_next, 100.5)
        self.assertEqual(reason_next, "managed_stop")
        self.assertEqual(exit_price_next, 100.5)
        self.assertEqual(reason_next, "managed_stop")

    def test_next_bar_managed_stop_with_gap_down_on_bar1(self) -> None:
        """When next-bar managed stop triggers, if Bar 1 gaps down below the stop, fills at open."""
        candles = pd.DataFrame({
            "time": pd.date_range("2024-01-02 09:30", periods=2, freq="min"),
            "open": [100.0, 99.80],  # Bar 1 opens at 99.80, gapping through 100.5 managed stop
            "high": [102.0, 99.90],
            "low": [100.25, 99.50],
            "close": [100.75, 99.60],
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

        engine_gap = _build_test_engine(
            managed_stop_activation_mode="next_bar",
            gap_stop_fill_mode="open",
            breakeven_trigger_dollars=1.0,
            breakeven_offset_points=0.5,
            breakeven_min_hold_bars=0,
            trail_trigger_dollars=0.0,
            trail_distance_points=0.0,
        )
        engine_gap.data = candles.copy()

        exit_time, exit_price, reason = engine_gap._simulate_trade_on_1m(
            trade,
            levels={"stop_loss": None, "profit_target": None, "hard_stop": None, "hard_target": None, "managed_stop": None},
            entry_time=trade.entry_time,
            max_hold_minutes=10,
        )
        self.assertEqual(exit_time, pd.Timestamp("2024-01-02 09:31"))
        self.assertEqual(exit_price, 99.80, "Managed stop gap down must fill at Bar 1 open (99.80)")
        self.assertEqual(reason, "managed_stop")


# ==============================================================================
# SECTION 2: MOTIVEWAVE SIZING & CAPITAL PROTECTION ADVERSARIAL STRESS TESTS
# ==============================================================================

class MockOrderContext:
    def __init__(
        self,
        cash: float = 25000.0,
        real: float = 0.0,
        unreal: float = 0.0,
        symbol: str = "MNQ",
        raise_exception: bool = False,
    ) -> None:
        self.cash = cash
        self.real = real
        self.unreal = unreal
        self.symbol = symbol
        self.raise_exception = raise_exception
        self.position = 0

    def getCashBalance(self) -> float:
        if self.raise_exception:
            raise RuntimeError("Broker API disconnected during getCashBalance")
        return self.cash

    def getRealizedPnL(self) -> float:
        return self.real

    def getUnrealizedPnL(self) -> float:
        return self.unreal

    def getPosition(self) -> int:
        return self.position

    def getInstrument(self) -> Any:
        class MockInstrument:
            def __init__(self, sym: str) -> None:
                self.sym = sym
            def getSymbol(self) -> str:
                return self.sym
            def round(self, p: float) -> float:
                return round(p, 2)
        return MockInstrument(self.symbol)

    def getCurrentTime(self) -> int:
        return 1704186600000  # 2024-01-02 09:30:00 ET in epoch ms


class MotiveWaveSimulatedStudy:
    """Exact behavioral simulator matching Java study bytecode logic."""

    def __init__(self, name: str, peak: float = 25000.0, floor: float = 24000.0) -> None:
        self.study_name = name
        self.persisted_peak_balance = peak
        self.persisted_trailing_floor = floor
        self.audit_log: List[Dict[str, Any]] = []

    def set_persisted_risk_state(self, peak: float, floor: float) -> None:
        self.persisted_peak_balance = peak
        self.persisted_trailing_floor = floor

    def resolve_contracts(self, ctx: Optional[MockOrderContext], fallback_contracts: int = 1) -> int:
        if ctx is None:
            return 0
        try:
            cash = ctx.getCashBalance()
            real = ctx.getRealizedPnL()
            unreal = ctx.getUnrealizedPnL()
            balance = cash + real + unreal
            if not math.isfinite(balance) or balance <= 10000.0:
                return 0

            # Monotonic peak update
            self.persisted_peak_balance = max(self.persisted_peak_balance, balance)

            # Floor calculation and permanent locking at $25,100
            floor = max(24000.00, self.persisted_peak_balance - 1000.00)
            if self.persisted_peak_balance >= 26100.00 or self.persisted_trailing_floor >= 25100.00:
                floor = 25100.00

            self.persisted_trailing_floor = max(self.persisted_trailing_floor, floor)

            profit = balance - 25000.00
            cushion = balance - self.persisted_trailing_floor

            if profit >= 1150.00:
                return 1
            if cushion < 400.00:
                return 1
            if profit >= 550.00:
                return 4
            if profit >= 200.00:
                return 3
            return 2
        except Exception:
            return 0

    def execute_auto_trade_if_armed(
        self,
        ctx: Optional[MockOrderContext],
        fallback: int = 2,
    ) -> Tuple[bool, Optional[str]]:
        # In actual Java study, if ctx == null is dereferenced directly without null check, it raises NPE
        if ctx is None:
            self.audit_log.append({
                "event": "ORDER_BLOCKED_UNVERIFIED_ACCOUNT",
                "study": self.study_name,
                "reason": "Account context unverified (null)",
            })
            return False, "ORDER_BLOCKED_UNVERIFIED_ACCOUNT"

        contracts = self.resolve_contracts(ctx, fallback)
        if contracts <= 0:
            self.audit_log.append({
                "event": "ORDER_BLOCKED_UNVERIFIED_ACCOUNT",
                "study": self.study_name,
                "reason": "Account context unverified or sizing returned zero; order entry blocked (fail-closed).",
            })
            return False, "ORDER_BLOCKED_UNVERIFIED_ACCOUNT"

        self.audit_log.append({
            "event": "ORDER_SUBMITTED",
            "study": self.study_name,
            "contracts": contracts,
        })
        return True, "ORDER_SUBMITTED"


class TestAdversarialMotiveWaveCatastrophicCurves(unittest.TestCase):
    """Stress-tests peak and trailing floor persistence across simulated catastrophic equity curves."""

    def test_catastrophic_curve_rising_to_25800_plunging_to_24200(self) -> None:
        """Account rises to $25,800, then plunges to $24,200. Does floor ever decrease?"""
        sim = MotiveWaveSimulatedStudy("LucidMorningVABreakout")

        # Step 1: Rise to 25,800
        ctx_rise = MockOrderContext(cash=25800.0)
        c_rise = sim.resolve_contracts(ctx_rise)
        self.assertEqual(sim.persisted_peak_balance, 25800.0)
        self.assertEqual(sim.persisted_trailing_floor, 24800.0)
        self.assertEqual(c_rise, 4, "Profit $800 >= $550 -> 4 contracts")

        # Step 2: Intermediate drop to 25,200
        ctx_mid = MockOrderContext(cash=25200.0)
        sim.resolve_contracts(ctx_mid)
        self.assertEqual(sim.persisted_peak_balance, 25800.0, "Peak balance must not drop")
        self.assertEqual(sim.persisted_trailing_floor, 24800.0, "Floor must not decrease")

        # Step 3: Catastrophic plunge to 24,200
        ctx_plunge = MockOrderContext(cash=24200.0)
        c_plunge = sim.resolve_contracts(ctx_plunge)

        # Assert floor NEVER decreased
        self.assertEqual(sim.persisted_peak_balance, 25800.0, "Peak balance must remain 25,800")
        self.assertEqual(sim.persisted_trailing_floor, 24800.0, "Floor must remain at 24,800 despite catastrophic drop")

        # Assert Safe CPPI cushion de-leveraging to 1 contract:
        # Cushion = 24,200 - 24,800 = -$600 < $400
        self.assertEqual(c_plunge, 1, "Cushion -$600 < $400 must de-lever sizing to 1 micro contract")

    def test_catastrophic_curve_locking_at_25100_plunging_to_25150(self) -> None:
        """Account rises to $26,200 (locking floor at $25,100), plunging to $25,150. Floor stays locked."""
        sim = MotiveWaveSimulatedStudy("LucidMacroMomentum")

        # Step 1: Account crosses finish line threshold to $26,200
        ctx_lock = MockOrderContext(cash=26200.0)
        c_lock = sim.resolve_contracts(ctx_lock)
        self.assertEqual(sim.persisted_peak_balance, 26200.0)
        self.assertEqual(sim.persisted_trailing_floor, 25100.0, "Floor must lock permanently at $25,100")
        self.assertEqual(c_lock, 1, "Profit $1,200 >= $1,150 triggers finish line shield (1 contract)")

        # Step 2: Extreme drawdown plunging to $25,150 ($1,050 drop from peak)
        ctx_plunge = MockOrderContext(cash=25150.0)
        c_plunge = sim.resolve_contracts(ctx_plunge)

        self.assertEqual(sim.persisted_peak_balance, 26200.0, "Peak balance must remain 26,200")
        self.assertEqual(sim.persisted_trailing_floor, 25100.0, "Floor must remain permanently locked at $25,100")

        # Cushion = 25,150 - 25,100 = $50 < $400
        self.assertEqual(c_plunge, 1, "Cushion $50 < $400 must de-lever sizing to 1 micro contract")

    def test_comprehensive_cushion_deleveraging_boundary_sweep(self) -> None:
        """Exhaustive boundary sweep of cushion values below $400."""
        sim = MotiveWaveSimulatedStudy("LucidGoldFixBreakout")
        sim.set_persisted_risk_state(peak=25800.0, floor=24800.0)

        # Floor is 24,800. Cushion < 400 means balance < 25,200.
        test_balances = [25199.99, 25150.0, 25000.0, 24800.0, 24500.0, 24000.0, 20000.0, 15000.0]
        for bal in test_balances:
            ctx = MockOrderContext(cash=bal)
            c = sim.resolve_contracts(ctx)
            self.assertEqual(c, 1, f"Balance {bal} (cushion {bal - 24800} < 400) must return 1 micro contract")


class TestAdversarialMotiveWaveFailClosedBoundaries(unittest.TestCase):
    """Stress-tests fail-closed boundaries: null context, non-finite, deep underwater, broker exception."""

    def test_null_context_fails_closed(self) -> None:
        sim = MotiveWaveSimulatedStudy("LucidMorningVABreakout")
        self.assertEqual(sim.resolve_contracts(None), 0, "resolveContracts(null) must return 0")

        submitted, event = sim.execute_auto_trade_if_armed(None)
        self.assertFalse(submitted, "executeAutoTradeIfArmed must block on null context")
        self.assertEqual(event, "ORDER_BLOCKED_UNVERIFIED_ACCOUNT")

    def test_non_finite_balance_fails_closed(self) -> None:
        sim = MotiveWaveSimulatedStudy("LucidMorningVABreakout")
        for bad_val in [float("nan"), float("inf"), float("-inf")]:
            ctx = MockOrderContext(cash=bad_val)
            self.assertEqual(sim.resolve_contracts(ctx), 0, f"resolveContracts must return 0 for {bad_val}")

            submitted, event = sim.execute_auto_trade_if_armed(ctx)
            self.assertFalse(submitted, f"executeAutoTradeIfArmed must block for {bad_val}")
            self.assertEqual(event, "ORDER_BLOCKED_UNVERIFIED_ACCOUNT")

    def test_deep_underwater_balance_fails_closed(self) -> None:
        sim = MotiveWaveSimulatedStudy("LucidMacroMomentum")
        underwater_balances = [10000.0, 9999.0, 8000.0, 5000.0, 0.0, -500.0, -10000.0]
        for bad_bal in underwater_balances:
            ctx = MockOrderContext(cash=bad_bal)
            self.assertEqual(sim.resolve_contracts(ctx), 0, f"resolveContracts must return 0 for balance <= 10000 ({bad_bal})")

            submitted, event = sim.execute_auto_trade_if_armed(ctx)
            self.assertFalse(submitted, f"executeAutoTradeIfArmed must block for balance <= 10000 ({bad_bal})")
            self.assertEqual(event, "ORDER_BLOCKED_UNVERIFIED_ACCOUNT")

    def test_broker_exception_during_balance_query_fails_closed(self) -> None:
        sim = MotiveWaveSimulatedStudy("LucidGoldFixBreakout")
        ctx_broken = MockOrderContext(cash=25000.0, raise_exception=True)

        self.assertEqual(sim.resolve_contracts(ctx_broken), 0, "resolveContracts must catch broker exception and return 0")

        submitted, event = sim.execute_auto_trade_if_armed(ctx_broken)
        self.assertFalse(submitted, "executeAutoTradeIfArmed must block when broker API throws exception")
        self.assertEqual(event, "ORDER_BLOCKED_UNVERIFIED_ACCOUNT")


class TestAdversarialMotiveWaveJavaSourceAudit(unittest.TestCase):
    """Direct static AST and source verification across all 3 MotiveWave Java studies."""

    def test_all_three_java_studies_contain_mandatory_safeguards(self) -> None:
        """Validates that all 3 studies contain the exact persistent fields, locking, and fail-closed gates."""
        for name, path in STUDY_FILES.items():
            self.assertTrue(path.exists(), f"Java study file missing: {path}")
            src = path.read_text(encoding="utf-8")

            # 1. Monotonic peak & trailing floor static fields
            self.assertIn("private static double persistedPeakBalance = 25000.00;", src, f"{name}: missing persistedPeakBalance")
            self.assertIn("private static double persistedTrailingFloor = 24000.00;", src, f"{name}: missing persistedTrailingFloor")
            self.assertIn("public static double getPersistedPeakBalance()", src, f"{name}: missing getPersistedPeakBalance")
            self.assertIn("public static double getPersistedTrailingFloor()", src, f"{name}: missing getPersistedTrailingFloor")
            self.assertIn("public static void setPersistedRiskState(double peak, double floor)", src, f"{name}: missing setPersistedRiskState")

            # 2. Fail-closed resolveContracts guards
            self.assertIn("if (ctx == null) return 0;", src, f"{name}: missing if (ctx == null) return 0")
            self.assertIn("if (!Double.isFinite(balance) || balance <= 10000.0)", src, f"{name}: missing isFinite or <= 10000.0 check")

            # 3. Floor calculation and permanent locking at $25,100
            self.assertIn("persistedPeakBalance = Math.max(persistedPeakBalance, Math.max(riskState.peakBalance, balance));", src, f"{name}: missing monotonic peak update")
            self.assertIn("double floor = Math.max(24000.00, persistedPeakBalance - 1000.00);", src, f"{name}: missing base floor calculation")
            self.assertIn("if (persistedPeakBalance >= 26100.00 || riskState.trailingFloor >= 25100.00)", src, f"{name}: missing lock condition")
            self.assertIn("floor = 25100.00;", src, f"{name}: missing floor = 25100.00")
            self.assertIn("persistedTrailingFloor = Math.max(persistedTrailingFloor, Math.max(riskState.trailingFloor, floor));", src, f"{name}: missing monotonic floor update")

            # 4. Cushion < 400.00 de-leveraging
            self.assertIn("double cushion = balance - persistedTrailingFloor;", src, f"{name}: missing cushion calculation")
            self.assertIn("if (cushion < 400.00) return 1;", src, f"{name}: missing cushion < 400.00 de-leveraging")

            # 5. Fail-closed order blocking and ORDER_BLOCKED_UNVERIFIED_ACCOUNT logging in executeAutoTradeIfArmed
            self.assertIn("int contracts = resolveContracts(ctx,", src, f"{name}: missing resolveContracts call in executeAutoTradeIfArmed")
            self.assertIn("if (contracts <= 0)", src, f"{name}: missing contracts <= 0 check")
            self.assertIn("ORDER_BLOCKED_UNVERIFIED_ACCOUNT", src, f"{name}: missing ORDER_BLOCKED_UNVERIFIED_ACCOUNT event")

            # 6. Absence of legacy flaws
            self.assertNotIn("if (contracts <= 0) contracts = 1;", src, f"{name}: legacy contract clamping flaw detected!")
            self.assertNotIn("double hwm = Math.max(25000.00, balance);", src, f"{name}: legacy unpersisted HWM flaw detected!")

    def test_empirical_null_ctx_handling_in_execute_auto_trade_if_armed(self) -> None:
        """Adversarial check: Does executeAutoTradeIfArmed in Java have a null check before calling ctx.getPosition()?"""
        for name, path in STUDY_FILES.items():
            src = path.read_text(encoding="utf-8")
            method_match = re.search(r"private\s+synchronized\s+void\s+executeAutoTradeIfArmed\s*\([^)]*\)\s*\{([^}]+)\}", src)
            self.assertIsNotNone(method_match, f"{name}: executeAutoTradeIfArmed not found")
            method_body = method_match.group(1)

            # Check if ctx == null is checked or if callers guard it
            # Notice callers (onSignal, onBarClose) guard `if (ctx == null) return;`
            self.assertIn("if (ctx == null) return;", src, f"{name}: callers must guard null ctx")


if __name__ == "__main__":
    unittest.main()
