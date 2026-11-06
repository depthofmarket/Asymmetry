"""
Test Suite: Strategy Registry, Lifecycle Tiers & Quantitative Governance.

Verifies:
1. StrategyTier enum definitions and string compatibility.
2. Canonical production baseline strategy registration.
3. Utility functions: get_strategy_tier, is_production_baseline, validate_strategy_id, list_strategies_by_tier.
4. Dynamic candidate registration and protection invariants preventing baseline contamination.
5. Deep ProvenanceStore integration: tier resolution, SQLite schema persistence, backwards compatibility.
6. Rejection of unauthorized candidate runs masquerading as BASELINE.
7. Agent instruction synchronization across CLAUDE.md, AGENTS.md, and GEMINI.md.
8. CLI query tool displaying strategy tiers.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.provenance import ProvenanceRecord, ProvenanceStore
import config.strategy_registry as sr
from config.strategy_registry import StrategyTier


@pytest.fixture(autouse=True)
def reset_strategy_registry():
    """Ensure every test begins with a clean, unpolluted strategy registry."""
    sr.reset_registry()
    yield
    sr.reset_registry()


@pytest.fixture
def temp_store(tmp_path):
    """Provides an isolated ProvenanceStore for testing."""
    db_file = tmp_path / "test_strategy_registry_provenance.db"
    jsonl_file = tmp_path / "test_strategy_registry_provenance.jsonl"
    return ProvenanceStore(db_path=db_file, jsonl_path=jsonl_file)


# ==============================================================================
# 1. StrategyTier Enum Tests
# ==============================================================================

class TestStrategyTierEnum:
    def test_tier_members_and_values(self):
        assert StrategyTier.BASELINE.value == "BASELINE"
        assert StrategyTier.FORWARD_DEMO.value == "FORWARD_DEMO"
        assert StrategyTier.CANDIDATE.value == "CANDIDATE"
        assert StrategyTier.REJECTED.value == "REJECTED"

    def test_tier_is_str_compatible(self):
        assert isinstance(StrategyTier.BASELINE, str)
        assert StrategyTier.BASELINE == "BASELINE"
        assert StrategyTier.FORWARD_DEMO == "FORWARD_DEMO"

    def test_from_str_case_insensitivity(self):
        assert StrategyTier.from_str("baseline") == StrategyTier.BASELINE
        assert StrategyTier.from_str("BASELINE") == StrategyTier.BASELINE
        assert StrategyTier.from_str("forward_demo") == StrategyTier.FORWARD_DEMO
        assert StrategyTier.from_str("Candidate") == StrategyTier.CANDIDATE
        assert StrategyTier.from_str("rejected") == StrategyTier.REJECTED
        assert StrategyTier.from_str(StrategyTier.BASELINE) == StrategyTier.BASELINE

    def test_from_str_invalid_raises_value_error(self):
        with pytest.raises(ValueError, match="Unknown StrategyTier"):
            StrategyTier.from_str("UNKNOWN_TIER")


# ==============================================================================
# 2. Production Baseline Registrations
# ==============================================================================

class TestBaselineRegistrations:
    def test_all_production_baselines_registered(self):
        expected_baselines = [
            "morning_va_breakout_s1",
            "macro_momentum_s2",
            "gold_london_fix_s3",
            "lucid_flex_ensemble",
        ]
        for strat_id in expected_baselines:
            tier = sr.get_strategy_tier(strat_id)
            assert tier == StrategyTier.BASELINE, f"Expected {strat_id} to have tier BASELINE, got {tier}"
            assert sr.is_production_baseline(strat_id) is True
            assert sr.validate_strategy_id(strat_id) is True

    def test_forward_demo_registered(self):
        tier = sr.get_strategy_tier("lucid_flex_forward_demo")
        assert tier == StrategyTier.FORWARD_DEMO
        assert sr.is_production_baseline("lucid_flex_forward_demo") is False
        assert sr.validate_strategy_id("lucid_flex_forward_demo") is True

    def test_list_strategies_by_tier(self):
        baselines = sr.list_strategies_by_tier(StrategyTier.BASELINE)
        assert "morning_va_breakout_s1" in baselines
        assert "macro_momentum_s2" in baselines
        assert "gold_london_fix_s3" in baselines
        assert "lucid_flex_ensemble" in baselines
        assert "lucid_flex_forward_demo" not in baselines

        # String tier argument support
        baselines_str = sr.list_strategies_by_tier("BASELINE")
        assert baselines_str == baselines

        demos = sr.list_strategies_by_tier(StrategyTier.FORWARD_DEMO)
        assert demos == ["lucid_flex_forward_demo"]

    def test_get_authorized_baseline_ids(self):
        ids = sr.get_authorized_baseline_ids()
        assert len(ids) == 5
        assert "morning_va_breakout_s1" in ids
        assert "lucid_flex_ensemble" in ids


# ==============================================================================
# 3. Strategy ID Validation & Format Checks
# ==============================================================================

class TestStrategyIdValidation:
    def test_validate_strategy_id_registered_vs_unregistered(self):
        # Known registered strategies pass
        assert sr.validate_strategy_id("morning_va_breakout_s1") is True
        assert sr.validate_strategy_id("lucid_flex_forward_demo") is True

        # Unregistered strategy fails strict validation by default
        assert sr.validate_strategy_id("unregistered_random_strat") is False

        # When allow_valid_syntax=True, valid syntax unregistered passes
        assert sr.validate_strategy_id("unregistered_random_strat", allow_valid_syntax=True) is True

    def test_validate_strategy_id_invalid_formats(self):
        invalid_ids = [
            "",
            "   ",
            None,
            12345,
            "has space",
            "has;semicolon",
            "has|pipe",
            "has/slash",
            "rm -rf /",
            "bad$token",
            "-leading-dash",
        ]
        for inv in invalid_ids:
            assert sr.validate_strategy_id(inv) is False
            assert sr.validate_strategy_id(inv, allow_valid_syntax=True) is False
            assert sr.is_valid_strategy_id_format(inv) is False

    def test_is_registered(self):
        assert sr.is_registered("morning_va_breakout_s1") is True
        assert sr.is_registered("non_existent_strat") is False
        assert sr.is_registered("") is False


# ==============================================================================
# 4. Candidate Registration & Protection Invariants
# ==============================================================================

class TestCandidateRegistrationAndProtection:
    def test_register_candidate(self):
        meta = sr.register_candidate(
            strategy_id="edge_vp_mr_failed_auction",
            name="Edge VP Failed Auction Mean Reversion",
            instrument="NQ",
            description="Exploratory test candidate for failed auction reclaim",
        )
        assert meta.strategy_id == "edge_vp_mr_failed_auction"
        assert meta.tier == StrategyTier.CANDIDATE
        assert sr.get_strategy_tier("edge_vp_mr_failed_auction") == StrategyTier.CANDIDATE
        assert sr.is_production_baseline("edge_vp_mr_failed_auction") is False
        assert sr.validate_strategy_id("edge_vp_mr_failed_auction") is True

        # Candidate is listed under CANDIDATE tier
        candidates = sr.list_strategies_by_tier(StrategyTier.CANDIDATE)
        assert "edge_vp_mr_failed_auction" in candidates

    def test_cannot_register_unauthorized_strategy_as_baseline(self):
        """Protection: Non-baseline strategies cannot claim BASELINE tier without explicit override."""
        with pytest.raises(ValueError, match="cannot be registered with tier BASELINE"):
            sr.register_strategy(
                strategy_id="unvetted_exploratory_strat",
                tier=StrategyTier.BASELINE,
            )

    def test_cannot_override_frozen_baseline_tier(self):
        """Protection: Frozen production baselines cannot have their tier modified."""
        with pytest.raises(ValueError, match="Cannot override frozen production baseline"):
            sr.register_strategy(
                strategy_id="morning_va_breakout_s1",
                tier=StrategyTier.REJECTED,
            )

    def test_register_rejected_strategy(self):
        meta = sr.register_strategy(
            strategy_id="failed_high_vol_widening",
            tier=StrategyTier.REJECTED,
            description="Failed idea #3 from wiki/failed_ideas.md",
        )
        assert meta.tier == StrategyTier.REJECTED
        assert sr.get_strategy_tier("failed_high_vol_widening") == StrategyTier.REJECTED
        assert sr.list_strategies_by_tier(StrategyTier.REJECTED) == ["failed_high_vol_widening"]


# ==============================================================================
# 5. Provenance Store Integration & Tier Segregation
# ==============================================================================

class TestProvenanceIntegration:
    def test_record_baseline_strategy_assigns_baseline_tier(self, temp_store, tmp_path):
        data_file = tmp_path / "trades.parquet"
        data_file.write_bytes(b"DATA")

        record = temp_store.record_run(
            strategy_id="morning_va_breakout_s1",
            strategy_name="Morning VA Breakout",
            methodology="walkforward",
            date_start="2021-01-01",
            date_end="2026-10-30",
            data_path=data_file,
            total_trades=100,
            win_rate=55.0,
            profit_factor=1.60,
            gross_profit=10000.0,
            net_profit=8000.0,
            max_drawdown=1000.0,
            sharpe_ratio=1.2,
            largest_win=500.0,
        )
        assert record.strategy_tier == "BASELINE"

        # Check SQLite row
        fetched = temp_store.get_run(record.run_id)
        assert fetched is not None
        assert fetched.strategy_tier == "BASELINE"

    def test_record_forward_demo_assigns_forward_demo_tier(self, temp_store, tmp_path):
        data_file = tmp_path / "demo.parquet"
        data_file.write_bytes(b"DEMO_DATA")

        record = temp_store.record_run(
            strategy_id="lucid_flex_forward_demo",
            strategy_name="Live Forward Demo Parity",
            methodology="forward_demo",
            date_start="2026-10-30",
            date_end="2026-11-06",
            data_path=data_file,
            total_trades=5,
            win_rate=80.0,
            profit_factor=2.5,
            gross_profit=500.0,
            net_profit=400.0,
            max_drawdown=100.0,
            sharpe_ratio=1.5,
            largest_win=150.0,
        )
        assert record.strategy_tier == "FORWARD_DEMO"

    def test_record_unregistered_strategy_defaults_to_candidate_tier(self, temp_store, tmp_path):
        data_file = tmp_path / "cand.parquet"
        data_file.write_bytes(b"CAND_DATA")

        record = temp_store.record_run(
            strategy_id="new_experimental_candidate_s4",
            strategy_name="Experimental S4",
            methodology="in_sample",
            date_start="2026-01-01",
            date_end="2026-06-30",
            data_path=data_file,
            total_trades=50,
            win_rate=52.0,
            profit_factor=1.35,
            gross_profit=4000.0,
            net_profit=2500.0,
            max_drawdown=600.0,
            sharpe_ratio=0.8,
            largest_win=200.0,
        )
        # Unregistered strategy must default to CANDIDATE tier
        assert record.strategy_tier == "CANDIDATE"

        fetched = temp_store.get_run(record.run_id)
        assert fetched is not None
        assert fetched.strategy_tier == "CANDIDATE"

    def test_unauthorized_strategy_cannot_claim_baseline_tier(self, temp_store, tmp_path):
        """Protection: Unvetted strategies are blocked from passing strategy_tier='BASELINE'."""
        data_file = tmp_path / "data.parquet"
        data_file.write_bytes(b"DATA")

        with pytest.raises(ValueError, match="not an authorized production baseline"):
            temp_store.record_run(
                strategy_id="malicious_unvetted_bot",
                strategy_name="Rogue Bot",
                strategy_tier=StrategyTier.BASELINE,
                methodology="in_sample",
                date_start="2026-01-01",
                date_end="2026-06-30",
                data_path=data_file,
                total_trades=50,
                win_rate=90.0,
                profit_factor=5.0,
                gross_profit=10000.0,
                net_profit=10000.0,
                max_drawdown=100.0,
                sharpe_ratio=3.0,
                largest_win=500.0,
            )

    def test_invalid_strategy_id_rejected_at_recording(self, temp_store, tmp_path):
        data_file = tmp_path / "data.parquet"
        data_file.write_bytes(b"DATA")

        for bad_id in ["", "   ", "rm -rf /", "bad name with space"]:
            with pytest.raises(ValueError, match="Invalid strategy_id"):
                temp_store.record_run(
                    strategy_id=bad_id,
                    strategy_name="Bad Strat",
                    methodology="in_sample",
                    date_start="2026-01-01",
                    date_end="2026-06-30",
                    data_path=data_file,
                    total_trades=10,
                    win_rate=50.0,
                    profit_factor=1.0,
                    gross_profit=100.0,
                    net_profit=50.0,
                    max_drawdown=50.0,
                    sharpe_ratio=0.5,
                    largest_win=20.0,
                )

    def test_list_runs_tier_filter(self, temp_store, tmp_path):
        data_file = tmp_path / "data.parquet"
        data_file.write_bytes(b"DATA")

        # 1. Baseline run
        temp_store.record_run(
            run_id="run_base_1",
            strategy_id="morning_va_breakout_s1",
            strategy_name="S1",
            methodology="walkforward",
            date_start="2021-01-01",
            date_end="2026-10-30",
            data_path=data_file,
            total_trades=100,
            win_rate=55.0,
            profit_factor=1.60,
            gross_profit=10000.0,
            net_profit=8000.0,
            max_drawdown=1000.0,
            sharpe_ratio=1.2,
            largest_win=500.0,
        )
        # 2. Demo run
        temp_store.record_run(
            run_id="run_demo_1",
            strategy_id="lucid_flex_forward_demo",
            strategy_name="Demo",
            methodology="forward_demo",
            date_start="2026-10-30",
            date_end="2026-11-06",
            data_path=data_file,
            total_trades=5,
            win_rate=80.0,
            profit_factor=2.5,
            gross_profit=500.0,
            net_profit=400.0,
            max_drawdown=100.0,
            sharpe_ratio=1.5,
            largest_win=150.0,
        )
        # 3. Candidate run
        temp_store.record_run(
            run_id="run_cand_1",
            strategy_id="candidate_alpha_v1",
            strategy_name="Cand",
            methodology="in_sample",
            date_start="2026-01-01",
            date_end="2026-06-30",
            data_path=data_file,
            total_trades=30,
            win_rate=50.0,
            profit_factor=1.2,
            gross_profit=1000.0,
            net_profit=500.0,
            max_drawdown=300.0,
            sharpe_ratio=0.7,
            largest_win=100.0,
        )

        # By default, candidate runs are quarantined from production list_runs()
        default_runs = temp_store.list_runs()
        assert len(default_runs) == 2  # Baseline and Forward Demo only

        # Explicitly request candidate runs
        all_runs = temp_store.list_runs(include_candidates=True)
        assert len(all_runs) == 3

        baseline_runs = temp_store.list_runs(tier=StrategyTier.BASELINE)
        assert len(baseline_runs) == 1
        assert baseline_runs[0].run_id == "run_base_1"

        demo_runs = temp_store.list_runs(tier="FORWARD_DEMO")
        assert len(demo_runs) == 1
        assert demo_runs[0].run_id == "run_demo_1"

        candidate_runs = temp_store.list_runs(tier=StrategyTier.CANDIDATE)
        assert len(candidate_runs) == 1
        assert candidate_runs[0].run_id == "run_cand_1"

    def test_provenance_footer_contains_strategy_tier(self, temp_store, tmp_path):
        data_file = tmp_path / "data.parquet"
        data_file.write_bytes(b"DATA")

        record = temp_store.record_run(
            strategy_id="macro_momentum_s2",
            strategy_name="Macro Release Momentum",
            methodology="walkforward",
            date_start="2021-01-20",
            date_end="2026-08-19",
            data_path=data_file,
            total_trades=143,
            win_rate=48.95,
            profit_factor=1.44,
            gross_profit=14120.0,
            net_profit=4573.23,
            max_drawdown=1182.0,
            sharpe_ratio=1.04,
            largest_win=630.0,
        )
        footer = temp_store.format_footer(record)
        assert "Strategy Tier: BASELINE" in footer


# ==============================================================================
# 6. Instruction Synchronization Verification
# ==============================================================================

class TestAgentInstructionSynchronization:
    def test_all_agent_instruction_files_contain_authorized_baselines(self):
        instruction_files = ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]
        expected_ids = [
            "morning_va_breakout_s1",
            "macro_momentum_s2",
            "gold_london_fix_s3",
            "lucid_flex_ensemble",
            "lucid_flex_forward_demo",
        ]

        for fname in instruction_files:
            fpath = REPO_ROOT / fname
            assert fpath.exists(), f"Agent instruction file missing: {fname}"
            content = fpath.read_text(encoding="utf-8")

            for strat_id in expected_ids:
                assert strat_id in content, f"{fname} missing baseline strategy ID: '{strat_id}'"

            assert "results/backtest_provenance.db" in content
            assert "scripts/query_provenance.py" in content


# ==============================================================================
# 7. Query Provenance CLI Display
# ==============================================================================

class TestQueryProvenanceCli:
    def test_cli_list_displays_strategy_tier(self):
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts/query_provenance.py"), "--list"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "TIER" in proc.stdout
        assert "BASELINE" in proc.stdout
        assert "FORWARD_DEMO" in proc.stdout
        assert "morning_va_breakout_s1" in proc.stdout
        assert "lucid_flex_forward_demo" in proc.stdout

    def test_cli_list_filter_tier(self):
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts/query_provenance.py"), "--list", "--tier", "FORWARD_DEMO"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "FORWARD_DEMO" in proc.stdout
        assert "lucid_flex_forward_demo" in proc.stdout
        assert "Total verified runs: 1" in proc.stdout
        assert "morning_va_breakout_s1" not in proc.stdout

    def test_cli_list_excludes_candidates_by_default(self):
        """CLI --list must strictly quarantine candidate runs by default."""
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts/query_provenance.py"), "--list"],
            capture_output=True,
            text=True,
            check=True,
        )
        # All lines in table should be BASELINE or FORWARD_DEMO
        for line in proc.stdout.splitlines():
            if "|" in line and "RUN ID" not in line and "===" not in line:
                assert "CANDIDATE" not in line, f"Candidate leaked into default CLI list: {line}"

    def test_candidate_quarantine_banner_displayed_on_candidate_query(self, temp_store, tmp_path, monkeypatch):
        """Querying a candidate run must display prominent quarantine banner."""
        data_file = tmp_path / "cand.parquet"
        data_file.write_bytes(b"DATA")

        temp_store.record_run(
            run_id="run_cand_banner_test",
            strategy_id="cand_test_alpha",
            strategy_name="Candidate Test Alpha",
            methodology="in_sample",
            date_start="2026-01-01",
            date_end="2026-06-30",
            data_path=data_file,
            total_trades=20,
            win_rate=50.0,
            profit_factor=1.1,
            gross_profit=500.0,
            net_profit=200.0,
            max_drawdown=100.0,
            sharpe_ratio=0.5,
            largest_win=50.0,
        )

        import scripts.query_provenance as qp
        monkeypatch.setattr(qp, "default_store", temp_store)
        test_args = ["query_provenance.py", "--strategy", "cand_test_alpha", "--include-candidates"]
        monkeypatch.setattr(sys, "argv", test_args)

        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            qp.main()
        output = buf.getvalue()
        assert "⚠️ [CANDIDATE TIER — QUARANTINED FROM PRODUCTION BASELINE]" in output
        assert "cand_test_alpha" in output
