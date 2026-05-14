from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class VwapRepricingReportPaths:
    events_csv: Path
    side_summary_csv: Path
    time_of_day_csv: Path
    period_summary_csv: Path
    warnings_csv: Path
    report_md: Path


def _clock_mask(times: pd.Series, start: str, end: str) -> pd.Series:
    dt = pd.to_datetime(times)
    hour_min = dt.dt.strftime("%H:%M")
    if start <= end:
        return hour_min.ge(start) & hour_min.lt(end)
    return hour_min.ge(start) | hour_min.lt(end)


def build_vwap_repricing_events(
    bars: pd.DataFrame,
    *,
    rth_start: str = "09:30",
    rth_end: str = "16:00",
) -> pd.DataFrame:
    """
    Build a paper-style VWAP continuation sample.

    Each row measures the current completed bar return and labels it with the
    previous completed bar's close-vs-VWAP side. That mirrors the paper's
    "previous candle close above/below VWAP" test and avoids lookahead leakage.
    """
    required = {"time", "close", "vwap"}
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"VWAP repricing report requires columns: {sorted(missing)}")

    work = bars.copy()
    work["time"] = pd.to_datetime(work["time"])
    work = work.sort_values("time").reset_index(drop=True)
    work["date_str"] = work["time"].dt.strftime("%Y-%m-%d")
    work["hour_min"] = work["time"].dt.strftime("%H:%M")
    work = work.loc[_clock_mask(work["time"], rth_start, rth_end)].copy()
    if work.empty:
        return pd.DataFrame()

    grouped = work.groupby("date_str", sort=False)
    work["prev_close"] = grouped["close"].shift(1)
    work["prev_vwap"] = grouped["vwap"].shift(1)
    work["bar_return_points"] = work["close"] - work["prev_close"]
    if "volume" in work.columns:
        work["bar_volume"] = pd.to_numeric(work["volume"], errors="coerce")
    else:
        work["bar_volume"] = np.nan

    side = pd.Series("unknown", index=work.index, dtype="object")
    side.loc[work["prev_close"].gt(work["prev_vwap"])] = "above_vwap"
    side.loc[work["prev_close"].lt(work["prev_vwap"])] = "below_vwap"
    side.loc[work["prev_close"].eq(work["prev_vwap"]) & work["prev_close"].notna()] = "at_vwap"
    work["prior_vwap_side"] = side
    work["prior_vwap_distance_points"] = work["prev_close"] - work["prev_vwap"]
    work["prior_abs_vwap_distance_points"] = work["prior_vwap_distance_points"].abs()

    direction = pd.Series(np.nan, index=work.index, dtype=float)
    direction.loc[work["prior_vwap_side"].eq("above_vwap")] = 1.0
    direction.loc[work["prior_vwap_side"].eq("below_vwap")] = -1.0
    work["vwap_side_direction"] = direction
    work["directional_return_points"] = work["bar_return_points"] * direction
    work["continuation_hit"] = work["directional_return_points"].gt(0)

    valid = work["prior_vwap_side"].isin(["above_vwap", "below_vwap"])
    return work.loc[valid & work["bar_return_points"].notna()].reset_index(drop=True)


def _profit_factor(points: pd.Series) -> float:
    wins = float(points[points > 0].sum())
    losses = abs(float(points[points <= 0].sum()))
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def summarize_vwap_repricing_by_side(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    for side, group in events.groupby("prior_vwap_side", dropna=False, sort=True):
        directional = pd.to_numeric(group["directional_return_points"], errors="coerce").dropna()
        raw = pd.to_numeric(group["bar_return_points"], errors="coerce").dropna()
        rows.append(
            {
                "prior_vwap_side": side,
                "bars": int(len(group)),
                "sample_share_pct": float(len(group) / len(events) * 100.0),
                "total_return_points": float(raw.sum()),
                "avg_return_points": float(raw.mean()) if len(raw) else np.nan,
                "total_directional_points": float(directional.sum()) if len(directional) else np.nan,
                "avg_directional_points": float(directional.mean()) if len(directional) else np.nan,
                "continuation_hit_rate_pct": float((directional > 0).mean() * 100.0) if len(directional) else np.nan,
                "directional_profit_factor": _profit_factor(directional),
                "avg_prior_vwap_distance_points": float(group["prior_vwap_distance_points"].mean()),
                "median_prior_abs_vwap_distance_points": float(group["prior_abs_vwap_distance_points"].median()),
                "total_volume": float(group["bar_volume"].sum()) if "bar_volume" in group else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("prior_vwap_side").reset_index(drop=True)


def summarize_vwap_repricing_by_time(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()

    grouped = events.groupby("hour_min", dropna=False, sort=True)
    out = grouped.agg(
        bars=("directional_return_points", "size"),
        total_directional_points=("directional_return_points", "sum"),
        avg_directional_points=("directional_return_points", "mean"),
        continuation_hit_rate_pct=("continuation_hit", lambda s: float(s.mean() * 100.0)),
        total_volume=("bar_volume", "sum"),
    ).reset_index()
    out["cumulative_directional_points"] = out["total_directional_points"].cumsum()
    return out


def summarize_vwap_repricing_by_period(events: pd.DataFrame, *, period: str = "Q") -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()

    work = events.copy()
    work["period"] = pd.to_datetime(work["time"]).dt.to_period(period).astype(str)
    grouped = work.groupby(["prior_vwap_side", "period"], dropna=False, sort=True)
    out = grouped.agg(
        bars=("directional_return_points", "size"),
        total_directional_points=("directional_return_points", "sum"),
        avg_directional_points=("directional_return_points", "mean"),
        continuation_hit_rate_pct=("continuation_hit", lambda s: float(s.mean() * 100.0)),
    ).reset_index()
    return out


def build_vwap_repricing_warnings(
    side_summary: pd.DataFrame,
    time_summary: pd.DataFrame,
    *,
    midday_start: str = "12:00",
    midday_end: str = "15:00",
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if side_summary.empty:
        return pd.DataFrame(rows)

    side_map = side_summary.set_index("prior_vwap_side")
    if "above_vwap" in side_map.index and float(side_map.loc["above_vwap", "total_return_points"]) <= 0:
        rows.append(
            {
                "warning": "above_vwap_no_positive_repricing",
                "severity": "review",
                "detail": "Bars following an above-VWAP close did not reprice upward in aggregate.",
            }
        )
    if "below_vwap" in side_map.index and float(side_map.loc["below_vwap", "total_return_points"]) >= 0:
        rows.append(
            {
                "warning": "below_vwap_no_negative_repricing",
                "severity": "review",
                "detail": "Bars following a below-VWAP close did not reprice downward in aggregate.",
            }
        )

    if not time_summary.empty:
        midday = time_summary[
            time_summary["hour_min"].astype(str).ge(midday_start)
            & time_summary["hour_min"].astype(str).lt(midday_end)
        ]
        total = float(time_summary["total_directional_points"].sum())
        midday_total = float(midday["total_directional_points"].sum()) if not midday.empty else 0.0
        if total > 0 and midday_total <= 0:
            rows.append(
                {
                    "warning": "midday_vwap_edge_weak_or_negative",
                    "severity": "hypothesis",
                    "detail": f"VWAP-side directional repricing from {midday_start}-{midday_end} is {midday_total:.2f} points.",
                }
            )
    return pd.DataFrame(rows)


def _fmt(value: object, decimals: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(number):
        return "nan"
    return f"{number:.{decimals}f}"


def _markdown_table(df: pd.DataFrame, columns: list[str], *, max_rows: int = 10) -> list[str]:
    if df.empty:
        return ["No rows."]
    shown = df.head(max_rows)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in shown.iterrows():
        values = []
        for col in columns:
            value = row.get(col, "")
            values.append(_fmt(value) if isinstance(value, (float, int, np.number)) else str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def _write_vwap_markdown_report(
    path: Path,
    side_summary: pd.DataFrame,
    time_summary: pd.DataFrame,
    warnings: pd.DataFrame,
) -> None:
    lines = [
        "# VWAP Repricing Report",
        "",
        "This report tests the paper's core premise on the local backtest data: a completed bar above RTH VWAP should be followed by upward repricing, and a completed bar below RTH VWAP should be followed by downward repricing.",
        "",
        "The side label uses the previous completed bar only, so the diagnostic is point-in-time safe.",
        "",
        "## Side Summary",
        "",
    ]
    lines.extend(
        _markdown_table(
            side_summary,
            [
                "prior_vwap_side",
                "bars",
                "total_return_points",
                "total_directional_points",
                "continuation_hit_rate_pct",
                "directional_profit_factor",
            ],
        )
    )
    lines.extend(["", "## Time Of Day", ""])
    lines.extend(
        _markdown_table(
            time_summary.sort_values("total_directional_points", ascending=False) if not time_summary.empty else time_summary,
            [
                "hour_min",
                "bars",
                "total_directional_points",
                "avg_directional_points",
                "continuation_hit_rate_pct",
                "cumulative_directional_points",
            ],
        )
    )
    lines.extend(["", "## Warnings", ""])
    if warnings.empty:
        lines.append("No VWAP repricing warnings triggered.")
    else:
        lines.extend(_markdown_table(warnings, ["severity", "warning", "detail"], max_rows=20))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_vwap_repricing_report(
    bars: pd.DataFrame,
    out_dir: Path | str,
    *,
    artifact_name: str = "vwap_repricing",
    rth_start: str = "09:30",
    rth_end: str = "16:00",
    period: str = "Q",
    midday_start: str = "12:00",
    midday_end: str = "15:00",
) -> VwapRepricingReportPaths:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    events_csv = out_dir / f"{artifact_name}_events.csv"
    side_summary_csv = out_dir / f"{artifact_name}_side_summary.csv"
    time_of_day_csv = out_dir / f"{artifact_name}_time_of_day.csv"
    period_summary_csv = out_dir / f"{artifact_name}_period_summary.csv"
    warnings_csv = out_dir / f"{artifact_name}_warnings.csv"
    report_md = out_dir / f"{artifact_name}_report.md"

    events = build_vwap_repricing_events(bars, rth_start=rth_start, rth_end=rth_end)
    side_summary = summarize_vwap_repricing_by_side(events)
    time_summary = summarize_vwap_repricing_by_time(events)
    period_summary = summarize_vwap_repricing_by_period(events, period=period)
    warnings = build_vwap_repricing_warnings(
        side_summary,
        time_summary,
        midday_start=midday_start,
        midday_end=midday_end,
    )

    events.to_csv(events_csv, index=False)
    side_summary.to_csv(side_summary_csv, index=False)
    time_summary.to_csv(time_of_day_csv, index=False)
    period_summary.to_csv(period_summary_csv, index=False)
    warnings.to_csv(warnings_csv, index=False)
    _write_vwap_markdown_report(report_md, side_summary, time_summary, warnings)

    return VwapRepricingReportPaths(
        events_csv=events_csv,
        side_summary_csv=side_summary_csv,
        time_of_day_csv=time_of_day_csv,
        period_summary_csv=period_summary_csv,
        warnings_csv=warnings_csv,
        report_md=report_md,
    )
