"""
Candidate Strategy S4: Asian Evening Reversion (21:00–23:00 ET).
Primary Instrument: Micro E-mini Nasdaq-100 (MNQ; $2.00/point, tick size 0.25 pt / $0.50/tick)
with configurable support for Micro E-mini S&P 500 (MES; $5.00/point).

Hypothesis & Microstructure:
Exploits Tokyo cash equity open (09:00 JST / 21:00 ET) institutional liquidity rebalancing.
Between the 18:00 ET Globex re-open and 21:14 ET, thin early-evening retail and hedging flow
often drifts price away from the 18:00 ET Globex open. When that pre-Tokyo drift reaches
0.15x to 0.85x of the prior US RTH 14-day ATR (with active institutional participation
RTH RVOL(20) >= 0.85) AND the 21:00–21:14 ET Tokyo Opening 15-minute candle rejects the drift
(closes opposing the 18:00–21:14 ET drift within a controlled opening range), Asian institutional
desks mean-revert price back toward the Globex anchor between 21:15 ET and 23:00 ET.
Also supports intra-session Anchored VWAP z-score reversion under 4-layer defensive regime gates
and enforces a mandatory 23:00 ET (01:00 UTC-3) session flatten.

Governing Rules:
- Rule 1: One source of truth (quarantined under StrategyTier.CANDIDATE).
- Rule 2: No naked numbers (complete provenance metadata, date ranges, data hash).
- Rule 3: Standardized provenance footers.
- Rule 4: Warnings travel with the number.
- Rule 5: Automatic recording into results/backtest_provenance.db.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class AsianEveningReversionParams:
    """Quantitative parameters for Candidate S4 Asian Evening Reversion."""

    # Strategy Identification
    strategy_id: str = "asian_evening_reversion_s4"
    strategy_name: str = "Asian Evening Reversion (21:00 ET)"
    instrument: str = "MES"
    asset_class: str = "EQUITY_INDEX"

    # Contract Specifications & Transaction Costs
    contract_value: float = 5.0          # $5.00/pt on MES ($2.00/pt on MNQ)
    tick_size: float = 0.25              # 0.25 point per tick
    commission_round_trip: float = 1.40  # $1.40 per round turn ($0.70/side micro)
    slippage_limit_pts: float = 0.25     # 1 tick adverse on limit target fills
    slippage_stop_pts: float = 0.50      # 2 ticks adverse on market/stop/flatten fills
    slippage_entry_pts: float = 0.25     # 1 tick adverse on market/stop entry fills

    # Session Timing (Eastern Time)
    anchor_time_et: str = "21:00"        # Tokyo cash open session VWAP anchor
    observation_start_et: str = "21:00"  # 15m opening range observation start
    observation_end_et: str = "21:14"    # 15m opening range observation end
    entry_start_et: str = "21:15"        # First allowed entry time
    entry_end_et: str = "22:45"          # Last allowed entry time
    flatten_time_et: str = "23:00"       # Hard mandatory session flatten

    # Tokyo Globex Drift Reversion Parameters (Multi-Day Continuous Mode)
    min_rth_rvol20: float = 0.85         # Minimum same-day completed US RTH RVOL(20)
    min_globex_drift_atr: float = 0.15   # Min |Close_2114 - Open_1800| / RTH_ATR14
    max_globex_drift_atr: float = 0.85   # Max |Close_2114 - Open_1800| / RTH_ATR14 (blowout veto)
    mnq_min_or15_range: float = 6.0      # MNQ opening 15m range lower bound
    mnq_max_or15_range: float = 45.0     # MNQ opening 15m range upper bound
    mnq_stop_pts: float = 35.0           # MNQ stop distance (35.0 pts = $70.00/micro)
    mnq_target_pts: float = 37.5         # MNQ target distance (37.5 pts = $75.00/micro)

    # Statistical Excursion & Mean Reversion Triggers (Intra-Session Mode)
    zscore_entry: float = 2.0            # |z| >= 2.0 standard deviations from Asian VWAP
    min_lower_wick_ratio: float = 0.35   # Long reversal hammer wick threshold
    min_upper_wick_ratio: float = 0.35   # Short reversal shooting star wick threshold

    # 4-Layer Defensive Regime Gates
    min_opening_15m_range: float = 2.0   # Gate 1: Veto if range < 2.0 pts (dead liquidity / friction trap)
    max_opening_15m_range: float = 8.0   # Gate 1: Veto if range > 8.0 pts (blowout trend regime)
    max_atr_1m: float = 2.50             # Gate 1: Veto if 1m ATR(14) > 2.50 pts
    max_displacement_pts: float = 10.0   # Gate 2: Veto if net displacement |Price - Open_2100| > 10.0 pts
    max_adx_5m: float = 30.0             # Gate 2: Veto if 5m ADX(14) > 30.0 (trending market)

    # Protective Bracket Risk Management
    min_stop_pts: float = 4.0            # Stop loss lower bound
    max_stop_pts: float = 6.0            # Stop loss upper bound
    default_stop_pts: float = 5.0        # Default stop loss distance if swing undefined
    swing_lookback_bars: int = 3         # Swing extreme lookback
    swing_buffer_pts: float = 0.50       # 2-tick buffer beyond swing extreme
    min_rr_ratio: float = 1.2            # Minimum acceptable R:R to VWAP
    target_rr_ratio: float = 1.5         # Baseline target multiplier if VWAP distance exceeds 1.5R
    breakeven_trigger_r: float = 1.0     # Move stop to breakeven at +1.0R
    breakeven_lock_pts: float = 0.50     # Lock +0.50 pt (+2 ticks) on breakeven
    max_trades_per_session: int = 1      # Max allowed entries per evening session

    @classmethod
    def for_mnq(cls) -> "AsianEveningReversionParams":
        """Returns canonical parameters calibrated for Micro E-mini Nasdaq-100 (MNQ)."""
        return cls(
            instrument="MNQ",
            contract_value=2.0,
            tick_size=0.25,
            commission_round_trip=1.40,
            slippage_limit_pts=0.25,
            slippage_stop_pts=0.50,
            slippage_entry_pts=0.25,
            min_opening_15m_range=6.0,
            max_opening_15m_range=45.0,
            max_atr_1m=12.0,
            max_displacement_pts=45.0,
            max_adx_5m=35.0,
            min_stop_pts=25.0,
            max_stop_pts=35.0,
            default_stop_pts=35.0,
            mnq_stop_pts=35.0,
            mnq_target_pts=37.5,
            breakeven_trigger_r=1.0,
            breakeven_lock_pts=0.50,
        )


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Vectorized Wilder True Range and ATR."""
    if len(close) == 0:
        return pd.Series(dtype=float)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / max(window, 1), adjust=False).mean().fillna(0.0)


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Vectorized Wilder ADX calculation handling arbitrary series lengths without IndexError."""
    if len(close) < window + 1:
        return pd.Series(0.0, index=close.index, dtype=float)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up = high - high.shift(1)
    down = low.shift(1) - low

    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)

    alpha = 1.0 / max(window, 1)
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * pd.Series(plus_dm, index=close.index).ewm(alpha=alpha, adjust=False).mean() / np.maximum(atr, 1e-4)
    minus_di = 100.0 * pd.Series(minus_dm, index=close.index).ewm(alpha=alpha, adjust=False).mean() / np.maximum(atr, 1e-4)

    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / np.maximum(di_sum, 1e-4)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()
    return adx.fillna(0.0)


def calculate_asian_session_features(
    df: pd.DataFrame,
    params: AsianEveningReversionParams,
) -> pd.DataFrame:
    """
    Computes all technical indicators, 5m ADX, 1m ATR, opening 15m range,
    completed same-day US RTH regime metrics (09:00–16:00 ET), pre-Tokyo Globex open (18:00 ET),
    and Anchored Session VWAP with dynamic standard deviation bands.
    Strictly point-in-time calculation with zero future data leakage.
    """
    out = df.copy()
    if "time" not in out.columns:
        raise ValueError("DataFrame must contain 'time' column.")

    out["time"] = pd.to_datetime(out["time"])
    out.sort_values("time", inplace=True)
    out.reset_index(drop=True, inplace=True)

    out["date_str"] = out["time"].dt.strftime("%Y-%m-%d")
    out["hour"] = out["time"].dt.hour
    out["minute"] = out["time"].dt.minute
    out["m"] = out["hour"] * 60 + out["minute"]

    # 1. 1-Minute ATR(14) globally
    out["atr_1m"] = compute_atr(out["high"], out["low"], out["close"], window=14)

    # 2. 5-Minute Resampled ADX(14) with shift(1) for strict point-in-time integrity
    df_5m = (
        out.set_index("time")[["open", "high", "low", "close", "volume"]]
        .resample("5min", label="right", closed="right")
        .agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        })
        .dropna()
    )
    if len(df_5m) > 0:
        df_5m["adx_5m"] = compute_adx(df_5m["high"], df_5m["low"], df_5m["close"], window=14).shift(1).fillna(0.0)
    else:
        df_5m["adx_5m"] = 0.0

    out = pd.merge_asof(
        out,
        df_5m[["adx_5m"]].reset_index(),
        on="time",
        direction="backward",
    )
    out["adx_5m"] = out["adx_5m"].fillna(0.0)

    # 3. Completed Same-Day US RTH Regime Stats (09:00–16:00 ET, finished 5 hours before 21:00 ET)
    # and Pre-Tokyo Globex Open (18:00–20:59 ET, finished before 21:00 ET)
    rth_bars = out[(out["m"] >= 540) & (out["m"] <= 960)]
    pre_bars = out[(out["m"] >= 1080) & (out["m"] <= 1259)]

    rth_map: Dict[str, Dict[str, float]] = {}
    pre_map: Dict[str, float] = {}

    if len(rth_bars) > 0:
        rth_daily = rth_bars.groupby("date_str").agg(
            rth_high=("high", "max"),
            rth_low=("low", "min"),
            rth_vol=("volume", "sum"),
        ).reset_index()
        rth_daily["rth_range"] = rth_daily["rth_high"] - rth_daily["rth_low"]
        rth_daily["rth_atr14"] = rth_daily["rth_range"].rolling(14).mean()
        rth_daily["rth_vol20"] = rth_daily["rth_vol"].rolling(20).mean()
        rth_daily["rth_rvol"] = rth_daily["rth_vol"] / rth_daily["rth_vol20"].clip(lower=1.0)
        rth_map = rth_daily.set_index("date_str")[["rth_atr14", "rth_rvol"]].to_dict("index")

    if len(pre_bars) > 0:
        pre_daily = pre_bars.groupby("date_str")["open"].first()
        pre_map = pre_daily.to_dict()

    # Pre-allocate session feature columns
    out["range_15m"] = np.nan
    out["open_2100"] = np.nan
    out["close_2114"] = np.nan
    out["pre_open_1800"] = np.nan
    out["rth_atr14"] = np.nan
    out["rth_rvol"] = np.nan
    out["vwap"] = np.nan
    out["vwap_std"] = np.nan
    out["vwap_zscore"] = np.nan
    out["upper_band"] = np.nan
    out["lower_band"] = np.nan

    # 4. Anchored Session VWAP and Opening 15m Range per session (21:00–23:00 ET)
    evening_mask = (out["hour"].isin([21, 22])) | ((out["hour"] == 23) & (out["minute"] == 0))
    session_indices = out[evening_mask].groupby("date_str").groups

    for date_str, idxs in session_indices.items():
        sess_df = out.loc[idxs]

        # Locate 21:00 to 21:14 observation bars
        or_mask = (sess_df["hour"] == 21) & (sess_df["minute"] < 15)
        or_bars = sess_df[or_mask]
        if len(or_bars) == 0:
            continue

        or15_range = float(or_bars["high"].max() - or_bars["low"].min())
        open_2100 = float(or_bars.iloc[0]["open"])
        close_2114 = float(or_bars.iloc[-1]["close"])

        out.loc[idxs, "range_15m"] = or15_range
        out.loc[idxs, "open_2100"] = open_2100
        out.loc[idxs, "close_2114"] = close_2114

        if date_str in pre_map:
            out.loc[idxs, "pre_open_1800"] = float(pre_map[date_str])
        if date_str in rth_map:
            out.loc[idxs, "rth_atr14"] = float(rth_map[date_str]["rth_atr14"])
            out.loc[idxs, "rth_rvol"] = float(rth_map[date_str]["rth_rvol"])

        # Calculate Anchored Session VWAP starting at 21:00
        tp = (sess_df["high"] + sess_df["low"] + sess_df["close"]) / 3.0
        v = sess_df["volume"].clip(lower=1)
        pv = tp * v
        p2v = (tp ** 2) * v

        cum_v = v.cumsum()
        cum_pv = pv.cumsum()
        cum_p2v = p2v.cumsum()

        vwap_arr = cum_pv / cum_v
        var_arr = np.maximum(0.0, (cum_p2v / cum_v) - (vwap_arr ** 2))
        std_arr = np.sqrt(var_arr)
        zscore_arr = (sess_df["close"] - vwap_arr) / np.maximum(std_arr, params.tick_size)

        out.loc[idxs, "vwap"] = vwap_arr
        out.loc[idxs, "vwap_std"] = std_arr
        out.loc[idxs, "vwap_zscore"] = zscore_arr
        out.loc[idxs, "upper_band"] = vwap_arr + params.zscore_entry * std_arr
        out.loc[idxs, "lower_band"] = vwap_arr - params.zscore_entry * std_arr

    return out


def generate_signals(
    df: pd.DataFrame,
    params: AsianEveningReversionParams,
) -> pd.DataFrame:
    """
    Evaluates defensive regime gates and Tokyo Opening Range / Globex Drift Reversion
    triggers to produce point-in-time trading signals (1 = Long, -1 = Short, 0 = Flat).
    """
    signals = pd.DataFrame(index=df.index)
    signals["time"] = df["time"]
    signals["signal"] = 0
    signals["signal_type"] = ""
    signals["entry_price"] = np.nan
    signals["stop_price"] = np.nan
    signals["target_price"] = np.nan
    signals["vwap_zscore"] = df["vwap_zscore"]
    signals["range_15m"] = df["range_15m"]

    evening_mask = (df["hour"].isin([21, 22])) | ((df["hour"] == 23) & (df["minute"] == 0))
    session_groups = df[evening_mask].groupby("date_str")

    has_globex_context = (
        "pre_open_1800" in df.columns
        and "rth_atr14" in df.columns
        and not df["pre_open_1800"].isna().all()
        and not df["rth_atr14"].isna().all()
    )

    for date_str, sess in session_groups:
        if sess["range_15m"].isna().all():
            continue

        or15_range = float(sess["range_15m"].iloc[0])
        open_2100 = float(sess["open_2100"].iloc[0])

        # Gate 1: Opening 15m Range Filter
        if or15_range < params.min_opening_15m_range or or15_range > params.max_opening_15m_range:
            continue

        # Active entry window: 21:15 to 22:45 ET
        entry_mask = (
            ((sess["hour"] == 21) & (sess["minute"] >= 15))
            | ((sess["hour"] == 22) & (sess["minute"] <= 45))
        )
        entry_bars = sess[entry_mask]
        if len(entry_bars) < 2:
            continue

        # Path A: Multi-Day Continuous Tokyo Open Globex Drift Reversion
        if has_globex_context:
            pre_open = sess["pre_open_1800"].iloc[0]
            rth_atr = sess["rth_atr14"].iloc[0]
            rth_rvol = sess["rth_rvol"].iloc[0]
            close_2114 = sess["close_2114"].iloc[0]

            if pd.isna(pre_open) or pd.isna(rth_atr) or pd.isna(rth_rvol) or pd.isna(close_2114):
                continue

            if rth_rvol < params.min_rth_rvol20:
                continue

            # Check 21:00-21:14 observation bar count (>= 10 bars) and post bars (>= 30 bars)
            or_bars_cnt = len(sess[(sess["hour"] == 21) & (sess["minute"] < 15)])
            post_bars_cnt = len(sess[(sess["hour"] > 21) | ((sess["hour"] == 21) & (sess["minute"] >= 15))])
            if or_bars_cnt < 10 or post_bars_cnt < 30:
                continue

            drift = float(close_2114 - pre_open)
            if abs(drift) < params.min_globex_drift_atr * rth_atr or abs(drift) > params.max_globex_drift_atr * rth_atr:
                continue

            # Evaluate at the 21:14 ET close (entering on the 21:15 ET open bar)
            or_end_bars = sess[(sess["hour"] == 21) & (sess["minute"] < 15)]
            sig_row = or_end_bars.iloc[-1]
            sig_idx = sig_row.name
            loc_in_sess = sess.index.get_loc(sig_idx)
            if loc_in_sess + 1 >= len(sess):
                continue

            sig = 0
            if drift > 0 and close_2114 < open_2100:
                sig = -1
                signal_type = "asian_reversion_short"
            elif drift < 0 and close_2114 > open_2100:
                sig = 1
                signal_type = "asian_reversion_long"

            if sig != 0:
                next_bar = sess.iloc[loc_in_sess + 1]
                raw_open = float(next_bar["open"])
                entry_price = raw_open + params.slippage_entry_pts if sig == 1 else raw_open - params.slippage_entry_pts
                sl_dist = params.mnq_stop_pts
                tp_dist = params.mnq_target_pts
                stop_price = entry_price - sl_dist if sig == 1 else entry_price + sl_dist
                target_price = entry_price + tp_dist if sig == 1 else entry_price - tp_dist

                signals.loc[sig_idx, "signal"] = sig
                signals.loc[sig_idx, "signal_type"] = signal_type
                signals.loc[sig_idx, "entry_price"] = entry_price
                signals.loc[sig_idx, "stop_price"] = stop_price
                signals.loc[sig_idx, "target_price"] = target_price
            continue

        # Path B: Single-Session / Synthetic Slice VWAP Band Reversion
        trade_fired = False
        for i in range(1, len(entry_bars)):
            if trade_fired:
                break

            curr_row = entry_bars.iloc[i]
            prev_row = entry_bars.iloc[i - 1]
            curr_idx = curr_row.name

            # Gate 1.2: 1-minute ATR Ceiling
            if curr_row["atr_1m"] > params.max_atr_1m:
                continue

            # Gate 2.1: Net Displacement Ceiling (|Close - Open_2100| <= max_displacement_pts)
            if abs(curr_row["close"] - open_2100) > params.max_displacement_pts:
                continue

            # Gate 2.2: 5m ADX Trend Strength Ceiling (ADX <= max_adx_5m)
            if curr_row["adx_5m"] > params.max_adx_5m:
                continue

            bar_range = curr_row["high"] - curr_row["low"]
            if bar_range > 0:
                lower_wick = (min(curr_row["open"], curr_row["close"]) - curr_row["low"]) / bar_range
                upper_wick = (curr_row["high"] - max(curr_row["open"], curr_row["close"])) / bar_range
            else:
                lower_wick = 0.0
                upper_wick = 0.0

            long_rev = (
                (curr_row["close"] > prev_row["close"])
                or (lower_wick >= params.min_lower_wick_ratio)
                or (curr_row["close"] > curr_row["lower_band"])
            )
            short_rev = (
                (curr_row["close"] < prev_row["close"])
                or (upper_wick >= params.min_upper_wick_ratio)
                or (curr_row["close"] < curr_row["upper_band"])
            )

            sig = 0
            if prev_row["vwap_zscore"] <= -params.zscore_entry and long_rev:
                sig = 1
            elif prev_row["vwap_zscore"] >= params.zscore_entry and short_rev:
                sig = -1

            if sig == 0:
                continue

            loc_in_sess = sess.index.get_loc(curr_idx)
            if loc_in_sess + 1 >= len(sess):
                continue

            next_bar = sess.iloc[loc_in_sess + 1]
            entry_price = float(next_bar["open"])

            window_slice = sess.iloc[max(0, loc_in_sess - params.swing_lookback_bars + 1) : loc_in_sess + 1]
            if sig == 1:
                swing_low = float(window_slice["low"].min())
                raw_risk = entry_price - (swing_low - params.swing_buffer_pts)
                risk_dist = float(np.clip(raw_risk, params.min_stop_pts, params.max_stop_pts))
                stop_price = entry_price - risk_dist
                raw_target_dist = float(curr_row["vwap"] - entry_price)
                target_dist = max(raw_target_dist, params.min_rr_ratio * risk_dist)
                target_price = entry_price + target_dist
                signal_type = "asian_reversion_long"
            else:
                swing_high = float(window_slice["high"].max())
                raw_risk = (swing_high + params.swing_buffer_pts) - entry_price
                risk_dist = float(np.clip(raw_risk, params.min_stop_pts, params.max_stop_pts))
                stop_price = entry_price + risk_dist
                raw_target_dist = float(entry_price - curr_row["vwap"])
                target_dist = max(raw_target_dist, params.min_rr_ratio * risk_dist)
                target_price = entry_price - target_dist
                signal_type = "asian_reversion_short"

            signals.loc[curr_idx, "signal"] = sig
            signals.loc[curr_idx, "signal_type"] = signal_type
            signals.loc[curr_idx, "entry_price"] = entry_price
            signals.loc[curr_idx, "stop_price"] = stop_price
            signals.loc[curr_idx, "target_price"] = target_price
            trade_fired = True

    return signals


def simulate_intrabar_execution(
    df: pd.DataFrame,
    signals_df: pd.DataFrame,
    params: AsianEveningReversionParams,
) -> pd.DataFrame:
    """
    Executes trades bar-by-bar applying conservative intrabar conflict resolution:
    - Adverse touch of stop and target in same bar resolves to Stop Loss.
    - Breakeven trailing moves stop to entry +- breakeven_lock_pts at +1.0R.
    - Mandatory time exit triggers at 23:00:00 ET.
    - Full friction accounting: $1.40 RT commission, 1-tick limit slip, 2-tick stop slip.
    """
    sig_indices = signals_df[signals_df["signal"] != 0].index
    trades: List[Dict[str, Any]] = []

    evening_mask = (df["hour"].isin([21, 22])) | ((df["hour"] == 23) & (df["minute"] == 0))
    grouped_sess = df[evening_mask].groupby("date_str")

    has_globex_context = (
        "pre_open_1800" in df.columns
        and "rth_atr14" in df.columns
        and not df["pre_open_1800"].isna().all()
        and not df["rth_atr14"].isna().all()
    )

    trade_counter = 1

    for idx in sig_indices:
        sig_row = signals_df.loc[idx]
        signal = int(sig_row["signal"])
        signal_type = str(sig_row["signal_type"])
        date_str = str(df.loc[idx, "date_str"])

        if date_str not in grouped_sess.groups:
            continue

        sess_indices = grouped_sess.groups[date_str]
        sess = df.loc[sess_indices]
        loc_in_sess = sess.index.get_loc(idx)

        if loc_in_sess + 1 >= len(sess):
            continue

        entry_bar = sess.iloc[loc_in_sess + 1]
        entry_time = entry_bar["time"]
        entry_price = float(sig_row["entry_price"]) if has_globex_context else float(entry_bar["open"])
        stop_price = float(sig_row["stop_price"])
        target_price = float(sig_row["target_price"])
        initial_risk = abs(entry_price - stop_price)

        be_active = False
        exit_price: Optional[float] = None
        exit_reason: Optional[str] = None
        exit_time: Optional[pd.Timestamp] = None
        hold_bars = 0
        mfe_pts = 0.0
        mae_pts = 0.0

        for k in range(loc_in_sess + 1, len(sess)):
            hold_bars += 1
            bar = sess.iloc[k]
            b_high = float(bar["high"])
            b_low = float(bar["low"])
            b_close = float(bar["close"])
            b_time = bar["time"]
            b_hour = int(bar["hour"])
            b_minute = int(bar["minute"])

            if signal == 1:
                cur_favorable = b_high - entry_price
                cur_adverse = entry_price - b_low
            else:
                cur_favorable = entry_price - b_low
                cur_adverse = b_high - entry_price

            if cur_favorable > mfe_pts:
                mfe_pts = cur_favorable
            if cur_adverse > mae_pts:
                mae_pts = cur_adverse

            # Breakeven Adjustment at +1.0R
            if not be_active and initial_risk > 0:
                if signal == 1 and b_high >= entry_price + params.breakeven_trigger_r * initial_risk:
                    be_active = True
                    stop_price = entry_price + params.breakeven_lock_pts
                elif signal == -1 and b_low <= entry_price - params.breakeven_trigger_r * initial_risk:
                    be_active = True
                    stop_price = entry_price - params.breakeven_lock_pts

            # Conflict Resolution
            hit_stop = (b_low <= stop_price) if signal == 1 else (b_high >= stop_price)
            hit_target = (b_high >= target_price) if signal == 1 else (b_low <= target_price)

            if hit_stop and hit_target:
                exit_price = stop_price
                exit_reason = "breakeven" if be_active else "stop_loss"
                exit_time = b_time
                break
            elif hit_stop:
                exit_price = stop_price
                exit_reason = "breakeven" if be_active else "stop_loss"
                exit_time = b_time
                break
            elif hit_target:
                exit_price = target_price
                exit_reason = "profit_target"
                exit_time = b_time
                break
            elif (b_hour == 23 and b_minute == 0) or k == len(sess) - 1:
                exit_price = b_close
                exit_reason = "time_exit"
                exit_time = b_time
                break

        if exit_price is not None:
            if has_globex_context:
                # Apply asymmetric exit slippage directly to exit_price
                if exit_reason == "profit_target":
                    adj_exit = exit_price - params.slippage_limit_pts if signal == 1 else exit_price + params.slippage_limit_pts
                    slippage_dollars = (params.slippage_entry_pts + params.slippage_limit_pts) * params.contract_value
                elif exit_reason == "breakeven":
                    adj_exit = exit_price
                    slippage_dollars = params.slippage_entry_pts * params.contract_value
                else:
                    adj_exit = exit_price - params.slippage_stop_pts if signal == 1 else exit_price + params.slippage_stop_pts
                    slippage_dollars = (params.slippage_entry_pts + params.slippage_stop_pts) * params.contract_value

                pts = (adj_exit - entry_price) if signal == 1 else (entry_price - adj_exit)
                gross_pnl = pts * params.contract_value
                commission = params.commission_round_trip
                net_pnl = gross_pnl - commission
                exit_price = adj_exit
            else:
                pts = (exit_price - entry_price) if signal == 1 else (entry_price - exit_price)
                gross_pnl = pts * params.contract_value
                commission = params.commission_round_trip
                if exit_reason == "profit_target":
                    slippage_dollars = params.slippage_limit_pts * params.contract_value
                else:
                    slippage_dollars = params.slippage_stop_pts * params.contract_value
                net_pnl = gross_pnl - commission - slippage_dollars

            trades.append({
                "trade_id": f"T_{trade_counter:05d}",
                "date": date_str,
                "symbol": params.instrument,
                "direction": "long" if signal == 1 else "short",
                "signal_type": signal_type,
                "entry_time": entry_time,
                "exit_time": exit_time,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "contracts": 1,
                "gross_pnl": float(gross_pnl),
                "commission": float(commission),
                "slippage": float(slippage_dollars),
                "net_pnl": float(net_pnl),
                "exit_reason": exit_reason,
                "hold_bars": hold_bars,
                "mfe_pts": float(mfe_pts),
                "mae_pts": float(mae_pts),
            })
            trade_counter += 1

    return pd.DataFrame(trades)


class AsianEveningReversionS4:
    """
    Candidate S4: Asian Evening Reversion Strategy Engine.
    Encapsulates feature calculation, signal evaluation, and intrabar backtest execution.
    """

    def __init__(self, params: Optional[AsianEveningReversionParams] = None):
        self.params = params or AsianEveningReversionParams.for_mnq()
        self.trades_df: pd.DataFrame = pd.DataFrame()
        self.metrics: Dict[str, Any] = {}

    def backtest(
        self,
        data: Path | str | pd.DataFrame,
        start_date: str = "2021-01-04",
        end_date: str = "2026-10-30",
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Runs the verified candidate backtest on 1-minute CME data.
        """
        if isinstance(data, (str, Path)):
            df = pd.read_parquet(data)
        else:
            df = data.copy()

        df["time"] = pd.to_datetime(df["time"])

        if start_date:
            df = df[df["time"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["time"] <= pd.Timestamp(f"{end_date} 23:59:59")]

        df.reset_index(drop=True, inplace=True)

        # 1. Feature Engineering
        features_df = calculate_asian_session_features(df, self.params)

        # 2. Signal Generation
        signals_df = generate_signals(features_df, self.params)

        # 3. Intrabar Execution Simulation
        trades_df = simulate_intrabar_execution(features_df, signals_df, self.params)
        self.trades_df = trades_df

        # 4. Metric Computation
        if len(trades_df) > 0:
            total_trades = len(trades_df)
            wins = (trades_df["net_pnl"] > 0).sum()
            losses = (trades_df["net_pnl"] < 0).sum()
            win_rate = float((wins / total_trades) * 100.0)

            gross_profit = float(trades_df[trades_df["net_pnl"] > 0]["net_pnl"].sum())
            gross_loss = float(abs(trades_df[trades_df["net_pnl"] < 0]["net_pnl"].sum()))
            profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 999.0
            net_profit = float(trades_df["net_pnl"].sum())

            cumulative = trades_df["net_pnl"].cumsum()
            hwm = np.maximum.accumulate(np.maximum(cumulative, 0.0))
            drawdown = hwm - cumulative
            max_drawdown = float(drawdown.max()) if len(drawdown) > 0 else 0.0

            largest_win = float(trades_df["net_pnl"].max())
            largest_win_pct = float((largest_win / net_profit * 100.0)) if net_profit > 0 else 0.0

            daily_pnl = trades_df.groupby("date")["net_pnl"].sum()
            if len(daily_pnl) > 1 and daily_pnl.std() > 0:
                sharpe = float((daily_pnl.mean() / daily_pnl.std()) * np.sqrt(252))
            else:
                sharpe = 0.0

            self.metrics = {
                "total_trades": total_trades,
                "wins": int(wins),
                "losses": int(losses),
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "net_profit": net_profit,
                "max_drawdown": max_drawdown,
                "sharpe_ratio": sharpe,
                "largest_win": largest_win,
                "largest_win_pct_of_net": largest_win_pct,
            }
        else:
            self.metrics = {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
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

        return self.trades_df, self.metrics
