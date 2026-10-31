"""
Late-Day Cross-Asset MOC Institutional Imbalance Drive Signal (H11).

Pre-registered in docs/research_hypotheses/2026-10-30_late_day_cross_asset_moc_drive_h11.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_MOC_DRIVE_FEATURE_COLUMNS = (
    "moc_drive_score",
    "nq_session_ret_pct",
    "nq_move_to_range",
    "nq_close_pos",
    "nq_vwap_dist_pct",
    "nq_ret_30m_pct",
    "es_session_ret_pct",
    "es_close_pos",
    "es_ret_30m_pct",
    "tick_5m_close",
    "tick_15m_mean",
    "vx_change_30m",
)

DEFAULT_MOC_DRIVE_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "late_day_subwindow",
    "vx_30m_state",
    "tick_breadth_state",
)


@dataclass(frozen=True)
class LateDayCrossAssetMocDriveConfig:
    rth_start: str = "09:30"
    signal_window_start: str = "14:00"
    signal_window_end: str = "15:30"
    rth_end: str = "16:00"
    momentum_lookback_bars: int = 30
    min_nq_session_ret_pct: float = 0.0040  # 0.40%
    min_nq_move_to_range: float = 0.45
    min_long_nq_close_pos: float = 0.80
    max_short_nq_close_pos: float = 0.20
    min_nq_vwap_dist_pct: float = 0.0005  # 0.05%
    min_nq_ret_30m_pct: float = 0.0008  # 0.08%
    min_es_session_ret_pct: float = 0.0025  # 0.25%
    min_long_es_close_pos: float = 0.70
    max_short_es_close_pos: float = 0.30
    min_es_ret_30m_pct: float = 0.0005  # 0.05%
    min_long_tick_15m_mean: float = 0.0
    min_long_tick_5m_close: float = -200.0
    max_short_tick_15m_mean: float = 0.0
    max_short_tick_5m_close: float = 200.0
    max_long_vx_change_30m: float = 0.05
    min_short_vx_change_30m: float = -0.05
    min_stop_points: float = 15.0
    max_stop_points: float = 60.0
    reward_risk_ratio: float = 1.5
    allow_long: bool = True
    allow_short: bool = True
    es_data_path: str = "data/raw/es_1m_2014_2026_et.parquet"
    tick_data_path: str = "data/processed/macro_context/nyse_tick_5m_et.parquet"
    vx_data_path: str = "data/processed/macro_context/vix_futures_5m_et.parquet"


def build_late_day_cross_asset_moc_drive_signal_export(
    data: pd.DataFrame,
    *,
    config: LateDayCrossAssetMocDriveConfig | None = None,
    es_data: pd.DataFrame | None = None,
    tick_data: pd.DataFrame | None = None,
    vx_data: pd.DataFrame | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_MOC_DRIVE_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_MOC_DRIVE_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_late_day_cross_asset_moc_drive_signal_frame(
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


def build_late_day_cross_asset_moc_drive_signal_frame(
    data: pd.DataFrame,
    *,
    config: LateDayCrossAssetMocDriveConfig | None = None,
    es_data: pd.DataFrame | None = None,
    tick_data: pd.DataFrame | None = None,
    vx_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    cfg = config or LateDayCrossAssetMocDriveConfig()
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
    rth_nq["sess_date"] = rth_nq["time"].dt.date

    # 1. NQ RTH features (cumulative session return, efficiency, close position, VWAP distance, 30m return)
    nq_g = rth_nq.groupby("sess_date", sort=False)
    nq_rth_open = nq_g["open"].transform("first")
    nq_sess_high = nq_g["high"].cummax()
    nq_sess_low = nq_g["low"].cummin()
    nq_sess_range = (nq_sess_high - nq_sess_low).replace(0.0, np.nan)

    nq_tp = (rth_nq["high"] + rth_nq["low"] + rth_nq["close"]) / 3.0
    nq_vol = rth_nq["volume"].clip(lower=1.0)
    nq_vwap = (nq_tp * nq_vol).groupby(rth_nq["sess_date"], sort=False).cumsum() / nq_vol.groupby(
        rth_nq["sess_date"], sort=False
    ).cumsum()

    rth_nq["nq_session_ret_pct"] = (rth_nq["close"] - nq_rth_open) / nq_rth_open.replace(0.0, np.nan)
    rth_nq["nq_move_to_range"] = (rth_nq["close"] - nq_rth_open).abs() / nq_sess_range
    rth_nq["nq_close_pos"] = ((rth_nq["close"] - nq_sess_low) / nq_sess_range).clip(lower=0.0, upper=1.0)
    rth_nq["nq_vwap_dist_pct"] = (rth_nq["close"] - nq_vwap) / rth_nq["close"].replace(0.0, np.nan)
    nq_close_lag30 = nq_g["close"].shift(int(cfg.momentum_lookback_bars))
    rth_nq["nq_ret_30m_pct"] = (rth_nq["close"] - nq_close_lag30) / nq_close_lag30.replace(0.0, np.nan)
    rth_nq["nq_30m_range_points"] = (
        nq_g["high"].transform(lambda s: s.rolling(30, min_periods=15).max())
        - nq_g["low"].transform(lambda s: s.rolling(30, min_periods=15).min())
    )

    # 2. ES 1-minute RTH features aligned by exact timestamp
    es = es_data.loc[:, ["time", "open", "high", "low", "close"]].copy()
    es["time"] = pd.to_datetime(es["time"], errors="coerce").astype("datetime64[ns]")
    es = es.dropna(subset=["time"]).sort_values("time", kind="stable").drop_duplicates("time", keep="last")
    es_min = es["time"].dt.hour * 60 + es["time"].dt.minute
    es_rth = es.loc[es_min.ge(rth_start_min) & es_min.le(rth_end_min)].copy()
    es_rth["sess_date"] = es_rth["time"].dt.date
    es_g = es_rth.groupby("sess_date", sort=False)

    es_rth_open = es_g["open"].transform("first")
    es_sess_high = es_g["high"].cummax()
    es_sess_low = es_g["low"].cummin()
    es_sess_range = (es_sess_high - es_sess_low).replace(0.0, np.nan)
    es_close_lag30 = es_g["close"].shift(int(cfg.momentum_lookback_bars))

    es_rth["es_session_ret_pct"] = (es_rth["close"] - es_rth_open) / es_rth_open.replace(0.0, np.nan)
    es_rth["es_close_pos"] = ((es_rth["close"] - es_sess_low) / es_sess_range).clip(lower=0.0, upper=1.0)
    es_rth["es_ret_30m_pct"] = (es_rth["close"] - es_close_lag30) / es_close_lag30.replace(0.0, np.nan)

    rth_merged = rth_nq.merge(
        es_rth[["time", "es_session_ret_pct", "es_close_pos", "es_ret_30m_pct"]],
        on="time",
        how="left",
    ).sort_values("time", kind="stable")

    # 3. 5-Minute NYSE $TICK features (completed at bar_start + 4m, backward-asof aligned within session)
    tick = tick_data.loc[:, ["time", "open", "high", "low", "close"]].copy()
    tick["time"] = pd.to_datetime(tick["time"], errors="coerce").astype("datetime64[ns]")
    tick = tick.dropna(subset=["time"]).sort_values("time", kind="stable").drop_duplicates("time", keep="last")
    tick["sess_date"] = tick["time"].dt.date
    tick["tick_5m_close"] = pd.to_numeric(tick["close"], errors="coerce")
    tick["tick_15m_mean"] = (
        tick.groupby("sess_date", sort=False)["tick_5m_close"]
        .transform(lambda s: s.rolling(3, min_periods=3).mean())
    )
    tick["completion_time"] = (tick["time"] + pd.Timedelta(minutes=4)).astype("datetime64[ns]")
    tick_asof = tick[["completion_time", "sess_date", "tick_5m_close", "tick_15m_mean"]].sort_values(
        "completion_time", kind="stable"
    )

    rth_merged = pd.merge_asof(
        rth_merged,
        tick_asof,
        left_on="time",
        right_on="completion_time",
        by="sess_date",
        direction="backward",
    ).drop(columns=["completion_time"])

    # 4. 5-Minute VIX Futures (VX) features (completed at bar_start + 4m, backward-asof aligned within session)
    vx = vx_data.loc[:, ["time", "open", "high", "low", "close"]].copy()
    vx["time"] = pd.to_datetime(vx["time"], errors="coerce").astype("datetime64[ns]")
    vx = vx.dropna(subset=["time"]).sort_values("time", kind="stable").drop_duplicates("time", keep="last")
    vx_min = vx["time"].dt.hour * 60 + vx["time"].dt.minute
    vx_rth = vx.loc[vx_min.ge(rth_start_min) & vx_min.le(rth_end_min)].copy()
    vx_rth["sess_date"] = vx_rth["time"].dt.date
    vx_rth["vx_close"] = pd.to_numeric(vx_rth["close"], errors="coerce")
    vx_rth["vx_change_30m"] = (
        vx_rth["vx_close"] - vx_rth.groupby("sess_date", sort=False)["vx_close"].shift(6)
    )
    vx_rth["completion_time"] = (vx_rth["time"] + pd.Timedelta(minutes=4)).astype("datetime64[ns]")
    vx_asof = vx_rth[["completion_time", "sess_date", "vx_close", "vx_change_30m"]].sort_values(
        "completion_time", kind="stable"
    )

    rth_merged = pd.merge_asof(
        rth_merged,
        vx_asof,
        left_on="time",
        right_on="completion_time",
        by="sess_date",
        direction="backward",
    ).drop(columns=["completion_time"])

    # 5. Evaluate entry conditions in [14:00..15:30] ET
    m_rth = rth_merged["time"].dt.hour * 60 + rth_merged["time"].dt.minute
    in_window = m_rth.ge(sig_start_min) & m_rth.le(sig_end_min)

    long_cond = (
        bool(cfg.allow_long)
        & in_window
        & (rth_merged["nq_session_ret_pct"] >= float(cfg.min_nq_session_ret_pct))
        & (rth_merged["nq_move_to_range"] >= float(cfg.min_nq_move_to_range))
        & (rth_merged["nq_close_pos"] >= float(cfg.min_long_nq_close_pos))
        & (rth_merged["nq_vwap_dist_pct"] >= float(cfg.min_nq_vwap_dist_pct))
        & (rth_merged["nq_ret_30m_pct"] >= float(cfg.min_nq_ret_30m_pct))
        & (rth_merged["es_session_ret_pct"] >= float(cfg.min_es_session_ret_pct))
        & (rth_merged["es_close_pos"] >= float(cfg.min_long_es_close_pos))
        & (rth_merged["es_ret_30m_pct"] >= float(cfg.min_es_ret_30m_pct))
        & (rth_merged["tick_15m_mean"] >= float(cfg.min_long_tick_15m_mean))
        & (rth_merged["tick_5m_close"] >= float(cfg.min_long_tick_5m_close))
        & (rth_merged["vx_change_30m"] <= float(cfg.max_long_vx_change_30m))
    )

    short_cond = (
        bool(cfg.allow_short)
        & in_window
        & (rth_merged["nq_session_ret_pct"] <= -float(cfg.min_nq_session_ret_pct))
        & (rth_merged["nq_move_to_range"] >= float(cfg.min_nq_move_to_range))
        & (rth_merged["nq_close_pos"] <= float(cfg.max_short_nq_close_pos))
        & (rth_merged["nq_vwap_dist_pct"] <= -float(cfg.min_nq_vwap_dist_pct))
        & (rth_merged["nq_ret_30m_pct"] <= -float(cfg.min_nq_ret_30m_pct))
        & (rth_merged["es_session_ret_pct"] <= -float(cfg.min_es_session_ret_pct))
        & (rth_merged["es_close_pos"] <= float(cfg.max_short_es_close_pos))
        & (rth_merged["es_ret_30m_pct"] <= -float(cfg.min_es_ret_30m_pct))
        & (rth_merged["tick_15m_mean"] <= float(cfg.max_short_tick_15m_mean))
        & (rth_merged["tick_5m_close"] <= float(cfg.max_short_tick_5m_close))
        & (rth_merged["vx_change_30m"] >= float(cfg.min_short_vx_change_30m))
    )

    raw_sig = pd.Series(0.0, index=rth_merged.index, dtype=float)
    raw_sig.loc[long_cond] = 1.0
    raw_sig.loc[short_cond & raw_sig.eq(0.0)] = -1.0

    # Deduplicate to maximum 1 signal per session (first bar satisfying all criteria)
    rth_merged["raw_sig"] = raw_sig
    qualifying = rth_merged.loc[rth_merged["raw_sig"] != 0.0]
    first_per_session_idx = qualifying.groupby("sess_date", sort=False).head(1).index

    rth_sig = pd.Series(0.0, index=rth_merged.index, dtype=float)
    rth_sig.loc[first_per_session_idx] = rth_merged.loc[first_per_session_idx, "raw_sig"]
    rth_merged["candidate_signal"] = rth_sig

    merge_back_cols = [
        "time",
        "candidate_signal",
        "nq_session_ret_pct",
        "nq_move_to_range",
        "nq_close_pos",
        "nq_vwap_dist_pct",
        "nq_ret_30m_pct",
        "nq_30m_range_points",
        "es_session_ret_pct",
        "es_close_pos",
        "es_ret_30m_pct",
        "tick_5m_close",
        "tick_15m_mean",
        "vx_change_30m",
    ]
    out = df.merge(rth_merged[merge_back_cols], on="time", how="left")
    out["candidate_signal"] = out["candidate_signal"].fillna(0.0)

    active_idx = out["candidate_signal"].ne(0.0)
    direction = pd.Series("flat", index=out.index, dtype="object")
    direction.loc[out["candidate_signal"] > 0.0] = "long"
    direction.loc[out["candidate_signal"] < 0.0] = "short"

    # Composite signed score on active bars
    moc_drive_score = pd.Series(0.0, index=out.index, dtype=float)
    if active_idx.any():
        act = out.loc[active_idx]
        dir_close_es = np.where(act["candidate_signal"] > 0.0, act["es_close_pos"], 1.0 - act["es_close_pos"])
        mom_norm = (act["nq_ret_30m_pct"].abs() / max(float(cfg.min_nq_ret_30m_pct), 1e-6)).clip(upper=5.0)
        tick_norm = (act["tick_15m_mean"].abs() / 250.0).clip(upper=3.0)
        raw_mag = (act["nq_move_to_range"].clip(0.0, 1.0) + pd.Series(dir_close_es, index=act.index) + mom_norm + tick_norm) / 4.0
        moc_drive_score.loc[active_idx] = act["candidate_signal"] * raw_mag

    stop_points = pd.Series(np.nan, index=out.index, dtype=float)
    target_points = pd.Series(np.nan, index=out.index, dtype=float)
    clipped_stop = out.loc[active_idx, "nq_30m_range_points"].clip(
        lower=float(cfg.min_stop_points),
        upper=float(cfg.max_stop_points),
    )
    stop_points.loc[active_idx] = clipped_stop
    target_points.loc[active_idx] = clipped_stop * float(cfg.reward_risk_ratio)

    out_min = out["time"].dt.hour * 60 + out["time"].dt.minute
    late_day_subwindow = pd.Series("none", index=out.index, dtype="object")
    late_day_subwindow.loc[active_idx & out_min.lt(15 * 60)] = "hour_14_pre_moc"
    late_day_subwindow.loc[active_idx & out_min.ge(15 * 60)] = "hour_15_power_hour"

    vx_30m_state = pd.Series("none", index=out.index, dtype="object")
    vx_30m_state.loc[active_idx & (out["vx_change_30m"] <= -0.10)] = "vx_crushing"
    vx_30m_state.loc[active_idx & (out["vx_change_30m"] > -0.10) & (out["vx_change_30m"] < 0.10)] = "vx_flat"
    vx_30m_state.loc[active_idx & (out["vx_change_30m"] >= 0.10)] = "vx_expanding"

    tick_breadth_state = pd.Series("none", index=out.index, dtype="object")
    tick_breadth_state.loc[active_idx & (out["tick_15m_mean"].abs() >= 200.0)] = "strong_breadth_200plus"
    tick_breadth_state.loc[active_idx & (out["tick_15m_mean"].abs() < 200.0)] = "moderate_breadth_0_200"

    out["signal"] = out["candidate_signal"]
    out["signal_type"] = np.where(active_idx, "late_day_cross_asset_moc_drive", "")
    out["direction"] = direction
    out["moc_drive_score"] = moc_drive_score
    out["stop_points"] = stop_points
    out["target_points"] = target_points
    out["late_day_subwindow"] = late_day_subwindow
    out["vx_30m_state"] = vx_30m_state
    out["tick_breadth_state"] = tick_breadth_state
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
    df["time"] = pd.to_datetime(df["time"], errors="coerce").astype("datetime64[ns]")
    df = df.dropna(subset=["time"]).sort_values("time", kind="stable").reset_index(drop=True)
    return df


def _parse_hhmm(value: str) -> int:
    hour, minute = str(value).split(":", 1)
    return int(hour) * 60 + int(minute)
