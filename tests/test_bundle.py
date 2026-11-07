"""
Unit test suite for Open Backtest Format (.obtf) bundle engine.
Verifies portable bundle serialization, compression, extraction, and schema parity.
"""

import json
import tempfile
import zipfile
from pathlib import Path
import pandas as pd
import pytest

from backtest.bundle import BacktestBundle


@pytest.fixture
def sample_trade_data():
    return pd.DataFrame({
        "trade_id": [1, 2, 3, 4, 5],
        "date": ["2024-01-10", "2024-01-11", "2024-01-12", "2024-01-15", "2024-01-16"],
        "symbol": ["MNQ", "MNQ", "MNQ", "MNQ", "MNQ"],
        "side": ["LONG", "SHORT", "LONG", "LONG", "SHORT"],
        "entry_price": [18000.0, 18050.0, 18020.0, 18100.0, 18080.0],
        "exit_price": [18020.0, 18010.0, 18010.0, 18140.0, 18100.0],
        "net_pnl": [40.0, 80.0, -20.0, 80.0, -40.0],
        "return_pct": [0.0022, 0.0044, -0.0011, 0.0044, -0.0022],
    })


def test_bundle_creation_and_save(sample_trade_data):
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "test_run.obtf"
        bundle = BacktestBundle.create(
            run_id="test_run_001",
            strategy_id="test_strategy",
            strategy_name="Test Alpha Strategy",
            trades_df=sample_trade_data,
            strategy_tier="CANDIDATE",
            methodology="walkforward",
            date_start="2024-01-10",
            date_end="2024-01-16",
            data_hash="abc123hash",
            audit_log=[{"event": "start", "time": "2024-01-10T09:30:00"}],
        )

        saved = bundle.save(bundle_path)
        assert saved.exists()
        assert saved.name == "test_run.obtf"

        # Verify ZIP contents
        with zipfile.ZipFile(saved, "r") as z:
            namelist = z.namelist()
            assert "manifest.json" in namelist
            assert "trades.parquet" in namelist
            assert "equity.parquet" in namelist
            assert "audit_log.json" in namelist

            # Verify manifest schema
            manifest = json.loads(z.read("manifest.json").decode("utf-8"))
            assert manifest["run_id"] == "test_run_001"
            assert manifest["strategy_id"] == "test_strategy"
            assert manifest["obtf_version"] == "1.0.0"

        # Test sub-millisecond manifest reader without decoding parquet
        quick_manifest = BacktestBundle.read_manifest(bundle_path)
        assert quick_manifest["run_id"] == "test_run_001"
        assert quick_manifest["metrics"]["net_pnl"] == 140.0


def test_bundle_load_and_parity(sample_trade_data):
    with tempfile.TemporaryDirectory() as tmpdir:
        bundle_path = Path(tmpdir) / "test_run.obtf"
        orig_bundle = BacktestBundle.create(
            run_id="test_run_002",
            strategy_id="test_strategy_2",
            strategy_name="Test Parity Strategy",
            trades_df=sample_trade_data,
            strategy_tier="BASELINE",
            methodology="multi_year_walkforward",
            date_start="2024-01-10",
            date_end="2024-01-16",
            data_hash="fedcba9876543210",
            audit_log=[{"event": "fill", "trade_id": 1}],
        )
        orig_bundle.save(bundle_path)

        # Load back
        loaded = BacktestBundle.load(bundle_path)
        assert loaded.manifest["run_id"] == "test_run_002"
        assert loaded.manifest["strategy_id"] == "test_strategy_2"
        assert loaded.manifest["strategy_tier"] == "BASELINE"
        assert len(loaded.trades) == len(sample_trade_data)
        assert len(loaded.equity) > 0
        assert loaded.audit_log == [{"event": "fill", "trade_id": 1}]

        # Check summary
        summary = loaded.get_summary()
        assert summary["run_id"] == "test_run_002"
        assert summary["strategy_id"] == "test_strategy_2"
        assert summary["trades_count"] == 5
        assert "core_metrics" in summary
        assert "institutional_risk" in summary
        assert summary["core_metrics"]["net_pnl"] == 140.0


def test_bundle_load_invalid_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        non_existent = Path(tmpdir) / "does_not_exist.obtf"
        with pytest.raises(FileNotFoundError):
            BacktestBundle.load(non_existent)

        with pytest.raises(FileNotFoundError):
            BacktestBundle.read_manifest(non_existent)

        # Corrupted non-zip file
        bad_file = Path(tmpdir) / "corrupt.obtf"
        bad_file.write_text("not a zip file content")
        with pytest.raises(zipfile.BadZipFile):
            BacktestBundle.load(bad_file)
