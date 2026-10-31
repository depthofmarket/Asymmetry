"""Unit tests for Late-Day Cross-Asset MOC Institutional Imbalance Drive signal (H11)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.late_day_cross_asset_moc_drive_signal import (
    LateDayCrossAssetMocDriveConfig,
    build_late_day_cross_asset_moc_drive_signal_export,
    build_late_day_cross_asset_moc_drive_signal_frame,
)


def _make_synthetic_session(
    session_date: str = "2024-03-15",
    direction: str = "long",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    times_1m = pd.date_range(f"{session_date} 09:30:00", f"{session_date} 16:00:00", freq="1min")
    n = len(times_1m)
    sign = 1.0 if direction == "long" else -1.0

    # Smooth monotonic trend from 09:30 to 16:00 so session return >= 0.40%, move/range >= 0.45, close_pos >= 0.80, 30m ret >= 0.08%
    nq_base = 18000.0
    nq_step = sign * 0.65  # over 30 bars, +19.5 pts (~0.108% return)
    nq_close = nq_base + np.arange(n) * nq_step
    nq_open = nq_close - sign * 0.20
    nq_high = np.maximum(nq_open, nq_close) + 0.50
    nq_low = np.minimum(nq_open, nq_close) - 0.50
    nq_df = pd.DataFrame(
        {
            "time": times_1m,
            "open": nq_open,
            "high": nq_high,
            "low": nq_low,
            "close": nq_close,
            "volume": np.full(n, 1000.0),
        }
    )

    es_base = 5100.0
    es_step = sign * 0.10  # over 300 bars, +30 pts (~0.58% return)
    es_close = es_base + np.arange(n) * es_step
    es_open = es_close - sign * 0.05
    es_high = np.maximum(es_open, es_close) + 0.25
    es_low = np.minimum(es_open, es_close) - 0.25
    es_df = pd.DataFrame(
        {
            "time": times_1m,
            "open": es_open,
            "high": es_high,
            "low": es_low,
            "close": es_close,
            "volume": np.full(n, 2000.0),
        }
    )

    times_5m = pd.date_range(f"{session_date} 09:30:00", f"{session_date} 15:55:00", freq="5min")
    m = len(times_5m)
    tick_val = 250.0 * sign
    tick_df = pd.DataFrame(
        {
            "time": times_5m,
            "open": np.full(m, tick_val),
            "high": np.full(m, tick_val + 150.0),
            "low": np.full(m, tick_val - 150.0),
            "close": np.full(m, tick_val),
        }
    )

    vx_base = 15.00
    vx_close = vx_base - sign * np.arange(m) * 0.01
    vx_df = pd.DataFrame(
        {
            "time": times_5m,
            "open": vx_close,
            "high": vx_close + 0.05,
            "low": vx_close - 0.05,
            "close": vx_close,
        }
    )
    return nq_df, es_df, tick_df, vx_df


def test_long_and_short_moc_drive_and_one_per_session() -> None:
    nq1, es1, tick1, vx1 = _make_synthetic_session("2024-03-15", "long")
    nq2, es2, tick2, vx2 = _make_synthetic_session("2024-03-18", "short")

    nq = pd.concat([nq1, nq2], ignore_index=True)
    es = pd.concat([es1, es2], ignore_index=True)
    tick = pd.concat([tick1, tick2], ignore_index=True)
    vx = pd.concat([vx1, vx2], ignore_index=True)

    cfg = LateDayCrossAssetMocDriveConfig()
    frame = build_late_day_cross_asset_moc_drive_signal_frame(
        nq, config=cfg, es_data=es, tick_data=tick, vx_data=vx
    )
    active = frame.loc[frame["signal"] != 0.0]
    assert len(active) == 2
    assert list(active["signal"]) == [1.0, -1.0]
    assert list(active["time"].dt.strftime("%H:%M")) == ["14:00", "14:00"]

    exported = build_late_day_cross_asset_moc_drive_signal_export(
        nq, config=cfg, es_data=es, tick_data=tick, vx_data=vx
    )
    assert int((exported["candidate_signal"] != 0.0).sum()) == 2


def test_point_in_time_no_lookahead_and_cross_asset_veto() -> None:
    nq, es, tick, vx = _make_synthetic_session("2024-03-15", "long")
    cfg = LateDayCrossAssetMocDriveConfig()

    base = build_late_day_cross_asset_moc_drive_signal_frame(
        nq, config=cfg, es_data=es, tick_data=tick, vx_data=vx
    )
    sig_bar = base.loc[base["signal"] != 0.0].iloc[0]
    sig_time = sig_bar["time"]

    # Mutate all bars strictly after sig_time -> signal at sig_time must be identical
    nq_mut = nq.copy()
    nq_mut.loc[nq_mut["time"] > sig_time, "close"] = 10000.0
    tick_mut = tick.copy()
    # A 5m bar starting at 14:00 completes at 14:04 (> 14:00), so mutating it must NOT affect 14:00!
    tick_mut.loc[tick_mut["time"] >= pd.Timestamp("2024-03-15 14:00:00"), "close"] = -900.0

    mut_frame = build_late_day_cross_asset_moc_drive_signal_frame(
        nq_mut, config=cfg, es_data=es, tick_data=tick_mut, vx_data=vx
    )
    mut_row = mut_frame.loc[mut_frame["time"] == sig_time].iloc[0]
    assert mut_row["signal"] == 1.0
    assert np.isclose(mut_row["moc_drive_score"], sig_bar["moc_drive_score"])

    # Veto test: if ES is flat/down, no long signal should fire
    es_flat = es.copy()
    es_flat["close"] = es_flat["open"].iloc[0]
    veto_frame = build_late_day_cross_asset_moc_drive_signal_frame(
        nq, config=cfg, es_data=es_flat, tick_data=tick, vx_data=vx
    )
    assert int((veto_frame["signal"] != 0.0).sum()) == 0
