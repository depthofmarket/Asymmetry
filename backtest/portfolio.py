import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

@dataclass
class Trade:
    entry_time: datetime
    entry_price: float
    contracts: float
    direction: str
    signal_type: str = ""
    setup_tag: str = ""
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    reason: str = "open"
    max_favorable_excursion_points: float = 0.0
    max_adverse_excursion_points: float = 0.0
    metadata: dict = field(default_factory=dict)

class Portfolio:
    def __init__(self, initial_capital: float, futures_specs: dict, max_drawdown_pct: float | None = None):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.futures_specs = futures_specs
        self.max_drawdown_pct = max_drawdown_pct
        self.circuit_breaker_level = (
            initial_capital * (1.0 - max_drawdown_pct)
            if max_drawdown_pct is not None else None
        )
        self.circuit_breaker_triggered = False
        self.positions: List[Trade] = []
        self.closed_trades: List[Trade] = []
        self.equity_history = [initial_capital]
        self.peak_equity = initial_capital

    def enter_position(
        self,
        entry_price: float,
        contracts: float,
        entry_time,
        direction: str = 'long',
        signal_type: str = "",
        setup_tag: str = "",
        metadata: dict | None = None,
        current_price: float | None = None,
    ):
        # Circuit breaker: refuse new trades when mark-to-market equity is too low.
        # Use current_price to include unrealized PnL from open positions.
        mtm_equity = self.get_mark_to_market_equity(current_price)
        if self.circuit_breaker_level is not None and mtm_equity <= self.circuit_breaker_level:
            self.circuit_breaker_triggered = True
            return None

        trade = Trade(
            entry_time=entry_time,
            entry_price=entry_price,
            contracts=contracts,
            direction=direction,
            signal_type=signal_type,
            setup_tag=setup_tag,
            metadata=dict(metadata or {}),
        )
        self.positions.append(trade)
        return trade

    # Exit reasons that correspond to adverse (stop) fills vs. favorable (limit) fills.
    _STOP_EXIT_REASONS = frozenset({
        'stop_loss', 'hard_stop', 'managed_stop', 'time_exit',
        'end_of_data', 'hawkes_vol_exit',
    })
    _LIMIT_EXIT_REASONS = frozenset({
        'profit_target', 'hard_target',
    })

    def _resolve_slippage_points(self, exit_reason: str) -> float:
        """Select slippage based on exit type: stops get wider fills, limits get tighter."""
        specs = self.futures_specs
        if exit_reason in self._STOP_EXIT_REASONS:
            return float(specs.get('slippage_stop_points', specs['slippage_points']))
        if exit_reason in self._LIMIT_EXIT_REASONS:
            return float(specs.get('slippage_limit_points', specs['slippage_points']))
        # Unknown exit reason: use the default
        return float(specs['slippage_points'])

    def exit_position(self, exit_price: float, exit_time, trade_index: int = 0, exit_reason: str = ""):
        if trade_index >= len(self.positions):
            return
        trade = self.positions.pop(trade_index)
        commission = self.futures_specs['commission_per_round_trip'] * trade.contracts
        slippage_points = self._resolve_slippage_points(exit_reason or trade.reason)
        slippage = slippage_points * self.futures_specs['contract_value'] * trade.contracts

        if trade.direction == 'long':
            points = (exit_price - trade.entry_price) * trade.contracts
        else:
            points = (trade.entry_price - exit_price) * trade.contracts

        gross_pnl = points * self.futures_specs['contract_value']
        net_pnl = gross_pnl - commission - slippage

        trade.exit_price = exit_price
        trade.exit_time = exit_time
        trade.pnl = net_pnl

        self.closed_trades.append(trade)
        self.current_capital += net_pnl
        self.peak_equity = max(self.peak_equity, self.get_equity())
        self.equity_history.append(self.get_equity())

    def get_equity(self) -> float:
        return self.current_capital

    def get_mark_to_market_equity(self, current_price: float | None = None) -> float:
        """Return equity including unrealized PnL from open positions."""
        if current_price is None or not self.positions:
            return self.current_capital
        cv = self.futures_specs['contract_value']
        unrealized = 0.0
        for pos in self.positions:
            if pos.direction == 'long':
                unrealized += (current_price - pos.entry_price) * pos.contracts * cv
            else:
                unrealized += (pos.entry_price - current_price) * pos.contracts * cv
        return self.current_capital + unrealized

    def get_trade_log(self) -> pd.DataFrame:
        trades_data = []
        contract_value = self.futures_specs['contract_value']
        for trade in self.closed_trades:
            row = {
                'entry_time': trade.entry_time,
                'exit_time': trade.exit_time,
                'direction': trade.direction,
                'signal_type': trade.signal_type,
                'setup_tag': trade.setup_tag,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'contracts': trade.contracts,
                'pnl': trade.pnl,
                'reason': trade.reason,
                'mfe_points': trade.max_favorable_excursion_points,
                'mae_points': trade.max_adverse_excursion_points,
                'mfe_dollars': trade.max_favorable_excursion_points * trade.contracts * contract_value,
                'mae_dollars': trade.max_adverse_excursion_points * trade.contracts * contract_value,
            }
            for key, value in trade.metadata.items():
                row[f'entry_{key}'] = value
            trades_data.append(row)
        return pd.DataFrame(trades_data)
