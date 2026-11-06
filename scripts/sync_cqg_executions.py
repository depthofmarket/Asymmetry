#!/usr/bin/env python3
"""
CQG Broker Execution Synchronizer & Real-Time Trade Log Constructor
Directly ingests MotiveWave's persistent CQG WebAPI audit journal:
  /Users/novo/Library/MotiveWave/workspaces/Mota/config/journal.csv
and reconstructs real broker fills, calculates execution drag, matches theoretical orders,
and synchronizes with the LucidFlex 25K demo parity ledger (results/forward_test/demo_trades_ledger.csv).

Modes:
  --list           : Display reconstructed broker trades in a terminal table.
  --sync           : Reconstruct trades and append/update results/forward_test/demo_trades_ledger.csv.
  --watch          : Real-time daemon watching journal.csv for new broker fills.
  --since <date>   : Filter executions on or after YYYY-MM-DD (default: 2026-10-27).
  --date <date>    : Filter executions for a specific date.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from backtest.demo_parity_engine import (
    DAILY_SOFT_STOP_DOLLARS,
    FORWARD_TEST_DIR,
    MAX_TRAILING_DRAWDOWN,
    PROFIT_TARGET_DOLLARS,
    STARTING_CAPITAL,
    TARGET_BALANCE,
    TRAILING_FLOOR_LOCK,
    AccountEvalState,
    DailySessionRecord,
    DemoParityJournal,
    TradeFillRecord,
    resolve_instrument,
)

ET_TZ = ZoneInfo("America/New_York")
DEFAULT_JOURNAL_PATH = Path(
    os.path.expanduser("~/Library/MotiveWave/workspaces/Mota/config/journal.csv")
)


@dataclass
class CQGFillEvent:
    timestamp_ms: int
    dt_et: datetime
    date_str: str
    time_str: str
    raw_symbol: str
    clean_symbol: str
    account_id: str
    order_id: str
    parent_id: str
    order_type: str
    side: str  # BUY or SELL
    qty: int
    fill_price: float
    message: str


@dataclass
class ReconstructedBrokerTrade:
    trade_key: str
    date: str
    symbol: str
    direction: str  # LONG or SHORT
    contracts: int
    entry_time: str
    exit_time: str
    entry_fill: float
    exit_fill: float
    points: float
    gross_pnl: float
    commission: float
    net_pnl: float
    exit_type: str
    strategy: str
    entry_order_id: str
    exit_order_id: str
    account_id: str
    notes: str


def normalize_cqg_symbol(raw_sym: str) -> str:
    """Extract standard base symbol (e.g. MESZ26.CQG -> MES, MNQZ26.CQG -> MNQ, MGCZ26.CQG -> MGC)."""
    s = raw_sym.strip().upper().split(".")[0]
    if s.startswith("MES"):
        return "MES"
    if s.startswith("MNQ"):
        return "MNQ"
    if s.startswith("MGC"):
        return "MGC"
    if s.startswith("ENQ"):
        return "NQ"  # Full-size or mapped NQ
    if s.startswith("NQ"):
        return "NQ"
    if s.startswith("ES"):
        return "ES"
    if s.startswith("GC"):
        return "GC"
    return s[:3]


def infer_strategy_from_window(time_str: str, sym: str) -> str:
    """Infers the systematic strategy based on execution window and symbol."""
    hhmm = time_str[:5]
    if sym in ("MNQ", "NQ"):
        if "08:30" <= hhmm <= "09:25":
            return "Macro Momentum (08:35)"
        elif "09:44" <= hhmm <= "10:15":
            return "VA Breakout (v2.0)"
    elif sym in ("MES", "ES"):
        if "09:44" <= hhmm <= "10:15":
            return "VA Breakout (v2.0)"
    elif sym in ("MGC", "GC"):
        if "10:14" <= hhmm <= "11:00":
            return "Gold London Fix (H14)"
    return "Discretionary / Manual Scalp"


def infer_exit_type(order_type: str, exit_time_str: str) -> str:
    """Infers exit type from closing order type and execution time."""
    hhmm = exit_time_str[:5]
    if order_type == "STP":
        return "STOP_LOSS"
    if order_type == "LMT":
        return "PROFIT_TARGET"
    if hhmm in ("10:15", "10:16"):
        return "TIME_EXIT_1015"
    if hhmm in ("11:00", "11:01"):
        return "TIME_EXIT_1100"
    if hhmm in ("09:25", "09:26"):
        return "TIME_EXIT_0925"
    return "MARKET_EXIT"


def parse_cqg_fills_from_journal(
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    min_date: str | None = None,
    exact_date: str | None = None,
    authorized_accounts: set[str] | None = None,
    allowed_symbols: set[str] | None = None,
) -> list[CQGFillEvent]:
    """Reads journal.csv and extracts all ORDER_FILLED events."""
    if not journal_path.exists():
        raise FileNotFoundError(f"MotiveWave CQG journal not found at: {journal_path}")

    fills: list[CQGFillEvent] = []
    with open(journal_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        try:
            next(reader)  # Header
        except StopIteration:
            return []

        for row in reader:
            if len(row) < 20:
                continue
            # Col 1: Type ('ORDER'), Col 2: Action ('ORDER_FILLED')
            record_type = row[1].strip()
            action = row[2].strip()
            if record_type != "ORDER" or action != "ORDER_FILLED":
                continue

            ts_ms_str = row[20].strip() if len(row) > 20 and row[20].strip() else row[0].strip()
            try:
                ts_ms = int(ts_ms_str)
            except ValueError:
                continue

            dt_et = datetime.fromtimestamp(ts_ms / 1000.0, tz=ET_TZ)
            date_str = dt_et.strftime("%Y-%m-%d")
            time_str = dt_et.strftime("%H:%M:%S")

            if exact_date and date_str != exact_date:
                continue
            if min_date and date_str < min_date:
                continue

            raw_sym = row[5].strip()
            clean_sym = normalize_cqg_symbol(raw_sym)
            if allowed_symbols and clean_sym not in allowed_symbols and raw_sym not in allowed_symbols:
                continue
            acct_id = row[6].strip()

            if authorized_accounts and acct_id not in authorized_accounts:
                continue

            ord_id = row[7].strip()
            parent_id = row[21].strip() if len(row) > 21 else ""
            otype = row[11].strip()
            side = row[12].strip().upper()

            # Qty: Col 17 is filled qty, col 15 is total order qty
            qty_str = row[17].strip() if row[17].strip() else (row[15].strip() if row[15].strip() else "1")
            try:
                qty = int(float(qty_str))
            except ValueError:
                qty = 1

            # Fill price: Col 19
            price_str = row[19].strip() if row[19].strip() else (row[14].strip() if row[14].strip() else "0")
            try:
                fill_price = float(price_str)
            except ValueError:
                continue

            msg = row[4].strip()

            fills.append(
                CQGFillEvent(
                    timestamp_ms=ts_ms,
                    dt_et=dt_et,
                    date_str=date_str,
                    time_str=time_str,
                    raw_symbol=raw_sym,
                    clean_symbol=clean_sym,
                    account_id=acct_id,
                    order_id=ord_id,
                    parent_id=parent_id,
                    order_type=otype,
                    side=side,
                    qty=qty,
                    fill_price=fill_price,
                    message=msg,
                )
            )

    # Sort fills chronologically
    fills.sort(key=lambda x: x.timestamp_ms)
    return fills


def reconstruct_trades_fifo(fills: list[CQGFillEvent]) -> list[ReconstructedBrokerTrade]:
    """
    Pairs raw fill events into closed round-turn trades using FIFO lot matching.
    Handles partial fills, multi-lot positions, and direction reversals.
    """
    trades: list[ReconstructedBrokerTrade] = []
    open_lots: dict[str, deque[CQGFillEvent]] = defaultdict(deque)

    for f in fills:
        sym = f.clean_symbol
        q = open_lots[sym]
        rem_qty = f.qty

        while rem_qty > 0 and q:
            top = q[0]
            if top.side == f.side:
                # Same direction: add to inventory
                break
            else:
                # Opposite direction: match and close lot
                matched_qty = min(top.qty, rem_qty)
                direction = "LONG" if top.side == "BUY" else "SHORT"
                entry_fill = top.fill_price
                exit_fill = f.fill_price

                pts = (exit_fill - entry_fill) if direction == "LONG" else (entry_fill - exit_fill)
                spec = resolve_instrument(sym)
                gross = round(pts * spec.point_value * matched_qty, 2)
                comm = round(spec.default_commission_rt * matched_qty, 2)
                net = round(gross - comm, 2)

                strat = infer_strategy_from_window(top.time_str, sym)
                etype = infer_exit_type(f.order_type, f.time_str)
                t_key = f"{top.date_str}_{sym}_{top.time_str}_{f.time_str}_{top.order_id}"

                trades.append(
                    ReconstructedBrokerTrade(
                        trade_key=t_key,
                        date=top.date_str,
                        symbol=sym,
                        direction=direction,
                        contracts=matched_qty,
                        entry_time=top.time_str,
                        exit_time=f.time_str,
                        entry_fill=entry_fill,
                        exit_fill=exit_fill,
                        points=round(pts, 4),
                        gross_pnl=gross,
                        commission=comm,
                        net_pnl=net,
                        exit_type=etype,
                        strategy=strat,
                        entry_order_id=top.order_id,
                        exit_order_id=f.order_id,
                        account_id=f.account_id or top.account_id,
                        notes=f"Reconstructed from CQG journal (Entry ID: {top.order_id}, Exit ID: {f.order_id})",
                    )
                )

                top.qty -= matched_qty
                rem_qty -= matched_qty
                if top.qty <= 0:
                    q.popleft()

        if rem_qty > 0:
            # New open inventory
            open_item = CQGFillEvent(
                timestamp_ms=f.timestamp_ms,
                dt_et=f.dt_et,
                date_str=f.date_str,
                time_str=f.time_str,
                raw_symbol=f.raw_symbol,
                clean_symbol=f.clean_symbol,
                account_id=f.account_id,
                order_id=f.order_id,
                parent_id=f.parent_id,
                order_type=f.order_type,
                side=f.side,
                qty=rem_qty,
                fill_price=f.fill_price,
                message=f.message,
            )
            q.append(open_item)

    return trades


def sync_broker_trades_to_ledger(
    reconstructed_trades: list[ReconstructedBrokerTrade],
    journal: DemoParityJournal | None = None,
    dry_run: bool = False,
    require_model_approval: bool = True,
) -> int:
    """
    Syncs reconstructed broker trades into results/forward_test/demo_trades_ledger.csv.
    Performs deduplication against existing trade entries.
    Enforces Rule 1 & Rule 2: Excludes trades that were mathematically GATED by the strategy model
    (unless require_model_approval=False).
    Returns count of newly synced trades.
    """
    if journal is None:
        journal = DemoParityJournal()

    df_existing = journal.load_trades_df()
    df_win = journal.load_windows_df()
    synced_count = 0

    for t in reconstructed_trades:
        # Check if trade was mathematically gated by the strategy model for that window
        if require_model_approval and not df_win.empty:
            w_match = df_win[
                (df_win["date"].astype(str) == t.date)
                & (df_win["symbol"].astype(str) == t.symbol)
            ]
            if not w_match.empty:
                w_row = w_match.iloc[-1]
                w_status = str(w_row.get("status", ""))
                if w_status != "TRADE_FIRED":
                    diag = str(w_row.get("diagnostic_reason", ""))
                    print(
                        f"⚠️  [MODEL GATE VIOLATION] Skipping {t.date} {t.symbol} {t.direction} ({t.strategy}):\n"
                        f"    Broker executed fill @ {t.entry_fill:.2f}, but strategy model explicitly GATED setup:\n"
                        f"    '{diag}'\n"
                        f"    Excluded from systematic baseline to prevent selection bias."
                    )
                    continue

        # Check if trade already exists
        is_duplicate = False
        if not df_existing.empty:
            match_mask = (
                (df_existing["date"].astype(str) == t.date)
                & (df_existing["symbol"].astype(str) == t.symbol)
                & (df_existing["direction"].astype(str) == t.direction)
            )
            if match_mask.any():
                subset = df_existing[match_mask]
                for _, existing_row in subset.iterrows():
                    # Match on entry time or fill price proximity
                    exist_entry_time = str(existing_row["actual_entry_time"])
                    exist_entry_fill = float(existing_row["actual_entry_fill"])
                    exist_exit_fill = float(existing_row["actual_exit_fill"])
                    if (
                        exist_entry_time[:5] == t.entry_time[:5]
                        or abs(exist_entry_fill - t.entry_fill) < 0.01
                    ) and abs(exist_exit_fill - t.exit_fill) < 0.01:
                        is_duplicate = True
                        break

        if is_duplicate:
            continue

        synced_count += 1
        if dry_run:
            print(
                f"[DRY-RUN SYNC] Would record: {t.date} {t.symbol} {t.direction} {t.contracts}x "
                f"@ {t.entry_fill:.2f} -> {t.exit_fill:.2f} | Net: ${t.net_pnl:+,.2f} ({t.strategy})"
            )
            continue

        # Look up if theoretical signal existed for this window/symbol in windows ledger
        df_win = journal.load_windows_df()
        theo_entry = t.entry_fill
        theo_stop = None
        theo_target = None
        theo_entry_time = t.entry_time
        theo_exit_time = t.exit_time

        if not df_win.empty:
            w_match = df_win[
                (df_win["date"].astype(str) == t.date)
                & (df_win["symbol"].astype(str) == t.symbol)
            ]
            if not w_match.empty:
                w_row = w_match.iloc[-1]
                if pd.notna(w_row.get("entry_price")) and float(w_row["entry_price"]) > 0:
                    theo_entry = float(w_row["entry_price"])
                    theo_stop = float(w_row["stop_price"]) if pd.notna(w_row.get("stop_price")) else None
                    theo_target = float(w_row["target_price"]) if pd.notna(w_row.get("target_price")) else None
                    theo_entry_time = str(w_row["window_time"])

        fill_rec = TradeFillRecord(
            date=t.date,
            symbol=t.symbol,
            direction=t.direction,
            contracts=t.contracts,
            theo_entry_price=theo_entry,
            actual_entry_fill=t.entry_fill,
            theo_stop_price=theo_stop,
            theo_target_price=theo_target,
            exit_type=t.exit_type,
            actual_exit_fill=t.exit_fill,
            strategy=t.strategy,
            theo_entry_time=theo_entry_time,
            actual_entry_time=t.entry_time,
            theo_exit_time=theo_exit_time,
            actual_exit_time=t.exit_time,
            notes=f"{t.notes} [Account: {t.account_id}]",
        )

        new_state = journal.record_trade(fill_rec)
        print(
            f"[SYNCED TO LEDGER] Trade #{fill_rec.trade_id}: {t.date} {t.symbol} {t.direction} {t.contracts}x "
            f"@ {t.entry_fill:.2f} -> {t.exit_fill:.2f} | Net: ${fill_rec.net_pnl:+,.2f} | "
            f"Account: ${new_state.balance:,.2f} (Floor: ${new_state.trailing_floor:,.2f})"
        )

        # Update session ledger for that day to show setup_fired=True
        df_sess = journal.load_sessions_df()
        if not df_sess.empty and t.date in df_sess["date"].astype(str).values:
            idx = df_sess[df_sess["date"].astype(str) == t.date].index[0]
            df_sess.at[idx, "setup_fired"] = True
            curr_trades = int(df_sess.at[idx, "trades_count"]) if pd.notna(df_sess.at[idx, "trades_count"]) else 0
            df_sess.at[idx, "trades_count"] = curr_trades + 1
            curr_pnl = float(df_sess.at[idx, "day_net_pnl"]) if pd.notna(df_sess.at[idx, "day_net_pnl"]) else 0.0
            df_sess.at[idx, "day_net_pnl"] = round(curr_pnl + fill_rec.net_pnl, 2)
            df_sess.at[idx, "end_of_day_balance"] = new_state.balance
            df_sess.at[idx, "notes"] = f"Real CQG Fill Synced ({t.symbol} {t.direction} {fill_rec.net_pnl:+,.2f})"
            df_sess.to_csv(journal.sessions_ledger_path, index=False)

        # Refresh existing dataframe reference
        df_existing = journal.load_trades_df()

    if not dry_run:
        # Reconcile session ledger against all recorded trades in demo_trades_ledger
        df_trades_all = journal.load_trades_df()
        df_sess = journal.load_sessions_df()
        if not df_trades_all.empty and not df_sess.empty:
            for s_date, grp in df_trades_all.groupby("date"):
                s_date_str = str(s_date)
                if s_date_str in df_sess["date"].astype(str).values:
                    idx = df_sess[df_sess["date"].astype(str) == s_date_str].index[0]
                    df_sess.at[idx, "setup_fired"] = True
                    df_sess.at[idx, "trades_count"] = int(len(grp))
                    df_sess.at[idx, "day_net_pnl"] = round(float(grp["net_pnl"].sum()), 2)
                    df_sess.at[idx, "end_of_day_balance"] = round(float(grp["account_balance_after"].iloc[-1]), 2)
                    df_sess.at[idx, "notes"] = f"Real CQG Broker Executions Synced ({len(grp)} trades | PnL: ${grp['net_pnl'].sum():+,.2f})"
            df_sess.to_csv(journal.sessions_ledger_path, index=False)

        # Refresh state JSON and regenerate dashboard HTML
        st = journal.get_eval_state()
        journal.save_state_json(st)
        journal.generate_html_dashboard()

    return synced_count


def watch_cqg_journal(
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    poll_interval_sec: float = 2.0,
    min_date: str | None = None,
) -> None:
    """Tails journal.csv in real time, detecting new fills and syncing immediately."""
    print(f"👀 [WATCH MODE] Monitoring MotiveWave CQG Journal at:\n    {journal_path}")
    print(f"    Polling every {poll_interval_sec}s. Press Ctrl+C to stop.\n")

    journal = DemoParityJournal()
    last_processed_ts = int(time.time() * 1000)

    try:
        while True:
            if journal_path.exists():
                fills = parse_cqg_fills_from_journal(journal_path, min_date=min_date)
                new_fills = [f for f in fills if f.timestamp_ms > last_processed_ts]
                if new_fills:
                    for nf in new_fills:
                        print(
                            f"\n⚡ [NEW FILL DETECTED] {nf.time_str} ET | {nf.clean_symbol} {nf.side} "
                            f"{nf.qty}x @ {nf.fill_price:.2f} ({nf.order_type}) [ID: {nf.order_id}]"
                        )
                        # Announce fill via macOS notifications
                        try:
                            msg = f"{nf.side} {nf.qty} {nf.clean_symbol} filled @ {nf.fill_price:.2f}"
                            subprocess.run(
                                [
                                    "osascript",
                                    "-e",
                                    f'display notification "{msg}" with title "MotiveWave CQG Fill" sound name "Glass"',
                                ],
                                check=False,
                                timeout=5,
                            )
                        except Exception:
                            pass

                    # Reconstruct all trades and sync
                    reconstructed = reconstruct_trades_fifo(fills)
                    synced = sync_broker_trades_to_ledger(reconstructed, journal=journal)
                    if synced > 0:
                        print(f"✅ Auto-synced {synced} completed broker trade(s) to ledger.")

                    last_processed_ts = max(f.timestamp_ms for f in new_fills)

            time.sleep(poll_interval_sec)
    except KeyboardInterrupt:
        print("\n[WATCH MODE STOPPED] Exiting smoothly.")


def main() -> None:
    parser = argparse.ArgumentParser(description="MotiveWave CQG Execution Synchronizer & Parity Logger")
    parser.add_argument(
        "--journal-path",
        type=Path,
        default=DEFAULT_JOURNAL_PATH,
        help="Path to MotiveWave journal.csv",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all reconstructed broker trades",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Sync reconstructed broker trades into demo_trades_ledger.csv",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Real-time file-watch mode tailing journal.csv for new fills",
    )
    parser.add_argument(
        "--since",
        type=str,
        default="2026-10-27",
        help="Filter executions on or after YYYY-MM-DD (default: 2026-10-27)",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated list of symbols to filter (e.g. MES,MNQ,MGC)",
    )
    parser.add_argument(
        "--systematic-only",
        action="store_true",
        help="Filter only systematic ensemble strategy executions (excludes manual/discretionary scalps)",
    )
    parser.add_argument(
        "--include-gated",
        action="store_true",
        help="Include broker executions even if the strategy model explicitly gated the setup (defaults to false to prevent selection bias)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Filter executions for a specific date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate sync without modifying ledger files",
    )
    args = parser.parse_args()

    if args.watch:
        watch_cqg_journal(
            journal_path=args.journal_path,
            min_date=args.since if not args.date else args.date,
        )
        return

    allowed_syms = set(args.symbols.split(",")) if args.symbols else None
    fills = parse_cqg_fills_from_journal(
        journal_path=args.journal_path,
        min_date=args.since if not args.date else None,
        exact_date=args.date,
        allowed_symbols=allowed_syms,
    )
    reconstructed = reconstruct_trades_fifo(fills)
    if args.systematic_only:
        reconstructed = [t for t in reconstructed if "Discretionary" not in t.strategy]

    # Print summary header
    filter_label = f"Date: {args.date}" if args.date else f"Since: {args.since}"
    print("=" * 110)
    print(f"🎯 MOTIVEWAVE CQG BROKER EXECUTION AUDIT ({filter_label})")
    print(f"   Journal Path : {args.journal_path}")
    print(f"   Raw Fills    : {len(fills)} fill events")
    print(f"   Round-Turns  : {len(reconstructed)} reconstructed trades")
    print("=" * 110)

    if not reconstructed:
        print("No broker trades found for the specified period.")
        return

    # Print table of reconstructed trades
    header = (
        f"{'Date':10} | {'Window':17} | {'Symbol':6} | {'Dir':5} | {'Qty':3} | "
        f"{'Entry Fill':10} | {'Exit Fill':10} | {'Pts':>7} | {'Net PnL':>10} | {'Strategy':24}"
    )
    print(header)
    print("-" * 110)
    total_net = 0.0
    for t in reconstructed:
        total_net += t.net_pnl
        win_str = f"{t.entry_time[:5]}-{t.exit_time[:5]}"
        print(
            f"{t.date:10} | {win_str:17} | {t.symbol:6} | {t.direction:5} | {t.contracts:3} | "
            f"{t.entry_fill:10.2f} | {t.exit_fill:10.2f} | {t.points:+7.2f} | ${t.net_pnl:>9.2f} | {t.strategy:24}"
        )
    print("-" * 110)
    print(f"Total Net PnL across {len(reconstructed)} trades: ${total_net:+,.2f}")
    print("=" * 110)

    if args.sync:
        synced = sync_broker_trades_to_ledger(
            reconstructed,
            dry_run=args.dry_run,
            require_model_approval=(not args.include_gated),
        )
        print(f"\n✅ Synchronization complete: {synced} trade(s) newly committed to demo parity ledger.")


if __name__ == "__main__":
    main()
