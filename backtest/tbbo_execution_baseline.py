from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TbboExecutionBaseline:
    summary: pd.DataFrame
    by_session: pd.DataFrame
    by_hour: pd.DataFrame
    by_date: pd.DataFrame
    quality_flags: pd.DataFrame


@dataclass(frozen=True)
class TbboExecutionBaselinePaths:
    summary_csv: Path
    by_session_csv: Path
    by_hour_csv: Path
    by_date_csv: Path
    quality_flags_csv: Path
    report_md: Path


NUMERIC_COLUMNS = [
    "rows",
    "median_mid_price",
    "median_spread_points",
    "p90_spread_points",
    "p95_spread_points",
    "median_spread_ticks",
    "p95_spread_ticks",
    "mean_bid_size",
    "mean_ask_size",
    "median_top_book_imbalance",
    "trade_count",
    "trade_size",
    "median_trade_size",
    "median_abs_trade_price_vs_mid",
    "p95_abs_trade_price_vs_mid",
    "mean_trade_price_vs_mid",
    "median_opposite_best_size",
    "p25_opposite_best_size",
    "median_trade_size_to_opposite_best_size",
    "p95_trade_size_to_opposite_best_size",
    "top_book_depth_exhausted_trade_count",
    "top_book_depth_exhausted_trade_size",
    "top_book_excess_trade_size",
    "top_book_depth_exhausted_trade_pct",
    "top_book_depth_exhausted_size_share",
    "zero_impact_depth_supported_trade_count",
    "zero_impact_depth_supported_trade_pct",
    "raw_b_side_count",
    "raw_a_side_count",
]


def read_tbbo_minute_stats(path: Path | str) -> pd.DataFrame:
    return pd.read_csv(path)


def build_tbbo_execution_baseline(
    minute_stats: pd.DataFrame,
    *,
    assumed_round_trip_cost_points: float = 1.5,
    min_rows_per_minute: int = 5,
    min_daily_minutes: int = 30,
    wide_spread_points: float = 10.0,
) -> TbboExecutionBaseline:
    prepared = _prepare_minute_stats(
        minute_stats,
        assumed_round_trip_cost_points=assumed_round_trip_cost_points,
    )
    prepared = _mark_active_contract_by_date(prepared)
    if prepared.empty:
        empty = pd.DataFrame()
        return TbboExecutionBaseline(
            summary=_empty_summary(assumed_round_trip_cost_points),
            by_session=empty,
            by_hour=empty,
            by_date=empty,
            quality_flags=empty,
        )
    analysis_data = prepared.loc[prepared["active_contract_for_date"]].copy()
    if analysis_data.empty:
        analysis_data = prepared.copy()

    by_session = _summarize_groups(
        analysis_data,
        ["session_bucket"],
        assumed_round_trip_cost_points=assumed_round_trip_cost_points,
        min_rows_per_minute=min_rows_per_minute,
        wide_spread_points=wide_spread_points,
    )
    by_hour = _summarize_groups(
        analysis_data,
        ["hour"],
        assumed_round_trip_cost_points=assumed_round_trip_cost_points,
        min_rows_per_minute=min_rows_per_minute,
        wide_spread_points=wide_spread_points,
    ).sort_values("hour", kind="stable")
    by_date = _summarize_groups(
        prepared,
        ["trade_date", "symbol"],
        assumed_round_trip_cost_points=assumed_round_trip_cost_points,
        min_rows_per_minute=min_rows_per_minute,
        wide_spread_points=wide_spread_points,
    )
    quality_flags = _build_quality_flags(
        by_date,
        min_daily_minutes=min_daily_minutes,
        wide_spread_points=wide_spread_points,
        assumed_round_trip_cost_points=assumed_round_trip_cost_points,
    )
    summary = _build_summary(
        analysis_data,
        by_date,
        quality_flags,
        all_minute_rows=len(prepared),
        inactive_contract_minute_rows=int((~prepared["active_contract_for_date"]).sum()),
        assumed_round_trip_cost_points=assumed_round_trip_cost_points,
        min_rows_per_minute=min_rows_per_minute,
        min_daily_minutes=min_daily_minutes,
        wide_spread_points=wide_spread_points,
    )
    return TbboExecutionBaseline(
        summary=summary,
        by_session=by_session,
        by_hour=by_hour,
        by_date=by_date,
        quality_flags=quality_flags,
    )


def write_tbbo_execution_baseline(
    baseline: TbboExecutionBaseline,
    out_dir: Path | str,
    *,
    prefix: str = "tbbo_execution_baseline",
) -> TbboExecutionBaselinePaths:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = TbboExecutionBaselinePaths(
        summary_csv=out_path / f"{prefix}_summary.csv",
        by_session_csv=out_path / f"{prefix}_by_session.csv",
        by_hour_csv=out_path / f"{prefix}_by_hour.csv",
        by_date_csv=out_path / f"{prefix}_by_date.csv",
        quality_flags_csv=out_path / f"{prefix}_quality_flags.csv",
        report_md=out_path / f"{prefix}.md",
    )
    baseline.summary.to_csv(paths.summary_csv, index=False)
    baseline.by_session.to_csv(paths.by_session_csv, index=False)
    baseline.by_hour.to_csv(paths.by_hour_csv, index=False)
    baseline.by_date.to_csv(paths.by_date_csv, index=False)
    baseline.quality_flags.to_csv(paths.quality_flags_csv, index=False)
    paths.report_md.write_text(render_tbbo_execution_baseline_markdown(baseline), encoding="utf-8")
    return paths


def render_tbbo_execution_baseline_markdown(baseline: TbboExecutionBaseline) -> str:
    if baseline.summary.empty:
        return "# TBBO Execution Baseline\n\nNo TBBO minute rows were available.\n"

    summary = baseline.summary.iloc[0]
    lines = [
        "# TBBO Execution Baseline",
        "",
        "This is an execution-realism report from processed TBBO minute stats. It does not run a strategy backtest and should not be used to mine signal filters.",
        "",
        "## Coverage",
        "",
        f"- Active-contract minute rows: {int(summary['minute_rows']):,}",
        f"- All minute rows before active-contract filter: {int(summary['all_minute_rows']):,}",
        f"- Inactive-contract minute rows excluded from primary cost check: {int(summary['inactive_contract_minute_rows']):,}",
        f"- Trade dates: {int(summary['trade_dates']):,}",
        f"- Symbols: {int(summary['symbols']):,}",
        f"- Minute range: {summary['minute_start']} to {summary['minute_end']}",
        f"- Total trades represented in TBBO stats: {int(summary['total_trades']):,}",
        "",
        "## Cost Model Check",
        "",
        f"- Assumed round-trip cost: {float(summary['assumed_round_trip_cost_points']):.3f} points",
        f"- Median spread-implied round trip: {float(summary['median_rt_spread_cost_points']):.3f} points",
        f"- 95th percentile spread-implied round trip: {float(summary['p95_rt_spread_cost_points']):.3f} points",
        f"- Median p95 trade-vs-mid round trip: {float(summary['median_rt_trade_vs_mid_cost_points']):.3f} points",
        f"- 95th percentile p95 trade-vs-mid round trip: {float(summary['p95_rt_trade_vs_mid_cost_points']):.3f} points",
        f"- Median top-book depth-exhausted trade share: {_fmt_pct(summary.get('median_top_book_depth_exhausted_trade_pct'))}",
        f"- Median zero-impact depth-supported trade share: {_fmt_pct(summary.get('median_zero_impact_depth_supported_trade_pct'))}",
        f"- Verdict: `{summary['cost_model_verdict']}`",
        "",
        "## Session Buckets",
        "",
        _frame_to_markdown(
            baseline.by_session[
                [
                    "session_bucket",
                    "minutes",
                    "trade_dates",
                    "median_rt_spread_cost_points",
                    "p95_rt_spread_cost_points",
                    "median_rt_trade_vs_mid_cost_points",
                    "pct_p95_spread_cost_gt_assumed",
                    "low_row_minutes_pct",
                    "wide_spread_minutes_pct",
                ]
            ],
            max_rows=12,
        ),
        "",
        "## Data Quality",
        "",
        f"- Sparse date/symbol groups: {int(summary['sparse_date_symbol_groups'])}",
        f"- Wide-spread date/symbol groups: {int(summary['wide_spread_date_symbol_groups'])}",
        f"- Tail-cost date/symbol groups above assumption: {int(summary['tail_cost_gt_assumed_date_symbol_groups'])}",
        "",
    ]
    if not baseline.quality_flags.empty:
        lines.extend(
            [
                "Top quality flags:",
                "",
                _frame_to_markdown(baseline.quality_flags.head(20), max_rows=20),
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation Guardrails",
            "",
            "- Treat median spread cost as typical liquidity, not guaranteed fill cost.",
            "- Treat p95 spread and p95 trade-vs-mid costs as stress evidence for fast or thin conditions.",
            "- Treat top-book depth exhaustion as a warning that zero-impact fills are implausible, not as a directional signal.",
            "- Sparse date/symbol groups should not be used to judge the strategy cost model.",
            "- The primary cost check uses the active contract by trade date, selected by highest TBBO trade count.",
            "- This report is for execution assumptions only; it is not signal evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def _prepare_minute_stats(
    minute_stats: pd.DataFrame,
    *,
    assumed_round_trip_cost_points: float,
) -> pd.DataFrame:
    required = {"symbol", "minute", "trade_date", "median_spread_points", "p95_spread_points"}
    missing = required.difference(minute_stats.columns)
    if missing:
        raise ValueError(f"TBBO minute stats missing required columns: {sorted(missing)}")

    out = minute_stats.copy()
    out["symbol"] = out["symbol"].fillna("").astype(str)
    out["minute"] = pd.to_datetime(out["minute"], errors="coerce")
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in NUMERIC_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "trade_count" not in out.columns:
        out["trade_count"] = 0.0
    if "trade_size" not in out.columns:
        out["trade_size"] = 0.0
    if "rth_session" in out.columns:
        if out["rth_session"].dtype != bool:
            out["rth_session"] = out["rth_session"].astype(str).str.lower().isin({"true", "1", "yes"})
    else:
        out["rth_session"] = False

    out = out.dropna(subset=["symbol", "minute", "trade_date"]).sort_values(["symbol", "minute"])
    out["hour"] = out["minute"].dt.hour
    out["minute_of_day"] = out["minute"].dt.hour * 60 + out["minute"].dt.minute
    out["session_bucket"] = _session_bucket(out["minute_of_day"])
    out["rt_median_spread_cost_points"] = out["median_spread_points"]
    out["rt_p95_spread_cost_points"] = out["p95_spread_points"]
    out["rt_p95_trade_vs_mid_cost_points"] = _numeric(out, "p95_abs_trade_price_vs_mid") * 2.0
    assumed = float(assumed_round_trip_cost_points)
    out["median_spread_cost_gt_assumed"] = out["rt_median_spread_cost_points"].gt(assumed)
    out["p95_spread_cost_gt_assumed"] = out["rt_p95_spread_cost_points"].gt(assumed)
    out["trade_vs_mid_cost_gt_assumed"] = out["rt_p95_trade_vs_mid_cost_points"].gt(assumed)
    return out.reset_index(drop=True)


def _mark_active_contract_by_date(data: pd.DataFrame) -> pd.DataFrame:
    out = data.copy()
    daily = (
        out.groupby(["trade_date", "symbol"], sort=True)
        .agg(total_trades=("trade_count", "sum"), minutes=("minute", "size"))
        .reset_index()
        .sort_values(["trade_date", "total_trades", "minutes", "symbol"], ascending=[True, False, False, True])
    )
    active = daily.drop_duplicates("trade_date").set_index("trade_date")["symbol"]
    out["active_symbol_for_date"] = out["trade_date"].map(active)
    out["active_contract_for_date"] = out["symbol"].eq(out["active_symbol_for_date"])
    return out


def _session_bucket(minute_of_day: pd.Series) -> pd.Series:
    out = pd.Series("overnight", index=minute_of_day.index, dtype="object")
    out.loc[minute_of_day.between(8 * 60, 9 * 60 + 29, inclusive="both")] = "premarket"
    out.loc[minute_of_day.between(9 * 60 + 30, 10 * 60 + 29, inclusive="both")] = "rth_open"
    out.loc[minute_of_day.between(10 * 60 + 30, 12 * 60 + 59, inclusive="both")] = "rth_midday"
    out.loc[minute_of_day.between(13 * 60, 15 * 60 + 29, inclusive="both")] = "rth_afternoon"
    out.loc[minute_of_day.between(15 * 60 + 30, 15 * 60 + 59, inclusive="both")] = "rth_close"
    out.loc[minute_of_day.between(16 * 60, 17 * 60, inclusive="both")] = "post_rth"
    return out


def _summarize_groups(
    data: pd.DataFrame,
    group_cols: list[str],
    *,
    assumed_round_trip_cost_points: float,
    min_rows_per_minute: int,
    wide_spread_points: float,
) -> pd.DataFrame:
    grouped = data.groupby(group_cols, dropna=False, sort=True)
    rows = []
    for key, group in grouped:
        if not isinstance(key, tuple):
            key = (key,)
        row = {col: value for col, value in zip(group_cols, key)}
        row.update(_summary_values(
            group,
            assumed_round_trip_cost_points=assumed_round_trip_cost_points,
            min_rows_per_minute=min_rows_per_minute,
            wide_spread_points=wide_spread_points,
        ))
        if "active_contract_for_date" in group.columns:
            row["active_contract_for_date"] = bool(group["active_contract_for_date"].all())
        rows.append(row)
    return pd.DataFrame(rows)


def _summary_values(
    group: pd.DataFrame,
    *,
    assumed_round_trip_cost_points: float,
    min_rows_per_minute: int,
    wide_spread_points: float,
) -> dict[str, float | int]:
    median_spread = pd.to_numeric(group["rt_median_spread_cost_points"], errors="coerce")
    p95_spread = pd.to_numeric(group["rt_p95_spread_cost_points"], errors="coerce")
    trade_vs_mid = pd.to_numeric(group["rt_p95_trade_vs_mid_cost_points"], errors="coerce")
    depth_exhausted_pct = _numeric(group, "top_book_depth_exhausted_trade_pct")
    zero_impact_supported_pct = _numeric(group, "zero_impact_depth_supported_trade_pct")
    rows = _numeric(group, "rows")
    trade_count = _numeric(group, "trade_count").fillna(0)
    trade_size = _numeric(group, "trade_size").fillna(0)
    exhausted_trade_count = _numeric(group, "top_book_depth_exhausted_trade_count").fillna(0)
    exhausted_trade_size = _numeric(group, "top_book_depth_exhausted_trade_size").fillna(0)
    excess_trade_size = _numeric(group, "top_book_excess_trade_size").fillna(0)
    assumed = float(assumed_round_trip_cost_points)
    return {
        "minutes": int(len(group)),
        "trade_dates": int(group["trade_date"].nunique()),
        "symbols": int(group["symbol"].nunique()),
        "rth_minutes": int(group["rth_session"].fillna(False).astype(bool).sum()),
        "total_rows": float(rows.sum(skipna=True)),
        "total_trades": float(trade_count.sum(skipna=True)),
        "total_trade_size": float(trade_size.sum(skipna=True)),
        "median_rt_spread_cost_points": _median(median_spread),
        "p75_rt_spread_cost_points": _quantile(median_spread, 0.75),
        "p95_rt_spread_cost_points": _quantile(median_spread, 0.95),
        "median_rt_p95_spread_cost_points": _median(p95_spread),
        "p95_rt_p95_spread_cost_points": _quantile(p95_spread, 0.95),
        "median_rt_trade_vs_mid_cost_points": _median(trade_vs_mid),
        "p95_rt_trade_vs_mid_cost_points": _quantile(trade_vs_mid, 0.95),
        "top_book_depth_exhausted_trade_count": float(exhausted_trade_count.sum(skipna=True)),
        "top_book_depth_exhausted_trade_size": float(exhausted_trade_size.sum(skipna=True)),
        "top_book_excess_trade_size": float(excess_trade_size.sum(skipna=True)),
        "median_top_book_depth_exhausted_trade_pct": _median(depth_exhausted_pct),
        "median_top_book_depth_exhausted_size_share": _median(_numeric(group, "top_book_depth_exhausted_size_share")),
        "median_zero_impact_depth_supported_trade_pct": _median(zero_impact_supported_pct),
        "median_trade_size_to_opposite_best_size": _median(_numeric(group, "median_trade_size_to_opposite_best_size")),
        "p95_trade_size_to_opposite_best_size": _quantile(_numeric(group, "p95_trade_size_to_opposite_best_size"), 0.95),
        "median_top_book_depth": _median(
            _numeric(group, "mean_bid_size")
            + _numeric(group, "mean_ask_size")
        ),
        "pct_median_spread_cost_gt_assumed": _pct(median_spread.gt(assumed)),
        "pct_p95_spread_cost_gt_assumed": _pct(p95_spread.gt(assumed)),
        "pct_trade_vs_mid_cost_gt_assumed": _pct(trade_vs_mid.gt(assumed)),
        "zero_trade_minutes_pct": _pct(trade_count.le(0)),
        "low_row_minutes_pct": _pct(rows.lt(float(min_rows_per_minute))),
        "wide_spread_minutes_pct": _pct(median_spread.gt(float(wide_spread_points))),
    }


def _build_summary(
    data: pd.DataFrame,
    by_date: pd.DataFrame,
    quality_flags: pd.DataFrame,
    *,
    all_minute_rows: int,
    inactive_contract_minute_rows: int,
    assumed_round_trip_cost_points: float,
    min_rows_per_minute: int,
    min_daily_minutes: int,
    wide_spread_points: float,
) -> pd.DataFrame:
    values = _summary_values(
        data,
        assumed_round_trip_cost_points=assumed_round_trip_cost_points,
        min_rows_per_minute=min_rows_per_minute,
        wide_spread_points=wide_spread_points,
    )
    assumed = float(assumed_round_trip_cost_points)
    values.update(
        {
            "minute_rows": int(len(data)),
            "all_minute_rows": int(all_minute_rows),
            "inactive_contract_minute_rows": int(inactive_contract_minute_rows),
            "minute_start": str(data["minute"].min()),
            "minute_end": str(data["minute"].max()),
            "trade_date_start": str(data["trade_date"].min()),
            "trade_date_end": str(data["trade_date"].max()),
            "assumed_round_trip_cost_points": assumed,
            "min_rows_per_minute": int(min_rows_per_minute),
            "min_daily_minutes": int(min_daily_minutes),
            "wide_spread_points": float(wide_spread_points),
            "sparse_date_symbol_groups": int((quality_flags["flag"].eq("sparse_date_symbol_group")).sum())
            if not quality_flags.empty
            else 0,
            "wide_spread_date_symbol_groups": int((quality_flags["flag"].eq("wide_spread_date_symbol_group")).sum())
            if not quality_flags.empty
            else 0,
            "tail_cost_gt_assumed_date_symbol_groups": int(
                (quality_flags["flag"].eq("tail_cost_gt_assumed_date_symbol_group")).sum()
            )
            if not quality_flags.empty
            else 0,
        }
    )
    values["median_spread_cost_minus_assumed_points"] = values["median_rt_spread_cost_points"] - assumed
    values["p95_spread_cost_minus_assumed_points"] = values["p95_rt_spread_cost_points"] - assumed
    values["p95_trade_vs_mid_cost_minus_assumed_points"] = values["p95_rt_trade_vs_mid_cost_points"] - assumed
    values["cost_model_verdict"] = _cost_model_verdict(values)
    # Keep this available for downstream QA even if not used directly in markdown.
    values["date_symbol_groups"] = int(len(by_date))
    return pd.DataFrame([values])


def _build_quality_flags(
    by_date: pd.DataFrame,
    *,
    min_daily_minutes: int,
    wide_spread_points: float,
    assumed_round_trip_cost_points: float,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, row in by_date.iterrows():
        base = {
            "trade_date": row.get("trade_date"),
            "symbol": row.get("symbol"),
            "active_contract_for_date": bool(row.get("active_contract_for_date", False)),
            "minutes": int(row.get("minutes", 0)),
            "total_trades": float(row.get("total_trades", np.nan)),
        }
        if float(row.get("minutes", 0)) < float(min_daily_minutes):
            rows.append(
                {
                    **base,
                    "flag": "sparse_date_symbol_group",
                    "value": float(row.get("minutes", np.nan)),
                    "threshold": float(min_daily_minutes),
                    "detail": "Too few TBBO minutes to rely on this date/symbol group.",
                }
            )
        if float(row.get("median_rt_spread_cost_points", np.nan)) > float(wide_spread_points):
            rows.append(
                {
                    **base,
                    "flag": "wide_spread_date_symbol_group",
                    "value": float(row.get("median_rt_spread_cost_points", np.nan)),
                    "threshold": float(wide_spread_points),
                    "detail": "Median spread-implied round-trip cost is unusually wide.",
                }
            )
        if float(row.get("p95_rt_p95_spread_cost_points", np.nan)) > float(assumed_round_trip_cost_points):
            rows.append(
                {
                    **base,
                    "flag": "tail_cost_gt_assumed_date_symbol_group",
                    "value": float(row.get("p95_rt_p95_spread_cost_points", np.nan)),
                    "threshold": float(assumed_round_trip_cost_points),
                    "detail": "Tail spread-implied round-trip cost exceeds the assumed cost.",
                }
            )
    columns = [
        "trade_date",
        "symbol",
        "active_contract_for_date",
        "flag",
        "value",
        "threshold",
        "minutes",
        "total_trades",
        "detail",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(["trade_date", "symbol", "flag"]).reset_index(drop=True)


def _cost_model_verdict(values: dict[str, object]) -> str:
    assumed = float(values["assumed_round_trip_cost_points"])
    median_cost = float(values["median_rt_spread_cost_points"])
    p95_cost = float(values["p95_rt_spread_cost_points"])
    trade_vs_mid_tail = float(values["p95_rt_trade_vs_mid_cost_points"])
    sparse_groups = int(values.get("sparse_date_symbol_groups", 0))
    if median_cost > assumed:
        return "assumed_cost_too_low_for_typical_spread"
    if p95_cost > assumed or trade_vs_mid_tail > assumed:
        return "assumed_cost_ok_for_typical_liquidity_but_too_low_for_tail_conditions"
    if sparse_groups > 0:
        return "assumed_cost_ok_on_available_rows_but_data_quality_needs_filtering"
    return "assumed_cost_conservative_on_available_tbbo_rows"


def _empty_summary(assumed_round_trip_cost_points: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "minute_rows": 0,
                "all_minute_rows": 0,
                "inactive_contract_minute_rows": 0,
                "trade_dates": 0,
                "symbols": 0,
                "assumed_round_trip_cost_points": float(assumed_round_trip_cost_points),
                "cost_model_verdict": "no_tbbo_rows",
            }
        ]
    )


def _median(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return np.nan
    return float(clean.median())


def _quantile(series: pd.Series, q: float) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return np.nan
    return float(clean.quantile(q))


def _numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(df[col], errors="coerce")


def _pct(mask: pd.Series) -> float:
    clean = mask.dropna()
    if clean.empty:
        return np.nan
    return float(clean.astype(bool).mean() * 100.0)


def _fmt_pct(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "n/a"
    return f"{float(numeric) * 100.0:.2f}%"


def _frame_to_markdown(df: pd.DataFrame, *, max_rows: int) -> str:
    if df.empty:
        return "_No rows._"
    view = df.head(max_rows).copy()
    for col in view.columns:
        if pd.api.types.is_float_dtype(view[col]):
            view[col] = view[col].map(lambda value: "" if pd.isna(value) else f"{float(value):.3f}")
    headers = [str(col) for col in view.columns]
    rows = [[str(value) for value in row] for row in view.to_numpy()]
    widths = [
        max(len(headers[idx]), *(len(row[idx]) for row in rows)) if rows else len(headers[idx])
        for idx in range(len(headers))
    ]
    header = "| " + " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(headers)) + " |"
    divider = "| " + " | ".join("-" * widths[idx] for idx in range(len(headers))) + " |"
    body = ["| " + " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(row)) + " |" for row in rows]
    return "\n".join([header, divider, *body])
