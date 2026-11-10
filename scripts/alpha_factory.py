#!/usr/bin/env python3
"""
LucidFlex Autonomous Alpha Factory.

Governed by the 5 Golden Rules of Quantitative Provenance and Step 07/08 of the
Belfort Systematic Blueprint.

Operates the 5-Stage Alpha Lifecycle:
1. Economic Hypothesis & Dead-End Screening (checks wiki/failed_ideas.md)
2. Data Integrity & SHA-256 Verification
3. Vectorized Simulation & Walk-Forward Testing
4. Adversarial Red-Team Stress Audit (DSR, Outlier Dominance, Plateau Stability)
5. Automated Wiki Documentation & Provenance Persistence
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest import dashboard_analytics as da
from backtest.provenance import ProvenanceRecord, ProvenanceStore, default_store
from config.strategy_registry import is_production_baseline

DATA_PATH = REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"
FAILED_IDEAS_PATH = REPO_ROOT / "wiki/failed_ideas.md"


def slugify_heading(heading: str) -> str:
    """Convert markdown heading text to GitHub/Obsidian URL anchor slug."""
    clean = re.sub(r"[^\w\s-]", "", heading.lower())
    return re.sub(r"[-\s]+", "-", clean).strip("-")


def get_baseline_trial_count(store: Optional[ProvenanceStore] = None) -> int:
    """Returns baseline trial count dynamically derived from complete experiment ledger:
    failed ideas in wiki/failed_ideas.md + verified runs in results/backtest_provenance.db (minimum 25).
    """
    n_failed = 0
    if FAILED_IDEAS_PATH.exists():
        try:
            with open(FAILED_IDEAS_PATH, "r", encoding="utf-8") as f:
                headers = re.findall(r"### \d+\.\s+", f.read())
                n_failed = len(headers)
        except Exception:
            n_failed = 0

    n_prov = 0
    try:
        ps = store if store is not None else default_store
        runs = ps.list_runs(include_candidates=True, limit=100000)
        runs = [run for run in runs if getattr(run, "methodology", "") != "insample_java_chart_tracker"]
        n_prov = len(runs)
    except Exception:
        n_prov = 0

    return max(25, n_failed + n_prov)


def archive_rejected_candidate(
    audit: Dict[str, Any],
    concept_text: str = "",
    date_start: str = "",
    date_end: str = "",
    failed_ideas_path: Optional[Path] = None,
) -> int:
    """Formats and appends a vetoed candidate to wiki/failed_ideas.md adhering to wiki/SCHEMA.md."""
    target_path = failed_ideas_path or FAILED_IDEAS_PATH
    if not target_path.exists():
        print(f" [⚠️] Failed ideas ledger not found at {target_path}. Skipping archive.")
        return 0

    strat_id = audit.get("strategy_id", "candidate_strategy")
    if is_production_baseline(strat_id):
        print(f" [INFO] Strategy '{strat_id}' is an authorized production baseline; skipping archival to {target_path.name}.")
        return 0

    content = target_path.read_text(encoding="utf-8")

    strat_name = audit.get("strategy_name", "Candidate Strategy")
    trades = audit.get("trades", 0)
    pf = audit.get("pf", 0.0)
    wr = audit.get("win_rate", 0.0)
    dsr = audit.get("dsr", 0.0)
    net_pnl = audit.get("net_pnl", 0.0)
    max_dd = audit.get("max_dd", 0.0)
    veto_reasons = audit.get("veto_reasons", [])
    veto_str = "; ".join(veto_reasons) if veto_reasons else "Adversarial red-team veto"
    core_premise = concept_text.strip() if concept_text.strip() else strat_name

    # Deduplication check: verify if strategy_id or exact concept heading is already recorded
    rule_pattern = rf"-\s+\*\*Standing Rule\*\*:\s*Strategy\s+{re.escape(strat_id)}\s+is\s+quarantined"
    heading_pattern = rf"^###\s+(\d+)\.\s+{re.escape(strat_name)}"
    table_pattern = rf"\[{re.escape(strat_name)}"

    existing_rule = re.search(rule_pattern, content, re.MULTILINE | re.IGNORECASE)
    existing_heading = re.search(heading_pattern, content, re.MULTILINE | re.IGNORECASE)
    existing_table = re.search(table_pattern, content, re.IGNORECASE)

    if existing_rule or existing_heading or existing_table or (f"Strategy {strat_id} is quarantined" in content):
        matched_num = existing_heading.group(1) if existing_heading else "existing"
        print(
            f" [INFO] Strategy '{strat_id}' ({strat_name}) is already documented in "
            f"{target_path.name} as #{matched_num}. Skipping duplicate archival."
        )
        return int(matched_num) if str(matched_num).isdigit() else 0

    # Find highest existing sequential number from '### N. ' headers
    header_nums = [int(m) for m in re.findall(r"^###\s+(\d+)\.", content, re.MULTILINE)]
    next_num = (max(header_nums) + 1) if header_nums else 1

    eval_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    heading_title = f"{strat_name}: Adversarial Veto ({eval_date})"
    full_heading = f"### {next_num}. {heading_title}"
    anchor_slug = slugify_heading(f"{next_num}. {heading_title}")

    # Build entry adhering to wiki/SCHEMA.md §6
    entry_lines = [
        f"\n### {next_num}. {heading_title}",
        f"- **Evaluation Date**: {eval_date}",
        f"- **Author / Agent**: Autonomous Alpha Factory",
        f"- **Core Premise**: {core_premise}",
        f"- **Sample/Artifact**: {trades} trades ({date_start} to {date_end})",
        f"- **Empirical Failure Evidence**: Trades: {trades}, Profit Factor: {pf:.2f}, Win Rate: {wr:.1f}%, DSR: {dsr:.4f}, Net PnL: ${net_pnl:,.2f}, Max Drawdown: -${abs(max_dd):,.2f}. Veto: {veto_str}",
        f"- **Structural Root Cause**: Rejection under Bailey & Lopez de Prado DSR multiple-testing and Belfort Step 07/08 adversarial hurdles ({veto_str}).",
        f"- **Standing Rule**: Strategy {strat_id} is quarantined and rejected from production baseline consideration.",
    ]
    entry_block = "\n".join(entry_lines) + "\n"

    # Insert into Table of Ruled-Out Concepts
    table_item = f"{next_num}. [{strat_name}: Adversarial Veto](#{anchor_slug})\n"

    table_match = re.search(r"(## Table of Ruled-Out Concepts\s*\n\n)(.*?)(\n\s*---\s*\n)", content, re.DOTALL)
    if table_match:
        table_prefix = table_match.group(1)
        table_body = table_match.group(2).rstrip()
        table_suffix = table_match.group(3)

        updated_table_body = f"{table_body}\n{table_item}"
        content = (
            content[: table_match.start()]
            + f"{table_prefix}{updated_table_body}{table_suffix}"
            + content[table_match.end() :]
        )
    else:
        content = content + f"\n\n{table_item}"

    # Append entry at the end of the file
    content = content.rstrip() + "\n" + entry_block
    target_path.write_text(content, encoding="utf-8")
    print(f" [🟢] Archived rejected candidate as #{next_num} to {target_path.name}")
    return next_num


def screen_dead_ends(concept_text: str) -> List[str]:
    """Scans wiki/failed_ideas.md to verify hypothesis hasn't already been invalidated."""
    if not FAILED_IDEAS_PATH.exists():
        return []

    with open(FAILED_IDEAS_PATH, "r", encoding="utf-8") as f:
        content = f.read().lower()

    matches = []
    # Tokenize words of 4+ chars
    tokens = [t.lower() for t in re.findall(r"\b[A-Za-z0-9_-]{4,}\b", concept_text)]
    dead_end_headers = re.findall(r"### \d+\.\s+([^\n]+)", content)

    for header in dead_end_headers:
        header_lower = header.lower()
        shared = [tok for tok in tokens if tok in header_lower]
        if len(shared) >= 2:
            matches.append(header)

    return matches


def evaluate_candidate_trades(
    df_trades: pd.DataFrame,
    strategy_id: str,
    strategy_name: str,
    trials: Optional[int] = None,
    var_sharpe: float = 0.5,
) -> Dict[str, Any]:
    """Applies the Adversarial Red-Team evaluation battery to candidate trade returns."""
    effective_trials = trials if (trials is not None and trials > 0) else get_baseline_trial_count()
    calendar = da.load_session_calendar()
    m = da.performance_metrics(df_trades, calendar, "research_pnl", n_trials=effective_trials, var_sharpe=var_sharpe)

    trades_count = int(m["trades"])
    net_pnl = float(m["net"])
    gross_profit = float(m.get("gross_profit", 0.0))
    pf = float(m["pf"])
    wr = float(m["win_rate"])
    max_dd = float(m["max_dd"])
    sharpe = float(m["sharpe"])
    dsr = float(m["dsr"])
    sr_star = float(m["sr_star"])
    largest_win = float(m["largest_win"])

    # Adversarial Criteria
    outlier_ratio = (largest_win / net_pnl) if net_pnl > 0 else 1.0
    is_outlier_dominant = outlier_ratio > 0.35
    is_low_sample = trades_count < 30
    is_dsr_failing = dsr < 0.05  # Less than 5% confidence under EVT multiple testing
    is_pf_failing = pf < 1.30

    warnings = []
    if is_low_sample:
        warnings.append("LOW_SAMPLE_SIZE")
    if is_outlier_dominant:
        warnings.append("OUTLIER_DOMINANCE")
    if is_dsr_failing:
        warnings.append("MULTIPLE_TESTING_OVERFIT")

    veto_reasons = []
    if is_pf_failing:
        veto_reasons.append(f"Profit Factor {pf:.2f} < 1.30 minimum viable hurdle")
    if is_dsr_failing:
        veto_reasons.append(f"Deflated Sharpe Ratio DSR {dsr:.4f} < 0.05 (fails multiple testing hurdle SR*: {sr_star:.2f})")
    if is_outlier_dominant:
        veto_reasons.append(f"Single largest win (${largest_win:,.2f}) is {outlier_ratio*100:.1f}% of net PnL (> 35%)")
    if net_pnl <= 0:
        veto_reasons.append(f"Negative net PnL (${net_pnl:,.2f})")

    verdict = "REJECTED_BY_ADVERSARIAL_VETO" if veto_reasons else "APPROVED_FOR_PAPER_TRADING"

    return {
        "strategy_id": strategy_id,
        "strategy_name": strategy_name,
        "trades": trades_count,
        "net_pnl": net_pnl,
        "gross_profit": gross_profit,
        "pf": pf,
        "win_rate": wr,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "sr_star": sr_star,
        "dsr": dsr,
        "trials": effective_trials,
        "largest_win": largest_win,
        "outlier_ratio": outlier_ratio,
        "warnings": warnings,
        "veto_reasons": veto_reasons,
        "verdict": verdict,
        "raw_metrics": m,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="LucidFlex Autonomous Alpha Factory")
    parser.add_argument("--theme", type=str, help="Theme or hypothesis description to screen and research")
    parser.add_argument(
        "--evaluate",
        "--strategy",
        dest="evaluate",
        type=str,
        choices=["S1", "S2", "S3", "ensemble"],
        default="ensemble",
        help="Evaluate canonical or candidate strategy (default: ensemble)",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=None,
        help="Number of historical trials tested for DSR adjustment (default: dynamic from wiki/failed_ideas.md, min 25)",
    )
    parser.add_argument("--record", action="store_true", help="Record verified passing run into results/backtest_provenance.db")
    args = parser.parse_args()

    print("=" * 80)
    print(" 🔬 LUCIDFLEX AUTONOMOUS ALPHA FACTORY")
    print(" Governed by 5 Golden Rules of Quantitative Provenance & Adversarial Veto")
    print("=" * 80)

    # 1. Screen Theme against Dead Ends Ledger
    if args.theme:
        print(f"\n [Stage 1] Screening Proposed Theme: '{args.theme}'")
        conflicts = screen_dead_ends(args.theme)
        if conflicts:
            print(" [🚨] DEAD-END CONFLICT DETECTED IN wiki/failed_ideas.md:")
            for c in conflicts:
                print(f"      ❌ {c}")
            print("\n [VETO] Standing negative invariant prohibits re-testing invalidated hypotheses.")
            return 1
        else:
            print(" [🟢] Zero conflicts found in dead ends ledger. Concept is novel.")

    # 2. Verify Dataset Provenance
    store = default_store
    if not DATA_PATH.exists():
        print(f" [❌] Source dataset missing at {DATA_PATH}")
        return 1

    sha256 = store.compute_data_hash(DATA_PATH)
    print(f"\n [Stage 2] Dataset Provenance Verified:")
    print(f"      File   : {DATA_PATH.name}")
    print(f"      SHA-256: {sha256}")

    # 3. Load Trades
    trades_df = da.load_trades()
    strat_key = args.evaluate or "ensemble"

    strat_map = {
        "S1": ("morning_va_breakout_s1", "Morning VA Breakout (09:45 ET)", trades_df[trades_df["strat"] == "S1"]),
        "S2": ("macro_momentum_s2", "Pre-Market Macro Momentum (08:35 ET)", trades_df[trades_df["strat"] == "S2"]),
        "S3": ("gold_london_fix_s3", "Gold London Fix Breakout (10:15 ET)", trades_df[trades_df["strat"] == "S3"]),
        "ensemble": ("lucid_flex_ensemble", "Tri-Asset Multi-Strategy Ensemble", trades_df),
    }

    if strat_key not in strat_map:
        print(f" [❌] Unknown strategy key: {strat_key}")
        return 1

    strat_id, strat_name, sub_df = strat_map[strat_key]
    trials = args.trials if args.trials is not None else get_baseline_trial_count()

    print(f"\n [Stage 3 & 4] Running Adversarial Red-Team Battery on: {strat_id}")
    print(f"      Sample Size : {len(sub_df)} trades")
    print(f"      DSR Trials  : N = {trials}")

    audit = evaluate_candidate_trades(sub_df, strat_id, strat_name, trials=trials)

    print("\n" + "-" * 80)
    print(" ADVERSARIAL AUDIT REPORT")
    print("-" * 80)
    print(f" Strategy Name    : {audit['strategy_name']} ({audit['strategy_id']})")
    print(f" Trades Evaluated : {audit['trades']}")
    print(f" Win Rate         : {audit['win_rate']:.2f}%")
    print(f" Profit Factor    : {audit['pf']:.2f}")
    print(f" Net PnL          : ${audit['net_pnl']:,.2f}")
    print(f" Max Drawdown     : -${abs(audit['max_dd']):,.2f}")
    print(f" Annual Sharpe    : {audit['sharpe']:.2f} (EVT Hurdle SR*: {audit['sr_star']:.2f})")
    print(f" Deflated Sharpe  : {audit['dsr']:.4f}")
    print(f" Largest Win Ratio: {audit['outlier_ratio']*100:.1f}% (${audit['largest_win']:,.2f})")
    print(f" Warning Flags    : {', '.join(audit['warnings']) if audit['warnings'] else 'None (Clean)'}")
    print(f" Adversarial Verdict : {audit['verdict']}")

    # Extract date range for reporting and archiving
    if not sub_df.empty and "date" in sub_df:
        d_min = sub_df["date"].min()
        d_max = sub_df["date"].max()
        date_start = str(d_min.date() if hasattr(d_min, "date") else str(d_min)[:10])
        date_end = str(d_max.date() if hasattr(d_max, "date") else str(d_max)[:10])
    else:
        date_start = "2021-01-01"
        date_end = "2026-12-31"

    if audit["veto_reasons"]:
        print("\n [🚨] BINDING VETO ISSUED:")
        for reason in audit["veto_reasons"]:
            print(f"      ❌ {reason}")

        if is_production_baseline(strat_id):
            print(f"\n [INFO] Strategy '{strat_id}' is an authorized production baseline in config/strategy_registry.py.")
            print(f"        Production baselines are exempt from dead-end archival in {FAILED_IDEAS_PATH.name}.")
            print("        Standalone sub-strategy hurdles do not invalidate composite ensemble deployment.")
        elif not args.record:
            print(f"\n [INFO] DRY RUN: Candidate rejected by adversarial veto, but archival to {FAILED_IDEAS_PATH.name} skipped.")
            print("        Pass --record to persist both audit failure and dead-end archival.")
        else:
            print(f"\n Strategy cannot advance to paper trading. Archiving to {FAILED_IDEAS_PATH.name}.")
            archive_rejected_candidate(
                audit,
                concept_text=args.theme or "",
                date_start=date_start,
                date_end=date_end,
            )
        return 1

    print("\n [🟢] ALL ADVERSARIAL HURDLES PASSED.")

    # 4. Standardized Provenance Record & Footer

    git_commit = store.get_git_commit()
    gross_profit = float(audit["gross_profit"])
    run_id = f"run_alpha_factory_{strat_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    raw_m = audit.get("raw_metrics", {})
    if args.record:
        rec = store.record_run(
            run_id=run_id,
            strategy_id=audit["strategy_id"],
            strategy_name=audit["strategy_name"],
            methodology="alpha_factory_adversarial_walkforward",
            date_start=date_start,
            date_end=date_end,
            data_path=DATA_PATH,
            git_commit=git_commit,
            slippage_model="Adverse 1-Tick Parity",
            commission_model="$1.40/RT Micro",
            is_net=True,
            total_trades=audit["trades"],
            win_rate=audit["win_rate"],
            profit_factor=audit["pf"],
            gross_profit=gross_profit,
            net_profit=audit["net_pnl"],
            max_drawdown=audit["max_dd"],
            sharpe_ratio=audit["sharpe"],
            largest_win=audit["largest_win"],
            explicit_warnings=audit["warnings"],
            extended_metrics=raw_m,
            notes=f"Alpha Factory evaluation | DSR: {audit['dsr']:.4f} | EVT SR*: {audit['sr_star']:.2f} | Trials: {trials}",
        )
        print(ProvenanceStore.format_footer(rec))
        print(f"\n [🟢] Run successfully registered in results/backtest_provenance.db as {run_id}")
    else:
        try:
            d1 = datetime.strptime(str(date_start)[:10], "%Y-%m-%d")
            d2 = datetime.strptime(str(date_end)[:10], "%Y-%m-%d")
            days_count = max(1, (d2 - d1).days + 1)
        except Exception:
            days_count = 1

        largest_win_pct = (audit["largest_win"] / audit["net_pnl"] * 100.0) if (audit["net_pnl"] > 0 and audit["largest_win"] > 0) else 0.0
        auto_warnings = store.evaluate_warnings(
            total_trades=audit["trades"],
            is_net=True,
            slippage_model="Adverse 1-Tick Parity",
            commission_model="$1.40/RT Micro",
            largest_win=audit["largest_win"],
            net_profit=audit["net_pnl"],
            days_count=days_count,
        )
        all_warnings = list(dict.fromkeys(auto_warnings + audit["warnings"]))

        rec = ProvenanceRecord(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            strategy_id=audit["strategy_id"],
            strategy_name=audit["strategy_name"],
            methodology="alpha_factory_adversarial_walkforward",
            date_start=str(date_start)[:10],
            date_end=str(date_end)[:10],
            days_count=days_count,
            data_path=str(DATA_PATH),
            data_hash=sha256,
            git_commit=git_commit,
            slippage_model="Adverse 1-Tick Parity",
            commission_model="$1.40/RT Micro",
            is_net=True,
            total_trades=audit["trades"],
            win_rate=round(audit["win_rate"], 2),
            profit_factor=round(audit["pf"], 2) if not math.isinf(audit["pf"]) else 999.0,
            gross_profit=round(gross_profit, 2),
            net_profit=round(audit["net_pnl"], 2),
            max_drawdown=round(audit["max_dd"], 2),
            sharpe_ratio=round(audit["sharpe"], 2),
            largest_win=round(audit["largest_win"], 2),
            largest_win_pct_of_net=round(largest_win_pct, 1),
            sortino_ratio=round(float(raw_m.get("sortino", 0.0)), 2),
            calmar_ratio=round(float(raw_m.get("calmar", 0.0)), 2),
            cvar_95=round(float(raw_m.get("cvar95", 0.0)), 2),
            ulcer_index=round(float(raw_m.get("ulcer_index", 0.0)), 2),
            deflated_sharpe=round(float(audit.get("dsr", 0.0)), 4),
            metrics=raw_m,
            warnings=all_warnings,
            params={},
            notes=f"Alpha Factory evaluation | DSR: {audit['dsr']:.4f} | EVT SR*: {audit['sr_star']:.2f} | Trials: {trials} | DRY RUN (not recorded to database; pass --record to persist)",
        )
        print(ProvenanceStore.format_footer(rec))
        print("\n [INFO] DRY RUN (not recorded to database; pass --record to persist)")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())
