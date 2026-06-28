#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.aggressive_flow_location_signal import (  # noqa: E402
    DEFAULT_AGGRESSIVE_FLOW_LOCATION_CONTEXT_COLUMNS,
    DEFAULT_AGGRESSIVE_FLOW_LOCATION_FEATURE_COLUMNS,
    AggressiveFlowLocationSignalConfig,
    build_aggressive_flow_location_signal_export,
)
from backtest.signal_export import load_ohlcv_data, write_prepared_signal_export  # noqa: E402
from config.backtest_config import BACKTEST_CONFIG  # noqa: E402


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the pre-candidate aggressive-flow/location signal. This creates "
            "point-in-time signal rows only and does not execute trades or run a backtest."
        )
    )
    parser.add_argument("--data-path", default=BACKTEST_CONFIG.get("data_path"))
    parser.add_argument(
        "--location-context",
        default="data/processed/location_context/aggressive_flow_location_l2.csv",
        help="Point-in-time location context CSV from scripts/build_location_context.py.",
    )
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default="results/research_master/signal_exports")
    parser.add_argument("--artifact-name", default="aggressive_flow_location_l2_signal_gate")
    parser.add_argument("--signal-col-name", default="candidate_signal")
    parser.add_argument("--min-abs-flow-share", type=float, default=0.35)
    parser.add_argument("--min-price-change-points", type=float, default=1.0)
    parser.add_argument("--min-score", type=float, default=1.0)
    parser.add_argument("--value-acceptance-buffer-points", type=float, default=0.5)
    parser.add_argument("--profile-acceptance-buffer-points", type=float, default=0.5)
    parser.add_argument("--max-context-age", default="5min")
    parser.add_argument("--trade-start", default="09:35")
    parser.add_argument("--trade-end", default="15:45")
    parser.add_argument("--score-price-scale-points", type=float, default=2.0)
    parser.add_argument("--score-cap", type=float, default=4.0)
    parser.add_argument(
        "--allow-inside-value",
        action="store_true",
        help="Allow price-expansion signals without accepted-above/below profile or value context.",
    )
    parser.add_argument(
        "--allow-stale-context",
        action="store_true",
        help="Allow stale/missing location context. Intended only for plumbing diagnostics.",
    )
    parser.add_argument(
        "--feature-cols",
        default=",".join(DEFAULT_AGGRESSIVE_FLOW_LOCATION_FEATURE_COLUMNS),
        help="Comma-separated numeric point-in-time signal/diagnostic columns to copy.",
    )
    parser.add_argument(
        "--context-cols",
        default=",".join(DEFAULT_AGGRESSIVE_FLOW_LOCATION_CONTEXT_COLUMNS),
        help="Comma-separated context columns to keep when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    location_path = Path(args.location_context)
    if not location_path.exists():
        raise SystemExit(
            f"Location context not found: {location_path}\n"
            "Build it first with scripts/build_location_context.py; this exporter does not build context inline."
        )

    print(f"Loading bars: {args.data_path}", flush=True)
    cfg = AggressiveFlowLocationSignalConfig(
        min_abs_flow_share=float(args.min_abs_flow_share),
        min_price_change_points=float(args.min_price_change_points),
        min_score=float(args.min_score),
        value_acceptance_buffer_points=float(args.value_acceptance_buffer_points),
        profile_acceptance_buffer_points=float(args.profile_acceptance_buffer_points),
        max_context_age=str(args.max_context_age),
        trade_start=str(args.trade_start),
        trade_end=str(args.trade_end),
        score_price_scale_points=float(args.score_price_scale_points),
        score_cap=float(args.score_cap),
        require_profile_acceptance=not bool(args.allow_inside_value),
        require_context_fresh=not bool(args.allow_stale_context),
    )

    data = load_ohlcv_data(
        args.data_path,
        continuous_contract_method=BACKTEST_CONFIG.get("continuous_contract_method"),
        start=args.start,
        end=args.end,
    )
    if data.empty:
        raise SystemExit("No bars after applying the requested date range.")
    print(f"Loaded bars: {len(data):,} rows", flush=True)
    print(f"Loading location context: {location_path}", flush=True)

    feature_cols = _csv_items(args.feature_cols)
    context_cols = _csv_items(args.context_cols)
    print("Building aggressive-flow/location signal export...", flush=True)
    frame = build_aggressive_flow_location_signal_export(
        data,
        location_path,
        config=cfg,
        signal_col_name=args.signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )
    active = int(frame.get(args.signal_col_name, []).astype(float).ne(0.0).sum()) if args.signal_col_name in frame else 0
    print(f"Built signal export: {len(frame):,} rows, {active:,} active signals", flush=True)
    print(f"Writing prepared signal export to: {args.out_dir}", flush=True)
    paths = write_prepared_signal_export(
        frame,
        out_dir=Path(args.out_dir),
        artifact_name=args.artifact_name,
        metadata={
            "hypothesis": "aggressive_flow_location_l2_signal_gate",
            "data_path": args.data_path,
            "location_context": str(location_path),
            "start": args.start or "",
            "end": args.end or "",
            "signal_col_name": args.signal_col_name,
            "feature_cols": ",".join(feature_cols),
            "context_cols": ",".join(context_cols),
            "min_abs_flow_share": cfg.min_abs_flow_share,
            "min_price_change_points": cfg.min_price_change_points,
            "min_score": cfg.min_score,
            "value_acceptance_buffer_points": cfg.value_acceptance_buffer_points,
            "profile_acceptance_buffer_points": cfg.profile_acceptance_buffer_points,
            "max_context_age": cfg.max_context_age,
            "trade_start": cfg.trade_start,
            "trade_end": cfg.trade_end,
            "score_price_scale_points": cfg.score_price_scale_points,
            "score_cap": cfg.score_cap,
            "require_profile_acceptance": cfg.require_profile_acceptance,
            "require_context_fresh": cfg.require_context_fresh,
        },
    )

    report_signal_cols = [args.signal_col_name]
    if "aggressive_flow_location_score" in feature_cols:
        report_signal_cols.append("aggressive_flow_location_score")
    print(f"Saved prepared signals: {paths.signals_csv}")
    print(f"Saved manifest:         {paths.manifest_md}")
    print()
    print("Next signal-gate command:")
    print(
        "python3 scripts/run_signal_research_report.py "
        f"--signals-csv {paths.signals_csv} "
        f"--signal-cols {','.join(report_signal_cols)} "
        "--context-cols direction,hour,session_bucket,vwap_side,profile_acceptance_state,orderflow_state,flow_price_state "
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
