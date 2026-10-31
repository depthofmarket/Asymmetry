from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.cross_asset_context import add_morning_cross_asset_features
from backtest.engine import BacktestEngine
from backtest.portfolio import Portfolio
from config.backtest_config import FUTURES_SPECS, STRATEGY_PARAMS


def _sample_5m_bars() -> pd.DataFrame:
    times = pd.to_datetime(
        [
            "2024-01-03 09:25:00",
            "2024-01-03 09:30:00",
            "2024-01-03 09:35:00",
            "2024-01-03 09:40:00",
            "2024-01-03 09:45:00",
        ]
    )
    return pd.DataFrame(
        {
            "time": times,
            "date_str": ["2024-01-03"] * len(times),
            "hour_min": ["09:25", "09:30", "09:35", "09:40", "09:45"],
            "open": [16500.0, 16505.0, 16515.0, 16525.0, 16535.0],
            "high": [16506.0, 16516.0, 16526.0, 16538.0, 16545.0],
            "low": [16498.0, 16502.0, 16512.0, 16522.0, 16532.0],
            "close": [16504.0, 16514.0, 16524.0, 16536.0, 16540.0],
            "volume": [100.0, 1000.0, 1200.0, 1500.0, 1100.0],
        }
    )


def _sample_cross_asset_table() -> pd.DataFrame:
    # Mirrors the real schema of morning_cross_asset_features_0945.parquet
    return pd.DataFrame(
        [
            {
                "date_str": "2024-01-03",
                "vx_open_930": 15.20,
                "vx_close_945": 15.10,
                "vx_high_945": 15.35,
                "vx_low_945": 15.05,
                "vx_or15_volume": 3200.0,
                "vx_prior_rth_close": 15.40,
                "vx_overnight_change_pct": (15.20 - 15.40) / 15.40,
                "vx_or15_change_pct": (15.10 - 15.20) / 15.20,
                "tick_or15_open": -120.0,
                "tick_or15_close": 85.0,
                "tick_or15_mean": -42.0,
                "tick_or15_max": 450.0,
                "tick_or15_min": -380.0,
                "vix_spot_open_930": 13.80,
                "vix_spot_close_945": 13.75,
                "vix_spot_or15_change_pct": -0.05 / 13.80,
                "spx_open_930": 4725.0,
                "spx_close_945": 4733.0,
                "spx_iv_open_930": 0.132,
                "spx_iv_close_945": 0.130,
                "spx_or15_return_pct": (4733.0 - 4725.0) / 4725.0,
                "spx_iv_or15_change_pct": -0.002 / 0.132,
                "vx_minus_vix_spot_945": 15.10 - 13.75,
            }
        ]
    )


def test_cross_asset_point_in_time_masking():
    bars = _sample_5m_bars()
    feat = _sample_cross_asset_table()
    merged = add_morning_cross_asset_features(
        bars,
        feat,
        rth_start="09:30",
        or15_available_at="09:40",
    )

    # Pre-09:30 bar has neither 09:30 open nor 09:45 OR15 features
    row_925 = merged.loc[merged["hour_min"] == "09:25"].iloc[0]
    assert np.isnan(row_925["vx_open_930"])
    assert np.isnan(row_925["vx_close_945"])
    assert np.isnan(row_925["tick_or15_mean"])

    # 09:30 and 09:35 bars have 09:30 open values, but OR15 09:45 values are still masked
    for hm in ("09:30", "09:35"):
        row = merged.loc[merged["hour_min"] == hm].iloc[0]
        assert np.isclose(row["vx_open_930"], 15.20)
        assert np.isclose(row["spx_open_930"], 4725.0)
        assert np.isnan(row["vx_close_945"])
        assert np.isnan(row["tick_or15_mean"])
        assert np.isnan(row["spx_iv_close_945"])
        assert np.isnan(row["vx_minus_vix_spot_945"])
        assert np.isnan(row["vx_or15_change"])

    # At 09:40 (the 5m bar closing at 09:45) and 09:45, all OR15 values are available
    for hm in ("09:40", "09:45"):
        row = merged.loc[merged["hour_min"] == hm].iloc[0]
        assert np.isclose(row["vx_close_945"], 15.10)
        assert np.isclose(row["tick_or15_mean"], -42.0)
        assert np.isclose(row["spx_iv_close_945"], 0.130)
        assert np.isclose(row["vx_minus_vix_spot_945"], 1.35)
        assert np.isclose(row["vx_or15_change"], -0.10)


def test_cross_asset_signal_filters():
    bars = add_morning_cross_asset_features(_sample_5m_bars(), _sample_cross_asset_table())
    bars["signal"] = [0, 0, 0, 1, 0]
    bars["signal_type"] = ["", "", "", "va_breakout", ""]

    # 1. vx_min_level=16.0 blocks when vx_close_945=15.10
    p1 = dict(STRATEGY_PARAMS, cross_asset_filter="vx_min_level", cross_asset_min_vx_close_945=16.0)
    eng1 = BacktestEngine(bars, Portfolio(100000.0, FUTURES_SPECS), FUTURES_SPECS, p1)
    out1 = eng1.apply_cross_asset_signal_filters(bars)
    assert int(out1.loc[out1["hour_min"] == "09:40", "signal"].iloc[0]) == 0

    # 2. vx_compressing_on_long passes when vx_or15_change = -0.10 <= 0.0
    p2 = dict(STRATEGY_PARAMS, cross_asset_filter="vx_compressing_on_long", cross_asset_max_vx_or15_change_long=0.0)
    eng2 = BacktestEngine(bars, Portfolio(100000.0, FUTURES_SPECS), FUTURES_SPECS, p2)
    out2 = eng2.apply_cross_asset_signal_filters(bars)
    assert int(out2.loc[out2["hour_min"] == "09:40", "signal"].iloc[0]) == 1

    # 3. spx_iv_min_level=0.14 blocks when spx_iv_close_945=0.130
    p3 = dict(STRATEGY_PARAMS, cross_asset_filter="spx_iv_min_level", cross_asset_min_spx_iv_945=0.14)
    eng3 = BacktestEngine(bars, Portfolio(100000.0, FUTURES_SPECS), FUTURES_SPECS, p3)
    out3 = eng3.apply_cross_asset_signal_filters(bars)
    assert int(out3.loc[out3["hour_min"] == "09:40", "signal"].iloc[0]) == 0


    # 4. vx_compressing_on_long actually blocks when VX rose during OR15 (regression for no-op bug)
    rising = _sample_cross_asset_table()
    rising.loc[0, "vx_close_945"] = 15.40  # +0.20 vs 15.20 open
    bars_r = add_morning_cross_asset_features(_sample_5m_bars(), rising)
    bars_r["signal"] = [0, 0, 0, 1, 0]
    bars_r["signal_type"] = ["", "", "", "va_breakout", ""]
    out4 = eng2.apply_cross_asset_signal_filters(bars_r)
    assert int(out4.loc[out4["hour_min"] == "09:40", "signal"].iloc[0]) == 0

    # 5. spx_direction_confirm and vix_contango read real columns
    p5 = dict(STRATEGY_PARAMS, cross_asset_filter="spx_direction_confirm")
    eng5 = BacktestEngine(bars, Portfolio(100000.0, FUTURES_SPECS), FUTURES_SPECS, p5)
    bars_neg = bars.copy()
    bars_neg["spx_or15_return_pct"] = -0.001
    assert int(eng5.apply_cross_asset_signal_filters(bars_neg).loc[3, "signal"]) == 0
    p6 = dict(STRATEGY_PARAMS, cross_asset_filter="vix_contango")
    eng6 = BacktestEngine(bars, Portfolio(100000.0, FUTURES_SPECS), FUTURES_SPECS, p6)
    bars_bw = bars.copy()
    bars_bw["vx_minus_vix_spot_945"] = -0.5
    assert int(eng6.apply_cross_asset_signal_filters(bars_bw).loc[3, "signal"]) == 0


def test_real_feature_file_schema():
    """Every column a filter reads must exist in the real generated feature file."""
    import pytest
    from backtest.cross_asset_context import (
        ALL_CROSS_ASSET_COLUMNS,
        DEFAULT_CROSS_ASSET_FEATURES_PATH,
        load_morning_cross_asset_features,
    )

    if not DEFAULT_CROSS_ASSET_FEATURES_PATH.exists():
        pytest.skip("real cross-asset feature file not generated")
    feat = load_morning_cross_asset_features(DEFAULT_CROSS_ASSET_FEATURES_PATH)
    missing = [c for c in ALL_CROSS_ASSET_COLUMNS if c not in feat.columns]
    assert not missing, f"declared cross-asset columns missing from real file: {missing}"
    for col in ("vx_close_945", "vx_or15_change", "spx_or15_return_pct", "spx_iv_close_945",
                "tick_or15_mean", "vx_minus_vix_spot_945"):
        assert feat[col].notna().sum() > 1000, f"{col} is mostly empty"
