import pandas as pd
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config.backtest_config import FUTURES_SPECS, BACKTEST_CONFIG, MEAN_REVERSION_PARAMS
from backtest.engine import BacktestEngine
from backtest.portfolio import Portfolio

def load_data(filepath: str) -> pd.DataFrame:
    """Load NQ minute data"""
    df = pd.read_csv(filepath)
    # Handle different column names
    if 'datetime' in df.columns:
        df['time'] = pd.to_datetime(df['datetime'])
    elif 'time' in df.columns:
        df['time'] = pd.to_datetime(df['time'])
    
    # Ensure OHLCV columns exist
    df.columns = df.columns.str.lower()
    return df.sort_values('time').reset_index(drop=True)

def run_backtest():
    """Execute backtest"""
    print("="*60)
    print("NQ Scalper Backtest - Mean Reversion Strategy")
    print("="*60)
    
    # Load data
    data_path = 'data/raw/NQ_1min_2019-2024.csv'
    if not Path(data_path).exists():
        print(f"\n❌ Data file not found: {data_path}")
        print("📥 Download from Kaggle:")
        print("   https://www.kaggle.com/datasets/youneseloiarm/nasdaq-cme-future-nq")
        print("\n📝 Place the CSV file in: data/raw/")
        return
    
    print(f"\n📊 Loading data...")
    data = load_data(data_path)
    print(f"✅ Loaded {len(data):,} bars")
    print(f"   From: {data['time'].min()}")
    print(f"   To:   {data['time'].max()}")
    
    # Run backtest
    print(f"\n🔄 Running backtest...")
    portfolio = Portfolio(BACKTEST_CONFIG['starting_capital'], FUTURES_SPECS)
    backtester = BacktestEngine(data, portfolio, FUTURES_SPECS, MEAN_REVERSION_PARAMS)
    
    results = backtester.run()
    
    # Display results
    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    print(f"Total Trades:        {results['total_trades']}")
    print(f"Winning Trades:      {results['winning_trades']}")
    print(f"Losing Trades:       {results['losing_trades']}")
    print(f"Win Rate:            {results['win_rate']:.2f}%")
    print(f"\nTotal P&L:           ${results['total_pnl']:,.2f}")
    print(f"Avg Win:             ${results['avg_win']:,.2f}")
    print(f"Avg Loss:            ${results['avg_loss']:,.2f}")
    print(f"Profit Factor:       {results['profit_factor']:.2f}")
    print(f"\nFinal Equity:        ${results['final_equity']:,.2f}")
    print(f"Return:              {results['return_pct']:.2f}%")
    print(f"Sharpe Ratio:        {results['sharpe_ratio']:.2f}")
    print("="*60)
    
    # Save results
    Path('results/trades').mkdir(parents=True, exist_ok=True)
    results['trades'].to_csv('results/trades/trade_log.csv', index=False)
    print(f"\n💾 Trade log saved: results/trades/trade_log.csv")

if __name__ == "__main__":
    run_backtest()
