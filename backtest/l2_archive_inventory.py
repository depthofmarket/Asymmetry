from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
from pathlib import Path
import re
from typing import Iterable
from zipfile import BadZipFile, ZipFile


PARQUET_DATE_RE = re.compile(r"(20\d{6})\.parquet$")


@dataclass(frozen=True)
class L2ZipInventory:
    archive_path: str
    archive_name: str
    status: str
    parquet_file_count: int
    unique_parquet_file_count: int
    duplicate_parquet_file_count: int
    first_date: str
    last_date: str
    first_month: str
    last_month: str
    semesters: str
    assigned_folder: str
    compressed_size_bytes: int
    uncompressed_size_bytes: int
    zip_size_bytes: int
    compression_ratio: float
    error: str = ""


def semester_folder_for_date(yyyymmdd: str) -> str:
    if len(yyyymmdd) < 6 or not yyyymmdd[:6].isdigit():
        raise ValueError(f"Expected yyyymmdd date string, got: {yyyymmdd!r}")
    year = yyyymmdd[:4]
    month = int(yyyymmdd[4:6])
    if 1 <= month <= 6:
        return f"{year}_1st_semester_Jan-Jun"
    if 7 <= month <= 12:
        return f"{year}_2nd_semester_Jul-Dec"
    raise ValueError(f"Invalid month in date string: {yyyymmdd!r}")


def expected_semester_folders(start_year: int = 2020, end_year: int = 2025) -> list[str]:
    folders: list[str] = []
    for year in range(int(start_year), int(end_year) + 1):
        folders.append(f"{year}_1st_semester_Jan-Jun")
        folders.append(f"{year}_2nd_semester_Jul-Dec")
    return folders


def discover_zip_archives(source_dir: Path | str, patterns: Iterable[str]) -> list[Path]:
    root = Path(source_dir).expanduser()
    found: set[Path] = set()
    for pattern in patterns:
        found.update(path for path in root.glob(pattern) if path.is_file() and path.suffix.lower() == ".zip")
    return sorted(found)


def inspect_l2_zip_archive(path: Path | str) -> L2ZipInventory:
    archive = Path(path).expanduser()
    try:
        zip_size = archive.stat().st_size
    except FileNotFoundError:
        return _error_inventory(archive, status="missing", error="archive_not_found")

    try:
        with ZipFile(archive) as zf:
            infos = [info for info in zf.infolist() if info.filename.endswith(".parquet")]
    except BadZipFile as exc:
        return _error_inventory(archive, status="bad_zip", zip_size_bytes=zip_size, error=str(exc))

    names = [Path(info.filename).name for info in infos]
    dates = sorted(
        match.group(1)
        for name in names
        if (match := PARQUET_DATE_RE.search(name)) is not None
    )
    compressed = sum(info.compress_size for info in infos)
    uncompressed = sum(info.file_size for info in infos)
    unique_names = set(names)
    semesters = sorted({semester_folder_for_date(date) for date in dates})
    assigned = _assigned_folder(semesters, dates)
    status = "ok" if dates else "no_dated_parquets"

    return L2ZipInventory(
        archive_path=str(archive),
        archive_name=archive.name,
        status=status,
        parquet_file_count=len(infos),
        unique_parquet_file_count=len(unique_names),
        duplicate_parquet_file_count=len(names) - len(unique_names),
        first_date=dates[0] if dates else "",
        last_date=dates[-1] if dates else "",
        first_month=dates[0][:6] if dates else "",
        last_month=dates[-1][:6] if dates else "",
        semesters=";".join(semesters),
        assigned_folder=assigned,
        compressed_size_bytes=compressed,
        uncompressed_size_bytes=uncompressed,
        zip_size_bytes=zip_size,
        compression_ratio=(uncompressed / compressed) if compressed else 0.0,
    )


def inspect_l2_zip_archives(paths: Iterable[Path | str]) -> list[L2ZipInventory]:
    return [inspect_l2_zip_archive(path) for path in paths]


def write_l2_zip_inventory_csv(inventories: Iterable[L2ZipInventory], path: Path | str) -> Path:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(item) for item in inventories]
    fieldnames = list(L2ZipInventory.__dataclass_fields__.keys())
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def create_semester_folder_skeleton(root: Path | str, *, start_year: int = 2020, end_year: int = 2025) -> list[Path]:
    archive_root = Path(root)
    created: list[Path] = []
    for folder in expected_semester_folders(start_year=start_year, end_year=end_year):
        path = archive_root / folder
        path.mkdir(parents=True, exist_ok=True)
        created.append(path)
    for folder in ("mixed_semesters_review", "unknown_dates_review"):
        path = archive_root / folder
        path.mkdir(parents=True, exist_ok=True)
        created.append(path)
    return created


def _assigned_folder(semesters: list[str], dates: list[str]) -> str:
    if not dates:
        return "unknown_dates_review"
    if len(semesters) == 1:
        return semesters[0]
    return "mixed_semesters_review"


def _error_inventory(
    archive: Path,
    *,
    status: str,
    error: str,
    zip_size_bytes: int = 0,
) -> L2ZipInventory:
    return L2ZipInventory(
        archive_path=str(archive),
        archive_name=archive.name,
        status=status,
        parquet_file_count=0,
        unique_parquet_file_count=0,
        duplicate_parquet_file_count=0,
        first_date="",
        last_date="",
        first_month="",
        last_month="",
        semesters="",
        assigned_folder="unknown_dates_review",
        compressed_size_bytes=0,
        uncompressed_size_bytes=0,
        zip_size_bytes=zip_size_bytes,
        compression_ratio=0.0,
        error=error,
    )
