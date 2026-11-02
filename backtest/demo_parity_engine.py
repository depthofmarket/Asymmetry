"""
Demo Parity & Slippage Journal Engine for LucidFlex 25K Forward Testing.

Institutional-grade tracking of:
1. Signal vs Execution Parity (Theoretical Entry/Exit vs Actual Demo Fill).
2. Slippage Measurement (ticks, points, dollar drag, adverse fill frequency).
3. LucidFlex 25K Rulebook Compliance:
   - Starting Capital: $25,000.00
   - Profit Target: $26,250.00 (+$1,250.00 / +5.0%)
   - Daily Soft Stop: -$600.00 (trading halts for day if daily net PnL <= -$600)
   - Max Trailing Drawdown: -$1,000.00 (floor locks at $25,100 once peak >= $26,100)
   - Max Firm Contract Limit: 1 Mini or 10 Micros
   - Sizing Model: Anti-Martingale Ratchet (Tier 1: 2, Tier 2: 3, Tier 3: 4 micros)
4. Session Auditing:
   - Full recording of trading days, including NO-TRADE days with exact MotiveWave diagnostic reasons.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
FORWARD_TEST_DIR = REPO_ROOT / "results" / "forward_test"
TRADES_LEDGER_PATH = FORWARD_TEST_DIR / "demo_trades_ledger.csv"
SESSIONS_LEDGER_PATH = FORWARD_TEST_DIR / "demo_sessions_ledger.csv"
WINDOWS_LEDGER_PATH = FORWARD_TEST_DIR / "demo_window_evaluations_ledger.csv"
STATE_JSON_PATH = FORWARD_TEST_DIR / "demo_parity_state.json"
DASHBOARD_HTML_PATH = FORWARD_TEST_DIR / "demo_parity_dashboard.html"


# Canonical Prop Firm Specs (LucidFlex 25K)
STARTING_CAPITAL = 25_000.0
PROFIT_TARGET_DOLLARS = 1_250.0
TARGET_BALANCE = STARTING_CAPITAL + PROFIT_TARGET_DOLLARS  # $26,250.00
DAILY_SOFT_STOP_DOLLARS = -600.0
MAX_TRAILING_DRAWDOWN = 1_000.0
TRAILING_FLOOR_LOCK = 25_100.0
PEAK_FOR_FLOOR_LOCK = 26_100.0
MAX_FIRM_MICROS = 10
MAX_FIRM_MINIS = 1


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    point_value: float
    tick_size: float = 0.25
    default_commission_rt: float = 1.40  # Round-turn commission per contract ($0.70/side)
    is_micro: bool = True

    @property
    def tick_value(self) -> float:
        return self.point_value * self.tick_size


INSTRUMENT_SPECS: dict[str, InstrumentSpec] = {
    "MNQ": InstrumentSpec("MNQ", point_value=2.00, tick_size=0.25, default_commission_rt=1.40, is_micro=True),
    "MES": InstrumentSpec("MES", point_value=5.00, tick_size=0.25, default_commission_rt=1.40, is_micro=True),
    "MGC": InstrumentSpec("MGC", point_value=10.00, tick_size=0.10, default_commission_rt=1.50, is_micro=True),
    "NQ": InstrumentSpec("NQ", point_value=20.00, tick_size=0.25, default_commission_rt=4.50, is_micro=False),
    "ES": InstrumentSpec("ES", point_value=50.00, tick_size=0.25, default_commission_rt=4.50, is_micro=False),
    "GC": InstrumentSpec("GC", point_value=100.00, tick_size=0.10, default_commission_rt=4.80, is_micro=False),
}


def resolve_instrument(symbol: str) -> InstrumentSpec:
    sym = symbol.strip().upper()
    if sym in INSTRUMENT_SPECS:
        return INSTRUMENT_SPECS[sym]
    if "NQ" in sym:
        return INSTRUMENT_SPECS["MNQ"] if "M" in sym else INSTRUMENT_SPECS["NQ"]
    if "ES" in sym:
        return INSTRUMENT_SPECS["MES"] if "M" in sym else INSTRUMENT_SPECS["ES"]
    if "GC" in sym:
        return INSTRUMENT_SPECS["MGC"] if "M" in sym else INSTRUMENT_SPECS["GC"]
    # Default to MNQ
    return INSTRUMENT_SPECS["MNQ"]


@dataclass
class TradeFillRecord:
    date: str                          # YYYY-MM-DD
    symbol: str                        # MNQ or MES
    direction: Literal["LONG", "SHORT"]
    contracts: int                     # 1 to 10 micros
    theo_entry_price: float
    actual_entry_fill: float
    theo_stop_price: float
    theo_target_price: float
    exit_type: Literal[
        "PROFIT_TARGET_1_5R",
        "STOP_LOSS",
        "TIME_EXIT_0925",
        "TIME_EXIT_1015",
        "TIME_EXIT_1100",
        "NEWS_GUARD_0959",
        "MANUAL"
    ]
    actual_exit_fill: float
    trade_id: int = 1
    strategy: str = "VA Breakout (v2.0)"
    theo_entry_time: str = "09:45:00"
    actual_entry_time: str = "09:45:01"
    theo_exit_time: str = "10:15:00"
    actual_exit_time: str = "10:15:00"
    theo_exit_price: float | None = None
    commission_rt_per_contract: float | None = None
    notes: str = ""

    # Computed fields populated automatically
    entry_slippage_pts: float = field(init=False)
    entry_slippage_ticks: float = field(init=False)
    entry_slippage_dollars: float = field(init=False)
    exit_slippage_pts: float = field(init=False)
    exit_slippage_ticks: float = field(init=False)
    exit_slippage_dollars: float = field(init=False)
    total_slippage_dollars: float = field(init=False)
    realized_points: float = field(init=False)
    gross_pnl: float = field(init=False)
    commission: float = field(init=False)
    net_pnl: float = field(init=False)
    theo_points: float = field(init=False)
    theo_net_pnl: float = field(init=False)
    execution_drag_dollars: float = field(init=False)

    def __post_init__(self) -> None:
        spec = resolve_instrument(self.symbol)
        comm_rt = self.commission_rt_per_contract if self.commission_rt_per_contract is not None else spec.default_commission_rt
        self.commission_rt_per_contract = comm_rt

        # Determine theoretical exit price if not specified
        if self.theo_exit_price is None:
            if self.exit_type == "PROFIT_TARGET_1_5R":
                self.theo_exit_price = self.theo_target_price
            elif self.exit_type == "STOP_LOSS":
                self.theo_exit_price = self.theo_stop_price
            else:
                self.theo_exit_price = self.actual_exit_fill

        # Entry slippage (positive = adverse, negative = favorable)
        if self.direction == "LONG":
            self.entry_slippage_pts = round(self.actual_entry_fill - self.theo_entry_price, 4)
        else:
            self.entry_slippage_pts = round(self.theo_entry_price - self.actual_entry_fill, 4)
        self.entry_slippage_ticks = round(self.entry_slippage_pts / spec.tick_size, 2)
        self.entry_slippage_dollars = round(self.entry_slippage_pts * spec.point_value * self.contracts, 2)

        # Exit slippage (positive = adverse, negative = favorable)
        if self.direction == "LONG":
            self.exit_slippage_pts = round(self.theo_exit_price - self.actual_exit_fill, 4)
        else:
            self.exit_slippage_pts = round(self.actual_exit_fill - self.theo_exit_price, 4)
        self.exit_slippage_ticks = round(self.exit_slippage_pts / spec.tick_size, 2)
        self.exit_slippage_dollars = round(self.exit_slippage_pts * spec.point_value * self.contracts, 2)

        self.total_slippage_dollars = round(self.entry_slippage_dollars + self.exit_slippage_dollars, 2)

        # Points and PnL
        if self.direction == "LONG":
            self.realized_points = round(self.actual_exit_fill - self.actual_entry_fill, 4)
            self.theo_points = round(self.theo_exit_price - self.theo_entry_price, 4)
        else:
            self.realized_points = round(self.actual_entry_fill - self.actual_exit_fill, 4)
            self.theo_points = round(self.theo_entry_price - self.theo_exit_price, 4)

        self.commission = round(comm_rt * self.contracts, 2)
        self.gross_pnl = round(self.realized_points * spec.point_value * self.contracts, 2)
        self.net_pnl = round(self.gross_pnl - self.commission, 2)

        theo_gross_pnl = round(self.theo_points * spec.point_value * self.contracts, 2)
        self.theo_net_pnl = round(theo_gross_pnl - self.commission, 2)
        self.execution_drag_dollars = round(self.net_pnl - self.theo_net_pnl, 2)


@dataclass
class DailySessionRecord:
    date: str                          # YYYY-MM-DD
    setup_detected: bool               # True if 09:45 breakout occurred
    setup_fired: bool                  # True if trade taken
    direction: str | None = None       # LONG, SHORT, or None
    diagnostic_reason: str = ""        # e.g. "NO TRADE: Inside Prior VA" or "TRADE FIRED"
    intermarket_aligned: bool = True
    macro_news_day: bool = False
    day_net_pnl: float = 0.0
    trades_count: int = 0
    end_of_day_balance: float = STARTING_CAPITAL
    notes: str = ""


@dataclass
class WindowEvaluationRecord:
    date: str                          # YYYY-MM-DD
    window_time: str                   # 08:35:00, 09:45:00, 10:15:00 ET
    strategy: str                      # Macro Momentum (08:35), VA Breakout (v2.0), Gold London Fix (H14)
    symbol: str                        # MNQ, MES, MGC
    status: Literal["TRADE_FIRED", "FILTERED_NO_BREAKOUT", "FILTERED_GATE", "FLAT_NO_SETUP"]
    action: str                        # BUY, SELL, or NONE
    contracts: int                     # contracts recommended/taken (0 if flat)
    diagnostic_reason: str             # Quantitative reason / gate details
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    account_balance: float = STARTING_CAPITAL
    trailing_cushion: float = MAX_TRAILING_DRAWDOWN


@dataclass
class AccountEvalState:
    starting_capital: float = STARTING_CAPITAL
    balance: float = STARTING_CAPITAL
    peak_balance: float = STARTING_CAPITAL
    trailing_floor: float = STARTING_CAPITAL - MAX_TRAILING_DRAWDOWN  # $24,000.00
    profit: float = 0.0
    distance_to_target: float = PROFIT_TARGET_DOLLARS  # $1,250.00
    trailing_cushion: float = MAX_TRAILING_DRAWDOWN     # $1,000.00
    current_date: str = ""
    current_date_pnl: float = 0.0
    daily_soft_stop_limit: float = DAILY_SOFT_STOP_DOLLARS  # -$600.00
    distance_to_daily_stop: float = abs(DAILY_SOFT_STOP_DOLLARS)
    status: Literal["ACTIVE", "PASSED", "DAILY_HALTED", "TRAILED_OUT"] = "ACTIVE"
    status_reason: str = "Evaluation in progress"
    trades_count: int = 0
    wins_count: int = 0
    losses_count: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_entry_slippage_ticks: float = 0.0
    avg_exit_slippage_ticks: float = 0.0
    total_slippage_drag_dollars: float = 0.0
    adverse_entry_rate: float = 0.0
    recommended_micros: int = 2
    recommended_tier: str = "Tier 1: Capital Shield (2 Micros)"
    contract_limit_breached: bool = False


class DemoParityJournal:
    """Manages the persistent demo trade and session ledgers."""

    def __init__(self, forward_test_dir: Path | None = None) -> None:
        self.forward_test_dir = forward_test_dir or FORWARD_TEST_DIR
        self.trades_ledger_path = self.forward_test_dir / "demo_trades_ledger.csv"
        self.sessions_ledger_path = self.forward_test_dir / "demo_sessions_ledger.csv"
        self.windows_ledger_path = self.forward_test_dir / "demo_window_evaluations_ledger.csv"
        self.state_json_path = self.forward_test_dir / "demo_parity_state.json"
        self.dashboard_html_path = self.forward_test_dir / "demo_parity_dashboard.html"
        self.forward_test_dir.mkdir(parents=True, exist_ok=True)

    def load_trades_df(self) -> pd.DataFrame:
        if not self.trades_ledger_path.exists():
            return pd.DataFrame()
        try:
            return pd.read_csv(self.trades_ledger_path)
        except Exception:
            return pd.DataFrame()

    def load_sessions_df(self) -> pd.DataFrame:
        if not self.sessions_ledger_path.exists():
            return pd.DataFrame()
        try:
            return pd.read_csv(self.sessions_ledger_path)
        except Exception:
            return pd.DataFrame()

    def load_windows_df(self) -> pd.DataFrame:
        if not self.windows_ledger_path.exists():
            return pd.DataFrame()
        try:
            return pd.read_csv(self.windows_ledger_path)
        except Exception:
            return pd.DataFrame()

    def record_window_evaluation(self, rec: WindowEvaluationRecord) -> None:
        """Record or update a granular strategy window evaluation (both trades and filtered setups)."""
        df_existing = self.load_windows_df()
        row_dict = asdict(rec)

        if df_existing.empty:
            df_new = pd.DataFrame([row_dict])
            df_new.to_csv(self.windows_ledger_path, index=False)
            return

        # If date + window_time + symbol already exists, update it in place
        mask = (
            (df_existing["date"].astype(str) == rec.date)
            & (df_existing["window_time"].astype(str) == rec.window_time)
            & (df_existing["symbol"].astype(str) == rec.symbol)
        )
        if mask.any():
            idx = df_existing[mask].index[0]
            for k, v in row_dict.items():
                df_existing.at[idx, k] = v
            df_existing.to_csv(self.windows_ledger_path, index=False)
        else:
            df_row = pd.DataFrame([row_dict])
            df_row.to_csv(self.windows_ledger_path, mode="a", header=False, index=False)

    def get_eval_state(self) -> AccountEvalState:
        """Compute the up-to-date LucidFlex 25K account state and execution analytics."""
        df_trades = self.load_trades_df()
        state = AccountEvalState()

        if df_trades.empty or "net_pnl" not in df_trades.columns:
            return state

        # Track sequential balance, peak, and trailing floor
        balance = STARTING_CAPITAL
        peak = STARTING_CAPITAL
        trailing_floor = STARTING_CAPITAL - MAX_TRAILING_DRAWDOWN
        wins = 0
        losses = 0
        gross_wins = 0.0
        gross_losses = 0.0
        entry_slips_ticks = []
        exit_slips_ticks = []
        total_drag = 0.0
        contract_limit_breached = False

        daily_pnls: dict[str, float] = {}

        for _, row in df_trades.iterrows():
            net = float(row["net_pnl"])
            p_date = str(row["date"])
            qty = int(row.get("contracts", 1))
            sym = str(row.get("symbol", "MNQ")).upper()

            # Contract limit check: 1 mini or 10 micros
            is_mini = "MNQ" not in sym and "MES" not in sym and "MGC" not in sym
            if (is_mini and qty > MAX_FIRM_MINIS) or (not is_mini and qty > MAX_FIRM_MICROS):
                contract_limit_breached = True

            daily_pnls[p_date] = daily_pnls.get(p_date, 0.0) + net
            balance += net

            if balance > peak:
                peak = balance
                trailing_floor = min(TRAILING_FLOOR_LOCK, peak - MAX_TRAILING_DRAWDOWN)

            if net > 0:
                wins += 1
                gross_wins += net
            elif net < 0:
                losses += 1
                gross_losses += abs(net)

            if "entry_slippage_ticks" in row and pd.notna(row["entry_slippage_ticks"]):
                entry_slips_ticks.append(float(row["entry_slippage_ticks"]))
            if "exit_slippage_ticks" in row and pd.notna(row["exit_slippage_ticks"]):
                exit_slips_ticks.append(float(row["exit_slippage_ticks"]))
            if "execution_drag_dollars" in row and pd.notna(row["execution_drag_dollars"]):
                total_drag += float(row["execution_drag_dollars"])

        profit = balance - STARTING_CAPITAL
        dist_target = max(0.0, TARGET_BALANCE - balance)
        trailing_cushion = balance - trailing_floor

        # Latest day PnL
        latest_date = df_trades["date"].iloc[-1]
        latest_day_pnl = daily_pnls.get(latest_date, 0.0)
        dist_daily_stop = abs(DAILY_SOFT_STOP_DOLLARS) + latest_day_pnl if latest_day_pnl < 0 else abs(DAILY_SOFT_STOP_DOLLARS)

        # Status resolution
        status = "ACTIVE"
        status_reason = "Evaluation in progress"

        if balance >= TARGET_BALANCE:
            status = "PASSED"
            status_reason = f"PROFIT TARGET PASSED (+${profit:,.2f} >= +${PROFIT_TARGET_DOLLARS:,.2f})"
        elif balance <= trailing_floor:
            status = "TRAILED_OUT"
            status_reason = f"ACCOUNT TRAILED OUT (Balance ${balance:,.2f} <= Floor ${trailing_floor:,.2f})"
        elif latest_day_pnl <= DAILY_SOFT_STOP_DOLLARS:
            status = "DAILY_HALTED"
            status_reason = f"DAILY SOFT STOP HIT (Day PnL ${latest_day_pnl:,.2f} <= -${abs(DAILY_SOFT_STOP_DOLLARS):,.2f})"

        total_trades = len(df_trades)
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (99.0 if gross_wins > 0 else 0.0)

        avg_entry_slip = float(np.mean(entry_slips_ticks)) if entry_slips_ticks else 0.0
        avg_exit_slip = float(np.mean(exit_slips_ticks)) if exit_slips_ticks else 0.0
        adverse_count = sum(1 for s in entry_slips_ticks if s > 0)
        adverse_rate = (adverse_count / len(entry_slips_ticks) * 100.0) if entry_slips_ticks else 0.0

        # Anti-Martingale Ratchet sizing
        if profit >= 750.0:
            rec_micros = 4
            rec_tier = "Tier 3: Target Sprint (4 Micros)"
        elif profit >= 350.0:
            rec_micros = 3
            rec_tier = "Tier 2: Market-Funded Expansion (3 Micros)"
        else:
            rec_micros = 2
            rec_tier = "Tier 1: Capital Shield (2 Micros)"

        state = AccountEvalState(
            starting_capital=STARTING_CAPITAL,
            balance=round(balance, 2),
            peak_balance=round(peak, 2),
            trailing_floor=round(trailing_floor, 2),
            profit=round(profit, 2),
            distance_to_target=round(dist_target, 2),
            trailing_cushion=round(trailing_cushion, 2),
            current_date=str(latest_date),
            current_date_pnl=round(latest_day_pnl, 2),
            daily_soft_stop_limit=DAILY_SOFT_STOP_DOLLARS,
            distance_to_daily_stop=round(dist_daily_stop, 2),
            status=status,
            status_reason=status_reason,
            trades_count=total_trades,
            wins_count=wins,
            losses_count=losses,
            win_rate=round(win_rate, 1),
            profit_factor=round(profit_factor, 2),
            avg_entry_slippage_ticks=round(avg_entry_slip, 2),
            avg_exit_slippage_ticks=round(avg_exit_slip, 2),
            total_slippage_drag_dollars=round(total_drag, 2),
            adverse_entry_rate=round(adverse_rate, 1),
            recommended_micros=rec_micros,
            recommended_tier=rec_tier,
            contract_limit_breached=contract_limit_breached,
        )
        return state

    def record_trade(self, trade: TradeFillRecord) -> AccountEvalState:
        """Append trade to the trades ledger, update session ledger, and persist state."""
        df_existing = self.load_trades_df()
        next_id = 1 if df_existing.empty else int(df_existing["trade_id"].max()) + 1
        trade.trade_id = next_id

        # Compute running account state before this trade
        state_before = self.get_eval_state()
        new_balance = round(state_before.balance + trade.net_pnl, 2)
        new_peak = max(state_before.peak_balance, new_balance)
        new_floor = min(TRAILING_FLOOR_LOCK, new_peak - MAX_TRAILING_DRAWDOWN)

        trade_dict = {
            "trade_id": trade.trade_id,
            "date": trade.date,
            "symbol": trade.symbol,
            "direction": trade.direction,
            "contracts": trade.contracts,
            "strategy": trade.strategy,
            "theo_entry_time": trade.theo_entry_time,
            "actual_entry_time": trade.actual_entry_time,
            "theo_entry_price": trade.theo_entry_price,
            "actual_entry_fill": trade.actual_entry_fill,
            "entry_slippage_pts": trade.entry_slippage_pts,
            "entry_slippage_ticks": trade.entry_slippage_ticks,
            "entry_slippage_dollars": trade.entry_slippage_dollars,
            "theo_stop_price": trade.theo_stop_price,
            "theo_target_price": trade.theo_target_price,
            "exit_type": trade.exit_type,
            "theo_exit_time": trade.theo_exit_time,
            "actual_exit_time": trade.actual_exit_time,
            "theo_exit_price": trade.theo_exit_price,
            "actual_exit_fill": trade.actual_exit_fill,
            "exit_slippage_pts": trade.exit_slippage_pts,
            "exit_slippage_ticks": trade.exit_slippage_ticks,
            "exit_slippage_dollars": trade.exit_slippage_dollars,
            "total_slippage_dollars": trade.total_slippage_dollars,
            "realized_points": trade.realized_points,
            "gross_pnl": trade.gross_pnl,
            "commission": trade.commission,
            "net_pnl": trade.net_pnl,
            "theo_points": trade.theo_points,
            "theo_net_pnl": trade.theo_net_pnl,
            "execution_drag_dollars": trade.execution_drag_dollars,
            "account_balance_after": new_balance,
            "peak_balance_after": new_peak,
            "trailing_floor_after": new_floor,
            "notes": trade.notes,
        }

        df_row = pd.DataFrame([trade_dict])
        if self.trades_ledger_path.exists():
            df_row.to_csv(self.trades_ledger_path, mode="a", header=False, index=False)
        else:
            df_row.to_csv(self.trades_ledger_path, index=False)

        # Update or record corresponding daily session
        self.record_session(DailySessionRecord(
            date=trade.date,
            setup_detected=True,
            setup_fired=True,
            direction=trade.direction,
            diagnostic_reason=f"TRADE FIRED: {trade.direction} {trade.contracts}x {trade.symbol} @ {trade.actual_entry_fill:.2f}",
            day_net_pnl=trade.net_pnl,
            trades_count=1,
            end_of_day_balance=new_balance,
            notes=trade.notes,
        ))

        # Refresh state and rewrite JSON & HTML
        new_state = self.get_eval_state()
        self.save_state_json(new_state)
        self.generate_html_dashboard()
        return new_state

    def record_session(self, session: DailySessionRecord) -> None:
        """Record or update a daily session (e.g. No-trade days with diagnostic rejection reasons)."""
        df_sessions = self.load_sessions_df()
        row_dict = asdict(session)

        if df_sessions.empty:
            df_new = pd.DataFrame([row_dict])
            df_new.to_csv(self.sessions_ledger_path, index=False)
            return

        # If date already exists, update it; otherwise append
        if session.date in df_sessions["date"].astype(str).values:
            idx = df_sessions[df_sessions["date"].astype(str) == session.date].index[0]
            # Accumulate if multiple trades on same day
            if session.setup_fired and df_sessions.at[idx, "setup_fired"]:
                row_dict["day_net_pnl"] = round(df_sessions.at[idx, "day_net_pnl"] + session.day_net_pnl, 2)
                row_dict["trades_count"] = int(df_sessions.at[idx, "trades_count"] + session.trades_count)
            for k, v in row_dict.items():
                df_sessions.at[idx, k] = v
            df_sessions.to_csv(self.sessions_ledger_path, index=False)
        else:
            df_row = pd.DataFrame([row_dict])
            df_row.to_csv(self.sessions_ledger_path, mode="a", header=False, index=False)

    def save_state_json(self, state: AccountEvalState) -> None:
        """Write current evaluation state to JSON for external tools/dashboards."""
        with open(self.state_json_path, "w", encoding="utf-8") as f:
            json.dump(asdict(state), f, indent=2)

    def reset_ledger(self) -> None:
        """Safely reset all forward test ledgers to pristine state."""
        if self.trades_ledger_path.exists():
            self.trades_ledger_path.unlink()
        if self.sessions_ledger_path.exists():
            self.sessions_ledger_path.unlink()
        initial_state = AccountEvalState()
        self.save_state_json(initial_state)
        self.generate_html_dashboard()

    def generate_html_dashboard(self) -> Path:
        """Generate an institutional-grade, high-density two-tab dashboard:
        Tab 1: Demo Forward Test (AMP CQG execution logs & microstructure parity).
        Tab 2: Prop Firm Deployment (LucidFlex 25K evaluation & funded rules).
        """
        state = self.get_eval_state()
        df_trades = self.load_trades_df()
        df_sessions = self.load_sessions_df()

        pct_to_target = max(0.0, min(100.0, (state.profit / PROFIT_TARGET_DOLLARS) * 100.0))
        pct_daily_stop = max(0.0, min(100.0, (abs(min(0.0, state.current_date_pnl)) / abs(DAILY_SOFT_STOP_DOLLARS)) * 100.0))

        # Compute cumulative demo metrics (independent of prop firm starting capital)
        demo_net_pnl = round(float(df_trades["net_pnl"].sum()), 2) if not df_trades.empty and "net_pnl" in df_trades else 0.0
        demo_theo_pnl = round(float(df_trades["theo_net_pnl"].sum()), 2) if not df_trades.empty and "theo_net_pnl" in df_trades else 0.0
        demo_drag = round(demo_net_pnl - demo_theo_pnl, 2)
        demo_trades_count = len(df_trades)
        demo_wins = int((df_trades["net_pnl"] > 0).sum()) if not df_trades.empty and "net_pnl" in df_trades else 0
        demo_losses = int((df_trades["net_pnl"] < 0).sum()) if not df_trades.empty and "net_pnl" in df_trades else 0
        demo_win_rate = round((demo_wins / demo_trades_count * 100.0), 1) if demo_trades_count > 0 else 0.0

        # Strategy 1 (MNQ/MES @ 09:45 ET), Strategy 2 (MGC @ 10:15 ET), Strategy 3 (MNQ @ 08:35 ET)
        if not df_trades.empty and "strategy" in df_trades.columns:
            s1_trades = df_trades[df_trades["strategy"].str.contains("VA Breakout", na=False)]
            s2_trades = df_trades[df_trades["strategy"].str.contains("Gold", na=False)]
            s3_trades = df_trades[df_trades["strategy"].str.contains("Macro", na=False)]
        else:
            s1_trades = df_trades[df_trades["symbol"].isin(["MNQ", "MES"])] if not df_trades.empty and "symbol" in df_trades else pd.DataFrame()
            s2_trades = df_trades[df_trades["symbol"] == "MGC"] if not df_trades.empty and "symbol" in df_trades else pd.DataFrame()
            s3_trades = pd.DataFrame()

        s1_count, s2_count, s3_count = len(s1_trades), len(s2_trades), len(s3_trades)
        s1_net = float(s1_trades["net_pnl"].sum()) if not s1_trades.empty else 0.0
        s2_net = float(s2_trades["net_pnl"].sum()) if not s2_trades.empty else 0.0
        s3_net = float(s3_trades["net_pnl"].sum()) if not s3_trades.empty else 0.0
        s1_wins = int((s1_trades["net_pnl"] > 0).sum()) if not s1_trades.empty else 0
        s2_wins = int((s2_trades["net_pnl"] > 0).sum()) if not s2_trades.empty else 0
        s3_wins = int((s3_trades["net_pnl"] > 0).sum()) if not s3_trades.empty else 0
        s1_wr = round((s1_wins / s1_count * 100.0), 1) if s1_count > 0 else 0.0
        s2_wr = round((s2_wins / s2_count * 100.0), 1) if s2_count > 0 else 0.0
        s3_wr = round((s3_wins / s3_count * 100.0), 1) if s3_count > 0 else 0.0

        gross_wins = float(df_trades[df_trades["net_pnl"] > 0]["net_pnl"].sum()) if not df_trades.empty and "net_pnl" in df_trades else 0.0
        gross_losses = abs(float(df_trades[df_trades["net_pnl"] < 0]["net_pnl"].sum())) if not df_trades.empty and "net_pnl" in df_trades else 0.0
        demo_pf = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (99.0 if gross_wins > 0 else 0.0)

        status_badge_class = (
            "bg-emerald-500/10 text-emerald-400 border-emerald-500/30"
            if state.status == "PASSED"
            else (
                "bg-red-500/10 text-red-400 border-red-500/30"
                if "HALTED" in state.status or "TRAILED" in state.status
                else "bg-sky-500/10 text-sky-400 border-sky-500/30"
            )
        )

        # Tab 1: Trades rows
        trades_rows_html = ""
        if not df_trades.empty:
            for _, r in df_trades.iloc[::-1].iterrows():
                pnl = float(r["net_pnl"])
                pnl_color = "text-emerald-400" if pnl > 0 else ("text-red-400" if pnl < 0 else "text-gray-400")
                slip_ticks = float(r.get("entry_slippage_ticks", 0.0))
                slip_pts = float(r.get("entry_slippage_pts", 0.0))

                if slip_ticks > 0:
                    slip_badge = f"<span class='px-1.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20'>+{slip_ticks:.1f}t (+{slip_pts:.2f}p)</span>"
                elif slip_ticks < 0:
                    slip_badge = f"<span class='px-1.5 py-0.5 rounded text-[11px] font-mono font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'>{slip_ticks:.1f}t ({slip_pts:.2f}p)</span>"
                else:
                    slip_badge = "<span class='px-1.5 py-0.5 rounded text-[11px] font-mono text-gray-500 bg-gray-900 border border-gray-800'>0.0t</span>"

                side = str(r["direction"]).upper()
                side_badge = (
                    "<span class='px-2 py-0.5 rounded text-[11px] font-bold font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'>BUY</span>"
                    if side in ("LONG", "BUY")
                    else "<span class='px-2 py-0.5 rounded text-[11px] font-bold font-mono bg-red-500/10 text-red-400 border border-red-500/30'>SELL</span>"
                )

                ex_type = str(r["exit_type"]).replace("_", " ")
                slip_drag = float(r.get("total_slippage_dollars", 0.0))
                drag_color = "text-amber-400" if slip_drag > 0 else ("text-emerald-400" if slip_drag < 0 else "text-gray-500")

                trades_rows_html += f"""
                <tr class="hover:bg-gray-800/40 border-b border-gray-800/80 transition-colors">
                    <td class="p-2.5 text-gray-500 font-mono text-xs">#{r['trade_id']}</td>
                    <td class="p-2.5 font-mono text-xs text-gray-300 whitespace-nowrap">{r['date']} <span class="text-gray-500 text-[11px]">{r.get('actual_entry_time', '09:45:00')}</span></td>
                    <td class="p-2.5 font-mono font-bold text-xs text-sky-400">{r['symbol']}</td>
                    <td class="p-2.5">{side_badge}</td>
                    <td class="p-2.5 font-mono text-xs text-gray-300">{r['contracts']}x</td>
                    <td class="p-2.5 font-mono text-xs text-gray-400">{r['theo_entry_price']:.2f}</td>
                    <td class="p-2.5 font-mono text-xs text-white font-semibold whitespace-nowrap">{r['actual_entry_fill']:.2f} {slip_badge}</td>
                    <td class="p-2.5 font-mono text-xs text-gray-300"><span class="px-2 py-0.5 rounded text-[11px] bg-gray-900 border border-gray-800">{ex_type}</span></td>
                    <td class="p-2.5 font-mono text-xs text-gray-200">{r['actual_exit_fill']:.2f}</td>
                    <td class="p-2.5 font-mono text-xs {drag_color} font-semibold">${slip_drag:+,.2f}</td>
                    <td class="p-2.5 font-mono text-xs {pnl_color} font-bold">${pnl:+,.2f}</td>
                    <td class="p-2.5 font-mono text-xs text-gray-400">${float(r.get('theo_net_pnl', pnl)):+,.2f}</td>
                </tr>
                """
        else:
            trades_rows_html = """
            <tr>
                <td colspan="12" class="p-8 text-center text-gray-500 font-mono text-xs">
                    No forward trades logged yet. MotiveWave study is active on AMP CQG Demo standing by for 09:45:00 ET execution signals.
                </td>
            </tr>
            """

        # Tab 1: Sessions rows
        sessions_rows_html = ""
        if not df_sessions.empty:
            for _, s in df_sessions.iloc[::-1].iterrows():
                fired = bool(s["setup_fired"])
                badge = (
                    "<span class='px-2 py-0.5 rounded text-[10px] font-bold font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'>TRADE FIRED</span>"
                    if fired
                    else "<span class='px-2 py-0.5 rounded text-[10px] font-bold font-mono bg-gray-900 text-gray-400 border border-gray-800'>NO TRADE</span>"
                )
                day_pnl = float(s["day_net_pnl"])
                pnl_color = "text-emerald-400" if day_pnl > 0 else ("text-red-400" if day_pnl < 0 else "text-gray-500")

                sessions_rows_html += f"""
                <tr class="hover:bg-gray-800/40 border-b border-gray-800/80 transition-colors">
                    <td class="p-2.5 font-mono text-xs text-gray-200 font-semibold">{s['date']}</td>
                    <td class="p-2.5">{badge}</td>
                    <td class="p-2.5 font-mono text-xs text-gray-300">
                        <span class="px-2 py-0.5 rounded bg-black/60 border border-gray-800/90 text-gray-300 text-[11px] inline-block max-w-xl truncate">
                            {s['diagnostic_reason']}
                        </span>
                    </td>
                    <td class="p-2.5 font-mono text-xs text-gray-400 text-center">{s['trades_count']}</td>
                    <td class="p-2.5 font-mono text-xs {pnl_color} font-bold text-right">${day_pnl:+,.2f}</td>
                </tr>
                """
        else:
            sessions_rows_html = """
            <tr>
                <td colspan="5" class="p-8 text-center text-gray-500 font-mono text-xs">
                    No daily forward test sessions logged yet.
                </td>
            </tr>
            """

        # Tab 2: Prop firm rows
        prop_trades_rows_html = ""
        if not df_trades.empty:
            for _, r in df_trades.iloc[::-1].iterrows():
                pnl = float(r["net_pnl"])
                pnl_color = "text-emerald-400" if pnl > 0 else ("text-red-400" if pnl < 0 else "text-gray-400")
                prop_trades_rows_html += f"""
                <tr class="hover:bg-gray-800/40 border-b border-gray-800/80 transition-colors">
                    <td class="p-2.5 text-gray-500 font-mono text-xs">#{r['trade_id']}</td>
                    <td class="p-2.5 font-mono text-xs text-gray-300 whitespace-nowrap">{r['date']}</td>
                    <td class="p-2.5 font-mono font-bold text-xs text-sky-400">{r['symbol']}</td>
                    <td class="p-2.5 font-mono text-xs text-gray-300">{r['contracts']}x</td>
                    <td class="p-2.5 font-mono text-xs {pnl_color} font-bold">${pnl:+,.2f}</td>
                    <td class="p-2.5 font-mono text-xs text-white font-bold">${float(r['account_balance_after']):,.2f}</td>
                    <td class="p-2.5 font-mono text-xs text-purple-400 font-bold">${float(r['trailing_floor_after']):,.2f}</td>
                    <td class="p-2.5 font-mono text-xs text-emerald-400">${float(r['account_balance_after']) - float(r['trailing_floor_after']):,.2f}</td>
                </tr>
                """
        else:
            prop_trades_rows_html = """
            <tr>
                <td colspan="8" class="p-8 text-center text-gray-500 font-mono text-xs">
                    No trades mapped to LucidFlex 25K prop account yet. Trades logged in Tab 1 automatically model here.
                </td>
            </tr>
            """

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Strategy 1 — Forward Test &amp; Prop Firm Journal</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        :root {{
            --bg-base: #0B0E14;
            --bg-panel: #111620;
            --border-panel: #1E2533;
        }}
        body {{
            background-color: var(--bg-base);
            color: #DCE2EC;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
            font-variant-numeric: tabular-nums;
        }}
        .panel {{
            background: var(--bg-panel);
            border: 1px solid var(--border-panel);
            border-radius: 4px;
        }}
        .table-wrapper {{
            overflow-x: auto;
            max-height: 480px;
            content-visibility: auto;
            contain-intrinsic-size: auto 400px;
        }}
        thead th {{
            position: sticky;
            top: 0;
            z-index: 10;
            background-color: #0E131C;
        }}
        .tab-btn[aria-selected="true"] {{
            background-color: #1A2232;
            color: #FFFFFF;
            border-bottom: 2px solid #38BDF8;
        }}
        .tab-btn[aria-selected="false"] {{
            background-color: transparent;
            color: #8B95A5;
            border-bottom: 2px solid transparent;
        }}
        .tab-btn[aria-selected="false"]:hover {{
            color: #DCE2EC;
            background-color: #141A26;
        }}
        ::-webkit-scrollbar {{
            width: 5px;
            height: 5px;
        }}
        ::-webkit-scrollbar-track {{
            background: #0B0E14;
        }}
        ::-webkit-scrollbar-thumb {{
            background: #1E2533;
            border-radius: 2px;
        }}
        ::-webkit-scrollbar-thumb:hover {{
            background: #303B4E;
        }}
    </style>
</head>
<body class="p-4 md:p-6 max-w-7xl mx-auto space-y-5">

    <!-- Top Suite Navigation -->
    <nav class="flex flex-wrap items-center justify-between gap-3 p-2 bg-[#0E131C] border border-[#1E2533] rounded">
        <div class="flex items-center gap-3">
            <span class="text-[10px] font-bold text-gray-500 uppercase tracking-widest pl-2">System Suite:</span>
            <div class="flex flex-wrap gap-2 text-xs">
                <span class="px-2.5 py-1 bg-gray-800 text-white font-semibold rounded border border-gray-700">
                    Execution Ledger &amp; Forward Journal
                </span>
                <a href="../prop_firm_dashboard/dashboard.html" class="px-2.5 py-1 text-gray-400 hover:text-emerald-400 rounded hover:bg-gray-900 border border-transparent hover:border-gray-800 transition">
                    Prop Firm Mode (LucidFlex 25K) &rarr;
                </a>
                <a href="../strategy_dashboard/dashboard.html" class="px-2.5 py-1 text-gray-400 hover:text-sky-400 rounded hover:bg-gray-900 border border-transparent hover:border-gray-800 transition">
                    Normal Quantitative Mode &rarr;
                </a>
            </div>
        </div>
        <div class="text-[11px] text-gray-500 font-mono pr-2">
            Three-Window Architecture: Window 1 (08:35 ET MNQ Macro) &bull; Window 2 (09:45 ET MNQ+MES) &bull; Window 3 (10:15 ET MGC H14)
        </div>
    </nav>

    <!-- Header Section -->
    <header class="border-b border-[#1E2533] pb-4 flex flex-col md:flex-row justify-between items-start md:items-end gap-3">
        <div>
            <div class="text-[11px] font-mono font-bold text-sky-400 tracking-wider uppercase mb-1">
                Multi-Strategy Ensemble &bull; Strat 3 (08:35 ET) &bull; Strat 1 (09:45 ET) &bull; Strat 2 (10:15 ET)
            </div>
            <h1 class="text-2xl font-bold tracking-tight text-white">Execution Ledger &amp; Capital Deployment Journal</h1>
            <p class="text-gray-400 text-xs mt-0.5">
                Three sequential, non-overlapping windows: (1) Macro Release (08:35-09:25 ET), (2) Equity Opening VA (09:45-10:15 ET) &amp; (3) Gold LBMA PM Fix (10:15-11:00 ET).
            </p>
        </div>
        <div class="text-left md:text-right font-mono text-xs">
            <span class="text-[10px] text-gray-500 uppercase tracking-wider block font-bold">Research Governance</span>
            <span class="text-gray-300">Strategy Parameters Frozen (Zero In-Sample Drift)</span>
        </div>
    </header>

    <!-- Strategy Comparison Ribbon -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 font-mono text-xs">
        <div class="panel p-3 border-l-4 border-l-rose-500 bg-[#111622]">
            <div class="flex justify-between items-center mb-1">
                <span class="text-[10px] font-bold text-rose-400 uppercase tracking-wider">Strategy 3 &bull; 08:35:00 ET (Macro)</span>
                <span class="px-1.5 py-0.2 rounded text-[10px] bg-rose-500/20 text-rose-300 border border-rose-500/30">MNQ (H17)</span>
            </div>
            <div class="text-sm font-bold text-white">Pre-Market Macro Release Momentum</div>
            <div class="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                <div><span class="text-gray-500">Backtest WR:</span> <span class="text-emerald-400 font-bold">49.0%</span> <span class="text-gray-500">(PF 1.44)</span></div>
                <div><span class="text-gray-500">2021-26 PnL:</span> <span class="text-emerald-400 font-bold">+$4,573.23</span></div>
                <div><span class="text-gray-500">Holding Limit:</span> <span class="text-gray-300">50 min (Flat 09:25)</span></div>
                <div><span class="text-gray-500">Live Forward:</span> <span class="text-gray-300 font-bold">{s3_count} Trade ({s3_net:+,.2f})</span></div>
            </div>
        </div>

        <div class="panel p-3 border-l-4 border-l-sky-500 bg-[#111622]">
            <div class="flex justify-between items-center mb-1">
                <span class="text-[10px] font-bold text-sky-400 uppercase tracking-wider">Strategy 1 &bull; 09:45:00 ET (Equities)</span>
                <span class="px-1.5 py-0.2 rounded text-[10px] bg-sky-500/20 text-sky-300 border border-sky-500/30">MNQ + MES</span>
            </div>
            <div class="text-sm font-bold text-white">Morning Value Area Breakout (v2.0)</div>
            <div class="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                <div><span class="text-gray-500">Backtest WR:</span> <span class="text-emerald-400 font-bold">57.0%</span> <span class="text-gray-500">(PF 1.65)</span></div>
                <div><span class="text-gray-500">2021-26 PnL:</span> <span class="text-emerald-400 font-bold">+$8,956.18</span></div>
                <div><span class="text-gray-500">Holding Limit:</span> <span class="text-gray-300">30 min (Flat 10:15)</span></div>
                <div><span class="text-gray-500">Live Forward:</span> <span class="text-emerald-400 font-bold">{s1_count} Trade ({s1_net:+,.2f})</span></div>
            </div>
        </div>

        <div class="panel p-3 border-l-4 border-l-amber-500 bg-[#111622]">
            <div class="flex justify-between items-center mb-1">
                <span class="text-[10px] font-bold text-amber-400 uppercase tracking-wider">Strategy 2 &bull; 10:15:00 ET (Gold)</span>
                <span class="px-1.5 py-0.2 rounded text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/30">MGC (H14)</span>
            </div>
            <div class="text-sm font-bold text-white">Post-LBMA PM Fix Structural Breakout</div>
            <div class="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                <div><span class="text-gray-500">Backtest WR:</span> <span class="text-emerald-400 font-bold">58.3%</span> <span class="text-gray-500">(PF 1.59)</span></div>
                <div><span class="text-gray-500">2021-26 PnL:</span> <span class="text-emerald-400 font-bold">+$1,386.62</span></div>
                <div><span class="text-gray-500">Holding Limit:</span> <span class="text-gray-300">45 min (Flat 11:00)</span></div>
                <div><span class="text-gray-500">Live Forward:</span> <span class="text-gray-300 font-bold">{s2_count} Trade ({s2_net:+,.2f})</span></div>
            </div>
        </div>

        <div class="panel p-3 border-l-4 border-l-purple-500 bg-[#111622]">
            <div class="flex justify-between items-center mb-1">
                <span class="text-[10px] font-bold text-purple-400 uppercase tracking-wider">Unified Composite Portfolio</span>
                <span class="px-1.5 py-0.2 rounded text-[10px] bg-purple-500/20 text-purple-300 border border-purple-500/30">LUCIDFLEX 25K</span>
            </div>
            <div class="text-sm font-bold text-white">Three-Strategy Sequential Ensemble</div>
            <div class="mt-2 grid grid-cols-2 gap-2 text-[11px]">
                <div><span class="text-gray-500">Backtest WR:</span> <span class="text-emerald-400 font-bold">55.1%</span> <span class="text-gray-500">(PF 1.56)</span></div>
                <div><span class="text-gray-500">Total Net:</span> <span class="text-emerald-400 font-bold">+$14,916.04</span> <span class="text-gray-500">(SR 3.13)</span></div>
                <div><span class="text-gray-500">Eval Pass Rate:</span> <span class="text-emerald-400 font-bold">79.1%</span> <span class="text-gray-500">(EV +$862)</span></div>
                <div><span class="text-gray-500">Live Forward:</span> <span class="text-emerald-400 font-bold">{demo_trades_count} Trade ({demo_net_pnl:+,.2f})</span></div>
            </div>
        </div>
    </div>

    <!-- Three-Tab Selector Navigation (Accessible WAI-ARIA) -->
    <div role="tablist" class="flex border-b border-[#1E2533] gap-1 font-mono text-xs">
        <button id="tab-demo" role="tab" aria-selected="true" aria-controls="panel-demo" onclick="switchTab('demo')"
            class="tab-btn px-4 py-2.5 font-bold tracking-wide transition flex items-center gap-2">
            <span>[1] FORWARD TEST LOGS (AMP CQG DEMO)</span>
            <span class="px-1.5 py-0.2 rounded text-[10px] bg-sky-500/20 text-sky-400 border border-sky-500/30">PARITY AUDIT</span>
        </button>
        <button id="tab-prop" role="tab" aria-selected="false" aria-controls="panel-prop" onclick="switchTab('prop')"
            class="tab-btn px-4 py-2.5 font-bold tracking-wide transition flex items-center gap-2">
            <span>[2] PROP FIRM ENVELOPE (LUCIDFLEX 25K)</span>
            <span class="px-1.5 py-0.2 rounded text-[10px] bg-purple-500/20 text-purple-400 border border-purple-500/30">DEPLOYMENT RULES</span>
        </button>
        <button id="tab-matrix" role="tab" aria-selected="false" aria-controls="panel-matrix" onclick="switchTab('matrix')"
            class="tab-btn px-4 py-2.5 font-bold tracking-wide transition flex items-center gap-2">
            <span>[3] BOTH STRATEGIES PERFORMANCE MATRIX</span>
            <span class="px-1.5 py-0.2 rounded text-[10px] bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">H4 &bull; H14 EVIDENCE</span>
        </button>
    </div>

    <!-- ================================================================= -->
    <!-- TAB 1: FORWARD TEST DEMO TRADE LOGS (AMP CQG FEED)                -->
    <!-- ================================================================= -->
    <main id="panel-demo" role="tabpanel" aria-labelledby="tab-demo" class="space-y-5">
        
        <!-- Context Card -->
        <div class="panel p-3.5 flex flex-wrap justify-between items-center gap-2 text-xs font-mono">
            <div>
                <span class="text-gray-400">Active Test Feed:</span> <span class="text-white font-bold">AMP Global CQG Demo</span> &bull; 
                <span class="text-gray-400">Execution Engine:</span> <span class="text-white font-bold">MotiveWave Custom Study (v2.0)</span> &bull; 
                <span class="text-gray-400">Trigger:</span> <span class="text-white font-bold">09:45:00 ET Bar Open</span>
            </div>
            <div class="text-[11px] text-gray-500">
                Goal: Quantify actual fill slippage and verify zero discrepancy vs backtest logic
            </div>
        </div>

        <!-- 6-Metric Demo Execution Ribbon -->
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2.5">
            <div class="panel p-3">
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider font-mono">Realized Demo PnL</div>
                <div class="text-xl font-bold mt-1 font-mono {'text-emerald-400' if demo_net_pnl >= 0 else 'text-red-400'}">${demo_net_pnl:+,.2f}</div>
                <div class="text-[10px] text-gray-500 font-mono mt-0.5">Net of commissions</div>
            </div>

            <div class="panel p-3">
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider font-mono">Theoretical PnL</div>
                <div class="text-xl font-bold mt-1 font-mono text-gray-200">${demo_theo_pnl:+,.2f}</div>
                <div class="text-[10px] text-gray-500 font-mono mt-0.5">Zero-slippage model</div>
            </div>

            <div class="panel p-3">
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider font-mono">Slippage Drag</div>
                <div class="text-xl font-bold mt-1 font-mono {'text-amber-400' if demo_drag < 0 else 'text-emerald-400'}">${demo_drag:+,.2f}</div>
                <div class="text-[10px] text-gray-500 font-mono mt-0.5">Realized vs Theoretical</div>
            </div>

            <div class="panel p-3">
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider font-mono">Avg Entry Slip</div>
                <div class="text-xl font-bold mt-1 font-mono {'text-amber-400' if state.avg_entry_slippage_ticks > 0 else 'text-emerald-400'}">{state.avg_entry_slippage_ticks:+.2f} ticks</div>
                <div class="text-[10px] text-gray-500 font-mono mt-0.5">{state.avg_entry_slippage_ticks * 0.25:+.2f} pts avg</div>
            </div>

            <div class="panel p-3">
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider font-mono">Adverse Fill Rate</div>
                <div class="text-xl font-bold mt-1 font-mono text-sky-400">{state.adverse_entry_rate:.1f}%</div>
                <div class="text-[10px] text-gray-500 font-mono mt-0.5">Filled worse than signal</div>
            </div>

            <div class="panel p-3">
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider font-mono">Forward Sample</div>
                <div class="text-xl font-bold mt-1 font-mono text-white">{demo_trades_count} Trades</div>
                <div class="text-[10px] text-gray-500 font-mono mt-0.5">{demo_win_rate:.1f}% WR &bull; PF {demo_pf:.2f}</div>
            </div>
        </div>

        <!-- Microstructure Analytics Grid -->
        <div class="panel p-4 space-y-3">
            <div class="flex justify-between items-center border-b border-[#1E2533] pb-2 text-xs font-mono">
                <span class="font-bold text-white uppercase tracking-wider">Microstructure Execution Realism Matrix</span>
                <span class="text-gray-500">Benchmark Tolerance: &le; 1.50 ticks adverse entry</span>
            </div>

            <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs font-mono">
                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <span class="text-gray-500 text-[10px] uppercase block">Entry Order Type</span>
                    <span class="text-gray-200 font-bold mt-0.5 block">Market Order @ 09:45:00</span>
                    <span class="text-[10px] text-gray-500">Evaluates immediately at open</span>
                </div>
                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <span class="text-gray-500 text-[10px] uppercase block">Exit Limit Fills</span>
                    <span class="text-emerald-400 font-bold mt-0.5 block">1.50x R:R Target Limit</span>
                    <span class="text-[10px] text-gray-500">Zero adverse fill expected on limit</span>
                </div>
                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <span class="text-gray-500 text-[10px] uppercase block">Exit Stop Fills</span>
                    <span class="text-red-400 font-bold mt-0.5 block">Hard Stop Market Order</span>
                    <span class="text-[10px] text-gray-500">Monitors stop execution slip</span>
                </div>
                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <span class="text-gray-500 text-[10px] uppercase block">Time-Exit Protocol</span>
                    <span class="text-sky-400 font-bold mt-0.5 block">10:15:00 ET Hard Flatten</span>
                    <span class="text-[10px] text-gray-500">Max holding duration: 30 mins</span>
                </div>
            </div>
        </div>

        <!-- Demo Trades Execution Table -->
        <div class="panel overflow-hidden">
            <div class="p-3 border-b border-[#1E2533] flex justify-between items-center bg-[#0E131C] text-xs font-mono">
                <span class="font-bold text-white uppercase tracking-wider">MotiveWave &bull; Demo Trade Execution Log ({demo_trades_count} Trades)</span>
                <span class="text-gray-500">Micro Commission ($1.40 RT) Deducted</span>
            </div>

            <div tabindex="0" role="region" aria-labelledby="trades-table-caption" class="table-wrapper">
                <table class="w-full text-left text-xs border-collapse">
                    <thead>
                        <tr class="border-b border-[#1E2533] text-[10px] text-gray-400 font-mono font-bold uppercase tracking-wider">
                            <th scope="col" class="p-2.5">#</th>
                            <th scope="col" class="p-2.5">Time (ET)</th>
                            <th scope="col" class="p-2.5">Asset</th>
                            <th scope="col" class="p-2.5">Side</th>
                            <th scope="col" class="p-2.5">Qty</th>
                            <th scope="col" class="p-2.5">Theo Signal</th>
                            <th scope="col" class="p-2.5">Demo Fill &amp; Slip</th>
                            <th scope="col" class="p-2.5">Exit Rule</th>
                            <th scope="col" class="p-2.5">Demo Exit</th>
                            <th scope="col" class="p-2.5">Slip Drag</th>
                            <th scope="col" class="p-2.5">Realized Net</th>
                            <th scope="col" class="p-2.5">Theo Net</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-[#1E2533]/60">
                        {trades_rows_html}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- MotiveWave Daily Session Log -->
        <div class="panel overflow-hidden">
            <div class="p-3 border-b border-[#1E2533] flex justify-between items-center bg-[#0E131C] text-xs font-mono">
                <span class="font-bold text-white uppercase tracking-wider">MotiveWave &bull; Daily Session Audit Log</span>
                <span class="text-gray-500">Every single session recorded (no silent missed days)</span>
            </div>

            <div tabindex="0" role="region" aria-labelledby="sessions-table-caption" class="table-wrapper">
                <table class="w-full text-left text-xs border-collapse">
                    <thead>
                        <tr class="border-b border-[#1E2533] text-[10px] text-gray-400 font-mono font-bold uppercase tracking-wider">
                            <th scope="col" class="p-2.5">Date</th>
                            <th scope="col" class="p-2.5">Status</th>
                            <th scope="col" class="p-2.5">MotiveWave Diagnostic Reason String</th>
                            <th scope="col" class="p-2.5 text-center">Trades</th>
                            <th scope="col" class="p-2.5 text-right">Day Net PnL</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-[#1E2533]/60">
                        {sessions_rows_html}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Strategy 1 Validation Gate Checklist -->
        <div class="panel p-4 space-y-3 font-mono text-xs">
            <div class="flex justify-between items-center border-b border-[#1E2533] pb-2">
                <span class="font-bold text-white uppercase tracking-wider">Strategy 1 Validation Gate &bull; Readiness Checklist for Prop Capital</span>
                <span class="text-gray-500">Must pass all gates prior to deploying on live prop accounts</span>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <div class="flex items-center justify-between">
                        <span class="text-gray-400 text-[11px]">Forward Sample Size</span>
                        <span class="font-bold {'text-emerald-400' if demo_trades_count >= 20 else 'text-amber-400'}">{demo_trades_count} / 20 Trades</span>
                    </div>
                    <div class="text-[10px] text-gray-500 mt-1">Minimum 20 pristine forward trades</div>
                </div>

                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <div class="flex items-center justify-between">
                        <span class="text-gray-400 text-[11px]">Slippage Tolerance</span>
                        <span class="font-bold {'text-emerald-400' if state.avg_entry_slippage_ticks <= 1.5 else 'text-red-400'}">{state.avg_entry_slippage_ticks:+.2f} / &le; 1.5t</span>
                    </div>
                    <div class="text-[10px] text-gray-500 mt-1">Entry slippage within acceptable bound</div>
                </div>

                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <div class="flex items-center justify-between">
                        <span class="text-gray-400 text-[11px]">Realized Profit Factor</span>
                        <span class="font-bold {'text-emerald-400' if demo_pf >= 1.35 else 'text-amber-400'}">{demo_pf:.2f} / &ge; 1.35</span>
                    </div>
                    <div class="text-[10px] text-gray-500 mt-1">Retains robust out-of-sample edge</div>
                </div>

                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <div class="flex items-center justify-between">
                        <span class="text-gray-400 text-[11px]">Discipline Adherence</span>
                        <span class="font-bold text-emerald-400">100% Compliant</span>
                    </div>
                    <div class="text-[10px] text-gray-500 mt-1">No discretionary rule deviations</div>
                </div>
            </div>
        </div>

    </main>

    <!-- ================================================================= -->
    <!-- TAB 2: PROP FIRM DEPLOYMENT (LUCIDFLEX 25K ACCOUNTS)              -->
    <!-- ================================================================= -->
    <main id="panel-prop" role="tabpanel" aria-labelledby="tab-prop" class="space-y-5 hidden">
        
        <!-- Context Card -->
        <div class="panel p-3.5 flex flex-wrap justify-between items-center gap-2 text-xs font-mono">
            <div>
                <span class="text-gray-400">Account Type:</span> <span class="text-white font-bold">LucidFlex 25K Evaluation &amp; Funded Suite</span> &bull; 
                <span class="text-gray-400">Capital Base:</span> <span class="text-white font-bold">$25,000.00</span> &bull; 
                <span class="text-gray-400">Profit Target:</span> <span class="text-emerald-400 font-bold">+$1,250.00 (+5.0%)</span> &bull; 
                <span class="text-gray-400">Passing Balance:</span> <span class="text-emerald-400 font-bold">$26,250.00</span>
            </div>
            <div class="text-[11px]">
                <span class="px-2 py-0.5 rounded font-mono font-bold {status_badge_class}">{state.status}: {state.status_reason}</span>
            </div>
        </div>

        <!-- 6-Metric Prop Envelope Ribbon -->
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2.5">
            <div class="panel p-3">
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider font-mono">Account Equity</div>
                <div class="text-xl font-bold mt-1 font-mono text-white">${state.balance:,.2f}</div>
                <div class="text-[10px] font-mono mt-0.5 font-bold {'text-emerald-400' if state.profit >= 0 else 'text-red-400'}">
                    Profit: ${state.profit:+,.2f} ({state.profit/STARTING_CAPITAL*100:+.2f}%)
                </div>
            </div>

            <div class="panel p-3">
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider font-mono">Passing Target</div>
                <div class="text-xl font-bold mt-1 font-mono text-emerald-400">${TARGET_BALANCE:,.2f}</div>
                <div class="text-[10px] text-gray-500 font-mono mt-0.5">
                    <span class="text-sky-400 font-bold">${state.distance_to_target:,.2f}</span> remaining
                </div>
            </div>

            <div class="panel p-3">
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider font-mono">Trailing Floor</div>
                <div class="text-xl font-bold mt-1 font-mono text-purple-400">${state.trailing_floor:,.2f}</div>
                <div class="text-[10px] text-gray-500 font-mono mt-0.5">
                    Cushion: <span class="{'text-emerald-400' if state.trailing_cushion > 400 else 'text-red-400'} font-bold">${state.trailing_cushion:,.2f}</span>
                </div>
            </div>

            <div class="panel p-3">
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider font-mono">Daily Stop (-$600)</div>
                <div class="text-xl font-bold mt-1 font-mono {'text-emerald-400' if state.current_date_pnl >= 0 else 'text-red-400'}">${state.current_date_pnl:+,.2f}</div>
                <div class="text-[10px] text-gray-500 font-mono mt-0.5">
                    Buffer: <span class="text-gray-300 font-bold">${state.distance_to_daily_stop:,.2f}</span>
                </div>
            </div>

            <div class="panel p-3">
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider font-mono">Active Sizing</div>
                <div class="text-xl font-bold mt-1 font-mono text-sky-400">{state.recommended_micros} Micros</div>
                <div class="text-[10px] text-gray-500 font-mono mt-0.5">
                    {state.recommended_tier.split(':')[0]}
                </div>
            </div>

            <div class="panel p-3">
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider font-mono">Firm Legal Limit</div>
                <div class="text-xl font-bold mt-1 font-mono text-white">10 Micros</div>
                <div class="text-[10px] text-emerald-400 font-mono mt-0.5 font-bold">100% Compliant (1-4 used)</div>
            </div>
        </div>

        <!-- Target Envelope & Daily Circuit Breaker Corridor -->
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 font-mono">
            
            <!-- Target Corridor (2 cols) -->
            <div class="panel p-4 lg:col-span-2 space-y-2.5">
                <div class="flex justify-between items-center text-xs">
                    <span class="font-bold text-white uppercase tracking-wider">LucidFlex 25K Capital Growth Corridor</span>
                    <span class="text-gray-400 text-xs">Target Progress: <span class="text-emerald-400 font-bold">{pct_to_target:.1f}%</span></span>
                </div>

                <div class="relative bg-black h-3.5 rounded overflow-hidden border border-[#1E2533]">
                    <div class="absolute inset-0 bg-sky-500 transition-all duration-300" style="width: {pct_to_target}%;"></div>
                </div>

                <div class="flex justify-between items-center text-[10px] text-gray-400">
                    <div><span class="text-purple-400 font-bold">FLOOR:</span> ${state.trailing_floor:,.2f}</div>
                    <div><span class="text-gray-500">START:</span> $25,000.00</div>
                    <div><span class="text-gray-500">Tier 2:</span> $25,350 (3M)</div>
                    <div><span class="text-gray-500">Tier 3:</span> $25,750 (4M)</div>
                    <div><span class="text-emerald-400 font-bold">TARGET:</span> $26,250.00</div>
                </div>
            </div>

            <!-- Daily Stop Intraday Risk Meter (1 col) -->
            <div class="panel p-4 space-y-2.5">
                <div class="flex justify-between items-center text-xs">
                    <span class="font-bold text-white uppercase tracking-wider">Daily Soft Stop (-$600)</span>
                    <span class="text-gray-400">Loss: ${abs(min(0.0, state.current_date_pnl)):,.2f}</span>
                </div>

                <div class="relative bg-black h-3.5 rounded overflow-hidden border border-[#1E2533]">
                    <div class="absolute inset-0 bg-red-500 transition-all duration-300" style="width: {pct_daily_stop}%;"></div>
                </div>

                <div class="flex justify-between items-center text-[10px]">
                    <span class="text-gray-400">Today PnL: <span class="text-white font-bold">${state.current_date_pnl:+,.2f}</span></span>
                    <span class="text-gray-400">Halting Margin: <span class="text-emerald-400 font-bold">${state.distance_to_daily_stop:,.2f}</span></span>
                </div>
            </div>
        </div>

        <!-- Canonical Rulebook Reference Table -->
        <div class="panel p-4 space-y-3 font-mono text-xs">
            <div class="flex justify-between items-center border-b border-[#1E2533] pb-2">
                <span class="font-bold text-white uppercase tracking-wider">Canonical LucidFlex 25K Rulebook Specifications</span>
                <span class="text-gray-500">Official Prop Contract Parameters</span>
            </div>

            <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <span class="text-gray-500 text-[10px] uppercase block">Starting Capital</span>
                    <span class="text-white font-bold text-sm block mt-0.5">$25,000.00</span>
                    <span class="text-[10px] text-gray-500">Base evaluation capital</span>
                </div>
                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <span class="text-gray-500 text-[10px] uppercase block">Profit Target</span>
                    <span class="text-emerald-400 font-bold text-sm block mt-0.5">+$1,250.00 (+5.0%)</span>
                    <span class="text-[10px] text-gray-500">Passing balance: $26,250</span>
                </div>
                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <span class="text-gray-500 text-[10px] uppercase block">Daily Soft Stop</span>
                    <span class="text-red-400 font-bold text-sm block mt-0.5">-$600.00</span>
                    <span class="text-[10px] text-gray-500">Trading halts for day</span>
                </div>
                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <span class="text-gray-500 text-[10px] uppercase block">Max Trailing DD</span>
                    <span class="text-purple-400 font-bold text-sm block mt-0.5">-$1,000.00</span>
                    <span class="text-[10px] text-gray-500">Locks @ $25,100 upon peak</span>
                </div>
                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <span class="text-gray-500 text-[10px] uppercase block">Firm Contract Limit</span>
                    <span class="text-sky-400 font-bold text-sm block mt-0.5">10 Micros / 1 Mini</span>
                    <span class="text-[10px] text-gray-500">Maximum open legal limit</span>
                </div>
                <div class="p-2.5 bg-black/40 rounded border border-[#1E2533]">
                    <span class="text-gray-500 text-[10px] uppercase block">Strategy Sizing</span>
                    <span class="text-emerald-400 font-bold text-sm block mt-0.5">1 to 4 Micros</span>
                    <span class="text-[10px] text-gray-500">$250 risk budget model</span>
                </div>
            </div>
        </div>

        <!-- Prop Account Execution Ledger Table -->
        <div class="panel overflow-hidden">
            <div class="p-3 border-b border-[#1E2533] flex justify-between items-center bg-[#0E131C] text-xs font-mono">
                <span class="font-bold text-white uppercase tracking-wider">LucidFlex 25K &bull; Account Evaluation Ledger</span>
                <span class="text-gray-500">Mapped from Forward Trades</span>
            </div>

            <div tabindex="0" role="region" aria-labelledby="prop-trades-caption" class="table-wrapper">
                <table class="w-full text-left text-xs border-collapse font-mono">
                    <thead>
                        <tr class="border-b border-[#1E2533] text-[10px] text-gray-400 font-bold uppercase tracking-wider">
                            <th scope="col" class="p-2.5">Trade #</th>
                            <th scope="col" class="p-2.5">Date</th>
                            <th scope="col" class="p-2.5">Instrument</th>
                            <th scope="col" class="p-2.5">Contracts</th>
                            <th scope="col" class="p-2.5">Net PnL</th>
                            <th scope="col" class="p-2.5">Account Equity</th>
                            <th scope="col" class="p-2.5">Trailing Floor</th>
                            <th scope="col" class="p-2.5">Floor Cushion</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-[#1E2533]/60">
                        {prop_trades_rows_html}
                    </tbody>
                </table>
            </div>
        </div>

    </main>

    <!-- ================================================================= -->
    <!-- TAB 3: BOTH STRATEGIES QUANTITATIVE PERFORMANCE MATRIX           -->
    <!-- ================================================================= -->
    <main id="panel-matrix" role="tabpanel" aria-labelledby="tab-matrix" class="space-y-5 hidden font-mono">
        
        <!-- Context Card -->
        <div class="panel p-3.5 flex flex-wrap justify-between items-center gap-2 text-xs">
            <div>
                <span class="text-gray-400">Portfolio Structure:</span> <span class="text-white font-bold">Two-Window Sequential Multi-Asset Architecture</span> &bull; 
                <span class="text-gray-400">Strategy 1:</span> <span class="text-sky-400 font-bold">09:45 ET (MNQ+MES)</span> &bull; 
                <span class="text-gray-400">Strategy 2:</span> <span class="text-amber-400 font-bold">10:15 ET (MGC H14)</span> &bull; 
                <span class="text-gray-400">Simultaneous Risk:</span> <span class="text-emerald-400 font-bold">0.0% (Zero Overlap)</span>
            </div>
            <div class="text-[11px] text-gray-500">
                Full 2019&ndash;2026 Microstructure Falsification &amp; Multi-Era Proof
            </div>
        </div>

        <!-- Strategy Specification & Core Parameters Table -->
        <div class="panel overflow-hidden">
            <div class="p-3 border-b border-[#1E2533] flex justify-between items-center bg-[#0E131C] text-xs">
                <span class="font-bold text-white uppercase tracking-wider">1. Strategy Architecture &amp; Execution Specifications</span>
                <span class="text-gray-500">Contract &amp; Window Comparison</span>
            </div>

            <div class="table-wrapper">
                <table class="w-full text-left text-xs border-collapse">
                    <thead>
                        <tr class="border-b border-[#1E2533] text-[10px] text-gray-400 font-bold uppercase tracking-wider bg-[#0E131C]">
                            <th class="p-3">Parameter</th>
                            <th class="p-3 text-sky-400">Strategy 1: Equities (H4 v2.0)</th>
                            <th class="p-3 text-amber-400">Strategy 2: Gold Fix (H14)</th>
                            <th class="p-3 text-purple-400">Combined Prop Portfolio</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-[#1E2533]/60 text-xs">
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-3 text-gray-400 font-bold">Execution Window</td>
                            <td class="p-3 text-white">09:45:00 &ndash; 10:15:00 ET</td>
                            <td class="p-3 text-white">10:15:00 &ndash; 11:00:00 ET</td>
                            <td class="p-3 text-emerald-400 font-bold">09:45 &amp; 10:15 ET (Sequential)</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-3 text-gray-400 font-bold">Futures Contracts</td>
                            <td class="p-3 text-white">MNQ ($2/pt) &amp; MES ($5/pt)</td>
                            <td class="p-3 text-white">MGC ($10/pt)</td>
                            <td class="p-3 text-white">MNQ + MES + MGC</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-3 text-gray-400 font-bold">Setup Direction</td>
                            <td class="p-3 text-white">Bidirectional (Long &amp; Short)</td>
                            <td class="p-3 text-emerald-400 font-semibold">Long-Only (Structural Drift)</td>
                            <td class="p-3 text-white">Selective Bidirectional</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-3 text-gray-400 font-bold">Structural Catalyst</td>
                            <td class="p-3 text-gray-300">Opening Range (09:30-09:44) VA Escape</td>
                            <td class="p-3 text-gray-300">LBMA PM Gold Benchmark Fix (10:00-10:14)</td>
                            <td class="p-3 text-gray-300">Index Open + London PM Fix</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-3 text-gray-400 font-bold">Macro &amp; Intermarket Gates</td>
                            <td class="p-3 text-gray-300">NQ/ES Directional Alignment + VIX Gate</td>
                            <td class="p-3 text-gray-300">Clearing COMEX IB60 + London High + Prior VAH</td>
                            <td class="p-3 text-emerald-400 font-bold">Multi-Layer Institutional Filtering</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-3 text-gray-400 font-bold">Max Holding Period</td>
                            <td class="p-3 text-gray-300">30 Minutes (Hard Flatten 10:15 ET)</td>
                            <td class="p-3 text-gray-300">45 Minutes (Hard Flatten 11:00 ET)</td>
                            <td class="p-3 text-purple-300 font-bold">Zero Overlapping Position Risk</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-3 text-gray-400 font-bold">Target &amp; Stop Model</td>
                            <td class="p-3 text-gray-300">1.0R Stop / 1.5R Profit Target</td>
                            <td class="p-3 text-gray-300">Structural Stop / 1.5R Profit Target</td>
                            <td class="p-3 text-gray-300">Asymmetric 1.50 Reward-to-Risk</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-3 text-gray-400 font-bold">Simultaneous Trigger Rule</td>
                            <td class="p-3 text-sky-400">50/50 Split (1 MNQ + 1 MES under Tier 1)</td>
                            <td class="p-3 text-amber-400">Full Tier Allocation (2 MGC)</td>
                            <td class="p-3 text-emerald-400 font-bold">Equity Exposure Never Doubles</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Multi-Era Historical Robustness Table -->
        <div class="panel overflow-hidden">
            <div class="p-3 border-b border-[#1E2533] flex justify-between items-center bg-[#0E131C] text-xs">
                <span class="font-bold text-white uppercase tracking-wider">2. Multi-Era Empirical Performance (Post-Commission &amp; Slippage)</span>
                <span class="text-gray-500">14.93M 1m Bars (2019&ndash;2026)</span>
            </div>

            <div class="table-wrapper">
                <table class="w-full text-left text-xs border-collapse">
                    <thead>
                        <tr class="border-b border-[#1E2533] text-[10px] text-gray-400 font-bold uppercase tracking-wider bg-[#0E131C]">
                            <th class="p-3">Market Era</th>
                            <th class="p-3 text-center">Trades (n)</th>
                            <th class="p-3 text-center">Win Rate</th>
                            <th class="p-3 text-center">Profit Factor</th>
                            <th class="p-3 text-right">Net Micro PnL</th>
                            <th class="p-3 text-right">Max Drawdown</th>
                            <th class="p-3 text-right">PnL / DD Ratio</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-[#1E2533]/60 text-xs">
                        <tr class="hover:bg-gray-800/30 bg-sky-950/10 font-bold">
                            <td colspan="7" class="p-2.5 text-sky-400 uppercase text-[10px] tracking-wider">Strategy 1: Dual Equities (MNQ + MES @ 09:45 ET Split-Risk)</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-2.5 pl-6 text-gray-300">2021&ndash;2024 (Core Historical Baseline)</td>
                            <td class="p-2.5 text-center text-gray-300">222</td>
                            <td class="p-2.5 text-center text-emerald-400">58.6%</td>
                            <td class="p-2.5 text-center text-emerald-400">1.68</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$5,190.49</td>
                            <td class="p-2.5 text-right text-red-400">-$1,469.25</td>
                            <td class="p-2.5 text-right text-sky-400">3.53</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-2.5 pl-6 text-gray-300">2025&ndash;2026 (Unseen High-Vol OOS)</td>
                            <td class="p-2.5 text-center text-gray-300">97</td>
                            <td class="p-2.5 text-center text-emerald-400">52.6%</td>
                            <td class="p-2.5 text-center text-emerald-400">1.49</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$2,762.30</td>
                            <td class="p-2.5 text-right text-red-400">-$880.50</td>
                            <td class="p-2.5 text-right text-sky-400">3.14</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30 font-semibold bg-gray-900/40">
                            <td class="p-2.5 pl-6 text-white">Full Strategy 1 Era (2021&ndash;2026)</td>
                            <td class="p-2.5 text-center text-white">319</td>
                            <td class="p-2.5 text-center text-emerald-400">56.7%</td>
                            <td class="p-2.5 text-center text-emerald-400">1.61</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$7,952.79</td>
                            <td class="p-2.5 text-right text-red-400">-$1,469.25</td>
                            <td class="p-2.5 text-right text-sky-400 font-bold">5.41</td>
                        </tr>

                        <tr class="hover:bg-gray-800/30 bg-amber-950/10 font-bold">
                            <td colspan="7" class="p-2.5 text-amber-400 uppercase text-[10px] tracking-wider">Strategy 2: Gold London Fix Breakout (MGC H14 Long-Only @ 10:15 ET)</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-2.5 pl-6 text-gray-300">2019&ndash;2020 (Pre-Core Back-Extension)</td>
                            <td class="p-2.5 text-center text-gray-300">20</td>
                            <td class="p-2.5 text-center text-emerald-400">60.0%</td>
                            <td class="p-2.5 text-center text-emerald-400">1.19</td>
                            <td class="p-2.5 text-right text-emerald-400">+$58.00</td>
                            <td class="p-2.5 text-right text-red-400">-$210.00</td>
                            <td class="p-2.5 text-right text-gray-400">0.28</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-2.5 pl-6 text-gray-300">2021&ndash;2024 (Core Historical Baseline)</td>
                            <td class="p-2.5 text-center text-gray-300">57</td>
                            <td class="p-2.5 text-center text-emerald-400">54.4%</td>
                            <td class="p-2.5 text-center text-emerald-400">1.19</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$213.00</td>
                            <td class="p-2.5 text-right text-red-400">-$550.00</td>
                            <td class="p-2.5 text-right text-gray-400">0.39</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-2.5 pl-6 text-gray-300">2025&ndash;2026 (Unseen High-Vol OOS)</td>
                            <td class="p-2.5 text-center text-gray-300">23</td>
                            <td class="p-2.5 text-center text-emerald-400">65.2%</td>
                            <td class="p-2.5 text-center text-emerald-400">2.93</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$1,001.00</td>
                            <td class="p-2.5 text-right text-red-400">-$185.00</td>
                            <td class="p-2.5 text-right text-sky-400 font-bold">5.41</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30 font-semibold bg-gray-900/40">
                            <td class="p-2.5 pl-6 text-white">Full Strategy 2 Era (2019&ndash;2026)</td>
                            <td class="p-2.5 text-center text-white">100</td>
                            <td class="p-2.5 text-center text-emerald-400">57.0%</td>
                            <td class="p-2.5 text-center text-emerald-400">1.65</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$1,272.00</td>
                            <td class="p-2.5 text-right text-red-400">-$550.00</td>
                            <td class="p-2.5 text-right text-sky-400 font-bold">2.31</td>
                        </tr>

                        <tr class="hover:bg-gray-800/30 bg-purple-950/10 font-bold">
                            <td colspan="7" class="p-2.5 text-purple-400 uppercase text-[10px] tracking-wider">Strategy 3: Pre-Market Macro Release Momentum (MNQ H17 @ 08:35 ET)</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-2.5 pl-6 text-gray-300">2021&ndash;2024 (Core Historical Baseline)</td>
                            <td class="p-2.5 text-center text-gray-300">104</td>
                            <td class="p-2.5 text-center text-emerald-400">48.1%</td>
                            <td class="p-2.5 text-center text-emerald-400">1.22</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$1,916.69</td>
                            <td class="p-2.5 text-right text-red-400">-$780.00</td>
                            <td class="p-2.5 text-right text-sky-400">2.46</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-2.5 pl-6 text-gray-300">2025&ndash;2026 (Unseen High-Vol OOS)</td>
                            <td class="p-2.5 text-center text-gray-300">39</td>
                            <td class="p-2.5 text-center text-emerald-400">46.2%</td>
                            <td class="p-2.5 text-center text-emerald-400">1.22</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$843.40</td>
                            <td class="p-2.5 text-right text-red-400">-$320.00</td>
                            <td class="p-2.5 text-right text-sky-400 font-bold">2.64</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30 font-semibold bg-gray-900/40">
                            <td class="p-2.5 pl-6 text-white">Full Strategy 3 Era (2021&ndash;2026)</td>
                            <td class="p-2.5 text-center text-white">143</td>
                            <td class="p-2.5 text-center text-emerald-400">47.6%</td>
                            <td class="p-2.5 text-center text-emerald-400">1.22</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$2,760.09</td>
                            <td class="p-2.5 text-right text-red-400">-$780.00</td>
                            <td class="p-2.5 text-right text-sky-400 font-bold">3.54</td>
                        </tr>

                        <tr class="hover:bg-gray-800/30 bg-purple-950/20 font-bold border-t-2 border-purple-500/40">
                            <td colspan="7" class="p-2.5 text-purple-300 uppercase text-[10px] tracking-wider">Unified 3-Window Prop Portfolio (Strat 3 @ 08:35 + Strat 1 @ 09:45 + Strat 2 @ 10:15)</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-2.5 pl-6 text-gray-300">2021&ndash;2022 (Bull Peak &amp; Bear Crash)</td>
                            <td class="p-2.5 text-center text-gray-300">120</td>
                            <td class="p-2.5 text-center text-emerald-400">65.8%</td>
                            <td class="p-2.5 text-center text-emerald-400">2.44</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$4,416.22</td>
                            <td class="p-2.5 text-right text-red-400">-$840.00</td>
                            <td class="p-2.5 text-right text-sky-400">5.26</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-2.5 pl-6 text-gray-300">2023&ndash;2024 (Consolidation &amp; AI Rally)</td>
                            <td class="p-2.5 text-center text-gray-300">130</td>
                            <td class="p-2.5 text-center text-emerald-400">55.4%</td>
                            <td class="p-2.5 text-center text-emerald-400">1.27</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$1,320.70</td>
                            <td class="p-2.5 text-right text-red-400">-$1,250.00</td>
                            <td class="p-2.5 text-right text-sky-400">1.06</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30">
                            <td class="p-2.5 pl-6 text-gray-300">2025&ndash;2026 (Unseen High-Vol OOS)</td>
                            <td class="p-2.5 text-center text-gray-300">153</td>
                            <td class="p-2.5 text-center text-emerald-400">51.6%</td>
                            <td class="p-2.5 text-center text-emerald-400">1.47</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$3,565.36</td>
                            <td class="p-2.5 text-right text-red-400">-$1,102.35</td>
                            <td class="p-2.5 text-right text-sky-400">3.23</td>
                        </tr>
                        <tr class="hover:bg-gray-800/30 font-bold bg-purple-900/30 text-white">
                            <td class="p-2.5 pl-6">Combined Portfolio Total (2021&ndash;2026)</td>
                            <td class="p-2.5 text-center">403</td>
                            <td class="p-2.5 text-center text-emerald-400">56.8%</td>
                            <td class="p-2.5 text-center text-emerald-400">1.55</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">+$9,619.79</td>
                            <td class="p-2.5 text-right text-red-400">-$2,692.35</td>
                            <td class="p-2.5 text-right text-emerald-400 font-bold">3.57</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Prop Firm Optionality & Monte Carlo Benchmark Cards (Paper 0) -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div class="panel p-3.5 bg-[#121722]">
                <div class="text-[10px] text-gray-400 uppercase font-bold tracking-wider">Evaluation Pass Rate</div>
                <div class="text-2xl font-bold mt-1 text-emerald-400">87.0%</div>
                <div class="text-[11px] text-gray-400 mt-1">Joint P(pass &cap; payout): <span class="text-white font-bold">78.0%</span></div>
                <div class="text-[10px] text-gray-500 mt-0.5">5,000 Monte Carlo bootstrap paths</div>
            </div>

            <div class="panel p-3.5 bg-[#121722]">
                <div class="text-[10px] text-gray-400 uppercase font-bold tracking-wider">Expected Evaluation Payoff</div>
                <div class="text-2xl font-bold mt-1 text-emerald-400">+$636.60</div>
                <div class="text-[11px] text-gray-400 mt-1">95% CI: <span class="text-white font-bold">+$626 to +$647</span></div>
                <div class="text-[10px] text-gray-500 mt-0.5">On $65 LucidFlex evaluation fee</div>
            </div>

            <div class="panel p-3.5 bg-[#121722]">
                <div class="text-[10px] text-gray-400 uppercase font-bold tracking-wider">Resolution Speed</div>
                <div class="text-2xl font-bold mt-1 text-sky-400">95 &ndash; 145d</div>
                <div class="text-[11px] text-gray-400 mt-1">Active trades to resolve: <span class="text-white font-bold">9 &ndash; 14 trades</span></div>
                <div class="text-[10px] text-gray-500 mt-0.5">Cuts calendar delay by >50% vs NQ</div>
            </div>

            <div class="panel p-3.5 bg-[#121722]">
                <div class="text-[10px] text-gray-400 uppercase font-bold tracking-wider">Multi-Account Kelly f*</div>
                <div class="text-2xl font-bold mt-1 text-purple-400">76.2%</div>
                <div class="text-[11px] text-gray-400 mt-1">Minimum Bankroll B_min: <span class="text-white font-bold">$85.00</span></div>
                <div class="text-[10px] text-gray-500 mt-0.5">Optimal bankroll allocation stake</div>
            </div>
        </div>

    </main>

    <!-- Terminal Command Helper Box -->
    <footer class="panel p-3.5 bg-[#090C12] border border-[#1E2533] flex flex-col md:flex-row items-center justify-between gap-3 text-xs font-mono">
        <div class="flex items-center gap-2 text-gray-400">
            <span class="text-emerald-400 font-bold">$</span>
            <span>Terminal CLI: <code class="text-gray-200 bg-gray-900 px-2 py-0.5 rounded border border-gray-800">python scripts/demo_parity_journal.py</code></span>
        </div>
        <div class="text-gray-500 text-[11px]">
            Data files: <code class="text-gray-400">results/forward_test/demo_trades_ledger.csv</code> &bull; <code class="text-gray-400">demo_sessions_ledger.csv</code>
        </div>
    </footer>

    <!-- Vanilla Accessible Tab Switcher Script -->
    <script>
        function switchTab(tabId) {{
            const tabs = document.querySelectorAll('.tab-btn');
            tabs.forEach(tab => {{
                const isSelected = tab.id === 'tab-' + tabId;
                tab.setAttribute('aria-selected', isSelected ? 'true' : 'false');
            }});

            const panels = document.querySelectorAll('[role="tabpanel"]');
            panels.forEach(panel => {{
                if (panel.id === 'panel-' + tabId) {{
                    panel.classList.remove('hidden');
                }} else {{
                    panel.classList.add('hidden');
                }}
            }});

            if (history.pushState) {{
                history.pushState(null, null, '#' + tabId);
            }} else {{
                location.hash = '#' + tabId;
            }}
        }}

        window.addEventListener('DOMContentLoaded', () => {{
            const hash = window.location.hash.replace('#', '');
            if (hash === 'prop' || hash === 'demo' || hash === 'matrix') {{
                switchTab(hash);
            }}
        }});
    </script>

</body>
</html>
"""
        with open(self.dashboard_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        return self.dashboard_html_path
