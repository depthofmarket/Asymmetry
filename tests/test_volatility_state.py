from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backtest.volatility_state import (
    VOLATILITY_STATE_FEATURE_COLUMNS,
    VolatilityStateConfig,
    add_volatility_state_features,
)


class VolatilityStateTests(unittest.TestCase):
    def test_adds_expected_columns_without_signal_columns(self) -> None:
        frame = add_volatility_state_features(_sample_bars(), config=_test_config(include_markov=False))

        for col in VOLATILITY_STATE_FEATURE_COLUMNS:
            self.assertIn(col, frame.columns)
        self.assertNotIn("signal", frame.columns)
        self.assertNotIn("candidate_signal", frame.columns)

    def test_features_do_not_change_when_future_rows_change(self) -> None:
        base = _sample_bars()
        changed = base.copy()
        cutoff = 90
        changed.loc[cutoff + 1 :, "close"] += np.linspace(25.0, 80.0, len(changed) - cutoff - 1)
        changed.loc[cutoff + 1 :, "high"] = changed.loc[cutoff + 1 :, "close"] + 5.0
        changed.loc[cutoff + 1 :, "low"] = changed.loc[cutoff + 1 :, "close"] - 5.0

        kwargs = _test_config(include_markov=True)
        first = add_volatility_state_features(base, config=kwargs)
        second = add_volatility_state_features(changed, config=kwargs)

        compare_cols = [
            "realized_vol_short",
            "realized_vol_long",
            "realized_vol_ratio",
            "volatility_range_ratio",
            "volatility_jump_threshold",
            "volatility_jump_score",
            "volatility_roughness_hurst",
            "volatility_state",
            "markov_state",
            "markov_state_label",
        ]
        for col in compare_cols:
            left = first.loc[:cutoff, col].reset_index(drop=True)
            right = second.loc[:cutoff, col].reset_index(drop=True)
            if pd.api.types.is_numeric_dtype(left):
                np.testing.assert_allclose(left.to_numpy(dtype=float), right.to_numpy(dtype=float), equal_nan=True)
            else:
                self.assertEqual(left.tolist(), right.tolist())

    def test_labels_compressed_then_expanded_volatility(self) -> None:
        data = _regime_bars()
        frame = add_volatility_state_features(data, config=_test_config(include_markov=False))

        compressed_tail = frame.loc[70:100, "volatility_compression_state"]
        expanded_tail = frame.loc[145:, "volatility_compression_state"]

        self.assertIn("compressed_volatility", set(compressed_tail.dropna()))
        self.assertIn("expanded_volatility", set(expanded_tail.dropna()))

    def test_jump_event_uses_prior_threshold(self) -> None:
        data = _sample_bars(n=110)
        data.loc[80, "close"] = data.loc[79, "close"] + 12.0
        data.loc[80, "high"] = data.loc[80, "close"] + 2.0
        data.loc[80, "low"] = data.loc[79, "close"] - 1.0

        frame = add_volatility_state_features(data, config=_test_config(include_markov=False))

        self.assertTrue(bool(frame.loc[80, "volatility_jump_event"]))
        self.assertGreater(float(frame.loc[80, "volatility_jump_score"]), 1.0)

    def test_markov_integration_can_be_enabled(self) -> None:
        frame = add_volatility_state_features(_regime_bars(), config=_test_config(include_markov=True))

        self.assertIn("markov_state_label", frame.columns)
        self.assertIn("markov_state_confidence", frame.columns)
        self.assertTrue(frame["markov_state_label"].astype(str).str.len().gt(0).any())

    def test_rejects_non_point_in_time_window_shape(self) -> None:
        with self.assertRaises(ValueError):
            add_volatility_state_features(
                _sample_bars(),
                config=VolatilityStateConfig(short_window_bars=20, long_window_bars=20),
            )


def _test_config(*, include_markov: bool) -> VolatilityStateConfig:
    return VolatilityStateConfig(
        short_window_bars=8,
        long_window_bars=24,
        min_short_bars=4,
        min_long_bars=12,
        compression_ratio_threshold=0.75,
        expansion_ratio_threshold=1.25,
        vol_of_vol_window_bars=12,
        vol_of_vol_reference_bars=24,
        jump_window_bars=30,
        jump_min_bars=20,
        jump_quantile=0.95,
        roughness_window_bars=48,
        roughness_min_bars=32,
        roughness_recompute_every_bars=1,
        include_markov_regime=include_markov,
        markov_calibration_bars=24,
        markov_min_calibration_bars=18,
        markov_refit_every_bars=6,
    )


def _sample_bars(n: int = 140) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    returns = rng.normal(0.02, 0.12, n)
    close = 100.0 + np.cumsum(returns)
    spread = np.full(n, 0.35)
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-02 09:30", periods=n, freq="min"),
            "open": close - returns,
            "high": np.maximum(close, close - returns) + spread,
            "low": np.minimum(close, close - returns) - spread,
            "close": close,
            "volume": rng.integers(100, 400, n),
        }
    )


def _regime_bars() -> pd.DataFrame:
    rng = np.random.default_rng(23)
    returns = np.r_[
        rng.normal(0.01, 0.22, 45),
        rng.normal(0.005, 0.03, 60),
        rng.normal(0.00, 0.65, 55),
    ]
    close = 100.0 + np.cumsum(returns)
    spread = np.r_[np.full(45, 0.80), np.full(60, 0.01), np.full(55, 0.90)]
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-03 09:30", periods=len(close), freq="min"),
            "open": close - returns,
            "high": np.maximum(close, close - returns) + spread,
            "low": np.minimum(close, close - returns) - spread,
            "close": close,
            "volume": 1000,
        }
    )


if __name__ == "__main__":
    unittest.main()
