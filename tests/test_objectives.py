from __future__ import annotations

import unittest

import pandas as pd

from backtest.objectives import bar_objective_metrics, execution_bar_objective_metrics


FUTURES = {
    "contract_value": 20,
    "commission_per_round_trip": 2.0,
    "slippage_points": 0.25,
}


class ObjectiveMetricTests(unittest.TestCase):
    def test_execution_bar_metrics_prefix_bar_objective_metrics(self) -> None:
        bars = pd.DataFrame(
            {
                "time": pd.date_range("2024-01-02 09:30", periods=5, freq="min"),
                "close": [100.0, 101.0, 102.0, 101.5, 103.0],
            }
        )
        trades = pd.DataFrame(
            [
                {
                    "entry_time": "2024-01-02 09:31",
                    "exit_time": "2024-01-02 09:34",
                    "direction": "long",
                    "contracts": 1,
                    "pnl": 33.0,
                }
            ]
        )

        base = bar_objective_metrics(bars, trades, FUTURES, 100_000)
        execution = execution_bar_objective_metrics(bars, trades, FUTURES, 100_000)

        for key, value in base.items():
            self.assertIn(f"execution_{key}", execution)
            self.assertAlmostEqual(execution[f"execution_{key}"], value)


if __name__ == "__main__":
    unittest.main()
