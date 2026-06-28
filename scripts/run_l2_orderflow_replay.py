#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_execution_engine import L2ExecutionConfig  # noqa: E402
from backtest.l2_full_depth import L2FullDepthConfig, build_l2_full_depth_frame  # noqa: E402
from backtest.l2_mbp import decode_l2_mbp_sources, select_l2_parquet_sources  # noqa: E402
from backtest.l2_orderflow_replay import (  # noqa: E402
    L2OrderFlowReplayConfig,
    filter_l2_events_by_ny_window,
    load_l2_orderflow_strategy,
    run_l2_orderflow_replay,
    write_l2_orderflow_replay_result,
)
from backtest.l2_replay_protocol import (  # noqa: E402
    command_context_from_replay_args,
    export_l2_replay_protocol_report,
    verify_l2_replay_protocol,
)
from backtest.l2_source_resolver import decode_l2_source_selection, resolve_l2_source_index  # noqa: E402
from backtest.l2_topbook_execution import L2TopBookExecutionConfig, build_l2_topbook_frame  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an event-driven L2 orderflow replay in top-book or full-depth mode. "
            "This consumes guarded bid/ask events directly and is separate from the OHLCV bar backtest."
        )
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--topbook-events",
        help="CSV produced by build_l2_topbook_execution_stats.py, usually *_events.csv.",
    )
    input_group.add_argument("--source", help="CSV/parquet file, directory, or zip archive to decode before replay.")
    input_group.add_argument(
        "--source-index",
        help="l2_source_index.csv produced by scripts/build_l2_dataset_qa.py.",
    )
    parser.add_argument(
        "--member",
        action="append",
        default=[],
        help="Specific CSV/parquet member inside a zip, or relative file path inside a directory.",
    )
    parser.add_argument("--member-glob", default="*.parquet")
    parser.add_argument("--max-members", type=int, default=1)
    parser.add_argument(
        "--max-rows-per-member",
        type=int,
        default=200_000,
        help="Rows to decode per selected source member. Use 0 to decode the full selected member.",
    )
    parser.add_argument("--start-row-group", type=int, default=0)
    parser.add_argument(
        "--trade-date",
        action="append",
        default=[],
        help="YYYYMMDD date to load from --source-index. Repeat for multiple dates.",
    )
    parser.add_argument("--start-date", help="Inclusive YYYYMMDD range start for --source-index.")
    parser.add_argument("--end-date", help="Inclusive YYYYMMDD range end for --source-index.")
    parser.add_argument("--max-dates", type=int, help="Optional cap on resolved dates from --source-index.")
    parser.add_argument("--allow-missing-dates", action="store_true")
    parser.add_argument("--allow-duplicate-dates", action="store_true")

    parser.add_argument(
        "--strategy",
        default="noop",
        help=(
            "Strategy to run: noop, topbook_imbalance, tape_read_orderflow, bar_signal_csv, "
            "or module:function returning an object with on_event(event, context)."
        ),
    )
    parser.add_argument(
        "--strategy-kwargs",
        default="{}",
        help="JSON object passed to the strategy factory, for example '{\"threshold\": 0.8}'.",
    )

    parser.add_argument("--symbol", default="NQ_L2")
    parser.add_argument(
        "--execution-mode",
        choices=["topbook_only", "full_depth"],
        default="topbook_only",
        help="topbook_only uses bid/ask level 0 only; full_depth reconstructs displayed MBP depth.",
    )
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument("--contract-value", type=float, default=20.0)
    parser.add_argument("--policy", default="auto")
    parser.add_argument("--max-depth-levels", type=int, default=10)
    parser.add_argument("--coalesce-window", default="100ms")
    parser.add_argument("--max-spread-ticks", type=float, default=40.0)
    parser.add_argument("--trade-alignment-tolerance", default="5s")
    parser.add_argument("--include-unknown-side-trades", action="store_true")
    parser.add_argument(
        "--start-ny",
        default="",
        help="Optional inclusive New York replay start clock/timestamp, e.g. 09:30 or '2021-01-04 09:30'.",
    )
    parser.add_argument(
        "--end-ny",
        default="",
        help="Optional exclusive New York replay end clock/timestamp, e.g. 16:00 or '2021-01-04 16:00'.",
    )
    parser.add_argument("--replay-timezone", default="America/New_York")

    parser.add_argument("--latency", default="0ms")
    parser.add_argument(
        "--limit-fill-model",
        choices=["trade_through", "queue", "touch"],
        default="trade_through",
    )
    parser.add_argument("--queue-ahead-multiplier", type=float, default=1.0)
    parser.add_argument("--allow-full-depth-unknown-limits", action="store_true")
    parser.add_argument("--no-partial-fills", action="store_true")

    parser.add_argument(
        "--protocol-manifest",
        help="Optional L2 replay protocol manifest to validate against this command before execution.",
    )
    parser.add_argument(
        "--protocol-report-dir",
        default="",
        help="Optional directory where the protocol gate report should be written before replay.",
    )
    parser.add_argument("--out-dir", default="results/research_master/l2_orderflow_replay")
    parser.add_argument("--prefix", default="l2_orderflow_replay")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _check_protocol(args)
    topbook_events = _load_topbook_events(args)
    strategy_kwargs = _json_object(args.strategy_kwargs, arg_name="--strategy-kwargs")
    strategy = load_l2_orderflow_strategy(str(args.strategy), strategy_kwargs)
    execution_config = L2ExecutionConfig(
        tick_size=float(args.tick_size),
        contract_value=float(args.contract_value),
        latency=str(args.latency),
        allow_partial_fills=not bool(args.no_partial_fills),
        reject_non_topbook_limits=not (args.execution_mode == "full_depth" or bool(args.allow_full_depth_unknown_limits)),
        reject_unknown_depth_limits=True,
        taking_depth_levels=int(args.max_depth_levels) if args.execution_mode == "full_depth" else 1,
        passive_depth_levels=int(args.max_depth_levels) if args.execution_mode == "full_depth" else 1,
        limit_fill_model=args.limit_fill_model,
        queue_ahead_multiplier=float(args.queue_ahead_multiplier),
    )
    result = run_l2_orderflow_replay(
        topbook_events,
        strategy,
        config=L2OrderFlowReplayConfig(
            execution_config=execution_config,
            strategy_name=str(args.strategy),
            contract_value=float(args.contract_value),
        ),
    )
    paths = write_l2_orderflow_replay_result(result, args.out_dir, prefix=args.prefix)
    print(result.replay_summary.to_string(index=False))
    print(f"orders:          {paths['orders_csv']}")
    print(f"fills:           {paths['fills_csv']}")
    print(f"replay summary:  {paths['replay_summary_csv']}")
    print(f"strategy events: {paths['strategy_events_csv']}")
    print(f"report:          {paths['report_md']}")
    return 0


def _check_protocol(args: argparse.Namespace) -> None:
    if not args.protocol_manifest:
        return
    report = verify_l2_replay_protocol(
        args.protocol_manifest,
        command_context=command_context_from_replay_args(args),
    )
    if args.protocol_report_dir:
        paths = export_l2_replay_protocol_report(
            report,
            args.protocol_report_dir,
            prefix=f"{args.prefix}_protocol_gate",
        )
        print(f"protocol report: {paths.markdown_path}")
    if not report.passed:
        raise SystemExit(report.summary())


def _load_topbook_events(args: argparse.Namespace) -> pd.DataFrame:
    if args.topbook_events:
        events = pd.read_csv(args.topbook_events)
        if args.execution_mode == "full_depth":
            _require_full_depth_columns(events, source=args.topbook_events)
        return _filter_topbook_events(events, args)

    if args.source_index:
        selection = resolve_l2_source_index(
            args.source_index,
            trade_dates=args.trade_date,
            start_date=args.start_date,
            end_date=args.end_date,
            max_dates=args.max_dates,
            allow_missing_dates=bool(args.allow_missing_dates),
            allow_duplicate_dates=bool(args.allow_duplicate_dates),
            repo_root=REPO_ROOT,
        )
        if not selection.refs:
            raise SystemExit("No L2 sources were resolved from --source-index.")
        decoded = decode_l2_source_selection(
            selection,
            max_rows_per_source=int(args.max_rows_per_member),
            start_row=int(args.start_row_group),
        )
    else:
        refs = select_l2_parquet_sources(
            args.source,
            members=args.member,
            member_glob=args.member_glob,
            max_members=args.max_members,
        )
        if not refs:
            raise SystemExit(f"No CSV/parquet files selected from source: {args.source}")
        decoded = decode_l2_mbp_sources(
            refs,
            max_rows_per_source=int(args.max_rows_per_member),
            start_row_group=int(args.start_row_group),
        )
    if args.execution_mode == "full_depth":
        full_depth_config = L2FullDepthConfig(
            symbol=str(args.symbol),
            tick_size=float(args.tick_size),
            policy=str(args.policy),
            max_depth_levels=int(args.max_depth_levels),
            coalesce_window=str(args.coalesce_window),
            max_spread_ticks=float(args.max_spread_ticks),
            trade_alignment_tolerance=str(args.trade_alignment_tolerance),
            include_unknown_side_trades=bool(args.include_unknown_side_trades),
        )
        return _filter_topbook_events(build_l2_full_depth_frame(decoded.events, config=full_depth_config), args)

    topbook_config = L2TopBookExecutionConfig(
        symbol=str(args.symbol),
        tick_size=float(args.tick_size),
        policy=str(args.policy),
        coalesce_window=str(args.coalesce_window),
        max_spread_ticks=float(args.max_spread_ticks),
        trade_alignment_tolerance=str(args.trade_alignment_tolerance),
        include_unknown_side_trades=bool(args.include_unknown_side_trades),
    )
    return _filter_topbook_events(build_l2_topbook_frame(decoded.events, config=topbook_config), args)


def _filter_topbook_events(events: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    start_ny = str(getattr(args, "start_ny", "") or "").strip()
    end_ny = str(getattr(args, "end_ny", "") or "").strip()
    if not start_ny and not end_ny:
        return events
    filtered = filter_l2_events_by_ny_window(
        events,
        start_ny=start_ny,
        end_ny=end_ny,
        timezone=str(getattr(args, "replay_timezone", "America/New_York")),
    )
    print(
        f"NY replay window {start_ny or '*'} -> {end_ny or '*'} kept {len(filtered):,}/{len(events):,} events",
        flush=True,
    )
    if events.empty or not filtered.empty:
        return filtered
    raise SystemExit(
        "NY replay window selected 0 events. If you used --max-rows-per-member, increase it or pass "
        "--max-rows-per-member 0 so the RTH rows are loaded before filtering."
    )


def _require_full_depth_columns(events: pd.DataFrame, *, source: str) -> None:
    required = {"bid_px_00", "ask_px_00", "bid_sz_00", "ask_sz_00", "bid_px_01", "ask_px_01", "bid_sz_01", "ask_sz_01"}
    missing = sorted(required - set(events.columns))
    if missing:
        raise SystemExit(
            f"--execution-mode full_depth requires full-depth event columns in {source}; missing: {', '.join(missing)}"
        )


def _json_object(raw: str, *, arg_name: str) -> dict[str, object]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{arg_name} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{arg_name} must be a JSON object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
