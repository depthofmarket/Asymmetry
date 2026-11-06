"""
Unit tests for MotiveWave CQG Broker Execution Synchronizer (scripts/sync_cqg_executions.py).
Verifies symbol normalization, FIFO lot matching, strategy inference, deduplication,
and reconciliation into the LucidFlex 25K demo parity ledger.
"""

from __future__ import annotations

import csv
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.demo_parity_engine import DemoParityJournal, resolve_instrument
from scripts.sync_cqg_executions import (
    CQGFillEvent,
    ReconstructedBrokerTrade,
    infer_exit_type,
    infer_strategy_from_window,
    normalize_cqg_symbol,
    parse_cqg_fills_from_journal,
    reconstruct_trades_fifo,
    sync_broker_trades_to_ledger,
)

ET_TZ = ZoneInfo("America/New_York")


def test_normalize_cqg_symbol():
    assert normalize_cqg_symbol("MESZ26.CQG") == "MES"
    assert normalize_cqg_symbol("MNQZ26.CQG") == "MNQ"
    assert normalize_cqg_symbol("MGCZ26.CQG") == "MGC"
    assert normalize_cqg_symbol("ENQZ26.CQG") == "NQ"
    assert normalize_cqg_symbol("ESZ26.CQG") == "ES"
    assert normalize_cqg_symbol("MES") == "MES"


def test_infer_strategy_from_window():
    assert infer_strategy_from_window("08:35:10", "MNQ") == "Macro Momentum (08:35)"
    assert infer_strategy_from_window("09:48:14", "MES") == "VA Breakout (v2.0)"
    assert infer_strategy_from_window("09:45:01", "MNQ") == "VA Breakout (v2.0)"
    assert infer_strategy_from_window("10:15:22", "MGC") == "Gold London Fix (H14)"
    assert infer_strategy_from_window("14:30:00", "MNQ") == "Discretionary / Manual Scalp"


def test_infer_exit_type():
    assert infer_exit_type("STP", "08:50:00") == "STOP_LOSS"
    assert infer_exit_type("LMT", "09:55:00") == "PROFIT_TARGET"
    assert infer_exit_type("MKT", "10:15:01") == "TIME_EXIT_1015"
    assert infer_exit_type("MKT", "11:00:02") == "TIME_EXIT_1100"
    assert infer_exit_type("MKT", "09:25:30") == "TIME_EXIT_0925"
    assert infer_exit_type("MKT", "12:00:00") == "MARKET_EXIT"


def test_fifo_matching_simple_round_turn():
    # Long trade: BUY 2 MES @ 7731.00 at 09:48, SELL 2 MES @ 7736.00 at 10:15
    f1 = CQGFillEvent(
        timestamp_ms=1793803694320,
        dt_et=datetime(2026, 11, 4, 9, 48, 14, tzinfo=ET_TZ),
        date_str="2026-11-04",
        time_str="09:48:14",
        raw_symbol="MESZ26.CQG",
        clean_symbol="MES",
        account_id="17014406",
        order_id="68342242",
        parent_id="68333652",
        order_type="LMT",
        side="BUY",
        qty=2,
        fill_price=7731.0,
        message="Order Filled",
    )
    f2 = CQGFillEvent(
        timestamp_ms=1793805301039,
        dt_et=datetime(2026, 11, 4, 10, 15, 1, tzinfo=ET_TZ),
        date_str="2026-11-04",
        time_str="10:15:01",
        raw_symbol="MESZ26.CQG",
        clean_symbol="MES",
        account_id="17014406",
        order_id="68318889",
        parent_id="",
        order_type="MKT",
        side="SELL",
        qty=2,
        fill_price=7736.0,
        message="Order Filled",
    )

    trades = reconstruct_trades_fifo([f1, f2])
    assert len(trades) == 1
    t = trades[0]
    assert t.date == "2026-11-04"
    assert t.symbol == "MES"
    assert t.direction == "LONG"
    assert t.contracts == 2
    assert t.entry_fill == 7731.0
    assert t.exit_fill == 7736.0
    assert t.points == 5.0
    assert t.gross_pnl == pytest.approx(50.0)  # 5 pts * $5/pt * 2 = $50.00
    assert t.commission == pytest.approx(2.80)  # $1.40 * 2 = $2.80
    assert t.net_pnl == pytest.approx(47.20)
    assert t.strategy == "VA Breakout (v2.0)"
    assert t.exit_type == "TIME_EXIT_1015"


def test_fifo_matching_partial_fills():
    # Opened SHORT 4 MNQ @ 20000.00
    # Closed 2 MNQ @ 19990.00 (+10 pts)
    # Closed 2 MNQ @ 19980.00 (+20 pts)
    f_open = CQGFillEvent(
        timestamp_ms=1000,
        dt_et=datetime(2026, 11, 4, 8, 35, 0, tzinfo=ET_TZ),
        date_str="2026-11-04",
        time_str="08:35:00",
        raw_symbol="MNQZ26.CQG",
        clean_symbol="MNQ",
        account_id="17014406",
        order_id="101",
        parent_id="",
        order_type="MKT",
        side="SELL",
        qty=4,
        fill_price=20000.0,
        message="",
    )
    f_close1 = CQGFillEvent(
        timestamp_ms=2000,
        dt_et=datetime(2026, 11, 4, 8, 40, 0, tzinfo=ET_TZ),
        date_str="2026-11-04",
        time_str="08:40:00",
        raw_symbol="MNQZ26.CQG",
        clean_symbol="MNQ",
        account_id="17014406",
        order_id="102",
        parent_id="",
        order_type="LMT",
        side="BUY",
        qty=2,
        fill_price=19990.0,
        message="",
    )
    f_close2 = CQGFillEvent(
        timestamp_ms=3000,
        dt_et=datetime(2026, 11, 4, 8, 45, 0, tzinfo=ET_TZ),
        date_str="2026-11-04",
        time_str="08:45:00",
        raw_symbol="MNQZ26.CQG",
        clean_symbol="MNQ",
        account_id="17014406",
        order_id="103",
        parent_id="",
        order_type="LMT",
        side="BUY",
        qty=2,
        fill_price=19980.0,
        message="",
    )

    trades = reconstruct_trades_fifo([f_open, f_close1, f_close2])
    assert len(trades) == 2
    assert trades[0].contracts == 2
    assert trades[0].points == 10.0
    assert trades[0].gross_pnl == pytest.approx(10.0 * 2.0 * 2)  # $40.00
    assert trades[1].contracts == 2
    assert trades[1].points == 20.0
    assert trades[1].gross_pnl == pytest.approx(20.0 * 2.0 * 2)  # $80.00


def test_sync_to_ledger_and_deduplication():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        journal = DemoParityJournal(forward_test_dir=tmp_path)

        trade = ReconstructedBrokerTrade(
            trade_key="key1",
            date="2026-11-04",
            symbol="MES",
            direction="LONG",
            contracts=2,
            entry_time="09:48:14",
            exit_time="10:15:01",
            entry_fill=7731.0,
            exit_fill=7736.0,
            points=5.0,
            gross_pnl=50.0,
            commission=2.80,
            net_pnl=47.20,
            exit_type="TIME_EXIT_1015",
            strategy="VA Breakout (v2.0)",
            entry_order_id="68342242",
            exit_order_id="68318889",
            account_id="17014406",
            notes="CQG Test Fill",
        )

        # Initial sync
        synced_count = sync_broker_trades_to_ledger([trade], journal=journal)
        assert synced_count == 1

        df_trades = journal.load_trades_df()
        assert len(df_trades) == 1
        assert float(df_trades.iloc[0]["net_pnl"]) == 47.20
        assert float(df_trades.iloc[0]["account_balance_after"]) == 25047.20

        # Second sync with exact same trade -> should be deduplicated (0 new trades)
        synced_count_2 = sync_broker_trades_to_ledger([trade], journal=journal)
        assert synced_count_2 == 0

        df_trades_2 = journal.load_trades_df()
        assert len(df_trades_2) == 1


def test_model_gate_violation_prevents_sync():
    """Verifies that trades gated by the model (e.g. GARCH exhaustion) are NOT synced into baseline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        journal = DemoParityJournal(forward_test_dir=tmp_path)

        from backtest.demo_parity_engine import WindowEvaluationRecord

        # Record a gated evaluation for 2026-11-04 MES
        journal.record_window_evaluation(
            WindowEvaluationRecord(
                date="2026-11-04",
                window_time="09:45:00",
                strategy="VA Breakout (v2.0)",
                symbol="MES",
                status="FILTERED_NO_BREAKOUT",
                action="NONE",
                contracts=0,
                diagnostic_reason="GARCH Exhaustion: Price extended 2.62 DP > 2.50 DP",
            )
        )

        trade = ReconstructedBrokerTrade(
            trade_key="key_nov4",
            date="2026-11-04",
            symbol="MES",
            direction="LONG",
            contracts=2,
            entry_time="09:48:14",
            exit_time="10:15:01",
            entry_fill=7731.0,
            exit_fill=7736.0,
            points=5.0,
            gross_pnl=50.0,
            commission=2.80,
            net_pnl=47.20,
            exit_type="TIME_EXIT_1015",
            strategy="VA Breakout (v2.0)",
            entry_order_id="68342242",
            exit_order_id="68318889",
            account_id="17014406",
            notes="CQG Test Fill on Gated Setup",
        )

        # Sync with require_model_approval=True (default) -> must be rejected
        synced_count = sync_broker_trades_to_ledger([trade], journal=journal, require_model_approval=True)
        assert synced_count == 0
        df_trades = journal.load_trades_df()
        assert df_trades.empty

        # Sync with require_model_approval=False (force override) -> accepted
        synced_count_forced = sync_broker_trades_to_ledger([trade], journal=journal, require_model_approval=False)
        assert synced_count_forced == 1
        df_trades_forced = journal.load_trades_df()
        assert len(df_trades_forced) == 1

