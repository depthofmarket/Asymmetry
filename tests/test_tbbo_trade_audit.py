from __future__ import annotations

import unittest

import pandas as pd

from backtest.tbbo_trade_audit import build_tbbo_trade_audit


def _minute_stats() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "NQH6",
                "minute": "2026-03-18 10:20:00",
                "trade_date": "2026-03-18",
                "rth_session": True,
                "median_spread_points": 0.50,
                "p95_spread_points": 1.00,
                "trade_count": 100,
                "p95_abs_trade_price_vs_mid": 0.50,
            },
            {
                "symbol": "NQH6",
                "minute": "2026-03-18 10:25:00",
                "trade_date": "2026-03-18",
                "rth_session": True,
                "median_spread_points": 0.50,
                "p95_spread_points": 1.00,
                "trade_count": 110,
                "p95_abs_trade_price_vs_mid": 0.50,
            },
            {
                "symbol": "NQM6",
                "minute": "2026-03-18 10:20:00",
                "trade_date": "2026-03-18",
                "rth_session": True,
                "median_spread_points": 3.00,
                "p95_spread_points": 4.00,
                "trade_count": 2,
                "p95_abs_trade_price_vs_mid": 2.00,
            },
        ]
    )


def _trades() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entry_time": "2026-03-18 10:20:00",
                "exit_time": "2026-03-18 10:25:00",
                "direction": "short",
                "setup_tag": "trend_short",
                "contracts": 1,
                "pnl": 100.0,
                "reason": "profit_target",
            },
            {
                "entry_time": "2026-01-02 10:20:00",
                "exit_time": "2026-01-02 10:25:00",
                "direction": "long",
                "setup_tag": "trend_long",
                "contracts": 1,
                "pnl": -10.0,
                "reason": "stop_loss",
            },
        ]
    )


class TbboTradeAuditTests(unittest.TestCase):
    def test_audit_matches_active_contract_and_estimates_cost(self) -> None:
        audit = build_tbbo_trade_audit(_trades(), _minute_stats())
        row = audit.audited_trades.iloc[0]

        self.assertTrue(bool(row["tbbo_entry_exit_matched"]))
        self.assertEqual(row["entry_tbbo_symbol"], "NQH6")
        self.assertEqual(row["exit_tbbo_symbol"], "NQH6")
        self.assertAlmostEqual(float(row["tbbo_median_round_trip_spread_cost_points"]), 0.50)
        self.assertAlmostEqual(float(row["assumed_slippage_points"]), 0.25)
        self.assertAlmostEqual(float(row["pnl_with_tbbo_median_spread_cost"]), 95.0)

    def test_audit_reports_window_coverage(self) -> None:
        audit = build_tbbo_trade_audit(_trades(), _minute_stats())
        summary = audit.summary.iloc[0]

        self.assertEqual(int(summary["total_trades"]), 2)
        self.assertEqual(int(summary["tbbo_window_trades"]), 1)
        self.assertEqual(int(summary["entry_exit_matched_trades"]), 1)
        self.assertAlmostEqual(float(summary["entry_exit_match_rate_in_window"]), 1.0)


if __name__ == "__main__":
    unittest.main()
