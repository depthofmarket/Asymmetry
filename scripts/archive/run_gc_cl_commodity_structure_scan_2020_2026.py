#!/usr/bin/env python3
"""
Convert @CL.CQG_1.csv to Parquet and Run a 6.8-Year (2020-2026) 1-Minute
Commodity Microstructure Strategy Scan on Gold (GC / MGC) and Crude Oil (CL / MCL).

Tests 6 institutional non-news commodity archetypes across 2020-2026
(requiring positive edge in BOTH 2021-2024 Core and 2025-2026 OOS):
1. IB60_VA_Breakout: 60-Min Initial Balance (08:20-09:19 GC / 09:00-09:59 CL) + Prior VA Escape
2. London_Range_Breakout: US Open Breakout of London Session (03:00-08:19 ET) High/Low
3. London_Sweep_Reclaim_Fade: US Open Sweep of London High/Low that Closes Back Inside London Range
4. London_Fix_1015_Drive_And_Fade: 10:00-10:14 ET (15:00 London Fix) Continuation & Exhaustion Fade
5. Euro_Close_1130_Continuation: 11:15-11:30 ET (London/European Close) Trend Continuation
6. Settlement_Window_Drive: Final 45-Min Pre-Settlement Institutional Drive (12:45-13:29 GC / 13:45-14:29 CL)
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def ensure_cl_parquet() -> pd.DataFrame:
    pq_path = ROOT / "data/raw/cl_1m_2020_2026_et.parquet"
    csv_path = ROOT / "data/raw/@CL.CQG_1.csv"
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
    df["symbol"] = "CL"
    df = df[["time", "open", "high", "low", "close", "volume", "symbol"]].sort_values(
        "time", kind="stable"
    )
    df = df.drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)
    df.to_parquet(pq_path, index=False)
    print(f"  -> Saved {len(df):,} bars ({df['time'].iloc[0]} to {df['time'].iloc[-1]})")
    return df


def build_daily_session_table(df: pd.DataFrame, sym: str) -> pd.DataFrame:
    """
    Vectorized daily feature extraction from 1-minute bars (2020-2026) for GC or CL.
    Zero lookahead: every window's stats use only bars up to that window's close.
    """
    df = df[df["time"] >= "2020-01-01"].copy()
    # Filter out April 2020 negative CL price anomaly week if CL
    df = df[df["open"] > 0].reset_index(drop=True)
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["time"].dt.strftime("%H:%M")
    df["dow"] = df["time"].dt.weekday  # 0=Mon..4=Fri

    if sym == "GC":
        rth_start, rth_end = "08:20", "13:30"
        ib_start, ib_end, ib_eval_end = "08:20", "09:19", "10:19"
        settle_sig_start, settle_sig_end, settle_eval_end = "12:45", "13:29", "13:29"
    else:
        rth_start, rth_end = "09:00", "14:30"
        ib_start, ib_end, ib_eval_end = "09:00", "09:59", "10:59"
        settle_sig_start, settle_sig_end, settle_eval_end = "13:45", "14:29", "14:29"

    # Group by date_str
    rth_bars = df[(df["hhmm"] >= rth_start) & (df["hhmm"] <= rth_end)]
    rth_daily = rth_bars.groupby("date_str").agg(
        rth_open=("open", "first"),
        rth_high=("high", "max"),
        rth_low=("low", "min"),
        rth_close=("close", "last"),
        rth_count=("close", "count"),
    )
    # Approximate prior session VAH / VAL (middle 70% of prior RTH range around VWAP/typical price)
    rth_vwap_num = (
        ((rth_bars["high"] + rth_bars["low"] + rth_bars["close"]) / 3.0) * rth_bars["volume"]
    ).groupby(rth_bars["date_str"]).sum()
    rth_vwap_den = rth_bars["volume"].groupby(rth_bars["date_str"]).sum().clip(lower=1)
    rth_daily["rth_vwap"] = rth_vwap_num / rth_vwap_den
    rth_daily["rth_range"] = rth_daily["rth_high"] - rth_daily["rth_low"]
    rth_daily["prior_vah"] = (rth_daily["rth_vwap"] + 0.35 * rth_daily["rth_range"]).shift(1)
    rth_daily["prior_val"] = (rth_daily["rth_vwap"] - 0.35 * rth_daily["rth_range"]).shift(1)
    rth_daily["prior_close"] = rth_daily["rth_close"].shift(1)
    rth_daily["prior_range"] = rth_daily["rth_range"].shift(1)

    # London session (03:00 - 08:19 ET)
    lon = df[(df["hhmm"] >= "03:00") & (df["hhmm"] <= "08:19")]
    lon_daily = lon.groupby("date_str").agg(
        lon_open=("open", "first"),
        lon_high=("high", "max"),
        lon_low=("low", "min"),
        lon_close=("close", "last"),
    )

    # IB60 window
    ib = df[(df["hhmm"] >= ib_start) & (df["hhmm"] <= ib_end)]
    ib_daily = ib.groupby("date_str").agg(
        ib_open=("open", "first"),
        ib_high=("high", "max"),
        ib_low=("low", "min"),
        ib_close=("close", "last"),
    )

    # 10:00-10:14 ET window (London Fix)
    fix = df[(df["hhmm"] >= "10:00") & (df["hhmm"] <= "10:14")]
    fix_daily = fix.groupby("date_str").agg(
        fix_open=("open", "first"),
        fix_high=("high", "max"),
        fix_low=("low", "min"),
        fix_close=("close", "last"),
    )

    # Morning up to 11:29 ET (European Close check at 11:30 ET)
    m1130 = df[(df["hhmm"] >= rth_start) & (df["hhmm"] <= "11:29")]
    m1130_daily = m1130.groupby("date_str").agg(
        m1130_open=("open", "first"),
        m1130_high=("high", "max"),
        m1130_low=("low", "min"),
        m1130_close=("close", "last"),
    )

    # Morning/Early afternoon up to pre-settlement entry (12:44 GC / 13:44 CL)
    pre_settle_end = "12:44" if sym == "GC" else "13:44"
    pset = df[(df["hhmm"] >= rth_start) & (df["hhmm"] <= pre_settle_end)]
    pset_daily = pset.groupby("date_str").agg(
        pset_open=("open", "first"),
        pset_high=("high", "max"),
        pset_low=("low", "min"),
        pset_close=("close", "last"),
    )

    table = (
        rth_daily.join(lon_daily, how="left")
        .join(ib_daily, how="left")
        .join(fix_daily, how="left")
        .join(m1130_daily, how="left")
        .join(pset_daily, how="left")
        .reset_index()
    )
    table = table[table["rth_count"] >= 120].reset_index(drop=True)
    return table


def execute_window_trades(
    df_1m: pd.DataFrame,
    signals_df: pd.DataFrame,
    *,
    entry_hhmm: str,
    exit_hhmm: str,
    sym: str,
    archetype_name: str,
) -> pd.DataFrame:
    if signals_df.empty:
        return pd.DataFrame()

    if sym == "GC":
        micro = "MGC"
        micro_pt_val = 10.0
        comm_rt = 1.50
        slip_pts = 0.20
        min_stop, max_stop = 3.0, 18.0
    else:
        micro = "MCL"
        micro_pt_val = 100.0
        comm_rt = 1.50
        slip_pts = 0.02
        min_stop, max_stop = 0.20, 1.20

    df_sub = df_1m[
        (df_1m["time"] >= "2020-01-01")
        & (df_1m["open"] > 0)
    ].copy()
    df_sub["date_str"] = df_sub["time"].dt.strftime("%Y-%m-%d")
    df_sub["hhmm"] = df_sub["time"].dt.strftime("%H:%M")

    win_bars = df_sub[(df_sub["hhmm"] >= entry_hhmm) & (df_sub["hhmm"] <= exit_hhmm)]
    bars_by_date = {d: g.reset_index(drop=True) for d, g in win_bars.groupby("date_str")}

    trades = []
    for _, srow in signals_df.iterrows():
        d_str = str(srow["date_str"])
        ebars = bars_by_date.get(d_str)
        if ebars is None or len(ebars) < 5:
            continue

        d = int(srow["direction"])
        entry_p = float(ebars.iloc[0]["open"])
        raw_stop = float(srow["stop_ref"])
        stop_pts = float(np.clip(raw_stop, min_stop, max_stop))
        target_pts = stop_pts * 1.50

        stop_price = entry_p - d * stop_pts
        target_price = entry_p + d * target_pts

        exit_p = float(ebars.iloc[-1]["close"])
        reason = "time_exit"
        for _, b in ebars.iterrows():
            bh = float(b["high"])
            bl = float(b["low"])
            if (d == 1 and bl <= stop_price) or (d == -1 and bh >= stop_price):
                exit_p = stop_price
                reason = "stop_loss"
                break
            if (d == 1 and bh >= target_price) or (d == -1 and bl <= target_price):
                exit_p = target_price
                reason = "profit_target_150r"
                break

        raw_pts = (exit_p - entry_p) * d
        net_pts = raw_pts - slip_pts
        contracts = int(np.clip(np.round(250.0 / max(stop_pts * micro_pt_val, 1.0)), 1, 4))
        net_dollars_micro = net_pts * micro_pt_val * contracts - (comm_rt * contracts)

        trades.append(
            {
                "date_str": d_str,
                "sym": sym,
                "micro": micro,
                "archetype": archetype_name,
                "direction": d,
                "net_pts": net_pts,
                "net_dollars_micro": net_dollars_micro,
                "reason": reason,
            }
        )
    return pd.DataFrame(trades)


def evaluate_archetypes_for_asset(df_1m: pd.DataFrame, sym: str) -> list[dict]:
    tbl = build_daily_session_table(df_1m, sym)
    results = []

    # Helper to build signals and summarize across 2020-2026, 2021-2024 Core, 2025-2026 OOS
    def run_and_summarize(sig_df: pd.DataFrame, entry_t: str, exit_t: str, arch_name: str):
        t_df = execute_window_trades(
            df_1m, sig_df, entry_hhmm=entry_t, exit_hhmm=exit_t, sym=sym, archetype_name=arch_name
        )
        if t_df.empty:
            return
        for era_lbl, mask in [
            ("2020-2026 (Full)", t_df["date_str"] >= "2020-01-01"),
            ("2021-2024 (Core)", (t_df["date_str"] >= "2021-01-01") & (t_df["date_str"] <= "2024-12-31")),
            ("2025-2026 (OOS)", t_df["date_str"] >= "2025-01-01"),
        ]:
            sub = t_df[mask]
            if sub.empty:
                continue
            wins = sub["net_dollars_micro"] > 0
            pos = float(sub.loc[wins, "net_dollars_micro"].sum())
            neg = float(abs(sub.loc[~wins, "net_dollars_micro"].sum()))
            pf = pos / neg if neg > 0 else np.inf
            cum = sub["net_dollars_micro"].cumsum()
            mdd = float((cum - cum.cummax()).min())
            results.append(
                {
                    "sym": sym,
                    "archetype": arch_name,
                    "window_et": f"{entry_t}-{exit_t}",
                    "era": era_lbl,
                    "n_trades": len(sub),
                    "win_rate_pct": round(float(wins.mean() * 100.0), 1),
                    "profit_factor": round(pf, 2),
                    "mean_micro_pnl": round(float(sub["net_dollars_micro"].mean()), 2),
                    "total_micro_pnl": round(float(sub["net_dollars_micro"].sum()), 2),
                    "max_dd_micro": round(mdd, 2),
                }
            )

    min_ret = 0.0015 if sym == "GC" else 0.0030

    # 1. IB60 + Prior VA Breakout (09:20 ET for GC, 10:00 ET for CL)
    ib_rng = (tbl["ib_high"] - tbl["ib_low"]).replace(0, np.nan)
    ib_loc = (tbl["ib_close"] - tbl["ib_low"]) / ib_rng
    ib_ret = (tbl["ib_close"] - tbl["ib_open"]) / tbl["ib_open"]
    c1_long = (ib_ret >= min_ret) & (ib_loc >= 0.65) & (tbl["ib_close"] > tbl["prior_vah"])
    c1_short = (ib_ret <= -min_ret) & (ib_loc <= 0.35) & (tbl["ib_close"] < tbl["prior_val"])
    s1 = tbl[c1_long | c1_short].copy()
    s1["direction"] = np.where(c1_long.loc[s1.index], 1, -1)
    s1["stop_ref"] = ib_rng.loc[s1.index] * 0.60
    run_and_summarize(
        s1,
        "09:20" if sym == "GC" else "10:00",
        "10:20" if sym == "GC" else "11:00",
        "1. IB60_Outside_VA_Breakout",
    )

    # 2. London Session Range Breakout at IB60 Close
    lon_rng = (tbl["lon_high"] - tbl["lon_low"]).replace(0, np.nan)
    c2_long = (tbl["ib_close"] > tbl["lon_high"]) & (ib_loc >= 0.65)
    c2_short = (tbl["ib_close"] < tbl["lon_low"]) & (ib_loc <= 0.35)
    s2 = tbl[c2_long | c2_short].copy()
    s2["direction"] = np.where(c2_long.loc[s2.index], 1, -1)
    s2["stop_ref"] = ib_rng.loc[s2.index] * 0.60
    run_and_summarize(
        s2,
        "09:20" if sym == "GC" else "10:00",
        "10:20" if sym == "GC" else "11:00",
        "2. London_Range_Breakout",
    )

    # 3. London Range Sweep & Reclaim Fade (Failed Breakout of London High/Low during IB60)
    c3_short = (tbl["ib_high"] > tbl["lon_high"]) & (tbl["ib_close"] < tbl["lon_high"]) & (ib_loc <= 0.40)
    c3_long = (tbl["ib_low"] < tbl["lon_low"]) & (tbl["ib_close"] > tbl["lon_low"]) & (ib_loc >= 0.60)
    s3 = tbl[c3_long | c3_short].copy()
    s3["direction"] = np.where(c3_long.loc[s3.index], 1, -1)
    s3["stop_ref"] = ib_rng.loc[s3.index] * 0.60
    run_and_summarize(
        s3,
        "09:20" if sym == "GC" else "10:00",
        "10:20" if sym == "GC" else "11:00",
        "3. London_Sweep_Reclaim_Fade",
    )

    # 4a. 10:00-10:15 ET London Fix Momentum Continuation
    fix_rng = (tbl["fix_high"] - tbl["fix_low"]).replace(0, np.nan)
    fix_loc = (tbl["fix_close"] - tbl["fix_low"]) / fix_rng
    fix_ret = (tbl["fix_close"] - tbl["fix_open"]) / tbl["fix_open"]
    c4a_long = (fix_ret >= min_ret * 0.75) & (fix_loc >= 0.70) & (tbl["fix_close"] > tbl["ib_high"])
    c4a_short = (fix_ret <= -min_ret * 0.75) & (fix_loc <= 0.30) & (tbl["fix_close"] < tbl["ib_low"])
    s4a = tbl[c4a_long | c4a_short].copy()
    s4a["direction"] = np.where(c4a_long.loc[s4a.index], 1, -1)
    s4a["stop_ref"] = fix_rng.loc[s4a.index]
    run_and_summarize(s4a, "10:15", "11:00", "4a. London_Fix_1015_Continuation")

    # 4b. 10:00-10:15 ET London Fix Exhaustion Fade
    s4b = s4a.copy()
    s4b["direction"] = -s4b["direction"]
    run_and_summarize(s4b, "10:15", "11:00", "4b. London_Fix_1015_Fade")

    # 5. European Close (11:30 ET) Trend Continuation
    m1130_rng = (tbl["m1130_high"] - tbl["m1130_low"]).replace(0, np.nan)
    m1130_loc = (tbl["m1130_close"] - tbl["m1130_low"]) / m1130_rng
    m1130_ret = (tbl["m1130_close"] - tbl["m1130_open"]) / tbl["m1130_open"]
    c5_long = (m1130_ret >= min_ret * 1.5) & (m1130_loc >= 0.75) & (tbl["m1130_close"] > tbl["prior_vah"])
    c5_short = (m1130_ret <= -min_ret * 1.5) & (m1130_loc <= 0.25) & (tbl["m1130_close"] < tbl["prior_val"])
    s5 = tbl[c5_long | c5_short].copy()
    s5["direction"] = np.where(c5_long.loc[s5.index], 1, -1)
    s5["stop_ref"] = m1130_rng.loc[s5.index] * 0.35
    run_and_summarize(s5, "11:30", "12:30", "5. Euro_Close_1130_Continuation")

    # 6. Pre-Settlement Final 45-Min Institutional Drive (12:45-13:29 GC / 13:45-14:29 CL)
    pset_rng = (tbl["pset_high"] - tbl["pset_low"]).replace(0, np.nan)
    pset_loc = (tbl["pset_close"] - tbl["pset_low"]) / pset_rng
    pset_ret = (tbl["pset_close"] - tbl["pset_open"]) / tbl["pset_open"]
    c6_long = (pset_ret >= min_ret * 1.5) & (pset_loc >= 0.75) & (tbl["pset_close"] > tbl["prior_vah"])
    c6_short = (pset_ret <= -min_ret * 1.5) & (pset_loc <= 0.25) & (tbl["pset_close"] < tbl["prior_val"])
    s6 = tbl[c6_long | c6_short].copy()
    s6["direction"] = np.where(c6_long.loc[s6.index], 1, -1)
    s6["stop_ref"] = pset_rng.loc[s6.index] * 0.30
    run_and_summarize(
        s6,
        "12:45" if sym == "GC" else "13:45",
        "13:29" if sym == "GC" else "14:29",
        "6a. Pre_Settlement_45m_Drive",
    )

    # 6b. Pre-Settlement Final 45-Min Profit-Taking Mean-Reversion Fade
    s6b = s6.copy()
    s6b["direction"] = -s6b["direction"]
    run_and_summarize(
        s6b,
        "12:45" if sym == "GC" else "13:45",
        "13:29" if sym == "GC" else "14:29",
        "6b. Pre_Settlement_45m_Fade",
    )

    return results


def main() -> int:
    df_cl = ensure_cl_parquet()
    df_gc = pd.read_parquet(ROOT / "data/raw/gc_1m_2020_2026_et.parquet")

    print("\nRunning 2020-2026 1-Minute Commodity Archetype Scan on Gold (GC / MGC)...")
    res_gc = evaluate_archetypes_for_asset(df_gc, "GC")

    print("Running 2020-2026 1-Minute Commodity Archetype Scan on Crude Oil (CL / MCL)...")
    res_cl = evaluate_archetypes_for_asset(df_cl, "CL")

    all_df = pd.DataFrame(res_gc + res_cl)

    print("\n=== GOLD (GC / MGC) 2020-2026 ARCHETYPE SCAN ===")
    print(all_df[all_df["sym"] == "GC"].to_string(index=False))

    print("\n=== CRUDE OIL (CL / MCL) 2020-2026 ARCHETYPE SCAN ===")
    print(all_df[all_df["sym"] == "CL"].to_string(index=False))

    out_csv = ROOT / "results/research_master/gc_cl_commodity_archetype_scan_2020_2026.csv"
    all_df.to_csv(out_csv, index=False)
    print(f"\nSaved full commodity archetype scan to {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
