#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.memory_impulse_signal import (
    DEFAULT_MEMORY_IMPULSE_CONTEXT_COLUMNS,
    DEFAULT_MEMORY_IMPULSE_FEATURE_COLUMNS,
    MemoryImpulseSignalConfig,
    build_memory_impulse_signal_export,
)
from backtest.signal_export import load_ohlcv_data, write_prepared_signal_export
from config.backtest_config import BACKTEST_CONFIG


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the pre-candidate market-memory impulse-continuation signal. "
            "This creates point-in-time signal rows only and does not execute trades."
        )
    )
    parser.add_argument("--data-path", default=BACKTEST_CONFIG.get("data_path"))
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default="results/research_master/signal_exports")
    parser.add_argument("--artifact-name", default="memory_impulse_dev_2010_2024")
    parser.add_argument("--signal-col-name", default="candidate_signal")
    parser.add_argument("--atr-lookback-bars", type=int, default=78)
    parser.add_argument("--cusum-event-atr-multiple", type=float, default=1.0)
    parser.add_argument("--cusum-min-threshold-points", type=float, default=1.0)
    parser.add_argument("--min-event-move-atr", type=float, default=1.0)
    parser.add_argument("--memory-window-bars", type=int, default=156)
    parser.add_argument("--memory-min-bars", type=int, default=64)
    parser.add_argument("--min-persistence", type=float, default=0.30)
    parser.add_argument("--max-entropy", type=float, default=0.95)
    parser.add_argument("--max-complexity", type=float, default=0.55)
    parser.add_argument("--cooldown-bars", type=int, default=6)
    parser.add_argument(
        "--feature-cols",
        default=",".join(DEFAULT_MEMORY_IMPULSE_FEATURE_COLUMNS),
        help="Comma-separated numeric point-in-time signal/diagnostic columns to copy.",
    )
    parser.add_argument(
        "--context-cols",
        default=",".join(DEFAULT_MEMORY_IMPULSE_CONTEXT_COLUMNS),
        help="Comma-separated context columns to keep when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = MemoryImpulseSignalConfig(
        atr_lookback_bars=int(args.atr_lookback_bars),
        cusum_event_atr_multiple=float(args.cusum_event_atr_multiple),
        cusum_min_threshold_points=float(args.cusum_min_threshold_points),
        min_event_move_atr=float(args.min_event_move_atr),
        memory_window_bars=int(args.memory_window_bars),
        memory_min_bars=int(args.memory_min_bars),
        min_persistence=float(args.min_persistence),
        max_entropy=float(args.max_entropy),
        max_complexity=float(args.max_complexity),
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
    frame = build_memory_impulse_signal_export(
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
            "hypothesis": "memory_impulse_continuation",
            "data_path": args.data_path,
            "start": args.start or "",
            "end": args.end or "",
            "signal_col_name": args.signal_col_name,
            "feature_cols": ",".join(feature_cols),
            "context_cols": ",".join(context_cols),
            "atr_lookback_bars": cfg.atr_lookback_bars,
            "cusum_event_atr_multiple": cfg.cusum_event_atr_multiple,
            "cusum_min_threshold_points": cfg.cusum_min_threshold_points,
            "min_event_move_atr": cfg.min_event_move_atr,
            "memory_window_bars": cfg.memory_window_bars,
            "memory_min_bars": cfg.memory_min_bars,
            "min_persistence": cfg.min_persistence,
            "max_entropy": cfg.max_entropy,
            "max_complexity": cfg.max_complexity,
            "cooldown_bars": cfg.cooldown_bars,
        },
    )

    report_signal_cols = [args.signal_col_name]
    if "memory_impulse_score" in feature_cols:
        report_signal_cols.append("memory_impulse_score")
    print(f"Saved prepared signals: {paths.signals_csv}")
    print(f"Saved manifest:         {paths.manifest_md}")
    print()
    print("Next temporal signal-gate command:")
    print(
        "python3.12 scripts/run_temporal_signal_research_report.py "
        f"--signals-csv {paths.signals_csv} "
        f"--signal-cols {','.join(report_signal_cols)} "
        "--context-cols setup_tag,direction,signal_type,hour,session_bucket,prior_memory_state,"
        "prior_memory_persistence_regime,prior_memory_entropy_regime,prior_memory_complexity_regime,"
        "memory_impulse_side,memory_impulse_pattern "
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
