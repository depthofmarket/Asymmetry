from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from backtest.l2_dataset_qa import parse_yyyymmdd
from backtest.l2_mbp import L2DecodeArtifacts, L2ParquetSourceRef, decode_l2_mbp_sources


SOURCE_INDEX_REQUIRED_COLUMNS = (
    "trade_date",
    "archive_path",
    "archive_name",
    "zip_member",
    "compressed_size_bytes",
    "uncompressed_size_bytes",
    "duplicate_count_for_date",
    "duplicate_status",
)


@dataclass(frozen=True)
class L2ResolvedSource:
    trade_date: str
    archive_path: Path
    archive_name: str
    zip_member: str
    compressed_size_bytes: int
    uncompressed_size_bytes: int
    duplicate_count_for_date: int
    duplicate_status: str

    @property
    def label(self) -> str:
        return f"{self.trade_date}:{self.archive_name}:{self.zip_member}"

    def to_decode_ref(self) -> L2ParquetSourceRef:
        return L2ParquetSourceRef(
            source_path=self.archive_path,
            label=self.label,
            zip_member=self.zip_member,
        )


@dataclass(frozen=True)
class L2SourceIndexSelection:
    index_path: Path
    requested_dates: tuple[str, ...]
    resolved_sources: tuple[L2ResolvedSource, ...]
    missing_dates: tuple[str, ...]

    @property
    def refs(self) -> list[L2ParquetSourceRef]:
        return [source.to_decode_ref() for source in self.resolved_sources]

    @property
    def resolved_dates(self) -> tuple[str, ...]:
        return tuple(source.trade_date for source in self.resolved_sources)


def load_l2_source_index(index_path: Path | str) -> pd.DataFrame:
    path = Path(index_path)
    frame = pd.read_csv(path, dtype="string")
    missing = [col for col in SOURCE_INDEX_REQUIRED_COLUMNS if col not in frame.columns]
    if missing:
        raise ValueError(f"L2 source index is missing required column(s): {', '.join(missing)}")

    out = frame.copy()
    out["trade_date"] = out["trade_date"].map(_normalize_yyyymmdd)
    out["zip_member"] = out["zip_member"].astype("string")
    out["archive_path"] = out["archive_path"].astype("string")
    out["archive_name"] = out["archive_name"].astype("string")
    out["duplicate_status"] = out["duplicate_status"].fillna("").astype("string")
    for col in ("compressed_size_bytes", "uncompressed_size_bytes", "duplicate_count_for_date"):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype("int64")
    return out.sort_values(["trade_date", "archive_name", "zip_member"], kind="stable").reset_index(drop=True)


def resolve_l2_source_index(
    index_path: Path | str,
    *,
    trade_dates: Iterable[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    max_dates: int | None = None,
    allow_missing_dates: bool = False,
    allow_duplicate_dates: bool = False,
    require_archive_exists: bool = True,
    repo_root: Path | str | None = None,
) -> L2SourceIndexSelection:
    path = Path(index_path)
    index = load_l2_source_index(path)
    requested = _requested_dates(trade_dates=trade_dates, start_date=start_date, end_date=end_date)
    if max_dates is not None and int(max_dates) > 0:
        requested = requested[: int(max_dates)]

    requested_set = set(requested)
    selected = index.loc[index["trade_date"].isin(requested_set)].copy()
    present_dates = set(selected["trade_date"].astype(str))
    missing_dates = tuple(day for day in requested if day not in present_dates)
    if missing_dates and not allow_missing_dates:
        raise ValueError(f"L2 source index has no source for requested date(s): {', '.join(missing_dates)}")

    duplicate_dates = _duplicate_dates(selected)
    if duplicate_dates and not allow_duplicate_dates:
        raise ValueError(
            "L2 source index has duplicate source rows for requested date(s): "
            f"{', '.join(duplicate_dates)}. Rebuild the manifest or pass allow_duplicate_dates=True for diagnostics."
        )

    sources = tuple(
        _source_from_row(
            row,
            index_path=path,
            repo_root=Path(repo_root) if repo_root is not None else None,
            require_archive_exists=require_archive_exists,
        )
        for _, row in selected.iterrows()
    )
    return L2SourceIndexSelection(
        index_path=path,
        requested_dates=tuple(requested),
        resolved_sources=sources,
        missing_dates=missing_dates,
    )


def decode_l2_source_selection(
    selection: L2SourceIndexSelection,
    *,
    max_rows_per_source: int = 200_000,
    start_row: int = 0,
) -> L2DecodeArtifacts:
    if not selection.resolved_sources:
        return decode_l2_mbp_sources([], max_rows_per_source=max_rows_per_source, start_row_group=start_row)
    return decode_l2_mbp_sources(
        selection.refs,
        max_rows_per_source=int(max_rows_per_source),
        start_row_group=int(start_row),
    )


def _requested_dates(
    *,
    trade_dates: Iterable[str] | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[str, ...]:
    explicit = [_normalize_yyyymmdd(value) for value in trade_dates or ()]
    if explicit and (start_date or end_date):
        raise ValueError("Use either explicit trade_dates or start_date/end_date, not both")
    if explicit:
        return tuple(dict.fromkeys(explicit))
    if not start_date and not end_date:
        raise ValueError("L2 source-index resolution requires at least one trade_date or a start_date/end_date range")
    if not start_date or not end_date:
        raise ValueError("Both start_date and end_date are required for range selection")
    start = parse_yyyymmdd(_normalize_yyyymmdd(start_date))
    end = parse_yyyymmdd(_normalize_yyyymmdd(end_date))
    if end < start:
        raise ValueError("end_date must be on or after start_date")
    return tuple(day.strftime("%Y%m%d") for day in pd.date_range(start, end, freq="D").date)


def _normalize_yyyymmdd(value: object) -> str:
    raw = str(value).strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    return parse_yyyymmdd(raw).strftime("%Y%m%d")


def _duplicate_dates(selected: pd.DataFrame) -> tuple[str, ...]:
    if selected.empty:
        return ()
    row_counts = selected["trade_date"].astype(str).value_counts()
    duplicate_by_rows = set(row_counts.loc[row_counts > 1].index.astype(str))
    duplicate_by_manifest = set(
        selected.loc[pd.to_numeric(selected["duplicate_count_for_date"], errors="coerce").fillna(0) > 1, "trade_date"]
        .astype(str)
        .unique()
    )
    return tuple(sorted(duplicate_by_rows | duplicate_by_manifest))


def _source_from_row(
    row: pd.Series,
    *,
    index_path: Path,
    repo_root: Path | None,
    require_archive_exists: bool,
) -> L2ResolvedSource:
    archive_path = _resolve_archive_path(str(row["archive_path"]), index_path=index_path, repo_root=repo_root)
    if require_archive_exists and not archive_path.exists():
        raise FileNotFoundError(f"L2 archive path from source index does not exist: {archive_path}")
    return L2ResolvedSource(
        trade_date=str(row["trade_date"]),
        archive_path=archive_path,
        archive_name=str(row["archive_name"]),
        zip_member=str(row["zip_member"]),
        compressed_size_bytes=int(row["compressed_size_bytes"]),
        uncompressed_size_bytes=int(row["uncompressed_size_bytes"]),
        duplicate_count_for_date=int(row["duplicate_count_for_date"]),
        duplicate_status=str(row["duplicate_status"]),
    )


def _resolve_archive_path(raw_path: str, *, index_path: Path, repo_root: Path | None) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    if repo_root is not None:
        return repo_root / path
    cwd_path = Path.cwd() / path
    if cwd_path.exists():
        return cwd_path
    index_relative = index_path.resolve().parent / path
    if index_relative.exists():
        return index_relative
    return path


__all__ = [
    "L2ResolvedSource",
    "L2SourceIndexSelection",
    "decode_l2_source_selection",
    "load_l2_source_index",
    "resolve_l2_source_index",
]
