from __future__ import annotations

import numpy as np
import pandas as pd


def clock_ge(times: pd.Series, hour_min: str) -> pd.Series:
    """Return True where timestamp clock time is at or after HH:MM."""

    dt = pd.to_datetime(times, errors="coerce")
    hour, minute = [int(part) for part in str(hour_min).split(":", 1)]
    return (dt.dt.hour > hour) | ((dt.dt.hour == hour) & (dt.dt.minute >= minute))


def mask_columns_before_clock(
    df: pd.DataFrame,
    columns: list[str] | tuple[str, ...] | set[str],
    *,
    time_col: str = "time",
    available_at: str,
) -> pd.DataFrame:
    """
    Blank feature columns before their first point-in-time availability.

    This is deliberately simple: for intraday features such as ORB, opening
    profile, or final RTH summaries, a feature computed from a completed window
    should not be present on rows inside that still-forming window.
    """

    existing = [col for col in columns if col in df.columns]
    if not existing:
        return df

    out = df.copy()
    known = clock_ge(out[time_col], available_at)
    out.loc[~known, existing] = np.nan
    return out


def assert_columns_blank_before_clock(
    df: pd.DataFrame,
    columns: list[str] | tuple[str, ...] | set[str],
    *,
    time_col: str = "time",
    available_at: str,
) -> None:
    """Raise if any guarded feature is populated before its availability time."""

    existing = [col for col in columns if col in df.columns]
    if not existing:
        return

    known = clock_ge(df[time_col], available_at)
    early = df.loc[~known, existing]
    leaked = [
        col
        for col in existing
        if early[col].notna().any()
    ]
    if leaked:
        raise AssertionError(
            f"Columns populated before {available_at}: {', '.join(sorted(leaked))}"
        )
