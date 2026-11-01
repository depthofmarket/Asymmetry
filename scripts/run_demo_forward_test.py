#!/usr/bin/env python3
"""
Live / Demo Forward Test Runner & Tri-Asset Execution Card Generator for LucidFlex 25K.

Supports Two Non-Overlapping Institutional Windows:
1. Window 1 (09:45:00 ET — Strategy 1 / H4):
   - Dual-Asset Equity Opening Range + Prior RTH Value Area Breakout on MNQ & MES.
   - Requires NQ + ES 09:30-09:44 Intermarket Alignment + VIX Macro Gate (Compression for Long, Expansion for Short).
   - Automatically splits contract allocation when both MNQ & MES trigger simultaneously to cap combined 09:45 risk.
2. Window 2 (10:15:00 ET — Strategy 2 / H14):
   - Gold (MGC / GC=F) Post-LBMA PM Fix Structural Breakout (Long-Only, 10:15-11:00 ET).
   - Evaluates 10:00-10:14 ET LBMA Fix breakout above COMEX IB60 High (08:20-09:19),
     London Session High (03:00-08:19), and Prior Session RTH VAH (08:20-13:30).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from io import StringIO
from pathlib import Path
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.demo_parity_engine import (
    DAILY_SOFT_STOP_DOLLARS,
    STARTING_CAPITAL,
    TARGET_BALANCE,
    AccountEvalState,
    DailySessionRecord,
    DemoParityJournal,
    TradeFillRecord,
)
from backtest.poc_rejection_signal import _compute_prior_session_profiles


def fetch_live_morning_bars(ticker: str, period: str = "5d") -> pd.DataFrame:
    """Fetch 1-min intraday bars from yfinance and convert to America/New_York."""
    import yfinance as yf
    t = yf.Ticker(ticker)
    df = t.history(period=period, interval="1m")
    if df.empty:
        return pd.DataFrame()
    df = df.tz_convert("America/New_York").reset_index()
    col_map = {
        "Datetime": "time",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df = df.rename(columns=col_map)[["time", "open", "high", "low", "close", "volume"]]
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
    return df


def load_asset_bars_priority(
    sym: str,
    yf_ticker: str,
    local_parquet: Path,
    cqg_csv: Path | None = None,
) -> pd.DataFrame:
    """
    Loads intraday 1m bars prioritizing zero-delay local CQG CSV exports from MotiveWave / AMP.
    Falls back to converted parquet archive.
    Yahoo Finance is queried only as a tertiary emergency fallback with an explicit delay warning.
    """
    if cqg_csv and cqg_csv.exists():
        try:
            res = subprocess.run(
                ["tail", "-n", "8000", str(cqg_csv)],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if res.stdout.strip():
                df_cqg = pd.read_csv(
                    StringIO(res.stdout),
                    names=["dt_str", "open", "high", "low", "close", "volume"],
                )
                df_cqg["time"] = pd.to_datetime(df_cqg["dt_str"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
                df_cqg = df_cqg.dropna(subset=["time"]).drop(columns=["dt_str"]).reset_index(drop=True)
                if not df_cqg.empty:
                    return df_cqg
        except Exception:
            pass

    if local_parquet.exists():
        try:
            df_pq = pd.read_parquet(local_parquet)
            if not df_pq.empty:
                return df_pq.tail(8000).reset_index(drop=True)
        except Exception:
            pass

    print(f"[DATA WARNING] Fetching {yf_ticker} from Yahoo Finance. Free CME futures data on Yahoo Finance is delayed by 10-15 minutes!")
    return fetch_live_morning_bars(yf_ticker, period="5d")


def compute_prior_va_for_latest_session(
    bars: pd.DataFrame,
    rth_start: str,
    rth_end: str,
    bin_size: float,
) -> tuple[float, float, float, float]:
    """Return (prior_poc, prior_vah, prior_val, prior_close) for the latest session in bars."""
    if bars.empty:
        return np.nan, np.nan, np.nan, np.nan
    hhmm = bars["time"].dt.strftime("%H:%M")
    rth = bars[(hhmm >= rth_start) & (hhmm <= rth_end)].copy()
    if rth.empty:
        return np.nan, np.nan, np.nan, np.nan
    profs = _compute_prior_session_profiles(rth, bin_size=bin_size, value_area_pct=0.70)
    prior_closes = rth.groupby(rth["time"].dt.date, sort=True)["close"].last().shift(1)
    latest_date = bars["time"].dt.date.max()
    profs_idx = profs.set_index("session")
    if latest_date not in profs_idx.index:
        return np.nan, np.nan, np.nan, np.nan
    row = profs_idx.loc[latest_date]
    p_close = float(prior_closes.get(latest_date, np.nan))
    return float(row["prior_poc"]), float(row["prior_vah"]), float(row["prior_val"]), p_close


def get_daily_markov_regime(symbol: str, date_str: str) -> dict | None:
    """Return point-in-time daily Markov regime features for session date_str."""
    mkv_path = REPO_ROOT / f"data/processed/{symbol.lower()}_daily_markov_regimes_2020_2026.parquet"
    if not mkv_path.exists():
        # Fallback to NQ if ES or GC not found
        mkv_path = REPO_ROOT / "data/processed/nq_daily_markov_regimes_2020_2026.parquet"
        if not mkv_path.exists():
            return None
    try:
        df_m = pd.read_parquet(mkv_path)
        match = df_m[df_m["date_str"] == date_str]
        if not match.empty:
            r = match.iloc[0]
            return {
                "state": int(r["markov_state"]),
                "label": str(r["markov_state_label"]),
                "conf": float(r["markov_state_confidence"]),
                "p_low": float(r["markov_prob_low_vol"]),
                "p_mid": float(r["markov_prob_mid_vol"]),
                "p_high": float(r["markov_prob_high_vol"]),
            }
        past = df_m[df_m["date_str"] < date_str]
        if not past.empty:
            r = past.iloc[-1]
            return {
                "state": int(r["markov_state"]),
                "label": str(r["markov_state_label"]),
                "conf": float(r["markov_state_confidence"]),
                "p_low": float(r["markov_prob_low_vol"]),
                "p_mid": float(r["markov_prob_mid_vol"]),
                "p_high": float(r["markov_prob_high_vol"]),
            }
    except Exception:
        pass
    return None


def get_or15_direction(bars: pd.DataFrame) -> int:
    if bars.empty:
        return 0
    latest_date = bars["time"].dt.strftime("%Y-%m-%d").max()
    df_today = bars[bars["time"].dt.strftime("%Y-%m-%d") == latest_date]
    m15 = df_today[df_today["time"].dt.strftime("%H:%M").between("09:30", "09:44")]
    if m15.empty:
        return 0
    o = float(m15.iloc[0]["open"])
    c = float(m15.iloc[-1]["close"])
    return 1 if c > o else (-1 if c < o else 0)


def evaluate_signal_for_asset(
    bars: pd.DataFrame,
    symbol: str,
    vix_chg_pct: float | None,
    other_index_dir: int | None = None,
    tick_val: float | None = None,
) -> dict | None:
    """Evaluate 09:30-09:44 Strategy 1 (H4) breakout, Prior VA escape, Intermarket, and VIX gate for NQ or ES."""
    if bars.empty:
        return None

    latest_date = bars["time"].dt.strftime("%Y-%m-%d").max()
    df_today = bars[bars["time"].dt.strftime("%Y-%m-%d") == latest_date].copy()
    df_today["time_et"] = df_today["time"].dt.strftime("%H:%M")
    m15 = df_today[df_today["time_et"].between("09:30", "09:44")].copy()
    if len(m15) < 10:
        return None

    bin_size = 1.0 if symbol == "NQ" else 0.5
    p_poc, p_vah, p_val, p_close = compute_prior_va_for_latest_session(bars, "09:30", "16:00", bin_size)

    open_930 = float(m15.iloc[0]["open"])
    close_944 = float(m15.iloc[-1]["close"])
    high_15 = float(m15["high"].max())
    low_15 = float(m15["low"].min())
    range_pts = high_15 - low_15
    ret_pct = (close_944 - open_930) / open_930
    close_loc = (close_944 - low_15) / range_pts if range_pts > 0 else 0.5

    va_long_ok = True if np.isnan(p_vah) else (close_944 > p_vah)
    va_short_ok = True if np.isnan(p_val) else (close_944 < p_val)
    gap_long_ok = True if np.isnan(p_close) else (open_930 > p_close)
    gap_short_ok = True if np.isnan(p_close) else (open_930 < p_close)

    is_long = (ret_pct >= 0.0010) and (close_loc >= 0.65) and va_long_ok and gap_long_ok
    is_short = (ret_pct <= -0.0010) and (close_loc <= 0.35) and va_short_ok and gap_short_ok

    if not is_long and not is_short:
        return None

    direction = "long" if is_long else "short"
    d_int = 1 if is_long else -1

    macro_pass = True
    macro_reason = []

    if other_index_dir is not None and other_index_dir != 0:
        if d_int != other_index_dir:
            macro_pass = False
            macro_reason.append("Intermarket divergence (NQ vs ES disagreed)")
        else:
            macro_reason.append("Intermarket aligned (NQ + ES agreed)")

    if vix_chg_pct is not None:
        if direction == "long" and vix_chg_pct > 0.0:
            macro_pass = False
            macro_reason.append(f"VIX expanding (+{vix_chg_pct:.2f}% > 0.0%)")
        elif direction == "short" and vix_chg_pct < 0.0:
            macro_pass = False
            macro_reason.append(f"VIX compressing ({vix_chg_pct:.2f}% < 0.0%)")
        else:
            macro_reason.append(f"VIX gate passed ({vix_chg_pct:+.2f}%)")
    else:
        macro_reason.append("VIX data neutral/missing")

    if tick_val is not None:
        if direction == "long" and tick_val > 100.0:
            macro_pass = False
            macro_reason.append(f"TICK exhausted (+{tick_val:.0f} > +100)")
        elif direction == "short" and tick_val < -100.0:
            macro_pass = False
            macro_reason.append(f"TICK oversold ({tick_val:.0f} < -100)")

    # GARCH MVT Statistical Gate (AntiAchismo)
    mvt_info = None
    try:
        from backtest.garch_volatility import compute_mvt_envelope_at_bar, evaluate_garch_mvt_filter
        cond_vol = 1.25
        garch_p = REPO_ROOT / f"data/processed/{symbol.lower()}_daily_garch_forecasts_2020_2026.parquet"
        if garch_p.exists():
            df_g = pd.read_parquet(garch_p)
            match = df_g[df_g["date_str"] == str(latest_date)]
            if not match.empty:
                cond_vol = float(match.iloc[0]["garch_cond_vol_pct"])
            else:
                cond_vol = float(df_g.iloc[-1]["garch_cond_vol_pct"])

        mvt = compute_mvt_envelope_at_bar(m15, cond_daily_vol_pct=cond_vol, intraday_window_minutes=15.0)
        mvt_eval = evaluate_garch_mvt_filter(close_944, mvt, direction=d_int)
        mvt_info = {
            "mvt_0": mvt["mvt_0"],
            "sigma_pts": mvt["sigma_intraday_pts"],
            "z_score": mvt_eval["z_score"],
            "status": mvt_eval["status"],
            "reason": mvt_eval["reason"],
            "dp_target": mvt["dp_pos_2"] if d_int == 1 else mvt["dp_neg_2"],
        }
        if mvt_eval["is_exhausted"]:
            macro_pass = False
            macro_reason.append(f"GARCH Exhaustion: {mvt_eval['reason']}")
        elif not mvt_eval["is_sweet_spot"]:
            macro_reason.append(f"GARCH Gate: {mvt_eval['status']} ({mvt_eval['z_score']:.2f} DP)")
        else:
            macro_reason.append(f"GARCH Sweet-Spot ({mvt_eval['z_score']:.2f} DP)")
    except Exception as e:
        macro_reason.append(f"GARCH check skipped: {e}")

    if symbol == "NQ":
        min_stop, max_stop = 15.0, 60.0
        contract_symbol = "MNQ"
        point_value = 2.00
    else:
        min_stop, max_stop = 5.0, 35.0
        contract_symbol = "MES"
        point_value = 5.00

    markov_info = get_daily_markov_regime(symbol, str(latest_date))
    markov_mult = 1.00
    sizing_label = "1.00x Baseline"
    if markov_info:
        macro_reason.append(f"Markov Regime: {markov_info['label'].upper()} ({markov_info['conf']:.0%})")
        if markov_info["label"] == "low_vol":
            markov_mult = 1.25
            sizing_label = "1.25x Edge Expansion (Low-Vol)"
        else:
            sizing_label = f"1.00x Baseline ({markov_info['label'].upper()})"

    stop_pts = min(max_stop, max(min_stop, range_pts))
    entry_price = close_944
    stop_price = entry_price - d_int * stop_pts
    target_price = entry_price + d_int * (stop_pts * 1.5)

    return {
        "date_str": str(latest_date),
        "window_label": "09:45:00 ET (Strategy 1 — Equity Opening VA Breakout)",
        "exit_time_rule": "HARD FLATTEN AT 10:15:00 ET (30-min holding limit)",
        "symbol": symbol,
        "contract": contract_symbol,
        "direction": direction,
        "action": "BUY" if direction == "long" else "SELL",
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "stop_points": stop_pts,
        "point_value": point_value,
        "macro_pass": macro_pass,
        "macro_reason": " | ".join(macro_reason),
        "ret_pct": ret_pct,
        "close_loc": close_loc,
        "mvt_info": mvt_info,
        "markov_info": markov_info,
        "markov_mult": markov_mult,
        "sizing_label": sizing_label,
    }


def evaluate_gold_h14_signal(bars_gc: pd.DataFrame) -> dict | None:
    """Evaluate 10:00-10:14 ET Gold (MGC) Post-LBMA PM Fix Structural Breakout (H14, Long-Only)."""
    if bars_gc.empty:
        return None

    latest_date = bars_gc["time"].dt.strftime("%Y-%m-%d").max()
    df_today = bars_gc[bars_gc["time"].dt.strftime("%Y-%m-%d") == latest_date].copy()
    df_today["time_et"] = df_today["time"].dt.strftime("%H:%M")

    fix_bars = df_today[df_today["time_et"].between("10:00", "10:14")]
    ib_bars = df_today[df_today["time_et"].between("08:20", "09:19")]
    lon_bars = df_today[df_today["time_et"].between("03:00", "08:19")]
    if len(fix_bars) < 10 or ib_bars.empty:
        return None

    _, p_vah, _, _ = compute_prior_va_for_latest_session(bars_gc, "08:20", "13:30", 0.50)

    fix_open = float(fix_bars.iloc[0]["open"])
    fix_close = float(fix_bars.iloc[-1]["close"])
    fix_high = float(fix_bars["high"].max())
    fix_low = float(fix_bars["low"].min())
    fix_rng = fix_high - fix_low
    if fix_rng <= 0 or fix_open <= 0:
        return None

    ret_pct = (fix_close - fix_open) / fix_open
    close_loc = (fix_close - fix_low) / fix_rng
    ib60_high = float(ib_bars["high"].max())
    lon_high = float(lon_bars["high"].max()) if not lon_bars.empty else ib60_high

    va_ok = True if np.isnan(p_vah) else (fix_close > p_vah)
    is_long = (
        (ret_pct >= 0.001125)
        and (close_loc >= 0.70)
        and (fix_close > ib60_high)
        and (fix_close > lon_high)
        and va_ok
    )
    if not is_long:
        return None

    stop_pts = float(np.clip(fix_rng, 3.0, 18.0))
    entry_price = fix_close
    stop_price = entry_price - stop_pts
    target_price = entry_price + stop_pts * 1.50

    markov_info = get_daily_markov_regime("NQ", str(latest_date))
    markov_mult = 1.00
    sizing_label = "1.00x Baseline"
    macro_reason = f"Above IB60 ({ib60_high:.1f}), London High ({lon_high:.1f}) & Prior VAH ({p_vah:.1f})"
    if markov_info:
        macro_reason += f" | Markov: {markov_info['label'].upper()} ({markov_info['conf']:.0%})"
        if markov_info["label"] == "low_vol":
            markov_mult = 1.25
            sizing_label = "1.25x Edge Expansion (Low-Vol)"
        else:
            sizing_label = f"1.00x Baseline ({markov_info['label'].upper()})"

    return {
        "date_str": str(latest_date),
        "window_label": "10:15:00 ET (Strategy 2 / H14 — Gold Post-LBMA Fix Breakout)",
        "exit_time_rule": "HARD FLATTEN AT 11:00:00 ET (45-min holding limit)",
        "symbol": "GC",
        "contract": "MGC",
        "direction": "long",
        "action": "BUY",
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "stop_points": stop_pts,
        "point_value": 10.00,
        "macro_pass": True,
        "macro_reason": macro_reason,
        "ret_pct": ret_pct,
        "close_loc": close_loc,
        "mvt_info": mvt_info,
        "markov_info": markov_info,
        "markov_mult": markov_mult,
        "sizing_label": sizing_label,
    }


def evaluate_macro_momentum_signal(bars_nq: pd.DataFrame) -> dict | None:
    """Evaluate 08:35 ET Pre-Market Macro Release Momentum on MNQ (Strategy 3 / H17)."""
    if bars_nq.empty:
        return None

    latest_date = bars_nq["time"].dt.strftime("%Y-%m-%d").max()
    df_today = bars_nq[bars_nq["time"].dt.strftime("%Y-%m-%d") == latest_date].copy()
    df_today["time_et"] = df_today["time"].dt.strftime("%H:%M")

    ovn_bars = df_today[df_today["time_et"].between("00:00", "08:29")]
    spike_bars = df_today[df_today["time_et"].between("08:30", "08:34")]
    if len(ovn_bars) < 30 or len(spike_bars) < 4:
        return None

    ovn_high = float(ovn_bars["high"].max())
    ovn_low = float(ovn_bars["low"].min())
    if ovn_high <= ovn_low:
        return None

    spike_vol = float(spike_bars["volume"].sum())
    pre_vol_5m = float(ovn_bars["volume"].tail(30).mean() * 5.0) if len(ovn_bars) >= 10 else 1.0
    if spike_vol < pre_vol_5m * 2.5:
        return None

    spike_open = float(spike_bars.iloc[0]["open"])
    spike_close = float(spike_bars.iloc[-1]["close"])
    spike_high = float(spike_bars["high"].max())
    spike_low = float(spike_bars["low"].min())
    spike_rng = spike_high - spike_low
    if spike_rng <= 0:
        return None

    cl_loc = (spike_close - spike_low) / spike_rng

    direction = 0
    if spike_close > ovn_high and cl_loc >= 0.65:
        direction = 1
    elif spike_close < ovn_low and cl_loc <= 0.35:
        direction = -1

    if direction == 0:
        return None

    stop_pts = float(np.clip(spike_rng * 0.50, 20.0, 50.0))
    entry_price = spike_close
    stop_price = entry_price - direction * stop_pts
    target_price = entry_price + direction * (stop_pts * 1.50)

    markov_info = get_daily_markov_regime("NQ", str(latest_date))
    macro_pass = True
    macro_reasons = [f"High-Impact Macro Release Spike ({spike_vol:.0f} vs {pre_vol_5m:.0f} vol) breaking {'Overnight High' if direction==1 else 'Overnight Low'}"]
    markov_mult = 1.00
    sizing_label = "1.00x Baseline"
    if markov_info:
        macro_reasons.append(f"Markov Regime: {markov_info['label'].upper()} ({markov_info['conf']:.0%})")
        if markov_info["label"] == "high_vol":
            markov_mult = 0.50
            sizing_label = "0.50x Defensive Halving (High-Vol Whipsaw Defense)"
            macro_reasons.append("Option 2 Adaptive Sizing: 0.50x Contracts")
        elif markov_info["label"] == "low_vol":
            markov_mult = 1.25
            sizing_label = "1.25x Edge Expansion (Low-Vol Smooth Trend)"
            macro_reasons.append("Option 2 Adaptive Sizing: 1.25x Contracts")
        else:
            sizing_label = "1.00x Baseline (Mid-Vol Balanced)"
            macro_reasons.append("Option 2 Adaptive Sizing: 1.00x Contracts")

    return {
        "date_str": str(latest_date),
        "window_label": "08:35:00 ET (Strategy 3 / H17 — Pre-Market Macro Momentum)",
        "exit_time_rule": "HARD FLATTEN AT 09:25:00 ET (Pre-Market cash open exit)",
        "symbol": "NQ",
        "contract": "MNQ",
        "direction": "long" if direction == 1 else "short",
        "action": "BUY" if direction == 1 else "SELL",
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "stop_points": stop_pts,
        "point_value": 2.00,
        "macro_pass": macro_pass,
        "macro_reason": " | ".join(macro_reasons),
        "ret_pct": (spike_close - spike_open) / spike_open,
        "close_loc": cl_loc,
        "markov_info": markov_info,
        "markov_mult": markov_mult,
        "sizing_label": sizing_label,
    }


def print_execution_card(sig: dict, eval_state: AccountEvalState, contracts: int, tier_label: str) -> None:
    """Print the order execution card."""
    risk_dollars = sig["stop_points"] * sig["point_value"] * contracts
    reward_dollars = sig["stop_points"] * 1.5 * sig["point_value"] * contracts

    print("\n" + "=" * 72)
    print(f"  LUCID 25K EXECUTION CARD  ({sig['date_str']} @ {sig['window_label']})")
    print("=" * 72)
    print(f"  AccountBalance:    ${eval_state.balance:,.2f}  (Profit: ${eval_state.profit:+,.2f})")
    print(f"  Profit Target:     ${TARGET_BALANCE:,.2f}  (Distance: ${eval_state.distance_to_target:,.2f})")
    print(f"  Trailing Floor:    ${eval_state.trailing_floor:,.2f}  (Buffer: ${eval_state.trailing_cushion:,.2f})")
    print(f"  Daily Soft Stop:   ${eval_state.current_date_pnl:+,.2f} / ${DAILY_SOFT_STOP_DOLLARS:,.2f}")
    print(f"  Sizing Ratchet:    {tier_label}")
    print("-" * 72)
    print(f"  INSTRUMENT:        {sig['contract']}  (Micro {sig['symbol']})")
    print(f"  ACTION:            {sig['action']} ({sig['direction'].upper()} BREAKOUT)")
    print(f"  QUANTITY:          {contracts} Contract(s)")
    print(f"  EST. ENTRY PRICE:  {sig['entry_price']:.2f}")
    print(f"  HARD STOP LOSS:    {sig['stop_price']:.2f}  ({sig['stop_points']:.2f} pts | -${risk_dollars:,.2f} max risk)")
    print(f"  PROFIT TARGET:     {sig['target_price']:.2f}  ({sig['stop_points']*1.5:.2f} pts | +${reward_dollars:,.2f})")
    print(f"  TIME-EXIT RULE:    {sig['exit_time_rule']}")
    if sig.get("mvt_info"):
        m = sig["mvt_info"]
        print(f"  GARCH MVT ANCHOR:  {m['mvt_0']:.2f}  (15m Sigma: ±{m['sigma_pts']:.1f} pts | 2.0 DP Target: {m['dp_target']:.2f})")
        print(f"  GARCH EXTENSION:   {m['z_score']:+.2f} DP  [{m['status']}]")
    if sig.get("markov_info"):
        mkv = sig["markov_info"]
        print(f"  MARKOV REGIME:     {mkv['label'].upper()}  (Confidence: {mkv['conf']:.0%} | P[low]={mkv['p_low']:.2f}, P[mid]={mkv['p_mid']:.2f}, P[high]={mkv['p_high']:.2f})")
    if sig.get("markov_mult"):
        print(f"  MARKOV SIZING:     {sig['markov_mult']:.2f}x  [{sig.get('sizing_label', '')}]")
    print("-" * 72)
    gate_status = "PASSED" if sig["macro_pass"] else "BLOCKED (FILTER GATE ACTIVE)"
    print(f"  STRUCTURAL GATE:   {gate_status}")
    print(f"  GATE DETAILS:      {sig['macro_reason']}")
    print("=" * 72 + "\n")


def record_trade_prompt(sig: dict, contracts: int, journal: DemoParityJournal) -> None:
    """Prompt the user to record actual demo fills into the unified parity journal."""
    print("Would you like to record a completed trade into the demo forward ledger? (y/n)")
    choice = input("> ").strip().lower()
    if choice != "y":
        print("Signal displayed. No trade recorded to ledger.")
        return

    print(f"Enter actual Fill Price (or press Enter for est {sig['entry_price']:.2f}):")
    fill_input = input("> ").strip()
    fill_price = float(fill_input) if fill_input else sig["entry_price"]

    print("Select Exit Rule:")
    print("  [1] PROFIT_TARGET_1_5R")
    print("  [2] STOP_LOSS")
    print("  [3] TIME_EXIT_1015")
    print("  [4] NEWS_GUARD_0959")
    print("  [5] MANUAL")
    ex_choice = input("Select [1]: ").strip() or "1"
    ex_map = {
        "1": "PROFIT_TARGET_1_5R",
        "2": "STOP_LOSS",
        "3": "TIME_EXIT_1015",
        "4": "NEWS_GUARD_0959",
        "5": "MANUAL",
    }
    exit_type = ex_map.get(ex_choice, "PROFIT_TARGET_1_5R")

    default_exit = (
        sig["target_price"]
        if exit_type == "PROFIT_TARGET_1_5R"
        else (sig["stop_price"] if exit_type == "STOP_LOSS" else fill_price)
    )
    print(f"Enter actual Exit Price (or press Enter for {default_exit:.2f}):")
    exit_input = input("> ").strip()
    exit_price = float(exit_input) if exit_input else default_exit

    rec = TradeFillRecord(
        date=sig["date_str"],
        symbol=sig["contract"],
        direction="LONG" if sig["direction"] == "long" else "SHORT",
        contracts=contracts,
        theo_entry_price=sig["entry_price"],
        actual_entry_fill=fill_price,
        theo_stop_price=sig["stop_price"],
        theo_target_price=sig["target_price"],
        exit_type=exit_type,
        actual_exit_fill=exit_price,
    )
    new_state = journal.record_trade(rec)
    print(
        f"\n[OK] Trade recorded in Demo Parity Journal! Net PnL: ${rec.net_pnl:+,.2f}. Updated Balance: ${new_state.balance:,.2f}"
    )
    print(f"Interactive Dashboard updated at: {journal.dashboard_html_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Live / Demo Forward Test Runner (MNQ + MES @ 09:45, MGC @ 10:15)")
    parser.add_argument("--interactive", action="store_true", help="Prompt to record fill and exit into ledger")
    args = parser.parse_args()

    journal = DemoParityJournal()
    eval_state = journal.get_eval_state()
    base_contracts = eval_state.recommended_micros
    tier_label = eval_state.recommended_tier

    print("Loading morning 1m bars (prioritizing real-time MotiveWave CQG feed)...")
    try:
        bars_nq = load_asset_bars_priority(
            "NQ",
            "NQ=F",
            REPO_ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet",
            cqg_csv=REPO_ROOT / "data/raw/@NQ.CQG_1.csv",
        )
        bars_es = load_asset_bars_priority(
            "ES",
            "ES=F",
            REPO_ROOT / "data/raw/es_1m_2020_2026_cqg_et.parquet",
            cqg_csv=REPO_ROOT / "data/raw/@ES.CQG_1.csv",
        )
        bars_gc = load_asset_bars_priority(
            "GC",
            "GC=F",
            REPO_ROOT / "data/raw/gc_1m_2020_2026_et.parquet",
            cqg_csv=REPO_ROOT / "data/raw/@GC.CQG_1.csv",
        )
        bars_vix = fetch_live_morning_bars("^VIX", period="2d")
    except Exception as exc:
        print(f"Error loading morning data: {exc}")
        return 1

    vix_chg = None
    if not bars_vix.empty:
        today_vix = bars_vix[bars_vix["time"].dt.strftime("%H:%M").between("09:30", "09:44")]
        if not today_vix.empty:
            v_open = float(today_vix.iloc[0]["open"])
            v_close = float(today_vix.iloc[-1]["close"])
            vix_chg = (v_close - v_open) / v_open * 100.0

    nq_dir = get_or15_direction(bars_nq)
    es_dir = get_or15_direction(bars_es)

    sig_macro = evaluate_macro_momentum_signal(bars_nq)
    sig_nq = evaluate_signal_for_asset(bars_nq, "NQ", vix_chg, other_index_dir=es_dir)
    sig_es = evaluate_signal_for_asset(bars_es, "ES", vix_chg, other_index_dir=nq_dir)
    sig_gc = evaluate_gold_h14_signal(bars_gc)

    eq_signals = [s for s in [sig_nq, sig_es] if s is not None]
    both_eq_passed = len([s for s in eq_signals if s["macro_pass"]]) == 2

    print("\n--- DAILY MULTI-STRATEGY ENSEMBLE SIGNAL SCAN ---")
    print(f"  [08:35 ET] MNQ (Strategy 3 / Macro): {'SIGNAL FIRED' if sig_macro else 'NO SIGNAL'}")
    print(f"  [09:45 ET] MNQ (Strategy 1 / Cash):  {'SIGNAL FIRED' if sig_nq else 'NO SIGNAL'}")
    print(f"  [09:45 ET] MES (Strategy 1 / Cash):  {'SIGNAL FIRED' if sig_es else 'NO SIGNAL'}")
    print(f"  [10:15 ET] MGC (Strategy 2 / Fix):   {'SIGNAL FIRED' if sig_gc else 'NO SIGNAL'}")
    print("--------------------------------------------------")

    all_signals = ([sig_macro] if sig_macro is not None else []) + eq_signals + ([sig_gc] if sig_gc is not None else [])

    if not all_signals:
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(
            "\n[NO SIGNAL TODAY] None of 08:35 ET (Macro), 09:45 ET (Cash VA), or 10:15 ET (Fix) met breakout criteria."
        )
        print(f"Account Balance: ${eval_state.balance:,.2f} | Trailing Floor: ${eval_state.trailing_floor:,.2f}")
        journal.record_session(
            DailySessionRecord(
                date=today_str,
                setup_detected=False,
                setup_fired=False,
                diagnostic_reason="NO SIGNAL: 08:35 ET (MNQ Macro), 09:45 ET (MNQ/MES), and 10:15 ET (MGC) flat",
                end_of_day_balance=eval_state.balance,
            )
        )
        journal.generate_html_dashboard()
        return 0

    if sig_macro is not None:
        mult = sig_macro.get("markov_mult", 1.0)
        macro_contracts = max(1, int(round(base_contracts * mult)))
        macro_label = f"{tier_label} (08:35 ET Macro Release)"
        if mult != 1.0:
            macro_label += f" [Markov {mult:.2f}x]"
        print_execution_card(sig_macro, eval_state, macro_contracts, macro_label)
        if args.interactive and sig_macro["macro_pass"]:
            record_trade_prompt(sig_macro, macro_contracts, journal)

    for sig in eq_signals:
        mult = sig.get("markov_mult", 1.0)
        eq_base = max(1, base_contracts // 2) if both_eq_passed else base_contracts
        leg_contracts = max(1, int(round(eq_base * mult)))
        leg_label = f"{tier_label} (50/50 Dual-Equity Split)" if both_eq_passed else tier_label
        if mult != 1.0:
            leg_label += f" [Markov {mult:.2f}x]"
        print_execution_card(sig, eval_state, leg_contracts, leg_label)
        if args.interactive and sig["macro_pass"]:
            record_trade_prompt(sig, leg_contracts, journal)

    if sig_gc is not None:
        mult = sig_gc.get("markov_mult", 1.0)
        gc_contracts = max(1, int(round(base_contracts * mult)))
        gc_label = f"{tier_label} (10:15 ET Non-Overlapping Window)"
        if mult != 1.0:
            gc_label += f" [Markov {mult:.2f}x]"
        print_execution_card(sig_gc, eval_state, gc_contracts, gc_label)
        if args.interactive and sig_gc["macro_pass"]:
            record_trade_prompt(sig_gc, gc_contracts, journal)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
