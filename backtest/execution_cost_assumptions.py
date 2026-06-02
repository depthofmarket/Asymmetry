from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_L2_QUALITY_SUMMARY = Path(
    "results/research_master/l2_topbook_validation_matrix/l2_topbook_validation_matrix_quality_summary.csv"
)
DEFAULT_L2_BASELINE_SUMMARY = Path(
    "results/research_master/l2_topbook_validation_matrix/l2_topbook_validation_matrix_baseline_summary.csv"
)
DEFAULT_WARM_STATE_REPORT = Path(
    "results/research_master/l2_warm_state_execution_matrix_smoke/"
    "l2_warm_state_execution_matrix_smoke_report.md"
)

NQ_TICK_SIZE_POINTS = 0.25
NQ_COMMISSION_PER_ROUND_TRIP = 3.50


@dataclass(frozen=True)
class ExecutionCostAssumptionReport:
    evidence: pd.DataFrame
    recommendation: pd.DataFrame


@dataclass(frozen=True)
class ExecutionCostAssumptionPaths:
    evidence_csv: Path
    recommendation_csv: Path
    report_md: Path


def read_l2_cost_evidence(
    quality_summary_path: Path | str = DEFAULT_L2_QUALITY_SUMMARY,
    baseline_summary_path: Path | str = DEFAULT_L2_BASELINE_SUMMARY,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return pd.read_csv(quality_summary_path), pd.read_csv(baseline_summary_path)


def build_execution_cost_assumption_report(
    quality_summary: pd.DataFrame,
    baseline_summary: pd.DataFrame,
    *,
    tick_size_points: float = NQ_TICK_SIZE_POINTS,
    commission_per_round_trip: float = NQ_COMMISSION_PER_ROUND_TRIP,
    min_accepted_minutes: int = 30,
    min_accepted_quotes: int = 1000,
    min_quote_rows_per_depth_update: float = 0.01,
) -> ExecutionCostAssumptionReport:
    evidence = _merge_l2_evidence(quality_summary, baseline_summary)
    evidence = _classify_l2_evidence(
        evidence,
        min_accepted_minutes=min_accepted_minutes,
        min_accepted_quotes=min_accepted_quotes,
        min_quote_rows_per_depth_update=min_quote_rows_per_depth_update,
    )
    accepted = evidence.loc[evidence["cost_evidence_status"].eq("accepted")].copy()
    recommendation = _recommend_costs(
        accepted,
        evidence=evidence,
        tick_size_points=float(tick_size_points),
        commission_per_round_trip=float(commission_per_round_trip),
        min_accepted_minutes=min_accepted_minutes,
        min_accepted_quotes=min_accepted_quotes,
        min_quote_rows_per_depth_update=min_quote_rows_per_depth_update,
    )
    return ExecutionCostAssumptionReport(evidence=evidence, recommendation=recommendation)


def build_execution_cost_assumption_report_from_csv(
    quality_summary_path: Path | str = DEFAULT_L2_QUALITY_SUMMARY,
    baseline_summary_path: Path | str = DEFAULT_L2_BASELINE_SUMMARY,
    **kwargs,
) -> ExecutionCostAssumptionReport:
    quality_summary, baseline_summary = read_l2_cost_evidence(
        quality_summary_path=quality_summary_path,
        baseline_summary_path=baseline_summary_path,
    )
    return build_execution_cost_assumption_report(quality_summary, baseline_summary, **kwargs)


def write_execution_cost_assumption_report(
    report: ExecutionCostAssumptionReport,
    out_dir: Path | str,
    *,
    prefix: str = "execution_cost_assumptions",
) -> ExecutionCostAssumptionPaths:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = ExecutionCostAssumptionPaths(
        evidence_csv=out_path / f"{prefix}_evidence.csv",
        recommendation_csv=out_path / f"{prefix}_recommendation.csv",
        report_md=out_path / f"{prefix}.md",
    )
    report.evidence.to_csv(paths.evidence_csv, index=False)
    report.recommendation.to_csv(paths.recommendation_csv, index=False)
    paths.report_md.write_text(render_execution_cost_assumption_markdown(report), encoding="utf-8")
    return paths


def render_execution_cost_assumption_markdown(report: ExecutionCostAssumptionReport) -> str:
    if report.recommendation.empty:
        return "# Execution Cost Assumptions\n\nNo accepted L2 evidence was available.\n"

    rec = report.recommendation.iloc[0]
    accepted = report.evidence.loc[report.evidence["cost_evidence_status"].eq("accepted")]
    rejected = report.evidence.loc[report.evidence["cost_evidence_status"].eq("rejected")]
    lines = [
        "# Execution Cost Assumptions",
        "",
        "This report converts validated L2 top-book evidence into static backtest round-trip cost assumptions. It does not run a strategy backtest and must not be used as signal evidence.",
        "",
        "## Recommendation",
        "",
        f"- Commission per round trip: ${float(rec['commission_per_round_trip']):.2f}",
        f"- Default slippage: {float(rec['slippage_points']):.2f} points round trip",
        f"- Stop/urgent-exit slippage: {float(rec['slippage_stop_points']):.2f} points round trip",
        f"- Limit/target-exit slippage: {float(rec['slippage_limit_points']):.2f} points round trip",
        "",
        "## Basis",
        "",
        f"- Accepted date samples: {int(rec['accepted_dates'])}",
        f"- Rejected date samples: {int(rec['rejected_dates'])}",
        f"- Accepted source schema: `{rec['accepted_source_schema']}`",
        f"- Median accepted trade-vs-mid round trip: {float(rec['median_accepted_rt_trade_vs_mid_cost_points']):.3f} points",
        f"- Median accepted p95 trade-vs-mid round trip: {float(rec['median_accepted_p95_rt_trade_vs_mid_cost_points']):.3f} points",
        f"- Median accepted spread-implied round trip: {float(rec['median_accepted_rt_spread_cost_points']):.3f} points",
        "",
        "## Accepted Evidence",
        "",
        _frame_to_markdown(
            accepted[
                [
                    "date",
                    "source_schemas",
                    "minute_rows",
                    "usable_quote_rows",
                    "usable_trade_rows",
                    "median_rt_spread_cost_points",
                    "median_rt_trade_vs_mid_cost_points",
                    "p95_rt_trade_vs_mid_cost_points",
                ]
            ],
            max_rows=20,
        ),
        "",
        "## Rejected Evidence",
        "",
        _frame_to_markdown(
            rejected[
                [
                    "date",
                    "source_schemas",
                    "minute_rows",
                    "usable_quote_rows",
                    "usable_trade_rows",
                    "cost_evidence_reason",
                ]
            ],
            max_rows=20,
        ),
        "",
        "## Interpretation",
        "",
        "- The prior default of 0.75 points was below the accepted median trade-vs-mid round-trip evidence.",
        "- Stop and other urgent exits are costed from the accepted p95 trade-vs-mid evidence because these are the fills most likely to demand immediacy.",
        "- Limit exits still receive a lower assumption, but no longer the old 0.25-point near-free fill; depth exhaustion in the accepted samples makes that too optimistic.",
        "- Structured 2022+ rows remain readable but are excluded until warm-state reconstruction produces non-trivial accepted coverage.",
        "",
    ]
    return "\n".join(lines)


def _merge_l2_evidence(quality_summary: pd.DataFrame, baseline_summary: pd.DataFrame) -> pd.DataFrame:
    quality_cols = [
        "date",
        "source_schemas",
        "decoded_rows",
        "usable_quote_rows",
        "usable_trade_rows",
        "quote_rows_per_depth_update",
        "trade_rows_per_type1_event",
        "minute_rows",
    ]
    quality = quality_summary[[col for col in quality_cols if col in quality_summary.columns]].copy()
    quality = quality.rename(columns={"minute_rows": "quality_minute_rows"})
    merged = baseline_summary.merge(quality, on="date", how="left", validate="one_to_one")
    numeric_cols = [
        "minute_rows",
        "quality_minute_rows",
        "usable_quote_rows",
        "usable_trade_rows",
        "quote_rows_per_depth_update",
        "median_rt_spread_cost_points",
        "p95_rt_spread_cost_points",
        "median_rt_trade_vs_mid_cost_points",
        "p95_rt_trade_vs_mid_cost_points",
        "median_top_book_depth_exhausted_trade_pct",
        "p95_trade_size_to_opposite_best_size",
    ]
    for col in numeric_cols:
        if col in merged.columns:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
    return merged


def _classify_l2_evidence(
    evidence: pd.DataFrame,
    *,
    min_accepted_minutes: int,
    min_accepted_quotes: int,
    min_quote_rows_per_depth_update: float,
) -> pd.DataFrame:
    out = evidence.copy()
    statuses: list[str] = []
    reasons: list[str] = []
    for _, row in out.iterrows():
        row_reasons = []
        source_schemas = str(row.get("source_schemas", ""))
        if "semicolon_1col" not in source_schemas:
            row_reasons.append("structured schema not yet accepted for cost calibration")
        if float(row.get("minute_rows", 0.0) or 0.0) < min_accepted_minutes:
            row_reasons.append(f"fewer than {min_accepted_minutes} accepted minute rows")
        if float(row.get("usable_quote_rows", 0.0) or 0.0) < min_accepted_quotes:
            row_reasons.append(f"fewer than {min_accepted_quotes} usable quote rows")
        if float(row.get("quote_rows_per_depth_update", 0.0) or 0.0) < min_quote_rows_per_depth_update:
            row_reasons.append(f"quote/depth ratio below {min_quote_rows_per_depth_update:.2%}")
        if row_reasons:
            statuses.append("rejected")
            reasons.append("; ".join(row_reasons))
        else:
            statuses.append("accepted")
            reasons.append("accepted validated semicolon-schema top-book sample")
    out["cost_evidence_status"] = statuses
    out["cost_evidence_reason"] = reasons
    return out


def _recommend_costs(
    accepted: pd.DataFrame,
    *,
    evidence: pd.DataFrame,
    tick_size_points: float,
    commission_per_round_trip: float,
    min_accepted_minutes: int,
    min_accepted_quotes: int,
    min_quote_rows_per_depth_update: float,
) -> pd.DataFrame:
    if accepted.empty:
        raise ValueError("No accepted L2 evidence rows are available for execution-cost assumptions.")

    median_trade_vs_mid = _median(accepted["median_rt_trade_vs_mid_cost_points"])
    median_p95_trade_vs_mid = _median(accepted["p95_rt_trade_vs_mid_cost_points"])
    median_spread_rt = _median(accepted["median_rt_spread_cost_points"])

    default_slippage = _round_to_tick(median_trade_vs_mid, tick_size_points)
    stop_slippage = _ceil_to_tick(median_p95_trade_vs_mid, tick_size_points)
    limit_slippage = _round_to_tick(median_spread_rt * 0.75, tick_size_points)
    limit_slippage = max(3.0 * tick_size_points, min(limit_slippage, default_slippage))

    accepted_schemas = sorted({str(value).split(":", 1)[0] for value in accepted["source_schemas"].dropna()})
    row = {
        "symbol": "NQ",
        "contract_value": 20.0,
        "commission_per_round_trip": float(commission_per_round_trip),
        "slippage_points": float(default_slippage),
        "slippage_stop_points": float(max(stop_slippage, default_slippage)),
        "slippage_limit_points": float(min(limit_slippage, default_slippage)),
        "accepted_dates": int(len(accepted)),
        "rejected_dates": int(evidence["cost_evidence_status"].eq("rejected").sum()),
        "accepted_source_schema": ",".join(accepted_schemas),
        "median_accepted_rt_trade_vs_mid_cost_points": float(median_trade_vs_mid),
        "median_accepted_p95_rt_trade_vs_mid_cost_points": float(median_p95_trade_vs_mid),
        "median_accepted_rt_spread_cost_points": float(median_spread_rt),
        "max_accepted_top_book_depth_exhausted_trade_pct": float(
            accepted["median_top_book_depth_exhausted_trade_pct"].max()
        ),
        "min_accepted_minutes": int(min_accepted_minutes),
        "min_accepted_quotes": int(min_accepted_quotes),
        "min_quote_rows_per_depth_update": float(min_quote_rows_per_depth_update),
        "evidence_quality_path": str(DEFAULT_L2_QUALITY_SUMMARY),
        "evidence_baseline_path": str(DEFAULT_L2_BASELINE_SUMMARY),
        "excluded_warm_state_report": str(DEFAULT_WARM_STATE_REPORT),
    }
    return pd.DataFrame([row])


def _median(series: pd.Series) -> float:
    value = pd.to_numeric(series, errors="coerce").dropna().median()
    if pd.isna(value):
        raise ValueError("Cannot compute execution-cost recommendation from empty numeric evidence.")
    return float(value)


def _round_to_tick(value: float, tick_size_points: float) -> float:
    return float(round(float(value) / tick_size_points) * tick_size_points)


def _ceil_to_tick(value: float, tick_size_points: float) -> float:
    return float(np.ceil(float(value) / tick_size_points) * tick_size_points)


def _frame_to_markdown(frame: pd.DataFrame, *, max_rows: int = 20) -> str:
    if frame.empty:
        return "_None._"
    visible = frame.head(max_rows).copy()
    headers = list(visible.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for _, row in visible.iterrows():
        lines.append("| " + " | ".join(_fmt_value(row[col]) for col in headers) + " |")
    if len(frame) > max_rows:
        lines.append(f"\n_Only showing first {max_rows} of {len(frame)} rows._")
    return "\n".join(lines)


def _fmt_value(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.4g}"
    return str(value)
