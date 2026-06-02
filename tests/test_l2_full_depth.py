from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from backtest.l2_full_depth import (
    L2FullDepthConfig,
    build_l2_full_depth_artifacts,
    build_l2_full_depth_frame,
    write_l2_full_depth_artifacts,
)
from backtest.l2_mbp import parse_l2_mbp_records


def _decoded_events():
    return parse_l2_mbp_records(
        [
            "20210104050000000001;2;0;100.00;5;1;1",
            "20210104050000000002;2;0;99.75;4;2;1",
            "20210104050000000003;2;1;100.25;6;1;1",
            "20210104050000000004;2;1;100.50;3;2;1",
            "20210104050000010000;1;2;100.25;2",
        ],
        source_label="synthetic",
    )


class L2FullDepthTests(unittest.TestCase):
    def test_build_l2_full_depth_frame_emits_multiple_depth_levels(self) -> None:
        frame = build_l2_full_depth_frame(
            _decoded_events(),
            config=L2FullDepthConfig(policy="all_actions_set", coalesce_window="event", max_depth_levels=2),
        )

        quote = frame.loc[frame["action"].astype(str).eq("Q")].iloc[-1]
        trade = frame.loc[frame["action"].astype(str).eq("T")].iloc[0]

        self.assertIn("bid_px_01", frame.columns)
        self.assertIn("ask_sz_01", frame.columns)
        self.assertAlmostEqual(float(quote["bid_px_00"]), 100.00)
        self.assertAlmostEqual(float(quote["bid_px_01"]), 99.75)
        self.assertAlmostEqual(float(quote["ask_px_00"]), 100.25)
        self.assertAlmostEqual(float(quote["ask_px_01"]), 100.50)
        self.assertEqual(str(frame.loc[0, "book_depth_mode"]), "full_depth")
        self.assertEqual(str(trade["side"]), "B")

    def test_writer_emits_full_depth_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts = build_l2_full_depth_artifacts(
                _decoded_events(),
                config=L2FullDepthConfig(policy="all_actions_set", coalesce_window="event", max_depth_levels=2),
            )

            paths = write_l2_full_depth_artifacts(artifacts, root)

            self.assertTrue(paths["full_depth_events_csv"].exists())
            self.assertTrue(paths["quality_summary_csv"].exists())
            self.assertIn("L2 Full-Depth Replay Frame", paths["report_md"].read_text(encoding="utf-8"))

    def test_price_key_policy_is_rejected_for_full_depth(self) -> None:
        with self.assertRaisesRegex(ValueError, "level-keyed policy"):
            build_l2_full_depth_frame(
                _decoded_events(),
                config=L2FullDepthConfig(policy="price_key_all_actions_set"),
            )


if __name__ == "__main__":
    unittest.main()
