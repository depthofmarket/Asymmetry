from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

from backtest.bar_exposure_audit import (
    build_trade_exposure_audit,
    export_bar_exposure_audit,
    load_bars_csv,
    reconstruct_bar_pnl_frame,
    resample_bars,
)
from backtest.objectives import bar_objective_metrics, profit_factor_from_pnl


FUTURES = {
    "contract_value": 20,
    "commission_per_round_trip": 2.0,
    "slippage_points": 0.25,
}


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-02 09:30", periods=6, freq="min"),
            "close": [100.0, 101.0, 103.0, 102.0, 99.0, 98.0],
        }
    )


def _trades() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entry_time": "2024-01-02 09:31",
                "exit_time": "2024-01-02 09:33",
                "direction": "long",
                "signal_type": "trend",
                "setup_tag": "trend_long",
                "reason": "managed_stop",
                "contracts": 1,
                "pnl": 13.0,
                "entry_open_context": "inside_prior_range",
                "entry_inside_ib": False,
                "entry_cusum_event": True,
                "entry_vwap_side": "above_vwap",
                "entry_market_memory_state": "persistent_memory",
            },
            {
                "entry_time": "2024-01-02 09:33",
                "exit_time": "2024-01-02 09:35",
                "direction": "short",
                "signal_type": "trend",
                "setup_tag": "trend_short",
                "reason": "managed_stop",
                "contracts": 1,
                "pnl": 73.0,
                "entry_open_context": "gap_above_prior_high",
                "entry_inside_ib": True,
                "entry_cusum_event": False,
                "entry_vwap_side": "below_vwap",
                "entry_market_memory_state": "tail_risk_memory",
            },
            {
                "entry_time": "2024-01-02 09:35",
                "exit_time": "2024-01-02 09:35",
                "direction": "long",
                "signal_type": "mr",
                "setup_tag": "mr_long",
                "reason": "hard_stop",
                "contracts": 1,
                "pnl": -7.0,
            },
        ]
    )


class BarExposureAuditTests(unittest.TestCase):
    def test_reconstructed_bar_metrics_match_objective_metrics(self) -> None:
        bars = _bars()
        trades = _trades()

        frame = reconstruct_bar_pnl_frame(
            bars=bars,
            trades=trades,
            futures_specs=FUTURES,
            starting_capital=100_000,
        )
        expected = bar_objective_metrics(bars, trades, FUTURES, 100_000)
        nonzero_pnl = frame.loc[frame["bar_pnl"].abs() > 1e-9, "bar_pnl"]

        self.assertAlmostEqual(
            expected["bar_profit_factor"],
            profit_factor_from_pnl(nonzero_pnl),
        )
        self.assertAlmostEqual(frame["bar_pnl"].sum(), expected["bar_total_pnl"])
        self.assertAlmostEqual(float(frame["exposed"].mean() * 100.0), expected["bar_exposure_pct"])

    def test_trade_audit_handles_long_short_and_same_bar_costs(self) -> None:
        by_trade = build_trade_exposure_audit(
            bars=_bars(),
            trades=_trades(),
            futures_specs=FUTURES,
        )

        self.assertEqual(by_trade.loc[0, "favorable_bars"], 1)
        self.assertEqual(by_trade.loc[0, "adverse_bars"], 1)
        self.assertAlmostEqual(by_trade.loc[0, "path_net_pnl"], 13.0)
        self.assertEqual(by_trade.loc[1, "favorable_bars"], 2)
        self.assertEqual(by_trade.loc[1, "adverse_bars"], 0)
        self.assertAlmostEqual(by_trade.loc[1, "path_net_pnl"], 73.0)
        self.assertTrue(bool(by_trade.loc[2, "zero_duration_or_unmatched"]))
        self.assertAlmostEqual(by_trade.loc[2, "path_net_pnl"], -7.0)

    def test_export_writes_audit_artifacts_and_summary(self) -> None:
        bars = _bars()
        trades = _trades()
        expected = bar_objective_metrics(bars, trades, FUTURES, 100_000)
        with tempfile.TemporaryDirectory() as tmp:
            dev_report = Path(tmp) / "development_report.csv"
            pd.DataFrame(
                [
                    {"check": "bar_profit_factor", "value": expected["bar_profit_factor"]},
                    {"check": "trade_profit_factor", "value": 2.0},
                ]
            ).to_csv(dev_report, index=False)

            paths = export_bar_exposure_audit(
                bars=bars,
                trades=trades,
                futures_specs=FUTURES,
                starting_capital=100_000,
                out_dir=Path(tmp) / "audit",
                development_report_csv=dev_report,
            )

            summary = pd.read_csv(paths.summary_csv)
            by_slice = pd.read_csv(paths.by_slice_csv)

            self.assertTrue(paths.by_trade_csv.exists())
            self.assertTrue(paths.report_md.exists())
            self.assertFalse(bool(summary.loc[0, "bar_pf_mismatch"]))
            self.assertAlmostEqual(summary.loc[0, "reconstructed_bar_profit_factor"], expected["bar_profit_factor"])
            self.assertIn("direction", set(by_slice["slice"]))

    def test_export_writes_execution_bar_diagnostics_when_supplied(self) -> None:
        execution_bars = _bars()
        signal_bars = resample_bars(execution_bars, rule="5min")
        trades = _trades()
        with tempfile.TemporaryDirectory() as tmp:
            paths = export_bar_exposure_audit(
                bars=signal_bars,
                execution_bars=execution_bars,
                trades=trades,
                futures_specs=FUTURES,
                starting_capital=100_000,
                out_dir=Path(tmp) / "audit",
            )

            summary = pd.read_csv(paths.summary_csv)

            self.assertIsNotNone(paths.execution_by_trade_csv)
            self.assertIsNotNone(paths.execution_by_slice_csv)
            self.assertTrue(paths.execution_by_trade_csv.exists())
            self.assertTrue(paths.execution_by_slice_csv.exists())
            self.assertIn("execution_bar_profit_factor", summary.columns)
            self.assertIn("execution_zero_duration_or_unmatched_trades", summary.columns)
            self.assertGreaterEqual(float(summary.loc[0, "execution_bar_profit_factor"]), 0.0)

    def test_export_flags_absolute_or_relative_bar_pf_mismatch(self) -> None:
        bars = _bars()
        trades = _trades()
        expected = bar_objective_metrics(bars, trades, FUTURES, 100_000)
        with tempfile.TemporaryDirectory() as tmp:
            dev_report = Path(tmp) / "development_report.csv"
            pd.DataFrame(
                [
                    {"check": "bar_profit_factor", "value": expected["bar_profit_factor"] + 0.06},
                    {"check": "trade_profit_factor", "value": 2.0},
                ]
            ).to_csv(dev_report, index=False)

            paths = export_bar_exposure_audit(
                bars=bars,
                trades=trades,
                futures_specs=FUTURES,
                starting_capital=100_000,
                out_dir=Path(tmp) / "audit",
                development_report_csv=dev_report,
            )
            summary = pd.read_csv(paths.summary_csv)

            self.assertTrue(bool(summary.loc[0, "bar_pf_mismatch"]))
            self.assertEqual(summary.loc[0, "decision"], "metric_code_audit_required")

    def test_load_bars_csv_accepts_databento_ts_event_column(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bars_csv = Path(tmp) / "bars.csv"
            pd.DataFrame(
                {
                    "ts_event": [
                        "2024-01-02T09:30:00.000000000Z",
                        "2024-01-02T09:31:00.000000000Z",
                        "2024-01-02T09:32:00.000000000Z",
                    ],
                    "rtype": [33, 33, 33],
                    "close": [100.0, 101.0, 102.0],
                }
            ).to_csv(bars_csv, index=False)

            loaded = load_bars_csv(bars_csv)
            frame = reconstruct_bar_pnl_frame(
                bars=loaded,
                trades=pd.DataFrame(
                    [
                        {
                            "entry_time": "2024-01-02 09:30",
                            "exit_time": "2024-01-02 09:32",
                            "direction": "long",
                            "contracts": 1,
                            "pnl": 33.0,
                        }
                    ]
                ),
                futures_specs=FUTURES,
                starting_capital=100_000,
            )

            self.assertEqual(list(loaded.columns), ["time", "close"])
            self.assertEqual(len(frame), 3)
            self.assertIn("bar_pnl", frame.columns)

    def test_load_bars_csv_can_select_continuous_contract_and_resample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bars_csv = Path(tmp) / "bars.csv"
            pd.DataFrame(
                {
                    "ts_event": [
                        "2024-01-02T14:30:00.000000000Z",
                        "2024-01-02T14:30:00.000000000Z",
                        "2024-01-02T14:31:00.000000000Z",
                        "2024-01-02T14:31:00.000000000Z",
                    ],
                    "open": [100.0, 1000.0, 101.0, 1001.0],
                    "high": [100.0, 1000.0, 101.0, 1001.0],
                    "low": [100.0, 1000.0, 101.0, 1001.0],
                    "close": [100.0, 1000.0, 101.0, 1001.0],
                    "volume": [1, 10, 1, 10],
                    "symbol": ["NQH4", "NQM4", "NQH4", "NQM4"],
                }
            ).to_csv(bars_csv, index=False)

            loaded = load_bars_csv(
                bars_csv,
                continuous_contract_method="timestamp_volume",
                bar_timeframe="5min",
            )

            self.assertEqual(len(loaded), 1)
            self.assertEqual(pd.Timestamp(loaded.loc[0, "time"]), pd.Timestamp("2024-01-02 09:30:00"))
            self.assertAlmostEqual(float(loaded.loc[0, "close"]), 1001.0)

    def test_cli_smoke_writes_outputs(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "results" / "runs" / "unit_run"
            trades_dir = run_dir / "trades"
            research_dir = run_dir / "research"
            trades_dir.mkdir(parents=True)
            research_dir.mkdir(parents=True)
            bars_csv = root / "bars.csv"
            _bars().to_csv(bars_csv, index=False)
            _trades().to_csv(trades_dir / "trade_log.csv", index=False)
            pd.DataFrame(
                [
                    {"check": "bar_profit_factor", "value": 1.0},
                    {"check": "trade_profit_factor", "value": 1.0},
                ]
            ).to_csv(research_dir / "development_report.csv", index=False)

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "scripts" / "audit_bar_exposure.py"),
                    "--run-dir",
                    str(run_dir),
                    "--bars-csv",
                    str(bars_csv),
                ],
                cwd=repo_root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((run_dir / "research" / "bar_exposure_audit" / "bar_exposure_audit_summary.csv").exists())
            self.assertTrue((run_dir / "research" / "bar_exposure_audit" / "execution_bar_exposure_by_trade.csv").exists())


if __name__ == "__main__":
    unittest.main()
