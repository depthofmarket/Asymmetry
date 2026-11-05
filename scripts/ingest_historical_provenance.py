#!/usr/bin/env python3
"""
Baseline Provenance Ingestion Script.

Seeds results/backtest_provenance.db with canonical, verified backtest runs:
1. S1: Morning VA Breakout (09:45 ET) [2021-2026]
2. S2: Macro Momentum (08:35 ET) [2021-2026]
3. S3: Gold London Fix (10:15 ET) [2021-2026]
4. LucidFlex Ensemble (S1 + S2 + S3 Multi-Strategy Portfolio) [2021-2026]
5. LucidFlex 25K Forward Demo / Live Parity Ledger [2026-present]

Computes real cryptographic SHA-256 hashes for source datasets,
evaluates warning flags, and exports JSONL audit mirror.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest import dashboard_analytics as da
from backtest.provenance import ProvenanceStore, default_store
from backtest.demo_parity_engine import DemoParityJournal, TRADES_LEDGER_PATH


def ingest_canonical_runs():
    store = default_store
    print("=" * 80)
    print("INGESTING CANONICAL VERIFIED BACKTEST RUNS INTO PROVENANCE STORE")
    print("=" * 80)
    print(f"Target SQLite Database : {store.db_path}")
    print(f"JSONL Audit Mirror     : {store.jsonl_path}")

    # 1. Source Parquet Dataset
    parquet_path = da.DEFAULT_TRADES_PATH
    if not parquet_path.exists():
        print(f"ERROR: Dataset {parquet_path} not found!", file=sys.stderr)
        sys.exit(1)

    print(f"\nComputing SHA-256 hash for {parquet_path.name}...")
    parquet_hash = store.compute_data_hash(parquet_path)
    print(f"  SHA-256: {parquet_hash}")

    trades = da.load_trades(parquet_path)
    calendar = da.load_session_calendar()
    date_start = str(trades["date"].min())
    date_end = str(trades["date"].max())
    days_count = len(calendar)

    # Ingest S1: Morning VA Breakout (09:45 ET)
    s1_trades = trades[trades["strat"] == "S1"]
    m_s1 = da.performance_metrics(s1_trades, calendar, "research_pnl")
    r_s1 = store.record_run(
        run_id="run_canonical_s1_va_breakout_2021_2026",
        strategy_id="morning_va_breakout_s1",
        strategy_name="Morning VA Breakout (09:45 ET)",
        methodology="multi_year_walkforward",
        date_start=date_start,
        date_end=date_end,
        days_count=days_count,
        data_path=str(parquet_path.relative_to(REPO_ROOT)),
        total_trades=m_s1["trades"],
        win_rate=m_s1["win_rate"],
        profit_factor=m_s1["pf"],
        gross_profit=m_s1["gross_profit"],
        net_profit=m_s1["net"],
        max_drawdown=m_s1["max_dd"],
        sharpe_ratio=m_s1["sharpe"],
        largest_win=m_s1["largest_win"],
        slippage_model="CQG 1-Tick Adverse + Limit Fill Parity",
        commission_model="$1.40 RT ($0.70/side micro)",
        is_net=True,
        notes="Canonical multi-year walk-forward backtest across 2021-2026 NQ/MNQ and ES/MES with Markov regime sizing.",
    )
    print(f"  [Recorded] {r_s1.strategy_id:<25} | Trades: {r_s1.total_trades} | PF: {r_s1.profit_factor:.2f} | Net: ${r_s1.net_profit:,.2f} | Warnings: {len(r_s1.warnings)}")

    # Ingest S2: Macro Momentum (08:35 ET) - mapped to 'S3' in dataset
    s2_trades = trades[trades["strat"] == "S3"]
    m_s2 = da.performance_metrics(s2_trades, calendar, "research_pnl")
    r_s2 = store.record_run(
        run_id="run_canonical_s2_macro_momentum_2021_2026",
        strategy_id="macro_momentum_s2",
        strategy_name="Macro Release Momentum (08:35 ET)",
        methodology="multi_year_walkforward",
        date_start=date_start,
        date_end=date_end,
        days_count=days_count,
        data_path=str(parquet_path.relative_to(REPO_ROOT)),
        total_trades=m_s2["trades"],
        win_rate=m_s2["win_rate"],
        profit_factor=m_s2["pf"],
        gross_profit=m_s2["gross_profit"],
        net_profit=m_s2["net"],
        max_drawdown=m_s2["max_dd"],
        sharpe_ratio=m_s2["sharpe"],
        largest_win=m_s2["largest_win"],
        slippage_model="CQG 1-Tick Adverse Parity",
        commission_model="$1.40 RT ($0.70/side micro)",
        is_net=True,
        notes="Canonical pre-market CPI/NFP release momentum breakout on NQ/MNQ with 09:25 cash flatten.",
    )
    print(f"  [Recorded] {r_s2.strategy_id:<25} | Trades: {r_s2.total_trades} | PF: {r_s2.profit_factor:.2f} | Net: ${r_s2.net_profit:,.2f} | Warnings: {len(r_s2.warnings)}")

    # Ingest S3: Gold London Fix (10:15 ET) - mapped to 'S2' in dataset
    s3_trades = trades[trades["strat"] == "S2"]
    m_s3 = da.performance_metrics(s3_trades, calendar, "research_pnl")
    r_s3 = store.record_run(
        run_id="run_canonical_s3_gold_london_fix_2021_2026",
        strategy_id="gold_london_fix_s3",
        strategy_name="Gold London Fix Breakout (10:15 ET)",
        methodology="multi_year_walkforward",
        date_start=date_start,
        date_end=date_end,
        days_count=days_count,
        data_path=str(parquet_path.relative_to(REPO_ROOT)),
        total_trades=m_s3["trades"],
        win_rate=m_s3["win_rate"],
        profit_factor=m_s3["pf"],
        gross_profit=m_s3["gross_profit"],
        net_profit=m_s3["net"],
        max_drawdown=m_s3["max_dd"],
        sharpe_ratio=m_s3["sharpe"],
        largest_win=m_s3["largest_win"],
        slippage_model="COMEX 1-Tick Adverse Parity",
        commission_model="$1.40 RT ($0.70/side micro)",
        is_net=True,
        notes="Canonical LBMA PM Fix 3-way barrier breakout on GC/MGC with 11:00 cash flatten.",
    )
    print(f"  [Recorded] {r_s3.strategy_id:<25} | Trades: {r_s3.total_trades} | PF: {r_s3.profit_factor:.2f} | Net: ${r_s3.net_profit:,.2f} | Warnings: {len(r_s3.warnings)}")

    # Ingest Unified Ensemble (S1 + S2 + S3)
    m_comp = da.performance_metrics(trades, calendar, "research_pnl")
    r_comp = store.record_run(
        run_id="run_canonical_lucid_flex_ensemble_2021_2026",
        strategy_id="lucid_flex_ensemble",
        strategy_name="LucidFlex 25K Multi-Strategy Ensemble",
        methodology="multi_year_walkforward",
        date_start=date_start,
        date_end=date_end,
        days_count=days_count,
        data_path=str(parquet_path.relative_to(REPO_ROOT)),
        total_trades=m_comp["trades"],
        win_rate=m_comp["win_rate"],
        profit_factor=m_comp["pf"],
        gross_profit=m_comp["gross_profit"],
        net_profit=m_comp["net"],
        max_drawdown=m_comp["max_dd"],
        sharpe_ratio=m_comp["sharpe"],
        largest_win=m_comp["largest_win"],
        slippage_model="Multi-Asset CQG Adverse Realism",
        commission_model="$1.40 RT ($0.70/side micro)",
        is_net=True,
        notes="Master 3-strategy ensemble with Markov 3-state volatility weighting across 2021-2026.",
    )
    print(f"  [Recorded] {r_comp.strategy_id:<25} | Trades: {r_comp.total_trades} | PF: {r_comp.profit_factor:.2f} | Net: ${r_comp.net_profit:,.2f} | Warnings: {len(r_comp.warnings)}")

    # 2. Ingest Forward Demo / Live Parity Ledger if available
    if TRADES_LEDGER_PATH.exists():
        journal = DemoParityJournal()
        fwd_df = journal.load_trades_df()
        if not fwd_df.empty:
            fwd_hash = store.compute_data_hash(TRADES_LEDGER_PATH)
            state = journal.get_eval_state()
            fwd_start = str(fwd_df["date"].min())
            fwd_end = str(fwd_df["date"].max())
            gross_pnl = float(fwd_df["gross_pnl"].sum()) if "gross_pnl" in fwd_df else state.profit
            largest_win = float(fwd_df["net_pnl"].max()) if not fwd_df.empty else 0.0

            r_fwd = store.record_run(
                run_id="run_canonical_forward_demo_live_parity",
                strategy_id="lucid_flex_forward_demo",
                strategy_name="LucidFlex 25K Forward Demo / Live Parity",
                methodology="forward_demo",
                date_start=fwd_start,
                date_end=fwd_end,
                days_count=len(journal.load_sessions_df()) if journal.load_sessions_df() is not None else 1,
                data_path=str(TRADES_LEDGER_PATH.relative_to(REPO_ROOT)),
                total_trades=state.trades_count,
                win_rate=state.win_rate,
                profit_factor=state.profit_factor,
                gross_profit=gross_pnl,
                net_profit=state.profit,
                max_drawdown=float(state.peak_balance - state.balance),
                sharpe_ratio=0.0,
                largest_win=largest_win,
                slippage_model="Realized CQG Demo Executions",
                commission_model="$1.40 RT ($0.70/side micro)",
                is_net=True,
                notes="Live execution parity ledger tracking actual demo fills, broker slippage drag, and rulebook compliance.",
            )
            print(f"  [Recorded] {r_fwd.strategy_id:<25} | Trades: {r_fwd.total_trades} | PF: {r_fwd.profit_factor:.2f} | Net: ${r_fwd.net_profit:,.2f} | Warnings: {len(r_fwd.warnings)}")

    print("\nBaseline ingestion complete. All verified runs committed to SQLite and JSONL mirror.")


if __name__ == "__main__":
    ingest_canonical_runs()
