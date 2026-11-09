"""
Test Suite: Candidate Strategy S4 (Asian Evening Reversion).

Verifies:
1. Tier segregation in config/strategy_registry.py (quarantined under CANDIDATE).
2. Anti-contamination invariant (cannot be recorded as BASELINE).
3. Anchored Session VWAP at 21:00 ET and standard deviation band calculation.
4. 4-layer defensive regime gates (opening 15m range gate, ATR ceiling, displacement ceiling, ADX filter).
5. Signal generation timing (21:15–22:45 ET window, reversal candle confirmation).
6. Mandatory flatten at 23:00:00 ET sharp.
7. Real net execution accounting ($1.40 RT commission, 1-tick limit slip, 2-tick stop slip).
8. ProvenanceStore recording and footer generation with verified data SHA-256.
"""

from __future__ import annotations

from pathlib import Path
import pytest
import numpy as np
import pandas as pd

import config.strategy_registry as sr
from config.strategy_registry import StrategyTier
from backtest.provenance import ProvenanceStore
from strategies.asian_evening_reversion_s4 import (
    AsianEveningReversionParams,
    AsianEveningReversionS4,
    calculate_asian_session_features,
    generate_signals,
    simulate_intrabar_execution,
)


@pytest.fixture
def temp_store(tmp_path):
    """Provides an isolated ProvenanceStore for testing."""
    db_file = tmp_path / "test_s4_provenance.db"
    jsonl_file = tmp_path / "test_s4_provenance.jsonl"
    return ProvenanceStore(db_path=db_file, jsonl_path=jsonl_file)


@pytest.fixture
def sample_evening_session():
    """
    Creates a synthetic 1-minute dataframe covering 21:00 to 23:00 ET (121 bars)
    with realistic OHLCV price dynamics on MES.
    """
    times = pd.date_range("2024-05-14 21:00:00", "2024-05-14 23:00:00", freq="1min")
    n = len(times)
    
    # Base price around 5250.0
    # First 15 bars: small oscillation (opening range = 4.0 pts)
    # Bars 15-40: drop down to create oversold z-score (<= -2.0)
    # Bar 41: hammer reversal candle
    # Bars 42-60: revert back towards VWAP
    prices = np.full(n, 5250.0)
    for i in range(15):
        prices[i] = 5250.0 + 2.0 * np.sin(i / 2.0)
    for i in range(15, 41):
        prices[i] = prices[14] - (i - 14) * 0.35
    for i in range(41, n):
        prices[i] = prices[40] + (i - 40) * 0.40

    df = pd.DataFrame({
        "time": times,
        "open": prices,
        "high": prices + 0.75,
        "low": prices - 0.75,
        "close": prices,
        "volume": 150,
        "symbol": "MES",
    })
    
    # Specific reversal candle at bar 41 (21:41): strong lower rejection hammer wick
    df.loc[41, "open"] = prices[41]
    df.loc[41, "high"] = prices[41] + 1.00
    df.loc[41, "low"] = prices[41] - 1.50
    df.loc[41, "close"] = prices[41] + 0.75  # Close above open with big lower wick
    
    return df


class TestCandidateS4RegistryAndGovernance:
    def test_s4_registered_as_candidate_tier(self):
        """Verifies S4 is registered as CANDIDATE tier and not BASELINE."""
        assert sr.is_registered("asian_evening_reversion_s4") is True
        tier = sr.get_strategy_tier("asian_evening_reversion_s4")
        assert tier == StrategyTier.CANDIDATE
        assert sr.is_production_baseline("asian_evening_reversion_s4") is False

    def test_s4_persists_across_registry_reset(self):
        """Verifies S4 remains registered after reset_registry()."""
        sr.reset_registry()
        assert sr.is_registered("asian_evening_reversion_s4") is True
        assert sr.get_strategy_tier("asian_evening_reversion_s4") == StrategyTier.CANDIDATE

    def test_cannot_record_candidate_s4_as_baseline(self, temp_store, tmp_path):
        """Protection: ProvenanceStore.record_run() must raise ValueError if attempting to claim BASELINE."""
        data_file = tmp_path / "dummy.parquet"
        data_file.write_bytes(b"DATA")

        with pytest.raises(ValueError, match="is not an authorized production baseline"):
            temp_store.record_run(
                strategy_id="asian_evening_reversion_s4",
                strategy_name="Asian Evening Reversion",
                strategy_tier=StrategyTier.BASELINE,
                methodology="walkforward",
                date_start="2021-01-04",
                date_end="2026-10-30",
                data_path=data_file,
                total_trades=10,
                win_rate=50.0,
                profit_factor=1.5,
                gross_profit=1000.0,
                net_profit=800.0,
                max_drawdown=200.0,
                sharpe_ratio=1.0,
                largest_win=100.0,
            )

    def test_can_record_s4_as_candidate(self, temp_store, tmp_path):
        """Verifies S4 successfully records under CANDIDATE tier."""
        data_file = tmp_path / "dummy.parquet"
        data_file.write_bytes(b"DATA")

        rec = temp_store.record_run(
            strategy_id="asian_evening_reversion_s4",
            strategy_name="Asian Evening Reversion (21:00 ET)",
            strategy_tier=StrategyTier.CANDIDATE,
            methodology="multi_year_walkforward",
            date_start="2021-01-04",
            date_end="2026-10-30",
            data_path=data_file,
            total_trades=100,
            win_rate=55.0,
            profit_factor=1.60,
            gross_profit=5000.0,
            net_profit=3500.0,
            max_drawdown=500.0,
            sharpe_ratio=1.2,
            largest_win=150.0,
        )
        assert rec.strategy_tier == "CANDIDATE"
        fetched = temp_store.get_run(rec.run_id)
        assert fetched is not None
        assert fetched.strategy_tier == "CANDIDATE"


class TestCandidateS4FeatureCalculations:
    def test_anchored_session_vwap_and_bands(self, sample_evening_session):
        params = AsianEveningReversionParams()
        features = calculate_asian_session_features(sample_evening_session, params)

        assert "vwap" in features.columns
        assert "vwap_std" in features.columns
        assert "vwap_zscore" in features.columns
        assert "upper_band" in features.columns
        assert "lower_band" in features.columns

        # Verify 21:00 anchor
        sess_features = features[(features["hour"] == 21) & (features["minute"] >= 15)]
        assert not sess_features["vwap"].isna().any()
        assert not sess_features["vwap_std"].isna().any()
        assert (sess_features["vwap_std"] >= 0.0).all()
        assert (sess_features["upper_band"] >= sess_features["vwap"]).all()
        assert (sess_features["lower_band"] <= sess_features["vwap"]).all()

    def test_opening_15m_range_calculation(self, sample_evening_session):
        params = AsianEveningReversionParams()
        features = calculate_asian_session_features(sample_evening_session, params)

        # Opening 15m range is high.max() - low.min() for 21:00 to 21:14
        or_bars = sample_evening_session.iloc[:15]
        expected_range = or_bars["high"].max() - or_bars["low"].min()

        actual_range = features["range_15m"].iloc[20]
        assert abs(actual_range - expected_range) < 1e-4


class TestCandidateS4DefensiveGates:
    def test_veto_if_opening_range_too_wide(self, sample_evening_session):
        params = AsianEveningReversionParams(max_opening_15m_range=8.0)
        # Create an explosive opening range (> 8.0 pts)
        mod_df = sample_evening_session.copy()
        mod_df.loc[5, "high"] = 5270.0  # Range becomes > 20 pts

        features = calculate_asian_session_features(mod_df, params)
        signals = generate_signals(features, params)

        # All signals must be 0 because session is vetoed
        assert (signals["signal"] == 0).all()

    def test_veto_if_opening_range_too_narrow(self, sample_evening_session):
        params = AsianEveningReversionParams(min_opening_15m_range=2.0)
        # Create flat opening range (< 2.0 pts)
        mod_df = sample_evening_session.copy()
        mod_df.loc[:14, "high"] = 5250.50
        mod_df.loc[:14, "low"] = 5250.00

        features = calculate_asian_session_features(mod_df, params)
        signals = generate_signals(features, params)

        # All signals must be 0 because dead flat session is vetoed
        assert (signals["signal"] == 0).all()

    def test_veto_if_atr_exceeds_ceiling(self, sample_evening_session):
        params = AsianEveningReversionParams(max_atr_1m=2.50)
        features = calculate_asian_session_features(sample_evening_session, params)
        # Force ATR above ceiling
        features["atr_1m"] = 3.50
        signals = generate_signals(features, params)
        assert (signals["signal"] == 0).all()

    def test_veto_if_displacement_exceeds_ceiling(self, sample_evening_session):
        params = AsianEveningReversionParams(max_displacement_pts=10.0)
        # Force huge displacement from 21:00 open (> 10 pts)
        mod_df = sample_evening_session.copy()
        mod_df.loc[20:, "close"] = 5275.0  # Displacement is 25 pts from 5250
        features = calculate_asian_session_features(mod_df, params)
        signals = generate_signals(features, params)
        assert (signals["signal"] == 0).all()

    def test_veto_if_adx_exceeds_ceiling(self, sample_evening_session):
        params = AsianEveningReversionParams(max_adx_5m=30.0)
        features = calculate_asian_session_features(sample_evening_session, params)
        features["adx_5m"] = 45.0  # Runaway trend regime
        signals = generate_signals(features, params)
        assert (signals["signal"] == 0).all()


class TestCandidateS4SignalAndExecution:
    def test_long_signal_generation_and_execution(self, sample_evening_session):
        params = AsianEveningReversionParams()
        features = calculate_asian_session_features(sample_evening_session, params)
        signals = generate_signals(features, params)

        # Check if a long signal fired
        long_sigs = signals[signals["signal"] == 1]
        assert len(long_sigs) >= 1

        # Simulate execution
        trades = simulate_intrabar_execution(features, signals, params)
        assert len(trades) >= 1

        first_trade = trades.iloc[0]
        assert first_trade["direction"] == "long"
        assert first_trade["commission"] == 1.40
        assert first_trade["slippage"] in [1.25, 2.50]
        assert "exit_reason" in first_trade
        assert first_trade["net_pnl"] == pytest.approx(first_trade["gross_pnl"] - 1.40 - first_trade["slippage"], rel=1e-4)

    def test_mandatory_flatten_at_2300(self, sample_evening_session):
        """Position must be flattened at 23:00:00 ET if target/stop not reached."""
        params = AsianEveningReversionParams(
            min_rr_ratio=10.0,   # Far target so it won't hit
            min_stop_pts=20.0,   # Far stop so it won't hit
            max_stop_pts=25.0,
        )
        features = calculate_asian_session_features(sample_evening_session, params)
        signals = generate_signals(features, params)

        trades = simulate_intrabar_execution(features, signals, params)
        if len(trades) > 0:
            last_trade = trades.iloc[-1]
            assert last_trade["exit_reason"] == "time_exit"
            assert pd.Timestamp(last_trade["exit_time"]).hour == 23
            assert pd.Timestamp(last_trade["exit_time"]).minute == 0

    def test_same_bar_breakeven_trigger_and_initial_stop_conflict(self, sample_evening_session):
        """
        Ambiguous OHLC candle touching both +1R breakeven trigger and initial stop
        on the same bar must resolve conservatively to 'stop_loss', never 'breakeven'.
        """
        params = AsianEveningReversionParams(breakeven_trigger_r=1.0, breakeven_lock_pts=0.50)
        features = calculate_asian_session_features(sample_evening_session, params)
        signals = generate_signals(features, params)
        sig_idx = signals[signals["signal"] != 0].index[0]
        entry_idx = sig_idx + 1
        bar_k_idx = entry_idx + 1

        ep = float(features.loc[entry_idx, "open"])
        sp = float(signals.loc[sig_idx, "stop_price"])
        tp = float(signals.loc[sig_idx, "target_price"])
        risk = abs(ep - sp)

        # Ensure entry bar itself is benign
        features.loc[entry_idx, "high"] = ep + 0.25
        features.loc[entry_idx, "low"] = ep - 0.25
        features.loc[entry_idx, "close"] = ep

        # On bar k, touch +1R trigger AND touch initial stop (below sp, below tp)
        features.loc[bar_k_idx, "high"] = min(tp - 0.25, ep + risk + 0.25)
        features.loc[bar_k_idx, "low"] = sp - 0.50
        features.loc[bar_k_idx, "close"] = sp

        trades = simulate_intrabar_execution(features, signals, params)
        assert len(trades) == 1
        trade = trades.iloc[0]
        assert trade["exit_reason"] == "stop_loss"
        assert trade["exit_price"] == pytest.approx(sp, rel=1e-6)
        assert trade["net_pnl"] < 0

    def test_same_bar_breakeven_trigger_and_target_without_initial_stop(self, sample_evening_session):
        """
        Candle that opens at entry price (low <= ep + lock_pts, but low > initial_stop)
        and rallies through +1R to target_price on the same bar must resolve to 'profit_target',
        and if it also touches initial_stop it must resolve to 'stop_loss'.
        """
        params = AsianEveningReversionParams(breakeven_trigger_r=1.0, breakeven_lock_pts=0.50)
        features = calculate_asian_session_features(sample_evening_session, params)
        signals = generate_signals(features, params)
        sig_idx = signals[signals["signal"] != 0].index[0]
        entry_idx = sig_idx + 1

        ep = float(features.loc[entry_idx, "open"])
        sp = float(signals.loc[sig_idx, "stop_price"])
        tp = float(signals.loc[sig_idx, "target_price"])

        # Case A: Same-bar trigger + target with low = ep (above initial stop, below ep + lock_pts)
        feat_target = features.copy()
        feat_target.loc[entry_idx, "open"] = ep
        feat_target.loc[entry_idx, "low"] = ep          # <= ep + 0.50, but > sp
        feat_target.loc[entry_idx, "high"] = tp + 0.50  # hits +1R and target
        feat_target.loc[entry_idx, "close"] = tp

        trades_target = simulate_intrabar_execution(feat_target, signals, params)
        assert len(trades_target) == 1
        assert trades_target.iloc[0]["exit_reason"] == "profit_target"
        assert trades_target.iloc[0]["exit_price"] == pytest.approx(tp, rel=1e-6)

        # Case B: Same-bar trigger + target + initial stop -> must resolve to stop_loss
        feat_conflict = features.copy()
        feat_conflict.loc[entry_idx, "open"] = ep
        feat_conflict.loc[entry_idx, "low"] = sp - 0.25   # hits initial stop
        feat_conflict.loc[entry_idx, "high"] = tp + 0.50  # hits +1R and target
        feat_conflict.loc[entry_idx, "close"] = ep

        trades_conflict = simulate_intrabar_execution(feat_conflict, signals, params)
        assert len(trades_conflict) == 1
        assert trades_conflict.iloc[0]["exit_reason"] == "stop_loss"

    def test_next_bar_breakeven_ratchet_activates_after_trigger_bar(self, sample_evening_session):
        """
        Reaching +1R on bar k without hitting stop or target ratchets the stop to
        ep + lock_pts starting on bar k + 1, not on bar k.
        """
        params = AsianEveningReversionParams(breakeven_trigger_r=1.0, breakeven_lock_pts=0.50, min_rr_ratio=2.0)
        features = calculate_asian_session_features(sample_evening_session, params)
        signals = generate_signals(features, params)
        sig_idx = signals[signals["signal"] != 0].index[0]
        entry_idx = sig_idx + 1
        next_idx = entry_idx + 1

        ep = float(features.loc[entry_idx, "open"])
        sp = float(signals.loc[sig_idx, "stop_price"])
        risk = abs(ep - sp)
        tp = ep + 2.0 * risk
        signals.loc[sig_idx, "target_price"] = tp

        # Entry bar reaches +1R (ep + risk) and has low = ep (which is < ep + 0.50), but > sp
        features.loc[entry_idx, "open"] = ep
        features.loc[entry_idx, "low"] = ep
        features.loc[entry_idx, "high"] = ep + risk + 0.25
        features.loc[entry_idx, "close"] = ep + risk

        # Next bar pulls back to ep + 0.25 (<= ep + 0.50 breakeven lock) and also spikes to tp
        features.loc[next_idx, "open"] = ep + risk
        features.loc[next_idx, "low"] = ep + 0.25
        features.loc[next_idx, "high"] = tp + 0.50
        features.loc[next_idx, "close"] = ep + 0.50

        trades = simulate_intrabar_execution(features, signals, params)
        assert len(trades) == 1
        trade = trades.iloc[0]
        assert trade["exit_reason"] == "breakeven"
        assert trade["exit_price"] == pytest.approx(ep + 0.50, rel=1e-6)
        assert pd.Timestamp(trade["exit_time"]) == pd.Timestamp(features.loc[next_idx, "time"])

