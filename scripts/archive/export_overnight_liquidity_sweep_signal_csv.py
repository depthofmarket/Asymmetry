#!/usr/bin/env python3
"""
Export script for Overnight High/Low Liquidity Sweep Signal (H7).

Pre-registered in docs/research_hypotheses/2026-10-29_overnight_high_low_liquidity_sweep_h7.md.
Creates point-in-time signal rows only; does not execute trades or curve-fit.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.overnight_liquidity_sweep_signal import (
    DEFAULT_ON_SWEEP_CONTEXT_COLUMNS,
    DEFAULT_ON_SWEEP_FEATURE_COLUMNS,
    OvernightLiquiditySweepConfig,
    build_overnight_liquidity_sweep_signal_export,
)
from backtest.signal_export import load_ohlcv_data, write_prepared_signal_export
from config.backtest_config import BACKTEST_CONFIG


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Overnight High/Low Liquidity Sweep (H7) point-in-time signals."
    )
    parser.add_argument("--data-path", default="data/raw/nq_1m_2014_2026_merged.parquet")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default="results/research_master/signal_exports")
    parser.add_argument("--artifact-name", default="overnight_liquidity_sweep_h7")
    parser.add_argument("--signal-col-name", default="candidate_signal")
    parser.add_argument("--min-sweep-points", type=float, default=1.0)
    parser.add_argument("--max-sweep-points", type=float, default=25.0)
    parser.add_argument("--max-short-close-location", type=float, default=0.45)
    parser.add_argument("--min-long-close-location", type=float, default=0.55)
    parser.add_argument(
        "--feature-cols",
        default=",".join(DEFAULT_ON_SWEEP_FEATURE_COLUMNS),
        help="Comma-separated numeric point-in-time signal/diagnostic columns to copy.",
    )
    parser.add_argument(
        "--context-cols",
        default=",".join(DEFAULT_ON_SWEEP_CONTEXT_COLUMNS),
        help="Comma-separated context columns to keep when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = OvernightLiquiditySweepConfig(
        min_sweep_points=float(args.min_sweep_points),
        max_sweep_points=float(args.max_sweep_points),
        max_short_close_location=float(args.max_short_close_location),
        min_long_close_location=float(args.min_long_close_location),
    )

    data = load_ohlcv_data(
        args.data_path,
        continuous_contract_method=BACKTEST_CONFIG.get("continuous_contract_method"),
        start=args.start,
        end=args.end,
    )
    if data.empty:
        raise SystemExit("No bars after applying the requested date range.")

    feature_cols = _csv_items(args.feature_cols)
    context_cols = _csv_items(args.context_cols)
    frame = build_overnight_liquidity_sweep_signal_export(
        data,
        config=cfg,
        signal_col_name=args.signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )
    paths = write_prepared_signal_export(
        frame,
        out_dir=Path(args.out_dir),
        artifact_name=args.artifact_name,
        metadata={
            "hypothesis": "overnight_liquidity_sweep_h7",
            "source": "Brogaard et al. 2014 / Dalton 1990",
            "data_path": args.data_path,
            "start": args.start or "",
            "end": args.end or "",
            "signal_col_name": args.signal_col_name,
            "feature_cols": ",".join(feature_cols),
            "context_cols": ",".join(context_cols),
            "min_sweep_points": cfg.min_sweep_points,
            "max_sweep_points": cfg.max_sweep_points,
        },
    )
    print(f"Exported prepared signal CSV: {paths.signals_csv}")
    print(f"Metadata manifest: {paths.manifest_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
