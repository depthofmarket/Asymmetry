from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.location_context import (
    LocationContextConfig,
    _profile_row,
    build_location_context,
    write_location_context_artifacts,
)


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-03 09:30:00", periods=6, freq="min"),
            "open": [17000.0, 17001.0, 17002.0, 17003.0, 17004.0, 17005.0],
            "high": [17002.0, 17003.0, 17004.0, 17005.0, 17006.0, 17007.0],
            "low": [16998.0, 16999.0, 17000.0, 17001.0, 17002.0, 17003.0],
            "close": [17001.0, 17002.0, 17003.0, 17004.0, 17005.0, 17006.0],
            "volume": [100.0, 120.0, 140.0, 160.0, 180.0, 200.0],
        }
    )


class LocationContextTests(unittest.TestCase):
    def test_profile_levels_are_point_in_time(self) -> None:
        config = LocationContextConfig(
            min_profile_bars=1,
            availability_lag="0min",
            shelf_min_volume_share=0.01,
            shelf_min_distance_points=0.25,
            volume_spike_min_periods=1,
        )
        base = _bars()
        changed_future = base.copy()
        changed_future.loc[4:, ["high", "low", "close", "volume"]] = [
            [17200.0, 17190.0, 17195.0, 10_000.0],
            [17210.0, 17200.0, 17205.0, 20_000.0],
        ]

        before = build_location_context(base, config=config).frame
        after = build_location_context(changed_future, config=config).frame
        cols = [
            "profile_poc",
            "profile_val",
            "profile_vah",
            "tpo_poc",
            "tpo_val",
            "tpo_vah",
            "profile_shelf_below",
            "profile_shelf_above",
            "profile_lower",
            "profile_upper",
        ]
        for col in cols:
            np.testing.assert_allclose(before.loc[:3, col], after.loc[:3, col], equal_nan=True)

    def test_incremental_profile_matches_reference_rebuild(self) -> None:
        config = LocationContextConfig(
            min_profile_bars=1,
            availability_lag="0min",
            shelf_min_volume_share=0.01,
            shelf_min_distance_points=0.25,
            volume_spike_min_periods=1,
        )
        bars = _bars()
        frame = build_location_context(bars, config=config).frame
        cols = [
            "profile_poc",
            "profile_val",
            "profile_vah",
            "tpo_poc",
            "tpo_val",
            "tpo_vah",
            "profile_shelf_below",
            "profile_shelf_above",
            "profile_total_volume",
            "profile_bin_count",
            "profile_shelf_count",
        ]

        for pos in range(len(bars)):
            expected = _profile_row(bars.iloc[: pos + 1], config)
            for col in cols:
                actual_value = frame.loc[pos, col]
                expected_value = expected[col]
                if pd.isna(expected_value):
                    self.assertTrue(pd.isna(actual_value), col)
                else:
                    self.assertAlmostEqual(float(actual_value), float(expected_value), places=9, msg=col)

    def test_futures_session_boundary_defaults_to_18_et(self) -> None:
        bars = pd.DataFrame(
            {
                "time": pd.to_datetime(["2024-01-07 17:59:00", "2024-01-07 18:00:00"]),
                "high": [17001.0, 17002.0],
                "low": [16999.0, 17000.0],
                "close": [17000.0, 17001.0],
                "volume": [100.0, 100.0],
            }
        )
        frame = build_location_context(
            bars,
            config=LocationContextConfig(min_profile_bars=1, availability_lag="0min"),
        ).frame

        self.assertEqual(frame.loc[0, "profile_session"], "2024-01-07")
        self.assertEqual(frame.loc[1, "profile_session"], "2024-01-08")

    def test_options_gex_and_call_put_ratios_are_merged_point_in_time(self) -> None:
        bars = pd.DataFrame(
            {
                "time": pd.to_datetime(["2024-01-03 04:59:00", "2024-01-03 05:00:00", "2024-01-03 05:01:00"]),
                "high": [17001.0, 17001.0, 17026.0],
                "low": [16999.0, 16999.0, 17024.0],
                "close": [17000.0, 17000.0, 17025.0],
                "volume": [100.0, 100.0, 100.0],
            }
        )
        flow = pd.DataFrame(
            {
                "options_available_time": pd.to_datetime(["2024-01-03 05:00:00"]),
                "options_call_oi": [10.0],
                "options_put_oi": [20.0],
                "options_net_gex": [123.0],
                "options_abs_gex": [123.0],
                "options_gamma_wall_strike": [17050.0],
                "options_gamma_environment": ["positive_gamma"],
            }
        )

        frame = build_location_context(
            bars,
            options_flow_features=flow,
            config=LocationContextConfig(min_profile_bars=1, availability_lag="0min"),
        ).frame

        self.assertTrue(pd.isna(frame.loc[0, "options_net_gex"]))
        self.assertEqual(float(frame.loc[1, "options_put_call_oi_ratio"]), 2.0)
        self.assertEqual(float(frame.loc[1, "options_call_put_oi_ratio"]), 0.5)
        self.assertEqual(float(frame.loc[2, "options_gamma_wall_distance"]), 25.0)
        self.assertEqual(frame.loc[2, "options_gamma_environment"], "positive_gamma")

    def test_volume_spike_and_orderflow_dominance_context(self) -> None:
        bars = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 09:30:00", periods=4, freq="min"),
                "high": [17001.0, 17001.0, 17001.0, 17001.0],
                "low": [16999.0, 16999.0, 16999.0, 16999.0],
                "close": [17000.0, 17000.0, 17000.0, 17000.0],
                "volume": [100.0, 100.0, 100.0, 300.0],
            }
        )
        orderflow = pd.DataFrame(
            {
                "minute": pd.to_datetime(["2024-01-03 09:31:00", "2024-01-03 09:33:00"]),
                "raw_b_minus_a_trade_size_share": [-0.30, 0.40],
            }
        )

        frame = build_location_context(
            bars,
            orderflow_minute_stats=orderflow,
            config=LocationContextConfig(
                min_profile_bars=1,
                availability_lag="0min",
                volume_spike_lookback=3,
                volume_spike_min_periods=1,
                volume_spike_multiplier=2.0,
                dominance_threshold=0.20,
            ),
        ).frame

        self.assertFalse(bool(frame.loc[0, "volume_spike"]))
        self.assertTrue(bool(frame.loc[3, "volume_spike"]))
        self.assertAlmostEqual(float(frame.loc[3, "volume_spike_ratio"]), 3.0)
        self.assertTrue(bool(frame.loc[1, "orderflow_ask_dominant"]))
        self.assertTrue(bool(frame.loc[3, "orderflow_bid_dominant"]))
        self.assertAlmostEqual(float(frame.loc[3, "orderflow_bid_ask_dominance"]), 0.40)

    def test_orderflow_merge_accepts_datetime_precision_mismatch(self) -> None:
        bars = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 09:30:00", periods=2, freq="min"),
                "high": [17001.0, 17001.0],
                "low": [16999.0, 16999.0],
                "close": [17000.0, 17000.0],
                "volume": [100.0, 100.0],
            }
        )
        orderflow = pd.DataFrame(
            {
                "minute": np.array(["2024-01-03T09:31:00.000000"], dtype="datetime64[us]"),
                "raw_b_minus_a_trade_size_share": [0.40],
            }
        )

        frame = build_location_context(
            bars,
            orderflow_minute_stats=orderflow,
            config=LocationContextConfig(
                min_profile_bars=1,
                availability_lag="0min",
                dominance_threshold=0.20,
            ),
        ).frame

        self.assertTrue(bool(frame.loc[1, "orderflow_bid_dominant"]))
        self.assertAlmostEqual(float(frame.loc[1, "orderflow_bid_ask_dominance"]), 0.40)

    def test_pre_orderflow_checkpoint_can_resume_after_profile_context(self) -> None:
        bars = _bars().head(3)
        orderflow = pd.DataFrame(
            {
                "minute": pd.to_datetime(["2024-01-03 09:31:00", "2024-01-03 09:32:00"]),
                "raw_b_minus_a_trade_size_share": [-0.30, 0.40],
            }
        )
        config = LocationContextConfig(
            min_profile_bars=1,
            availability_lag="0min",
            volume_spike_min_periods=1,
            dominance_threshold=0.20,
        )

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = Path(tmp) / "pre_orderflow.parquet"
            first = build_location_context(
                bars,
                orderflow_minute_stats=orderflow,
                config=config,
                pre_orderflow_checkpoint=checkpoint,
            ).frame
            self.assertTrue(checkpoint.exists())

            changed_bars = bars.copy()
            changed_bars["volume"] = 1_000_000.0
            resumed = build_location_context(
                changed_bars,
                orderflow_minute_stats=orderflow,
                config=config,
                pre_orderflow_checkpoint=checkpoint,
                resume_pre_orderflow_checkpoint=True,
            ).frame

        np.testing.assert_allclose(first["profile_poc"], resumed["profile_poc"], equal_nan=True)
        self.assertAlmostEqual(float(resumed.loc[2, "orderflow_bid_ask_dominance"]), 0.40)

    def test_write_artifacts(self) -> None:
        artifacts = build_location_context(
            _bars().head(2),
            config=LocationContextConfig(min_profile_bars=1, availability_lag="0min"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_location_context_artifacts(artifacts, tmp, prefix="test_context")

            self.assertTrue(Path(paths["csv"]).exists())
            self.assertTrue(Path(paths["report_md"]).exists())
            self.assertIn("Location Context", Path(paths["report_md"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
