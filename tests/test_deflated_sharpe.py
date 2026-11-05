"""
Unit tests for Deflated Sharpe Ratio (DSR) and Extreme Value Theory (EVT)
maximum Sharpe estimation based on Bailey & Lopez de Prado (2014).
"""

import math
import numpy as np
import pandas as pd
import pytest

from backtest.dashboard_analytics import (
    deflated_sharpe_ratio,
    expected_max_sharpe,
    performance_metrics,
    probabilistic_sharpe,
)


class TestDeflatedSharpeRatio:
    """Test suite for Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio."""

    @pytest.fixture
    def positive_returns(self) -> np.ndarray:
        """Reproducible positive returns series with positive Sharpe."""
        rng = np.random.default_rng(42)
        # 500 daily sessions, mean 0.1, sd 1.0 -> per-period SR ~ 0.1
        return rng.normal(loc=0.1, scale=1.0, size=500)

    @pytest.fixture
    def high_sharpe_returns(self) -> np.ndarray:
        """Positive returns series calibrated so DSR is in sensitive (non-saturated) range."""
        rng = np.random.default_rng(42)
        return rng.normal(loc=1.1, scale=1.0, size=35)

    def test_dsr_reduces_to_psr_when_n_trials_is_one(self, positive_returns):
        """Verify that DSR reduces identically to PSR when n_trials = 1."""
        psr = probabilistic_sharpe(positive_returns, sr_benchmark=0.0)
        dsr = deflated_sharpe_ratio(positive_returns, n_trials=1, sr_benchmark=0.0)
        assert math.isclose(dsr, psr, rel_tol=1e-12)

        # Test with custom benchmark
        for bm in (0.05, 0.1, -0.05):
            psr_bm = probabilistic_sharpe(positive_returns, sr_benchmark=bm)
            dsr_bm = deflated_sharpe_ratio(positive_returns, n_trials=1, sr_benchmark=bm)
            assert math.isclose(dsr_bm, psr_bm, rel_tol=1e-12)

        # Test edge case n_trials <= 0
        dsr_zero = deflated_sharpe_ratio(positive_returns, n_trials=0, sr_benchmark=0.0)
        assert math.isclose(dsr_zero, psr, rel_tol=1e-12)

    def test_dsr_decreases_as_n_trials_increases(self, high_sharpe_returns):
        """Verify that DSR strictly decreases as n_trials increases (1 -> 5 -> 50)."""
        dsr_1 = deflated_sharpe_ratio(high_sharpe_returns, n_trials=1)
        dsr_5 = deflated_sharpe_ratio(high_sharpe_returns, n_trials=5)
        dsr_50 = deflated_sharpe_ratio(high_sharpe_returns, n_trials=50)

        # Multiple testing penalty must discount confidence:
        assert dsr_1 > dsr_5 > dsr_50

        # Also verify expected maximum Sharpe increases strictly with n_trials
        sr_star_1 = expected_max_sharpe(n_trials=1)
        sr_star_5 = expected_max_sharpe(n_trials=5)
        sr_star_50 = expected_max_sharpe(n_trials=50)
        assert sr_star_1 < sr_star_5 < sr_star_50

    def test_dsr_returns_valid_float_in_unit_interval(self, positive_returns):
        """Verify that DSR returns a valid float within [0, 1] for positive return series."""
        dsr = deflated_sharpe_ratio(positive_returns)
        assert isinstance(dsr, float)
        assert np.isfinite(dsr)
        assert 0.0 <= dsr <= 1.0

        # Test with varied distributions: skewed, fat-tailed, etc.
        rng = np.random.default_rng(999)
        # Log-normal shifted
        skewed_returns = rng.lognormal(mean=0.0, sigma=0.5, size=500) - 1.0
        dsr_skewed = deflated_sharpe_ratio(skewed_returns)
        assert isinstance(dsr_skewed, float)
        assert np.isfinite(dsr_skewed)
        assert 0.0 <= dsr_skewed <= 1.0

        # Fat-tailed Student-t shifted positive
        t_returns = rng.standard_t(df=4, size=600) * 0.5 + 0.1
        dsr_t = deflated_sharpe_ratio(t_returns)
        assert isinstance(dsr_t, float)
        assert np.isfinite(dsr_t)
        assert 0.0 <= dsr_t <= 1.0

    def test_dsr_handling_of_small_samples_and_zero_variance(self):
        """Verify handling of small samples (n < 3) and zero variance."""
        # Empty array
        assert np.isnan(deflated_sharpe_ratio(np.array([])))

        # 1-sample array
        assert np.isnan(deflated_sharpe_ratio(np.array([1.5])))

        # 2-sample array
        assert np.isnan(deflated_sharpe_ratio(np.array([1.0, 2.0])))

        # Zero variance: constant returns
        assert np.isnan(deflated_sharpe_ratio(np.array([5.0, 5.0, 5.0, 5.0])))
        assert np.isnan(deflated_sharpe_ratio(np.zeros(100)))

    def test_expected_max_sharpe_properties(self):
        """Verify mathematical properties of expected_max_sharpe."""
        # n_trials <= 1 returns sr_benchmark
        assert expected_max_sharpe(n_trials=1, sr_benchmark=0.15) == 0.15
        assert expected_max_sharpe(n_trials=0, sr_benchmark=0.25) == 0.25
        assert expected_max_sharpe(n_trials=-10, sr_benchmark=0.0) == 0.0

        # Zero variance yields 0.0 when benchmark is 0
        assert expected_max_sharpe(n_trials=20, var_sharpe=0.0) == 0.0

        # Negative variance guarded to 0.0
        assert expected_max_sharpe(n_trials=20, var_sharpe=-1.0) == 0.0

        # Known analytical benchmark value for n_trials=20, var_sharpe=0.5
        val = expected_max_sharpe(n_trials=20, var_sharpe=0.5)
        assert math.isclose(val, 1.344003479887537, rel_tol=1e-6)

        # Monotonicity across a sequence of trials
        trials = [2, 5, 10, 20, 50, 100, 500]
        stars = [expected_max_sharpe(n_trials=n, var_sharpe=0.5) for n in trials]
        for a, b in zip(stars[:-1], stars[1:]):
            assert a < b

    def test_performance_metrics_integration(self):
        """Verify that performance_metrics includes 'dsr' and 'sr_star'."""
        # Construct synthetic trades dataframe and session calendar
        dates = pd.date_range("2024-01-01", periods=100, freq="B").strftime("%Y-%m-%d").tolist()
        rng = np.random.default_rng(777)
        trades_list = []
        for d in dates[:60]:  # trade on 60 sessions
            pnl = float(rng.normal(loc=150.0, scale=300.0))
            trades_list.append({
                "entry_time": f"{d} 09:30:00",
                "exit_time": f"{d} 09:45:00",
                "date": d,
                "strategy": "Strategy 1",
                "direction": "long",
                "pnl": pnl,
                "research_pnl": pnl,
                "contracts": 2,
            })
        trades_df = pd.DataFrame(trades_list)

        metrics = performance_metrics(trades_df, dates, "research_pnl")

        assert "dsr" in metrics
        assert "sr_star" in metrics
        assert "psr" in metrics

        assert isinstance(metrics["dsr"], float)
        assert isinstance(metrics["sr_star"], float)
        assert np.isfinite(metrics["dsr"])
        assert 0.0 <= metrics["dsr"] <= 1.0
        assert metrics["sr_star"] > 0.0
        # DSR should be <= PSR due to multi-testing deflation
        assert metrics["dsr"] <= metrics["psr"]
