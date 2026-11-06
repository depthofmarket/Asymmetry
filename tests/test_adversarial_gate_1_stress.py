"""
Adversarial Stress Test Suite: Gate 1 Empirical Validation.

Empirically and adversarially challenges:
1. Alpha Factory DSR trial accounting extreme/corner cases & automated archiving integrity:
   - Missing store, corrupted SQLite binary store, empty store, missing/corrupted failed_ideas.md.
   - Ultra-large trial counts (N = 100,000) and EVT multiple testing numerical stability.
   - Automated archiving to wiki/failed_ideas.md with multi-line premises, unicode, markdown injection,
     and 100% compliance under scripts/verify_wiki_integrity.py.
2. Candidate Quarantine leak testing:
   - Attempt to leak candidate runs into --list, --latest, --stat, check_morning_readiness.py, and session_sentinel.py.
   - Verify candidates cannot masquerade as baselines via spoofing, whitespace, or unauthorized tier claims.
3. Agent Security Guardrails bypass attempts:
   - Redirection injections (>, >>, <, <<, &, |, &&, ;, $(), `, \\n, \\r) in string and argument sequences.
   - shell=True and truthy variants injection.
   - Command argument variations and path escapes (../../../../bin/rm, /bin/./rm, /usr/bin/sudo, env rm, python -m main_backtest).
   - Assert CommandExecutionBlockedError is raised in every blocked scenario.
"""

from __future__ import annotations

import io
import json
import math
from contextlib import redirect_stdout
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest import dashboard_analytics as da
from backtest.agent_guardrails import (
    CommandExecutionBlockedError,
    DANGEROUS_BINARIES,
    DANGEROUS_SHELL_TOKENS,
    safe_subprocess_run,
    validate_command,
)
from backtest.provenance import ProvenanceRecord, ProvenanceStore
from config.strategy_registry import (
    StrategyTier,
    get_authorized_baseline_ids,
    get_strategy_tier,
    is_production_baseline,
    is_valid_strategy_id_format,
    register_candidate,
    register_strategy,
    reset_registry,
    validate_strategy_id,
)
import scripts.alpha_factory as af
import scripts.check_morning_readiness as cmr
import scripts.query_provenance as qp


# ==============================================================================
# SECTION 1: Alpha Factory DSR Trial Accounting & Archiving Stress
# ==============================================================================

class TestAlphaFactoryDSRTrialAccountingStress(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path("/tmp/challenger_gate1_dsr_stress")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        reset_registry()

    def tearDown(self):
        import shutil
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        reset_registry()

    def test_missing_store_graceful_fallback(self):
        """Corner Case: Missing store file or uninitialized path must not crash and returns >= 25."""
        nonexistent_db = self.tmp_dir / "does_not_exist.db"
        nonexistent_jsonl = self.tmp_dir / "does_not_exist.jsonl"
        store = ProvenanceStore(db_path=nonexistent_db, jsonl_path=nonexistent_jsonl)
        if nonexistent_db.exists():
            nonexistent_db.unlink()

        count = af.get_baseline_trial_count(store=store)
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 25)

    def test_corrupted_sqlite_store_graceful_handling(self):
        """Corner Case: Store with corrupted binary garbage bytes must not raise an unhandled exception."""
        class CorruptedStore:
            def list_runs(self, *args, **kwargs):
                raise sqlite3.DatabaseError("file is not a database")

        count = af.get_baseline_trial_count(store=CorruptedStore())  # type: ignore[arg-type]
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 25)

    def test_empty_store_and_missing_failed_ideas(self):
        """Corner Case: Both empty store and non-existent failed_ideas.md must return exactly the minimum 25."""
        empty_db = self.tmp_dir / "empty.db"
        empty_jsonl = self.tmp_dir / "empty.jsonl"
        empty_store = ProvenanceStore(db_path=empty_db, jsonl_path=empty_jsonl)

        with patch.object(af, "FAILED_IDEAS_PATH", self.tmp_dir / "nonexistent_failed_ideas.md"):
            count = af.get_baseline_trial_count(store=empty_store)
            self.assertEqual(count, 25, f"Expected minimum 25 for empty store + missing failed ideas, got {count}")

    def test_corrupted_failed_ideas_file(self):
        """Corner Case: failed_ideas.md with corrupted content or invalid markdown headers."""
        corrupted_failed_ideas = self.tmp_dir / "corrupted_failed_ideas.md"
        corrupted_failed_ideas.write_text(
            "# Corrupted Ledger\n\n### Invalid Header\n### -5. Negative Number\n### NotANumber. Missing Period\n"
            "Random text without any schema\n",
            encoding="utf-8",
        )

        with patch.object(af, "FAILED_IDEAS_PATH", corrupted_failed_ideas):
            empty_db = self.tmp_dir / "empty2.db"
            empty_jsonl = self.tmp_dir / "empty2.jsonl"
            empty_store = ProvenanceStore(db_path=empty_db, jsonl_path=empty_jsonl)
            count = af.get_baseline_trial_count(store=empty_store)
            self.assertGreaterEqual(count, 25)

    def test_ultra_large_trial_ledger_numerical_stability(self):
        """Corner Case: Large trial ledger (N = 100,000) does not cause numerical overflow in EVT/DSR."""
        class HugeStore:
            def list_runs(self, *args, **kwargs):
                return [None] * 100000

        huge_trials = af.get_baseline_trial_count(store=HugeStore())  # type: ignore[arg-type]
        self.assertGreaterEqual(huge_trials, 100000)

        # Test EVT max Sharpe calculation with N = 100,000
        sr_star = da.expected_max_sharpe(n_trials=huge_trials, var_sharpe=0.5)
        self.assertTrue(math.isfinite(sr_star), "sr_star became non-finite with N=100,000")
        self.assertGreater(sr_star, 2.5, "sr_star should be elevated for N=100,000 trials")

        # Test DSR computation under N = 100,000
        np.random.seed(42)
        returns = np.random.normal(0.0005, 0.01, 500)  # Moderate positive returns
        dsr = da.deflated_sharpe_ratio(
            returns=returns,
            n_trials=huge_trials,
            var_sharpe=0.5,
            annualization_factor=252.0,
        )
        self.assertTrue(math.isfinite(dsr), "DSR became non-finite with N=100,000")
        self.assertLess(dsr, 0.05, "DSR should heavily penalize moderate returns over 100,000 trials")

    def test_archive_rejected_candidate_with_multiline_premise_and_strange_chars(self):
        """Stress: Archive rejected candidate with multi-line premise, unicode/emojis, and markdown characters,
        verifying 100% compliance with python scripts/verify_wiki_integrity.py.
        """
        failed_ideas_real = REPO_ROOT / "wiki/failed_ideas.md"
        backup_text = failed_ideas_real.read_text(encoding="utf-8")

        try:
            # Adversarial candidate payload with strange characters & emojis
            adversarial_audit = {
                "strategy_id": "adversarial_multi_asset_breakout_v7",
                "strategy_name": "Adversarial [V7.1] (NQ/MES) & Cross-Flow: 'quotes' *bold* _italics_ #alpha",
                "trades": 64,
                "pf": 0.94,
                "win_rate": 43.5,
                "dsr": 0.0002,
                "net_pnl": -850.50,
                "max_dd": 1420.00,
                "veto_reasons": ["Profit Factor 0.94 < 1.30 minimum viable hurdle", "DSR 0.0002 < 0.05 multiple testing hurdle"],
            }

            multiline_premise = (
                "Line 1: High-volatility breakout probe across cash equity open.\n"
                "Line 2: Conditioned on opposing TICK thrust & 🚀 multi-asset delta flow.\n"
                "Line 3: Tested with strange characters: 'single' \"double\" [bracketed] (parenthesized) & symbols."
            )

            # Execute archive directly to wiki/failed_ideas.md
            archived_num = af.archive_rejected_candidate(
                audit=adversarial_audit,
                concept_text=multiline_premise,
                date_start="2021-01-01",
                date_end="2026-10-30",
                failed_ideas_path=failed_ideas_real,
            )

            self.assertGreaterEqual(archived_num, 25)

            # Verify content was appended properly
            updated_content = failed_ideas_real.read_text(encoding="utf-8")
            self.assertIn(f"### {archived_num}.", updated_content)
            self.assertIn("Adversarial [V7.1] (NQ/MES) & Cross-Flow", updated_content)
            self.assertIn("Line 1: High-volatility breakout probe", updated_content)

            # Run verify_wiki_integrity.py directly on the live repo
            proc = subprocess.run(
                [sys.executable, "scripts/verify_wiki_integrity.py"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"verify_wiki_integrity.py failed after archiving candidate! Output:\n{proc.stdout}\n{proc.stderr}",
            )
            self.assertIn("ALL CHECKS PASSED: Wiki setup and protocols verified 100% compliant.", proc.stdout)

        finally:
            # Restore wiki/failed_ideas.md to original state
            failed_ideas_real.write_text(backup_text, encoding="utf-8")


# ==============================================================================
# SECTION 2: Candidate Quarantine Leak Testing
# ==============================================================================

class TestCandidateQuarantineStress(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path("/tmp/challenger_gate1_quarantine_stress")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        reset_registry()

        self.data_file = self.tmp_dir / "test_data.parquet"
        self.data_file.write_bytes(b"PARQUET_TEST_PAYLOAD")

        self.store = ProvenanceStore(
            db_path=self.tmp_dir / "quarantine_test.db",
            jsonl_path=self.tmp_dir / "quarantine_test.jsonl",
        )

        # Seed 1 baseline run
        self.base_record = self.store.record_run(
            run_id="run_base_20260101_s1",
            strategy_id="morning_va_breakout_s1",
            strategy_name="Morning VA Breakout",
            methodology="walkforward",
            date_start="2021-01-01",
            date_end="2026-10-30",
            data_path=self.data_file,
            total_trades=150,
            win_rate=56.0,
            profit_factor=1.65,
            gross_profit=15000.0,
            net_profit=11000.0,
            max_drawdown=1200.0,
            sharpe_ratio=1.35,
            largest_win=600.0,
        )

        # Seed 1 candidate run with a NEWER timestamp
        self.cand_record = self.store.record_run(
            run_id="run_cand_20260201_leak_attempt",
            strategy_id="experimental_cand_alpha_x",
            strategy_name="Experimental Alpha X",
            methodology="in_sample",
            date_start="2026-01-01",
            date_end="2026-06-30",
            data_path=self.data_file,
            total_trades=45,
            win_rate=51.0,
            profit_factor=1.32,
            gross_profit=3000.0,
            net_profit=1800.0,
            max_drawdown=700.0,
            sharpe_ratio=0.85,
            largest_win=250.0,
        )

    def tearDown(self):
        import shutil
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
        reset_registry()

    def test_candidate_does_not_leak_into_default_list(self):
        """Quarantine: store.list_runs() must not return candidate runs by default."""
        runs = self.store.list_runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].run_id, "run_base_20260101_s1")
        self.assertNotIn("run_cand_20260201_leak_attempt", [r.run_id for r in runs])

    def test_candidate_cannot_be_listed_without_include_candidates_flag(self):
        """Quarantine: Querying candidate strategy_id via list_runs without include_candidates returns 0 rows."""
        runs = self.store.list_runs(strategy_id="experimental_cand_alpha_x", include_candidates=False)
        self.assertEqual(len(runs), 0, "Candidate was returned by list_runs when include_candidates=False!")

    def test_candidate_does_not_leak_into_latest_run(self):
        """Quarantine: store.get_latest_run() must return the latest BASELINE, not a newer candidate."""
        latest = self.store.get_latest_run(include_candidates=False)
        self.assertIsNotNone(latest)
        self.assertEqual(latest.run_id, "run_base_20260101_s1")
        self.assertEqual(latest.strategy_id, "morning_va_breakout_s1")
        self.assertEqual(latest.strategy_tier, "BASELINE")

    def test_cli_list_strictly_quarantines_candidates(self):
        """Quarantine: query_provenance.py --list must not display candidate runs."""
        with patch.object(qp, "default_store", self.store):
            buf = io.StringIO()
            with patch.object(sys, "argv", ["query_provenance.py", "--list"]):
                with redirect_stdout(buf):
                    qp.main()
            out = buf.getvalue()

            self.assertIn("morning_va_breakout_s1", out)
            self.assertNotIn("experimental_cand_alpha_x", out)
            self.assertNotIn("CANDIDATE", out)

    def test_cli_latest_strictly_quarantines_candidates(self):
        """Quarantine: query_provenance.py --latest must display the baseline run, not the candidate."""
        with patch.object(qp, "default_store", self.store):
            buf = io.StringIO()
            with patch.object(sys, "argv", ["query_provenance.py", "--latest"]):
                with redirect_stdout(buf):
                    qp.main()
            out = buf.getvalue()

            self.assertIn("morning_va_breakout_s1", out)
            self.assertNotIn("experimental_cand_alpha_x", out)
            self.assertIn("Strategy Tier: BASELINE", out)

    def test_candidate_query_forces_quarantine_banner_and_warning_tag(self):
        """Quarantine: Explicitly querying a candidate strategy displays prominent quarantine banner and warning."""
        with patch.object(qp, "default_store", self.store):
            buf = io.StringIO()
            with patch.object(sys, "argv", ["query_provenance.py", "--strategy", "experimental_cand_alpha_x", "--include-candidates"]):
                with redirect_stdout(buf):
                    qp.main()
            out = buf.getvalue()

            self.assertIn("⚠️ [CANDIDATE TIER — QUARANTINED FROM PRODUCTION BASELINE]", out)
            self.assertIn("Strategy Tier: CANDIDATE", out)
            self.assertIn("CANDIDATE_TIER_QUARANTINED", out)

    def test_candidate_stat_query_forces_warning_tag(self):
        """Quarantine: Querying a stat on a candidate forces quarantine warning adjacent to number."""
        with patch.object(qp, "default_store", self.store):
            buf = io.StringIO()
            with patch.object(sys, "argv", ["query_provenance.py", "--strategy", "experimental_cand_alpha_x", "--stat", "profit_factor", "--include-candidates"]):
                with redirect_stdout(buf):
                    qp.main()
            out = buf.getvalue()

            self.assertIn("1.32", out)
            self.assertIn("CANDIDATE_TIER_QUARANTINED", out)
            self.assertIn("⚠️ [CANDIDATE TIER — QUARANTINED FROM PRODUCTION BASELINE]", out)

    def test_check_morning_readiness_quarantines_candidates(self):
        """Quarantine: check_morning_readiness.py check_provenance_store() must only count baselines."""
        with patch("backtest.provenance.default_store", self.store):
            prov_status = cmr.check_provenance_store()
            self.assertTrue(prov_status["valid"])
            self.assertEqual(prov_status["runs_count"], 1, "check_morning_readiness counted candidate runs!")
            self.assertEqual(prov_status["latest_run"], "run_base_20260101_s1")

        # Store with ONLY candidates -> runs_count must be 0
        cand_only_store = ProvenanceStore(
            db_path=self.tmp_dir / "cand_only.db",
            jsonl_path=self.tmp_dir / "cand_only.jsonl",
        )
        cand_only_store.record_run(
            run_id="cand_only_1",
            strategy_id="experimental_cand_only",
            strategy_name="Candidate Only",
            methodology="in_sample",
            date_start="2026-01-01",
            date_end="2026-06-30",
            data_path=self.data_file,
            total_trades=30,
            win_rate=50.0,
            profit_factor=1.2,
            gross_profit=1000.0,
            net_profit=500.0,
            max_drawdown=300.0,
            sharpe_ratio=0.7,
            largest_win=100.0,
        )
        with patch("backtest.provenance.default_store", cand_only_store):
            prov_status_cand = cmr.check_provenance_store()
            self.assertTrue(prov_status_cand["valid"])
            self.assertEqual(prov_status_cand["runs_count"], 0, "Candidate-only store should report 0 runs in readiness check!")
            self.assertIsNone(prov_status_cand["latest_run"])

    def test_masquerade_prevention_unauthorized_baseline_claims(self):
        """Spoofing Defense: Unvetted strategy cannot register or record as BASELINE."""
        with self.assertRaises(ValueError) as ctx:
            register_strategy("rogue_unvetted_scalper", tier=StrategyTier.BASELINE)
        self.assertIn("cannot be registered with tier BASELINE", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx2:
            self.store.record_run(
                strategy_id="rogue_unvetted_scalper",
                strategy_name="Rogue Scalper",
                strategy_tier=StrategyTier.BASELINE,
                methodology="walkforward",
                date_start="2021-01-01",
                date_end="2026-10-30",
                data_path=self.data_file,
                total_trades=100,
                win_rate=90.0,
                profit_factor=5.0,
                gross_profit=10000.0,
                net_profit=10000.0,
                max_drawdown=100.0,
                sharpe_ratio=3.0,
                largest_win=500.0,
            )
        self.assertIn("not an authorized production baseline", str(ctx2.exception))

    def test_masquerade_prevention_frozen_baseline_tampering(self):
        """Spoofing Defense: Cannot demote or alter frozen baseline tier."""
        with self.assertRaises(ValueError) as ctx:
            register_strategy("morning_va_breakout_s1", tier=StrategyTier.CANDIDATE)
        self.assertIn("Cannot override frozen production baseline", str(ctx.exception))

    def test_masquerade_prevention_malformed_strategy_slugs(self):
        """Spoofing Defense: Reject malformed or path-traversal strategy IDs."""
        malicious_slugs = [
            "",
            "   ",
            "has space inside",
            "rm -rf /",
            "strat;id",
            "strat|id",
            "strat&id",
            "-leading-dash",
            "../../../etc/passwd",
        ]
        for bad_slug in malicious_slugs:
            with self.assertRaises(ValueError, msg=f"Malformed slug {bad_slug!r} did not raise ValueError"):
                self.store.record_run(
                    strategy_id=bad_slug,
                    strategy_name="Bad Slug",
                    methodology="in_sample",
                    date_start="2021-01-01",
                    date_end="2026-10-30",
                    data_path=self.data_file,
                    total_trades=50,
                    win_rate=50.0,
                    profit_factor=1.2,
                    gross_profit=1000.0,
                    net_profit=500.0,
                    max_drawdown=200.0,
                    sharpe_ratio=0.8,
                    largest_win=100.0,
                )


# ==============================================================================
# SECTION 3: Agent Security Guardrails Adversarial Bypasses
# ==============================================================================

class TestAgentSecurityGuardrailsStress(unittest.TestCase):
    """Adversarially attempts every possible bypass vector against agent_guardrails.py."""

    def test_redirection_and_chaining_tokens_in_string_commands(self):
        """Adversarial bypass: Redirection and command chaining tokens in string commands."""
        attack_vectors = [
            ("pytest > /tmp/output.txt", ">"),
            ("pytest >> /tmp/append.log", ">>"),
            ("pytest < /tmp/input.txt", "<"),
            ("pytest << EOF\nsecret\nEOF", "<<"),
            ("python run.py &", "&"),
            ("pytest | grep -i fail", "|"),
            ("pytest && echo PWNED", "&&"),
            ("pytest || echo PWNED", "||"),
            ("pytest ; whoami", ";"),
            ("echo $(cat /etc/passwd)", "$("),
            ("echo `whoami`", "`"),
            ("pytest\nrm -rf /", "\n"),
            ("pytest\rrm -rf /", "\r"),
            ("echo 1 >out.txt", ">"),
            ("cmd 2>err.txt", ">"),
            ("cmd &>all.txt", ">"),
            ("cat <<< 'here string'", "<"),
        ]

        for cmd, token in attack_vectors:
            valid, reason = validate_command(cmd)
            self.assertFalse(valid, f"Expected attack vector {cmd!r} containing '{token}' to be blocked!")
            self.assertIn("Shell chaining/injection detected", reason or "")

            with self.assertRaises(CommandExecutionBlockedError, msg=f"Command {cmd!r} did not raise CommandExecutionBlockedError") as ctx:
                safe_subprocess_run(cmd)
            self.assertIsInstance(ctx.exception, PermissionError)
            self.assertIn("Command blocked by agent guardrails", str(ctx.exception))

    def test_redirection_and_chaining_tokens_in_argument_sequences(self):
        """Adversarial bypass: Redirection and command chaining tokens passed inside argument lists."""
        attack_lists = [
            ["echo", "pwn > file.txt"],
            ["python", "test.py", ">>", "log.txt"],
            ["cat", "<", "file.txt"],
            ["sh", "-c", "input << EOF"],
            ["python", "run.py", "&"],
            ["ls", "|", "grep", "secret"],
            ["pytest", "-k", "test_a && test_b"],
            ["pytest", "-k", "test_a || test_b"],
            ["echo", "foo; bar"],
            ["echo", "$(whoami)"],
            ["echo", "`id`"],
            ["pytest", "arg1\narg2"],
            ["pytest", "arg1\rarg2"],
        ]

        for cmd_list in attack_lists:
            valid, reason = validate_command(cmd_list)
            self.assertFalse(valid, f"Expected argument list {cmd_list!r} to be blocked!")
            self.assertIn("Shell chaining/injection detected", reason or "")

            with self.assertRaises(CommandExecutionBlockedError, msg=f"Command {cmd_list!r} did not raise CommandExecutionBlockedError") as ctx:
                safe_subprocess_run(cmd_list)
            self.assertIsInstance(ctx.exception, PermissionError)
            self.assertIn("Command blocked by agent guardrails", str(ctx.exception))

    def test_shell_true_injection_prohibition(self):
        """Adversarial bypass: Attempt to pass shell=True or truthy values to execute raw shell commands."""
        truthy_shell_values = [True, 1, "true", "True", [1]]

        for val in truthy_shell_values:
            with self.assertRaises(CommandExecutionBlockedError, msg=f"shell={val!r} was not blocked!") as ctx:
                safe_subprocess_run(["echo", "hello"], shell=val)
            self.assertIsInstance(ctx.exception, PermissionError)
            self.assertIn("shell=True is strictly prohibited", str(ctx.exception))

    def test_path_traversal_and_escapes_to_dangerous_binaries(self):
        """Adversarial bypass: Path traversal escapes (../../bin/rm, /bin/./rm, /usr/bin/sudo)."""
        traversal_binaries = [
            "../../../../bin/rm",
            "/bin/./rm",
            "/bin/../bin/rm",
            "/usr/bin/sudo",
            "/bin/sh",
            "/bin/bash",
            "/usr/bin/curl",
            "/usr/bin/wget",
            "/usr/bin/kill",
        ]

        for bin_path in traversal_binaries:
            # As string
            cmd_str = f"{bin_path} -rf /tmp/data"
            valid, reason = validate_command(cmd_str)
            self.assertFalse(valid, f"Expected binary path escape '{bin_path}' in string to be blocked!")
            self.assertIn("Blocked dangerous binary", reason or "")

            with self.assertRaises(CommandExecutionBlockedError):
                safe_subprocess_run(cmd_str)

            # As list
            cmd_list = [bin_path, "-rf", "/tmp/data"]
            valid_list, reason_list = validate_command(cmd_list)
            self.assertFalse(valid_list, f"Expected binary path escape '{bin_path}' in list to be blocked!")
            self.assertIn("Blocked dangerous binary", reason_list or "")

            with self.assertRaises(CommandExecutionBlockedError):
                safe_subprocess_run(cmd_list)

    def test_wrapper_binary_injection(self):
        """Adversarial bypass: Invoking dangerous binaries through wrappers (env rm, xargs sudo, etc.)."""
        wrappers = [
            ["env", "rm", "-rf", "/"],
            ["env", "/bin/rm", "-rf", "/"],
            ["xargs", "kill", "-9"],
            ["sudo", "ls"],
        ]

        for wrap in wrappers:
            valid, reason = validate_command(wrap)
            self.assertFalse(valid, f"Expected wrapper command {wrap!r} to be blocked!")
            self.assertIn("Blocked dangerous binary", reason or "")

            with self.assertRaises(CommandExecutionBlockedError):
                safe_subprocess_run(wrap)

    def test_unauthorized_exploratory_scripts_and_module_escapes(self):
        """Adversarial bypass: Attempt to run exploratory scripts or modules via python -m or python -c."""
        exploratory_vectors = [
            "python main_backtest.py",
            ["python", "main_backtest.py"],
            ["python3", "./main_backtest.py"],
            ["python", "scripts/probe_candidate_frequency.py"],
            ["python", "-m", "main_backtest"],
            ["python3", "-m", "scripts.probe_candidate_frequency"],
            ["python", "-c", "import main_backtest; main_backtest.main()"],
            ["python", "-c", "import probe_candidate_frequency; probe_candidate_frequency.run()"],
        ]

        for vec in exploratory_vectors:
            valid, reason = validate_command(vec)
            self.assertFalse(valid, f"Expected exploratory command {vec!r} to be blocked!")
            self.assertTrue(
                "Blocked unauthorized agent exploratory" in (reason or ""),
                f"Unexpected reason: {reason}",
            )

            with self.assertRaises(CommandExecutionBlockedError):
                safe_subprocess_run(vec)

    def test_command_execution_blocked_error_exception_hierarchy(self):
        """Hierarchy: CommandExecutionBlockedError must be a subclass of PermissionError."""
        self.assertTrue(issubclass(CommandExecutionBlockedError, PermissionError))
        err = CommandExecutionBlockedError("test blocked")
        self.assertIsInstance(err, PermissionError)
        self.assertIsInstance(err, CommandExecutionBlockedError)


if __name__ == "__main__":
    unittest.main()
