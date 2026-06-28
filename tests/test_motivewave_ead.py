from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

from backtest.motivewave_ead import (
    MotiveWaveEADConfig,
    build_motivewave_ead_parity,
    build_trade_buckets,
    compare_native_ead_to_motivewave,
    compute_native_ead,
)


def _trade_prints() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_event": [
                "2021-01-04T14:30:00.000000Z",
                "2021-01-04T14:30:00.100000Z",
                "2021-01-04T14:30:00.200000Z",
                "2021-01-04T14:30:00.300000Z",
            ],
            "side": ["B", "B", "A", "A"],
            "price": [100.00, 99.00, 100.00, 101.00],
            "size": [10, 10, 10, 10],
        }
    )


def _matching_motivewave_export() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": [
                "2021-01-04T14:30:00.100000Z",
                "2021-01-04T14:30:00.300000Z",
            ],
            "Buy-side Absorption": [1, 0],
            "Sell-side Absorption": [0, 1],
            "Buy-side Initiation": [0, 0],
            "Sell-side Initiation": [0, 0],
        }
    )


class MotiveWaveEADTests(unittest.TestCase):
    def test_builds_tick_buckets_from_trade_prints(self) -> None:
        buckets = build_trade_buckets(_trade_prints(), bucket_mode="tick", bucket_size=2)

        self.assertEqual(len(buckets), 2)
        self.assertEqual(buckets["trade_count"].tolist(), [2, 2])
        self.assertEqual(buckets["buy_volume"].tolist(), [20.0, 0.0])
        self.assertEqual(buckets["sell_volume"].tolist(), [0.0, 20.0])
        self.assertEqual(buckets["open"].tolist(), [100.0, 100.0])
        self.assertEqual(buckets["close"].tolist(), [99.0, 101.0])

    def test_builds_volume_buckets_without_splitting_trades(self) -> None:
        trades = pd.DataFrame(
            {
                "ts_event": [
                    "2021-01-04T14:30:00.000000Z",
                    "2021-01-04T14:30:00.100000Z",
                    "2021-01-04T14:30:00.200000Z",
                    "2021-01-04T14:30:00.300000Z",
                ],
                "side": ["B", "B", "B", "B"],
                "price": [100.0, 100.25, 100.5, 100.75],
                "size": [3, 4, 6, 2],
            }
        )

        buckets = build_trade_buckets(trades, bucket_mode="volume", bucket_size=10)

        self.assertEqual(len(buckets), 2)
        self.assertEqual(buckets["trade_count"].tolist(), [3, 1])
        self.assertEqual(buckets["volume"].tolist(), [13.0, 2.0])

    def test_ead_defaults_and_fast_mode(self) -> None:
        default = MotiveWaveEADConfig.for_mode("default")
        fast = MotiveWaveEADConfig.for_mode("fast")

        self.assertEqual(default.absorption_intensity, 3)
        self.assertEqual(default.volume_sensitivity, 10)
        self.assertAlmostEqual(default.threshold, 0.6669999957084656)
        self.assertEqual(fast.absorption_intensity, 6)
        self.assertEqual(fast.volume_sensitivity, 20)
        self.assertAlmostEqual(fast.threshold, default.threshold)

    def test_native_ead_preserves_absorption_directional_mapping(self) -> None:
        buckets = build_trade_buckets(_trade_prints(), bucket_mode="tick", bucket_size=2)
        ead = compute_native_ead(buckets)

        self.assertTrue(bool(ead.loc[0, "mw_buy_absorption"]))
        self.assertFalse(bool(ead.loc[0, "mw_absorption_long_trigger"]))
        self.assertTrue(bool(ead.loc[0, "mw_absorption_short_trigger"]))
        self.assertTrue(bool(ead.loc[1, "mw_sell_absorption"]))
        self.assertTrue(bool(ead.loc[1, "mw_absorption_long_trigger"]))
        self.assertFalse(bool(ead.loc[1, "mw_absorption_short_trigger"]))

    def test_parity_passes_when_motivewave_booleans_match_exactly(self) -> None:
        result = build_motivewave_ead_parity(
            _trade_prints(),
            _matching_motivewave_export(),
            bucket_mode="tick",
            bucket_size=2,
            motivewave_timezone="UTC",
        )

        self.assertTrue(result.passed)
        self.assertEqual(len(result.mismatches), 0)
        self.assertIn("Status: PASS", result.report_md)

    def test_parity_fails_on_boolean_mismatch(self) -> None:
        buckets = build_trade_buckets(_trade_prints(), bucket_mode="tick", bucket_size=2)
        native = compute_native_ead(buckets)
        motivewave = _matching_motivewave_export().copy()
        motivewave.loc[0, "Buy-side Absorption"] = 0
        mw_context = build_motivewave_ead_parity(
            _trade_prints(),
            motivewave,
            bucket_mode="tick",
            bucket_size=2,
            motivewave_timezone="UTC",
        )

        self.assertFalse(mw_context.passed)
        self.assertEqual(len(mw_context.mismatches), 1)
        self.assertIn("Status: FAIL", mw_context.report_md)

        direct = compare_native_ead_to_motivewave(native, mw_context.motivewave_ead)
        self.assertFalse(direct.passed)

    def test_parity_cli_smoke_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trades_path = root / "trades.csv"
            mw_path = root / "motivewave.csv"
            out_dir = root / "out"
            _trade_prints().to_csv(trades_path, index=False)
            _matching_motivewave_export().to_csv(mw_path, index=False)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/check_motivewave_ead_parity.py",
                    "--trades",
                    str(trades_path),
                    "--motivewave-export",
                    str(mw_path),
                    "--bucket-mode",
                    "tick",
                    "--bucket-size",
                    "2",
                    "--motivewave-timezone",
                    "UTC",
                    "--out-dir",
                    str(out_dir),
                    "--prefix",
                    "smoke",
                ],
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertTrue((out_dir / "smoke_native_ead.csv").exists())
            self.assertTrue((out_dir / "smoke_aligned.csv").exists())
            self.assertTrue((out_dir / "smoke_mismatches.csv").exists())
            self.assertIn("Status: PASS", (out_dir / "smoke_report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
