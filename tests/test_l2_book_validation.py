from __future__ import annotations

import unittest

from backtest.l2_book_validation import (
    L2ActionPolicy,
    validate_l2_book_semantics,
)
from backtest.l2_mbp import parse_l2_mbp_records


class L2BookValidationTests(unittest.TestCase):
    def test_action_policy_with_set_updates_produces_sane_top_book(self) -> None:
        events = parse_l2_mbp_records(
            [
                "20201201050000000000;2;1;101.00;4;1;0",
                "20201201050000000001;2;1;101.25;3;2;0",
                "20201201050000000002;2;0;100.75;5;1;0",
                "20201201050000000003;2;0;100.50;2;2;0",
                "20201201050000000004;2;0;100.50;8;1;1",
                "20201201050000000005;2;1;101.25;0;2;2",
            ],
            source_label="synthetic",
        )
        policies = (
            L2ActionPolicy(
                name="candidate",
                set_actions=(0, 1),
                clear_actions=(2,),
                description="candidate",
            ),
        )

        artifacts = validate_l2_book_semantics(events, policies=policies, max_snapshots_per_policy=100)
        row = artifacts.summary.iloc[0]

        self.assertEqual(row["policy"], "candidate")
        self.assertGreater(float(row["valid_top_book_pct"]), 0.0)
        self.assertEqual(float(row["crossed_or_locked_pct"]), 0.0)
        self.assertLess(float(row["median_spread_ticks"]), 5.0)
        self.assertIn("bid_px_00", artifacts.snapshots.columns)
        self.assertIn("ask_px_00", artifacts.snapshots.columns)

    def test_bad_clear_policy_is_penalized_for_missing_top_book(self) -> None:
        events = parse_l2_mbp_records(
            [
                "20201201050000000000;2;1;101.00;4;1;0",
                "20201201050000000001;2;0;100.75;5;1;0",
                "20201201050000000002;2;1;101.25;3;2;0",
                "20201201050000000003;2;0;100.50;2;2;0",
            ],
            source_label="synthetic",
        )
        policies = (
            L2ActionPolicy(name="good", set_actions=(0,), clear_actions=()),
            L2ActionPolicy(name="bad", set_actions=(), clear_actions=(0,)),
        )

        artifacts = validate_l2_book_semantics(events, policies=policies)
        summary = artifacts.summary.set_index("policy")

        self.assertGreater(float(summary.loc["good", "sanity_score"]), float(summary.loc["bad", "sanity_score"]))
        self.assertEqual(float(summary.loc["bad", "valid_top_book_pct"]), 0.0)

    def test_crossed_book_policy_is_detected(self) -> None:
        events = parse_l2_mbp_records(
            [
                "20201201050000000000;2;1;101.00;4;1;0",
                "20201201050000000001;2;0;100.75;5;1;0",
                "20201201050000000002;2;0;101.25;5;1;1",
            ],
            source_label="synthetic",
        )
        policies = (
            L2ActionPolicy(name="all_set", set_actions=(0, 1), clear_actions=()),
        )

        artifacts = validate_l2_book_semantics(events, policies=policies)
        row = artifacts.summary.iloc[0]

        self.assertGreater(float(row["crossed_or_locked_pct"]), 0.0)
        self.assertLess(float(row["sanity_score"]), 1.0)

    def test_insert_update_delete_policy_shifts_depth_levels(self) -> None:
        events = parse_l2_mbp_records(
            [
                "20201201050000000000;2;1;101.00;4;1;0",
                "20201201050000000001;2;1;101.25;3;2;0",
                "20201201050000000002;2;0;100.75;5;1;0",
                "20201201050000000003;2;0;100.50;2;2;0",
                "20201201050000000004;2;0;100.90;8;1;0",
                "20201201050000000005;2;1;101.25;0;1;2",
            ],
            source_label="synthetic",
        )
        policies = (
            L2ActionPolicy(
                name="insert_update_delete",
                set_actions=(),
                clear_actions=(),
                action_operations=((0, "insert"), (1, "update"), (2, "delete")),
            ),
        )

        artifacts = validate_l2_book_semantics(events, policies=policies)
        row = artifacts.summary.iloc[0]

        self.assertEqual(float(row["crossed_or_locked_pct"]), 0.0)
        self.assertEqual(float(row["monotonic_violation_pct"]), 0.0)
        self.assertGreater(float(row["sanity_score"]), 0.25)

    def test_price_key_policy_uses_best_prices_instead_of_level_field(self) -> None:
        events = parse_l2_mbp_records(
            [
                "20201201050000000000;2;1;101.00;4;1;0",
                "20201201050000000001;2;1;101.25;3;2;0",
                "20201201050000000002;2;0;100.75;5;1;0",
                "20201201050000000003;2;0;100.50;2;2;0",
                "20201201050000000004;2;1;101.00;6;6;1",
                "20201201050000000005;2;0;100.75;4;9;1",
            ],
            source_label="synthetic",
        )
        policies = (
            L2ActionPolicy(
                name="price_key",
                set_actions=(0, 1),
                clear_actions=(2,),
                book_key="price",
            ),
        )

        artifacts = validate_l2_book_semantics(events, policies=policies)
        row = artifacts.summary.iloc[0]
        last = artifacts.snapshots.iloc[-1]

        self.assertEqual(float(row["monotonic_violation_pct"]), 0.0)
        self.assertEqual(float(last["bid_px_00"]), 100.75)
        self.assertEqual(float(last["ask_px_00"]), 101.00)


if __name__ == "__main__":
    unittest.main()
