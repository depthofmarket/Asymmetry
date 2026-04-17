import pandas as pd
import numpy as np
import ta
from datetime import datetime

class BacktestEngine:
    """Core backtesting engine for NQ futures"""
    
    def __init__(self, data: pd.DataFrame, portfolio, futures_specs: dict, strategy_params: dict):
        self.data = data.reset_index(drop=True)
        self.portfolio = portfolio
        self.futures_specs = futures_specs
        self.strategy_params = strategy_params
        self.equity_curve = []
        
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate technical indicators"""
        df = df.copy()
        
        # RSI
        df['rsi'] = ta.momentum.rsi(df['close'], length=self.strategy_params['rsi_period'])
        
        # Bollinger Bands
        bb = ta.volatility.bollinger_bands(
            df['close'],
            length=20,
            std=2.0
        )
        df['bb_upper'] = bb.iloc[:, 0]
        df['bb_middle'] = bb.iloc[:, 1]
        df['bb_lower'] = bb.iloc[:, 2]
        
        # ATR
        df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'], length=14)
        
        return df
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Generate entry/exit signals based on mean reversion"""
        df = df.copy()
        df['signal'] = 0
        
        for i in range(1, len(df)):
            # Entry: RSI oversold + price below lower BB
            if (df.loc[i, 'rsi'] < self.strategy_params['rsi_oversold'] and
                df.loc[i, 'close'] < df.loc[i, 'bb_lower']):
                df.loc[i, 'signal'] = 1
            
            # Exit: RSI overbought or price above middle BB
            elif (df.loc[i, 'rsi'] > 70 or df.loc[i, 'close'] > df.loc[i, 'bb_middle']):
                df.loc[i, 'signal'] = -1
        
        return df
    
    def run(self) -> dict:
        """Execute backtest"""
        df = self.data.copy()
        df = self.calculate_indicators(df)
        df = self.generate_signals(df)
        
        open_position = None
        entry_bar = None
        
        for i in range(1, len(df)):
            close_price = df.loc[i, 'close']
            timestamp = i
            
            # Position management
            if open_position is not None:
                exit_flag = False
                exit_reason = ""
                
                # Profit target
                if close_price >= (open_position.entry_price + self.strategy_params['profit_target_points']):
                    exit_flag = True
                    exit_reason = "profit_target"
                
                # Stop loss
                elif close_price <= (open_position.entry_price - self.strategy_params['stop_loss_points']):
                    exit_flag = True
                    exit_reason = "stop_loss"
                
                # Time-based exit
                elif i - entry_bar >= self.strategy_params['max_hold_minutes']:
                    exit_flag = True
                    exit_reason = "time_exit"
                
                # Exit signal
                elif df.loc[i, 'signal'] == -1:
                    exit_flag = True
                    exit_reason = "signal"
                
                if exit_flag:
                    open_position.reason = exit_reason
                    self.portfolio.exit_position(close_price, timestamp, 0)
                    open_position = None
            
            # Entry conditions
            if open_position is None and df.loc[i, 'signal'] == 1:
                risk_amount = self.portfolio.current_capital * self.strategy_params['risk_per_trade_pct']
                stop_loss_amount = self.strategy_params['stop_loss_points'] * 20
                contracts = max(1, int(risk_amount / stop_loss_amount))
                contracts = min(contracts, self.strategy_params['max_contracts'])
                
                open_position = self.portfolio.enter_position(close_price, contracts, timestamp)
                entry_bar = i
            
            self.equity_curve.append(self.portfolio.get_equity())
        
        # Close any open position
        if open_position is not None:
            self.portfolio.exit_position(df.loc[len(df)-1, 'close'], len(df)-1, 0)
        
        return self.get_results()
    
    def get_results(self) -> dict:
        """Calculate performance metrics"""
        trades_df = self.portfolio.get_trade_log()
        
        if len(trades_df) == 0:
            return {'error': 'No trades generated'}
        
        total_trades = len(trades_df)
        winning_trades = len(trades_df[trades_df['pnl'] > 0])
        losing_trades = len(trades_df[trades_df['pnl'] <= 0])
        
        total_pnl = trades_df['pnl'].sum()
        avg_win = trades_df[trades_df['pnl'] > 0]['pnl'].mean() if winning_trades > 0 else 0
        avg_loss = trades_df[trades_df['pnl'] <= 0]['pnl'].mean() if losing_trades > 0 else 0
        
        win_sum = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
        loss_sum = abs(trades_df[trades_df['pnl'] <= 0]['pnl'].sum())
        profit_factor = win_sum / loss_sum if loss_sum > 0 else 0
        
        equity_array = np.array(self.equity_curve)
        returns = np.diff(equity_array) / equity_array[:-1]
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 * 390) if np.std(returns) > 0 else 0
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': (winning_trades / total_trades * 100),
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe,
            'final_equity': self.portfolio.get_equity(),
            'return_pct': ((self.portfolio.get_equity() - self.portfolio.initial_capital) / 
                          self.portfolio.initial_capital * 100),
            'trades': trades_df
        }
