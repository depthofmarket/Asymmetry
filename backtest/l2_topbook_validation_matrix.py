from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from zipfile import BadZipFile, ZipFile

import numpy as np
import pandas as pd

from backtest.l2_mbp import L2ParquetSourceRef, decode_l2_mbp_sources
from backtest.l2_topbook_execution import (
    L2TopBookExecutionConfig,
    build_l2_topbook_execution_artifacts,
    write_l2_topbook_execution_artifacts,
)
from backtest.tbbo_execution_baseline import build_tbbo_execution_baseline, write_tbbo_execution_baseline


DATE_RE = re.compile(r"(20\d{6})\.parquet$")
DEFAULT_VALIDATION_DATES = (
    "20201201",
    "20210104",
    "20210601",
    "20220103",
    "20220629",
    "20230104",
)


@dataclass(frozen=True)
class L2DateMember:
    date: str
    source_path: str
    member: str
    duplicate_sources: int = 0


@dataclass(frozen=True)
class L2ValidationMatrixResult:
    targets: pd.DataFrame
    quality_summary: pd.DataFrame
    baseline_summary: pd.DataFrame
    report_md: str


def discover_l2_date_members(
    archive_root: Path | str,
    *,
    target_dates: list[str] | tuple[str, ...] | None = None,
) -> dict[str, L2DateMember]:
    root = Path(archive_root)
    targets = set(str(date) for date in target_dates) if target_dates else None
    found: dict[str, L2DateMember] = {}
    duplicates: dict[str, int] = {}
    for archive in sorted(root.rglob("*.zip")):
        try:
            with ZipFile(archive) as zf:
                members = sorted(name for name in zf.namelist() if name.endswith(".parquet"))
        except BadZipFile:
            continue
        for member in members:
            match = DATE_RE.search(Path(member).name)
            if not match:
                continue
            date = match.group(1)
            if targets is not None and date not in targets:
                continue
            if date in found:
                duplicates[date] = duplicates.get(date, 0) + 1
                continue
            found[date] = L2DateMember(date=date, source_path=str(archive), member=member)

    for date, duplicate_count in duplicates.items():
        item = found[date]
        found[date] = L2DateMember(
            date=item.date,
            source_path=item.source_path,
            member=item.member,
            duplicate_sources=duplicate_count,
        )
    return found


def build_l2_topbook_validation_matrix(
    archive_root: Path | str,
    *,
    target_dates: list[str] | tuple[str, ...] | None = None,
    config: L2TopBookExecutionConfig | None = None,
    max_rows_per_member: int = 200_000,
    start_row_group: int = 0,
    out_dir: Path | str = "results/research_master/l2_topbook_validation_matrix",
    write_baselines: bool = True,
    dry_run: bool = False,
) -> L2ValidationMatrixResult:
    dates = tuple(target_dates or DEFAULT_VALIDATION_DATES)
    discovered = discover_l2_date_members(archive_root, target_dates=dates)
    target_rows = []
    quality_frames: list[pd.DataFrame] = []
    baseline_frames: list[pd.DataFrame] = []
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    cfg = config or L2TopBookExecutionConfig()

    for date in dates:
        item = discovered.get(date)
        if item is None:
            target_rows.append(
                {
                    "date": date,
                    "status": "missing",
                    "source_path": "",
                    "member": "",
                    "duplicate_sources": 0,
                    "out_dir": "",
                    "error": "date_not_found_in_archives",
                }
            )
            continue

        day_dir = out_path / date
        target_rows.append(
            {
                "date": date,
                "status": "found" if dry_run else "pending",
                "source_path": item.source_path,
                "member": item.member,
                "duplicate_sources": item.duplicate_sources,
                "out_dir": str(day_dir),
                "error": "",
            }
        )
        if dry_run:
            continue

        try:
            refs = [
                L2ParquetSourceRef(
                    source_path=Path(item.source_path),
                    label=f"{Path(item.source_path).name}:{item.member}",
                    zip_member=item.member,
                )
            ]
            decoded = decode_l2_mbp_sources(
                refs,
                max_rows_per_source=int(max_rows_per_member),
                start_row_group=int(start_row_group),
            )
            artifacts = build_l2_topbook_execution_artifacts(decoded.events, config=cfg)
            paths = write_l2_topbook_execution_artifacts(artifacts, day_dir, prefix=date)

            quality = artifacts.quality_summary.copy()
            quality.insert(0, "date", date)
            quality["source_path"] = item.source_path
            quality["member"] = item.member
            quality["topbook_report"] = str(paths["report_md"])
            quality["minute_stats_csv"] = str(paths["minute_stats_csv"])
            quality_frames.append(quality)

            if write_baselines:
                baseline = build_tbbo_execution_baseline(artifacts.minute_stats)
                baseline_paths = write_tbbo_execution_baseline(
                    baseline,
                    day_dir / "tbbo_baseline",
                    prefix=f"{date}_tbbo_baseline",
                )
                summary = baseline.summary.copy()
                summary.insert(0, "date", date)
                summary["baseline_report"] = str(baseline_paths.report_md)
                baseline_frames.append(summary)

            target_rows[-1]["status"] = "processed"
        except Exception as exc:  # pragma: no cover - defensive artifact logging
            target_rows[-1]["status"] = "error"
            target_rows[-1]["error"] = str(exc)

    targets = pd.DataFrame(target_rows)
    quality_summary = pd.concat(quality_frames, ignore_index=True) if quality_frames else pd.DataFrame()
    baseline_summary = pd.concat(baseline_frames, ignore_index=True) if baseline_frames else pd.DataFrame()
    report_md = render_l2_topbook_validation_matrix_report(
        targets,
        quality_summary,
        baseline_summary,
        config=cfg,
        max_rows_per_member=max_rows_per_member,
        start_row_group=start_row_group,
        dry_run=dry_run,
    )
    return L2ValidationMatrixResult(
        targets=targets,
        quality_summary=quality_summary,
        baseline_summary=baseline_summary,
        report_md=report_md,
    )


def write_l2_topbook_validation_matrix(
    result: L2ValidationMatrixResult,
    out_dir: Path | str,
    *,
    prefix: str = "l2_topbook_validation_matrix",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "targets_csv": out_path / f"{prefix}_targets.csv",
        "quality_summary_csv": out_path / f"{prefix}_quality_summary.csv",
        "baseline_summary_csv": out_path / f"{prefix}_baseline_summary.csv",
        "report_md": out_path / f"{prefix}_report.md",
    }
    result.targets.to_csv(paths["targets_csv"], index=False)
    result.quality_summary.to_csv(paths["quality_summary_csv"], index=False)
    result.baseline_summary.to_csv(paths["baseline_summary_csv"], index=False)
    paths["report_md"].write_text(result.report_md, encoding="utf-8")
    return paths


def render_l2_topbook_validation_matrix_report(
    targets: pd.DataFrame,
    quality_summary: pd.DataFrame,
    baseline_summary: pd.DataFrame,
    *,
    config: L2TopBookExecutionConfig,
    max_rows_per_member: int,
    start_row_group: int,
    dry_run: bool,
) -> str:
    lines = [
        "# L2 Top-Book Validation Matrix",
        "",
        "This is a bounded execution-realism validation matrix. It does not run a strategy backtest and must not be used as signal evidence.",
        "",
        "## Run Config",
        "",
        f"- Dry run: `{dry_run}`",
        f"- Max rows per member: {int(max_rows_per_member):,}",
        f"- Start row group: {int(start_row_group):,}",
        f"- Requested policy: `{config.policy}`",
        f"- Coalesce window: `{config.coalesce_window}`",
        f"- Max retained spread: {float(config.max_spread_ticks):.2f} ticks",
        f"- Trade alignment tolerance: `{config.trade_alignment_tolerance}`",
        "",
        "## Targets",
        "",
        _frame_to_markdown(targets, ["date", "status", "member", "duplicate_sources", "error"], max_rows=40),
        "",
    ]
    if not quality_summary.empty:
        lines.extend(
            [
                "## Top-Book Quality",
                "",
                _frame_to_markdown(
                    quality_summary,
                    [
                        "date",
                        "policy",
                        "decoded_rows",
                        "usable_quote_rows",
                        "usable_trade_rows",
                        "minute_rows",
                        "median_spread_ticks",
                        "p95_spread_ticks",
                        "max_observed_spread_ticks",
                        "trade_rows_per_type1_event",
                    ],
                    max_rows=40,
                ),
                "",
            ]
        )
        warnings = _coverage_warnings(quality_summary)
        if not warnings.empty:
            lines.extend(
                [
                    "## Coverage Warnings",
                    "",
                    "Rows in this section are decoded, but the bounded top-book sample is too thin to trust as an execution-cost baseline without a broader warm-state pass.",
                    "",
                    _frame_to_markdown(
                        warnings,
                        [
                            "date",
                            "policy",
                            "source_schemas",
                            "usable_quote_rows",
                            "minute_rows",
                            "quote_rows_per_depth_update",
                            "reason",
                        ],
                        max_rows=40,
                    ),
                    "",
                ]
            )
    if not baseline_summary.empty:
        lines.extend(
            [
                "## Execution Baseline",
                "",
                _frame_to_markdown(
                    baseline_summary,
                    [
                        "date",
                        "minute_rows",
                        "total_trades",
                        "median_rt_spread_cost_points",
                        "p95_rt_spread_cost_points",
                        "median_rt_trade_vs_mid_cost_points",
                        "p95_rt_trade_vs_mid_cost_points",
                        "cost_model_verdict",
                    ],
                    max_rows=40,
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Decision Rule",
            "",
            "- If date-level spread and trade-vs-mid costs are stable across this matrix, expand to month-level processing.",
            "- If one date produces missing rows, extreme spreads, or unstable trade alignment, fix semantics before scaling.",
            "- Full-depth MBP-10 reconstruction remains disabled until depth-level behavior is proven separately.",
            "- Use this matrix for execution-cost realism only, not for entry-filter mining.",
            "",
        ]
    )
    return "\n".join(lines)


def _coverage_warnings(quality_summary: pd.DataFrame) -> pd.DataFrame:
    if quality_summary.empty:
        return pd.DataFrame()
    frame = quality_summary.copy()
    quote_ratio = pd.to_numeric(frame.get("quote_rows_per_depth_update"), errors="coerce")
    minute_rows = pd.to_numeric(frame.get("minute_rows"), errors="coerce")
    usable_quotes = pd.to_numeric(frame.get("usable_quote_rows"), errors="coerce")
    weak_mask = quote_ratio.lt(0.01) | minute_rows.lt(30) | usable_quotes.lt(1_000)
    warnings = frame.loc[weak_mask].copy()
    if warnings.empty:
        return warnings

    reasons = []
    for _, row in warnings.iterrows():
        row_reasons = []
        if float(row.get("quote_rows_per_depth_update", np.nan)) < 0.01:
            row_reasons.append("quote/depth ratio < 1%")
        if float(row.get("minute_rows", np.nan)) < 30:
            row_reasons.append("fewer than 30 minute rows")
        if float(row.get("usable_quote_rows", np.nan)) < 1_000:
            row_reasons.append("fewer than 1,000 usable quotes")
        reasons.append("; ".join(row_reasons))
    warnings["reason"] = reasons
    return warnings


def _frame_to_markdown(df: pd.DataFrame, columns: list[str], *, max_rows: int) -> str:
    if df.empty:
        return "_No rows._"
    existing = [col for col in columns if col in df.columns]
    if not existing:
        return "_No requested columns._"
    view = df.loc[:, existing].head(max_rows)
    lines = [
        "| " + " | ".join(existing) + " |",
        "| " + " | ".join("---" for _ in existing) + " |",
    ]
    for _, row in view.iterrows():
        lines.append("| " + " | ".join(_format_cell(row[col]) for col in existing) + " |")
    if len(df) > max_rows:
        lines.append(f"| ... {len(df) - max_rows} more rows |" + " |" * (len(existing) - 1))
    return "\n".join(lines)


def _format_cell(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        if np.isfinite(value) and float(value).is_integer():
            return str(int(value))
        return f"{value:.4g}"
    return str(value)
