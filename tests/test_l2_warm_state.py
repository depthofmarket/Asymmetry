from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from backtest.l2_mbp import L2ParquetSourceRef
from backtest.l2_topbook_execution import L2TopBookExecutionConfig
from backtest.l2_warm_state import (
    L2WarmStateWindowConfig,
    build_l2_warm_state_topbook_execution_artifacts,
)


try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    pa = None
    pq = None


class L2WarmStateTests(unittest.TestCase):
    @unittest.skipIf(pa is None or pq is None, "pyarrow is required")
    def test_warm_state_sampler_aligns_early_window_trade_to_pre_window_book(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "structured.parquet"
            table = pa.table(
                {
                    "raw_timestamp": [
                        "20220103142950000000",
                        "20220103142951000000",
                        "20220103143000000000",
                        "20220103143001000000",
                        "20220103143002000000",
                    ],
                    "msg_type": [2, 2, 1, 2, 1],
                    "book_level": [1, 0, 2, 1, 2],
                    "price": [100.25, 100.00, 100.25, 100.50, 100.00],
                    "size": [4, 5, 2, 3, 1],
                }
            )
            pq.write_table(table, path, row_group_size=2)

            artifacts = build_l2_warm_state_topbook_execution_artifacts(
                L2ParquetSourceRef(source_path=path, label="structured"),
                window_config=L2WarmStateWindowConfig(
                    window_start="2022-01-03 09:30:00",
                    window_end="2022-01-03 09:31:00",
                ),
                execution_config=L2TopBookExecutionConfig(
                    symbol="NQ_WARM",
                    coalesce_window="event",
                    policy="price_key_all_actions_set",
                ),
            )

            self.assertFalse(artifacts.topbook_events.empty)
            self.assertEqual(int(artifacts.topbook_events["is_trade"].sum()), 2)
            first_trade = artifacts.topbook_events.loc[artifacts.topbook_events["is_trade"]].iloc[0]
            self.assertAlmostEqual(float(first_trade["bid_px_00"]), 100.00)
            self.assertAlmostEqual(float(first_trade["ask_px_00"]), 100.25)
            self.assertFalse(artifacts.minute_stats.empty)
            self.assertEqual(int(artifacts.minute_stats.iloc[0]["trade_count"]), 2)
            summary = artifacts.warm_state_summary.iloc[0]
            self.assertTrue(bool(summary["warm_start_valid_top_book"]))
            self.assertEqual(int(summary["window_type1_rows"]), 2)
            self.assertIn("Trades are aligned to uncoalesced prior quotes", artifacts.report_md)

    @unittest.skipIf(pa is None or pq is None, "pyarrow is required")
    def test_warm_state_sampler_reports_invalid_warm_start_when_book_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "structured.parquet"
            table = pa.table(
                {
                    "raw_timestamp": ["20220103143000000000", "20220103143001000000"],
                    "msg_type": [2, 1],
                    "book_level": [1, 2],
                    "price": [100.25, 100.25],
                    "size": [4, 1],
                }
            )
            pq.write_table(table, path)

            artifacts = build_l2_warm_state_topbook_execution_artifacts(
                L2ParquetSourceRef(source_path=path, label="structured"),
                window_config=L2WarmStateWindowConfig(
                    window_start="2022-01-03 09:30:00",
                    window_end="2022-01-03 09:31:00",
                ),
                execution_config=L2TopBookExecutionConfig(
                    symbol="NQ_WARM",
                    coalesce_window="event",
                    policy="price_key_all_actions_set",
                ),
            )

            summary = artifacts.warm_state_summary.iloc[0]
            self.assertFalse(bool(summary["warm_start_valid_top_book"]))
            self.assertIn("warm start did not have a valid non-crossed top book", summary["warnings"])


if __name__ == "__main__":
    unittest.main()
