"""
ES vs. NQ Intermarket SMT Divergence + $TICK Exhaustion Reversal Signal (H12).

Pre-registered in docs/research_hypotheses/2026-10-30_es_nq_smt_tick_divergence_h12.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_SMT_DIVERGENCE_FEATURE_COLUMNS = (
    "smt_divergence_score",
    "nq_5m_close_pos",
    "es_5m_close_pos",
    "nq_vwap_dist_pct",
    "tick_5m_close",
    "tick_15m_mean",
    "vx_15m_change",
)

DEFAULT_SMT_DIVERGENCE_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "smt_leader",
    "vwap_alignment",
    "smt_window",
)


@dataclass(frozen=True)
class EsNqSmtTickDivergenceConfig:
    rth_start: str = "09:30"
    signal_window_start: str = "10:20"
    signal_window_end: str = "14:00"
    rth_end: str = "16:00"
    prior_window_bars: int = 45
    sweep_window_bars: int = 5
    min_long_5m_close_pos: float = 0.55
    max_short_5m_close_pos: float = 0.45
    min_long_tick_5m_close: float = -150.0
    min_long_tick_15m_mean: float = -200.0
    max_short_tick_5m_close: float = 150.0
    max_short_tick_15m_mean: float = 200.0
    max_long_vx_15m_change: float = 0.05
    min_short_vx_15m_change: float = -0.05
    min_stop_points: float = 12.0
    max_stop_points: float = 50.0
    reward_risk_ratio: float = 1.5
    allow_long: bool = True
    allow_short: bool = True
    es_data_path: str = "data/raw/es_1m_2014_2026_et.parquet"
    tick_data_path: str = "data/processed/macro_context/nyse_tick_5m_et.parquet"
    vx_data_path: str = "data/processed/macro_context/vix_futures_5m_et.parquet"


def build_es_nq_smt_tick_divergence_signal_export(
    data: pd.DataFrame,
    *,
    config: EsNqSmtTickDivergenceConfig | None = None,
    es_data: pd.DataFrame | None = None,
    tick_data: pd.DataFrame | None = None,
    vx_data: pd.DataFrame | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_SMT_DIVERGENCE_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_SMT_DIVERGENCE_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_es_nq_smt_tick_divergence_signal_frame(
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


def build_es_nq_smt_tick_divergence_signal_frame(
    data: pd.DataFrame,
    *,
    config: EsNqSmtTickDivergenceConfig | None = None,
    es_data: pd.DataFrame | None = None,
    tick_data: pd.DataFrame | None = None,
    vx_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    cfg = config or EsNqSmtTickDivergenceConfig()
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

    # 1. NQ structural windows (prior 45m [t-50..t-5] vs recent 5m [t-4..t]) & RTH VWAP
    sw = int(cfg.sweep_window_bars)
    pw = int(cfg.prior_window_bars)
    nq_g = rth_nq.groupby("sess_date", sort=False)

    nq_tp = (rth_nq["high"] + rth_nq["low"] + rth_nq["close"]) / 3.0
    nq_vol = rth_nq["volume"].clip(lower=1.0)
    nq_vwap = (nq_tp * nq_vol).groupby(rth_nq["sess_date"], sort=False).cumsum() / nq_vol.groupby(
        rth_nq["sess_date"], sort=False
    ).cumsum()

    rth_nq["nq_vwap"] = nq_vwap
    rth_nq["nq_vwap_dist_pct"] = (rth_nq["close"] - nq_vwap) / rth_nq["close"].replace(0.0, np.nan)
    rth_nq["nq_recent5_high"] = nq_g["high"].transform(lambda s: s.rolling(sw, min_periods=sw).max())
    rth_nq["nq_recent5_low"] = nq_g["low"].transform(lambda s: s.rolling(sw, min_periods=sw).min())
    rth_nq["nq_prior45_high"] = nq_g["high"].transform(lambda s: s.shift(sw).rolling(pw, min_periods=pw).max())
    rth_nq["nq_prior45_low"] = nq_g["low"].transform(lambda s: s.shift(sw).rolling(pw, min_periods=pw).min())

    nq_5m_range = (rth_nq["nq_recent5_high"] - rth_nq["nq_recent5_low"]).replace(0.0, np.nan)
    rth_nq["nq_5m_close_pos"] = ((rth_nq["close"] - rth_nq["nq_recent5_low"]) / nq_5m_range).clip(0.0, 1.0)
    rth_nq["nq_5m_range_points"] = nq_5m_range

    # 2. ES 1-minute structural windows aligned by exact timestamp
    es = es_data.loc[:, ["time", "open", "high", "low", "close"]].copy()
    es["time"] = pd.to_datetime(es["time"], errors="coerce").astype("datetime64[ns]")
    es = es.dropna(subset=["time"]).sort_values("time", kind="stable").drop_duplicates("time", keep="last")
    es_min = es["time"].dt.hour * 60 + es["time"].dt.minute
    es_rth = es.loc[es_min.ge(rth_start_min) & es_min.le(rth_end_min)].copy()
    es_rth["sess_date"] = es_rth["time"].dt.date
    es_g = es_rth.groupby("sess_date", sort=False)

    es_rth["es_recent5_high"] = es_g["high"].transform(lambda s: s.rolling(sw, min_periods=sw).max())
    es_rth["es_recent5_low"] = es_g["low"].transform(lambda s: s.rolling(sw, min_periods=sw).min())
    es_rth["es_prior45_high"] = es_g["high"].transform(lambda s: s.shift(sw).rolling(pw, min_periods=pw).max())
    es_rth["es_prior45_low"] = es_g["low"].transform(lambda s: s.shift(sw).rolling(pw, min_periods=pw).min())
    es_5m_range = (es_rth["es_recent5_high"] - es_rth["es_recent5_low"]).replace(0.0, np.nan)
    es_rth["es_5m_close_pos"] = ((es_rth["close"] - es_rth["es_recent5_low"]) / es_5m_range).clip(0.0, 1.0)

    rth_merged = rth_nq.merge(
        es_rth[
            [
                "time",
                "es_recent5_high",
                "es_recent5_low",
                "es_prior45_high",
                "es_prior45_low",
                "es_5m_close_pos",
            ]
        ],
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
    vx_rth["vx_15m_change"] = (
        vx_rth["vx_close"] - vx_rth.groupby("sess_date", sort=False)["vx_close"].shift(3)
    )
    vx_rth["completion_time"] = (vx_rth["time"] + pd.Timedelta(minutes=4)).astype("datetime64[ns]")
    vx_asof = vx_rth[["completion_time", "sess_date", "vx_close", "vx_15m_change"]].sort_values(
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

    # 5. Evaluate SMT divergence + $TICK exhaustion reversal conditions in [10:20..14:00] ET
    m_rth = rth_merged["time"].dt.hour * 60 + rth_merged["time"].dt.minute
    in_window = m_rth.ge(sig_start_min) & m_rth.le(sig_end_min)

    bull_nq_swept = (rth_merged["nq_recent5_low"] < rth_merged["nq_prior45_low"]) & (
        rth_merged["es_recent5_low"] >= rth_merged["es_prior45_low"]
    )
    bull_es_swept = (rth_merged["es_recent5_low"] < rth_merged["es_prior45_low"]) & (
        rth_merged["nq_recent5_low"] >= rth_merged["nq_prior45_low"]
    )
    bull_smt = bull_nq_swept | bull_es_swept

    bear_nq_swept = (rth_merged["nq_recent5_high"] > rth_merged["nq_prior45_high"]) & (
        rth_merged["es_recent5_high"] <= rth_merged["es_prior45_high"]
    )
    bear_es_swept = (rth_merged["es_recent5_high"] > rth_merged["es_prior45_high"]) & (
        rth_merged["nq_recent5_high"] <= rth_merged["nq_prior45_high"]
    )
    bear_smt = bear_nq_swept | bear_es_swept

    long_cond = (
        bool(cfg.allow_long)
        & in_window
        & bull_smt
        & (rth_merged["close"] >= rth_merged["nq_prior45_low"])
        & (rth_merged["nq_5m_close_pos"] >= float(cfg.min_long_5m_close_pos))
        & (rth_merged["close"] > rth_merged["open"])
        & (rth_merged["tick_5m_close"] >= float(cfg.min_long_tick_5m_close))
        & (rth_merged["tick_15m_mean"] >= float(cfg.min_long_tick_15m_mean))
        & (rth_merged["vx_15m_change"] <= float(cfg.max_long_vx_15m_change))
    )

    short_cond = (
        bool(cfg.allow_short)
        & in_window
        & bear_smt
        & (rth_merged["close"] <= rth_merged["nq_prior45_high"])
        & (rth_merged["nq_5m_close_pos"] <= float(cfg.max_short_5m_close_pos))
        & (rth_merged["close"] < rth_merged["open"])
        & (rth_merged["tick_5m_close"] <= float(cfg.max_short_tick_5m_close))
        & (rth_merged["tick_15m_mean"] <= float(cfg.max_short_tick_15m_mean))
        & (rth_merged["vx_15m_change"] >= float(cfg.min_short_vx_15m_change))
    )

    raw_sig = pd.Series(0.0, index=rth_merged.index, dtype=float)
    raw_sig.loc[long_cond] = 1.0
    raw_sig.loc[short_cond & raw_sig.eq(0.0)] = -1.0

    rth_merged["raw_sig"] = raw_sig
    rth_merged["nq_swept_flag"] = np.where(
        raw_sig > 0.0,
        bull_nq_swept,
        np.where(raw_sig < 0.0, bear_nq_swept, False),
    )

    # Deduplicate to maximum 1 signal per session (first trigger of the session)
    qualifying = rth_merged.loc[rth_merged["raw_sig"] != 0.0]
    first_per_session_idx = qualifying.groupby("sess_date", sort=False).head(1).index

    rth_sig = pd.Series(0.0, index=rth_merged.index, dtype=float)
    rth_sig.loc[first_per_session_idx] = rth_merged.loc[first_per_session_idx, "raw_sig"]
    rth_merged["candidate_signal"] = rth_sig

    merge_back_cols = [
        "time",
        "candidate_signal",
        "nq_5m_close_pos",
        "es_5m_close_pos",
        "nq_vwap_dist_pct",
        "nq_5m_range_points",
        "tick_5m_close",
        "tick_15m_mean",
        "vx_15m_change",
        "nq_swept_flag",
    ]
    out = df.merge(rth_merged[merge_back_cols], on="time", how="left")
    out["candidate_signal"] = out["candidate_signal"].fillna(0.0)

    active_idx = out["candidate_signal"].ne(0.0)
    direction = pd.Series("flat", index=out.index, dtype="object")
    direction.loc[out["candidate_signal"] > 0.0] = "long"
    direction.loc[out["candidate_signal"] < 0.0] = "short"

    smt_divergence_score = pd.Series(0.0, index=out.index, dtype=float)
    if active_idx.any():
        act = out.loc[active_idx]
        nq_rej = np.where(act["candidate_signal"] > 0.0, act["nq_5m_close_pos"], 1.0 - act["nq_5m_close_pos"])
        es_rej = np.where(act["candidate_signal"] > 0.0, act["es_5m_close_pos"], 1.0 - act["es_5m_close_pos"])
        tick_support = np.where(
            act["candidate_signal"] > 0.0,
            (act["tick_5m_close"] + 200.0) / 400.0,
            (200.0 - act["tick_5m_close"]) / 400.0,
        )
        raw_mag = (
            pd.Series(nq_rej, index=act.index).clip(0.0, 1.0)
            + pd.Series(es_rej, index=act.index).clip(0.0, 1.0)
            + pd.Series(tick_support, index=act.index).clip(0.0, 2.0)
        ) / 3.0
        smt_divergence_score.loc[active_idx] = act["candidate_signal"] * raw_mag

    stop_points = pd.Series(np.nan, index=out.index, dtype=float)
    target_points = pd.Series(np.nan, index=out.index, dtype=float)
    clipped_stop = (out.loc[active_idx, "nq_5m_range_points"] * 1.25).clip(
        lower=float(cfg.min_stop_points),
        upper=float(cfg.max_stop_points),
    )
    stop_points.loc[active_idx] = clipped_stop
    target_points.loc[active_idx] = clipped_stop * float(cfg.reward_risk_ratio)

    smt_leader = pd.Series("none", index=out.index, dtype="object")
    smt_leader.loc[active_idx & out["nq_swept_flag"].fillna(False).astype(bool)] = "nq_swept_es_held"
    smt_leader.loc[active_idx & (~out["nq_swept_flag"].fillna(False).astype(bool))] = "es_swept_nq_held"

    vwap_alignment = pd.Series("none", index=out.index, dtype="object")
    with_vwap = ((out["candidate_signal"] > 0.0) & (out["nq_vwap_dist_pct"] >= 0.0)) | (
        (out["candidate_signal"] < 0.0) & (out["nq_vwap_dist_pct"] <= 0.0)
    )
    vwap_alignment.loc[active_idx & with_vwap] = "with_vwap_trend"
    vwap_alignment.loc[active_idx & (~with_vwap)] = "counter_vwap_fade"

    out_min = out["time"].dt.hour * 60 + out["time"].dt.minute
    smt_window = pd.Series("none", index=out.index, dtype="object")
    smt_window.loc[active_idx & out_min.le(12 * 60)] = "morning_1020_1200"
    smt_window.loc[active_idx & out_min.gt(12 * 60)] = "midday_1201_1400"

    out["signal"] = out["candidate_signal"]
    out["signal_type"] = np.where(active_idx, "es_nq_smt_tick_divergence", "")
    out["direction"] = direction
    out["smt_divergence_score"] = smt_divergence_score
    out["stop_points"] = stop_points
    out["target_points"] = target_points
    out["smt_leader"] = smt_leader
    out["vwap_alignment"] = vwap_alignment
    out["smt_window"] = smt_window
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
