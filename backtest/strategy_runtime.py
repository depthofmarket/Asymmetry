from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SignalEvent:
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    direction: str
    signal_type: str
    setup_tag: str
    signal_price: float
    entry_reference_price: float


class StrategyBrain(Protocol):
    """Protocol for strategy logic that can produce a timestamped signal frame."""

    def build_signal_frame(self, pre_df: pd.DataFrame | None = None) -> pd.DataFrame:
        ...


def direction_from_signal(signal: int | float) -> str:
    if int(signal) > 0:
        return "long"
    if int(signal) < 0:
        return "short"
    return ""


def setup_tag(signal_type: str, direction: str) -> str:
    signal_type = str(signal_type or "")
    return f"{signal_type}_{direction}" if signal_type else direction


def extract_signal_events(
    signal_frame: pd.DataFrame,
    *,
    entry_mode: str = "next_bar_open",
    entry_delay_bars: int = 0,
) -> list[SignalEvent]:
    """
    Convert a signal dataframe into explicit signal events.

    This is deliberately independent from order execution. Backtest, paper,
    and live runners can all consume the same event shape later.
    """
    if "signal" not in signal_frame.columns or "time" not in signal_frame.columns:
        return []

    df = signal_frame.copy()
    df["time"] = pd.to_datetime(df["time"])
    signals = df["signal"].fillna(0).astype(int)
    active_idx = list(df.index[signals.ne(0)])
    events: list[SignalEvent] = []
    entry_delay_bars = max(0, int(entry_delay_bars or 0))

    for idx in active_idx:
        signal = int(df.at[idx, "signal"])
        direction = direction_from_signal(signal)
        if not direction:
            continue

        if entry_mode == "next_bar_open":
            entry_idx = idx + 1 + entry_delay_bars
            if entry_idx >= len(df):
                continue
            entry_time = pd.Timestamp(df.at[entry_idx, "time"])
            entry_price = float(df.at[entry_idx, "open"]) if "open" in df.columns else np.nan
        else:
            entry_idx = idx + entry_delay_bars
            if entry_idx >= len(df):
                continue
            if entry_delay_bars > 0:
                entry_time = pd.Timestamp(df.at[entry_idx, "time"])
                entry_price = float(df.at[entry_idx, "open"]) if "open" in df.columns else np.nan
            else:
                entry_time = pd.Timestamp(df.at[entry_idx, "time"]) + pd.Timedelta(minutes=5)
                entry_price = float(df.at[entry_idx, "close"]) if "close" in df.columns else np.nan

        signal_type = str(df.at[idx, "signal_type"]) if "signal_type" in df.columns else ""
        signal_price = float(df.at[idx, "close"]) if "close" in df.columns else np.nan
        events.append(
            SignalEvent(
                signal_time=pd.Timestamp(df.at[idx, "time"]),
                entry_time=entry_time,
                direction=direction,
                signal_type=signal_type,
                setup_tag=setup_tag(signal_type, direction),
                signal_price=signal_price,
                entry_reference_price=entry_price,
            )
        )
    return events
