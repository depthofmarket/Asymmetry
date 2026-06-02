from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.l2_execution_engine import (
    L2ExecutionConfig,
    L2ExecutionEngine,
    L2Order,
    read_l2_order_schedule,
    simulate_l2_execution,
    write_l2_execution_result,
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
                "bid_sz_00": 3,
                "ask_sz_00": 2,
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
                "bid_sz_00": 3,
                "ask_sz_00": 2,
                "symbol": "NQ_TEST",
            },
            {
                "ts_event": "2021-01-04T14:30:00.200000Z",
                "action": "T",
                "side": "A",
                "price": 100.00,
                "size": 2,
                "bid_px_00": 100.00,
                "ask_px_00": 100.25,
                "bid_sz_00": 3,
                "ask_sz_00": 2,
                "symbol": "NQ_TEST",
            },
            {
                "ts_event": "2021-01-04T14:30:00.300000Z",
                "action": "T",
                "side": "A",
                "price": 99.75,
                "size": 5,
                "bid_px_00": 100.00,
                "ask_px_00": 100.25,
                "bid_sz_00": 3,
                "ask_sz_00": 2,
                "symbol": "NQ_TEST",
            },
            {
                "ts_event": "2021-01-04T14:30:00.400000Z",
                "action": "Q",
                "side": "",
                "price": None,
                "size": None,
                "bid_px_00": 99.75,
                "ask_px_00": 100.00,
                "bid_sz_00": 4,
                "ask_sz_00": 1,
                "symbol": "NQ_TEST",
            },
        ]
    )


class L2ExecutionEngineTests(unittest.TestCase):
    def test_market_order_fills_against_opposite_topbook_after_submit_time(self) -> None:
        result = simulate_l2_execution(
            _events(),
            [
                L2Order(
                    order_id="mkt1",
                    submit_time="2021-01-04T14:29:59.999000Z",
                    side="buy",
                    quantity=1,
                    order_type="market",
                )
            ],
        )

        order = result.orders.set_index("order_id").loc["mkt1"]
        fill = result.fills.iloc[0]
        self.assertEqual(order["status"], "filled")
        self.assertAlmostEqual(float(fill["price"]), 100.25)
        self.assertAlmostEqual(float(fill["quantity"]), 1.0)
        self.assertEqual(fill["liquidity"], "taking")

    def test_quote_rows_with_pd_na_trade_price_can_drive_taking_fills(self) -> None:
        events = pd.DataFrame(
            [
                {
                    "ts_event": "2021-01-04T14:30:00.000000Z",
                    "action": "Q",
                    "side": "",
                    "price": pd.NA,
                    "size": pd.NA,
                    "bid_px_00": 100.00,
                    "ask_px_00": 100.25,
                    "bid_sz_00": 3,
                    "ask_sz_00": 2,
                },
                {
                    "ts_event": "2021-01-04T14:30:00.100000Z",
                    "action": "Q",
                    "side": "",
                    "price": pd.NA,
                    "size": pd.NA,
                    "bid_px_00": 100.00,
                    "ask_px_00": 100.25,
                    "bid_sz_00": 3,
                    "ask_sz_00": 2,
                },
            ]
        )

        result = simulate_l2_execution(
            events,
            [L2Order(submit_time="2021-01-04T14:29:59.999000Z", side="buy", quantity=1)],
        )

        self.assertEqual(int(result.summary.loc[0, "fills"]), 1)
        self.assertAlmostEqual(float(result.fills.loc[0, "price"]), 100.25)

    def test_strategy_callback_orders_cannot_fill_on_same_event(self) -> None:
        engine = L2ExecutionEngine(_events())

        def strategy(event, broker) -> None:
            if event.event_seq == 0:
                broker.submit_market("buy", 1, tag="after_first_quote")

        result = engine.run(strategy=strategy)
        fill = result.fills.iloc[0]

        self.assertEqual(int(fill["event_seq"]), 1)
        self.assertEqual(result.orders.iloc[0]["tag"], "after_first_quote")

    def test_market_order_partial_cancels_when_topbook_depth_is_insufficient(self) -> None:
        result = simulate_l2_execution(
            _events(),
            [
                L2Order(
                    order_id="large_buy",
                    submit_time="2021-01-04T14:29:59.999000Z",
                    side="buy",
                    quantity=5,
                    order_type="market",
                )
            ],
        )

        order = result.orders.set_index("order_id").loc["large_buy"]
        fill = result.fills.iloc[0]
        self.assertEqual(order["status"], "partial_cancelled")
        self.assertAlmostEqual(float(order["filled_quantity"]), 2.0)
        self.assertTrue(bool(fill["depth_exhausted"]))
        self.assertEqual(order["cancel_reason"], "insufficient_topbook_depth")

    def test_non_topbook_limit_is_rejected_by_default(self) -> None:
        result = simulate_l2_execution(
            _events(),
            [
                L2Order(
                    order_id="deep_bid",
                    submit_time="2021-01-04T14:29:59.999000Z",
                    side="buy",
                    quantity=1,
                    order_type="limit",
                    limit_price=99.50,
                )
            ],
        )

        order = result.orders.set_index("order_id").loc["deep_bid"]
        self.assertEqual(order["status"], "rejected")
        self.assertEqual(order["reject_reason"], "non_topbook_limit_price")
        self.assertTrue(result.fills.empty)

    def test_limit_trade_through_model_waits_for_through_trade(self) -> None:
        result = simulate_l2_execution(
            _events(),
            [
                L2Order(
                    order_id="bid_limit",
                    submit_time="2021-01-04T14:29:59.999000Z",
                    side="buy",
                    quantity=1,
                    order_type="limit",
                    limit_price=100.00,
                )
            ],
        )

        fill = result.fills.iloc[0]
        self.assertEqual(int(fill["event_seq"]), 3)
        self.assertAlmostEqual(float(fill["price"]), 100.00)
        self.assertEqual(fill["reason"], "limit_trade_through")
        self.assertEqual(fill["liquidity"], "passive")

    def test_limit_queue_model_uses_displayed_best_size_as_queue_ahead(self) -> None:
        result = simulate_l2_execution(
            _events(),
            [
                L2Order(
                    order_id="bid_queue",
                    submit_time="2021-01-04T14:29:59.999000Z",
                    side="buy",
                    quantity=1,
                    order_type="limit",
                    limit_price=100.00,
                )
            ],
            config=L2ExecutionConfig(limit_fill_model="queue"),
        )

        fill = result.fills.iloc[0]
        self.assertEqual(int(fill["event_seq"]), 3)
        self.assertEqual(fill["reason"], "limit_trade_through")
        self.assertAlmostEqual(float(result.orders.set_index("order_id").loc["bid_queue", "queue_ahead"]), 1.0)

    def test_stop_market_triggers_and_takes_topbook(self) -> None:
        result = simulate_l2_execution(
            _events(),
            [
                L2Order(
                    order_id="sell_stop",
                    submit_time="2021-01-04T14:29:59.999000Z",
                    side="sell",
                    quantity=1,
                    order_type="stop_market",
                    stop_price=99.75,
                )
            ],
        )

        fill = result.fills.iloc[0]
        self.assertEqual(fill["reason"], "stop_market_triggered")
        self.assertAlmostEqual(float(fill["price"]), 100.00)
        self.assertEqual(fill["liquidity"], "taking")

    def test_read_order_schedule_and_write_result_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schedule = root / "orders.csv"
            pd.DataFrame(
                [
                    {
                        "order_id": "mkt1",
                        "submit_time": "2021-01-04T14:29:59.999000Z",
                        "side": "buy",
                        "quantity": 1,
                        "order_type": "market",
                    }
                ]
            ).to_csv(schedule, index=False)

            orders = read_l2_order_schedule(schedule)
            result = simulate_l2_execution(_events(), orders)
            paths = write_l2_execution_result(result, root / "out")

            self.assertTrue(paths["orders_csv"].exists())
            self.assertTrue(paths["fills_csv"].exists())
            self.assertIn("L2 Execution Simulation", paths["report_md"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
