from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable
import zipfile

import numpy as np
import pandas as pd


L2_TIMESTAMP_FORMAT = "%Y%m%d%H%M%S%f"
STRUCTURED_L2_COLUMNS = ("raw_timestamp", "msg_type", "book_level", "price", "size")
MARKETTICK_PARQUET_COLUMNS = ("timestamp", "side", "level", "price", "size", "order_count", "implied_flag")


@dataclass(frozen=True)
class L2ParquetSourceRef:
    source_path: Path
    label: str
    zip_member: str | None = None


@dataclass(frozen=True)
class L2DecodeArtifacts:
    events: pd.DataFrame
    summary: pd.DataFrame
    report_md: str


def select_l2_parquet_sources(
    source: Path | str,
    *,
    members: Iterable[str] | None = None,
    member_glob: str = "*.parquet",
    max_members: int | None = 1,
) -> list[L2ParquetSourceRef]:
    source_path = Path(source)
    requested_members = list(members or [])
    if source_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(source_path) as zf:
            names = sorted(name for name in zf.namelist() if name.lower().endswith((".parquet", ".csv")))
        if requested_members:
            selected = [name for name in requested_members if name in names]
            missing = sorted(set(requested_members) - set(selected))
            if missing:
                raise ValueError(f"Zip member(s) not found: {', '.join(missing)}")
        else:
            selected = [name for name in names if fnmatch(name, member_glob)]
        if max_members is not None:
            selected = selected[: max(0, int(max_members))]
        return [
            L2ParquetSourceRef(
                source_path=source_path,
                label=f"{source_path.name}:{member}",
                zip_member=member,
            )
            for member in selected
        ]

    if source_path.is_file():
        if source_path.suffix.lower() not in {".parquet", ".csv"}:
            return []
        return [L2ParquetSourceRef(source_path=source_path, label=str(source_path))]

    if not source_path.is_dir():
        return []

    files = sorted(
        path
        for path in source_path.rglob("*")
        if path.is_file() and path.suffix.lower() in {".parquet", ".csv"}
    )
    if requested_members:
        requested = {str(Path(member)) for member in requested_members}
        files = [path for path in files if str(path.relative_to(source_path)) in requested]
    else:
        files = [path for path in files if fnmatch(str(path.relative_to(source_path)), member_glob)]
    if max_members is not None:
        files = files[: max(0, int(max_members))]
    return [L2ParquetSourceRef(source_path=path, label=str(path)) for path in files]


def decode_l2_mbp_sources(
    source_refs: Iterable[L2ParquetSourceRef],
    *,
    max_rows_per_source: int = 50_000,
    start_row_group: int = 0,
) -> L2DecodeArtifacts:
    frames = [
        decode_l2_mbp_parquet(ref, max_rows=max_rows_per_source, start_row_group=start_row_group)
        for ref in source_refs
    ]
    events = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True) if frames else pd.DataFrame()
    summary = summarize_l2_mbp_events(events)
    return L2DecodeArtifacts(
        events=events,
        summary=summary,
        report_md=render_l2_mbp_decode_report(events, summary),
    )


def decode_l2_mbp_parquet(
    source_ref: L2ParquetSourceRef,
    *,
    max_rows: int = 50_000,
    start_row_group: int = 0,
) -> pd.DataFrame:
    if max_rows <= 0:
        raise ValueError("max_rows must be positive for this bounded decoder")
    if start_row_group < 0:
        raise ValueError("start_row_group must be non-negative")

    source_name = source_ref.zip_member or str(source_ref.source_path)
    if source_name.lower().endswith(".csv"):
        records = _read_l2_csv_record_sample(source_ref, max_rows=max_rows, start_row=start_row_group)
        decoded = parse_l2_mbp_records(
            records,
            source_path=str(source_ref.source_path),
            source_member=source_ref.zip_member or "",
            source_label=source_ref.label,
        )
        decoded["parquet_num_rows"] = np.nan
        decoded["parquet_row_groups"] = np.nan
        decoded["sample_start_row_group"] = int(start_row_group)
        decoded["source_format"] = "csv"
        return decoded

    pq, pa = _require_pyarrow()
    if source_ref.zip_member is not None:
        with zipfile.ZipFile(source_ref.source_path) as zf:
            raw = zf.read(source_ref.zip_member)
        parquet_file = pq.ParquetFile(pa.BufferReader(raw))
    else:
        parquet_file = pq.ParquetFile(source_ref.source_path)

    if _is_markettick_parquet_schema(parquet_file.schema.names):
        raw_frame = _read_l2_markettick_parquet_sample(
            parquet_file,
            max_rows=max_rows,
            start_row_group=start_row_group,
        )
        decoded = parse_l2_mbp_markettick_parquet_frame(
            raw_frame,
            source_path=str(source_ref.source_path),
            source_member=source_ref.zip_member or "",
            source_label=source_ref.label,
        )
    elif _is_structured_l2_schema(parquet_file.schema.names):
        raw_frame = _read_l2_structured_sample(parquet_file, max_rows=max_rows, start_row_group=start_row_group)
        decoded = parse_l2_mbp_structured_frame(
            raw_frame,
            source_path=str(source_ref.source_path),
            source_member=source_ref.zip_member or "",
            source_label=source_ref.label,
        )
    else:
        records = _read_l2_record_sample(parquet_file, max_rows=max_rows, start_row_group=start_row_group)
        decoded = parse_l2_mbp_records(
            records,
            source_path=str(source_ref.source_path),
            source_member=source_ref.zip_member or "",
            source_label=source_ref.label,
        )
    decoded["parquet_num_rows"] = int(parquet_file.metadata.num_rows)
    decoded["parquet_row_groups"] = int(parquet_file.metadata.num_row_groups)
    decoded["sample_start_row_group"] = int(start_row_group)
    decoded["source_format"] = "parquet"
    return decoded


def parse_l2_mbp_records(
    records: Iterable[str],
    *,
    source_path: str = "",
    source_member: str = "",
    source_label: str = "",
) -> pd.DataFrame:
    raw = pd.Series([str(record) for record in records if str(record) != ""], dtype="string")
    if raw.empty:
        return pd.DataFrame()

    parts = raw.str.split(";", expand=True)
    field_count = parts.notna().sum(axis=1)

    out = pd.DataFrame(
        {
            "source_label": source_label,
            "source_path": source_path,
            "source_member": source_member,
            "source_schema": "semicolon_1col",
            "raw_record": raw,
            "field_count": field_count.astype("int64"),
            "ts_raw": parts[0].astype("string") if 0 in parts.columns else pd.NA,
            "data_level": _numeric_part(parts, 1),
            "type_code": _numeric_part(parts, 2),
            "price": _numeric_part(parts, 3),
            "size": _numeric_part(parts, 4),
            "level": _numeric_part(parts, 5),
            "action_code": _numeric_part(parts, 6),
        }
    )
    out["event_type_code"] = out["data_level"]
    out["side_or_code"] = out["type_code"]
    out["event_time_utc"] = pd.to_datetime(
        out["ts_raw"].astype("string"),
        format=L2_TIMESTAMP_FORMAT,
        utc=True,
        errors="coerce",
    )
    out["event_time_ny"] = out["event_time_utc"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    out["event_family"] = np.select(
        [
            out["data_level"].eq(2) & out["field_count"].eq(7),
            out["data_level"].eq(1) & out["field_count"].eq(5) & out["type_code"].isin([0, 1]),
            out["data_level"].eq(1) & out["field_count"].eq(5) & out["type_code"].eq(2),
            out["data_level"].eq(1) & out["field_count"].eq(5) & out["type_code"].ge(3),
        ],
        ["depth_update", "l1_quote", "trade_or_market_event", "l1_stat"],
        default="unknown",
    )
    out["action_code_source"] = np.where(out["event_family"].eq("depth_update"), "raw", "")
    out["book_side"] = np.select(
        [
            out["event_family"].eq("depth_update") & out["type_code"].eq(0),
            out["event_family"].eq("depth_update") & out["type_code"].eq(1),
        ],
        ["bid", "ask"],
        default=pd.NA,
    )
    out["l1_side"] = np.select(
        [
            out["event_family"].eq("l1_quote") & out["type_code"].eq(0),
            out["event_family"].eq("l1_quote") & out["type_code"].eq(1),
        ],
        ["bid", "ask"],
        default=pd.NA,
    )
    out["minute"] = out["event_time_ny"].dt.floor("min")
    out["trade_date"] = out["event_time_ny"].dt.date.astype("string")
    return out


def parse_l2_mbp_structured_frame(
    frame: pd.DataFrame,
    *,
    source_path: str = "",
    source_member: str = "",
    source_label: str = "",
) -> pd.DataFrame:
    missing = [col for col in STRUCTURED_L2_COLUMNS if col not in frame.columns]
    if missing:
        raise ValueError(f"Structured L2 parquet is missing required column(s): {', '.join(missing)}")
    if frame.empty:
        return pd.DataFrame()

    raw = frame.loc[:, STRUCTURED_L2_COLUMNS].copy()
    raw_record = raw.astype("string").fillna("").agg(";".join, axis=1)
    data_level = pd.to_numeric(raw["msg_type"], errors="coerce")
    type_code = pd.to_numeric(raw["book_level"], errors="coerce")
    price = pd.to_numeric(raw["price"], errors="coerce")
    size = pd.to_numeric(raw["size"], errors="coerce")

    out = pd.DataFrame(
        {
            "source_label": source_label,
            "source_path": source_path,
            "source_member": source_member,
            "source_schema": "structured_5col",
            "raw_record": raw_record,
            "field_count": 5,
            "ts_raw": raw["raw_timestamp"].astype("string"),
            "data_level": data_level,
            "type_code": type_code,
            "event_type_code": data_level,
            "side_or_code": type_code,
            "price": price,
            "size": size,
            "level": np.nan,
            "action_code": np.where(data_level.eq(2), np.where(size.le(0.0), 2, 1), np.nan),
        }
    )
    out["event_time_utc"] = pd.to_datetime(
        out["ts_raw"].astype("string"),
        format=L2_TIMESTAMP_FORMAT,
        utc=True,
        errors="coerce",
    )
    out["event_time_ny"] = out["event_time_utc"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    out["event_family"] = np.select(
        [
            out["data_level"].eq(2),
            out["data_level"].eq(1) & out["type_code"].isin([0, 1]),
            out["data_level"].eq(1) & out["type_code"].eq(2),
            out["data_level"].eq(1) & out["type_code"].ge(3),
        ],
        ["depth_update", "l1_quote", "trade_or_market_event", "l1_stat"],
        default="unknown",
    )
    out["action_code_source"] = np.select(
        [out["event_family"].eq("depth_update"), out["event_family"].eq("trade_or_market_event")],
        ["synthetic_size_rule", ""],
        default="",
    )
    out["book_side"] = np.select(
        [
            out["event_family"].eq("depth_update") & out["type_code"].eq(0),
            out["event_family"].eq("depth_update") & out["type_code"].eq(1),
        ],
        ["bid", "ask"],
        default=pd.NA,
    )
    out["l1_side"] = np.select(
        [
            out["event_family"].eq("l1_quote") & out["type_code"].eq(0),
            out["event_family"].eq("l1_quote") & out["type_code"].eq(1),
        ],
        ["bid", "ask"],
        default=pd.NA,
    )
    out["minute"] = out["event_time_ny"].dt.floor("min")
    out["trade_date"] = out["event_time_ny"].dt.date.astype("string")
    return out


def parse_l2_mbp_markettick_parquet_frame(
    frame: pd.DataFrame,
    *,
    source_path: str = "",
    source_member: str = "",
    source_label: str = "",
) -> pd.DataFrame:
    missing = [col for col in MARKETTICK_PARQUET_COLUMNS if col not in frame.columns]
    if missing:
        raise ValueError(f"MarketTick L2 parquet is missing required column(s): {', '.join(missing)}")
    if frame.empty:
        return pd.DataFrame()

    raw = frame.loc[:, MARKETTICK_PARQUET_COLUMNS].copy()
    data_level = pd.to_numeric(raw["side"], errors="coerce")
    type_code = pd.to_numeric(raw["level"], errors="coerce")
    price = pd.to_numeric(raw["price"], errors="coerce")
    size = pd.to_numeric(raw["size"], errors="coerce")
    depth_rank = pd.to_numeric(raw["order_count"], errors="coerce")
    action_code = pd.to_numeric(raw["implied_flag"], errors="coerce")
    event_time_utc = pd.to_datetime(raw["timestamp"], utc=True, errors="coerce")
    ts_raw = event_time_utc.dt.strftime(L2_TIMESTAMP_FORMAT)
    field_count = np.where(data_level.eq(2), 7, 5)

    raw_record = pd.DataFrame(
        {
            "ts_raw": ts_raw,
            "data_level": data_level.astype("Int64").astype("string"),
            "type_code": type_code.astype("Int64").astype("string"),
            "price": price.astype("string"),
            "size": size.astype("Int64").astype("string"),
            "level": depth_rank.astype("Int64").astype("string"),
            "action_code": action_code.astype("Int64").astype("string"),
        }
    )
    depth_record = raw_record.loc[:, ["ts_raw", "data_level", "type_code", "price", "size", "level", "action_code"]]
    l1_record = raw_record.loc[:, ["ts_raw", "data_level", "type_code", "price", "size"]]
    raw_record_text = pd.Series(index=raw.index, dtype="string")
    depth_mask = data_level.eq(2)
    raw_record_text.loc[depth_mask] = depth_record.loc[depth_mask].fillna("").agg(";".join, axis=1)
    raw_record_text.loc[~depth_mask] = l1_record.loc[~depth_mask].fillna("").agg(";".join, axis=1)

    out = pd.DataFrame(
        {
            "source_label": source_label,
            "source_path": source_path,
            "source_member": source_member,
            "source_schema": "markettick_7col",
            "raw_record": raw_record_text,
            "field_count": field_count.astype("int64"),
            "ts_raw": ts_raw.astype("string"),
            "data_level": data_level,
            "type_code": type_code,
            "event_type_code": data_level,
            "side_or_code": type_code,
            "price": price,
            "size": size,
            "level": depth_rank,
            "action_code": action_code,
        }
    )
    out["event_time_utc"] = event_time_utc
    out["event_time_ny"] = out["event_time_utc"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    out["event_family"] = np.select(
        [
            out["data_level"].eq(2),
            out["data_level"].eq(1) & out["type_code"].isin([0, 1]),
            out["data_level"].eq(1) & out["type_code"].eq(2),
            out["data_level"].eq(1) & out["type_code"].ge(3),
        ],
        ["depth_update", "l1_quote", "trade_or_market_event", "l1_stat"],
        default="unknown",
    )
    out["action_code_source"] = np.where(out["event_family"].eq("depth_update"), "raw", "")
    out["book_side"] = np.select(
        [
            out["event_family"].eq("depth_update") & out["type_code"].eq(0),
            out["event_family"].eq("depth_update") & out["type_code"].eq(1),
        ],
        ["bid", "ask"],
        default=pd.NA,
    )
    out["l1_side"] = np.select(
        [
            out["event_family"].eq("l1_quote") & out["type_code"].eq(0),
            out["event_family"].eq("l1_quote") & out["type_code"].eq(1),
        ],
        ["bid", "ask"],
        default=pd.NA,
    )
    out["minute"] = out["event_time_ny"].dt.floor("min")
    out["trade_date"] = out["event_time_ny"].dt.date.astype("string")
    return out


def summarize_l2_mbp_events(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for source_label, frame in events.groupby("source_label", dropna=False, sort=True):
        depth = frame.loc[frame["event_family"].eq("depth_update")]
        trades_or_market = frame.loc[frame["event_family"].eq("trade_or_market_event")]
        l1_quotes = frame.loc[frame["event_family"].eq("l1_quote")]
        l1_stats = frame.loc[frame["event_family"].eq("l1_stat")]
        rows.append(
            {
                "source_label": source_label,
                "decoded_rows": len(frame),
                "parquet_num_rows": _first_non_null(frame, "parquet_num_rows"),
                "parquet_row_groups": _first_non_null(frame, "parquet_row_groups"),
                "sample_start_row_group": _first_non_null(frame, "sample_start_row_group"),
                "source_formats": _value_counts_text(frame["source_format"]) if "source_format" in frame else "",
                "sample_first_time_utc": _min_time(frame, "event_time_utc"),
                "sample_last_time_utc": _max_time(frame, "event_time_utc"),
                "source_schemas": _value_counts_text(frame["source_schema"]) if "source_schema" in frame else "",
                "event_type_codes": _value_counts_text(frame["event_type_code"]),
                "data_levels": _value_counts_text(frame["data_level"]) if "data_level" in frame else "",
                "type_codes": _value_counts_text(frame["type_code"]) if "type_code" in frame else "",
                "event_families": _value_counts_text(frame["event_family"]) if "event_family" in frame else "",
                "field_counts": _value_counts_text(frame["field_count"]),
                "depth_rows": len(depth),
                "l1_quote_rows": len(l1_quotes),
                "trade_or_market_rows": len(trades_or_market),
                "l1_stat_rows": len(l1_stats),
                "depth_sides": _value_counts_text(depth["book_side"]) if not depth.empty else "",
                "depth_levels": _value_counts_text(depth["level"]) if not depth.empty else "",
                "depth_action_codes": _value_counts_text(depth["action_code"]) if not depth.empty else "",
                "action_code_sources": (
                    _value_counts_text(depth["action_code_source"]) if "action_code_source" in depth and not depth.empty else ""
                ),
                "trade_or_market_codes": (
                    _value_counts_text(trades_or_market["side_or_code"]) if not trades_or_market.empty else ""
                ),
                "price_min": _numeric_min(frame["price"]),
                "price_max": _numeric_max(frame["price"]),
                "size_min": _numeric_min(frame["size"]),
                "size_max": _numeric_max(frame["size"]),
                "timestamp_parse_failures": int(frame["event_time_utc"].isna().sum()),
                "unknown_family_rows": int(frame["event_family"].eq("unknown").sum()),
            }
        )
    return pd.DataFrame(rows)


def write_l2_mbp_decode_artifacts(
    artifacts: L2DecodeArtifacts,
    out_dir: Path | str,
    *,
    prefix: str = "l2_mbp_decode",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    events_path = out_path / f"{prefix}_events_sample.csv"
    summary_path = out_path / f"{prefix}_summary.csv"
    report_path = out_path / f"{prefix}_report.md"
    artifacts.events.to_csv(events_path, index=False)
    artifacts.summary.to_csv(summary_path, index=False)
    report_path.write_text(artifacts.report_md, encoding="utf-8")
    return {"events_csv": events_path, "summary_csv": summary_path, "report_md": report_path}


def render_l2_mbp_decode_report(events: pd.DataFrame, summary: pd.DataFrame) -> str:
    lines = [
        "# L2 MBP Decode Report",
        "",
        "This is a bounded decode sample. It is not a backtest, full-month scan, or signal-mining pass.",
        "",
    ]
    if events.empty:
        lines.extend(["No events decoded.", ""])
        return "\n".join(lines)

    lines.extend(
        [
            "## Interpretation",
            "",
            "- `event_type_code=2` with seven fields is treated as a depth update: `timestamp;2;side;price;size;level;action`.",
            "- In MarketTick flat files the second field is data level. `data_level=2` with seven fields is L2 book depth; `data_level=1` with five fields is L1 tick/stat data.",
            "- `type_code=0` is bid, `type_code=1` is ask, and `type_code=2` is last/trade.",
            "- For seven-field L2 rows, field six behaves as depth/rank and field seven behaves as action code: add=0, update=1, remove=2.",
            "- Corrected MarketTick parquet files are treated as `timestamp,side,level,price,size,order_count,implied_flag`, where `side` maps to data level, `level` maps to side/type code, `order_count` maps to depth rank, and `implied_flag` maps to action code.",
            "- Structured five-column files are treated as `raw_timestamp,msg_type,book_level,price,size`; `msg_type` is normalized as data level and `book_level` as type/side code.",
            "- Structured five-column files have no explicit depth rank/action, so deletes are inferred from `size<=0` only for price-keyed top-book diagnostics.",
            "- Only `data_level=1,type_code=2` rows are treated as trade prints; L1 bid/ask ticks are not treated as trades.",
            "",
            "## Sample Summary",
            "",
        ]
    )
    for _, row in summary.iterrows():
        lines.extend(
            [
                f"### {row['source_label']}",
                "",
                f"- Decoded rows: {int(row['decoded_rows']):,}",
                f"- Parquet rows: {_format_count(row['parquet_num_rows'])}",
                f"- Parquet row groups: {_format_count(row.get('parquet_row_groups', 0))}",
                f"- Sample start row group: {int(row.get('sample_start_row_group', 0)):,}",
                f"- Time range UTC: {row['sample_first_time_utc']} to {row['sample_last_time_utc']}",
                f"- Source formats: {row.get('source_formats', '')}",
                f"- Source schemas: {row.get('source_schemas', '')}",
                f"- Event type codes: {row['event_type_codes']}",
                f"- Data levels: {row.get('data_levels', '')}",
                f"- Type codes: {row.get('type_codes', '')}",
                f"- Event families: {row.get('event_families', '')}",
                f"- Field counts: {row['field_counts']}",
                f"- Depth rows: {int(row['depth_rows']):,}",
                f"- L1 quote rows: {int(row.get('l1_quote_rows', 0)):,}",
                f"- Trade/market rows: {int(row['trade_or_market_rows']):,}",
                f"- L1 stat rows: {int(row.get('l1_stat_rows', 0)):,}",
                f"- Depth sides: {row['depth_sides']}",
                f"- Depth action codes: {row['depth_action_codes']}",
                f"- Action code sources: {row.get('action_code_sources', '')}",
                f"- Trade/market subcodes: {row['trade_or_market_codes']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Next Step",
            "",
            "Use this decoder to validate semantics on a few days first. Only after side/action codes are verified should we reconstruct top-of-book or build execution-realism stats.",
            "",
        ]
    )
    return "\n".join(lines)


def _read_l2_record_sample(parquet_file, *, max_rows: int, start_row_group: int = 0) -> list[str]:
    names = parquet_file.schema.names
    if len(names) != 1:
        raise ValueError(f"Expected one string column, found {len(names)} columns: {names}")

    column_name = names[0]
    records = [str(column_name)] if start_row_group == 0 else []
    remaining = max(0, int(max_rows) - 1)
    if start_row_group > 0:
        remaining = int(max_rows)
    for row_group_idx in range(int(start_row_group), parquet_file.num_row_groups):
        if remaining <= 0:
            break
        table = parquet_file.read_row_group(row_group_idx, columns=[column_name])
        values = table.column(0).slice(0, remaining).to_pylist()
        records.extend(str(value) for value in values if value is not None)
        remaining = max(0, int(max_rows) - len(records))
    return records


def _read_l2_csv_record_sample(
    source_ref: L2ParquetSourceRef,
    *,
    max_rows: int,
    start_row: int = 0,
) -> list[str]:
    rows: list[str] = []
    if source_ref.zip_member is not None:
        with zipfile.ZipFile(source_ref.source_path) as zf, zf.open(source_ref.zip_member) as fh:
            for idx, raw in enumerate(fh):
                if idx < start_row:
                    continue
                if len(rows) >= max_rows:
                    break
                text = raw.decode("utf-8", errors="replace").strip()
                if text:
                    rows.append(text)
        return rows

    with source_ref.source_path.open("r", encoding="utf-8", errors="replace") as fh:
        for idx, text in enumerate(fh):
            if idx < start_row:
                continue
            if len(rows) >= max_rows:
                break
            clean = text.strip()
            if clean:
                rows.append(clean)
    return rows


def _read_l2_structured_sample(parquet_file, *, max_rows: int, start_row_group: int = 0) -> pd.DataFrame:
    remaining = int(max_rows)
    frames: list[pd.DataFrame] = []
    for row_group_idx in range(int(start_row_group), parquet_file.num_row_groups):
        if remaining <= 0:
            break
        table = parquet_file.read_row_group(row_group_idx, columns=list(STRUCTURED_L2_COLUMNS))
        if table.num_rows > remaining:
            table = table.slice(0, remaining)
        frame = table.to_pandas()
        frames.append(frame)
        remaining -= len(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=STRUCTURED_L2_COLUMNS)


def _read_l2_markettick_parquet_sample(parquet_file, *, max_rows: int, start_row_group: int = 0) -> pd.DataFrame:
    remaining = int(max_rows)
    frames: list[pd.DataFrame] = []
    for row_group_idx in range(int(start_row_group), parquet_file.num_row_groups):
        if remaining <= 0:
            break
        table = parquet_file.read_row_group(row_group_idx, columns=list(MARKETTICK_PARQUET_COLUMNS))
        if table.num_rows > remaining:
            table = table.slice(0, remaining)
        frame = table.to_pandas()
        frames.append(frame)
        remaining -= len(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=MARKETTICK_PARQUET_COLUMNS)


def _is_markettick_parquet_schema(names: list[str]) -> bool:
    return set(MARKETTICK_PARQUET_COLUMNS).issubset(set(names))


def _is_structured_l2_schema(names: list[str]) -> bool:
    return set(STRUCTURED_L2_COLUMNS).issubset(set(names))


def _numeric_part(parts: pd.DataFrame, idx: int) -> pd.Series:
    if idx not in parts.columns:
        return pd.Series(np.nan, index=parts.index)
    return pd.to_numeric(parts[idx], errors="coerce")


def _value_counts_text(series: pd.Series, *, max_items: int = 20) -> str:
    if series.empty:
        return ""
    counts = series.dropna().value_counts().sort_index()
    return ";".join(f"{key}:{int(value)}" for key, value in counts.head(max_items).items())


def _numeric_min(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.min()) if not clean.empty else np.nan


def _numeric_max(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.max()) if not clean.empty else np.nan


def _min_time(frame: pd.DataFrame, column: str) -> str:
    clean = pd.to_datetime(frame[column], errors="coerce").dropna()
    return str(clean.min()) if not clean.empty else ""


def _max_time(frame: pd.DataFrame, column: str) -> str:
    clean = pd.to_datetime(frame[column], errors="coerce").dropna()
    return str(clean.max()) if not clean.empty else ""


def _first_non_null(frame: pd.DataFrame, column: str) -> object:
    if column not in frame.columns:
        return np.nan
    clean = frame[column].dropna()
    return clean.iloc[0] if not clean.empty else np.nan


def _format_count(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    if not np.isfinite(numeric):
        return ""
    return f"{int(numeric):,}"


def _require_pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "Decoding this L2 parquet format requires pyarrow. Run `python -m pip install -r requirements.txt`."
        ) from exc
    return pq, pa
