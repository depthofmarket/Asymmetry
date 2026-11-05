#!/usr/bin/env python3
"""
Live Broker Fill & Slippage Reconciliation Tool
Allows instant synchronization between broker fills and the forward-test ledger.
Updates trade fills, commissions, realized PnL, cumulative account balance,
and automatically refreshes parity state JSON and the HTML dashboard.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from backtest.demo_parity_engine import (
    MAX_TRAILING_DRAWDOWN,
    STARTING_CAPITAL,
    TRAILING_FLOOR_LOCK,
    DemoParityJournal,
    resolve_instrument,
)


def reconcile_trade(
    trade_id: int,
    entry_fill: float | None = None,
    exit_fill: float | None = None,
    commission: float | None = None,
    contracts: int | None = None,
    entry_time: str | None = None,
    exit_time: str | None = None,
    notes: str | None = None,
    dry_run: bool = False,
) -> dict[str, any]:
    """Reconciles a recorded trade with real broker execution values."""
    journal = DemoParityJournal()
    df_trades = journal.load_trades_df()
    df_sessions = journal.load_sessions_df()

    if df_trades.empty:
        raise ValueError("demo_trades_ledger.csv is empty; no trades to reconcile.")

    if trade_id not in df_trades["trade_id"].values:
        available_ids = df_trades["trade_id"].tolist()
        raise ValueError(f"Trade ID {trade_id} not found in trades ledger. Available IDs: {available_ids}")

    idx = df_trades[df_trades["trade_id"] == trade_id].index[0]
    row = df_trades.loc[idx].copy()

    sym = str(row["symbol"]).upper()
    spec = resolve_instrument(sym)
    direction = str(row["direction"]).upper()

    before_entry = float(row["actual_entry_fill"])
    before_exit = float(row["actual_exit_fill"])
    before_comm = float(row["commission"])
    before_net = float(row["net_pnl"])
    before_balance = float(row["account_balance_after"])

    # Update fields if provided
    new_entry = float(entry_fill) if entry_fill is not None else before_entry
    new_exit = float(exit_fill) if exit_fill is not None else before_exit
    new_contracts = int(contracts) if contracts is not None else int(row["contracts"])
    new_comm = float(commission) if commission is not None else before_comm
    new_entry_time = str(entry_time) if entry_time is not None else str(row["actual_entry_time"])
    new_exit_time = str(exit_time) if exit_time is not None else str(row["actual_exit_time"])

    # Theoretical values
    theo_entry = float(row["theo_entry_price"])
    theo_exit = float(row["theo_exit_price"])
    theo_net = float(row["theo_net_pnl"])

    # Recalculate Slippage
    if direction == "LONG":
        entry_slip_pts = round(new_entry - theo_entry, 4)
        exit_slip_pts = round(theo_exit - new_exit, 4)
        realized_pts = round(new_exit - new_entry, 4)
    else:
        entry_slip_pts = round(theo_entry - new_entry, 4)
        exit_slip_pts = round(new_exit - theo_exit, 4)
        realized_pts = round(new_entry - new_exit, 4)

    entry_slip_ticks = round(entry_slip_pts / spec.tick_size, 2)
    entry_slip_dollars = round(entry_slip_pts * spec.point_value * new_contracts, 2)
    exit_slip_ticks = round(exit_slip_pts / spec.tick_size, 2)
    exit_slip_dollars = round(exit_slip_pts * spec.point_value * new_contracts, 2)
    total_slip_dollars = round(entry_slip_dollars + exit_slip_dollars, 2)

    gross_pnl = round(realized_pts * spec.point_value * new_contracts, 2)
    net_pnl = round(gross_pnl - new_comm, 2)
    exec_drag = round(net_pnl - theo_net, 2)

    new_notes = str(row["notes"])
    reconciled_note = f"Reconciled via CLI at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    if notes:
        new_notes = f"{new_notes} | {notes} ({reconciled_note})"
    else:
        new_notes = f"{new_notes} | {reconciled_note}"

    # Apply updates to row
    df_trades.at[idx, "actual_entry_fill"] = new_entry
    df_trades.at[idx, "actual_exit_fill"] = new_exit
    df_trades.at[idx, "contracts"] = new_contracts
    df_trades.at[idx, "commission"] = new_comm
    df_trades.at[idx, "actual_entry_time"] = new_entry_time
    df_trades.at[idx, "actual_exit_time"] = new_exit_time
    df_trades.at[idx, "entry_slippage_pts"] = entry_slip_pts
    df_trades.at[idx, "entry_slippage_ticks"] = entry_slip_ticks
    df_trades.at[idx, "entry_slippage_dollars"] = entry_slip_dollars
    df_trades.at[idx, "exit_slippage_pts"] = exit_slip_pts
    df_trades.at[idx, "exit_slippage_ticks"] = exit_slip_ticks
    df_trades.at[idx, "exit_slippage_dollars"] = exit_slip_dollars
    df_trades.at[idx, "total_slippage_dollars"] = total_slip_dollars
    df_trades.at[idx, "realized_points"] = realized_pts
    df_trades.at[idx, "gross_pnl"] = gross_pnl
    df_trades.at[idx, "net_pnl"] = net_pnl
    df_trades.at[idx, "execution_drag_dollars"] = exec_drag
    df_trades.at[idx, "notes"] = new_notes

    # Recompute running account balances across ALL trades in sequential order
    running_balance = STARTING_CAPITAL
    running_peak = STARTING_CAPITAL
    running_floor = STARTING_CAPITAL - MAX_TRAILING_DRAWDOWN

    for i in range(len(df_trades)):
        t_net = float(df_trades.at[i, "net_pnl"])
        running_balance = round(running_balance + t_net, 2)
        if running_balance > running_peak:
            running_peak = running_balance
            running_floor = min(TRAILING_FLOOR_LOCK, running_peak - MAX_TRAILING_DRAWDOWN)
        df_trades.at[i, "account_balance_after"] = running_balance
        df_trades.at[i, "peak_balance_after"] = running_peak
        df_trades.at[i, "trailing_floor_after"] = running_floor

    # Update corresponding daily session in df_sessions
    trade_date = str(row["date"])
    if not df_sessions.empty and trade_date in df_sessions["date"].astype(str).values:
        s_idx = df_sessions[df_sessions["date"].astype(str) == trade_date].index[0]
        # Sum all trades for that date
        day_trades = df_trades[df_trades["date"].astype(str) == trade_date]
        day_net = round(day_trades["net_pnl"].sum(), 2)
        day_end_bal = float(day_trades.iloc[-1]["account_balance_after"])
        df_sessions.at[s_idx, "day_net_pnl"] = day_net
        df_sessions.at[s_idx, "end_of_day_balance"] = day_end_bal

    # Cascade updated balance through all subsequent session end_of_day_balance rows
    if not df_sessions.empty:
        curr_b = STARTING_CAPITAL
        for s_i in range(len(df_sessions)):
            s_d = str(df_sessions.at[s_i, "date"])
            t_on_day = df_trades[df_trades["date"].astype(str) == s_d]
            if not t_on_day.empty:
                curr_b = float(t_on_day.iloc[-1]["account_balance_after"])
            df_sessions.at[s_i, "end_of_day_balance"] = curr_b

    after_balance = float(df_trades.loc[idx, "account_balance_after"])
    diff_balance = round(after_balance - before_balance, 2)

    summary = {
        "trade_id": trade_id,
        "symbol": sym,
        "direction": direction,
        "contracts": new_contracts,
        "before": {
            "entry_fill": before_entry,
            "exit_fill": before_exit,
            "commission": before_comm,
            "net_pnl": before_net,
            "account_balance": before_balance,
        },
        "after": {
            "entry_fill": new_entry,
            "exit_fill": new_exit,
            "commission": new_comm,
            "net_pnl": net_pnl,
            "account_balance": after_balance,
        },
        "delta_pnl": round(net_pnl - before_net, 2),
        "delta_balance": diff_balance,
        "dry_run": dry_run,
    }

    if not dry_run:
        df_trades.to_csv(journal.trades_ledger_path, index=False)
        df_sessions.to_csv(journal.sessions_ledger_path, index=False)
        new_state = journal.get_eval_state()
        journal.save_state_json(new_state)
        journal.generate_html_dashboard()

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile a demo/forward-test trade with live broker fills.")
    parser.add_argument("--trade-id", type=int, required=True, help="Trade ID to reconcile (e.g. 1).")
    parser.add_argument("--entry-fill", "--entry-price", type=float, default=None, help="Actual broker entry fill price.")
    parser.add_argument("--exit-fill", "--exit-price", type=float, default=None, help="Actual broker exit fill price.")
    parser.add_argument("--commission", type=float, default=None, help="Actual total round-turn commission ($).")
    parser.add_argument("--contracts", type=int, default=None, help="Number of contracts filled.")
    parser.add_argument("--entry-time", type=str, default=None, help="Actual fill entry time (HH:MM:SS).")
    parser.add_argument("--exit-time", type=str, default=None, help="Actual fill exit time (HH:MM:SS).")
    parser.add_argument("--notes", type=str, default=None, help="Reconciliation note to append.")
    parser.add_argument("--dry-run", action="store_true", help="Preview calculations without writing to files.")
    args = parser.parse_args()

    try:
        res = reconcile_trade(
            trade_id=args.trade_id,
            entry_fill=args.entry_fill,
            exit_fill=args.exit_fill,
            commission=args.commission,
            contracts=args.contracts,
            entry_time=args.entry_time,
            exit_time=args.exit_time,
            notes=args.notes,
            dry_run=args.dry_run,
        )

        b = res["before"]
        a = res["after"]
        mode_str = "🔍 PREVIEW (DRY-RUN - NO CHANGES SAVED)" if args.dry_run else "✅ TRADE RECONCILED & PERSISTED"

        print("=" * 72)
        print(f" {mode_str}")
        print("=" * 72)
        print(f" Trade ID    : {res['trade_id']} ({res['direction']} {res['contracts']}x {res['symbol']})")
        print("-" * 72)
        print(f" Field                  Before              After               Delta")
        print(f" Entry Fill           : {b['entry_fill']:<18.2f} {a['entry_fill']:<18.2f} {a['entry_fill'] - b['entry_fill']:+.2f}")
        print(f" Exit Fill            : {b['exit_fill']:<18.2f} {a['exit_fill']:<18.2f} {a['exit_fill'] - b['exit_fill']:+.2f}")
        print(f" Commission           : ${b['commission']:<17.2f} ${a['commission']:<17.2f} ${a['commission'] - b['commission']:+.2f}")
        print(f" Net PnL              : ${b['net_pnl']:<17.2f} ${a['net_pnl']:<17.2f} ${res['delta_pnl']:+.2f}")
        print(f" Account Balance      : ${b['account_balance']:<17.2f} ${a['account_balance']:<17.2f} ${res['delta_balance']:+.2f}")
        print("=" * 72)
        if not args.dry_run:
            print(" 🟢 Ledgers, parity state JSON, and HTML dashboard successfully resynced.")
        print("=" * 72)
        return 0

    except Exception as e:
        print(f"❌ Reconciliation failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
