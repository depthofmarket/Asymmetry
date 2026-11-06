from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

from backtest.engine import BacktestEngine, _EXECUTION_1M_CACHE
from backtest.execution_realism import build_execution_realism_summary, build_fill_assumption_audit
from backtest.portfolio import Portfolio, Trade
from config.backtest_config import BACKTEST_CONFIG, EXECUTION_PRESETS, FUTURES_SPECS, STRATEGY_PARAMS


def _engine(**overrides) -> BacktestEngine:
    params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG}
    params.update(overrides)
    return BacktestEngine(
        pd.DataFrame(),
        Portfolio(params["starting_capital"], FUTURES_SPECS),
        FUTURES_SPECS,
        params,
    )



class TargetFillModelTests(unittest.TestCase):
    def test_touch_target_fill_mode_preserves_existing_target_behavior(self) -> None:
        engine = _engine(target_fill_mode="touch")
        hit, reason, price = engine.resolve_intrabar_exit(
            "long",
            bar_open=100.0,
            high_price=101.0,
            low_price=99.75,
            levels={"profit_target": 101.0},
        )

        self.assertTrue(hit)
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 101.0)

    def test_trade_through_target_fill_requires_one_tick_beyond_target(self) -> None:
        engine = _engine(target_fill_mode="trade_through", target_fill_trade_through_ticks=1, vp_tick_size=0.25)

        touch_hit, _, _ = engine.resolve_intrabar_exit(
            "long",
            bar_open=100.0,
            high_price=101.0,
            low_price=99.75,
            levels={"profit_target": 101.0},
        )
        through_hit, reason, price = engine.resolve_intrabar_exit(
            "long",
            bar_open=100.0,
            high_price=101.25,
            low_price=99.75,
            levels={"profit_target": 101.0},
        )

        self.assertFalse(touch_hit)
        self.assertTrue(through_hit)
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 101.0)

    def test_trade_through_target_fill_handles_shorts(self) -> None:
        engine = _engine(target_fill_mode="trade_through", target_fill_trade_through_ticks=1, vp_tick_size=0.25)

        touch_hit, _, _ = engine.resolve_intrabar_exit(
            "short",
            bar_open=100.0,
            high_price=100.25,
            low_price=99.0,
            levels={"profit_target": 99.0},
        )
        through_hit, reason, price = engine.resolve_intrabar_exit(
            "short",
            bar_open=100.0,
            high_price=100.25,
            low_price=98.75,
            levels={"profit_target": 99.0},
        )

        self.assertFalse(touch_hit)
        self.assertTrue(through_hit)
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 99.0)


class ManagedStopActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        _EXECUTION_1M_CACHE.clear()

    def tearDown(self) -> None:
        _EXECUTION_1M_CACHE.clear()

    def _managed_stop_engine(self, mode: str, **kwargs) -> BacktestEngine:
        params = {
            "managed_stop_activation_mode": mode,
            "gap_stop_fill_mode": "stop_price",
            "breakeven_trigger_dollars": 1.0,
            "breakeven_offset_points": 0.5,
            "breakeven_min_hold_bars": 0,
            "trail_trigger_dollars": 0.0,
            "trail_distance_points": 0.0,
        }
        params.update(kwargs)
        engine = _engine(**params)
        engine.data = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-02 09:30", periods=2, freq="min"),
                "open": [100.0, 100.75],
                "high": [101.0, 100.75],
                "low": [100.25, 100.25],
                "close": [100.75, 100.25],
                "volume": [100, 100],
            }
        )
        engine._execution_1m = None
        engine._execution_times = None
        return engine

    def test_default_managed_stop_can_activate_and_fill_on_same_execution_bar(self) -> None:
        engine = self._managed_stop_engine("same_bar")
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
            levels={
                "stop_loss": None,
                "profit_target": None,
                "hard_stop": None,
                "hard_target": None,
                "managed_stop": None,
            },
            entry_time=trade.entry_time,
            max_hold_minutes=10,
        )

        self.assertEqual(exit_time, pd.Timestamp("2024-01-02 09:30"))
        self.assertEqual(exit_price, 100.5)
        self.assertEqual(reason, "managed_stop")

    def test_next_bar_managed_stop_uses_prior_execution_bar_excursion(self) -> None:
        engine = self._managed_stop_engine("next_bar")
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
            levels={
                "stop_loss": None,
                "profit_target": None,
                "hard_stop": None,
                "hard_target": None,
                "managed_stop": None,
            },
            entry_time=trade.entry_time,
            max_hold_minutes=10,
        )

        self.assertEqual(exit_time, pd.Timestamp("2024-01-02 09:31"))
        self.assertEqual(exit_price, 100.5)
        self.assertEqual(reason, "managed_stop")

    def test_next_bar_managed_stop_handles_shorts(self) -> None:
        engine = _engine(
            managed_stop_activation_mode="next_bar",
            breakeven_trigger_dollars=1.0,
            breakeven_offset_points=0.5,
            breakeven_min_hold_bars=0,
            trail_trigger_dollars=0.0,
            trail_distance_points=0.0,
        )
        engine.data = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-02 09:30", periods=2, freq="min"),
                "open": [100.0, 99.25],
                "high": [100.0, 99.75],
                "low": [99.0, 99.25],
                "close": [99.25, 99.5],
                "volume": [100, 100],
            }
        )
        trade = Trade(
            entry_time=pd.Timestamp("2024-01-02 09:30"),
            entry_price=100.0,
            contracts=1,
            direction="short",
            signal_type="trend",
            setup_tag="trend_short",
        )

        exit_time, exit_price, reason = engine._simulate_trade_on_1m(
            trade,
            levels={
                "stop_loss": None,
                "profit_target": None,
                "hard_stop": None,
                "hard_target": None,
                "managed_stop": None,
            },
            entry_time=trade.entry_time,
            max_hold_minutes=10,
        )

        self.assertEqual(exit_time, pd.Timestamp("2024-01-02 09:31"))
        self.assertEqual(exit_price, 99.5)
        self.assertEqual(reason, "managed_stop")


class ExecutionRealismReportTests(unittest.TestCase):
    def test_summary_shows_target_slippage_sensitivity(self) -> None:
        trades = pd.DataFrame(
            [
                {"pnl": 100.0, "contracts": 1, "reason": "profit_target"},
                {"pnl": -50.0, "contracts": 1, "reason": "hard_stop"},
            ]
        )

        summary, by_reason = build_execution_realism_summary(
            trades,
            futures_specs=FUTURES_SPECS,
            strategy_params={"target_fill_mode": "trade_through", "target_fill_trade_through_ticks": 1},
        )

        current = summary.loc[summary["scenario"].eq("current")].iloc[0]
        default = summary.loc[summary["scenario"].eq("target_default_slippage")].iloc[0]
        stop_like = summary.loc[summary["scenario"].eq("target_stop_like_slippage")].iloc[0]
        self.assertEqual(float(current["total_pnl"]), 50.0)
        self.assertEqual(float(default["pnl_delta_vs_current"]), -15.0)
        self.assertEqual(float(stop_like["pnl_delta_vs_current"]), -35.0)
        self.assertEqual(int(by_reason.loc[by_reason["reason"].eq("profit_target"), "target_exit_trades"].iloc[0]), 1)

    def test_fill_assumption_audit_flags_touch_only_and_same_minute_exits(self) -> None:
        bars = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-02 09:30", periods=3, freq="min"),
                "open": [100.0, 100.0, 100.0],
                "high": [100.0, 110.0, 101.0],
                "low": [100.0, 89.0, 99.0],
                "close": [100.0, 95.0, 100.0],
            }
        )
        trades = pd.DataFrame(
            [
                {
                    "entry_time": "2024-01-02 09:30",
                    "exit_time": "2024-01-02 09:31",
                    "direction": "long",
                    "signal_type": "trend",
                    "setup_tag": "trend_long",
                    "entry_price": 100.0,
                    "exit_price": 110.0,
                    "contracts": 1,
                    "pnl": 100.0,
                    "reason": "profit_target",
                },
                {
                    "entry_time": "2024-01-02 09:32",
                    "exit_time": "2024-01-02 09:32",
                    "direction": "long",
                    "signal_type": "trend",
                    "setup_tag": "trend_long",
                    "entry_price": 100.0,
                    "exit_price": 99.0,
                    "contracts": 1,
                    "pnl": -10.0,
                    "reason": "hard_stop",
                },
            ]
        )

        summary, by_trade, by_reason = build_fill_assumption_audit(
            trades,
            bars,
            futures_specs={"contract_value": 10.0, "commission_per_round_trip": 0.0, "slippage_points": 0.0},
            strategy_params={
                "exit_mode": "hybrid",
                "max_loss_per_trade_dollars": 100.0,
                "max_profit_per_trade_dollars": 100.0,
                "tick_size": 0.25,
            },
        )

        self.assertEqual(int(summary.loc[0, "target_touch_only_1tick_trades"]), 1)
        self.assertEqual(int(summary.loc[0, "same_minute_exits"]), 1)
        self.assertEqual(int(summary.loc[0, "known_hard_bracket_ambiguous_trades"]), 1)
        self.assertEqual(int(summary.loc[0, "entry_cross_ordering_ambiguous_trades"]), 2)
        self.assertAlmostEqual(float(summary.loc[0, "target_fail_to_exit_bar_close_delta_1tick"]), -150.0)
        self.assertTrue(bool(by_trade.loc[0, "target_touch_only_1tick"]))
        self.assertTrue(bool(by_trade.loc[0, "known_hard_bracket_ambiguous"]))
        self.assertIn("profit_target", set(by_reason["reason"]))

    def test_fill_assumption_cli_smoke_writes_outputs(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "results" / "runs" / "unit_run"
            trades_dir = run_dir / "trades"
            trades_dir.mkdir(parents=True)
            bars_csv = root / "bars.csv"
            pd.DataFrame(
                {
                    "time": pd.date_range("2024-01-02 09:30", periods=2, freq="min"),
                    "open": [100.0, 100.0],
                    "high": [100.0, 101.0],
                    "low": [100.0, 99.0],
                    "close": [100.0, 100.5],
                    "volume": [10, 12],
                }
            ).to_csv(bars_csv, index=False)
            pd.DataFrame(
                [
                    {
                        "entry_time": "2024-01-02 09:30",
                        "exit_time": "2024-01-02 09:31",
                        "direction": "long",
                        "signal_type": "trend",
                        "setup_tag": "trend_long",
                        "entry_price": 100.0,
                        "exit_price": 101.0,
                        "contracts": 1,
                        "pnl": 13.0,
                        "reason": "profit_target",
                    }
                ]
            ).to_csv(trades_dir / "trade_log.csv", index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "scripts" / "audit_fill_assumptions.py"),
                    "--run-dir",
                    str(run_dir),
                    "--bars-csv",
                    str(bars_csv),
                ],
                cwd=repo_root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((run_dir / "research" / "fill_assumptions" / "fill_assumption_summary.csv").exists())
            self.assertTrue((run_dir / "research" / "fill_assumptions" / "fill_assumption_by_trade.csv").exists())


class GapThroughStopFillTests(unittest.TestCase):
    def test_long_gap_down_stop_fills_at_open_in_realistic_mode(self) -> None:
        """When market gaps down below long stop, fill must resolve at open, not stop price."""
        engine = _engine(gap_stop_fill_mode="open")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=95.0,
            high_price=96.0,
            low_price=94.0,
            levels={"stop_loss": 100.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 95.0, "Gap-down long stop must fill at bar open (95.0)")

    def test_short_gap_up_stop_fills_at_open_in_realistic_mode(self) -> None:
        """When market gaps up above short stop, fill must resolve at open, not stop price."""
        engine = _engine(gap_stop_fill_mode="open")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=105.0,
            high_price=106.0,
            low_price=104.0,
            levels={"stop_loss": 100.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 105.0, "Gap-up short stop must fill at bar open (105.0)")

    def test_normal_intrabar_stop_no_gap_fills_at_stop_price(self) -> None:
        """When bar open is on the safe side of stop and low/high penetrates, fill resolves at stop price."""
        engine = _engine(gap_stop_fill_mode="open")
        # Long trade, stop 100.0, open 102.0 > 100.0, low penetrates to 99.0
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=102.0,
            high_price=103.0,
            low_price=99.0,
            levels={"stop_loss": 100.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 100.0, "Normal intrabar long stop must fill at stop price (100.0)")

        # Short trade, stop 100.0, open 98.0 < 100.0, high penetrates to 101.0
        s_hit, s_reason, s_price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=98.0,
            high_price=101.0,
            low_price=97.0,
            levels={"stop_loss": 100.0},
        )
        self.assertTrue(s_hit)
        self.assertEqual(s_reason, "stop_loss")
        self.assertEqual(s_price, 100.0, "Normal intrabar short stop must fill at stop price (100.0)")

    def test_legacy_gap_stop_fill_mode_fills_at_stop_price(self) -> None:
        """Legacy mode preserves historical behavior of filling at exact stop price even during gaps."""
        engine = _engine(gap_stop_fill_mode="stop_price")
        # Long gap down
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=95.0,
            high_price=96.0,
            low_price=94.0,
            levels={"stop_loss": 100.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 100.0, "Legacy mode must return static stop price (100.0)")

        # Short gap up
        s_hit, s_reason, s_price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=105.0,
            high_price=106.0,
            low_price=104.0,
            levels={"stop_loss": 100.0},
        )
        self.assertTrue(s_hit)
        self.assertEqual(s_reason, "stop_loss")
        self.assertEqual(s_price, 100.0, "Legacy mode must return static stop price (100.0)")

    def test_gap_down_managed_and_hard_stops_fill_at_open(self) -> None:
        """Hard stops and managed stops must also obey authentic gap-fill resolution."""
        engine = _engine(gap_stop_fill_mode="open")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=94.0,
            high_price=95.0,
            low_price=93.0,
            levels={"hard_stop": 98.0, "managed_stop": 99.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "managed_stop")
        self.assertEqual(price, 94.0, "Managed stop must trigger and fill at bar open")


class StopFillModeTests(unittest.TestCase):
    def test_touch_stop_fill_mode_triggers_on_exact_touch(self) -> None:
        """Touch mode triggers stop orders when price touches the stop level."""
        engine = _engine(stop_fill_mode="touch")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=101.0,
            high_price=101.5,
            low_price=100.0,
            levels={"stop_loss": 100.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 100.0)

    def test_trade_through_stop_fill_requires_ticks_beyond_stop(self) -> None:
        """Trade-through mode requires price to penetrate beyond the stop level by specified ticks."""
        engine = _engine(
            stop_fill_mode="trade_through",
            stop_fill_trade_through_ticks=1,
            vp_tick_size=0.25,
        )
        # Touch only (low is 100.0, stop is 100.0, needs 99.75)
        touch_hit, _, _ = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=101.0,
            high_price=101.5,
            low_price=100.0,
            levels={"stop_loss": 100.0},
        )
        # Trade through by 1 tick (low is 99.75 <= 99.75)
        through_hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=101.0,
            high_price=101.5,
            low_price=99.75,
            levels={"stop_loss": 100.0},
        )
        self.assertFalse(touch_hit, "Exact touch must not trigger stop in trade-through mode")
        self.assertTrue(through_hit, "Trade-through must trigger stop")
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 100.0)

    def test_trade_through_stop_fill_handles_shorts(self) -> None:
        """Short stop trade-through requires high price to penetrate above stop level."""
        engine = _engine(
            stop_fill_mode="trade_through",
            stop_fill_trade_through_ticks=1,
            vp_tick_size=0.25,
        )
        # Touch only (high is 100.0, stop is 100.0, needs 100.25)
        touch_hit, _, _ = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=99.0,
            high_price=100.0,
            low_price=98.5,
            levels={"stop_loss": 100.0},
        )
        # Trade through by 1 tick (high is 100.25 >= 100.25)
        through_hit, reason, price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=99.0,
            high_price=100.25,
            low_price=98.5,
            levels={"stop_loss": 100.0},
        )
        self.assertFalse(touch_hit, "Exact touch must not trigger short stop in trade-through mode")
        self.assertTrue(through_hit, "Trade-through must trigger short stop")
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 100.0)

    def test_top_level_fill_mode_sets_both_targets_and_stops(self) -> None:
        """Top-level fill_mode parameter sets defaults for both targets and stops."""
        engine = _engine(fill_mode="trade_through", vp_tick_size=0.25)

        # Target: touch only (high 101.0 == target 101.0, requires 101.25) -> no fill
        t_touch, _, _ = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=101.0,
            low_price=99.5,
            levels={"profit_target": 101.0},
        )
        # Target: through (high 101.25 >= 101.25) -> fills
        t_through, t_reason, t_price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=101.25,
            low_price=99.5,
            levels={"profit_target": 101.0},
        )
        self.assertFalse(t_touch)
        self.assertTrue(t_through)
        self.assertEqual(t_reason, "profit_target")
        self.assertEqual(t_price, 101.0)

        # Stop: touch only (low 99.0 == stop 99.0, requires 98.75) -> no fill
        s_touch, _, _ = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=100.5,
            low_price=99.0,
            levels={"stop_loss": 99.0},
        )
        # Stop: through (low 98.75 <= 98.75) -> fills
        s_through, s_reason, s_price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=100.5,
            low_price=98.75,
            levels={"stop_loss": 99.0},
        )
        self.assertFalse(s_touch)
        self.assertTrue(s_through)
        self.assertEqual(s_reason, "stop_loss")
        self.assertEqual(s_price, 99.0)

    def test_top_level_fill_mode_overridden_by_specific_mode(self) -> None:
        """Specific target_fill_mode or stop_fill_mode overrides top-level fill_mode."""
        engine = _engine(
            fill_mode="trade_through",
            target_fill_mode="touch",
            vp_tick_size=0.25,
        )
        # Target fills on touch because target_fill_mode='touch'
        t_hit, t_reason, _ = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=101.0,
            low_price=99.5,
            levels={"profit_target": 101.0},
        )
        self.assertTrue(t_hit)
        self.assertEqual(t_reason, "profit_target")

        # Stop does not fill on touch because stop inherits fill_mode='trade_through'
        s_touch, _, _ = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=100.5,
            low_price=99.0,
            levels={"stop_loss": 99.0},
        )
        self.assertFalse(s_touch)


class ExecutionPresetsFillModeTests(unittest.TestCase):
    """Verify institutional_realistic and legacy_baseline presets resolve fill modes cleanly."""

    def test_institutional_realistic_resolves_trade_through_target_and_touch_stop(self) -> None:
        p = {**STRATEGY_PARAMS, **BACKTEST_CONFIG, **EXECUTION_PRESETS['institutional_realistic']}
        engine = BacktestEngine(pd.DataFrame(), Portfolio(p['starting_capital'], FUTURES_SPECS), FUTURES_SPECS, p)
        self.assertEqual(engine.get_fill_mode('target'), 'trade_through')
        self.assertEqual(engine.get_fill_mode('stop'), 'touch')

    def test_legacy_baseline_resolves_touch_modes(self) -> None:
        p = {**STRATEGY_PARAMS, **BACKTEST_CONFIG, **EXECUTION_PRESETS['legacy_baseline']}
        engine = BacktestEngine(pd.DataFrame(), Portfolio(p['starting_capital'], FUTURES_SPECS), FUTURES_SPECS, p)
        self.assertEqual(engine.get_fill_mode('target'), 'touch')
        self.assertEqual(engine.get_fill_mode('stop'), 'touch')

    def test_custom_overrides_without_private_flags(self) -> None:
        p1 = {**STRATEGY_PARAMS, **BACKTEST_CONFIG, 'fill_mode': 'trade_through', 'target_fill_mode': 'touch'}
        e1 = BacktestEngine(pd.DataFrame(), Portfolio(p1['starting_capital'], FUTURES_SPECS), FUTURES_SPECS, p1)
        self.assertEqual(e1.get_fill_mode('target'), 'touch')
        self.assertEqual(e1.get_fill_mode('stop'), 'trade_through')

        p2 = {**STRATEGY_PARAMS, **BACKTEST_CONFIG, 'fill_mode': 'touch', 'stop_fill_mode': 'trade_through'}
        e2 = BacktestEngine(pd.DataFrame(), Portfolio(p2['starting_capital'], FUTURES_SPECS), FUTURES_SPECS, p2)
        self.assertEqual(e2.get_fill_mode('target'), 'touch')
        self.assertEqual(e2.get_fill_mode('stop'), 'trade_through')


class IntrabarBracketAssumptionTests(unittest.TestCase):
    def test_conservative_assumption_prefers_stop_over_target(self) -> None:
        """When both stop and target are touched on same bar, conservative assumption selects stop."""
        engine = _engine(intrabar_exit_assumption="conservative")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=102.0,
            low_price=98.0,
            levels={"stop_loss": 99.0, "profit_target": 100.5},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 99.0)

    def test_proximity_assumption_selects_closer_level(self) -> None:
        """Proximity assumption selects the level closer to bar open."""
        engine = _engine(intrabar_exit_assumption="proximity")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=102.0,
            low_price=98.0,
            levels={"stop_loss": 98.5, "profit_target": 100.5},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 100.5)

    def test_optimistic_assumption_selects_target(self) -> None:
        """Optimistic assumption always awards target when both are hit."""
        engine = _engine(intrabar_exit_assumption="optimistic")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=100.0,
            high_price=102.0,
            low_price=98.0,
            levels={"stop_loss": 99.5, "profit_target": 101.5},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 101.5)


if __name__ == "__main__":
    unittest.main()

