"""
Mid-Day VWAP Mean Reversion Scalp Signal (H6).

Pre-registered in docs/research_hypotheses/2026-10-29_midday_vwap_mean_reversion_h6.md.

Thesis:
During the European close and NY lunch lull (11:30–13:30 ET), institutional volume declines
by 60-70%. In the absence of directional initiative order flow, deviations beyond +/-2.0
standard deviations from session RTH VWAP represent transient liquidity voids that mean-revert
toward session fair value (VWAP).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_MIDDAY_VWAP_FEATURE_COLUMNS = (
    "vwap_z_score",
    "dist_to_vwap_points",
    "vwap",
    "vwap_std",
    "vwap_upper_band",
    "vwap_lower_band",
    "close_location",
)

DEFAULT_MIDDAY_VWAP_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "level_tested",
    "rotation_target",
)


@dataclass(frozen=True)
class MiddayVwapMeanReversionConfig:
    rth_start: str = "09:30"
    scan_start: str = "11:30"
    scan_end: str = "13:30"
    rth_end: str = "16:00"
    num_std: float = 2.0
    min_std_points: float = 10.0
    max_short_close_location: float = 0.45
    min_long_close_location: float = 0.55
    min_stop_points: float = 15.0
    max_stop_points: float = 45.0
    stop_buffer_points: float = 6.0
    min_target_points: float = 15.0
    allow_long: bool = True
    allow_short: bool = True


def build_midday_vwap_mean_reversion_signal_export(
    data: pd.DataFrame,
    *,
    config: MiddayVwapMeanReversionConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_MIDDAY_VWAP_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_MIDDAY_VWAP_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_midday_vwap_mean_reversion_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_midday_vwap_mean_reversion_signal_frame(
    data: pd.DataFrame,
    *,
    config: MiddayVwapMeanReversionConfig | None = None,
) -> pd.DataFrame:
    cfg = config or MiddayVwapMeanReversionConfig()
    df = _base_ohlcv_frame(data)

    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    rth_start_min = _parse_hhmm(cfg.rth_start)
    scan_start_min = _parse_hhmm(cfg.scan_start)
    scan_end_min = _parse_hhmm(cfg.scan_end)
    rth_end_min = _parse_hhmm(cfg.rth_end)

    # Filter to RTH bars only
    rth_mask = (minutes >= rth_start_min) & (minutes <= rth_end_min)
    rth = df.loc[rth_mask].copy()
    rth["session_date"] = rth["time"].dt.date

    # Vectorized point-in-time RTH VWAP & standard deviation bands
    # Typical price P = (High + Low + Close) / 3.0
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

    upper_bands = vwap_arr + float(cfg.num_std) * std_arr
    lower_bands = vwap_arr - float(cfg.num_std) * std_arr

    rth["vwap"] = vwap_arr
    rth["vwap_std"] = std_arr
    rth["vwap_upper_band"] = upper_bands
    rth["vwap_lower_band"] = lower_bands

    safe_std = np.where(std_arr > 0.0, std_arr, np.nan)
    z_scores = (closes - vwap_arr) / safe_std
    rth["vwap_z_score"] = np.nan_to_num(z_scores, nan=0.0)
    rth["dist_to_vwap_points"] = np.abs(closes - vwap_arr)

    # Scan within [scan_start_min, scan_end_min]
    rth_minutes = rth["time"].dt.hour.to_numpy() * 60 + rth["time"].dt.minute.to_numpy()
    in_scan_window = (rth_minutes >= scan_start_min) & (rth_minutes <= scan_end_min)
    valid_dispersion = std_arr >= float(cfg.min_std_points)
    session_dates = rth["session_date"].to_numpy()

    bar_ranges = np.maximum(highs - lows, 1e-4)
    close_locs = (closes - lows) / bar_ranges
    rth["close_location"] = close_locs

    n = len(rth)
    signal = np.zeros(n, dtype=float)
    stop_points = np.full(n, np.nan, dtype=float)
    target_points = np.full(n, np.nan, dtype=float)
    setup_tag = np.full(n, "", dtype=object)
    direction_col = np.full(n, "flat", dtype=object)
    level_tested_col = np.full(n, "none", dtype=object)
    rot_target_col = np.full(n, "none", dtype=object)

    current_session = None
    session_has_triggered = False

    for i in range(n):
        s_date = session_dates[i]
        if s_date != current_session:
            current_session = s_date
            session_has_triggered = False

        if not in_scan_window[i] or not valid_dispersion[i] or session_has_triggered:
            continue

        h = highs[i]
        l = lows[i]
        c = closes[i]
        u_band = upper_bands[i]
        l_band = lower_bands[i]
        vwap_val = vwap_arr[i]
        cloc = close_locs[i]

        # 1. Short Setup (Upper 2.0 std extension and rejection)
        if cfg.allow_short and (h >= u_band) and (c < u_band) and (cloc <= cfg.max_short_close_location):
            signal[i] = -1.0
            setup_tag[i] = "midday_vwap_upper_short"
            direction_col[i] = "short"
            level_tested_col[i] = "upper_2std"
            rot_target_col[i] = "vwap"

            raw_stop = (h - c) + cfg.stop_buffer_points
            stop_points[i] = float(np.clip(raw_stop, cfg.min_stop_points, cfg.max_stop_points))
            target_points[i] = float(max(cfg.min_target_points, c - vwap_val))

            session_has_triggered = True
            continue

        # 2. Long Setup (Lower 2.0 std extension and rejection)
        if cfg.allow_long and (l <= l_band) and (c > l_band) and (cloc >= cfg.min_long_close_location):
            signal[i] = 1.0
            setup_tag[i] = "midday_vwap_lower_long"
            direction_col[i] = "long"
            level_tested_col[i] = "lower_2std"
            rot_target_col[i] = "vwap"

            raw_stop = (c - l) + cfg.stop_buffer_points
            stop_points[i] = float(np.clip(raw_stop, cfg.min_stop_points, cfg.max_stop_points))
            target_points[i] = float(max(cfg.min_target_points, vwap_val - c))

            session_has_triggered = True
            continue

    rth["candidate_signal"] = signal
    rth["stop_points"] = stop_points
    rth["target_points"] = target_points
    rth["setup_tag"] = setup_tag
    rth["direction"] = direction_col
    rth["level_tested"] = level_tested_col
    rth["rotation_target"] = rot_target_col
    rth["signal_type"] = "midday_vwap_mean_reversion"

    # Merge back to original data frame
    out = df.copy()
    cols_to_transfer = [
        "candidate_signal",
        "vwap",
        "vwap_std",
        "vwap_upper_band",
        "vwap_lower_band",
        "vwap_z_score",
        "dist_to_vwap_points",
        "close_location",
        "stop_points",
        "target_points",
        "setup_tag",
        "direction",
        "level_tested",
        "rotation_target",
        "signal_type",
    ]
    for col in cols_to_transfer:
        out[col] = rth[col]

    out["candidate_signal"] = out["candidate_signal"].fillna(0.0)
    out["signal"] = out["candidate_signal"]
    out["direction"] = out["direction"].fillna("flat")
    out["setup_tag"] = out["setup_tag"].fillna("")
    out["level_tested"] = out["level_tested"].fillna("none")
    out["rotation_target"] = out["rotation_target"].fillna("none")
    out["signal_type"] = out["signal_type"].fillna("none")

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
