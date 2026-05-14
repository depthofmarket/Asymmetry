from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backtest.engine import BacktestEngine
from backtest.options_flow import (
    OptionsFlowBuildConfig,
    add_options_flow_features,
    black76_greeks,
    black76_price,
    build_options_flow_features,
    build_options_flow_features_from_source,
    implied_volatility_black76,
)


def _stats(
    *,
    ts_event: str = "2024-01-03T10:00:00Z",
    ts_ref: str = "2024-01-02T00:00:00Z",
    options: list[tuple[str, float, int, int]] | None = None,
) -> pd.DataFrame:
    rows = []
    option_rows = options or [
        ("NQF4 C17000", 100.0, 10, 4),
        ("NQF4 P17000", 95.0, 20, 6),
    ]
    for symbol, settlement, oi, volume in option_rows:
        for stat_type, price, quantity in [
            (3, settlement, 2147483647),
            (6, None, volume),
            (9, None, oi),
        ]:
            rows.append(
                {
                    "ts_event": ts_event,
                    "ts_ref": ts_ref,
                    "instrument_id": abs(hash((symbol, stat_type))) % 1_000_000,
                    "symbol": symbol,
                    "stat_type": stat_type,
                    "price": price,
                    "quantity": quantity,
                    "update_action": 1,
                }
            )
    return pd.DataFrame(rows)


class OptionsFlowTests(unittest.TestCase):
    def test_black76_iv_and_greeks_round_trip(self) -> None:
        price = black76_price(17000.0, 17000.0, 30 / 365.25, 0.25, "C")
        iv = implied_volatility_black76(price, 17000.0, 17000.0, 30 / 365.25, "C")
        greeks = black76_greeks(17000.0, 17000.0, 30 / 365.25, iv, "C")

        self.assertAlmostEqual(iv, 0.25, places=3)
        self.assertGreater(greeks["delta"], 0.45)
        self.assertGreater(greeks["gamma"], 0.0)

    def test_build_options_flow_features_and_merge_point_in_time(self) -> None:
        futures = pd.DataFrame(
            {
                "time": pd.to_datetime(["2024-01-03 04:59:00", "2024-01-03 05:00:00"]),
                "close": [17000.0, 17000.0],
            }
        )
        daily, strikes = build_options_flow_features(
            _stats(),
            futures,
            OptionsFlowBuildConfig(max_dte=30, strike_window_points=100.0),
        )

        self.assertEqual(len(daily), 1)
        self.assertFalse(strikes.empty)
        self.assertEqual(float(daily.loc[0, "options_total_oi"]), 30.0)
        self.assertIn(daily.loc[0, "options_gex_regime"], {"positive", "negative", "neutral"})
        self.assertIn(daily.loc[0, "options_gamma_environment"], {"positive_gamma", "negative_gamma", "neutral_gamma"})
        self.assertIn(daily.loc[0, "options_call_wall_role"], {"resistance_pin", "upside_amplifier", "neutral"})
        self.assertIn(daily.loc[0, "options_put_wall_role"], {"support_pin", "downside_amplifier", "neutral"})

        merged = add_options_flow_features(futures, daily)
        self.assertTrue(pd.isna(merged.loc[0, "options_net_gex"]))
        self.assertFalse(pd.isna(merged.loc[1, "options_net_gex"]))

    def test_options_flow_merge_normalizes_datetime_resolution(self) -> None:
        futures = pd.DataFrame(
            {
                "time": pd.Series(
                    pd.to_datetime(["2024-01-03 04:59:00", "2024-01-03 05:00:00"])
                ).astype("datetime64[us]"),
                "close": [17000.0, 17000.0],
            }
        )
        flow = pd.DataFrame(
            {
                "options_available_time": pd.Series(
                    pd.to_datetime(["2024-01-03 05:00:00"])
                ).astype("datetime64[ns]"),
                "options_net_gex": [123.0],
                "options_abs_gex": [123.0],
            }
        )

        merged = add_options_flow_features(futures, flow)

        self.assertTrue(pd.isna(merged.loc[0, "options_net_gex"]))
        self.assertEqual(float(merged.loc[1, "options_net_gex"]), 123.0)

    def test_build_options_flow_features_from_source_matches_in_memory_build(self) -> None:
        futures = pd.DataFrame(
            {
                "time": pd.to_datetime(
                    [
                        "2024-01-03 05:00:00",
                        "2024-02-01 05:00:00",
                    ]
                ),
                "close": [17000.0, 17100.0],
            }
        )
        day_one_member = "glbx-mdp3-20240102.statistics.csv"
        day_two_member = "glbx-mdp3-20240201.statistics.csv"
        day_one = _stats()
        day_two = _stats(
            ts_event="2024-02-01T10:00:00Z",
            ts_ref="2024-02-01T00:00:00Z",
            options=[
                ("NQH4 C17100", 110.0, 30, 5),
                ("NQH4 P17100", 90.0, 12, 3),
            ],
        )
        expected_stats = pd.concat(
            [
                day_one.assign(source_member=day_one_member),
                day_two.assign(source_member=day_two_member),
            ],
            ignore_index=True,
        )
        expected_daily, expected_strikes = build_options_flow_features(
            expected_stats,
            futures,
            OptionsFlowBuildConfig(max_dte=60, strike_window_points=150.0),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            day_one.to_csv(tmp_path / day_one_member, index=False)
            day_two.to_csv(tmp_path / day_two_member, index=False)

            daily, strikes = build_options_flow_features_from_source(
                tmp_path,
                futures,
                OptionsFlowBuildConfig(max_dte=60, strike_window_points=150.0),
            )

        pd.testing.assert_frame_equal(daily.reset_index(drop=True), expected_daily.reset_index(drop=True))
        pd.testing.assert_frame_equal(strikes.reset_index(drop=True), expected_strikes.reset_index(drop=True))

    def test_same_day_expiry_requires_max_dte_above_zero(self) -> None:
        futures = pd.DataFrame(
            {
                "time": pd.to_datetime(["2024-01-19 09:59:00", "2024-01-19 10:00:00"]),
                "close": [17000.0, 17000.0],
            }
        )
        same_day_stats = _stats(
            ts_event="2024-01-19T15:00:00Z",
            ts_ref="2024-01-19T00:00:00Z",
        )

        zero_dte_daily, _ = build_options_flow_features(
            same_day_stats,
            futures,
            OptionsFlowBuildConfig(max_dte=0, strike_window_points=100.0),
        )
        one_day_daily, _ = build_options_flow_features(
            same_day_stats,
            futures,
            OptionsFlowBuildConfig(max_dte=1, strike_window_points=100.0),
        )

        self.assertTrue(zero_dte_daily.empty)
        self.assertEqual(len(one_day_daily), 1)

    def test_context_filter_uses_gex_regime_by_signal_type(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=2, freq="5min"),
                "signal": [1, 1],
                "signal_type": ["mr", "trend"],
                "options_net_gex": [-100.0, -100.0],
                "options_abs_gex": [100.0, 100.0],
            }
        )
        engine = BacktestEngine(
            df,
            portfolio=object(),
            futures_specs={"contract_value": 20},
            strategy_params={
                "options_flow_filter": "context",
                "options_flow_allow_missing": False,
            },
        )

        out = engine.apply_options_flow_signal_filters(df)

        self.assertEqual(int(out.loc[0, "signal"]), 0)
        self.assertEqual(int(out.loc[1, "signal"]), 1)

    def test_gamma_environment_filter_uses_pin_and_amplifier_logic(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-03 10:00", periods=5, freq="5min"),
                "signal": [1, 1, 1, 1, -1],
                "signal_type": ["mr", "mr", "trend", "trend", "trend"],
                "options_net_gex": [100.0, 100.0, 100.0, -100.0, -100.0],
                "options_abs_gex": [100.0] * 5,
                "options_call_wall_distance": [20.0, 4.0, 20.0, 5.0, 50.0],
                "options_put_wall_distance": [20.0, 20.0, 20.0, 50.0, 5.0],
                "options_gamma_wall_above_distance": [20.0, 4.0, 20.0, 50.0, 50.0],
                "options_gamma_wall_below_distance": [20.0, 20.0, 20.0, 50.0, 5.0],
            }
        )
        engine = BacktestEngine(
            df,
            portfolio=object(),
            futures_specs={"contract_value": 20},
            strategy_params={
                "options_flow_filter": "gamma_environment",
                "options_flow_allow_missing": False,
                "options_flow_wall_room_points": 10.0,
                "options_flow_amplifier_trigger_points": 10.0,
                "options_flow_require_negative_gamma_amplifier": True,
            },
        )

        out = engine.apply_options_flow_signal_filters(df)

        self.assertEqual(int(out.loc[0, "signal"]), 1)   # positive gamma range/MR context
        self.assertEqual(int(out.loc[1, "signal"]), 0)   # positive gamma call wall pins/resists nearby
        self.assertEqual(int(out.loc[2, "signal"]), 0)   # trend is not the positive gamma playbook
        self.assertEqual(int(out.loc[3, "signal"]), 1)   # negative gamma call wall amplifier for long trend
        self.assertEqual(int(out.loc[4, "signal"]), -1)  # negative gamma put wall amplifier for short trend


if __name__ == "__main__":
    unittest.main()
