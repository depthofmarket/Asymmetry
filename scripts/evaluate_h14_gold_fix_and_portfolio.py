#!/usr/bin/env python3
"""
Formal 1-Minute Point-in-Time Evaluation of Candidate H14:
Gold (GC / MGC) 10:15 ET Post-LBMA PM Fix Structural Breakout (2020-2026)
and Unified Multi-Asset Portfolio Comparison (MNQ + MES at 09:45 ET + MGC at 10:15 ET).
"""

from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.gold_london_fix_structural_breakout_signal import (
    GoldLondonFixBreakoutConfig,
    build_gold_london_fix_breakout_signal_export,
    build_gold_london_fix_breakout_signal_frame,
)
from scripts.convert_and_evaluate_multi_asset_cqg_2020_2026 import (
    CQG_EXPORTS,
    compute_daily_or15_dir,
    simulate_asset_trades,
    summarize_era,
)


def evaluate_h14_on_1m_gc(df_gc: pd.DataFrame, *, allow_short: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    df_2020 = df_gc[(df_gc["time"] >= "2020-01-01") & (df_gc["open"] > 0)].reset_index(drop=True)
    cfg = GoldLondonFixBreakoutConfig(allow_long=True, allow_short=allow_short)
    sig_frame = build_gold_london_fix_breakout_signal_frame(df_2020, config=cfg)

    if not allow_short:
        exp_path = (
            ROOT
            / "results/research_master/signal_research/gold_london_fix_structural_breakout_h14_signals.csv"
        )
        exp_path.parent.mkdir(parents=True, exist_ok=True)
        exp_df = build_gold_london_fix_breakout_signal_export(df_2020, config=cfg)
        exp_df[exp_df["candidate_signal"] != 0.0].to_csv(exp_path, index=False)
        print(f"Exported H14 active signals CSV to {exp_path}")

    active = sig_frame[sig_frame["candidate_signal"] != 0.0].copy()
    df_2020["date_str"] = df_2020["time"].dt.strftime("%Y-%m-%d")
    df_2020["hhmm"] = df_2020["time"].dt.strftime("%H:%M")

    win_bars = df_2020[(df_2020["hhmm"] >= "10:15") & (df_2020["hhmm"] <= "11:00")]
    bars_by_date = {d: g.reset_index(drop=True) for d, g in win_bars.groupby("date_str")}

    micro_pt_val = 10.0
    comm_rt = 1.50
    slip_pts = 0.20

    trades = []
    for _, srow in active.iterrows():
        sig_time = pd.Timestamp(srow["time"])
        d_str = sig_time.strftime("%Y-%m-%d")
        ebars = bars_by_date.get(d_str)
        if ebars is None or len(ebars) < 15:
            continue

        d = 1 if float(srow["candidate_signal"]) > 0 else -1
        entry_p = float(ebars.iloc[0]["open"])
        stop_pts = float(srow["stop_points"])
        target_pts = float(srow["target_points"])
        stop_price = entry_p - d * stop_pts
        target_price = entry_p + d * target_pts

        # Un-stopped multi-horizon returns (6m, 12m, 24m, 30m, 45m)
        def ret_at(k: int) -> float:
            idx = min(k - 1, len(ebars) - 1)
            return float((float(ebars.iloc[idx]["close"]) - entry_p) * d - slip_pts - 0.15)

        r6 = ret_at(6)
        r12 = ret_at(12)
        r24 = ret_at(24)
        r30 = ret_at(30)
        r45 = ret_at(45)

        exit_p = float(ebars.iloc[-1]["close"])
        exit_time = pd.Timestamp(ebars.iloc[-1]["time"])
        reason = "time_exit_1100"
        for _, b in ebars.iterrows():
            bh = float(b["high"])
            bl = float(b["low"])
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

        raw_pts = (exit_p - entry_p) * d
        net_pts = raw_pts - slip_pts
        contracts = int(np.clip(np.round(250.0 / max(stop_pts * micro_pt_val, 1.0)), 1, 4))
        net_dollars_micro = net_pts * micro_pt_val * contracts - (comm_rt * contracts)

        trades.append(
            {
                "date_str": d_str,
                "year": sig_time.year,
                "sym": "GC",
                "micro": "MGC",
                "asset": "Gold (GC / MGC 10:15 Fix)",
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
                "ret_6m_pts": r6,
                "ret_12m_pts": r12,
                "ret_24m_pts": r24,
                "ret_30m_pts": r30,
                "ret_45m_pts": r45,
            }
        )

    t_df = pd.DataFrame(trades)
    return t_df, sig_frame


def main() -> int:
    df_gc = pd.read_parquet(ROOT / "data/raw/gc_1m_2020_2026_et.parquet")
    df_es = pd.read_parquet(ROOT / "data/raw/es_1m_2020_2026_cqg_et.parquet")
    df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")

    t_long, _ = evaluate_h14_on_1m_gc(df_gc, allow_short=False)
    t_ls, _ = evaluate_h14_on_1m_gc(df_gc, allow_short=True)

    print("\n=== 1. H14 GOLD 10:15 ET POST-LBMA FIX BREAKOUT (EXACT 1M VOLUME PROFILE) ===")
    rows = []
    for mode_lbl, t_df in [("H14 Long-Only", t_long), ("H14 Long+Short", t_ls)]:
        for era_lbl, m in [
            ("2020-2026 (Full)", t_df["date_str"] >= "2020-01-01"),
            ("2021-2024 (Core)", (t_df["date_str"] >= "2021-01-01") & (t_df["date_str"] <= "2024-12-31")),
            ("2025-2026 (OOS)", t_df["date_str"] >= "2025-01-01"),
        ]:
            sub = t_df[m].reset_index(drop=True)
            s = summarize_era(sub, "Gold (GC / MGC)", "MGC", mode_lbl, era_lbl)
            s["mean_12m_pts"] = round(float(sub["ret_12m_pts"].mean()), 2) if not sub.empty else 0.0
            s["mean_30m_pts"] = round(float(sub["ret_30m_pts"].mean()), 2) if not sub.empty else 0.0
            s["mean_45m_pts"] = round(float(sub["ret_45m_pts"].mean()), 2) if not sub.empty else 0.0
            rows.append(s)
    h14_sum = pd.DataFrame(rows)
    print(h14_sum.to_string(index=False))

    # Build MNQ and MES 2021-2026 VIX+Intermarket Gated Trades for Portfolio Comparison
    m_df = pd.read_parquet(ROOT / "data/processed/macro_context/morning_cross_asset_features_0945.parquet")
    macro_map = {}
    for _, r in m_df.iterrows():
        vx_c = float(r["vx_or15_change_pct"]) if pd.notna(r.get("vx_or15_change_pct")) else (
            float(r["vix_spot_or15_change_pct"]) if pd.notna(r.get("vix_spot_or15_change_pct")) else float("nan")
        )
        tk_m = float(r["tick_or15_mean"]) if pd.notna(r.get("tick_or15_mean")) else float("nan")
        macro_map[str(r["date_str"])] = (vx_c, tk_m)

    v_1h_path = ROOT / "data/raw/vix_spot_1h_2026_et.csv"
    if v_1h_path.exists():
        v_1h = pd.read_csv(v_1h_path)
        v_1h["time"] = pd.to_datetime(v_1h["time"], utc=True).dt.tz_convert("America/New_York")
        v_1h["date_str"] = v_1h["time"].dt.strftime("%Y-%m-%d")
        v_1h["hhmm"] = v_1h["time"].dt.strftime("%H:%M")
        for d_str, g in v_1h.groupby("date_str"):
            if d_str not in macro_map or np.isnan(macro_map[d_str][0]):
                b9 = g[g["hhmm"] == "09:00"]
                if not b9.empty:
                    o, c = float(b9.iloc[0]["open"]), float(b9.iloc[-1]["close"])
                    macro_map[d_str] = ((c - o) / o * 100.0 if o > 0 else 0.0, float("nan"))

    v_5m_path = ROOT / "data/raw/vix_spot_5m_recent_et.csv"
    if v_5m_path.exists():
        v_5m = pd.read_csv(v_5m_path)
        v_5m["time"] = pd.to_datetime(v_5m["time"], utc=True).dt.tz_convert("America/New_York")
        v_5m["date_str"] = v_5m["time"].dt.strftime("%Y-%m-%d")
        v_5m["hhmm"] = v_5m["time"].dt.strftime("%H:%M")
        for d_str, g in v_5m.groupby("date_str"):
            w = g[(g["hhmm"] >= "09:30") & (g["hhmm"] <= "09:40")]
            if not w.empty:
                o, c = float(w.iloc[0]["open"]), float(w.iloc[-1]["close"])
                macro_map[d_str] = ((c - o) / o * 100.0 if o > 0 else 0.0, float("nan"))

    es_dir = compute_daily_or15_dir(df_es)
    nq_dir = compute_daily_or15_dir(df_nq)

    es_spec = next(x for x in CQG_EXPORTS if x["sym"] == "ES")
    nq_spec = next(x for x in CQG_EXPORTS if x["sym"] == "NQ")

    t_es = simulate_asset_trades(df_es, es_spec, require_with_gap=True, es_dir_map=es_dir, nq_dir_map=nq_dir, macro_map=macro_map)
    t_nq = simulate_asset_trades(df_nq, nq_spec, require_with_gap=True, es_dir_map=es_dir, nq_dir_map=nq_dir, macro_map=macro_map)

    t_es_g = t_es[t_es["full_gate_ok"] & (t_es["date_str"] >= "2021-01-01")].reset_index(drop=True)
    t_nq_g = t_nq[t_nq["full_gate_ok"] & (t_nq["date_str"] >= "2021-01-01")].reset_index(drop=True)
    t_gc_g = t_long[t_long["date_str"] >= "2021-01-01"].reset_index(drop=True)

    # Risk-capped 09:45 split (when both NQ and ES trigger on the same day, split 09:45 risk 50/50)
    both_dates = set(t_es_g["date_str"]).intersection(set(t_nq_g["date_str"]))
    t_es_split = t_es_g.copy()
    t_nq_split = t_nq_g.copy()
    t_es_split.loc[t_es_split["date_str"].isin(both_dates), "net_dollars_micro"] *= 0.5
    t_nq_split.loc[t_nq_split["date_str"].isin(both_dates), "net_dollars_micro"] *= 0.5

    print("\n=== 2. UNIFIED MULTI-ASSET PROP PORTFOLIO COMPARISON (2021-2026) ===")
    port_rows = []
    for p_name, p_df in [
        ("1. MNQ Alone (09:45 ET)", t_nq_g),
        ("2. MES Alone (09:45 ET)", t_es_g),
        ("3. Dual Equity Split-Risk: MNQ + MES (09:45 ET)", pd.concat([t_nq_split, t_es_split], ignore_index=True)),
        ("4. Tri-Asset Split-Risk: MNQ+MES (09:45) + MGC (10:15 H14)", pd.concat([t_nq_split, t_es_split, t_gc_g], ignore_index=True)),
        (
            "5. Tri-Asset Full-Size: MNQ + MES (09:45 ET) + MGC (10:15 ET H14)",
            pd.concat([t_nq_g, t_es_g, t_gc_g], ignore_index=True),
        ),
    ]:
        p_sorted = p_df.sort_values(["date_str", "entry_time"]).reset_index(drop=True)
        active_days = p_sorted["date_str"].nunique()
        wins = p_sorted["net_dollars_micro"] > 0
        pos = float(p_sorted.loc[wins, "net_dollars_micro"].sum())
        neg = float(abs(p_sorted.loc[~wins, "net_dollars_micro"].sum()))
        pf = pos / neg if neg > 0 else np.inf
        daily_pnl = p_sorted.groupby("date_str")["net_dollars_micro"].sum()
        cum = daily_pnl.cumsum()
        mdd = float((cum - cum.cummax()).min())
        port_rows.append(
            {
                "portfolio": p_name,
                "active_days": active_days,
                "total_trades": len(p_sorted),
                "trades_per_yr": round(len(p_sorted) / 5.83, 1),
                "win_rate_pct": round(float(wins.mean() * 100.0), 1),
                "profit_factor": round(pf, 2),
                "total_micro_pnl": round(float(p_sorted["net_dollars_micro"].sum()), 2),
                "daily_max_dd": round(mdd, 2),
                "pnl_to_dd_ratio": round(float(p_sorted["net_dollars_micro"].sum()) / max(abs(mdd), 1.0), 2),
            }
        )
    port_df = pd.DataFrame(port_rows)
    print(port_df.to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
