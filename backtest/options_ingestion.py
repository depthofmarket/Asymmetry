from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
import re
from typing import Any
import zipfile

import numpy as np
import pandas as pd


NQ_OPTION_SYMBOL_RE = re.compile(
    r"^(?P<root>[A-Z]+)(?P<month>[FGHJKMNQUVXZ])(?P<year>\d{1,2})\s+(?P<option_type>[CP])(?P<strike>\d+(?:\.\d+)?)$"
)

MONTH_CODE_TO_MONTH = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}


OPTION_SCHEMA_DIRS = {
    "definition": "definition",
    "statistics": "statistics",
    "trades": "trades",
    "ohlcv-1s": "ohlcv-1s",
    "ohlcv-1m": "ohlcv-1m",
}


def _third_friday(year: int, month: int) -> pd.Timestamp:
    first = pd.Timestamp(year=year, month=month, day=1, hour=16)
    days_to_friday = (4 - first.weekday()) % 7
    return first + pd.Timedelta(days=days_to_friday + 14)


def _resolve_contract_year(year_code: str, as_of: pd.Timestamp | None) -> int:
    as_of_year = int(pd.Timestamp.today().year if as_of is None else pd.Timestamp(as_of).year)
    code = int(year_code)
    if len(year_code) == 1:
        decade_base = as_of_year // 10 * 10
        candidates = [decade + code for decade in range(decade_base - 30, decade_base + 31, 10)]
    else:
        century = as_of_year // 100 * 100
        candidates = [century + code, century - 100 + code, century + 100 + code]
    return min(candidates, key=lambda year: (abs(year - as_of_year), year))


def parse_nq_option_symbol(symbol: str, as_of: pd.Timestamp | None = None) -> dict[str, Any] | None:
    match = NQ_OPTION_SYMBOL_RE.match(str(symbol).strip())
    if not match:
        return None
    month = MONTH_CODE_TO_MONTH[match.group("month")]
    year = _resolve_contract_year(match.group("year"), as_of)
    expiration = _third_friday(year, month)
    if as_of is not None and expiration < pd.Timestamp(as_of) - pd.Timedelta(days=45):
        year += 10 if len(match.group("year")) == 1 else 100
        expiration = _third_friday(year, month)
    return {
        "root": match.group("root"),
        "month_code": match.group("month"),
        "contract_year": year,
        "contract_month": month,
        "option_type": match.group("option_type"),
        "strike": float(match.group("strike")),
        "estimated_expiration": expiration,
    }


@dataclass(frozen=True)
class OptionsRawFiles:
    definition: list[Path]
    statistics: list[Path]
    trades: list[Path]
    ohlcv_1s: list[Path]
    ohlcv_1m: list[Path]


def ensure_options_dirs(base_dir: Path | str = "data") -> dict[str, Path]:
    base = Path(base_dir)
    raw_base = base / "raw" / "options_nq"
    processed_base = base / "processed" / "options_nq"
    dirs = {
        "raw_base": raw_base,
        "processed_base": processed_base,
    }
    for schema, dirname in OPTION_SCHEMA_DIRS.items():
        dirs[f"raw_{schema}"] = raw_base / dirname
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def discover_options_raw_files(base_dir: Path | str = "data/raw/options_nq") -> OptionsRawFiles:
    base = Path(base_dir)

    def files(schema_dir: str) -> list[Path]:
        path = base / schema_dir
        if not path.exists():
            return []
        return sorted([p for p in path.iterdir() if p.is_file()])

    return OptionsRawFiles(
        definition=files("definition"),
        statistics=files("statistics"),
        trades=files("trades"),
        ohlcv_1s=files("ohlcv-1s"),
        ohlcv_1m=files("ohlcv-1m"),
    )


def file_manifest(raw_files: OptionsRawFiles) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for schema, paths in {
        "definition": raw_files.definition,
        "statistics": raw_files.statistics,
        "trades": raw_files.trades,
        "ohlcv-1s": raw_files.ohlcv_1s,
        "ohlcv-1m": raw_files.ohlcv_1m,
    }.items():
        for path in paths:
            rows.append(
                {
                    "schema": schema,
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "size_mb": path.stat().st_size / (1024 * 1024),
                    "suffix": path.suffix.lower(),
                }
            )
    return pd.DataFrame(rows)


def schema_csv_suffixes(schema: str) -> tuple[str, ...]:
    base = f".{schema}.csv"
    return (base, f"{base}.zst", f"{base}.zstd")


def is_schema_csv_name(name: str, schema: str) -> bool:
    return name.endswith(schema_csv_suffixes(schema))


def schema_members(path: Path | str, schema: str) -> list[str]:
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            return sorted(name for name in zf.namelist() if is_schema_csv_name(name, schema))
    if path.is_dir():
        return sorted(str(p) for p in path.iterdir() if p.is_file() and is_schema_csv_name(p.name, schema))
    if is_schema_csv_name(path.name, schema):
        return [str(path)]
    return []


def definition_members(path: Path | str) -> list[str]:
    return schema_members(path, "definition")


def _read_csv_member(
    source: Path,
    member: str,
    *,
    nrows: int | None = None,
    usecols: list[str] | None = None,
    zip_file: zipfile.ZipFile | None = None,
) -> pd.DataFrame:
    read_kwargs = {"nrows": nrows, "usecols": usecols, "low_memory": False}
    if usecols is None or callable(usecols) or "quantity" in usecols:
        read_kwargs["dtype"] = {"quantity": "string"}
    if source.suffix.lower() == ".zip":
        if zip_file is None:
            with zipfile.ZipFile(source) as zf:
                return _read_csv_member(source, member, nrows=nrows, usecols=usecols, zip_file=zf)
        with zip_file.open(member) as fh:
            if str(member).endswith((".zst", ".zstd")):
                return _read_zstd_csv(fh, **read_kwargs)
            return pd.read_csv(fh, **read_kwargs)
    member_path = Path(member)
    if member_path.suffix.lower() in {".zst", ".zstd"}:
        with member_path.open("rb") as fh:
            return _read_zstd_csv(fh, **read_kwargs)
    return pd.read_csv(member, **read_kwargs)


def _read_zstd_csv(file_obj, **read_kwargs) -> pd.DataFrame:
    try:
        import zstandard as zstd
    except ImportError as exc:
        raise RuntimeError(
            "Reading *.csv.zst files requires the optional 'zstandard' package. "
            "Install project requirements or run: python -m pip install zstandard"
        ) from exc

    dctx = zstd.ZstdDecompressor()
    with dctx.stream_reader(file_obj) as reader:
        with io.TextIOWrapper(reader, encoding="utf-8") as text:
            return pd.read_csv(text, **read_kwargs)


def _read_definition_member(
    source: Path,
    member: str,
    *,
    nrows: int | None = None,
    usecols: list[str] | None = None,
) -> pd.DataFrame:
    return _read_csv_member(source, member, nrows=nrows, usecols=usecols)


def normalize_option_definitions(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rename = {
        "raw_symbol": "option_symbol",
        "instrument_class": "option_type",
        "underlying": "underlying_symbol",
        "strike_price": "strike",
    }
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})
    for col in ("ts_event", "expiration", "activation"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")
    if "strike" in out.columns:
        out["strike"] = pd.to_numeric(out["strike"], errors="coerce")
    if "option_type" in out.columns:
        out["option_type"] = out["option_type"].astype(str).str.upper().str[0]
        out.loc[~out["option_type"].isin(["C", "P"]), "option_type"] = np.nan
    keep = [
        "ts_event",
        "instrument_id",
        "option_symbol",
        "symbol",
        "underlying_symbol",
        "underlying_id",
        "option_type",
        "strike",
        "expiration",
        "activation",
        "security_update_action",
        "min_price_increment",
        "display_factor",
        "contract_multiplier",
        "source_member",
    ]
    keep = [col for col in keep if col in out.columns]
    return out[keep].drop_duplicates()


def build_definition_sample(
    definition_source: Path | str,
    *,
    max_files: int = 5,
    rows_per_file: int = 1000,
) -> pd.DataFrame:
    source = Path(definition_source)
    members = definition_members(source)[: max(1, int(max_files))]
    if not members:
        return pd.DataFrame()

    frames = []
    preferred_cols = [
        "ts_event",
        "instrument_id",
        "raw_symbol",
        "symbol",
        "underlying",
        "underlying_id",
        "instrument_class",
        "strike_price",
        "expiration",
        "activation",
        "security_update_action",
        "min_price_increment",
        "display_factor",
        "contract_multiplier",
    ]
    for member in members:
        try:
            frame = _read_definition_member(
                source,
                member,
                nrows=max(1, int(rows_per_file)),
                usecols=lambda col: col in preferred_cols,
            )
        except ValueError:
            frame = _read_definition_member(source, member, nrows=max(1, int(rows_per_file)))
        frame["source_member"] = member
        frames.append(normalize_option_definitions(frame))
    return pd.concat(frames, ignore_index=True).drop_duplicates()


def normalize_option_trades(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("ts_recv", "ts_event"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")
    for col in ("price", "size", "instrument_id"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    keep = [
        "ts_event",
        "ts_recv",
        "instrument_id",
        "symbol",
        "price",
        "size",
        "side",
        "action",
        "source_member",
    ]
    keep = [col for col in keep if col in out.columns]
    return out[keep]


def normalize_option_statistics(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("ts_recv", "ts_event", "ts_ref"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")
    numeric_cols = [
        "rtype",
        "publisher_id",
        "instrument_id",
        "price",
        "quantity",
        "sequence",
        "ts_in_delta",
        "stat_type",
        "channel_id",
        "update_action",
        "stat_flags",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    keep = [
        "ts_recv",
        "ts_event",
        "rtype",
        "publisher_id",
        "instrument_id",
        "ts_ref",
        "price",
        "quantity",
        "sequence",
        "ts_in_delta",
        "stat_type",
        "channel_id",
        "update_action",
        "stat_flags",
        "symbol",
        "source_member",
    ]
    keep = [col for col in keep if col in out.columns]
    return out[keep]


def build_schema_sample(
    source_path: Path | str,
    schema: str,
    *,
    max_files: int = 5,
    rows_per_file: int = 1000,
) -> pd.DataFrame:
    source = Path(source_path)
    members = schema_members(source, schema)[: max(1, int(max_files))]
    if not members:
        return pd.DataFrame()

    frames = []
    for member in members:
        frame = _read_csv_member(source, member, nrows=max(1, int(rows_per_file)))
        frame["source_member"] = member
        if schema == "trades":
            frame = normalize_option_trades(frame)
        elif schema == "statistics":
            frame = normalize_option_statistics(frame)
        else:
            for col in ("ts_recv", "ts_event"):
                if col in frame.columns:
                    frame[col] = pd.to_datetime(frame[col], utc=True, errors="coerce")
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def load_options_ohlcv(
    path: Path | str,
    *,
    nrows: int | None = None,
    chunksize: int | None = None,
):
    usecols = ["ts_event", "instrument_id", "open", "high", "low", "close", "volume", "symbol"]
    reader = pd.read_csv(path, usecols=lambda col: col in usecols, nrows=nrows, chunksize=chunksize)

    def normalize(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if "ts_event" in out.columns:
            out["ts_event"] = pd.to_datetime(out["ts_event"], utc=True, errors="coerce")
        for col in ("open", "high", "low", "close", "volume"):
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        return out

    if chunksize is None:
        return normalize(reader)  # type: ignore[arg-type]
    return (normalize(chunk) for chunk in reader)


def write_options_manifest(
    raw_base: Path | str = "data/raw/options_nq",
    out_path: Path | str = "data/processed/options_nq/manifest.csv",
) -> Path:
    manifest = file_manifest(discover_options_raw_files(raw_base))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(out_path, index=False)
    return out_path
