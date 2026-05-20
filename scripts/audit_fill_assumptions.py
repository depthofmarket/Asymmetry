#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.bar_exposure_audit import load_bars_csv  # noqa: E402
from backtest.execution_realism import export_fill_assumption_audit  # noqa: E402
from config.backtest_config import BACKTEST_CONFIG, CANDIDATE_CONFIGS, FUTURES_SPECS, STRATEGY_PARAMS  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audit saved trade-log fill assumptions against execution bars. "
            "This reads saved trades and bars only; it does not replay strategy logic."
        )
    )
    parser.add_argument("--run-dir", default=None, help="Run folder containing trades/trade_log.csv. Defaults to results/latest.txt.")
    parser.add_argument("--trade-log", default=None, help="Explicit trade log CSV. Overrides --run-dir.")
    parser.add_argument("--bars-csv", default=str(BACKTEST_CONFIG["data_path"]), help="Historical execution-bar CSV.")
    parser.add_argument("--candidate", default=None, help="Candidate config name for hard stop/target and tick settings.")
    parser.add_argument("--out-dir", default=None, help="Output directory. Defaults to <run-dir>/research/fill_assumptions.")
    parser.add_argument(
        "--continuous-contract-method",
        default=str(BACKTEST_CONFIG.get("continuous_contract_method", "prior_session_volume")),
        help="Contract-selection method for multi-contract Databento bars.",
    )
    parser.add_argument("--start", default=None, help="Optional inclusive start date matching the saved run.")
    parser.add_argument("--end", default=None, help="Optional inclusive end date matching the saved run.")
    parser.add_argument("--trade-through-ticks", default="1,2", help="Comma-separated trade-through tick checks.")
    return parser.parse_args()


def _default_run_dir() -> Path:
    latest = Path("results/latest.txt")
    if not latest.exists():
        raise FileNotFoundError("results/latest.txt is missing; pass --run-dir or --trade-log")
    label = latest.read_text(encoding="utf-8").strip()
    if not label:
        raise ValueError("results/latest.txt is empty; pass --run-dir or --trade-log")
    return Path("results/runs") / label


def _strategy_params(candidate: str | None) -> dict:
    params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG}
    if candidate:
        if candidate not in CANDIDATE_CONFIGS:
            raise KeyError(f"Unknown candidate: {candidate}")
        params.update(CANDIDATE_CONFIGS[candidate])
        params["_candidate_name"] = candidate
    return params


def _tick_checks(value: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    return tuple(out) or (1,)


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else _default_run_dir()
    trade_log = Path(args.trade_log) if args.trade_log else run_dir / "trades" / "trade_log.csv"
    out_dir = Path(args.out_dir) if args.out_dir else run_dir / "research" / "fill_assumptions"

    bars = load_bars_csv(
        args.bars_csv,
        continuous_contract_method=args.continuous_contract_method,
        start=args.start,
        end=args.end,
    )
    trades = pd.read_csv(trade_log)
    paths = export_fill_assumption_audit(
        trades,
        bars,
        out_dir=out_dir,
        futures_specs=FUTURES_SPECS,
        strategy_params=_strategy_params(args.candidate),
        trade_through_ticks=_tick_checks(args.trade_through_ticks),
    )
    print(f"Fill assumption audit: {trade_log}")
    print(f"summary: {paths.summary_csv}")
    print(f"by_trade: {paths.by_trade_csv}")
    print(f"by_reason: {paths.by_reason_csv}")
    print(f"markdown: {paths.markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
