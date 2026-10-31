#!/usr/bin/env python3
"""
Multi-Asset Structural Opening Range + Prior Value Area Breakout Screening Scan
Across Gold (GC=F, 08:20 ET), Crude Oil (CL=F, 09:00 ET), Russell 2000 (RTY=F, 09:30 ET),
and Dow (YM=F, 09:30 ET), compared side-by-side with NQ=F and ES=F.

Includes:
1. 60-Day (5m) 15-Minute Opening Range + Prior Session Value Area Breakout (Unfiltered & Macro+ES Filtered)
2. 2-Year (730d, 1h) Opening-Hour + Prior Session Value Area Breakout (~500 sessions, 2024-2026)
3. Multi-Asset Prop Portfolio Combination (MNQ/MES Alone vs. Adding MGC 08:35 ET + MYM 09:45 ET)
"""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf


ASSET_SPECS = [
    {
        "name": "Gold (GC / MGC)",
        "ticker": "GC=F",
        "micro": "MGC",
        "rth_start": "08:20",
        "or_end": "08:30",  # 3x 5m bars: 08:20, 08:25, 08:30 (completes at 08:35 ET)
        "entry_time": "08:35",
        "rth_end": "13:30",
        "h1_open_hhmm": "08:00",
        "h1_entry_hhmm": "09:00",
        "min_ret_pct": 0.0008,  # 0.08% (~$2.20 on $2,750 Gold)
        "micro_pt_val": 10.0,   # MGC = $10 per $1.00 move ($1.00 per $0.10 tick)
        "cost_pts": 0.30,       # 3 ticks ($3.00/RT per MGC)
        "min_stop_pts": 2.5,
        "max_stop_pts": 15.0,
        "h1_max_stop_pts": 25.0,
    },
    {
        "name": "Crude Oil (CL / MCL)",
        "ticker": "CL=F",
        "micro": "MCL",
        "rth_start": "09:00",
        "or_end": "09:10",  # 3x 5m bars: 09:00, 09:05, 09:10 (completes at 09:15 ET)
        "entry_time": "09:15",
        "rth_end": "14:30",
        "h1_open_hhmm": "09:00",
        "h1_entry_hhmm": "10:00",
        "min_ret_pct": 0.0015,  # 0.15% (~$0.11 on $70 Crude)
        "micro_pt_val": 100.0,  # MCL = $100 per $1.00 move ($1.00 per $0.01 tick)
        "cost_pts": 0.03,       # 3 ticks ($3.00/RT per MCL)
        "min_stop_pts": 0.15,
        "max_stop_pts": 0.80,
        "h1_max_stop_pts": 1.50,
    },
    {
        "name": "Russell 2000 (RTY / M2K)",
        "ticker": "RTY=F",
        "micro": "M2K",
        "rth_start": "09:30",
        "or_end": "09:40",  # 3x 5m bars: 09:30, 09:35, 09:40 (completes at 09:45 ET)
        "entry_time": "09:45",
        "rth_end": "16:00",
        "h1_open_hhmm": "09:00",
        "h1_entry_hhmm": "10:00",
        "min_ret_pct": 0.0010,  # 0.10% (~2.2 pts on 2,200 RTY)
        "micro_pt_val": 5.0,    # M2K = $5.00 per 1.00 index point ($0.50 per 0.10 tick)
        "cost_pts": 0.40,       # 4 ticks ($2.00/RT per M2K)
        "min_stop_pts": 3.0,
        "max_stop_pts": 15.0,
        "h1_max_stop_pts": 25.0,
    },
    {
        "name": "Dow (YM / MYM)",
        "ticker": "YM=F",
        "micro": "MYM",
        "rth_start": "09:30",
        "or_end": "09:40",  # 09:30..09:45 ET
        "entry_time": "09:45",
        "rth_end": "16:00",
        "h1_open_hhmm": "09:00",
        "h1_entry_hhmm": "10:00",
        "min_ret_pct": 0.0008,  # 0.08% (~34 pts on 42,000 YM)
        "micro_pt_val": 0.50,   # MYM = $0.50 per 1.0 index point
        "cost_pts": 4.0,        # 4 pts ($2.00/RT per MYM)
        "min_stop_pts": 30.0,
        "max_stop_pts": 140.0,
        "h1_max_stop_pts": 220.0,
    },
    {
        "name": "Nasdaq-100 (NQ / MNQ)",
        "ticker": "NQ=F",
        "micro": "MNQ",
        "rth_start": "09:30",
        "or_end": "09:40",
        "entry_time": "09:45",
        "rth_end": "16:00",
        "h1_open_hhmm": "09:00",
        "h1_entry_hhmm": "10:00",
        "min_ret_pct": 0.0010,
        "micro_pt_val": 2.0,
        "cost_pts": 1.50,
        "min_stop_pts": 15.0,
        "max_stop_pts": 60.0,
        "h1_max_stop_pts": 110.0,
    },
    {
        "name": "S&P 500 (ES / MES)",
        "ticker": "ES=F",
        "micro": "MES",
        "rth_start": "09:30",
        "or_end": "09:40",
        "entry_time": "09:45",
        "rth_end": "16:00",
        "h1_open_hhmm": "09:00",
        "h1_entry_hhmm": "10:00",
        "min_ret_pct": 0.0010,
        "micro_pt_val": 5.0,
        "cost_pts": 0.50,
        "min_stop_pts": 5.0,
        "max_stop_pts": 25.0,
        "h1_max_stop_pts": 45.0,
    },
]


def compute_session_va(rth_bars: pd.DataFrame) -> tuple[float, float, float]:
    """Compute approximate prior session POC, VAH, VAL (70% volume area)."""
    if rth_bars.empty:
        return np.nan, np.nan, np.nan
    tp = (rth_bars["high"] + rth_bars["low"] + rth_bars["close"]) / 3.0
    vol = rth_bars["volume"].clip(lower=1.0)
    low_min = float(rth_bars["low"].min())
    high_max = float(rth_bars["high"].max())
    if high_max <= low_min:
        return low_min, high_max, low_min

    bins = np.linspace(low_min, high_max, 51)
    idx = np.clip(np.digitize(tp, bins) - 1, 0, 49)
    bin_vols = np.bincount(idx, weights=vol, minlength=50)
    bin_centers = 0.5 * (bins[:-1] + bins[1:])

    poc_idx = int(np.argmax(bin_vols))
    poc = float(bin_centers[poc_idx])
    total_vol = float(bin_vols.sum())
    target_vol = 0.70 * total_vol

    cum_vol = float(bin_vols[poc_idx])
    left = poc_idx
    right = poc_idx
    while cum_vol < target_vol and (left > 0 or right < 49):
        v_left = bin_vols[left - 1] if left > 0 else -1.0
        v_right = bin_vols[right + 1] if right < 49 else -1.0
        if v_right >= v_left:
            right += 1
            cum_vol += float(bin_vols[right])
        else:
            left -= 1
            cum_vol += float(bin_vols[left])

    val = float(bins[left])
    vah = float(bins[right + 1])
    return poc, vah, val


def fetch_yf_df(ticker: str, period: str, interval: str) -> pd.DataFrame:
    raw = yf.Ticker(ticker).history(period=period, interval=interval)
    if raw.empty:
        return pd.DataFrame()
    df = raw.tz_convert("America/New_York").reset_index()
    time_col = "Datetime" if "Datetime" in df.columns else "Date"
    df = df.rename(
        columns={
            time_col: "time",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )[["time", "open", "high", "low", "close", "volume"]]
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hhmm"] = df["time"].dt.strftime("%H:%M")
    return df


def summarize_trades(t_df: pd.DataFrame, spec: dict, sessions_scanned: int, label: str = "") -> dict:
    if t_df.empty:
        return {
            "asset": spec["name"],
            "micro": spec["micro"],
            "mode": label,
            "open_window_et": f"{spec['rth_start']}-{spec['entry_time']}",
            "sessions": sessions_scanned,
            "n_trades": 0,
            "freq_pct": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
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
        "asset": spec["name"],
        "micro": spec["micro"],
        "mode": label,
        "open_window_et": f"{spec['rth_start']}-{spec['entry_time']}",
        "sessions": sessions_scanned,
        "n_trades": len(t_df),
        "freq_pct": round(len(t_df) / max(sessions_scanned, 1) * 100.0, 1),
        "win_rate_pct": round(float(wins.mean() * 100.0), 1),
        "profit_factor": round(pf, 2),
        "mean_micro_pnl": round(float(t_df["net_dollars_micro"].mean()), 2),
        "total_micro_pnl": round(float(t_df["net_dollars_micro"].sum()), 2),
        "max_dd_micro": round(max_dd, 2),
    }


def evaluate_5m_opening_breakout(
    spec: dict,
    vix_5m: pd.DataFrame,
    es_5m: pd.DataFrame,
) -> tuple[dict, dict, pd.DataFrame, pd.DataFrame]:
    df = fetch_yf_df(spec["ticker"], period="60d", interval="5m")
    if df.empty:
        empty_s = summarize_trades(pd.DataFrame(), spec, 0, "Unfiltered")
        return empty_s, empty_s, pd.DataFrame(), pd.DataFrame()

    # Pre-compute daily VIX and ES 09:30-09:40 directional state
    vix_dir_map: dict[str, int] = {}
    if not vix_5m.empty:
        for d_str, g in vix_5m.groupby("date_str"):
            w = g[(g["hhmm"] >= "09:30") & (g["hhmm"] <= "09:40")]
            if not w.empty:
                vo = float(w.iloc[0]["open"])
                vc = float(w.iloc[-1]["close"])
                vix_dir_map[d_str] = 1 if vc > vo else (-1 if vc < vo else 0)

    es_dir_map: dict[str, int] = {}
    if not es_5m.empty:
        for d_str, g in es_5m.groupby("date_str"):
            w = g[(g["hhmm"] >= "09:30") & (g["hhmm"] <= "09:40")]
            if not w.empty:
                eo = float(w.iloc[0]["open"])
                ec = float(w.iloc[-1]["close"])
                es_dir_map[d_str] = 1 if ec > eo else (-1 if ec < eo else 0)

    dates = sorted(df["date_str"].unique())
    trades = []
    prior_va = (np.nan, np.nan, np.nan)

    for d_str in dates:
        day_df = df[df["date_str"] == d_str].reset_index(drop=True)
        rth_df = day_df[
            (day_df["hhmm"] >= spec["rth_start"]) & (day_df["hhmm"] <= spec["rth_end"])
        ].reset_index(drop=True)
        if len(rth_df) < 12:
            continue

        or_bars = rth_df[
            (rth_df["hhmm"] >= spec["rth_start"]) & (rth_df["hhmm"] <= spec["or_end"])
        ]
        post_bars = rth_df[rth_df["hhmm"] >= spec["entry_time"]].reset_index(drop=True)

        p_poc, p_vah, p_val = prior_va
        prior_va = compute_session_va(rth_df)

        if len(or_bars) < 2 or len(post_bars) < 6 or np.isnan(p_vah) or np.isnan(p_val):
            continue

        or_open = float(or_bars.iloc[0]["open"])
        or_close = float(or_bars.iloc[-1]["close"])
        or_high = float(or_bars["high"].max())
        or_low = float(or_bars["low"].min())
        or_range = or_high - or_low
        if or_range <= 0 or or_open <= 0:
            continue

        ret_pct = (or_close - or_open) / or_open
        close_loc = (or_close - or_low) / or_range

        is_long = (ret_pct >= spec["min_ret_pct"]) and (close_loc >= 0.65) and (or_close > p_vah)
        is_short = (ret_pct <= -spec["min_ret_pct"]) and (close_loc <= 0.35) and (or_close < p_val)
        if not is_long and not is_short:
            continue

        d = 1.0 if is_long else -1.0
        entry_p = float(post_bars.iloc[0]["open"])
        stop_pts = float(np.clip(or_range, spec["min_stop_pts"], spec["max_stop_pts"]))
        target_pts = stop_pts * 1.50

        eval_bars = post_bars.iloc[:6]
        outcome = "time_exit_30m"
        raw_pts = float(d * (float(eval_bars.iloc[-1]["close"]) - entry_p))
        for _, b in eval_bars.iterrows():
            bh = float(b["high"])
            bl = float(b["low"])
            stop_hit = (bl <= entry_p - stop_pts) if d > 0 else (bh >= entry_p + stop_pts)
            target_hit = (bh >= entry_p + target_pts) if d > 0 else (bl <= entry_p - target_pts)
            if stop_hit:
                outcome = "stop_loss"
                raw_pts = -stop_pts
                break
            if target_hit:
                outcome = "profit_target_150r"
                raw_pts = target_pts
                break

        net_pts = raw_pts - spec["cost_pts"]
        risk_dollars = 250.0
        contracts = int(np.clip(np.round(risk_dollars / max(stop_pts * spec["micro_pt_val"], 1.0)), 1, 4))
        net_dollars_micro = net_pts * spec["micro_pt_val"] * contracts

        # Check Macro + ES alignment for 09:45 ET equity index assets
        macro_aligned = True
        if spec["entry_time"] == "09:45":
            es_d = es_dir_map.get(d_str, 0)
            vix_d = vix_dir_map.get(d_str, 0)
            if d > 0:
                macro_aligned = (es_d >= 0) and (vix_d <= 0)
            else:
                macro_aligned = (es_d <= 0) and (vix_d >= 0)

        trades.append(
            {
                "date_str": d_str,
                "asset": spec["name"],
                "micro": spec["micro"],
                "entry_time": spec["entry_time"],
                "direction": "long" if d > 0 else "short",
                "entry_price": entry_p,
                "stop_pts": stop_pts,
                "target_pts": target_pts,
                "outcome": outcome,
                "net_pts": net_pts,
                "contracts": contracts,
                "net_dollars_micro": net_dollars_micro,
                "macro_aligned": macro_aligned,
            }
        )

    t_df = pd.DataFrame(trades)
    if t_df.empty:
        s_unf = summarize_trades(t_df, spec, len(dates), "Unfiltered")
        return s_unf, s_unf, t_df, t_df

    t_filt = t_df[t_df["macro_aligned"]].reset_index(drop=True)
    s_unf = summarize_trades(t_df, spec, len(dates), "Unfiltered")
    s_filt = summarize_trades(t_filt, spec, len(dates), "Macro+ES Filtered")
    return s_unf, s_filt, t_df, t_filt


def evaluate_2y_1h_opening_breakout(spec: dict) -> dict:
    """Evaluate 2-Year (730d, ~500 sessions) 1h Opening-Bar + Prior Session VA Breakout."""
    df = fetch_yf_df(spec["ticker"], period="730d", interval="1h")
    if df.empty:
        return summarize_trades(pd.DataFrame(), spec, 0, "2Y-1h")

    dates = sorted(df["date_str"].unique())
    trades = []
    prior_va = (np.nan, np.nan, np.nan)

    for d_str in dates:
        day_df = df[df["date_str"] == d_str].reset_index(drop=True)
        rth_df = day_df[
            (day_df["hhmm"] >= spec["h1_open_hhmm"]) & (day_df["hhmm"] <= spec["rth_end"])
        ].reset_index(drop=True)
        if len(rth_df) < 4:
            continue

        or_bars = rth_df[rth_df["hhmm"] == spec["h1_open_hhmm"]]
        post_bars = rth_df[rth_df["hhmm"] >= spec["h1_entry_hhmm"]].reset_index(drop=True)

        p_poc, p_vah, p_val = prior_va
        prior_va = compute_session_va(rth_df)

        if or_bars.empty or len(post_bars) < 2 or np.isnan(p_vah) or np.isnan(p_val):
            continue

        or_open = float(or_bars.iloc[0]["open"])
        or_close = float(or_bars.iloc[-1]["close"])
        or_high = float(or_bars["high"].max())
        or_low = float(or_bars["low"].min())
        or_range = or_high - or_low
        if or_range <= 0 or or_open <= 0:
            continue

        ret_pct = (or_close - or_open) / or_open
        close_loc = (or_close - or_low) / or_range

        is_long = (ret_pct >= spec["min_ret_pct"] * 1.25) and (close_loc >= 0.65) and (or_close > p_vah)
        is_short = (ret_pct <= -spec["min_ret_pct"] * 1.25) and (close_loc <= 0.35) and (or_close < p_val)
        if not is_long and not is_short:
            continue

        d = 1.0 if is_long else -1.0
        entry_p = float(post_bars.iloc[0]["open"])
        stop_pts = float(np.clip(or_range, spec["min_stop_pts"], spec["h1_max_stop_pts"]))
        target_pts = stop_pts * 1.50

        eval_bars = post_bars.iloc[:2]  # 2 hours forward
        outcome = "time_exit_2h"
        raw_pts = float(d * (float(eval_bars.iloc[-1]["close"]) - entry_p))
        for _, b in eval_bars.iterrows():
            bh = float(b["high"])
            bl = float(b["low"])
            stop_hit = (bl <= entry_p - stop_pts) if d > 0 else (bh >= entry_p + stop_pts)
            target_hit = (bh >= entry_p + target_pts) if d > 0 else (bl <= entry_p - target_pts)
            if stop_hit:
                outcome = "stop_loss"
                raw_pts = -stop_pts
                break
            if target_hit:
                outcome = "profit_target_150r"
                raw_pts = target_pts
                break

        net_pts = raw_pts - spec["cost_pts"]
        risk_dollars = 250.0
        contracts = int(np.clip(np.round(risk_dollars / max(stop_pts * spec["micro_pt_val"], 1.0)), 1, 4))
        net_dollars_micro = net_pts * spec["micro_pt_val"] * contracts

        trades.append(
            {
                "date_str": d_str,
                "asset": spec["name"],
                "micro": spec["micro"],
                "net_pts": net_pts,
                "net_dollars_micro": net_dollars_micro,
            }
        )

    t_df = pd.DataFrame(trades)
    return summarize_trades(t_df, spec, len(dates), "2Y-1h (2024-2026)")


def df_to_md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    rows = []
    for _, r in df.iterrows():
        rows.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join([header, sep] + rows)


def main() -> int:
    vix_5m = fetch_yf_df("^VIX", period="60d", interval="5m")
    es_5m = fetch_yf_df("ES=F", period="60d", interval="5m")

    unf_summaries = []
    filt_summaries = []
    h1_summaries = []
    all_unf_trades = []
    all_filt_trades = []

    for spec in ASSET_SPECS:
        s_unf, s_filt, t_unf, t_filt = evaluate_5m_opening_breakout(spec, vix_5m, es_5m)
        s_h1 = evaluate_2y_1h_opening_breakout(spec)
        unf_summaries.append(s_unf)
        filt_summaries.append(s_filt)
        h1_summaries.append(s_h1)
        if not t_unf.empty:
            all_unf_trades.append(t_unf)
        if not t_filt.empty:
            all_filt_trades.append(t_filt)

    df_unf = pd.DataFrame(unf_summaries)
    df_filt = pd.DataFrame(filt_summaries)
    df_h1 = pd.DataFrame(h1_summaries)

    print("\n=== 1. 60-DAY (5m) OPENING RANGE + PRIOR VA BREAKOUT: UNFILTERED ===")
    print(df_unf.to_string(index=False))

    print("\n=== 2. 60-DAY (5m) OPENING RANGE + PRIOR VA BREAKOUT: MACRO (^VIX) + ES FILTERED ===")
    print(df_filt.to_string(index=False))

    print("\n=== 3. 2-YEAR (730d, 1h, ~500 SESSIONS) OPENING-HOUR + PRIOR VA BREAKOUT ===")
    print(df_h1.to_string(index=False))

    if all_filt_trades:
        comb_filt = pd.concat(all_filt_trades, ignore_index=True)

        # Portfolio comparison:
        # A: MNQ + MES only (current setup)
        # B: MNQ + MES + MYM (09:45 ET) + MGC (08:35 ET)
        port_a = comb_filt[comb_filt["micro"].isin(["MNQ", "MES"])].sort_values(["date_str", "entry_time"])
        port_b = comb_filt[comb_filt["micro"].isin(["MNQ", "MES", "MYM", "MGC"])].sort_values(
            ["date_str", "entry_time"]
        )

        print("\n=== 4. PROP PORTFOLIO FREQUENCY & PNL IMPACT (60-DAY 5m MACRO-FILTERED) ===")
        for pname, pdf in [
            ("Current (MNQ + MES at 09:45 ET)", port_a),
            ("Expanded (MGC 08:35 ET + MNQ/MES/MYM 09:45 ET)", port_b),
        ]:
            active_days = pdf["date_str"].nunique()
            n_tr = len(pdf)
            wr = float((pdf["net_dollars_micro"] > 0).mean() * 100.0) if n_tr > 0 else 0.0
            pos = float(pdf.loc[pdf["net_dollars_micro"] > 0, "net_dollars_micro"].sum())
            neg = float(abs(pdf.loc[pdf["net_dollars_micro"] <= 0, "net_dollars_micro"].sum()))
            pf = pos / neg if neg > 0 else np.inf
            tot_pnl = float(pdf["net_dollars_micro"].sum())
            daily_pnl = pdf.groupby("date_str")["net_dollars_micro"].sum()
            cum = daily_pnl.cumsum()
            mdd = float((cum - cum.cummax()).min()) if not cum.empty else 0.0
            print(
                f"{pname}: Active Days={active_days}/59 ({active_days/59*100:.1f}%), "
                f"Total Trades={n_tr}, WR={wr:.1f}%, PF={pf:.2f}, "
                f"Total Micro PnL=${tot_pnl:,.2f}, Daily Max DD=${mdd:,.2f}"
            )

        out_path = Path("results/research_master/multi_asset_opening_breakout_scan.md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        md_lines = [
            "# Multi-Asset Opening Range + Prior Session Value Area Breakout Screening Scan",
            "",
            "## 1. 60-Day (5m) 15-Minute Opening Range + Prior VA Breakout (Unfiltered)",
            "",
            df_to_md(df_unf),
            "",
            "## 2. 60-Day (5m) 15-Minute Opening Range + Prior VA Breakout (Macro `^VIX` + `ES` Filtered)",
            "",
            df_to_md(df_filt),
            "",
            "## 3. 2-Year (730d, 1h, ~500 Sessions) Multi-Year Opening-Hour + Prior VA Breakout (`2024-2026`)",
            "",
            df_to_md(df_h1),
            "",
        ]
        out_path.write_text("\n".join(md_lines))
        print(f"\nSaved markdown report to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
