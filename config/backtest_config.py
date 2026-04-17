# NQ Futures Specifications
FUTURES_SPECS = {
    'symbol': 'NQ',
    'contract_value': 20,
    'commission_per_round_trip': 8.50,
    'slippage_points': 0.5,
}

# Backtest Settings
BACKTEST_CONFIG = {
    'starting_capital': 50000,
    'risk_per_trade_pct': 0.02,
    'max_contracts': 5,
}

# Mean Reversion Strategy
MEAN_REVERSION_PARAMS = {
    'rsi_period': 14,
    'rsi_oversold': 30,
    'profit_target_points': 5,
    'stop_loss_points': 3,
    'max_hold_minutes': 30,
}
