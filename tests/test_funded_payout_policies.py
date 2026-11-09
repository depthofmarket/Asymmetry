"""
Comprehensive Unit & Regression Tests: Funded Account Rules & Withdrawal Policies.
===================================================================================
Covers all 17 compliance & execution requirements for the LucidFlex 25K account:
1. Exactly $100 of daily profit qualifies.
2. Daily profit below $100 does not qualify.
3. Multiple profitable trades on one day count as one qualifying day.
4. Five separate qualifying days are required.
5. Four qualifying days do not permit a payout.
6. The fifth qualifying day makes the account eligible (if balance satisfies threshold).
7. The $500 minimum payout rule.
8. The $1,000 maximum payout cap.
9. Correct 90/10 payout calculations.
10. Correct $450 and $900 trader net examples.
11. Correct $400 and $900 post-payout cushion endpoints.
12. Correct cushion interpolation.
13. Payout-cycle reset behavior.
14. No duplicate payout processing.
15. No sixth funded-account payout.
16. Correct promotion after the fifth successful payout.
17. Correct behavior when an account breaches its drawdown limit.
18. Consistency between FundedRules, simulation results, and prop firm registry.
"""

from pathlib import Path
import pytest
import numpy as np

from backtest.dashboard_analytics import (
    FundedRules,
    Leg,
    PropRules,
    SizingPolicy,
    compute_pareto_frontier_3d,
    run_funded,
)
from config.prop_firm_registry import LUCID_FLEX_25K
import pandas as pd


def _make_dummy_leg(pnl_per_contract: float, order: int = 1) -> Leg:
    """Creates a dummy leg with 0 extra ticks and 1 contract multiplier."""
    return Leg(
        order=order,
        sym="NQ",
        micro="MNQ",
        per_contract=pnl_per_contract,
        research=pnl_per_contract,
        research_contracts=1,
        s1_pair=False,
    )


def _make_single_leg_session(day_pnl: float) -> list[list[Leg]]:
    """Creates a session with one group containing one leg of net PnL = day_pnl."""
    return [[_make_dummy_leg(day_pnl)]]


def _make_multi_trade_session(trade_pnls: list[float]) -> list[list[Leg]]:
    """Creates a session with multiple distinct trade groups."""
    return [[_make_dummy_leg(pnl, order=idx + 1)] for idx, pnl in enumerate(trade_pnls)]


class TestFundedAccountRulesAndPayoutPolicies:
    """Rigorous compliance tests for LucidFlex 25K Funded Account & Payout Policies."""

    @pytest.fixture
    def policy(self):
        return SizingPolicy("fixed_1", "fixed", fixed=1)

    @pytest.fixture
    def funded_rules(self):
        return FundedRules()

    def test_req01_exactly_100_qualifies(self, policy, funded_rules):
        """Req 1: Exactly $100.00 of daily net profit qualifies as a profitable day."""
        # 1 session with exactly $100.00
        sessions = [_make_single_leg_session(100.0)]
        res = run_funded(sessions, policy=policy, funded=funded_rules)
        assert res["qualifying_days_to_p1"] == 1

    def test_req02_below_100_does_not_qualify(self, policy, funded_rules):
        """Req 2: Daily profit below $100 (e.g., $99.99) does NOT qualify."""
        sessions = [_make_single_leg_session(99.99)]
        res = run_funded(sessions, policy=policy, funded=funded_rules)
        assert res["qualifying_days_to_p1"] == 0

    def test_req03_multiple_profitable_trades_one_session_counts_as_one(self, policy, funded_rules):
        """Req 3: Multiple profitable trades on the same day count as only one qualifying day."""
        # 3 separate winning trades on same session summing to $300
        sessions = [_make_multi_trade_session([100.0, 100.0, 100.0])]
        res = run_funded(sessions, policy=policy, funded=funded_rules)
        assert res["qualifying_days_to_p1"] == 1

    def test_req04_and_05_four_days_do_not_permit_payout(self, policy, funded_rules):
        """Req 4 & 5: Five separate qualifying days are required; 4 days do not permit payout."""
        # 4 sessions of $300 profit each ($1,200 total profit, balance $26,200)
        sessions = [_make_single_leg_session(300.0) for _ in range(4)]
        res = run_funded(sessions, policy=policy, funded=funded_rules, withdrawal_policy="immediate")
        assert len(res["payouts"]) == 0
        assert res["completed_payouts"] == 0
        assert res["qualifying_days_to_p1"] == 4

    def test_req06_fifth_qualifying_day_makes_account_eligible(self, policy, funded_rules):
        """Req 6: The fifth qualifying day triggers payout if balance requirement is met."""
        # 5 sessions of $200 each ($1,000 total profit -> balance $26,000)
        sessions = [_make_single_leg_session(200.0) for _ in range(5)]
        res = run_funded(sessions, policy=policy, funded=funded_rules, withdrawal_policy="immediate")
        assert len(res["payouts"]) == 1
        assert res["completed_payouts"] == 1
        assert res["payouts"][0][0] == 5  # occurred on session 5
        assert res["payouts"][0][1] == 450.0  # trader net $450

    def test_req07_min_payout_rule_500_gross(self, policy, funded_rules):
        """Req 7: Minimum gross payout is $500. Balance < $26,000 cannot withdraw even with 5 days."""
        # 5 sessions of $100 each -> $500 profit -> balance $25,500. 50% profit = $250 < $500 min!
        sessions = [_make_single_leg_session(100.0) for _ in range(5)]
        res = run_funded(sessions, policy=policy, funded=funded_rules, withdrawal_policy="immediate")
        assert len(res["payouts"]) == 0  # Cannot withdraw below $500 minimum!

    def test_req08_max_payout_cap_1000_gross(self, policy, funded_rules):
        """Req 8: Maximum gross payout request is capped at $1,000."""
        # 5 sessions of $1,000 each -> balance $30,000 ($5,000 profit). 50% is $2,500 -> capped at $1,000!
        sessions = [_make_single_leg_session(1000.0) for _ in range(5)]
        res = run_funded(sessions, policy=policy, funded=funded_rules, withdrawal_policy="patient")
        assert len(res["payouts"]) == 1
        p_record = res["payout_records"][0]
        assert p_record["gross_payout"] == 1_000.0
        assert p_record["trader_net"] == 900.0
        assert p_record["firm_share"] == 100.0

    def test_req09_and_10_correct_90_10_split_and_examples(self, policy, funded_rules):
        """Req 9 & 10: Correct 90/10 payout split ($450 net on $500 gross; $900 net on $1,000 gross)."""
        # Minimum scenario: balance $26,000
        sess_min = [_make_single_leg_session(200.0) for _ in range(5)]
        res_min = run_funded(sess_min, policy=policy, funded=funded_rules, withdrawal_policy="immediate")
        rec_min = res_min["payout_records"][0]
        assert rec_min["gross_payout"] == 500.0
        assert rec_min["trader_net"] == 450.0
        assert rec_min["firm_share"] == 50.0

        # Maximum scenario: balance $27,000
        sess_max = [_make_single_leg_session(400.0) for _ in range(5)]
        res_max = run_funded(sess_max, policy=policy, funded=funded_rules, withdrawal_policy="patient")
        rec_max = res_max["payout_records"][0]
        assert rec_max["gross_payout"] == 1_000.0
        assert rec_max["trader_net"] == 900.0
        assert rec_max["firm_share"] == 100.0

    def test_req11_and_12_post_payout_cushion_endpoints_and_interpolation(self, funded_rules):
        """Req 11 & 12: Correct $400 and $900 cushion endpoints and linear interpolation."""
        assert funded_rules.required_post_payout_cushion(500.0) == 400.0
        assert funded_rules.required_post_payout_cushion(1_000.0) == 900.0
        assert funded_rules.required_post_payout_cushion(750.0) == 650.0
        assert funded_rules.required_post_payout_cushion(600.0) == 500.0
        assert funded_rules.required_post_payout_cushion(900.0) == 800.0

    def test_req13_and_14_payout_cycle_reset_and_no_duplicate(self, policy, funded_rules):
        """Req 13 & 14: Qualifying-day counter resets to 0 after payout, no duplicate payouts."""
        # 5 sessions of $200 each -> Payout 1 on session 5.
        # Then session 6 has $0 profit. Payout should NOT fire again on session 6.
        sessions = [_make_single_leg_session(200.0) for _ in range(5)] + [_make_single_leg_session(0.0)]
        res = run_funded(sessions, policy=policy, funded=funded_rules, withdrawal_policy="immediate")
        assert len(res["payouts"]) == 1
        assert res["completed_payouts"] == 1

        # Now add 5 more qualifying sessions of $200 each ($1,000 profit in cycle 2)
        sessions_cycle2 = sessions + [_make_single_leg_session(200.0) for _ in range(5)]
        res2 = run_funded(sessions_cycle2, policy=policy, funded=funded_rules, withdrawal_policy="immediate")
        assert len(res2["payouts"]) == 2
        assert res2["completed_payouts"] == 2
        assert res2["payout_records"][1]["payout_number"] == 2
        assert res2["payout_records"][1]["session"] == 11

    def test_req15_and_16_max_five_payouts_and_live_promotion(self, policy, funded_rules):
        """Req 15 & 16: Account is promoted to live after 5th payout; no 6th payout allowed."""
        # 5 cycles of 5 sessions with $200 profit each = 25 sessions
        # Plus 10 extra sessions of $200 profit each
        sessions = [_make_single_leg_session(200.0) for _ in range(35)]
        res = run_funded(sessions, policy=policy, funded=funded_rules, withdrawal_policy="immediate")
        assert res["status"] == "promoted_to_live"
        assert len(res["payouts"]) == 5
        assert res["completed_payouts"] == 5
        # Verify 5th payout occurred on session 25
        assert res["payouts"][4][0] == 25
        # Total trader net across 5 payouts = 5 * $450 = $2,250
        assert sum(p[1] for p in res["payouts"]) == 2_250.0

    def test_req17_drawdown_breach_and_infant_mortality(self, policy, funded_rules):
        """Req 17: Account breaching trailing floor terminates immediately with breach status."""
        # Session 1: -$1,050 loss -> breaches $24,000 floor immediately
        sessions = [_make_single_leg_session(-1050.0)]
        res = run_funded(sessions, policy=policy, funded=funded_rules)
        assert res["status"] == "breach"
        assert res["sessions"] == 1
        assert res["infant_mortality"] is True
        assert len(res["payouts"]) == 0

    def test_req18_consistency_with_prop_firm_registry(self, funded_rules):
        """Req 18: FundedRules defaults match LUCID_FLEX_25K in config.prop_firm_registry."""
        assert funded_rules.min_profit_days == LUCID_FLEX_25K.PAYOUT_MIN_PROFIT_DAYS == 5
        assert funded_rules.profit_day_threshold == LUCID_FLEX_25K.PAYOUT_MIN_DAILY_PROFIT == 100.0
        assert funded_rules.min_cycle_net_profit == LUCID_FLEX_25K.PAYOUT_MIN_CYCLE_NET_PROFIT == 1.0
        assert funded_rules.min_payout == LUCID_FLEX_25K.PAYOUT_MIN_REQUEST == 500.0
        assert funded_rules.max_payout == LUCID_FLEX_25K.PAYOUT_MAX_REQUEST == 1_000.0
        assert funded_rules.payout_fraction == LUCID_FLEX_25K.PAYOUT_PCT_OF_PROFIT == 0.50
        assert funded_rules.split == (LUCID_FLEX_25K.PROFIT_SPLIT_TRADER_PCT / 100.0) == 0.90
        assert funded_rules.max_payouts == LUCID_FLEX_25K.MAX_PAYOUTS_BEFORE_LIVE == 5
        assert funded_rules.post_payout_floor == LUCID_FLEX_25K.FUNDED_LOCKED_FLOOR == 25_100.0
        assert funded_rules.start_balance == LUCID_FLEX_25K.FUNDED_STARTING_BALANCE == 25_000.0
        assert funded_rules.max_trailing_dd == LUCID_FLEX_25K.FUNDED_TRAILING_ALLOWANCE == 1_000.0
        assert funded_rules.floor_lock_peak == LUCID_FLEX_25K.FUNDED_FLOOR_LOCK_PEAK == 26_100.0

    def test_withdrawal_policies_behavioral_comparison(self, policy, funded_rules):
        """Tests that Policies A, B, and C behave distinctly on identical equity paths."""
        # Scenario: Account generates $200 for 5 sessions (balance $26,000),
        # then $200 for 5 more sessions (balance $27,000 before any withdrawal).
        sessions_10 = [_make_single_leg_session(200.0) for _ in range(10)]

        # Policy A: Takes $500 payout at session 5 (balance $26,000 -> $25,500),
        # then continues and on session 10 has completed 5 more days of $200 -> balance $26,500 -> takes 2nd payout!
        res_a = run_funded(sessions_10, policy=policy, funded=funded_rules, withdrawal_policy="immediate")
        assert len(res_a["payouts"]) == 2
        assert res_a["payout_records"][0]["gross_payout"] == 500.0
        assert res_a["payout_records"][0]["session"] == 5
        assert res_a["payout_records"][1]["gross_payout"] == 500.0
        assert res_a["payout_records"][1]["session"] == 10

        # Policy B: Waited at session 5 because available payout was only $500 < $1,000!
        # At session 10, balance reached $27,000 -> takes $1,000 payout!
        res_b = run_funded(sessions_10, policy=policy, funded=funded_rules, withdrawal_policy="patient")
        assert len(res_b["payouts"]) == 1
        assert res_b["payout_records"][0]["gross_payout"] == 1_000.0
        assert res_b["payout_records"][0]["session"] == 10
        assert res_b["payout_records"][0]["post_cushion"] == 900.0

        # Policy C (two_stage):
        # Payout 1 (session 5): Takes $500 immediately to suppress infant mortality! Post cushion = $400.
        # Payout 2: Target is $1,000. On sessions 6-10, account gains $1,000 (balance $26,500). Available is $750 < $1,000.
        # Policy C waits to accumulate full cushion, so len(payouts) == 1 on session 10!
        res_c = run_funded(sessions_10, policy=policy, funded=funded_rules, withdrawal_policy="adaptive", adaptive_threshold=1000.0, adaptive_mode="two_stage")
        assert len(res_c["payouts"]) == 1
        assert res_c["payout_records"][0]["gross_payout"] == 500.0
        assert res_c["payout_records"][0]["session"] == 5

    def test_three_authoritative_reference_scenarios(self, policy, funded_rules):
        """
        Regression test for all three authoritative reference scenarios:
        1. Pre-cushion $900  | Balance $26,000 | Gross $500   | Post-cushion $400
        2. Pre-cushion $1,400| Balance $26,500 | Gross $750   | Post-cushion $650
        3. Pre-cushion $1,900| Balance $27,000 | Gross $1,000 | Post-cushion $900
        Also verifies that a $1,000 payout cannot be triggered at a $1,400 cushion.
        """
        # Scenario 1: Exactly $26,000 balance ($1,000 profit across 5 days of $200)
        sess_scen1 = [_make_single_leg_session(200.0) for _ in range(5)]
        res1 = run_funded(sess_scen1, policy=policy, funded=funded_rules, withdrawal_policy="immediate")
        assert len(res1["payouts"]) == 1
        rec1 = res1["payout_records"][0]
        assert rec1["pre_balance"] == 26_000.0
        assert rec1["pre_balance"] - rec1["floor"] == 900.0  # Pre-cushion $900
        assert rec1["gross_payout"] == 500.0
        assert rec1["trader_net"] == 450.0
        assert rec1["firm_share"] == 50.0
        assert rec1["post_balance"] == 25_500.0
        assert rec1["post_cushion"] == 400.0  # Post-cushion $400 exactly

        # Scenario 2: Exactly $26,500 balance ($1,500 profit across 5 days of $300)
        # Testing Policy D (Fixed $750 threshold) and Policy C2
        sess_scen2 = [_make_single_leg_session(300.0) for _ in range(5)]
        res2_d = run_funded(sess_scen2, policy=policy, funded=funded_rules, withdrawal_policy="adaptive", adaptive_threshold=750.0, adaptive_mode="fixed_target")
        assert len(res2_d["payouts"]) == 1
        rec2 = res2_d["payout_records"][0]
        assert rec2["pre_balance"] == 26_500.0
        assert rec2["pre_balance"] - rec2["floor"] == 1_400.0  # Pre-cushion $1,400
        assert rec2["gross_payout"] == 750.0
        assert rec2["trader_net"] == 675.0
        assert rec2["firm_share"] == 75.0
        assert rec2["post_balance"] == 25_750.0
        assert rec2["post_cushion"] == 650.0  # Post-cushion $650 exactly

        # Invalidation check: At $1,400 pre-cushion ($26,500 balance), a $1,000 payout cannot be triggered
        res2_patient = run_funded(sess_scen2, policy=policy, funded=funded_rules, withdrawal_policy="patient")
        assert len(res2_patient["payouts"]) == 0  # Patient harvest refuses $1,000 payout because cushion is only $1,400

        # Scenario 3: Exactly $27,000 balance ($2,000 profit across 5 days of $400)
        sess_scen3 = [_make_single_leg_session(400.0) for _ in range(5)]
        res3 = run_funded(sess_scen3, policy=policy, funded=funded_rules, withdrawal_policy="patient")
        assert len(res3["payouts"]) == 1
        rec3 = res3["payout_records"][0]
        assert rec3["pre_balance"] == 27_000.0
        assert rec3["pre_balance"] - rec3["floor"] == 1_900.0  # Pre-cushion $1,900
        assert rec3["gross_payout"] == 1_000.0
        assert rec3["trader_net"] == 900.0
        assert rec3["firm_share"] == 100.0
        assert rec3["post_balance"] == 26_000.0
        assert rec3["post_cushion"] == 900.0  # Post-cushion $900 exactly

    def test_policy_c2_adaptive_cushion_aware_behavior(self, policy, funded_rules):
        """
        Verifies Policy C2:
        - Payout 1: harvests $500 minimum at $26,000 balance to suppress Infant Mortality.
        - Payout 2: if cushion reaches >= $1,400 ($26,500 balance), harvests available profit ($750).
        - Payout 3: if cushion reaches >= $1,900 ($27,000 balance), harvests full cap ($1,000).
        """
        # Cycle 1: 5 days of $200 = $1,000 profit -> balance $26,000 -> P1 takes $500 -> balance becomes $25,500
        c1 = [_make_single_leg_session(200.0) for _ in range(5)]
        # Cycle 2: 5 days of $200 = $1,000 profit -> balance $26,500 (pre-cushion $1,400) -> P2 takes $750 -> balance becomes $25,750
        c2 = [_make_single_leg_session(200.0) for _ in range(5)]
        # Cycle 3: 5 days of $250 = $1,250 profit -> balance $27,000 (pre-cushion $1,900) -> P3 takes $1,000 -> balance becomes $26,000
        c3 = [_make_single_leg_session(250.0) for _ in range(5)]

        res = run_funded(c1 + c2 + c3, policy=policy, funded=funded_rules, withdrawal_policy="adaptive", adaptive_mode="cushion_aware")
        assert len(res["payouts"]) == 3
        # P1: $500 gross ($450 net)
        assert res["payout_records"][0]["gross_payout"] == 500.0
        assert res["payout_records"][0]["post_cushion"] == 400.0
        # P2: $750 gross ($675 net)
        assert res["payout_records"][1]["gross_payout"] == 750.0
        assert res["payout_records"][1]["post_cushion"] == 650.0
        # P3: $1,000 gross ($900 net)
        assert res["payout_records"][2]["gross_payout"] == 1000.0
        assert res["payout_records"][2]["post_cushion"] == 900.0

    def test_v4_pareto_frontier_3d_authoritative_five_policies(self):
        """
        V4 Req 1: Verifies that on the authoritative 5-policy table:
        - Policy A, Policy B, Policy C, and Policy D are ALL Pareto-Optimal (nondominated).
        - Policy C2 is strictly dominated by Policy C.
        """
        df = pd.DataFrame([
            {"policy_key": "policy_a_immediate", "net_lifetime_ev": 948.39, "infant_mortality_pct": 19.38, "live_promotion_pct": 43.16},
            {"policy_key": "policy_b_patient", "net_lifetime_ev": 1837.68, "infant_mortality_pct": 30.95, "live_promotion_pct": 41.46},
            {"policy_key": "policy_c_adaptive_two_stage", "net_lifetime_ev": 1540.68, "infant_mortality_pct": 19.38, "live_promotion_pct": 38.05},
            {"policy_key": "policy_d_fixed_750", "net_lifetime_ev": 1382.08, "infant_mortality_pct": 27.05, "live_promotion_pct": 41.45},
            {"policy_key": "policy_c2_cushion_aware", "net_lifetime_ev": 1419.99, "infant_mortality_pct": 19.38, "live_promotion_pct": 34.53},
        ])
        res = compute_pareto_frontier_3d(df)
        pareto_map = dict(zip(res["policy_key"], res["is_pareto_3d"]))
        dom_map = dict(zip(res["policy_key"], res["dominated_by"]))

        assert pareto_map["policy_a_immediate"] is True
        assert pareto_map["policy_b_patient"] is True
        assert pareto_map["policy_c_adaptive_two_stage"] is True
        assert pareto_map["policy_d_fixed_750"] is True
        assert pareto_map["policy_c2_cushion_aware"] is False
        assert dom_map["policy_d_fixed_750"] == "None"
        assert dom_map["policy_c2_cushion_aware"] == "policy_c_adaptive_two_stage"

    def test_v4_pareto_frontier_3d_synthetic_dominance_and_ties(self):
        """
        V4 Req 1: Tests synthetic dominated, nondominated, and exact tie edge cases.
        """
        df = pd.DataFrame([
            {"policy_key": "P1_tie", "net_lifetime_ev": 1000.0, "infant_mortality_pct": 20.0, "live_promotion_pct": 40.0},
            {"policy_key": "P2_tie", "net_lifetime_ev": 1000.0, "infant_mortality_pct": 20.0, "live_promotion_pct": 40.0},
            {"policy_key": "P3_dom_ev", "net_lifetime_ev": 999.0, "infant_mortality_pct": 20.0, "live_promotion_pct": 40.0},
            {"policy_key": "P4_dom_im", "net_lifetime_ev": 1000.0, "infant_mortality_pct": 20.5, "live_promotion_pct": 40.0},
            {"policy_key": "P5_dom_promo", "net_lifetime_ev": 1000.0, "infant_mortality_pct": 20.0, "live_promotion_pct": 39.5},
            {"policy_key": "P6_nondom_tradeoff", "net_lifetime_ev": 900.0, "infant_mortality_pct": 18.0, "live_promotion_pct": 35.0},
        ])
        res = compute_pareto_frontier_3d(df)
        pareto_map = dict(zip(res["policy_key"], res["is_pareto_3d"]))
        assert pareto_map["P1_tie"] is True
        assert pareto_map["P2_tie"] is True
        assert pareto_map["P3_dom_ev"] is False
        assert pareto_map["P4_dom_im"] is False
        assert pareto_map["P5_dom_promo"] is False
        assert pareto_map["P6_nondom_tradeoff"] is True

    def test_v4_trailing_floor_lock_at_26100_permanent_hwm(self, policy, funded_rules):
        """
        V4 Req 8B: Verifies high-water mark trailing floor mechanics:
        - Starts at $24,000.00
        - Trails $1,000 behind EOD peak below $26,100
        - Locks permanently at $25,100 once EOD peak >= $26,100
        - Never decreases on subsequent losing days or after payouts
        """
        # Day 1: +$600 -> bal $25,600 -> floor trails to $24,600
        # Day 2: +$450 -> bal $26,050 -> floor trails to $25,050 (still < $26,100)
        # Day 3: +$150 -> bal $26,200 (>= $26,100!) -> floor locks at $25,100
        # Day 4: -$500 -> bal $25,700 -> floor remains locked at $25,100
        sessions = [
            _make_single_leg_session(600.0),
            _make_single_leg_session(450.0),
            _make_single_leg_session(150.0),
            _make_single_leg_session(-500.0),
        ]
        res = run_funded(sessions, policy=policy, funded=funded_rules, keep_path=True)
        # floor_path records floor at start of session [0] and during each session [1..4]
        # Let's check LUCID_FLEX_25K.get_eod_floor directly as well:
        assert LUCID_FLEX_25K.get_eod_floor(25_000.0) == 24_000.0
        assert LUCID_FLEX_25K.get_eod_floor(25_600.0) == 24_600.0
        assert LUCID_FLEX_25K.get_eod_floor(26_050.0) == 25_050.0
        assert LUCID_FLEX_25K.get_eod_floor(26_100.0) == 25_100.0
        assert LUCID_FLEX_25K.get_eod_floor(28_000.0) == 25_100.0
        # In run_funded:
        # Session 1 starts with floor 24,000 -> after EOD 1 ($25,600), floor becomes 24,600 (used in session 2)
        # Session 2 starts with floor 24,600 -> after EOD 2 ($26,050), floor becomes 25,050 (used in session 3)
        # Session 3 starts with floor 25,050 -> after EOD 3 ($26,200), floor locks at 25,100 (used in session 4)
        assert res["floor_path"] == [24_000.0, 24_000.0, 24_600.0, 25_050.0, 25_100.0]

    def test_v4_funded_contract_sizing_cppi_deleveraging_and_recovery(self, funded_rules):
        """
        V4 Req 8C: Verifies funded contract sizing:
        - Day 1 starts at 2 micros (profit=0, cushion=$1,000 >= $400)
        - Scales to 3 micros at profit >= $250, 4 micros at profit >= $500
        - De-levers to 1 micro when cushion < $400
        - Recovers to normal ratchet sizing once cushion >= $400
        - Does not cap sizing at $1,150 in funded mode (closeout_thresh=0.0)
        """
        funded_pol = SizingPolicy(
            name="Funded_Optimal",
            kind="ratchet",
            tiers=((500.0, 4), (250.0, 3), (-np.inf, 2)),
            cushion_floor_buffer=400.0,
            dynamic_delever_contracts=1,
            closeout_thresh=0.0,
            closeout_contracts=1,
        )
        # Day 1: profit = 0, cushion = 1000 -> 2 micros
        assert funded_pol.total_micros(profit=0.0, cushion=1000.0) == 2
        # Profit = $300, cushion = $1,000 -> 3 micros
        assert funded_pol.total_micros(profit=300.0, cushion=1000.0) == 3
        # Profit = $600, cushion = $1,000 -> 4 micros
        assert funded_pol.total_micros(profit=600.0, cushion=1000.0) == 4
        # Profit = $1,500, cushion = $1,400 -> still 4 micros (no evaluation closeout shield)
        assert funded_pol.total_micros(profit=1500.0, cushion=1400.0) == 4
        # Drawdown brings cushion to $350 (< $400) -> CPPI de-levers to 1 micro even if profit > $250!
        assert funded_pol.total_micros(profit=350.0, cushion=350.0) == 1
        assert funded_pol.total_micros(profit=-650.0, cushion=350.0) == 1
        # Recovery brings cushion back to $400.0 -> restores normal tier (2 micros at profit <= $250, 3 micros at profit >= $250)
        assert funded_pol.total_micros(profit=100.0, cushion=400.0) == 2
        assert funded_pol.total_micros(profit=300.0, cushion=400.0) == 3

    def test_v4_live_promotion_prohibits_post_promotion_withdrawals_and_earnings(self, policy, funded_rules):
        """
        V4 Req 8E: Verifies that upon completing the 5th payout, the account immediately transitions
        to 'promoted_to_live', stops processing further funded sessions, prohibits a 6th withdrawal,
        and does not fabricate post-promotion live brokerage earnings.
        """
        # 5 cycles of 5 days at +$400/day -> 5 payouts of $1,000 gross ($900 net each) by session 25
        # Followed by 20 more days of +$1,000/day
        sessions = [_make_single_leg_session(400.0) for _ in range(25)] + [_make_single_leg_session(1000.0) for _ in range(20)]
        res = run_funded(sessions, policy=policy, funded=funded_rules, withdrawal_policy="patient", keep_path=True)
        assert res["status"] == "promoted_to_live"
        assert res["sessions"] == 25  # Terminated at session 25, ignoring sessions 26..45
        assert res["completed_payouts"] == 5
        assert len(res["payouts"]) == 5
        assert sum(p[1] for p in res["payouts"]) == 4_500.0  # Exactly 5 * $900, zero post-promotion fabricated earnings



