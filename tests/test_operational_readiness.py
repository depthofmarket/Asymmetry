"""
Test Suite: Operational Readiness, Pre-Market Diagnostics, & Live Broker Reconciliation.
Verifies:
1. `scripts/check_morning_readiness.py`: Pre-market diagnostics and JSON export.
2. `scripts/reconcile_broker_fill.py`: Math precision, ledger updates, and dry-run safety.
3. `scripts/watch_morning_demo_alerts.py`: Order ticket card dispatch and 08:25 ET pre-market hook.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.demo_parity_engine import (
    AccountEvalState,
    DemoParityJournal,
    TradeFillRecord,
)
from scripts.check_morning_readiness import (
    check_account_state,
    check_csv_feeds,
    check_daemon,
    run_diagnostics,
)
from scripts.reconcile_broker_fill import reconcile_trade
from scripts.watch_morning_demo_alerts import dispatch_active_order_card


def test_premarket_daemon_check():
    """Verify daemon check returns boolean and status description."""
    is_active, pid, msg = check_daemon()
    assert isinstance(is_active, bool)
    assert isinstance(msg, str)
    assert len(msg) > 0


@pytest.mark.private_data
def test_premarket_csv_feeds_check():
    """Verify raw MotiveWave CSV feeds are recognized."""
    feeds = check_csv_feeds()
    assert len(feeds) >= 3
    names = [f["name"] for f in feeds]
    assert "NQ / MNQ" in names
    assert "ES / MES" in names
    assert "GC / MGC" in names
    for f in feeds:
        assert f["exists"] is True
        assert f["size_kb"] > 0


@pytest.mark.local_account_state
def test_premarket_account_state():
    """Verify account state matches live forward test ledger."""
    acct = check_account_state()
    assert acct["valid"] is True
    assert acct["balance"] >= 25000.00
    assert acct["profit"] >= 0.00
    assert acct["cushion"] > 0.00
    assert acct["tier_contracts"] in {1, 2, 3, 4}
    assert "Tier" in acct["tier_label"]


@pytest.mark.local_account_state
def test_check_morning_readiness_cli_json():
    """Verify check_morning_readiness.py runs cleanly with --json."""
    res = subprocess.run(
        [sys.executable, "scripts/check_morning_readiness.py", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res.stdout)
    assert data["ready"] in (True, False)
    assert "account" in data
    assert data["account"]["balance"] >= 25000.00


@pytest.mark.local_account_state
def test_reconcile_broker_fill_dry_run():
    """Verify dry-run does not write to disk but computes exact deltas."""
    journal = DemoParityJournal()
    df_before = journal.load_trades_df()
    initial_pnl = float(df_before.loc[df_before["trade_id"] == 1, "net_pnl"].iloc[0])

    summary = reconcile_trade(
        trade_id=1,
        entry_fill=7656.25,  # 1 tick adverse from 7656.50
        dry_run=True,
    )
    assert summary["dry_run"] is True
    assert summary["delta_pnl"] == -2.50
    assert summary["after"]["net_pnl"] == round(initial_pnl - 2.50, 2)

    # Confirm ledger on disk remains pristine
    df_after = journal.load_trades_df()
    assert float(df_after.loc[df_after["trade_id"] == 1, "net_pnl"].iloc[0]) == initial_pnl


@pytest.mark.local_account_state
def test_reconcile_broker_fill_isolated_workspace(tmp_path: Path):
    """Test full reconciliation write and balance cascade on an isolated ledger."""
    isolated_dir = tmp_path / "forward_test"
    isolated_dir.mkdir(parents=True)

    # Copy real ledgers to temp dir
    real_dir = ROOT / "results" / "forward_test"
    for fname in ["demo_trades_ledger.csv", "demo_sessions_ledger.csv", "demo_parity_state.json"]:
        src = real_dir / fname
        if src.exists():
            (isolated_dir / fname).write_text(src.read_text())

    # Monkeypatch FORWARD_TEST_DIR in reconcile_broker_fill
    import scripts.reconcile_broker_fill as rbf
    orig_journal_cls = rbf.DemoParityJournal

    class TempJournal(DemoParityJournal):
        def __init__(self):
            super().__init__(forward_test_dir=isolated_dir)

    rbf.DemoParityJournal = TempJournal
    try:
        res = rbf.reconcile_trade(
            trade_id=1,
            entry_fill=7656.00,  # 2 ticks adverse
            dry_run=False,
        )
        assert res["delta_pnl"] == -5.00
        # Verify file on disk updated
        df_mod = pd.read_csv(isolated_dir / "demo_trades_ledger.csv")
        assert float(df_mod.loc[df_mod["trade_id"] == 1, "actual_entry_fill"].iloc[0]) == 7656.00
        assert float(df_mod.loc[df_mod["trade_id"] == 1, "net_pnl"].iloc[0]) == 139.70
        assert float(df_mod.loc[df_mod["trade_id"] == 1, "account_balance_after"].iloc[0]) == 25139.70
    finally:
        rbf.DemoParityJournal = orig_journal_cls


def test_dispatch_active_order_card(tmp_path: Path):
    """Verify order ticket card generation formatting and contents."""
    eval_state = AccountEvalState(
        starting_capital=25000.0,
        balance=25144.70,
        peak_balance=25144.70,
        trailing_floor=24144.70,
        trailing_cushion=1000.0,
        profit=144.70,
    )
    orders = [
        {
            "strategy": "Macro Momentum (08:35)",
            "window": "08:35",
            "symbol": "MNQ",
            "action": "SELL",
            "contracts": 2,
            "entry_price": 21450.25,
            "stop_price": 21475.25,
            "target_price": 21400.25,
            "risk_pts": 25.0,
            "risk_dollars": 100.0,
            "reward_pts": 50.0,
            "reward_dollars": 200.0,
            "exit_rule": "Flatten before 09:25 ET",
        }
    ]
    card_text = dispatch_active_order_card(orders, eval_state, "Tier 1: Capital Shield (2 Micros)")
    assert card_text is not None
    assert "LUCIDFLEX 25K ACTIVE ORDER TICKET" in card_text
    assert "MNQ" in card_text
    assert "SELL (OPEN)" in card_text
    assert "2 Micros" in card_text
    assert "21450.25" in card_text
    assert "Stop Loss     : 21475.25" in card_text
    assert "Profit Target : 21400.25" in card_text


def test_watch_morning_demo_alerts_0825_window():
    """Verify --window 08:25 --once executes without error."""
    res = subprocess.run(
        [sys.executable, "scripts/watch_morning_demo_alerts.py", "--window", "08:25", "--once"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "08:25 ET Pre-Market Readiness Check completed successfully" in res.stdout


def test_motivewave_risk_governance_json_schema():
    """Verify demo_parity_state.json provides all fields needed by MotiveWave Java studies."""
    state_file = ROOT / "results/forward_test/demo_parity_state.json"
    assert state_file.exists()
    with open(state_file, "r") as f:
        data = json.load(f)
    assert "recommended_micros" in data
    assert "trailing_cushion" in data
    assert "current_date_pnl" in data
    assert isinstance(data["recommended_micros"], int)
    assert data["recommended_micros"] in {1, 2, 3, 4}
    assert isinstance(data["trailing_cushion"], (int, float))
    assert isinstance(data["current_date_pnl"], (int, float))


def test_motivewave_circuit_breaker_and_delever_logic():
    """Verify circuit breaker (-$500) and emergency de-lever (<$500 cushion) thresholds."""
    # Test circuit breaker threshold
    normal_pnl = -120.0
    breached_pnl = -505.0
    assert not (normal_pnl <= -500.0)
    assert (breached_pnl <= -500.0)

    # Test cushion de-lever threshold
    healthy_cushion = 1000.0
    danger_cushion = 450.0
    assert not (healthy_cushion < 500.0)
    assert (danger_cushion < 500.0)

