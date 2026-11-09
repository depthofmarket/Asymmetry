#!/usr/bin/env python3
"""
Candidate Strategy S5 (Crude Oil Post-Fix Range Expansion) Provenance Backtest Runner.

Executes:
1. Cryptographic SHA-256 verification of continuous CL data asset (Rule 2).
2. Point-in-time multi-year walkforward backtest on MCL (2021-01-04 to 2026-10-30).
3. Friction accounting ($3.50/RT commission, 1-tick limit slip, 2-tick stop slip).
4. Automatic persistence to results/backtest_provenance.db under StrategyTier.CANDIDATE (Rule 1 & 5).
5. Open Backtest Format (.obtf) bundle generation (Tier 2 portable container).
6. Output of standardized Provenance Verification Footer (Rule 3).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

# Add project root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from backtest import metrics as bm
from backtest.bundle import BacktestBundle
from backtest.provenance import ProvenanceStore, default_store
from config.strategy_registry import StrategyTier
from strategies.crude_rth_expansion_s5 import (
    CrudeRthExpansionParams,
    CrudeRthExpansionS5,
)

EXPECTED_DATA_SHA256 = "7f99fefece90be3114b7eb39060a5fe251038700a7238d3e1caac4f5909d1c90"


def main():
    parser = argparse.ArgumentParser(
        description="Run Candidate S5 Crude Oil Post-Fix Range Expansion backtest and record provenance."
    )
    parser.add_argument(
        "--data-path",
        type=str,
        default="data/raw/cl_1m_2020_2026_et.parquet",
        help="Path to continuous 1m parquet dataset.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2021-01-04",
        help="Evaluation start date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default="2026-10-30",
        help="Evaluation end date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default="run_canonical_s5_crude_rth_expansion_2021_2026",
        help="Unique identifier for the backtest run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run backtest without recording to results/backtest_provenance.db.",
    )
    args = parser.parse_args()

    data_path = Path(args.data_path)
    if not data_path.is_absolute():
        data_path = REPO_ROOT / data_path

    if not data_path.exists():
        print(f"ERROR: Dataset not found at {data_path}", file=sys.stderr)
        sys.exit(1)

    print("=" * 80)
    print(" CANDIDATE S5: CRUDE OIL POST-FIX RANGE EXPANSION (MCL 10:15–12:30 ET)")
    print("=" * 80)
    print(f"Data File       : {data_path}")

    # 1. Cryptographic SHA-256 verification (Rule 2)
    computed_hash = default_store.compute_data_hash(data_path)
    print(f"Data SHA-256    : {computed_hash}")
    if computed_hash != EXPECTED_DATA_SHA256:
        print(
            f"WARNING: Computed hash does not match expected canonical hash!\n"
            f"  Expected: {EXPECTED_DATA_SHA256}\n"
            f"  Computed: {computed_hash}"
        )
    else:
        print("Data Hash Status: ✅ VERIFIED MATCH")

    # 2. Execute Backtest
    print(f"\nExecuting backtest for evaluation window: {args.start_date} to {args.end_date}...")
    start_time = datetime.now()

    params = CrudeRthExpansionParams()
    strategy = CrudeRthExpansionS5(params=params)
    trades_df, raw_metrics = strategy.backtest(
        data=data_path,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"Backtest completed in {elapsed:.2f} seconds. Trades executed: {len(trades_df)}")

    if len(trades_df) == 0:
        print("ERROR: No trades generated during backtest.", file=sys.stderr)
        sys.exit(1)

    # 3. Institutional Metrics & Daily Series
    daily_series = trades_df.groupby("date")["net_pnl"].sum()
    inst_metrics = bm.calculate_institutional_metrics(
        trades=trades_df,
        daily_returns=daily_series,
        capital=25000.0,
        col="net_pnl",
    )

    # Calculate days count
    d_start = pd.Timestamp(args.start_date)
    d_end = pd.Timestamp(args.end_date)
    days_count = (d_end - d_start).days

    # 4. Create Open Backtest Format (.obtf) Bundle
    bundle = BacktestBundle.create(
        run_id=args.run_id,
        strategy_id=params.strategy_id,
        strategy_name=params.strategy_name,
        trades_df=trades_df,
        daily_series=daily_series,
        capital=25000.0,
        methodology="multi_year_walkforward",
        date_start=args.start_date,
        date_end=args.end_date,
        data_path=str(data_path.relative_to(REPO_ROOT)),
        data_hash=computed_hash,
        git_commit=default_store.get_git_commit(),
        slippage_model="1-tick limit ($1.00) / 2-tick stop ($2.00) adverse parity",
        commission_model="$3.50 RT micro energy",
        is_net=True,
        strategy_tier=StrategyTier.CANDIDATE.value,
        params=asdict(params),
        notes="Milestone M2 candidate backtest for Crude Oil Post-Fix Range Expansion on MCL.",
    )

    # 5. Record to results/backtest_provenance.db (Rule 1 & 5)
    if args.dry_run:
        print("\n[DRY RUN] Skipping provenance store persistence.")
        print(f"Trades: {len(trades_df)} | Win%: {raw_metrics['win_rate']:.1f}% | "
              f"PF: {raw_metrics['profit_factor']:.2f} | Net: ${raw_metrics['net_profit']:,.2f} | "
              f"MaxDD: -${raw_metrics['max_drawdown']:,.2f} | Sharpe: {inst_metrics.get('sharpe_ratio', 0.0):.2f}")
    else:
        rec = default_store.record_run(
            run_id=args.run_id,
            strategy_id=params.strategy_id,
            strategy_name=params.strategy_name,
            strategy_tier=StrategyTier.CANDIDATE,
            methodology="multi_year_walkforward",
            date_start=args.start_date,
            date_end=args.end_date,
            days_count=days_count,
            data_path=str(data_path.relative_to(REPO_ROOT)),
            total_trades=len(trades_df),
            win_rate=raw_metrics["win_rate"],
            profit_factor=raw_metrics["profit_factor"],
            gross_profit=raw_metrics["gross_profit"],
            net_profit=raw_metrics["net_profit"],
            max_drawdown=raw_metrics["max_drawdown"],
            sharpe_ratio=inst_metrics.get("sharpe_ratio", 0.0),
            largest_win=raw_metrics["largest_win"],
            sortino_ratio=inst_metrics.get("sortino", 0.0),
            calmar_ratio=inst_metrics.get("calmar", 0.0),
            slippage_model="1-tick limit ($1.00) / 2-tick stop ($2.00) adverse parity",
            commission_model="$3.50 RT micro energy",
            is_net=True,
            bundle=bundle,
            params=asdict(params),
            notes="Milestone M2 candidate backtest for Crude Oil Post-Fix Range Expansion on MCL.",
        )

        print("\n" + ProvenanceStore.format_footer(rec))


if __name__ == "__main__":
    main()
