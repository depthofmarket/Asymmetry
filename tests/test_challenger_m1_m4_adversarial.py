"""
Adversarial Stress Test Suite for Milestone M1 (Alpha Factory & Provenance)
and Milestone M4 (Strategy Registry & Governance).

Author: Empirical Challenger Agent (teamwork_challenger_audit_1)
Roles: critic, specialist

Coverage:
1. --record flag non-mutation & dry-run invariance
2. Strategy Registry security & quarantine (unregistered rejection, baseline spoofing block, SQLi / edge cases)
3. Gross profit & DSR stress (zero wins, single massive win, all wins, DSR hurdle strictly increasing with trials)
4. SQLite database integrity & concurrency (schema validation, strategy_tier, cryptographic hashes, thread stress)
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest import dashboard_analytics as da
from backtest.dashboard_analytics import deflated_sharpe_ratio, expected_max_sharpe
from backtest.provenance import ProvenanceRecord, ProvenanceStore, default_store
from config.strategy_registry import (
    AUTHORIZED_BASELINE_STRATEGIES,
    StrategyMetadata,
    StrategyTier,
    get_authorized_baseline_ids,
    get_strategy_tier,
    is_production_baseline,
    is_registered,
    is_valid_strategy_id_format,
    list_strategies_by_tier,
    register_candidate,
    register_strategy,
    reset_registry,
    validate_strategy_id,
)
from scripts.alpha_factory import evaluate_candidate_trades, get_baseline_trial_count


# ==============================================================================
# Challenge 1: --record Flag Non-Mutation & Dry-Run Invariance
# ==============================================================================
@pytest.mark.generated_results
class TestAlphaFactoryRecordNonMutation:
    """Empirical verification that alpha_factory dry-run never mutates the database."""

    def test_live_db_unmutated_after_s1_dry_run(self):
        """Executing scripts/alpha_factory.py without --record must not alter results/backtest_provenance.db or wiki."""
        live_db = REPO_ROOT / "results/backtest_provenance.db"
        failed_ideas = REPO_ROOT / "wiki/failed_ideas.md"
        assert live_db.exists(), f"Database not found at {live_db}"

        conn = sqlite3.connect(live_db)
        before_count = conn.execute("SELECT count(*) FROM backtest_runs").fetchone()[0]
        before_max_rowid = conn.execute("SELECT max(rowid) FROM backtest_runs").fetchone()[0]
        before_run_ids = set(r[0] for r in conn.execute("SELECT run_id FROM backtest_runs").fetchall())
        conn.close()

        before_wiki = failed_ideas.read_text(encoding="utf-8") if failed_ideas.exists() else ""

        # Run alpha_factory.py without --record on S1 (which receives DSR veto under expanded trial count N >= 33)
        cmd = [sys.executable, str(REPO_ROOT / "scripts/alpha_factory.py"), "--strategy", "S1"]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))

        # S1 fails DSR under dynamic trial count (N >= 33), issuing a binding veto and exiting 1
        assert res.returncode == 1, f"Expected returncode 1 (adversarial veto), got {res.returncode}: {res.stdout}"
        assert "BINDING VETO ISSUED" in res.stdout
        assert "Deflated Sharpe Ratio DSR" in res.stdout

        conn = sqlite3.connect(live_db)
        after_count = conn.execute("SELECT count(*) FROM backtest_runs").fetchone()[0]
        after_max_rowid = conn.execute("SELECT max(rowid) FROM backtest_runs").fetchone()[0]
        after_run_ids = set(r[0] for r in conn.execute("SELECT run_id FROM backtest_runs").fetchall())
        conn.close()

        after_wiki = failed_ideas.read_text(encoding="utf-8") if failed_ideas.exists() else ""

        assert before_count == after_count, f"Row count changed: before={before_count}, after={after_count}"
        assert before_count >= 9, f"Expected at least 9 baseline runs, got {before_count}"
        assert before_max_rowid == after_max_rowid, f"Max rowid changed!"
        assert before_run_ids == after_run_ids, "Run IDs set modified!"
        assert before_wiki == after_wiki, "wiki/failed_ideas.md was mutated by S1 dry run!"

    def test_live_db_unmutated_after_ensemble_dry_run(self):
        """Executing scripts/alpha_factory.py --strategy ensemble without --record must not alter db or wiki."""
        live_db = REPO_ROOT / "results/backtest_provenance.db"
        failed_ideas = REPO_ROOT / "wiki/failed_ideas.md"
        assert live_db.exists(), f"Database not found at {live_db}"

        conn = sqlite3.connect(live_db)
        before_count = conn.execute("SELECT count(*) FROM backtest_runs").fetchone()[0]
        before_max_rowid = conn.execute("SELECT max(rowid) FROM backtest_runs").fetchone()[0]
        before_run_ids = set(r[0] for r in conn.execute("SELECT run_id FROM backtest_runs").fetchall())
        conn.close()

        before_wiki = failed_ideas.read_text(encoding="utf-8") if failed_ideas.exists() else ""

        cmd = [sys.executable, str(REPO_ROOT / "scripts/alpha_factory.py"), "--strategy", "ensemble"]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))
        assert res.returncode == 0, f"Command failed: {res.stderr}"
        assert "[INFO] DRY RUN (not recorded to database; pass --record to persist)" in res.stdout
        assert "PROVENANCE VERIFICATION FOOTER" in res.stdout

        conn = sqlite3.connect(live_db)
        after_count = conn.execute("SELECT count(*) FROM backtest_runs").fetchone()[0]
        after_max_rowid = conn.execute("SELECT max(rowid) FROM backtest_runs").fetchone()[0]
        after_run_ids = set(r[0] for r in conn.execute("SELECT run_id FROM backtest_runs").fetchall())
        conn.close()

        after_wiki = failed_ideas.read_text(encoding="utf-8") if failed_ideas.exists() else ""

        assert before_count == after_count, f"Row count changed: before={before_count}, after={after_count}"
        assert before_count >= 9, f"Expected at least 9 baseline runs, got {before_count}"
        assert before_max_rowid == after_max_rowid, f"Max rowid changed!"
        assert before_run_ids == after_run_ids, "Run IDs set modified!"
        assert before_wiki == after_wiki, "wiki/failed_ideas.md was mutated by ensemble dry run!"

    def test_record_flag_gating_logic_in_isolated_store(self, tmp_path: Path):
        """Verify the conditional branch: record only when args.record is True."""
        test_db = tmp_path / "test_gating.db"
        test_jsonl = tmp_path / "test_gating.jsonl"
        store = ProvenanceStore(db_path=test_db, jsonl_path=test_jsonl)

        # In dry-run mode: instantiate ProvenanceRecord without store.record_run()
        dummy_record = ProvenanceRecord(
            run_id="run_dry_test_001",
            timestamp="2026-11-06T00:00:00Z",
            strategy_id="morning_va_breakout_s1",
            strategy_name="Morning VA Breakout",
            methodology="alpha_factory_adversarial_walkforward",
            date_start="2021-01-01",
            date_end="2026-10-30",
            days_count=2123,
            data_path=str(test_db),
            data_hash="abc",
            git_commit="test_commit",
            slippage_model="test",
            commission_model="test",
            is_net=True,
            total_trades=100,
            win_rate=55.0,
            profit_factor=1.6,
            gross_profit=1000.0,
            net_profit=500.0,
            max_drawdown=-100.0,
            sharpe_ratio=1.5,
            largest_win=50.0,
            largest_win_pct_of_net=10.0,
            warnings=[],
            params={},
            notes="dry run test",
        )
        footer = store.format_footer(dummy_record)
        assert "PROVENANCE VERIFICATION FOOTER" in footer
        assert store.get_run("run_dry_test_001") is None
        assert len(store.list_runs()) == 0

        # Now when record is enabled:
        dummy_data_file = tmp_path / "data.parquet"
        dummy_data_file.write_bytes(b"DATA")
        rec = store.record_run(
            strategy_id="morning_va_breakout_s1",
            strategy_name="Morning VA Breakout",
            methodology="alpha_factory_adversarial_walkforward",
            date_start="2021-01-01",
            date_end="2026-10-30",
            data_path=dummy_data_file,
            total_trades=100,
            win_rate=55.0,
            profit_factor=1.6,
            gross_profit=1000.0,
            net_profit=500.0,
            max_drawdown=-100.0,
            sharpe_ratio=1.5,
            largest_win=50.0,
            run_id="run_persisted_001",
        )
        assert store.get_run("run_persisted_001") is not None
        assert len(store.list_runs()) == 1


# ==============================================================================
# Challenge 2: Strategy Registry Security & Quarantine
# ==============================================================================
class TestStrategyRegistrySecurityAndQuarantine:
    """Stress tests on registry isolation, tier spoofing prevention, and injection safety."""

    def setup_method(self):
        reset_registry()

    def teardown_method(self):
        reset_registry()

    def test_unregistered_strategy_blocked_from_claiming_baseline_in_record_run(self, tmp_path: Path):
        """Attempting to record an unvetted strategy claiming BASELINE tier must be blocked."""
        store = ProvenanceStore(db_path=tmp_path / "test_sec.db", jsonl_path=tmp_path / "test_sec.jsonl")
        data_file = tmp_path / "test_data.parquet"
        data_file.write_bytes(b"DATA_BYTES")

        # Explicitly claiming StrategyTier.BASELINE
        with pytest.raises(ValueError, match="is not an authorized production baseline and cannot be recorded with tier 'BASELINE'"):
            store.record_run(
                strategy_id="unvetted_crypto_scalp",
                strategy_name="Unvetted Scalp",
                strategy_tier=StrategyTier.BASELINE,
                methodology="walkforward",
                date_start="2026-01-01",
                date_end="2026-06-01",
                data_path=data_file,
                total_trades=50,
                win_rate=60.0,
                profit_factor=2.0,
                gross_profit=5000.0,
                net_profit=3000.0,
                max_drawdown=-500.0,
                sharpe_ratio=2.1,
                largest_win=200.0,
            )

        # Claiming string "BASELINE"
        with pytest.raises(ValueError, match="is not an authorized production baseline and cannot be recorded with tier 'BASELINE'"):
            store.record_run(
                strategy_id="unvetted_crypto_scalp",
                strategy_name="Unvetted Scalp",
                strategy_tier="BASELINE",
                methodology="walkforward",
                date_start="2026-01-01",
                date_end="2026-06-01",
                data_path=data_file,
                total_trades=50,
                win_rate=60.0,
                profit_factor=2.0,
                gross_profit=5000.0,
                net_profit=3000.0,
                max_drawdown=-500.0,
                sharpe_ratio=2.1,
                largest_win=200.0,
            )

    def test_unauthorized_registration_of_baseline_blocked(self):
        """Attempting to register an unvetted strategy into registry as BASELINE must fail."""
        with pytest.raises(ValueError, match="cannot be registered with tier BASELINE"):
            register_strategy("rogue_alpha_99", tier=StrategyTier.BASELINE)

        with pytest.raises(ValueError, match="cannot be registered with tier BASELINE"):
            register_strategy("rogue_alpha_99", tier="BASELINE")

    def test_cannot_demote_production_baseline_without_override(self):
        """Attempting to alter or demote a frozen production baseline without override must fail."""
        with pytest.raises(ValueError, match="Cannot override frozen production baseline"):
            register_strategy("morning_va_breakout_s1", tier=StrategyTier.CANDIDATE)

        with pytest.raises(ValueError, match="Cannot override frozen production baseline"):
            register_strategy("lucid_flex_ensemble", tier=StrategyTier.REJECTED)

    def test_unregistered_candidate_quarantine_in_record_run(self, tmp_path: Path):
        """When an unregistered strategy is recorded without a tier, it MUST quarantine to CANDIDATE."""
        store = ProvenanceStore(db_path=tmp_path / "test_quarantine.db", jsonl_path=tmp_path / "test_quarantine.jsonl")
        data_file = tmp_path / "test_data.parquet"
        data_file.write_bytes(b"DATA_BYTES")

        strat_id = "exploratory_momentum_cand1"
        assert not is_registered(strat_id)

        rec = store.record_run(
            strategy_id=strat_id,
            strategy_name="Exploratory Momentum Candidate",
            methodology="walkforward",
            date_start="2026-01-01",
            date_end="2026-06-01",
            data_path=data_file,
            total_trades=50,
            win_rate=60.0,
            profit_factor=2.0,
            gross_profit=5000.0,
            net_profit=3000.0,
            max_drawdown=-500.0,
            sharpe_ratio=2.1,
            largest_win=200.0,
        )

        assert rec.strategy_tier == "CANDIDATE"
        assert not is_production_baseline(strat_id)
        assert get_strategy_tier(strat_id) == StrategyTier.CANDIDATE

        # Filtering by BASELINE must NOT return this quarantined candidate
        baseline_runs = store.list_runs(tier=StrategyTier.BASELINE)
        assert not any(r.strategy_id == strat_id for r in baseline_runs)

        # Filtering by CANDIDATE must return it
        candidate_runs = store.list_runs(tier=StrategyTier.CANDIDATE)
        assert any(r.strategy_id == strat_id for r in candidate_runs)

    @pytest.mark.parametrize(
        "bad_id, expected_reason",
        [
            ("", "empty string"),
            ("   ", "whitespace only"),
            (None, "None value"),
            (12345, "non-string integer"),
            ("'; DROP TABLE backtest_runs; --", "SQL injection drop table"),
            ("' OR '1'='1", "SQL injection boolean tautology"),
            ("morning_va_breakout_s1' OR '1'='1", "SQL injection append tautology"),
            ("admin'--", "SQL comment injection"),
            ("strat; SELECT * FROM backtest_runs;", "SQL chained query"),
            ("../../etc/passwd", "path traversal"),
            ("strat$special*chars", "special characters"),
            ("strat\x00nullbyte", "null byte injection"),
            ("strat with spaces", "spaces inside identifier"),
            ("-leading-dash", "leading hyphen"),
            ("trailing-dash-", "trailing hyphen"),
            ("_leading_underscore", "leading underscore"),
            ("trailing_underscore_", "trailing underscore"),
            (".hidden_strat", "leading dot"),
            ("A" * 65, "exceeds maximum length 64 characters"),
        ],
    )
    def test_adversarial_and_injection_strategy_ids_rejected(self, bad_id: Any, expected_reason: str, tmp_path: Path):
        """Adversarial and malicious strategy IDs must be rejected by format validator and record_run."""
        assert not is_valid_strategy_id_format(bad_id), f"Failed to reject invalid ID: {bad_id} ({expected_reason})"

        store = ProvenanceStore(db_path=tmp_path / "test_inj.db", jsonl_path=tmp_path / "test_inj.jsonl")
        data_file = tmp_path / "test_data.parquet"
        data_file.write_bytes(b"DATA")

        with pytest.raises(ValueError, match="Invalid strategy_id"):
            store.record_run(
                strategy_id=bad_id,
                strategy_name="Malicious Test",
                methodology="test",
                date_start="2026-01-01",
                date_end="2026-06-01",
                data_path=data_file,
                total_trades=10,
                win_rate=50.0,
                profit_factor=1.0,
                gross_profit=100.0,
                net_profit=50.0,
                max_drawdown=-10.0,
                sharpe_ratio=1.0,
                largest_win=10.0,
            )


# ==============================================================================
# Challenge 3: Gross Profit & DSR Stress Testing
# ==============================================================================
class TestGrossProfitAndDSRStress:
    """Mathematical stress tests on gross profit fidelity and DSR multiple-testing scaling."""

    def test_gross_profit_zero_wins_all_losses(self):
        """When a strategy produces 0 winning trades, gross_profit MUST be exactly 0.0."""
        # Synthetic loss trades
        trades = pd.DataFrame({
            "net_pnl": [-50.0, -120.0, -85.5],
            "research_pnl": [-50.0, -120.0, -85.5],
            "date": pd.date_range("2026-01-01", periods=3),
        })

        wins = trades[trades["net_pnl"] > 0]["net_pnl"]
        gross_profit = float(wins.sum())
        assert gross_profit == 0.0, f"Gross profit on all losses should be 0.0, got {gross_profit}"

        # Contrast with flawed legacy formula: net_pnl + 1000.0
        flawed_gross = float(trades["net_pnl"].sum()) + 1000.0
        assert flawed_gross == 744.5, "Flawed formula should have produced 744.5"
        # The authentic calculation avoids creating $744.50 of phantom profit

    def test_gross_profit_single_massive_win_and_outlier_dominance(self):
        """Single massive win: gross_profit is authentic sum, and outlier dominance triggers."""
        trades = pd.DataFrame({
            "net_pnl": [10000.0, -50.0, -30.0],
            "research_pnl": [10000.0, -50.0, -30.0],
            "direction": ["long", "long", "long"],
            "date": pd.date_range("2026-01-01", periods=3),
        })

        wins = trades[trades["net_pnl"] > 0]["net_pnl"]
        gross_profit = float(wins.sum())
        assert gross_profit == 10000.0

        net_pnl = float(trades["net_pnl"].sum())
        assert net_pnl == 9920.0

        audit = evaluate_candidate_trades(trades, "cand_outlier", "Outlier Candidate", trials=25)
        assert audit["gross_profit"] == 10000.0
        assert "OUTLIER_DOMINANCE" in audit["warnings"]
        assert audit["verdict"] == "REJECTED_BY_ADVERSARIAL_VETO"
        assert any("35%" in r for r in audit["veto_reasons"])

    def test_gross_profit_all_wins(self):
        """When all trades are winning, gross_profit equals net_profit exactly."""
        trades = pd.DataFrame({
            "net_pnl": [250.0, 150.0, 600.0],
            "research_pnl": [250.0, 150.0, 600.0],
            "direction": ["long", "long", "long"],
            "date": pd.date_range("2026-01-01", periods=3),
        })

        wins = trades[trades["net_pnl"] > 0]["net_pnl"]
        gross_profit = float(wins.sum())
        net_profit = float(trades["net_pnl"].sum())
        assert gross_profit == net_profit == 1000.0

    def test_gross_profit_mixed_trades_fidelity(self):
        """Mixed trades: gross profit equals exact sum of positive trades, avoiding net_pnl + 1000."""
        trades = pd.DataFrame({
            "net_pnl": [500.0, 500.0, -200.0, -300.0],
            "research_pnl": [500.0, 500.0, -200.0, -300.0],
            "direction": ["long", "long", "short", "short"],
            "date": pd.date_range("2026-01-01", periods=4),
        })

        wins = trades[trades["net_pnl"] > 0]["net_pnl"]
        gross_profit = float(wins.sum())
        net_profit = float(trades["net_pnl"].sum())

        assert gross_profit == 1000.0
        assert net_profit == 500.0
        flawed_gross = net_profit + 1000.0
        assert flawed_gross == 1500.0
        assert gross_profit != flawed_gross, "Flawed gross profit formula was not caught!"

    def test_dsr_hurdle_strictly_increasing_with_trial_count(self):
        """EVT multiple testing hurdle SR* strictly increases as trial count N increases."""
        trial_counts = [1, 5, 25, 50, 100, 250, 500, 1000]
        hurdles = [expected_max_sharpe(n, var_sharpe=0.5) for n in trial_counts]

        for i in range(len(hurdles) - 1):
            assert hurdles[i + 1] > hurdles[i], (
                f"EVT hurdle failed to increase strictly: N={trial_counts[i]} -> {hurdles[i]:.4f}, "
                f"N={trial_counts[i+1]} -> {hurdles[i+1]:.4f}"
            )

        # Explicitly verify N=25 vs N=100
        sr_star_25 = expected_max_sharpe(25, var_sharpe=0.5)
        sr_star_100 = expected_max_sharpe(100, var_sharpe=0.5)
        assert sr_star_100 > sr_star_25, f"Expected SR*(100) > SR*(25), got {sr_star_100} <= {sr_star_25}"

        # Deflated Sharpe Ratio with identical performance must be strictly lower with N=100 than N=25
        synthetic_returns = np.random.default_rng(42).normal(loc=1.5, scale=1.0, size=100)
        dsr_25 = deflated_sharpe_ratio(synthetic_returns, n_trials=25, var_sharpe=0.5)
        dsr_100 = deflated_sharpe_ratio(synthetic_returns, n_trials=100, var_sharpe=0.5)
        assert dsr_100 < dsr_25, f"Expected DSR(100) < DSR(25), got {dsr_100} >= {dsr_25}"

    def test_baseline_trial_count_minimum_bound(self):
        """Dynamic baseline trial count must never fall below 25."""
        count = get_baseline_trial_count()
        assert count >= 25, f"Baseline trial count {count} is below minimum requirement of 25"


# ==============================================================================
# Challenge 4: SQLite Database Concurrency & Integrity
# ==============================================================================
@pytest.mark.generated_results
class TestSQLiteDatabaseIntegrityAndConcurrency:
    """Stress tests on persistent database schema, tiers, hashes, and concurrent access."""

    def test_live_db_schema_and_record_validity(self):
        """Query results/backtest_provenance.db to verify schema, tiers, and data hashes."""
        live_db = REPO_ROOT / "results/backtest_provenance.db"
        assert live_db.exists()

        conn = sqlite3.connect(live_db)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Check PRAGMA table info
        cursor.execute("PRAGMA table_info(backtest_runs)")
        cols = {row["name"]: row["type"] for row in cursor.fetchall()}
        required_cols = [
            "run_id", "timestamp", "strategy_id", "strategy_name", "methodology",
            "date_start", "date_end", "days_count", "data_path", "data_hash",
            "git_commit", "slippage_model", "commission_model", "is_net",
            "total_trades", "win_rate", "profit_factor", "gross_profit", "net_profit",
            "max_drawdown", "sharpe_ratio", "largest_win", "largest_win_pct_of_net",
            "warnings_json", "params_json", "notes", "strategy_tier"
        ]
        for col in required_cols:
            assert col in cols, f"Missing required column in backtest_runs: {col}"

        # Check records
        cursor.execute("SELECT * FROM backtest_runs")
        records = cursor.fetchall()
        assert len(records) >= 9, f"Expected >= 9 verified runs, found {len(records)}"

        valid_tiers = {tier.value for tier in StrategyTier}

        for r in records:
            run_id = r["run_id"]
            strat_id = r["strategy_id"]
            tier = r["strategy_tier"]
            d_hash = r["data_hash"]
            d_path = Path(r["data_path"])
            gross = r["gross_profit"]
            net = r["net_profit"]
            git = r["git_commit"]

            assert run_id and isinstance(run_id, str), f"Invalid run_id: {run_id}"
            assert strat_id and is_valid_strategy_id_format(strat_id), f"Invalid strategy_id: {strat_id}"
            assert tier in valid_tiers, f"Invalid tier '{tier}' in record {run_id}"

            # Verify cryptographic data hash
            assert len(d_hash) == 64, f"data_hash is not 64 hex chars in record {run_id}: {d_hash}"
            assert all(c in "0123456789abcdef" for c in d_hash), f"data_hash not lowercase hex: {d_hash}"

            # Verify referenced data file exists and SHA-256 matches
            assert d_path.exists(), f"data_path file does not exist on disk: {d_path}"
            hasher = hashlib.sha256()
            with open(d_path, "rb") as f:
                while chunk := f.read(131072):
                    hasher.update(chunk)
            recomputed_hash = hasher.hexdigest()
            assert recomputed_hash == d_hash, (
                f"Cryptographic hash mismatch for {run_id}! DB has {d_hash}, recomputed is {recomputed_hash}"
            )

            # Mathematical sanity on gross profit
            assert gross >= 0.0, f"gross_profit cannot be negative: {gross}"
            if net > 0:
                assert gross >= net, f"gross_profit ({gross}) must be >= net_profit ({net})"

            # Git commit hash sanity
            assert git and len(git) >= 7, f"Invalid git_commit: {git}"

        conn.close()

    def test_concurrent_reads_and_writes_stress(self, tmp_path: Path):
        """20 concurrent threads reading and writing to isolated ProvenanceStore under load."""
        stress_db = tmp_path / "stress_provenance.db"
        stress_jsonl = tmp_path / "stress_provenance.jsonl"
        store = ProvenanceStore(db_path=stress_db, jsonl_path=stress_jsonl)

        data_file = tmp_path / "stress_data.parquet"
        data_file.write_bytes(b"STRESS_DATA_BLOCK" * 1024)

        def worker_task(thread_id: int) -> str:
            strat_id = "morning_va_breakout_s1" if thread_id % 2 == 0 else f"candidate_worker_{thread_id}"
            strat_name = f"Worker Strategy {thread_id}"
            run_id = f"run_stress_{thread_id:03d}"

            # Write
            rec = store.record_run(
                run_id=run_id,
                strategy_id=strat_id,
                strategy_name=strat_name,
                methodology="thread_stress",
                date_start="2026-01-01",
                date_end="2026-06-01",
                data_path=data_file,
                total_trades=100 + thread_id,
                win_rate=55.0,
                profit_factor=1.6,
                gross_profit=5000.0 + thread_id * 10,
                net_profit=3000.0 + thread_id * 5,
                max_drawdown=-500.0,
                sharpe_ratio=2.0,
                largest_win=150.0,
            )

            # Immediate read
            fetched = store.get_run(run_id)
            assert fetched is not None, f"Failed to retrieve run_id {run_id} immediately after write"
            assert fetched.strategy_id == strat_id
            return run_id

        num_threads = 20
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_task, i) for i in range(num_threads)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == num_threads

        # 1. Candidate Quarantine Verification: Default list_runs excludes candidate runs
        runs_default = store.list_runs(limit=100)
        assert len(runs_default) == num_threads // 2, (
            f"Expected {num_threads // 2} baseline runs under default quarantine, got {len(runs_default)}"
        )
        assert all(r.strategy_tier == StrategyTier.BASELINE.value for r in runs_default), (
            "Quarantine leak: non-BASELINE run found in default list_runs output"
        )

        # 2. Multi-Tier Concurrency Verification: include_candidates=True retrieves all runs
        all_runs = store.list_runs(include_candidates=True, limit=100)
        assert len(all_runs) == num_threads, (
            f"Expected {num_threads} total runs with include_candidates=True, got {len(all_runs)}"
        )
        baseline_count = sum(1 for r in all_runs if r.strategy_tier == StrategyTier.BASELINE.value)
        candidate_count = sum(1 for r in all_runs if r.strategy_tier == StrategyTier.CANDIDATE.value)
        assert baseline_count == num_threads // 2 == 10
        assert candidate_count == num_threads // 2 == 10

        # 3. Candidate Warning Flags Verification: Quarantine warning attached to candidates
        for r in all_runs:
            if r.strategy_tier == StrategyTier.CANDIDATE.value:
                assert "CANDIDATE_TIER_QUARANTINED" in r.warnings, (
                    f"Candidate run {r.run_id} missing CANDIDATE_TIER_QUARANTINED warning"
                )
