import subprocess
import unittest
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from backtest.gold_contract_value import confirmed_point_value, contract_root, gross_pnl
from backtest.provenance import CHART_TRACKER_METHODOLOGY, ProvenanceStore
from backtest.study_chart_replay import exclusive_end, load_bars_through
from config.strategy_registry import StrategyTier

ROOT = Path(__file__).resolve().parents[1]


class TestGoldContractValue(unittest.TestCase):
    def test_roots_and_rejected_symbols(self) -> None:
        self.assertEqual(contract_root("CME:MGCH25"), "MGC")
        self.assertEqual(contract_root("NYMEX:GCZ4"), "GC")
        self.assertIsNone(contract_root("MES"))
        self.assertIsNone(contract_root("GOLD"))
        with self.assertRaises(ValueError):
            confirmed_point_value("MES")
        with self.assertRaises(ValueError):
            confirmed_point_value("MGC", exchange_symbol="GC")
        with self.assertRaises(ValueError):
            confirmed_point_value("MGC", sdk_point_value=1.0)

    def test_one_contract_moves_match_cme_tick_values(self) -> None:
        self.assertEqual(confirmed_point_value("MGC", sdk_point_value=10.0), 10.0)
        self.assertEqual(confirmed_point_value("GC", sdk_point_value=100.0), 100.0)
        self.assertEqual(gross_pnl(1.0, 10.0, 1, True), 10.0)
        self.assertEqual(gross_pnl(0.10, 10.0, 1, True), 1.0)
        self.assertEqual(gross_pnl(-1.0, 10.0, 1, False), 10.0)
        self.assertEqual(gross_pnl(-0.10, 10.0, 1, False), 1.0)
        self.assertEqual(gross_pnl(1.0, 100.0, 1, True), 100.0)
        self.assertEqual(gross_pnl(0.10, 100.0, 1, True), 10.0)
        self.assertEqual(gross_pnl(-1.0, 100.0, 1, False), 100.0)
        self.assertEqual(gross_pnl(-0.10, 100.0, 1, False), 10.0)

    def test_java_helper_agrees(self) -> None:
        out = Path("/tmp/asymmetry-gold-value")
        out.mkdir(parents=True, exist_ok=True)
        javac = ROOT / "tools/jdk25/Contents/Home/bin/javac"
        java = ROOT / "tools/jdk25/Contents/Home/bin/java"
        compiled = subprocess.run(
            [str(javac), "-d", str(out), str(ROOT / "src/motivewave/GoldContractValue.java"), str(ROOT / "tests/java/GoldContractValueTest.java")],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        ran = subprocess.run(
            [str(java), "-cp", str(out), "com.motivewave.platform.study.custom.GoldContractValueTest"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertIn("passed", ran.stdout)


class TestInsamplePredicate(unittest.TestCase):
    def _write(self, path: Path) -> None:
        times = pd.date_range("2023-12-30", "2025-01-02 00:05", freq="min")
        frame = pd.DataFrame({
            "time": times,
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        })
        table = pa.Table.from_pandas(frame, preserve_index=False)
        pq.write_table(table, path, row_group_size=1000)

    def test_requested_end_and_protected_cutoff(self) -> None:
        path = Path("/tmp/asymmetry-cutoff.parquet")
        self._write(path)
        loaded = load_bars_through(path, "2023-12-31")
        self.assertLess(pd.to_datetime(loaded["time"]).max(), exclusive_end("2023-12-31"))
        self.assertGreaterEqual(pd.to_datetime(loaded["time"]).max(), pd.Timestamp("2023-12-31"))
        full = load_bars_through(path, "2024-12-31")
        self.assertLess(pd.to_datetime(full["time"]).max(), pd.Timestamp("2025-01-01"))
        with self.assertRaises(ValueError):
            load_bars_through(path, "2025-01-02")

    def test_command_rejects_protected_end_before_reading(self) -> None:
        ran = subprocess.run(
            ["python", "scripts/regenerate_insample_study_trades.py", "--end", "2025-01-02"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(ran.returncode, 0)
        self.assertIn("protected", (ran.stderr + ran.stdout).lower())


class TestChartTrackerQuarantine(unittest.TestCase):
    def test_baseline_chart_rows_are_excluded_and_quarantined_without_metric_changes(self) -> None:
        store = ProvenanceStore(
            db_path=Path("/tmp/asymmetry-chart-quarantine.db"),
            jsonl_path=Path("/tmp/asymmetry-chart-quarantine.jsonl"),
        )
        data = Path("/tmp/asymmetry-chart-quarantine.parquet")
        data.write_bytes(b"bars")
        record = store.record_run(
            run_id="run_chart_diag",
            strategy_id="morning_va_breakout_s1",
            strategy_name="chart",
            methodology=CHART_TRACKER_METHODOLOGY,
            date_start="2021-01-01",
            date_end="2024-12-31",
            data_path=data,
            total_trades=3,
            win_rate=50.0,
            profit_factor=1.2,
            gross_profit=30.0,
            net_profit=30.0,
            max_drawdown=-10.0,
            sharpe_ratio=0.0,
            largest_win=20.0,
            strategy_tier=StrategyTier.BASELINE,
            is_net=False,
            git_commit="abc123",
        )
        self.assertEqual(record.strategy_tier, "BASELINE")
        self.assertFalse(any(item.run_id == "run_chart_diag" for item in store.list_runs(limit=20)))
        self.assertTrue(store.quarantine_chart_tracker_baseline("run_chart_diag"))
        after = store.get_run("run_chart_diag")
        self.assertEqual(after.strategy_tier, "CANDIDATE")
        self.assertEqual(after.total_trades, 3)
        self.assertEqual(after.net_profit, 30.0)
        self.assertEqual(after.git_commit, "abc123")
        self.assertIn("QUARANTINE", after.notes)
