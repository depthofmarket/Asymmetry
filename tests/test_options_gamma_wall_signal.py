from __future__ import annotations

import unittest

import pandas as pd

from backtest.options_gamma_wall_signal import (
    OptionsGammaWallSignalConfig,
    build_options_gamma_wall_signal_export,
    build_options_gamma_wall_signal_frame,
)


class OptionsGammaWallSignalTests(unittest.TestCase):
    def test_signal_uses_only_available_options_flow_rows(self) -> None:
        bars = _bars(
            [
                ("2024-01-02 09:59:00", 90.0),
                ("2024-01-02 10:00:00", 90.0),
                ("2024-01-02 10:01:00", 112.0),
                ("2024-01-03 09:59:00", 90.0),
                ("2024-01-03 10:00:00", 190.0),
            ]
        )
        flow = pd.DataFrame(
            {
                "options_available_time": pd.to_datetime(["2024-01-02 10:00:00", "2024-01-03 10:00:00"]),
                "options_gamma_environment": ["positive_gamma", "positive_gamma"],
                "options_gex_regime": ["positive", "positive"],
                "options_gamma_wall_role": ["pinning_wall", "pinning_wall"],
                "options_gamma_wall_strike": [100.0, 200.0],
                "options_net_gex": [1000.0, 2000.0],
                "options_abs_gex": [1000.0, 2000.0],
                "options_total_oi": [50.0, 60.0],
            }
        )

        frame = build_options_gamma_wall_signal_frame(
            bars,
            flow,
            config=OptionsGammaWallSignalConfig(
                min_abs_wall_distance_points=5.0,
                max_abs_wall_distance_points=50.0,
                cooldown_bars=0,
            ),
        )

        self.assertEqual(float(frame.loc[0, "signal"]), 0.0)
        self.assertEqual(float(frame.loc[1, "signal"]), 1.0)
        self.assertEqual(float(frame.loc[2, "signal"]), -1.0)
        self.assertEqual(float(frame.loc[3, "options_gamma_wall_current_distance_points"]), 10.0)
        self.assertEqual(float(frame.loc[4, "options_gamma_wall_current_distance_points"]), 10.0)
        self.assertEqual(float(frame.loc[4, "signal"]), 1.0)

    def test_blocks_negative_gamma_and_stale_options_flow(self) -> None:
        negative_frame = build_options_gamma_wall_signal_frame(
            _bars([("2024-01-02 10:00:00", 90.0)]),
            pd.DataFrame(
                {
                    "options_available_time": pd.to_datetime(["2024-01-02 09:00:00"]),
                    "options_gamma_environment": ["negative_gamma"],
                    "options_gex_regime": ["negative"],
                    "options_gamma_wall_role": ["volatility_trigger"],
                    "options_gamma_wall_strike": [100.0],
                }
            ),
            config=OptionsGammaWallSignalConfig(
                min_abs_wall_distance_points=5.0,
                max_abs_wall_distance_points=50.0,
                max_options_age_days=120.0,
                cooldown_bars=0,
            ),
        )
        stale_frame = build_options_gamma_wall_signal_frame(
            _bars(
                [
                    ("2024-01-02 10:00:00", 90.0),
                    ("2024-05-15 10:00:00", 90.0),
                ]
            ),
            _positive_pinning_flow(),
            config=OptionsGammaWallSignalConfig(
                min_abs_wall_distance_points=5.0,
                max_abs_wall_distance_points=50.0,
                max_options_age_days=120.0,
                cooldown_bars=0,
            ),
        )

        self.assertEqual(int(negative_frame["signal"].ne(0).sum()), 0)
        self.assertEqual(float(stale_frame.loc[0, "signal"]), 1.0)
        self.assertEqual(float(stale_frame.loc[1, "signal"]), 0.0)
        self.assertEqual(stale_frame.loc[1, "options_flow_age_bucket"], "age_gt_120d")

    def test_export_includes_gate_columns(self) -> None:
        export = build_options_gamma_wall_signal_export(
            _bars([("2024-01-02 10:00:00", 90.0)]),
            _positive_pinning_flow(),
            config=OptionsGammaWallSignalConfig(
                min_abs_wall_distance_points=5.0,
                max_abs_wall_distance_points=50.0,
                cooldown_bars=0,
            ),
        )

        self.assertIn("candidate_signal", export.columns)
        self.assertIn("options_gamma_wall_score", export.columns)
        self.assertIn("options_flow_age_bucket", export.columns)
        self.assertIn("gamma_wall_side", export.columns)
        self.assertEqual(float(export.loc[0, "candidate_signal"]), 1.0)
        self.assertEqual(export.loc[0, "direction"], "long")


def _positive_pinning_flow() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "options_available_time": pd.to_datetime(["2024-01-02 09:00:00"]),
            "options_gamma_environment": ["positive_gamma"],
            "options_gex_regime": ["positive"],
            "options_gamma_wall_role": ["pinning_wall"],
            "options_call_wall_role": ["resistance_pin"],
            "options_put_wall_role": ["support_pin"],
            "options_gamma_wall_strike": [100.0],
            "options_call_wall_strike": [110.0],
            "options_put_wall_strike": [80.0],
            "options_net_gex": [1000.0],
            "options_abs_gex": [1000.0],
            "options_total_oi": [50.0],
        }
    )


def _bars(rows: list[tuple[str, float]]) -> pd.DataFrame:
    close = pd.Series([close for _, close in rows], dtype="float64")
    return pd.DataFrame(
        {
            "time": pd.to_datetime([time for time, _ in rows]),
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000,
        }
    )


if __name__ == "__main__":
    unittest.main()
