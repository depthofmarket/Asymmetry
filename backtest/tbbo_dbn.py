from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator
import re
import struct

import numpy as np
import pandas as pd
import zstandard as zstd

from backtest.tbbo_execution import (
    TbboExecutionStats,
    aggregate_tbbo_daily_stats,
    aggregate_tbbo_minute_stats,
    normalize_tbbo_frame,
)


DBN_MAGIC_PREFIX = b"DBN"
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
TBBO_RTYPE = 1
TBBO_RECORD_BYTES = 80
DBN_PRICE_SCALE = 1_000_000_000.0
DBN_UNDEF_PRICE_ABS = 9_000_000_000_000_000_000
TBBO_DTYPE = np.dtype(
    [
        ("length", "u1"),
        ("rtype", "u1"),
        ("publisher_id", "<u2"),
        ("instrument_id", "<u4"),
        ("ts_event", "<u8"),
        ("price", "<i8"),
        ("size", "<u4"),
        ("action", "S1"),
        ("side", "S1"),
        ("flags", "S1"),
        ("depth", "S1"),
        ("ts_recv", "<u8"),
        ("ts_in_delta", "<i4"),
        ("sequence", "<u4"),
        ("bid_px_00", "<i8"),
        ("ask_px_00", "<i8"),
        ("bid_sz_00", "<u4"),
        ("ask_sz_00", "<u4"),
        ("bid_ct_00", "<u4"),
        ("ask_ct_00", "<u4"),
    ]
)
if TBBO_DTYPE.itemsize != TBBO_RECORD_BYTES:
    raise RuntimeError(f"Unexpected TBBO dtype size: {TBBO_DTYPE.itemsize}")


@dataclass(frozen=True)
class DbnMetadata:
    version: int
    metadata_length: int
    dataset: str | None
    schema: int | None
    start_ns: int | None
    end_ns: int | None
    symbols: tuple[str, ...]


def read_dbn_metadata(source: Path | str) -> DbnMetadata:
    """Read only the DBN metadata header from a compressed or raw DBN file."""
    with _open_dbn_stream(source) as reader:
        header = _read_exact(reader, 8)
        return _parse_metadata_header(header, _read_exact(reader, _metadata_length(header)))


def infer_dbn_symbol(source: Path | str, fallback: str = "DBN") -> str:
    metadata = read_dbn_metadata(source)
    return _infer_symbol_from_metadata(metadata, fallback=fallback)


def _infer_symbol_from_metadata(metadata: DbnMetadata, fallback: str = "DBN") -> str:
    for symbol in metadata.symbols:
        if re.match(r"^[A-Z]{1,5}\.v\.\d+$", symbol):
            return symbol
    for symbol in metadata.symbols:
        if re.match(r"^[A-Z]{1,5}[A-Z0-9_.-]*$", symbol) and not symbol.isdigit():
            return symbol
    return fallback


def iter_dbn_tbbo_frames(
    source: Path | str,
    *,
    chunk_records: int = 500_000,
    limit_records: int | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    tick_size: float = 0.25,
    symbol: str | None = None,
    symbol_regex: str | None = None,
    progress_every: int = 500_000,
) -> Iterable[pd.DataFrame]:
    """Yield normalized TBBO frames from a Databento DBN file.

    This is intentionally narrow: it supports Databento DBN v1+ files containing
    TBBO records (`rtype=1`). It avoids the Databento Python client so the
    builder can stream large local files with only the existing zstd dependency.
    """
    source_path = Path(source)
    metadata = read_dbn_metadata(source_path)
    start_ns = _timestamp_to_ns(start) if start is not None else None
    end_ns = _timestamp_to_ns(end) if end is not None else None
    seen_records = 0
    emitted_records = 0
    skipped_records = 0
    next_progress = int(progress_every) if progress_every > 0 else 0
    frame_symbol = symbol or _infer_symbol_from_metadata(metadata)

    with _open_dbn_stream(source_path) as reader:
        header = _read_exact(reader, 8)
        _validate_metadata_header(header)
        _read_exact(reader, _metadata_length(header))

        read_size = max(TBBO_RECORD_BYTES, int(chunk_records) * TBBO_RECORD_BYTES)
        for records in _iter_tbbo_record_arrays(reader, read_size=read_size):
            if limit_records is not None and seen_records >= int(limit_records):
                break
            if limit_records is not None:
                records = records[: max(0, int(limit_records) - seen_records)]
            seen_records += int(len(records))
            valid = records["rtype"] == TBBO_RTYPE
            skipped_records += int((~valid).sum())
            records = records[valid]
            if len(records) == 0:
                continue
            if start_ns is not None:
                records = records[records["ts_event"] >= start_ns]
            if end_ns is not None:
                records = records[records["ts_event"] < end_ns]
            if len(records) == 0:
                continue
            emitted_records += int(len(records))
            yield _normalize_dbn_records(
                records,
                symbol=frame_symbol,
                tick_size=tick_size,
                symbol_regex=symbol_regex,
            )
            if next_progress and seen_records >= next_progress:
                print(
                    "DBN TBBO records "
                    f"seen={seen_records:,} emitted={emitted_records:,} skipped={skipped_records:,} "
                    f"dataset={metadata.dataset or 'unknown'} schema={metadata.schema if metadata.schema is not None else 'unknown'}"
                )
                next_progress += int(progress_every)


def iter_dbn_tbbo_minute_stats(
    source: Path | str,
    *,
    chunk_records: int = 500_000,
    limit_records: int | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    tick_size: float = 0.25,
    symbol: str | None = None,
    symbol_regex: str | None = None,
    progress_every: int = 500_000,
    carry_minutes: int = 2,
) -> Iterable[pd.DataFrame]:
    carry = pd.DataFrame()
    for frame in iter_dbn_tbbo_frames(
        source,
        chunk_records=chunk_records,
        limit_records=limit_records,
        start=start,
        end=end,
        tick_size=tick_size,
        symbol=symbol,
        symbol_regex=symbol_regex,
        progress_every=progress_every,
    ):
        if not carry.empty:
            frame = pd.concat([carry, frame], ignore_index=True)
        if frame.empty:
            carry = pd.DataFrame()
            continue
        minutes = frame["minute"].dropna().sort_values().unique()
        if len(minutes) <= max(1, int(carry_minutes)):
            carry = frame
            continue
        cutoff = minutes[-int(carry_minutes)]
        completed = frame.loc[frame["minute"] < cutoff].copy()
        carry = frame.loc[frame["minute"] >= cutoff].copy()
        minute_stats = aggregate_tbbo_minute_stats(completed)
        if not minute_stats.empty:
            yield minute_stats

    if not carry.empty:
        minute_stats = aggregate_tbbo_minute_stats(carry)
        if not minute_stats.empty:
            yield minute_stats


def build_tbbo_execution_stats_from_dbn(
    source: Path | str,
    *,
    chunk_records: int = 500_000,
    limit_records: int | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    tick_size: float = 0.25,
    symbol: str | None = None,
    symbol_regex: str | None = None,
    progress_every: int = 500_000,
) -> TbboExecutionStats:
    minute_frames = [
        frame
        for frame in iter_dbn_tbbo_minute_stats(
            source,
            chunk_records=chunk_records,
            limit_records=limit_records,
            start=start,
            end=end,
            tick_size=tick_size,
            symbol=symbol,
            symbol_regex=symbol_regex,
            progress_every=progress_every,
        )
        if frame is not None and not frame.empty
    ]
    if not minute_frames:
        empty = pd.DataFrame()
        return TbboExecutionStats(minute_stats=empty, daily_stats=empty)
    minute_stats = pd.concat(minute_frames, ignore_index=True)
    minute_stats = minute_stats.sort_values(["symbol", "minute"]).reset_index(drop=True)
    daily_stats = aggregate_tbbo_daily_stats(minute_stats)
    return TbboExecutionStats(minute_stats=minute_stats, daily_stats=daily_stats)


@contextmanager
def _open_dbn_stream(source: Path | str) -> Iterator[BinaryIO]:
    path = Path(source)
    raw = path.open("rb")
    try:
        magic = raw.read(4)
        raw.seek(0)
        if magic == ZSTD_MAGIC:
            dctx = zstd.ZstdDecompressor()
            with dctx.stream_reader(raw, read_across_frames=True) as reader:
                yield reader
        else:
            yield raw
    finally:
        raw.close()


def _read_exact(reader: BinaryIO, length: int) -> bytes:
    data = reader.read(int(length))
    if len(data) != int(length):
        raise ValueError(f"Unexpected end of DBN stream while reading {length} bytes")
    return data


def _metadata_length(header: bytes) -> int:
    _validate_metadata_header(header)
    return int(struct.unpack_from("<I", header, 4)[0])


def _validate_metadata_header(header: bytes) -> None:
    if len(header) != 8 or header[:3] != DBN_MAGIC_PREFIX:
        raise ValueError("Input is not a DBN stream")


def _parse_metadata_header(header: bytes, payload: bytes) -> DbnMetadata:
    _validate_metadata_header(header)
    version = int(header[3])
    length = int(struct.unpack_from("<I", header, 4)[0])
    dataset = _read_cstr(payload[:16]) if len(payload) >= 16 else None
    schema = int(struct.unpack_from("<H", payload, 16)[0]) if len(payload) >= 18 else None
    start_ns = int(struct.unpack_from("<Q", payload, 18)[0]) if len(payload) >= 26 else None
    end_ns = int(struct.unpack_from("<Q", payload, 26)[0]) if len(payload) >= 34 else None
    symbols = tuple(_extract_printable_symbols(payload))
    return DbnMetadata(
        version=version,
        metadata_length=length,
        dataset=dataset,
        schema=schema,
        start_ns=start_ns,
        end_ns=end_ns,
        symbols=symbols,
    )


def _extract_printable_symbols(payload: bytes) -> list[str]:
    strings = []
    for raw in re.findall(rb"[A-Za-z0-9_.-]{2,}", payload):
        value = raw.decode("ascii", errors="ignore").strip(".")
        if not value or value.isdigit():
            continue
        if value not in strings:
            strings.append(value)
    return strings


def _read_cstr(raw: bytes) -> str | None:
    value = raw.split(b"\0", 1)[0].decode("ascii", errors="ignore").strip()
    return value or None


def _timestamp_to_ns(value: str | pd.Timestamp) -> int:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.value)


def _iter_tbbo_record_arrays(reader: BinaryIO, read_size: int = 8 * 1024 * 1024) -> Iterable[np.ndarray]:
    buffer = b""
    while True:
        chunk = reader.read(read_size)
        if not chunk:
            break
        buffer += chunk
        complete = (len(buffer) // TBBO_RECORD_BYTES) * TBBO_RECORD_BYTES
        if complete == 0:
            continue
        block = buffer[:complete]
        buffer = buffer[complete:]
        records = np.frombuffer(block, dtype=TBBO_DTYPE)
        record_lengths = records["length"].astype("uint16") * 4
        if len(records) and not np.all(record_lengths == TBBO_RECORD_BYTES):
            raise ValueError("Encountered a non-80-byte record in a fixed-width TBBO DBN stream")
        yield records
    if buffer:
        raise ValueError("Truncated DBN record at end of stream")


def _scale_price_array(values: np.ndarray) -> np.ndarray:
    raw = values.astype("int64", copy=False)
    out = raw.astype("float64") / DBN_PRICE_SCALE
    out[np.abs(raw) >= DBN_UNDEF_PRICE_ABS] = np.nan
    return out


def _normalize_dbn_records(
    records: np.ndarray,
    *,
    symbol: str,
    tick_size: float,
    symbol_regex: str | None,
) -> pd.DataFrame:
    action = np.char.decode(records["action"], "ascii", errors="ignore")
    side = np.char.decode(records["side"], "ascii", errors="ignore")
    frame = pd.DataFrame(
        {
            "ts_recv": pd.to_datetime(records["ts_recv"].astype("int64"), unit="ns", utc=True, errors="coerce"),
            "ts_event": pd.to_datetime(records["ts_event"].astype("int64"), unit="ns", utc=True, errors="coerce"),
            "instrument_id": records["instrument_id"].astype("int64"),
            "action": action,
            "side": side,
            "price": _scale_price_array(records["price"]),
            "size": records["size"].astype("int64"),
            "bid_px_00": _scale_price_array(records["bid_px_00"]),
            "ask_px_00": _scale_price_array(records["ask_px_00"]),
            "bid_sz_00": records["bid_sz_00"].astype("int64"),
            "ask_sz_00": records["ask_sz_00"].astype("int64"),
            "bid_ct_00": records["bid_ct_00"].astype("int64"),
            "ask_ct_00": records["ask_ct_00"].astype("int64"),
            "symbol": symbol,
        }
    )
    frame = frame.replace([np.inf, -np.inf], np.nan)
    return normalize_tbbo_frame(frame, tick_size=tick_size, symbol_regex=symbol_regex)
