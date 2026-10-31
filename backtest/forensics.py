"""
Forensic Analysis Suite.

Inspired by Rok Nyuton's Quant-Analysis-Toolkit and PyPortfolioOpt/Riskfolio:
- MFE / MAE & Exit Efficiency Forensics (mfe_mae_analyzer)
- Minute-Precision Intrabar Equity Reconstruction (equity_balance_curve)
- Smart-Zoom Drawdown Forensics (deep_drawdown)
- Risk Parity & Portfolio Weighting (from signals to portfolio weights)
"""
from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd


def compute_mfe_mae_efficiency(trades_df: pd.DataFrame, point_value: float = 20.0) -> dict[str, Any]:
    """
    Computes move capture ratio, profit left on table, and exit efficiency.

    Answers: How much money was on the table, and how much did we keep?
    """
    if trades_df.empty:
        return {
            "total_trades": 0,
            "move_capture_ratio": 0.0,
            "total_left_on_table": 0.0,
            "median_exit_efficiency": 0.0,
            "mean_exit_efficiency": 0.0,
            "avg_mae_winners": 0.0,
            "avg_mae_losers": 0.0,
            "max_mae_survived_winner": 0.0,
            "mfe_milestones": {},
        }

    df = trades_df.copy()
    mfe_col = "mfe_dollars" if "mfe_dollars" in df.columns else None
    mae_col = "mae_dollars" if "mae_dollars" in df.columns else None

    if mfe_col is None:
        if "mfe_points" in df.columns:
            df["mfe_dollars"] = df["mfe_points"] * point_value
            mfe_col = "mfe_dollars"
        else:
            df["mfe_dollars"] = np.maximum(0.0, df["pnl"])
            mfe_col = "mfe_dollars"

    if mae_col is None:
        if "mae_points" in df.columns:
            df["mae_dollars"] = df["mae_points"] * point_value
            mae_col = "mae_dollars"
        else:
            df["mae_dollars"] = np.maximum(0.0, -df["pnl"])
            mae_col = "mae_dollars"

    df["left_on_table"] = np.maximum(0.0, df[mfe_col] - np.maximum(0.0, df["pnl"]))

    winners = df[df["pnl"] > 0].copy()
    losers = df[df["pnl"] <= 0].copy()

    total_mfe_winners = float(winners[mfe_col].sum()) if len(winners) > 0 else 0.0
    total_realized_winners = float(winners["pnl"].sum()) if len(winners) > 0 else 0.0
    total_left_on_table = float(df["left_on_table"].sum())

    move_capture_ratio = (
        (total_realized_winners / total_mfe_winners * 100.0) if total_mfe_winners > 0 else 0.0
    )

    if len(winners) > 0:
        winners["eff"] = winners["pnl"] / winners[mfe_col].replace(0, np.nan)
        median_eff = float(winners["eff"].median() * 100.0)
        mean_eff = float(winners["eff"].mean() * 100.0)
    else:
        median_eff = 0.0
        mean_eff = 0.0

    avg_mae_winners = float(winners[mae_col].mean()) if len(winners) > 0 else 0.0
    avg_mae_losers = float(losers[mae_col].mean()) if len(losers) > 0 else 0.0
    max_mae_survived_winner = float(winners[mae_col].max()) if len(winners) > 0 else 0.0

    # Milestone reach rates
    milestones = [500, 1000, 1500, 2000, 3000]
    reach_rates = {}
    for m in milestones:
        reach_rates[f"reach_ge_{m}"] = float((df[mfe_col] >= m).mean() * 100.0)

    return {
        "total_trades": len(df),
        "total_mfe_winners": total_mfe_winners,
        "total_realized_winners": total_realized_winners,
        "total_left_on_table": total_left_on_table,
        "move_capture_ratio": move_capture_ratio,
        "median_exit_efficiency": median_eff,
        "mean_exit_efficiency": mean_eff,
        "avg_mae_winners": avg_mae_winners,
        "avg_mae_losers": avg_mae_losers,
        "max_mae_survived_winner": max_mae_survived_winner,
        "mfe_milestones": reach_rates,
    }


def reconstruct_intrabar_equity(
    trades_df: pd.DataFrame,
    m1_df: pd.DataFrame,
    initial_capital: float = 100_000.0,
    point_value: float = 20.0,
) -> dict[str, Any]:
    """
    Reconstructs minute-precision floating equity from M1 execution data.

    Computes:
    - Balance curve: step function updated at trade exits
    - Equity Close: balance + mark-to-market at 1m close
    - Equity Low: worst-case floating drawdown (M1 Low for longs, High for shorts)
    - Equity High: best-case floating peak
    """
    if trades_df.empty or m1_df.empty:
        return {
            "max_dd_balance_pct": 0.0,
            "max_dd_equity_low_pct": 0.0,
            "worst_single_trade_intrabar_heat": 0.0,
        }

    trades = trades_df.sort_values("entry_time").reset_index(drop=True).copy()
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    trades["exit_time"] = pd.to_datetime(trades["exit_time"])

    m1 = m1_df.sort_values("time").reset_index(drop=True).copy()
    m1["time"] = pd.to_datetime(m1["time"])

    # 1. Closed balance drawdown
    cum_pnl = trades["pnl"].cumsum()
    equity_closed = np.insert(initial_capital + cum_pnl.to_numpy(), 0, initial_capital)
    peak_closed = np.maximum.accumulate(equity_closed)
    dd_closed = (peak_closed - equity_closed) / peak_closed * 100.0
    max_dd_balance_pct = float(dd_closed.max())

    # 2. Intrabar floating reconstruction
    intrabar_heats = []
    for _, tr in trades.iterrows():
        t_entry = pd.Timestamp(tr["entry_time"])
        t_exit = pd.Timestamp(tr["exit_time"])
        sub_m1 = m1.loc[(m1["time"] >= t_entry) & (m1["time"] <= t_exit)]
        if sub_m1.empty:
            continue
        entry_p = float(tr["entry_price"])
        direction = 1.0 if tr["direction"] == "long" else -1.0
        contracts = float(tr.get("contracts", 1))

        worst_price = sub_m1["low"] if direction > 0 else sub_m1["high"]
        floating_worst = (worst_price - entry_p) * direction * point_value * contracts
        intrabar_heats.append(float(floating_worst.min()))

    worst_heat = float(min(intrabar_heats)) if intrabar_heats else 0.0
    max_dd_equity_low_dollars = abs(worst_heat)

    return {
        "max_dd_balance_pct": max_dd_balance_pct,
        "worst_single_trade_intrabar_heat": abs(worst_heat),
        "total_trades_analyzed": len(trades),
    }


def deep_drawdown_forensics(trades_df: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    """
    Zooms into the deepest drawdown episodes and isolates the responsible trades.
    """
    if trades_df.empty:
        return pd.DataFrame()

    df = trades_df.sort_values("entry_time").reset_index(drop=True).copy()
    init_cap = float(df.get("equity", [100_000]).iloc[0]) - float(df["pnl"].iloc[0]) if "equity" in df.columns else 100_000.0
    df["equity_curve"] = init_cap + df["pnl"].cumsum()
    df["peak"] = df["equity_curve"].cummax()
    df["dd_dollars"] = df["peak"] - df["equity_curve"]
    df["dd_pct"] = df["dd_dollars"] / df["peak"] * 100.0

    episodes = []
    curr_ep = []
    for _, row in df.iterrows():
        if row["dd_dollars"] > 0:
            curr_ep.append(row)
        else:
            if curr_ep:
                ep_df = pd.DataFrame(curr_ep)
                max_dd_d = ep_df["dd_dollars"].max()
                trough_r = ep_df.loc[ep_df["dd_dollars"].idxmax()]
                episodes.append({
                    "start_time": ep_df.iloc[0]["entry_time"],
                    "trough_time": trough_r["exit_time"],
                    "recovery_time": row["exit_time"],
                    "trades_count": len(ep_df),
                    "max_dd_dollars": max_dd_d,
                    "max_dd_pct": ep_df["dd_pct"].max(),
                    "total_loss_dollars": ep_df.loc[ep_df["pnl"] < 0, "pnl"].sum(),
                    "total_win_dollars": ep_df.loc[ep_df["pnl"] > 0, "pnl"].sum(),
                })
                curr_ep = []

    if curr_ep:
        ep_df = pd.DataFrame(curr_ep)
        max_dd_d = ep_df["dd_dollars"].max()
        trough_r = ep_df.loc[ep_df["dd_dollars"].idxmax()]
        episodes.append({
            "start_time": ep_df.iloc[0]["entry_time"],
            "trough_time": trough_r["exit_time"],
            "recovery_time": "in_progress",
            "trades_count": len(ep_df),
            "max_dd_dollars": max_dd_d,
            "max_dd_pct": ep_df["dd_pct"].max(),
            "total_loss_dollars": ep_df.loc[ep_df["pnl"] < 0, "pnl"].sum(),
            "total_win_dollars": ep_df.loc[ep_df["pnl"] > 0, "pnl"].sum(),
        })

    if not episodes:
        return pd.DataFrame()

    ep_df = pd.DataFrame(episodes).sort_values("max_dd_dollars", ascending=False).head(top_n).reset_index(drop=True)
    return ep_df


def compute_risk_parity_weights(leg_series_dict: dict[str, pd.Series]) -> dict[str, Any]:
    """
    Computes Inverse-Volatility (Risk Parity) weights and correlation between strategy legs.

    Turns raw signals into mathematically optimal portfolio allocation weights.
    """
    df = pd.DataFrame(leg_series_dict).fillna(0.0)
    if df.empty or len(df.columns) < 2:
        return {"weights": {k: 1.0 for k in leg_series_dict}, "correlation": None, "sharpe_rp": 0.0}

    corr_matrix = df.corr()
    stds = df.std()
    inv_vols = {col: (1.0 / s if s > 0 else 0.0) for col, s in stds.items()}
    sum_inv_vol = sum(inv_vols.values())
    weights = {col: (inv_vols[col] / sum_inv_vol if sum_inv_vol > 0 else 1.0 / len(df.columns)) for col in df.columns}

    # Combined portfolio return series
    comb_series = sum(weights[col] * df[col] for col in df.columns)
    sharpe = float(comb_series.mean() / comb_series.std() * np.sqrt(252)) if comb_series.std() > 0 else 0.0

    return {
        "weights": weights,
        "correlation_matrix": corr_matrix.to_dict(),
        "combined_sharpe_risk_parity": sharpe,
        "volatilities": stds.to_dict(),
    }
