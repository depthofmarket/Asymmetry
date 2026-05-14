from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.market_memory import (
    add_market_memory_features,
    export_market_memory_report,
    summarize_market_memory_drift,
    wasserstein_distance_1d,
)


def _sample_bars(n: int = 240) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    returns = np.r_[rng.normal(0.20, 0.10, n // 3), rng.normal(0.0, 0.45, n - n // 3)]
    close = 100.0 + np.cumsum(returns)
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-02 09:30", periods=n, freq="5min"),
            "open": close - returns,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": rng.integers(100, 500, n),
        }
    )


class MarketMemoryTests(unittest.TestCase):
    def test_features_do_not_change_when_future_changes(self) -> None:
        base = _sample_bars()
        changed_future = base.copy()
        cutoff = 120
        changed_future.loc[cutoff + 1 :, "close"] += np.linspace(50.0, 100.0, len(changed_future) - cutoff - 1)

        kwargs = {
            "hurst_window_bars": 64,
            "hurst_min_bars": 32,
            "entropy_window_bars": 64,
            "entropy_min_bars": 32,
            "lz_window_bars": 48,
            "lz_min_bars": 24,
            "tail_window_bars": 80,
            "tail_min_bars": 40,
            "recompute_every_bars": 1,
        }
        a = add_market_memory_features(base, **kwargs)
        b = add_market_memory_features(changed_future, **kwargs)

        compare_cols = [
            "market_memory_hurst",
            "market_memory_entropy",
            "market_memory_lz_complexity",
            "market_memory_tail_alpha",
            "market_memory_tail_threshold_points",
            "market_memory_state",
        ]
        for col in compare_cols:
            left = a.loc[:cutoff, col].reset_index(drop=True)
            right = b.loc[:cutoff, col].reset_index(drop=True)
            if pd.api.types.is_numeric_dtype(left):
                np.testing.assert_allclose(left.to_numpy(dtype=float), right.to_numpy(dtype=float), equal_nan=True)
            else:
                self.assertEqual(left.tolist(), right.tolist())

    def test_report_and_drift_export(self) -> None:
        bars = add_market_memory_features(
            _sample_bars(),
            hurst_window_bars=64,
            hurst_min_bars=32,
            entropy_window_bars=64,
            entropy_min_bars=32,
            lz_window_bars=48,
            lz_min_bars=24,
            tail_window_bars=80,
            tail_min_bars=40,
            recompute_every_bars=1,
        )
        drift = summarize_market_memory_drift(bars, recent_fraction=0.25)
        self.assertFalse(drift.empty)
        self.assertIn("normalized_wasserstein", drift.columns)

        with tempfile.TemporaryDirectory() as tmp:
            paths = export_market_memory_report(bars, Path(tmp), artifact_name="memory")
            self.assertTrue(paths.feature_summary_csv.exists())
            self.assertTrue(paths.state_summary_csv.exists())
            self.assertTrue(paths.period_summary_csv.exists())
            self.assertTrue(paths.drift_csv.exists())
            self.assertTrue(paths.warnings_csv.exists())
            self.assertTrue(paths.report_md.exists())
            self.assertIn("Market Memory Report", paths.report_md.read_text(encoding="utf-8"))

    def test_wasserstein_detects_distribution_shift(self) -> None:
        baseline = np.array([0.0, 0.0, 1.0, 1.0])
        shifted = np.array([2.0, 2.0, 3.0, 3.0])
        self.assertGreater(wasserstein_distance_1d(baseline, shifted), 1.5)

    def test_context_filter_blocks_fragile_memory(self) -> None:
        engine = BacktestEngine(
            pd.DataFrame(),
            portfolio=None,
            futures_specs={},
            strategy_params={
                "market_memory_filter": "context",
                "market_memory_allow_missing": True,
                "market_memory_context_avoid_fragile": True,
            },
        )
        frame = pd.DataFrame(
            {
                "signal": [1, 1, -1, 1],
                "signal_type": ["mr", "trend", "mp", "trend"],
                "market_memory_state": [
                    "mean_reverting_memory",
                    "persistent_memory",
                    "chaotic_memory",
                    "unknown",
                ],
            }
        )

        out = engine.apply_market_memory_signal_filters(frame)
        self.assertEqual(out["signal"].tolist(), [1, 1, 0, 1])
        self.assertEqual(out["signal_type"].tolist(), ["mr", "trend", "", "trend"])


if __name__ == "__main__":
    unittest.main()
