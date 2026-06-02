from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.l2_orderflow_replay import (
    L2TopBookImbalanceSmokeStrategy,
    load_l2_orderflow_strategy,
    run_l2_orderflow_replay,
    write_l2_orderflow_replay_result,
)


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
                "bid_sz_00": 10,
                "ask_sz_00": 1,
                "symbol": "NQ_TEST",
            },
            {
                "ts_event": "2021-01-04T14:30:00.100000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 100.00,
                "ask_px_00": 100.25,
                "bid_sz_00": 10,
                "ask_sz_00": 1,
                "symbol": "NQ_TEST",
            },
            {
                "ts_event": "2021-01-04T14:30:00.200000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 100.25,
                "ask_px_00": 100.50,
                "bid_sz_00": 1,
                "ask_sz_00": 10,
                "symbol": "NQ_TEST",
            },
            {
                "ts_event": "2021-01-04T14:30:00.300000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 100.50,
                "ask_px_00": 100.75,
                "bid_sz_00": 4,
                "ask_sz_00": 4,
                "symbol": "NQ_TEST",
            },
        ]
    )


class FirstQuoteBuyStrategy:
    name = "first_quote_buy"

    def on_event(self, event, context) -> None:
        if event.event_seq == 0:
            context.submit_market("buy", 1, tag="first_quote_buy")
            context.log("signal", side="buy")


class L2OrderFlowReplayTests(unittest.TestCase):
    def test_strategy_callback_can_submit_market_order_event_by_event(self) -> None:
        result = run_l2_orderflow_replay(_events(), FirstQuoteBuyStrategy())

        self.assertEqual(int(result.replay_summary.loc[0, "orders"]), 1)
        self.assertEqual(int(result.replay_summary.loc[0, "fills"]), 1)
        self.assertEqual(float(result.replay_summary.loc[0, "net_position"]), 1.0)
        self.assertEqual(int(result.execution.fills.iloc[0]["event_seq"]), 1)
        self.assertEqual(result.strategy_events.iloc[0]["event_type"], "signal")

    def test_imbalance_smoke_strategy_enters_and_exits_with_fifo_pnl(self) -> None:
        strategy = L2TopBookImbalanceSmokeStrategy(threshold=0.75, cooldown="0ms")

        result = run_l2_orderflow_replay(_events(), strategy)

        self.assertEqual(int(result.replay_summary.loc[0, "orders"]), 2)
        self.assertEqual(int(result.replay_summary.loc[0, "fills"]), 2)
        self.assertAlmostEqual(float(result.replay_summary.loc[0, "net_position"]), 0.0)
        self.assertAlmostEqual(float(result.replay_summary.loc[0, "realized_pnl_points"]), 0.25)
        self.assertEqual(set(result.execution.fills["tag"]), {"imbalance_long_entry", "imbalance_long_exit"})
        self.assertIn("plumbing tests, not edge evidence", result.report_md)

    def test_noop_strategy_writes_empty_order_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = run_l2_orderflow_replay(_events())
            paths = write_l2_orderflow_replay_result(result, root)

            self.assertTrue(paths["orders_csv"].exists())
            self.assertTrue(paths["fills_csv"].exists())
            self.assertTrue(paths["replay_summary_csv"].exists())
            self.assertIn("L2 Orderflow Replay", paths["report_md"].read_text(encoding="utf-8"))
            self.assertEqual(int(result.replay_summary.loc[0, "orders"]), 0)

    def test_load_builtin_strategy(self) -> None:
        strategy = load_l2_orderflow_strategy("topbook_imbalance", {"threshold": 0.8})

        self.assertIsInstance(strategy, L2TopBookImbalanceSmokeStrategy)
        self.assertAlmostEqual(strategy.threshold, 0.8)


if __name__ == "__main__":
    unittest.main()
