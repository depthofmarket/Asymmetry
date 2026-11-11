"""
Automated Rulebook & Governance Test: LucidFlex 25K Specification Integrity.
============================================================================
Ensures that all AI agents, config registries, wiki documentation, and backtest
engines adhere strictly to the verified LucidFlex 25K account profile.
Fails immediately if any spec or formula deviates from official terms.
"""

from pathlib import Path
import pytest
from config.prop_firm_registry import LUCID_FLEX_25K

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestLucidFlexRulesIntegrity:
    """Verifies invariant parameters and calculations in config/prop_firm_registry.py."""

    def test_evaluation_parameters(self):
        assert LUCID_FLEX_25K.ACCOUNT_SIZE == 25_000.0
        assert LUCID_FLEX_25K.PROFIT_TARGET == 1_250.0
        assert LUCID_FLEX_25K.TARGET_BALANCE == 26_250.0
        assert LUCID_FLEX_25K.EVAL_TICKET_COST == 39.0
        assert LUCID_FLEX_25K.MONTHLY_REBILL == 0.0
        assert LUCID_FLEX_25K.TIME_LIMIT_DAYS == 0
        assert LUCID_FLEX_25K.MAX_TRAILING_DRAWDOWN == 1_000.0
        assert LUCID_FLEX_25K.INITIAL_FLOOR == 24_000.0
        assert LUCID_FLEX_25K.FLOOR_LOCK_PEAK_BALANCE == 26_100.0
        assert LUCID_FLEX_25K.LOCKED_FLOOR_VALUE == 25_100.0
        assert LUCID_FLEX_25K.DAILY_SOFT_STOP == 600.0
        assert LUCID_FLEX_25K.OFFICIAL_FIRM_MAX_MINIS == 2
        assert LUCID_FLEX_25K.OFFICIAL_FIRM_MAX_MICROS == 20
        assert LUCID_FLEX_25K.INTERNAL_RISK_CAP_MICROS == 10
        assert LUCID_FLEX_25K.MAX_MICRO_CONTRACTS == 10  # internal cap alias, not Lucid official max
        assert LUCID_FLEX_25K.CONSISTENCY_RULE_PCT == 40.0
        assert LUCID_FLEX_25K.CONSISTENCY_ADDON_PCT == 50.0

    def test_funded_payout_parameters(self):
        assert LUCID_FLEX_25K.FUNDED_STARTING_BALANCE == 25_000.0
        assert LUCID_FLEX_25K.FUNDED_INITIAL_FLOOR == 24_000.0
        assert LUCID_FLEX_25K.FUNDED_LOCKED_FLOOR == 25_100.0
        assert LUCID_FLEX_25K.PAYOUT_MIN_PROFIT_DAYS == 5
        assert LUCID_FLEX_25K.PAYOUT_MIN_DAILY_PROFIT == 100.0
        assert LUCID_FLEX_25K.PAYOUT_MIN_CYCLE_NET_PROFIT == 1.0
        assert LUCID_FLEX_25K.PAYOUT_PCT_OF_PROFIT == 0.50
        assert LUCID_FLEX_25K.PAYOUT_MIN_REQUEST == 500.0
        assert LUCID_FLEX_25K.PAYOUT_MAX_REQUEST == 1_000.0
        assert LUCID_FLEX_25K.PROFIT_SPLIT_TRADER_PCT == 90.0
        assert LUCID_FLEX_25K.PROFIT_SPLIT_PROP_PCT == 10.0
        assert LUCID_FLEX_25K.MIN_NET_PAYOUT_TO_TRADER == 450.0
        assert LUCID_FLEX_25K.MAX_NET_PAYOUT_TO_TRADER == 900.0
        assert LUCID_FLEX_25K.MAX_PAYOUTS_BEFORE_LIVE == 5

    def test_eod_floor_trailing_and_locking(self):
        # At start ($25,000 peak)
        assert LUCID_FLEX_25K.get_eod_floor(25_000.0) == 24_000.0
        # Below start (e.g. drawdown to $24,500, peak was $25,000)
        assert LUCID_FLEX_25K.get_eod_floor(25_000.0) == 24_000.0
        # Partial run-up (peak $25,500 -> floor $24,500)
        assert LUCID_FLEX_25K.get_eod_floor(25_500.0) == 24_500.0
        # Peak $26,000 -> floor $25,000
        assert LUCID_FLEX_25K.get_eod_floor(26_000.0) == 25_000.0
        # Peak reaches $26,100 -> floor locks permanently at $25,100
        assert LUCID_FLEX_25K.get_eod_floor(26_100.0) == 25_100.0
        # Peak continues to $27,500 -> floor remains locked at $25,100
        assert LUCID_FLEX_25K.get_eod_floor(27_500.0) == 25_100.0

    def test_payout_eligibility_scenarios(self):
        # Scenario 1: Only 4 days of $100 profit -> Ineligible
        assert not LUCID_FLEX_25K.is_payout_eligible(
            balance=26_500.0,
            profitable_days_count=4,
            cycle_net_profit=500.0,
            payouts_completed=0,
        )

        # Scenario 2: 5 days of profit, but daily profits < $100 (counted as 0) -> Ineligible
        assert not LUCID_FLEX_25K.is_payout_eligible(
            balance=26_500.0,
            profitable_days_count=0,
            cycle_net_profit=500.0,
            payouts_completed=0,
        )

        # Scenario 3: 5 days of >= $100, but balance is $25,900 (profit $900 * 50% = $450 < $500 min) -> Ineligible
        assert not LUCID_FLEX_25K.is_payout_eligible(
            balance=25_900.0,
            profitable_days_count=5,
            cycle_net_profit=900.0,
            payouts_completed=0,
        )

        # Scenario 4: Exactly $26,000 balance ($1,000 profit -> $500 payout) with 5 days >= $100 -> Eligible!
        assert LUCID_FLEX_25K.is_payout_eligible(
            balance=26_000.0,
            profitable_days_count=5,
            cycle_net_profit=1_000.0,
            payouts_completed=0,
        )

        # Scenario 5: Already completed 5 payouts -> Ineligible (must move to live)
        assert not LUCID_FLEX_25K.is_payout_eligible(
            balance=27_000.0,
            profitable_days_count=5,
            cycle_net_profit=1_000.0,
            payouts_completed=5,
        )

    def test_payout_calculations(self):
        # Minimum Payout ($26,000 balance)
        gross, net, post_bal = LUCID_FLEX_25K.calculate_payout(26_000.0, policy="immediate")
        assert gross == 500.0
        assert net == 450.0
        assert post_bal == 25_500.0
        # Remaining cushion if floor locked at $25,100:
        cushion = post_bal - 25_100.0
        assert cushion == 400.0
        assert LUCID_FLEX_25K.get_required_post_payout_cushion(500.0) == 400.0

        # Maximum Payout ($27,000 balance)
        gross_max, net_max, post_bal_max = LUCID_FLEX_25K.calculate_payout(27_000.0, policy="immediate")
        assert gross_max == 500.0  # Under immediate policy, extracts min $500 immediately
        gross_patient, net_patient, post_bal_patient = LUCID_FLEX_25K.calculate_payout(27_000.0, policy="patient")
        assert gross_patient == 1_000.0
        assert net_patient == 900.0
        assert post_bal_patient == 26_000.0
        # Remaining cushion if floor locked at $25,100:
        cushion_max = post_bal_patient - 25_100.0
        assert cushion_max == 900.0
        assert LUCID_FLEX_25K.get_required_post_payout_cushion(1_000.0) == 900.0

        # Patient policy waiting: balance $26,500 (available $750) -> returns 0.0 until $27,000
        gross_wait, _, _ = LUCID_FLEX_25K.calculate_payout(26_500.0, policy="patient")
        assert gross_wait == 0.0

        # Adaptive policy with target $750:
        gross_adapt, net_adapt, post_bal_adapt = LUCID_FLEX_25K.calculate_payout(26_500.0, policy="adaptive", target_payout=750.0)
        assert gross_adapt == 750.0
        assert net_adapt == 675.0
        assert post_bal_adapt == 25_750.0
        assert LUCID_FLEX_25K.get_required_post_payout_cushion(750.0) == 650.0

        # Dynamic Cushion Linear Interpolation tests
        assert LUCID_FLEX_25K.get_required_post_payout_cushion(500.0) == 400.0
        assert LUCID_FLEX_25K.get_required_post_payout_cushion(600.0) == 500.0
        assert LUCID_FLEX_25K.get_required_post_payout_cushion(700.0) == 600.0
        assert LUCID_FLEX_25K.get_required_post_payout_cushion(800.0) == 700.0
        assert LUCID_FLEX_25K.get_required_post_payout_cushion(900.0) == 800.0
        assert LUCID_FLEX_25K.get_required_post_payout_cushion(1_000.0) == 900.0
        # Bounds checking
        assert LUCID_FLEX_25K.get_required_post_payout_cushion(400.0) == 400.0
        assert LUCID_FLEX_25K.get_required_post_payout_cushion(1200.0) == 900.0

    def test_standing_rules_files_contain_lucid_specs(self):
        """Verifies that AGENTS.md, GEMINI.md, and wiki have the exact specs written."""
        agents_text = (REPO_ROOT / "AGENTS.md").read_text()
        gemini_text = (REPO_ROOT / "GEMINI.md").read_text()
        wiki_text = (REPO_ROOT / "wiki/prop_firm/lucid-flex-25k.md").read_text()

        for content in [agents_text, gemini_text, wiki_text]:
            assert "$25,000.00" in content
            assert "$1,250.00" in content
            assert "$39.00" in content
            assert "$1,000.00" in content
            assert "$25,100.00" in content
            assert "$600.00" in content
            assert "5 separate" in content
            assert "$100.00" in content
            assert "$500.00" in content
            assert "$1,000.00" in content
            assert "90/10" in content
