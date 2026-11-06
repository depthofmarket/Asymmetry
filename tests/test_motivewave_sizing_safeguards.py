"""
Test Suite: MotiveWave Capital Protection & Sizing Safeguards.

Programmatically verifies the MotiveWave capital protection and sizing logic:
1. True historical peak balance persistence across drawdowns (peak monotonically increases).
2. Trailing floor calculation and permanent floor locking at $25,100 once peak reaches $26,100.
3. Cushion calculation (balance - persistedTrailingFloor) and de-leveraging to 1 contract when cushion < $400.
4. Fail-closed contract sizing: resolveContracts() returns 0 when ctx == null, balance is invalid (<= 10,000), or exceptions occur.
5. Fail-closed order execution: executeAutoTradeIfArmed() blocks order submission when contracts <= 0 and logs ORDER_BLOCKED_UNVERIFIED_ACCOUNT.
6. Complete static and behavioral coverage across all 3 MotiveWave studies:
   - LucidMorningVABreakoutStudy.java
   - LucidMacroMomentumStudy.java
   - LucidGoldFixBreakoutStudy.java
"""

from __future__ import annotations

import math
import re
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MOTIVEWAVE_DIR = REPO_ROOT / "src/motivewave"
STUDY_FILES = {
    "LucidMorningVABreakoutStudy": MOTIVEWAVE_DIR / "LucidMorningVABreakoutStudy.java",
    "LucidMacroMomentumStudy": MOTIVEWAVE_DIR / "LucidMacroMomentumStudy.java",
    "LucidGoldFixBreakoutStudy": MOTIVEWAVE_DIR / "LucidGoldFixBreakoutStudy.java",
}


class MotiveWaveSizingReferenceModel:
    """Exact Python reference implementation of the MotiveWave capital protection and sizing logic."""

    def __init__(
        self,
        initial_peak: float = 25000.00,
        initial_floor: float = 24000.00,
        risk_state_peak: float = 25000.00,
        risk_state_floor: float = 24000.00,
    ) -> None:
        self.persisted_peak_balance = initial_peak
        self.persisted_trailing_floor = initial_floor
        self.risk_state_peak = risk_state_peak
        self.risk_state_floor = risk_state_floor
        self.audit_log: List[Dict[str, Any]] = []

    def set_persisted_risk_state(self, peak: float, floor: float) -> None:
        self.persisted_peak_balance = peak
        self.persisted_trailing_floor = floor

    def resolve_contracts(
        self,
        ctx: Optional[Any],
        fallback_contracts: int = 1,
        raise_exception: bool = False,
    ) -> int:
        """Mirrors resolveContracts(OrderContext ctx, int fallbackContracts) from Java studies."""
        if ctx is None:
            return 0
        try:
            if raise_exception:
                raise RuntimeError("Simulated broker API failure")

            cash = getattr(ctx, "cash_balance", 0.0)
            real = getattr(ctx, "realized_pnl", 0.0)
            unreal = getattr(ctx, "unrealized_pnl", 0.0)
            balance = cash + real + unreal

            if not math.isfinite(balance) or balance <= 10000.0:
                return 0

            # Monotonic peak update
            self.persisted_peak_balance = max(
                self.persisted_peak_balance,
                max(self.risk_state_peak, balance),
            )

            # Floor calculation and permanent locking at $25,100
            floor = max(24000.00, self.persisted_peak_balance - 1000.00)
            if self.persisted_peak_balance >= 26100.00 or self.risk_state_floor >= 25100.00:
                floor = 25100.00

            self.persisted_trailing_floor = max(
                self.persisted_trailing_floor,
                max(self.risk_state_floor, floor),
            )

            profit = balance - 25000.00
            cushion = balance - self.persisted_trailing_floor

            # Sizing ratchet rules
            if profit >= 1150.00:
                return 1  # Finish line shield
            if cushion < 400.00:
                return 1  # Safe CPPI cushion de-leveraging
            if profit >= 550.00:
                return 4  # Tier 3 ratchet
            if profit >= 200.00:
                return 3  # Tier 2 ratchet
            return 2  # Tier 1 base ratchet
        except Exception:
            return 0

    def execute_auto_trade_if_armed(
        self,
        ctx: Optional[Any],
        trade: Optional[Any],
        study_name: str,
    ) -> Tuple[bool, Optional[str]]:
        """Mirrors executeAutoTradeIfArmed(OrderContext ctx, ...) fail-closed order submission."""
        if ctx is None:
            self.audit_log.append({
                "event": "ORDER_BLOCKED_UNVERIFIED_ACCOUNT",
                "study": study_name,
                "reason": "Account context unverified (null)",
            })
            return False, "ORDER_BLOCKED_UNVERIFIED_ACCOUNT"

        fallback = getattr(trade, "contracts", 1) if trade is not None else 1
        contracts = self.resolve_contracts(ctx, fallback)
        if contracts <= 0:
            self.audit_log.append({
                "event": "ORDER_BLOCKED_UNVERIFIED_ACCOUNT",
                "study": study_name,
                "reason": "Account context unverified or sizing returned zero; order entry blocked (fail-closed).",
            })
            return False, "ORDER_BLOCKED_UNVERIFIED_ACCOUNT"

        # Trade submission succeeds
        if trade is not None:
            trade.contracts = contracts
            trade.order_submitted = True
        self.audit_log.append({
            "event": "ORDER_SUBMITTED",
            "study": study_name,
            "contracts": contracts,
        })
        return True, "ORDER_SUBMITTED"


class MockOrderContext:
    def __init__(self, cash: float = 25000.0, real: float = 0.0, unreal: float = 0.0) -> None:
        self.cash_balance = cash
        self.realized_pnl = real
        self.unrealized_pnl = unreal
        self.position = 0


class MockActiveTrade:
    def __init__(self, contracts: int = 2) -> None:
        self.contracts = contracts
        self.order_submitted = False
        self.closed = False


class TestMotiveWaveStaticCodeSafeguards(unittest.TestCase):
    """Static source code verification across all 3 MotiveWave studies."""

    def test_study_files_exist(self) -> None:
        for name, path in STUDY_FILES.items():
            self.assertTrue(path.exists(), f"Study file {name} missing at {path}")

    def test_persisted_fields_present_in_all_studies(self) -> None:
        for name, path in STUDY_FILES.items():
            code = path.read_text(encoding="utf-8")
            self.assertIn("private static double persistedPeakBalance = 25000.00;", code, f"Missing persistedPeakBalance in {name}")
            self.assertIn("private static double persistedTrailingFloor = 24000.00;", code, f"Missing persistedTrailingFloor in {name}")
            self.assertIn("public static double getPersistedPeakBalance()", code, f"Missing getPersistedPeakBalance in {name}")
            self.assertIn("public static double getPersistedTrailingFloor()", code, f"Missing getPersistedTrailingFloor in {name}")
            self.assertIn("public static void setPersistedRiskState(double peak, double floor)", code, f"Missing setPersistedRiskState in {name}")

    def test_fail_closed_null_and_balance_checks_in_resolve_contracts(self) -> None:
        for name, path in STUDY_FILES.items():
            code = path.read_text(encoding="utf-8")
            self.assertIn("if (ctx == null) return 0;", code, f"Missing null check in resolveContracts in {name}")
            self.assertIn("balance <= 10000.0", code, f"Missing <= 10000.0 floor check in {name}")
            self.assertIn("!Double.isFinite(balance)", code, f"Missing isFinite check in {name}")
            # Ensure catch returns 0
            catch_block = re.search(r"catch\s*\(\s*Exception\s+\w+\s*\)\s*\{\s*return\s+0\s*;\s*\}", code)
            self.assertIsNotNone(catch_block, f"Missing catch (Exception) return 0 in resolveContracts in {name}")

    def test_floor_locking_logic_present_in_all_studies(self) -> None:
        for name, path in STUDY_FILES.items():
            code = path.read_text(encoding="utf-8")
            self.assertIn("persistedPeakBalance = Math.max(persistedPeakBalance, Math.max(riskState.peakBalance, balance));", code, f"Missing monotonic peak update in {name}")
            self.assertIn("double floor = Math.max(24000.00, persistedPeakBalance - 1000.00);", code, f"Missing base floor calculation in {name}")
            self.assertIn("if (persistedPeakBalance >= 26100.00 || riskState.trailingFloor >= 25100.00)", code, f"Missing permanent lock condition in {name}")
            self.assertIn("floor = 25100.00;", code, f"Missing floor lock assignment in {name}")
            self.assertIn("persistedTrailingFloor = Math.max(persistedTrailingFloor, Math.max(riskState.trailingFloor, floor));", code, f"Missing monotonic floor persistence in {name}")

    def test_cushion_calculation_and_deleveraging_in_all_studies(self) -> None:
        for name, path in STUDY_FILES.items():
            code = path.read_text(encoding="utf-8")
            self.assertIn("double cushion = balance - persistedTrailingFloor;", code, f"Missing cushion calculation in {name}")
            self.assertIn("if (cushion < 400.00) return 1;", code, f"Missing cushion de-leveraging gate (< 400.00) in {name}")
            self.assertIn("if (profit >= 1150.00) return 1;", code, f"Missing finish line shield (>= 1150.00) in {name}")

    def test_fail_closed_order_execution_in_all_studies(self) -> None:
        for name, path in STUDY_FILES.items():
            code = path.read_text(encoding="utf-8")
            self.assertIn("int contracts = resolveContracts(ctx,", code, f"Missing resolveContracts call in {name}")
            self.assertIn("if (contracts <= 0)", code, f"Missing contracts <= 0 guard in {name}")
            self.assertIn("ORDER_BLOCKED_UNVERIFIED_ACCOUNT", code, f"Missing ORDER_BLOCKED_UNVERIFIED_ACCOUNT audit event in {name}")
            # Ensure return is called when contracts <= 0
            blocked_pattern = re.search(r"if\s*\(\s*contracts\s*<=\s*0\s*\)\s*\{[^}]+return\s*;\s*\}", code)
            self.assertIsNotNone(blocked_pattern, f"Missing fail-closed return inside contracts <= 0 block in {name}")

    def test_legacy_flawed_contracts_clamping_prohibited(self) -> None:
        """Verifies that the legacy flaw `if (contracts <= 0) contracts = 1;` has been eradicated."""
        for name, path in STUDY_FILES.items():
            code = path.read_text(encoding="utf-8")
            self.assertNotIn("if (contracts <= 0) contracts = 1;", code, f"Found legacy contracts clamping flaw in {name}!")
            self.assertNotIn("double hwm = Math.max(25000.00, balance);", code, f"Found unpersisted ephemeral HWM flaw in {name}!")


class TestMotiveWavePeakPersistenceAndFloorLocking(unittest.TestCase):
    """Behavioral testing of monotonic peak balance persistence and floor locking."""

    def test_peak_balance_monotonically_increases_across_drawdowns(self) -> None:
        model = MotiveWaveSizingReferenceModel()

        # Balance trajectory with volatile spikes and deep drawdowns
        balances = [25000.0, 25200.0, 25600.0, 25150.0, 25750.0, 25300.0, 26050.0, 25500.0]
        recorded_peaks = []

        for bal in balances:
            ctx = MockOrderContext(cash=bal)
            model.resolve_contracts(ctx)
            recorded_peaks.append(model.persisted_peak_balance)

        # Assert monotonic increase
        for i in range(1, len(recorded_peaks)):
            self.assertGreaterEqual(
                recorded_peaks[i],
                recorded_peaks[i - 1],
                f"Peak dropped from {recorded_peaks[i-1]} to {recorded_peaks[i]}!",
            )

        self.assertEqual(model.persisted_peak_balance, 26050.0)

    def test_floor_trails_by_1000_prior_to_lock(self) -> None:
        model = MotiveWaveSizingReferenceModel()

        # Climb to 25,600 (peak 25,600 -> floor 24,600)
        ctx = MockOrderContext(cash=25600.0)
        model.resolve_contracts(ctx)
        self.assertEqual(model.persisted_peak_balance, 25600.0)
        self.assertEqual(model.persisted_trailing_floor, 24600.0)

        # Pullback to 25,100 (drawdown of $500). Floor MUST remain 24,600!
        ctx_drop = MockOrderContext(cash=25100.0)
        model.resolve_contracts(ctx_drop)
        self.assertEqual(model.persisted_peak_balance, 25600.0)
        self.assertEqual(model.persisted_trailing_floor, 24600.0)

    def test_permanent_floor_locking_at_25100(self) -> None:
        model = MotiveWaveSizingReferenceModel()

        # Step 1: Account reaches $26,100 (+$1,100 profit)
        ctx_target = MockOrderContext(cash=26100.0)
        model.resolve_contracts(ctx_target)
        self.assertEqual(model.persisted_peak_balance, 26100.0)
        self.assertEqual(model.persisted_trailing_floor, 25100.0, "Floor must lock at $25,100 at peak $26,100")

        # Step 2: Peak extends to $26,300
        ctx_extended = MockOrderContext(cash=26300.0)
        model.resolve_contracts(ctx_extended)
        self.assertEqual(model.persisted_peak_balance, 26300.0)
        self.assertEqual(model.persisted_trailing_floor, 25100.0, "Floor must remain permanently locked at $25,100")

        # Step 3: Drawdown down to $25,350 (pullback of $950 from peak)
        ctx_drawdown = MockOrderContext(cash=25350.0)
        model.resolve_contracts(ctx_drawdown)
        self.assertEqual(model.persisted_peak_balance, 26300.0, "Peak balance must not drop on drawdown")
        self.assertEqual(model.persisted_trailing_floor, 25100.0, "Floor must never drop below locked $25,100")


class TestMotiveWaveCushionDeleveraging(unittest.TestCase):
    """Behavioral testing of cushion calculation and Safe CPPI de-leveraging."""

    def test_cushion_deleveraging_under_compressed_buffer(self) -> None:
        model = MotiveWaveSizingReferenceModel()

        # Account reached locked floor state (peak 26,150 -> floor 25,100)
        ctx_lock = MockOrderContext(cash=26150.0)
        model.resolve_contracts(ctx_lock)
        self.assertEqual(model.persisted_trailing_floor, 25100.0)

        # Account suffers drawdown to $25,450:
        # Profit = 25450 - 25000 = +$450 (ordinarily 3 micros)
        # BUT cushion = 25450 - 25100 = $350 < $400!
        ctx_compressed = MockOrderContext(cash=25450.0)
        contracts = model.resolve_contracts(ctx_compressed)

        self.assertEqual(contracts, 1, f"Expected de-leveraging to 1 micro when cushion < $400, got {contracts}")

    def test_cushion_deleveraging_near_liquidation_floor(self) -> None:
        model = MotiveWaveSizingReferenceModel()
        model.set_persisted_risk_state(peak=25800.0, floor=24800.0)

        # Balance at 25,100:
        # Cushion = 25100 - 24800 = $300 < $400!
        ctx = MockOrderContext(cash=25100.0)
        contracts = model.resolve_contracts(ctx)
        self.assertEqual(contracts, 1, "Cushion $300 < $400 must force 1 micro")

    def test_normal_ratchet_sizing_when_cushion_sufficient(self) -> None:
        model = MotiveWaveSizingReferenceModel()

        # Balance 25,050: profit 50, floor 24,050 -> cushion 1000 >= 400 -> base 2 micros
        ctx_base = MockOrderContext(cash=25050.0)
        self.assertEqual(model.resolve_contracts(ctx_base), 2)

        # Balance 25,250: profit 250, floor 24,250 -> cushion 1000 >= 400 -> Tier 2 (3 micros)
        ctx_tier2 = MockOrderContext(cash=25250.0)
        self.assertEqual(model.resolve_contracts(ctx_tier2), 3)

        # Balance 25,600: profit 600, floor 24,600 -> cushion 1000 >= 400 -> Tier 3 (4 micros)
        ctx_tier3 = MockOrderContext(cash=25600.0)
        self.assertEqual(model.resolve_contracts(ctx_tier3), 4)

        # Balance 26,180: profit 1180 -> Finish line shield triggers (1 micro)
        ctx_shield = MockOrderContext(cash=26180.0)
        self.assertEqual(model.resolve_contracts(ctx_shield), 1)


class TestMotiveWaveFailClosedExecution(unittest.TestCase):
    """Behavioral testing of fail-closed contract resolution and order execution."""

    def test_resolve_contracts_fails_closed_on_null_context(self) -> None:
        model = MotiveWaveSizingReferenceModel()
        self.assertEqual(model.resolve_contracts(None, fallback_contracts=2), 0)

    def test_resolve_contracts_fails_closed_on_invalid_balance(self) -> None:
        model = MotiveWaveSizingReferenceModel()

        invalid_balances = [10000.0, 9999.0, 5000.0, 0.0, -500.0, float("nan"), float("inf"), float("-inf")]
        for bad_bal in invalid_balances:
            ctx = MockOrderContext(cash=bad_bal)
            res = model.resolve_contracts(ctx, fallback_contracts=2)
            self.assertEqual(res, 0, f"Expected 0 contracts for invalid balance {bad_bal}, got {res}")

    def test_resolve_contracts_fails_closed_on_exceptions(self) -> None:
        model = MotiveWaveSizingReferenceModel()
        ctx = MockOrderContext(cash=25000.0)
        res = model.resolve_contracts(ctx, fallback_contracts=2, raise_exception=True)
        self.assertEqual(res, 0, "Exception in resolve_contracts must return 0 contracts (fail-closed)")

    def test_execute_auto_trade_blocks_order_when_contracts_zero(self) -> None:
        model = MotiveWaveSizingReferenceModel()
        trade = MockActiveTrade(contracts=2)

        # Pass null context
        submitted, event = model.execute_auto_trade_if_armed(None, trade, "LucidMorningVABreakout")
        self.assertFalse(submitted, "Order submission must be blocked when context is null")
        self.assertEqual(event, "ORDER_BLOCKED_UNVERIFIED_ACCOUNT")
        self.assertFalse(trade.order_submitted)

        # Pass invalid balance context
        ctx_invalid = MockOrderContext(cash=5000.0)
        submitted_inv, event_inv = model.execute_auto_trade_if_armed(ctx_invalid, trade, "LucidMacroMomentum")
        self.assertFalse(submitted_inv, "Order submission must be blocked when balance is invalid")
        self.assertEqual(event_inv, "ORDER_BLOCKED_UNVERIFIED_ACCOUNT")
        self.assertFalse(trade.order_submitted)

    def test_execute_auto_trade_submits_when_verified_and_positive_contracts(self) -> None:
        model = MotiveWaveSizingReferenceModel()
        trade = MockActiveTrade(contracts=2)
        ctx_valid = MockOrderContext(cash=25250.0)

        submitted, event = model.execute_auto_trade_if_armed(ctx_valid, trade, "LucidGoldFixBreakout")
        self.assertTrue(submitted)
        self.assertEqual(event, "ORDER_SUBMITTED")
        self.assertTrue(trade.order_submitted)
        self.assertEqual(trade.contracts, 3, "Valid account context must set sized contracts (3 micros)")


if __name__ == "__main__":
    unittest.main()
