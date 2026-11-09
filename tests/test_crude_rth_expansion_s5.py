"""
Test Suite: Candidate Strategy S5 (Crude Oil Post-Fix Range Expansion on MCL).

Verifies:
1. Strategy Registry Tier Segregation (quarantined under StrategyTier.CANDIDATE).
2. Anti-Contamination Invariants (cannot record under BASELINE).
3. Contract Specifications & Friction Accounting ($100/pt, $3.50 RT comm, $6.50 RT stop friction).
4. Consolidation Range Measurement (09:30–10:14 ET) and Validity Bounds ($0.30 <= Range <= $1.20).
5. Daily Regime Gates (ATR14 >= 2.00, RVOL20 >= 1.25, Macro Trend SMA20 vs SMA50).
6. Execution Timing Windows (10:15 earliest entry, 11:15 latest entry, 12:30 hard session flatten).
7. Breakeven Ratchet (+1.0R excursion locks +2 ticks).
8. Zero Lookahead Bias (all daily metrics lagged by 1 session, entries on bar close).
9. Provenance Database Recording & Verification Footer Generation.
"""

from __future__ import annotations

from pathlib import Path
import pytest
import numpy as np
import pandas as pd

import config.strategy_registry as sr
from config.strategy_registry import StrategyTier
from backtest.provenance import ProvenanceStore
from strategies.crude_rth_expansion_s5 import (
    CrudeRthExpansionParams,
    CrudeRthExpansionS5,
    calculate_crude_rth_features,
    generate_signals,
    simulate_intrabar_execution,
)


@pytest.fixture
def temp_store(tmp_path):
    """Provides an isolated ProvenanceStore for testing."""
    db_file = tmp_path / "test_s5_provenance.db"
    jsonl_file = tmp_path / "test_s5_provenance.jsonl"
    return ProvenanceStore(db_path=db_file, jsonl_path=jsonl_file)


@pytest.fixture
def synthetic_rth_days():
    """
    Creates a synthetic 60-day dataset covering 09:00 to 12:30 ET (211 bars per day)
    with realistic OHLCV price dynamics on Micro WTI Crude Oil (MCL).
    """
    days = []
    base_dates = pd.date_range("2024-01-02", periods=60, freq="B")  # 60 business days
    np.random.seed(42)

    for i, d in enumerate(base_dates):
        d_str = d.strftime("%Y-%m-%d")
        times = pd.date_range(f"{d_str} 09:00:00", f"{d_str} 12:30:00", freq="1min")
        n = len(times)

        # Baseline crude price around $75.00
        # High volatility on day 55 (index 54) to satisfy ATR14 >= 2.00 and RVOL >= 1.25
        base_price = 75.0 + float(np.sin(i / 5.0) * 3.0)
        daily_noise = np.random.normal(0, 0.05, n).cumsum()
        prices = base_price + daily_noise

        highs = prices + 0.10
        lows = prices - 0.10
        volume = np.random.randint(100, 300, n)

        # Ensure high volume on day 54 to produce high RVOL
        if i == 53:
            volume = volume * 3

        day_df = pd.DataFrame({
            "time": times,
            "open": prices,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": volume,
            "symbol": "MCL",
        })

        # Setup breakout scenario on day 55 (index 54)
        if i == 54:
            # Consolidation range: 09:30 to 10:14 ET (bars 30 to 74)
            # Confine high to 75.50 and low to 75.00 (range = 0.50 pts, within [0.30, 1.20])
            for b in range(30, 75):
                day_df.loc[b, "open"] = 75.20
                day_df.loc[b, "high"] = 75.50
                day_df.loc[b, "low"] = 75.00
                day_df.loc[b, "close"] = 75.25

            # At bar 80 (10:20 ET), close breaks above 75.50 to 75.75
            day_df.loc[80, "open"] = 75.30
            day_df.loc[80, "high"] = 75.80
            day_df.loc[80, "low"] = 75.25
            day_df.loc[80, "close"] = 75.75  # Breakout trigger bar!

            # Subsequent bars move to target (+90 cents above entry)
            # Entry is close + 0.01 = 75.76. Target is 76.66.
            for b in range(81, 100):
                day_df.loc[b, "open"] = 75.80 + (b - 80) * 0.05
                day_df.loc[b, "high"] = 75.80 + (b - 80) * 0.05 + 0.10
                day_df.loc[b, "low"] = 75.80 + (b - 80) * 0.05 - 0.10
                day_df.loc[b, "close"] = 75.80 + (b - 80) * 0.05

            # Bar 95 reaches target (> 76.66)
            day_df.loc[95, "high"] = 76.80

        days.append(day_df)

    full_df = pd.concat(days, ignore_index=True)
    return full_df


class TestCandidateS5RegistryAndGovernance:
    def test_s5_registered_as_candidate_tier(self):
        """Verifies S5 is registered as CANDIDATE tier and not BASELINE."""
        assert sr.is_registered("crude_rth_expansion_s5") is True
        tier = sr.get_strategy_tier("crude_rth_expansion_s5")
        assert tier == StrategyTier.CANDIDATE
        assert sr.is_production_baseline("crude_rth_expansion_s5") is False

    def test_s5_persists_across_registry_reset(self):
        """Verifies S5 remains registered after reset_registry()."""
        sr.reset_registry()
        assert sr.is_registered("crude_rth_expansion_s5") is True
        assert sr.get_strategy_tier("crude_rth_expansion_s5") == StrategyTier.CANDIDATE

    def test_cannot_record_candidate_s5_as_baseline(self, temp_store, tmp_path):
        """Protection: ProvenanceStore.record_run() must raise ValueError if attempting to claim BASELINE."""
        data_file = tmp_path / "dummy.parquet"
        data_file.write_bytes(b"DATA")

        with pytest.raises(ValueError, match="is not an authorized production baseline"):
            temp_store.record_run(
                strategy_id="crude_rth_expansion_s5",
                strategy_name="Crude Oil Post-Fix Range Expansion",
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

    def test_can_record_s5_as_candidate(self, temp_store, tmp_path):
        """Verifies S5 successfully records under CANDIDATE tier."""
        data_file = tmp_path / "dummy.parquet"
        data_file.write_bytes(b"DATA")

        rec = temp_store.record_run(
            strategy_id="crude_rth_expansion_s5",
            strategy_name="Crude Oil Post-Fix Range Expansion (10:15 ET)",
            strategy_tier=StrategyTier.CANDIDATE,
            methodology="multi_year_walkforward",
            date_start="2021-01-04",
            date_end="2026-10-30",
            data_path=data_file,
            total_trades=104,
            win_rate=41.3,
            profit_factor=1.50,
            gross_profit=3304.50,
            net_profit=1106.00,
            max_drawdown=372.00,
            sharpe_ratio=2.83,
            largest_win=85.50,
        )
        assert rec.strategy_tier == "CANDIDATE"
        fetched = temp_store.get_run(rec.run_id)
        assert fetched is not None
        assert fetched.strategy_tier == "CANDIDATE"


class TestCandidateS5ParametersAndFriction:
    def test_contract_specs_and_friction(self):
        """Verifies Micro WTI Crude contract specifications and net friction."""
        params = CrudeRthExpansionParams()
        assert params.instrument == "MCL"
        assert params.contract_value == 100.0  # $100 per point ($1.00 per cent/tick)
        assert params.tick_size == 0.01
        assert params.commission_round_trip == 3.50  # $3.50 RT
        assert params.slippage_limit_pts == 0.01     # 1 tick adverse ($1.00)
        assert params.slippage_stop_pts == 0.02      # 2 ticks adverse ($2.00)
        assert params.slippage_entry_pts == 0.01     # 1 tick adverse on stop-limit entry ($1.00)

        # Full RT stop loss friction: 1-tick entry slip ($1) + 2-tick stop slip ($2) + $3.50 comm = $6.50
        stop_friction = (params.slippage_entry_pts + params.slippage_stop_pts) * params.contract_value + params.commission_round_trip
        assert stop_friction == pytest.approx(6.50, rel=1e-5)


class TestCandidateS5ConsolidationAndFeatures:
    def test_consolidation_window_bounds(self):
        """Verifies consolidation window parameters match 09:30–10:14 ET specification."""
        params = CrudeRthExpansionParams()
        assert params.consolidation_start_m == 570  # 09:30 ET
        assert params.consolidation_end_m == 614    # 10:14 ET
        assert params.min_consolidation_range == 0.30
        assert params.max_consolidation_range == 1.20

    def test_zero_lookahead_bias_in_daily_stats(self, synthetic_rth_days):
        """Verifies that daily statistics use shift(1) and have zero lookahead into current session."""
        params = CrudeRthExpansionParams()
        rth_df, daily_map = calculate_crude_rth_features(synthetic_rth_days, params)

        # Verify daily stats exist
        assert len(daily_map) > 50

        # Modify future/current session prices & volume and recompute; check daily stats are strictly lagged
        mod_df = synthetic_rth_days.copy()
        last_date = mod_df["time"].dt.strftime("%Y-%m-%d").iloc[-1]
        mod_df.loc[mod_df["time"].dt.strftime("%Y-%m-%d") == last_date, "close"] += 100.0
        mod_df.loc[mod_df["time"].dt.strftime("%Y-%m-%d") == last_date, "volume"] *= 10

        _, mod_daily_map = calculate_crude_rth_features(mod_df, params)

        # Day 50 and last_date stats must be strictly identical (since all daily features use .shift(1))
        test_date = sorted(daily_map.keys())[50]
        assert daily_map[test_date]["atr14"] == pytest.approx(mod_daily_map[test_date]["atr14"], rel=1e-6)
        assert daily_map[test_date]["sma20"] == pytest.approx(mod_daily_map[test_date]["sma20"], rel=1e-6)
        assert daily_map[test_date]["sma50"] == pytest.approx(mod_daily_map[test_date]["sma50"], rel=1e-6)
        assert daily_map[last_date]["rvol"] == pytest.approx(mod_daily_map[last_date]["rvol"], rel=1e-6)


class TestCandidateS5RegimeGating:
    def test_veto_if_atr_below_threshold(self, synthetic_rth_days):
        """Verifies trade is suppressed if ATR14 < 2.00."""
        params = CrudeRthExpansionParams(min_atr14=2.00)
        rth_df, daily_map = calculate_crude_rth_features(synthetic_rth_days, params)

        # Force ATR14 to 1.50 across all dates
        for d in daily_map:
            daily_map[d]["atr14"] = 1.50

        signals = generate_signals(rth_df, daily_map, params)
        assert (signals["signal"] == 0).all()

    def test_veto_if_rvol_below_threshold(self, synthetic_rth_days):
        """Verifies trade is suppressed if RVOL20 < 1.25."""
        params = CrudeRthExpansionParams(min_rvol20=1.25)
        rth_df, daily_map = calculate_crude_rth_features(synthetic_rth_days, params)

        # Force RVOL to 1.00 across all dates
        for d in daily_map:
            daily_map[d]["rvol"] = 1.00

        signals = generate_signals(rth_df, daily_map, params)
        assert (signals["signal"] == 0).all()

    def test_veto_if_consolidation_range_out_of_bounds(self, synthetic_rth_days):
        """Verifies veto if consolidation range < $0.30 or > $1.20."""
        params_narrow = CrudeRthExpansionParams(min_consolidation_range=0.30)
        # Force consolidation range to 0.15 (too compressed)
        mod_df = synthetic_rth_days.copy()
        mod_df["m"] = mod_df["time"].dt.hour * 60 + mod_df["time"].dt.minute
        mod_df.loc[(mod_df["m"] >= 570) & (mod_df["m"] <= 614), "high"] = 75.10
        mod_df.loc[(mod_df["m"] >= 570) & (mod_df["m"] <= 614), "low"] = 75.00

        rth_df, daily_map = calculate_crude_rth_features(mod_df, params_narrow)
        signals = generate_signals(rth_df, daily_map, params_narrow)
        assert (signals["signal"] == 0).all()


class TestCandidateS5ExecutionAndTiming:
    def test_entry_timing_window(self):
        """Verifies entry window is strictly 10:15–11:15 ET and flatten is 12:30 ET."""
        params = CrudeRthExpansionParams()
        assert params.entry_start_m == 615  # 10:15 ET
        assert params.entry_end_m == 675    # 11:15 ET
        assert params.session_flatten_m == 750  # 12:30 ET

    def test_breakeven_ratchet_calculation(self):
        """Verifies that reaching +1.0R excursion moves stop to entry + 2 ticks."""
        params = CrudeRthExpansionParams()
        entry_price = 70.00
        stop_price = entry_price - params.stop_loss_pts  # 69.55
        target_price = entry_price + params.profit_target_pts  # 70.90

        # Simulate price reaching +0.45 excursion (70.45)
        high_excursion = entry_price + params.breakeven_trigger_pts
        assert high_excursion == 70.45

        # Ratchet stop price
        ratcheted_stop = entry_price + params.breakeven_lock_pts
        assert ratcheted_stop == 70.02

        # Net PnL when filled at ratcheted stop: (70.02 - 70.00) * 100 - $3.50 = +$2.00 - $3.50 = -$1.50
        net_breakeven_pnl = (ratcheted_stop - entry_price) * params.contract_value - params.commission_round_trip
        assert net_breakeven_pnl == pytest.approx(-1.50, rel=1e-5)

    def test_target_pnl_calculation(self):
        """Verifies profit target fill with 1-tick adverse limit slip."""
        params = CrudeRthExpansionParams()
        entry_price = 70.00
        target_price = entry_price + params.profit_target_pts  # 70.90
        fill_price = target_price - params.slippage_limit_pts  # 70.89

        gross_pnl = (fill_price - entry_price) * params.contract_value  # 0.89 * 100 = $89.00
        net_pnl = gross_pnl - params.commission_round_trip  # $89.00 - $3.50 = $85.50
        assert gross_pnl == pytest.approx(89.00, rel=1e-5)
        assert net_pnl == pytest.approx(85.50, rel=1e-5)

    def test_stop_loss_pnl_calculation(self):
        """Verifies initial stop loss fill with 2-ticks adverse stop slip."""
        params = CrudeRthExpansionParams()
        entry_price = 70.00
        stop_price = entry_price - params.stop_loss_pts  # 69.55
        fill_price = stop_price - params.slippage_stop_pts  # 69.53

        gross_pnl = (fill_price - entry_price) * params.contract_value  # -0.47 * 100 = -$47.00
        net_pnl = gross_pnl - params.commission_round_trip  # -$47.00 - $3.50 = -$50.50
        assert gross_pnl == pytest.approx(-47.00, rel=1e-5)
        assert net_pnl == pytest.approx(-50.50, rel=1e-5)

    def test_same_bar_breakeven_trigger_and_stop_or_target_conflicts(self):
        """
        Verifies conservative intrabar breakeven resolution in simulate_intrabar_execution:
        1. Same-bar +1R trigger + initial stop -> resolves to 'stop_loss', never 'breakeven'.
        2. Same-bar +1R trigger + target + initial stop -> resolves to 'stop_loss'.
        3. Same-bar +1R trigger + target (with low = ep > initial_stop) -> resolves to 'profit_target'.
        4. Bar k +1R trigger activates breakeven stop starting on bar k + 1.
        """
        params = CrudeRthExpansionParams()
        ep = 70.00
        sp = ep - params.stop_loss_pts       # 69.55
        tp = ep + params.profit_target_pts   # 70.90

        def _build_session(bars_after_entry):
            rows = [
                {
                    "time": pd.Timestamp("2025-06-10 10:15:00"),
                    "date_str": "2025-06-10",
                    "m": 615,
                    "open": 69.90,
                    "high": 70.00,
                    "low": 69.85,
                    "close": 69.99,
                    "volume": 500,
                }
            ]
            for idx_b, b in enumerate(bars_after_entry, start=1):
                rows.append({
                    "time": pd.Timestamp("2025-06-10 10:15:00") + pd.Timedelta(minutes=idx_b),
                    "date_str": "2025-06-10",
                    "m": 615 + idx_b,
                    "open": b["open"],
                    "high": b["high"],
                    "low": b["low"],
                    "close": b["close"],
                    "volume": 500,
                })
            rth_df = pd.DataFrame(rows)
            sig_df = rth_df[["time", "date_str", "close"]].copy()
            sig_df["signal"] = 0
            sig_df["signal_type"] = ""
            sig_df["entry_price"] = np.nan
            sig_df["stop_price"] = np.nan
            sig_df["target_price"] = np.nan
            sig_df.loc[0, "signal"] = 1
            sig_df.loc[0, "signal_type"] = "crude_rth_expansion_long"
            sig_df.loc[0, "entry_price"] = ep
            sig_df.loc[0, "stop_price"] = sp
            sig_df.loc[0, "target_price"] = tp
            return rth_df, sig_df

        # 1. Same-bar +1R trigger (70.45) + initial stop (69.55) -> stop_loss
        rth_1, sig_1 = _build_session([
            {"open": 70.00, "high": 70.55, "low": 69.50, "close": 69.60},
        ])
        trades_1 = simulate_intrabar_execution(rth_1, sig_1, params)
        assert len(trades_1) == 1
        assert trades_1.iloc[0]["exit_reason"] == "stop_loss"
        assert trades_1.iloc[0]["exit_price"] == pytest.approx(sp - params.slippage_stop_pts, rel=1e-6)

        # 2. Same-bar +1R trigger + target (70.90) + initial stop (69.55) -> stop_loss
        rth_2, sig_2 = _build_session([
            {"open": 70.00, "high": 71.00, "low": 69.50, "close": 70.20},
        ])
        trades_2 = simulate_intrabar_execution(rth_2, sig_2, params)
        assert len(trades_2) == 1
        assert trades_2.iloc[0]["exit_reason"] == "stop_loss"

        # 3. Same-bar +1R trigger + target with low = ep (70.00 <= 70.02 BE lock, but > 69.55 stop) -> profit_target
        rth_3, sig_3 = _build_session([
            {"open": 70.00, "high": 70.95, "low": 70.00, "close": 70.90},
        ])
        trades_3 = simulate_intrabar_execution(rth_3, sig_3, params)
        assert len(trades_3) == 1
        assert trades_3.iloc[0]["exit_reason"] == "profit_target"
        assert trades_3.iloc[0]["exit_price"] == pytest.approx(tp - params.slippage_limit_pts, rel=1e-6)

        # 4. Bar 1 reaches +1R (70.50) with low = 70.00 (stays open); Bar 2 hits both BE stop (70.02) and target (70.95) -> breakeven on Bar 2
        rth_4, sig_4 = _build_session([
            {"open": 70.00, "high": 70.50, "low": 70.00, "close": 70.46},
            {"open": 70.46, "high": 70.95, "low": 70.01, "close": 70.50},
        ])
        trades_4 = simulate_intrabar_execution(rth_4, sig_4, params)
        assert len(trades_4) == 1
        assert trades_4.iloc[0]["exit_reason"] == "breakeven"
        assert trades_4.iloc[0]["exit_price"] == pytest.approx(ep + params.breakeven_lock_pts, rel=1e-6)
        assert trades_4.iloc[0]["hold_bars"] == 2

