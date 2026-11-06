"""
Adversarial Empirical Stress-Testing Suite for Gate 2 Audit:
1. Agent Security Redirection Bypasses (validate_command, safe_subprocess_run).
2. Candidate Quarantine Leakage (ProvenanceStore, query_provenance CLI, sentinels).
3. Dynamic DSR Accounting Stress (ledger scaling, EVT hurdle monotonicity, automated archival).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from backtest.agent_guardrails import (
    CommandExecutionBlockedError,
    DANGEROUS_BINARIES,
    DANGEROUS_SHELL_TOKENS,
    safe_subprocess_run,
    validate_command,
)
from backtest import dashboard_analytics as da
from backtest.provenance import (
    ProvenanceRecord,
    ProvenanceStore,
    default_store,
)
from config.strategy_registry import (
    StrategyTier,
    get_authorized_baseline_ids,
    is_production_baseline,
)
import scripts.alpha_factory as af

REPO_ROOT = Path(__file__).resolve().parents[1]


# ==============================================================================
# SECTION 1: AGENT SECURITY REDIRECTION & SHELL INJECTION BYPASSES
# ==============================================================================

class TestAdversarialAgentSecurityRedirectionBypasses(unittest.TestCase):
    """
    Adversarially probe and stress-test agent guardrails against shell redirection tricks,
    backgrounding, subshells, quoting variants, and exception inheritance.
    """

    def test_exception_type_and_inheritance(self) -> None:
        """Verify CommandExecutionBlockedError inherits from PermissionError."""
        self.assertTrue(issubclass(CommandExecutionBlockedError, PermissionError))
        err = CommandExecutionBlockedError("test blocked")
        self.assertIsInstance(err, PermissionError)
        self.assertIsInstance(err, CommandExecutionBlockedError)

    def test_standard_output_redirection_bypasses(self) -> None:
        """Test variations of stdout redirection (> and >>) in string and list commands."""
        tricks = [
            "pytest > /tmp/out.txt",
            "pytest 1> /tmp/out.txt",
            "pytest >/tmp/out.txt",
            "pytest >> /tmp/out.txt",
            "pytest 1>> /tmp/out.txt",
            "pytest >>/tmp/out.txt",
            "echo 1 > output.log",
            "python -c 'print(1)' > out.txt",
            "python -c 'print(1)' >> append.log",
        ]
        for cmd in tricks:
            valid, reason = validate_command(cmd)
            self.assertFalse(valid, f"Expected '{cmd}' to be blocked by validate_command")
            self.assertIn("Shell chaining/injection detected", reason or "")

            with self.assertRaises(CommandExecutionBlockedError) as ctx:
                safe_subprocess_run(cmd)
            self.assertIsInstance(ctx.exception, PermissionError)

    def test_stderr_and_combined_redirection_bypasses(self) -> None:
        """Test stderr redirection and combinations (2>&1, &>, >&, 2>)."""
        tricks = [
            "pytest 2>&1",
            "pytest 2>&1 > /tmp/out.txt",
            "pytest 2>&1 | tee out.txt",
            "pytest &> /tmp/out.txt",
            "pytest >& /tmp/out.txt",
            "pytest 2> /tmp/err.txt",
            "python -c 'pass' 2>&1",
            "ls 2>/dev/null",
        ]
        for cmd in tricks:
            valid, reason = validate_command(cmd)
            self.assertFalse(valid, f"Expected '{cmd}' to be blocked by validate_command")
            self.assertIn("Shell chaining/injection detected", reason or "")

            with self.assertRaises(CommandExecutionBlockedError) as ctx:
                safe_subprocess_run(cmd)
            self.assertIsInstance(ctx.exception, PermissionError)

    def test_input_redirection_bypasses(self) -> None:
        """Test input redirection tricks (<, <<, <<<, 0<)."""
        tricks = [
            "pytest < /tmp/in.txt",
            "cat < /etc/passwd",
            "cat << EOF\nsecret\nEOF",
            "cat <<< 'hello'",
            "python -c 'pass' 0< /tmp/in.txt",
            "pytest 0</dev/null",
        ]
        for cmd in tricks:
            valid, reason = validate_command(cmd)
            self.assertFalse(valid, f"Expected '{cmd}' to be blocked by validate_command")
            self.assertIn("Shell chaining/injection detected", reason or "")

            with self.assertRaises(CommandExecutionBlockedError) as ctx:
                safe_subprocess_run(cmd)
            self.assertIsInstance(ctx.exception, PermissionError)

    def test_background_concurrency_bypasses(self) -> None:
        """Test background execution (&, &!, &&)."""
        tricks = [
            "pytest &",
            "pytest & echo 1",
            "python run.py &",
            "sleep 10 &",
            "pytest &; ls",
        ]
        for cmd in tricks:
            valid, reason = validate_command(cmd)
            self.assertFalse(valid, f"Expected '{cmd}' to be blocked by validate_command")
            self.assertIn("Shell chaining/injection detected", reason or "")

            with self.assertRaises(CommandExecutionBlockedError) as ctx:
                safe_subprocess_run(cmd)
            self.assertIsInstance(ctx.exception, PermissionError)

    def test_subshell_and_command_substitution_bypasses(self) -> None:
        """Test subshells and substitution tricks ($(cmd), `cmd`, (cmd))."""
        tricks = [
            "echo $(whoami)",
            "echo `id`",
            "pytest $(echo tests/)",
            "cat `ls`",
        ]
        for cmd in tricks:
            valid, reason = validate_command(cmd)
            self.assertFalse(valid, f"Expected '{cmd}' to be blocked by validate_command")
            self.assertIn("Shell chaining/injection detected", reason or "")

            with self.assertRaises(CommandExecutionBlockedError) as ctx:
                safe_subprocess_run(cmd)
            self.assertIsInstance(ctx.exception, PermissionError)

    def test_argument_list_tokens_contain_redirection(self) -> None:
        """Test sequence/list inputs containing redirection characters."""
        list_tricks = [
            ["pytest", ">", "/tmp/out.txt"],
            ["python", "-c", "print(1)", ">>", "/tmp/out.txt"],
            ["pytest", "2>&1"],
            ["cat", "<", "/tmp/in.txt"],
            ["cat", "<<", "EOF"],
            ["sleep", "100", "&"],
            ["python", "script.py", "&>out.txt"],
        ]
        for cmd_list in list_tricks:
            valid, reason = validate_command(cmd_list)
            self.assertFalse(valid, f"Expected argument list {cmd_list!r} to be blocked")
            self.assertIn("Shell chaining/injection detected", reason or "")

            with self.assertRaises(CommandExecutionBlockedError) as ctx:
                safe_subprocess_run(cmd_list)
            self.assertIsInstance(ctx.exception, PermissionError)

    def test_shell_true_is_strictly_prohibited(self) -> None:
        """Verify safe_subprocess_run rejects shell=True regardless of command benignity."""
        benign_commands = [
            ["echo", "hello"],
            "pytest --version",
            ["git", "status"],
        ]
        for cmd in benign_commands:
            with self.assertRaises(CommandExecutionBlockedError) as ctx:
                safe_subprocess_run(cmd, shell=True)
            self.assertIn("shell=True is strictly prohibited", str(ctx.exception))
            self.assertIsInstance(ctx.exception, PermissionError)

    def test_benign_commands_without_redirection_succeed(self) -> None:
        """Verify benign commands execute safely without error."""
        res = safe_subprocess_run(
            [sys.executable, "-c", "import sys; sys.stdout.write('gate2_challenger_ok')"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "gate2_challenger_ok")


# ==============================================================================
# SECTION 2: CANDIDATE QUARANTINE LEAKAGE ADVERSARIAL STRESS TESTS
# ==============================================================================

class TestAdversarialCandidateQuarantineLeakage(unittest.TestCase):
    """
    Adversarially probe candidate quarantine in SQLite store, CLI queries,
    pre-market readiness, and session sentinels.
    """

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="test_quarantine_")
        self.db_path = Path(self.tmp_dir) / "test_provenance.db"
        self.jsonl_path = Path(self.tmp_dir) / "test_provenance.jsonl"
        self.store = ProvenanceStore(db_path=self.db_path, jsonl_path=self.jsonl_path)

        # Seed 1 BASELINE run and 1 FORWARD_DEMO run
        self.store.record_run(
            strategy_id="morning_va_breakout_s1",
            strategy_name="Morning VA Breakout",
            methodology="multi_year_walkforward",
            date_start="2021-01-01",
            date_end="2026-10-30",
            data_path=str(REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"),
            total_trades=150,
            win_rate=58.5,
            profit_factor=1.75,
            gross_profit=45000.0,
            net_profit=32000.0,
            max_drawdown=2800.0,
            sharpe_ratio=2.1,
            largest_win=1200.0,
            strategy_tier=StrategyTier.BASELINE,
            run_id="run_baseline_s1",
        )
        self.store.record_run(
            strategy_id="lucid_flex_forward_demo",
            strategy_name="Live Forward Demo Parity",
            methodology="forward_demo",
            date_start="2026-10-01",
            date_end="2026-11-06",
            data_path=str(REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"),
            total_trades=40,
            win_rate=62.0,
            profit_factor=2.05,
            gross_profit=5000.0,
            net_profit=4100.0,
            max_drawdown=650.0,
            sharpe_ratio=2.6,
            largest_win=350.0,
            strategy_tier=StrategyTier.FORWARD_DEMO,
            run_id="run_forward_demo",
        )

        # Seed 1 CANDIDATE run dated in future to ensure it would be latest if not quarantined
        self.store.record_run(
            strategy_id="experimental_breakout_cand_v1",
            strategy_name="Experimental Breakout Candidate",
            methodology="in_sample",
            date_start="2026-01-01",
            date_end="2026-11-06",
            data_path=str(REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"),
            total_trades=200,
            win_rate=75.0,
            profit_factor=3.50,
            gross_profit=90000.0,
            net_profit=80000.0,
            max_drawdown=1200.0,
            sharpe_ratio=3.8,
            largest_win=2000.0,
            strategy_tier=StrategyTier.CANDIDATE,
            run_id="run_candidate_2099",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_default_list_runs_never_includes_candidates(self) -> None:
        """Verify default list_runs() strictly returns BASELINE and FORWARD_DEMO, never CANDIDATE."""
        runs = self.store.list_runs()
        self.assertEqual(len(runs), 2, "Default list_runs must only return 2 baseline/demo runs")
        tiers = {r.strategy_tier for r in runs}
        self.assertNotIn("CANDIDATE", tiers)
        self.assertNotIn(StrategyTier.CANDIDATE.value, tiers)
        run_ids = {r.run_id for r in runs}
        self.assertNotIn("run_candidate_2099", run_ids)

    def test_default_get_latest_run_never_returns_candidate(self) -> None:
        """Verify default get_latest_run() never returns candidate even if candidate has newest timestamp."""
        latest = self.store.get_latest_run()
        self.assertIsNotNone(latest)
        self.assertNotEqual(latest.run_id, "run_candidate_2099")
        self.assertIn(latest.strategy_tier, ("BASELINE", "FORWARD_DEMO"))

    def test_default_list_runs_for_candidate_id_returns_empty(self) -> None:
        """Verify default list_runs(strategy_id=cand_id) excludes candidate without explicit flag."""
        runs = self.store.list_runs(strategy_id="experimental_breakout_cand_v1")
        self.assertEqual(len(runs), 0, "Default list_runs for candidate id must return empty list")

    def test_explicit_include_candidates_surfaces_candidate_with_quarantine_warning(self) -> None:
        """Verify explicit include_candidates=True returns candidates with CANDIDATE_TIER_QUARANTINED warning."""
        runs = self.store.list_runs(include_candidates=True)
        self.assertEqual(len(runs), 3)
        cand_runs = [r for r in runs if r.run_id == "run_candidate_2099"]
        self.assertEqual(len(cand_runs), 1)
        self.assertEqual(cand_runs[0].strategy_tier, "CANDIDATE")
        self.assertIn("CANDIDATE_TIER_QUARANTINED", cand_runs[0].warnings)

    def test_explicit_tier_candidate_surfaces_candidate(self) -> None:
        """Verify explicit tier=CANDIDATE returns only candidates."""
        runs = self.store.list_runs(tier=StrategyTier.CANDIDATE)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].run_id, "run_candidate_2099")
        self.assertIn("CANDIDATE_TIER_QUARANTINED", runs[0].warnings)

    def test_cli_query_provenance_default_list_quarantines_candidates(self) -> None:
        """Verify CLI scripts/query_provenance.py --list does not display candidates by default."""
        env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
        # Patch DB path or run against production store
        cmd = [sys.executable, "scripts/query_provenance.py", "--list"]
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        # Production store must not have CANDIDATE in --list
        for line in proc.stdout.splitlines():
            if "|" in line and "RUN ID" not in line and "=" not in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    tier = parts[2]
                    self.assertNotEqual(tier, "CANDIDATE", f"Candidate run leaked into CLI --list: {line}")

    def test_cli_query_provenance_latest_quarantines_candidates(self) -> None:
        """Verify CLI scripts/query_provenance.py --latest does not display candidate tier."""
        cmd = [sys.executable, "scripts/query_provenance.py", "--latest"]
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Strategy Tier: CANDIDATE", proc.stdout)

    def test_premarket_readiness_quarantines_candidates(self) -> None:
        """Verify check_morning_readiness.py check_provenance_store uses include_candidates=False."""
        from scripts.check_morning_readiness import check_provenance_store
        res = check_provenance_store()
        self.assertTrue(res["valid"])
        # default_store.list_runs(include_candidates=False) must match
        baseline_runs = default_store.list_runs(include_candidates=False, limit=100)
        self.assertEqual(res["runs_count"], len(baseline_runs))

    def test_unregistered_candidate_cannot_claim_baseline_tier(self) -> None:
        """Verify that record_run raises ValueError when an unvetted strategy attempts to record as BASELINE."""
        with self.assertRaises(ValueError) as ctx:
            self.store.record_run(
                strategy_id="fake_unvetted_strat",
                strategy_name="Fake Unvetted Strat",
                methodology="in_sample",
                date_start="2026-01-01",
                date_end="2026-11-06",
                data_path=str(REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"),
                total_trades=50,
                win_rate=60.0,
                profit_factor=2.0,
                gross_profit=10000.0,
                net_profit=8000.0,
                max_drawdown=500.0,
                sharpe_ratio=2.0,
                largest_win=500.0,
                strategy_tier=StrategyTier.BASELINE,
            )
        self.assertIn("is not an authorized production baseline", str(ctx.exception))


# ==============================================================================
# SECTION 3: DYNAMIC DSR ACCOUNTING & EVT HURDLE STRESS TESTS
# ==============================================================================

class TestAdversarialDynamicDSRAccountingStress(unittest.TestCase):
    """
    Stress-tests dynamic trial accounting:
    1. Scaling of baseline trial count with wiki dead ends + provenance store runs.
    2. Monotonic increase of EVT hurdle SR* with trial count N.
    3. Monotonic decrease of Deflated Sharpe Ratio with trial count N.
    4. Automated rejection archival to wiki/failed_ideas.md without duplicate pollution.
    """

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(prefix="test_dsr_")
        self.fake_failed_ideas = Path(self.tmp_dir) / "failed_ideas.md"
        # Seed fake failed ideas with 3 headings
        self.fake_failed_ideas.write_text(
            "# Failed Ideas Ledger\n\n"
            "## Table of Ruled-Out Concepts\n\n"
            "1. [Idea 1](#1-idea-1)\n2. [Idea 2](#2-idea-2)\n3. [Idea 3](#3-idea-3)\n\n"
            "---\n\n"
            "### 1. Idea 1\n- details\n\n"
            "### 2. Idea 2\n- details\n\n"
            "### 3. Idea 3\n- details\n",
            encoding="utf-8",
        )

        self.db_path = Path(self.tmp_dir) / "prov.db"
        self.jsonl_path = Path(self.tmp_dir) / "prov.jsonl"
        self.store = ProvenanceStore(db_path=self.db_path, jsonl_path=self.jsonl_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_baseline_trial_count_floor_is_twenty_five(self) -> None:
        """Trial count must never fall below minimum floor of 25."""
        with patch.object(af, "FAILED_IDEAS_PATH", self.fake_failed_ideas):
            # n_failed = 3, n_prov = 0 -> sum = 3 < 25 -> floor is 25
            count = af.get_baseline_trial_count(self.store)
            self.assertEqual(count, 25)

    def test_trial_count_scales_dynamically_with_failed_ideas_and_provenance_runs(self) -> None:
        """Trial count scales dynamically as failed ideas and provenance runs are added."""
        # Seed 20 additional failed ideas (total 23)
        extra_content = "\n".join(f"### {i}. Mock Failed Concept {i}\n- details\n" for i in range(4, 24))
        self.fake_failed_ideas.write_text(self.fake_failed_ideas.read_text() + extra_content, encoding="utf-8")

        # Seed 10 runs in provenance store
        for i in range(10):
            self.store.record_run(
                strategy_id=f"candidate_test_run_{i}",
                strategy_name=f"Candidate {i}",
                methodology="in_sample",
                date_start="2026-01-01",
                date_end="2026-11-06",
                data_path=str(REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"),
                total_trades=35,
                win_rate=55.0,
                profit_factor=1.5,
                gross_profit=5000.0,
                net_profit=3500.0,
                max_drawdown=500.0,
                sharpe_ratio=1.5,
                largest_win=400.0,
                strategy_tier=StrategyTier.CANDIDATE,
                run_id=f"run_test_{i}",
            )

        with patch.object(af, "FAILED_IDEAS_PATH", self.fake_failed_ideas):
            # 23 failed ideas + 10 provenance runs = 33 (> 25)
            count = af.get_baseline_trial_count(self.store)
            self.assertEqual(count, 33, f"Expected exactly 33 trials (23 failed + 10 runs), got {count}")

            # Add 5 more failed ideas
            more_failed = "\n".join(f"### {i}. Mock Concept {i}\n- details\n" for i in range(24, 29))
            self.fake_failed_ideas.write_text(self.fake_failed_ideas.read_text() + more_failed, encoding="utf-8")

            count2 = af.get_baseline_trial_count(self.store)
            self.assertEqual(count2, 38, "Adding 5 failed ideas must scale trial count by 5")

    def test_evt_hurdle_increases_strictly_monotonically_with_trials(self) -> None:
        """
        Extreme Value Theory expected maximum Sharpe (SR*) must increase strictly
        monotonically as trial count N scales: N1 < N2 ==> SR*(N1) < SR*(N2).
        """
        trial_steps = [2, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]
        sr_stars = [da.expected_max_sharpe(n_trials=n, var_sharpe=0.5) for n in trial_steps]

        for i in range(len(trial_steps) - 1):
            n1, n2 = trial_steps[i], trial_steps[i + 1]
            sr1, sr2 = sr_stars[i], sr_stars[i + 1]
            self.assertLess(
                sr1, sr2,
                f"EVT hurdle SR* violated strict monotonicity between N={n1} ({sr1:.4f}) and N={n2} ({sr2:.4f})"
            )

    def test_dsr_decreases_strictly_monotonically_with_trials(self) -> None:
        """
        For a fixed sequence of returns, Deflated Sharpe Ratio (DSR) must decrease
        strictly monotonically as trial count N scales.
        """
        np.random.seed(42)
        # Moderate positive return series with annualized Sharpe around 2.3
        returns = np.random.normal(loc=0.001, scale=0.01, size=1000)

        trial_steps = [1, 5, 10, 25, 50, 100, 250, 500]
        dsr_values = [
            da.deflated_sharpe_ratio(returns, n_trials=n, var_sharpe=0.5, annualization_factor=252)
            for n in trial_steps
        ]

        for i in range(len(trial_steps) - 1):
            n1, n2 = trial_steps[i], trial_steps[i + 1]
            d1, d2 = dsr_values[i], dsr_values[i + 1]
            self.assertGreater(
                d1, d2,
                f"DSR violated strict downward penalty between N={n1} ({d1:.5f}) and N={n2} ({d2:.5f})"
            )

    def test_automated_rejection_archival_and_deduplication(self) -> None:
        """
        Verify archive_rejected_candidate appends sequentially numbered heading
        and prevents duplicate entries.
        """
        audit_mock = {
            "strategy_id": "candidate_failed_v1",
            "strategy_name": "Failed Mean Reversion Probe",
            "trades": 45,
            "pf": 1.12,
            "win_rate": 42.0,
            "dsr": 0.015,
            "net_pnl": 1200.0,
            "max_dd": 2400.0,
            "veto_reasons": ["Profit Factor 1.12 < 1.30", "DSR 0.015 < 0.05"],
        }

        # First archival: appends as #4 (since initial had 3)
        res_num = af.archive_rejected_candidate(
            audit_mock,
            concept_text="Failed Mean Reversion Probe on NQ",
            failed_ideas_path=self.fake_failed_ideas,
        )
        self.assertEqual(res_num, 4)

        updated_text = self.fake_failed_ideas.read_text(encoding="utf-8")
        self.assertIn("### 4. Failed Mean Reversion Probe", updated_text)
        self.assertIn("candidate_failed_v1 is quarantined", updated_text)
        self.assertIn("Profit Factor 1.12 < 1.30", updated_text)

        # Second archival with same candidate: must detect duplicate and NOT append #5
        res_dup = af.archive_rejected_candidate(
            audit_mock,
            concept_text="Failed Mean Reversion Probe on NQ",
            failed_ideas_path=self.fake_failed_ideas,
        )
        self.assertEqual(res_dup, 4, "Duplicate candidate archival must return existing index without adding new entry")
        re_updated_text = self.fake_failed_ideas.read_text(encoding="utf-8")
        self.assertNotIn("### 5.", re_updated_text, "Duplicate candidate archival must not create ### 5 heading")

    def test_production_baselines_are_exempt_from_failed_ideas_archival(self) -> None:
        """Production baselines must never be archived to failed_ideas.md."""
        baseline_ids = [s for s in get_authorized_baseline_ids() if is_production_baseline(s)]
        self.assertEqual(len(baseline_ids), 4, "Must have exactly 4 authorized production baselines")
        for strat_id in baseline_ids:
            audit = {
                "strategy_id": strat_id,
                "strategy_name": "Baseline Strat",
                "trades": 100,
                "pf": 1.05,
                "win_rate": 50.0,
                "dsr": 0.02,
                "net_pnl": 500.0,
                "max_dd": 1000.0,
                "veto_reasons": ["PF < 1.30"],
            }
            res = af.archive_rejected_candidate(audit, failed_ideas_path=self.fake_failed_ideas)
            self.assertEqual(res, 0, f"Baseline '{strat_id}' must return 0 and be exempt from failed_ideas archival")


if __name__ == "__main__":
    unittest.main()
