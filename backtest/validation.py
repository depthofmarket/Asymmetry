from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DevelopmentReportPaths:
    csv_path: Path
    markdown_path: Path


@dataclass(frozen=True)
class OptimizationStabilityReportPaths:
    csv_path: Path
    markdown_path: Path


@dataclass(frozen=True)
class MultipleTestingDebtReportPaths:
    csv_path: Path
    markdown_path: Path


@dataclass(frozen=True)
class ResearchDisciplineReportPaths:
    csv_path: Path
    markdown_path: Path


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _safe_float(value: Any, default: float = float("nan")) -> float:
    if value is None or value == "":
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if np.isfinite(out) else default


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        if np.isnan(value):
            return "nan"
        return f"{value:.4f}"
    return str(value)


def _trades_per_year(results: dict[str, Any], years: float) -> float:
    if years <= 0 or "error" in results:
        return 0.0
    return float(results.get("total_trades", 0)) / years


def _metric_value(results: dict[str, Any], metric: str) -> float:
    metric = str(metric)
    if metric == "sharpe":
        return _safe_float(results.get("sharpe_ratio"))
    if metric == "profit_factor":
        return _safe_float(results.get("profit_factor"))
    if metric == "expectancy":
        return _safe_float(results.get("expectancy"))
    if metric == "total_pnl":
        return _safe_float(results.get("total_pnl"))
    if metric == "bar_profit_factor":
        return _safe_float(results.get("bar_profit_factor"))
    if metric == "bar_sharpe":
        return _safe_float(results.get("bar_sharpe_ratio"))
    return _safe_float(results.get(metric))


def _metric_threshold(metric: str, validation_config: dict[str, Any]) -> tuple[float | None, str]:
    metric = str(metric)
    if metric == "bar_profit_factor":
        value = float(validation_config.get("min_walk_forward_bar_profit_factor", 1.0))
        return value, f">= {value}"
    if metric == "profit_factor":
        value = float(validation_config.get("min_walk_forward_profit_factor", 1.05))
        return value, f">= {value}"
    if metric == "total_pnl":
        value = float(validation_config.get("min_walk_forward_total_pnl", 0.0))
        return value, f">= {value}"
    return None, "reported only"


def _slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in str(value)).strip("_")


def _candidate_family(
    candidate_name: str,
    configured_candidates: list[str],
    research_config: dict[str, Any],
) -> tuple[str, list[str]]:
    explicit = research_config.get("candidate_research_families", {})
    if isinstance(explicit, dict):
        for family_name, members in explicit.items():
            if not isinstance(members, list):
                continue
            member_names = [str(member) for member in members]
            if candidate_name in member_names:
                return str(family_name), [name for name in member_names if name in configured_candidates]

    if candidate_name in configured_candidates:
        tokens = candidate_name.split("_")
        prefix = "_".join(tokens[: min(len(tokens), 6)])
        inferred = [name for name in configured_candidates if name.startswith(prefix)]
        return prefix or candidate_name, inferred or [candidate_name]

    return candidate_name, [candidate_name]


def _candidate_family_from_run_dir(
    run_dir: Path | str,
    research_config: dict[str, Any],
) -> tuple[str, str]:
    explicit = research_config.get("candidate_research_families", {})
    if not isinstance(explicit, dict):
        return "", ""

    run_slug = _slugify(Path(run_dir).name)
    matches: list[tuple[int, str, str]] = []
    for family_name, members in explicit.items():
        if not isinstance(members, list):
            continue
        for member in members:
            candidate_name = str(member)
            candidate_slug = _slugify(candidate_name)
            if candidate_slug and candidate_slug in run_slug:
                matches.append((len(candidate_slug), candidate_name, str(family_name)))

    if not matches:
        return "", ""

    _, candidate_name, family_name = max(matches, key=lambda item: item[0])
    return candidate_name, family_name


def _rejected_family_info(
    family_name: str,
    research_config: dict[str, Any],
) -> dict[str, Any] | None:
    if not family_name:
        return None
    rejected = research_config.get("rejected_research_families", {})
    if not isinstance(rejected, dict) or family_name not in rejected:
        return None

    info = rejected.get(family_name)
    if isinstance(info, dict):
        return dict(info)
    if _truthy(info):
        return {"status": "rejected", "reason": "Family is listed in rejected_research_families."}
    return None


def _saved_run_count(candidate_name: str, results_root: Path | str | None) -> int:
    if results_root is None:
        return 0
    root = Path(results_root)
    if not root.exists():
        return 0
    slug = _slugify(candidate_name)
    count = 0
    for path in root.iterdir():
        if path.is_dir() and slug and slug in path.name:
            count += 1
    return count


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and np.isfinite(value):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "pass"}


def _first_row(frame: pd.DataFrame, mask: pd.Series) -> pd.Series | None:
    rows = frame.loc[mask].head(1)
    if rows.empty:
        return None
    return rows.iloc[0]


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def export_development_report(
    results: dict[str, Any],
    years: float,
    out_dir: Path | str,
    validation_config: dict[str, Any],
    walk_forward_result=None,
    walk_forward_years: float | None = None,
    in_sample_permutation=None,
    walk_forward_permutation=None,
    stress_summary_csv: Path | str | None = None,
) -> DevelopmentReportPaths:
    """
    Write a compact pass/fail report for the four-step strategy-development flow.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    def add(step: str, check: str, value: Any, threshold: Any, ok: bool | None, notes: str = "") -> None:
        rows.append(
            {
                "step": step,
                "check": check,
                "status": "SKIP" if ok is None else _status(bool(ok)),
                "value": value,
                "threshold": threshold,
                "notes": notes,
            }
        )

    in_sample_pf = float(results.get("profit_factor", 0.0))
    in_sample_bar_pf = float(results.get("bar_profit_factor", 0.0))
    in_sample_execution_bar_pf = _safe_float(results.get("execution_bar_profit_factor"))
    in_sample_tpy = _trades_per_year(results, years)
    add(
        "1_in_sample_excellence",
        "trade_profit_factor",
        in_sample_pf,
        f">= {validation_config['min_in_sample_profit_factor']}",
        in_sample_pf >= float(validation_config["min_in_sample_profit_factor"]),
    )
    add(
        "1_in_sample_excellence",
        "bar_profit_factor",
        in_sample_bar_pf,
        f">= {validation_config['min_in_sample_bar_profit_factor']}",
        in_sample_bar_pf >= float(validation_config["min_in_sample_bar_profit_factor"]),
        "Hard warning: trade PF is not enough if bar-level exposure fails.",
    )
    add(
        "1_in_sample_excellence",
        "execution_bar_profit_factor",
        in_sample_execution_bar_pf,
        "diagnostic only",
        None,
        "1-minute execution-path diagnostic; does not replace the 5-minute signal-bar warning.",
    )
    add(
        "1_in_sample_excellence",
        "trades_per_year",
        in_sample_tpy,
        f">= {validation_config['min_trades_per_year']}",
        in_sample_tpy >= float(validation_config["min_trades_per_year"]),
    )

    win_rate = float(results.get("win_rate", 0.0))
    in_sample_sharpe = _safe_float(results.get("sharpe_ratio"))
    max_suspicious_sharpe = float(validation_config.get("max_suspicious_sharpe_ratio", 3.0))
    if np.isfinite(in_sample_sharpe):
        add(
            "1_in_sample_excellence",
            "sharpe_overfit_smell",
            in_sample_sharpe,
            f"abs <= {max_suspicious_sharpe}",
            abs(in_sample_sharpe) <= max_suspicious_sharpe,
            "Sharpe above institutional-quality ranges is suspicious until leakage, costs, and multiple testing are ruled out.",
        )
    else:
        add("1_in_sample_excellence", "sharpe_overfit_smell", None, f"abs <= {max_suspicious_sharpe}", None)

    suspicious = (
        win_rate > float(validation_config["max_suspicious_win_rate_pct"])
        or in_sample_pf > float(validation_config["max_suspicious_profit_factor"])
    )
    add(
        "1_in_sample_excellence",
        "obvious_overfit_smell",
        f"win_rate={win_rate:.2f}, pf={in_sample_pf:.2f}",
        "below suspicious limits",
        not suspicious,
        "High values are not automatically bad, but they deserve leak/overfit review.",
    )

    if in_sample_permutation is None:
        add("2_in_sample_permutation", "p_value", None, f"<= {validation_config['max_in_sample_permutation_p']}", None)
    else:
        p_value = float(in_sample_permutation.p_value_smoothed)
        add(
            "2_in_sample_permutation",
            "p_value_smoothed",
            p_value,
            f"<= {validation_config['max_in_sample_permutation_p']}",
            p_value <= float(validation_config["max_in_sample_permutation_p"]),
        )

    if walk_forward_result is None or "error" in walk_forward_result.stitched_results:
        add("3_walk_forward", "stitched_oos_profit_factor", None, f">= {validation_config['min_walk_forward_profit_factor']}", None)
        add("3_walk_forward", "stitched_oos_total_pnl", None, f">= {validation_config['min_walk_forward_total_pnl']}", None)
    else:
        wf = walk_forward_result.stitched_results
        wf_pf = float(wf.get("profit_factor", 0.0))
        wf_bar_pf = float(wf.get("bar_profit_factor", 0.0))
        wf_execution_bar_pf = _safe_float(wf.get("execution_bar_profit_factor"))
        wf_pnl = float(wf.get("total_pnl", 0.0))
        wf_tpy = _trades_per_year(wf, walk_forward_years if walk_forward_years is not None else years)
        add(
            "3_walk_forward",
            "stitched_oos_profit_factor",
            wf_pf,
            f">= {validation_config['min_walk_forward_profit_factor']}",
            wf_pf >= float(validation_config["min_walk_forward_profit_factor"]),
        )
        add(
            "3_walk_forward",
            "stitched_oos_bar_profit_factor",
            wf_bar_pf,
            f">= {validation_config['min_walk_forward_bar_profit_factor']}",
            wf_bar_pf >= float(validation_config["min_walk_forward_bar_profit_factor"]),
            "Hard warning: OOS trade PF is not enough if OOS bar-level exposure fails.",
        )
        add(
            "3_walk_forward",
            "stitched_oos_execution_bar_profit_factor",
            wf_execution_bar_pf,
            "diagnostic only",
            None,
            "1-minute execution-path diagnostic; approval still requires scoped walk-forward evidence.",
        )
        add(
            "3_walk_forward",
            "stitched_oos_total_pnl",
            wf_pnl,
            f">= {validation_config['min_walk_forward_total_pnl']}",
            wf_pnl >= float(validation_config["min_walk_forward_total_pnl"]),
        )
        add(
            "3_walk_forward",
            "stitched_oos_trades_per_year",
            wf_tpy,
            f">= {validation_config['min_trades_per_year']}",
            wf_tpy >= float(validation_config["min_trades_per_year"]),
        )
        stability_ratios = []
        for fold in getattr(walk_forward_result, "folds", []):
            train_metric = float(getattr(fold, "train_metric", np.nan))
            neighbor_metric = float(getattr(fold, "train_neighbor_metric", np.nan))
            if np.isfinite(train_metric) and np.isfinite(neighbor_metric) and train_metric > 0:
                stability_ratios.append(neighbor_metric / train_metric)
        if stability_ratios:
            median_stability = float(np.nanmedian(stability_ratios))
            threshold = float(validation_config.get("min_walk_forward_neighbor_metric_ratio", 0.75))
            add(
                "3_walk_forward",
                "selected_param_neighborhood_ratio",
                median_stability,
                f">= {threshold}",
                median_stability >= threshold,
                "Median selected-neighborhood metric divided by selected training metric.",
            )
        else:
            add("3_walk_forward", "selected_param_neighborhood_ratio", None, "stable WF diagnostics available", None)

    if walk_forward_permutation is None:
        add("4_walk_forward_permutation", "p_value", None, f"<= {validation_config['max_walk_forward_permutation_p']}", None)
    else:
        p_value = float(walk_forward_permutation.p_value_smoothed)
        add(
            "4_walk_forward_permutation",
            "p_value_smoothed",
            p_value,
            f"<= {validation_config['max_walk_forward_permutation_p']}",
            p_value <= float(validation_config["max_walk_forward_permutation_p"]),
        )

    min_stress_pf = float(validation_config.get("min_combined_mild_profit_factor", 1.05))
    min_stress_pnl = float(validation_config.get("min_combined_mild_total_pnl", 0.0))
    if stress_summary_csv is None:
        add(
            "5_stress_hard_warnings",
            "combined_mild_profit_factor",
            None,
            f">= {min_stress_pf}",
            None,
            "Hard warning: run trade stress tests before promoting a candidate.",
        )
        add(
            "5_stress_hard_warnings",
            "combined_mild_total_pnl",
            None,
            f"> {min_stress_pnl}",
            None,
            "Hard warning: stress-adjusted PnL must stay positive.",
        )
    else:
        stress_path = Path(stress_summary_csv)
        if not stress_path.exists():
            add("5_stress_hard_warnings", "combined_mild_stress_exists", str(stress_path), "file exists", False)
        else:
            stress_df = pd.read_csv(stress_path)
            row = stress_df.loc[stress_df["scenario"].astype(str).eq("combined_mild")].head(1)
            if row.empty:
                add("5_stress_hard_warnings", "combined_mild_stress_exists", "missing", "scenario exists", False)
            else:
                stress_row = row.iloc[0]
                stress_pf = _safe_float(stress_row.get("profit_factor"))
                stress_pnl = _safe_float(stress_row.get("total_pnl"))
                add(
                    "5_stress_hard_warnings",
                    "combined_mild_profit_factor",
                    stress_pf,
                    f">= {min_stress_pf}",
                    stress_pf >= min_stress_pf,
                    "Hard warning: small cost/slippage degradation should not erase the edge.",
                )
                add(
                    "5_stress_hard_warnings",
                    "combined_mild_total_pnl",
                    stress_pnl,
                    f"> {min_stress_pnl}",
                    stress_pnl > min_stress_pnl,
                    "Hard warning: stress-adjusted total PnL must stay positive.",
                )

    report = pd.DataFrame(rows)
    csv_path = out_dir / "development_report.csv"
    md_path = out_dir / "development_report.md"
    report.to_csv(csv_path, index=False)

    lines = ["# Strategy Development Report", ""]
    for row in rows:
        lines.append(
            f"- {row['status']} | {row['step']} | {row['check']} | "
            f"value={_fmt(row['value'])} | threshold={row['threshold']}"
        )
        if row["notes"]:
            lines.append(f"  {row['notes']}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return DevelopmentReportPaths(csv_path=csv_path, markdown_path=md_path)


def export_optimization_stability_report(
    walk_forward_result,
    out_dir: Path | str,
    validation_config: dict[str, Any],
    metric: str = "bar_profit_factor",
) -> OptimizationStabilityReportPaths:
    """
    Export a fold-by-fold report that separates optimization from validation.

    The report flags sharp train optima and OOS collapse without re-running any
    extra backtests. It uses diagnostics already produced by walk-forward.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "optimization_stability.csv"
    md_path = out_dir / "optimization_stability.md"

    min_neighbor_ratio = float(validation_config.get("min_walk_forward_neighbor_metric_ratio", 0.75))
    test_threshold, test_threshold_label = _metric_threshold(metric, validation_config)
    min_oos_pnl = float(validation_config.get("min_walk_forward_total_pnl", 0.0))
    rows: list[dict[str, Any]] = []

    for fold in getattr(walk_forward_result, "folds", []) or []:
        train_metric = _safe_float(getattr(fold, "train_metric", np.nan))
        train_neighbor_metric = _safe_float(getattr(fold, "train_neighbor_metric", np.nan))
        train_neighbor_ratio = (
            train_neighbor_metric / train_metric
            if np.isfinite(train_neighbor_metric) and np.isfinite(train_metric) and train_metric > 0
            else np.nan
        )
        test_results = getattr(fold, "test_results", {}) or {}
        test_metric = _metric_value(test_results, metric)
        test_pnl = _safe_float(test_results.get("total_pnl", np.nan))
        test_trades = int(test_results.get("total_trades", 0) or 0)

        neighborhood_ok = bool(np.isfinite(train_neighbor_ratio) and train_neighbor_ratio >= min_neighbor_ratio)
        test_metric_ok = True if test_threshold is None else bool(np.isfinite(test_metric) and test_metric >= test_threshold)
        pnl_ok = bool(np.isfinite(test_pnl) and test_pnl >= min_oos_pnl)
        trades_ok = test_trades > 0
        boundary_ok = bool(getattr(fold, "purge_embargo_ok", True))

        notes = []
        if not neighborhood_ok:
            notes.append("sharp_train_optimum")
        if not test_metric_ok:
            notes.append("oos_metric_failed")
        if not pnl_ok:
            notes.append("oos_pnl_failed")
        if not trades_ok:
            notes.append("no_oos_trades")
        if not boundary_ok:
            notes.append("purge_embargo_failed")

        rows.append(
            {
                "fold_idx": getattr(fold, "fold_idx", len(rows)),
                "window_mode": getattr(fold, "window_mode", ""),
                "planned_train_start": getattr(fold, "planned_train_start", ""),
                "planned_train_end": getattr(fold, "planned_train_end", ""),
                "train_start": getattr(fold, "train_start", ""),
                "train_end": getattr(fold, "train_end", ""),
                "test_start": getattr(fold, "test_start", ""),
                "test_end": getattr(fold, "test_end", ""),
                "purge_bars": getattr(fold, "purge_bars", 0),
                "embargo_bars": getattr(fold, "embargo_bars", 0),
                "gap_bars": getattr(fold, "gap_bars", 0),
                "boundary_gap_minutes": getattr(fold, "boundary_gap_minutes", np.nan),
                "purge_embargo_ok": boundary_ok,
                "metric": metric,
                "train_metric": train_metric,
                "train_neighbor_metric": train_neighbor_metric,
                "train_neighbor_ratio": train_neighbor_ratio,
                "min_neighbor_ratio": min_neighbor_ratio,
                "test_metric": test_metric,
                "test_metric_threshold": test_threshold_label,
                "test_total_trades": test_trades,
                "test_total_pnl": test_pnl,
                "test_profit_factor": _safe_float(test_results.get("profit_factor", np.nan)),
                "test_bar_profit_factor": _safe_float(test_results.get("bar_profit_factor", np.nan)),
                "best_overrides": getattr(fold, "best_overrides", {}),
                "status": "PASS" if neighborhood_ok and test_metric_ok and pnl_ok and trades_ok and boundary_ok else "FAIL",
                "notes": ";".join(notes),
            }
        )

    pd.DataFrame(rows).to_csv(csv_path, index=False)

    fail_count = sum(1 for row in rows if row["status"] != "PASS")
    lines = [
        "# Optimization Stability Report",
        "",
        "This report checks whether selected walk-forward parameters sit in a stable train neighborhood and survive OOS.",
        f"- Folds checked: {len(rows)}",
        f"- Failed folds: {fail_count}",
        f"- Metric: {metric}",
        f"- Neighborhood ratio threshold: {min_neighbor_ratio}",
        f"- OOS metric threshold: {test_threshold_label}",
        "",
    ]
    for row in rows:
        lines.append(
            f"- {row['status']} fold {row['fold_idx']}: "
            f"train={_fmt(row['train_metric'])}, neighbor_ratio={_fmt(row['train_neighbor_ratio'])}, "
            f"oos_{metric}={_fmt(row['test_metric'])}, oos_pnl={_fmt(row['test_total_pnl'])}"
        )
        if row["notes"]:
            lines.append(f"  notes={row['notes']}")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return OptimizationStabilityReportPaths(csv_path=csv_path, markdown_path=md_path)


def export_multiple_testing_debt_report(
    *,
    candidate_name: str,
    candidate_configs: dict[str, Any],
    out_dir: Path | str,
    research_config: dict[str, Any],
    results_root: Path | str | None = None,
) -> MultipleTestingDebtReportPaths:
    """
    Record the hypothesis-search surface attached to a run.

    This does not prove or disprove an edge. It makes the false-discovery debt
    visible by counting configured family variants and saved runs.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "multiple_testing_debt.csv"
    md_path = out_dir / "multiple_testing_debt.md"

    configured = sorted(str(name) for name in candidate_configs if not str(name).startswith("_"))
    family_name, family_candidates = _candidate_family(str(candidate_name), configured, research_config)
    planned = [str(name) for name in research_config.get("next_validation_candidates", [])]
    max_family_runs = int(research_config.get("max_candidate_family_runs_before_holdout", 4))

    rows: list[dict[str, Any]] = []
    for name in family_candidates:
        saved_runs = _saved_run_count(name, results_root)
        rows.append(
            {
                "candidate": name,
                "family": family_name,
                "is_current": name == candidate_name,
                "planned_rank": planned.index(name) + 1 if name in planned else np.nan,
                "saved_run_count": saved_runs,
                "configured_family_candidates": len(family_candidates),
                "configured_total_candidates": len(configured),
            }
        )

    family_saved_runs = int(sum(int(row["saved_run_count"]) for row in rows))
    status = "WARN" if family_saved_runs > max_family_runs else "PASS"
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    lines = [
        "# Multiple-Testing Debt Report",
        "",
        "Every configured variant is a tested hypothesis. More variants increase false-discovery risk.",
        f"- Current candidate: {candidate_name}",
        f"- Family: {family_name}",
        f"- Configured family variants: {len(family_candidates)}",
        f"- Saved runs in family: {family_saved_runs}",
        f"- Family saved-run warning threshold: {max_family_runs}",
        f"- Status: {status}",
        "",
        "## Narrow Next Candidates",
    ]
    if planned:
        for idx, name in enumerate(planned, start=1):
            lines.append(f"- {idx}. {name}")
    else:
        lines.append("- No configured narrow candidate plan.")
    lines.extend(["", "## Family Candidates"])
    for row in rows:
        marker = " current" if row["is_current"] else ""
        lines.append(f"- {row['candidate']}: saved_runs={row['saved_run_count']}{marker}")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return MultipleTestingDebtReportPaths(csv_path=csv_path, markdown_path=md_path)


def export_research_discipline_report(
    *,
    run_dir: Path | str,
    out_dir: Path | str | None = None,
    validation_config: dict[str, Any] | None = None,
    research_config: dict[str, Any] | None = None,
) -> ResearchDisciplineReportPaths:
    """
    Export a strict saved-run gate that encodes the anti-overfit research protocol.

    This only reads artifacts already produced by a run. It does not replay
    strategy logic, scan historical bars, or mine a new filter.
    """
    run_dir = Path(run_dir)
    out_dir = Path(out_dir) if out_dir is not None else run_dir / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    validation_config = validation_config or {}
    research_config = research_config or {}

    csv_path = out_dir / "research_discipline_gate.csv"
    md_path = out_dir / "research_discipline_gate.md"
    rows: list[dict[str, Any]] = []

    def add(
        section: str,
        check: str,
        value: Any,
        threshold: Any,
        ok: bool,
        source: Path | str,
        notes: str = "",
        severity: str = "hard",
    ) -> None:
        rows.append(
            {
                "section": section,
                "check": check,
                "severity": severity,
                "status": _status(ok) if severity == "hard" else ("PASS" if ok else "WARN"),
                "value": value,
                "threshold": threshold,
                "source": str(source),
                "notes": notes,
            }
        )

    inferred_candidate, inferred_family = _candidate_family_from_run_dir(run_dir, research_config)
    if inferred_family:
        add(
            "governance",
            "candidate_family_resolved",
            f"{inferred_family}:{inferred_candidate}",
            "resolved from run folder",
            True,
            "config.RESEARCH_CONFIG.candidate_research_families",
            severity="warning",
        )
        rejected_info = _rejected_family_info(inferred_family, research_config)
        notes = ""
        if rejected_info is not None:
            reason = str(rejected_info.get("reason", "")).strip()
            decision_date = str(rejected_info.get("decision_date", "")).strip()
            if decision_date and reason:
                notes = f"{decision_date}: {reason}"
            else:
                notes = reason or "Candidate family is rejected."
        add(
            "governance",
            "candidate_family_not_rejected",
            inferred_family,
            "not listed in rejected_research_families",
            rejected_info is None,
            "config.RESEARCH_CONFIG.rejected_research_families",
            notes,
        )
    else:
        add(
            "governance",
            "candidate_family_resolved",
            "unresolved",
            "resolved from run folder",
            False,
            "config.RESEARCH_CONFIG.candidate_research_families",
            "Run label did not match a configured research family; governance rejection checks could not be applied.",
            severity="warning",
        )

    dev_path = run_dir / "research" / "development_report.csv"
    dev = pd.DataFrame()
    if dev_path.exists():
        dev = pd.read_csv(dev_path)
        add("evidence", "development_report_exists", "present", "file exists", True, dev_path)
    else:
        add("evidence", "development_report_exists", "missing", "file exists", False, dev_path)

    def add_dev_check(section: str, step: str, check: str, notes: str = "") -> None:
        if dev.empty:
            add(section, check, "missing", "status PASS", False, dev_path, notes)
            return
        row = _first_row(dev, dev["step"].astype(str).eq(step) & dev["check"].astype(str).eq(check))
        if row is None:
            add(section, check, "missing", "status PASS", False, dev_path, notes)
            return
        status = str(row.get("status", ""))
        add(
            section,
            check,
            row.get("value"),
            row.get("threshold"),
            status == "PASS",
            dev_path,
            notes or str(row.get("notes", "")),
        )

    add_dev_check("in_sample", "1_in_sample_excellence", "trade_profit_factor")
    add_dev_check("in_sample", "1_in_sample_excellence", "bar_profit_factor", "Trade PF is not enough if bar exposure fails.")
    add_dev_check("in_sample", "1_in_sample_excellence", "obvious_overfit_smell")
    if not dev.empty and (dev["check"].astype(str) == "sharpe_overfit_smell").any():
        add_dev_check("in_sample", "1_in_sample_excellence", "sharpe_overfit_smell")

    add_dev_check("walk_forward", "3_walk_forward", "stitched_oos_profit_factor")
    add_dev_check("walk_forward", "3_walk_forward", "stitched_oos_bar_profit_factor")
    add_dev_check("walk_forward", "3_walk_forward", "stitched_oos_total_pnl")
    add_dev_check("walk_forward", "3_walk_forward", "stitched_oos_trades_per_year")
    add_dev_check("walk_forward", "3_walk_forward", "selected_param_neighborhood_ratio")

    add_dev_check("stress", "5_stress_hard_warnings", "combined_mild_profit_factor")
    add_dev_check("stress", "5_stress_hard_warnings", "combined_mild_total_pnl")

    permutation_required = bool(validation_config.get("research_discipline_require_permutation", True))
    for step, check_name in [
        ("2_in_sample_permutation", "in_sample_permutation_p_value"),
        ("4_walk_forward_permutation", "walk_forward_permutation_p_value"),
    ]:
        if dev.empty:
            add("multiple_testing", check_name, "missing", "permutation p-value PASS", False, dev_path)
            continue
        step_rows = dev.loc[dev["step"].astype(str).eq(step)]
        if step_rows.empty:
            add("multiple_testing", check_name, "missing", "permutation p-value PASS", False, dev_path)
            continue
        item = step_rows.iloc[0]
        status = str(item.get("status", ""))
        ok = status == "PASS" or (status == "SKIP" and not permutation_required)
        add(
            "multiple_testing",
            check_name,
            item.get("value"),
            item.get("threshold"),
            ok,
            dev_path,
            "Permutation/false-discovery evidence is required before promotion." if permutation_required else "",
        )

    if not dev.empty:
        max_pf_ratio = float(validation_config.get("max_in_sample_to_walk_forward_profit_factor_ratio", 2.5))
        for check_name, wf_check_name, label in [
            ("trade_profit_factor", "stitched_oos_profit_factor", "trade_pf_degradation_ratio"),
            ("bar_profit_factor", "stitched_oos_bar_profit_factor", "bar_pf_degradation_ratio"),
        ]:
            in_row = _first_row(dev, dev["check"].astype(str).eq(check_name))
            wf_row = _first_row(dev, dev["check"].astype(str).eq(wf_check_name))
            in_value = _safe_float(in_row.get("value") if in_row is not None else np.nan)
            wf_value = _safe_float(wf_row.get("value") if wf_row is not None else np.nan)
            if np.isfinite(in_value) and np.isfinite(wf_value) and wf_value > 0:
                ratio = in_value / wf_value
                add(
                    "walk_forward",
                    label,
                    ratio,
                    f"<= {max_pf_ratio}",
                    ratio <= max_pf_ratio,
                    dev_path,
                    "Large IS/OOS degradation is a section-18 overfit smell.",
                )
            else:
                add("walk_forward", label, "missing", f"<= {max_pf_ratio}", False, dev_path)

    debt_path = run_dir / "research" / "multiple_testing_debt.csv"
    if debt_path.exists():
        debt = pd.read_csv(debt_path)
        family_runs = int(pd.to_numeric(debt.get("saved_run_count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
        family_variants_value = _safe_float(
            pd.to_numeric(debt.get("configured_family_candidates", pd.Series(dtype=float)), errors="coerce").max(),
            0.0,
        )
        family_variants = int(family_variants_value) if np.isfinite(family_variants_value) else 0
        max_family_runs = int(research_config.get("max_candidate_family_runs_before_holdout", 4))
        max_family_variants = int(
            research_config.get(
                "max_candidate_family_variants_before_holdout",
                validation_config.get("max_candidate_family_variants_before_holdout", 12),
            )
        )
        add("multiple_testing", "multiple_testing_debt_report_exists", "present", "file exists", True, debt_path)
        add(
            "multiple_testing",
            "candidate_family_saved_runs",
            family_runs,
            f"<= {max_family_runs} before untouched holdout",
            family_runs <= max_family_runs,
            debt_path,
            "Too many related runs means the next acceptable evidence must come from untouched holdout/live-paper, not another variant.",
        )
        add(
            "multiple_testing",
            "candidate_family_variant_count",
            family_variants,
            f"<= {max_family_variants}",
            family_variants <= max_family_variants,
            debt_path,
            severity="warning",
        )
    else:
        add("multiple_testing", "multiple_testing_debt_report_exists", "missing", "file exists", False, debt_path)

    bar_audit_path = run_dir / "research" / "bar_exposure_audit" / "bar_exposure_audit_summary.csv"
    require_bar_audit = bool(validation_config.get("research_discipline_require_bar_exposure_audit", True))
    if bar_audit_path.exists():
        audit = pd.read_csv(bar_audit_path)
        row = audit.iloc[0] if not audit.empty else pd.Series(dtype=object)
        mismatch = _truthy(row.get("bar_pf_mismatch", False))
        decision = str(row.get("decision", ""))
        add("bar_exposure", "bar_exposure_audit_exists", "present", "file exists", True, bar_audit_path)
        add("bar_exposure", "bar_pf_reconstruction_matches_saved", not mismatch, "no mismatch", not mismatch, bar_audit_path)
        add(
            "bar_exposure",
            "bar_exposure_audit_decision",
            decision,
            "inconclusive_or_candidate_survives",
            decision == "inconclusive_or_candidate_survives",
            bar_audit_path,
            "Metric bugs, broad bar losses, or slice-only hypotheses are not promotion evidence.",
        )
    else:
        add(
            "bar_exposure",
            "bar_exposure_audit_exists",
            "missing",
            "file exists",
            not require_bar_audit,
            bar_audit_path,
            "Saved-run bar-exposure audit is required before promotion.",
        )

    exec_path = run_dir / "research" / "execution_realism" / "execution_realism_summary.csv"
    require_execution_realism = bool(validation_config.get("research_discipline_require_execution_realism", True))
    if exec_path.exists():
        exec_df = pd.read_csv(exec_path)
        add("execution", "execution_realism_report_exists", "present", "file exists", True, exec_path)
        min_exec_pf = float(validation_config.get("min_execution_realism_profit_factor", 1.0))
        for scenario in ["target_default_slippage", "target_stop_like_slippage"]:
            row = _first_row(exec_df, exec_df["scenario"].astype(str).eq(scenario))
            value = _safe_float(row.get("profit_factor") if row is not None else np.nan)
            add(
                "execution",
                f"{scenario}_profit_factor",
                value if np.isfinite(value) else "missing",
                f">= {min_exec_pf}",
                bool(np.isfinite(value) and value >= min_exec_pf),
                exec_path,
                "High-turnover strategies need to survive harsher fill assumptions.",
            )
    else:
        add(
            "execution",
            "execution_realism_report_exists",
            "missing",
            "file exists",
            not require_execution_realism,
            exec_path,
        )

    prop_summary_path = _first_existing(
        [
            run_dir / "research" / "walkforward" / "prop_firm" / "walkforward_stitched_summary.csv",
            run_dir / "research" / "prop_firm" / "prop_firm_summary.csv",
        ]
    )
    if prop_summary_path is None:
        add("prop_firm", "prop_summary_exists", "missing", "walk-forward prop summary exists", False, run_dir / "research" / "prop_firm")
    else:
        prop_summary = pd.read_csv(prop_summary_path)
        row = prop_summary.iloc[0] if not prop_summary.empty else pd.Series(dtype=object)
        scope = str(row.get("sample_scope", "missing"))
        ev = _safe_float(row.get("expected_net_payout_per_eval_attempt"))
        add("prop_firm", "prop_summary_exists", "present", "file exists", True, prop_summary_path)
        add(
            "prop_firm",
            "prop_sample_scope",
            scope,
            "walkforward_oos|lockbox",
            scope in {"walkforward_oos", "lockbox"},
            prop_summary_path,
            "In-sample prop pass rates remain research_only.",
        )
        add("prop_firm", "prop_expected_net_payout", ev, "> 0", bool(np.isfinite(ev) and ev > 0.0), prop_summary_path)

    prop_random_path = _first_existing(
        [
            run_dir / "research" / "walkforward" / "prop_firm" / "walkforward_stitched_random_walk.csv",
            run_dir / "research" / "prop_firm" / "prop_firm_random_walk.csv",
        ]
    )
    if prop_random_path is None:
        add("prop_firm", "prop_random_walk_exists", "missing", "file exists", False, run_dir / "research" / "prop_firm")
    else:
        random_walk = pd.read_csv(prop_random_path)
        row = random_walk.iloc[0] if not random_walk.empty else pd.Series(dtype=object)
        add(
            "prop_firm",
            "prop_random_walk_pnl",
            _safe_float(row.get("pnl_p_value")),
            "p <= 0.05",
            _truthy(row.get("pnl_pass_5pct")),
            prop_random_path,
        )
        add(
            "prop_firm",
            "prop_random_walk_sharpe",
            _safe_float(row.get("sharpe_p_value")),
            "p <= 0.05",
            _truthy(row.get("sharpe_pass_5pct")),
            prop_random_path,
        )

    hard_fails = [row for row in rows if row["severity"] == "hard" and row["status"] == "FAIL"]
    warnings = [row for row in rows if row["status"] == "WARN"]
    rows.append(
        {
            "section": "summary",
            "check": "promotion_eligible",
            "severity": "hard",
            "status": "PASS" if not hard_fails else "FAIL",
            "value": len(hard_fails),
            "threshold": "0 hard failures",
            "source": str(run_dir),
            "notes": f"{len(warnings)} warning(s). This is a research gate, not a backtest.",
        }
    )

    pd.DataFrame(rows).to_csv(csv_path, index=False)

    lines = [
        "# Research Discipline Gate",
        "",
        "This saved-run gate applies the anti-overfit protocol: OOS first, costs high, no prop approval from in-sample, and no strategy promotion while section-18 defenses are missing.",
        f"- Run: `{run_dir}`",
        f"- Promotion eligible: `{'yes' if not hard_fails else 'no'}`",
        f"- Hard failures: `{len(hard_fails)}`",
        f"- Warnings: `{len(warnings)}`",
        "",
        "## Checks",
    ]
    for row in rows:
        lines.append(
            f"- {row['status']} | {row['section']} | {row['check']} | "
            f"value={_fmt(row['value'])} | threshold={row['threshold']}"
        )
        if row["notes"]:
            lines.append(f"  {row['notes']}")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ResearchDisciplineReportPaths(csv_path=csv_path, markdown_path=md_path)
