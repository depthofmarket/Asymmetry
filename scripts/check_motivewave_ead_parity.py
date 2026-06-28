#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.motivewave_ead import (  # noqa: E402
    MotiveWaveEADConfig,
    build_motivewave_ead_parity,
    read_frame,
    write_motivewave_ead_parity_result,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare native EAD candidate output against a MotiveWave EAD export. "
            "This is a parity gate only; it is not a backtest and makes no edge claim."
        )
    )
    parser.add_argument("--trades", required=True, help="Normalized trade-print CSV/parquet.")
    parser.add_argument("--motivewave-export", required=True, help="MotiveWave EAD export CSV/parquet.")
    parser.add_argument("--bucket-mode", choices=["tick", "volume"], required=True)
    parser.add_argument("--bucket-size", type=float, required=True)
    parser.add_argument("--mode", choices=["default", "fast"], default="default")
    parser.add_argument("--absorption-intensity", type=int, default=None)
    parser.add_argument("--volume-sensitivity", type=int, default=None)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--trade-time-col", default="ts_event")
    parser.add_argument("--trade-timezone", default="UTC")
    parser.add_argument("--motivewave-time-col", default="time")
    parser.add_argument("--motivewave-timezone", default="America/New_York")
    parser.add_argument("--motivewave-availability-lag", default="0min")
    parser.add_argument("--allow-result-columns", action="store_true")
    parser.add_argument("--max-trades", type=int, default=None, help="Optional cap for bounded parity samples.")
    parser.add_argument("--out-dir", default="results/research_master/motivewave_ead_parity")
    parser.add_argument("--prefix", default="motivewave_ead_parity")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    trades = read_frame(args.trades, max_rows=args.max_trades)
    config = _ead_config(args)
    result = build_motivewave_ead_parity(
        trades,
        args.motivewave_export,
        bucket_mode=str(args.bucket_mode),
        bucket_size=float(args.bucket_size),
        ead_config=config,
        trade_time_col=str(args.trade_time_col),
        trade_timezone=str(args.trade_timezone),
        motivewave_time_col=str(args.motivewave_time_col),
        motivewave_timezone=str(args.motivewave_timezone),
        motivewave_availability_lag=str(args.motivewave_availability_lag),
        allow_result_columns=bool(args.allow_result_columns),
    )
    paths = write_motivewave_ead_parity_result(result, args.out_dir, prefix=args.prefix)
    print(result.report_md)
    print(f"native EAD:       {paths['native_ead_csv']}")
    print(f"MotiveWave EAD:   {paths['motivewave_ead_csv']}")
    print(f"aligned parity:   {paths['aligned_csv']}")
    print(f"mismatches:       {paths['mismatches_csv']}")
    print(f"report:           {paths['report_md']}")
    return 0 if result.passed else 1


def _ead_config(args: argparse.Namespace) -> MotiveWaveEADConfig:
    base = MotiveWaveEADConfig.for_mode(str(args.mode))
    return MotiveWaveEADConfig(
        absorption_intensity=(
            int(args.absorption_intensity)
            if args.absorption_intensity is not None
            else int(base.absorption_intensity)
        ),
        volume_sensitivity=(
            int(args.volume_sensitivity)
            if args.volume_sensitivity is not None
            else int(base.volume_sensitivity)
        ),
        threshold=float(args.threshold) if args.threshold is not None else float(base.threshold),
        mode=str(base.mode),
    )


if __name__ == "__main__":
    raise SystemExit(main())
