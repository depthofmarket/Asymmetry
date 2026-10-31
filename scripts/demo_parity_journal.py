#!/usr/bin/env python3
"""
CLI Tool for LucidFlex 25K Demo Parity & Slippage Journal.

Usage:
  Interactive Menu:
    python scripts/demo_parity_journal.py

  Direct Commands:
    python scripts/demo_parity_journal.py status
    python scripts/demo_parity_journal.py log-trade [options]
    python scripts/demo_parity_journal.py log-session [options]
    python scripts/demo_parity_journal.py html
    python scripts/demo_parity_journal.py reset
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.demo_parity_engine import (
    DAILY_SOFT_STOP_DOLLARS,
    MAX_FIRM_MICROS,
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


# Terminal ANSI Colors
class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BLUE = "\033[94m"
    WHITE = "\033[97m"


def print_status_banner(state: AccountEvalState) -> None:
    """Print institutional-grade status dashboard in terminal with 2 clear stages."""
    pnl_color = Color.GREEN if state.profit >= 0 else Color.RED
    pct_to_target = max(0.0, min(100.0, (state.profit / PROFIT_TARGET_DOLLARS) * 100.0))
    bar_len = 24
    filled_len = int(bar_len * (pct_to_target / 100.0))
    bar_str = "█" * filled_len + "░" * (bar_len - filled_len)

    print("\n" + "=" * 74)
    print(f"  {Color.BOLD}{Color.WHITE}STRATEGY 1: MORNING VA BREAKOUT (v2.0) — EXECUTION & PARITY JOURNAL{Color.RESET}")
    print(f"  Feed: AMP Global CQG Demo  |  Engine: MotiveWave Study  |  09:45:00 ET")
    print("=" * 74)

    # STAGE 1: DEMO FORWARD TEST AUDIT
    print(f"  {Color.BOLD}{Color.CYAN}[STAGE 1: FORWARD TEST DEMO AUDIT — AMP CQG FEED]{Color.RESET}")
    print(f"  Forward Trades:    {state.trades_count} Trades ({state.wins_count}W - {state.losses_count}L | Win Rate: {state.win_rate:.1f}%)")
    print(f"  Realized PnL:      {pnl_color}{Color.BOLD}${state.profit:+,.2f}{Color.RESET} (Commissions: $1.40 RT/micro deducted)")
    print(f"  Profit Factor:     {state.profit_factor:.2f}")
    print(f"  Avg Entry Slip:    {Color.YELLOW if state.avg_entry_slippage_ticks > 0 else Color.GREEN}{state.avg_entry_slippage_ticks:+.2f} ticks{Color.RESET} ({state.avg_entry_slippage_ticks*0.25:+.2f} pts | Adverse: {state.adverse_entry_rate:.1f}%)")
    print(f"  Avg Exit Slip:     {Color.YELLOW if state.avg_exit_slippage_ticks > 0 else Color.GREEN}{state.avg_exit_slippage_ticks:+.2f} ticks{Color.RESET} ({state.avg_exit_slippage_ticks*0.25:+.2f} pts)")
    drag_color = Color.RED if state.total_slippage_drag_dollars < 0 else Color.GREEN
    print(f"  Slippage Drag:     {drag_color}${state.total_slippage_drag_dollars:+,.2f}{Color.RESET} (Total execution friction vs theoretical)")
    print("-" * 74)

    # STAGE 2: PROP FIRM DEPLOYMENT
    print(f"  {Color.BOLD}{Color.WHITE}[STAGE 2: PROP FIRM DEPLOYMENT RULES — LUCIDFLEX 25K]{Color.RESET}")
    print(f"  Account Equity:    {Color.BOLD}${state.balance:,.2f}{Color.RESET} (Start: ${state.starting_capital:,.2f} | Floor: ${state.trailing_floor:,.2f})")
    print(f"  Passing Target:    {Color.BOLD}${TARGET_BALANCE:,.2f}{Color.RESET} (+$1,250.00 / +5.0% | Remaining: ${state.distance_to_target:,.2f})")
    print(f"  Corridor Progress: [{Color.GREEN}{bar_str}{Color.RESET}] {pct_to_target:.1f}%")
    print(f"  Trailing Cushion:  {Color.GREEN if state.trailing_cushion > 300 else Color.RED}${state.trailing_cushion:,.2f}{Color.RESET} (Locks at ${TRAILING_FLOOR_LOCK:,.2f} once peak >= $26,100)")
    day_color = Color.RED if state.current_date_pnl <= DAILY_SOFT_STOP_DOLLARS else Color.GREEN
    print(f"  Daily Soft Stop:   {day_color}${state.current_date_pnl:+,.2f}{Color.RESET} / ${DAILY_SOFT_STOP_DOLLARS:,.2f} (Safety Margin: ${state.distance_to_daily_stop:,.2f})")
    print(f"  Ratchet Sizing:    {state.recommended_tier} (Max Firm Limit: 10 Micros)")
    print("=" * 74 + "\n")


def prompt_log_trade(journal: DemoParityJournal) -> None:
    """Step-by-step interactive wizard for logging a live demo trade."""
    print(f"\n{Color.BOLD}{Color.CYAN}--- LOG FORWARD DEMO TRADE ---{Color.RESET}")
    today_str = datetime.now().strftime("%Y-%m-%d")

    date_str = input(f"Date [{today_str}]: ").strip() or today_str
    symbol = input("Symbol (MNQ / MES / NQ / ES) [MNQ]: ").strip().upper() or "MNQ"
    direction = input("Direction (LONG / SHORT) [LONG]: ").strip().upper() or "LONG"
    while direction not in ("LONG", "SHORT"):
        direction = input("Please enter LONG or SHORT: ").strip().upper()

    eval_state = journal.get_eval_state()
    default_qty = eval_state.recommended_micros
    qty_input = input(f"Contracts / Micros (Firm Max 10) [{default_qty}]: ").strip()
    contracts = int(qty_input) if qty_input else default_qty

    if contracts > MAX_FIRM_MICROS:
        print(f"{Color.RED}[WARNING] Quantity {contracts} exceeds firm limit of 10 Micros!{Color.RESET}")

    # Theoretical Levels
    theo_entry_in = input("Theoretical Signal Entry Price (e.g. 20450.25): ").strip()
    theo_entry = float(theo_entry_in)

    actual_entry_in = input(f"Actual Demo Fill Price [{theo_entry}]: ").strip()
    actual_entry = float(actual_entry_in) if actual_entry_in else theo_entry

    entry_time_in = input("Actual Fill Time ET [09:45:01]: ").strip()
    actual_entry_time = entry_time_in or "09:45:01"

    # Stop Loss & Target
    spec = resolve_instrument(symbol)
    default_stop_pts = 35.0 if "ES" in symbol else 50.0
    theo_stop_default = theo_entry - default_stop_pts if direction == "LONG" else theo_entry + default_stop_pts
    theo_target_default = theo_entry + (default_stop_pts * 1.5) if direction == "LONG" else theo_entry - (default_stop_pts * 1.5)

    stop_in = input(f"Theoretical Stop Price [{theo_stop_default:.2f}]: ").strip()
    theo_stop = float(stop_in) if stop_in else theo_stop_default

    target_in = input(f"Theoretical 1.5R Target Price [{theo_target_default:.2f}]: ").strip()
    theo_target = float(target_in) if target_in else theo_target_default

    print("\nExit Rule Trigger:")
    print("  [1] PROFIT_TARGET_1_5R")
    print("  [2] STOP_LOSS")
    print("  [3] TIME_EXIT_1015 (30-min Max Holding)")
    print("  [4] NEWS_GUARD_0959 (10:00 AM Macro News Flatten)")
    print("  [5] MANUAL")
    exit_choice = input("Select [1]: ").strip() or "1"
    exit_map = {
        "1": "PROFIT_TARGET_1_5R",
        "2": "STOP_LOSS",
        "3": "TIME_EXIT_1015",
        "4": "NEWS_GUARD_0959",
        "5": "MANUAL",
    }
    exit_type = exit_map.get(exit_choice, "PROFIT_TARGET_1_5R")

    theo_exit = theo_target if exit_type == "PROFIT_TARGET_1_5R" else (theo_stop if exit_type == "STOP_LOSS" else actual_entry)
    actual_exit_in = input(f"Actual Exit Fill Price [{theo_exit:.2f}]: ").strip()
    actual_exit = float(actual_exit_in) if actual_exit_in else theo_exit

    exit_time_in = input("Actual Exit Time ET [10:04:15]: ").strip()
    actual_exit_time = exit_time_in or "10:04:15"

    notes = input("Trade Notes / Context (optional): ").strip()

    record = TradeFillRecord(
        date=date_str,
        symbol=symbol,
        direction=direction,
        contracts=contracts,
        theo_entry_price=theo_entry,
        actual_entry_fill=actual_entry,
        theo_stop_price=theo_stop,
        theo_target_price=theo_target,
        exit_type=exit_type,
        actual_exit_fill=actual_exit,
        actual_entry_time=actual_entry_time,
        actual_exit_time=actual_exit_time,
        notes=notes,
    )

    new_state = journal.record_trade(record)

    # Print Receipt
    print("\n" + "=" * 65)
    print(f"  {Color.BOLD}{Color.GREEN}TRADE RECORDED IN FORWARD LEDGER!{Color.RESET}")
    print("=" * 65)
    pnl_col = Color.GREEN if record.net_pnl >= 0 else Color.RED
    print(f"  Trade ID:          #{record.trade_id}")
    print(f"  Instrument:        {record.contracts}x {record.symbol} {record.direction}")
    print(f"  Entry Parity:      Theo: {record.theo_entry_price:.2f} | Fill: {record.actual_entry_fill:.2f}  ({record.entry_slippage_ticks:+.1f} ticks slip)")
    print(f"  Exit Parity:       Theo: {record.theo_exit_price:.2f} | Fill: {record.actual_exit_fill:.2f}  ({record.exit_slippage_ticks:+.1f} ticks slip)")
    print(f"  Realized Points:   {record.realized_points:+.2f} pts")
    print(f"  Slippage Drag:     ${record.total_slippage_dollars:+,.2f}")
    print(f"  Commission:        ${record.commission:.2f}")
    print(f"  Net PnL:           {pnl_col}{Color.BOLD}${record.net_pnl:+,.2f}{Color.RESET}")
    print(f"  Updated Balance:   {Color.BOLD}${new_state.balance:,.2f}{Color.RESET}")
    print(f"  Trailing Cushion:  ${new_state.trailing_cushion:,.2f}")
    print(f"  Dashboard Updated: {journal.dashboard_html_path}")
    print("=" * 65 + "\n")


def prompt_log_session(journal: DemoParityJournal) -> None:
    """Prompt to log an audited trading day where no trade was fired."""
    print(f"\n{Color.BOLD}{Color.CYAN}--- LOG NO-SETUP SESSION / MOTIVEWAVE DIAGNOSTIC ---{Color.RESET}")
    today_str = datetime.now().strftime("%Y-%m-%d")
    date_str = input(f"Date [{today_str}]: ").strip() or today_str

    print("\nCommon Diagnostic Reasons from MotiveWave:")
    print("  [1] NO TRADE: Inside Prior VA [VAL: ... | VAH: ... | Close: ...]")
    print("  [2] NO TRADE: Weak Momentum (Return: ... vs req +/-0.10%)")
    print("  [3] NO TRADE: Upper Wick Reject (CloseLoc: ... vs req >= 0.65)")
    print("  [4] NO TRADE: Lower Wick Reject (CloseLoc: ... vs req <= 0.35)")
    print("  [5] Custom reason from MotiveWave chart marker")

    choice = input("Select [1]: ").strip() or "1"
    if choice == "1":
        reason = input("Paste exact text or press Enter for default: ").strip() or "NO TRADE: Inside Prior VA"
    elif choice == "2":
        reason = input("Paste exact text or press Enter for default: ").strip() or "NO TRADE: Weak Momentum"
    elif choice == "3":
        reason = input("Paste exact text or press Enter for default: ").strip() or "NO TRADE: Upper Wick Reject"
    elif choice == "4":
        reason = input("Paste exact text or press Enter for default: ").strip() or "NO TRADE: Lower Wick Reject"
    else:
        reason = input("Enter MotiveWave marker text: ").strip() or "NO TRADE: No Setup"

    macro_in = input("Was there a 10:00 AM Tier-1 Macro News release today? (y/n) [n]: ").strip().lower()
    macro_day = macro_in == "y"

    eval_state = journal.get_eval_state()
    session = DailySessionRecord(
        date=date_str,
        setup_detected=False,
        setup_fired=False,
        diagnostic_reason=reason,
        macro_news_day=macro_day,
        day_net_pnl=0.0,
        trades_count=0,
        end_of_day_balance=eval_state.balance,
    )
    journal.record_session(session)
    journal.generate_html_dashboard()

    print(f"\n{Color.GREEN}[OK] Session recorded for {date_str}:{Color.RESET} {reason}")
    print(f"Dashboard updated at {journal.dashboard_html_path}\n")


def import_motivewave_csv(journal: DemoParityJournal, csv_path: str) -> None:
    """Import trades directly from MotiveWave exported CSV file."""
    p = Path(csv_path)
    if not p.exists():
        print(f"{Color.RED}File not found: {csv_path}{Color.RESET}")
        return

    df = pd.read_csv(p)
    print(f"Loaded {len(df)} rows from {csv_path}. Mapping columns...")

    # Normalize column names
    col_map = {c.strip().lower(): c for c in df.columns}
    
    # Try finding typical MotiveWave columns
    # Symbol, Side/Action, Qty, Entry Price, Exit Price, P/L, etc.
    imported = 0
    for _, row in df.iterrows():
        try:
            sym = "MNQ"
            for k in ["symbol", "instrument"]:
                if k in col_map:
                    sym = str(row[col_map[k]]).upper()
            
            side = "LONG"
            for k in ["side", "action", "type", "direction"]:
                if k in col_map:
                    val = str(row[col_map[k]]).upper()
                    if "SELL" in val or "SHORT" in val:
                        side = "SHORT"

            qty = 2
            for k in ["qty", "quantity", "contracts", "shares"]:
                if k in col_map:
                    qty = int(row[col_map[k]])

            entry_p = 0.0
            for k in ["entry price", "entry_price", "price", "buy price", "open price"]:
                if k in col_map:
                    entry_p = float(row[col_map[k]])

            exit_p = entry_p
            for k in ["exit price", "exit_price", "close price", "sell price"]:
                if k in col_map:
                    exit_p = float(row[col_map[k]])

            date_str = datetime.now().strftime("%Y-%m-%d")
            for k in ["date", "entry date", "entry time", "time"]:
                if k in col_map:
                    dt_val = str(row[col_map[k]])[:10]
                    if len(dt_val) == 10 and "-" in dt_val:
                        date_str = dt_val

            record = TradeFillRecord(
                date=date_str,
                symbol=sym,
                direction=side,
                contracts=qty,
                theo_entry_price=entry_p,
                actual_entry_fill=entry_p,
                theo_stop_price=entry_p - 40.0 if side == "LONG" else entry_p + 40.0,
                theo_target_price=entry_p + 60.0 if side == "LONG" else entry_p - 60.0,
                exit_type="PROFIT_TARGET_1_5R" if (exit_p > entry_p if side == "LONG" else exit_p < entry_p) else "STOP_LOSS",
                actual_exit_fill=exit_p,
                notes="Imported from MotiveWave CSV",
            )
            journal.record_trade(record)
            imported += 1
        except Exception as exc:
            print(f"Skipping row due to error: {exc}")

    print(f"\n{Color.GREEN}Successfully imported {imported} trade(s) from MotiveWave!{Color.RESET}")
    print_status_banner(journal.get_eval_state())


def interactive_menu(journal: DemoParityJournal) -> None:
    """Main interactive terminal loop."""
    while True:
        state = journal.get_eval_state()
        print_status_banner(state)

        print(f"{Color.BOLD}ACTION MENU:{Color.RESET}")
        print("  [1] Log Today's Trade Fill (Theoretical vs Demo Execution Parity)")
        print("  [2] Log No-Setup Session (MotiveWave Diagnostic Reason)")
        print("  [3] Re-generate & Open HTML Visual Dashboard")
        print("  [4] Import Fills from MotiveWave CSV Export")
        print("  [5] Reset / Initialize Forward Ledger (Start Fresh)")
        print("  [q] Exit")

        choice = input("\nSelect an action [1-5 or q]: ").strip().lower()

        if choice == "1":
            prompt_log_trade(journal)
        elif choice == "2":
            prompt_log_session(journal)
        elif choice == "3":
            path = journal.generate_html_dashboard()
            print(f"\n{Color.GREEN}[OK] HTML Dashboard generated at:{Color.RESET} {path}")
            print(f"You can open it in any browser: open \"{path}\"")
        elif choice == "4":
            csv_path = input("Enter path to MotiveWave CSV export file: ").strip()
            import_motivewave_csv(journal, csv_path)
        elif choice == "5":
            confirm = input(f"{Color.RED}Are you sure you want to RESET all forward demo data? (yes/no): {Color.RESET}").strip().lower()
            if confirm == "yes":
                journal.reset_ledger()
                print(f"{Color.GREEN}Forward ledger reset to pristine state ($25,000.00).{Color.RESET}")
        elif choice in ("q", "quit", "exit"):
            print("Standing by for next trading session.")
            break
        else:
            print("Invalid option. Please choose 1-5 or q.")


def main() -> int:
    parser = argparse.ArgumentParser(description="LucidFlex 25K Demo Parity & Slippage Journal")
    subparsers = parser.add_subparsers(dest="command")

    # Status
    subparsers.add_parser("status", help="Print account status and execution analytics")

    # Log Trade
    trade_p = subparsers.add_parser("log-trade", help="Record a trade fill into the ledger")
    trade_p.add_argument("--date", default=None)
    trade_p.add_argument("--symbol", default="MNQ")
    trade_p.add_argument("--direction", choices=["LONG", "SHORT"], required=True)
    trade_p.add_argument("--contracts", type=int, default=2)
    trade_p.add_argument("--theo-entry", type=float, required=True)
    trade_p.add_argument("--actual-entry", type=float, required=True)
    trade_p.add_argument("--theo-stop", type=float, default=None)
    trade_p.add_argument("--theo-target", type=float, default=None)
    trade_p.add_argument("--exit-type", choices=["PROFIT_TARGET_1_5R", "STOP_LOSS", "TIME_EXIT_1015", "NEWS_GUARD_0959", "MANUAL"], default="PROFIT_TARGET_1_5R")
    trade_p.add_argument("--actual-exit", type=float, required=True)
    trade_p.add_argument("--theo-exit", type=float, default=None)
    trade_p.add_argument("--notes", default="")

    # Log Session
    session_p = subparsers.add_parser("log-session", help="Record a daily session (no-trade reason)")
    session_p.add_argument("--date", default=None)
    session_p.add_argument("--reason", required=True)
    session_p.add_argument("--macro-news", action="store_true")

    # HTML
    subparsers.add_parser("html", help="Rebuild HTML visual dashboard")

    # Import
    import_p = subparsers.add_parser("import-motivewave", help="Import MotiveWave CSV")
    import_p.add_argument("--file", required=True)

    # Reset
    subparsers.add_parser("reset", help="Reset forward ledger")

    args = parser.parse_args()
    journal = DemoParityJournal()

    if args.command is None:
        interactive_menu(journal)
        return 0

    if args.command == "status":
        print_status_banner(journal.get_eval_state())
        return 0

    if args.command == "log-trade":
        date_str = args.date or datetime.now().strftime("%Y-%m-%d")
        theo_stop = args.theo_stop or (args.theo_entry - 50.0 if args.direction == "LONG" else args.theo_entry + 50.0)
        theo_target = args.theo_target or (args.theo_entry + 75.0 if args.direction == "LONG" else args.theo_entry - 75.0)
        rec = TradeFillRecord(
            date=date_str,
            symbol=args.symbol,
            direction=args.direction,
            contracts=args.contracts,
            theo_entry_price=args.theo_entry,
            actual_entry_fill=args.actual_entry,
            theo_stop_price=theo_stop,
            theo_target_price=theo_target,
            exit_type=args.exit_type,
            actual_exit_fill=args.actual_exit,
            theo_exit_price=args.theo_exit,
            notes=args.notes,
        )
        journal.record_trade(rec)
        print_status_banner(journal.get_eval_state())
        return 0

    if args.command == "log-session":
        date_str = args.date or datetime.now().strftime("%Y-%m-%d")
        state = journal.get_eval_state()
        session = DailySessionRecord(
            date=date_str,
            setup_detected=False,
            setup_fired=False,
            diagnostic_reason=args.reason,
            macro_news_day=args.macro_news,
            end_of_day_balance=state.balance,
        )
        journal.record_session(session)
        journal.generate_html_dashboard()
        print(f"[OK] Logged session for {date_str}: {args.reason}")
        return 0

    if args.command == "html":
        out = journal.generate_html_dashboard()
        print(f"[OK] Generated: {out}")
        return 0

    if args.command == "import-motivewave":
        import_motivewave_csv(journal, args.file)
        return 0

    if args.command == "reset":
        journal.reset_ledger()
        print("[OK] Forward ledger reset.")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
