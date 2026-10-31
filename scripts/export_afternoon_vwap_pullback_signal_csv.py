#!/usr/bin/env python3
"""
Export script for Afternoon Trend Continuation via Session VWAP Pullback Signal (H8).

Pre-registered in docs/research_hypotheses/2026-10-30_afternoon_vwap_pullback_continuation_h8.md.
Creates point-in-time signal rows only; does not execute trades or curve-fit.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.afternoon_vwap_pullback_signal import (
    AfternoonVwapPullbackConfig,
    DEFAULT_AFTERNOON_VWAP_PULLBACK_CONTEXT_COLUMNS,
    DEFAULT_AFTERNOON_VWAP_PULLBACK_FEATURE_COLUMNS,
    build_afternoon_vwap_pullback_signal_export,
)
from backtest.signal_export import load_ohlcv_data, write_prepared_signal_export
from config.backtest_config import BACKTEST_CONFIG


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Afternoon VWAP Pullback Continuation (H8) point-in-time signals."
    )
    parser.add_argument("--data-path", default="data/raw/nq_1m_2014_2026_merged.parquet")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default="results/research_master/signal_exports")
    parser.add_argument("--artifact-name", default="afternoon_vwap_pullback_continuation_h8")
    parser.add_argument("--signal-col-name", default="candidate_signal")
    parser.add_argument("--min-session-return-pct", type=float, default=0.0015)
    parser.add_argument("--pullback-lookback-bars", type=int, default=15)
    parser.add_argument("--pullback-min-z", type=float, default=-0.50)
    parser.add_argument("--pullback-max-z", type=float, default=0.75)
    parser.add_argument("--max-extension-z", type=float, default=1.75)
    parser.add_argument("--min-long-close-location", type=float, default=0.65)
    parser.add_argument("--max-short-close-location", type=float, default=0.35)
    parser.add_argument(
        "--feature-cols",
        default=",".join(DEFAULT_AFTERNOON_VWAP_PULLBACK_FEATURE_COLUMNS),
        help="Comma-separated numeric point-in-time signal/diagnostic columns to copy.",
    )
    parser.add_argument(
        "--context-cols",
        default=",".join(DEFAULT_AFTERNOON_VWAP_PULLBACK_CONTEXT_COLUMNS),
        help="Comma-separated context columns to keep when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = AfternoonVwapPullbackConfig(
        min_session_return_pct=float(args.min_session_return_pct),
        pullback_lookback_bars=int(args.pullback_lookback_bars),
        pullback_min_z=float(args.pullback_min_z),
        pullback_max_z=float(args.pullback_max_z),
        max_extension_z=float(args.max_extension_z),
        min_long_close_location=float(args.min_long_close_location),
        max_short_close_location=float(args.max_short_close_location),
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
    frame = build_afternoon_vwap_pullback_signal_export(
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
            "hypothesis": "afternoon_vwap_pullback_continuation_h8",
            "source": "Berkowitz et al. 1988 / Madhavan et al. 1997",
            "data_path": args.data_path,
            "start": args.start or "",
            "end": args.end or "",
            "signal_col_name": args.signal_col_name,
            "feature_cols": ",".join(feature_cols),
            "context_cols": ",".join(context_cols),
            "min_session_return_pct": cfg.min_session_return_pct,
            "pullback_lookback_bars": cfg.pullback_lookback_bars,
        },
    )
    print(f"Exported prepared signal CSV: {paths.signals_csv}")
    print(f"Metadata manifest: {paths.manifest_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
