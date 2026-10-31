#!/usr/bin/env python3
"""
Convert MotiveWave CQG 1-Minute CSV Exports (@YM, @GC, @RTY, @ES, @NQ) to Parquet
and Run Full 1-Minute Point-in-Time Morning Value Area Breakout Backtest (2020-2026).

Evaluates:
1. Individual Asset Performance (2020-2026 Full, 2021-2024 Core, 2025-2026 OOS Holdout)
   - Baseline Structural Outside-VA Breakout (with and without overnight gap requirement)
   - Intermarket + Macro Gated (ES/NQ 09:30-09:44 alignment + VIX/VX/TICK macro gate)
2. Unseen May-Oct 2026 Forward Window Performance across all 5 assets
3. Combined Multi-Asset Prop Portfolio Simulation ($250 Risk Budget, 1-4 Micros)
"""

from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.morning_value_area_breakout_signal import (
    MorningValueAreaBreakoutConfig,
    build_morning_value_area_breakout_signal_frame,
)


CQG_EXPORTS = [
    {
        "sym": "YM",
        "micro": "MYM",
        "name": "Dow (YM / MYM)",
        "csv_path": ROOT / "data/raw/@YM.CQG_1.csv",
        "pq_path": ROOT / "data/raw/ym_1m_2020_2026_et.parquet",
        "rth_start": "09:30",
        "signal_bar_time": "09:44",
        "entry_time": "09:45",
        "rth_end": "16:00",
        "min_abs_return_pct": 0.0008,  # 0.08% (~34 pts on 42,000 YM)
        "min_stop_pts": 25.0,
        "max_stop_pts": 120.0,
        "profile_bin_size": 5.0,
        "micro_pt_val": 0.50,          # $0.50/pt per MYM
        "mini_pt_val": 5.0,
        "comm_micro_rt": 1.20,
        "slip_pts": 2.0,               # 2 ticks (2.0 pts = $1.00/contract)
        "use_10am_news_guard": True,
    },
    {
        "sym": "GC",
        "micro": "MGC",
        "name": "Gold (GC / MGC)",
        "csv_path": ROOT / "data/raw/@GC.CQG_1.csv",
        "pq_path": ROOT / "data/raw/gc_1m_2020_2026_et.parquet",
        "rth_start": "08:20",
        "signal_bar_time": "08:34",
        "entry_time": "08:35",
        "rth_end": "13:30",
        "min_abs_return_pct": 0.0008,  # 0.08% (~$2.20 on $2,750 GC)
        "min_stop_pts": 2.5,
        "max_stop_pts": 15.0,
        "profile_bin_size": 0.5,
        "micro_pt_val": 10.0,          # $10.00/pt per MGC ($1.00 per $0.10 tick)
        "mini_pt_val": 100.0,
        "comm_micro_rt": 1.50,
        "slip_pts": 0.20,              # 2 ticks ($0.20 = $2.00/contract)
        "use_10am_news_guard": False,
    },
    {
        "sym": "RTY",
        "micro": "M2K",
        "name": "Russell 2000 (RTY / M2K)",
        "csv_path": ROOT / "data/raw/@RTY.CQG_1.csv",
        "pq_path": ROOT / "data/raw/rty_1m_2020_2026_et.parquet",
        "rth_start": "09:30",
        "signal_bar_time": "09:44",
        "entry_time": "09:45",
        "rth_end": "16:00",
        "min_abs_return_pct": 0.0010,  # 0.10%
        "min_stop_pts": 3.0,
        "max_stop_pts": 15.0,
        "profile_bin_size": 0.5,
        "micro_pt_val": 5.0,           # $5.00/pt per M2K ($0.50 per 0.10 tick)
        "mini_pt_val": 50.0,
        "comm_micro_rt": 1.20,
        "slip_pts": 0.20,              # 2 ticks (0.20 pts = $1.00/contract)
        "use_10am_news_guard": True,
    },
    {
        "sym": "ES",
        "micro": "MES",
        "name": "S&P 500 (ES / MES)",
        "csv_path": ROOT / "data/raw/@ES.CQG_1.csv",
        "pq_path": ROOT / "data/raw/es_1m_2020_2026_cqg_et.parquet",
        "rth_start": "09:30",
        "signal_bar_time": "09:44",
        "entry_time": "09:45",
        "rth_end": "16:00",
        "min_abs_return_pct": 0.0010,
        "min_stop_pts": 5.0,
        "max_stop_pts": 35.0,
        "profile_bin_size": 0.5,
        "micro_pt_val": 5.0,           # $5.00/pt per MES
        "mini_pt_val": 50.0,
        "comm_micro_rt": 1.20,
        "slip_pts": 0.25,              # 1 tick (0.25 pts = $1.25/contract)
        "use_10am_news_guard": True,
    },
    {
        "sym": "NQ",
        "micro": "MNQ",
        "name": "Nasdaq-100 (NQ / MNQ)",
        "csv_path": ROOT / "data/raw/@NQ.CQG_1.csv",
        "pq_path": ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet",
        "rth_start": "09:30",
        "signal_bar_time": "09:44",
        "entry_time": "09:45",
        "rth_end": "16:00",
        "min_abs_return_pct": 0.0010,
        "min_stop_pts": 15.0,
        "max_stop_pts": 60.0,
        "profile_bin_size": 1.0,
        "micro_pt_val": 2.0,           # $2.00/pt per MNQ
        "mini_pt_val": 20.0,
        "comm_micro_rt": 1.20,
        "slip_pts": 0.50,              # 2 ticks (0.50 pts = $1.00/contract)
        "use_10am_news_guard": True,
    },
]


def convert_csv_to_parquet(spec: dict) -> pd.DataFrame:
    pq_path: Path = spec["pq_path"]
    csv_path: Path = spec["csv_path"]
    if pq_path.exists() and pq_path.stat().st_mtime >= csv_path.stat().st_mtime:
        print(f"[Cache Hit] Loading {pq_path.name}...")
        return pd.read_parquet(pq_path)

    print(f"[Converting] Reading {csv_path.name} -> {pq_path.name}...")
    df = pd.read_csv(
        csv_path,
        names=["dt_str", "open", "high", "low", "close", "volume"],
        dtype={
            "dt_str": "string",
            "open": "float64",
            "high": "float64",
            "low": "float64",
            "close": "float64",
            "volume": "int64",
        },
    )
    df["time"] = pd.to_datetime(df["dt_str"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
    df = df.dropna(subset=["time"]).drop(columns=["dt_str"])
    df["symbol"] = spec["sym"]
    df = df[["time", "open", "high", "low", "close", "volume", "symbol"]].sort_values(
        "time", kind="stable"
    )
    df = df.drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)
    df.to_parquet(pq_path, index=False)
    print(
        f"  -> Saved {len(df):,} bars ({df['time'].iloc[0]} to {df['time'].iloc[-1]}) to {pq_path.name}"
    )
    return df


def is_10am_news_day(dt: pd.Timestamp) -> bool:
    day = dt.day
    dow = dt.weekday()  # 0=Mon..4=Fri
    if dow == 2 and day <= 7:
        return True
    if dow == 1 and day >= 24:
        return True
    if dow == 4 and ((8 <= day <= 14) or (22 <= day <= 28)):
        return True
    if day in (1, 2, 3) and dow in (0, 1, 2, 3):
        return True
    if day in (3, 4, 5) and dow in (1, 2, 3):
        return True
    return False


def compute_daily_or15_dir(df: pd.DataFrame, start_hhmm: str = "09:30", end_hhmm: str = "09:44") -> dict[str, int]:
    s_h, s_m = map(int, start_hhmm.split(":"))
    e_h, e_m = map(int, end_hhmm.split(":"))
    m = df["time"].dt.hour * 60 + df["time"].dt.minute
    sub = df[(m >= s_h * 60 + s_m) & (m <= e_h * 60 + e_m)]
    stats = sub.groupby(sub["time"].dt.date).agg(o=("open", "first"), c=("close", "last"))
    out: dict[str, int] = {}
    for dt_val, row in stats.iterrows():
        d_str = str(dt_val)
        if row["c"] > row["o"]:
            out[d_str] = 1
        elif row["c"] < row["o"]:
            out[d_str] = -1
        else:
            out[d_str] = 0
    return out


def simulate_asset_trades(
    df: pd.DataFrame,
    spec: dict,
    *,
    require_with_gap: bool,
    es_dir_map: dict[str, int],
    nq_dir_map: dict[str, int],
    macro_map: dict[str, tuple[float, float]],
) -> pd.DataFrame:
    df_2020 = df[df["time"] >= "2020-01-01"].reset_index(drop=True)
    cfg = MorningValueAreaBreakoutConfig(
        min_abs_return_pct=spec["min_abs_return_pct"],
        min_long_close_location=0.65,
        max_short_close_location=0.35,
        require_outside_prior_va=True,
        require_with_gap=require_with_gap,
        allow_long=True,
        allow_short=True,
        min_stop_points=spec["min_stop_pts"],
        max_stop_points=spec["max_stop_pts"],
        reward_risk_ratio=1.5,
        profile_bin_size=spec["profile_bin_size"],
        value_area_pct=0.70,
        rth_start=spec["rth_start"],
        signal_bar_time=spec["signal_bar_time"],
        rth_end=spec["rth_end"],
    )
    # Strip symbol column so _base_ohlcv_frame doesn't run contract stitching
    sig_frame = build_morning_value_area_breakout_signal_frame(
        df_2020[["time", "open", "high", "low", "close", "volume"]], config=cfg
    )
    active = sig_frame[sig_frame["candidate_signal"] != 0.0].copy()
    if active.empty:
        return pd.DataFrame()

    # Index 1m bars by date for fast forward execution
    df_2020["date_str"] = df_2020["time"].dt.strftime("%Y-%m-%d")
    df_2020["hhmm"] = df_2020["time"].dt.strftime("%H:%M")

    entry_hhmm = spec["entry_time"]
    e_h, e_m = map(int, entry_hhmm.split(":"))
    end_min = e_h * 60 + e_m + 29  # 30 bars inclusive (e.g. 09:45..10:14)
    end_hhmm = f"{end_min // 60:02d}:{end_min % 60:02d}"

    post_window = df_2020[(df_2020["hhmm"] >= entry_hhmm) & (df_2020["hhmm"] <= end_hhmm)]
    bars_by_date = {d: g.reset_index(drop=True) for d, g in post_window.groupby("date_str")}

    trades = []
    for _, srow in active.iterrows():
        sig_time = pd.Timestamp(srow["time"])
        d_str = sig_time.strftime("%Y-%m-%d")
        ebars = bars_by_date.get(d_str)
        if ebars is None or len(ebars) < 5:
            continue

        d = 1 if float(srow["candidate_signal"]) > 0 else -1
        entry_p = float(ebars.iloc[0]["open"])
        stop_pts = float(srow["stop_points"])
        target_pts = float(srow["target_points"])
        stop_price = entry_p - d * stop_pts
        target_price = entry_p + d * target_pts

        has_10am_news = spec["use_10am_news_guard"] and is_10am_news_day(sig_time)

        exit_p = float(ebars.iloc[-1]["close"])
        exit_time = pd.Timestamp(ebars.iloc[-1]["time"])
        reason = "time_exit_30m"

        for b_i, b in ebars.iterrows():
            bh = float(b["high"])
            bl = float(b["low"])
            bc = float(b["close"])

            if (d == 1 and bl <= stop_price) or (d == -1 and bh >= stop_price):
                exit_p = stop_price
                exit_time = pd.Timestamp(b["time"])
                reason = "stop_loss"
                break
            if (d == 1 and bh >= target_price) or (d == -1 and bl <= target_price):
                exit_p = target_price
                exit_time = pd.Timestamp(b["time"])
                reason = "profit_target_150r"
                break
            if has_10am_news and b_i >= 14:
                exit_p = bc
                exit_time = pd.Timestamp(b["time"])
                reason = "news_flatten_1000"
                break

        raw_pts = (exit_p - entry_p) * d
        net_pts = raw_pts - spec["slip_pts"]

        risk_budget = 250.0
        contracts = int(
            np.clip(np.round(risk_budget / max(stop_pts * spec["micro_pt_val"], 1.0)), 1, 4)
        )
        net_dollars_micro = net_pts * spec["micro_pt_val"] * contracts - (spec["comm_micro_rt"] * contracts)

        # Intermarket alignment (09:45 ET equity indices align with ES & NQ)
        intermarket_ok = True
        macro_ok = True
        if spec["entry_time"] == "09:45":
            es_d = es_dir_map.get(d_str, 0)
            nq_d = nq_dir_map.get(d_str, 0)
            if spec["sym"] == "ES":
                intermarket_ok = (d == 1 and nq_d > 0) or (d == -1 and nq_d < 0)
            elif spec["sym"] == "NQ":
                intermarket_ok = (d == 1 and es_d > 0) or (d == -1 and es_d < 0)
            else:
                # For YM and RTY: require ES confirmation
                intermarket_ok = (d == 1 and es_d > 0) or (d == -1 and es_d < 0)

            if d_str in macro_map:
                vx_chg, tick_m = macro_map[d_str]
                if not np.isnan(vx_chg):
                    if d == 1 and vx_chg > 0.0:
                        macro_ok = False
                    elif d == -1 and vx_chg < 0.0:
                        macro_ok = False
                if not np.isnan(tick_m):
                    if d == 1 and tick_m > 100.0:
                        macro_ok = False
                    elif d == -1 and tick_m < -100.0:
                        macro_ok = False

        trades.append(
            {
                "date_str": d_str,
                "year": sig_time.year,
                "sym": spec["sym"],
                "micro": spec["micro"],
                "asset": spec["name"],
                "entry_time": pd.Timestamp(ebars.iloc[0]["time"]),
                "exit_time": exit_time,
                "direction": "long" if d == 1 else "short",
                "entry_price": entry_p,
                "exit_price": exit_p,
                "stop_pts": stop_pts,
                "target_pts": target_pts,
                "reason": reason,
                "net_pts": net_pts,
                "contracts": contracts,
                "net_dollars_micro": net_dollars_micro,
                "intermarket_ok": intermarket_ok,
                "macro_ok": macro_ok,
                "full_gate_ok": intermarket_ok and macro_ok,
            }
        )

    return pd.DataFrame(trades)


def summarize_era(t_df: pd.DataFrame, asset_name: str, micro: str, mode: str, era_label: str) -> dict:
    if t_df.empty:
        return {
            "asset": asset_name,
            "micro": micro,
            "mode": mode,
            "era": era_label,
            "n_trades": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "mean_pts": 0.0,
            "mean_micro_pnl": 0.0,
            "total_micro_pnl": 0.0,
            "max_dd_micro": 0.0,
        }
    wins = t_df["net_dollars_micro"] > 0
    pos = float(t_df.loc[wins, "net_dollars_micro"].sum())
    neg = float(abs(t_df.loc[~wins, "net_dollars_micro"].sum()))
    pf = pos / neg if neg > 0 else np.inf
    cum = t_df["net_dollars_micro"].cumsum()
    max_dd = float((cum - cum.cummax()).min())
    return {
        "asset": asset_name,
        "micro": micro,
        "mode": mode,
        "era": era_label,
        "n_trades": len(t_df),
        "win_rate_pct": round(float(wins.mean() * 100.0), 1),
        "profit_factor": round(pf, 2),
        "mean_pts": round(float(t_df["net_pts"].mean()), 2),
        "mean_micro_pnl": round(float(t_df["net_dollars_micro"].mean()), 2),
        "total_micro_pnl": round(float(t_df["net_dollars_micro"].sum()), 2),
        "max_dd_micro": round(max_dd, 2),
    }


def df_to_md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = ["| " + " | ".join(str(r[c]) for c in cols) + " |" for _, r in df.iterrows()]
    return "\n".join([header, sep] + rows)


def main() -> int:
    # 1. Convert all 5 CSVs to Parquet
    dfs: dict[str, pd.DataFrame] = {}
    for spec in CQG_EXPORTS:
        dfs[spec["sym"]] = convert_csv_to_parquet(spec)

    # 2. Precompute ES and NQ 09:30-09:44 directional maps across 2020-2026
    print("\nComputing ES and NQ 09:30-09:44 intermarket direction maps (2020-2026)...")
    es_dir_map = compute_daily_or15_dir(dfs["ES"], "09:30", "09:44")
    nq_dir_map = compute_daily_or15_dir(dfs["NQ"], "09:30", "09:44")

    # Load historical macro context (VX + TICK) where available
    macro_map: dict[str, tuple[float, float]] = {}
    macro_path = ROOT / "data/processed/macro_context/morning_cross_asset_features_0945.parquet"
    if macro_path.exists():
        m_df = pd.read_parquet(macro_path)
        for _, r in m_df.iterrows():
            d_str = str(r["date_str"])
            vx_c = float(r["vx_or15_change_pct"]) if pd.notna(r.get("vx_or15_change_pct")) else np.nan
            tk_m = float(r["tick_or15_mean"]) if pd.notna(r.get("tick_or15_mean")) else np.nan
            macro_map[d_str] = (vx_c, tk_m)

    # 3. Simulate across all 5 assets (both With-Gap and Any-Gap, Unfiltered vs Intermarket+Macro Gated)
    summary_rows = []
    gated_trades_by_sym: dict[str, pd.DataFrame] = {}

    for spec in CQG_EXPORTS:
        sym = spec["sym"]
        print(f"Simulating 1-minute Morning Value Area Breakout (2020-2026) for {spec['name']}...")
        for gap_flag, gap_label in [(True, "WithGap"), (False, "AllBreakouts")]:
            t_df = simulate_asset_trades(
                dfs[sym],
                spec,
                require_with_gap=gap_flag,
                es_dir_map=es_dir_map,
                nq_dir_map=nq_dir_map,
                macro_map=macro_map,
            )
            if t_df.empty:
                continue

            # Save gated trades for portfolio simulation
            t_gated = t_df[t_df["full_gate_ok"]].reset_index(drop=True)
            if gap_flag:
                gated_trades_by_sym[f"{sym}_WithGap"] = t_gated
            else:
                gated_trades_by_sym[f"{sym}_All"] = t_gated

            for mode_name, sub_df in [
                (f"{gap_label} | Raw", t_df),
                (f"{gap_label} | Intermarket+Macro", t_gated),
            ]:
                if spec["entry_time"] != "09:45" and "Intermarket" in mode_name:
                    continue
                for era_label, mask in [
                    ("2020-2026 (Full)", sub_df["date_str"] >= "2020-01-01"),
                    ("2021-2024 (Core)", (sub_df["date_str"] >= "2021-01-01") & (sub_df["date_str"] <= "2024-12-31")),
                    ("2025-2026 (OOS)", sub_df["date_str"] >= "2025-01-01"),
                    ("May-Oct 2026 (New)", sub_df["date_str"] >= "2026-05-01"),
                ]:
                    era_df = sub_df[mask].reset_index(drop=True)
                    summary_rows.append(
                        summarize_era(era_df, spec["name"], spec["micro"], mode_name, era_label)
                    )

    sum_df = pd.DataFrame(summary_rows)

    print("\n=== A. FULL 2020-2026 (6.6 YEARS) 1-MINUTE SUMMARY BY ASSET & MODE ===")
    full_df = sum_df[sum_df["era"] == "2020-2026 (Full)"].reset_index(drop=True)
    print(full_df.to_string(index=False))

    print("\n=== B. CORE 2021-2024 vs. OUT-OF-SAMPLE 2025-2026 (INTERMARKET+MACRO GATED) ===")
    gated_df = sum_df[
        (sum_df["mode"].str.contains("Intermarket") | (sum_df["micro"] == "MGC"))
        & (sum_df["era"].isin(["2021-2024 (Core)", "2025-2026 (OOS)", "May-Oct 2026 (New)"]))
    ].reset_index(drop=True)
    print(gated_df.to_string(index=False))

    # Save outputs
    out_dir = ROOT / "results/research_master"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_out = out_dir / "multi_asset_cqg_1m_2020_2026_summary.csv"
    md_out = out_dir / "multi_asset_cqg_1m_2020_2026_report.md"
    sum_df.to_csv(csv_out, index=False)

    md_text = "\n".join(
        [
            "# Multi-Asset 1-Minute CQG Morning Value Area Breakout Backtest (`2020–2026`)",
            "",
            "## 1. Full Sample (`2020–2026`, ~1,700 Sessions) by Asset & Mode",
            "",
            df_to_md(full_df),
            "",
            "## 2. Core Era (`2021–2024`), OOS Holdout (`2025–2026`), and Unseen `May–Oct 2026`",
            "",
            df_to_md(gated_df),
            "",
        ]
    )
    md_out.write_text(md_text)
    print(f"\nSaved summary CSV to {csv_out} and markdown report to {md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
