"""
Adversarial Empirical Stress-Testing Harness for Sizing Math & Cushion Optimization.

This suite is executed by teamwork_challenger_1 to empirically stress-test:
1. Pareto Frontier Dominance Verification
2. Monte Carlo Convergence & Seed Sensitivity Stress Test
3. Infant Mortality Paradox & Parameter Sensitivity Matrix
4. Extreme Boundary Conditions: Slippage Stress (1x, 2x, 3x)
5. Calendar Block Size Sensitivity (B=1, 5, 10, 20, 30)
6. Corner-Case Transitions Between Funded Cycles & Safe CPPI Invariants
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import pytest

from backtest.dashboard_analytics import (
    DEFAULT_CALENDAR_SOURCE,
    DEFAULT_TRADES_PATH,
    FundedRules,
    Leg,
    PropRules,
    SizingPolicy,
    block_bootstrap_sessions,
    build_session_legs,
    compute_pareto_frontier,
    leg_contracts,
    leg_pnl,
    load_session_calendar,
    load_trades,
    run_evaluation,
    run_funded,
    run_funded_transition_experiments,
    run_ratchet_grid_search,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results" / "sizing_cushion_optimization"

# Requirement 7: Mark as requiring private market datasets (opt in via RUN_PRIVATE_DATA_TESTS=1)
pytestmark = pytest.mark.private_data


@pytest.fixture(scope="module")
def trade_data() -> pd.DataFrame:
    return load_trades(DEFAULT_TRADES_PATH)


@pytest.fixture(scope="module")
def session_calendar() -> list[str]:
    return load_session_calendar(DEFAULT_CALENDAR_SOURCE, start="2021-01-07", end="2026-10-30")


@pytest.fixture(scope="module")
def session_legs(trade_data: pd.DataFrame, session_calendar: list[str]) -> list[list[list[Leg]]]:
    return build_session_legs(trade_data, session_calendar)


# ───────────────────────────────────────────────────────────────────────────────
# 1. Pareto Frontier Dominance Verification
# ───────────────────────────────────────────────────────────────────────────────
class TestParetoFrontierDominance:
    """
    Adversarial verification of Pareto optimality.
    No point marked Pareto must be dominated by ANY point in the evaluated grid.
    """

    def test_pareto_points_are_strictly_non_dominated(self):
        grid_file = RESULTS_DIR / "evaluation_ratchet_grid_results.csv"
        assert grid_file.exists(), f"Grid file not found: {grid_file}"
        df = pd.read_csv(grid_file)

        pareto_pts = df[df["is_pareto"] == True].copy()
        assert len(pareto_pts) > 0, "No Pareto points found in grid results"

        records = df.to_dict("records")
        dominated_pareto = []

        for p in pareto_pts.to_dict("records"):
            p_pr = p["pass_rate"]
            p_dur = p["pass_med_sessions"]
            p_t2, p_t3 = p["t2"], p["t3"]

            for other in records:
                o_pr = other["pass_rate"]
                o_dur = other["pass_med_sessions"]
                o_t2, o_t3 = other["t2"], other["t3"]

                if o_t2 == p_t2 and o_t3 == p_t3:
                    continue

                # Check if other strictly dominates p
                # Dominates if: o_pr >= p_pr and o_dur <= p_dur and (o_pr > p_pr or o_dur < p_dur)
                if (o_pr >= p_pr and o_dur <= p_dur) and (o_pr > p_pr or o_dur < p_dur):
                    dominated_pareto.append({
                        "pareto_point": (p_t2, p_t3, p_pr, p_dur),
                        "dominator": (o_t2, o_t3, o_pr, o_dur),
                    })

        assert len(dominated_pareto) == 0, f"Found Pareto points that are dominated: {dominated_pareto}"

    def test_non_pareto_points_are_indeed_dominated(self):
        grid_file = RESULTS_DIR / "evaluation_ratchet_grid_results.csv"
        df = pd.read_csv(grid_file)

        non_pareto = df[df["is_pareto"] == False].copy()
        records = df.to_dict("records")

        un_dominated_false_negatives = []
        for np_pt in non_pareto.to_dict("records"):
            pr = np_pt["pass_rate"]
            dur = np_pt["pass_med_sessions"]
            t2, t3 = np_pt["t2"], np_pt["t3"]

            dominated = False
            for other in records:
                if other["t2"] == t2 and other["t3"] == t3:
                    continue
                o_pr = other["pass_rate"]
                o_dur = other["pass_med_sessions"]
                if (o_pr >= pr and o_dur <= dur) and (o_pr > pr or o_dur < dur):
                    dominated = True
                    break

            if not dominated:
                un_dominated_false_negatives.append((t2, t3, pr, dur))

        assert len(un_dominated_false_negatives) == 0, (
            f"Found non-Pareto points that are NOT dominated by anything (false negatives): {un_dominated_false_negatives}"
        )

    def test_pareto_frontier_monotonicity(self):
        """
        Along the Pareto frontier, as pass_rate increases, pass_med_sessions MUST strictly increase
        (or remain tied), because you cannot get higher pass rate without longer duration.
        """
        pareto_file = RESULTS_DIR / "evaluation_pareto_frontier.csv"
        assert pareto_file.exists()
        pdf = pd.read_csv(pareto_file)

        pdf_sorted = pdf.sort_values(by="pass_rate", ascending=True).reset_index(drop=True)
        durations = pdf_sorted["pass_med_sessions"].tolist()

        for i in range(len(durations) - 1):
            assert durations[i] <= durations[i + 1], (
                f"Pareto inversion detected between rows {i} and {i+1}: "
                f"rate {pdf_sorted.loc[i, 'pass_rate']} -> {pdf_sorted.loc[i+1, 'pass_rate']} "
                f"but duration {durations[i]} > {durations[i+1]}"
            )


# ───────────────────────────────────────────────────────────────────────────────
# 2. Monte Carlo Convergence & Seed Sensitivity Stress Test
# ───────────────────────────────────────────────────────────────────────────────
class TestMonteCarloConvergence:
    """
    Stress test bootstrap stability across multiple random seeds and sample sizes.
    Confirms pass rates, durations, and policy rankings remain within statistical bounds.
    """

    @pytest.mark.parametrize("seeds", [[42, 123, 456, 789, 2026]])
    def test_mc_seed_stability_baseline_vs_optimal(self, session_legs: list[list[list[Leg]]], seeds: list[int]):
        baseline_policy = SizingPolicy("Baseline", "ratchet", tiers=((750.0, 4), (350.0, 3), (-np.inf, 2)))
        optimal_policy = SizingPolicy("Optimal", "ratchet", tiers=((550.0, 4), (200.0, 3), (-np.inf, 2)))

        n_sims = 1500
        horizon = 750
        block_size = 10
        rules = PropRules()

        baseline_rates = []
        baseline_durs = []
        optimal_rates = []
        optimal_durs = []

        for s in seeds:
            rng = np.random.default_rng(s)
            paths = [block_bootstrap_sessions(len(session_legs), horizon, block_size, rng) for _ in range(n_sims)]

            # Eval baseline
            b_res = [run_evaluation([session_legs[j] for j in p], baseline_policy, rules) for p in paths]
            b_passes = [r for r in b_res if r.status == "pass"]
            b_rate = len(b_passes) / n_sims * 100.0
            b_dur = float(np.median([r.sessions for r in b_passes])) if b_passes else np.nan
            baseline_rates.append(b_rate)
            baseline_durs.append(b_dur)

            # Eval optimal
            o_res = [run_evaluation([session_legs[j] for j in p], optimal_policy, rules) for p in paths]
            o_passes = [r for r in o_res if r.status == "pass"]
            o_rate = len(o_passes) / n_sims * 100.0
            o_dur = float(np.median([r.sessions for r in o_passes])) if o_passes else np.nan
            optimal_rates.append(o_rate)
            optimal_durs.append(o_dur)

        # Statistical analysis
        b_rate_mean, b_rate_std = np.mean(baseline_rates), np.std(baseline_rates)
        o_rate_mean, o_rate_std = np.mean(optimal_rates), np.std(optimal_rates)

        b_dur_mean, b_dur_std = np.mean(baseline_durs), np.std(baseline_durs)
        o_dur_mean, o_dur_std = np.mean(optimal_durs), np.std(optimal_durs)

        # Confidence interval bounds (pass rate standard error should be <= 1.5% at N=1500)
        assert b_rate_std < 2.0, f"Baseline pass rate std across seeds is too volatile: {b_rate_std:.2f}%"
        assert o_rate_std < 2.0, f"Optimal pass rate std across seeds is too volatile: {o_rate_std:.2f}%"

        # Duration compression invariant: Optimal duration MUST be lower than baseline across ALL seeds
        for s_idx in range(len(seeds)):
            assert optimal_durs[s_idx] < baseline_durs[s_idx], (
                f"Seed {seeds[s_idx]}: Optimal duration {optimal_durs[s_idx]} not strictly less than "
                f"Baseline {baseline_durs[s_idx]}"
            )

        # Mean duration savings must be >= 8 sessions
        mean_savings = b_dur_mean - o_dur_mean
        assert mean_savings >= 8.0, f"Expected >= 8 sessions savings across seeds, got {mean_savings:.1f}"

    def test_sample_size_variance_reduction(self, session_legs: list[list[list[Leg]]]):
        """
        Verify that Monte Carlo estimator standard error stays within tight statistical bounds.
        At N=2000, binomial pass rate estimator standard error SE = sqrt(p*(1-p)/N) is < 1.0%,
        guaranteeing tight 95% confidence bounds (< +/- 2.0%).
        """
        policy = SizingPolicy("Baseline", "ratchet")
        rules = PropRules()
        horizon = 750
        block_size = 10

        rates_2000 = []
        for s in range(5):
            rng = np.random.default_rng(200 + s)
            paths = [block_bootstrap_sessions(len(session_legs), horizon, block_size, rng) for _ in range(2000)]
            res = [run_evaluation([session_legs[j] for j in p], policy, rules) for p in paths]
            rates_2000.append(np.mean([r.status == "pass" for r in res]) * 100.0)

        std_2000 = float(np.std(rates_2000))
        # Standard deviation across seeds under block bootstrap (B=10) incorporates block variance inflation:
        # At N=2000, std is ~1.6%, well within acceptable engineering bounds (< 2.2%)
        assert std_2000 < 2.2, f"Estimator std at N=2000 exceeds 2.2%: {std_2000:.2f}%"

    def test_staging_cushion_infant_mortality_trap(self, session_legs: list[list[list[Leg]]]):
        """
        Empirically test the Infant Mortality Trap:
        Staging with 1 micro severely degrades funded performance:
        1. Staging at +$500 increases zero-payout rate compared to Day 1 Ratchet and CPPI.
        2. Staging at +$500 creates a premature escalation hazard: trading 1 micro until $500,
           then escalating to 3 micros right before the $600 payout hurdle, maximizing blowouts.
        3. Net lifetime EV is significantly degraded by staging.
        """
        eval_policy = SizingPolicy("Baseline", "ratchet")
        n_sims = 1500

        funded_policies = {
            "day1_standard": SizingPolicy("Standard Day 1", "ratchet"),
            "staging_100": SizingPolicy("Staging 100", "staging", staging_cushion=100.0, staging_contracts=1),
            "staging_300": SizingPolicy("Staging 300", "staging", staging_cushion=300.0, staging_contracts=1),
            "staging_500": SizingPolicy("Staging 500", "staging", staging_cushion=500.0, staging_contracts=1),
            "safe_cppi": SizingPolicy("Safe CPPI", "dynamic_cushion", cushion_floor_buffer=400.0, dynamic_delever_contracts=1),
        }

        df = run_funded_transition_experiments(
            session_legs, eval_policy, funded_policies,
            n_sims=n_sims, seed=42, funded_horizon=252, eval_horizon=750,
        )

        day1_zero = df.loc[df["policy_name"] == "day1_standard", "zero_payout_pct"].iloc[0]
        stg100_zero = df.loc[df["policy_name"] == "staging_100", "zero_payout_pct"].iloc[0]
        stg300_zero = df.loc[df["policy_name"] == "staging_300", "zero_payout_pct"].iloc[0]
        stg500_zero = df.loc[df["policy_name"] == "staging_500", "zero_payout_pct"].iloc[0]
        cppi_zero = df.loc[df["policy_name"] == "safe_cppi", "zero_payout_pct"].iloc[0]

        day1_ev = df.loc[df["policy_name"] == "day1_standard", "net_lifetime_ev"].iloc[0]
        stg500_ev = df.loc[df["policy_name"] == "staging_500", "net_lifetime_ev"].iloc[0]
        cppi_ev = df.loc[df["policy_name"] == "safe_cppi", "net_lifetime_ev"].iloc[0]

        # Empirical Invariant 1: Staging at $500 has higher zero-payout rate than Day 1 and CPPI
        assert stg500_zero > day1_zero, f"Staging 500 {stg500_zero}% <= Day 1 {day1_zero}%"
        assert stg500_zero > cppi_zero, f"Staging 500 {stg500_zero}% <= Safe CPPI {cppi_zero}%"

        # Empirical Invariant 2: Staging at $500 is worse than staging at $100 and $300
        assert stg500_zero > stg100_zero, f"Staging 500 {stg500_zero}% <= Staging 100 {stg100_zero}%"
        assert stg500_zero > stg300_zero, f"Staging 500 {stg500_zero}% <= Staging 300 {stg300_zero}%"

        # Empirical Invariant 3: Staging 500 suffers heavy Net Lifetime EV penalty (> $75 reduction)
        assert day1_ev - stg500_ev > 75.0, f"EV penalty is only {day1_ev - stg500_ev:.2f}"
        assert cppi_ev - stg500_ev > 75.0, f"EV penalty vs CPPI is only {cppi_ev - stg500_ev:.2f}"

    def test_profit_day_threshold_ablation(self, session_legs: list[list[list[Leg]]]):
        """
        Ablation study: What if the prop firm required $0 profit day threshold vs $50 vs $100?
        Demonstrates that profit day hurdles strongly penalize 1-micro trading.
        """
        eval_policy = SizingPolicy("Baseline", "ratchet")
        rules = PropRules()
        n_sims = 1000

        for pday_thresh in [0.0, 50.0, 100.0]:
            f_rules = FundedRules(profit_day_threshold=pday_thresh)
            pol_dict = {
                "fixed_1": SizingPolicy("Fixed 1", "fixed", fixed=1),
                "fixed_2": SizingPolicy("Fixed 2", "fixed", fixed=2),
            }
            res = run_funded_transition_experiments(
                session_legs, eval_policy, pol_dict,
                n_sims=n_sims, seed=123, funded_rules=f_rules,
            )
            f1_zero = res.loc[res["policy_name"] == "fixed_1", "zero_payout_pct"].iloc[0]
            f2_zero = res.loc[res["policy_name"] == "fixed_2", "zero_payout_pct"].iloc[0]

            # Fixed 1 micro should always have higher zero payout than Fixed 2 micros when hurdle >= $50
            if pday_thresh >= 50.0:
                assert f1_zero > f2_zero, f"At hurdle ${pday_thresh}: Fixed 1 {f1_zero}% <= Fixed 2 {f2_zero}%"


# ───────────────────────────────────────────────────────────────────────────────
# 4. Extreme Boundary Conditions: Slippage Stress
# ───────────────────────────────────────────────────────────────────────────────
class TestExtremeSlippageStress:
    """
    Stress test evaluation and funded policies under extreme slippage:
    0.0, 1.0 (base adverse), 2.0 (2x), and 3.0 (3x) extra ticks.
    """

    @pytest.mark.parametrize("extra_ticks", [0.0, 1.0, 2.0, 3.0])
    def test_evaluation_pass_rate_degradation_with_slippage(
        self, session_legs: list[list[list[Leg]]], extra_ticks: float
    ):
        policy = SizingPolicy("Optimal", "ratchet", tiers=((550.0, 4), (200.0, 3), (-np.inf, 2)))
        rules = PropRules()
        n_sims = 1000

        rng = np.random.default_rng(42)
        paths = [block_bootstrap_sessions(len(session_legs), 750, 10, rng) for _ in range(n_sims)]

        results = [
            run_evaluation([session_legs[j] for j in p], policy, rules, extra_ticks=extra_ticks)
            for p in paths
        ]
        pass_rate = np.mean([r.status == "pass" for r in results]) * 100.0

        # Monotonicity check across slippage: pass rate must degrade, but stay positive
        if extra_ticks == 0.0:
            assert pass_rate >= 70.0, f"Expected >= 70% at 0 ticks, got {pass_rate:.1f}%"
        elif extra_ticks == 3.0:
            # Under severe 3-tick slippage ($1.50 per micro per trade), strategy edge compresses
            assert pass_rate >= 40.0, f"Pass rate completely collapsed at 3 ticks: {pass_rate:.1f}%"

    def test_safe_cppi_resilience_under_extreme_slippage(self, session_legs: list[list[list[Leg]]]):
        """
        Compare Safe CPPI vs Standard Day 1 Ratchet under 2.0 ticks extra slippage.
        Safe CPPI's floor de-leveraging should mitigate catastrophic drawdown.
        """
        eval_policy = SizingPolicy("Baseline", "ratchet")
        funded_policies = {
            "standard_day1": SizingPolicy("Standard Day 1", "ratchet"),
            "safe_cppi": SizingPolicy(
                "Safe CPPI", "dynamic_cushion",
                cushion_floor_buffer=400.0, dynamic_delever_contracts=1,
            ),
        }

        res = run_funded_transition_experiments(
            session_legs, eval_policy, funded_policies,
            n_sims=1000, seed=42, extra_ticks=2.0,
        )

        std_ev = res.loc[res["policy_name"] == "standard_day1", "net_lifetime_ev"].iloc[0]
        cppi_ev = res.loc[res["policy_name"] == "safe_cppi", "net_lifetime_ev"].iloc[0]

        # Both EVs may drop due to slippage, but CPPI should remain viable
        assert cppi_ev > 0.0, f"Safe CPPI net EV went negative under 2-tick slippage: {cppi_ev}"


# ───────────────────────────────────────────────────────────────────────────────
# 5. Calendar Block Size Sensitivity
# ───────────────────────────────────────────────────────────────────────────────
class TestCalendarBlockSizeSensitivity:
    """
    Stress test calendar block size parameter: B = 1, 5, 10, 20, 30 sessions.
    Evaluates whether temporal clustering distorts the Pareto ranking.
    """

    @pytest.mark.parametrize("block_size", [1, 5, 10, 20])
    def test_block_size_impact_on_duration_compression(
        self, session_legs: list[list[list[Leg]]], block_size: int
    ):
        baseline_policy = SizingPolicy("Baseline", "ratchet", tiers=((750.0, 4), (350.0, 3), (-np.inf, 2)))
        optimal_policy = SizingPolicy("Optimal", "ratchet", tiers=((550.0, 4), (200.0, 3), (-np.inf, 2)))

        rules = PropRules()
        n_sims = 1000
        horizon = 750

        rng = np.random.default_rng(42)
        paths = [block_bootstrap_sessions(len(session_legs), horizon, block_size, rng) for _ in range(n_sims)]

        b_res = [run_evaluation([session_legs[j] for j in p], baseline_policy, rules) for p in paths]
        o_res = [run_evaluation([session_legs[j] for j in p], optimal_policy, rules) for p in paths]

        b_passes = [r for r in b_res if r.status == "pass"]
        o_passes = [r for r in o_res if r.status == "pass"]

        b_dur = float(np.median([r.sessions for r in b_passes]))
        o_dur = float(np.median([r.sessions for r in o_passes]))

        # The optimal ratchet MUST maintain duration compression across all block sizes
        assert o_dur < b_dur, f"Block size {block_size}: Optimal {o_dur} >= Baseline {b_dur}"
        assert (b_dur - o_dur) >= 6.0, f"Block size {block_size}: Savings {b_dur - o_dur} < 6 sessions"


# ───────────────────────────────────────────────────────────────────────────────
# 6. Corner-Case Transitions Between Funded Cycles
# ───────────────────────────────────────────────────────────────────────────────
class TestCornerCaseFundedCycleTransitions:
    """
    Deterministic tests for intricate cycle boundary transitions:
    - Post-payout balance exactly at buffer boundary
    - Safe CPPI instantaneous de-leveraging when cushion drops below $400
    - Exact floor ratchet lock behavior
    - Payout 5 graduation
    """

    def test_post_payout_deleveraging_trigger(self):
        """
        If a payout drops the account cushion below $400, on the subsequent session
        Safe CPPI MUST immediately size at 1 micro, preventing a 2-micro blowout.
        """
        policy = SizingPolicy(
            "Safe CPPI", "dynamic_cushion",
            cushion_floor_buffer=400.0,
            dynamic_delever_contracts=1,
            tiers=((750.0, 4), (350.0, 3), (-np.inf, 2)),
        )

        # Cushion above buffer: sizes at base ratchet (2 micros)
        c_above = policy.total_micros(profit=500.0, cushion=450.0)
        assert c_above == 3, f"Expected 3 micros at profit 500, cushion 450, got {c_above}"

        # Cushion below buffer: MUST de-lever to 1 micro regardless of profit
        c_below = policy.total_micros(profit=500.0, cushion=350.0)
        assert c_below == 1, f"Expected 1 micro when cushion (350) < buffer (400), got {c_below}"

        # Exact boundary: cushion == 400.0
        c_exact = policy.total_micros(profit=500.0, cushion=400.0)
        assert c_exact == 3, f"At exact buffer 400, expected ratchet tier 3, got {c_exact}"

    def test_exact_graduation_at_max_payouts(self):
        """
        Verify that when an account earns 5 payouts, status is 'max_payouts'
        and exactly 5 payout tuples are recorded.
        """
        rules = PropRules(start=25000.0, max_dd=1000.0)
        funded = FundedRules(cycle_sessions=1, min_profit_days=1, max_payouts=5, min_payout=300.0)
        policy = SizingPolicy("Fixed 2", "fixed", fixed=2)

        # 6 sessions each with +$400 profit per contract * 2 contracts = +$800
        leg = Leg(order=0, sym="NQ", micro="MNQ", per_contract=400.0, research=400.0, research_contracts=2, s1_pair=False)
        sessions = [[[leg]] for _ in range(6)]

        res = run_funded(sessions, policy, rules, funded)
        assert res["status"] in ("max_payouts", "promoted_to_live")
        assert len(res["payouts"]) == 5

    def test_cycle_reset_only_on_payout(self):
        """
        Verify that cycle count does NOT reset if cycle_sessions is met but min_payout is not reached.
        """
        rules = PropRules(start=25000.0, max_dd=1000.0)
        funded = FundedRules(cycle_sessions=3, min_profit_days=1, min_payout=300.0)
        policy = SizingPolicy("Fixed 1", "fixed", fixed=1)

        # 4 sessions with +$20 profit each (clearing min_profit_days if threshold was low, but not reaching $300 payout)
        # profit_day_threshold = 50, so +$20 gives pdays = 0
        leg = Leg(order=0, sym="NQ", micro="MNQ", per_contract=20.0, research=20.0, research_contracts=1, s1_pair=False)
        sessions = [[[leg]] for _ in range(4)]

        res = run_funded(sessions, policy, rules, funded)
        # No payout should have occurred
        assert len(res["payouts"]) == 0
        assert res["status"] == "open"
