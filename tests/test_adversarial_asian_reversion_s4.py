"""
Adversarial Stress Test Suite: Candidate Strategy S4 (Asian Evening Reversion).

Empirically verifies:
1. Extreme Price Shocks & Flash Crashes (50pt opening blowout, 35pt upward rally, 40pt crash).
2. Defensive Regime Gates (Net displacement ceiling <= 10.0 pts, 1m ATR <= 2.50 pts, Opening Range [2.0, 8.0] pts).
3. Runaway Trend Regimes (5m ADX > 30.0 veto and exact 30.00 vs 30.01 boundary precision).
4. Session Boundary Edge Cases (Zero signals after 22:45 ET, hard mandatory flatten at 23:00:00 ET, early truncation).
5. Missing Bar Sequences, Gaps, Zero Volume, and Dead Flat Sessions.
6. Intrabar Conflict Resolution & Bracket Risk Invariants (Stop priority, [4.0, 6.0] clamp, 1 trade/session cap).
7. Point-in-Time Integrity (Zero lookahead leakage).

Governed by the 5 Golden Rules of Quantitative Provenance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from strategies.asian_evening_reversion_s4 import (
    AsianEveningReversionParams,
    AsianEveningReversionS4,
    calculate_asian_session_features,
    generate_signals,
    simulate_intrabar_execution,
)


@pytest.fixture
def base_evening_session():
    """
    Creates a synthetic evening session including 18:00–21:00 warmup (Globex open)
    and 21:00–23:00 trading window with a clear reversal setup at bar 36 (21:36 ET).
    """
    times = pd.date_range("2024-05-14 18:00:00", "2024-05-14 23:00:00", freq="1min")
    n = len(times)
    base_price = 5250.0
    prices = np.full(n, base_price)

    # 18:00 to 21:00 (bars 0 to 180): gentle background oscillation for ADX warmup
    for i in range(180):
        prices[i] = base_price + 1.5 * np.sin(i / 10.0)

    # 21:00 to 21:14 (bars 180 to 194): 4.0 pt opening 15m range
    for i in range(180, 195):
        prices[i] = base_price + 2.0 * np.sin((i - 180) / 2.0)

    # 21:15 to 21:35 (bars 195 to 215): drift down to oversold excursion
    for i in range(195, 216):
        prices[i] = prices[194] - (i - 194) * 0.30

    # 21:36 to 23:00: mean revert back up
    for i in range(216, n):
        prices[i] = prices[215] + (i - 215) * 0.25

    df = pd.DataFrame({
        "time": times,
        "open": prices,
        "high": prices + 0.50,
        "low": prices - 0.50,
        "close": prices,
        "volume": 200,
        "symbol": "MES",
    })

    # Reversal hammer candle at bar 216 (21:36 ET)
    p216 = prices[216]
    df.loc[216, "open"] = p216
    df.loc[216, "high"] = p216 + 0.75
    df.loc[216, "low"] = p216 - 1.50
    df.loc[216, "close"] = p216 + 0.50

    return df


class TestAdversarialPriceShocks:
    def test_opening_range_blowout_shock(self, base_evening_session):
        """Extreme Shock: 50-point spike in opening 15m range (> 8.0 pts gate) vetoes entire session."""
        params = AsianEveningReversionParams()
        df = base_evening_session.copy()
        # Bar 187 is 21:07 ET
        df.loc[187, "high"] = 5300.0

        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)

        assert features.loc[features["hour"] == 21, "range_15m"].iloc[0] > 45.0
        assert (signals.loc[features["hour"].isin([21, 22]), "signal"] == 0).all()

    def test_sudden_displacement_ceiling_upward(self, base_evening_session):
        """Extreme Shock: Sudden 35-point rally during trading window (|C_t - O_21:00| > 10.0 pts) vetoes entry."""
        params = AsianEveningReversionParams()
        df = base_evening_session.copy()
        # At 21:35 ET (bar 215 onwards), price spikes up to 5285 (+35 pts from open 5250)
        df.loc[215:, "open"] = 5285.0
        df.loc[215:, "high"] = 5286.0
        df.loc[215:, "low"] = 5284.0
        df.loc[215:, "close"] = 5285.0
        df.loc[216, "high"] = 5290.0
        df.loc[216, "close"] = 5284.5

        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)

        spike_signals = signals.loc[215:, "signal"]
        assert (spike_signals == 0).all()

    def test_sudden_displacement_ceiling_downward_flash_crash(self, base_evening_session):
        """Extreme Shock: Sudden 40-point flash crash (|C_t - O_21:00| = 40.0 > 10.0 pts) vetoes entry."""
        params = AsianEveningReversionParams()
        df = base_evening_session.copy()
        # At 21:30 ET (bar 210 onwards), plunge to 5210 (-40 pts)
        df.loc[210:, "open"] = 5210.0
        df.loc[210:, "high"] = 5211.0
        df.loc[210:, "low"] = 5208.0
        df.loc[210:, "close"] = 5210.0
        df.loc[211, "high"] = 5212.0
        df.loc[211, "low"] = 5202.0
        df.loc[211, "close"] = 5211.5

        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)

        crash_signals = signals.loc[210:, "signal"]
        assert (crash_signals == 0).all()

    def test_extreme_atr_ceiling_veto(self, base_evening_session):
        """Extreme Shock: High-frequency ATR spike (ATR > 2.50 pts) blocks entry."""
        params = AsianEveningReversionParams()
        df = base_evening_session.copy()
        for i in range(200, 230):
            df.loc[i, "high"] = df.loc[i, "open"] + 3.00
            df.loc[i, "low"] = df.loc[i, "open"] - 3.00

        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)

        high_atr_signals = signals.loc[210:230, "signal"]
        assert (high_atr_signals == 0).all()


class TestAdversarialRunawayTrendRegimes:
    def test_runaway_trend_regime_adx_veto(self):
        """Runaway Trend: Persistent trending market (ADX > 30.0) vetoes mean-reversion counter-trend entry."""
        params = AsianEveningReversionParams()
        times = pd.date_range("2024-05-14 18:00:00", "2024-05-14 23:00:00", freq="1min")
        n = len(times)
        trend_prices = 5200.0 + np.linspace(0, 50.0, n)
        df = pd.DataFrame({
            "time": times,
            "open": trend_prices,
            "high": trend_prices + 0.50,
            "low": trend_prices - 0.25,
            "close": trend_prices + 0.25,
            "volume": 250,
            "symbol": "MES",
        })

        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)

        evening_mask = (features["hour"] == 21) & (features["minute"] >= 15)
        assert features.loc[evening_mask, "adx_5m"].max() > 30.0
        assert (signals.loc[evening_mask, "signal"] == 0).all()

    def test_adx_exact_threshold_boundary(self, base_evening_session):
        """Precision Check: ADX <= 30.00 allows trade, ADX = 30.01 vetoes trade."""
        params = AsianEveningReversionParams(max_adx_5m=30.0)
        df = base_evening_session.copy()
        features = calculate_asian_session_features(df, params)

        # Baseline signal fires at bar 216
        features.loc[216, "adx_5m"] = 30.00
        sigs_at_30 = generate_signals(features, params)
        assert sigs_at_30.loc[216, "signal"] == 1

        features.loc[216, "adx_5m"] = 30.01
        sigs_above_30 = generate_signals(features, params)
        assert sigs_above_30.loc[216, "signal"] == 0


class TestAdversarialSessionBoundaries:
    def test_zero_signals_after_2245(self, base_evening_session):
        """Session Boundary: Zero signals may be generated after 22:45 ET."""
        params = AsianEveningReversionParams()
        df = base_evening_session.copy()
        # Craft hammer candles at 22:46, 22:50, 22:55
        for m in [46, 50, 55]:
            idx = df[(df["time"].dt.hour == 22) & (df["time"].dt.minute == m)].index[0]
            df.loc[idx, "open"] = 5245.0
            df.loc[idx, "high"] = 5246.0
            df.loc[idx, "low"] = 5242.0
            df.loc[idx, "close"] = 5245.8

        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)

        post_2245_mask = (
            ((signals["time"].dt.hour == 22) & (signals["time"].dt.minute > 45))
            | (signals["time"].dt.hour == 23)
        )
        assert (signals.loc[post_2245_mask, "signal"] == 0).all()

    def test_mandatory_flatten_at_2300(self, base_evening_session):
        """Session Boundary: Open position must be flattened at 23:00:00 ET sharp."""
        params = AsianEveningReversionParams(
            min_rr_ratio=50.0,
            min_stop_pts=50.0,
            max_stop_pts=60.0,
        )
        df = base_evening_session.copy()
        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)
        trades = simulate_intrabar_execution(features, signals, params)

        assert len(trades) == 1
        trade = trades.iloc[0]
        exit_time = pd.Timestamp(trade["exit_time"])
        assert exit_time.hour == 23
        assert exit_time.minute == 0
        assert exit_time.second == 0
        assert trade["exit_reason"] == "time_exit"
        assert trade["slippage"] == 2.50

    def test_early_session_cutoff(self, base_evening_session):
        """Session Boundary: Early cutoff (e.g. holiday early close at 22:30) flattens on final bar."""
        params = AsianEveningReversionParams(
            min_rr_ratio=50.0,
            min_stop_pts=50.0,
            max_stop_pts=60.0,
        )
        df = base_evening_session.copy()
        df = df[df["time"] <= pd.Timestamp("2024-05-14 22:30:00")].copy()
        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)
        trades = simulate_intrabar_execution(features, signals, params)

        assert len(trades) == 1
        trade = trades.iloc[0]
        assert pd.Timestamp(trade["exit_time"]) == pd.Timestamp("2024-05-14 22:30:00")
        assert trade["exit_reason"] == "time_exit"


class TestAdversarialDataDegradation:
    def test_missing_opening_15m_window(self, base_evening_session):
        """Missing Data: Zero bars in 21:00-21:14 window produces zero crashes and zero trades."""
        params = AsianEveningReversionParams()
        df = base_evening_session.copy()
        # Drop all bars between 21:00 and 21:19
        df = df[~((df["time"].dt.hour == 21) & (df["time"].dt.minute < 20))].copy()
        df.reset_index(drop=True, inplace=True)

        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)
        trades = simulate_intrabar_execution(features, signals, params)

        assert (signals["signal"] == 0).all()
        assert len(trades) == 0

    def test_sparse_and_zero_volume_bars(self, base_evening_session):
        """Missing Data: Bars with volume=0 and dropped minutes do not produce NaNs in VWAP."""
        params = AsianEveningReversionParams()
        df = base_evening_session.copy()
        df.loc[df.index % 2 == 0, "volume"] = 0
        df = df[df.index % 5 != 0].copy()
        df.reset_index(drop=True, inplace=True)

        features = calculate_asian_session_features(df, params)
        evening_features = features[features["hour"].isin([21, 22])]
        assert not evening_features["vwap"].isna().any()

    def test_zero_volatility_flatline(self):
        """Missing Data: Constant flatline price vetoed by opening range minimum (< 2.0 pts)."""
        params = AsianEveningReversionParams()
        times = pd.date_range("2024-05-14 21:00:00", "2024-05-14 23:00:00", freq="1min")
        df = pd.DataFrame({
            "time": times,
            "open": 5250.0,
            "high": 5250.0,
            "low": 5250.0,
            "close": 5250.0,
            "volume": 100,
            "symbol": "MES",
        })

        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)
        assert (signals["signal"] == 0).all()

    def test_empty_typed_dataframe(self):
        """Missing Data: Empty typed dataframe returns zero trades cleanly without exception."""
        params = AsianEveningReversionParams()
        empty_df = pd.DataFrame({
            "time": pd.Series(dtype="datetime64[ns]"),
            "open": pd.Series(dtype="float64"),
            "high": pd.Series(dtype="float64"),
            "low": pd.Series(dtype="float64"),
            "close": pd.Series(dtype="float64"),
            "volume": pd.Series(dtype="float64"),
            "symbol": pd.Series(dtype="object"),
        })
        engine = AsianEveningReversionS4(params)
        trades, metrics = engine.backtest(empty_df, start_date="", end_date="")
        assert len(trades) == 0
        assert metrics["total_trades"] == 0


class TestAdversarialExecutionAndLookahead:
    def test_simultaneous_stop_and_target_conflict(self, base_evening_session):
        """Intrabar Conflict: Conservative resolution ensures stop loss prevails over target (even with default 1.0R breakeven trigger)."""
        params = AsianEveningReversionParams(breakeven_trigger_r=1.0)
        df = base_evening_session.copy()
        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)

        sig_idx = 216
        entry_idx = sig_idx + 1
        conflict_idx = entry_idx + 1

        features.loc[conflict_idx, "high"] = 5300.0  # Above target and +1R trigger
        features.loc[conflict_idx, "low"] = 5200.0   # Below initial stop

        trades = simulate_intrabar_execution(features, signals, params)
        assert len(trades) == 1
        trade = trades.iloc[0]
        assert trade["exit_reason"] == "stop_loss"
        assert trade["net_pnl"] < 0

    def test_max_stop_loss_clamping(self, base_evening_session):
        """Risk Invariant: Stop loss distance clamped to max_stop_pts (6.0 pts)."""
        params = AsianEveningReversionParams(min_stop_pts=4.0, max_stop_pts=6.0)
        df = base_evening_session.copy()
        sig_idx = 216
        # Push bar 216 low deep so raw swing distance is ~12 pts
        df.loc[sig_idx, "low"] = 5233.0

        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)

        sig = signals.loc[sig_idx]
        risk_dist = sig["entry_price"] - sig["stop_price"]
        assert risk_dist == pytest.approx(6.0, rel=1e-4)

    def test_single_trade_per_session_cap(self, base_evening_session):
        """Risk Invariant: Exactly 1 trade allowed per session even with multiple setups."""
        params = AsianEveningReversionParams(max_trades_per_session=1)
        df = base_evening_session.copy()
        features = calculate_asian_session_features(df, params)
        signals = generate_signals(features, params)
        trades = simulate_intrabar_execution(features, signals, params)

        assert (signals["signal"] != 0).sum() == 1
        assert len(trades) == 1

    def test_point_in_time_integrity(self, base_evening_session):
        """Lookahead Falsification: Features at bar T must be strictly invariant to future truncation."""
        params = AsianEveningReversionParams()
        full_df = base_evening_session.copy()
        partial_df = full_df[full_df["time"] <= pd.Timestamp("2024-05-14 21:45:00")].copy()

        feats_full = calculate_asian_session_features(full_df, params)
        feats_part = calculate_asian_session_features(partial_df, params)

        idx_check = full_df[full_df["time"] == pd.Timestamp("2024-05-14 21:36:00")].index[0]

        assert abs(feats_full.loc[idx_check, "vwap"] - feats_part.loc[idx_check, "vwap"]) < 1e-6
        assert abs(feats_full.loc[idx_check, "vwap_zscore"] - feats_part.loc[idx_check, "vwap_zscore"]) < 1e-6
        assert abs(feats_full.loc[idx_check, "adx_5m"] - feats_part.loc[idx_check, "adx_5m"]) < 1e-6
