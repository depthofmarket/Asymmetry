import pandas as pd
import numpy as np
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Trade:
    """Individual trade record"""
    entry_time: datetime
    entry_price: float
    contracts: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    pnl: float = 0.0
    reason: str = "open"

class Portfolio:
    """Portfolio manager for NQ futures"""
    
    def __init__(self, initial_capital: float, futures_specs: dict):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.futures_specs = futures_specs
        
        self.positions: List[Trade] = []
        self.closed_trades: List[Trade] = []
        self.equity_history = [initial_capital]
        self.peak_equity = initial_capital
        
    def enter_position(self, entry_price: float, contracts: float, entry_time):
        """Open a new position"""
        trade = Trade(
            entry_time=entry_time,
            entry_price=entry_price,
            contracts=contracts
        )
        self.positions.append(trade)
        return trade
    
    def exit_position(self, exit_price: float, exit_time, trade_index: int = 0):
        """Close a position"""
        if trade_index >= len(self.positions):
            return
        
        trade = self.positions.pop(trade_index)
        commission = self.futures_specs['commission_per_round_trip']
        slippage = self.futures_specs['slippage_points'] * 20
        
        # Calculate P&L
        points = (exit_price - trade.entry_price) * trade.contracts
        gross_pnl = points * 20
        net_pnl = gross_pnl - commission - slippage
        
        trade.exit_price = exit_price
        trade.exit_time = exit_time
        trade.pnl = net_pnl
        
        self.closed_trades.append(trade)
        self.current_capital += net_pnl
        self.peak_equity = max(self.peak_equity, self.get_equity())
        self.equity_history.append(self.get_equity())
    
    def get_equity(self) -> float:
        """Current equity"""
        return self.current_capital
    
    def get_drawdown(self) -> float:
        """Current drawdown from peak"""
        if self.peak_equity > 0:
            return ((self.peak_equity - self.get_equity()) / self.peak_equity) * 100
        return 0
    
    def get_trade_log(self) -> pd.DataFrame:
        """Export trades as DataFrame"""
        trades_data = []
        for trade in self.closed_trades:
            trades_data.append({
                'entry_time': trade.entry_time,
                'exit_time': trade.exit_time,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'contracts': trade.contracts,
                'pnl': trade.pnl,
                'reason': trade.reason,
            })
        return pd.DataFrame(trades_data)
