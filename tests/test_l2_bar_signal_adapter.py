from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.l2_bar_signal_adapter import (
    L2BarSignalAdapterConfig,
    build_l2_scheduled_bar_signals,
)
from backtest.l2_orderflow_replay import load_l2_orderflow_strategy, run_l2_orderflow_replay


def _events() -> pd.DataFrame:
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
                "ts_event": "2021-01-04T14:30:02.000000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 100.50,
                "ask_px_00": 100.75,
                "bid_sz_00": 5,
                "ask_sz_00": 5,
            },
            {
                "ts_event": "2021-01-04T14:30:03.000000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 100.75,
                "ask_px_00": 101.00,
                "bid_sz_00": 5,
                "ask_sz_00": 5,
            },
        ]
    )


def _signal_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": ["2021-01-04 09:25:00", "2021-01-04 09:30:00"],
            "open": [99.50, 100.00],
            "close": [99.75, 100.25],
            "candidate_signal": [1.0, 0.0],
            "signal_type": ["unit", ""],
            "setup_tag": ["unit_long", ""],
        }
    )


class L2BarSignalAdapterTests(unittest.TestCase):
    def test_prepared_signal_rows_schedule_next_bar_l2_entry(self) -> None:
        signals = build_l2_scheduled_bar_signals(
            _signal_frame(),
            config=L2BarSignalAdapterConfig(signals_csv="unused.csv", quantity=2),
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].direction, "long")
        self.assertEqual(signals[0].side, "buy")
        self.assertEqual(signals[0].quantity, 2)
        self.assertEqual(str(signals[0].signal_time), "2021-01-04 14:25:00+00:00")
        self.assertEqual(str(signals[0].entry_time), "2021-01-04 14:30:00+00:00")

    def test_bar_signal_strategy_replays_entry_and_max_hold_exit_on_l2_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            signals_csv = Path(tmp) / "signals.csv"
            _signal_frame().to_csv(signals_csv, index=False)
            strategy = load_l2_orderflow_strategy(
                "bar_signal_csv",
                {
                    "signals_csv": str(signals_csv),
                    "quantity": 1,
                    "max_hold": "1s",
                },
            )

            result = run_l2_orderflow_replay(_events(), strategy)

            self.assertEqual(int(result.replay_summary.loc[0, "orders"]), 2)
            self.assertEqual(int(result.replay_summary.loc[0, "fills"]), 2)
            self.assertAlmostEqual(float(result.replay_summary.loc[0, "net_position"]), 0.0)
            self.assertAlmostEqual(float(result.replay_summary.loc[0, "realized_pnl_points"]), 0.50)
            self.assertTrue(result.execution.fills["tag"].astype(str).str.contains("bar_signal_entry").any())
            self.assertTrue(result.execution.fills["tag"].astype(str).str.contains("bar_signal_exit:max_hold").any())
            self.assertIn("bar_signal_entry_submitted", set(result.strategy_events["event_type"]))


if __name__ == "__main__":
    unittest.main()
