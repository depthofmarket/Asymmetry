from __future__ import annotations

import unittest

import pandas as pd

from backtest.l2_mbp import parse_l2_mbp_records, parse_l2_mbp_structured_frame
from backtest.l2_topbook_execution import (
    L2TopBookExecutionConfig,
    build_l2_topbook_execution_artifacts,
    build_l2_topbook_frame,
    resolve_l2_topbook_policy,
)


class L2TopBookExecutionTests(unittest.TestCase):
    def test_build_l2_topbook_frame_maps_quotes_and_type1_trades(self) -> None:
        events = parse_l2_mbp_records(
            [
                "20210104050000000001;2;1;100.25;2;1;0",
                "20210104050000000002;2;0;100.00;3;1;0",
                "20210104050000100000;1;2;100.25;2",
                "20210104050000200000;1;2;100.00;1",
                "20210104050000300000;1;3;0;30000",
            ],
            source_label="sample",
        )

        frame = build_l2_topbook_frame(
            events,
            config=L2TopBookExecutionConfig(symbol="NQ_TEST", coalesce_window="event"),
        )

        self.assertEqual(set(frame["symbol"]), {"NQ_TEST"})
        self.assertEqual(int(frame["is_trade"].sum()), 2)
        self.assertEqual(set(frame.loc[frame["is_trade"], "side"].astype(str)), {"A", "B"})
        self.assertTrue(frame["spread_ticks"].dropna().eq(1.0).all())

    def test_build_l2_topbook_execution_artifacts_produces_tbbo_compatible_minute_stats(self) -> None:
        events = parse_l2_mbp_records(
            [
                "20210104050000000001;2;1;100.25;2;1;0",
                "20210104050000000002;2;0;100.00;3;1;0",
                "20210104050000100000;1;2;100.25;2",
                "20210104050000200000;1;2;100.00;1",
            ],
            source_label="sample",
        )

        artifacts = build_l2_topbook_execution_artifacts(
            events,
            config=L2TopBookExecutionConfig(symbol="NQ_TEST", coalesce_window="event"),
        )

        self.assertFalse(artifacts.minute_stats.empty)
        minute = artifacts.minute_stats.iloc[0]
        self.assertEqual(minute["symbol"], "NQ_TEST")
        self.assertEqual(int(minute["trade_count"]), 2)
        self.assertEqual(int(minute["raw_b_side_count"]), 1)
        self.assertEqual(int(minute["raw_a_side_count"]), 1)
        self.assertAlmostEqual(float(minute["median_spread_points"]), 0.25)
        self.assertFalse(artifacts.quality_summary.empty)
        self.assertIn("full-depth MBP-10 reconstruction is still disabled", artifacts.report_md)

    def test_auto_policy_uses_price_key_for_structured_five_column_events(self) -> None:
        events = parse_l2_mbp_structured_frame(
            pd.DataFrame(
                {
                    "raw_timestamp": [
                        "20220103050000000001",
                        "20220103050000000002",
                        "20220103050000100000",
                    ],
                    "msg_type": [2, 2, 1],
                    "book_level": [1, 0, 2],
                    "price": [100.25, 100.00, 100.25],
                    "size": [2, 3, 1],
                }
            ),
            source_label="structured",
        )

        policy = resolve_l2_topbook_policy(events, requested_policy="auto")
        artifacts = build_l2_topbook_execution_artifacts(
            events,
            config=L2TopBookExecutionConfig(symbol="NQ_STRUCT", coalesce_window="event", policy="auto"),
        )

        self.assertEqual(policy.name, "price_key_all_actions_set")
        self.assertFalse(artifacts.minute_stats.empty)
        self.assertEqual(artifacts.quality_summary.loc[0, "policy"], "price_key_all_actions_set")
        self.assertEqual(artifacts.quality_summary.loc[0, "source_schemas"], "structured_5col:3")
        self.assertEqual(int(artifacts.minute_stats.iloc[0]["trade_count"]), 1)


if __name__ == "__main__":
    unittest.main()
