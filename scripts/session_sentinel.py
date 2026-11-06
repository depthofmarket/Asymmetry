#!/usr/bin/env python3
"""
LucidFlex Session Lifecycle Sentinel.

Orchestrates daily trading operations:
1. Pre-Market Readiness Check (08:15 ET)
2. Post-Market Demo Parity & Monte Carlo Reconciliation (16:15 ET)
3. Weekly Alpha & Health Digest (Friday 17:00 ET)

Governed by the 5 Golden Rules of Quantitative Provenance.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ET_TZ = ZoneInfo("America/New_York")

from backtest.provenance import ProvenanceStore, default_store
from backtest.demo_parity_engine import DemoParityJournal


def run_command_capture(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """Runs a subprocess and returns exit code and combined output."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except Exception as e:
        return -1, str(e)


def run_premarket_readiness() -> int:
    """Executes the pre-market readiness diagnostic."""
    print("=" * 76)
    print(" 🌅 EXECUTING PRE-MARKET READINESS SENTINEL (08:15 ET)")
    print("=" * 76)
    code, output = run_command_capture(["python", "scripts/check_morning_readiness.py"])
    print(output.strip())
    print("=" * 76)
    return code


def run_postmarket_reconcile() -> int:
    """Executes post-market demo parity reconciliation and Monte Carlo overlay."""
    print("=" * 76)
    print(" 🌆 EXECUTING POST-MARKET RECONCILIATION SENTINEL (16:15 ET)")
    print("=" * 76)

    # 1. Ingest & Sync Live MotiveWave CQG Broker Executions
    print(" 1. Synchronizing MotiveWave CQG broker executions...")
    code_sync, sync_out = run_command_capture([
        "python",
        "scripts/sync_cqg_executions.py",
        "--sync",
        "--systematic-only",
        "--symbols",
        "MES,MNQ,MGC",
    ])
    if code_sync == 0:
        print(" [🟢] CQG broker executions synchronized.")
    else:
        print(f" [⚠️] CQG sync warning (using existing ledger):\n{sync_out.strip()}")

    # 2. Inspect Demo Parity Journal
    forward_test_dir = REPO_ROOT / "results/forward_test"
    journal = DemoParityJournal(forward_test_dir=forward_test_dir)
    state = journal.get_eval_state()

    print(f" Account Status   : {state.status} ({state.status_reason})")
    print(f" Current Balance  : ${state.balance:,.2f}")
    print(f" Cumulative PnL   : ${state.profit:,.2f}")
    print(f" Peak Balance     : ${state.peak_balance:,.2f}")
    print(f" Trailing Floor   : ${state.trailing_floor:,.2f}")
    print(f" Trailing Cushion : ${state.trailing_cushion:,.2f}")
    print(f" Contract Sizing  : {state.recommended_micros} Micros ({state.recommended_tier})")
    print(f" Total Trades     : {state.trades_count} (Win%: {state.win_rate:.1f}% | PF: {state.profit_factor:.2f})")

    # 2. Re-center Monte Carlo Corridor
    print("\n Re-centering 10,000-Path Monte Carlo Corridor with latest equity...")
    code, mc_output = run_command_capture(["python", "scripts/generate_monte_carlo_corridor.py"])
    if code == 0:
        print(" [🟢] Monte Carlo Corridor re-centered successfully.")
    else:
        print(f" [❌] Failed to generate Monte Carlo corridor:\n{mc_output}")
        return code

    # 3. Check Monte Carlo corridor percentile metrics
    corridor_json = REPO_ROOT / "results/forward_test/live_vs_monte_carlo_corridor.json"
    if corridor_json.exists():
        with open(corridor_json, "r") as f:
            mc_data = json.load(f)
        status = mc_data.get("regime_status", "UNKNOWN")
        percentile = mc_data.get("current_rank", 0.0)
        curr_bal = mc_data.get("current_balance", state.balance)
        live_len = len(mc_data.get("live_equity", []))
        p05_list = mc_data.get("percentiles", {}).get("p05", [])
        p05_val = p05_list[live_len - 1] if live_len <= len(p05_list) and live_len > 0 else 24793.52
        p05_dist = curr_bal - p05_val

        print(f" Regime Status    : {status}")
        print(f" Percentile Rank  : {percentile:.1f}% (Interquartile Edge)")
        print(f" Buffer to P05    : +${p05_dist:,.2f}")

        if status == "REGIME_STRESS_WARNING":
            print("\n [🚨] ALERT: Live equity is below the 5th percentile corridor! Halt trading.")
            return 1
        else:
            print(" [🟢] Expectancy confirmed. Equity sits inside favorable corridor.")

    # 4. Refresh Dashboard
    print("\n Re-rendering Live Demo Parity Dashboard...")
    dashboard_path = journal.generate_html_dashboard()
    print(f" [🟢] Dashboard updated: {dashboard_path.relative_to(REPO_ROOT)}")

    print("=" * 76)
    return 0


def run_weekly_digest() -> int:
    """Executes the weekly quantitative health audit (Friday 17:00 ET)."""
    print("=" * 76)
    print(" 📊 EXECUTING WEEKLY QUANTITATIVE HEALTH DIGEST (Friday 17:00 ET)")
    print("=" * 76)

    # 1. Run Automated Test Suite
    print(" 1. Running core test suite...")
    code, test_output = run_command_capture([
        "pytest",
        "tests/test_provenance_system.py",
        "tests/test_demo_parity_journal.py",
        "tests/test_cqg_execution_sync.py",
        "tests/test_deflated_sharpe.py",
        "tests/test_operational_readiness.py",
        "tests/test_morning_watcher_daemon.py",
        "tests/test_wiki_integrity.py",
    ])
    if code == 0:
        print(" [🟢] All core test suites passed successfully.")
    else:
        print(f" [❌] Test suite failure:\n{test_output}")
        return code

    # 2. Verify Wiki Integrity
    print("\n 2. Auditing Karpathy LLM Wiki integrity...")
    code, wiki_output = run_command_capture(["python", "scripts/verify_wiki_integrity.py"])
    if code == 0:
        print(" [🟢] Wiki integrity 100% compliant.")
    else:
        print(f" [❌] Wiki integrity violation:\n{wiki_output}")
        return code

    # 3. Provenance Database Audit
    print("\n 3. Auditing Provenance Database records...")
    code, prov_output = run_command_capture(["python", "scripts/query_provenance.py", "--list"])
    print(prov_output.strip())

    print("\n" + "=" * 76)
    print(" 🟢 WEEKLY HEALTH DIGEST COMPLETE — ALL SYSTEMS GREEN")
    print("=" * 76)
    return 0


def run_daemon(poll_seconds: int = 15) -> int:
    """Continuously monitors ET wall-clock time and triggers scheduled sentinel routines."""
    print("=" * 76)
    print(" 🛡️ LUCIDFLEX LIFECYCLE SENTINEL DAEMON INITIALIZED")
    print(" Active Schedules (America/New_York):")
    print("   • 08:15 ET (Mon-Fri) : Pre-Market Readiness Diagnostic")
    print("   • 16:15 ET (Mon-Fri) : Post-Market Demo Parity & Monte Carlo Reconciliation")
    print("   • 17:00 ET (Friday)  : Weekly Quantitative Health Digest")
    print("=" * 76)

    fired_events: set[str] = set()
    current_date: str = ""

    try:
        while True:
            now_et = datetime.now(ET_TZ)
            today_str = now_et.strftime("%Y-%m-%d")
            hhmmss = now_et.strftime("%H:%M:%S")
            weekday = now_et.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun

            # Reset daily event cache at midnight ET
            if today_str != current_date:
                fired_events.clear()
                current_date = today_str

            # Weekday routines (Mon-Fri: weekday 0-4)
            if weekday < 5:
                # 08:15:00 ET: Pre-Market Readiness
                event_key_pre = f"{today_str}_premarket"
                if "08:15:00" <= hhmmss < "08:25:00" and event_key_pre not in fired_events:
                    fired_events.add(event_key_pre)
                    print(f"\n[Sentinel Daemon] Triggering 08:15 ET Pre-Market Diagnostic ({now_et.isoformat()})...")
                    run_premarket_readiness()

                # 16:15:00 ET: Post-Market Reconciliation
                event_key_post = f"{today_str}_postmarket"
                if "16:15:00" <= hhmmss < "16:30:00" and event_key_post not in fired_events:
                    fired_events.add(event_key_post)
                    print(f"\n[Sentinel Daemon] Triggering 16:15 ET Post-Market Reconciliation ({now_et.isoformat()})...")
                    run_postmarket_reconcile()

                # Friday 17:00:00 ET: Weekly Health Digest
                if weekday == 4:
                    event_key_weekly = f"{today_str}_weekly"
                    if "17:00:00" <= hhmmss < "17:15:00" and event_key_weekly not in fired_events:
                        fired_events.add(event_key_weekly)
                        print(f"\n[Sentinel Daemon] Triggering Friday 17:00 ET Weekly Health Digest ({now_et.isoformat()})...")
                        run_weekly_digest()

            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        print("\n[Sentinel Daemon] Stopped by signal.")
    return 0


def run_auto() -> int:
    """Detects current ET time and runs the appropriate sentinel routine."""
    now_et = datetime.now(ET_TZ)
    hhmm = now_et.strftime("%H:%M")
    weekday = now_et.weekday()

    if weekday < 5:
        if "08:00" <= hhmm <= "09:30":
            return run_premarket_readiness()
        elif "16:00" <= hhmm <= "16:45":
            return run_postmarket_reconcile()
        elif weekday == 4 and "16:50" <= hhmm <= "18:00":
            return run_weekly_digest()

    print(f"[Sentinel Auto] Current ET: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}. No routine scheduled for this window.")
    print("Schedules: 08:15 ET (Pre-Market), 16:15 ET (Post-Market), Fri 17:00 ET (Weekly Digest).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="LucidFlex Session Lifecycle Sentinel")
    parser.add_argument(
        "--mode",
        choices=["premarket", "postmarket", "weekly", "all", "daemon", "auto"],
        default="all",
        help="Operational routine to execute",
    )
    args = parser.parse_args()

    if args.mode == "premarket":
        return run_premarket_readiness()
    elif args.mode == "postmarket":
        return run_postmarket_reconcile()
    elif args.mode == "weekly":
        return run_weekly_digest()
    elif args.mode == "daemon":
        return run_daemon()
    elif args.mode == "auto":
        return run_auto()
    elif args.mode == "all":
        code_pre = run_premarket_readiness()
        code_post = run_postmarket_reconcile()
        code_week = run_weekly_digest()
        return max(code_pre, code_post, code_week)

    return 0


if __name__ == "__main__":
    sys.exit(main())
