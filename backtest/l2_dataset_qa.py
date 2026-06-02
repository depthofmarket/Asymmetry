from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import calendar
import csv
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile


CSV_DATE_RE = re.compile(r"(20\d{6})\.csv$")


EXPECTED_MARKET_CLOSURES = {
    "20201225": "Christmas Day",
    "20211224": "Christmas Day observed",
    "20230220": "Presidents Day",
    "20230529": "Memorial Day",
    "20230904": "Labor Day",
    "20231225": "Christmas Day",
    "20240115": "Martin Luther King Jr. Day",
    "20240902": "Labor Day",
}


KNOWN_OBSERVANCE_REVIEW = {
    "20231110": "Veterans Day observed; NQ full-session absence should be reviewed",
}


@dataclass(frozen=True)
class L2SourceIndexRow:
    trade_date: str
    month: str
    year: str
    archive_folder: str
    archive_path: str
    archive_name: str
    zip_member: str
    member_name: str
    compressed_size_bytes: int
    uncompressed_size_bytes: int
    duplicate_count_for_date: int
    duplicate_status: str


@dataclass(frozen=True)
class L2MissingDayRow:
    trade_date: str
    month: str
    year: str
    day_of_week: str
    missing_class: str
    expected_absence: bool
    reason: str
    action: str


@dataclass(frozen=True)
class L2MonthCoverageRow:
    month: str
    year: str
    expected_calendar_days: int
    present_unique_days: int
    missing_calendar_days: int
    missing_weekdays: int
    expected_absence_days: int
    source_gap_review_days: int
    duplicate_dates: int
    first_present_date: str
    last_present_date: str


@dataclass(frozen=True)
class L2ArchiveErrorRow:
    archive_path: str
    archive_name: str
    error_class: str
    error: str


@dataclass(frozen=True)
class L2DatasetQa:
    source_index: list[L2SourceIndexRow]
    missing_days: list[L2MissingDayRow]
    month_coverage: list[L2MonthCoverageRow]
    archive_errors: list[L2ArchiveErrorRow]
    archive_root: str
    start_date: str
    end_date: str


def build_l2_dataset_qa(
    archive_root: Path | str,
    *,
    start_date: str,
    end_date: str,
) -> L2DatasetQa:
    root = Path(archive_root)
    start = parse_yyyymmdd(start_date)
    end = parse_yyyymmdd(end_date)
    if end < start:
        raise ValueError("end_date must be on or after start_date")

    rows, errors = build_l2_source_index(root)
    counts_by_date: dict[str, int] = {}
    for row in rows:
        counts_by_date[row.trade_date] = counts_by_date.get(row.trade_date, 0) + 1
    rows = [
        L2SourceIndexRow(
            trade_date=row.trade_date,
            month=row.month,
            year=row.year,
            archive_folder=row.archive_folder,
            archive_path=row.archive_path,
            archive_name=row.archive_name,
            zip_member=row.zip_member,
            member_name=row.member_name,
            compressed_size_bytes=row.compressed_size_bytes,
            uncompressed_size_bytes=row.uncompressed_size_bytes,
            duplicate_count_for_date=counts_by_date[row.trade_date],
            duplicate_status="duplicate" if counts_by_date[row.trade_date] > 1 else "unique",
        )
        for row in rows
    ]

    present_dates = {row.trade_date for row in rows}
    duplicates = {trade_date for trade_date, count in counts_by_date.items() if count > 1}
    missing = [
        classify_missing_day(day)
        for day in iter_dates(start, end)
        if yyyymmdd(day) not in present_dates
    ]
    month_coverage = build_month_coverage(
        start,
        end,
        present_dates=present_dates,
        missing_days=missing,
        duplicate_dates=duplicates,
    )

    return L2DatasetQa(
        source_index=sorted(rows, key=lambda row: (row.trade_date, row.archive_name, row.zip_member)),
        missing_days=missing,
        month_coverage=month_coverage,
        archive_errors=errors,
        archive_root=str(root),
        start_date=start_date,
        end_date=end_date,
    )


def build_l2_source_index(archive_root: Path | str) -> tuple[list[L2SourceIndexRow], list[L2ArchiveErrorRow]]:
    root = Path(archive_root)
    rows: list[L2SourceIndexRow] = []
    errors: list[L2ArchiveErrorRow] = []
    for archive in sorted(root.rglob("*.zip")):
        try:
            with ZipFile(archive) as zf:
                for info in zf.infolist():
                    if info.is_dir() or not info.filename.lower().endswith(".csv"):
                        continue
                    member_name = Path(info.filename).name
                    match = CSV_DATE_RE.search(member_name)
                    if match is None:
                        continue
                    trade_date = match.group(1)
                    rows.append(
                        L2SourceIndexRow(
                            trade_date=trade_date,
                            month=trade_date[:6],
                            year=trade_date[:4],
                            archive_folder=archive.parent.name,
                            archive_path=str(archive),
                            archive_name=archive.name,
                            zip_member=info.filename,
                            member_name=member_name,
                            compressed_size_bytes=int(info.compress_size),
                            uncompressed_size_bytes=int(info.file_size),
                            duplicate_count_for_date=1,
                            duplicate_status="unique",
                        )
                    )
        except BadZipFile as exc:
            errors.append(
                L2ArchiveErrorRow(
                    archive_path=str(archive),
                    archive_name=archive.name,
                    error_class="bad_zip",
                    error=str(exc),
                )
            )
        except OSError as exc:
            errors.append(
                L2ArchiveErrorRow(
                    archive_path=str(archive),
                    archive_name=archive.name,
                    error_class=exc.__class__.__name__,
                    error=str(exc),
                )
            )
    return rows, errors


def classify_missing_day(day: date) -> L2MissingDayRow:
    trade_date = yyyymmdd(day)
    day_name = calendar.day_name[day.weekday()]
    if day.weekday() >= 5:
        missing_class = "weekend"
        expected_absence = True
        reason = "Weekend calendar day"
        action = "none"
    elif trade_date in EXPECTED_MARKET_CLOSURES:
        missing_class = "expected_market_closure"
        expected_absence = True
        reason = EXPECTED_MARKET_CLOSURES[trade_date]
        action = "none"
    elif trade_date in KNOWN_OBSERVANCE_REVIEW:
        missing_class = "observance_review"
        expected_absence = False
        reason = KNOWN_OBSERVANCE_REVIEW[trade_date]
        action = "review_source_gap"
    else:
        missing_class = "source_gap_review"
        expected_absence = False
        reason = "Weekday missing from archive and not in expected-closure list"
        action = "review_source_gap"
    return L2MissingDayRow(
        trade_date=trade_date,
        month=trade_date[:6],
        year=trade_date[:4],
        day_of_week=day_name,
        missing_class=missing_class,
        expected_absence=expected_absence,
        reason=reason,
        action=action,
    )


def build_month_coverage(
    start: date,
    end: date,
    *,
    present_dates: set[str],
    missing_days: list[L2MissingDayRow],
    duplicate_dates: set[str],
) -> list[L2MonthCoverageRow]:
    missing_by_month: dict[str, list[L2MissingDayRow]] = {}
    for row in missing_days:
        missing_by_month.setdefault(row.month, []).append(row)

    months = sorted({yyyymmdd(day)[:6] for day in iter_dates(start, end)})
    rows: list[L2MonthCoverageRow] = []
    for month in months:
        month_start = date(int(month[:4]), int(month[4:6]), 1)
        _, last_day = calendar.monthrange(month_start.year, month_start.month)
        month_end = date(month_start.year, month_start.month, last_day)
        window_start = max(start, month_start)
        window_end = min(end, month_end)
        expected_dates = [yyyymmdd(day) for day in iter_dates(window_start, window_end)]
        present = sorted(day for day in expected_dates if day in present_dates)
        missing = missing_by_month.get(month, [])
        source_gap_review_days = sum(1 for row in missing if row.action == "review_source_gap")
        rows.append(
            L2MonthCoverageRow(
                month=month,
                year=month[:4],
                expected_calendar_days=len(expected_dates),
                present_unique_days=len(present),
                missing_calendar_days=len(missing),
                missing_weekdays=sum(1 for row in missing if row.day_of_week not in {"Saturday", "Sunday"}),
                expected_absence_days=sum(1 for row in missing if row.expected_absence),
                source_gap_review_days=source_gap_review_days,
                duplicate_dates=sum(1 for day in expected_dates if day in duplicate_dates),
                first_present_date=present[0] if present else "",
                last_present_date=present[-1] if present else "",
            )
        )
    return rows


def write_l2_dataset_qa_artifacts(qa: L2DatasetQa, out_dir: Path | str) -> dict[str, Path]:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths = {
        "source_index_csv": root / "l2_source_index.csv",
        "missing_days_csv": root / "l2_missing_days.csv",
        "month_coverage_csv": root / "l2_month_coverage.csv",
        "archive_errors_csv": root / "l2_archive_errors.csv",
        "report_md": root / "l2_dataset_qa_report.md",
    }
    write_dataclass_csv(qa.source_index, paths["source_index_csv"], L2SourceIndexRow)
    write_dataclass_csv(qa.missing_days, paths["missing_days_csv"], L2MissingDayRow)
    write_dataclass_csv(qa.month_coverage, paths["month_coverage_csv"], L2MonthCoverageRow)
    write_dataclass_csv(qa.archive_errors, paths["archive_errors_csv"], L2ArchiveErrorRow)
    paths["report_md"].write_text(render_l2_dataset_qa_report(qa), encoding="utf-8")
    return paths


def render_l2_dataset_qa_report(qa: L2DatasetQa) -> str:
    unique_dates = {row.trade_date for row in qa.source_index}
    duplicate_dates = sorted({row.trade_date for row in qa.source_index if row.duplicate_status == "duplicate"})
    source_gap_rows = [row for row in qa.missing_days if row.action == "review_source_gap"]
    expected_absences = [row for row in qa.missing_days if row.expected_absence]
    lines = [
        "# L2 Dataset QA Report",
        "",
        "This report inventories L2 source files and calendar coverage only. It is not a backtest, strategy replay, or signal scan.",
        "",
        "## Summary",
        "",
        f"- Archive root: `{qa.archive_root}`",
        f"- Requested span: `{qa.start_date}` to `{qa.end_date}`",
        f"- Source rows: {len(qa.source_index):,}",
        f"- Unique source dates: {len(unique_dates):,}",
        f"- First source date: {min(unique_dates) if unique_dates else ''}",
        f"- Last source date: {max(unique_dates) if unique_dates else ''}",
        f"- Missing calendar days: {len(qa.missing_days):,}",
        f"- Expected absences: {len(expected_absences):,}",
        f"- Source gaps requiring review: {len(source_gap_rows):,}",
        f"- Duplicate source dates: {len(duplicate_dates):,}",
        f"- Archive read errors: {len(qa.archive_errors):,}",
        "",
        "## Source Gaps Requiring Review",
        "",
    ]
    if source_gap_rows:
        for row in source_gap_rows:
            lines.append(f"- `{row.trade_date}` {row.day_of_week}: {row.reason}")
    else:
        lines.append("- None")
    lines.extend(["", "## Duplicate Dates", ""])
    if duplicate_dates:
        for trade_date in duplicate_dates:
            lines.append(f"- `{trade_date}`")
    else:
        lines.append("- None")
    lines.extend(["", "## Month Coverage", ""])
    for row in qa.month_coverage:
        lines.append(
            f"- `{row.month}`: present={row.present_unique_days}/{row.expected_calendar_days}, "
            f"missing_weekdays={row.missing_weekdays}, source_gap_review={row.source_gap_review_days}, "
            f"duplicates={row.duplicate_dates}"
        )
    return "\n".join(lines) + "\n"


def write_dataclass_csv(rows: list[object], path: Path, row_type: type[object]) -> None:
    fieldnames = list(row_type.__dataclass_fields__.keys())  # type: ignore[attr-defined]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


def parse_yyyymmdd(value: str) -> date:
    if len(value) != 8 or not value.isdigit():
        raise ValueError(f"Expected YYYYMMDD date string, got: {value!r}")
    return date(int(value[:4]), int(value[4:6]), int(value[6:]))


def yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def iter_dates(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)
