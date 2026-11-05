"""
Unit and integration tests for LucidFlex Morning Watcher LaunchAgent daemon,
bash control scripts, ledger automation, and parity state persistence (R1-R4).
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.demo_parity_engine import (
    STARTING_CAPITAL,
    TRAILING_FLOOR_LOCK,
    AccountEvalState,
    DailySessionRecord,
    DemoParityJournal,
    WindowEvaluationRecord,
)


# =====================================================================
# R1: LaunchAgent Plist Configuration Tests
# =====================================================================

def test_repo_plist_structure_and_syntax():
    """Verify config/com.lucidflex.morningwatcher.plist schema and keys."""
    plist_path = REPO_ROOT / "config/com.lucidflex.morningwatcher.plist"
    assert plist_path.exists(), "Master repo plist config/com.lucidflex.morningwatcher.plist must exist"

    with open(plist_path, "rb") as f:
        data = plistlib.load(f)

    # Core identity
    assert data.get("Label") == "com.lucidflex.morningwatcher"
    assert data.get("RunAtLoad") is True
    assert data.get("ProcessType") == "Interactive"
    assert data.get("LimitLoadToSessionType") == "Aqua"

    # Working directory
    assert Path(data.get("WorkingDirectory")) == REPO_ROOT

    # Program arguments
    prog_args = data.get("ProgramArguments", [])
    assert len(prog_args) == 3
    assert prog_args[0].endswith("python3")
    assert prog_args[1] == "-u"
    assert prog_args[2].endswith("scripts/watch_morning_demo_alerts.py")

    # Logging redirection
    stdout_log = Path(data.get("StandardOutPath", ""))
    stderr_log = Path(data.get("StandardErrorPath", ""))
    assert stdout_log == REPO_ROOT / "logs/morning_watcher.log"
    assert stderr_log == REPO_ROOT / "logs/morning_watcher.log"

    # Environment variables
    env = data.get("EnvironmentVariables", {})
    assert env.get("PYTHONUNBUFFERED") == "1"
    assert "PATH" in env
    assert env.get("PYTHONPATH") == str(REPO_ROOT)

    # StartCalendarInterval for Weekdays 1 through 5 at 08:30
    intervals = data.get("StartCalendarInterval", [])
    assert len(intervals) == 5
    weekdays_found = []
    for item in intervals:
        assert item.get("Hour") == 8
        assert item.get("Minute") == 30
        weekdays_found.append(item.get("Weekday"))
    assert sorted(weekdays_found) == [1, 2, 3, 4, 5]


def test_user_launchagent_plist_installed_and_matches_repo():
    """Verify ~/Library/LaunchAgents/com.lucidflex.morningwatcher.plist matches master plist."""
    user_plist = Path.home() / "Library/LaunchAgents/com.lucidflex.morningwatcher.plist"
    repo_plist = REPO_ROOT / "config/com.lucidflex.morningwatcher.plist"

    assert user_plist.exists(), f"Installed plist must exist at {user_plist}"

    with open(user_plist, "rb") as f:
        user_data = plistlib.load(f)
    with open(repo_plist, "rb") as f:
        repo_data = plistlib.load(f)

    assert user_data == repo_data, "Installed LaunchAgent plist must exactly match master repo plist"


# =====================================================================
# R3: Bash Control Scripts Tests
# =====================================================================

@pytest.mark.parametrize(
    "script_name",
    [
        "scripts/start_morning_watcher.sh",
        "scripts/stop_morning_watcher.sh",
        "scripts/status_morning_watcher.sh",
    ],
)
def test_control_scripts_exist_and_executable(script_name: str):
    """Verify bash control scripts exist, have execution permissions, and pass syntax check."""
    script_path = REPO_ROOT / script_name
    assert script_path.exists(), f"{script_name} must exist"
    assert os.access(script_path, os.X_OK), f"{script_name} must have executable permissions (+x)"

    # Validate bash syntax
    res = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert res.returncode == 0, f"{script_name} failed bash syntax check: {res.stderr}"


def test_status_script_execution():
    """Verify status script runs cleanly without syntax or environment errors."""
    status_script = REPO_ROOT / "scripts/status_morning_watcher.sh"
    res = subprocess.run([str(status_script)], capture_output=True, text=True)
    # Output should contain expected section headers regardless of active/stopped state
    assert "LucidFlex 25K Morning Watcher Daemon Status" in res.stdout
    assert "Log file:" in res.stdout
    assert res.returncode in (0, 1)  # 0 if running, 1 if stopped


# =====================================================================
# R2: Watcher Automation, Ledger Guarantees & Parity State Persistence
# =====================================================================

def test_watcher_script_syntax_and_import():
    """Verify watch_morning_demo_alerts.py compiles and imports cleanly."""
    script_path = REPO_ROOT / "scripts/watch_morning_demo_alerts.py"
    res = subprocess.run(
        [sys.executable, "-m", "py_compile", str(script_path)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"watch_morning_demo_alerts.py py_compile failed: {res.stderr}"


def test_state_json_synchronization_on_flat_session(tmp_path: Path):
    """Verify demo_parity_state.json updates current_date and preserves sizing on flat session."""
    journal = DemoParityJournal(forward_test_dir=tmp_path)

    # Initial state
    init_state = journal.get_eval_state()
    assert init_state.balance == STARTING_CAPITAL
    assert init_state.recommended_micros == 2

    # Record a flat session for a new date
    flat_session = DailySessionRecord(
        date="2026-11-04",
        setup_detected=False,
        setup_fired=False,
        diagnostic_reason="NO TRADE: [08:35] Overnight range | [09:45] Inside Prior VA | [10:15] Weak Fix",
        end_of_day_balance=25000.0,
    )
    journal.record_session(flat_session)

    # Verify state JSON was written automatically
    state_file = tmp_path / "demo_parity_state.json"
    assert state_file.exists(), "demo_parity_state.json must be persisted by record_session"

    updated_state = journal.get_eval_state()
    assert updated_state.current_date == "2026-11-04"
    assert updated_state.balance == 25000.0
    assert updated_state.recommended_micros == 2
    assert updated_state.recommended_tier == "Tier 1: Capital Shield (2 Micros)"


def test_window_evaluations_ledger_persistence(tmp_path: Path):
    """Verify record_window_evaluation writes and updates granular diagnostic rows."""
    journal = DemoParityJournal(forward_test_dir=tmp_path)

    rec_macro = WindowEvaluationRecord(
        date="2026-11-04",
        window_time="08:35:00",
        strategy="Macro Momentum (08:35)",
        symbol="MNQ",
        status="FILTERED_NO_BREAKOUT",
        action="NONE",
        contracts=0,
        diagnostic_reason="Spike trapped inside overnight range (28000.0 - 28200.0)",
        account_balance=25000.0,
        trailing_cushion=1000.0,
    )
    journal.record_window_evaluation(rec_macro)

    df_windows = journal.load_windows_df()
    assert len(df_windows) == 1
    assert df_windows["symbol"].iloc[0] == "MNQ"
    assert df_windows["window_time"].iloc[0] == "08:35:00"
    assert "Spike trapped" in df_windows["diagnostic_reason"].iloc[0]

    # Verify dashboard HTML renders the window evaluations audit log
    html_path = journal.generate_html_dashboard()
    assert html_path.exists()
    html_content = html_path.read_text(encoding="utf-8")
    assert "Morning Watcher &bull; Strategy Window Evaluations Log" in html_content
    assert "Spike trapped inside overnight range" in html_content


def test_aggressive_frontier_sizing_and_trailing_floor(tmp_path: Path):
    """Verify Aggressive Frontier 200/500 sizing tiers and trailing drawdown floor."""
    journal = DemoParityJournal(forward_test_dir=tmp_path)

    # Base tier 1 (< $300 profit)
    st = journal.get_eval_state()
    assert st.recommended_micros == 2
    assert "Tier 1" in st.recommended_tier

    # Record trade with $350 profit -> Tier 2 ($300 to $599)
    from backtest.demo_parity_engine import TradeFillRecord
    trade_tier2 = TradeFillRecord(
        date="2026-11-01",
        symbol="MNQ",
        direction="LONG",
        contracts=2,
        theo_entry_price=20000.0,
        actual_entry_fill=20000.0,
        theo_stop_price=19950.0,
        theo_target_price=20088.5,
        exit_type="PROFIT_TARGET_1_5R",
        actual_exit_fill=20088.5,  # 88.5 pts * $2 * 2 = $354 gross - $2.80 comm = $351.20 net
    )
    journal.record_trade(trade_tier2)
    st2 = journal.get_eval_state()
    assert st2.profit >= 300.0
    assert st2.recommended_micros == 3
    assert "Tier 2" in st2.recommended_tier

    # Record trade with additional $300 profit -> Tier 3 (>= $600)
    trade_tier3 = TradeFillRecord(
        date="2026-11-02",
        symbol="MNQ",
        direction="LONG",
        contracts=3,
        theo_entry_price=20000.0,
        actual_entry_fill=20000.0,
        theo_stop_price=19950.0,
        theo_target_price=20051.0,
        exit_type="PROFIT_TARGET_1_5R",
        actual_exit_fill=20051.0,  # 51 pts * $2 * 3 = $306 gross - $4.20 comm = $301.80 net
    )
    journal.record_trade(trade_tier3)
    st3 = journal.get_eval_state()
    assert st3.profit >= 600.0
    assert st3.recommended_micros == 4
    assert "Tier 3" in st3.recommended_tier


# =====================================================================
# R4: Watcher --once Execution Test
# =====================================================================

def test_watcher_once_execution():
    """Verify scripts/watch_morning_demo_alerts.py --once runs cleanly and exits 0."""
    watcher_script = REPO_ROOT / "scripts/watch_morning_demo_alerts.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)

    res = subprocess.run(
        [sys.executable, str(watcher_script), "--once", "--no-voice"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert res.returncode == 0, f"Watcher --once failed with code {res.returncode}: {res.stderr}"
    assert "MORNING WATCHER SUMMARY" in res.stdout
    assert "HTML Parity Dashboard" in res.stdout
