from __future__ import annotations

import pandas as pd

from backtest.cross_asset_program_thrust_signal import (
    CrossAssetProgramThrustConfig,
    build_cross_asset_program_thrust_signal_export,
    build_cross_asset_program_thrust_signal_frame,
)


def _make_synthetic_cross_asset_session():
    times_1m = pd.date_range("2024-02-01 09:30", "2024-02-01 11:00", freq="1min")
    nq_rows = []
    es_rows = []
    for ts in times_1m:
        hm = ts.strftime("%H:%M")
        if hm <= "10:04":
            # Consolidation between 09:30 and 10:04
            nq_rows.append({"time": ts, "open": 17500.0, "high": 17510.0, "low": 17490.0, "close": 17502.0, "volume": 1000.0})
            es_rows.append({"time": ts, "open": 5000.0, "high": 5003.0, "low": 4997.0, "close": 5000.5, "volume": 1000.0})
        elif hm <= "10:14":
            # Synchronized breakout between 10:05 and 10:14 (completed at 10:14)
            nq_rows.append({"time": ts, "open": 17505.0, "high": 17535.0, "low": 17504.0, "close": 17532.0, "volume": 2500.0})
            es_rows.append({"time": ts, "open": 5001.0, "high": 5012.0, "low": 5000.5, "close": 5011.0, "volume": 2500.0})
        else:
            nq_rows.append({"time": ts, "open": 17532.0, "high": 17550.0, "low": 17530.0, "close": 17545.0, "volume": 1500.0})
            es_rows.append({"time": ts, "open": 5011.0, "high": 5018.0, "low": 5010.0, "close": 5016.0, "volume": 1500.0})

    times_5m = pd.date_range("2024-02-01 09:30", "2024-02-01 10:55", freq="5min")
    tick_rows = []
    vx_rows = []
    for ts in times_5m:
        hm = ts.strftime("%H:%M")
        if hm in ("10:00", "10:05", "10:10"):
            # Strong NYSE $TICK program buying & VX compression
            tick_rows.append({"time": ts, "open": 150.0, "high": 650.0, "low": 50.0, "close": 320.0})
            vx_rows.append({"time": ts, "open": 14.20, "high": 14.25, "low": 14.00, "close": 14.05, "volume": 500.0})
        else:
            tick_rows.append({"time": ts, "open": 0.0, "high": 200.0, "low": -200.0, "close": 20.0})
            vx_rows.append({"time": ts, "open": 14.30, "high": 14.35, "low": 14.20, "close": 14.25, "volume": 300.0})

    return pd.DataFrame(nq_rows), pd.DataFrame(es_rows), pd.DataFrame(tick_rows), pd.DataFrame(vx_rows)


def test_cross_asset_program_thrust_fires_on_4_asset_alignment():
    nq, es, tick, vx = _make_synthetic_cross_asset_session()
    out = build_cross_asset_program_thrust_signal_frame(
        nq,
        config=CrossAssetProgramThrustConfig(),
        es_data=es,
        tick_data=tick,
        vx_data=vx,
    )
    active = out.loc[out["candidate_signal"] != 0.0]
    assert len(active) == 1
    row = active.iloc[0]
    # 10:05 5m bar completes at 10:09 1m bar close!
    assert row["time"] == pd.Timestamp("2024-02-01 10:09:00")
    assert row["candidate_signal"] == 1.0
    assert row["direction"] == "long"
    assert row["program_thrust_score"] > 0.0


def test_cross_asset_program_thrust_blocks_when_vx_expands_on_long():
    nq, es, tick, vx = _make_synthetic_cross_asset_session()
    # Make VX spike higher at 10:05 and 10:10 (diverging from equity rally)
    vx.loc[vx["time"] >= "2024-02-01 10:00", "close"] = 14.80
    exp = build_cross_asset_program_thrust_signal_export(
        nq,
        config=CrossAssetProgramThrustConfig(),
        es_data=es,
        tick_data=tick,
        vx_data=vx,
    )
    assert (exp["candidate_signal"] == 0.0).all()
