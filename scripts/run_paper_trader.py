#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.live import PaperTradingConfig, PaperTradingEngine, save_execution_observation_reports
from backtest.live_prop_rules import LivePropRuleConfig, LivePropRuleGuard, profile_by_name
from config.backtest_config import BACKTEST_CONFIG, CANDIDATE_CONFIGS, FUTURES_SPECS, RESEARCH_CONFIG, STRATEGY_PARAMS
from main_backtest import load_data, resolve_max_drawdown_pct, slugify


DEFAULT_PAPER_CANDIDATE = "current"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the strategy through the live-style paper execution runtime. "
            "The default feed replays historical 1-minute bars and simulates "
            "fills locally; no broker orders are submitted."
        )
    )
    parser.add_argument(
        "--candidate",
        choices=sorted(CANDIDATE_CONFIGS),
        default=DEFAULT_PAPER_CANDIDATE,
        help="Candidate override from config/backtest_config.py.",
    )
    parser.add_argument(
        "--strategy",
        default=None,
        help="Optional strategy_name override.",
    )
    parser.add_argument(
        "--data-path",
        default=None,
        help="Override BACKTEST_CONFIG['data_path'].",
    )
    parser.add_argument("--start", default=None, help="Inclusive replay start date/time.")
    parser.add_argument("--end", default=None, help="Inclusive replay end date/time.")
    parser.add_argument(
        "--warmup-bars",
        type=int,
        default=500,
        help="Minimum 1-minute bars to collect before evaluating entries.",
    )
    parser.add_argument(
        "--max-bars",
        type=int,
        default=None,
        help="Optional cap on replayed bars after date filtering.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Seconds to sleep between replayed bars. Use 0 for fast replay.",
    )
    parser.add_argument(
        "--out-dir",
        default="results/paper",
        help="Directory for paper event and trade logs.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print each paper fill/skip event.",
    )
    parser.add_argument("--prop-guard", action="store_true", help="Enable prop-firm eval/funded rule guard and ledger.")
    parser.add_argument("--prop-profile", default="traders_launch_100k_nyc")
    parser.add_argument("--prop-phase", choices=["eval", "funded"], default="eval")
    parser.add_argument("--prop-daily-profit-lock", type=float, default=0.0)
    parser.add_argument("--prop-daily-loss-stop", type=float, default=None)
    return parser.parse_args()


def build_params(args: argparse.Namespace) -> dict:
    if args.candidate not in CANDIDATE_CONFIGS:
        raise ValueError(f"Unknown candidate: {args.candidate}")
    params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG, **CANDIDATE_CONFIGS[args.candidate]}
    params["_candidate_name"] = args.candidate
    if args.strategy is not None:
        params["strategy_name"] = args.strategy
    return params


def build_run_dir(base_dir: Path, params: dict, data: pd.DataFrame) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = slugify(params.get("_candidate_name", "current"))
    strategy = slugify(params.get("strategy_name", "strategy"))
    start = slugify(str(pd.to_datetime(data["time"]).min()).replace(":", ""))
    end = slugify(str(pd.to_datetime(data["time"]).max()).replace(":", ""))
    return base_dir / f"{timestamp}_{candidate}_{strategy}_{start}_to_{end}"


def print_event(event) -> None:
    price = "" if event.price is None else f" @{event.price:.2f}"
    contracts = "" if event.contracts is None else f" {event.contracts}x"
    pnl = "" if event.pnl is None else f" pnl=${event.pnl:,.2f}"
    reason = "" if not event.reason else f" reason={event.reason}"
    print(
        f"{event.timestamp} {event.event_type}{contracts} "
        f"{event.setup_tag or event.direction}{price}{pnl}{reason}",
        flush=True,
    )


def build_prop_guard(args: argparse.Namespace, params: dict) -> LivePropRuleGuard | None:
    if not args.prop_guard:
        return None
    profile = profile_by_name(
        list(RESEARCH_CONFIG.get("prop_firm_profiles", [])),
        str(args.prop_profile),
    )
    return LivePropRuleGuard(
        LivePropRuleConfig(
            profile=profile,
            candidate=str(params.get("_candidate_name", args.candidate)),
            phase=str(args.prop_phase),
            daily_loss_stop=args.prop_daily_loss_stop,
            daily_profit_lock=float(args.prop_daily_profit_lock or 0.0),
        )
    )


def main() -> int:
    args = parse_args()
    params = build_params(args)

    data_path = args.data_path or BACKTEST_CONFIG.get("data_path")
    if not data_path or not Path(data_path).exists():
        print(f"Data file not found: {data_path}")
        return 1

    print("Loading replay data...")
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
        return 1

    print(f"Loaded {len(data):,} 1-minute bars")
    print(f"From: {pd.to_datetime(data['time']).min()}")
    print(f"To:   {pd.to_datetime(data['time']).max()}")
    print(f"Candidate: {args.candidate}")
    print(f"Strategy:  {params.get('strategy_name')}")
    print("Paper runtime: local simulated fills only; no broker orders are submitted.")
    prop_guard = build_prop_guard(args, params)
    if prop_guard is not None:
        print(f"Prop guard: {prop_guard.profile_name} phase={args.prop_phase}")

    engine = PaperTradingEngine(
        futures_specs=FUTURES_SPECS,
        strategy_params=params,
        config=PaperTradingConfig(
            starting_capital=float(BACKTEST_CONFIG["starting_capital"]),
            max_drawdown_pct=resolve_max_drawdown_pct(params),
            warmup_1m_bars=max(0, int(args.warmup_bars)),
            prop_guard=prop_guard,
        ),
    )

    for _, row in data.iterrows():
        events = engine.on_bar(row)
        if not args.quiet:
            for event in events:
                print_event(event)
        if args.sleep > 0:
            time.sleep(args.sleep)

    run_dir = build_run_dir(Path(args.out_dir), params, data)
    run_dir.mkdir(parents=True, exist_ok=True)

    events = engine.event_log()
    trades = engine.trade_log()
    observations = engine.execution_observation_log()
    events_path = run_dir / "events.csv"
    trades_path = run_dir / "trades.csv"
    events.to_csv(events_path, index=False)
    trades.to_csv(trades_path, index=False)
    observation_paths = save_execution_observation_reports(observations, run_dir)
    prop_ledger_path = None
    if engine.prop_guard is not None:
        prop_ledger_path = run_dir / "prop_attempt_ledger.csv"
        engine.prop_guard.ledger_frame().to_csv(prop_ledger_path, index=False)

    final_price = float(data.iloc[-1]["close"])
    mtm_equity = engine.mark_to_market_equity(final_price)
    closed_pnl = float(trades["pnl"].sum()) if not trades.empty else 0.0
    print("\nPaper replay complete")
    print(f"Events:        {len(events)}")
    print(f"Closed trades: {len(trades)}")
    print(f"Closed P&L:    ${closed_pnl:,.2f}")
    print(f"MTM equity:    ${mtm_equity:,.2f}")
    print(f"Events CSV:    {events_path}")
    print(f"Trades CSV:    {trades_path}")
    print(f"Obs CSV:       {observation_paths['observations']}")
    print(f"Obs summary:   {observation_paths['summary']}")
    if prop_ledger_path is not None:
        print(f"Prop ledger:   {prop_ledger_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
