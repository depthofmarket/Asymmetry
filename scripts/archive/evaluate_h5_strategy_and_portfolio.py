#!/usr/bin/env python3
"""
Full Stop/Target-Managed Strategy Backtest for Candidate H5 (Value Area Responsive Rotation, 10:00-11:30 ET)
and Combined Orthogonal Portfolio Evaluation with Strategy 1 (Morning Value Area Breakout v2.0, 09:45 ET).
"""

from __future__ import annotations

from pathlib import Path
import sys
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.value_area_responsive_rotation_signal import (
    ValueAreaResponsiveRotationConfig,
    build_value_area_responsive_rotation_signal_frame,
)
from backtest.signal_export import load_ohlcv_data
from config.backtest_config import BACKTEST_CONFIG


def simulate_h5_barrier_trades(
    signal_frame: pd.DataFrame,
    *,
    horizon_bars: int = 30,
    entry_lag_bars: int = 1,
    round_trip_cost_points: float = 1.50,
    stress_cost_points: float = 2.00,
    risk_budget_dollars: float = 250.0,
    max_micros: int = 4,
) -> pd.DataFrame:
    df = signal_frame.reset_index(drop=True)
    active_indices = np.flatnonzero(df["candidate_signal"].to_numpy(dtype=float) != 0.0)
    n_rows = len(df)

    times = pd.to_datetime(df["time"])
    open_arr = df["open"].to_numpy(dtype=float)
    high_arr = df["high"].to_numpy(dtype=float)
    low_arr = df["low"].to_numpy(dtype=float)
    close_arr = df["close"].to_numpy(dtype=float)
    sig_arr = df["candidate_signal"].to_numpy(dtype=float)
    stop_arr = df["stop_points"].to_numpy(dtype=float)
    target_arr = df["target_points"].to_numpy(dtype=float)
    level_arr = df["level_tested"].to_numpy(dtype=object)
    poc_arr = df["prior_rth_poc"].to_numpy(dtype=float)
    vah_arr = df["prior_rth_vah"].to_numpy(dtype=float)
    val_arr = df["prior_rth_val"].to_numpy(dtype=float)

    trades: list[dict[str, object]] = []
    for idx in active_indices:
        i_entry = int(idx) + int(entry_lag_bars)
        i_exit = int(idx) + int(horizon_bars)
        if i_entry >= n_rows or i_exit >= n_rows:
            continue

        # Ensure entry and exit stay within the same trading session
        sess_date = times.iloc[idx].date()
        if times.iloc[i_entry].date() != sess_date:
            continue
        while i_exit > i_entry and times.iloc[i_exit].date() != sess_date:
            i_exit -= 1

        entry_p = float(open_arr[i_entry])
        d = float(np.sign(sig_arr[idx]))
        s_pts = float(stop_arr[idx])
        t_pts = float(target_arr[idx])

        outcome = "timeout_30m"
        exit_p = float(close_arr[i_exit])
        exit_time = times.iloc[i_exit]
        realized_raw_pts = float(d * (exit_p - entry_p))

        for t_idx in range(i_entry, i_exit + 1):
            bh = float(high_arr[t_idx])
            bl = float(low_arr[t_idx])
            stop_hit = (bl <= entry_p - s_pts) if d > 0 else (bh >= entry_p + s_pts)
            target_hit = (bh >= entry_p + t_pts) if d > 0 else (bl <= entry_p - t_pts)

            # Conservative stop-first resolution if both touched on same 1-minute bar
            if stop_hit:
                outcome = "stop_loss"
                exit_p = entry_p - d * s_pts
                exit_time = times.iloc[t_idx]
                realized_raw_pts = -s_pts
                break
            if target_hit:
                outcome = "profit_target_poc"
                exit_p = entry_p + d * t_pts
                exit_time = times.iloc[t_idx]
                realized_raw_pts = t_pts
                break

        net_pts_150 = realized_raw_pts - float(round_trip_cost_points)
        net_pts_200 = realized_raw_pts - float(stress_cost_points)

        # Volatility-targeted Micro MNQ sizing ($250 risk budget, 1..4 MNQ contracts, $2/pt per MNQ)
        micro_pt_val = 2.0
        ideal_contracts = float(risk_budget_dollars) / max(s_pts * micro_pt_val, 1.0)
        contracts_micro = int(np.clip(np.round(ideal_contracts), 1, max_micros))

        # Net Micro PnL including 1.50pt total friction ($3.00/RT per micro = $1.20 comm + 0.90pt slippage)
        pnl_micro_net_150 = net_pts_150 * micro_pt_val * contracts_micro
        pnl_micro_net_200 = net_pts_200 * micro_pt_val * contracts_micro
        pnl_mini_net_150 = net_pts_150 * 20.0

        trades.append(
            {
                "date_str": str(sess_date),
                "signal_time": times.iloc[idx],
                "entry_time": times.iloc[i_entry],
                "exit_time": exit_time,
                "direction": "long" if d > 0 else "short",
                "level_tested": str(level_arr[idx]),
                "entry_price": entry_p,
                "exit_price": exit_p,
                "prior_poc": float(poc_arr[idx]),
                "prior_vah": float(vah_arr[idx]),
                "prior_val": float(val_arr[idx]),
                "stop_pts": s_pts,
                "target_pts": t_pts,
                "rr_ratio": t_pts / max(s_pts, 1e-6),
                "reason": outcome,
                "hold_minutes": max(1, int((exit_time - times.iloc[i_entry]).total_seconds() // 60) + 1),
                "gross_pts": realized_raw_pts,
                "net_pts_150": net_pts_150,
                "net_pts_200": net_pts_200,
                "contracts_micro": contracts_micro,
                "pnl_micro_net_150": pnl_micro_net_150,
                "pnl_micro_net_200": pnl_micro_net_200,
                "pnl_mini_net_150": pnl_mini_net_150,
                "strategy": "H5_VA_Responsive_Rotation",
            }
        )
    return pd.DataFrame(trades)


def summarize_era(df_trades: pd.DataFrame, label: str) -> dict[str, object]:
    if df_trades.empty:
        return {"era": label, "n_trades": 0}
    n = len(df_trades)
    wins = df_trades["net_pts_150"] > 0
    win_rate = float(wins.mean() * 100.0)
    gross_mean = float(df_trades["gross_pts"].mean())
    net_mean_150 = float(df_trades["net_pts_150"].mean())
    net_mean_200 = float(df_trades["net_pts_200"].mean())

    pos_sum = float(df_trades.loc[df_trades["net_pts_150"] > 0, "net_pts_150"].sum())
    neg_sum = float(abs(df_trades.loc[df_trades["net_pts_150"] <= 0, "net_pts_150"].sum()))
    pf_pts = pos_sum / neg_sum if neg_sum > 0 else np.inf

    cum_micro = df_trades["pnl_micro_net_150"].cumsum()
    dd_micro = float((cum_micro - cum_micro.cummax()).min())

    cum_pts = df_trades["net_pts_150"].cumsum()
    dd_pts = float((cum_pts - cum_pts.cummax()).min())

    target_pct = float((df_trades["reason"] == "profit_target_poc").mean() * 100.0)
    stop_pct = float((df_trades["reason"] == "stop_loss").mean() * 100.0)
    timeout_pct = float((df_trades["reason"] == "timeout_30m").mean() * 100.0)

    longs = df_trades[df_trades["direction"] == "long"]
    shorts = df_trades[df_trades["direction"] == "short"]

    return {
        "era": label,
        "n_trades": n,
        "win_rate_pct": win_rate,
        "gross_mean_pts": gross_mean,
        "net_mean_150_pts": net_mean_150,
        "net_mean_200_pts": net_mean_200,
        "total_net_pts_150": float(df_trades["net_pts_150"].sum()),
        "profit_factor_150": pf_pts,
        "max_dd_pts": dd_pts,
        "total_micro_pnl_150": float(df_trades["pnl_micro_net_150"].sum()),
        "max_dd_micro_150": dd_micro,
        "target_hit_pct": target_pct,
        "stop_hit_pct": stop_pct,
        "timeout_pct": timeout_pct,
        "long_n": len(longs),
        "long_net_mean_pts": float(longs["net_pts_150"].mean()) if len(longs) else np.nan,
        "short_n": len(shorts),
        "short_net_mean_pts": float(shorts["net_pts_150"].mean()) if len(shorts) else np.nan,
    }


def main() -> int:
    print("Loading 2016-2026 NQ 1m dataset...")
    data = load_ohlcv_data(
        "data/raw/nq_1m_2014_2026_merged.parquet",
        continuous_contract_method=BACKTEST_CONFIG.get("continuous_contract_method"),
        start="2015-12-15",
        end="2026-04-28 23:59:59",
    )
    cfg = ValueAreaResponsiveRotationConfig()
    sig_frame = build_value_area_responsive_rotation_signal_frame(data, config=cfg)

    for hz in (24, 30):
        all_trades = simulate_h5_barrier_trades(sig_frame, horizon_bars=hz)
        all_trades["entry_dt"] = pd.to_datetime(all_trades["entry_time"])
        all_trades = all_trades.loc[all_trades["entry_dt"] >= pd.Timestamp("2016-01-01")].reset_index(drop=True)

        t_2016_2020 = all_trades.loc[all_trades["entry_dt"] <= pd.Timestamp("2020-12-31 23:59:59")]
        t_2021_2024 = all_trades.loc[
            (all_trades["entry_dt"] >= pd.Timestamp("2021-01-01"))
            & (all_trades["entry_dt"] <= pd.Timestamp("2024-12-31 23:59:59"))
        ]
        t_2025_2026 = all_trades.loc[all_trades["entry_dt"] >= pd.Timestamp("2025-01-01")]
        t_2021_2026 = all_trades.loc[all_trades["entry_dt"] >= pd.Timestamp("2021-01-01")]

        rows = [
            summarize_era(t_2016_2020, "2016-2020 (Transition)"),
            summarize_era(t_2021_2024, "2021-2024 (Recent Dev)"),
            summarize_era(t_2025_2026, "2025-2026 (OOS Holdout)"),
            summarize_era(t_2021_2026, "2021-2026 (Full Modern)"),
        ]
        summary_df = pd.DataFrame(rows)
        print(f"\n=== H5 BARRIER-MANAGED BACKTEST SUMMARY (Horizon = {hz}m) ===")
        print(summary_df.to_string(index=False))

        if hz == 30:
            t_2021_2026_copy = t_2021_2026.copy()
            t_2021_2026_copy["year"] = t_2021_2026_copy["entry_dt"].dt.year
            yr_rows = [
                summarize_era(grp, f"Year {yr}") for yr, grp in t_2021_2026_copy.groupby("year", sort=True)
            ]
            print("\n=== H5 YEAR-BY-YEAR BREAKDOWN (2021-2026, 30m Horizon) ===")
            print(pd.DataFrame(yr_rows).to_string(index=False))

            out_dir = REPO_ROOT / "results/research_master/strategy_backtests"
            out_dir.mkdir(parents=True, exist_ok=True)
            all_trades.to_csv(out_dir / "h5_va_responsive_rotation_trades_2016_2026.csv", index=False)
            summary_df.to_csv(out_dir / "h5_va_responsive_rotation_era_summary.csv", index=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
