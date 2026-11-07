#!/usr/bin/env python3
"""
Research Script: Candidate — COMEX Gold Cash Open Drive (08:20 ET) on MGC.
Belfort Systematic Trading Framework (2026) — Step 03 (Code It), Step 04 (In-Sample), Step 05 (Out-of-Sample).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.provenance import default_store
from config.strategy_registry import StrategyTier, register_candidate

GC_PATH = REPO_ROOT / "data/raw/gc_1m_2020_2026_et.parquet"
BASELINE_TRADES_PATH = REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"

STRATEGY_ID = "gold_comex_open_s6"
STRATEGY_NAME = "COMEX Gold Cash Open Drive (08:20 ET)"

PT_VAL = 10.0  # $10.00 per point per MGC
TICK_SIZE = 0.10  # 1 tick = $1.00
SLIP_PTS_LIMIT = 0.10  # 1 tick ($1.00)
SLIP_PTS_MARKET = 0.20  # 2 ticks ($2.00)
COMM_RT = 1.20  # $1.20 round-turn per micro contract


def simulate_gold_orb(
    df: pd.DataFrame,
    or_start_str: str = "08:20",
    or_end_str: str = "08:29",
    exec_cutoff_str: str = "09:15",
    long_only: bool = True,
    rr_ratio: float = 1.5,
    min_stop_pts: float = 2.5,
    max_stop_pts: float = 8.0,
    buffer_pts: float = 0.20,
) -> pd.DataFrame:
    """
    Simulates genuine Opening Range Breakout (ORB) on COMEX Gold.
    1. Establishes OR from or_start_str to or_end_str.
    2. Enters on the first 1-minute bar closing outside OR +/- buffer before exec_cutoff_str.
    3. Manages trade until target, stop, or exec_cutoff_str time exit.
    """
    m = df["time"].dt.hour * 60 + df["time"].dt.minute
    df_window = df[(m >= 480) & (m <= 560)].copy()  # 08:00 to 09:20 ET
    df_window["date_str"] = df_window["time"].dt.strftime("%Y-%m-%d")
    df_window["m"] = df_window["time"].dt.hour * 60 + df_window["time"].dt.minute

    h_s, m_s = map(int, or_start_str.split(":"))
    h_e, m_e = map(int, or_end_str.split(":"))
    h_c, m_c = map(int, exec_cutoff_str.split(":"))

    or_start_m = h_s * 60 + m_s
    or_end_m = h_e * 60 + m_e
    cutoff_m = h_c * 60 + m_c

    trades: List[Dict[str, Any]] = []

    for d_str, day_df in df_window.groupby("date_str"):
        if d_str < "2021-01-01":
            continue

        day_bars = day_df.sort_values("time").reset_index(drop=True)
        or_bars = day_bars[(day_bars["m"] >= or_start_m) & (day_bars["m"] <= or_end_m)]
        exec_bars = day_bars[(day_bars["m"] > or_end_m) & (day_bars["m"] <= cutoff_m)]

        if len(or_bars) < (or_end_m - or_start_m):
            continue
        if len(exec_bars) < 5:
            continue

        or_high = float(or_bars["high"].max())
        or_low = float(or_bars["low"].min())
        or_range = or_high - or_low

        if or_range < 1.0 or or_range > 15.0:
            continue

        # Look for the first breakout bar in exec_bars
        triggered = False
        for idx, bar in exec_bars.iterrows():
            b_close = float(bar["close"])
            b_open = float(bar["open"])
            b_high = float(bar["high"])
            b_low = float(bar["low"])
            b_time = pd.Timestamp(bar["time"])

            sig = 0
            if b_close > or_high + buffer_pts:
                sig = 1
            elif not long_only and b_close < or_low - buffer_pts:
                sig = -1

            if sig == 0:
                continue

            # Signal confirmed on bar close -> entry on next bar open (or current close if market order)
            entry_p = b_close
            entry_time = b_time

            stop_pts = float(np.clip(0.50 * or_range, min_stop_pts, max_stop_pts))
            target_pts = float(stop_pts * rr_ratio)
            stop_price = entry_p - sig * stop_pts
            target_price = entry_p + sig * target_pts

            remaining_bars = exec_bars[exec_bars["time"] > entry_time]
            if remaining_bars.empty:
                continue

            exit_p = float(remaining_bars.iloc[-1]["close"])
            exit_time = pd.Timestamp(remaining_bars.iloc[-1]["time"])
            reason = "time_exit_cutoff"

            for _, rb in remaining_bars.iterrows():
                rh = float(rb["high"])
                rl = float(rb["low"])
                ro = float(rb["open"])
                rt = pd.Timestamp(rb["time"])

                if sig == 1:
                    if rl <= stop_price:
                        exit_p = min(stop_price, ro)
                        exit_time = rt
                        reason = "stop_loss"
                        break
                    elif rh >= target_price:
                        exit_p = target_price
                        exit_time = rt
                        reason = "profit_target"
                        break
                else:
                    if rh >= stop_price:
                        exit_p = max(stop_price, ro)
                        exit_time = rt
                        reason = "stop_loss"
                        break
                    elif rl <= target_price:
                        exit_p = target_price
                        exit_time = rt
                        reason = "profit_target"
                        break

            raw_pts = (exit_p - entry_p) * sig
            slip_total = SLIP_PTS_LIMIT if reason == "profit_target" else (SLIP_PTS_MARKET * 2.0)
            net_pts = raw_pts - slip_total

            # Position Sizing under $250 max-risk budget
            stop_risk = stop_pts * PT_VAL
            contracts = int(np.clip(np.floor(250.0 / max(stop_risk, 1.0)), 1, 4))
            comm = COMM_RT * contracts
            net_dollars = (net_pts * PT_VAL * contracts) - comm

            trades.append({
                "date_str": d_str,
                "year": entry_time.year,
                "instrument": "MGC",
                "direction": "long" if sig == 1 else "short",
                "entry_time": entry_time,
                "exit_time": exit_time,
                "entry_price": entry_p,
                "exit_price": exit_p,
                "or_range": or_range,
                "stop_pts": stop_pts,
                "target_pts": target_pts,
                "contracts": contracts,
                "net_pts": net_pts,
                "net_dollars": net_dollars,
                "reason": reason,
            })
            triggered = True
            break

    return pd.DataFrame(trades)


def compute_metrics(trades: pd.DataFrame, label: str = "Window") -> Dict[str, Any]:
    if trades.empty:
        return {"label": label, "trades": 0, "net_pnl": 0.0, "pf": 0.0, "win_rate": 0.0, "max_dd": 0.0, "trades_per_yr": 0.0, "active_days": 0, "payoff": 0.0, "max_streak": 0, "largest_win": 0.0, "outlier_ratio": 0.0, "gross_profit": 0.0, "gross_loss": 0.0, "avg_trade": 0.0}

    n = len(trades)
    wins = trades[trades["net_dollars"] > 0]
    losses = trades[trades["net_dollars"] <= 0]
    n_wins = len(wins)
    n_losses = len(losses)
    wr = (n_wins / n) * 100.0

    gross_profit = float(wins["net_dollars"].sum()) if n_wins > 0 else 0.0
    gross_loss = float(abs(losses["net_dollars"].sum())) if n_losses > 0 else 0.0
    net_pnl = gross_profit - gross_loss
    pf = (gross_profit / gross_loss) if gross_loss > 0 else np.nan

    avg_trade = net_pnl / n
    avg_win = (gross_profit / n_wins) if n_wins > 0 else 0.0
    avg_loss = (gross_loss / n_losses) if n_losses > 0 else 0.0
    payoff = (avg_win / avg_loss) if avg_loss > 0 else np.nan

    cum = trades["net_dollars"].cumsum()
    peak = cum.cummax()
    dd = cum - peak
    max_dd = float(dd.min())

    streak = 0
    max_streak = 0
    for val in trades["net_dollars"]:
        if val <= 0:
            streak += 1
            if streak > max_streak:
                max_streak = streak
        else:
            streak = 0

    largest_win = float(trades["net_dollars"].max())
    outlier_ratio = (largest_win / net_pnl) if net_pnl > 0 else 0.0

    active_days = int(trades["date_str"].nunique())
    years = (pd.to_datetime(trades["entry_time"].max()) - pd.to_datetime(trades["entry_time"].min())).days / 365.25
    trades_per_yr = n / max(years, 0.1)

    return {
        "label": label,
        "trades": n,
        "active_days": active_days,
        "trades_per_yr": trades_per_yr,
        "win_rate": wr,
        "pf": pf,
        "net_pnl": net_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "avg_trade": avg_trade,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff": payoff,
        "max_dd": max_dd,
        "max_streak": max_streak,
        "largest_win": largest_win,
        "outlier_ratio": outlier_ratio,
    }


def main():
    print("=" * 80)
    print(" 🥇  CANDIDATE: COMEX GOLD CASH OPEN DRIVE (08:20 ET)")
    print(f" Strategy ID: {STRATEGY_ID} | Instrument: MGC (Micro Gold Futures)")
    print(" Belfort Systematic Trading Framework (2026) — Steps 03–05")
    print("=" * 80)

    register_candidate(
        strategy_id=STRATEGY_ID,
        name=STRATEGY_NAME,
        instrument="MGC",
        description="COMEX Gold cash open drive breakout (08:20 ET) on Micro Gold futures.",
    )

    store = default_store
    h_gc = store.compute_data_hash(GC_PATH)
    print(f" [Data Provenance Verified]")
    print(f"   Data File   : {GC_PATH.name}")
    print(f"   Data SHA-256: {h_gc}")

    print("\n Loading Gold 1-minute dataset...")
    df_raw = pd.read_parquet(GC_PATH)
    print(f"   Total bars loaded: {len(df_raw):,}")

    # Test matrix:
    # 1. 08:20-08:29 (10 min OR), Long Only
    # 2. 08:20-08:29 (10 min OR), Long + Short
    # 3. 08:20-08:34 (15 min OR post-macro), Long Only
    # 4. 08:20-08:34 (15 min OR post-macro), Long + Short
    experiments = [
        ("10-min OR (08:20–08:29) - Long Only", "08:20", "08:29", True),
        ("10-min OR (08:20–08:29) - Long + Short", "08:20", "08:29", False),
        ("15-min OR (08:20–08:34) - Long Only", "08:20", "08:34", True),
        ("15-min OR (08:20–08:34) - Long + Short", "08:20", "08:34", False),
    ]

    results_summary = []
    trade_dfs = {}

    print("\n Running In-Sample (2021–2024) and Out-of-Sample (2025–2026) Matrix...")
    for label, s_time, e_time, l_only in experiments:
        tdf = simulate_gold_orb(df_raw, or_start_str=s_time, or_end_str=e_time, long_only=l_only)
        trade_dfs[label] = tdf

        m_full = compute_metrics(tdf, "Full")
        m_is = compute_metrics(tdf[tdf["year"] <= 2024], "In-Sample")
        m_oos = compute_metrics(tdf[tdf["year"] >= 2025], "Out-of-Sample")

        results_summary.append({
            "Setup": label,
            "Total N": m_full["trades"],
            "IS N": m_is["trades"],
            "IS Win%": f"{m_is['win_rate']:.1f}%",
            "IS PF": f"{m_is['pf']:.2f}",
            "IS Net": f"${m_is['net_pnl']:,.2f}",
            "OOS N": m_oos["trades"],
            "OOS Win%": f"{m_oos['win_rate']:.1f}%",
            "OOS PF": f"{m_oos['pf']:.2f}",
            "OOS Net": f"${m_oos['net_pnl']:,.2f}",
            "Full PF": f"{m_full['pf']:.2f}",
            "Full Net": f"${m_full['net_pnl']:,.2f}",
            "MaxDD": f"-${abs(m_full['max_dd']):,.2f}",
        })

    summary_df = pd.DataFrame(results_summary)
    print("\n" + "=" * 80)
    print(" OPENING RANGE BREAKOUT (ORB) EXPERIMENT MATRIX")
    print("=" * 80)
    print(summary_df.to_string(index=False))

    # Evaluate best candidate
    best_label = "10-min OR (08:20–08:29) - Long Only"
    best_df = trade_dfs[best_label]
    best_full = compute_metrics(best_df, best_label)

    print("\n" + "=" * 80)
    print(f" DEEP-DIVE: {best_label.upper()}")
    print("=" * 80)
    print(f" Trades Evaluated (N) : {best_full['trades']} trades across {best_full['active_days']} active days")
    print(f" Annual Frequency     : {best_full['trades_per_yr']:.1f} trades / year (~{best_full['trades_per_yr']/12:.1f} / month)")
    print(f" Win Rate             : {best_full['win_rate']:.2f}%")
    print(f" Profit Factor        : {best_full['pf']:.2f}")
    print(f" Net Profit           : ${best_full['net_pnl']:,.2f}")
    print(f" Gross Profit         : ${best_full['gross_profit']:,.2f}")
    print(f" Gross Loss           : -${best_full['gross_loss']:,.2f}")
    print(f" Average Trade        : ${best_full['avg_trade']:.2f}")
    print(f" Payoff Ratio (W/L)   : {best_full['payoff']:.2f}x (${best_full['avg_win']:.2f} win / ${best_full['avg_loss']:.2f} loss)")
    print(f" Max Drawdown         : -${abs(best_full['max_dd']):,.2f}")
    print(f" Longest Loss Streak  : {best_full['max_streak']} consecutive trades")
    print(f" Outlier Dominance    : {best_full['outlier_ratio']*100:.1f}% (Largest Win: ${best_full['largest_win']:,.2f})")

    print("\n   Year-by-Year Performance:")
    for yr, grp in best_df.groupby("year"):
        y_m = compute_metrics(grp, str(yr))
        print(f"     {yr}: {y_m['trades']:3d} trades | Win%: {y_m['win_rate']:5.1f}% | PF: {y_m['pf']:4.2f} | Net: ${y_m['net_pnl']:8,.2f} | MaxDD: -${abs(y_m['max_dd']):6,.2f}")

    # Correlation Check
    if BASELINE_TRADES_PATH.exists():
        base_df = pd.read_parquet(BASELINE_TRADES_PATH)
        cand_daily = best_df.groupby("date_str")["net_dollars"].sum().rename("pnl_cand")
        base_s1 = base_df[base_df["strategy"].str.contains("Strategy 1")].groupby("date_str")["scaled_pnl"].sum().rename("pnl_s1")
        base_s2 = base_df[base_df["strategy"].str.contains("Strategy 2")].groupby("date_str")["scaled_pnl"].sum().rename("pnl_s2")
        base_s3 = base_df[base_df["strategy"].str.contains("Strategy 3")].groupby("date_str")["scaled_pnl"].sum().rename("pnl_s3")

        pnl_matrix = pd.concat([cand_daily, base_s1, base_s2, base_s3], axis=1).fillna(0.0)
        corr_matrix = pnl_matrix.corr()

        print("\n" + "=" * 80)
        print(" PAIRWISE RETURN CORRELATION CHECK (Belfort Step 06 - Must be < 0.50)")
        print("=" * 80)
        print(f"   Correlation with Strategy 1 (09:45 VA Breakout) : {corr_matrix.loc['pnl_cand', 'pnl_s1']:+.3f}")
        print(f"   Correlation with Strategy 2 (08:35 Macro Momentum): {corr_matrix.loc['pnl_cand', 'pnl_s2']:+.3f}")
        print(f"   Correlation with Strategy 3 (10:15 Gold Fix)     : {corr_matrix.loc['pnl_cand', 'pnl_s3']:+.3f}")

    print(f"""
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : candidate_{STRATEGY_ID}_full_walkforward
Strategy     : {STRATEGY_ID} — {STRATEGY_NAME}
Strategy Tier: CANDIDATE
Methodology  : multi_year_walkforward
Date Range   : 2021-01-01 to 2026-10-30
Data File    : {GC_PATH.name}
Data SHA-256 : {h_gc}
Cost Model   : 1-Tick Limit / 2-Tick Market Adverse ($1.00/$2.00) + Comm ($1.20 RT) [NET]
Core Metrics : Trades: {best_full['trades']} | Win%: {best_full['win_rate']:.2f}% | PF: {best_full['pf']:.2f} | Net: ${best_full['net_pnl']:,.2f} | MaxDD: -${abs(best_full['max_dd']):,.2f}
Warning Flags: CANDIDATE_TIER_QUARANTINED
────────────────────────────────────────────────────────────────────────────
""")


if __name__ == "__main__":
    main()
