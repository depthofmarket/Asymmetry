#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.bar_exposure_audit import (
    export_bar_exposure_audit,
    load_bars_csv,
    resample_bars,
    load_trades_csv,
    resolve_run_dir,
)
from config.backtest_config import BACKTEST_CONFIG, FUTURES_SPECS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit saved trade-log exposure against close-to-close bar PnL. "
            "This reads saved trades and bars only; it does not replay strategy logic."
        )
    )
    parser.add_argument("--run-dir", default=None, help="Saved results/runs/<label> directory. Defaults to results/latest.txt.")
    parser.add_argument("--bars-csv", default=str(BACKTEST_CONFIG["data_path"]), help="Historical bar CSV with time and close columns.")
    parser.add_argument("--out-dir", default=None, help="Output directory. Defaults to <run-dir>/research/bar_exposure_audit.")
    parser.add_argument(
        "--continuous-contract-method",
        default=str(BACKTEST_CONFIG.get("continuous_contract_method", "prior_session_volume")),
        help="Contract-selection method for multi-contract Databento bars.",
    )
    parser.add_argument("--bar-timeframe", default="5min", help="Signal objective bar timeframe. Use empty string to keep source bars.")
    parser.add_argument(
        "--execution-bar-timeframe",
        default="",
        help="Execution-path audit timeframe. Default keeps source bars, normally 1-minute.",
    )
    parser.add_argument("--start", default=None, help="Optional inclusive start date matching the saved run.")
    parser.add_argument("--end", default=None, help="Optional inclusive end date matching the saved run.")
    parser.add_argument("--abs-pf-tolerance", type=float, default=0.05)
    parser.add_argument("--rel-pf-tolerance", type=float, default=0.05)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = resolve_run_dir(args.run_dir)
    trades_csv = run_dir / "trades" / "trade_log.csv"
    development_report = run_dir / "research" / "development_report.csv"
    out_dir = Path(args.out_dir) if args.out_dir else run_dir / "research" / "bar_exposure_audit"

    source_bars = load_bars_csv(
        args.bars_csv,
        continuous_contract_method=args.continuous_contract_method,
        start=args.start,
        end=args.end,
    )
    bars = resample_bars(source_bars, rule=args.bar_timeframe) if args.bar_timeframe else source_bars
    execution_bars = (
        resample_bars(source_bars, rule=args.execution_bar_timeframe)
        if args.execution_bar_timeframe
        else source_bars
    )
    trades = load_trades_csv(trades_csv)
    paths = export_bar_exposure_audit(
        bars=bars,
        execution_bars=execution_bars,
        trades=trades,
        futures_specs=FUTURES_SPECS,
        starting_capital=float(BACKTEST_CONFIG["starting_capital"]),
        out_dir=out_dir,
        development_report_csv=development_report,
        abs_pf_tolerance=float(args.abs_pf_tolerance),
        rel_pf_tolerance=float(args.rel_pf_tolerance),
    )

    print(f"Bar exposure audit written to: {out_dir}")
    print(f"- {paths.summary_csv}")
    print(f"- {paths.by_trade_csv}")
    print(f"- {paths.by_slice_csv}")
    if paths.execution_by_trade_csv is not None:
        print(f"- {paths.execution_by_trade_csv}")
    if paths.execution_by_slice_csv is not None:
        print(f"- {paths.execution_by_slice_csv}")
    print(f"- {paths.report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
