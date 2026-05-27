#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.power_hour_signal import (
    DEFAULT_POWER_HOUR_CONTEXT_COLUMNS,
    DEFAULT_POWER_HOUR_FEATURE_COLUMNS,
    PowerHourSignalConfig,
    build_power_hour_signal_export,
)
from backtest.signal_export import load_ohlcv_data, write_prepared_signal_export
from config.backtest_config import BACKTEST_CONFIG


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the pre-candidate power-hour accepted-trend continuation signal. "
            "This creates point-in-time signal rows only and does not execute trades."
        )
    )
    parser.add_argument("--data-path", default=BACKTEST_CONFIG.get("data_path"))
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default="results/research_master/signal_exports")
    parser.add_argument("--artifact-name", default="power_hour_continuation_dev_2010_2024")
    parser.add_argument("--signal-col-name", default="candidate_signal")
    parser.add_argument("--signal-start", default="15:00")
    parser.add_argument("--signal-end", default="15:30")
    parser.add_argument("--rth-start", default="09:30")
    parser.add_argument("--rth-end", default="16:00")
    parser.add_argument("--momentum-lookback-bars", type=int, default=30)
    parser.add_argument("--min-session-move-points", type=float, default=20.0)
    parser.add_argument("--min-session-move-to-range-ratio", type=float, default=0.45)
    parser.add_argument("--min-momentum-points", type=float, default=8.0)
    parser.add_argument("--close-position-long-min", type=float, default=0.80)
    parser.add_argument("--close-position-short-max", type=float, default=0.20)
    parser.add_argument("--min-vwap-distance-points", type=float, default=3.0)
    parser.add_argument(
        "--feature-cols",
        default=",".join(DEFAULT_POWER_HOUR_FEATURE_COLUMNS),
        help="Comma-separated numeric point-in-time signal/diagnostic columns to copy.",
    )
    parser.add_argument(
        "--context-cols",
        default=",".join(DEFAULT_POWER_HOUR_CONTEXT_COLUMNS),
        help="Comma-separated context columns to keep when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = PowerHourSignalConfig(
        signal_start=str(args.signal_start),
        signal_end=str(args.signal_end),
        rth_start=str(args.rth_start),
        rth_end=str(args.rth_end),
        momentum_lookback_bars=int(args.momentum_lookback_bars),
        min_session_move_points=float(args.min_session_move_points),
        min_session_move_to_range_ratio=float(args.min_session_move_to_range_ratio),
        min_momentum_points=float(args.min_momentum_points),
        close_position_long_min=float(args.close_position_long_min),
        close_position_short_max=float(args.close_position_short_max),
        min_vwap_distance_points=float(args.min_vwap_distance_points),
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
    frame = build_power_hour_signal_export(
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
            "hypothesis": "power_hour_accepted_trend_continuation",
            "data_path": args.data_path,
            "start": args.start or "",
            "end": args.end or "",
            "signal_col_name": args.signal_col_name,
            "feature_cols": ",".join(feature_cols),
            "context_cols": ",".join(context_cols),
            "signal_start": cfg.signal_start,
            "signal_end": cfg.signal_end,
            "rth_start": cfg.rth_start,
            "rth_end": cfg.rth_end,
            "momentum_lookback_bars": cfg.momentum_lookback_bars,
            "min_session_move_points": cfg.min_session_move_points,
            "min_session_move_to_range_ratio": cfg.min_session_move_to_range_ratio,
            "min_momentum_points": cfg.min_momentum_points,
            "close_position_long_min": cfg.close_position_long_min,
            "close_position_short_max": cfg.close_position_short_max,
            "min_vwap_distance_points": cfg.min_vwap_distance_points,
        },
    )

    report_signal_cols = [args.signal_col_name]
    if "power_hour_score" in feature_cols:
        report_signal_cols.append("power_hour_score")
    print(f"Saved prepared signals: {paths.signals_csv}")
    print(f"Saved manifest:         {paths.manifest_md}")
    print()
    print("Next temporal signal-gate command:")
    print(
        "python3.12 scripts/run_temporal_signal_research_report.py "
        f"--signals-csv {paths.signals_csv} "
        f"--signal-cols {','.join(report_signal_cols)} "
        "--context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side,closing_flow_side,close_location,momentum_state,power_hour_pattern "
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
