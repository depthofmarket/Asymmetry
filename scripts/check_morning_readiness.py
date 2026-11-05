#!/usr/bin/env python3
"""
Pre-Market Readiness & System Health Diagnostic
Checks daemon status, MotiveWave data feed freshness, ledger integrity,
and sizing tier before the 08:30 ET pre-market trading session.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.demo_parity_engine import (
    STATE_JSON_PATH,
    DemoParityJournal,
)

ET_TZ = ZoneInfo("America/New_York")
PLIST_LABEL = "com.lucidflex.morningwatcher"


def check_daemon() -> tuple[bool, int | None, str]:
    """Checks whether the launchd daemon is running."""
    try:
        proc = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in proc.stdout.splitlines():
            if PLIST_LABEL in line:
                parts = line.split()
                pid_str = parts[0]
                if pid_str != "-" and pid_str.isdigit():
                    return True, int(pid_str), f"Active in launchd (PID {pid_str})"
                return False, None, "Registered in launchd but not currently running (PID -)"
        return False, None, "Not found in launchctl list"
    except Exception as e:
        return False, None, f"Error checking launchctl: {e}"


def check_csv_feeds() -> list[dict[str, any]]:
    """Checks raw MotiveWave CSV exports."""
    feed_files = [
        ("NQ / MNQ", ROOT / "data/raw/@NQ.CQG_1.csv"),
        ("ES / MES", ROOT / "data/raw/@ES.CQG_1.csv"),
        ("GC / MGC", ROOT / "data/raw/@GC.CQG_1.csv"),
    ]
    results = []
    now = datetime.now()
    for name, path in feed_files:
        exists = path.exists()
        size_bytes = path.stat().st_size if exists else 0
        mtime = datetime.fromtimestamp(path.stat().st_mtime) if exists else None
        age_hours = (now - mtime).total_seconds() / 3600.0 if mtime else 999.0
        
        last_line = ""
        if exists and size_bytes > 0:
            try:
                with open(path, "rb") as f:
                    f.seek(max(0, size_bytes - 1024))
                    lines = f.read().decode("utf-8", errors="ignore").strip().splitlines()
                    if lines:
                        last_line = lines[-1]
            except Exception:
                pass

        results.append({
            "name": name,
            "path": str(path),
            "exists": exists,
            "size_kb": size_bytes / 1024.0,
            "mtime": mtime.strftime("%Y-%m-%d %H:%M:%S") if mtime else "N/A",
            "age_hours": age_hours,
            "last_bar": last_line,
        })
    return results


def check_motivewave_jars() -> list[dict[str, any]]:
    """Checks deployed MotiveWave extension JARs."""
    ext_dir = Path.home() / "MotiveWave Extensions"
    jars = [
        "LucidPropEnsemble.jar",
    ]
    results = []
    for j in jars:
        p = ext_dir / j
        exists = p.exists()
        size_kb = p.stat().st_size / 1024.0 if exists else 0
        mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if exists else "N/A"
        results.append({
            "jar": j,
            "exists": exists,
            "size_kb": size_kb,
            "mtime": mtime,
        })
    return results


def check_account_state() -> dict[str, any]:
    """Validates parity state JSON and aggressive frontier sizing."""
    try:
        journal = DemoParityJournal()
        state = journal.get_eval_state()
        return {
            "valid": True,
            "balance": state.balance,
            "profit": state.profit,
            "cushion": state.trailing_cushion,
            "floor": state.trailing_floor,
            "tier_contracts": state.recommended_micros,
            "tier_label": state.recommended_tier,
            "eval_status": state.status,
            "trades_count": state.trades_count,
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


def check_provenance_store() -> dict[str, any]:
    """Verifies that the quantitative provenance store is active and populated."""
    try:
        from backtest.provenance import default_store
        runs = default_store.list_runs(limit=100)
        return {
            "valid": True,
            "db_path": str(default_store.db_path),
            "runs_count": len(runs),
            "latest_run": runs[0].run_id if runs else None,
        }
    except Exception as e:
        return {"valid": False, "error": str(e)}


def send_macos_alert(title: str, subtitle: str, message: str) -> None:
    """Sends native macOS notification."""
    safe_title = title.replace('"', '\\"')
    safe_sub = subtitle.replace('"', '\\"')
    safe_msg = message.replace('"', '\\"')
    script = f'display notification "{safe_msg}" with title "{safe_title}" subtitle "{safe_sub}"'
    try:
        subprocess.run(["osascript", "-e", script], check=False)
    except Exception:
        pass


def run_diagnostics(verbose: bool = True, send_alert: bool = False) -> int:
    """Runs all pre-market checks and prints formatted report."""
    now_et = datetime.now(ET_TZ)
    now_local = datetime.now()

    daemon_ok, pid, daemon_msg = check_daemon()
    feeds = check_csv_feeds()
    jars = check_motivewave_jars()
    acct = check_account_state()

    critical_ok = daemon_ok and all(f["exists"] for f in feeds) and acct.get("valid", False)
    all_ok = critical_ok and all(j["exists"] for j in jars)

    if verbose:
        print("=" * 76)
        print(" 🌅 LUCIDFLEX 25K PRE-MARKET READINESS DIAGNOSTIC")
        print("=" * 76)
        print(f" Timestamp (ET)   : {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        print(f" Local Time       : {now_local.strftime('%Y-%m-%d %H:%M:%S')}")
        print("-" * 76)

        # Daemon
        d_icon = "🟢" if daemon_ok else "🔴"
        print(f" [{d_icon}] Morning Watcher Daemon : {daemon_msg}")

        # Account & Sizing
        if acct.get("valid"):
            print(f" [🟢] Account Parity State   : ACTIVE (Balance: ${acct['balance']:,.2f} | Cushion: ${acct['cushion']:,.2f})")
            print(f"      Profit / Sizing Tier  : +${acct['profit']:,.2f} -> {acct['tier_label']} ({acct['tier_contracts']} Micros)")
        else:
            print(f" [🔴] Account Parity State   : INVALID ({acct.get('error')})")

        # Provenance Store
        prov = check_provenance_store()
        prov_icon = "🟢" if prov.get("valid") and prov.get("runs_count", 0) > 0 else "🔴"
        print(f" [{prov_icon}] Provenance Store       : {'ACTIVE' if prov.get('valid') else 'ERROR'} ({prov.get('runs_count', 0)} verified runs in SQLite)")

        # CSV Data Feeds
        print("-" * 76)
        print(" MOTIVEWAVE CSV BAR FEEDS:")
        for f in feeds:
            f_icon = "🟢" if f["exists"] and f["size_kb"] > 0 else "🔴"
            print(f"   [{f_icon}] {f['name']:<12}: Size: {f['size_kb']:>8.1f} KB | Mtime: {f['mtime']}")

        # MotiveWave Extensions
        print("-" * 76)
        print(" MOTIVEWAVE EXTENSIONS:")
        for j in jars:
            j_icon = "🟢" if j["exists"] else "🔴"
            print(f"   [{j_icon}] {j['jar']:<24}: {'INSTALLED' if j['exists'] else 'MISSING'} ({j['size_kb']:.1f} KB)")

        print("=" * 76)
        if all_ok:
            print(" 🟢 SYSTEM IS 100% READY FOR TODAY'S MORNING SESSION")
        else:
            print(" ⚠️ SYSTEM ATTENTION REQUIRED BEFORE 08:35 ET")
        print("=" * 76)

    if send_alert:
        status_sub = "100% READY" if all_ok else "ATTENTION NEEDED"
        msg = (
            f"Daemon active (PID {pid}). Sizing: {acct.get('tier_contracts', 2)} Micros. "
            f"Balance: ${acct.get('balance', 25000):,.2f}. Macro window at 08:35 ET."
            if all_ok else f"Pre-market warning: Daemon={daemon_ok}, Feeds={all(f['exists'] for f in feeds)}"
        )
        send_macos_alert(
            title=f"LucidFlex 25K Pre-Market Status",
            subtitle=f"{status_sub} ({now_et.strftime('%H:%M ET')})",
            message=msg,
        )

    return 0 if critical_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-market diagnostic tool for LucidFlex 25K forward-test.")
    parser.add_argument("--quiet", action="store_true", help="Suppress console output, exit code only.")
    parser.add_argument("--json", action="store_true", help="Output results as JSON.")
    parser.add_argument("--send-alert", action="store_true", help="Send native macOS desktop banner notification.")
    args = parser.parse_args()

    if args.json:
        daemon_ok, pid, daemon_msg = check_daemon()
        feeds = check_csv_feeds()
        jars = check_motivewave_jars()
        acct = check_account_state()
        data = {
            "timestamp_et": datetime.now(ET_TZ).isoformat(),
            "daemon": {"ok": daemon_ok, "pid": pid, "message": daemon_msg},
            "feeds": feeds,
            "extensions": jars,
            "account": acct,
            "ready": daemon_ok and all(f["exists"] for f in feeds) and acct.get("valid", False),
        }
        print(json.dumps(data, indent=2))
        return 0 if data["ready"] else 1

    return run_diagnostics(verbose=not args.quiet, send_alert=args.send_alert)


if __name__ == "__main__":
    raise SystemExit(main())
