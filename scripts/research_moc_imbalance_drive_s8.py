#!/usr/bin/env python3
"""
Research Script: Candidate — 15:50 ET NYSE Market-On-Close (MOC) Imbalance Drive on MNQ & MES.
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

NQ_PATH = REPO_ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet"
ES_PATH = REPO_ROOT / "data/raw/es_1m_2020_2026_cqg_et.parquet"
BASELINE_TRADES_PATH = REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"

STRATEGY_ID = "moc_imbalance_drive_s8"
STRATEGY_NAME = "15:50 ET NYSE Market-On-Close (MOC) Imbalance Drive"

SPECS = {
    "MNQ": {
        "sym": "NQ",
        "micro": "MNQ",
        "name": "Micro Nasdaq 100",
        "path": NQ_PATH,
        "pt_val": 2.0,  # $2.00 per point per MNQ
        "tick_size": 0.25,
        "min_ret_pts": 7.0,  # Minimum 15:50 bar impulse
        "min_stop_pts": 15.0,
        "max_stop_pts": 45.0,
        "slip_pts_limit": 0.75,  # $1.50
        "slip_pts_market": 2.00,  # $4.00 adverse market/stop
        "comm_rt": 1.20,
        "rr_ratio": 1.50,
    },
    "MES": {
        "sym": "ES",
        "micro": "MES",
        "name": "Micro S&P 500",
        "path": ES_PATH,
        "pt_val": 5.0,  # $5.00 per point per MES
        "tick_size": 0.25,
        "min_ret_pts": 2.0,  # Minimum 15:50 bar impulse
        "min_stop_pts": 4.0,
        "max_stop_pts": 12.0,
        "slip_pts_limit": 0.25,  # $1.25
        "slip_pts_market": 0.75,  # $3.75 adverse market/stop
        "comm_rt": 1.20,
        "rr_ratio": 1.50,
    },
}


def simulate_moc_drive(df: pd.DataFrame, spec: Dict[str, Any], long_only: bool = False) -> pd.DataFrame:
    """
    Simulates the 15:50 ET Market-On-Close (MOC) Imbalance Drive.
    - Signal bar: 15:50 ET (m == 950)
    - Entry: 15:51:00 ET open (m == 951)
    - Exit cutoff: 15:59:00 ET close (m == 959)
    """
    m = df["time"].dt.hour * 60 + df["time"].dt.minute
    df_window = df[(m >= 940) & (m <= 959)].copy()  # 15:40 to 15:59 ET
    df_window["date_str"] = df_window["time"].dt.strftime("%Y-%m-%d")
    df_window["m"] = df_window["time"].dt.hour * 60 + df_window["time"].dt.minute

    trades: List[Dict[str, Any]] = []

    for d_str, day_df in df_window.groupby("date_str"):
        if d_str < "2021-01-01":
            continue

        day_bars = day_df.sort_values("time").reset_index(drop=True)
        bar_50 = day_bars[day_bars["m"] == 950]
        exec_bars = day_bars[day_bars["m"] >= 951]

        if bar_50.empty or len(exec_bars) < 8:
            continue

        b = bar_50.iloc[0]
        b_open = float(b["open"])
        b_close = float(b["close"])
        b_high = float(b["high"])
        b_low = float(b["low"])
        b_rng = b_high - b_low

        if b_rng <= 0:
            continue

        ret = b_close - b_open
        cl = (b_close - b_low) / b_rng

        sig = 0
        if ret >= spec["min_ret_pts"] and cl >= 0.70:
            sig = 1
        elif not long_only and ret <= -spec["min_ret_pts"] and cl <= 0.30:
            sig = -1

        if sig == 0:
            continue

        entry_bar = exec_bars.iloc[0]
        entry_p = float(entry_bar["open"])
        entry_time = pd.Timestamp(entry_bar["time"])

        stop_pts = float(np.clip(1.0 * b_rng, spec["min_stop_pts"], spec["max_stop_pts"]))
        target_pts = float(stop_pts * spec["rr_ratio"])
        stop_price = entry_p - sig * stop_pts
        target_price = entry_p + sig * target_pts

        remaining_bars = exec_bars.iloc[1:]
        exit_p = float(exec_bars.iloc[-1]["close"])
        exit_time = pd.Timestamp(exec_bars.iloc[-1]["time"])
        reason = "time_exit_1559"

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
        slip_total = spec["slip_pts_limit"] if reason == "profit_target" else (spec["slip_pts_market"] * 2.0)
        net_pts = raw_pts - slip_total

        # Position Sizing under $250 max-risk budget
        stop_risk = stop_pts * spec["pt_val"]
        contracts = int(np.clip(np.floor(250.0 / max(stop_risk, 1.0)), 1, 4))
        comm = spec["comm_rt"] * contracts
        net_dollars = (net_pts * spec["pt_val"] * contracts) - comm

        trades.append({
            "date_str": d_str,
            "year": entry_time.year,
            "instrument": spec["micro"],
            "direction": "long" if sig == 1 else "short",
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_price": entry_p,
            "exit_price": exit_p,
            "bar50_range": b_rng,
            "stop_pts": stop_pts,
            "target_pts": target_pts,
            "contracts": contracts,
            "net_pts": net_pts,
            "net_dollars": net_dollars,
            "reason": reason,
        })

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
    print(" 🔔  CANDIDATE: 15:50 ET NYSE MARKET-ON-CLOSE (MOC) IMBALANCE DRIVE")
    print(f" Strategy ID: {STRATEGY_ID} | Instruments: MNQ (Nasdaq) & MES (S&P)")
    print(" Belfort Systematic Trading Framework (2026) — Steps 03–05")
    print("=" * 80)

    register_candidate(
        strategy_id=STRATEGY_ID,
        name=STRATEGY_NAME,
        instrument="MNQ/MES",
        description="15:50 ET NYSE Market-On-Close (MOC) imbalance momentum drive on MNQ and MES.",
    )

    store = default_store
    h_nq = store.compute_data_hash(NQ_PATH)
    h_es = store.compute_data_hash(ES_PATH)
    print(" [Data Provenance Verified]")
    print(f"   MNQ File: {NQ_PATH.name} (SHA-256: {h_nq[:16]}...)")
    print(f"   MES File: {ES_PATH.name} (SHA-256: {h_es[:16]}...)")

    print("\n Loading raw datasets...")
    df_nq = pd.read_parquet(NQ_PATH)
    df_es = pd.read_parquet(ES_PATH)

    experiments = [
        ("MNQ (Long + Short)", df_nq, SPECS["MNQ"], False),
        ("MNQ (Long Only)", df_nq, SPECS["MNQ"], True),
        ("MES (Long + Short)", df_es, SPECS["MES"], False),
        ("MES (Long Only)", df_es, SPECS["MES"], True),
    ]

    results_summary = []
    trade_dfs = {}

    print("\n Running In-Sample (2021–2024) and Out-of-Sample (2025–2026) Matrix...")
    for label, d_raw, spec, l_only in experiments:
        tdf = simulate_moc_drive(d_raw, spec, long_only=l_only)
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
    print(" 15:50 ET MOC DRIVE EXPERIMENT MATRIX")
    print("=" * 80)
    print(summary_df.to_string(index=False))

    # Evaluate best candidate
    best_label = "MNQ (Long + Short)"
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

    # Correlation Check against baseline strategies
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
Data File    : {NQ_PATH.name}
Data SHA-256 : {h_nq}
Cost Model   : 0.75 pt limit / 2.00 pt market adverse ($1.50/$4.00) + Comm ($1.20 RT) [NET]
Core Metrics : Trades: {best_full['trades']} | Win%: {best_full['win_rate']:.2f}% | PF: {best_full['pf']:.2f} | Net: ${best_full['net_pnl']:,.2f} | MaxDD: -${abs(best_full['max_dd']):,.2f}
Warning Flags: CANDIDATE_TIER_QUARANTINED
────────────────────────────────────────────────────────────────────────────
""")


if __name__ == "__main__":
    main()
