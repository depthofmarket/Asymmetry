"""
Afternoon Trend Continuation via Session VWAP Pullback Scalp Signal (H8).

Pre-registered in docs/research_hypotheses/2026-10-30_afternoon_vwap_pullback_continuation_h8.md.

Thesis:
On established trend days (session return >= 0.15%, VWAP aligned with open and Initial Balance),
when price pulls back to test the session VWAP value zone (-0.50*sigma to +0.75*sigma) and
resumes the primary trend during the afternoon institutional window (13:30-15:15 ET) by breaking
the prior bar's extreme with strong close location, continuation order flow drives an afternoon leg.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_AFTERNOON_VWAP_PULLBACK_FEATURE_COLUMNS = (
    "afternoon_pullback_score",
    "session_return_pct",
    "vwap_z_score",
    "pullback_depth_z",
    "vwap",
    "vwap_std",
    "ib_mid",
    "close_location",
)

DEFAULT_AFTERNOON_VWAP_PULLBACK_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "trend_regime",
    "pullback_zone",
)


@dataclass(frozen=True)
class AfternoonVwapPullbackConfig:
    rth_start: str = "09:30"
    ib_end: str = "10:30"
    scan_start: str = "13:30"
    scan_end: str = "15:15"
    rth_end: str = "16:00"
    min_session_return_pct: float = 0.0015  # 0.15% scale-free
    pullback_lookback_bars: int = 15
    pullback_min_z: float = -0.50
    pullback_max_z: float = 0.75
    max_extension_z: float = 1.75
    min_long_close_location: float = 0.65
    max_short_close_location: float = 0.35
    min_stop_points: float = 12.0
    max_stop_points: float = 50.0
    reward_risk_ratio: float = 1.5
    allow_long: bool = True
    allow_short: bool = True


def build_afternoon_vwap_pullback_signal_export(
    data: pd.DataFrame,
    *,
    config: AfternoonVwapPullbackConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_AFTERNOON_VWAP_PULLBACK_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_AFTERNOON_VWAP_PULLBACK_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_afternoon_vwap_pullback_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_afternoon_vwap_pullback_signal_frame(
    data: pd.DataFrame,
    *,
    config: AfternoonVwapPullbackConfig | None = None,
) -> pd.DataFrame:
    cfg = config or AfternoonVwapPullbackConfig()
    df = _base_ohlcv_frame(data)

    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    rth_start_min = _parse_hhmm(cfg.rth_start)
    ib_end_min = _parse_hhmm(cfg.ib_end)
    scan_start_min = _parse_hhmm(cfg.scan_start)
    scan_end_min = _parse_hhmm(cfg.scan_end)
    rth_end_min = _parse_hhmm(cfg.rth_end)

    rth_mask = (minutes >= rth_start_min) & (minutes <= rth_end_min)
    rth = df.loc[rth_mask].copy()
    rth["session_date"] = rth["time"].dt.date

    # 1. RTH Open & Initial Balance (09:30 - 10:30 ET), frozen at 10:30 ET
    rth_open_by_session = rth.groupby("session_date", sort=False)["open"].first()
    rth["rth_open"] = rth["session_date"].map(rth_open_by_session)

    ib_mask = (minutes >= rth_start_min) & (minutes <= ib_end_min)
    ib_bars = df.loc[ib_mask].copy()
    ib_bars["session_date"] = ib_bars["time"].dt.date
    ib_stats = ib_bars.groupby("session_date", sort=False).agg(
        ib_high=("high", "max"),
        ib_low=("low", "min"),
    )
    ib_stats["ib_mid"] = 0.5 * (ib_stats["ib_high"] + ib_stats["ib_low"])
    rth["ib_high"] = rth["session_date"].map(ib_stats["ib_high"])
    rth["ib_low"] = rth["session_date"].map(ib_stats["ib_low"])
    rth["ib_mid"] = rth["session_date"].map(ib_stats["ib_mid"])

    # 2. Vectorized point-in-time RTH VWAP & standard deviation
    highs = rth["high"].to_numpy(dtype=float)
    lows = rth["low"].to_numpy(dtype=float)
    closes = rth["close"].to_numpy(dtype=float)
    volumes = np.maximum(rth["volume"].to_numpy(dtype=float), 1.0)
    typical_prices = (highs + lows + closes) / 3.0

    rth["_pv"] = typical_prices * volumes
    rth["_p2v"] = (typical_prices ** 2) * volumes
    rth["_v"] = volumes

    grouped = rth.groupby("session_date", sort=False)
    cum_pv = grouped["_pv"].cumsum().to_numpy(dtype=float)
    cum_p2v = grouped["_p2v"].cumsum().to_numpy(dtype=float)
    cum_v = grouped["_v"].cumsum().to_numpy(dtype=float)

    vwap_arr = cum_pv / cum_v
    var_arr = np.maximum(0.0, (cum_p2v / cum_v) - (vwap_arr ** 2))
    std_arr = np.sqrt(var_arr)

    rth["vwap"] = vwap_arr
    rth["vwap_std"] = std_arr

    # 3. Rolling pullback highs/lows and prior bar high/low within each session
    lookback = int(cfg.pullback_lookback_bars)
    pullback_low_15 = (
        grouped["low"]
        .rolling(window=lookback, min_periods=1)
        .min()
        .reset_index(level=0, drop=True)
        .to_numpy(dtype=float)
    )
    pullback_high_15 = (
        grouped["high"]
        .rolling(window=lookback, min_periods=1)
        .max()
        .reset_index(level=0, drop=True)
        .to_numpy(dtype=float)
    )
    prev_high = grouped["high"].shift(1).to_numpy(dtype=float)
    prev_low = grouped["low"].shift(1).to_numpy(dtype=float)

    rth_opens = rth["rth_open"].to_numpy(dtype=float)
    ib_mids = rth["ib_mid"].to_numpy(dtype=float)
    session_dates = rth["session_date"].to_numpy()

    safe_open = np.where(rth_opens > 0.0, rth_opens, np.nan)
    session_ret_pct = (closes - safe_open) / safe_open

    safe_std = np.where(std_arr > 0.0, std_arr, np.nan)
    vwap_z = (closes - vwap_arr) / safe_std
    pullback_low_z = (pullback_low_15 - vwap_arr) / safe_std
    pullback_high_z = (pullback_high_15 - vwap_arr) / safe_std

    bar_ranges = np.maximum(highs - lows, 1e-4)
    close_locs = (closes - lows) / bar_ranges

    rth["session_return_pct"] = np.nan_to_num(session_ret_pct, nan=0.0)
    rth["vwap_z_score"] = np.nan_to_num(vwap_z, nan=0.0)
    rth["close_location"] = close_locs

    rth_minutes = rth["time"].dt.hour.to_numpy() * 60 + rth["time"].dt.minute.to_numpy()
    in_scan_window = (rth_minutes >= scan_start_min) & (rth_minutes <= scan_end_min)
    valid_refs = (
        np.isfinite(rth_opens)
        & np.isfinite(ib_mids)
        & np.isfinite(vwap_arr)
        & np.isfinite(std_arr)
        & (std_arr > 0.0)
        & np.isfinite(prev_high)
        & np.isfinite(prev_low)
    )

    n = len(rth)
    signal = np.zeros(n, dtype=float)
    score = np.zeros(n, dtype=float)
    pullback_depth_z_col = np.zeros(n, dtype=float)
    stop_points = np.full(n, np.nan, dtype=float)
    target_points = np.full(n, np.nan, dtype=float)
    setup_tag = np.full(n, "", dtype=object)
    direction_col = np.full(n, "flat", dtype=object)
    trend_regime_col = np.full(n, "neutral", dtype=object)
    pullback_zone_col = np.full(n, "none", dtype=object)

    current_session = None
    session_has_triggered = False

    for i in range(n):
        s_date = session_dates[i]
        if s_date != current_session:
            current_session = s_date
            session_has_triggered = False

        if not in_scan_window[i] or not valid_refs[i] or session_has_triggered:
            continue

        c = closes[i]
        vwap_val = vwap_arr[i]
        sigma = std_arr[i]
        r_open = rth_opens[i]
        ib_m = ib_mids[i]
        s_ret = session_ret_pct[i]
        cloc = close_locs[i]
        z_now = vwap_z[i]
        pb_low_z = pullback_low_z[i]
        pb_high_z = pullback_high_z[i]

        # 1. Long Setup: Uptrend + Pullback to VWAP zone + Bullish breakout of prior bar high
        if cfg.allow_long:
            uptrend_ok = (
                (s_ret >= cfg.min_session_return_pct)
                and (vwap_val > r_open)
                and (c > ib_m)
                and (c > vwap_val)
            )
            pullback_ok = (cfg.pullback_min_z <= pb_low_z <= cfg.pullback_max_z)
            trigger_ok = (
                (c > prev_high[i])
                and (cloc >= cfg.min_long_close_location)
                and (z_now <= cfg.max_extension_z)
            )
            if uptrend_ok and pullback_ok and trigger_ok:
                signal[i] = 1.0
                raw_score = (abs(s_ret) / cfg.min_session_return_pct) * cloc
                score[i] = float(raw_score)
                pullback_depth_z_col[i] = float(pb_low_z)
                setup_tag[i] = "afternoon_vwap_pullback_long"
                direction_col[i] = "long"
                trend_regime_col[i] = "uptrend"
                pullback_zone_col[i] = "vwap_support"

                raw_stop = max(c - pullback_low_15[i], 0.75 * sigma)
                sp = float(np.clip(raw_stop, cfg.min_stop_points, cfg.max_stop_points))
                stop_points[i] = sp
                target_points[i] = float(sp * cfg.reward_risk_ratio)

                session_has_triggered = True
                continue

        # 2. Short Setup: Downtrend + Bounce to VWAP zone + Bearish breakdown of prior bar low
        if cfg.allow_short:
            downtrend_ok = (
                (s_ret <= -cfg.min_session_return_pct)
                and (vwap_val < r_open)
                and (c < ib_m)
                and (c < vwap_val)
            )
            pullback_ok = (-cfg.pullback_max_z <= pb_high_z <= -cfg.pullback_min_z)
            trigger_ok = (
                (c < prev_low[i])
                and (cloc <= cfg.max_short_close_location)
                and (z_now >= -cfg.max_extension_z)
            )
            if downtrend_ok and pullback_ok and trigger_ok:
                signal[i] = -1.0
                raw_score = (abs(s_ret) / cfg.min_session_return_pct) * (1.0 - cloc)
                score[i] = -float(raw_score)
                pullback_depth_z_col[i] = float(pb_high_z)
                setup_tag[i] = "afternoon_vwap_pullback_short"
                direction_col[i] = "short"
                trend_regime_col[i] = "downtrend"
                pullback_zone_col[i] = "vwap_resistance"

                raw_stop = max(pullback_high_15[i] - c, 0.75 * sigma)
                sp = float(np.clip(raw_stop, cfg.min_stop_points, cfg.max_stop_points))
                stop_points[i] = sp
                target_points[i] = float(sp * cfg.reward_risk_ratio)

                session_has_triggered = True
                continue

    rth["candidate_signal"] = signal
    rth["afternoon_pullback_score"] = score
    rth["pullback_depth_z"] = pullback_depth_z_col
    rth["stop_points"] = stop_points
    rth["target_points"] = target_points
    rth["setup_tag"] = setup_tag
    rth["direction"] = direction_col
    rth["trend_regime"] = trend_regime_col
    rth["pullback_zone"] = pullback_zone_col
    rth["signal_type"] = np.where(signal != 0.0, "afternoon_vwap_pullback", "")

    out = df.copy()
    cols_to_transfer = [
        "candidate_signal",
        "afternoon_pullback_score",
        "session_return_pct",
        "vwap_z_score",
        "pullback_depth_z",
        "vwap",
        "vwap_std",
        "ib_mid",
        "close_location",
        "stop_points",
        "target_points",
        "setup_tag",
        "direction",
        "trend_regime",
        "pullback_zone",
        "signal_type",
    ]
    for col in cols_to_transfer:
        out[col] = rth[col]

    out["candidate_signal"] = out["candidate_signal"].fillna(0.0)
    out["signal"] = out["candidate_signal"]
    out["afternoon_pullback_score"] = out["afternoon_pullback_score"].fillna(0.0)
    out["session_return_pct"] = out["session_return_pct"].fillna(0.0)
    out["vwap_z_score"] = out["vwap_z_score"].fillna(0.0)
    out["pullback_depth_z"] = out["pullback_depth_z"].fillna(0.0)
    out["direction"] = out["direction"].fillna("flat")
    out["setup_tag"] = out["setup_tag"].fillna("")
    out["trend_regime"] = out["trend_regime"].fillna("neutral")
    out["pullback_zone"] = out["pullback_zone"].fillna("none")
    out["signal_type"] = out["signal_type"].fillna("")

    return out


def _base_ohlcv_frame(data: pd.DataFrame) -> pd.DataFrame:
    required = ["time", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in data.columns]
    if missing:
        raise ValueError(f"Missing required OHLCV columns: {missing}")
    df = data.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"])
    return df.sort_values("time").reset_index(drop=True)


def _parse_hhmm(value: str) -> int:
    parts = str(value).split(":")
    return int(parts[0]) * 60 + int(parts[1])
