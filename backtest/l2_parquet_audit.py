from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd


TIMESTAMP_CANDIDATES = (
    "ts_event",
    "ts_recv",
    "timestamp",
    "time",
    "datetime",
    "date_time",
    "event_time",
    "receive_time",
    "ts",
)
SYMBOL_CANDIDATES = ("symbol", "raw_symbol", "instrument_id", "contract", "ticker")
TOP_BID_CANDIDATES = ("bid_px_00", "bid_price_00", "bid_price_0", "bid_price_1", "bid_px_0", "bid")
TOP_ASK_CANDIDATES = ("ask_px_00", "ask_price_00", "ask_price_0", "ask_price_1", "ask_px_0", "ask")
TOP_BID_SIZE_CANDIDATES = ("bid_sz_00", "bid_size_00", "bid_size_0", "bid_size_1", "bid_qty_00", "bid_qty_1")
TOP_ASK_SIZE_CANDIDATES = ("ask_sz_00", "ask_size_00", "ask_size_0", "ask_size_1", "ask_qty_00", "ask_qty_1")


@dataclass(frozen=True)
class ParquetFileSummary:
    path: str
    size_bytes: int
    num_rows: int | None
    num_row_groups: int | None
    columns: tuple[str, ...]


@dataclass(frozen=True)
class L2ColumnMap:
    timestamp: str | None
    symbol: str | None
    bid_price: str | None
    ask_price: str | None
    bid_size: str | None
    ask_size: str | None
    bid_price_levels: tuple[str, ...]
    ask_price_levels: tuple[str, ...]


@dataclass(frozen=True)
class L2ParquetAudit:
    file_manifest: pd.DataFrame
    sample_quality: pd.DataFrame
    schema_summary: dict[str, Any]
    report_md: str


def discover_parquet_files(source: Path | str, *, max_files: int | None = 5) -> list[Path]:
    source_path = Path(source)
    if source_path.is_file():
        files = [source_path] if source_path.suffix.lower() == ".parquet" else []
    elif source_path.is_dir():
        files = sorted(path for path in source_path.rglob("*.parquet") if path.is_file())
    else:
        files = []
    if max_files is not None:
        return files[: max(0, int(max_files))]
    return files


def infer_l2_column_map(columns: Iterable[str]) -> L2ColumnMap:
    cols = tuple(str(col) for col in columns)
    lower_to_original = {col.lower(): col for col in cols}

    def first(candidates: Iterable[str]) -> str | None:
        for candidate in candidates:
            if candidate.lower() in lower_to_original:
                return lower_to_original[candidate.lower()]
        return None

    bid_levels = _price_level_columns(cols, side="bid")
    ask_levels = _price_level_columns(cols, side="ask")
    return L2ColumnMap(
        timestamp=first(TIMESTAMP_CANDIDATES),
        symbol=first(SYMBOL_CANDIDATES),
        bid_price=first(TOP_BID_CANDIDATES) or (bid_levels[0] if bid_levels else None),
        ask_price=first(TOP_ASK_CANDIDATES) or (ask_levels[0] if ask_levels else None),
        bid_size=first(TOP_BID_SIZE_CANDIDATES),
        ask_size=first(TOP_ASK_SIZE_CANDIDATES),
        bid_price_levels=tuple(bid_levels),
        ask_price_levels=tuple(ask_levels),
    )


def inspect_l2_parquet_dataset(
    source: Path | str,
    *,
    max_files: int | None = 5,
    sample_rows: int = 2_000,
    tick_size: float = 0.25,
) -> L2ParquetAudit:
    pq = _require_pyarrow_parquet()
    files = discover_parquet_files(source, max_files=max_files)
    summaries: list[ParquetFileSummary] = []
    quality_rows: list[dict[str, Any]] = []
    all_columns: dict[str, int] = {}

    for path in files:
        parquet_file = pq.ParquetFile(path)
        columns = tuple(parquet_file.schema.names)
        for col in columns:
            all_columns[col] = all_columns.get(col, 0) + 1
        summary = ParquetFileSummary(
            path=str(path),
            size_bytes=path.stat().st_size,
            num_rows=int(parquet_file.metadata.num_rows) if parquet_file.metadata is not None else None,
            num_row_groups=int(parquet_file.metadata.num_row_groups) if parquet_file.metadata is not None else None,
            columns=columns,
        )
        summaries.append(summary)
        if sample_rows > 0:
            column_map = infer_l2_column_map(columns)
            sample = _read_parquet_head(parquet_file, sample_rows=sample_rows, columns=_sample_columns(column_map))
            quality_rows.append(sample_l2_quality(sample, path=str(path), column_map=column_map, tick_size=tick_size))

    file_manifest = pd.DataFrame(
        [
            {
                "path": item.path,
                "size_bytes": item.size_bytes,
                "size_mb": item.size_bytes / (1024 * 1024),
                "num_rows": item.num_rows,
                "num_row_groups": item.num_row_groups,
                "columns": ",".join(item.columns),
            }
            for item in summaries
        ]
    )
    sample_quality = pd.DataFrame(quality_rows)
    schema_summary = {
        "source": str(source),
        "inspected_file_count": len(summaries),
        "max_files": max_files,
        "sample_rows_per_file": int(sample_rows),
        "column_frequency": dict(sorted(all_columns.items())),
        "common_columns": sorted([col for col, count in all_columns.items() if count == len(summaries)]),
    }
    report_md = render_l2_parquet_audit_report(file_manifest, sample_quality, schema_summary)
    return L2ParquetAudit(
        file_manifest=file_manifest,
        sample_quality=sample_quality,
        schema_summary=schema_summary,
        report_md=report_md,
    )


def sample_l2_quality(
    sample: pd.DataFrame,
    *,
    path: str,
    column_map: L2ColumnMap | None = None,
    tick_size: float = 0.25,
) -> dict[str, Any]:
    column_map = column_map or infer_l2_column_map(sample.columns)
    row: dict[str, Any] = {
        "path": path,
        "sample_rows": int(len(sample)),
        "timestamp_col": column_map.timestamp,
        "symbol_col": column_map.symbol,
        "bid_price_col": column_map.bid_price,
        "ask_price_col": column_map.ask_price,
        "bid_size_col": column_map.bid_size,
        "ask_size_col": column_map.ask_size,
        "bid_depth_levels_found": len(column_map.bid_price_levels),
        "ask_depth_levels_found": len(column_map.ask_price_levels),
        "warnings": "",
    }
    warnings: list[str] = []
    if sample.empty:
        warnings.append("empty_sample")
        row["warnings"] = ";".join(warnings)
        return row

    if column_map.timestamp is None:
        warnings.append("missing_timestamp_column")
    else:
        ts = pd.to_datetime(sample[column_map.timestamp], utc=True, errors="coerce")
        row["timestamp_null_pct"] = float(ts.isna().mean())
        if ts.notna().any():
            row["first_timestamp"] = str(ts.dropna().iloc[0])
            row["last_timestamp"] = str(ts.dropna().iloc[-1])
            row["timestamp_monotonic_in_sample"] = bool(ts.dropna().is_monotonic_increasing)
        if ts.isna().mean() > 0.0:
            warnings.append("timestamp_parse_failures")

    if column_map.symbol is not None:
        symbols = sample[column_map.symbol].astype("string").dropna().unique()
        row["symbol_count_in_sample"] = int(len(symbols))
        row["sample_symbols"] = ",".join(map(str, symbols[:10]))

    if column_map.bid_price is None or column_map.ask_price is None:
        warnings.append("missing_top_book_bid_ask")
    else:
        bid = pd.to_numeric(sample[column_map.bid_price], errors="coerce")
        ask = pd.to_numeric(sample[column_map.ask_price], errors="coerce")
        spread = ask - bid
        valid_spread = spread[np.isfinite(spread)]
        row["spread_valid_rows"] = int(valid_spread.size)
        if valid_spread.size:
            row["median_spread_points"] = float(valid_spread.median())
            row["p95_spread_points"] = float(valid_spread.quantile(0.95))
            row["negative_spread_pct"] = float((valid_spread < 0).mean())
            row["zero_or_negative_spread_pct"] = float((valid_spread <= 0).mean())
            row["off_tick_spread_pct"] = float(_off_tick_pct(valid_spread, tick_size=tick_size))
            if (valid_spread < 0).any():
                warnings.append("negative_spreads")
            if _off_tick_pct(valid_spread, tick_size=tick_size) > 0.01:
                warnings.append("spreads_off_tick_grid")
        else:
            warnings.append("no_valid_spreads")

    if column_map.bid_size is not None:
        bid_size = pd.to_numeric(sample[column_map.bid_size], errors="coerce")
        row["nonpositive_bid_size_pct"] = float((bid_size <= 0).mean())
    if column_map.ask_size is not None:
        ask_size = pd.to_numeric(sample[column_map.ask_size], errors="coerce")
        row["nonpositive_ask_size_pct"] = float((ask_size <= 0).mean())

    if column_map.timestamp is not None and column_map.symbol is not None:
        keys = sample[[column_map.timestamp, column_map.symbol]].astype("string")
        row["duplicate_timestamp_symbol_pct"] = float(keys.duplicated().mean())

    row["warnings"] = ";".join(warnings)
    return row


def write_l2_parquet_audit(audit: L2ParquetAudit, out_dir: Path | str) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    manifest_path = out_path / "l2_parquet_file_manifest.csv"
    quality_path = out_path / "l2_parquet_sample_quality.csv"
    schema_path = out_path / "l2_parquet_schema_summary.json"
    report_path = out_path / "l2_parquet_audit.md"
    audit.file_manifest.to_csv(manifest_path, index=False)
    audit.sample_quality.to_csv(quality_path, index=False)
    schema_path.write_text(json.dumps(audit.schema_summary, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(audit.report_md, encoding="utf-8")
    return {
        "manifest_csv": manifest_path,
        "sample_quality_csv": quality_path,
        "schema_json": schema_path,
        "report_md": report_path,
    }


def render_l2_parquet_audit_report(
    file_manifest: pd.DataFrame,
    sample_quality: pd.DataFrame,
    schema_summary: dict[str, Any],
) -> str:
    lines = [
        "# L2 Parquet Dataset Audit",
        "",
        "This is a bounded metadata/sample audit. It is not a backtest, signal scan, or full-history edge test.",
        "",
        "## Scope",
        "",
        f"- Source: `{schema_summary.get('source', '')}`",
        f"- Files inspected: {schema_summary.get('inspected_file_count', 0)}",
        f"- Sample rows per file: {schema_summary.get('sample_rows_per_file', 0)}",
        "",
    ]
    if not file_manifest.empty:
        total_rows = pd.to_numeric(file_manifest.get("num_rows"), errors="coerce").sum()
        total_size_gb = pd.to_numeric(file_manifest.get("size_bytes"), errors="coerce").sum() / (1024**3)
        lines.extend(
            [
                "## File Metadata",
                "",
                f"- Sampled parquet rows: {int(total_rows):,}",
                f"- Sampled parquet size: {total_size_gb:.3f} GB",
                "",
            ]
        )
    if not sample_quality.empty:
        warning_rows = sample_quality[sample_quality["warnings"].astype(str).ne("")]
        lines.extend(["## Sample Quality", ""])
        if warning_rows.empty:
            lines.append("- No sample-level warnings in inspected files.")
        else:
            for _, row in warning_rows.iterrows():
                lines.append(f"- `{row['path']}`: {row['warnings']}")
        lines.append("")
    common_columns = schema_summary.get("common_columns", [])
    if common_columns:
        preview = ", ".join(f"`{col}`" for col in common_columns[:30])
        suffix = " ..." if len(common_columns) > 30 else ""
        lines.extend(["## Common Columns", "", f"{preview}{suffix}", ""])
    lines.extend(
        [
            "## Next Decision",
            "",
            "Use this dataset first for execution realism: spread, depth, queue-pressure, and adverse-selection audits. Do not mine strategy filters from it until the schema, contract roll, timestamp, and bid/ask conventions are verified.",
            "",
        ]
    )
    return "\n".join(lines)


def _price_level_columns(columns: tuple[str, ...], *, side: str) -> list[str]:
    pattern = re.compile(rf"^{side}_(?:px|price)_(\d+)$|^{side}_(?:px|price)_(\d\d)$", re.IGNORECASE)
    found: list[tuple[int, str]] = []
    for col in columns:
        match = pattern.match(col)
        if not match:
            continue
        level_text = next(group for group in match.groups() if group is not None)
        found.append((int(level_text), col))
    return [col for _, col in sorted(found)]


def _sample_columns(column_map: L2ColumnMap) -> list[str] | None:
    cols = [
        column_map.timestamp,
        column_map.symbol,
        column_map.bid_price,
        column_map.ask_price,
        column_map.bid_size,
        column_map.ask_size,
    ]
    selected = [col for col in cols if col is not None]
    return selected or None


def _read_parquet_head(parquet_file: Any, *, sample_rows: int, columns: list[str] | None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    remaining = int(sample_rows)
    for row_group_idx in range(parquet_file.num_row_groups):
        if remaining <= 0:
            break
        table = parquet_file.read_row_group(row_group_idx, columns=columns)
        frame = table.slice(0, remaining).to_pandas()
        frames.append(frame)
        remaining -= len(frame)
    if not frames:
        return pd.DataFrame(columns=columns or [])
    return pd.concat(frames, ignore_index=True)


def _off_tick_pct(values: pd.Series, *, tick_size: float) -> float:
    if tick_size <= 0:
        return 0.0
    clean = pd.to_numeric(values, errors="coerce").dropna().abs()
    if clean.empty:
        return 0.0
    ticks = clean / float(tick_size)
    off_grid = ~np.isclose(ticks, np.round(ticks), atol=1e-7)
    return float(np.mean(off_grid))


def _require_pyarrow_parquet() -> Any:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "Inspecting parquet metadata requires pyarrow. Install it in this environment with "
            "`python -m pip install pyarrow`, then rerun the bounded audit command."
        ) from exc
    return pq
