from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from backtest.live import PaperTradingEvent
from backtest.live_brokers import CsvOrderAuditBroker, PaperEventOrderBridge, order_intent_from_event
from backtest.live_feeds import CsvReplayFeed, FileTailBarFeed
from scripts.check_cqg_setup import collect_env_status


class LiveFeedAdapterTests(unittest.TestCase):
    def test_csv_replay_feed_emits_sorted_live_bars(self) -> None:
        data = pd.DataFrame(
            {
                "time": ["2024-01-03 10:01", "2024-01-03 10:00"],
                "open": [101.0, 100.0],
                "high": [102.0, 101.0],
                "low": [100.5, 99.5],
                "close": [101.5, 100.5],
                "volume": [20, 10],
            }
        )

        bars = list(CsvReplayFeed(data))

        self.assertEqual([bar.time for bar in bars], list(pd.to_datetime(["2024-01-03 10:00", "2024-01-03 10:01"])))
        self.assertEqual(bars[0].close, 100.5)

    def test_file_tail_feed_polls_only_new_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.csv"
            path.write_text(
                "time,open,high,low,close,volume\n"
                "2024-01-03 10:00,100,101,99,100.5,10\n",
                encoding="utf-8",
            )
            feed = FileTailBarFeed(path, start_at_end=True)
            self.assertEqual(feed.poll_once(), [])

            path.write_text(
                "time,open,high,low,close,volume\n"
                "2024-01-03 10:00,100,101,99,100.5,10\n"
                "2024-01-03 10:01,100.5,102,100,101.5,20\n",
                encoding="utf-8",
            )

            bars = feed.poll_once()

            self.assertEqual(len(bars), 1)
            self.assertEqual(bars[0].time, pd.Timestamp("2024-01-03 10:01"))
            self.assertEqual(bars[0].close, 101.5)


class LiveBrokerAdapterTests(unittest.TestCase):
    def test_order_intent_maps_entry_and_exit_sides(self) -> None:
        entry = PaperTradingEvent(
            event_type="entry_filled",
            timestamp=pd.Timestamp("2024-01-03 10:05"),
            message="entry",
            direction="short",
            setup_tag="trend_short",
            price=100.0,
            contracts=2,
        )
        exit_ = PaperTradingEvent(
            event_type="exit_filled",
            timestamp=pd.Timestamp("2024-01-03 10:10"),
            message="exit",
            direction="short",
            setup_tag="trend_short",
            price=98.0,
            contracts=2,
            reason="profit_target",
        )

        entry_order = order_intent_from_event(entry, symbol="NQ")
        exit_order = order_intent_from_event(exit_, symbol="NQ")

        self.assertEqual(entry_order.side, "SELL")
        self.assertEqual(entry_order.action, "OPEN")
        self.assertEqual(exit_order.side, "BUY")
        self.assertEqual(exit_order.action, "CLOSE")

    def test_csv_order_audit_broker_persists_order_intents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "orders.csv"
            broker = CsvOrderAuditBroker(path)
            bridge = PaperEventOrderBridge(broker, symbol="NQ")
            bridge.connect()
            event = PaperTradingEvent(
                event_type="entry_filled",
                timestamp=pd.Timestamp("2024-01-03 10:05"),
                message="entry",
                direction="long",
                setup_tag="trend_long",
                price=100.0,
                contracts=1,
            )

            order = bridge.handle_event(event)

            self.assertIsNotNone(order)
            written = pd.read_csv(path)
            self.assertEqual(written.loc[0, "side"], "BUY")
            self.assertEqual(int(written.loc[0, "quantity"]), 1)


class CqgSetupTests(unittest.TestCase):
    def test_collect_env_status_reports_missing_required_values(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            missing, present = collect_env_status(require_account=True)

        self.assertIn("CQG_USERNAME", missing)
        self.assertIn("CQG_PASSWORD", missing)
        self.assertIn("CQG_CONTRACT_SYMBOL", missing)
        self.assertIn("CQG_ACCOUNT_ID", missing)
        self.assertEqual(present, {})

    def test_collect_env_status_masks_password(self) -> None:
        env = {
            "CQG_USERNAME": "demo_user",
            "CQG_PASSWORD": "secret-password",
            "CQG_CONTRACT_SYMBOL": "F.US.ENQM26",
        }
        with patch.dict("os.environ", env, clear=True):
            missing, present = collect_env_status(require_account=False)

        self.assertEqual(missing, [])
        self.assertEqual(present["CQG_PASSWORD"], "***")
        self.assertIn("CQG_USERNAME", present)


if __name__ == "__main__":
    unittest.main()
