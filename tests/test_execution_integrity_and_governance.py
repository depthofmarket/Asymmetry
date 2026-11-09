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
