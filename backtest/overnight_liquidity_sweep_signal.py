"""
Overnight High/Low Liquidity Sweep Scalp Signal (H7).

Pre-registered in docs/research_hypotheses/2026-10-29_overnight_high_low_liquidity_sweep_h7.md.

Thesis:
Between 09:35 and 10:30 ET, price tests prominent liquidity pools resting beyond
the Overnight High (ONH) or Overnight Low (ONL). Probes that fail to follow through
leave an exhaustion wick and close back inside the overnight boundary, trapping breakout
traders and mean-reverting toward the Overnight Midpoint (ON_MID).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_ON_SWEEP_FEATURE_COLUMNS = (
    "sweep_score",
    "sweep_depth_points",
    "dist_to_on_mid_points",
    "close_location",
    "overnight_high",
    "overnight_low",
    "overnight_range",
)

DEFAULT_ON_SWEEP_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "level_tested",
    "rotation_target",
)


@dataclass(frozen=True)
class OvernightLiquiditySweepConfig:
    rth_start: str = "09:30"
    scan_start: str = "09:35"
    scan_end: str = "10:30"
    rth_end: str = "16:00"
    overnight_start: str = "18:00"
    min_sweep_points: float = 1.0
    max_sweep_points: float = 25.0
    max_short_close_location: float = 0.45
    min_long_close_location: float = 0.55
    min_stop_points: float = 15.0
    max_stop_points: float = 45.0
    stop_buffer_points: float = 6.0
    min_target_points: float = 15.0
    allow_long: bool = True
    allow_short: bool = True


def build_overnight_liquidity_sweep_signal_export(
    data: pd.DataFrame,
    *,
    config: OvernightLiquiditySweepConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_ON_SWEEP_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_ON_SWEEP_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_overnight_liquidity_sweep_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def _compute_overnight_levels_map(
    df: pd.DataFrame,
    *,
    rth_start_min: int,
    rth_end_min: int,
    ovn_start_min: int,
) -> pd.DataFrame:
    """
    Compute point-in-time overnight high, low, and mid per RTH trading session.
    
    Overnight for session date D includes bars from prior calendar days after ovn_start_min (18:00)
    up through today's bars prior to rth_start_min (09:30).
    """
    times = pd.to_datetime(df["time"])
    minutes = times.dt.hour * 60 + times.dt.minute
    dates = times.dt.date

    # Assign each bar to its effective RTH session date:
    # Bars at or after 18:00 belong to the next session.
    # To handle weekends accurately, we group by chronological trading day sequence.
    is_evening = minutes >= ovn_start_min
    
    # We assign an overnight session date tag:
    # Evening bars get shifted forward to the next business date.
    # Cleanest method: find unique RTH session dates, map each bar's timestamp to the next RTH session.
    is_rth = (minutes >= rth_start_min) & (minutes <= rth_end_min)
    rth_dates = sorted(df.loc[is_rth, "time"].dt.date.unique())
    rth_date_set = set(rth_dates)

    if not rth_dates:
        return pd.DataFrame()

    # Map each timestamp to its target RTH date:
    # 1. If date is an RTH date and minute < rth_start_min: target is today's date.
    # 2. If minute >= ovn_start_min: target is the next available RTH date.
    target_dates = pd.Series(index=df.index, dtype="object")
    
    # Before RTH:
    pre_rth_mask = minutes < rth_start_min
    target_dates.loc[pre_rth_mask] = dates.loc[pre_rth_mask]

    # After RTH evening bars:
    if is_evening.any():
        evening_indices = df.index[is_evening]
        evening_dates = dates.loc[evening_indices]
        
        # Build lookup for next RTH date after any calendar date
        all_cal_dates = pd.date_range(min(dates), max(dates) + pd.Timedelta(days=7)).date
        next_rth_map = {}
        rth_idx = 0
        n_rth = len(rth_dates)
        for cd in all_cal_dates:
            while rth_idx < n_rth and rth_dates[rth_idx] <= cd:
                rth_idx += 1
            if rth_idx < n_rth:
                next_rth_map[cd] = rth_dates[rth_idx]
            else:
                next_rth_map[cd] = None
        
        target_dates.loc[is_evening] = evening_dates.map(next_rth_map)

    # Overnight bars are those with a valid target RTH date and not in RTH
    ovn_bar_mask = target_dates.notna() & (~is_rth)
    ovn_bars = df.loc[ovn_bar_mask].copy()
    ovn_bars["session_date"] = target_dates.loc[ovn_bar_mask]

    # Filter to only known RTH dates
    ovn_bars = ovn_bars.loc[ovn_bars["session_date"].isin(rth_date_set)]

    if ovn_bars.empty:
        return pd.DataFrame()

    grouped = ovn_bars.groupby("session_date", sort=True)
    ovn_summary = grouped.agg(
        overnight_high=("high", "max"),
        overnight_low=("low", "min"),
    )
    ovn_summary["overnight_mid"] = (ovn_summary["overnight_high"] + ovn_summary["overnight_low"]) / 2.0
    ovn_summary["overnight_range"] = ovn_summary["overnight_high"] - ovn_summary["overnight_low"]

    return ovn_summary


def build_overnight_liquidity_sweep_signal_frame(
    data: pd.DataFrame,
    *,
    config: OvernightLiquiditySweepConfig | None = None,
) -> pd.DataFrame:
    cfg = config or OvernightLiquiditySweepConfig()
    df = _base_ohlcv_frame(data)

    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    rth_start_min = _parse_hhmm(cfg.rth_start)
    scan_start_min = _parse_hhmm(cfg.scan_start)
    scan_end_min = _parse_hhmm(cfg.scan_end)
    rth_end_min = _parse_hhmm(cfg.rth_end)
    ovn_start_min = _parse_hhmm(cfg.overnight_start)

    ovn_summary = _compute_overnight_levels_map(
        df,
        rth_start_min=rth_start_min,
        rth_end_min=rth_end_min,
        ovn_start_min=ovn_start_min,
    )

    # Work strictly on RTH bars
    rth_mask = (minutes >= rth_start_min) & (minutes <= rth_end_min)
    rth = df.loc[rth_mask].copy()
    rth["session_date"] = rth["time"].dt.date

    # Join overnight levels onto RTH bars by session date
    rth = rth.join(ovn_summary, on="session_date", how="left")

    # Initialize signal arrays
    n = len(rth)
    signal = np.zeros(n, dtype=float)
    sweep_score = np.zeros(n, dtype=float)
    sweep_depth = np.full(n, np.nan, dtype=float)
    dist_to_on_mid = np.full(n, np.nan, dtype=float)
    stop_points = np.full(n, np.nan, dtype=float)
    target_points = np.full(n, np.nan, dtype=float)
    setup_tag = np.full(n, "", dtype=object)
    direction_col = np.full(n, "flat", dtype=object)
    level_tested_col = np.full(n, "none", dtype=object)
    rot_target_col = np.full(n, "none", dtype=object)

    rth_minutes = rth["time"].dt.hour.to_numpy() * 60 + rth["time"].dt.minute.to_numpy()
    highs = rth["high"].to_numpy(dtype=float)
    lows = rth["low"].to_numpy(dtype=float)
    opens = rth["open"].to_numpy(dtype=float)
    closes = rth["close"].to_numpy(dtype=float)
    on_highs = rth["overnight_high"].to_numpy(dtype=float)
    on_lows = rth["overnight_low"].to_numpy(dtype=float)
    on_mids = rth["overnight_mid"].to_numpy(dtype=float)
    session_dates = rth["session_date"].to_numpy()

    bar_ranges = np.maximum(highs - lows, 1e-4)
    close_locs = (closes - lows) / bar_ranges

    # Scan within [scan_start_min, scan_end_min]
    in_scan_window = (rth_minutes >= scan_start_min) & (rth_minutes <= scan_end_min)
    valid_ovn = np.isfinite(on_highs) & np.isfinite(on_lows) & (on_highs > on_lows)

    # Track 1 signal per session (deduplication)
    current_session = None
    session_has_triggered = False

    for i in range(n):
        s_date = session_dates[i]
        if s_date != current_session:
            current_session = s_date
            session_has_triggered = False

        if not in_scan_window[i] or not valid_ovn[i] or session_has_triggered:
            continue

        h = highs[i]
        l = lows[i]
        c = closes[i]
        on_h = on_highs[i]
        on_l = on_lows[i]
        on_m = on_mids[i]
        cloc = close_locs[i]

        # 1. Bearish ONH Sweep Setup (Short)
        if cfg.allow_short and (h > on_h):
            s_depth = h - on_h
            if (cfg.min_sweep_points <= s_depth <= cfg.max_sweep_points) and (c < on_h) and (cloc <= cfg.max_short_close_location):
                signal[i] = -1.0
                sweep_score[i] = -float(s_depth)
                sweep_depth[i] = float(s_depth)
                dist_to_on_mid[i] = float(c - on_m)
                setup_tag[i] = "onh_sweep_short"
                direction_col[i] = "short"
                level_tested_col[i] = "onh"
                rot_target_col[i] = "on_mid"
                
                raw_stop = (h - c) + cfg.stop_buffer_points
                stop_points[i] = float(np.clip(raw_stop, cfg.min_stop_points, cfg.max_stop_points))
                target_points[i] = float(max(cfg.min_target_points, c - on_m))
                
                session_has_triggered = True
                continue

        # 2. Bullish ONL Sweep Setup (Long)
        if cfg.allow_long and (l < on_l):
            s_depth = on_l - l
            if (cfg.min_sweep_points <= s_depth <= cfg.max_sweep_points) and (c > on_l) and (cloc >= cfg.min_long_close_location):
                signal[i] = 1.0
                sweep_score[i] = float(s_depth)
                sweep_depth[i] = float(s_depth)
                dist_to_on_mid[i] = float(on_m - c)
                setup_tag[i] = "onl_sweep_long"
                direction_col[i] = "long"
                level_tested_col[i] = "onl"
                rot_target_col[i] = "on_mid"
                
                raw_stop = (c - l) + cfg.stop_buffer_points
                stop_points[i] = float(np.clip(raw_stop, cfg.min_stop_points, cfg.max_stop_points))
                target_points[i] = float(max(cfg.min_target_points, on_m - c))
                
                session_has_triggered = True
                continue

    # Assign columns back to RTH frame
    rth["candidate_signal"] = signal
    rth["sweep_score"] = sweep_score
    rth["sweep_depth_points"] = sweep_depth
    rth["dist_to_on_mid_points"] = dist_to_on_mid
    rth["close_location"] = close_locs
    rth["stop_points"] = stop_points
    rth["target_points"] = target_points
    rth["setup_tag"] = setup_tag
    rth["direction"] = direction_col
    rth["level_tested"] = level_tested_col
    rth["rotation_target"] = rot_target_col
    rth["signal_type"] = "overnight_liquidity_sweep"

    # Merge back into full dataset
    out = df.copy()
    cols_to_transfer = [
        "candidate_signal",
        "sweep_score",
        "sweep_depth_points",
        "dist_to_on_mid_points",
        "close_location",
        "overnight_high",
        "overnight_low",
        "overnight_mid",
        "overnight_range",
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
    out["sweep_score"] = out["sweep_score"].fillna(0.0)
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
