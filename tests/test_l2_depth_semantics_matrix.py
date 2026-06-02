from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.l2_depth_semantics_matrix import (
    L2DepthSemanticsProofConfig,
    build_l2_depth_semantics_proof,
    build_l2_depth_semantics_proof_matrix,
    write_l2_depth_semantics_proof_matrix,
)
from backtest.l2_mbp import parse_l2_mbp_records, parse_l2_mbp_structured_frame


class L2DepthSemanticsMatrixTests(unittest.TestCase):
    def test_clean_semicolon_level_book_can_be_accepted_under_relaxed_sample_thresholds(self) -> None:
        events = parse_l2_mbp_records(
            [
                "20210104050000000001;2;0;100.00;5;1;1",
                "20210104050000000002;2;0;99.75;4;2;1",
                "20210104050000000003;2;1;100.25;6;1;1",
                "20210104050000000004;2;1;100.50;3;2;1",
                "20210104050000000005;2;0;100.00;5;1;1",
                "20210104050000000006;2;1;100.25;6;1;1",
            ],
            source_label="clean",
        )

        evidence, decision = build_l2_depth_semantics_proof(
            events,
            date="20210104",
            config=L2DepthSemanticsProofConfig(
                min_depth_events=4,
                min_snapshots=4,
                min_valid_top_book_pct=0.50,
                min_median_levels_present=1.0,
                max_crossed_or_locked_pct=0.0,
                max_monotonic_violation_pct=0.0,
            ),
        )

        accepted = evidence.loc[evidence["policy"].eq("all_actions_set")].iloc[0]
        self.assertEqual(accepted["policy_proof_status"], "accepted")
        self.assertTrue(bool(decision.loc[0, "full_depth_allowed"]))
        self.assertEqual(decision.loc[0, "decision"], "full_depth_allowed")

    def test_monotonic_failure_keeps_semicolon_sample_topbook_only(self) -> None:
        events = parse_l2_mbp_records(
            [
                "20210104050000000001;2;0;100.00;5;1;1",
                "20210104050000000002;2;0;100.25;4;2;1",
                "20210104050000000003;2;1;100.50;6;1;1",
                "20210104050000000004;2;1;100.75;3;2;1",
                "20210104050000000005;2;0;100.00;5;1;1",
                "20210104050000000006;2;1;100.50;6;1;1",
            ],
            source_label="bad_depth",
        )

        evidence, decision = build_l2_depth_semantics_proof(
            events,
            date="20210104",
            config=L2DepthSemanticsProofConfig(
                min_depth_events=4,
                min_snapshots=4,
                min_valid_top_book_pct=0.50,
                min_median_levels_present=1.0,
                max_crossed_or_locked_pct=0.0,
                max_monotonic_violation_pct=0.0,
                topbook_min_valid_top_book_pct=0.50,
            ),
        )

        best = decision.iloc[0]
        self.assertFalse(bool(best["full_depth_allowed"]))
        self.assertTrue(bool(best["topbook_only_allowed"]))
        self.assertEqual(best["decision"], "topbook_only")
        self.assertTrue(evidence["policy_rejection_reason"].astype(str).str.contains("monotonic").any())

    def test_structured_schema_is_rejected_for_full_depth_without_explicit_level(self) -> None:
        events = parse_l2_mbp_structured_frame(
            pd.DataFrame(
                {
                    "raw_timestamp": ["20220103050000000001", "20220103050000000002"],
                    "msg_type": [2, 2],
                    "book_level": [1, 0],
                    "price": [100.25, 100.00],
                    "size": [2, 3],
                }
            ),
            source_label="structured",
        )

        evidence, decision = build_l2_depth_semantics_proof(events, date="20220103")

        self.assertEqual(evidence.loc[0, "policy"], "no_full_depth_policy")
        self.assertFalse(bool(decision.loc[0, "full_depth_allowed"]))
        self.assertEqual(decision.loc[0, "decision"], "rejected")
        self.assertIn("missing explicit depth level", evidence.loc[0, "policy_rejection_reason"])

    def test_matrix_dry_run_and_writer_emit_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = build_l2_depth_semantics_proof_matrix(
                root,
                target_dates=("20210104",),
                dry_run=True,
            )
            paths = write_l2_depth_semantics_proof_matrix(result, root / "out")

            self.assertTrue(paths["targets_csv"].exists())
            self.assertTrue(paths["policy_evidence_csv"].exists())
            self.assertIn("L2 Depth Semantics Proof Matrix", paths["report_md"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
