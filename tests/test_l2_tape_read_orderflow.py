from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.l2_orderflow_replay import load_l2_orderflow_strategy, run_l2_orderflow_replay
from backtest.l2_tape_read_orderflow import L2TapeReadOrderFlowStrategy


def _long_target_events(*, spread_ticks: float = 1.0) -> pd.DataFrame:
    ask = 100.25 + (spread_ticks - 1.0) * 0.25
    return pd.DataFrame(
        [
            {
                "ts_event": "2021-01-04T14:30:00.000000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 100.00,
                "ask_px_00": ask,
                "bid_sz_00": 5,
                "ask_sz_00": 5,
            },
            {
                "ts_event": "2021-01-04T14:30:00.100000Z",
                "action": "T",
                "side": "B",
                "price": ask,
                "size": 6,
                "bid_px_00": 100.00,
                "ask_px_00": ask,
                "bid_sz_00": 12,
                "ask_sz_00": 2,
            },
            {
                "ts_event": "2021-01-04T14:30:00.200000Z",
                "action": "T",
                "side": "B",
                "price": ask,
                "size": 6,
                "bid_px_00": 100.00,
                "ask_px_00": ask,
                "bid_sz_00": 12,
                "ask_sz_00": 2,
            },
            {
                "ts_event": "2021-01-04T14:30:00.300000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 100.00,
                "ask_px_00": 100.25,
                "bid_sz_00": 12,
                "ask_sz_00": 2,
            },
            {
                "ts_event": "2021-01-04T14:30:01.000000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 100.75,
                "ask_px_00": 101.00,
                "bid_sz_00": 8,
                "ask_sz_00": 2,
            },
            {
                "ts_event": "2021-01-04T14:30:01.100000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 100.75,
                "ask_px_00": 101.00,
                "bid_sz_00": 8,
                "ask_sz_00": 2,
            },
        ]
    )


def _short_reversion_events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts_event": "2021-01-04T14:30:00.000000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 100.00,
                "ask_px_00": 100.25,
                "bid_sz_00": 5,
                "ask_sz_00": 5,
            },
            {
                "ts_event": "2021-01-04T14:30:00.100000Z",
                "action": "T",
                "side": "A",
                "price": 100.00,
                "size": 6,
                "bid_px_00": 100.00,
                "ask_px_00": 100.25,
                "bid_sz_00": 2,
                "ask_sz_00": 12,
            },
            {
                "ts_event": "2021-01-04T14:30:00.200000Z",
                "action": "T",
                "side": "A",
                "price": 100.00,
                "size": 6,
                "bid_px_00": 100.00,
                "ask_px_00": 100.25,
                "bid_sz_00": 2,
                "ask_sz_00": 12,
            },
            {
                "ts_event": "2021-01-04T14:30:00.300000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 100.00,
                "ask_px_00": 100.25,
                "bid_sz_00": 2,
                "ask_sz_00": 12,
            },
            {
                "ts_event": "2021-01-04T14:30:01.000000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 99.25,
                "ask_px_00": 99.50,
                "bid_sz_00": 2,
                "ask_sz_00": 8,
            },
            {
                "ts_event": "2021-01-04T14:30:01.100000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 99.25,
                "ask_px_00": 99.50,
                "bid_sz_00": 2,
                "ask_sz_00": 8,
            },
        ]
    )


def _write_location_csv(path: Path, *, upper: float = 100.25, lower: float = 99.00) -> None:
    pd.DataFrame(
        {
            "time": ["2021-01-04 09:29:00"],
            "vp_val": [lower],
            "vp_poc": [100.00],
            "vp_vah": [upper],
            "options_gamma_wall_strike": [upper],
            "options_gamma_environment": ["positive_gamma"],
        }
    ).to_csv(path, index=False)


def _write_trigger_csv(path: Path, *, long_ok: bool = False, short_ok: bool = True) -> None:
    pd.DataFrame(
        {
            "time": ["2021-01-04 09:29:00"],
            "mw_any_long_trigger": [long_ok],
            "mw_any_short_trigger": [short_ok],
        }
    ).to_csv(path, index=False)


class L2TapeReadOrderFlowTests(unittest.TestCase):
    def test_loader_builds_tape_read_strategy(self) -> None:
        strategy = load_l2_orderflow_strategy("tape_read_orderflow", {"min_trade_events": 2})

        self.assertIsInstance(strategy, L2TapeReadOrderFlowStrategy)
        self.assertEqual(strategy.config.min_trade_events, 2)

    def test_tape_read_strategy_enters_on_flow_and_exits_at_target(self) -> None:
        strategy = load_l2_orderflow_strategy(
            "tape_read_orderflow",
            {
                "window": "5s",
                "cooldown": "0ms",
                "min_trade_events": 2,
                "min_trade_size": 10,
                "min_aggressive_delta": 0.75,
                "min_topbook_imbalance": 0.50,
                "max_spread_ticks": 2,
                "profit_target_points": 0.50,
                "stop_loss_points": 2.0,
                "max_hold": "",
                "flatten_at_time": "",
            },
        )

        result = run_l2_orderflow_replay(_long_target_events(), strategy)

        self.assertEqual(int(result.replay_summary.loc[0, "orders"]), 2)
        self.assertEqual(int(result.replay_summary.loc[0, "fills"]), 2)
        self.assertAlmostEqual(float(result.replay_summary.loc[0, "net_position"]), 0.0)
        self.assertAlmostEqual(float(result.replay_summary.loc[0, "realized_pnl_points"]), 0.50)
        self.assertTrue(result.execution.fills["tag"].astype(str).str.contains("tape_read_entry:long").any())
        self.assertTrue(result.execution.fills["tag"].astype(str).str.contains("tape_read_exit:profit_target").any())
        self.assertIn("tape_read_entry_submitted", set(result.strategy_events["event_type"]))
        self.assertIn("tape_read_exit_submitted", set(result.strategy_events["event_type"]))

    def test_tape_read_strategy_blocks_wide_spread_entries(self) -> None:
        strategy = load_l2_orderflow_strategy(
            "tape_read_orderflow",
            {
                "window": "5s",
                "cooldown": "0ms",
                "min_trade_events": 2,
                "min_trade_size": 10,
                "min_aggressive_delta": 0.75,
                "min_topbook_imbalance": 0.50,
                "max_spread_ticks": 2,
                "flatten_at_time": "",
            },
        )

        result = run_l2_orderflow_replay(_long_target_events(spread_ticks=8.0), strategy)

        self.assertEqual(int(result.replay_summary.loc[0, "orders"]), 0)
        self.assertEqual(int(result.replay_summary.loc[0, "fills"]), 0)

    def test_profile_gex_location_context_allows_mean_reversion_short_at_upper_level(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            location_csv = Path(tmp) / "location.csv"
            _write_location_csv(location_csv)
            strategy = load_l2_orderflow_strategy(
                "tape_read_orderflow",
                {
                    "location_context_csv": str(location_csv),
                    "location_mode": "mean_reversion",
                    "window": "5s",
                    "cooldown": "0ms",
                    "min_trade_events": 2,
                    "min_trade_size": 10,
                    "min_aggressive_delta": 0.75,
                    "min_topbook_imbalance": 0.50,
                    "location_proximity_points": 1.0,
                    "gex_wall_proximity_points": 1.0,
                    "max_spread_ticks": 2,
                    "profit_target_points": 0.50,
                    "stop_loss_points": 2.0,
                    "max_hold": "",
                    "flatten_at_time": "",
                },
            )

            result = run_l2_orderflow_replay(_short_reversion_events(), strategy)

            self.assertEqual(int(result.replay_summary.loc[0, "orders"]), 2)
            self.assertEqual(int(result.replay_summary.loc[0, "fills"]), 2)
            self.assertAlmostEqual(float(result.replay_summary.loc[0, "net_position"]), 0.0)
            self.assertAlmostEqual(float(result.replay_summary.loc[0, "realized_pnl_points"]), 0.50)
            entries = result.strategy_events.loc[
                result.strategy_events["event_type"].astype(str).eq("tape_read_entry_submitted")
            ]
            self.assertEqual(entries.iloc[0]["setup_type"], "profile_gex_mean_reversion_short")
            self.assertEqual(bool(entries.iloc[0]["location_near_upper"]), True)
            self.assertEqual(entries.iloc[0]["location_gamma_environment"], "positive_gamma")

    def test_location_mode_blocks_middle_of_nowhere_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            location_csv = Path(tmp) / "location.csv"
            _write_location_csv(location_csv, upper=120.00, lower=80.00)
            strategy = load_l2_orderflow_strategy(
                "tape_read_orderflow",
                {
                    "location_context_csv": str(location_csv),
                    "location_mode": "mean_reversion",
                    "window": "5s",
                    "cooldown": "0ms",
                    "min_trade_events": 2,
                    "min_trade_size": 10,
                    "min_aggressive_delta": 0.75,
                    "min_topbook_imbalance": 0.50,
                    "location_proximity_points": 1.0,
                    "gex_wall_proximity_points": 1.0,
                    "max_spread_ticks": 2,
                    "flatten_at_time": "",
                },
            )

            result = run_l2_orderflow_replay(_short_reversion_events(), strategy)

            self.assertEqual(int(result.replay_summary.loc[0, "orders"]), 0)
            self.assertEqual(int(result.replay_summary.loc[0, "fills"]), 0)

    def test_trigger_context_blocks_and_allows_manual_orderflow_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            location_csv = Path(tmp) / "location.csv"
            blocked_trigger_csv = Path(tmp) / "trigger_blocked.csv"
            allowed_trigger_csv = Path(tmp) / "trigger_allowed.csv"
            _write_location_csv(location_csv)
            _write_trigger_csv(blocked_trigger_csv, short_ok=False)
            _write_trigger_csv(allowed_trigger_csv, short_ok=True)
            common = {
                "location_context_csv": str(location_csv),
                "location_mode": "mean_reversion",
                "trigger_mode": "any",
                "trigger_max_age": "1D",
                "window": "5s",
                "cooldown": "0ms",
                "min_trade_events": 2,
                "min_trade_size": 10,
                "min_aggressive_delta": 0.75,
                "min_topbook_imbalance": 0.50,
                "location_proximity_points": 1.0,
                "gex_wall_proximity_points": 1.0,
                "max_spread_ticks": 2,
                "profit_target_points": 0.50,
                "stop_loss_points": 2.0,
                "max_hold": "",
                "flatten_at_time": "",
            }

            blocked = load_l2_orderflow_strategy(
                "tape_read_orderflow",
                {**common, "trigger_context_csv": str(blocked_trigger_csv)},
            )
            allowed = load_l2_orderflow_strategy(
                "tape_read_orderflow",
                {**common, "trigger_context_csv": str(allowed_trigger_csv)},
            )

            blocked_result = run_l2_orderflow_replay(_short_reversion_events(), blocked)
            allowed_result = run_l2_orderflow_replay(_short_reversion_events(), allowed)

            self.assertEqual(int(blocked_result.replay_summary.loc[0, "orders"]), 0)
            self.assertEqual(int(allowed_result.replay_summary.loc[0, "orders"]), 2)
            entries = allowed_result.strategy_events.loc[
                allowed_result.strategy_events["event_type"].astype(str).eq("tape_read_entry_submitted")
            ]
            self.assertEqual(bool(entries.iloc[0]["trigger_available"]), True)
            self.assertEqual(bool(entries.iloc[0]["trigger_short_ok"]), True)
            self.assertEqual(entries.iloc[0]["trigger_mode"], "any")


if __name__ == "__main__":
    unittest.main()
