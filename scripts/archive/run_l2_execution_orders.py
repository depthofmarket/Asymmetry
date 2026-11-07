#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.l2_execution_engine import (  # noqa: E402
    L2ExecutionConfig,
    read_l2_order_schedule,
    simulate_l2_execution,
    write_l2_execution_result,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay a scheduled order CSV against guarded L2 top-book event rows. "
            "This is an event-driven execution simulator, not the OHLCV strategy backtest."
        )
    )
    parser.add_argument("--topbook-events", required=True, help="CSV from build_l2_topbook_execution_stats.py.")
    parser.add_argument(
        "--orders-csv",
        required=True,
        help=(
            "Order schedule CSV with columns submit_time, side, quantity, order_type, "
            "limit_price, stop_price, time_in_force, post_only, tag."
        ),
    )
    parser.add_argument("--out-dir", default="results/research_master/l2_execution_orders")
    parser.add_argument("--prefix", default="l2_execution_orders")
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument("--contract-value", type=float, default=20.0)
    parser.add_argument("--latency", default="0ms")
    parser.add_argument(
        "--limit-fill-model",
        choices=["trade_through", "queue", "touch"],
        default="trade_through",
        help="Passive limit fill rule. trade_through is the conservative default.",
    )
    parser.add_argument("--queue-ahead-multiplier", type=float, default=1.0)
    parser.add_argument("--allow-full-depth-unknown-limits", action="store_true")
    parser.add_argument("--no-partial-fills", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    topbook = pd.read_csv(args.topbook_events)
    orders = read_l2_order_schedule(args.orders_csv)
    config = L2ExecutionConfig(
        tick_size=float(args.tick_size),
        contract_value=float(args.contract_value),
        latency=str(args.latency),
        allow_partial_fills=not bool(args.no_partial_fills),
        reject_non_topbook_limits=not bool(args.allow_full_depth_unknown_limits),
        limit_fill_model=args.limit_fill_model,
        queue_ahead_multiplier=float(args.queue_ahead_multiplier),
    )
    result = simulate_l2_execution(topbook, orders, config=config)
    paths = write_l2_execution_result(result, args.out_dir, prefix=args.prefix)
    print(result.summary.to_string(index=False))
    print(f"orders:  {paths['orders_csv']}")
    print(f"fills:   {paths['fills_csv']}")
    print(f"summary: {paths['summary_csv']}")
    print(f"report:  {paths['report_md']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
