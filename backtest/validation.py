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


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


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


def export_development_report(
    results: dict[str, Any],
    years: float,
    out_dir: Path | str,
    validation_config: dict[str, Any],
    walk_forward_result=None,
    walk_forward_years: float | None = None,
    in_sample_permutation=None,
    walk_forward_permutation=None,
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
    )
    add(
        "1_in_sample_excellence",
        "trades_per_year",
        in_sample_tpy,
        f">= {validation_config['min_trades_per_year']}",
        in_sample_tpy >= float(validation_config["min_trades_per_year"]),
    )

    win_rate = float(results.get("win_rate", 0.0))
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
