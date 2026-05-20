from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from backtest.walkforward import run_walk_forward


def _daily_bars() -> pd.DataFrame:
    times = pd.date_range("2020-01-01", "2022-01-01", freq="D", inclusive="left")
    return pd.DataFrame(
        {
            "time": times,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000,
        }
    )


def _fake_segment_result(*args, **kwargs) -> dict:
    return {
        "total_trades": 50,
        "total_pnl": 100.0,
        "final_equity": 100_100.0,
        "profit_factor": 1.2,
        "bar_profit_factor": 1.15,
        "sharpe_ratio": 0.5,
        "bar_sharpe_ratio": 0.4,
        "expectancy": 2.0,
        "trades": pd.DataFrame(),
    }


class WalkForwardTests(unittest.TestCase):
    def test_auto_purge_and_embargo_create_boundary_gap(self) -> None:
        bars = _daily_bars()
        with tempfile.TemporaryDirectory() as tmp, patch(
            "backtest.walkforward._run_segment",
            side_effect=_fake_segment_result,
        ):
            result = run_walk_forward(
                pre_df=bars,
                raw_data=None,
                futures_specs={"contract_value": 20.0},
                base_params={"strategy_name": "unit", "max_hold_bars": 2, "entry_delay_bars": 1},
                starting_capital=100_000.0,
                train_years=1,
                test_months=3,
                step_months=3,
                window_mode="rolling",
                purge_bars="auto",
                embargo_bars=1,
                param_grid={"max_hold_bars": [2], "entry_delay_bars": [1]},
                metric="bar_profit_factor",
                min_trades_train=1,
                min_trades_test=1,
                out_dir=Path(tmp),
                progress=False,
            )

            fold = result.folds[0]
            self.assertEqual(fold.purge_bars, 4)
            self.assertEqual(fold.embargo_bars, 1)
            self.assertEqual(fold.gap_bars, 5)
            self.assertTrue(fold.purge_embargo_ok)
            self.assertEqual(
                pd.Timestamp(fold.train_end),
                pd.Timestamp(fold.test_start) - pd.Timedelta(days=5),
            )

            fold_csv = pd.read_csv(result.fold_summary_csv)
            self.assertEqual(int(fold_csv.loc[0, "gap_bars"]), 5)
            self.assertTrue(bool(fold_csv.loc[0, "purge_embargo_ok"]))
            self.assertIn("planned_train_end", fold_csv.columns)
            self.assertIn("boundary_gap_minutes", fold_csv.columns)

    def test_anchored_window_keeps_original_train_start(self) -> None:
        bars = _daily_bars()
        kwargs = dict(
            pre_df=bars,
            raw_data=None,
            futures_specs={"contract_value": 20.0},
            base_params={"strategy_name": "unit", "max_hold_bars": 2},
            starting_capital=100_000.0,
            train_years=1,
            test_months=3,
            step_months=3,
            purge_bars=0,
            embargo_bars=0,
            param_grid={"max_hold_bars": [2]},
            metric="bar_profit_factor",
            min_trades_train=1,
            min_trades_test=1,
            progress=False,
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "backtest.walkforward._run_segment",
            side_effect=_fake_segment_result,
        ):
            rolling = run_walk_forward(
                **kwargs,
                window_mode="rolling",
                out_dir=Path(tmp) / "rolling",
            )
            anchored = run_walk_forward(
                **kwargs,
                window_mode="anchored",
                out_dir=Path(tmp) / "anchored",
            )

            self.assertGreaterEqual(len(rolling.folds), 2)
            self.assertEqual(pd.Timestamp(anchored.folds[1].train_start), pd.Timestamp("2020-01-01"))
            self.assertGreater(pd.Timestamp(rolling.folds[1].train_start), pd.Timestamp("2020-01-01"))
            self.assertEqual(anchored.folds[1].window_mode, "anchored")
            self.assertEqual(rolling.folds[1].window_mode, "rolling")


if __name__ == "__main__":
    unittest.main()
