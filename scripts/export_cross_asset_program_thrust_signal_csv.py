#!/usr/bin/env python3
"""
Export script for Cross-Asset Institutional Program Thrust Signal (H10).

Pre-registered in docs/research_hypotheses/2026-10-30_cross_asset_program_thrust_h10.md.
Creates point-in-time signal rows only; does not execute trades or curve-fit.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.cross_asset_program_thrust_signal import (
    CrossAssetProgramThrustConfig,
    DEFAULT_CROSS_ASSET_THRUST_CONTEXT_COLUMNS,
    DEFAULT_CROSS_ASSET_THRUST_FEATURE_COLUMNS,
    build_cross_asset_program_thrust_signal_export,
)
from backtest.signal_export import load_ohlcv_data, write_prepared_signal_export
from config.backtest_config import BACKTEST_CONFIG


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Cross-Asset Institutional Program Thrust (H10) point-in-time signals."
    )
    parser.add_argument("--data-path", default="data/raw/nq_1m_2014_2026_merged.parquet")
    parser.add_argument("--es-data-path", default="data/raw/es_1m_2014_2026_et.parquet")
    parser.add_argument("--tick-data-path", default="data/processed/macro_context/nyse_tick_5m_et.parquet")
    parser.add_argument("--vx-data-path", default="data/processed/macro_context/vix_futures_5m_et.parquet")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default="results/research_master/signal_exports")
    parser.add_argument("--artifact-name", default="cross_asset_program_thrust_h10")
    parser.add_argument("--signal-col-name", default="candidate_signal")
    parser.add_argument(
        "--feature-cols",
        default=",".join(DEFAULT_CROSS_ASSET_THRUST_FEATURE_COLUMNS),
        help="Comma-separated numeric point-in-time signal/diagnostic columns to copy.",
    )
    parser.add_argument(
        "--context-cols",
        default=",".join(DEFAULT_CROSS_ASSET_THRUST_CONTEXT_COLUMNS),
        help="Comma-separated context columns to keep when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = CrossAssetProgramThrustConfig(
        es_data_path=str(args.es_data_path),
        tick_data_path=str(args.tick_data_path),
        vx_data_path=str(args.vx_data_path),
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
    frame = build_cross_asset_program_thrust_signal_export(
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
            "hypothesis": "cross_asset_program_thrust_h10",
            "source": "Hasbrouck & Seppi 2001 / Chordia, Roll, Subrahmanyam 2008",
            "data_path": args.data_path,
            "es_data_path": args.es_data_path,
            "tick_data_path": args.tick_data_path,
            "vx_data_path": args.vx_data_path,
            "start": args.start,
            "end": args.end,
        },
    )
    print(f"Wrote signals: {paths.signals_csv}")
    print(f"Wrote manifest: {paths.manifest_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
