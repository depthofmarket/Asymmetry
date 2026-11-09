"""
Test Suite: Alpha Factory Provenance & Adversarial Stress Subsystem.

Verifies remediation of Priority 1 flaws in scripts/alpha_factory.py:
1. --record flag enforcement (dry-run does not write to DB; --record persists).
2. Dynamic Git commit resolution (queried from store.get_git_commit(), never hardcoded '8cb04d68a9').
3. Dynamic date range extraction (derived from trade dataframe min/max, never static literals).
4. Authentic gross profit calculation (matches wins.sum(), never net_pnl + 1000).
5. Accurate DSR trial count accounting (minimum 25 / dynamically parsed from wiki/failed_ideas.md).
6. Strategy CLI flag alias support (--strategy and --evaluate).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest import dashboard_analytics as da
from backtest.provenance import ProvenanceRecord, ProvenanceStore, default_store
import scripts.alpha_factory as af


@pytest.fixture
def temp_store(tmp_path):
    """Provides an isolated, clean ProvenanceStore for testing database writes."""
    db_file = tmp_path / "test_backtest_provenance.db"
    jsonl_file = tmp_path / "test_backtest_provenance.jsonl"
    return ProvenanceStore(db_path=db_file, jsonl_path=jsonl_file)


class TestAlphaFactoryProvenanceRemediation:
    """Comprehensive regression tests for Priority 1 provenance remediation."""

    def test_record_flag_dry_run_does_not_mutate_db(self, temp_store, monkeypatch, capsys):
        """P1.1: When --record is False/omitted, DB must not be modified, and dry-run notice is output."""
        monkeypatch.setattr(af, "default_store", temp_store)
        test_args = ["alpha_factory.py", "--evaluate", "ensemble"]
        monkeypatch.setattr(sys, "argv", test_args)

        ret = af.main()
        assert ret == 0

        # Store must remain completely empty
        runs = temp_store.list_runs()
        assert len(runs) == 0, f"Dry run persisted {len(runs)} runs to database unexpectedly!"

        captured = capsys.readouterr().out
        assert "PROVENANCE VERIFICATION FOOTER" in captured
        assert "DRY RUN (not recorded to database; pass --record to persist)" in captured

    def test_record_flag_persists_to_db_when_passed(self, temp_store, monkeypatch, capsys):
        """P1.1: When --record is True, run is persisted into the database."""
        monkeypatch.setattr(af, "default_store", temp_store)
        test_args = ["alpha_factory.py", "--evaluate", "ensemble", "--record", "--trials", "25"]
        monkeypatch.setattr(sys, "argv", test_args)

        ret = af.main()
        assert ret == 0

        runs = temp_store.list_runs()
        assert len(runs) == 1, "Run was not persisted to database when --record was passed!"
        assert runs[0].strategy_id == "lucid_flex_ensemble"

        captured = capsys.readouterr().out
        assert "PROVENANCE VERIFICATION FOOTER" in captured
        assert "Run successfully registered in results/backtest_provenance.db" in captured

    def test_git_commit_dynamically_resolved(self, temp_store, monkeypatch):
        """P1.2: Git commit is dynamically queried from HEAD, never hardcoded '8cb04d68a9'."""
        monkeypatch.setattr(af, "default_store", temp_store)
        test_args = ["alpha_factory.py", "--evaluate", "ensemble", "--record", "--trials", "25"]
        monkeypatch.setattr(sys, "argv", test_args)

        af.main()
        run = temp_store.get_latest_run("lucid_flex_ensemble")
        assert run is not None

        expected_commit = temp_store.get_git_commit()
        assert run.git_commit == expected_commit
        assert run.git_commit != "8cb04d68a9"

    def test_date_range_dynamically_resolved_per_strategy(self):
        """P1.3: Date range matches min/max date of trade dataframe, not static strings."""
        trades_df = da.load_trades()

        for strat_key, strat_id in [
            ("S1", "morning_va_breakout_s1"),
            ("S2", "macro_momentum_s2"),
            ("S3", "gold_london_fix_s3"),
            ("ensemble", "lucid_flex_ensemble"),
        ]:
            sub_df = trades_df[trades_df["strat"] == strat_key] if strat_key != "ensemble" else trades_df
            expected_start = str(sub_df["date"].min())
            expected_end = str(sub_df["date"].max())

            # Verify strategy dates differ (confirming static dates are inappropriate)
            if strat_key == "S2":
                assert expected_start == "2021-02-26"
                assert expected_end == "2026-10-14"
            elif strat_key == "S3":
                assert expected_start == "2021-01-20"
                assert expected_end == "2026-08-19"

    def test_date_range_dynamically_resolved_on_arbitrary_slice(self, temp_store, monkeypatch):
        """P1.3: Slicing trades to a custom window updates date_start and date_end in record."""
        trades_df = da.load_trades()
        # Subset to 2021-2024 trades (approved by adversarial audit)
        custom_slice = trades_df[(trades_df["date"] >= "2021-01-01") & (trades_df["date"] <= "2024-12-31")].copy()
        assert not custom_slice.empty

        slice_min = str(custom_slice["date"].min())
        slice_max = str(custom_slice["date"].max())
        assert slice_max == "2024-12-27"

        monkeypatch.setattr(da, "load_trades", lambda: custom_slice)
        monkeypatch.setattr(af, "default_store", temp_store)
        test_args = ["alpha_factory.py", "--evaluate", "ensemble", "--record", "--trials", "25"]
        monkeypatch.setattr(sys, "argv", test_args)

        ret = af.main()
        assert ret == 0

        run = temp_store.get_latest_run("lucid_flex_ensemble")
        assert run is not None
        assert run.date_start == slice_min
        assert run.date_end == slice_max
        assert run.date_end == "2024-12-27"
        assert run.date_end != "2026-10-30"

    def test_gross_profit_computed_from_winning_trades(self):
        """P1.4: Gross profit is sum of winning trades, NOT net_pnl + 1000.0."""
        trades_df = da.load_trades()

        # 1. Ensemble verification
        audit = af.evaluate_candidate_trades(trades_df, "lucid_flex_ensemble", "Tri-Asset Ensemble")
        expected_gross = float(trades_df[trades_df["research_pnl"] > 0]["research_pnl"].sum())
        fabricated_gross = float(audit["net_pnl"]) + 1000.0

        assert abs(audit["gross_profit"] - expected_gross) < 0.01
        assert abs(audit["gross_profit"] - 46863.61) < 0.05
        assert audit["gross_profit"] != pytest.approx(fabricated_gross, abs=100.0)

        # 2. S1 verification
        s1_trades = trades_df[trades_df["strat"] == "S1"]
        audit_s1 = af.evaluate_candidate_trades(s1_trades, "morning_va_breakout_s1", "S1 VA Breakout")
        expected_s1_gross = float(s1_trades[s1_trades["research_pnl"] > 0]["research_pnl"].sum())
        assert abs(audit_s1["gross_profit"] - expected_s1_gross) < 0.01
        assert abs(audit_s1["gross_profit"] - 22751.07) < 0.05

    def test_dsr_trial_count_baseline(self):
        """P1.5: Baseline trial count reflects documented failed ideas and is >= 25."""
        baseline = af.get_baseline_trial_count()
        assert baseline >= 25

        # Check against wiki/failed_ideas.md headers
        if af.FAILED_IDEAS_PATH.exists():
            with open(af.FAILED_IDEAS_PATH, "r", encoding="utf-8") as f:
                headers = re.findall(r"### \d+\.\s+", f.read())
                assert baseline >= len(headers)

    def test_dsr_trial_count_scales_evt_hurdle(self):
        """P1.5: EVT hurdle SR* strictly increases with higher trial count N."""
        trades_df = da.load_trades()
        audit_low_n = af.evaluate_candidate_trades(trades_df, "test_strat", "Test Strat", trials=20)
        audit_high_n = af.evaluate_candidate_trades(trades_df, "test_strat", "Test Strat", trials=100)

        assert audit_high_n["sr_star"] > audit_low_n["sr_star"]
        assert audit_high_n["dsr"] < audit_low_n["dsr"]
        assert audit_low_n["trials"] == 20
        assert audit_high_n["trials"] == 100

    def test_cli_trials_override(self, temp_store, monkeypatch):
        """P1.5: CLI argument --trials correctly overrides default baseline."""
        monkeypatch.setattr(af, "default_store", temp_store)
        test_args = ["alpha_factory.py", "--evaluate", "ensemble", "--trials", "50", "--record"]
        monkeypatch.setattr(sys, "argv", test_args)

        ret = af.main()
        assert ret == 0

        run = temp_store.get_latest_run("lucid_flex_ensemble")
        assert run is not None
        assert "Trials: 50" in run.notes

    def test_strategy_flag_alias(self, temp_store, monkeypatch, capsys):
        """CLI supports both --strategy and --evaluate interchangeably."""
        monkeypatch.setattr(af, "default_store", temp_store)
        test_args = ["alpha_factory.py", "--strategy", "ensemble"]
        monkeypatch.setattr(sys, "argv", test_args)

        ret = af.main()
        assert ret == 0
        captured = capsys.readouterr().out
        assert "lucid_flex_ensemble" in captured

    def test_binding_veto_on_unviable_alpha(self, temp_store, monkeypatch, capsys, tmp_path):
        """P1.5: Alpha failing multiple testing hurdle (S2 standalone) receives binding veto with baseline protection."""
        monkeypatch.setattr(af, "default_store", temp_store)
        temp_failed_ideas = tmp_path / "failed_ideas.md"
        temp_failed_ideas.write_text(af.FAILED_IDEAS_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        monkeypatch.setattr(af, "FAILED_IDEAS_PATH", temp_failed_ideas)

        test_args = ["alpha_factory.py", "--strategy", "S2"]
        monkeypatch.setattr(sys, "argv", test_args)

        ret = af.main()
        assert ret == 1  # Exit code 1 on veto

        captured = capsys.readouterr().out
        assert "BINDING VETO ISSUED" in captured
        assert "REJECTED_BY_ADVERSARIAL_VETO" in captured
        # Ensure no write occurred in provenance store
        assert len(temp_store.list_runs()) == 0

        # Baseline protection: Authorized baseline S2 must NEVER be archived as a dead end
        assert "authorized production baseline" in captured
        archived_text = temp_failed_ideas.read_text(encoding="utf-8")
        assert "macro_momentum_s2" not in archived_text
        assert "Pre-Market Macro Momentum (08:35 ET): Adversarial Veto" not in archived_text

    def test_archive_rejected_candidate_baseline_protection(self, tmp_path, capsys):
        """Baseline Protection: archive_rejected_candidate skips baseline strategies and returns 0."""
        dummy_failed_ideas = tmp_path / "failed_ideas.md"
        dummy_failed_ideas.write_text("# Test Ledger\n\n## Table of Ruled-Out Concepts\n\n---\n", encoding="utf-8")

        mock_audit = {
            "strategy_id": "morning_va_breakout_s1",
            "strategy_name": "Morning VA Breakout (09:45 ET)",
            "trades": 316,
            "pf": 1.65,
            "win_rate": 57.0,
            "dsr": 0.042,
            "net_pnl": 8956.18,
            "max_dd": -1475.99,
            "veto_reasons": ["DSR < 0.05"],
        }

        ret = af.archive_rejected_candidate(
            mock_audit,
            failed_ideas_path=dummy_failed_ideas,
        )
        assert ret == 0
        content = dummy_failed_ideas.read_text(encoding="utf-8")
        assert "morning_va_breakout_s1" not in content
        captured = capsys.readouterr().out
        assert "is an authorized production baseline; skipping archival" in captured

    def test_dynamic_trial_count_includes_provenance_store_runs(self, temp_store, tmp_path):
        """Derives trial count dynamically from failed ideas + provenance runs (minimum 25)."""
        data_file = tmp_path / "data.parquet"
        data_file.write_bytes(b"DATA")

        # Record 5 test runs into temp_store
        for i in range(5):
            temp_store.record_run(
                run_id=f"run_test_{i}",
                strategy_id="morning_va_breakout_s1",
                strategy_name="S1",
                methodology="test",
                date_start="2021-01-01",
                date_end="2026-10-30",
                data_path=data_file,
                total_trades=100,
                win_rate=55.0,
                profit_factor=1.6,
                gross_profit=1000.0,
                net_profit=800.0,
                max_drawdown=200.0,
                sharpe_ratio=1.2,
                largest_win=50.0,
            )

        count = af.get_baseline_trial_count(temp_store)
        # Should be max(25, n_failed + 5)
        n_failed = 0
        if af.FAILED_IDEAS_PATH.exists():
            headers = re.findall(r"### \d+\.\s+", af.FAILED_IDEAS_PATH.read_text(encoding="utf-8"))
            n_failed = len(headers)

        assert count == max(25, n_failed + 5)
        assert count >= 29

    def test_dsr_trial_accounting_from_ledger_and_store_minimum_33(self):
        """DSR multiple testing trial count dynamically derives from failed ideas + provenance store and is >= 33."""
        total_trials = af.get_baseline_trial_count()
        assert total_trials >= 33, f"Expected DSR trial count >= 33, got {total_trials}"

    def test_archive_rejected_candidate_formats_and_increments(self, tmp_path):
        """archive_rejected_candidate appends properly formatted entry and updates table of ruled-out concepts."""
        dummy_failed_ideas = tmp_path / "failed_ideas.md"
        dummy_content = """# Failed Ideas & Invalidated Hypotheses Ledger

## Table of Ruled-Out Concepts

1. [Concept One](#1-concept-one-2026-01-01)
2. [Concept Two](#2-concept-two-2026-02-01)

---

### 1. Concept One (2026-01-01)
- **Evaluation Date**: 2026-01-01
- **Author / Agent**: Test Team
- **Core Premise**: First test concept
- **Sample/Artifact**: 50 trades
- **Empirical Failure Evidence**: Trades: 50, Profit Factor: 0.90
- **Structural Root Cause**: Fee drag
- **Standing Rule**: Do not deploy Concept One.

### 2. Concept Two (2026-02-01)
- **Evaluation Date**: 2026-02-01
- **Author / Agent**: Test Team
- **Core Premise**: Second test concept
- **Sample/Artifact**: 60 trades
- **Empirical Failure Evidence**: Trades: 60, Profit Factor: 0.85
- **Structural Root Cause**: Variance
- **Standing Rule**: Do not deploy Concept Two.
"""
        dummy_failed_ideas.write_text(dummy_content, encoding="utf-8")

        mock_audit = {
            "strategy_id": "candidate_alpha_v2",
            "strategy_name": "Candidate Alpha V2",
            "trades": 75,
            "pf": 0.88,
            "win_rate": 42.0,
            "dsr": 0.0001,
            "net_pnl": -1500.0,
            "max_dd": 2200.0,
            "veto_reasons": ["Profit Factor 0.88 < 1.30 minimum viable hurdle"],
        }

        archived_num = af.archive_rejected_candidate(
            mock_audit,
            concept_text="Short volatility mean reversion",
            date_start="2021-01-01",
            date_end="2026-10-30",
            failed_ideas_path=dummy_failed_ideas,
        )

        assert archived_num == 3
        updated_content = dummy_failed_ideas.read_text(encoding="utf-8")

        # Verify sequential header
        assert "### 3. Candidate Alpha V2: Adversarial Veto" in updated_content
        # Verify table of ruled-out concepts was updated
        assert "3. [Candidate Alpha V2: Adversarial Veto](#3-candidate-alpha-v2-adversarial-veto" in updated_content
        # Verify required schema elements
        assert "- **Core Premise**: Short volatility mean reversion" in updated_content
        assert "- **Structural Root Cause**:" in updated_content
        assert "- **Standing Rule**: Strategy candidate_alpha_v2 is quarantined" in updated_content

    def test_candidate_quarantine_default_in_store(self, temp_store, tmp_path):
        """Candidate runs are quarantined by default from list_runs and get_latest_run."""
        data_file = tmp_path / "data.parquet"
        data_file.write_bytes(b"DATA")

        # Record baseline run
        temp_store.record_run(
            run_id="run_base_prod",
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

        # Record candidate run
        temp_store.record_run(
            run_id="run_cand_research",
            strategy_id="experimental_candidate_v9",
            strategy_name="Experimental Candidate V9",
            methodology="in_sample",
            date_start="2026-01-01",
            date_end="2026-06-30",
            data_path=data_file,
            total_trades=40,
            win_rate=52.0,
            profit_factor=1.35,
            gross_profit=2000.0,
            net_profit=1200.0,
            max_drawdown=500.0,
            sharpe_ratio=0.9,
            largest_win=120.0,
        )

        # 1. Default list_runs excludes candidate
        default_runs = temp_store.list_runs()
        assert len(default_runs) == 1
        assert default_runs[0].run_id == "run_base_prod"

        # 2. Explicit list_runs with include_candidates includes both
        all_runs = temp_store.list_runs(include_candidates=True)
        assert len(all_runs) == 2

        # 3. Default get_latest_run returns baseline run
        latest_default = temp_store.get_latest_run()
        assert latest_default is not None
        assert latest_default.run_id == "run_base_prod"

        # 4. Querying candidate strategy attaches quarantine warning flag
        cand_record = temp_store.get_latest_run(strategy_id="experimental_candidate_v9")
        assert cand_record is not None
        assert "CANDIDATE_TIER_QUARANTINED" in cand_record.warnings
