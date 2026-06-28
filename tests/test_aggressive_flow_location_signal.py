from __future__ import annotations

import unittest

import pandas as pd

from backtest.aggressive_flow_location_signal import (
    AggressiveFlowLocationSignalConfig,
    build_aggressive_flow_location_signal_export,
    build_aggressive_flow_location_signal_frame,
)


class AggressiveFlowLocationSignalTests(unittest.TestCase):
    def test_builds_long_and_short_signals_from_completed_context(self) -> None:
        bars = _bars()
        bars.loc[6, ["open", "high", "low", "close"]] = [100.0, 102.25, 99.75, 102.0]
        bars.loc[8, ["open", "high", "low", "close"]] = [100.0, 100.25, 97.75, 98.0]
        context = _location_context(bars["time"])
        context.loc[6, ["profile_lower", "profile_upper", "vp_val", "vp_vah", "orderflow_bid_ask_dominance"]] = [
            98.0,
            101.0,
            98.5,
            101.0,
            0.50,
        ]
        context.loc[8, ["profile_lower", "profile_upper", "vp_val", "vp_vah", "orderflow_bid_ask_dominance"]] = [
            99.0,
            102.0,
            99.0,
            101.5,
            -0.55,
        ]

        frame = build_aggressive_flow_location_signal_frame(bars, context, config=_test_config())

        self.assertEqual(float(frame.loc[6, "signal"]), 1.0)
        self.assertEqual(frame.loc[6, "profile_acceptance_state"], "accepted_above_profile")
        self.assertEqual(frame.loc[6, "orderflow_state"], "raw_b_side_dominant")
        self.assertEqual(float(frame.loc[8, "signal"]), -1.0)
        self.assertEqual(frame.loc[8, "profile_acceptance_state"], "accepted_below_profile")
        self.assertEqual(frame.loc[8, "orderflow_state"], "raw_a_side_dominant")

    def test_future_rows_do_not_change_prior_signal(self) -> None:
        bars = _bars()
        bars.loc[6, ["open", "high", "low", "close"]] = [100.0, 102.25, 99.75, 102.0]
        context = _location_context(bars["time"])
        context.loc[6, ["profile_lower", "profile_upper", "vp_val", "vp_vah", "orderflow_bid_ask_dominance"]] = [
            98.0,
            101.0,
            98.5,
            101.0,
            0.50,
        ]
        mutated_bars = bars.copy()
        mutated_context = context.copy()
        mutated_bars.loc[7:, "close"] = mutated_bars.loc[7:, "close"] + 25.0
        mutated_context.loc[7:, "orderflow_bid_ask_dominance"] = -1.0

        frame = build_aggressive_flow_location_signal_frame(bars, context, config=_test_config())
        changed = build_aggressive_flow_location_signal_frame(mutated_bars, mutated_context, config=_test_config())

        pd.testing.assert_series_equal(frame.loc[:6, "signal"], changed.loc[:6, "signal"])
        pd.testing.assert_series_equal(
            frame.loc[:6, "aggressive_flow_location_score"],
            changed.loc[:6, "aggressive_flow_location_score"],
        )

    def test_stale_location_context_blocks_signal(self) -> None:
        bars = _bars()
        bars.loc[10, ["open", "high", "low", "close"]] = [100.0, 102.25, 99.75, 102.0]
        stale_context = _location_context(pd.Series([bars.loc[0, "time"]]))
        stale_context.loc[0, ["profile_lower", "profile_upper", "vp_val", "vp_vah", "orderflow_bid_ask_dominance"]] = [
            98.0,
            101.0,
            98.5,
            101.0,
            0.50,
        ]

        frame = build_aggressive_flow_location_signal_frame(bars, stale_context, config=_test_config())

        self.assertEqual(float(frame.loc[10, "signal"]), 0.0)
        self.assertFalse(bool(frame.loc[10, "location_context_fresh"]))

    def test_allow_inside_value_relaxes_location_acceptance_gate(self) -> None:
        bars = _bars()
        bars.loc[6, ["open", "high", "low", "close"]] = [100.0, 102.25, 99.75, 102.0]
        context = _location_context(bars["time"])
        context.loc[6, ["profile_lower", "profile_upper", "vp_val", "vp_vah", "orderflow_bid_ask_dominance"]] = [
            98.0,
            103.0,
            98.5,
            103.0,
            0.50,
        ]
        strict = build_aggressive_flow_location_signal_frame(bars, context, config=_test_config())
        relaxed = build_aggressive_flow_location_signal_frame(
            bars,
            context,
            config=AggressiveFlowLocationSignalConfig(
                **{**_test_config().__dict__, "require_profile_acceptance": False}
            ),
        )

        self.assertEqual(float(strict.loc[6, "signal"]), 0.0)
        self.assertEqual(float(relaxed.loc[6, "signal"]), 1.0)

    def test_export_includes_signal_gate_columns(self) -> None:
        bars = _bars()
        bars.loc[6, ["open", "high", "low", "close"]] = [100.0, 102.25, 99.75, 102.0]
        context = _location_context(bars["time"])
        context.loc[6, ["profile_lower", "profile_upper", "vp_val", "vp_vah", "orderflow_bid_ask_dominance"]] = [
            98.0,
            101.0,
            98.5,
            101.0,
            0.50,
        ]

        export = build_aggressive_flow_location_signal_export(bars, context, config=_test_config())

        self.assertIn("candidate_signal", export.columns)
        self.assertIn("aggressive_flow_location_score", export.columns)
        self.assertIn("profile_acceptance_state", export.columns)
        self.assertIn("orderflow_state", export.columns)
        self.assertEqual(float(export.loc[6, "candidate_signal"]), 1.0)
        self.assertEqual(export.loc[6, "setup_tag"], "aggressive_flow_location_long")


def _test_config() -> AggressiveFlowLocationSignalConfig:
    return AggressiveFlowLocationSignalConfig(
        min_abs_flow_share=0.35,
        min_price_change_points=1.0,
        min_score=1.0,
        value_acceptance_buffer_points=0.5,
        profile_acceptance_buffer_points=0.5,
        max_context_age="5min",
        trade_start="09:30",
        trade_end="10:00",
        score_price_scale_points=2.0,
    )


def _bars() -> pd.DataFrame:
    times = pd.date_range("2024-01-03 09:30", periods=12, freq="1min")
    return pd.DataFrame(
        {
            "time": times,
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "close": 100.0,
            "volume": 1000,
        }
    )


def _location_context(times: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.to_datetime(times),
            "context_available_time": pd.to_datetime(times),
            "source_bar_time": pd.to_datetime(times) - pd.Timedelta(minutes=1),
            "profile_lower": 98.0,
            "profile_upper": 102.0,
            "vp_val": 98.5,
            "vp_vah": 101.5,
            "orderflow_bid_ask_dominance": 0.0,
            "volume_spike_ratio": 1.0,
        }
    )


if __name__ == "__main__":
    unittest.main()
