#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.signal_export import (
    DEFAULT_CONTEXT_COLUMNS,
    build_prepared_signal_export,
    load_ohlcv_data,
    write_prepared_signal_export,
)
from config.backtest_config import BACKTEST_CONFIG, CANDIDATE_CONFIGS, FUTURES_SPECS, STRATEGY_PARAMS


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in str(value)).strip("_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export point-in-time strategy signals and context to a prepared CSV for "
            "pre-candidate signal research. This does not execute trades."
        )
    )
    parser.add_argument("--candidate", required=True, choices=sorted(CANDIDATE_CONFIGS))
    parser.add_argument(
        "--strategy",
        default="",
        choices=[
            "",
            "amt_mean_reversion",
            "amt_trend",
            "amt_combined",
            "vwap_regime",
            "volume_profile_regime",
            "market_profile_cross",
            "hybrid_profile_regime_no_orb",
        ],
        help="Optional strategy_name override before applying the candidate.",
    )
    parser.add_argument("--data-path", default=BACKTEST_CONFIG.get("data_path"))
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out-dir", default="results/research_master/signal_exports")
    parser.add_argument("--artifact-name", default="")
    parser.add_argument("--signal-col-name", default="candidate_signal")
    parser.add_argument(
        "--feature-cols",
        default="",
        help="Optional comma-separated numeric point-in-time feature columns to copy as explicit signal candidates.",
    )
    parser.add_argument(
        "--context-cols",
        default=",".join(DEFAULT_CONTEXT_COLUMNS),
        help="Comma-separated context columns to keep when available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate = str(args.candidate)
    artifact_name = args.artifact_name or _slugify(
        "_".join(part for part in [candidate, args.start or "all", args.end or "open", "prepared_signals"] if part)
    )

    data = load_ohlcv_data(
        args.data_path,
        continuous_contract_method=BACKTEST_CONFIG.get("continuous_contract_method"),
        start=args.start,
        end=args.end,
    )
    if data.empty:
        raise SystemExit("No bars after applying the requested date range.")

    strategy_params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG}
    if args.strategy:
        strategy_params["strategy_name"] = args.strategy
    strategy_params.update(CANDIDATE_CONFIGS[candidate])
    strategy_params["_candidate_name"] = candidate

    frame = build_prepared_signal_export(
        data,
        futures_specs=FUTURES_SPECS,
        strategy_params=strategy_params,
        starting_capital=float(BACKTEST_CONFIG["starting_capital"]),
        signal_col_name=args.signal_col_name,
        feature_cols=_csv_items(args.feature_cols),
        context_cols=_csv_items(args.context_cols),
    )
    paths = write_prepared_signal_export(
        frame,
        out_dir=Path(args.out_dir),
        artifact_name=artifact_name,
        metadata={
            "candidate": candidate,
            "strategy": args.strategy or strategy_params.get("strategy_name", ""),
            "data_path": args.data_path,
            "start": args.start or "",
            "end": args.end or "",
            "signal_col_name": args.signal_col_name,
            "feature_cols": ",".join(_csv_items(args.feature_cols)),
            "context_cols": ",".join(_csv_items(args.context_cols)),
        },
    )

    report_signal_cols = [args.signal_col_name] + _csv_items(args.feature_cols)
    print(f"Saved prepared signals: {paths.signals_csv}")
    print(f"Saved manifest:         {paths.manifest_md}")
    print()
    print("Next signal-gate command:")
    print(
        "python3 scripts/run_signal_research_report.py "
        f"--signals-csv {paths.signals_csv} "
        f"--signal-cols {','.join(report_signal_cols)} "
        "--context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side "
        "--entry-price-col open "
        "--entry-lag-bars 1 "
        "--exit-price-col close "
        "--round-trip-cost-points 1.5 "
        "--stress-round-trip-cost-points 2.0,4.25"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
