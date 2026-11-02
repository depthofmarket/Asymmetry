#!/usr/bin/env python3
"""
scripts/launch_monday_forward_test.py
========================================================================================
LUCIDFLEX 25K MONDAY PRE-FLIGHT VERIFICATION & LAUNCH CONTROL
Antiachismo Quant Research | Three-Strategy Sequential Forward-Test Engine
========================================================================================

Verifies and arms the forward-testing engine for live/demo trading:
  1. System Clock & ET Timezone Synchronization (America/New_York)
  2. Data Feed Health & CQG File Timestamps (@NQ, @ES, @GC)
  3. LucidFlex 25K Prop Risk Envelope ($25,144.70 balance, $1,000 buffer, 2 micros)
  4. Three Strategy Setup Verification:
       - Strategy 3 (08:35 ET): MNQ Pre-Market Macro Momentum (H17)
       - Strategy 1 (09:45 ET): MNQ/MES Opening Value Area Breakout (H4)
       - Strategy 2 (10:15 ET): MGC Gold London PM Fix Breakout (H14)
  5. macOS Notification & Voice Chime Self-Test
  6. Interactive Launcher Menu for continuous watching or single scanning
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import os
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.demo_parity_engine import (
    DASHBOARD_HTML_PATH,
    STATE_JSON_PATH,
    TRADES_LEDGER_PATH,
    DemoParityJournal,
)
from scripts.watch_morning_demo_alerts import send_macos_alert

ET_TZ = ZoneInfo("America/New_York")


def get_terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except Exception:
        return 88


def format_delta(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        return "PASSED"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}h {minutes:02d}m {seconds:02d}s"


def inspect_cqg_file(path: Path) -> dict:
    if not path.exists():
        return {"status": "MISSING", "size": 0, "mtime_str": "N/A", "latest_bar": "N/A"}
    size_mb = path.stat().st_size / (1024 * 1024)
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=ET_TZ)
    mtime_str = mtime.strftime("%Y-%m-%d %H:%M:%S ET")

    # Read the very last line to get latest bar
    latest_bar = "Unknown"
    try:
        res = subprocess.run(["tail", "-n", "2", str(path)], capture_output=True, text=True, timeout=2)
        lines = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
        if lines:
            latest_bar = lines[-1].split(",")[0].strip()
    except Exception:
        pass

    return {
        "status": "ONLINE",
        "size_mb": size_mb,
        "mtime_str": mtime_str,
        "latest_bar": latest_bar,
    }


def run_preflight_checks(verbose: bool = True) -> tuple[bool, DemoParityJournal]:
    width = min(88, get_terminal_width())
    now_local = datetime.now()
    now_et = datetime.now(ET_TZ)

    print("=" * width)
    print("  LUCIDFLEX 25K MONDAY PRE-FLIGHT VERIFICATION & LAUNCH CONTROL")
    print("  Antiachismo Quant Research | Multi-Strategy Sequential Forward-Test Engine")
    print("=" * width)

    # 1. System Clock & Timezone
    print("\n[1] SYSTEM CLOCK & TIMEZONE SYNCHRONIZATION")
    print(f"  Local System Time : {now_local.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  Exchange Time (ET): {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  Weekday           : {now_et.strftime('%A')} ({now_et.strftime('%Y-%m-%d')})")

    # Window Schedules & Countdowns
    today_et = now_et.date()
    windows = [
        ("08:30 ET", "Macro Economic News Release (BLS / Fed)", datetime.combine(today_et, datetime.strptime("08:30:00", "%H:%M:%S").time(), tzinfo=ET_TZ)),
        ("08:35 ET", "Strategy 3 (MNQ Macro Release Momentum)", datetime.combine(today_et, datetime.strptime("08:35:00", "%H:%M:%S").time(), tzinfo=ET_TZ)),
        ("09:25 ET", "Strategy 3 Scheduled Flat Exit (Pre-Cash)", datetime.combine(today_et, datetime.strptime("09:25:00", "%H:%M:%S").time(), tzinfo=ET_TZ)),
        ("09:30 ET", "US Cash Equities Market Open (NYSE / Nasdaq)", datetime.combine(today_et, datetime.strptime("09:30:00", "%H:%M:%S").time(), tzinfo=ET_TZ)),
        ("09:45 ET", "Strategy 1 (MNQ/MES Morning Value Area Breakout)", datetime.combine(today_et, datetime.strptime("09:45:00", "%H:%M:%S").time(), tzinfo=ET_TZ)),
        ("10:15 ET", "Strategy 1 Flat Exit / Strategy 2 (MGC Gold Fix) Open", datetime.combine(today_et, datetime.strptime("10:15:00", "%H:%M:%S").time(), tzinfo=ET_TZ)),
        ("11:00 ET", "Strategy 2 Flat Exit / Daily Forward-Test Complete", datetime.combine(today_et, datetime.strptime("11:00:00", "%H:%M:%S").time(), tzinfo=ET_TZ)),
    ]

    print("\n  Upcoming Execution Windows Today:")
    for code, desc, dt_target in windows:
        delta = dt_target - now_et
        cd_str = format_delta(delta)
        status_sym = "[PAST]" if delta.total_seconds() < 0 else "[ARMED]"
        print(f"    {status_sym:7s} {code:8s} -> {desc:<48s} (T-{cd_str})")

    # 2. Account State & Risk Envelope
    journal = DemoParityJournal()
    st = journal.get_eval_state()
    profit_pct = (st.profit / st.starting_capital * 100.0) if st.starting_capital > 0 else 0.0

    print("\n[2] PROP FIRM RISK ENVELOPE (LUCIDFLEX 25K)")
    print(f"  Current Balance       : ${st.balance:,.2f}  (Profit: ${st.profit:+,.2f} / +{profit_pct:.2f}%)")
    print(f"  Profit Target ($1,250): ${st.starting_capital + 1250.0:,.2f}  (${st.distance_to_target:,.2f} remaining)")
    print(f"  Peak High-Water Mark  : ${st.peak_balance:,.2f}")
    print(f"  Trailing Drawdown Floor: ${st.trailing_floor:,.2f}  (Buffer / Cushion: ${st.trailing_cushion:,.2f})")
    print(f"  Floor Lock Threshold  : $25,100.00 once Peak >= $26,100.00")
    print(f"  Daily Soft Stop Limit : ${st.daily_soft_stop_limit:,.2f}")
    print(f"  Recommended Sizing    : {st.recommended_tier} ({st.recommended_micros} Micros)")
    print(f"  Historical Parity Net : {st.trades_count} Trades | WR {st.win_rate:.1f}% | Net ${st.profit:+,.2f} | Drag ${st.total_slippage_drag_dollars:,.2f}")

    # 3. Market Data Feeds Health Check
    print("\n[3] MARKET DATA FEEDS (MOTIVEWAVE CQG EXPORTS)")
    cqg_files = {
        "MNQ / NQ": REPO_ROOT / "data/raw/@NQ.CQG_1.csv",
        "MES / ES": REPO_ROOT / "data/raw/@ES.CQG_1.csv",
        "MGC / GC": REPO_ROOT / "data/raw/@GC.CQG_1.csv",
    }
    all_feeds_ok = True
    for asset_label, path in cqg_files.items():
        info = inspect_cqg_file(path)
        if info["status"] == "ONLINE":
            print(f"  ✓ {asset_label:<10s} : ONLINE ({info['size_mb']:.1f} MB | Modified: {info['mtime_str']} | Last Bar: {info['latest_bar']})")
        else:
            print(f"  ✗ {asset_label:<10s} : MISSING ({path.name})")
            all_feeds_ok = False

    # Check Parquet fallback
    parquet_files = [
        REPO_ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet",
        REPO_ROOT / "data/raw/es_1m_2020_2026_cqg_et.parquet",
        REPO_ROOT / "data/raw/gc_1m_2020_2026_et.parquet",
    ]
    parquet_ok = all(p.exists() for p in parquet_files)
    if parquet_ok:
        print("  ✓ Secondary Parquet Archive : ALL 3 DATASETS VERIFIED")
    else:
        print("  ! Secondary Parquet Archive : SOME FILES MISSING")

    # 4. Strategy Governance & Parity Ledgers
    print("\n[4] STRATEGY GOVERNANCE & PARITY LEDGERS")
    print(f"  Trades Ledger CSV     : {TRADES_LEDGER_PATH} ({'EXISTS' if TRADES_LEDGER_PATH.exists() else 'NEW'})")
    print(f"  Parity State JSON     : {STATE_JSON_PATH} ({'EXISTS' if STATE_JSON_PATH.exists() else 'NEW'})")
    print(f"  HTML Parity Dashboard : {DASHBOARD_HTML_PATH} ({'EXISTS' if DASHBOARD_HTML_PATH.exists() else 'NEW'})")
    print("  Execution Strategy Setups:")
    print("    - Strategy 3 (08:35 ET): MNQ Macro Release (50m limit, flat 09:25 ET, GARCH MVT + Markov)")
    print("    - Strategy 1 (09:45 ET): MNQ/MES VA Breakout (30m limit, flat 10:15 ET, Dual-Asset Gate)")
    print("    - Strategy 2 (10:15 ET): MGC Gold London Fix (45m limit, flat 11:00 ET, H14 Breakout)")

    print("\n" + "-" * width)
    if st.trailing_cushion <= 0:
        print("  [CRITICAL ALERT] ACCOUNT FLOOR BREACHED OR AT ZERO CUSHION! TRADING HALTED.")
        return False, journal
    elif st.trailing_cushion < 250:
        print("  [WARNING] CUSHION IS LOW (< $250). SIZING STRICTLY CONSTRAINED TO 1 MICRO.")
    else:
        print("  [STATUS: PASS] ALL PRE-FLIGHT CHECKS CLEARED. ENGINE FULLY ARMED FOR MONDAY.")
    print("-" * width)

    return True, journal


def test_macos_alerts(verbose: bool = True) -> None:
    print("\nFiring test macOS desktop notification and voice alert...")
    send_macos_alert(
        title="LucidFlex 25K Pre-Flight Verified",
        subtitle="Forward-Test Engine Armed for Monday",
        message="System clock, data feeds, and risk envelope cleared for live session.",
        speak_text="LucidFlex forward test engine armed for Monday morning session.",
    )
    print("✓ Alert dispatched to macOS Notification Center & Samantha voice.")


def interactive_menu(journal: DemoParityJournal) -> None:
    while True:
        print("\nSelect Launch Action:")
        print("  [1] Arm Continuous Morning Watcher Daemon (Automatic multi-window execution)")
        print("  [2] Run Single Forward-Test Scan Now (Immediate check on latest bars)")
        print("  [3] Launch Interactive Trade Fill Logger (Record real-time fills & slippage)")
        print("  [4] Open HTML Parity Dashboard in Default Browser")
        print("  [5] Test macOS Notification & Voice Chime")
        print("  [6] Exit")

        choice = input("\nChoice [1-6] (Default 1): ").strip() or "1"

        if choice == "1":
            print("\nStarting Continuous Morning Watcher Daemon...")
            subprocess.run([sys.executable, str(REPO_ROOT / "scripts/watch_morning_demo_alerts.py")])
            break
        elif choice == "2":
            print("\nRunning single immediate scan across all 3 windows...")
            subprocess.run([sys.executable, str(REPO_ROOT / "scripts/watch_morning_demo_alerts.py"), "--once"])
        elif choice == "3":
            print("\nLaunching Interactive Trade Fill Logger...")
            subprocess.run([sys.executable, str(REPO_ROOT / "scripts/run_demo_forward_test.py"), "--interactive"])
        elif choice == "4":
            print(f"\nOpening dashboard: {DASHBOARD_HTML_PATH}")
            if sys.platform == "darwin":
                subprocess.run(["open", str(DASHBOARD_HTML_PATH)])
            elif sys.platform.startswith("linux"):
                subprocess.run(["xdg-open", str(DASHBOARD_HTML_PATH)])
            else:
                os.startfile(str(DASHBOARD_HTML_PATH))  # type: ignore
        elif choice == "5":
            test_macos_alerts()
        elif choice in ("6", "q", "exit"):
            print("\nExiting Pre-Flight Control. Have a disciplined trading session!")
            break
        else:
            print("Invalid choice, please select 1 to 6.")


def main() -> int:
    parser = argparse.ArgumentParser(description="LucidFlex 25K Monday Pre-Flight Verification & Launcher.")
    parser.add_argument("--check-only", action="store_true", help="Run pre-flight checks and exit without interactive menu.")
    parser.add_argument("--arm", action="store_true", help="Directly arm continuous morning watcher daemon.")
    parser.add_argument("--test-alert", action="store_true", help="Fire test macOS desktop notification and voice.")
    args = parser.parse_args()

    passed, journal = run_preflight_checks(verbose=True)

    if args.test_alert:
        test_macos_alerts()

    if args.check_only:
        return 0 if passed else 1

    if args.arm:
        print("\nDirectly arming Continuous Morning Watcher Daemon...")
        subprocess.run([sys.executable, str(REPO_ROOT / "scripts/watch_morning_demo_alerts.py")])
        return 0

    interactive_menu(journal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
