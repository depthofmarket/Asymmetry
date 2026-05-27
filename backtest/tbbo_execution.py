from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import re
import zipfile

import numpy as np
import pandas as pd

from backtest.options_ingestion import _read_csv_member, schema_members


TBBO_USECOLS = [
    "ts_recv",
    "ts_event",
    "instrument_id",
    "action",
    "side",
    "price",
    "size",
    "bid_px_00",
    "ask_px_00",
    "bid_sz_00",
    "ask_sz_00",
    "bid_ct_00",
    "ask_ct_00",
    "symbol",
]
NQ_OUTRIGHT_SYMBOL_PATTERN = r"^NQ[FGHJKMNQUVXZ]\d{1,2}$"


@dataclass(frozen=True)
class TbboExecutionStats:
    minute_stats: pd.DataFrame
    daily_stats: pd.DataFrame


def _date_from_member(member: str) -> pd.Timestamp | None:
    match = re.search(r"(20\d{6})", Path(str(member)).name)
    if not match:
        return None
    return pd.Timestamp(match.group(1))


def _filtered_tbbo_members(
    source: Path | str,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    max_files: int | None = None,
) -> list[str]:
    source_path = Path(source)
    start_date = pd.Timestamp(start).normalize() if start is not None else None
    end_date = pd.Timestamp(end).normalize() if end is not None else None
    members = schema_members(source_path, "tbbo")
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


def normalize_tbbo_frame(
    df: pd.DataFrame,
    *,
    tick_size: float = 0.25,
    symbol_regex: str | None = None,
) -> pd.DataFrame:
    out = df.copy()
    for col in ("ts_recv", "ts_event"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")
    numeric_cols = [
        "instrument_id",
        "price",
        "size",
        "bid_px_00",
        "ask_px_00",
        "bid_sz_00",
        "ask_sz_00",
        "bid_ct_00",
        "ask_ct_00",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in ("action", "side", "symbol"):
        if col in out.columns:
            out[col] = out[col].astype("string")
    if symbol_regex and "symbol" in out.columns:
        mask = out["symbol"].astype(str).str.match(str(symbol_regex), na=False)
        out = out.loc[mask].copy()

    bid = out.get("bid_px_00", pd.Series(np.nan, index=out.index)).astype(float)
    ask = out.get("ask_px_00", pd.Series(np.nan, index=out.index)).astype(float)
    bid_size = out.get("bid_sz_00", pd.Series(np.nan, index=out.index)).astype(float)
    ask_size = out.get("ask_sz_00", pd.Series(np.nan, index=out.index)).astype(float)
    trade_price = out.get("price", pd.Series(np.nan, index=out.index)).astype(float)

    out["mid_price"] = (bid + ask) / 2.0
    out["spread_points"] = ask - bid
    out["spread_ticks"] = out["spread_points"] / float(tick_size)
    denom = bid_size + ask_size
    out["top_book_imbalance"] = np.where(denom > 0, (bid_size - ask_size) / denom, np.nan)
    out["trade_price_vs_mid"] = trade_price - out["mid_price"]
    if "action" in out.columns:
        out["is_trade"] = out["action"].astype(str).eq("T")
    else:
        out["is_trade"] = True
    side = out.get("side", pd.Series("", index=out.index)).astype(str).str.upper()
    trade_size = out.get("size", pd.Series(np.nan, index=out.index)).astype(float)
    opposite_best_size = np.select(
        [side.eq("B"), side.eq("A") | side.eq("S")],
        [ask_size, bid_size],
        default=np.nan,
    )
    same_side_best_size = np.select(
        [side.eq("B"), side.eq("A") | side.eq("S")],
        [bid_size, ask_size],
        default=np.nan,
    )
    valid_opposite_depth = np.asarray(opposite_best_size, dtype=float) > 0.0
    is_trade = out["is_trade"].fillna(False).astype(bool)
    out["opposite_best_size"] = opposite_best_size
    out["same_side_best_size"] = same_side_best_size
    out["trade_size_to_opposite_best_size"] = np.where(
        valid_opposite_depth,
        trade_size / np.asarray(opposite_best_size, dtype=float),
        np.nan,
    )
    out["top_book_depth_exhausted"] = is_trade & valid_opposite_depth & trade_size.ge(opposite_best_size)
    out["zero_impact_depth_supported"] = is_trade & valid_opposite_depth & trade_size.lt(opposite_best_size)
    out["top_book_excess_trade_size"] = np.where(
        is_trade & valid_opposite_depth,
        np.maximum(trade_size - np.asarray(opposite_best_size, dtype=float), 0.0),
        np.nan,
    )
    out["event_time_ny"] = out["ts_event"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    out["minute"] = out["event_time_ny"].dt.floor("min")
    out["trade_date"] = out["event_time_ny"].dt.date.astype("string")
    out["hour"] = out["event_time_ny"].dt.hour
    out["minute_of_day"] = out["event_time_ny"].dt.hour * 60 + out["event_time_ny"].dt.minute
    out["rth_session"] = out["minute_of_day"].between(9 * 60 + 30, 16 * 60, inclusive="left")
    return out


def iter_tbbo_frames(
    source: Path | str,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    max_files: int | None = None,
    rows_per_file: int | None = None,
    tick_size: float = 0.25,
    symbol_regex: str | None = None,
    progress_every: int = 10,
) -> Iterable[pd.DataFrame]:
    source_path = Path(source)
    members = _filtered_tbbo_members(source_path, start=start, end=end, max_files=max_files)
    if source_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(source_path) as zf:
            for idx, member in enumerate(members, start=1):
                if progress_every > 0 and (idx == 1 or idx == len(members) or idx % progress_every == 0):
                    print(f"TBBO member {idx}/{len(members)}: {member}")
                frame = _read_csv_member(
                    source_path,
                    member,
                    nrows=rows_per_file,
                    usecols=lambda col: col in TBBO_USECOLS,
                    zip_file=zf,
                )
                frame["source_member"] = member
                yield normalize_tbbo_frame(frame, tick_size=tick_size, symbol_regex=symbol_regex)
        return

    for idx, member in enumerate(members, start=1):
        if progress_every > 0 and (idx == 1 or idx == len(members) or idx % progress_every == 0):
            print(f"TBBO member {idx}/{len(members)}: {member}")
        frame = _read_csv_member(
            source_path,
            member,
            nrows=rows_per_file,
            usecols=lambda col: col in TBBO_USECOLS,
        )
        frame["source_member"] = member
        yield normalize_tbbo_frame(frame, tick_size=tick_size, symbol_regex=symbol_regex)


def _q(series: pd.Series, q: float) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return np.nan
    return float(clean.quantile(q))


def aggregate_tbbo_minute_stats(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    work = frame.dropna(subset=["minute", "symbol"]).copy()
    if work.empty:
        return pd.DataFrame()
    trades = work[work["is_trade"]].copy()
    grouped = work.groupby(["symbol", "minute"], sort=True)
    base = grouped.agg(
        rows=("minute", "size"),
        trade_date=("trade_date", "first"),
        rth_session=("rth_session", "max"),
        median_mid_price=("mid_price", "median"),
        median_spread_points=("spread_points", "median"),
        p90_spread_points=("spread_points", lambda s: _q(s, 0.90)),
        p95_spread_points=("spread_points", lambda s: _q(s, 0.95)),
        median_spread_ticks=("spread_ticks", "median"),
        p95_spread_ticks=("spread_ticks", lambda s: _q(s, 0.95)),
        mean_bid_size=("bid_sz_00", "mean"),
        mean_ask_size=("ask_sz_00", "mean"),
        median_top_book_imbalance=("top_book_imbalance", "median"),
    ).reset_index()

    if trades.empty:
        base["trade_count"] = 0
        base["trade_size"] = 0.0
        base["median_abs_trade_price_vs_mid"] = np.nan
        base["p95_abs_trade_price_vs_mid"] = np.nan
        base["median_opposite_best_size"] = np.nan
        base["p25_opposite_best_size"] = np.nan
        base["median_trade_size_to_opposite_best_size"] = np.nan
        base["p95_trade_size_to_opposite_best_size"] = np.nan
        base["top_book_depth_exhausted_trade_count"] = 0
        base["top_book_depth_exhausted_trade_size"] = 0.0
        base["top_book_excess_trade_size"] = 0.0
        base["zero_impact_depth_supported_trade_count"] = 0
        base["raw_b_side_count"] = 0
        base["raw_a_side_count"] = 0
        base["top_book_depth_exhausted_trade_pct"] = np.nan
        base["top_book_depth_exhausted_size_share"] = np.nan
        base["zero_impact_depth_supported_trade_pct"] = np.nan
        return base

    trades["abs_trade_price_vs_mid"] = trades["trade_price_vs_mid"].abs()
    trade_grouped = trades.groupby(["symbol", "minute"], sort=True)
    trade_stats = trade_grouped.agg(
        trade_count=("minute", "size"),
        trade_size=("size", "sum"),
        median_trade_size=("size", "median"),
        median_abs_trade_price_vs_mid=("abs_trade_price_vs_mid", "median"),
        p95_abs_trade_price_vs_mid=("abs_trade_price_vs_mid", lambda s: _q(s, 0.95)),
        mean_trade_price_vs_mid=("trade_price_vs_mid", "mean"),
        median_opposite_best_size=("opposite_best_size", "median"),
        p25_opposite_best_size=("opposite_best_size", lambda s: _q(s, 0.25)),
        median_trade_size_to_opposite_best_size=("trade_size_to_opposite_best_size", "median"),
        p95_trade_size_to_opposite_best_size=("trade_size_to_opposite_best_size", lambda s: _q(s, 0.95)),
        top_book_depth_exhausted_trade_count=("top_book_depth_exhausted", "sum"),
        top_book_depth_exhausted_trade_size=(
            "size",
            lambda s: float(s.loc[trades.loc[s.index, "top_book_depth_exhausted"].fillna(False)].sum()),
        ),
        top_book_excess_trade_size=("top_book_excess_trade_size", "sum"),
        zero_impact_depth_supported_trade_count=("zero_impact_depth_supported", "sum"),
        raw_b_side_count=("side", lambda s: int((s.astype(str) == "B").sum())),
        raw_a_side_count=("side", lambda s: int((s.astype(str) == "A").sum())),
        raw_b_side_trade_size=("size", lambda s: float(s.loc[trades.loc[s.index, "side"].astype(str) == "B"].sum())),
        raw_a_side_trade_size=("size", lambda s: float(s.loc[trades.loc[s.index, "side"].astype(str) == "A"].sum())),
    ).reset_index()
    out = base.merge(trade_stats, on=["symbol", "minute"], how="left").fillna(
        {
            "trade_count": 0,
            "trade_size": 0,
            "top_book_depth_exhausted_trade_count": 0,
            "top_book_depth_exhausted_trade_size": 0.0,
            "top_book_excess_trade_size": 0.0,
            "zero_impact_depth_supported_trade_count": 0,
            "raw_b_side_count": 0,
            "raw_a_side_count": 0,
            "raw_b_side_trade_size": 0.0,
            "raw_a_side_trade_size": 0.0,
        }
    )
    out["raw_b_minus_a_trade_size"] = out["raw_b_side_trade_size"] - out["raw_a_side_trade_size"]
    out["raw_b_minus_a_trade_count"] = out["raw_b_side_count"] - out["raw_a_side_count"]
    out["raw_b_minus_a_trade_size_share"] = np.where(
        out["trade_size"].astype(float) > 0.0,
        out["raw_b_minus_a_trade_size"] / out["trade_size"].astype(float),
        np.nan,
    )
    out["top_book_depth_exhausted_trade_pct"] = np.where(
        out["trade_count"].astype(float) > 0.0,
        out["top_book_depth_exhausted_trade_count"].astype(float) / out["trade_count"].astype(float),
        np.nan,
    )
    out["top_book_depth_exhausted_size_share"] = np.where(
        out["trade_size"].astype(float) > 0.0,
        out["top_book_depth_exhausted_trade_size"].astype(float) / out["trade_size"].astype(float),
        np.nan,
    )
    out["zero_impact_depth_supported_trade_pct"] = np.where(
        out["trade_count"].astype(float) > 0.0,
        out["zero_impact_depth_supported_trade_count"].astype(float) / out["trade_count"].astype(float),
        np.nan,
    )
    return out


def aggregate_tbbo_daily_stats(minute_stats: pd.DataFrame) -> pd.DataFrame:
    if minute_stats.empty:
        return pd.DataFrame()
    work = minute_stats.copy()
    grouped = work.groupby(["symbol", "trade_date"], sort=True)
    return grouped.agg(
        minutes=("minute", "size"),
        rth_minutes=("rth_session", "sum"),
        total_trades=("trade_count", "sum"),
        total_trade_size=("trade_size", "sum"),
        top_book_depth_exhausted_trade_count=("top_book_depth_exhausted_trade_count", "sum"),
        top_book_depth_exhausted_trade_size=("top_book_depth_exhausted_trade_size", "sum"),
        top_book_excess_trade_size=("top_book_excess_trade_size", "sum"),
        zero_impact_depth_supported_trade_count=("zero_impact_depth_supported_trade_count", "sum"),
        median_trade_size_to_opposite_best_size=("median_trade_size_to_opposite_best_size", "median"),
        p95_trade_size_to_opposite_best_size=("p95_trade_size_to_opposite_best_size", "median"),
        median_top_book_depth_exhausted_trade_pct=("top_book_depth_exhausted_trade_pct", "median"),
        median_zero_impact_depth_supported_trade_pct=("zero_impact_depth_supported_trade_pct", "median"),
        raw_b_side_trade_size=("raw_b_side_trade_size", "sum"),
        raw_a_side_trade_size=("raw_a_side_trade_size", "sum"),
        raw_b_minus_a_trade_size=("raw_b_minus_a_trade_size", "sum"),
        median_spread_points=("median_spread_points", "median"),
        p95_spread_points=("p95_spread_points", "median"),
        median_spread_ticks=("median_spread_ticks", "median"),
        p95_abs_trade_price_vs_mid=("p95_abs_trade_price_vs_mid", "median"),
        median_top_book_imbalance=("median_top_book_imbalance", "median"),
    ).reset_index()


def build_tbbo_execution_stats_from_source(
    source: Path | str,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    max_files: int | None = None,
    rows_per_file: int | None = None,
    tick_size: float = 0.25,
    symbol_regex: str | None = None,
    progress_every: int = 10,
) -> TbboExecutionStats:
    minute_frames: list[pd.DataFrame] = []
    for frame in iter_tbbo_frames(
        source,
        start=start,
        end=end,
        max_files=max_files,
        rows_per_file=rows_per_file,
        tick_size=tick_size,
        symbol_regex=symbol_regex,
        progress_every=progress_every,
    ):
        minute = aggregate_tbbo_minute_stats(frame)
        if not minute.empty:
            minute_frames.append(minute)
    if not minute_frames:
        empty = pd.DataFrame()
        return TbboExecutionStats(minute_stats=empty, daily_stats=empty)
    minute_stats = pd.concat(minute_frames, ignore_index=True)
    minute_stats = minute_stats.sort_values(["symbol", "minute"]).reset_index(drop=True)
    daily_stats = aggregate_tbbo_daily_stats(minute_stats)
    return TbboExecutionStats(minute_stats=minute_stats, daily_stats=daily_stats)
