from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


GROUP_COLUMNS = ["trade_date", "direction", "setup_tag"]


@dataclass(frozen=True)
class L2ExecutionComparisonArtifacts:
    normalized_trades: pd.DataFrame
    grouped_summary: pd.DataFrame
    comparison: pd.DataFrame
    report_md: str


@dataclass(frozen=True)
class L2ExecutionComparisonPaths:
    normalized_trades_csv: Path
    grouped_summary_csv: Path
    comparison_csv: Path
    report_md: Path


def compare_l2_vs_bar_execution(
    bar_trades: pd.DataFrame,
    l2_trades: pd.DataFrame,
    *,
    timezone: str = "America/New_York",
) -> L2ExecutionComparisonArtifacts:
    normalized = pd.concat(
        [
            _normalize_trade_frame(bar_trades, source="bar_assumed", timezone=timezone),
            _normalize_trade_frame(l2_trades, source="l2_filled", timezone=timezone),
        ],
        ignore_index=True,
    )
    grouped = _group_execution_summary(normalized)
    comparison = _comparison_from_grouped(grouped)
    return L2ExecutionComparisonArtifacts(
        normalized_trades=normalized,
        grouped_summary=grouped,
        comparison=comparison,
        report_md=render_l2_execution_comparison_report(comparison, grouped),
    )


def write_l2_execution_comparison(
    bar_trades_csv: Path | str,
    l2_trades_csv: Path | str,
    out_dir: Path | str,
    *,
    prefix: str = "l2_execution_comparison",
    timezone: str = "America/New_York",
) -> L2ExecutionComparisonPaths:
    artifacts = compare_l2_vs_bar_execution(
        pd.read_csv(bar_trades_csv),
        pd.read_csv(l2_trades_csv),
        timezone=timezone,
    )
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = L2ExecutionComparisonPaths(
        normalized_trades_csv=out_path / f"{prefix}_normalized_trades.csv",
        grouped_summary_csv=out_path / f"{prefix}_grouped_summary.csv",
        comparison_csv=out_path / f"{prefix}_comparison.csv",
        report_md=out_path / f"{prefix}_report.md",
    )
    artifacts.normalized_trades.to_csv(paths.normalized_trades_csv, index=False)
    artifacts.grouped_summary.to_csv(paths.grouped_summary_csv, index=False)
    artifacts.comparison.to_csv(paths.comparison_csv, index=False)
    paths.report_md.write_text(artifacts.report_md, encoding="utf-8")
    return paths


def render_l2_execution_comparison_report(comparison: pd.DataFrame, grouped_summary: pd.DataFrame) -> str:
    lines = [
        "# L2 Execution Comparison",
        "",
        "This report compares existing OHLCV/bar-assumed trade artifacts against L2-filled trade artifacts. It does not run a backtest, and a favorable comparison is not live-edge proof.",
        "",
    ]
    if comparison.empty:
        lines.extend(["No comparable trade groups were produced.", ""])
    else:
        total_bar = float(comparison["bar_net_pnl"].sum())
        total_l2 = float(comparison["l2_net_pnl"].sum())
        lines.extend(
            [
                "## Summary",
                "",
                f"- Bar-assumed net PnL: ${total_bar:.2f}",
                f"- L2-filled net PnL: ${total_l2:.2f}",
                f"- L2 minus bar delta: ${total_l2 - total_bar:.2f}",
                f"- Compared groups: {int(len(comparison)):,}",
                "",
                "## Group Comparison",
                "",
                _frame_markdown_table(comparison.head(25)),
                "",
            ]
        )
    lines.extend(
        [
            "## Guardrails",
            "",
            "- Use this to find where OHLCV fills are lying, not to create new signal filters from lockbox data.",
            "- Promotion requires the original candidate thesis to survive L2 execution, not just aggregate PnL to remain positive.",
            "",
        ]
    )
    if not grouped_summary.empty:
        lines.extend(["## Source Summary", "", _frame_markdown_table(grouped_summary.head(25)), ""])
    return "\n".join(lines)


def _normalize_trade_frame(frame: pd.DataFrame, *, source: str, timezone: str) -> pd.DataFrame:
    columns = [
        "source",
        "trade_date",
        "entry_time",
        "exit_time",
        "direction",
        "setup_tag",
        "quantity",
        "entry_price",
        "exit_price",
        "pnl",
    ]
    if frame.empty:
        return pd.DataFrame(columns=columns)
    out = pd.DataFrame(index=frame.index)
    out["source"] = source
    out["entry_time"] = _coerce_time(frame, ("entry_time", "entry_ts", "open_time", "time"), timezone=timezone)
    out["exit_time"] = _coerce_time(frame, ("exit_time", "exit_ts", "close_time", "time"), timezone=timezone)
    out["trade_date"] = out["exit_time"].dt.tz_convert(timezone).dt.strftime("%Y-%m-%d")
    out["direction"] = _coerce_direction(frame)
    out["setup_tag"] = _first_text(frame, ("setup_tag", "signal_type", "strategy", "tag"), default="unknown")
    out["quantity"] = _first_numeric(frame, ("quantity", "contracts", "size"), default=1.0)
    out["entry_price"] = _first_numeric(frame, ("entry_price", "entry", "avg_entry_price", "open"), default=np.nan)
    out["exit_price"] = _first_numeric(frame, ("exit_price", "exit", "avg_exit_price", "close"), default=np.nan)
    out["pnl"] = _first_numeric(frame, ("pnl", "net_pnl", "realized_pnl", "pnl_dollars"), default=np.nan)
    out = out.dropna(subset=["exit_time"]).reset_index(drop=True)
    return out.loc[:, columns]


def _group_execution_summary(normalized: pd.DataFrame) -> pd.DataFrame:
    columns = ["source", *GROUP_COLUMNS, "trades", "net_pnl", "avg_entry_price", "avg_exit_price", "avg_quantity"]
    if normalized.empty:
        return pd.DataFrame(columns=columns)
    work = normalized.copy()
    for col in ("pnl", "entry_price", "exit_price", "quantity"):
        work[col] = pd.to_numeric(work[col], errors="coerce")
    grouped = (
        work.groupby(["source", *GROUP_COLUMNS], dropna=False)
        .agg(
            trades=("pnl", "size"),
            net_pnl=("pnl", "sum"),
            avg_entry_price=("entry_price", "mean"),
            avg_exit_price=("exit_price", "mean"),
            avg_quantity=("quantity", "mean"),
        )
        .reset_index()
    )
    return grouped.loc[:, columns]


def _comparison_from_grouped(grouped: pd.DataFrame) -> pd.DataFrame:
    columns = [
        *GROUP_COLUMNS,
        "bar_trades",
        "l2_trades",
        "trade_count_delta",
        "bar_net_pnl",
        "l2_net_pnl",
        "net_pnl_delta",
        "bar_avg_entry_price",
        "l2_avg_entry_price",
        "entry_price_delta",
        "bar_avg_exit_price",
        "l2_avg_exit_price",
        "exit_price_delta",
    ]
    if grouped.empty:
        return pd.DataFrame(columns=columns)
    bar = _source_summary(grouped, "bar_assumed", "bar")
    l2 = _source_summary(grouped, "l2_filled", "l2")
    merged = bar.merge(l2, on=GROUP_COLUMNS, how="outer")
    for col in ("bar_trades", "l2_trades", "bar_net_pnl", "l2_net_pnl"):
        merged[col] = pd.to_numeric(merged.get(col), errors="coerce").fillna(0.0)
    merged["trade_count_delta"] = merged["l2_trades"] - merged["bar_trades"]
    merged["net_pnl_delta"] = merged["l2_net_pnl"] - merged["bar_net_pnl"]
    merged["entry_price_delta"] = merged["l2_avg_entry_price"] - merged["bar_avg_entry_price"]
    merged["exit_price_delta"] = merged["l2_avg_exit_price"] - merged["bar_avg_exit_price"]
    return merged.loc[:, columns].sort_values(GROUP_COLUMNS).reset_index(drop=True)


def _source_summary(grouped: pd.DataFrame, source: str, prefix: str) -> pd.DataFrame:
    frame = grouped.loc[grouped["source"].astype(str).eq(source)].copy()
    if frame.empty:
        return pd.DataFrame(columns=[*GROUP_COLUMNS, f"{prefix}_trades", f"{prefix}_net_pnl", f"{prefix}_avg_entry_price", f"{prefix}_avg_exit_price"])
    frame = frame.rename(
        columns={
            "trades": f"{prefix}_trades",
            "net_pnl": f"{prefix}_net_pnl",
            "avg_entry_price": f"{prefix}_avg_entry_price",
            "avg_exit_price": f"{prefix}_avg_exit_price",
        }
    )
    return frame.loc[:, [*GROUP_COLUMNS, f"{prefix}_trades", f"{prefix}_net_pnl", f"{prefix}_avg_entry_price", f"{prefix}_avg_exit_price"]]


def _coerce_time(frame: pd.DataFrame, candidates: tuple[str, ...], *, timezone: str) -> pd.Series:
    for col in candidates:
        if col in frame.columns:
            return pd.to_datetime(frame[col], utc=True, errors="coerce")
    return pd.Series(pd.NaT, index=frame.index, dtype=f"datetime64[ns, {timezone}]")


def _coerce_direction(frame: pd.DataFrame) -> pd.Series:
    if "direction" in frame.columns:
        raw = frame["direction"].astype(str).str.lower()
    elif "side" in frame.columns:
        raw = frame["side"].astype(str).str.lower()
    else:
        raw = pd.Series("", index=frame.index, dtype="string")
    return raw.map({"buy": "long", "sell": "short", "long": "long", "short": "short"}).fillna("unknown")


def _first_text(frame: pd.DataFrame, candidates: tuple[str, ...], *, default: str) -> pd.Series:
    for col in candidates:
        if col in frame.columns:
            values = frame[col].astype(str).replace({"": default, "nan": default, "None": default})
            return values.fillna(default)
    return pd.Series(default, index=frame.index, dtype="string")


def _first_numeric(frame: pd.DataFrame, candidates: tuple[str, ...], *, default: float) -> pd.Series:
    for col in candidates:
        if col in frame.columns:
            values = pd.to_numeric(frame[col], errors="coerce")
            return values.fillna(default)
    return pd.Series(default, index=frame.index, dtype="float64")


def _frame_markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_None._"
    columns = [str(col) for col in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(_fmt_cell(row[col]) for col in frame.columns) + " |")
    return "\n".join(lines)


def _fmt_cell(value: object) -> str:
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            return ""
        return f"{float(value):.6g}"
    if pd.isna(value):
        return ""
    return str(value).replace("|", "/")


__all__ = [
    "L2ExecutionComparisonArtifacts",
    "L2ExecutionComparisonPaths",
    "compare_l2_vs_bar_execution",
    "render_l2_execution_comparison_report",
    "write_l2_execution_comparison",
]
