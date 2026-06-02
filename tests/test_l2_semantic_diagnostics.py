from __future__ import annotations

import unittest

from backtest.l2_mbp import parse_l2_mbp_records
from backtest.l2_semantic_diagnostics import diagnose_l2_semantics, reconstruct_l2_top_book_snapshots
from backtest.l2_book_validation import default_l2_action_policies, _prepare_depth_events


class L2SemanticDiagnosticsTests(unittest.TestCase):
    def test_diagnostics_identifies_delete_action_and_top_book(self) -> None:
        events = parse_l2_mbp_records(
            [
                "20201201050000000001;2;1;100.25;3;1;0",
                "20201201050000000002;2;1;100.50;2;2;0",
                "20201201050000000003;2;0;100.00;4;1;0",
                "20201201050000000004;2;0;99.75;5;2;0",
                "20201201050000000005;1;0;100.00;1",
                "20201201050000000006;2;1;100.50;0;2;2",
            ],
            source_label="sample",
        )

        artifacts = diagnose_l2_semantics(events, policy_names=("0_insert_1_update_2_delete",))

        self.assertFalse(artifacts.field_summary.empty)
        action2 = artifacts.depth_action_summary.loc[artifacts.depth_action_summary["action_code"].eq(2)]
        self.assertEqual(float(action2["zero_size_pct"].iloc[0]), 1.0)
        event_summary = artifacts.top_book_summary.loc[artifacts.top_book_summary["window"].eq("event")].iloc[0]
        self.assertGreater(float(event_summary["valid_top_book_pct"]), 0.0)
        self.assertIn("action_code=2", artifacts.report_md)

    def test_reconstruct_top_book_snapshots_tracks_spread(self) -> None:
        events = parse_l2_mbp_records(
            [
                "20201201050000000001;2;1;100.25;3;1;0",
                "20201201050000000002;2;0;100.00;4;1;0",
                "20201201050000000003;2;1;100.50;2;2;0",
            ],
            source_label="sample",
        )
        depth = _prepare_depth_events(events)
        policy = next(item for item in default_l2_action_policies() if item.name == "all_actions_set")

        snapshots = reconstruct_l2_top_book_snapshots(depth, policy=policy)

        valid = snapshots.loc[snapshots["valid_top_book"]]
        self.assertFalse(valid.empty)
        self.assertEqual(float(valid.iloc[0]["spread_ticks"]), 1.0)


if __name__ == "__main__":
    unittest.main()
