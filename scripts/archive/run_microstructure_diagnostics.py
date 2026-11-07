#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.microstructure_diagnostics import (  # noqa: E402
    build_microstructure_diagnostics,
    write_microstructure_diagnostics,
)


def _csv_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build execution-first market microstructure diagnostics from processed TBBO, "
            "aggressive-flow, and optional prepared-signal artifacts."
        )
    )
    parser.add_argument(
        "--tbbo-minute",
        default="data/processed/tbbo/tbbo_minute_execution_stats.csv",
        help="Processed TBBO minute stats CSV from build_tbbo_execution_stats.py.",
    )
    parser.add_argument(
        "--aggressive-flow-minute",
        default="data/processed/orderflow/aggressive_flow_minute_stats.csv",
        help="Optional processed aggressive-flow minute stats CSV from build_aggressive_flow_stats.py.",
    )
    parser.add_argument(
        "--signals-csv",
        default="",
        help="Optional prepared signal CSV for signal-aligned adverse-selection diagnostics.",
    )
    parser.add_argument("--out-dir", default="results/research_master/microstructure_diagnostics")
    parser.add_argument("--artifact-name", default="microstructure_diagnostics")
    parser.add_argument("--horizons-minutes", default="1,5,15")
    parser.add_argument("--max-autocorr-lag", type=int, default=30)
    parser.add_argument("--tick-size", type=float, default=0.25)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tbbo_path = Path(args.tbbo_minute)
    if not tbbo_path.exists():
        raise SystemExit(f"TBBO minute stats not found: {tbbo_path}")
    tbbo_minute = pd.read_csv(tbbo_path, low_memory=False)

    aggressive_path = Path(args.aggressive_flow_minute)
    aggressive_minute = (
        pd.read_csv(aggressive_path, low_memory=False)
        if args.aggressive_flow_minute and aggressive_path.exists()
        else pd.DataFrame()
    )
    signals = (
        pd.read_csv(args.signals_csv, low_memory=False)
        if args.signals_csv and Path(args.signals_csv).exists()
        else pd.DataFrame()
    )

    diagnostics = build_microstructure_diagnostics(
        tbbo_minute,
        aggressive_flow_minute_stats=aggressive_minute,
        signals=signals,
        horizons_minutes=_csv_ints(args.horizons_minutes),
        max_autocorr_lag=int(args.max_autocorr_lag),
        tick_size=float(args.tick_size),
    )
    paths = write_microstructure_diagnostics(
        diagnostics,
        args.out_dir,
        artifact_name=args.artifact_name,
    )

    print(f"Microstructure diagnostics report: {paths.report_md}")
    print(f"Depth exhaustion summary:        {paths.depth_exhaustion_summary_csv}")
    print(f"Composite cost-state summary:    {paths.microstructure_cost_state_summary_csv}")
    print(f"Book imbalance summary:          {paths.book_imbalance_summary_csv}")
    print(f"Spread reversion:                {paths.spread_reversion_csv}")
    print(f"Trade-sign autocorr:             {paths.trade_sign_autocorr_csv}")
    print(f"Trade-sign memory summary:       {paths.trade_sign_memory_summary_csv}")
    print(f"Price-changing buckets:          {paths.price_change_buckets_csv}")
    print(f"Signal adverse selection summary:{paths.signal_adverse_selection_summary_csv}")
    print(f"Signal cost-state summary:       {paths.signal_cost_state_summary_csv}")
    print(f"Options context cost stress:     {paths.signal_options_context_summary_csv}")
    if aggressive_minute.empty:
        print("Aggressive-flow minute stats were not found; price-changing buckets are empty.")
    if signals.empty:
        print("No signals CSV supplied; signal-aligned adverse-selection outputs are empty.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
