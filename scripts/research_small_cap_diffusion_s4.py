#!/usr/bin/env python3
"""
Candidate Strategy S4 (H30): Small-Cap Beta Diffusion Lag (10:00 ET on M2K).

Academic & Structural Foundations:
1. Hou, Kewei (2007 JFE): "Industry Information Diffusion and the Lead-Lag Effect in Stock Returns"
   - Information diffuses slowly from large-cap bellwethers to small-cap firms due to differential analyst
     coverage and institutional attention, creating a systematic lead-lag transmission window.
2. Lo, Andrew W. & MacKinlay, A. Craig (1990 RFS): "When are Contrarian Profits Due to Stock Market Overreaction?"
   - Cross-autocorrelations between large and small-capitalization portfolios generate predictable diffusion
     inertia where large-cap movements lead small-cap index adjustments.
3. Chordia, Roll, & Subrahmanyam (2008 JFE): "Liquidity and Market Efficiency"
   - Microstructural friction and inventory-holding constraints delay small-cap price discovery
     during opening market-wide order-flow surges.

Hypothesis H30 Mechanism:
When broad large-cap equity indexes (MES and MNQ) experience a large, concordance-aligned directional thrust
during the first 30 minutes of cash trading (09:30:00 to 09:59:59 ET), small caps (M2K / Russell 2000) often lag
due to informational and microstructural friction. If M2K has captured <= 60% of its historical rolling beta-expected
displacement, it acts as a "coiled spring" and diffuses toward the market expansion between 10:01 and 10:55 ET.

Belfort Systematic Trading Framework (2026) — Step 03 (Code It), Step 04 (In-Sample), Step 05 (Out-of-Sample).
Governance: Auto-records into results/backtest_provenance.db under StrategyTier.CANDIDATE.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.metrics import calculate_institutional_metrics
from backtest.provenance import ProvenanceStore, default_store
from config.strategy_registry import StrategyTier, register_strategy

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION & CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

STRATEGY_ID = "candidate_small_cap_diffusion_s4"
STRATEGY_NAME = "Small-Cap Beta Diffusion Lag (10:00 ET)"

RTY_PATH = REPO_ROOT / "data" / "raw" / "rty_1m_2020_2026_et.parquet"
ES_PATH = REPO_ROOT / "data" / "raw" / "es_1m_2020_2026_cqg_et.parquet"
NQ_PATH = REPO_ROOT / "data" / "raw" / "nq_1m_2017_2026_cqg_et.parquet"

# M2K Contract Specifications
M2K_POINT_VAL = 5.00        # $5.00 per index point ($0.50 per 0.10 tick)
M2K_TICK_SIZE = 0.10        # 0.10 index points
M2K_COMMISSION_RT = 1.20    # $1.20 round-trip per micro contract
M2K_SLIPPAGE_TICKS = 1      # 1 tick adverse entry + 1 tick adverse exit
M2K_SLIPPAGE_COST = 2 * M2K_TICK_SIZE * M2K_POINT_VAL  # $1.00 total slippage ($0.50 / side)
M2K_TOTAL_FRICTION = M2K_COMMISSION_RT + M2K_SLIPPAGE_COST  # $2.20 total round-turn friction

# Risk Brackets (in index points)
STOP_LOSS_POINTS = 8.00       # $40.00 risk per micro contract
PROFIT_TARGET_POINTS = 16.00  # $80.00 target per micro contract (1:2.0 R:R)

# Gate Thresholds
MES_MIN_RETURN_ABS = 0.0035   # |r_MES| >= 0.35%
NQ_MIN_RETURN_ABS = 0.0050    # |r_NQ| >= 0.50%
LAGGARD_MAX_CAPTURE = 0.60    # |r_M2K| <= 60% of beta-expected return
FALLBACK_BETA = 1.25          # Fallback beta when historical sample < 20 sessions
BETA_WINDOW = 20              # Rolling 20-day historical window

EVAL_START_DATE = "2021-01-04"
EVAL_END_DATE = "2026-10-30"
IS_SPLIT_DATE = "2025-01-01"


# ─────────────────────────────────────────────────────────────────────────────
# DATA INGESTION & POINT-IN-TIME ROLLING BETA
# ─────────────────────────────────────────────────────────────────────────────

def load_data():
    """Loads and preprocesses 1-minute data for RTY, ES, and NQ."""
    print("Loading raw parquet datasets...")
    df_rty = pd.read_parquet(RTY_PATH, columns=["time", "open", "high", "low", "close", "volume"])
    df_es = pd.read_parquet(ES_PATH, columns=["time", "open", "high", "low", "close", "volume"])
    df_nq = pd.read_parquet(NQ_PATH, columns=["time", "open", "high", "low", "close", "volume"])

    for df in (df_rty, df_es, df_nq):
        df["time"] = pd.to_datetime(df["time"])
        df["m"] = df["time"].dt.hour * 60 + df["time"].dt.minute
        df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")

    return df_rty, df_es, df_nq


def compute_daily_returns(df: pd.DataFrame) -> pd.Series:
    """Computes daily close-to-close percentage returns from session closes (m <= 960 / 16:00 ET)."""
    rth_bars = df[df["m"] <= 960]
    daily_closes = rth_bars.groupby("date_str")["close"].last()
    daily_ret = daily_closes.pct_change().dropna()
    return daily_ret


def compute_point_in_time_rolling_betas(r_rty: pd.Series, r_es: pd.Series) -> Dict[str, float]:
    """
    Computes rolling 20-day historical beta strictly using completed sessions prior to session d.
    Zero-lookahead guarantee: date d is NEVER included in its own estimation window.
    """
    common_dates = sorted(list(set(r_rty.index).intersection(set(r_es.index))))
    rolling_betas: Dict[str, float] = {}

    for i, d in enumerate(common_dates):
        if i < BETA_WINDOW:
            rolling_betas[d] = FALLBACK_BETA
        else:
            # Strictly completed prior 20 sessions: [i - 20 : i]
            prior_dates = common_dates[i - BETA_WINDOW : i]
            r_rty_win = r_rty.loc[prior_dates].to_numpy()
            r_es_win = r_es.loc[prior_dates].to_numpy()

            var_es = float(np.var(r_es_win, ddof=1))
            if var_es > 1e-10:
                cov_mat = np.cov(r_rty_win, r_es_win)
                beta = float(cov_mat[0, 1] / var_es)
                rolling_betas[d] = beta
            else:
                rolling_betas[d] = FALLBACK_BETA

    return rolling_betas


# ─────────────────────────────────────────────────────────────────────────────
# BACKTEST SIMULATION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def run_backtest():
    register_strategy(
        strategy_id=STRATEGY_ID,
        tier=StrategyTier.CANDIDATE,
        name=STRATEGY_NAME,
        instrument="M2K",
        timeframe="1m",
        schedule="10:01–10:55 ET",
        description="Micro Russell 2000 beta diffusion lag following 09:30–10:00 ET broad market (ES/NQ) aligned thrust.",
    )

    store = default_store
    h_rty = store.compute_data_hash(RTY_PATH)
    h_es = store.compute_data_hash(ES_PATH)
    h_nq = store.compute_data_hash(NQ_PATH)

    print(f"Data SHA-256 (RTY / M2K): {h_rty}")
    print(f"Data SHA-256 (ES  / MES): {h_es}")
    print(f"Data SHA-256 (NQ  / MNQ): {h_nq}")

    df_rty, df_es, df_nq = load_data()

    print("Computing daily returns and point-in-time rolling 20-day betas...")
    r_rty_daily = compute_daily_returns(df_rty)
    r_es_daily = compute_daily_returns(df_es)
    rolling_betas = compute_point_in_time_rolling_betas(r_rty_daily, r_es_daily)

    # Filter to intraday evaluation window (09:30 to 11:00 ET, m in [570, 660])
    rty_sub = df_rty[(df_rty["m"] >= 570) & (df_rty["m"] <= 660)].sort_values("time").reset_index(drop=True)
    es_sub = df_es[(df_es["m"] >= 570) & (df_es["m"] <= 660)].sort_values("time").reset_index(drop=True)
    nq_sub = df_nq[(df_nq["m"] >= 570) & (df_nq["m"] <= 660)].sort_values("time").reset_index(drop=True)

    rty_dict = {d: group for d, group in rty_sub.groupby("date_str")}
    es_dict = {d: group for d, group in es_sub.groupby("date_str")}
    nq_dict = {d: group for d, group in nq_sub.groupby("date_str")}

    all_dates = sorted(list(set(rty_dict.keys()) & set(es_dict.keys()) & set(nq_dict.keys())))
    eval_dates = [d for d in all_dates if EVAL_START_DATE <= d <= EVAL_END_DATE]

    print(f"Simulating across {len(eval_dates)} sessions ({EVAL_START_DATE} to {EVAL_END_DATE})...\n")

    trades: List[Dict[str, Any]] = []

    for d in eval_dates:
        rty_day = rty_dict.get(d)
        es_day = es_dict.get(d)
        nq_day = nq_dict.get(d)

        if rty_day is None or es_day is None or nq_day is None:
            continue

        # Extract 09:30:00 to 09:59:59 ET bars (m in [570, 599])
        es_morn = es_day[(es_day["m"] >= 570) & (es_day["m"] <= 599)]
        nq_morn = nq_day[(nq_day["m"] >= 570) & (nq_day["m"] <= 599)]
        rty_morn = rty_day[(rty_day["m"] >= 570) & (rty_day["m"] <= 599)]

        if len(es_morn) < 28 or len(nq_morn) < 28 or len(rty_morn) < 28:
            continue

        # Returns from 09:30 open to 09:59 close
        o_mes = float(es_morn.iloc[0]["open"])
        c_mes = float(es_morn.iloc[-1]["close"])
        r_mes = (c_mes - o_mes) / o_mes

        o_nq = float(nq_morn.iloc[0]["open"])
        c_nq = float(nq_morn.iloc[-1]["close"])
        r_nq = (c_nq - o_nq) / o_nq

        o_rty = float(rty_morn.iloc[0]["open"])
        c_rty = float(rty_morn.iloc[-1]["close"])
        r_m2k = (c_rty - o_rty) / o_rty

        # 1. Broad Market Alignment Gate
        # Concordance: same sign and non-zero
        if not ((r_mes > 0 and r_nq > 0) or (r_mes < 0 and r_nq < 0)):
            continue

        # Magnitude Floor
        if abs(r_mes) < MES_MIN_RETURN_ABS or abs(r_nq) < NQ_MIN_RETURN_ABS:
            continue

        # 2. Small-Cap Laggard Diffusion Gate (The Coiled Spring)
        beta = rolling_betas.get(d, FALLBACK_BETA)
        r_expected = beta * r_mes

        if abs(r_m2k) > LAGGARD_MAX_CAPTURE * abs(r_expected):
            continue

        # 3. Execution & Risk Brackets
        direction = 1 if r_mes > 0 else -1

        # Entry at 10:01:00 ET open on M2K
        rty_trade = rty_day[(rty_day["m"] >= 601) & (rty_day["m"] <= 655)]
        if rty_trade.empty or rty_trade.iloc[0]["m"] != 601:
            continue

        entry_p = float(rty_trade.iloc[0]["open"])
        entry_time = rty_trade.iloc[0]["time"]

        if direction == 1:
            stop_p = entry_p - STOP_LOSS_POINTS
            target_p = entry_p + PROFIT_TARGET_POINTS
        else:
            stop_p = entry_p + STOP_LOSS_POINTS
            target_p = entry_p - PROFIT_TARGET_POINTS

        exit_p = float(rty_trade.iloc[-1]["close"])
        exit_reason = "time_exit_1055"
        exit_time = rty_trade.iloc[-1]["time"]

        for row in rty_trade.itertuples():
            bh = float(row.high)
            bl = float(row.low)
            bo = float(row.open)
            bt = row.time

            if direction == 1:
                stop_hit = bl <= stop_p
                target_hit = bh >= target_p

                if stop_hit and target_hit:
                    exit_p = stop_p
                    exit_reason = "stop_loss"
                    exit_time = bt
                    break
                elif stop_hit:
                    exit_p = min(bo, stop_p) if bo < stop_p else stop_p
                    exit_reason = "stop_loss"
                    exit_time = bt
                    break
                elif target_hit:
                    exit_p = target_p
                    exit_reason = "profit_target"
                    exit_time = bt
                    break
            else:
                stop_hit = bh >= stop_p
                target_hit = bl <= target_p

                if stop_hit and target_hit:
                    exit_p = stop_p
                    exit_reason = "stop_loss"
                    exit_time = bt
                    break
                elif stop_hit:
                    exit_p = max(bo, stop_p) if bo > stop_p else stop_p
                    exit_reason = "stop_loss"
                    exit_time = bt
                    break
                elif target_hit:
                    exit_p = target_p
                    exit_reason = "profit_target"
                    exit_time = bt
                    break

        gross_pts = (exit_p - entry_p) * direction
        gross_pnl = gross_pts * M2K_POINT_VAL
        net_pnl = gross_pnl - M2K_TOTAL_FRICTION

        trades.append({
            "date": d,
            "year": d[:4],
            "entry_time": entry_time,
            "exit_time": exit_time,
            "direction": "LONG" if direction == 1 else "SHORT",
            "dir_num": direction,
            "entry_p": entry_p,
            "exit_p": exit_p,
            "gross_pts": gross_pts,
            "gross_pnl": gross_pnl,
            "net_pnl": net_pnl,
            "win": net_pnl > 0,
            "exit_reason": exit_reason,
            "beta": beta,
            "r_mes": r_mes,
            "r_nq": r_nq,
            "r_m2k": r_m2k,
            "r_expected": r_expected,
            "is_oos": "IS" if d < IS_SPLIT_DATE else "OOS",
        })

    tdf = pd.DataFrame(trades)
    return tdf, h_rty, h_es, h_nq


# ─────────────────────────────────────────────────────────────────────────────
# METRICS & REPORTING
# ─────────────────────────────────────────────────────────────────────────────

def compute_summary_metrics(tdf: pd.DataFrame, label: str = "") -> Dict[str, Any]:
    if tdf.empty:
        return {
            "label": label,
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "net_profit": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "largest_win": 0.0,
            "largest_win_pct_of_net": 0.0,
        }

    trades_n = len(tdf)
    wins = tdf[tdf["net_pnl"] > 0]["net_pnl"]
    losses = tdf[tdf["net_pnl"] < 0]["net_pnl"]
    gross_win = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    wr = float((tdf["net_pnl"] > 0).mean() * 100.0)
    net_pnl = float(tdf["net_pnl"].sum())

    cum = tdf["net_pnl"].cumsum()
    peak = cum.cummax()
    dd = peak - cum
    max_dd = float(dd.max()) if not dd.empty else 0.0

    daily_pnl = tdf.groupby("date")["net_pnl"].sum()
    if len(daily_pnl) > 1 and daily_pnl.std() > 1e-12:
        sharpe = float(daily_pnl.mean() / daily_pnl.std() * np.sqrt(252.0))
    else:
        sharpe = 0.0

    largest_win = float(tdf["net_pnl"].max()) if not tdf.empty else 0.0
    largest_win_pct = (largest_win / net_pnl * 100.0) if (net_pnl > 0 and largest_win > 0) else 0.0

    return {
        "label": label,
        "trades": trades_n,
        "win_rate": wr,
        "profit_factor": pf,
        "gross_profit": gross_win,
        "gross_loss": gross_loss,
        "net_profit": net_pnl,
        "max_drawdown": max_dd,
        "sharpe_ratio": sharpe,
        "largest_win": largest_win,
        "largest_win_pct_of_net": largest_win_pct,
    }


def main():
    print("=" * 80)
    print(" CANDIDATE RESEARCH: SMALL-CAP BETA DIFFUSION LAG (H30 / M2K)")
    print("=" * 80)

    tdf, h_rty, h_es, h_nq = run_backtest()

    m_walk = compute_summary_metrics(tdf, "Full Walkforward (2021-2026)")
    m_is = compute_summary_metrics(tdf[tdf["is_oos"] == "IS"], "In-Sample (2021-2024)")
    m_oos = compute_summary_metrics(tdf[tdf["is_oos"] == "OOS"], "Out-of-Sample (2025-2026)")

    print("\n" + "=" * 80)
    print(" PERFORMANCE SCORECARD (Belfort Steps 04 & 05)")
    print("=" * 80)
    print(f"{'Partition':<28} | {'Trades':<7} | {'Win%':<7} | {'PF':<6} | {'Net PnL':<12} | {'MaxDD':<10} | {'Sharpe':<6}")
    print("-" * 86)
    for m in (m_walk, m_is, m_oos):
        print(f"{m['label']:<28} | {m['trades']:<7} | {m['win_rate']:>6.1f}% | {m['profit_factor']:>6.2f} | ${m['net_profit']:>10,.2f} | -${m['max_drawdown']:>8,.2f} | {m['sharpe_ratio']:>6.2f}")

    print("\n" + "-" * 80)
    print(" YEARLY BREAKDOWN:")
    print("-" * 80)
    for yr in sorted(tdf["year"].unique()):
        sub_yr = tdf[tdf["year"] == yr]
        myr = compute_summary_metrics(sub_yr, yr)
        print(f"  {yr}: {myr['trades']:>3} tr | WR: {myr['win_rate']:>5.1f}% | PF: {myr['profit_factor']:>5.2f} | Net: ${myr['net_profit']:>9,.2f} | MaxDD: -${myr['max_drawdown']:>7,.2f}")

    print("\n" + "-" * 80)
    print(" DIRECTIONAL & EXIT BREAKDOWN:")
    print("-" * 80)
    for d in ("LONG", "SHORT"):
        sub_d = tdf[tdf["direction"] == d]
        md = compute_summary_metrics(sub_d, d)
        print(f"  Direction {d:<5}: {md['trades']:>3} tr | WR: {md['win_rate']:>5.1f}% | PF: {md['profit_factor']:>5.2f} | Net: ${md['net_profit']:>9,.2f}")

    print("\n  Exit Reasons:")
    for reason, cnt in tdf["exit_reason"].value_counts().items():
        sub_r = tdf[tdf["exit_reason"] == reason]
        pnl_r = sub_r["net_pnl"].sum()
        print(f"    - {reason:<16}: {cnt:>3} trades ({cnt / len(tdf) * 100:.1f}%) | Net PnL: ${pnl_r:>9,.2f}")

    # ACID Provenance Store Recording
    store = default_store
    run_id = f"{STRATEGY_ID}_2021_2026"

    daily_returns_series = tdf.groupby("date")["net_pnl"].sum()
    inst_metrics = calculate_institutional_metrics(
        tdf["net_pnl"].to_numpy(),
        daily_returns=daily_returns_series,
        capital=25000.0,
    )

    warnings = ["CANDIDATE_TIER_QUARANTINED"]
    if m_walk["profit_factor"] < 1.0 or m_walk["net_profit"] < 0:
        warnings.append("FALSIFIED_HYPOTHESIS")
    if m_walk["trades"] < 30:
        warnings.append("LOW_SAMPLE_SIZE")
    if m_walk["largest_win_pct_of_net"] > 35.0:
        warnings.append("OUTLIER_DOMINANCE")

    record = store.record_run(
        run_id=run_id,
        strategy_id=STRATEGY_ID,
        strategy_name=STRATEGY_NAME,
        strategy_tier=StrategyTier.CANDIDATE.value,
        methodology="multi_year_walkforward",
        date_start=EVAL_START_DATE,
        date_end=EVAL_END_DATE,
        data_path=str(RTY_PATH),
        total_trades=m_walk["trades"],
        win_rate=m_walk["win_rate"],
        profit_factor=m_walk["profit_factor"],
        gross_profit=m_walk["gross_profit"],
        net_profit=m_walk["net_profit"],
        max_drawdown=m_walk["max_drawdown"],
        sharpe_ratio=m_walk["sharpe_ratio"],
        largest_win=m_walk["largest_win"],
        slippage_model="1 tick adverse parity ($1 per RT)",
        commission_model="$1.20 round-trip micro",
        is_net=True,
        explicit_warnings=warnings,
        extended_metrics=inst_metrics,
        params={
            "rty_hash": h_rty,
            "es_hash": h_es,
            "nq_hash": h_nq,
            "rolling_beta_window": BETA_WINDOW,
            "beta_fallback": FALLBACK_BETA,
            "mes_min_abs_return": MES_MIN_RETURN_ABS,
            "nq_min_abs_return": NQ_MIN_RETURN_ABS,
            "laggard_max_capture": LAGGARD_MAX_CAPTURE,
            "stop_loss_points": STOP_LOSS_POINTS,
            "profit_target_points": PROFIT_TARGET_POINTS,
            "point_value": M2K_POINT_VAL,
            "commission_rt": M2K_COMMISSION_RT,
            "slippage_rt": M2K_SLIPPAGE_COST,
            "total_friction": M2K_TOTAL_FRICTION,
        },
        notes="H30 Small-Cap Beta Diffusion Lag on M2K conditioned on 09:30-10:00 ET ES/NQ concordance and rolling 20-day beta lag.",
    )

    # Standardized Provenance Verification Footer (Rule 2 & 3)
    print("\n" + "─" * 76)
    print("PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)")
    print("─" * 76)
    print(f"Run ID       : {record.run_id}")
    print(f"Strategy     : {record.strategy_id} — {record.strategy_name} [{record.strategy_tier}]")
    print(f"Methodology  : {record.methodology}")
    print(f"Date Range   : {record.date_start} to {record.date_end} ({record.days_count} days)")
    print(f"Data File    : {record.data_path}")
    print(f"Data SHA-256 : {record.data_hash}")
    print(f"Git Commit   : {record.git_commit}")
    print(f"Cost Model   : {record.slippage_model} | {record.commission_model} [NET]")
    print(f"Metrics      : Trades: {record.total_trades} | Win%: {record.win_rate:.1f}% | PF: {record.profit_factor:.2f} | Net: ${record.net_profit:,.2f} | MaxDD: -${record.max_drawdown:,.2f} | Sharpe: {record.sharpe_ratio:.2f}")
    warn_str = ", ".join(record.warnings) if record.warnings else "None"
    print(f"Warning Flags: {warn_str}")
    print("─" * 76)


if __name__ == "__main__":
    main()
