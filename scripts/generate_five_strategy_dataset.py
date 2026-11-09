#!/usr/bin/env python3
"""
Generates the canonical unified 5-strategy portfolio trade dataset:
data/processed/unified_five_strategy_portfolio_trades_2021_2026.parquet

Combines verified canonical .obtf bundles for:
1. Strategy 1 (09:45 ET): morning_va_breakout_s1 (MNQ/MES)
2. Strategy 2 (08:35 ET): macro_momentum_s2 (MNQ)
3. Strategy 3 (10:15 ET): gold_london_fix_s3 (MGC)
4. Candidate S4 (21:00 ET): asian_evening_reversion_s4 (MNQ)
5. Candidate S5 (10:15 ET): crude_rth_expansion_s5 (MCL)
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.bundle import BacktestBundle

OUTPUT_PARQUET = REPO_ROOT / "data/processed/unified_five_strategy_portfolio_trades_2021_2026.parquet"


def build_five_strategy_dataset() -> pd.DataFrame:
    bundles_meta = [
        {
            "strat_code": "S1",
            "strat_id": "morning_va_breakout_s1",
            "display_name": "Strategy 1: Morning VA Breakout (09:45 ET)",
            "bundle_file": "run_canonical_s1_va_breakout_2021_2026.obtf",
            "default_sym": "MNQ",
            "window": "09:45-10:15 ET",
        },
        {
            "strat_code": "S3",
            "strat_id": "macro_momentum_s2",
            "display_name": "Strategy 3: Macro Release Momentum (08:35 ET)",
            "bundle_file": "run_canonical_s2_macro_momentum_2021_2026.obtf",
            "default_sym": "MNQ",
            "window": "08:35-09:25 ET",
        },
        {
            "strat_code": "S2",
            "strat_id": "gold_london_fix_s3",
            "display_name": "Strategy 2: Gold London Fix (10:15 ET)",
            "bundle_file": "run_canonical_s3_gold_london_fix_2021_2026.obtf",
            "default_sym": "MGC",
            "window": "10:15-11:00 ET",
        },
        {
            "strat_code": "S4",
            "strat_id": "asian_evening_reversion_s4",
            "display_name": "Strategy 4: Asian Evening Reversion (21:00 ET)",
            "bundle_file": "run_canonical_s4_asian_evening_reversion_2021_2026.obtf",
            "default_sym": "MNQ",
            "window": "21:00-23:00 ET",
        },
        {
            "strat_code": "S5",
            "strat_id": "crude_rth_expansion_s5",
            "display_name": "Strategy 5: Crude RTH Expansion (10:15 ET)",
            "bundle_file": "run_canonical_s5_crude_rth_expansion_2021_2026.obtf",
            "default_sym": "MCL",
            "window": "10:15-12:30 ET",
        },
    ]

    all_trades: List[pd.DataFrame] = []

    for meta in bundles_meta:
        bpath = REPO_ROOT / "results/bundles" / meta["bundle_file"]
        if not bpath.exists():
            raise FileNotFoundError(f"Missing bundle: {bpath}")
        bundle = BacktestBundle.load(bpath)
        t = bundle.trades.copy()

        # Date normalization
        if "date_str" in t.columns:
            date_col = t["date_str"].astype(str).str.slice(0, 10)
        elif "date" in t.columns:
            date_col = t["date"].astype(str).str.slice(0, 10)
        else:
            date_col = pd.to_datetime(t["entry_time"]).dt.strftime("%Y-%m-%d")

        t["date_str"] = date_col
        t["entry_time"] = pd.to_datetime(t["entry_time"])
        t["exit_time"] = pd.to_datetime(t["exit_time"])
        t["year"] = t["entry_time"].dt.year

        # Symbol resolution
        if "symbol" in t.columns:
            sym_col = t["symbol"].astype(str)
        elif "sym" in t.columns:
            sym_col = t["sym"].astype(str)
        else:
            sym_col = meta["default_sym"]
        t["sym"] = sym_col
        # Micro symbol mapping
        micro_map = {"NQ": "MNQ", "ES": "MES", "GC": "MGC", "CL": "MCL", "MNQ": "MNQ", "MES": "MES", "MGC": "MGC", "MCL": "MCL"}
        t["micro"] = t["sym"].map(micro_map).fillna(meta["default_sym"])

        # Strategy labelling
        t["window"] = meta["window"]
        t["strategy"] = meta["display_name"]
        t["strategy_id"] = meta["strat_id"]
        t["strat"] = meta["strat_code"]

        # Contracts
        if "contracts" in t.columns:
            t["contracts"] = t["contracts"].astype(int).clip(lower=1)
        else:
            t["contracts"] = 1

        # PnL fields
        if "per_contract_pnl" in t.columns:
            base_pnl = t["per_contract_pnl"].astype(float) * t["contracts"]
            res_pnl = t["research_pnl"].astype(float)
        elif "net_pnl" in t.columns:
            base_pnl = t["net_pnl"].astype(float)
            res_pnl = t["net_pnl"].astype(float)
        elif "net_dollars_micro" in t.columns:
            base_pnl = t["net_dollars_micro"].astype(float)
            res_pnl = t["pnl"].astype(float) if "pnl" in t.columns else base_pnl
        else:
            raise KeyError(f"No recognizable PnL column in bundle {meta['bundle_file']}")

        t["net_dollars_micro"] = base_pnl
        t["scaled_pnl"] = res_pnl
        t["pnl"] = res_pnl

        keep_cols = [
            "date_str",
            "year",
            "sym",
            "micro",
            "window",
            "strategy",
            "entry_time",
            "exit_time",
            "direction",
            "contracts",
            "net_dollars_micro",
            "scaled_pnl",
            "pnl",
        ]
        all_trades.append(t[keep_cols])

    df_all = pd.concat(all_trades, ignore_index=True)
    df_all = df_all.sort_values("entry_time").reset_index(drop=True)

    # Compute portfolio cumulative equity trajectory & drawdown
    df_all["cum_pnl"] = df_all["pnl"].cumsum()
    df_all["peak"] = df_all["cum_pnl"].cummax()
    df_all["dd"] = df_all["cum_pnl"] - df_all["peak"]

    return df_all


def main():
    print("=" * 80)
    print("Building Canonical Unified 5-Strategy Portfolio Trades Parquet...")
    print("=" * 80)
    df = build_five_strategy_dataset()
    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_PARQUET, index=False)

    hasher = hashlib.sha256()
    with open(OUTPUT_PARQUET, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    sha256_hash = hasher.hexdigest()

    print(f"Output File : {OUTPUT_PARQUET}")
    print(f"Total Trades: {len(df)}")
    print(f"Date Range  : {df['date_str'].min()} to {df['date_str'].max()}")
    print(f"Total PnL   : ${df['pnl'].sum():,.2f}")
    print(f"Max Drawdown: ${df['dd'].min():,.2f}")
    print(f"SHA-256     : {sha256_hash}")
    print("-" * 80)
    print("Trades Breakdown by Strategy:")
    for strat, count in df["strategy"].value_counts().items():
        sub = df[df["strategy"] == strat]
        pnl = sub["pnl"].sum()
        wr = (sub["pnl"] > 0).mean() * 100.0
        print(f"  - {strat:<45}: {count:>4} trades | WR: {wr:>5.1f}% | Net: ${pnl:>9,.2f}")
    print("=" * 80)


if __name__ == "__main__":
    main()
