from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

from backtest.engine import BacktestEngine
from backtest.execution_realism import build_execution_realism_summary, build_fill_assumption_audit
from backtest.portfolio import Portfolio, Trade
from config.backtest_config import BACKTEST_CONFIG, FUTURES_SPECS, STRATEGY_PARAMS


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
    def _managed_stop_engine(self, mode: str) -> BacktestEngine:
        engine = _engine(
            managed_stop_activation_mode=mode,
            breakeven_trigger_dollars=1.0,
            breakeven_offset_points=0.5,
            breakeven_min_hold_bars=0,
            trail_trigger_dollars=0.0,
            trail_distance_points=0.0,
        )
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


if __name__ == "__main__":
    unittest.main()
