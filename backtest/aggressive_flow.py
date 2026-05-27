from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import zipfile

import numpy as np
import pandas as pd

from backtest.options_ingestion import _read_csv_member, schema_members
from backtest.tbbo_execution import NQ_OUTRIGHT_SYMBOL_PATTERN, _date_from_member


TRADES_USECOLS = [
    "ts_recv",
    "ts_event",
    "instrument_id",
    "action",
    "side",
    "price",
    "size",
    "symbol",
]


@dataclass(frozen=True)
class AggressiveFlowStats:
    minute_stats: pd.DataFrame
    daily_stats: pd.DataFrame


def _filtered_trade_members(
    source: Path | str,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    max_files: int | None = None,
) -> list[str]:
    source_path = Path(source)
    start_date = pd.Timestamp(start).normalize() if start is not None else None
    end_date = pd.Timestamp(end).normalize() if end is not None else None
    members = schema_members(source_path, "trades")
    out: list[str] = []
    for member in members:
        date = _date_from_member(member)
        if date is not None:
            if start_date is not None and date < start_date:
                continue
            if end_date is not None and date > end_date:
                continue
        out.append(member)
        if max_files is not None and len(out) >= int(max_files):
            break
    return out


def normalize_trade_frame(
    df: pd.DataFrame,
    *,
    symbol_regex: str | None = None,
) -> pd.DataFrame:
    out = df.copy()
    for col in ("ts_recv", "ts_event"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")
    for col in ("instrument_id", "price", "size"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in ("action", "side", "symbol"):
        if col in out.columns:
            out[col] = out[col].astype("string")
    if symbol_regex and "symbol" in out.columns:
        mask = out["symbol"].astype(str).str.match(str(symbol_regex), na=False)
        out = out.loc[mask].copy()

    if "action" in out.columns:
        out = out.loc[out["action"].astype(str).eq("T")].copy()
    out = out.dropna(subset=["ts_event", "symbol", "price", "size"])
    out["event_time_ny"] = out["ts_event"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    out["minute"] = out["event_time_ny"].dt.floor("min")
    out["trade_date"] = out["event_time_ny"].dt.date.astype("string")
    out["hour"] = out["event_time_ny"].dt.hour
    out["minute_of_day"] = out["event_time_ny"].dt.hour * 60 + out["event_time_ny"].dt.minute
    out["rth_session"] = out["minute_of_day"].between(9 * 60 + 30, 16 * 60, inclusive="left")
    return out


def iter_trade_frames(
    source: Path | str,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    max_files: int | None = None,
    rows_per_file: int | None = None,
    symbol_regex: str | None = None,
    progress_every: int = 10,
) -> Iterable[pd.DataFrame]:
    source_path = Path(source)
    members = _filtered_trade_members(source_path, start=start, end=end, max_files=max_files)
    if source_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(source_path) as zf:
            for idx, member in enumerate(members, start=1):
                if progress_every > 0 and (idx == 1 or idx == len(members) or idx % progress_every == 0):
                    print(f"trade member {idx}/{len(members)}: {member}", flush=True)
                frame = _read_csv_member(
                    source_path,
                    member,
                    nrows=rows_per_file,
                    usecols=lambda col: col in TRADES_USECOLS,
                    zip_file=zf,
                )
                frame["source_member"] = member
                yield normalize_trade_frame(frame, symbol_regex=symbol_regex)
        return

    for idx, member in enumerate(members, start=1):
        if progress_every > 0 and (idx == 1 or idx == len(members) or idx % progress_every == 0):
            print(f"trade member {idx}/{len(members)}: {member}", flush=True)
        frame = _read_csv_member(
            source_path,
            member,
            nrows=rows_per_file,
            usecols=lambda col: col in TRADES_USECOLS,
        )
        frame["source_member"] = member
        yield normalize_trade_frame(frame, symbol_regex=symbol_regex)


def aggregate_aggressive_flow_minute_stats(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    work = frame.dropna(subset=["minute", "symbol"]).copy()
    if work.empty:
        return pd.DataFrame()
    work["raw_b_size"] = np.where(work["side"].astype(str).eq("B"), work["size"].astype(float), 0.0)
    work["raw_a_size"] = np.where(work["side"].astype(str).eq("A"), work["size"].astype(float), 0.0)
    work["raw_b_count"] = work["side"].astype(str).eq("B").astype(int)
    work["raw_a_count"] = work["side"].astype(str).eq("A").astype(int)
    work["notional"] = work["price"].astype(float) * work["size"].astype(float)

    grouped = work.groupby(["symbol", "minute"], sort=True)
    out = grouped.agg(
        trade_date=("trade_date", "first"),
        rth_session=("rth_session", "max"),
        trade_count=("minute", "size"),
        trade_size=("size", "sum"),
        raw_b_side_count=("raw_b_count", "sum"),
        raw_a_side_count=("raw_a_count", "sum"),
        raw_b_side_trade_size=("raw_b_size", "sum"),
        raw_a_side_trade_size=("raw_a_size", "sum"),
        first_trade_price=("price", "first"),
        last_trade_price=("price", "last"),
        high_trade_price=("price", "max"),
        low_trade_price=("price", "min"),
    ).reset_index()
    notional = grouped["notional"].sum().reset_index(name="notional")
    out = out.merge(notional, on=["symbol", "minute"], how="left")
    out["trade_vwap"] = np.where(
        out["trade_size"].astype(float) > 0.0,
        out["notional"].astype(float) / out["trade_size"].astype(float),
        np.nan,
    )
    out["raw_b_minus_a_trade_size"] = out["raw_b_side_trade_size"] - out["raw_a_side_trade_size"]
    out["raw_b_minus_a_trade_count"] = out["raw_b_side_count"] - out["raw_a_side_count"]
    out["raw_b_minus_a_trade_size_share"] = np.where(
        out["trade_size"].astype(float) > 0.0,
        out["raw_b_minus_a_trade_size"] / out["trade_size"].astype(float),
        np.nan,
    )
    out["trade_price_change_points"] = out["last_trade_price"] - out["first_trade_price"]
    return out.drop(columns=["notional"])


def aggregate_aggressive_flow_daily_stats(minute_stats: pd.DataFrame) -> pd.DataFrame:
    if minute_stats.empty:
        return pd.DataFrame()
    grouped = minute_stats.groupby(["symbol", "trade_date"], sort=True)
    out = grouped.agg(
        minutes=("minute", "size"),
        rth_minutes=("rth_session", "sum"),
        total_trades=("trade_count", "sum"),
        total_trade_size=("trade_size", "sum"),
        raw_b_side_trade_size=("raw_b_side_trade_size", "sum"),
        raw_a_side_trade_size=("raw_a_side_trade_size", "sum"),
        raw_b_minus_a_trade_size=("raw_b_minus_a_trade_size", "sum"),
        median_abs_raw_b_minus_a_trade_size_share=("raw_b_minus_a_trade_size_share", lambda s: float(s.abs().median())),
    ).reset_index()
    out["raw_b_minus_a_trade_size_share"] = np.where(
        out["total_trade_size"].astype(float) > 0.0,
        out["raw_b_minus_a_trade_size"] / out["total_trade_size"].astype(float),
        np.nan,
    )
    return out


def build_aggressive_flow_stats_from_source(
    source: Path | str,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    max_files: int | None = None,
    rows_per_file: int | None = None,
    symbol_regex: str | None = NQ_OUTRIGHT_SYMBOL_PATTERN,
    progress_every: int = 10,
) -> AggressiveFlowStats:
    minute_frames: list[pd.DataFrame] = []
    for frame in iter_trade_frames(
        source,
        start=start,
        end=end,
        max_files=max_files,
        rows_per_file=rows_per_file,
        symbol_regex=symbol_regex,
        progress_every=progress_every,
    ):
        minute = aggregate_aggressive_flow_minute_stats(frame)
        if not minute.empty:
            minute_frames.append(minute)
    if not minute_frames:
        empty = pd.DataFrame()
        return AggressiveFlowStats(minute_stats=empty, daily_stats=empty)
    minute_stats = pd.concat(minute_frames, ignore_index=True)
    minute_stats = merge_aggressive_flow_minute_stats(minute_stats)
    daily_stats = aggregate_aggressive_flow_daily_stats(minute_stats)
    return AggressiveFlowStats(minute_stats=minute_stats, daily_stats=daily_stats)


def merge_aggressive_flow_minute_stats(*frames: pd.DataFrame) -> pd.DataFrame:
    non_empty = [frame for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return pd.DataFrame()
    out = pd.concat(non_empty, ignore_index=True)
    out["minute"] = pd.to_datetime(out["minute"], errors="coerce")
    out = out.dropna(subset=["symbol", "minute"])
    return out.drop_duplicates(subset=["symbol", "minute"], keep="last").sort_values(["symbol", "minute"]).reset_index(drop=True)


def merge_aggressive_flow_daily_stats(*frames: pd.DataFrame) -> pd.DataFrame:
    non_empty = [frame for frame in frames if frame is not None and not frame.empty]
    if not non_empty:
        return pd.DataFrame()
    out = pd.concat(non_empty, ignore_index=True)
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.date.astype("string")
    out = out.dropna(subset=["symbol", "trade_date"])
    return out.drop_duplicates(subset=["symbol", "trade_date"], keep="last").sort_values(["symbol", "trade_date"]).reset_index(drop=True)
