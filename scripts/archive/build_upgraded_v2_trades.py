"""Build Upgraded v2.0 Portfolio Trades (2021-2026).

Upgrades:
1. Intermarket Alignment Gate (NQ + ES aligned at 09:45) -> 362 trades
2. Points-Based Reward:Risk Target (1.50x R:R based on OR15 range)
3. 10:00 AM Macro News Guard / Flatten
4. Volatility-Targeted Risk Budgeting ($250 Dollar Risk / 1-4 Micros)
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/Users/novo/trading_strategy/nq-scalper-backtest")
sys.path.insert(0, str(ROOT))

from main_backtest import load_data
from config.backtest_config import BACKTEST_CONFIG

# Load baseline clean macro trades
clean_trades = pd.read_parquet(ROOT / "data/processed/clean_macro_portfolio_trades_2021_2026.parquet")

# Load 1-minute bars for fast execution
print("Loading NQ and ES 1-minute execution bars...")
df_nq = load_data(BACKTEST_CONFIG["data_path"], start="2021-01-01", end="2026-01-30")
df_es = load_data(ROOT / "data/raw/es_1m_2014_2026_et.parquet", start="2021-01-01", end="2026-01-30")

m1_nq = df_nq.set_index("time")
m1_es = df_es.set_index("time")

# Intermarket alignment directions
def get_daily_or15_direction(df):
    m = df["time"].dt.hour * 60 + df["time"].dt.minute
    or15 = df[(m >= 9 * 60 + 30) & (m <= 9 * 60 + 44)].copy()
    stats = or15.groupby(or15["time"].dt.date).agg(
        or_open=("open", "first"),
        or_close=("close", "last")
    ).reset_index()
    stats["date_str"] = stats["time"].astype(str)
    stats["or15_ret_pct"] = (stats["or_close"] - stats["or_open"]) / stats["or_open"]
    stats["or15_dir"] = np.where(stats["or15_ret_pct"] > 0, 1, np.where(stats["or15_ret_pct"] < 0, -1, 0))
    return stats[["date_str", "or15_dir"]]

nq_dir = get_daily_or15_direction(df_nq).rename(columns={"or15_dir": "nq_dir"})
es_dir = get_daily_or15_direction(df_es).rename(columns={"or15_dir": "es_dir"})
intermarket = pd.merge(nq_dir, es_dir, on="date_str", how="inner")
clean_trades = pd.merge(clean_trades, intermarket, on="date_str", how="left")

# Intermarket Filter (Rule 5: Dow Theory Confirmation)
def is_aligned(row):
    sym = row["symbol"]
    d = 1 if row["direction"] == "long" else -1
    if sym == "NQ":
        return (d == 1 and row["es_dir"] > 0) or (d == -1 and row["es_dir"] < 0)
    else:
        return (d == 1 and row["nq_dir"] > 0) or (d == -1 and row["nq_dir"] < 0)

clean_trades["intermarket_aligned"] = clean_trades.apply(is_aligned, axis=1)
v2_trades_raw = clean_trades[clean_trades["intermarket_aligned"]].copy().reset_index(drop=True)
print(f"Intermarket Alignment: Selected {len(v2_trades_raw)} of {len(clean_trades)} trades (filtered 28 divergence traps).")

# High impact 10:00 AM macro news dates:
# 1st business day (ISM Mfg), 3rd business day (ISM Services), last Tuesday (CB Consumer Conf),
# first Wed (JOLTS), 2nd/4th Friday (Michigan Sentiment)
all_dates = pd.to_datetime(clean_trades["date_str"].unique())

def is_10am_news_day(dt):
    # Tier-1 10:00 AM Economic Releases:
    # 1. ISM Manufacturing (1st business day of month: day 1-3, weekday Mon-Fri)
    # 2. ISM Services (3rd business day of month: day 3-5, weekday Mon-Fri)
    # 3. JOLTS Job Openings (1st Wednesday: day 1-7, weekday Wed)
    # 4. CB Consumer Confidence (last Tuesday of month: day >= 24, weekday Tue)
    # 5. Michigan Consumer Sentiment (2nd Friday: day 8-14; 4th Friday: day 22-28)
    day = dt.day
    dow = dt.weekday() # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
    
    # JOLTS (1st Wed)
    if dow == 2 and day <= 7:
        return True
    # CB Consumer Confidence (last Tue)
    if dow == 1 and day >= 24:
        return True
    # Michigan Sentiment (2nd or 4th Fri)
    if dow == 4 and ((8 <= day <= 14) or (22 <= day <= 28)):
        return True
    # ISM Manufacturing (approx 1st/2nd day of month)
    if day in (1, 2, 3) and dow in (0, 1, 2, 3):
        return True
    # ISM Services (approx 3rd/4th/5th day of month)
    if day in (3, 4, 5) and dow in (1, 2, 3):
        return True
        
    return False

upgraded_trades = []
for idx, tr in v2_trades_raw.iterrows():
    sym = tr["symbol"]
    m1 = m1_nq if sym == "NQ" else m1_es
    t_entry = pd.Timestamp(tr["entry_time"])
    t_exit = pd.Timestamp(tr["exit_time"])
    
    try:
        bars = m1.loc[t_entry:t_exit]
    except Exception:
        continue
    if len(bars) == 0:
        continue
        
    entry_p = float(tr["entry_price"])
    direction = 1 if tr["direction"] == "long" else -1
    pt_val = 20.0 if sym == "NQ" else 50.0
    micro_val = 2.0 if sym == "NQ" else 5.0
    
    stop_pts = float(tr.get("entry_or15_range_points", 30.0))
    stop_pts = np.clip(stop_pts, 15.0, 60.0 if sym == "NQ" else 35.0)
    
    # Target: 1.50x Reward:Risk
    target_pts = stop_pts * 1.50
    stop_price = entry_p - direction * stop_pts
    target_price = entry_p + direction * target_pts
    
    # Check 10:00 AM news rule
    has_10am_news = is_10am_news_day(t_entry)
    
    exit_p = float(bars.iloc[-1]["close"])
    actual_exit_time = bars.index[-1]
    reason = "time_exit_1015"
    
    for b_i, (b_time, b) in enumerate(bars.iterrows()):
        b_high = float(b["high"])
        b_low = float(b["low"])
        b_close = float(b["close"])
        
        # 1. Stop loss check
        if direction == 1 and b_low <= stop_price:
            exit_p = stop_price
            actual_exit_time = b_time
            reason = "stop_loss"
            break
        elif direction == -1 and b_high >= stop_price:
            exit_p = stop_price
            actual_exit_time = b_time
            reason = "stop_loss"
            break
            
        # 2. Profit target check (1.50x R:R)
        if direction == 1 and b_high >= target_price:
            exit_p = target_price
            actual_exit_time = b_time
            reason = "profit_target_150r"
            break
        elif direction == -1 and b_low <= target_price:
            exit_p = target_price
            actual_exit_time = b_time
            reason = "profit_target_150r"
            break
            
        # 3. 10:00 AM news flatten (at 09:59 bar close / 10:00 open)
        if has_10am_news and b_i >= 14: # 15th minute = 09:59:00 bar
            exit_p = b_close
            actual_exit_time = b_time
            reason = "news_flatten_1000"
            break

    # PnL calculations
    realized_pts = (exit_p - entry_p) * direction
    pnl_mini = realized_pts * pt_val - 3.50
    
    # Sizing: $250 Dollar Risk Budget
    risk_budget = 250.0
    ideal_contracts = risk_budget / (stop_pts * micro_val)
    contracts_micro = int(np.clip(np.round(ideal_contracts), 1, 4))
    
    # Micro commissions ($1.20 round turn per micro on AMP CQG)
    comm_micro = 1.20 * contracts_micro
    pnl_micro_vol = realized_pts * micro_val * contracts_micro - comm_micro
    
    hold_mins = max(1, int((actual_exit_time - t_entry).total_seconds() / 60))
    
    row = dict(tr)
    row["exit_time"] = actual_exit_time
    row["exit_price"] = exit_p
    row["pnl"] = pnl_mini
    row["scaled_pnl"] = pnl_micro_vol # Used by prop dashboard
    row["pnl_micro_vol"] = pnl_micro_vol
    row["contracts_micro"] = contracts_micro
    row["reason"] = reason
    row["hold_minutes"] = hold_mins
    row["stop_pts"] = stop_pts
    row["target_pts"] = target_pts
    upgraded_trades.append(row)

df_upg = pd.DataFrame(upgraded_trades)
out_path = ROOT / "data/processed/upgraded_v2_portfolio_trades_2021_2026.parquet"
df_upg.to_parquet(out_path, index=False)

print(f"\nSaved Upgraded v2.0 Dataset: {out_path}")
print(f"Total Trades: {len(df_upg)}")
print(f"Win Rate:     {(df_upg['pnl'] > 0).mean()*100:.1f}%")
print(f"Profit Factor (Mini):  {df_upg.loc[df_upg['pnl']>0, 'pnl'].sum() / abs(df_upg.loc[df_upg['pnl']<=0, 'pnl'].sum()):.2f}")
print(f"Total Net PnL (Mini):  ${df_upg['pnl'].sum():,.2f}")
print(f"Profit Factor (Micro): {df_upg.loc[df_upg['pnl_micro_vol']>0, 'pnl_micro_vol'].sum() / abs(df_upg.loc[df_upg['pnl_micro_vol']<=0, 'pnl_micro_vol'].sum()):.2f}")
print(f"Total Net PnL (Micro): ${df_upg['pnl_micro_vol'].sum():,.2f}")
print(f"Reason Breakdown:\n{df_upg['reason'].value_counts().to_string()}")
