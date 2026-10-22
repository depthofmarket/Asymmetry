from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_FIRST30MIN_MOMENTUM_FEATURE_COLUMNS = (
    "first15_return_pct",
    "abs_first15_return_pct",
    "first15_return_points",
    "prior_rth_atr14_points",
    "first15_momentum_score",
)

DEFAULT_FIRST30MIN_MOMENTUM_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "momentum_direction",
)


@dataclass(frozen=True)
class First30MinMomentumConfig:
    min_abs_return_pct: float = 0.0010  # 0.10%
    stop_atr_multiplier: float = 2.0
    atr_period: int = 14
    rth_start: str = "09:30"
    signal_bar_time: str = "09:44"  # 09:30..09:44 inclusive = first 15 1-min bars
    rth_end: str = "16:00"


def build_first30min_momentum_signal_export(
    data: pd.DataFrame,
    *,
    config: First30MinMomentumConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_FIRST30MIN_MOMENTUM_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_FIRST30MIN_MOMENTUM_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_first30min_momentum_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_first30min_momentum_signal_frame(
    data: pd.DataFrame,
    *,
    config: First30MinMomentumConfig | None = None,
) -> pd.DataFrame:
    cfg = config or First30MinMomentumConfig()
    df = _base_ohlcv_frame(data)

    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    rth_start_min = _parse_hhmm(cfg.rth_start)
    signal_min = _parse_hhmm(cfg.signal_bar_time)
    rth_end_min = _parse_hhmm(cfg.rth_end)

    rth_mask = minutes.ge(rth_start_min) & minutes.le(rth_end_min)
    rth = df.loc[rth_mask].copy()
    session = df["time"].dt.date

    # Prior session 1-minute ATR(14) at close of prior RTH session (point-in-time safe)
    prior_atr_by_session = _prior_session_rth_atr(rth, atr_period=cfg.atr_period)
    prior_atr_series = session.map(prior_atr_by_session)

    # 09:30 bar open for each session
    open_930_by_session = (
        df.loc[minutes.eq(rth_start_min)]
        .groupby(df.loc[minutes.eq(rth_start_min), "time"].dt.date, sort=True)["open"]
        .first()
    )
    open_930_series = session.map(open_930_by_session)

    # At 09:44 bar close, compute return from 09:30 open
    ret_points = df["close"] - open_930_series
    ret_pct = ret_points / open_930_series.replace(0.0, np.nan)
    abs_ret_pct = ret_pct.abs()

    signal_time_mask = minutes.eq(signal_min)
    qualifies = (
        signal_time_mask
        & open_930_series.notna()
        & abs_ret_pct.ge(float(cfg.min_abs_return_pct))
    )

    candidate_signal = pd.Series(0.0, index=df.index, dtype=float)
    candidate_signal.loc[qualifies & ret_pct.gt(0.0)] = 1.0
    candidate_signal.loc[qualifies & ret_pct.lt(0.0)] = -1.0

    direction = pd.Series("flat", index=df.index, dtype="object")
    direction.loc[candidate_signal > 0.0] = "long"
    direction.loc[candidate_signal < 0.0] = "short"

    momentum_direction = pd.Series("none", index=df.index, dtype="object")
    momentum_direction.loc[signal_time_mask & ret_pct.gt(0.0)] = "up"
    momentum_direction.loc[signal_time_mask & ret_pct.lt(0.0)] = "down"

    first15_momentum_score = pd.Series(0.0, index=df.index, dtype=float)
    active_idx = candidate_signal.ne(0.0)
    first15_momentum_score.loc[active_idx] = ret_pct.loc[active_idx] * 100.0

    stop_points = pd.Series(np.nan, index=df.index, dtype=float)
    stop_points.loc[active_idx] = float(cfg.stop_atr_multiplier) * prior_atr_series.loc[active_idx]

    out = df.copy()
    out["signal"] = candidate_signal
    out["signal_type"] = np.where(active_idx, "first30min_momentum", "")
    out["candidate_signal"] = candidate_signal
    out["direction"] = direction
    out["first15_return_pct"] = np.where(signal_time_mask, ret_pct, np.nan)
    out["abs_first15_return_pct"] = np.where(signal_time_mask, abs_ret_pct, np.nan)
    out["first15_return_points"] = np.where(signal_time_mask, ret_points, np.nan)
    out["prior_rth_atr14_points"] = prior_atr_series
    out["first15_momentum_score"] = first15_momentum_score
    out["stop_points"] = stop_points
    out["target_points"] = np.nan
    out["momentum_direction"] = momentum_direction
    out["session_bucket"] = "rth_open"
    return out


def _prior_session_rth_atr(rth: pd.DataFrame, *, atr_period: int = 14) -> pd.Series:
    if rth.empty:
        return pd.Series(dtype=float)
    work = rth.sort_values("time", kind="stable").copy()
    session_col = work["time"].dt.date
    prev_close = work.groupby(session_col)["close"].shift(1)
    tr1 = work["high"] - work["low"]
    tr2 = (work["high"] - prev_close).abs()
    tr3 = (work["low"] - prev_close).abs()
    work["tr"] = np.nanmax(np.column_stack([tr1, tr2, tr3]), axis=1)
    work["atr14"] = (
        work.groupby(session_col)["tr"]
        .transform(lambda s: s.rolling(window=atr_period, min_periods=max(1, atr_period // 2)).mean())
    )
    eod_atr = work.groupby(session_col, sort=True)["atr14"].last()
    return eod_atr.shift(1)


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
