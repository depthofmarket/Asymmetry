#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.live_parity import (
    compare_trade_logs,
    run_backtest_trade_log,
    run_paper_replay_trade_log,
)
from config.backtest_config import BACKTEST_CONFIG, CANDIDATE_CONFIGS, FUTURES_SPECS, STRATEGY_PARAMS
from main_backtest import load_data, resolve_max_drawdown_pct


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare BacktestEngine trades with PaperTradingEngine replay trades on one historical window."
    )
    parser.add_argument("--candidate", choices=sorted(CANDIDATE_CONFIGS), default="current")
    parser.add_argument("--strategy", default=None)
    parser.add_argument("--data-path", default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--max-bars", type=int, default=None)
    parser.add_argument("--warmup-bars", type=int, default=0)
    parser.add_argument("--price-tolerance", type=float, default=1e-9)
    parser.add_argument("--pnl-tolerance", type=float, default=1e-6)
    parser.add_argument("--show", type=int, default=20, help="Maximum mismatches to print.")
    return parser.parse_args()


def build_params(args: argparse.Namespace) -> dict:
    params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG, **CANDIDATE_CONFIGS[args.candidate]}
    params["_candidate_name"] = args.candidate
    if args.strategy is not None:
        params["strategy_name"] = args.strategy
    return params


def main() -> int:
    args = parse_args()
    params = build_params(args)
    data_path = args.data_path or BACKTEST_CONFIG.get("data_path")
    if not data_path or not Path(data_path).exists():
        print(f"Data file not found: {data_path}")
        return 2

    data = load_data(
        data_path,
        continuous_contract_method=BACKTEST_CONFIG.get("continuous_contract_method"),
        start=args.start,
        end=args.end,
    )
    if args.max_bars is not None:
        data = data.head(max(0, int(args.max_bars))).copy()
    if data.empty:
        print("No data after filtering.")
        return 2

    max_drawdown_pct = resolve_max_drawdown_pct(params)
    print(f"Loaded {len(data):,} 1-minute bars")
    print(f"Window: {data['time'].min()} -> {data['time'].max()}")
    print(f"Candidate: {args.candidate}")
    print("Running BacktestEngine...")
    backtest_trades = run_backtest_trade_log(
        data,
        futures_specs=FUTURES_SPECS,
        strategy_params=params,
        starting_capital=float(BACKTEST_CONFIG["starting_capital"]),
        max_drawdown_pct=max_drawdown_pct,
    )
    print("Running PaperTradingEngine replay...")
    paper_trades = run_paper_replay_trade_log(
        data,
        futures_specs=FUTURES_SPECS,
        strategy_params=params,
        starting_capital=float(BACKTEST_CONFIG["starting_capital"]),
        max_drawdown_pct=max_drawdown_pct,
        warmup_1m_bars=int(args.warmup_bars),
    )

    report = compare_trade_logs(
        backtest_trades,
        paper_trades,
        price_tolerance=float(args.price_tolerance),
        pnl_tolerance=float(args.pnl_tolerance),
    )
    print(report.summary())
    for mismatch in report.mismatches[: max(0, int(args.show))]:
        print(
            f"row={mismatch.row} field={mismatch.field} "
            f"backtest={mismatch.backtest_value!r} paper={mismatch.paper_value!r}"
        )
    if len(report.mismatches) > args.show:
        print(f"... {len(report.mismatches) - args.show} more mismatches")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
