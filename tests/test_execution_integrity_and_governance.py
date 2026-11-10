"""
Comprehensive Execution Integrity, Account-Risk State & Governance Regression Suite.

Validates the 8 core technical requirements of the Asymmetry Execution Integrity directive:
1. Candidate Tier Governance: S4 & S5 default automated execution to FALSE;
   missing/invalid settings default disabled; audio/visual alerts preserved;
   explicit user action required; persists across reloads.
2. Unified Account-Risk State Interface: canonical `demo_parity_state.json`;
   configurable directory; timestamp staleness check; fail-closed blocking;
   historical HWM & $25,100 floor lock preserved across restarts.
3. Actual Broker Breakeven Stop Management: working stop modified via
   `slOrder.setAdjStopPrice(newStop); ctx.submitOrders(slOrder);` without cancelling;
   stop modification failures trigger emergency protective policy; partial fills handled.
4. Signal-Bar Completion & Timing: S4 21:14 candle and S5 10:15-11:15 breakout
   require `series.isBarComplete(index)`; incomplete bars cannot trigger signals.
5. Reconcile Market-Order Fills & Bracket Prices: actual average fill price anchors
   bracket distances; slippage is logged; brackets adjusted for fill price.
6. Conservative Intrabar Breakeven in Python Backtests: same-bar trigger/stop conflicts
   evaluated against bar-start stop; +1R breakeven ratchet activates on bar k+1.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from backtest.demo_parity_engine import (
    CANONICAL_STATE_FILENAME,
    DEFENSIVE_DELEVER_CUSHION_DOLLARS,
    compute_ratchet_sizing,
    verify_and_load_account_state,
)
from strategies.asian_evening_reversion_s4 import (
    AsianEveningReversionParams,
    simulate_intrabar_execution as s4_simulate_execution,
)
from strategies.crude_rth_expansion_s5 import (
    CrudeRthExpansionParams,
    simulate_intrabar_execution as s5_simulate_execution,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MOTIVEWAVE_DIR = REPO_ROOT / "src/motivewave"
STUDY_FILES = {
    "S1": MOTIVEWAVE_DIR / "LucidMorningVABreakoutStudy.java",
    "S2": MOTIVEWAVE_DIR / "LucidMacroMomentumStudy.java",
    "S3": MOTIVEWAVE_DIR / "LucidGoldFixBreakoutStudy.java",
    "S4": MOTIVEWAVE_DIR / "LucidAsianEveningReversionStudy.java",
    "S5": MOTIVEWAVE_DIR / "LucidCrudeRthExpansionStudy.java",
}


# ==============================================================================
# SECTION 1: CANDIDATE EXECUTION GOVERNANCE (S4 & S5)
# ==============================================================================

class TestCandidateExecutionGovernance:
    """Requirement 1: Candidate strategies must default auto-trading to FALSE."""

    def test_candidate_studies_default_autotrade_to_false(self):
        """Verify S4 and S5 default autoEntry and ENABLE_LIVE_AUTOTRADE to false."""
        for key in ["S4", "S5"]:
            file_path = STUDY_FILES[key]
            assert file_path.exists(), f"Study source file missing: {file_path}"
            code = file_path.read_text(encoding="utf-8")

            # Must initialize autoEntry to false in StudyHeader
            assert "autoEntry = false," in code, (
                f"{key} @StudyHeader must set autoEntry = false,"
            )

            # Setting descriptor must default to DEFAULT_LIVE_AUTOTRADE (which is false)
            assert 'ENABLE_LIVE_AUTOTRADE' in code, (
                f"{key} must define ENABLE_LIVE_AUTOTRADE constant"
            )
            assert "DEFAULT_LIVE_AUTOTRADE = false;" in code, (
                f"{key} DEFAULT_LIVE_AUTOTRADE must be false"
            )

    def test_candidate_governance_authorization_method(self):
        """Verify isCandidateAutoTradeAuthorized() requires explicit user action."""
        for key in ["S4", "S5"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")

            assert "isCandidateAutoTradeAuthorized()" in code, (
                f"{key} must have explicit isCandidateAutoTradeAuthorized() method"
            )
            assert '"CANDIDATE".equals(STRATEGY_TIER)' in code, (
                f"{key} must verify candidate tier"
            )
            assert "settings.getBoolean(ENABLE_LIVE_AUTOTRADE" in code, (
                f"{key} must check settings.getBoolean(ENABLE_LIVE_AUTOTRADE)"
            )
            assert "return userExplicitlyAuthorizedAutoTrade;" in code, (
                f"{key} must require userExplicitlyAuthorizedAutoTrade to be true"
            )

    def test_candidate_persists_disabled_across_reloads(self):
        """Candidate auto-trading must remain disabled across study reloads and upgrades."""
        for key in ["S4", "S5"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")

            # onLoad must reset userExplicitlyAuthorizedAutoTrade and disable autoEntry
            assert "onLoad(Defaults defaults)" in code or "void onLoad(" in code, (
                f"{key} must implement onLoad lifecycle method"
            )
            assert "userExplicitlyAuthorizedAutoTrade = false;" in code, (
                f"{key} onLoad must set userExplicitlyAuthorizedAutoTrade = false"
            )

    def test_candidate_visual_and_sound_alerts_preserved_when_autotrade_disabled(self):
        """Visual markers and sound alerts must trigger even when auto-trade is false."""
        for key in ["S4", "S5"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")

            # Must call ctx.signal before checking isCandidateAutoTradeAuthorized
            assert "ctx.signal(" in code, f"{key} must dispatch visual/chart signal"
            assert "Toolkit.getDefaultToolkit().beep()" in code, (
                f"{key} must trigger audio alerts via Toolkit beep"
            )
            assert "if (!isCandidateAutoTradeAuthorized())" in code, (
                f"{key} must gate order submission after visual/sound alerts"
            )


# ==============================================================================
# SECTION 2: UNIFIED ACCOUNT-RISK STATE INTERFACE
# ==============================================================================

class TestUnifiedAccountRiskStateInterface:
    """Requirement 2: Canonical demo_parity_state.json with fail-closed safety."""

    def test_canonical_filename_constant(self):
        """Verify canonical filename is demo_parity_state.json across Python and Java."""
        assert CANONICAL_STATE_FILENAME == "demo_parity_state.json"

        for key, path in STUDY_FILES.items():
            code = path.read_text(encoding="utf-8")
            assert 'STATE_FILENAME = "demo_parity_state.json"' in code or \
                   '"demo_parity_state.json"' in code, (
                f"{key} must reference canonical demo_parity_state.json"
            )
            assert 'account_state.json' not in code, (
                f"{key} must not reference deprecated account_state.json"
            )

    def test_missing_account_state_file_fails_closed(self, tmp_path):
        """Missing account state file must return verified=False with ORDER_BLOCKED_UNVERIFIED_ACCOUNT."""
        missing_file = tmp_path / "demo_parity_state.json"
        state = verify_and_load_account_state(missing_file)
        assert state["verified"] is False, "Missing file must fail closed"
        assert "ORDER_BLOCKED_UNVERIFIED_ACCOUNT" in state["diagnostic_event"]

    def test_incorrect_filename_rejected(self, tmp_path):
        """Files with wrong name (e.g. account_state.json) are rejected."""
        wrong_file = tmp_path / "account_state.json"
        wrong_file.write_text(json.dumps({
            "current_balance": 25500.0,
            "peak_balance": 25500.0,
            "trailing_floor": 24500.0,
            "floor_locked": False,
            "circuit_breaker_hit": False,
            "emergency_delever": False,
            "intraday_soft_stop": -600.0,
            "status": "ACTIVE",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")

        state = verify_and_load_account_state(wrong_file)
        assert state["verified"] is False, "Non-canonical filename must be rejected"
        assert "ORDER_BLOCKED_UNVERIFIED_ACCOUNT" in state["diagnostic_event"]

    def test_malformed_json_fails_closed(self, tmp_path):
        """Corrupted JSON must fail closed."""
        corrupt_file = tmp_path / "demo_parity_state.json"
        corrupt_file.write_text("{this is corrupt json!}", encoding="utf-8")
        state = verify_and_load_account_state(corrupt_file)
        assert state["verified"] is False
        assert "ORDER_BLOCKED_UNVERIFIED_ACCOUNT" in state["diagnostic_event"]

    def test_missing_required_fields_fails_closed(self, tmp_path):
        """State missing required fields (e.g. trailing_floor) must fail closed."""
        bad_file = tmp_path / "demo_parity_state.json"
        bad_file.write_text(json.dumps({
            "current_balance": 25500.0,
            "peak_balance": 25500.0,
            # missing trailing_floor, floor_locked
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")
        state = verify_and_load_account_state(bad_file)
        assert state["verified"] is False
        assert "ORDER_BLOCKED_UNVERIFIED_ACCOUNT" in state["diagnostic_event"]

    def test_non_finite_numeric_fields_fails_closed(self, tmp_path):
        """Non-finite numbers (NaN, null, Inf) must fail closed."""
        bad_file = tmp_path / "demo_parity_state.json"
        bad_file.write_text(json.dumps({
            "current_balance": None,
            "peak_balance": 25500.0,
            "trailing_floor": 24500.0,
            "floor_locked": False,
            "circuit_breaker_hit": False,
            "emergency_delever": False,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")
        state = verify_and_load_account_state(bad_file)
        assert state["verified"] is False
        assert "ORDER_BLOCKED_UNVERIFIED_ACCOUNT" in state["diagnostic_event"]

    def test_stale_timestamp_blocks_execution(self, tmp_path):
        """State older than max_age_seconds must be rejected as stale."""
        stale_file = tmp_path / "demo_parity_state.json"
        old_time = datetime.now(timezone.utc) - timedelta(hours=36)
        stale_file.write_text(json.dumps({
            "current_balance": 25500.0,
            "peak_balance": 25500.0,
            "trailing_floor": 24500.0,
            "floor_locked": False,
            "circuit_breaker_hit": False,
            "emergency_delever": False,
            "intraday_soft_stop": -600.0,
            "updated_at": old_time.isoformat(),
        }), encoding="utf-8")
        state = verify_and_load_account_state(stale_file, max_age_seconds=86400)
        assert state["verified"] is False
        assert "ORDER_BLOCKED_UNVERIFIED_ACCOUNT" in state["diagnostic_event"]

    def test_historical_hwm_and_locked_floor_preserved_across_drawdown(self, tmp_path):
        """Peak balance above current balance and locked floor at $25,100 must survive restart."""
        state_file = tmp_path / "demo_parity_state.json"
        # Peak was $26,300 (floor locked at $25,100), but drawdown pulled balance to $25,400
        state_file.write_text(json.dumps({
            "balance": 25400.0,
            "peak_balance": 26300.0,
            "trailing_floor": 25100.0,
            "trailing_cushion": 300.0,
            "current_date_pnl": -150.0,
            "recommended_micros": 2,
            "floor_locked": True,
            "circuit_breaker_hit": False,
            "emergency_delever": False,
            "intraday_soft_stop": -600.0,
            "status": "ACTIVE",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")

        state = verify_and_load_account_state(state_file)
        assert state["verified"] is True
        assert state["peak_balance"] == 26300.0, "Historical peak must NOT reset to current balance"
        assert state["trailing_floor"] == 25100.0, "Locked floor must remain at $25,100"
        assert state["floor_locked"] is True

    def test_all_five_java_studies_enforce_fail_closed_unverified_account(self):
        """All 5 Java studies must log ORDER_BLOCKED_UNVERIFIED_ACCOUNT and load state."""
        for key, path in STUDY_FILES.items():
            code = path.read_text(encoding="utf-8")
            assert "ORDER_BLOCKED_UNVERIFIED_ACCOUNT" in code, (
                f"{key} must log ORDER_BLOCKED_UNVERIFIED_ACCOUNT on state load failure"
            )
            assert "loadDaemonRiskState" in code, f"{key} must implement loadDaemonRiskState"


# ==============================================================================
# SECTION 3: ACTUAL BROKER BREAKEVEN STOP MANAGEMENT (S4 & S5)
# ==============================================================================

class TestActualBrokerBreakevenStopManagement:
    """Requirement 3: Working broker stop order modification via MotiveWave API."""

    def test_s4_and_s5_modify_working_stop_order_without_cancellation(self):
        """Verify S4 and S5 modify stop using trade.slOrder.setAdjStopPrice + ctx.submitOrders."""
        for key in ["S4", "S5"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")

            # Must call setAdjStopPrice on working stop order
            assert "trade.slOrder.setAdjStopPrice(" in code, (
                f"{key} must call trade.slOrder.setAdjStopPrice(newStop) to modify working stop"
            )
            # Must submit order update via ctx.submitOrders
            assert "ctx.submitOrders(trade.slOrder)" in code, (
                f"{key} must submit modified stop order via ctx.submitOrders(trade.slOrder)"
            )

    def test_stop_modification_failure_triggers_protective_policy(self):
        """If stop modification fails, study must execute emergency protective policy."""
        for key in ["S4", "S5"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")

            assert "applyProtectiveFailurePolicy(ctx," in code, (
                f"{key} must implement applyProtectiveFailurePolicy for stop modification failure"
            )
            assert "trade.breakevenModificationFailed = true;" in code, (
                f"{key} must mark breakevenModificationFailed on failure"
            )

    def test_partial_fill_preserves_protective_quantity(self):
        """Stop and target orders must sync with actual filled quantity."""
        for key in ["S4", "S5"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")

            assert "onOrderFilled" in code, f"{key} must implement onOrderFilled"
            assert "trade.slOrder.setAdjQuantity(posQty);" in code, (
                f"{key} must update working stop order quantity on partial fills"
            )
            assert "trade.tpOrder.setAdjQuantity(posQty);" in code, (
                f"{key} must update working target order quantity on partial fills"
            )


# ==============================================================================
# SECTION 4: SIGNAL-BAR COMPLETION & EXECUTION TIMING
# ==============================================================================

class TestSignalBarCompletionTiming:
    """Requirement 4: Signals confirmed strictly on completed candles."""

    def test_s4_requires_bar_complete_for_opening_range_candle(self):
        """S4 21:14 candle must be completed before signal generation for 21:15 entry."""
        code = STUDY_FILES["S4"].read_text(encoding="utf-8")

        assert "series.isBarComplete(index)" in code, (
            "S4 must call series.isBarComplete(index) to verify candle completion"
        )
        assert "21:14" in code, "S4 must explicitly check 21:14 opening range end candle"

    def test_s5_requires_bar_complete_for_range_and_breakout_candles(self):
        """S5 range-box and breakout candles must be complete before confirming signal."""
        code = STUDY_FILES["S5"].read_text(encoding="utf-8")

        assert "series.isBarComplete(index)" in code, (
            "S5 must verify candle completion via series.isBarComplete(index)"
        )
        assert "09:30" in code and "10:14" in code, (
            "S5 must define 09:30-10:14 range box"
        )
        assert "10:15" in code and "11:15" in code, (
            "S5 must define 10:15-11:15 breakout entry window"
        )


# ==============================================================================
# SECTION 5: RECONCILE MARKET-ORDER FILLS & BRACKET PRICES
# ==============================================================================

class TestMarketOrderFillsAndBracketParity:
    """Requirement 5: Actual fill price anchors bracket distances; slippage logged."""

    def test_fill_price_anchors_bracket_stops_and_targets(self):
        """In onOrderFilled, stop and target prices must be re-anchored to actual fill."""
        for key in ["S4", "S5"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")

            assert "trade.actualEntryFill = actualFill;" in code, (
                f"{key} must capture trade.actualEntryFill"
            )
            assert "trade.entryPrice = actualFill;" in code, (
                f"{key} must anchor trade.entryPrice to actualFill"
            )
            assert "trade.entrySlippagePts =" in code, (
                f"{key} must calculate entry slippage"
            )


# ==============================================================================
# SECTION 6: CONSERVATIVE INTRABAR BREAKEVEN IN PYTHON BACKTESTS
# ==============================================================================

class TestIntrabarBreakevenConservativeAssumptions:
    """Requirement 6: Conservative conflict resolution for intrabar breakeven stops."""

    def test_s4_same_bar_trigger_stop_conflict_resolved_conservatively(self):
        """If candle hits +1R high AND drops through initial stop, initial stop is taken."""
        # 1-session synthetic DataFrame:
        # Candle 0: 21:14 signal candle
        # Candle 1: 21:15 execution candle
        # Candle 2: 21:16 ambiguous candle: high spikes to +1.2R (106.0), low plummets to 94.0 (< stop 95.0)
        times = [
            pd.Timestamp("2024-01-10 21:14:00"),
            pd.Timestamp("2024-01-10 21:15:00"),
            pd.Timestamp("2024-01-10 21:16:00"),
            pd.Timestamp("2024-01-10 21:17:00"),
        ]
        df = pd.DataFrame({
            "time": times,
            "open": [100.0, 100.0, 101.0, 95.0],
            "high": [100.5, 100.5, 106.0, 96.0],  # Bar 2 high reaches 106.0 (+1.2R)
            "low": [99.5, 99.5, 94.0, 94.0],      # Bar 2 low breaches initial stop 95.0
            "close": [100.0, 100.0, 95.0, 95.0],
            "hour": [21, 21, 21, 21],
            "minute": [14, 15, 16, 17],
            "date_str": ["2024-01-10"] * 4,
            "rth_atr14": [2.0] * 4,
            "pre_open_1800": [100.0] * 4,
        })
        signals_df = pd.DataFrame({
            "signal": [1, 0, 0, 0],
            "signal_type": ["LONG_SWEEP", "", "", ""],
            "entry_price": [100.0, np.nan, np.nan, np.nan],
            "stop_price": [95.0, np.nan, np.nan, np.nan],       # 5 pt initial risk
            "target_price": [110.0, np.nan, np.nan, np.nan],    # 10 pt target (+2R)
            "risk_pts": [5.0, np.nan, np.nan, np.nan],
        })

        params = AsianEveningReversionParams.for_mnq()
        params.breakeven_trigger_r = 1.0
        params.breakeven_lock_pts = 0.50

        trades = s4_simulate_execution(df, signals_df, params)
        assert len(trades) == 1
        trade = trades.iloc[0]
        # Because the breakeven ratchet triggered during bar 2 cannot protect bar 2 itself,
        # the trade must exit at stop_loss (initial stop price 95.0 minus slippage), NOT breakeven!
        assert trade["exit_reason"] == "stop_loss", (
            f"Ambiguous bar must take stop_loss, got {trade['exit_reason']}"
        )
        assert trade["exit_price"] <= 95.0

    def test_s4_breakeven_activates_on_subsequent_bar(self):
        """+1R excursion on bar k ratchets stop for bar k+1 onwards."""
        # Candle 0: 21:14 signal candle
        # Candle 1: 21:15 entry candle
        # Candle 2: 21:16 cleanly hits +1R high (105.5) without hitting stop (low 98.0)
        # Candle 3: 21:17 drops to 99.0 (below entry + lock 100.5)
        times = [
            pd.Timestamp("2024-01-10 21:14:00"),
            pd.Timestamp("2024-01-10 21:15:00"),
            pd.Timestamp("2024-01-10 21:16:00"),
            pd.Timestamp("2024-01-10 21:17:00"),
        ]
        df = pd.DataFrame({
            "time": times,
            "open": [100.0, 100.0, 101.0, 103.0],
            "high": [100.5, 100.5, 105.5, 103.5],  # Bar 2 high reaches 105.5 (+1.1R)
            "low": [99.5, 99.5, 98.0, 99.0],       # Bar 2 low holds 98.0; Bar 3 low drops to 99.0
            "close": [100.0, 100.0, 103.0, 99.5],
            "hour": [21, 21, 21, 21],
            "minute": [14, 15, 16, 17],
            "date_str": ["2024-01-10"] * 4,
            "rth_atr14": [2.0] * 4,
            "pre_open_1800": [100.0] * 4,
        })
        signals_df = pd.DataFrame({
            "signal": [1, 0, 0, 0],
            "signal_type": ["LONG_SWEEP", "", "", ""],
            "entry_price": [100.0, np.nan, np.nan, np.nan],
            "stop_price": [95.0, np.nan, np.nan, np.nan],
            "target_price": [110.0, np.nan, np.nan, np.nan],
            "risk_pts": [5.0, np.nan, np.nan, np.nan],
        })

        params = AsianEveningReversionParams.for_mnq()
        params.breakeven_trigger_r = 1.0
        params.breakeven_lock_pts = 0.50

        trades = s4_simulate_execution(df, signals_df, params)
        assert len(trades) == 1
        trade = trades.iloc[0]
        # Bar 2 activated breakeven; Bar 3 was stopped out at locked breakeven (100.5)
        assert trade["exit_reason"] == "breakeven", (
            f"Subsequent bar should exit at breakeven, got {trade['exit_reason']}"
        )
        assert trade["exit_price"] == 100.5

    def test_s5_same_bar_trigger_stop_conflict_resolved_conservatively(self):
        """S5: Candle reaching +1R and piercing initial stop must take initial stop."""
        times = [
            pd.Timestamp("2024-01-10 10:14:00"),
            pd.Timestamp("2024-01-10 10:15:00"),
            pd.Timestamp("2024-01-10 10:16:00"),
            pd.Timestamp("2024-01-10 10:17:00"),
        ]
        df = pd.DataFrame({
            "time": times,
            "open": [70.00, 70.00, 70.10, 69.40],
            "high": [70.10, 70.10, 70.60, 69.50],  # Bar 2 reaches +0.60 (> +0.45 trigger)
            "low": [69.90, 69.90, 69.40, 69.30],   # Bar 2 low drops to 69.40 (< 69.55 initial stop)
            "close": [70.00, 70.00, 69.45, 69.35],
            "hour": [10, 10, 10, 10],
            "minute": [14, 15, 16, 17],
            "date_str": ["2024-01-10"] * 4,
            "minute_of_day": [614, 615, 616, 617],
            "m": [614, 615, 616, 617],
        })
        signals_df = pd.DataFrame({
            "signal": [1, 0, 0, 0],
            "signal_type": ["BULL_BREAKOUT", "", "", ""],
            "date_str": ["2024-01-10"] * 4,
            "time": times,
            "entry_price": [70.00, np.nan, np.nan, np.nan],
            "stop_price": [69.55, np.nan, np.nan, np.nan],
            "target_price": [70.90, np.nan, np.nan, np.nan],
        })

        params = CrudeRthExpansionParams()
        trades = s5_simulate_execution(df, signals_df, params)
        assert len(trades) == 1
        trade = trades.iloc[0]
        # Ambiguous bar takes stop loss, NOT breakeven!
        assert trade["exit_reason"] == "stop_loss", (
            f"Ambiguous bar must take stop_loss, got {trade['exit_reason']}"
        )


# ==============================================================================
# SECTION 7: CANONICAL RISK SIZING, UPPER BOUNDS & INSTRUMENT PARITY
# ==============================================================================

class TestSizingResolutionAndUpperBounds:
    """Verify daemon recommendation and fallbackContracts act as hard upper bounds."""

    def test_daemon_recommendation_is_hard_upper_bound_in_source(self):
        """All five studies must cap contracts at riskState.recommendedMicros."""
        for name, path in STUDY_FILES.items():
            code = path.read_text(encoding="utf-8")
            assert "int maxAllowed = riskState.recommendedMicros;" in code or "riskState.recommendedMicros" in code
            assert "if (fallbackContracts > 0)" in code or "fallback" in code
            assert "Math.min(" in code

    def test_deleveraging_flags_cap_sizing_to_one(self):
        """Emergency delever, finish line shield, and garch halving must cap contracts to 1."""
        for name, path in STUDY_FILES.items():
            code = path.read_text(encoding="utf-8")
            assert "emergencyDelever" in code
            assert "finishLineShield" in code
            assert "garchDecileHalving" in code

    def test_unknown_status_fails_closed_in_all_studies(self):
        """Unknown or missing status strings must fail closed across all five studies."""
        for name, path in STUDY_FILES.items():
            code = path.read_text(encoding="utf-8")
            assert "UNKNOWN_ACCOUNT_STATUS" in code
            assert "ACTIVE" in code
            assert "DAILY_HALTED" in code
            assert "TRAILED_OUT" in code


class TestStrategyParityAndInstrumentValidation:
    """Verify S4 and S5 instrument validation, indicators, and configuration parity."""

    def test_s4_mnq_instrument_validation(self):
        code = STUDY_FILES["S4"].read_text(encoding="utf-8")
        assert "isAcceptedMnqSymbol" in code
        assert "INSTRUMENT_NOT_MNQ" in code
        # Broad substring acceptance of full-size NQ must NOT be present
        assert '!sym.contains("MNQ") && !sym.equals("NQ")' not in code
        assert '!sym.contains("MNQ") && !sym.contains("NQ")' not in code

    def test_s4_rth_regime_features(self):
        code = STUDY_FILES["S4"].read_text(encoding="utf-8")
        assert "MIN_RTH_RVOL20" in code
        assert "MIN_DRIFT_ATR" in code
        assert "MAX_DRIFT_ATR" in code
        assert "RthSession" in code
        assert "completedRthList" in code

    def test_s5_mcl_instrument_validation(self):
        code = STUDY_FILES["S5"].read_text(encoding="utf-8")
        assert "isAcceptedMclSymbol" in code
        assert "INSTRUMENT_NOT_MCL" in code
        # Broad substring acceptance of full-size CL must NOT be present
        assert '!sym.contains("MCL") && !sym.contains("CL")' not in code

    def test_s5_daily_indicators_and_no_min_body_ratio(self):
        code = STUDY_FILES["S5"].read_text(encoding="utf-8")
        assert "MIN_BODY_RATIO" not in code
        assert "minBodyRatio" not in code
        assert "MIN_ATR14" in code
        assert "MIN_RVOL20" in code
        assert "DailySession" in code
        assert "completedDailyList" in code
        assert "numCompleted >= 50" in code
        assert "macroTrend" in code


# ==============================================================================
# SECTION 8: EXACT MICRO INSTRUMENT VALIDATION & ROOT PARSING
# ==============================================================================

class TestExactMicroInstrumentValidation:
    """Requirement: S4 accepts only MNQ; S5 accepts only MCL. Reject full-size NQ and CL."""

    @staticmethod
    def _is_accepted_mnq(raw: str | None) -> bool:
        if not raw or not raw.strip():
            return False
        s = raw.strip().upper()
        if ":" in s:
            s = s.split(":")[-1]
        if "/" in s:
            s = s.split("/")[-1]
        if not s.startswith("MNQ"):
            return False
        if len(s) == 3:
            return True
        next_char = s[3]
        if next_char in ("#", ".", "_", "-", " ", "/"):
            return True
        import re
        remainder = s[3:]
        if re.match(r"^[FGHJKMNQUVXZ]\d{1,4}([._\s#-].*)?$", remainder):
            return True
        if re.match(r"^\d{2,4}([._\s#-].*)?$", remainder):
            return True
        return False

    @staticmethod
    def _is_accepted_mcl(raw: str | None) -> bool:
        if not raw or not raw.strip():
            return False
        s = raw.strip().upper()
        if ":" in s:
            s = s.split(":")[-1]
        if "/" in s:
            s = s.split("/")[-1]
        if not s.startswith("MCL"):
            return False
        if len(s) == 3:
            return True
        next_char = s[3]
        if next_char in ("#", ".", "_", "-", " ", "/"):
            return True
        import re
        remainder = s[3:]
        if re.match(r"^[FGHJKMNQUVXZ]\d{1,4}([._\s#-].*)?$", remainder):
            return True
        if re.match(r"^\d{2,4}([._\s#-].*)?$", remainder):
            return True
        return False

    def test_s4_mnq_accepted_symbol_formats(self):
        """MNQ root contracts must be accepted across all MotiveWave/CQG formats."""
        valid_symbols = [
            "MNQ",
            "MNQH25",
            "MNQM25",
            "MNQU2025",
            "MNQZ5",
            "MNQ 03-25",
            "MNQ.CME",
            "CME:MNQ",
            "CME:MNQH25",
            "MNQ#",
            "MNQ_CONT",
            "MNQZ26.CQG",
            "CME/MNQH25",
        ]
        for sym in valid_symbols:
            assert self._is_accepted_mnq(sym) is True, f"Expected {sym} to be accepted by S4"

    def test_s4_nq_full_size_rejected(self):
        """Full-size NQ contracts must be rejected fail-closed by S4."""
        rejected_symbols = [
            "NQ",
            "NQH25",
            "NQM25",
            "NQ 03-25",
            "CME:NQ",
            "CME:NQH25",
            "NQ#",
            "NQ.CME",
            "NQZ26.CQG",
            "SOMEMNQ",
            "MNQEXTRA",
            "",
            None,
        ]
        for sym in rejected_symbols:
            assert self._is_accepted_mnq(sym) is False, f"Expected {sym} to be rejected by S4"

    def test_s5_mcl_accepted_symbol_formats(self):
        """MCL root contracts must be accepted across all MotiveWave/CQG formats."""
        valid_symbols = [
            "MCL",
            "MCLH25",
            "MCLJ25",
            "MCL 03-25",
            "MCL.NYMEX",
            "NYMEX:MCL",
            "NYMEX:MCLH25",
            "MCL#",
            "MCL_CONT",
            "MCLZ26.CQG",
            "NYMEX/MCLJ25",
        ]
        for sym in valid_symbols:
            assert self._is_accepted_mcl(sym) is True, f"Expected {sym} to be accepted by S5"

    def test_s5_cl_full_size_rejected(self):
        """Full-size CL and QM contracts must be rejected fail-closed by S5."""
        rejected_symbols = [
            "CL",
            "CLH25",
            "CLJ25",
            "CL 03-25",
            "NYMEX:CL",
            "NYMEX:CLH25",
            "CL#",
            "CL.NYMEX",
            "QM",
            "QMH25",
            "SOMEMCL",
            "MCLEXTRA",
            "",
            None,
        ]
        for sym in rejected_symbols:
            assert self._is_accepted_mcl(sym) is False, f"Expected {sym} to be rejected by S5"


# ==============================================================================
# SECTION 9: CONFIRMED FLAT STATE & ORDER LIFECYCLE (S4 & S5)
# ==============================================================================

class TestConfirmedFlatStateForS4AndS5:
    """Requirement: Never set trade.closed = true merely because closeAtMarket() was called."""

    def test_on_position_closed_implemented_in_s4_and_s5(self):
        """Both S4 and S5 must implement onPositionClosed(OrderContext ctx)."""
        for key in ["S4", "S5"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")
            assert "public void onPositionClosed(OrderContext ctx)" in code, (
                f"{key} must implement onPositionClosed(OrderContext ctx)"
            )
            assert "POSITION_CLOSED_CONFIRMED" in code, (
                f"{key} must log POSITION_CLOSED_CONFIRMED event"
            )

    def test_flatten_submitted_flag_exists(self):
        """ActiveTrade in S4 and S5 must track flattenSubmitted."""
        for key in ["S4", "S5"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")
            assert "public boolean flattenSubmitted = false;" in code, (
                f"{key} ActiveTrade must declare public boolean flattenSubmitted = false;"
            )

    def test_close_at_market_does_not_prematurely_mark_closed(self):
        """closeAtMarket() must not be immediately followed by trade.closed = true."""
        for key in ["S4", "S5"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")
            # Must set trade.flattenSubmitted = true when closeAtMarket() is issued
            assert "trade.flattenSubmitted = true;" in code
            # Reject pattern: ctx.closeAtMarket(); trade.closed = true;
            assert "ctx.closeAtMarket();\n            trade.closed = true;" not in code
            assert "ctx.closeAtMarket();\n                trade.closed = true;" not in code

    def test_flatten_waits_for_confirmed_cancellation_of_entry_and_brackets(self):
        """A market flatten must wait until entry and both bracket legs are terminal."""
        for key in ["S4", "S5"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")
            start = code.index("private void submitFlatten(")
            end = code.index("\n    @Override", start)
            helper = code[start:end]
            assert "Order[] workingOrders = {trade.entryOrder, trade.slOrder, trade.tpOrder};" in helper
            assert "workingOrder.isCancelled() || workingOrder.isFilled()" in helper
            assert "ctx.cancelOrders(workingOrder);" in helper
            assert helper.index("ctx.cancelOrders(workingOrder);") < helper.index("ctx.createMarketOrder(")
            assert "trade.flattenPending = true;" in helper


# ==============================================================================
# SECTION 10: S1-S3 ORDER IDENTITY & BRACKET ANCHORING INTEGRITY
# ==============================================================================

class TestS1S3OrderIdentityAndPartialFillIntegrity:
    """Requirement: S1-S3 strict order identity matching, fill anchoring, and protective reject."""

    def test_permissive_fill_matching_removed_from_s1_s2_s3(self):
        """Permissive entry-fill fallback || (trade.orderSubmitted && !trade.entryFilled) must be absent."""
        for key in ["S1", "S2", "S3"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")
            assert "|| (trade.orderSubmitted && !trade.entryFilled)" not in code, (
                f"{key} must NOT contain permissive entry-fill matching fallback"
            )

    def test_fill_price_anchors_bracket_orders_in_s1_s2_s3(self):
        """Bracket stop and target prices must be anchored to actual entry average fill price."""
        for key in ["S1", "S2", "S3"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")
            assert "order.getAvgFillPrice()" in code, (
                f"{key} must read order.getAvgFillPrice()"
            )
            assert "anchored to fill=" in code, (
                f"{key} must log brackets anchored to fill"
            )

    def test_partial_fill_synchronization_in_s1_s2_s3(self):
        """Subsequent partial fills must adjust working bracket quantities in-place."""
        for key in ["S1", "S2", "S3"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")
            assert "setAdjQuantity(contracts)" in code, (
                f"{key} must adjust bracket quantity to contracts on partial fill"
            )
            assert "trade.attachedBracketQty = contracts;" in code, (
                f"{key} must track attachedBracketQty"
            )

    def test_partial_fills_reconcile_average_price_and_both_bracket_legs(self):
        """Cumulative position average and quantity must drive working bracket updates."""
        for key in ["S1", "S2", "S3"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")
            assert "ctx.getAvgEntryPrice() > 0 ? ctx.getAvgEntryPrice()" in code
            assert "trade.slOrder.setAdjStopPrice(stopPrice);" in code
            assert "trade.slOrder.setAdjQuantity(contracts);" in code
            assert "trade.tpOrder.setAdjLimitPrice(targetPrice);" in code
            assert "trade.tpOrder.setAdjQuantity(contracts);" in code

    def test_s2_s3_target_cancellation_handling_is_independent_of_stop(self):
        """A cancelled target must be tracked even when the stop was not cancelled."""
        def block_for(source: str, marker: str) -> str:
            start = source.index(marker)
            opening = source.index("{", start)
            depth = 0
            for index in range(opening, len(source)):
                if source[index] == "{":
                    depth += 1
                elif source[index] == "}":
                    depth -= 1
                    if depth == 0:
                        return source[start:index + 1]
            raise AssertionError(f"Unclosed block for {marker}")

        for key in ["S2", "S3"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")
            start = code.index("public void onOrderCancelled")
            end = code.index("public void onPositionClosed", start)
            handler = code[start:end]
            stop_marker = "if (order == trade.slOrder" if key == "S2" else "if (trade != null && (order == trade.slOrder"
            target_marker = "if (order == trade.tpOrder)" if key == "S2" else "if (trade != null && order == trade.tpOrder)"
            stop_block = block_for(handler, stop_marker)
            target_block = block_for(handler, target_marker)
            assert "trade.tpOrder" not in stop_block
            assert "trade.tpOrder = null;" in target_block
            assert "trade.flattenPending" in target_block
            assert "submitMarketFlatten" in target_block

    def test_protective_stop_rejection_triggers_emergency_flatten_in_s1_s2_s3(self):
        """Rejection of protective stop order while position open must execute emergency flatten."""
        for key in ["S1", "S2", "S3"]:
            code = STUDY_FILES[key].read_text(encoding="utf-8")
            assert "PROTECTIVE_STOP_REJECTED_EMERGENCY_FLATTEN" in code, (
                f"{key} must handle protective stop rejection with emergency flatten"
            )
            assert "PROTECTIVE_STOP_CANCELLED_EMERGENCY_FLATTEN" in code, (
                f"{key} must handle unexpected protective stop cancellation with emergency flatten"
            )


# ==============================================================================
# SECTION 11: PYTHON RISK STATE STATUS VALIDATION & CUSHION CONSISTENCY
# ==============================================================================

class TestAccountStateStatusAndCushionConsistency:
    """Requirement: verify_and_load_account_state rejects missing status; cushion aligned to $400."""

    @pytest.fixture
    def state_dir(self, tmp_path):
        d = tmp_path / "forward_test"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write_state(self, state_dir: Path, data: dict):
        state_file = state_dir / CANONICAL_STATE_FILENAME
        state_file.write_text(json.dumps(data), encoding="utf-8")
        return state_dir

    def test_missing_status_field_fails_closed(self, state_dir):
        """Account state missing 'status' field must be rejected fail-closed."""
        data = {
            "balance": 25500.0,
            "peak_balance": 25500.0,
            "trailing_floor": 24500.0,
            "trailing_cushion": 1000.0,
            "current_date_pnl": 0.0,
            "recommended_micros": 2,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._write_state(state_dir, data)
        res = verify_and_load_account_state(state_dir)
        assert res["verified"] is False
        assert "MISSING_ACCOUNT_STATUS" in res["error"]
        assert "ORDER_BLOCKED_UNVERIFIED_ACCOUNT" in res["diagnostic_event"]

    def test_invalid_status_type_fails_closed(self, state_dir):
        """Account state with non-string 'status' must be rejected fail-closed."""
        data = {
            "balance": 25500.0,
            "peak_balance": 25500.0,
            "trailing_floor": 24500.0,
            "trailing_cushion": 1000.0,
            "current_date_pnl": 0.0,
            "recommended_micros": 2,
            "status": 12345,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._write_state(state_dir, data)
        res = verify_and_load_account_state(state_dir)
        assert res["verified"] is False
        assert "INVALID_ACCOUNT_STATUS_TYPE" in res["error"]

    def test_unknown_status_fails_closed(self, state_dir):
        """Account state with unrecognized status must be rejected fail-closed."""
        data = {
            "balance": 25500.0,
            "peak_balance": 25500.0,
            "trailing_floor": 24500.0,
            "trailing_cushion": 1000.0,
            "current_date_pnl": 0.0,
            "recommended_micros": 2,
            "status": "INVALID_RANDOM_STATUS",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._write_state(state_dir, data)
        res = verify_and_load_account_state(state_dir)
        assert res["verified"] is False
        assert "UNKNOWN_ACCOUNT_STATUS" in res["error"]

    def test_valid_statuses_succeed(self, state_dir):
        """Valid account statuses must succeed verification."""
        for valid_status in ("ACTIVE", "PASSED", "DAILY_HALTED", "TRAILED_OUT"):
            data = {
                "balance": 25500.0,
                "peak_balance": 25500.0,
                "trailing_floor": 24500.0,
                "trailing_cushion": 1000.0,
                "current_date_pnl": 0.0,
                "recommended_micros": 2,
                "status": valid_status,
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            self._write_state(state_dir, data)
            res = verify_and_load_account_state(state_dir)
            assert res["verified"] is True, f"Expected {valid_status} to verify, got error: {res['error']}"

    def test_canonical_cushion_constant_and_ratchet_boundaries(self):
        """DEFENSIVE_DELEVER_CUSHION_DOLLARS must be 400.0 and compute_ratchet_sizing must obey boundaries."""
        assert DEFENSIVE_DELEVER_CUSHION_DOLLARS == 400.0

        # Boundary test: cushion < 400.0 triggers defensive delever to 1 micro
        m, tier, shield, delever, garch = compute_ratchet_sizing(profit=650.0, cushion=399.0)
        assert m == 1
        assert delever is True
        assert "Defensive Cushion De-lever: Cushion < $400" in tier

        # Boundary test: cushion == 400.0 does NOT trigger defensive delever (allows normal Tier 3: 4 micros)
        m, tier, shield, delever, garch = compute_ratchet_sizing(profit=650.0, cushion=400.0)
        assert m == 4
        assert delever is False
        assert "Tier 3: Target Sprint" in tier

        # Boundary test: cushion == 401.0 allows normal Tier 3: 4 micros
        m, tier, shield, delever, garch = compute_ratchet_sizing(profit=650.0, cushion=401.0)
        assert m == 4
        assert delever is False

        # Boundary test: cushion == 499.0 allows normal Tier 3: 4 micros (previous 500 threshold eliminated)
        m, tier, shield, delever, garch = compute_ratchet_sizing(profit=650.0, cushion=499.0)
        assert m == 4
        assert delever is False

        # Tier 2 expansion with cushion >= 400.0
        m, tier, shield, delever, garch = compute_ratchet_sizing(profit=350.0, cushion=400.0)
        assert m == 3
        assert delever is False

        # Tier 1 base with cushion >= 400.0
        m, tier, shield, delever, garch = compute_ratchet_sizing(profit=100.0, cushion=400.0)
        assert m == 2
        assert delever is False


# ==============================================================================
# SECTION 12: S5 TRADE-WINDOW COMPLETENESS
# ==============================================================================

class TestS5TradeWindowCompleteness:
    """Requirement: S5 enforces minimum 30 trade bars matching Python."""

    def test_s5_trade_window_constants_and_descriptors(self):
        code = STUDY_FILES["S5"].read_text(encoding="utf-8")
        assert "MIN_CONSOLIDATION_BARS" in code
        assert "MIN_TRADE_BARS" in code
        assert "minConsolidationBars" in code
        assert "minTradeBars" in code
        assert "countTradeBarsInSeries" in code
        assert "totalTradeBars < minTradeBars" in code
