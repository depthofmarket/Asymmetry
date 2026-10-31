"""Unit tests for Late-Day VX-Crush & Cross-Asset Power-Hour Long Drive signal (H13)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.late_day_vx_crush_power_hour_long_signal import (
    LateDayVxCrushPowerHourLongConfig,
    build_late_day_vx_crush_power_hour_long_signal_export,
    build_late_day_vx_crush_power_hour_long_signal_frame,
)


def _make_synthetic_h13_session(
    session_date: str = "2024-05-10",
    vx_slope: float = -0.01,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    times_1m = pd.date_range(f"{session_date} 09:30:00", f"{session_date} 16:00:00", freq="1min")
    n = len(times_1m)

    nq_base = 18000.0
    nq_close = nq_base + np.arange(n) * 0.55
    nq_open = nq_close - 0.25
    nq_high = nq_close + 0.50
    nq_low = nq_open - 0.50
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
    es_close = es_base + np.arange(n) * 0.12
    es_open = es_close - 0.05
    es_high = es_close + 0.20
    es_low = es_open - 0.20
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
    tick_df = pd.DataFrame(
        {
            "time": times_5m,
            "open": np.full(m, 180.0),
            "high": np.full(m, 300.0),
            "low": np.full(m, 50.0),
            "close": np.full(m, 180.0),
        }
    )

    vx_close = 15.50 + np.arange(m) * vx_slope
    vx_df = pd.DataFrame(
        {
            "time": times_5m,
            "open": vx_close,
            "high": vx_close + 0.03,
            "low": vx_close - 0.03,
            "close": vx_close,
        }
    )
    return nq_df, es_df, tick_df, vx_df


def test_h13_signal_fires_once_at_1445_and_respects_vx_crush() -> None:
    nq1, es1, tick1, vx1 = _make_synthetic_h13_session("2024-05-10", vx_slope=-0.01)
    # Second session has expanding VX -> must be vetoed
    nq2, es2, tick2, vx2 = _make_synthetic_h13_session("2024-05-13", vx_slope=+0.01)

    nq = pd.concat([nq1, nq2], ignore_index=True)
    es = pd.concat([es1, es2], ignore_index=True)
    tick = pd.concat([tick1, tick2], ignore_index=True)
    vx = pd.concat([vx1, vx2], ignore_index=True)

    cfg = LateDayVxCrushPowerHourLongConfig()
    frame = build_late_day_vx_crush_power_hour_long_signal_frame(
        nq, config=cfg, es_data=es, tick_data=tick, vx_data=vx
    )
    active = frame.loc[frame["signal"] != 0.0]
    assert len(active) == 1
    assert active.iloc[0]["time"] == pd.Timestamp("2024-05-10 14:45:00")
    assert active.iloc[0]["signal"] == 1.0

    exported = build_late_day_vx_crush_power_hour_long_signal_export(
        nq, config=cfg, es_data=es, tick_data=tick, vx_data=vx
    )
    assert int((exported["candidate_signal"] != 0.0).sum()) == 1


def test_h13_point_in_time_no_lookahead() -> None:
    nq, es, tick, vx = _make_synthetic_h13_session("2024-05-10", vx_slope=-0.01)
    cfg = LateDayVxCrushPowerHourLongConfig()
    base = build_late_day_vx_crush_power_hour_long_signal_frame(
        nq, config=cfg, es_data=es, tick_data=tick, vx_data=vx
    )
    sig_row = base.loc[base["signal"] != 0.0].iloc[0]
    sig_time = sig_row["time"]

    # Mutate all bars after 14:45 -> signal at 14:45 must remain identical
    nq_mut = nq.copy()
    nq_mut.loc[nq_mut["time"] > sig_time, "close"] = 10000.0
    vx_mut = vx.copy()
    # 5m bar stamped 14:45 completes at 14:49 (> 14:45), so mutating it must NOT affect 14:45
    vx_mut.loc[vx_mut["time"] >= pd.Timestamp("2024-05-10 14:45:00"), "close"] = 25.0

    mut_frame = build_late_day_vx_crush_power_hour_long_signal_frame(
        nq_mut, config=cfg, es_data=es, tick_data=tick, vx_data=vx_mut
    )
    mut_row = mut_frame.loc[mut_frame["time"] == sig_time].iloc[0]
    assert mut_row["signal"] == 1.0
    assert np.isclose(mut_row["vx_crush_power_score"], sig_row["vx_crush_power_score"])
