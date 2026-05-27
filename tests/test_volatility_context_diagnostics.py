from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from backtest.volatility_context_diagnostics import (
    build_volatility_context_diagnostics,
    write_volatility_context_diagnostics,
)


def _bars() -> pd.DataFrame:
    times = pd.date_range("2024-01-03 09:30:00", periods=24, freq="min")
    close = 100.0 + np.cumsum([0.10, -0.05, 0.08, -0.04] * 6)
    return pd.DataFrame(
        {
            "time": times,
            "open": close - 0.02,
            "high": close + 0.10,
            "low": close - 0.10,
            "close": close,
            "volume": np.full(len(times), 1000),
        }
    )


def _volatility_state() -> pd.DataFrame:
    bars = _bars()
    state = bars.copy()
    state["volatility_state"] = ["compressed_volatility_context"] * 10 + ["expanded_volatility_context"] * 14
    state["volatility_compression_state"] = ["compressed_volatility"] * 10 + ["expanded_volatility"] * 14
    state["volatility_vol_of_vol_state"] = "stable_volatility_of_volatility"
    state["volatility_roughness_state"] = "neutral_volatility_memory"
    state["volatility_jump_event"] = False
    state["realized_vol_short"] = np.linspace(0.01, 0.03, len(state))
    state["realized_vol_long"] = np.linspace(0.02, 0.025, len(state))
    return state


def _tbbo_minute() -> pd.DataFrame:
    times = pd.date_range("2024-01-03 09:30:00", periods=24, freq="min")
    rows = []
    for idx, minute in enumerate(times):
        expanded = idx >= 10
        rows.append(
            {
                "symbol": "NQH4",
                "minute": minute,
                "trade_date": "2024-01-03",
                "median_mid_price": 100.0 + idx * 0.25,
                "median_spread_points": 2.0 if expanded else 0.75,
                "p95_spread_points": 2.5 if expanded else 1.0,
                "p95_abs_trade_price_vs_mid": 0.75 if expanded else 0.20,
                "median_top_book_imbalance": 0.10,
                "trade_count": 20,
                "trade_size": 50.0,
                "top_book_depth_exhausted_trade_pct": 0.40 if expanded else 0.05,
                "top_book_depth_exhausted_size_share": 0.35 if expanded else 0.04,
                "zero_impact_depth_supported_trade_pct": 0.25 if expanded else 0.80,
            }
        )
    return pd.DataFrame(rows)


def _signals() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.to_datetime(["2024-01-03 09:35:00", "2024-01-03 09:45:00"]),
            "candidate_signal": [1.0, -1.0],
            "signal_active": [True, True],
            "direction": ["long", "short"],
            "setup_tag": ["test_long", "test_short"],
        }
    )


class VolatilityContextDiagnosticsTests(unittest.TestCase):
    def test_builds_future_rv_and_year_regime_splits(self) -> None:
        diagnostics = build_volatility_context_diagnostics(
            _bars(),
            volatility_state=_volatility_state(),
            future_rv_horizons_bars=[3],
            tbbo_minute_stats=pd.DataFrame(),
        )

        self.assertFalse(diagnostics.future_realized_vol_by_state.empty)
        self.assertIn("expanded_volatility_context", set(diagnostics.future_realized_vol_by_state["volatility_state"]))
        self.assertIn("year", set(diagnostics.future_realized_vol_splits["split_type"]))
        self.assertIn(
            "regime:volatility_compression_state",
            set(diagnostics.future_realized_vol_splits["split_type"]),
        )

    def test_tbbo_cost_state_and_spread_reversion_are_grouped_by_vol_state(self) -> None:
        diagnostics = build_volatility_context_diagnostics(
            _bars(),
            volatility_state=_volatility_state(),
            tbbo_minute_stats=_tbbo_minute(),
            future_rv_horizons_bars=[3],
            spread_reversion_horizons_minutes=[1],
        )

        self.assertFalse(diagnostics.tbbo_cost_state_by_vol_state.empty)
        expanded = diagnostics.tbbo_cost_state_by_vol_state.loc[
            diagnostics.tbbo_cost_state_by_vol_state["volatility_state"].eq("expanded_volatility_context")
        ]
        self.assertFalse(expanded.empty)
        self.assertGreater(float(expanded["median_spread_points"].iloc[0]), 1.0)
        self.assertFalse(diagnostics.spread_reversion_during_expansion.empty)
        self.assertTrue(
            diagnostics.spread_reversion_during_expansion["volatility_state"]
            .astype(str)
            .str.contains("expanded")
            .all()
        )

    def test_signal_adverse_selection_by_vol_state_is_optional(self) -> None:
        without_signals = build_volatility_context_diagnostics(
            _bars(),
            volatility_state=_volatility_state(),
            tbbo_minute_stats=_tbbo_minute(),
            future_rv_horizons_bars=[3],
            spread_reversion_horizons_minutes=[1],
        )
        self.assertTrue(without_signals.signal_adverse_selection_by_vol_state.empty)

        with_signals = build_volatility_context_diagnostics(
            _bars(),
            volatility_state=_volatility_state(),
            tbbo_minute_stats=_tbbo_minute(),
            signals=_signals(),
            future_rv_horizons_bars=[3],
            spread_reversion_horizons_minutes=[1],
        )
        self.assertFalse(with_signals.signal_adverse_selection_by_vol_state.empty)
        self.assertIn("adverse_after_spread_pct", with_signals.signal_adverse_selection_by_vol_state.columns)
        self.assertIn("year", set(with_signals.signal_adverse_selection_splits["split_type"]))

    def test_write_outputs_report_and_csvs(self) -> None:
        diagnostics = build_volatility_context_diagnostics(
            _bars(),
            volatility_state=_volatility_state(),
            tbbo_minute_stats=_tbbo_minute(),
            signals=_signals(),
            future_rv_horizons_bars=[3],
            spread_reversion_horizons_minutes=[1],
        )

        with tempfile.TemporaryDirectory() as tmp:
            paths = write_volatility_context_diagnostics(diagnostics, Path(tmp), artifact_name="Vol Context")

            self.assertTrue(paths.report_md.exists())
            self.assertTrue(paths.future_realized_vol_by_state_csv.exists())
            self.assertTrue(paths.tbbo_cost_state_by_vol_state_csv.exists())
            report = paths.report_md.read_text(encoding="utf-8")
            self.assertIn("Volatility Context Diagnostics", report)
            self.assertIn("Guardrails", report)


if __name__ == "__main__":
    unittest.main()
