from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_GAP_FADE_FEATURE_COLUMNS = (
    "gap_fade_score",
    "gap_points",
    "abs_gap_points",
    "gap_pct",
    "abs_gap_pct",
    "daily_atr_20",
    "gap_to_atr_ratio",
)


DEFAULT_GAP_FADE_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "gap_direction",
    "gap_size_bucket",
)


@dataclass(frozen=True)
class GapFadeSignalConfig:
    min_gap_pct: float = 0.0050  # 0.50%
    min_gap_to_atr_ratio: float = 0.20  # 0.20x 20-day daily ATR
    atr_window_days: int = 20
    target_gap_fraction: float = 0.50
    max_target_points: float = 30.0
    stop_gap_fraction: float = 1.00
    signal_time: str = "09:30"
    rth_start: str = "09:30"
    rth_end: str = "16:00"


def build_gap_fade_signal_export(
    data: pd.DataFrame,
    *,
    config: GapFadeSignalConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_GAP_FADE_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_GAP_FADE_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_gap_fade_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_gap_fade_signal_frame(
    data: pd.DataFrame,
    *,
    config: GapFadeSignalConfig | None = None,
) -> pd.DataFrame:
    cfg = config or GapFadeSignalConfig()
    _validate_config(cfg)
    df = _base_ohlcv_frame(data)

    # 1. Compute Daily RTH Stats and 20-day ATR strictly from completed prior sessions
    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    rth_start_min = _parse_hhmm(cfg.rth_start)
    rth_end_min = _parse_hhmm(cfg.rth_end)
    rth_mask = minutes.ge(rth_start_min) & minutes.le(rth_end_min)
    rth = df.loc[rth_mask].copy()

    session = df["time"].dt.date
    daily_stats = _daily_rth_stats(rth, atr_window=cfg.atr_window_days)

    # Map prior session stats to current session
    daily_by_session = daily_stats.set_index("session")
    prior_close_series = session.map(daily_by_session["prior_close"])
    daily_atr_series = session.map(daily_by_session["prior_daily_atr"])

    # 2. Identify 09:30 RTH Open print for each session
    signal_min = _parse_hhmm(cfg.signal_time)
    signal_time_mask = minutes.eq(signal_min)

    # Extract rth_open from first bar of RTH
    rth_open_by_session = rth.groupby(rth["time"].dt.date, sort=True)["open"].first()
    rth_open_series = session.map(rth_open_by_session)

    # 3. Calculate Gap
    gap_points = rth_open_series - prior_close_series
    abs_gap_points = gap_points.abs()
    gap_pct = _safe_divide(gap_points, prior_close_series)
    abs_gap_pct = gap_pct.abs()
    gap_to_atr_ratio = _safe_divide(abs_gap_points, daily_atr_series)

    # 4. Apply Pre-registered Hypothesis Gates
    # Qualifies if |gap| > 0.50% AND |gap in points| > 0.20 * ATR20
    qualifies = (
        signal_time_mask
        & (abs_gap_pct >= float(cfg.min_gap_pct))
        & (gap_to_atr_ratio >= float(cfg.min_gap_to_atr_ratio))
        & prior_close_series.notna()
        & daily_atr_series.notna()
    )

    # Ensure only 1 signal per session (the 09:30 bar)
    first_signal_per_session = _first_true_per_session(qualifies, session)

    # Direction: Fade the gap (Short if gap up, Long if gap down)
    candidate_signal = pd.Series(0.0, index=df.index, dtype=float)
    candidate_signal.loc[first_signal_per_session & (gap_points > 0.0)] = -1.0
    candidate_signal.loc[first_signal_per_session & (gap_points < 0.0)] = 1.0

    # Direction context
    direction = pd.Series("flat", index=df.index, dtype="object")
    direction.loc[candidate_signal > 0.0] = "long"
    direction.loc[candidate_signal < 0.0] = "short"

    gap_direction = pd.Series("none", index=df.index, dtype="object")
    gap_direction.loc[signal_time_mask & (gap_points > 0.0)] = "up"
    gap_direction.loc[signal_time_mask & (gap_points < 0.0)] = "down"

    gap_size_bucket = pd.Series("none", index=df.index, dtype="object")
    gap_size_bucket.loc[abs_gap_pct >= 0.010] = "large_ge_100bps"
    gap_size_bucket.loc[(abs_gap_pct >= 0.005) & (abs_gap_pct < 0.010)] = "medium_50_to_100bps"
    gap_size_bucket.loc[abs_gap_pct < 0.005] = "small_lt_50bps"

    # Score: signed normalized gap magnitude relative to ATR
    gap_fade_score = pd.Series(0.0, index=df.index, dtype=float)
    active_idx = candidate_signal.ne(0.0)
    gap_fade_score.loc[active_idx] = (
        candidate_signal.loc[active_idx] * gap_to_atr_ratio.loc[active_idx]
    )

    stop_points = pd.Series(np.nan, index=df.index, dtype=float)
    target_points = pd.Series(np.nan, index=df.index, dtype=float)
    stop_points.loc[active_idx] = float(cfg.stop_gap_fraction) * abs_gap_points.loc[active_idx]
    raw_target = float(cfg.target_gap_fraction) * abs_gap_points.loc[active_idx]
    if cfg.max_target_points and cfg.max_target_points > 0:
        raw_target = np.minimum(raw_target, float(cfg.max_target_points))
    target_points.loc[active_idx] = raw_target

    out = df.copy()
    out["signal"] = candidate_signal
    out["signal_type"] = np.where(candidate_signal.ne(0.0), "gap_fade", "")
    out["candidate_signal"] = candidate_signal
    out["direction"] = direction
    out["gap_fade_score"] = gap_fade_score
    out["gap_points"] = gap_points
    out["abs_gap_points"] = abs_gap_points
    out["gap_pct"] = gap_pct
    out["abs_gap_pct"] = abs_gap_pct
    out["daily_atr_20"] = daily_atr_series
    out["gap_to_atr_ratio"] = gap_to_atr_ratio
    out["stop_points"] = stop_points
    out["target_points"] = target_points
    out["gap_direction"] = gap_direction
    out["gap_size_bucket"] = gap_size_bucket
    out["session_bucket"] = "rth_open"

    return out


def _daily_rth_stats(rth: pd.DataFrame, *, atr_window: int = 20) -> pd.DataFrame:
    if rth.empty:
        return pd.DataFrame(columns=["session", "prior_close", "prior_daily_atr"])

    session_col = rth["time"].dt.date
    daily = (
        rth.groupby(session_col, sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
        )
        .reset_index(names="session")
    )

    # True Range calculation
    prev_close = daily["close"].shift(1)
    tr1 = daily["high"] - daily["low"]
    tr2 = (daily["high"] - prev_close).abs()
    tr3 = (daily["low"] - prev_close).abs()
    daily["true_range"] = np.nanmax(np.column_stack([tr1, tr2, tr3]), axis=1)

    # 20-day rolling ATR
    min_p = min(atr_window, max(1, atr_window // 4))
    daily["daily_atr"] = daily["true_range"].rolling(window=atr_window, min_periods=min_p).mean()
    # Shift by 1 day for strict Point-In-Time safety (today uses yesterday's ATR and yesterday's close)
    daily["prior_close"] = daily["close"].shift(1)
    daily["prior_daily_atr"] = daily["daily_atr"].shift(1)

    return daily.loc[:, ["session", "prior_close", "prior_daily_atr"]]


def _base_ohlcv_frame(data: pd.DataFrame) -> pd.DataFrame:
    required = ["time", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in data.columns]
    if missing:
        raise ValueError(f"Missing required OHLCV columns: {missing}")

    work = data.copy()
    if "symbol" in work.columns:
        from main_backtest import select_continuous_outright_contract

        work = select_continuous_outright_contract(work, method="prior_session_volume")

    df = work.loc[:, required].copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time", kind="stable").reset_index(drop=True)
    return df


def _parse_hhmm(value: str) -> int:
    hour, minute = str(value).split(":", 1)
    return int(hour) * 60 + int(minute)


def _safe_divide(numerator: pd.Series | np.ndarray, denominator: pd.Series | np.ndarray) -> pd.Series:
    num = pd.Series(numerator)
    den = pd.Series(denominator)
    result = num / den.replace(0.0, np.nan)
    return result.replace([np.inf, -np.inf], np.nan)


def _first_true_per_session(mask: pd.Series, session: pd.Series) -> pd.Series:
    active = mask.fillna(False).astype(bool)
    counts = active.groupby(session).cumsum()
    return active & counts.eq(1)


def _validate_config(cfg: GapFadeSignalConfig) -> None:
    if cfg.min_gap_pct <= 0.0:
        raise ValueError("min_gap_pct must be positive")
    if cfg.min_gap_to_atr_ratio <= 0.0:
        raise ValueError("min_gap_to_atr_ratio must be positive")
    if cfg.atr_window_days <= 0:
        raise ValueError("atr_window_days must be positive")
