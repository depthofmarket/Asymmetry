#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.gap_go_signal import (
    DEFAULT_GAP_GO_CONTEXT_COLUMNS,
    DEFAULT_GAP_GO_FEATURE_COLUMNS,
    GapGoSignalConfig,
    build_gap_go_signal_export,
)
from backtest.signal_export import load_ohlcv_data, write_prepared_signal_export
from config.backtest_config import BACKTEST_CONFIG


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the pre-candidate RTH gap-and-go opening-range continuation signal. "
            "This creates point-in-time signal rows only and does not execute trades."
        )
    )
    parser.add_argument("--data-path", default=BACKTEST_CONFIG.get("data_path"))
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default="results/research_master/signal_exports")
    parser.add_argument("--artifact-name", default="gap_go_dev_2010_2024")
    parser.add_argument("--signal-col-name", default="candidate_signal")
    parser.add_argument("--opening-range-minutes", type=int, default=15)
    parser.add_argument("--min-abs-gap-points", type=float, default=20.0)
    parser.add_argument("--min-gap-to-prior-range-ratio", type=float, default=0.15)
    parser.add_argument("--gap-hold-tolerance-points", type=float, default=2.0)
    parser.add_argument("--breakout-buffer-points", type=float, default=0.25)
    parser.add_argument("--close-position-long-min", type=float, default=0.70)
    parser.add_argument("--close-position-short-max", type=float, default=0.30)
    parser.add_argument("--min-vwap-distance-points", type=float, default=0.0)
    parser.add_argument("--trade-start", default="09:45")
    parser.add_argument("--trade-end", default="11:00")
    parser.add_argument("--rth-start", default="09:30")
    parser.add_argument("--rth-end", default="16:00")
    parser.add_argument(
        "--feature-cols",
        default=",".join(DEFAULT_GAP_GO_FEATURE_COLUMNS),
        help="Comma-separated numeric point-in-time signal/diagnostic columns to copy.",
    )
    parser.add_argument(
        "--context-cols",
        default=",".join(DEFAULT_GAP_GO_CONTEXT_COLUMNS),
        help="Comma-separated context columns to keep when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = GapGoSignalConfig(
        opening_range_minutes=int(args.opening_range_minutes),
        min_abs_gap_points=float(args.min_abs_gap_points),
        min_gap_to_prior_range_ratio=float(args.min_gap_to_prior_range_ratio),
        gap_hold_tolerance_points=float(args.gap_hold_tolerance_points),
        breakout_buffer_points=float(args.breakout_buffer_points),
        close_position_long_min=float(args.close_position_long_min),
        close_position_short_max=float(args.close_position_short_max),
        min_vwap_distance_points=float(args.min_vwap_distance_points),
        trade_start=str(args.trade_start),
        trade_end=str(args.trade_end),
        rth_start=str(args.rth_start),
        rth_end=str(args.rth_end),
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
    frame = build_gap_go_signal_export(
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
            "hypothesis": "rth_gap_go_opening_range_continuation",
            "data_path": args.data_path,
            "start": args.start or "",
            "end": args.end or "",
            "signal_col_name": args.signal_col_name,
            "feature_cols": ",".join(feature_cols),
            "context_cols": ",".join(context_cols),
            "opening_range_minutes": cfg.opening_range_minutes,
            "min_abs_gap_points": cfg.min_abs_gap_points,
            "min_gap_to_prior_range_ratio": cfg.min_gap_to_prior_range_ratio,
            "gap_hold_tolerance_points": cfg.gap_hold_tolerance_points,
            "breakout_buffer_points": cfg.breakout_buffer_points,
            "close_position_long_min": cfg.close_position_long_min,
            "close_position_short_max": cfg.close_position_short_max,
            "min_vwap_distance_points": cfg.min_vwap_distance_points,
            "trade_start": cfg.trade_start,
            "trade_end": cfg.trade_end,
            "rth_start": cfg.rth_start,
            "rth_end": cfg.rth_end,
        },
    )

    report_signal_cols = [args.signal_col_name]
    if "gap_go_score" in feature_cols:
        report_signal_cols.append("gap_go_score")
    print(f"Saved prepared signals: {paths.signals_csv}")
    print(f"Saved manifest:         {paths.manifest_md}")
    print()
    print("Next temporal signal-gate command:")
    print(
        "python3.12 scripts/run_temporal_signal_research_report.py "
        f"--signals-csv {paths.signals_csv} "
        f"--signal-cols {','.join(report_signal_cols)} "
        "--context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side,gap_direction,gap_hold_status,opening_range_breakout_side,gap_go_pattern "
        "--splits legacy_context:2010-01-01:2015-12-31,transition:2016-01-01:2020-12-31,recent_development:2021-01-01:2024-12-31 "
        "--primary-split recent_development "
        "--supporting-splits transition "
        "--entry-price-col open "
        "--entry-lag-bars 1 "
        "--exit-price-col close "
        "--round-trip-cost-points 1.5 "
        "--stress-round-trip-cost-points 2.0,4.25 "
        f"--artifact-name {args.artifact_name}_temporal_gate"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
