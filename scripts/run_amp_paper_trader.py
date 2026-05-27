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

from backtest.live import (
    PaperTradingConfig,
    PaperTradingEngine,
    PaperTradingEvent,
    save_execution_observation_reports,
)
from backtest.live_brokers import (
    CqgWebApiBroker,
    CsvOrderAuditBroker,
    NullBroker,
    PaperEventOrderBridge,
)
from backtest.live_feeds import (
    CqgWebApiConfig,
    CqgWebApiFeed,
    CqgWebApiSetupError,
    CsvReplayFeed,
    FileTailBarFeed,
)
from backtest.live_prop_rules import (
    LivePropRuleConfig,
    LivePropRuleGuard,
    profile_by_name,
    validate_prop_research_gate,
)
from config.backtest_config import BACKTEST_CONFIG, CANDIDATE_CONFIGS, FUTURES_SPECS, RESEARCH_CONFIG, STRATEGY_PARAMS
from main_backtest import load_data, resolve_max_drawdown_pct, slugify


DEFAULT_PAPER_CANDIDATE = "current"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "AMP/CQG-oriented live paper runner. Replay and file-tail modes are "
            "available now; CQG modes are guarded until API credentials and "
            "sample protocol modules are configured."
        )
    )
    parser.add_argument("--candidate", choices=sorted(CANDIDATE_CONFIGS), default=DEFAULT_PAPER_CANDIDATE)
    parser.add_argument("--strategy", default=None)
    parser.add_argument(
        "--feed",
        choices=["replay", "tail", "cqg"],
        default="replay",
        help="Bar source. Use tail for an external live CSV bridge; cqg requires AMP/CQG WebAPI setup.",
    )
    parser.add_argument(
        "--broker",
        choices=["audit", "none", "cqg"],
        default="audit",
        help="Order destination. audit writes intended broker orders to CSV.",
    )
    parser.add_argument("--data-path", default=None, help="Replay mode data path.")
    parser.add_argument("--bar-file", default=None, help="Tail mode CSV path with completed bars.")
    parser.add_argument("--start", default=None, help="Replay start date/time.")
    parser.add_argument("--end", default=None, help="Replay end date/time.")
    parser.add_argument("--max-bars", type=int, default=None, help="Replay bar cap after filtering.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Replay sleep seconds per bar.")
    parser.add_argument("--poll-seconds", type=float, default=1.0, help="Tail mode polling cadence.")
    parser.add_argument("--tail-from-start", action="store_true", help="Tail existing rows too.")
    parser.add_argument("--warmup-bars", type=int, default=500)
    parser.add_argument("--cqg-symbol", default=None, help="Broker/order symbol override.")
    parser.add_argument("--max-daily-loss", type=float, default=0.0, help="Flatten/block entries after this MTM daily loss.")
    parser.add_argument("--no-new-trades-after", default=None, help="HH:MM clock after which entries are blocked.")
    parser.add_argument("--flatten-at", default=None, help="HH:MM clock at/after which open paper positions are flattened.")
    parser.add_argument("--emergency-stop-file", default=None, help="Create this file to block entries and flatten.")
    parser.add_argument("--state-path", default=None, help="JSON state file for restart/resume.")
    parser.add_argument("--no-resume", action="store_true", help="Ignore an existing state file on startup.")
    parser.add_argument("--no-persist-state", action="store_true", help="Do not write restart state.")
    parser.add_argument("--heartbeat-seconds", type=float, default=60.0, help="Print status this often; 0 disables.")
    parser.add_argument("--stop-after-bars", type=int, default=None, help="Stop after this many bars, useful for smoke tests.")
    parser.add_argument("--prop-guard", action="store_true", help="Enable live prop-firm rule guard and attempt ledger.")
    parser.add_argument("--prop-profile", default="traders_launch_100k_nyc", help="Profile name from RESEARCH_CONFIG['prop_firm_profiles'].")
    parser.add_argument("--prop-phase", choices=["eval", "funded"], default="eval", help="Apply eval or funded payout rules.")
    parser.add_argument("--prop-daily-profit-lock", type=float, default=0.0, help="Flatten/block entries after this daily profit.")
    parser.add_argument("--prop-daily-loss-stop", type=float, default=None, help="Override profile daily loss stop.")
    parser.add_argument("--prop-research-run-dir", default=None, help="Saved run folder for prop research gate. Defaults to results/latest.txt.")
    parser.add_argument("--require-prop-research-gate", action="store_true", help="Require saved WF prop and stress gates before starting.")
    parser.add_argument("--allow-unapproved-funded", action="store_true", help="Allow funded phase even if saved prop research gate fails.")
    parser.add_argument("--out-dir", default="results/paper_amp")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def build_params(args: argparse.Namespace) -> dict:
    params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG, **CANDIDATE_CONFIGS[args.candidate]}
    params["_candidate_name"] = args.candidate
    if args.strategy is not None:
        params["strategy_name"] = args.strategy
    return params


def run_label(args: argparse.Namespace, params: dict) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [
        timestamp,
        slugify(args.feed),
        slugify(args.broker),
        slugify(params.get("_candidate_name", "current")),
        slugify(params.get("strategy_name", "strategy")),
    ]
    return "_".join(parts)


def default_state_path(args: argparse.Namespace, params: dict, run_dir: Path) -> Path:
    if args.state_path:
        return Path(args.state_path)
    if args.feed == "replay":
        return run_dir / "state.json"
    candidate = slugify(params.get("_candidate_name", "current"))
    strategy = slugify(params.get("strategy_name", "strategy"))
    return Path(args.out_dir) / f"state_{candidate}_{strategy}.json"


def default_stop_path(args: argparse.Namespace, run_dir: Path) -> Path:
    if args.emergency_stop_file:
        return Path(args.emergency_stop_file)
    return run_dir / "STOP_TRADING"


def build_feed(args: argparse.Namespace):
    if args.feed == "replay":
        data_path = args.data_path or BACKTEST_CONFIG.get("data_path")
        if not data_path or not Path(data_path).exists():
            raise SystemExit(f"Data file not found: {data_path}")
        data = load_data(
            data_path,
            continuous_contract_method=BACKTEST_CONFIG.get("continuous_contract_method"),
            start=args.start,
            end=args.end,
        )
        if args.max_bars is not None:
            data = data.head(max(0, int(args.max_bars))).copy()
        if data.empty:
            raise SystemExit("No replay data after filtering.")
        print(f"Replay feed: {len(data):,} bars from {data['time'].min()} to {data['time'].max()}")
        return CsvReplayFeed(data, sleep_seconds=args.sleep)

    if args.feed == "tail":
        if not args.bar_file:
            raise SystemExit("--bar-file is required for --feed tail")
        print(f"Tail feed: {args.bar_file}")
        return FileTailBarFeed(
            args.bar_file,
            poll_seconds=args.poll_seconds,
            start_at_end=not args.tail_from_start,
        )

    config = CqgWebApiConfig.from_env(require_account=False)
    feed = CqgWebApiFeed(config)
    feed.check_ready()
    return feed


def build_order_bridge(args: argparse.Namespace, run_dir: Path) -> PaperEventOrderBridge:
    symbol = args.cqg_symbol or FUTURES_SPECS.get("symbol", "NQ")
    if args.broker == "none":
        broker = NullBroker()
    elif args.broker == "audit":
        broker = CsvOrderAuditBroker(run_dir / "orders_intended.csv")
    else:
        config = CqgWebApiConfig.from_env(require_account=True)
        broker = CqgWebApiBroker(config)
        symbol = args.cqg_symbol or config.contract_symbol
    return PaperEventOrderBridge(broker, symbol=str(symbol))


def build_prop_guard(args: argparse.Namespace, params: dict) -> LivePropRuleGuard | None:
    if not args.prop_guard:
        return None
    profiles = list(RESEARCH_CONFIG.get("prop_firm_profiles", []))
    profile = profile_by_name(profiles, str(args.prop_profile))
    return LivePropRuleGuard(
        LivePropRuleConfig(
            profile=profile,
            candidate=str(params.get("_candidate_name", args.candidate)),
            phase=str(args.prop_phase),
            daily_loss_stop=args.prop_daily_loss_stop,
            daily_profit_lock=float(args.prop_daily_profit_lock or 0.0),
        )
    )


def enforce_prop_research_gate(args: argparse.Namespace) -> int:
    needs_gate = bool(args.require_prop_research_gate)
    if args.prop_guard and args.prop_phase == "funded" and not args.allow_unapproved_funded:
        needs_gate = True
    if not needs_gate:
        return 0
    report = validate_prop_research_gate(args.prop_research_run_dir)
    print(report.summary())
    if report.passed:
        return 0
    if args.prop_guard and args.prop_phase == "funded" and args.allow_unapproved_funded:
        print("WARNING: funded phase is continuing despite failed prop research gate.")
        return 0
    print("Prop research gate failed; refusing funded/approved trading mode.")
    return 3


def print_event(event: PaperTradingEvent, order_text: str = "") -> None:
    price = "" if event.price is None else f" @{event.price:.2f}"
    contracts = "" if event.contracts is None else f" {event.contracts}x"
    pnl = "" if event.pnl is None else f" pnl=${event.pnl:,.2f}"
    reason = "" if not event.reason else f" reason={event.reason}"
    print(
        f"{event.timestamp} {event.event_type}{contracts} "
        f"{event.setup_tag or event.direction}{price}{pnl}{reason}{order_text}",
        flush=True,
    )


def main() -> int:
    args = parse_args()
    params = build_params(args)
    run_dir = Path(args.out_dir) / run_label(args, params)
    run_dir.mkdir(parents=True, exist_ok=True)
    state_path = default_state_path(args, params, run_dir)
    stop_path = default_stop_path(args, run_dir)

    gate_status = enforce_prop_research_gate(args)
    if gate_status != 0:
        return gate_status

    try:
        feed = build_feed(args)
        bridge = build_order_bridge(args, run_dir)
        bridge.connect()
    except CqgWebApiSetupError as exc:
        print(f"CQG setup is not ready: {exc}")
        return 2

    print(f"Candidate: {args.candidate}")
    print(f"Strategy:  {params.get('strategy_name')}")
    print(f"Broker:    {args.broker}")
    print(f"Run dir:   {run_dir}")
    print(f"State:     {state_path if not args.no_persist_state else 'disabled'}")
    print(f"Stop file: {stop_path}")
    prop_guard = build_prop_guard(args, params)
    if prop_guard is not None:
        print(f"Prop guard: {prop_guard.profile_name} phase={args.prop_phase}")
        if args.prop_phase == "eval":
            print("Prop mode: eval/paper guard only; this is not funded-cash approval.")
    if args.broker == "audit":
        print("Order mode: audit only. Intended orders are written to orders_intended.csv.")
    elif args.broker == "none":
        print("Order mode: local paper fills only.")

    engine = PaperTradingEngine(
        futures_specs=FUTURES_SPECS,
        strategy_params=params,
        config=PaperTradingConfig(
            starting_capital=float(BACKTEST_CONFIG["starting_capital"]),
            max_drawdown_pct=resolve_max_drawdown_pct(params),
            warmup_1m_bars=max(0, int(args.warmup_bars)),
            max_daily_loss_dollars=max(0.0, float(args.max_daily_loss or 0.0)),
            no_new_trades_after=args.no_new_trades_after,
            flatten_at=args.flatten_at,
            emergency_stop_path=str(stop_path),
            state_path=None if args.no_persist_state else str(state_path),
            persist_state=not args.no_persist_state,
            resume_state=not args.no_resume,
            prop_guard=prop_guard,
        ),
    )

    last_price: float | None = None
    processed_bars = 0
    last_heartbeat = 0.0
    previous_bar_time: pd.Timestamp | None = None
    missed_bars = 0
    max_bar_gap_seconds = 0.0
    runtime_status_rows: list[dict] = []
    try:
        for bar in feed:
            processed_bars += 1
            last_price = float(bar.close)
            bar_time = pd.Timestamp(bar.time)
            if previous_bar_time is not None:
                gap_seconds = max(0.0, (bar_time - previous_bar_time).total_seconds())
                max_bar_gap_seconds = max(max_bar_gap_seconds, gap_seconds)
                if gap_seconds > 90.0:
                    missed_bars += max(0, int(round(gap_seconds / 60.0)) - 1)
            previous_bar_time = bar_time
            events = engine.on_bar(bar)
            for event in events:
                order = bridge.handle_event(event)
                order_text = ""
                if order is not None:
                    order_text = f" -> {order.side} {order.quantity} {order.symbol}"
                if not args.quiet:
                    print_event(event, order_text)
            now = time.monotonic()
            runtime_status_rows.append(
                runtime_status_row(
                    engine,
                    timestamp=bar.time,
                    current_price=last_price,
                    processed_bars=processed_bars,
                    missed_bars=missed_bars,
                    max_bar_gap_seconds=max_bar_gap_seconds,
                    state_path=state_path,
                    persist_state=not args.no_persist_state,
                )
            )
            if args.heartbeat_seconds > 0 and now - last_heartbeat >= float(args.heartbeat_seconds):
                print_heartbeat(engine.status_snapshot(current_price=last_price, timestamp=bar.time))
                last_heartbeat = now
            if args.stop_after_bars is not None and processed_bars >= max(0, int(args.stop_after_bars)):
                print(f"Stopping after {processed_bars} processed bars.")
                break
    except KeyboardInterrupt:
        print("Stopping live paper runner.")
    finally:
        bridge.close()
        if not args.no_persist_state:
            engine.save_state(state_path)

    events = engine.event_log()
    trades = engine.trade_log()
    observations = engine.execution_observation_log()
    events_path = run_dir / "events.csv"
    trades_path = run_dir / "trades.csv"
    status_path = run_dir / "runtime_status.csv"
    events.to_csv(events_path, index=False)
    trades.to_csv(trades_path, index=False)
    pd.DataFrame(runtime_status_rows).to_csv(status_path, index=False)
    observation_paths = save_execution_observation_reports(observations, run_dir)
    prop_ledger_path = None
    if engine.prop_guard is not None:
        prop_ledger_path = run_dir / "prop_attempt_ledger.csv"
        engine.prop_guard.ledger_frame().to_csv(prop_ledger_path, index=False)

    mtm_equity = engine.mark_to_market_equity(last_price)
    closed_pnl = float(trades["pnl"].sum()) if not trades.empty else 0.0
    print("\nAMP paper runner stopped")
    print(f"Events:        {len(events)}")
    print(f"Closed trades: {len(trades)}")
    print(f"Closed P&L:    ${closed_pnl:,.2f}")
    print(f"MTM equity:    ${mtm_equity:,.2f}")
    print(f"Events CSV:    {events_path}")
    print(f"Trades CSV:    {trades_path}")
    print(f"Obs CSV:       {observation_paths['observations']}")
    print(f"Obs summary:   {observation_paths['summary']}")
    print(f"Status CSV:    {status_path}")
    if prop_ledger_path is not None:
        print(f"Prop ledger:   {prop_ledger_path}")
    return 0


def print_heartbeat(status: dict) -> None:
    ts = status.get("timestamp")
    price = status.get("last_price")
    equity = status.get("equity")
    daily = status.get("daily_pnl")
    position = "flat"
    if status.get("open_position"):
        position = (
            f"{status.get('open_contracts')}x {status.get('open_direction')} "
            f"@{float(status.get('open_entry_price')):.2f}"
        )
    daily_text = "n/a" if daily is None else f"${float(daily):,.2f}"
    price_text = "n/a" if price is None else f"{float(price):.2f}"
    equity_text = "n/a" if equity is None else f"${float(equity):,.2f}"
    print(
        f"[heartbeat] {ts} close={price_text} equity={equity_text} "
        f"daily_pnl={daily_text} position={position} "
        f"trades_today={status.get('trades_today')} stop={status.get('emergency_stop')}",
        flush=True,
    )
    prop_status = status.get("prop_guard")
    if prop_status:
        print(
            f"[prop] status={prop_status.get('status')} reason={prop_status.get('kill_reason')} "
            f"days={prop_status.get('day_count')} pnl=${float(prop_status.get('mtm_pnl', 0.0)):,.2f} "
            f"floor=${float(prop_status.get('drawdown_floor', 0.0)):,.2f} "
            f"payout_eligible={prop_status.get('payout_eligible')}",
            flush=True,
        )


def runtime_status_row(
    engine: PaperTradingEngine,
    *,
    timestamp,
    current_price: float | None,
    processed_bars: int,
    missed_bars: int,
    max_bar_gap_seconds: float,
    state_path: Path,
    persist_state: bool,
) -> dict:
    snapshot = engine.status_snapshot(current_price=current_price, timestamp=timestamp)
    ts = pd.Timestamp(timestamp)
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    bar_ts = ts.tz_localize(None) if ts.tzinfo is not None else ts
    latency_seconds = max(0.0, (now - bar_ts).total_seconds())
    row = {
        "timestamp": ts,
        "processed_bars": processed_bars,
        "missed_bars": missed_bars,
        "max_bar_gap_seconds": max_bar_gap_seconds,
        "latency_seconds": latency_seconds,
        "equity": snapshot.get("equity"),
        "daily_pnl": snapshot.get("daily_pnl"),
        "position_open": snapshot.get("open_position"),
        "closed_trades": snapshot.get("closed_trades"),
        "events": snapshot.get("events"),
        "state_path": str(state_path) if persist_state else "",
        "state_persisted": bool(persist_state and state_path.exists()),
    }
    prop = snapshot.get("prop_guard") or {}
    for key in (
        "profile",
        "phase",
        "status",
        "kill_reason",
        "day_count",
        "drawdown_floor",
        "consistency_ok",
        "target_reached",
        "payout_eligible",
        "gross_payout_available",
        "net_payout_after_split",
    ):
        row[f"prop_{key}"] = prop.get(key)
    return row


if __name__ == "__main__":
    raise SystemExit(main())
