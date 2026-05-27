#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.compression_breakout_signal import (
    DEFAULT_COMPRESSION_BREAKOUT_CONTEXT_COLUMNS,
    DEFAULT_COMPRESSION_BREAKOUT_FEATURE_COLUMNS,
    CompressionBreakoutSignalConfig,
    build_compression_breakout_signal_export,
)
from backtest.signal_export import load_ohlcv_data, write_prepared_signal_export
from config.backtest_config import BACKTEST_CONFIG


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the pre-candidate opening compression breakout continuation signal. "
            "This creates point-in-time signal rows only and does not execute trades."
        )
    )
    parser.add_argument("--data-path", default=BACKTEST_CONFIG.get("data_path"))
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default="results/research_master/signal_exports")
    parser.add_argument("--artifact-name", default="compression_breakout_2021_signal_gate")
    parser.add_argument("--signal-col-name", default="candidate_signal")
    parser.add_argument("--compression-lookback-bars", type=int, default=15)
    parser.add_argument("--range-lookback-bars", type=int, default=60)
    parser.add_argument("--volume-lookback-bars", type=int, default=60)
    parser.add_argument("--max-compression-range-ratio", type=float, default=0.85)
    parser.add_argument("--expansion-range-multiple", type=float, default=1.8)
    parser.add_argument("--expansion-volume-multiple", type=float, default=1.2)
    parser.add_argument("--breakout-buffer-points", type=float, default=0.25)
    parser.add_argument("--close-position-long-min", type=float, default=0.75)
    parser.add_argument("--close-position-short-max", type=float, default=0.25)
    parser.add_argument("--min-vwap-distance-points", type=float, default=0.0)
    parser.add_argument("--trade-start", default="09:45")
    parser.add_argument("--trade-end", default="11:30")
    parser.add_argument(
        "--feature-cols",
        default=",".join(DEFAULT_COMPRESSION_BREAKOUT_FEATURE_COLUMNS),
        help="Comma-separated numeric point-in-time signal/diagnostic columns to copy.",
    )
    parser.add_argument(
        "--context-cols",
        default=",".join(DEFAULT_COMPRESSION_BREAKOUT_CONTEXT_COLUMNS),
        help="Comma-separated context columns to keep when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = CompressionBreakoutSignalConfig(
        compression_lookback_bars=int(args.compression_lookback_bars),
        range_lookback_bars=int(args.range_lookback_bars),
        volume_lookback_bars=int(args.volume_lookback_bars),
        max_compression_range_ratio=float(args.max_compression_range_ratio),
        expansion_range_multiple=float(args.expansion_range_multiple),
        expansion_volume_multiple=float(args.expansion_volume_multiple),
        breakout_buffer_points=float(args.breakout_buffer_points),
        close_position_long_min=float(args.close_position_long_min),
        close_position_short_max=float(args.close_position_short_max),
        min_vwap_distance_points=float(args.min_vwap_distance_points),
        trade_start=str(args.trade_start),
        trade_end=str(args.trade_end),
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
    frame = build_compression_breakout_signal_export(
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
            "hypothesis": "opening_compression_breakout_continuation",
            "data_path": args.data_path,
            "start": args.start or "",
            "end": args.end or "",
            "signal_col_name": args.signal_col_name,
            "feature_cols": ",".join(feature_cols),
            "context_cols": ",".join(context_cols),
            "compression_lookback_bars": cfg.compression_lookback_bars,
            "range_lookback_bars": cfg.range_lookback_bars,
            "volume_lookback_bars": cfg.volume_lookback_bars,
            "max_compression_range_ratio": cfg.max_compression_range_ratio,
            "expansion_range_multiple": cfg.expansion_range_multiple,
            "expansion_volume_multiple": cfg.expansion_volume_multiple,
            "breakout_buffer_points": cfg.breakout_buffer_points,
            "close_position_long_min": cfg.close_position_long_min,
            "close_position_short_max": cfg.close_position_short_max,
            "min_vwap_distance_points": cfg.min_vwap_distance_points,
            "trade_start": cfg.trade_start,
            "trade_end": cfg.trade_end,
        },
    )

    report_signal_cols = [args.signal_col_name]
    if "compression_breakout_score" in feature_cols:
        report_signal_cols.append("compression_breakout_score")
    print(f"Saved prepared signals: {paths.signals_csv}")
    print(f"Saved manifest:         {paths.manifest_md}")
    print()
    print("Next signal-gate command:")
    print(
        "python3 scripts/run_signal_research_report.py "
        f"--signals-csv {paths.signals_csv} "
        f"--signal-cols {','.join(report_signal_cols)} "
        "--context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side,compression_breakout_side,compression_pattern "
        "--entry-price-col open "
        "--entry-lag-bars 1 "
        "--exit-price-col close "
        "--round-trip-cost-points 1.5 "
        "--stress-round-trip-cost-points 2.0,4.25 "
        f"--artifact-name {args.artifact_name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
