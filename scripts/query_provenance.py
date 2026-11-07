#!/usr/bin/env python3
"""
CLI Tool: Quantitative Backtest Provenance Query.

Enforces:
Rule 1: One source of truth (queries results/backtest_provenance.db).
Rule 2: No naked numbers (all outputs include methodology, dates, and data hash).
Rule 3: Standardized provenance footers.
Rule 4: Warnings travel with the number.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.provenance import ProvenanceStore, default_store


CANDIDATE_BANNER = """\
────────────────────────────────────────────────────────────────────────────
⚠️ [CANDIDATE TIER — QUARANTINED FROM PRODUCTION BASELINE]
────────────────────────────────────────────────────────────────────────────"""


def main():
    parser = argparse.ArgumentParser(description="Query verified backtest provenance records.")
    parser.add_argument("--strategy", type=str, help="Strategy ID (e.g., morning_va_breakout_s1, macro_momentum_s2, gold_london_fix_s3, lucid_flex_ensemble)")
    parser.add_argument("--tier", type=str, help="Filter runs by strategy tier (BASELINE, FORWARD_DEMO, CANDIDATE, REJECTED, ALL)")
    parser.add_argument("--include-candidates", action="store_true", help="Include quarantined candidate runs in queries and listings")
    parser.add_argument("--latest", action="store_true", help="Fetch the latest recorded backtest run")
    parser.add_argument("--list", action="store_true", help="List all verified backtest runs in the database")
    parser.add_argument("--run-id", type=str, help="Fetch a specific backtest run by ID")
    parser.add_argument("--stat", type=str, help="Quote a specific stat (e.g. profit_factor, win_rate, net_profit, max_drawdown)")
    parser.add_argument("--inspect-bundle", action="store_true", help="Inspect granular trade execution analytics from associated .obtf bundle")
    parser.add_argument("--hash-file", type=str, help="Compute or lookup cryptographic SHA-256 for a data file")
    parser.add_argument("--json", action="store_true", help="Output raw JSON record instead of human-readable text")
    args = parser.parse_args()

    store = default_store
    include_cand = args.include_candidates or (args.tier and args.tier.upper() in ("CANDIDATE", "ALL"))

    # 1. Hash file lookup
    if args.hash_file:
        p = Path(args.hash_file)
        h = store.compute_data_hash(p)
        print(f"File: {p}\nSHA-256: {h}")
        return

    # 2. List all runs
    if args.list:
        runs = store.list_runs(strategy_id=args.strategy, tier=args.tier, include_candidates=include_cand, limit=100)
        if not runs:
            tier_msg = f" with tier '{args.tier}'" if args.tier else ""
            print(f"No verified backtest runs found{tier_msg} in results/backtest_provenance.db.")
            return

        if args.json:
            print(json.dumps([r.to_dict() for r in runs], indent=2))
            return

        has_candidate = any(getattr(r, "strategy_tier", "") == "CANDIDATE" for r in runs)
        if has_candidate:
            print(f"\n{CANDIDATE_BANNER}\n")

        print("=" * 105)
        print(f"{'RUN ID':<32} | {'STRATEGY':<22} | {'TIER':<12} | {'METHOD':<12} | {'PF':<6} | {'WIN%':<6} | {'NET PNL':<10} | {'WARN':<5}")
        print("=" * 105)
        for r in runs:
            warn_badge = "⚠️ " if r.warnings else "✅ "
            pnl_str = f"${r.net_profit:,.0f}"
            tier_str = getattr(r, "strategy_tier", "BASELINE") or "BASELINE"
            print(f"{r.run_id:<32} | {r.strategy_id:<22} | {tier_str:<12} | {r.methodology:<12} | {r.profit_factor:<6.2f} | {r.win_rate:<5.1f}% | {pnl_str:<10} | {warn_badge}")
        print("=" * 105)
        print(f"Total verified runs: {len(runs)} (Store: {store.db_path})")
        return

    # 3. Query specific run or latest
    record = None
    if args.run_id:
        record = store.get_run(args.run_id)
        if not record:
            print(f"ERROR: Run ID '{args.run_id}' not found in {store.db_path}.", file=sys.stderr)
            sys.exit(1)
    elif args.latest or args.strategy:
        record = store.get_latest_run(strategy_id=args.strategy, include_candidates=include_cand)
        if not record:
            strat_msg = f" for strategy '{args.strategy}'" if args.strategy else ""
            print(f"ERROR: No verified backtest runs found{strat_msg} in {store.db_path}.", file=sys.stderr)
            print("To record a backtest, run the strategy engine or scripts/ingest_historical_provenance.py.", file=sys.stderr)
            sys.exit(1)
    else:
        # Default behavior: show latest run
        record = store.get_latest_run(include_candidates=include_cand)
        if not record:
            print("Store is empty. Run scripts/ingest_historical_provenance.py to seed canonical runs.", file=sys.stderr)
            sys.exit(1)

    # 4. JSON output
    if args.json:
        print(json.dumps(record.to_dict(), indent=2))
        return

    # Prominent quarantine banner for candidate records
    if getattr(record, "strategy_tier", "") == "CANDIDATE":
        print(CANDIDATE_BANNER)

    # 5. Inspect .obtf bundle
    if args.inspect_bundle:
        if not getattr(record, "bundle_path", ""):
            print(f"Error: Run '{record.run_id}' has no associated .obtf bundle recorded in provenance store.", file=sys.stderr)
            sys.exit(1)
        bundle_file = REPO_ROOT / record.bundle_path
        if not bundle_file.exists():
            print(f"Error: Bundle file '{bundle_file}' not found on disk.", file=sys.stderr)
            sys.exit(1)

        from backtest.bundle import BacktestBundle
        bundle = BacktestBundle.load(bundle_file)
        summary = bundle.get_summary()

        print("=" * 80)
        print("OPEN BACKTEST FORMAT (.obtf) BUNDLE INSPECTION")
        print("=" * 80)
        print(f"Run ID       : {summary['run_id']}")
        print(f"Strategy     : {summary['strategy_id']} ({summary['strategy_name']}) [{summary['tier']}]")
        print(f"Bundle File  : {record.bundle_path} ({bundle_file.stat().st_size:,} bytes)")
        print(f"Date Range   : {summary['date_range']} | Trades: {summary['trades_count']}")
        print("-" * 80)
        print("CORE EXECUTION METRICS:")
        for k, v in summary["core_metrics"].items():
            print(f"  {k:<22}: {v}")
        print("-" * 80)
        print("INSTITUTIONAL RISK DYNAMICS:")
        for k, v in summary["institutional_risk"].items():
            print(f"  {k:<25}: {v}")
        print("-" * 80)
        if not bundle.trades.empty:
            pnl_col = "research_pnl" if "research_pnl" in bundle.trades.columns else ("net_pnl" if "net_pnl" in bundle.trades.columns else "pnl")
            top_wins = bundle.trades.nlargest(3, pnl_col)[[pnl_col, "date"]].to_dict(orient="records")
            worst_losses = bundle.trades.nsmallest(3, pnl_col)[[pnl_col, "date"]].to_dict(orient="records")
            print("TOP 3 WINNING TRADES:")
            for t in top_wins:
                print(f"  +${t[pnl_col]:,.2f} on {t.get('date', 'N/A')}")
            print("WORST 3 LOSING TRADES:")
            for t in worst_losses:
                print(f"  -${abs(t[pnl_col]):,.2f} on {t.get('date', 'N/A')}")
        print("=" * 80)
        return

    # 6. Quote specific stat or full summary
    if args.stat:
        print(store.quote_stat(record, args.stat))
    else:
        print(store.format_footer(record))


if __name__ == "__main__":
    main()
