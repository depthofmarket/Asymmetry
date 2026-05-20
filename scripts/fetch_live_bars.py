#!/usr/bin/env python3
"""
Fetch NQ futures 1-minute bars from Yahoo Finance and append them to a CSV
that the paper trading engine can tail.

Yahoo Finance data is ~15 minutes delayed for NQ futures. This is fine for
paper-trading validation of strategy logic against live market conditions.

Usage:
    python scripts/fetch_live_bars.py [--out results/live_bars.csv] [--debug]
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── helpers ────────────────────────────────────────────────────────────────

HISTORY_DAYS = 7  # how many days to fetch on each poll to ensure recent bars


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "results" / "live_bars.csv"),
        help="Output CSV path (default: results/live_bars.csv)",
    )
    parser.add_argument(
        "--ticker",
        default="NQ=F",
        help="Yahoo Finance symbol for NQ futures (default: NQ=F)",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=60.0,
        help="Polling interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--warmup-rows",
        type=int,
        default=2500,
        help=(
            "Emit this many historical rows on first run for warmup "
            "(default: 2500, enough for 390 5-minute lookbacks)."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print each new bar as it is written",
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        default=None,
        help="Optional finite poll count for smoke tests.",
    )
    return parser.parse_args()


def fetch_intraday(
    ticker: str, days: int = HISTORY_DAYS
) -> pd.DataFrame:
    """Fetch intraday 1m data for the given ticker.

    Returns a DataFrame with columns:
        time, open, high, low, close, volume

    Returns an empty DataFrame on failure.
    """
    try:
        import yfinance as yf
    except ModuleNotFoundError:
        print(
            "yfinance is required. Install with: pip install yfinance",
            file=sys.stderr,
        )
        return pd.DataFrame()

    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=f"{days}d", interval="1m")
    except Exception as exc:
        print(f"yfinance fetch error: {exc}", file=sys.stderr)
        return pd.DataFrame()

    if hist.empty:
        return pd.DataFrame()

    # yfinance index is DatetimeIndex (timezone-aware to NY exchange).
    df = hist.reset_index()[["Datetime", "Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["time", "open", "high", "low", "close", "volume"]
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
    df = df.sort_values("time").reset_index(drop=True)
    return df


def load_existing(path: Path) -> pd.DataFrame:
    """Load existing bars CSV, returning empty DataFrame if absent or empty."""
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path)
        if df.empty:
            return pd.DataFrame()
        df["time"] = pd.to_datetime(df["time"])
        return df
    except Exception:
        return pd.DataFrame()


def get_last_emitted(existing: pd.DataFrame) -> pd.Timestamp | None:
    """Return the max time already written to CSV, or None."""
    if existing.empty or "time" not in existing.columns:
        return None
    return pd.to_datetime(existing["time"]).max()


def main() -> int:
    args = parse_args()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    warmup_remaining = args.warmup_rows

    print(f"Live bar collector started")
    print(f"  Ticker:    {args.ticker}")
    print(f"  Out file:  {out_path}")
    print(f"  Poll (s):  {args.poll_seconds}")
    print(f"  Warmup:    {warmup_remaining} rows")
    print(f"  Debug:     {args.debug}")
    print("Waiting for first fetch...", flush=True)

    polls = 0
    while True:
        polls += 1
        try:
            df = fetch_intraday(args.ticker)
        except Exception as exc:
            print(f"Fetch error: {exc}", file=sys.stderr)
            if args.max_polls is not None and polls >= max(0, int(args.max_polls)):
                break
            time.sleep(args.poll_seconds)
            continue

        if df.empty:
            print(
                f"{datetime.now():%H:%M:%S} No data returned (market closed? ticker wrong?)",
                file=sys.stderr,
            )
            if args.max_polls is not None and polls >= max(0, int(args.max_polls)):
                break
            time.sleep(args.poll_seconds)
            continue

        existing = load_existing(out_path)
        last_emitted = get_last_emitted(existing)

        # Filter to bars strictly after the last emitted time.
        if last_emitted is not None:
            new = df.loc[df["time"].gt(last_emitted)].copy()
        else:
            new = df.copy()

        if new.empty:
            if args.debug:
                print(f"{datetime.now():%H:%M:%S} No new bars.")
            if args.max_polls is not None and polls >= max(0, int(args.max_polls)):
                break
            time.sleep(args.poll_seconds)
            continue

        # During first run, respect warmup limit so the tail reader gets a
        # manageable history window.
        if warmup_remaining > 0 and last_emitted is None:
            if len(new) > warmup_remaining:
                new = new.tail(warmup_remaining).reset_index(drop=True)
            warmup_remaining -= len(new)
            if warmup_remaining < 0:
                warmup_remaining = 0

        # Append to CSV.
        new.to_csv(
            out_path,
            mode="a",
            header=not out_path.exists(),
            index=False,
        )

        if args.debug:
            bar_count = len(new)
            first_t = new["time"].iloc[0]
            last_t = new["time"].iloc[-1]
            print(
                f"{datetime.now():%H:%M:%S} Wrote {bar_count} bar(s) "
                f"[{first_t} .. {last_t}]  "
                f"last close={new['close'].iloc[-1]:.2f}",
                flush=True,
            )

        if args.max_polls is not None and polls >= max(0, int(args.max_polls)):
            break
        time.sleep(args.poll_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
