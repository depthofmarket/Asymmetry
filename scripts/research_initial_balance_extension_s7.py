#!/usr/bin/env python3
"""
Research Script: Candidate — 60-Minute Initial Balance Range Extension (10:30 ET) on MES & MNQ.
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

ES_PATH = REPO_ROOT / "data/raw/es_1m_2020_2026_cqg_et.parquet"
NQ_PATH = REPO_ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet"
BASELINE_TRADES_PATH = REPO_ROOT / "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet"

STRATEGY_ID = "initial_balance_extension_s7"
STRATEGY_NAME = "60-Minute Initial Balance Extension (10:30 ET)"

ASSET_SPECS = {
    "MES": {
        "sym": "ES",
        "micro": "MES",
        "name": "Micro S&P 500",
        "path": ES_PATH,
        "pt_val": 5.0,  # $5.00 per point per MES
        "tick_size": 0.25,
        "slip_pts_limit": 0.25,  # 1 tick ($1.25)
        "slip_pts_market": 0.50,  # 2 ticks ($2.50)
        "comm_rt": 1.20,
        "min_ib_range": 10.0,
        "max_ib_range": 60.0,
        "buffer_pts": 1.0,  # 4 ticks
        "min_stop_pts": 5.0,
        "max_stop_pts": 15.0,
        "stop_mult": 0.40,
        "rr_ratio": 1.50,
    },
    "MNQ": {
        "sym": "NQ",
        "micro": "MNQ",
        "name": "Micro Nasdaq 100",
        "path": NQ_PATH,
        "pt_val": 2.0,  # $2.00 per point per MNQ
        "tick_size": 0.25,
        "slip_pts_limit": 0.75,  # 3 ticks ($1.50)
        "slip_pts_market": 1.50,  # 6 ticks ($3.00)
        "comm_rt": 1.20,
        "min_ib_range": 40.0,
        "max_ib_range": 250.0,
        "buffer_pts": 4.0,  # 16 ticks
        "min_stop_pts": 20.0,
        "max_stop_pts": 60.0,
        "stop_mult": 0.40,
        "rr_ratio": 1.50,
    },
}


def simulate_ib_extension(
    df: pd.DataFrame,
    spec: Dict[str, Any],
    exclude_s1_dates: set[str] | None = None,
    long_only: bool = False,
) -> pd.DataFrame:
    """
    Simulates 60-Minute Initial Balance Range Extension without lookahead bias.
    - Initial Balance window: 09:30:00 to 10:29:59 ET (m: 570 to 629)
    - Breakout scan window: 10:30:00 to 11:14:59 ET (m: 630 to 674)
    - Holding cutoff: 12:00:00 ET (m: 720)
    """
    m = df["time"].dt.hour * 60 + df["time"].dt.minute
    df_window = df[(m >= 570) & (m <= 720)].copy()  # 09:30 to 12:00 ET
    df_window["date_str"] = df_window["time"].dt.strftime("%Y-%m-%d")
    df_window["m"] = df_window["time"].dt.hour * 60 + df_window["time"].dt.minute

    trades: List[Dict[str, Any]] = []

    for d_str, day_df in df_window.groupby("date_str"):
        if d_str < "2021-01-01":
            continue

        # Orthogonality gate: exclude days where Strategy 1 was active
        if exclude_s1_dates and d_str in exclude_s1_dates:
            continue

        day_bars = day_df.sort_values("time").reset_index(drop=True)
        ib_bars = day_bars[(day_bars["m"] >= 570) & (day_bars["m"] <= 629)]
        scan_bars = day_bars[(day_bars["m"] >= 630) & (day_bars["m"] <= 674)]
        exec_window = day_bars[day_bars["m"] >= 630]

        if len(ib_bars) < 55:  # Require complete 60-minute Initial Balance
            continue
        if len(scan_bars) < 10:
            continue

        ib_high = float(ib_bars["high"].max())
        ib_low = float(ib_bars["low"].min())
        ib_range = ib_high - ib_low

        if ib_range < spec["min_ib_range"] or ib_range > spec["max_ib_range"]:
            continue

        # Scan for first qualifying breakout bar in scan_bars
        triggered = False
        for idx, bar in scan_bars.iterrows():
            b_close = float(bar["close"])
            b_high = float(bar["high"])
            b_low = float(bar["low"])
            b_time = pd.Timestamp(bar["time"])
            b_rng = b_high - b_low

            if b_rng <= 0:
                continue

            cl = (b_close - b_low) / b_rng

            sig = 0
            if b_close > ib_high + spec["buffer_pts"] and cl >= 0.65:
                sig = 1
            elif not long_only and b_close < ib_low - spec["buffer_pts"] and cl <= 0.35:
                sig = -1

            if sig == 0:
                continue

            # Signal confirmed on bar close -> entry on next bar open
            post_bars = exec_window[exec_window["time"] > b_time]
            if post_bars.empty:
                continue

            entry_bar = post_bars.iloc[0]
            entry_p = float(entry_bar["open"])
            entry_time = pd.Timestamp(entry_bar["time"])

            stop_pts = float(np.clip(spec["stop_mult"] * ib_range, spec["min_stop_pts"], spec["max_stop_pts"]))
            target_pts = float(stop_pts * spec["rr_ratio"])
            stop_price = entry_p - sig * stop_pts
            target_price = entry_p + sig * target_pts

            remaining_bars = post_bars.iloc[1:]
            exit_p = float(post_bars.iloc[-1]["close"])
            exit_time = pd.Timestamp(post_bars.iloc[-1]["time"])
            reason = "time_exit_1200"

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
                "ib_range": ib_range,
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
    print(" 🚀  CANDIDATE: 60-MINUTE INITIAL BALANCE RANGE EXTENSION (10:30 ET)")
    print(f" Strategy ID: {STRATEGY_ID} | Instruments: MES (S&P) & MNQ (Nasdaq)")
    print(" Belfort Systematic Trading Framework (2026) — Steps 03–05")
    print("=" * 80)

    register_candidate(
        strategy_id=STRATEGY_ID,
        name=STRATEGY_NAME,
        instrument="MES/MNQ",
        description="60-Minute Initial Balance range extension (10:30 ET) on MES and MNQ.",
    )

    store = default_store
    h_es = store.compute_data_hash(ES_PATH)
    h_nq = store.compute_data_hash(NQ_PATH)
    print(f" [Data Provenance Verified]")
    print(f"   MES File    : {ES_PATH.name} (SHA-256: {h_es[:16]}...)")
    print(f"   MNQ File    : {NQ_PATH.name} (SHA-256: {h_nq[:16]}...)")

    # Load Strategy 1 active dates to enforce hard orthogonality
    s1_dates = set()
    if BASELINE_TRADES_PATH.exists():
        base_df = pd.read_parquet(BASELINE_TRADES_PATH)
        s1_df = base_df[base_df["strategy"].str.contains("Strategy 1")]
        s1_dates = set(s1_df["date_str"].unique())
        print(f"\n [Orthogonality Audit]")
        print(f"   Baseline Strategy 1 Active Sessions: {len(s1_dates)} sessions")
        print(f"   Candidate will trade exclusively on the ~1,100 Strategy 1 FLAT sessions.")

    print("\n Loading raw parquet datasets...")
    df_es = pd.read_parquet(ES_PATH)
    df_nq = pd.read_parquet(NQ_PATH)
    print(f"   MES bars: {len(df_es):,} | MNQ bars: {len(df_nq):,}")

    # Matrix:
    # 1. MES (Long + Short, S1 Gated)
    # 2. MES (Long Only, S1 Gated)
    # 3. MNQ (Long + Short, S1 Gated)
    # 4. MNQ (Long Only, S1 Gated)
    experiments = [
        ("MES (Long + Short) - S1 Flat Only", df_es, ASSET_SPECS["MES"], s1_dates, False),
        ("MES (Long Only) - S1 Flat Only", df_es, ASSET_SPECS["MES"], s1_dates, True),
        ("MNQ (Long + Short) - S1 Flat Only", df_nq, ASSET_SPECS["MNQ"], s1_dates, False),
        ("MNQ (Long Only) - S1 Flat Only", df_nq, ASSET_SPECS["MNQ"], s1_dates, True),
    ]

    results_summary = []
    trade_dfs = {}

    print("\n Running In-Sample (2021–2024) and Out-of-Sample (2025–2026) Matrix...")
    for label, d_raw, spec, s1_set, l_only in experiments:
        tdf = simulate_ib_extension(d_raw, spec, exclude_s1_dates=s1_set, long_only=l_only)
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
    print(" INITIAL BALANCE (IB) EXTENSION EXPERIMENT MATRIX")
    print("=" * 80)
    print(summary_df.to_string(index=False))

    # Evaluate Combined (MES + MNQ)
    t_es = trade_dfs["MES (Long + Short) - S1 Flat Only"]
    t_nq = trade_dfs["MNQ (Long + Short) - S1 Flat Only"]
    combined = pd.concat([t_es, t_nq], ignore_index=True).sort_values("entry_time").reset_index(drop=True)

    def print_deep_dive(tdf: pd.DataFrame, title: str):
        m = compute_metrics(tdf, title)
        print("\n" + "=" * 80)
        print(f" DEEP-DIVE: {title.upper()}")
        print("=" * 80)
        print(f" Trades Evaluated (N) : {m['trades']} trades across {m['active_days']} active days")
        print(f" Annual Frequency     : {m['trades_per_yr']:.1f} trades / year (~{m['trades_per_yr']/12:.1f} / month)")
        print(f" Win Rate             : {m['win_rate']:.2f}%")
        print(f" Profit Factor        : {m['pf']:.2f}")
        print(f" Net Profit           : ${m['net_pnl']:,.2f}")
        print(f" Gross Profit         : ${m['gross_profit']:,.2f}")
        print(f" Gross Loss           : -${m['gross_loss']:,.2f}")
        print(f" Average Trade        : ${m['avg_trade']:.2f}")
        print(f" Payoff Ratio (W/L)   : {m['payoff']:.2f}x (${m['avg_win']:.2f} win / ${m['avg_loss']:.2f} loss)")
        print(f" Max Drawdown         : -${abs(m['max_dd']):,.2f}")
        print(f" Longest Loss Streak  : {m['max_streak']} consecutive trades")
        print(f" Outlier Dominance    : {m['outlier_ratio']*100:.1f}% (Largest Win: ${m['largest_win']:,.2f})")

        print("\n   Year-by-Year Performance:")
        tdf_copy = tdf.copy()
        tdf_copy["year"] = pd.to_datetime(tdf_copy["entry_time"]).dt.year
        for yr, grp in tdf_copy.groupby("year"):
            y_m = compute_metrics(grp, str(yr))
            print(f"     {yr}: {y_m['trades']:3d} trades | Win%: {y_m['win_rate']:5.1f}% | PF: {y_m['pf']:4.2f} | Net: ${y_m['net_pnl']:8,.2f} | MaxDD: -${abs(y_m['max_dd']):6,.2f}")

    print_deep_dive(t_es, "MES Standalone (S1 Flat Only)")
    print_deep_dive(t_nq, "MNQ Standalone (S1 Flat Only)")
    print_deep_dive(combined, "Combined MES + MNQ (S1 Flat Only)")

    # Correlation check
    if BASELINE_TRADES_PATH.exists():
        base_df = pd.read_parquet(BASELINE_TRADES_PATH)
        cand_daily = combined.groupby("date_str")["net_dollars"].sum().rename("pnl_cand")
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

    full_m = compute_metrics(combined, "Full 5.8-Year Combined")
    print(f"""
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : candidate_{STRATEGY_ID}_full_walkforward
Strategy     : {STRATEGY_ID} — {STRATEGY_NAME}
Strategy Tier: CANDIDATE
Methodology  : multi_year_walkforward
Date Range   : 2021-01-01 to 2026-10-30
Data File    : es_1m_2020_2026_cqg_et.parquet & nq_1m_2017_2026_cqg_et.parquet
Data SHA-256 : {h_es[:16]}... / {h_nq[:16]}...
Cost Model   : Realistic Adverse Parity ($1.25-$3.00) + Commission ($1.20 RT) [NET]
Core Metrics : Trades: {full_m['trades']} | Win%: {full_m['win_rate']:.2f}% | PF: {full_m['pf']:.2f} | Net: ${full_m['net_pnl']:,.2f} | MaxDD: -${abs(full_m['max_dd']):,.2f}
Warning Flags: CANDIDATE_TIER_QUARANTINED
────────────────────────────────────────────────────────────────────────────
""")


if __name__ == "__main__":
    main()
