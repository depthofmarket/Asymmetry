#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.gap_fade_signal import (
    DEFAULT_GAP_FADE_CONTEXT_COLUMNS,
    DEFAULT_GAP_FADE_FEATURE_COLUMNS,
    GapFadeSignalConfig,
    build_gap_fade_signal_export,
)
from backtest.signal_export import load_ohlcv_data, write_prepared_signal_export
from config.backtest_config import BACKTEST_CONFIG


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export the pre-candidate RTH overnight gap fade signal (H2). "
            "This creates point-in-time signal rows only and does not execute trades."
        )
    )
    parser.add_argument("--data-path", default=BACKTEST_CONFIG.get("data_path"))
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default="results/research_master/signal_exports")
    parser.add_argument("--artifact-name", default="gap_fade_overnight_h2_signal_gate")
    parser.add_argument("--signal-col-name", default="candidate_signal")
    parser.add_argument("--min-gap-pct", type=float, default=0.0050)
    parser.add_argument("--min-gap-to-atr-ratio", type=float, default=0.20)
    parser.add_argument("--atr-window-days", type=int, default=20)
    parser.add_argument("--signal-time", default="09:30")
    parser.add_argument("--rth-start", default="09:30")
    parser.add_argument("--rth-end", default="16:00")
    parser.add_argument(
        "--feature-cols",
        default=",".join(DEFAULT_GAP_FADE_FEATURE_COLUMNS),
        help="Comma-separated numeric point-in-time signal/diagnostic columns to copy.",
    )
    parser.add_argument(
        "--context-cols",
        default=",".join(DEFAULT_GAP_FADE_CONTEXT_COLUMNS),
        help="Comma-separated context columns to keep when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = GapFadeSignalConfig(
        min_gap_pct=float(args.min_gap_pct),
        min_gap_to_atr_ratio=float(args.min_gap_to_atr_ratio),
        atr_window_days=int(args.atr_window_days),
        signal_time=str(args.signal_time),
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
    frame = build_gap_fade_signal_export(
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
            "hypothesis": "rth_overnight_gap_fade_h2",
            "source": "Lou, Polk, Skouras 2019 JFE",
            "data_path": args.data_path,
            "start": args.start or "",
            "end": args.end or "",
            "signal_col_name": args.signal_col_name,
            "feature_cols": ",".join(feature_cols),
            "context_cols": ",".join(context_cols),
            "min_gap_pct": cfg.min_gap_pct,
            "min_gap_to_atr_ratio": cfg.min_gap_to_atr_ratio,
            "atr_window_days": cfg.atr_window_days,
            "signal_time": cfg.signal_time,
            "rth_start": cfg.rth_start,
            "rth_end": cfg.rth_end,
        },
    )

    signal_rows = int((frame[args.signal_col_name] != 0.0).sum())
    print(f"Saved prepared signals: {paths.signals_csv}")
    print(f"Saved manifest:         {paths.manifest_md}")
    print(f"Active signal count:    {signal_rows:,}")
    print()
    print("Next signal-gate command:")
    print(
        f"python3 scripts/run_signal_research_report.py "
        f"--signals-csv {paths.signals_csv} "
        f"--signal-cols {args.signal_col_name},gap_fade_score "
        f"--context-cols direction,gap_direction,gap_size_bucket,hour,session_bucket "
        f"--entry-price-col open --entry-lag-bars 1 "
        f"--exit-price-col close "
        f"--round-trip-cost-points 1.5 "
        f"--stress-round-trip-cost-points 2.0,4.25 "
        f"--artifact-name {args.artifact_name}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
