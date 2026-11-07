#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.simulations import run_trade_stress_tests
from config.backtest_config import BACKTEST_CONFIG, RESEARCH_CONFIG
from results.analysis import (
    export_conditional_distribution_report,
    export_robustness_reports,
    export_trade_summaries,
)
from results.visualize import plot_diagnostics, plot_results


@dataclass(frozen=True)
class RunArtifacts:
    run_dir: Path
    trade_log: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill existing run folders with current analytics, charts, and a master scorecard.",
    )
    parser.add_argument("--runs-dir", default="results/runs", help="Directory containing run folders.")
    parser.add_argument("--out-dir", default="results/research_master", help="Where master comparison files are written.")
    parser.add_argument(
        "--starting-capital",
        type=float,
        default=float(BACKTEST_CONFIG["starting_capital"]),
        help="Starting capital used for diagnostics.",
    )
    parser.add_argument("--skip-charts", action="store_true", help="Only write CSV reports and master scorecards.")
    parser.add_argument(
        "--keep-legacy-standalone",
        action="store_true",
        help="Keep old standalone backtest_equity_curve/backtest_drawdown PNGs.",
    )
    return parser.parse_args()


def discover_runs(runs_dir: Path) -> list[RunArtifacts]:
    trade_logs = sorted(runs_dir.glob("*/trades/trade_log.csv"))
    return [RunArtifacts(run_dir=path.parents[1], trade_log=path) for path in trade_logs]


def read_trades(path: Path) -> pd.DataFrame:
    trades = pd.read_csv(path)
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    trades["exit_time"] = pd.to_datetime(trades["exit_time"])
    trades["pnl"] = trades["pnl"].astype(float)
    return trades.sort_values("exit_time").reset_index(drop=True)


def remove_legacy_standalone_charts(run_dir: Path) -> list[Path]:
    removed: list[Path] = []
    for name in ("backtest_equity_curve.png", "backtest_drawdown.png"):
        path = run_dir / "charts" / name
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def backfill_run(artifact: RunArtifacts, starting_capital: float, skip_charts: bool, keep_legacy: bool) -> None:
    trades = read_trades(artifact.trade_log)
    results = {"trades": trades}

    export_trade_summaries(
        trades,
        out_dir=artifact.run_dir / "research" / "summaries",
        artifact_name="trade_summary",
    )
    export_robustness_reports(
        trades,
        out_dir=artifact.run_dir / "research" / "robustness",
        artifact_name="robustness",
        starting_capital=starting_capital,
    )
    if RESEARCH_CONFIG.get("enable_conditional_distribution_reports", True):
        export_conditional_distribution_report(
            trades,
            out_dir=artifact.run_dir / "research" / "conditional_distributions",
            artifact_name="conditional_distributions",
            min_trades=int(RESEARCH_CONFIG.get("conditional_distribution_min_trades", 30)),
            min_periods=int(RESEARCH_CONFIG.get("conditional_distribution_min_periods", 3)),
            period=str(RESEARCH_CONFIG.get("conditional_distribution_period", "Q")),
            n_bootstrap=int(RESEARCH_CONFIG.get("conditional_distribution_bootstrap_samples", 300)),
            random_seed=int(RESEARCH_CONFIG.get("conditional_distribution_random_seed", 7)),
            max_groups_per_set=int(RESEARCH_CONFIG.get("conditional_distribution_max_groups_per_set", 80)),
        )
    run_trade_stress_tests(
        results,
        starting_capital=starting_capital,
        artifact_name="stress",
        out_dir=artifact.run_dir / "simulations",
    )

    wf_trades_path = artifact.run_dir / "research" / "walkforward" / "walkforward_stitched_trades.csv"
    if wf_trades_path.exists():
        wf_trades = read_trades(wf_trades_path)
        export_trade_summaries(
            wf_trades,
            out_dir=artifact.run_dir / "research" / "walkforward" / "summaries",
            artifact_name="walkforward_stitched",
        )
        export_robustness_reports(
            wf_trades,
            out_dir=artifact.run_dir / "research" / "walkforward" / "robustness",
            artifact_name="walkforward_stitched",
            starting_capital=starting_capital,
        )
        if RESEARCH_CONFIG.get("enable_conditional_distribution_reports", True):
            export_conditional_distribution_report(
                wf_trades,
                out_dir=artifact.run_dir / "research" / "walkforward" / "conditional_distributions",
                artifact_name="walkforward_stitched",
                min_trades=int(RESEARCH_CONFIG.get("conditional_distribution_min_trades", 30)),
                min_periods=int(RESEARCH_CONFIG.get("conditional_distribution_min_periods", 3)),
                period=str(RESEARCH_CONFIG.get("conditional_distribution_period", "Q")),
                n_bootstrap=int(RESEARCH_CONFIG.get("conditional_distribution_bootstrap_samples", 300)),
                random_seed=int(RESEARCH_CONFIG.get("conditional_distribution_random_seed", 7)),
                max_groups_per_set=int(RESEARCH_CONFIG.get("conditional_distribution_max_groups_per_set", 80)),
            )

    if not skip_charts:
        plot_diagnostics(
            results,
            initial_capital=starting_capital,
            artifact_name=artifact.run_dir.name,
            base_dir=artifact.run_dir,
            copy_to_downloads=False,
        )
        plot_results(
            results,
            starting_capital=starting_capital,
            artifact_name="backtest",
            base_dir=artifact.run_dir,
        )

    if not keep_legacy:
        remove_legacy_standalone_charts(artifact.run_dir)


def profit_factor(pnl: pd.Series) -> float:
    wins = float(pnl[pnl > 0].sum())
    losses = abs(float(pnl[pnl <= 0].sum()))
    if losses == 0:
        return np.nan
    return wins / losses


def max_drawdown_pct_from_pnl(pnl: pd.Series, starting_capital: float) -> float:
    equity = pnl.astype(float).cumsum() + float(starting_capital)
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    drawdown = np.where(peak > 0, (peak - equity) / peak * 100.0, 0.0)
    return float(np.nanmax(drawdown))


def summarize_trades(trades: pd.DataFrame, starting_capital: float) -> dict[str, float]:
    total_pnl = float(trades["pnl"].sum())
    return {
        "trades": float(len(trades)),
        "total_pnl": total_pnl,
        "profit_factor": profit_factor(trades["pnl"]),
        "avg_trade": float(trades["pnl"].mean()) if len(trades) else np.nan,
        "win_rate_pct": float((trades["pnl"] > 0).mean() * 100.0) if len(trades) else np.nan,
        "max_drawdown_pct": max_drawdown_pct_from_pnl(trades["pnl"], starting_capital),
    }


def read_first_row(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


def get_period_metric(path: Path, period: str, metric: str) -> float:
    if not path.exists():
        return np.nan
    df = pd.read_csv(path)
    if df.empty or "period_type" not in df.columns or "period" not in df.columns:
        return np.nan
    mask = df["period_type"].astype(str).eq("market_era") & df["period"].astype(str).eq(period)
    if not mask.any() or metric not in df.columns:
        return np.nan
    return float(df.loc[mask, metric].iloc[0])


def get_scenario_metric(path: Path, scenario: str, metric: str) -> float:
    if not path.exists():
        return np.nan
    df = pd.read_csv(path)
    if df.empty or "scenario" not in df.columns or metric not in df.columns:
        return np.nan
    mask = df["scenario"].astype(str).eq(scenario)
    if not mask.any():
        return np.nan
    return float(df.loc[mask, metric].iloc[0])


def pass_fail(ok: bool | None) -> str:
    if ok is None:
        return "SKIP"
    return "PASS" if ok else "FAIL"


def finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def build_checks(row: dict[str, Any]) -> list[dict[str, Any]]:
    def check(name: str, value: Any, threshold: str, ok: bool | None, critical: bool = False) -> dict[str, Any]:
        return {
            "run": row["run"],
            "check": name,
            "status": pass_fail(ok),
            "value": value,
            "threshold": threshold,
            "critical": critical,
        }

    checks = [
        check(
            "sample_size",
            row.get("trades"),
            ">= 300 trades",
            finite(row.get("trades")) and row["trades"] >= 300,
            True,
        ),
        check("profit_factor", row.get("profit_factor"), ">= 1.30", finite(row.get("profit_factor")) and row["profit_factor"] >= 1.30, True),
        check("avg_trade", row.get("avg_trade"), ">= $25", finite(row.get("avg_trade")) and row["avg_trade"] >= 25.0, True),
        check("max_drawdown", row.get("max_drawdown_pct"), "<= 25%", finite(row.get("max_drawdown_pct")) and row["max_drawdown_pct"] <= 25.0),
        check("net_profit_to_dd", row.get("net_profit_to_max_drawdown"), ">= 1.50", finite(row.get("net_profit_to_max_drawdown")) and row["net_profit_to_max_drawdown"] >= 1.50),
        check("profitable_years", row.get("pct_years_profitable"), ">= 50%", finite(row.get("pct_years_profitable")) and row["pct_years_profitable"] >= 50.0),
        check("pre_2020_survival", row.get("pre_2020_profit_factor"), "PF >= 1.00 and PnL > 0", finite(row.get("pre_2020_profit_factor")) and row["pre_2020_profit_factor"] >= 1.0 and row.get("pre_2020_total_pnl", -1.0) > 0),
        check("post_2020_survival", row.get("post_2020_profit_factor"), "PF >= 1.00 and PnL > 0", finite(row.get("post_2020_profit_factor")) and row["post_2020_profit_factor"] >= 1.0 and row.get("post_2020_total_pnl", -1.0) > 0),
        check("remove_best_5", row.get("remove_best_5_total_pnl"), "PnL remains > 0", finite(row.get("remove_best_5_total_pnl")) and row["remove_best_5_total_pnl"] > 0),
        check("remove_best_1_pct", row.get("remove_best_1_pct_total_pnl"), "PnL remains > 0", finite(row.get("remove_best_1_pct_total_pnl")) and row["remove_best_1_pct_total_pnl"] > 0),
        check("extra_cost_25", row.get("extra_cost_25_profit_factor"), "PF >= 1.00 and PnL > 0", finite(row.get("extra_cost_25_profit_factor")) and row["extra_cost_25_profit_factor"] >= 1.0 and row.get("extra_cost_25_total_pnl", -1.0) > 0, True),
        check("combined_mild_stress", row.get("combined_mild_profit_factor"), "PF >= 1.00 and PnL > 0", finite(row.get("combined_mild_profit_factor")) and row["combined_mild_profit_factor"] >= 1.0 and row.get("combined_mild_total_pnl", -1.0) > 0, True),
    ]

    if finite(row.get("walkforward_profit_factor")):
        checks.append(
            check(
                "walkforward_oos",
                row.get("walkforward_profit_factor"),
                "PF >= 1.05 and PnL > 0",
                row["walkforward_profit_factor"] >= 1.05 and row.get("walkforward_total_pnl", -1.0) > 0,
                True,
            )
        )
    else:
        checks.append(check("walkforward_oos", np.nan, "PF >= 1.05 and PnL > 0", None, True))
    return checks


def verdict_from_checks(checks: list[dict[str, Any]]) -> tuple[float, str]:
    scored = [c for c in checks if c["status"] != "SKIP"]
    if not scored:
        return 0.0, "NO_DATA"
    pass_count = sum(c["status"] == "PASS" for c in scored)
    critical_fails = sum(c["critical"] and c["status"] == "FAIL" for c in scored)
    score_pct = pass_count / len(scored) * 100.0
    if score_pct >= 80.0 and critical_fails == 0:
        verdict = "WATCHLIST"
    elif score_pct >= 65.0 and critical_fails <= 2:
        verdict = "NEEDS_RESEARCH"
    else:
        verdict = "DO_NOT_TRADE"
    return score_pct, verdict


def build_master_rows(runs: list[RunArtifacts], starting_capital: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    comparison_rows: list[dict[str, Any]] = []
    score_rows: list[dict[str, Any]] = []

    for artifact in runs:
        run_dir = artifact.run_dir
        trades = read_trades(artifact.trade_log)
        quality_path = run_dir / "research" / "robustness" / "robustness_quality_metrics.csv"
        period_path = run_dir / "research" / "robustness" / "robustness_period_summary.csv"
        outlier_path = run_dir / "research" / "robustness" / "robustness_outlier_dependence.csv"
        stress_path = run_dir / "simulations" / "stress_trade_stress_tests.csv"
        wf_path = run_dir / "research" / "walkforward" / "walkforward_stitched_trades.csv"

        row: dict[str, Any] = {"run": run_dir.name}
        row.update(read_first_row(quality_path))
        if "total_pnl" not in row and "net_profit" in row:
            row["total_pnl"] = row["net_profit"]
        if not row.get("trades"):
            row.update(summarize_trades(trades, starting_capital))

        for era in ("pre_2020", "post_2020"):
            row[f"{era}_total_pnl"] = get_period_metric(period_path, era, "total_pnl")
            row[f"{era}_profit_factor"] = get_period_metric(period_path, era, "profit_factor")
            row[f"{era}_trades"] = get_period_metric(period_path, era, "trades")

        row["remove_best_5_total_pnl"] = get_scenario_metric(outlier_path, "remove_best_5_trades", "total_pnl")
        row["remove_best_5_profit_retained_pct"] = get_scenario_metric(
            outlier_path,
            "remove_best_5_trades",
            "net_profit_retained_pct",
        )
        row["remove_best_1_pct_total_pnl"] = get_scenario_metric(outlier_path, "remove_best_1_pct", "total_pnl")
        row["remove_best_1_pct_profit_retained_pct"] = get_scenario_metric(
            outlier_path,
            "remove_best_1_pct",
            "net_profit_retained_pct",
        )
        row["top_1_pct_profit_share_pct"] = get_scenario_metric(outlier_path, "concentration", "top_1_pct_profit_share_pct")
        row["top_5_pct_profit_share_pct"] = get_scenario_metric(outlier_path, "concentration", "top_5_pct_profit_share_pct")

        row["extra_cost_25_total_pnl"] = get_scenario_metric(stress_path, "extra_cost_25_per_trade", "total_pnl")
        row["extra_cost_25_profit_factor"] = get_scenario_metric(stress_path, "extra_cost_25_per_trade", "profit_factor")
        row["combined_mild_total_pnl"] = get_scenario_metric(stress_path, "combined_mild", "total_pnl")
        row["combined_mild_profit_factor"] = get_scenario_metric(stress_path, "combined_mild", "profit_factor")
        row["combined_harsh_total_pnl"] = get_scenario_metric(stress_path, "combined_harsh", "total_pnl")
        row["combined_harsh_profit_factor"] = get_scenario_metric(stress_path, "combined_harsh", "profit_factor")

        if wf_path.exists():
            wf_summary = summarize_trades(read_trades(wf_path), starting_capital)
            row["walkforward_trades"] = wf_summary["trades"]
            row["walkforward_total_pnl"] = wf_summary["total_pnl"]
            row["walkforward_profit_factor"] = wf_summary["profit_factor"]
            row["walkforward_avg_trade"] = wf_summary["avg_trade"]
            row["walkforward_max_drawdown_pct"] = wf_summary["max_drawdown_pct"]
        else:
            row["walkforward_trades"] = np.nan
            row["walkforward_total_pnl"] = np.nan
            row["walkforward_profit_factor"] = np.nan
            row["walkforward_avg_trade"] = np.nan
            row["walkforward_max_drawdown_pct"] = np.nan

        checks = build_checks(row)
        score_pct, verdict = verdict_from_checks(checks)
        row["approval_score_pct"] = score_pct
        row["approval_verdict"] = verdict
        row["approval_passes"] = sum(c["status"] == "PASS" for c in checks)
        row["approval_fails"] = sum(c["status"] == "FAIL" for c in checks)
        row["approval_skips"] = sum(c["status"] == "SKIP" for c in checks)

        comparison_rows.append(row)
        score_rows.extend(checks)

    comparison = pd.DataFrame(comparison_rows)
    scorecard = pd.DataFrame(score_rows)
    if not comparison.empty:
        comparison = comparison.sort_values(
            ["approval_score_pct", "profit_factor", "total_pnl"],
            ascending=[False, False, False],
        )
    return comparison, scorecard


def write_markdown(comparison: pd.DataFrame, scorecard: pd.DataFrame, path: Path) -> None:
    def markdown_table(df: pd.DataFrame) -> str:
        if df.empty:
            return ""
        cols = list(df.columns)
        lines = [
            "| " + " | ".join(cols) + " |",
            "| " + " | ".join(["---"] * len(cols)) + " |",
        ]
        for _, row in df.iterrows():
            values = []
            for col in cols:
                value = row[col]
                if isinstance(value, float):
                    values.append("" if np.isnan(value) else f"{value:.2f}")
                else:
                    values.append(str(value))
            lines.append("| " + " | ".join(values) + " |")
        return "\n".join(lines)

    lines = [
        "# Run Comparison and Approval Scorecard",
        "",
        "This report is a triage tool, not live-trading approval.",
        "",
    ]
    if comparison.empty:
        lines.append("No runs found.")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    cols = [
        "run",
        "approval_verdict",
        "approval_score_pct",
        "trades",
        "total_pnl",
        "profit_factor",
        "avg_trade",
        "max_drawdown_pct",
        "net_profit_to_max_drawdown",
        "walkforward_profit_factor",
    ]
    table = comparison[[c for c in cols if c in comparison.columns]].copy()
    lines.append("## Ranking")
    lines.append("")
    lines.append(markdown_table(table))
    lines.append("")

    lines.append("## Failed Critical Checks")
    lines.append("")
    critical_fails = scorecard[(scorecard["critical"]) & (scorecard["status"] == "FAIL")]
    if critical_fails.empty:
        lines.append("No critical failures.")
    else:
        lines.append(markdown_table(critical_fails[["run", "check", "value", "threshold"]]))
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    runs_dir = Path(args.runs_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    runs = discover_runs(runs_dir)
    if not runs:
        print(f"No run trade logs found under {runs_dir}")
        return 1

    print(f"Found {len(runs)} runs.")
    for idx, artifact in enumerate(runs, start=1):
        print(f"[{idx}/{len(runs)}] Backfilling {artifact.run_dir.name}")
        backfill_run(
            artifact,
            starting_capital=float(args.starting_capital),
            skip_charts=bool(args.skip_charts),
            keep_legacy=bool(args.keep_legacy_standalone),
        )

    comparison, scorecard = build_master_rows(runs, starting_capital=float(args.starting_capital))
    comparison_csv = out_dir / "run_comparison.csv"
    scorecard_csv = out_dir / "approval_scorecard.csv"
    markdown_path = out_dir / "run_comparison.md"
    comparison.to_csv(comparison_csv, index=False)
    scorecard.to_csv(scorecard_csv, index=False)
    write_markdown(comparison, scorecard, markdown_path)

    print(f"Comparison CSV: {comparison_csv}")
    print(f"Scorecard CSV:  {scorecard_csv}")
    print(f"Markdown:       {markdown_path}")
    if not comparison.empty:
        print("\nTop runs by approval score:")
        cols = ["run", "approval_verdict", "approval_score_pct", "profit_factor", "avg_trade", "total_pnl"]
        print(comparison[cols].head(5).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
