#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.options_gamma_wall_signal import (
    DEFAULT_OPTIONS_GAMMA_WALL_CONTEXT_COLUMNS,
    DEFAULT_OPTIONS_GAMMA_WALL_FEATURE_COLUMNS,
    OptionsGammaWallSignalConfig,
    build_options_gamma_wall_signal_export,
)
from backtest.signal_export import load_ohlcv_data, write_prepared_signal_export
from config.backtest_config import BACKTEST_CONFIG, OPTIONS_FLOW_CONFIG


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the pre-candidate positive-gamma wall reversion signal. "
            "This creates point-in-time signal rows only and does not execute trades."
        )
    )
    parser.add_argument("--data-path", default=BACKTEST_CONFIG.get("data_path"))
    parser.add_argument("--options-flow-path", default=OPTIONS_FLOW_CONFIG.get("features_path"))
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default="results/research_master/signal_exports")
    parser.add_argument("--artifact-name", default="options_gamma_wall_dev_2010_2024")
    parser.add_argument("--signal-col-name", default="candidate_signal")
    parser.add_argument("--min-abs-wall-distance-points", type=float, default=10.0)
    parser.add_argument("--max-abs-wall-distance-points", type=float, default=100.0)
    parser.add_argument("--max-options-age-days", type=float, default=120.0)
    parser.add_argument("--cooldown-bars", type=int, default=15)
    parser.add_argument(
        "--feature-cols",
        default=",".join(DEFAULT_OPTIONS_GAMMA_WALL_FEATURE_COLUMNS),
        help="Comma-separated numeric point-in-time signal/diagnostic columns to copy.",
    )
    parser.add_argument(
        "--context-cols",
        default=",".join(DEFAULT_OPTIONS_GAMMA_WALL_CONTEXT_COLUMNS),
        help="Comma-separated context columns to keep when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = OptionsGammaWallSignalConfig(
        min_abs_wall_distance_points=float(args.min_abs_wall_distance_points),
        max_abs_wall_distance_points=float(args.max_abs_wall_distance_points),
        max_options_age_days=float(args.max_options_age_days),
        cooldown_bars=int(args.cooldown_bars),
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
    frame = build_options_gamma_wall_signal_export(
        data,
        args.options_flow_path,
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
            "hypothesis": "options_gamma_wall_positive_gamma_reversion",
            "data_path": args.data_path,
            "options_flow_path": args.options_flow_path,
            "start": args.start or "",
            "end": args.end or "",
            "signal_col_name": args.signal_col_name,
            "feature_cols": ",".join(feature_cols),
            "context_cols": ",".join(context_cols),
            "min_abs_wall_distance_points": cfg.min_abs_wall_distance_points,
            "max_abs_wall_distance_points": cfg.max_abs_wall_distance_points,
            "max_options_age_days": cfg.max_options_age_days,
            "cooldown_bars": cfg.cooldown_bars,
        },
    )

    report_signal_cols = [args.signal_col_name]
    if "options_gamma_wall_score" in feature_cols:
        report_signal_cols.append("options_gamma_wall_score")
    print(f"Saved prepared signals: {paths.signals_csv}")
    print(f"Saved manifest:         {paths.manifest_md}")
    print()
    print("Next temporal signal-gate command:")
    print(
        "python3.12 scripts/run_temporal_signal_research_report.py "
        f"--signals-csv {paths.signals_csv} "
        f"--signal-cols {','.join(report_signal_cols)} "
        "--context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side,"
        "options_gamma_environment,options_gex_regime,options_gamma_wall_role,"
        "options_call_wall_role,options_put_wall_role,options_flow_age_bucket,"
        "gamma_wall_side,options_gamma_wall_pattern "
        "--splits legacy_context:2010-01-01:2015-12-31,transition:2016-01-01:2020-12-31,recent_development:2021-01-01:2024-12-31 "
        "--primary-split recent_development "
        "--supporting-splits transition "
        "--entry-price-col open "
        "--entry-lag-bars 1 "
        "--exit-price-col close "
        "--round-trip-cost-points 1.5 "
        "--stress-round-trip-cost-points 2.0,4.25 "
        "--event-bootstrap-samples 2000 "
        "--event-placebo-samples 2000 "
        f"--artifact-name {args.artifact_name}_event_temporal_gate"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
