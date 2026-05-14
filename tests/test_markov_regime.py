from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.markov_regime import GaussianMarkovRegimeModel, add_markov_regime_features


def _bars(ranges: list[float]) -> pd.DataFrame:
    rows = []
    base = 17000.0
    for idx, span in enumerate(ranges):
        close = base + idx * 0.25
        rows.append(
            {
                "time": pd.Timestamp("2024-01-02 09:30") + pd.Timedelta(minutes=5 * idx),
                "open": close,
                "high": close + span / 2.0,
                "low": close - span / 2.0,
                "close": close,
                "volume": 100,
            }
        )
    return pd.DataFrame(rows)


class MarkovRegimeTests(unittest.TestCase):
    def test_model_classifies_larger_volatility_as_higher_state(self) -> None:
        model = GaussianMarkovRegimeModel(n_states=3, smoothing=0.1)
        observations = [0.00005] * 20 + [0.0002] * 20 + [0.001] * 20

        self.assertTrue(model.calibrate(observations))
        low_state, _ = model.update(0.00005)
        high_state, _ = model.update(0.0012)

        self.assertLessEqual(low_state, 1)
        self.assertEqual(high_state, 2)

    def test_rolling_features_do_not_react_to_future_bars(self) -> None:
        base = _bars([2.0] * 80)
        shocked_future = base.copy()
        shocked_future.loc[50:, "high"] = shocked_future.loc[50:, "close"] + 100.0
        shocked_future.loc[50:, "low"] = shocked_future.loc[50:, "close"] - 100.0

        first = add_markov_regime_features(
            base,
            calibration_bars=24,
            min_calibration_bars=18,
            refit_every_bars=6,
        )
        second = add_markov_regime_features(
            shocked_future,
            calibration_bars=24,
            min_calibration_bars=18,
            refit_every_bars=6,
        )

        cols = ["markov_state", "markov_state_confidence", "markov_prob_low_vol", "markov_prob_mid_vol", "markov_prob_high_vol"]
        pd.testing.assert_frame_equal(first.loc[:49, cols], second.loc[:49, cols])

    def test_context_filter_routes_signal_types_by_regime(self) -> None:
        df = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-02 10:00", periods=3, freq="5min"),
                "signal": [1, 1, -1],
                "signal_type": ["mr", "trend", "mp"],
                "markov_state": [2, 2, np.nan],
                "markov_state_confidence": [0.8, 0.8, 0.8],
            }
        )
        engine = BacktestEngine(
            df,
            portfolio=object(),
            futures_specs={"contract_value": 20},
            strategy_params={
                "markov_regime_filter": "context",
                "markov_n_states": 3,
            },
        )

        out = engine.apply_markov_regime_signal_filters(df)

        self.assertEqual(int(out.loc[0, "signal"]), 0)
        self.assertEqual(int(out.loc[1, "signal"]), 1)
        self.assertEqual(int(out.loc[2, "signal"]), 0)


if __name__ == "__main__":
    unittest.main()
