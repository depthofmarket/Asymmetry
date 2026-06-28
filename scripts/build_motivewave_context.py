#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.motivewave_context import (  # noqa: E402
    MotiveWaveContextConfig,
    build_motivewave_context,
    write_motivewave_context_artifacts,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize exported MotiveWave orderflow indicator values/signals into "
            "point-in-time trigger context for L2 replay gates."
        )
    )
    parser.add_argument("--export", required=True, help="MotiveWave CSV/parquet export with a time column.")
    parser.add_argument("--out-dir", default="data/processed/motivewave_context")
    parser.add_argument("--prefix", default="motivewave_context")
    parser.add_argument("--time-col", default="time")
    parser.add_argument("--timezone", default="America/New_York")
    parser.add_argument("--availability-lag", default="0min")
    parser.add_argument(
        "--allow-result-columns",
        action="store_true",
        help="Allow result-like columns for manual audit only. Do not use for replay features.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = MotiveWaveContextConfig(
        time_col=str(args.time_col),
        timezone=str(args.timezone),
        availability_lag=str(args.availability_lag),
        allow_result_columns=bool(args.allow_result_columns),
    )
    artifacts = build_motivewave_context(args.export, config=config)
    paths = write_motivewave_context_artifacts(artifacts, args.out_dir, prefix=args.prefix)
    print(f"MotiveWave context CSV:    {paths['csv']} ({len(artifacts.frame):,} rows)")
    print(f"MotiveWave context report: {paths['report_md']}")
    if not artifacts.frame.empty:
        cols = [
            "time",
            "source_signal_time",
            "mw_absorption_long_trigger",
            "mw_absorption_short_trigger",
            "mw_initiative_long_trigger",
            "mw_initiative_short_trigger",
            "mw_orderflow_long_trigger",
            "mw_orderflow_short_trigger",
            "mw_any_long_trigger",
            "mw_any_short_trigger",
        ]
        print(artifacts.frame[[col for col in cols if col in artifacts.frame.columns]].tail(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
