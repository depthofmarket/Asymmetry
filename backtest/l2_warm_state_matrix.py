from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.l2_mbp import L2ParquetSourceRef
from backtest.l2_topbook_execution import L2TopBookExecutionConfig
from backtest.l2_topbook_validation_matrix import discover_l2_date_members
from backtest.l2_warm_state import (
    L2WarmStateWindowConfig,
    build_l2_warm_state_topbook_execution_artifacts,
    write_l2_warm_state_topbook_artifacts,
)
from backtest.tbbo_execution_baseline import build_tbbo_execution_baseline, write_tbbo_execution_baseline


DEFAULT_WARM_STATE_DATES = (
    "20220103",
    "20220629",
    "20230104",
)

DEFAULT_WARM_STATE_WINDOWS = (
    ("rth_open_1m", "09:30:00", "09:31:00"),
    ("rth_midday_1m", "12:00:00", "12:01:00"),
    ("rth_close_1m", "15:59:00", "16:00:00"),
)


@dataclass(frozen=True)
class L2WarmStateWindowSpec:
    name: str
    start_time: str
    end_time: str


@dataclass(frozen=True)
class L2WarmStateMatrixResult:
    targets: pd.DataFrame
    warm_state_summary: pd.DataFrame
    quality_summary: pd.DataFrame
    baseline_summary: pd.DataFrame
    report_md: str


def default_warm_state_window_specs() -> tuple[L2WarmStateWindowSpec, ...]:
    return tuple(L2WarmStateWindowSpec(*item) for item in DEFAULT_WARM_STATE_WINDOWS)


def build_l2_warm_state_execution_matrix(
    archive_root: Path | str,
    *,
    target_dates: list[str] | tuple[str, ...] | None = None,
    windows: list[L2WarmStateWindowSpec] | tuple[L2WarmStateWindowSpec, ...] | None = None,
    execution_config: L2TopBookExecutionConfig | None = None,
    warmup_start_row_group: int = 0,
    max_row_groups: int | None = None,
    max_rows: int | None = None,
    stale_level_ttl: str | None = None,
    out_dir: Path | str = "results/research_master/l2_warm_state_execution_matrix",
    write_baselines: bool = True,
    dry_run: bool = False,
) -> L2WarmStateMatrixResult:
    dates = tuple(target_dates or DEFAULT_WARM_STATE_DATES)
    window_specs = tuple(windows or default_warm_state_window_specs())
    discovered = discover_l2_date_members(archive_root, target_dates=dates)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    exec_cfg = execution_config or L2TopBookExecutionConfig(policy="price_key_all_actions_set")

    target_rows: list[dict[str, object]] = []
    warm_frames: list[pd.DataFrame] = []
    quality_frames: list[pd.DataFrame] = []
    baseline_frames: list[pd.DataFrame] = []

    for date in dates:
        item = discovered.get(date)
        for window in window_specs:
            cell_dir = out_path / date / window.name
            base_row = {
                "date": date,
                "window": window.name,
                "window_start": _window_timestamp(date, window.start_time),
                "window_end": _window_timestamp(date, window.end_time),
                "status": "found" if dry_run and item is not None else "pending",
                "source_path": item.source_path if item is not None else "",
                "member": item.member if item is not None else "",
                "duplicate_sources": item.duplicate_sources if item is not None else 0,
                "out_dir": str(cell_dir) if item is not None else "",
                "error": "" if item is not None else "date_not_found_in_archives",
            }
            if item is None:
                base_row["status"] = "missing"
                target_rows.append(base_row)
                continue
            target_rows.append(base_row)
            if dry_run:
                continue

            try:
                ref = L2ParquetSourceRef(
                    source_path=Path(item.source_path),
                    label=f"{Path(item.source_path).name}:{item.member}",
                    zip_member=item.member,
                )
                artifacts = build_l2_warm_state_topbook_execution_artifacts(
                    ref,
                    window_config=L2WarmStateWindowConfig(
                        window_start=str(base_row["window_start"]),
                        window_end=str(base_row["window_end"]),
                        warmup_start_row_group=int(warmup_start_row_group),
                        max_row_groups=int(max_row_groups) if max_row_groups is not None else None,
                        max_rows=int(max_rows) if max_rows is not None else None,
                        stale_level_ttl=stale_level_ttl,
                    ),
                    execution_config=exec_cfg,
                )
                prefix = f"{date}_{window.name}"
                paths = write_l2_warm_state_topbook_artifacts(artifacts, cell_dir, prefix=prefix)

                warm = artifacts.warm_state_summary.copy()
                warm.insert(0, "date", date)
                warm.insert(1, "window", window.name)
                warm["report"] = str(paths["report_md"])
                warm["minute_stats_csv"] = str(paths["minute_stats_csv"])
                warm_frames.append(warm)

                quality = artifacts.quality_summary.copy()
                quality.insert(0, "date", date)
                quality.insert(1, "window", window.name)
                quality["report"] = str(paths["report_md"])
                quality["minute_stats_csv"] = str(paths["minute_stats_csv"])
                quality_frames.append(quality)

                if write_baselines and not artifacts.minute_stats.empty:
                    baseline = build_tbbo_execution_baseline(artifacts.minute_stats)
                    baseline_paths = write_tbbo_execution_baseline(
                        baseline,
                        cell_dir / "tbbo_baseline",
                        prefix=f"{prefix}_tbbo_baseline",
                    )
                    summary = baseline.summary.copy()
                    summary.insert(0, "date", date)
                    summary.insert(1, "window", window.name)
                    summary["baseline_report"] = str(baseline_paths.report_md)
                    baseline_frames.append(summary)

                target_rows[-1]["status"] = "processed"
            except Exception as exc:  # pragma: no cover - defensive artifact logging
                target_rows[-1]["status"] = "error"
                target_rows[-1]["error"] = str(exc)

    targets = pd.DataFrame(target_rows)
    warm_state_summary = pd.concat(warm_frames, ignore_index=True) if warm_frames else pd.DataFrame()
    quality_summary = pd.concat(quality_frames, ignore_index=True) if quality_frames else pd.DataFrame()
    baseline_summary = pd.concat(baseline_frames, ignore_index=True) if baseline_frames else pd.DataFrame()
    report_md = render_l2_warm_state_execution_matrix_report(
        targets,
        warm_state_summary,
        quality_summary,
        baseline_summary,
        execution_config=exec_cfg,
        warmup_start_row_group=warmup_start_row_group,
        max_row_groups=max_row_groups,
        max_rows=max_rows,
        stale_level_ttl=stale_level_ttl,
        dry_run=dry_run,
    )
    return L2WarmStateMatrixResult(
        targets=targets,
        warm_state_summary=warm_state_summary,
        quality_summary=quality_summary,
        baseline_summary=baseline_summary,
        report_md=report_md,
    )


def write_l2_warm_state_execution_matrix(
    result: L2WarmStateMatrixResult,
    out_dir: Path | str,
    *,
    prefix: str = "l2_warm_state_execution_matrix",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "targets_csv": out_path / f"{prefix}_targets.csv",
        "warm_state_summary_csv": out_path / f"{prefix}_warm_state_summary.csv",
        "quality_summary_csv": out_path / f"{prefix}_quality_summary.csv",
        "baseline_summary_csv": out_path / f"{prefix}_baseline_summary.csv",
        "report_md": out_path / f"{prefix}_report.md",
    }
    result.targets.to_csv(paths["targets_csv"], index=False)
    result.warm_state_summary.to_csv(paths["warm_state_summary_csv"], index=False)
    result.quality_summary.to_csv(paths["quality_summary_csv"], index=False)
    result.baseline_summary.to_csv(paths["baseline_summary_csv"], index=False)
    paths["report_md"].write_text(result.report_md, encoding="utf-8")
    return paths


def render_l2_warm_state_execution_matrix_report(
    targets: pd.DataFrame,
    warm_state_summary: pd.DataFrame,
    quality_summary: pd.DataFrame,
    baseline_summary: pd.DataFrame,
    *,
    execution_config: L2TopBookExecutionConfig,
    warmup_start_row_group: int,
    max_row_groups: int | None,
    max_rows: int | None,
    stale_level_ttl: str | None,
    dry_run: bool,
) -> str:
    lines = [
        "# L2 Warm-State Execution Matrix",
        "",
        "This matrix warms structured L2 price-key book state before each requested window. It does not run a strategy backtest and must not be used as signal evidence.",
        "",
        "## Run Config",
        "",
        f"- Dry run: `{dry_run}`",
        f"- Policy: `{execution_config.policy}`",
        f"- Coalesce window: `{execution_config.coalesce_window}`",
        f"- Trade alignment tolerance: `{execution_config.trade_alignment_tolerance}`",
        f"- Warmup start row group: {int(warmup_start_row_group):,}",
        f"- Max row groups: `{max_row_groups if max_row_groups is not None else ''}`",
        f"- Max rows: `{max_rows if max_rows is not None else ''}`",
        f"- Stale level TTL: `{stale_level_ttl or ''}`",
        "",
        "## Targets",
        "",
        _frame_to_markdown(targets, ["date", "window", "status", "member", "error"], max_rows=80),
        "",
    ]
    if not warm_state_summary.empty:
        lines.extend(
            [
                "## Warm-State Coverage",
                "",
                _frame_to_markdown(
                    warm_state_summary,
                    [
                        "date",
                        "window",
                        "warm_start_valid_top_book",
                        "coalesced_quote_rows",
                        "trade_rows",
                        "minute_rows",
                        "rows_read",
                        "row_groups_processed",
                        "warnings",
                    ],
                    max_rows=80,
                ),
                "",
            ]
        )
        rejected = _rejected_cells(warm_state_summary)
        if not rejected.empty:
            lines.extend(
                [
                    "## Rejected Cells",
                    "",
                    "These cells are readable but not accepted as execution-realism evidence.",
                    "",
                    _frame_to_markdown(
                        rejected,
                        [
                            "date",
                            "window",
                            "warm_start_valid_top_book",
                            "coalesced_quote_rows",
                            "minute_rows",
                            "warnings",
                        ],
                        max_rows=80,
                    ),
                    "",
                ]
            )
    if not quality_summary.empty:
        lines.extend(
            [
                "## Top-Book Quality",
                "",
                _frame_to_markdown(
                    quality_summary,
                    [
                        "date",
                        "window",
                        "usable_quote_rows",
                        "usable_trade_rows",
                        "median_spread_ticks",
                        "p95_spread_ticks",
                        "max_observed_spread_ticks",
                    ],
                    max_rows=80,
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
                        "window",
                        "minute_rows",
                        "total_trades",
                        "median_rt_spread_cost_points",
                        "p95_rt_trade_vs_mid_cost_points",
                        "cost_model_verdict",
                    ],
                    max_rows=80,
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Decision Rule",
            "",
            "- Accept a cell only if warm start is valid, quote coverage is non-trivial, and minute rows cover the intended window.",
            "- Treat stale-level TTL as a reconstruction assumption, not feed truth.",
            "- Use accepted cells only for execution-cost realism. Do not mine entry filters from this matrix.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_window_spec(value: str) -> L2WarmStateWindowSpec:
    normalized = value.strip()
    if not normalized:
        raise ValueError("window spec cannot be empty")
    if "=" in normalized:
        name, rest = normalized.split("=", 1)
    else:
        name, rest = normalized.split(":", 1)
    if "-" in rest:
        start, end = rest.split("-", 1)
    else:
        start, end = rest.split(",", 1)
    return L2WarmStateWindowSpec(name=name.strip(), start_time=start.strip(), end_time=end.strip())


def _window_timestamp(date: str, time_value: str) -> str:
    stamp = pd.Timestamp(f"{str(date)[:4]}-{str(date)[4:6]}-{str(date)[6:8]} {time_value}")
    return stamp.strftime("%Y-%m-%d %H:%M:%S")


def _rejected_cells(warm_state_summary: pd.DataFrame) -> pd.DataFrame:
    if warm_state_summary.empty:
        return pd.DataFrame()
    warm_valid = warm_state_summary.get("warm_start_valid_top_book", pd.Series(False, index=warm_state_summary.index))
    quotes = pd.to_numeric(warm_state_summary.get("coalesced_quote_rows"), errors="coerce")
    minutes = pd.to_numeric(warm_state_summary.get("minute_rows"), errors="coerce")
    warning_text = warm_state_summary.get("warnings", pd.Series("", index=warm_state_summary.index)).astype(str)
    mask = ~warm_valid.astype(bool) | quotes.lt(1_000) | minutes.lt(1) | warning_text.ne("")
    return warm_state_summary.loc[mask].copy()


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
