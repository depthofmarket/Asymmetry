#!/usr/bin/env python3
"""
Export script for Delayed Value-Area Escape & 10:00 ET Macro Impulse Breakout (H9).

Pre-registered in docs/research_hypotheses/2026-10-30_delayed_va_macro_breakout_h9.md.
Creates point-in-time signal rows only; does not execute trades or curve-fit.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.delayed_va_macro_breakout_signal import (
    DEFAULT_DELAYED_VA_BREAKOUT_CONTEXT_COLUMNS,
    DEFAULT_DELAYED_VA_BREAKOUT_FEATURE_COLUMNS,
    DelayedVaMacroBreakoutConfig,
    build_delayed_va_macro_breakout_signal_export,
)
from backtest.signal_export import load_ohlcv_data, write_prepared_signal_export
from config.backtest_config import BACKTEST_CONFIG


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Delayed Value-Area Escape & 10:00 ET Macro Breakout (H9) point-in-time signals."
    )
    parser.add_argument("--data-path", default="data/raw/nq_1m_2014_2026_merged.parquet")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default="results/research_master/signal_exports")
    parser.add_argument("--artifact-name", default="delayed_va_macro_breakout_h9")
    parser.add_argument("--signal-col-name", default="candidate_signal")
    parser.add_argument("--min-abs-return-pct", type=float, default=0.0010)
    parser.add_argument("--min-long-close-location", type=float, default=0.65)
    parser.add_argument("--max-short-close-location", type=float, default=0.35)
    parser.add_argument("--signal-bar-time", default="10:04")
    parser.add_argument(
        "--feature-cols",
        default=",".join(DEFAULT_DELAYED_VA_BREAKOUT_FEATURE_COLUMNS),
        help="Comma-separated numeric point-in-time signal/diagnostic columns to copy.",
    )
    parser.add_argument(
        "--context-cols",
        default=",".join(DEFAULT_DELAYED_VA_BREAKOUT_CONTEXT_COLUMNS),
        help="Comma-separated context columns to keep when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = DelayedVaMacroBreakoutConfig(
        min_abs_return_pct=float(args.min_abs_return_pct),
        min_long_close_location=float(args.min_long_close_location),
        max_short_close_location=float(args.max_short_close_location),
        signal_bar_time=str(args.signal_bar_time),
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
    frame = build_delayed_va_macro_breakout_signal_export(
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
            "hypothesis": "delayed_va_macro_breakout_h9",
            "source": "Steidlmayer 1984 / Crabel 1990 / Gao et al. 2018",
            "data_path": args.data_path,
            "start": args.start,
            "end": args.end,
            "signal_bar_time": args.signal_bar_time,
        },
    )
    print(f"Wrote signals: {paths.signals_csv}")
    print(f"Wrote manifest: {paths.manifest_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
