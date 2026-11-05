"""
Unit tests for LucidFlex 25K Demo Parity & Slippage Journal.
Verifies all mathematical formulas, slippage calculations, rulebook logic, and persistence.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import pytest
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


def test_resolve_instrument():
    mnq = resolve_instrument("MNQ")
    assert mnq.symbol == "MNQ"
    assert mnq.point_value == 2.00
    assert mnq.tick_size == 0.25
    assert mnq.tick_value == 0.50
    assert mnq.default_commission_rt == 1.40

    mes = resolve_instrument("MES")
    assert mes.symbol == "MES"
    assert mes.point_value == 5.00
    assert mes.tick_value == 1.25


def test_long_trade_slippage_and_pnl():
    # Long trade on MNQ (3 contracts)
    # Theo Entry: 20450.00, Actual Entry Fill: 20450.75 (+0.75 pts adverse = +3 ticks)
    # Theo Target: 20525.00, Actual Exit Fill: 20525.00 (0.00 slip)
    # Commission: 3 * $1.40 = $4.20
    trade = TradeFillRecord(
        date="2026-10-28",
        symbol="MNQ",
        direction="LONG",
        contracts=3,
        theo_entry_price=20450.00,
        actual_entry_fill=20450.75,
        theo_stop_price=20400.00,
        theo_target_price=20525.00,
        exit_type="PROFIT_TARGET_1_5R",
        actual_exit_fill=20525.00,
    )

    assert trade.entry_slippage_pts == 0.75
    assert trade.entry_slippage_ticks == 3.0
    assert trade.entry_slippage_dollars == pytest.approx(0.75 * 2.00 * 3)  # $4.50
    assert trade.exit_slippage_pts == 0.0
    assert trade.exit_slippage_ticks == 0.0
    assert trade.total_slippage_dollars == pytest.approx(4.50)

    # Realized points = 20525.00 - 20450.75 = 74.25 pts
    assert trade.realized_points == 74.25
    assert trade.gross_pnl == pytest.approx(74.25 * 2.00 * 3)  # $445.50
    assert trade.commission == pytest.approx(4.20)
    assert trade.net_pnl == pytest.approx(445.50 - 4.20)  # $441.30

    # Theo points = 20525.00 - 20450.00 = 75.00 pts ($450 gross - $4.20 = $445.80)
    assert trade.theo_points == 75.00
    assert trade.theo_net_pnl == pytest.approx(450.00 - 4.20)  # $445.80
    assert trade.execution_drag_dollars == pytest.approx(441.30 - 445.80)  # -$4.50


def test_short_trade_slippage_and_pnl():
    # Short trade on MNQ (2 contracts)
    # Theo Entry: 20500.00, Actual Fill: 20499.50 (+0.50 pts adverse = +2 ticks)
    # Stop Loss Hit: Theo Stop: 20550.00, Actual Stop Fill: 20551.00 (+1.00 pt adverse = +4 ticks)
    # Total slippage: 0.50 + 1.00 = 1.50 pts * $2 * 2 = $6.00 adverse
    trade = TradeFillRecord(
        date="2026-10-28",
        symbol="MNQ",
        direction="SHORT",
        contracts=2,
        theo_entry_price=20500.00,
        actual_entry_fill=20499.50,
        theo_stop_price=20550.00,
        theo_target_price=20425.00,
        exit_type="STOP_LOSS",
        actual_exit_fill=20551.00,
    )

    assert trade.entry_slippage_pts == 0.50
    assert trade.entry_slippage_ticks == 2.0
    assert trade.exit_slippage_pts == 1.00
    assert trade.exit_slippage_ticks == 4.0
    assert trade.total_slippage_dollars == pytest.approx(6.00)

    # Realized points = 20499.50 - 20551.00 = -51.50 pts
    assert trade.realized_points == -51.50
    assert trade.gross_pnl == pytest.approx(-51.50 * 2.00 * 2)  # -$206.00
    assert trade.commission == pytest.approx(2.80)
    assert trade.net_pnl == pytest.approx(-208.80)

    # Theo net pnl = (-50.00 * 4) - 2.80 = -$202.80
    assert trade.theo_net_pnl == pytest.approx(-202.80)
    assert trade.execution_drag_dollars == pytest.approx(-6.00)


def test_journal_account_progression_and_ratchet():
    with tempfile.TemporaryDirectory() as tmp_dir:
        journal = DemoParityJournal(forward_test_dir=Path(tmp_dir))

        # Initial State
        st0 = journal.get_eval_state()
        assert st0.balance == 25_000.0
        assert st0.peak_balance == 25_000.0
        assert st0.trailing_floor == 24_000.0
        assert st0.status == "ACTIVE"
        assert st0.recommended_micros == 2
        assert "Tier 1" in st0.recommended_tier

        # Trade 1: +$400 profit -> profit reaches $400 (>= $200), moves to Tier 2 (3 micros)
        t1 = TradeFillRecord(
            date="2026-10-28",
            symbol="MNQ",
            direction="LONG",
            contracts=2,
            theo_entry_price=20450.00,
            actual_entry_fill=20450.00,
            theo_stop_price=20400.00,
            theo_target_price=20550.00,
            exit_type="PROFIT_TARGET_1_5R",
            actual_exit_fill=20551.40,  # +$400 net approx
        )
        st1 = journal.record_trade(t1)
        assert st1.balance > 25_400.0
        assert st1.peak_balance == st1.balance
        assert st1.trailing_floor == pytest.approx(st1.balance - 1000.0)
        assert st1.recommended_micros == 3
        assert "Tier 2" in st1.recommended_tier

        # Trade 2: +$400 more profit -> total profit > $800 (>= $500) -> Tier 3 (4 micros)
        t2 = TradeFillRecord(
            date="2026-10-29",
            symbol="MNQ",
            direction="LONG",
            contracts=3,
            theo_entry_price=20450.00,
            actual_entry_fill=20450.00,
            theo_stop_price=20400.00,
            theo_target_price=20520.00,
            exit_type="PROFIT_TARGET_1_5R",
            actual_exit_fill=20520.00,
        )
        st2 = journal.record_trade(t2)
        assert st2.profit >= 500.0
        assert st2.recommended_micros == 4
        assert "Tier 3" in st2.recommended_tier


def test_trailing_floor_locks_at_25100():
    with tempfile.TemporaryDirectory() as tmp_dir:
        journal = DemoParityJournal(forward_test_dir=Path(tmp_dir))

        # Big win that pushes peak balance to $26,150
        t1 = TradeFillRecord(
            date="2026-10-28",
            symbol="MNQ",
            direction="LONG",
            contracts=10,
            theo_entry_price=20000.00,
            actual_entry_fill=20000.00,
            theo_stop_price=19950.00,
            theo_target_price=20060.00,
            exit_type="PROFIT_TARGET_1_5R",
            actual_exit_fill=20060.00,  # 60 pts * $2 * 10 = $1200 gross - $14 = $1186 net
        )
        st1 = journal.record_trade(t1)
        assert st1.balance == pytest.approx(26_186.0)
        assert st1.peak_balance == pytest.approx(26_186.0)
        # Peak >= $26,100 -> trailing floor locks at $25,100.00
        assert st1.trailing_floor == 25_100.0


def test_passing_target_reached():
    with tempfile.TemporaryDirectory() as tmp_dir:
        journal = DemoParityJournal(forward_test_dir=Path(tmp_dir))

        # Trade that reaches +$1,300 profit (Balance: $26,300 >= $26,250)
        t = TradeFillRecord(
            date="2026-10-28",
            symbol="MNQ",
            direction="LONG",
            contracts=4,
            theo_entry_price=20000.00,
            actual_entry_fill=20000.00,
            theo_stop_price=19950.00,
            theo_target_price=20165.00,
            exit_type="PROFIT_TARGET_1_5R",
            actual_exit_fill=20165.00,  # 165 pts * $2 * 4 = $1320 - $5.60 = $1314.40 net
        )
        st = journal.record_trade(t)
        assert st.balance >= 26_250.0
        assert st.status == "PASSED"
        assert "PROFIT TARGET PASSED" in st.status_reason


def test_daily_soft_stop_halt():
    with tempfile.TemporaryDirectory() as tmp_dir:
        journal = DemoParityJournal(forward_test_dir=Path(tmp_dir))

        # Big loss on the same day that exceeds -$600
        t = TradeFillRecord(
            date="2026-10-28",
            symbol="MNQ",
            direction="LONG",
            contracts=4,
            theo_entry_price=20000.00,
            actual_entry_fill=20000.00,
            theo_stop_price=19920.00,
            theo_target_price=20100.00,
            exit_type="STOP_LOSS",
            actual_exit_fill=19920.00,  # -80 pts * $2 * 4 = -$640 gross - comm = -$645.60
        )
        st = journal.record_trade(t)
        assert st.current_date_pnl <= -600.0
        assert st.status == "DAILY_HALTED"
        assert "DAILY SOFT STOP HIT" in st.status_reason


def test_trailed_out():
    with tempfile.TemporaryDirectory() as tmp_dir:
        journal = DemoParityJournal(forward_test_dir=Path(tmp_dir))

        # Massive loss that drops below $24,000 floor
        t = TradeFillRecord(
            date="2026-10-28",
            symbol="MNQ",
            direction="LONG",
            contracts=10,
            theo_entry_price=20000.00,
            actual_entry_fill=20000.00,
            theo_stop_price=19940.00,
            theo_target_price=20100.00,
            exit_type="STOP_LOSS",
            actual_exit_fill=19940.00,  # -60 pts * $2 * 10 = -$1200 -> Balance $23,786 <= $24,000 floor
        )
        st = journal.record_trade(t)
        assert st.balance <= st.trailing_floor
        assert st.status == "TRAILED_OUT"


def test_contract_limit_breach_detection():
    with tempfile.TemporaryDirectory() as tmp_dir:
        journal = DemoParityJournal(forward_test_dir=Path(tmp_dir))

        # Taking 12 micros (illegal: exceeds 10 micros limit)
        t = TradeFillRecord(
            date="2026-10-28",
            symbol="MNQ",
            direction="LONG",
            contracts=12,
            theo_entry_price=20000.00,
            actual_entry_fill=20000.00,
            theo_stop_price=19950.00,
            theo_target_price=20050.00,
            exit_type="PROFIT_TARGET_1_5R",
            actual_exit_fill=20050.00,
        )
        st = journal.record_trade(t)
        assert st.contract_limit_breached is True


def test_session_logging_and_html_generation():
    with tempfile.TemporaryDirectory() as tmp_dir:
        td = Path(tmp_dir)
        journal = DemoParityJournal(forward_test_dir=td)

        # Log a NO-TRADE day with exact MotiveWave marker text
        session = DailySessionRecord(
            date="2026-10-28",
            setup_detected=False,
            setup_fired=False,
            diagnostic_reason="NO TRADE: Inside Prior VA [VAL: 20420.00 | VAH: 20480.00 | Close: 20450.00]",
        )
        journal.record_session(session)

        sessions_df = journal.load_sessions_df()
        assert len(sessions_df) == 1
        assert "Inside Prior VA" in sessions_df["diagnostic_reason"].iloc[0]

        html_path = journal.generate_html_dashboard()
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        assert "LucidFlex 25K" in content or "LUCIDFLEX 25K" in content
        assert "Inside Prior VA" in content
