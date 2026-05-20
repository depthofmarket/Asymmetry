"""Tests for scripts/fetch_live_bars.py bar collection logic."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.fetch_live_bars import fetch_intraday, load_existing, get_last_emitted


class _FakeTicker:
    def __init__(self, frame: pd.DataFrame | None = None, exc: Exception | None = None):
        self.frame = frame
        self.exc = exc

    def history(self, period: str, interval: str) -> pd.DataFrame:
        if self.exc is not None:
            raise self.exc
        return self.frame.copy()


def _fake_yfinance_module(frame: pd.DataFrame | None = None, exc: Exception | None = None):
    return types.SimpleNamespace(Ticker=lambda ticker: _FakeTicker(frame=frame, exc=exc))


def _sample_yfinance_history() -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        ["2026-05-14 10:00:00", "2026-05-14 10:01:00"],
        tz="America/New_York",
        name="Datetime",
    )
    return pd.DataFrame(
        {
            "Open": [100.0, 100.5],
            "High": [101.0, 102.0],
            "Low": [99.5, 100.0],
            "Close": [100.5, 101.5],
            "Volume": [10, 20],
        },
        index=idx,
    )


class TestFetchLiveBars(unittest.TestCase):
    """Unit tests for the Yahoo Finance bar collector."""

    def test_load_existing_empty_path_returns_empty(self) -> None:
        """load_existing should return empty DataFrame for nonexistent files."""
        result = load_existing(Path("/tmp/nonexistent_file_for_testing.csv"))
        self.assertTrue(result.empty)

    def test_load_existing_empty_csv_returns_empty(self) -> None:
        """load_existing should handle empty CSV gracefully."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write("time,open,high,low,close,volume\n")
            tmp = f.name
        try:
            result = load_existing(Path(tmp))
            self.assertTrue(result.empty)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_load_existing_parses_csv_correctly(self) -> None:
        """load_existing should correctly parse a CSV with a few rows."""
        csv_content = (
            "time,open,high,low,close,volume\n"
            "2026-05-14 10:00:00,100.0,101.0,99.5,100.5,10\n"
            "2026-05-14 10:01:00,100.5,102.0,100.0,101.5,20\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            f.write(csv_content)
            tmp = f.name
        try:
            result = load_existing(Path(tmp))
            self.assertEqual(len(result), 2)
            self.assertIn("time", result.columns)
            self.assertEqual(result["close"].iloc[-1], 101.5)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_get_last_emitted_with_data(self) -> None:
        """get_last_emitted should return the max time from a loaded DataFrame."""
        df = pd.DataFrame({
            "time": pd.to_datetime(["2026-05-14 10:00:00", "2026-05-14 10:05:00"]),
            "close": [100.0, 101.0],
        })
        last = get_last_emitted(df)
        self.assertIsNotNone(last)
        self.assertEqual(last, pd.Timestamp("2026-05-14 10:05:00"))

    def test_get_last_emitted_empty(self) -> None:
        """get_last_emitted should return None for empty DataFrame."""
        df = pd.DataFrame()
        self.assertIsNone(get_last_emitted(df))

    def test_get_last_emitted_missing_time_column(self) -> None:
        """get_last_emitted should return None if 'time' column is absent."""
        df = pd.DataFrame({"close": [100.0]})
        self.assertIsNone(get_last_emitted(df))

    def test_fetch_intraday_returns_expected_columns(self) -> None:
        """fetch_intraday should normalize yfinance output into live bar columns."""
        with patch.dict(sys.modules, {"yfinance": _fake_yfinance_module(_sample_yfinance_history())}):
            df = fetch_intraday("NQ=F", days=5)

        expected_columns = {"time", "open", "high", "low", "close", "volume"}
        self.assertSetEqual(set(df.columns), expected_columns)
        self.assertEqual(len(df), 2)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(df["time"]))
        self.assertTrue(pd.api.types.is_float_dtype(df["close"]))

    def test_fetch_intraday_invalid_ticker_returns_empty(self) -> None:
        """fetch_intraday should return empty DataFrame for an invalid ticker."""
        with patch.dict(sys.modules, {"yfinance": _fake_yfinance_module(pd.DataFrame())}):
            df = fetch_intraday("INVALID_TICKER_XYZ_123", days=1)

        self.assertTrue(df.empty)

    def test_yfinance_output_compatible_with_file_tail_feed(self) -> None:
        """
        Realistic integration test: fetch bars, write to CSV, then verify
        FileTailBarFeed reads them as valid LiveBar objects.
        """
        from backtest.live_feeds import FileTailBarFeed

        with patch.dict(sys.modules, {"yfinance": _fake_yfinance_module(_sample_yfinance_history())}):
            df = fetch_intraday("NQ=F", days=5)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            df.to_csv(f.name, index=False)
            tmp = f.name

        try:
            feed = FileTailBarFeed(tmp, start_at_end=False)
            bars = feed.poll_once()
            self.assertGreater(len(bars), 0)
            first = bars[0]
            self.assertIsNotNone(first.time)
            self.assertTrue(0 < first.close < 100000)  # sanity check NQ price range
            self.assertEqual(first.volume.__class__.__name__, "float")
        finally:
            Path(tmp).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
