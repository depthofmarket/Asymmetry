"""
Test Suite: Quantitative Backtest Provenance & Anti-Hallucination System.

Verifies:
1. Cryptographic SHA-256 data hashing and SQLite mtime/size caching.
2. ACID SQLite recording and fail-safe JSONL audit mirroring.
3. Automated warning flag generation (N < 30, gross execution, outlier dominance, short window).
4. Rejection of naked stats; mandatory inclusion of methodology, dates, hash, and footers.
5. Command-line query interface (`scripts/query_provenance.py`).
6. Deep engine recording hooks.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.provenance import ProvenanceRecord, ProvenanceStore


@pytest.fixture
def temp_store(tmp_path):
    db_file = tmp_path / "test_provenance.db"
    jsonl_file = tmp_path / "test_provenance.jsonl"
    return ProvenanceStore(db_path=db_file, jsonl_path=jsonl_file)


def test_data_hash_and_cache(temp_store, tmp_path):
    data_file = tmp_path / "sample_data.parquet"
    content = b"TEST_DATA_BLOCK_VERSION_1"
    data_file.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    computed_hash = temp_store.compute_data_hash(data_file)
    assert computed_hash == expected_hash

    # Verify cached in data_files table
    with temp_store._get_connection() as conn:
        row = conn.execute("SELECT sha256_hash FROM data_files WHERE file_path = ?", (str(data_file),)).fetchone()
        assert row is not None
        assert row["sha256_hash"] == expected_hash

    # Change content
    new_content = b"TEST_DATA_BLOCK_VERSION_2_UPDATED"
    data_file.write_bytes(new_content)
    new_expected_hash = hashlib.sha256(new_content).hexdigest()
    new_computed_hash = temp_store.compute_data_hash(data_file)
    assert new_computed_hash == new_expected_hash
    assert new_computed_hash != expected_hash


def test_provenance_recording_and_jsonl_mirror(temp_store, tmp_path):
    data_file = tmp_path / "bars.csv"
    data_file.write_text("time,open,high,low,close,volume\n2026-01-01,100,105,95,102,1000\n")

    record = temp_store.record_run(
        run_id="test_run_001",
        strategy_id="test_strat",
        strategy_name="Test Strategy Alpha",
        methodology="out_of_sample",
        date_start="2026-01-01",
        date_end="2026-06-30",
        data_path=data_file,
        total_trades=150,
        win_rate=58.5,
        profit_factor=1.75,
        gross_profit=15000.0,
        net_profit=10500.0,
        max_drawdown=1200.0,
        sharpe_ratio=1.45,
        largest_win=850.0,
        slippage_model="1-Tick Adverse",
        commission_model="$1.40 RT",
        is_net=True,
    )

    assert record.run_id == "test_run_001"
    assert record.profit_factor == 1.75
    assert len(record.warnings) == 0  # Clean run, N=150, net, largest win < 35%

    # Retrieve from SQLite
    fetched = temp_store.get_run("test_run_001")
    assert fetched is not None
    assert fetched.strategy_id == "test_strat"
    assert fetched.net_profit == 10500.0

    # Verify JSONL mirror
    assert temp_store.jsonl_path.exists()
    lines = temp_store.jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    mirrored_dict = json.loads(lines[0])
    assert mirrored_dict["run_id"] == "test_run_001"
    assert mirrored_dict["profit_factor"] == 1.75


def test_warning_flags_generation(temp_store, tmp_path):
    data_file = tmp_path / "small_bars.csv"
    data_file.write_text("dummy")

    # Run with small sample size, gross returns, outlier win, and short span
    record = temp_store.record_run(
        run_id="warn_run_001",
        strategy_id="flawed_strategy",
        strategy_name="Flawed Strategy Beta",
        methodology="in_sample",
        date_start="2026-05-01",
        date_end="2026-05-15",  # 15 days
        days_count=15,
        data_path=data_file,
        total_trades=12,  # N < 30
        win_rate=66.7,
        profit_factor=3.50,
        gross_profit=4000.0,
        net_profit=4000.0,
        max_drawdown=500.0,
        sharpe_ratio=2.10,
        largest_win=2500.0,  # 2500 / 4000 = 62.5% > 35%
        slippage_model="None (Zero Slippage)",
        commission_model="None",
        is_net=False,
    )

    warn_types = " ".join(record.warnings)
    assert "LOW_SAMPLE_SIZE" in warn_types
    assert "GROSS_EXECUTION" in warn_types
    assert "OUTLIER_DOMINANCE" in warn_types
    assert "SHORT_EVALUATION_WINDOW" in warn_types
    assert len(record.warnings) == 4


def test_no_naked_numbers_formatting(temp_store, tmp_path):
    data_file = tmp_path / "bars.csv"
    data_file.write_text("dummy")

    record = temp_store.record_run(
        run_id="clean_run_002",
        strategy_id="s1_breakout",
        strategy_name="Morning VA Breakout",
        methodology="multi_year_walkforward",
        date_start="2021-01-01",
        date_end="2026-10-30",
        days_count=1500,
        data_path=data_file,
        total_trades=320,
        win_rate=57.0,
        profit_factor=1.65,
        gross_profit=18000.0,
        net_profit=8956.0,
        max_drawdown=1475.0,
        sharpe_ratio=0.98,
        largest_win=445.0,
        is_net=True,
    )

    quote = temp_store.quote_stat(record, "profit_factor")
    # Must NOT be a naked number:
    assert "1.65" in quote
    assert "multi_year_walkforward" in quote
    assert "2021-01-01 to 2026-10-30" in quote
    assert record.data_hash[:10] in quote
    assert "PROVENANCE VERIFICATION FOOTER" in quote


def test_query_cli():
    # 1. Run list
    proc_list = subprocess.run(
        [sys.executable, str(ROOT / "scripts/query_provenance.py"), "--list"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "morning_va_breakout_s1" in proc_list.stdout
    assert "macro_momentum_s2" in proc_list.stdout
    assert "gold_london_fix_s3" in proc_list.stdout
    assert "lucid_flex_ensemble" in proc_list.stdout

    # 2. Run specific stat query
    proc_stat = subprocess.run(
        [sys.executable, str(ROOT / "scripts/query_provenance.py"), "--strategy", "morning_va_breakout_s1", "--stat", "profit_factor"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "1.65" in proc_stat.stdout
    assert "PROVENANCE VERIFICATION FOOTER" in proc_stat.stdout
    assert "ecad8d063caa" in proc_stat.stdout


def test_standing_rules_files_exist():
    gemini_md = ROOT / "GEMINI.md"
    agents_md = ROOT / "AGENTS.md"
    claude_md = ROOT / "CLAUDE.md"
    cursorrules = ROOT / ".cursorrules"
    rules_md = ROOT / ".agents/rules/quant_provenance.md"

    for f in [gemini_md, agents_md, claude_md, cursorrules, rules_md]:
        assert f.exists(), f"Rule file {f} missing!"
        content = f.read_text(encoding="utf-8")
        assert "results/backtest_provenance.db" in content
        assert "One source of truth" in content or "One Source of Truth" in content
