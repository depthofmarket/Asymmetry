#!/usr/bin/env python3
"""
Print Complete Multi-Dimensional Metrics Matrix for the Unified Ensemble.
"""

from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

def get_stats(t: pd.DataFrame) -> dict:
    n = len(t)
    if n == 0:
        return {}
    wins = t[t["pnl"] > 0]["pnl"]
    losses = t[t["pnl"] <= 0]["pnl"]
    tot_pnl = t["pnl"].sum()
    pos = wins.sum()
    neg = abs(losses.sum())
    pf = pos / neg if neg > 0 else np.nan
    wr = len(wins) / n * 100
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 0
    payoff = avg_win / avg_loss if avg_loss > 0 else np.nan
    exp = t["pnl"].mean()
    
    cum = t["pnl"].cumsum()
    dd = (cum.cummax() - cum).max()
    ret_dd = tot_pnl / dd if dd > 0 else np.nan
    
    daily = t.groupby("date_str")["pnl"].sum()
    d_mean = daily.mean()
    d_std = daily.std()
    sharpe = (d_mean / d_std) * np.sqrt(252) if d_std > 0 else np.nan
    down_std = daily[daily < 0].std()
    sortino = (d_mean / down_std) * np.sqrt(252) if down_std > 0 else np.nan
    
    return {
        "trades": n,
        "wr": wr,
        "pf": pf,
        "net": tot_pnl,
        "avg_trade": exp,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff": payoff,
        "max_dd": dd,
        "ret_dd": ret_dd,
        "sharpe": sharpe,
        "sortino": sortino,
    }

def main():
    p = ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"
    df = pd.read_parquet(p)
    df["entry_time"] = pd.to_datetime(df["entry_time"])

    print("=" * 80)
    print("  1. FULL ENSEMBLE OVERVIEW (543 TRADES, 2021-2026)")
    print("=" * 80)
    s_all = get_stats(df)
    for k, v in s_all.items():
        if isinstance(v, (int, float)):
            print(f"  {k:15s}: {v:,.2f}")
        else:
            print(f"  {k:15s}: {v}")

    print("\n" + "=" * 80)
    print("  2. IN-SAMPLE DEV (2021-2024) VS OUT-OF-SAMPLE (2025-2026)")
    print("=" * 80)
    dev = get_stats(df[df["year"] <= 2024])
    oos = get_stats(df[df["year"] >= 2025])
    print(f"  DEV: {dev['trades']} trades | WR {dev['wr']:.1f}% | PF {dev['pf']:.2f} | Net ${dev['net']:,.2f} | Sharpe {dev['sharpe']:.2f} | Sortino {dev['sortino']:.2f} | Ret/DD {dev['ret_dd']:.2f}x | MaxDD ${dev['max_dd']:,.2f}")
    print(f"  OOS: {oos['trades']} trades | WR {oos['wr']:.1f}% | PF {oos['pf']:.2f} | Net ${oos['net']:,.2f} | Sharpe {oos['sharpe']:.2f} | Sortino {oos['sortino']:.2f} | Ret/DD {oos['ret_dd']:.2f}x | MaxDD ${oos['max_dd']:,.2f}")

    print("\n" + "=" * 80)
    print("  3. STRATEGY BREAKDOWN")
    print("=" * 80)
    for st in sorted(df["strategy"].unique()):
        sub = df[df["strategy"] == st]
        s = get_stats(sub)
        print(f"  {st:45s}: {s['trades']:3d} tr | WR {s['wr']:5.1f}% | PF {s['pf']:4.2f} | Net ${s['net']:>9,.2f} | Sharpe {s['sharpe']:4.2f} | Ret/DD {s['ret_dd']:4.2f}x | MaxDD ${s['max_dd']:>7,.2f}")

    print("\n" + "=" * 80)
    print("  4. INSTRUMENT BREAKDOWN")
    print("=" * 80)
    for sym in ["MNQ", "MES", "MGC"]:
        sub = df[df["micro"] == sym]
        s = get_stats(sub)
        print(f"  {sym:10s}: {s['trades']:3d} tr | WR {s['wr']:5.1f}% | PF {s['pf']:4.2f} | Net ${s['net']:>9,.2f} | Sharpe {s['sharpe']:4.2f} | Ret/DD {s['ret_dd']:4.2f}x | MaxDD ${s['max_dd']:>7,.2f}")

    print("\n" + "=" * 80)
    print("  5. DIRECTIONAL BREAKDOWN (LONG VS SHORT)")
    print("=" * 80)
    for d in ["long", "short"]:
        sub = df[df["direction"] == d]
        s = get_stats(sub)
        print(f"  {d.upper():10s}: {s['trades']:3d} tr | WR {s['wr']:5.1f}% | PF {s['pf']:4.2f} | Net ${s['net']:>9,.2f} | Sharpe {s['sharpe']:4.2f} | Ret/DD {s['ret_dd']:4.2f}x | MaxDD ${s['max_dd']:>7,.2f}")

    print("\n" + "=" * 80)
    print("  6. CALENDAR YEAR BREAKDOWN")
    print("=" * 80)
    for y in sorted(df["year"].unique()):
        sub = df[df["year"] == y]
        s = get_stats(sub)
        print(f"  {y}: {s['trades']:3d} tr | WR {s['wr']:5.1f}% | PF {s['pf']:4.2f} | Net ${s['net']:>9,.2f} | Sharpe {s['sharpe']:4.2f} | Ret/DD {s['ret_dd']:4.2f}x | MaxDD ${s['max_dd']:>7,.2f}")

    print("\n" + "=" * 80)
    print("  7. MARKOV VOLATILITY REGIME BREAKDOWN")
    print("=" * 80)
    for mkv in ["low_vol", "mid_vol", "high_vol"]:
        sub = df[df["markov_state_label"] == mkv]
        s = get_stats(sub)
        print(f"  {mkv:10s}: {s['trades']:3d} tr | WR {s['wr']:5.1f}% | PF {s['pf']:4.2f} | Net ${s['net']:>9,.2f} | Sharpe {s['sharpe']:4.2f} | Ret/DD {s['ret_dd']:4.2f}x | MaxDD ${s['max_dd']:>7,.2f}")

if __name__ == "__main__":
    main()
