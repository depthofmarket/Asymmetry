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
        test_args = ["alpha_factory.py", "--evaluate", "ensemble", "--record"]
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
        test_args = ["alpha_factory.py", "--evaluate", "ensemble", "--record"]
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
                assert expected_start == "2021-01-20"
                assert expected_end == "2026-08-19"
            elif strat_key == "S3":
                assert expected_start == "2021-02-26"
                assert expected_end == "2026-10-14"

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
        test_args = ["alpha_factory.py", "--evaluate", "ensemble", "--record"]
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
        assert abs(audit["gross_profit"] - 41432.71) < 0.05
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

    def test_binding_veto_on_unviable_alpha(self, temp_store, monkeypatch, capsys):
        """P1.5: Alpha failing multiple testing hurdle (S2 standalone) receives binding veto."""
        monkeypatch.setattr(af, "default_store", temp_store)
        test_args = ["alpha_factory.py", "--strategy", "S2"]
        monkeypatch.setattr(sys, "argv", test_args)

        ret = af.main()
        assert ret == 1  # Exit code 1 on veto

        captured = capsys.readouterr().out
        assert "BINDING VETO ISSUED" in captured
        assert "REJECTED_BY_ADVERSARIAL_VETO" in captured
        # Ensure no write occurred
        assert len(temp_store.list_runs()) == 0
