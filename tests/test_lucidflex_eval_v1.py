"""Causal LucidFlex 25K evaluator invariants (lucidflex_eval_v1)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from backtest.lucidflex_eval import (
    EQUITY_MODEL,
    LucidFlexEvalConfig,
    build_session_index,
    compile_trades,
    contracts_for_leg,
    expected_otp_cost_from_failed_attempts,
    meets_consistency,
    meets_evaluation_pass,
    s1_split_contracts,
    simulate_evaluation,
)
from config.prop_firm_registry import LUCID_FLEX_25K

REPO = Path(__file__).resolve().parents[1]
LEGACY_M3 = REPO / "results" / "m3_portfolio_ratchet_simulation.json"
LEGACY_M3_SHA256 = "11410935d0b14f0d422c82fb4a753e7cdd79788eb960f15d02681bcb38267de2"


def _trades(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["date"] = df["entry_time"].dt.strftime("%Y-%m-%d")
    return df


def _run(df: pd.DataFrame, calendar: list[str] | None = None, cfg: LucidFlexEvalConfig | None = None):
    compiled = compile_trades(df)
    cal = calendar or sorted(df["date"].unique())
    sessions, events = build_session_index(compiled, cal)
    return simulate_evaluation(compiled, events, cfg or LucidFlexEvalConfig()), compiled, events


class TestS1Split:
    def test_tier_allocations(self):
        assert s1_split_contracts(2) == (1, 1)
        assert s1_split_contracts(3) == (1, 2)
        assert s1_split_contracts(4) == (2, 2)
        assert contracts_for_leg(2, "MNQ", True) + contracts_for_leg(2, "MES", True) == 2
        assert contracts_for_leg(3, "MNQ", True) + contracts_for_leg(3, "MES", True) == 3
        assert contracts_for_leg(4, "MNQ", True) + contracts_for_leg(4, "MES", True) == 4

    def test_not_double_tier(self):
        for t in (2, 3, 4):
            assert contracts_for_leg(t, "MNQ", True) != t or t == 1


class TestLookahead:
    def test_later_entry_ignores_unclosed_pnl(self):
        cfg = LucidFlexEvalConfig(
            enable_safe_cppi=False, enable_finish_line_shield=False, ratchet_t2=200.0, ratchet_t3=550.0
        )
        # If terminal +$400 were credited at 10:00, the 10:30 entry would ratchet to 3 micros.
        df = _trades([
            dict(entry_time="2021-01-04 10:00:00", exit_time="2021-01-04 11:00:00",
                 strat="S3", micro="MGC", per_contract_pnl=400.0, s1_pair=False),
            dict(entry_time="2021-01-04 10:30:00", exit_time="2021-01-04 10:45:00",
                 strat="S5", micro="MCL", per_contract_pnl=1.0, s1_pair=False),
        ])
        res, _, _ = _run(df, ["2021-01-04"], cfg)
        # Causal: both sized at 2 micros. Lookahead would yield 2*400 + 3*1 = 803.
        assert res.final_balance == pytest.approx(25802.0)


class TestSimultaneousS1:
    def test_same_pre_entry_state_and_split_not_double(self):
        cfg = LucidFlexEvalConfig(enable_safe_cppi=False, enable_finish_line_shield=False)
        df = _trades([
            dict(entry_time="2021-01-04 09:45:00", exit_time="2021-01-04 10:15:00",
                 strat="S1", micro="MNQ", per_contract_pnl=10.0, s1_pair=True),
            dict(entry_time="2021-01-04 09:45:00", exit_time="2021-01-04 10:15:00",
                 strat="S1", micro="MES", per_contract_pnl=20.0, s1_pair=True),
        ])
        res, _, _ = _run(df, ["2021-01-04"], cfg)
        # 1 MNQ * 10 + 1 MES * 20 = 30, not 2*(10+20)=60
        assert res.final_balance == pytest.approx(25030.0)
        assert res.max_concurrent_micros == 2
        assert res.trades_taken == 2


class TestS3S5Overlap:
    def test_open_s3_does_not_size_s5(self):
        cfg = LucidFlexEvalConfig(enable_safe_cppi=False, enable_finish_line_shield=False)
        df = _trades([
            dict(entry_time="2021-11-30 10:15:00", exit_time="2021-11-30 11:00:00",
                 strat="S3", micro="MGC", per_contract_pnl=-183.5, s1_pair=False),
            dict(entry_time="2021-11-30 10:57:00", exit_time="2021-11-30 11:54:00",
                 strat="S5", micro="MCL", per_contract_pnl=85.5, s1_pair=False),
        ])
        res, _, _ = _run(df, ["2021-11-30"], cfg)
        # Both sized at 2 micros from profit 0: 2*(-183.5)+2*85.5 = -196
        assert res.final_balance == pytest.approx(25000.0 - 196.0)
        assert res.max_concurrent_micros == 4


class TestDailyLossLimit:
    def test_no_clip_and_blocks_later_entries(self):
        cfg = LucidFlexEvalConfig(enable_safe_cppi=False, enable_finish_line_shield=False)
        df = _trades([
            dict(entry_time="2021-01-04 09:00:00", exit_time="2021-01-04 09:10:00",
                 strat="S2", micro="MNQ", per_contract_pnl=-400.0, s1_pair=False),
            dict(entry_time="2021-01-04 09:20:00", exit_time="2021-01-04 09:30:00",
                 strat="S1", micro="MNQ", per_contract_pnl=500.0, s1_pair=False),
        ])
        res, _, _ = _run(df, ["2021-01-04"], cfg)
        # Full -800 retained; second entry blocked
        assert res.final_balance == pytest.approx(24200.0)
        assert res.entries_blocked_dll == 1
        assert res.trades_taken == 1

    def test_open_trade_still_settles_after_dll(self):
        cfg = LucidFlexEvalConfig(enable_safe_cppi=False, enable_finish_line_shield=False)
        df = _trades([
            dict(entry_time="2021-01-04 08:50:00", exit_time="2021-01-04 10:00:00",
                 strat="S2", micro="MNQ", per_contract_pnl=50.0, s1_pair=False),
            dict(entry_time="2021-01-04 09:00:00", exit_time="2021-01-04 09:05:00",
                 strat="S5", micro="MCL", per_contract_pnl=-400.0, s1_pair=False),
        ])
        res, _, _ = _run(df, ["2021-01-04"], cfg)
        # S2 still open when S5 realizes -800 and trips DLL; S2 later +100
        assert res.final_balance == pytest.approx(25000.0 - 800.0 + 100.0)
        assert res.trades_taken == 2


class TestFloorAndConsistency:
    def test_eod_floor_updates_only_at_session_close(self):
        cfg = LucidFlexEvalConfig(enable_safe_cppi=False, enable_finish_line_shield=False)
        df = _trades([
            dict(entry_time="2021-01-04 10:00:00", exit_time="2021-01-04 10:10:00",
                 strat="S2", micro="MNQ", per_contract_pnl=600.0, s1_pair=False),
        ])
        res, compiled, events = _run(df, ["2021-01-04", "2021-01-05"], cfg)
        # Day1: +1200 -> EOD 26200, floor locks at 25100 because peak 26200 >= 26100
        df2 = _trades([
            dict(entry_time="2021-01-04 10:00:00", exit_time="2021-01-04 10:10:00",
                 strat="S2", micro="MNQ", per_contract_pnl=600.0, s1_pair=False),
            dict(entry_time="2021-01-05 10:00:00", exit_time="2021-01-05 10:10:00",
                 strat="S2", micro="MNQ", per_contract_pnl=-600.0, s1_pair=False),
        ])
        res, _, _ = _run(df2, ["2021-01-04", "2021-01-05"], cfg)
        # After day1 26200 locked floor 25100; day2 -1200 -> 25000, still above 25100? 25000 <= 25100 fail
        assert res.status == "fail"
        assert res.sessions == 2

    def test_consistency_40_boundaries(self):
        assert meets_consistency(1250.0, 500.0, 0.40) is True
        assert meets_consistency(1250.0, 500.01, 0.40) is False
        assert meets_evaluation_pass(1250.0, 1250.0, 500.0, 0.40) is True
        assert meets_evaluation_pass(1250.0, 1250.0, 600.0, 0.40) is False
        assert meets_evaluation_pass(1500.0, 1250.0, 600.0, 0.40) is True

    def test_consistency_50_independent(self):
        assert meets_evaluation_pass(1400.0, 1250.0, 700.0, 0.50) is True
        assert meets_evaluation_pass(1400.0, 1250.0, 700.0, 0.40) is False
        cfg40 = LucidFlexEvalConfig(
            consistency_pct=0.40, enable_safe_cppi=False, enable_finish_line_shield=False,
            ratchet_t2=10_000.0, ratchet_t3=20_000.0,
        )
        cfg50 = LucidFlexEvalConfig(
            consistency_pct=0.50, enable_safe_cppi=False, enable_finish_line_shield=False,
            ratchet_t2=10_000.0, ratchet_t3=20_000.0,
        )
        rows = []
        for d, pnl in (("2021-01-04", 350.0), ("2021-01-05", 350.0)):
            rows.append(dict(
                entry_time=f"{d} 10:00:00", exit_time=f"{d} 10:10:00",
                strat="S2", micro="MNQ", per_contract_pnl=pnl, s1_pair=False,
            ))
        df = _trades(rows)
        cal = ["2021-01-04", "2021-01-05"]
        r40, _, _ = _run(df, cal, cfg40)
        r50, _, _ = _run(df, cal, cfg50)
        # Two days * 2 micros * $350 = $1400. Largest day $700. 700/1400 = 50%.
        assert r50.status == "pass"
        assert r40.status != "pass"


class TestHorizonAndFees:
    def test_unresolved_not_failed(self):
        cfg = LucidFlexEvalConfig(enable_safe_cppi=False, enable_finish_line_shield=False)
        df = _trades([
            dict(entry_time="2021-01-04 10:00:00", exit_time="2021-01-04 10:10:00",
                 strat="S2", micro="MNQ", per_contract_pnl=1.0, s1_pair=False),
        ])
        compiled = compile_trades(df)
        _, events = build_session_index(compiled, ["2021-01-04", "2021-01-05"])
        res = simulate_evaluation(compiled, events, cfg, max_sessions=2)
        assert res.status == "unresolved"
        assert res.fail_reason == "horizon_censored"

    def test_otp_excludes_unresolved(self):
        assert expected_otp_cost_from_failed_attempts(7279, 1983, 39.0) == pytest.approx(39.0 * (7279 + 1983) / 7279)
        # Unresolved must not enter the formula
        with_unresolved_wrong = 39.0 / 0.7279
        correct = expected_otp_cost_from_failed_attempts(7279, 1983, 39.0)
        assert correct != pytest.approx(with_unresolved_wrong, rel=1e-4)


class TestCapsAndRegistry:
    def test_official_and_internal_caps_are_distinct(self):
        assert LUCID_FLEX_25K.OFFICIAL_FIRM_MAX_MICROS == 20
        assert LUCID_FLEX_25K.OFFICIAL_FIRM_MAX_MINIS == 2
        assert LUCID_FLEX_25K.INTERNAL_RISK_CAP_MICROS == 10
        assert LUCID_FLEX_25K.MAX_MICRO_CONTRACTS == LUCID_FLEX_25K.INTERNAL_RISK_CAP_MICROS
        cfg = LucidFlexEvalConfig()
        assert cfg.official_firm_max_micros != cfg.internal_risk_cap_micros
        assert cfg.official_firm_max_micros == 20
        assert cfg.internal_risk_cap_micros == 10

    def test_internal_cap_blocks_beyond_10(self):
        cfg = LucidFlexEvalConfig(
            enable_safe_cppi=False, enable_finish_line_shield=False,
            internal_risk_cap_micros=2, official_firm_max_micros=20,
        )
        df = _trades([
            dict(entry_time="2021-01-04 10:15:00", exit_time="2021-01-04 11:00:00",
                 strat="S3", micro="MGC", per_contract_pnl=1.0, s1_pair=False),
            dict(entry_time="2021-01-04 10:16:00", exit_time="2021-01-04 11:00:00",
                 strat="S5", micro="MCL", per_contract_pnl=1.0, s1_pair=False),
        ])
        res, _, _ = _run(df, ["2021-01-04"], cfg)
        assert res.trades_taken == 1
        assert res.entries_blocked_cap == 1
        assert res.max_concurrent_micros == 2

    def test_equity_model_is_realized_close(self):
        assert EQUITY_MODEL == "realized_close_only"


class TestLegacyArtifact:
    def test_m3_json_unchanged(self):
        assert LEGACY_M3.is_file()
        digest = hashlib.sha256(LEGACY_M3.read_bytes()).hexdigest()
        assert digest == LEGACY_M3_SHA256
