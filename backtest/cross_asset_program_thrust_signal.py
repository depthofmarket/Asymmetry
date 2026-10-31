"""
Cross-Asset Institutional Program Thrust Signal ($TICK + VX + ES/NQ Lockstep, H10).

Pre-registered in docs/research_hypotheses/2026-10-30_cross_asset_program_thrust_h10.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_CROSS_ASSET_THRUST_FEATURE_COLUMNS = (
    "program_thrust_score",
    "nq_15m_return_pct",
    "es_15m_return_pct",
    "nq_15m_close_location",
    "es_15m_close_location",
    "tick_5m_close",
    "tick_15m_mean",
    "vx_15m_change",
    "vx_change_from_open",
)

DEFAULT_CROSS_ASSET_THRUST_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "thrust_window",
    "vx_regime",
)


@dataclass(frozen=True)
class CrossAssetProgramThrustConfig:
    rth_start: str = "09:30"
    signal_window_start: str = "10:09"
    signal_window_end: str = "14:29"
    rth_end: str = "16:00"
    min_nq_15m_return_pct: float = 0.0010  # 0.10%
    min_long_close_location: float = 0.65
    max_short_close_location: float = 0.35
    min_long_tick_5m_high: float = 500.0
    min_long_tick_5m_close: float = 200.0
    min_long_tick_15m_mean: float = 100.0
    max_short_tick_5m_low: float = -500.0
    max_short_tick_5m_close: float = -200.0
    max_short_tick_15m_mean: float = -100.0
    min_stop_points: float = 15.0
    max_stop_points: float = 60.0
    reward_risk_ratio: float = 1.5
    allow_long: bool = True
    allow_short: bool = True
    es_data_path: str = "data/raw/es_1m_2014_2026_et.parquet"
    tick_data_path: str = "data/processed/macro_context/nyse_tick_5m_et.parquet"
    vx_data_path: str = "data/processed/macro_context/vix_futures_5m_et.parquet"


def build_cross_asset_program_thrust_signal_export(
    data: pd.DataFrame,
    *,
    config: CrossAssetProgramThrustConfig | None = None,
    es_data: pd.DataFrame | None = None,
    tick_data: pd.DataFrame | None = None,
    vx_data: pd.DataFrame | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_CROSS_ASSET_THRUST_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_CROSS_ASSET_THRUST_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_cross_asset_program_thrust_signal_frame(
        data,
        config=config,
        es_data=es_data,
        tick_data=tick_data,
        vx_data=vx_data,
    )
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_cross_asset_program_thrust_signal_frame(
    data: pd.DataFrame,
    *,
    config: CrossAssetProgramThrustConfig | None = None,
    es_data: pd.DataFrame | None = None,
    tick_data: pd.DataFrame | None = None,
    vx_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    cfg = config or CrossAssetProgramThrustConfig()
    df = _base_ohlcv_frame(data)

    if es_data is None:
        es_data = pd.read_parquet(cfg.es_data_path)
    if tick_data is None:
        tick_data = pd.read_parquet(cfg.tick_data_path)
    if vx_data is None:
        vx_data = pd.read_parquet(cfg.vx_data_path)

    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    rth_start_min = _parse_hhmm(cfg.rth_start)
    sig_start_min = _parse_hhmm(cfg.signal_window_start)
    sig_end_min = _parse_hhmm(cfg.signal_window_end)
    rth_end_min = _parse_hhmm(cfg.rth_end)

    rth_mask = minutes.ge(rth_start_min) & minutes.le(rth_end_min)
    rth_nq = df.loc[rth_mask, ["time", "open", "high", "low", "close", "volume"]].copy()
    nq_sess = rth_nq["time"].dt.date

    # 1. NQ RTH features (15m impulse, prior 30m consolidation, cumulative RTH VWAP)
    nq_tp = (rth_nq["high"] + rth_nq["low"] + rth_nq["close"]) / 3.0
    nq_pv = nq_tp * rth_nq["volume"].clip(lower=1.0)
    rth_nq["nq_vwap"] = (
        nq_pv.groupby(nq_sess).cumsum() / rth_nq["volume"].clip(lower=1.0).groupby(nq_sess).cumsum()
    )

    nq_g = rth_nq.groupby(nq_sess, sort=False)
    nq_open_15m = nq_g["open"].shift(14)
    nq_high_15m = nq_g["high"].transform(lambda s: s.rolling(15, min_periods=15).max())
    nq_low_15m = nq_g["low"].transform(lambda s: s.rolling(15, min_periods=15).min())
    nq_range_15m = (nq_high_15m - nq_low_15m).replace(0.0, np.nan)
    rth_nq["nq_15m_return_pct"] = (rth_nq["close"] - nq_open_15m) / nq_open_15m.replace(0.0, np.nan)
    rth_nq["nq_15m_close_location"] = (rth_nq["close"] - nq_low_15m) / nq_range_15m
    rth_nq["nq_15m_range_points"] = nq_range_15m
    rth_nq["nq_prior30_high"] = nq_g["high"].transform(lambda s: s.shift(5).rolling(30, min_periods=20).max())
    rth_nq["nq_prior30_low"] = nq_g["low"].transform(lambda s: s.shift(5).rolling(30, min_periods=20).min())

    # 2. ES 1-minute features aligned by exact 1-minute timestamp
    es = es_data.loc[:, ["time", "open", "high", "low", "close"]].copy()
    es["time"] = pd.to_datetime(es["time"], errors="coerce")
    es = es.dropna(subset=["time"]).sort_values("time", kind="stable").drop_duplicates("time", keep="last")
    es_min = es["time"].dt.hour * 60 + es["time"].dt.minute
    es_rth = es.loc[es_min.ge(rth_start_min) & es_min.le(rth_end_min)].copy()
    es_sess = es_rth["time"].dt.date
    es_g = es_rth.groupby(es_sess, sort=False)

    es_open_15m = es_g["open"].shift(14)
    es_high_15m = es_g["high"].transform(lambda s: s.rolling(15, min_periods=15).max())
    es_low_15m = es_g["low"].transform(lambda s: s.rolling(15, min_periods=15).min())
    es_range_15m = (es_high_15m - es_low_15m).replace(0.0, np.nan)
    es_rth["es_close"] = es_rth["close"]
    es_rth["es_15m_return_pct"] = (es_rth["close"] - es_open_15m) / es_open_15m.replace(0.0, np.nan)
    es_rth["es_15m_close_location"] = (es_rth["close"] - es_low_15m) / es_range_15m
    es_rth["es_prior30_high"] = es_g["high"].transform(lambda s: s.shift(5).rolling(30, min_periods=20).max())
    es_rth["es_prior30_low"] = es_g["low"].transform(lambda s: s.shift(5).rolling(30, min_periods=20).min())

    es_feat_cols = [
        "time",
        "es_close",
        "es_15m_return_pct",
        "es_15m_close_location",
        "es_prior30_high",
        "es_prior30_low",
    ]
    rth_merged = rth_nq.merge(es_rth[es_feat_cols], on="time", how="left")

    # 3. 5-Minute NYSE $TICK features (stamped at 5m bar start -> completed at +4 minutes)
    tick = tick_data.loc[:, ["time", "open", "high", "low", "close"]].copy()
    tick["time"] = pd.to_datetime(tick["time"], errors="coerce")
    tick = tick.dropna(subset=["time"]).sort_values("time", kind="stable").drop_duplicates("time", keep="last")
    tick_sess = tick["time"].dt.date
    tick["tick_5m_high"] = pd.to_numeric(tick["high"], errors="coerce")
    tick["tick_5m_low"] = pd.to_numeric(tick["low"], errors="coerce")
    tick["tick_5m_close"] = pd.to_numeric(tick["close"], errors="coerce")
    tick["tick_15m_mean"] = (
        tick.groupby(tick_sess, sort=False)["tick_5m_close"]
        .transform(lambda s: s.rolling(3, min_periods=3).mean())
    )
    tick["completion_time"] = tick["time"] + pd.Timedelta(minutes=4)
    tick_feat = tick[["completion_time", "tick_5m_high", "tick_5m_low", "tick_5m_close", "tick_15m_mean"]].rename(
        columns={"completion_time": "time"}
    )
    rth_merged = rth_merged.merge(tick_feat, on="time", how="left")

    # 4. 5-Minute VIX Futures (VX) features (stamped at 5m bar start -> completed at +4 minutes)
    vx = vx_data.loc[:, ["time", "open", "high", "low", "close"]].copy()
    vx["time"] = pd.to_datetime(vx["time"], errors="coerce")
    vx = vx.dropna(subset=["time"]).sort_values("time", kind="stable").drop_duplicates("time", keep="last")
    vx_min = vx["time"].dt.hour * 60 + vx["time"].dt.minute
    vx_rth = vx.loc[vx_min.ge(rth_start_min) & vx_min.le(rth_end_min)].copy()
    vx_sess = vx_rth["time"].dt.date
    vx_open_930_map = (
        vx_rth.loc[vx_min.eq(rth_start_min)]
        .groupby(vx_rth.loc[vx_min.eq(rth_start_min), "time"].dt.date)["open"]
        .first()
    )
    vx_rth["vx_open_930"] = vx_sess.map(vx_open_930_map)
    vx_rth["vx_close"] = pd.to_numeric(vx_rth["close"], errors="coerce")
    vx_rth["vx_15m_change"] = vx_rth["vx_close"] - vx_rth.groupby(vx_sess, sort=False)["vx_close"].shift(3)
    vx_rth["vx_change_from_open"] = vx_rth["vx_close"] - vx_rth["vx_open_930"]
    vx_rth["completion_time"] = vx_rth["time"] + pd.Timedelta(minutes=4)
    vx_feat = vx_rth[["completion_time", "vx_close", "vx_open_930", "vx_15m_change", "vx_change_from_open"]].rename(
        columns={"completion_time": "time"}
    )
    rth_merged = rth_merged.merge(vx_feat, on="time", how="left")

    # 5. Evaluate entry conditions on completed 5-minute boundaries (minute % 5 == 4) in [10:09..14:29]
    m_rth = rth_merged["time"].dt.hour * 60 + rth_merged["time"].dt.minute
    in_window = (
        m_rth.ge(sig_start_min)
        & m_rth.le(sig_end_min)
        & ((rth_merged["time"].dt.minute % 5) == 4)
    )

    long_cond = (
        bool(cfg.allow_long)
        & in_window
        & (rth_merged["close"] > rth_merged["nq_prior30_high"])
        & (rth_merged["es_close"] > rth_merged["es_prior30_high"])
        & (rth_merged["nq_15m_return_pct"] >= float(cfg.min_nq_15m_return_pct))
        & (rth_merged["es_15m_return_pct"] > 0.0)
        & (rth_merged["nq_15m_close_location"] >= float(cfg.min_long_close_location))
        & (rth_merged["es_15m_close_location"] >= float(cfg.min_long_close_location))
        & (rth_merged["close"] > rth_merged["nq_vwap"])
        & (rth_merged["tick_5m_high"] >= float(cfg.min_long_tick_5m_high))
        & (rth_merged["tick_5m_close"] >= float(cfg.min_long_tick_5m_close))
        & (rth_merged["tick_15m_mean"] >= float(cfg.min_long_tick_15m_mean))
        & (rth_merged["vx_15m_change"] <= 0.0)
        & (rth_merged["vx_change_from_open"] <= 0.0)
    )

    short_cond = (
        bool(cfg.allow_short)
        & in_window
        & (rth_merged["close"] < rth_merged["nq_prior30_low"])
        & (rth_merged["es_close"] < rth_merged["es_prior30_low"])
        & (rth_merged["nq_15m_return_pct"] <= -float(cfg.min_nq_15m_return_pct))
        & (rth_merged["es_15m_return_pct"] < 0.0)
        & (rth_merged["nq_15m_close_location"] <= float(cfg.max_short_close_location))
        & (rth_merged["es_15m_close_location"] <= float(cfg.max_short_close_location))
        & (rth_merged["close"] < rth_merged["nq_vwap"])
        & (rth_merged["tick_5m_low"] <= float(cfg.max_short_tick_5m_low))
        & (rth_merged["tick_5m_close"] <= float(cfg.max_short_tick_5m_close))
        & (rth_merged["tick_15m_mean"] <= float(cfg.max_short_tick_15m_mean))
        & (rth_merged["vx_15m_change"] >= 0.0)
        & (rth_merged["vx_change_from_open"] >= 0.0)
    )

    raw_sig = pd.Series(0.0, index=rth_merged.index, dtype=float)
    raw_sig.loc[long_cond] = 1.0
    raw_sig.loc[short_cond & raw_sig.eq(0.0)] = -1.0

    # Deduplicate to maximum 1 signal per trading session (first trigger of the day)
    rth_merged["raw_sig"] = raw_sig
    rth_merged["sess_date"] = rth_merged["time"].dt.date
    qualifying = rth_merged.loc[rth_merged["raw_sig"] != 0.0]
    first_per_session_idx = qualifying.groupby("sess_date", sort=False).head(1).index

    rth_sig = pd.Series(0.0, index=rth_merged.index, dtype=float)
    rth_sig.loc[first_per_session_idx] = rth_merged.loc[first_per_session_idx, "raw_sig"]
    rth_merged["candidate_signal"] = rth_sig

    # Map back onto full DataFrame
    merge_back_cols = [
        "time",
        "candidate_signal",
        "nq_15m_return_pct",
        "es_15m_return_pct",
        "nq_15m_close_location",
        "es_15m_close_location",
        "nq_15m_range_points",
        "tick_5m_close",
        "tick_15m_mean",
        "vx_15m_change",
        "vx_change_from_open",
    ]
    out = df.merge(rth_merged[merge_back_cols], on="time", how="left")
    out["candidate_signal"] = out["candidate_signal"].fillna(0.0)

    active_idx = out["candidate_signal"].ne(0.0)
    direction = pd.Series("flat", index=out.index, dtype="object")
    direction.loc[out["candidate_signal"] > 0.0] = "long"
    direction.loc[out["candidate_signal"] < 0.0] = "short"

    program_thrust_score = pd.Series(0.0, index=out.index, dtype=float)
    program_thrust_score.loc[active_idx] = (
        out.loc[active_idx, "candidate_signal"]
        * out.loc[active_idx, "nq_15m_return_pct"].abs()
        * 100.0
        * (out.loc[active_idx, "tick_15m_mean"].abs() / 200.0)
    )

    stop_points = pd.Series(np.nan, index=out.index, dtype=float)
    target_points = pd.Series(np.nan, index=out.index, dtype=float)
    clipped_stop = out.loc[active_idx, "nq_15m_range_points"].clip(
        lower=float(cfg.min_stop_points),
        upper=float(cfg.max_stop_points),
    )
    stop_points.loc[active_idx] = clipped_stop
    target_points.loc[active_idx] = clipped_stop * float(cfg.reward_risk_ratio)

    out_min = out["time"].dt.hour * 60 + out["time"].dt.minute
    thrust_window = pd.Series("none", index=out.index, dtype="object")
    thrust_window.loc[active_idx & out_min.le(11 * 60 + 30)] = "morning_1009_1130"
    thrust_window.loc[active_idx & out_min.gt(11 * 60 + 30) & out_min.le(13 * 60)] = "midday_1131_1300"
    thrust_window.loc[active_idx & out_min.gt(13 * 60)] = "afternoon_1301_1429"

    vx_regime = pd.Series("none", index=out.index, dtype="object")
    vx_regime.loc[active_idx & (out["vx_change_from_open"] <= -0.15)] = "strong_vx_crush"
    vx_regime.loc[active_idx & (out["vx_change_from_open"] > -0.15) & (out["vx_change_from_open"] <= 0.0)] = "mild_vx_compression"
    vx_regime.loc[active_idx & (out["vx_change_from_open"] > 0.0) & (out["vx_change_from_open"] < 0.15)] = "mild_vx_expansion"
    vx_regime.loc[active_idx & (out["vx_change_from_open"] >= 0.15)] = "strong_vx_spike"

    out["signal"] = out["candidate_signal"]
    out["signal_type"] = np.where(active_idx, "cross_asset_program_thrust", "")
    out["direction"] = direction
    out["program_thrust_score"] = program_thrust_score
    out["stop_points"] = stop_points
    out["target_points"] = target_points
    out["thrust_window"] = thrust_window
    out["vx_regime"] = vx_regime
    out["session_bucket"] = np.where(out_min.le(11 * 60 + 30), "rth_morning", "rth_afternoon")
    return out


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
