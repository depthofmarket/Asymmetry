from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backtest.options_surface_state import (
    OptionsSurfaceStateConfig,
    add_options_surface_state_features,
    build_options_surface_forecast_bias_diagnostics,
    build_options_surface_state,
)


def _test_config() -> OptionsSurfaceStateConfig:
    return OptionsSurfaceStateConfig(
        realized_vol_window_bars=12,
        realized_vol_min_bars=6,
        realized_vol_annualization_bars=252.0 * 390.0,
        min_forward_realized_bars=3,
        skew_abs_threshold=0.01,
        smile_curvature_threshold=0.01,
        term_spread_threshold=0.02,
        rich_iv_premium_threshold=0.03,
    )


def _dashboard() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "options_trade_date": ["2024-01-03", "2024-01-03", "2024-01-03"],
            "options_available_time": pd.to_datetime(
                ["2024-01-03 10:00:00", "2024-01-03 10:00:00", "2024-01-03 10:00:00"]
            ),
            "options_dte_bucket": ["0dte", "31_120dte", "all"],
            "options_dte_bucket_priority": [0, 3, 99],
            "options_underlying_price": [100.0, 100.0, 100.0],
            "options_avg_iv": [0.30, 0.22, 0.26],
        }
    )


def _strike_surface() -> pd.DataFrame:
    rows = []
    specs = {
        "0dte": [
            (90.0, 0.35, 0.26, 0.45, 40.0),
            (100.0, 0.20, 0.19, 0.24, 100.0),
            (110.0, 0.32, 0.25, 0.35, 60.0),
        ],
        "31_120dte": [
            (90.0, 0.26, 0.21, 0.30, 40.0),
            (100.0, 0.18, 0.17, 0.20, 100.0),
            (110.0, 0.25, 0.20, 0.29, 60.0),
        ],
        "all": [
            (90.0, 0.30, 0.24, 0.38, 80.0),
            (100.0, 0.19, 0.18, 0.23, 200.0),
            (110.0, 0.28, 0.23, 0.33, 120.0),
        ],
    }
    for bucket, values in specs.items():
        for strike, avg_iv, call_iv, put_iv, oi in values:
            rows.append(
                {
                    "options_trade_date": "2024-01-03",
                    "options_available_time": pd.Timestamp("2024-01-03 10:00:00"),
                    "options_dte_bucket": bucket,
                    "options_underlying_price": 100.0,
                    "options_strike": strike,
                    "options_distance_from_underlying_points": strike - 100.0,
                    "options_total_oi": oi,
                    "options_avg_iv": avg_iv,
                    "options_call_avg_iv": call_iv,
                    "options_put_avg_iv": put_iv,
                }
            )
    return pd.DataFrame(rows)


def _futures_bars(*, future_scale: float = 0.04) -> pd.DataFrame:
    times = pd.date_range("2024-01-03 09:30:00", periods=80, freq="min")
    increments = np.r_[np.tile([0.03, -0.02, 0.04, -0.01], 13), np.full(28, future_scale)]
    close = 100.0 + np.cumsum(increments[:80])
    return pd.DataFrame({"time": times, "close": close})


class OptionsSurfaceStateTests(unittest.TestCase):
    def test_builds_surface_shape_by_dte_bucket(self) -> None:
        state = build_options_surface_state(
            _dashboard(),
            _strike_surface(),
            futures_bars=_futures_bars(),
            config=_test_config(),
        )

        zero_dte = state.loc[state["options_dte_bucket"].eq("0dte")].iloc[0]
        self.assertEqual(float(zero_dte["options_surface_atm_strike"]), 100.0)
        self.assertAlmostEqual(float(zero_dte["options_surface_atm_iv"]), 0.20)
        self.assertGreater(float(zero_dte["options_surface_put_call_iv_skew"]), 0.0)
        self.assertGreater(float(zero_dte["options_surface_smile_curvature"]), 0.0)
        self.assertGreater(float(zero_dte["options_surface_iv_dispersion"]), 0.0)
        self.assertEqual(int(zero_dte["options_surface_valid_iv_strikes"]), 3)

    def test_term_disagreement_compares_short_and_long_atm_iv(self) -> None:
        state = build_options_surface_state(
            _dashboard(),
            _strike_surface(),
            futures_bars=_futures_bars(),
            config=_test_config(),
        )

        zero_dte = state.loc[state["options_dte_bucket"].eq("0dte")].iloc[0]
        self.assertEqual(zero_dte["options_surface_short_dte_bucket"], "0dte")
        self.assertEqual(zero_dte["options_surface_long_dte_bucket"], "31_120dte")
        self.assertAlmostEqual(float(zero_dte["options_surface_short_long_iv_spread"]), 0.02)
        self.assertIn(zero_dte["options_surface_term_state"], {"flat_term_structure", "short_dte_iv_rich"})

    def test_iv_rv_premium_does_not_change_when_future_bars_change(self) -> None:
        base_bars = _futures_bars(future_scale=0.04)
        changed_bars = base_bars.copy()
        changed_bars.loc[changed_bars["time"].gt(pd.Timestamp("2024-01-03 10:00:00")), "close"] += np.linspace(
            0.0,
            25.0,
            int(changed_bars["time"].gt(pd.Timestamp("2024-01-03 10:00:00")).sum()),
        )

        first = build_options_surface_state(_dashboard(), _strike_surface(), futures_bars=base_bars, config=_test_config())
        second = build_options_surface_state(
            _dashboard(),
            _strike_surface(),
            futures_bars=changed_bars,
            config=_test_config(),
        )

        compare_cols = [
            "options_surface_trailing_realized_vol",
            "options_surface_iv_rv_premium",
            "options_surface_iv_rv_ratio",
            "options_surface_premium_state",
        ]
        pd.testing.assert_frame_equal(
            first[compare_cols].reset_index(drop=True),
            second[compare_cols].reset_index(drop=True),
            check_exact=False,
            atol=1e-12,
            rtol=1e-12,
        )

    def test_forecast_bias_is_diagnostic_only(self) -> None:
        state = build_options_surface_state(
            _dashboard(),
            _strike_surface(),
            futures_bars=_futures_bars(),
            config=_test_config(),
        )
        self.assertFalse(any("forecast_bias" in col for col in state.columns))

        diagnostics = build_options_surface_forecast_bias_diagnostics(
            state,
            _futures_bars(future_scale=0.15),
            horizons_bars=[5],
            config=_test_config(),
        )

        self.assertFalse(diagnostics.rows.empty)
        self.assertIn("options_surface_iv_forecast_bias", diagnostics.rows.columns)
        self.assertIn("mean_iv_forecast_bias", diagnostics.summary.columns)

    def test_asof_merge_waits_until_surface_is_available(self) -> None:
        state = build_options_surface_state(
            _dashboard(),
            _strike_surface(),
            futures_bars=_futures_bars(),
            config=_test_config(),
        )
        bars = pd.DataFrame(
            {
                "time": pd.to_datetime(["2024-01-03 09:59:00", "2024-01-03 10:00:00", "2024-01-03 10:01:00"]),
                "close": [99.0, 100.0, 101.0],
            }
        )

        merged = add_options_surface_state_features(bars, state, dte_bucket="0dte")

        self.assertTrue(pd.isna(merged.loc[0, "options_surface_atm_iv"]))
        self.assertAlmostEqual(float(merged.loc[1, "options_surface_atm_iv"]), 0.20)
        self.assertAlmostEqual(float(merged.loc[2, "options_surface_atm_iv"]), 0.20)

    def test_rejects_missing_strike_surface_columns(self) -> None:
        with self.assertRaises(ValueError):
            build_options_surface_state(_dashboard(), pd.DataFrame({"options_available_time": ["2024-01-03"]}))


if __name__ == "__main__":
    unittest.main()
