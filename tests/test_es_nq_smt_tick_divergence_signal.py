"""Unit tests for ES vs. NQ Intermarket SMT Divergence + $TICK Exhaustion Reversal signal (H12)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.es_nq_smt_tick_divergence_signal import (
    EsNqSmtTickDivergenceConfig,
    build_es_nq_smt_tick_divergence_signal_export,
    build_es_nq_smt_tick_divergence_signal_frame,
)


def _make_synthetic_smt_session(
    session_date: str = "2024-04-10",
    direction: str = "long",
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    times_1m = pd.date_range(f"{session_date} 09:30:00", f"{session_date} 16:00:00", freq="1min")
    n = len(times_1m)

    # Flat range [18000..18020] for NQ and [5100..5105] for ES during 09:30..10:25
    nq_open = np.full(n, 18010.0)
    nq_close = np.full(n, 18010.0)
    nq_high = np.full(n, 18020.0)
    nq_low = np.full(n, 18000.0)

    es_open = np.full(n, 5102.5)
    es_close = np.full(n, 5102.5)
    es_high = np.full(n, 5105.0)
    es_low = np.full(n, 5100.0)

    # At index 60 (10:30 ET), create an SMT sweep on NQ while ES holds its prior 45m boundary
    idx_1030 = 60
    if direction == "long":
        # NQ sweeps below 18000 (down to 17992) and closes bullishly at 18015 (reclaiming 18000, close_pos > 0.55)
        nq_low[idx_1030] = 17992.0
        nq_open[idx_1030] = 17998.0
        nq_close[idx_1030] = 18015.0
        nq_high[idx_1030] = 18020.0
        # ES holds above 5100 (low = 5100.5)
        es_low[idx_1030] = 5100.5
    else:
        # NQ sweeps above 18020 (up to 18028) and closes bearishly at 18005 (below 18020, close_pos < 0.45)
        nq_high[idx_1030] = 18028.0
        nq_open[idx_1030] = 18022.0
        nq_close[idx_1030] = 18005.0
        nq_low[idx_1030] = 18000.0
        # ES holds below 5105 (high = 5104.5)
        es_high[idx_1030] = 5104.5

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
            "open": np.zeros(m),
            "high": np.full(m, 100.0),
            "low": np.full(m, -100.0),
            "close": np.zeros(m),
        }
    )
    vx_df = pd.DataFrame(
        {
            "time": times_5m,
            "open": np.full(m, 15.0),
            "high": np.full(m, 15.05),
            "low": np.full(m, 14.95),
            "close": np.full(m, 15.0),
        }
    )
    return nq_df, es_df, tick_df, vx_df


def test_bullish_and_bearish_smt_divergence_signals() -> None:
    nq1, es1, tick1, vx1 = _make_synthetic_smt_session("2024-04-10", "long")
    nq2, es2, tick2, vx2 = _make_synthetic_smt_session("2024-04-11", "short")

    nq = pd.concat([nq1, nq2], ignore_index=True)
    es = pd.concat([es1, es2], ignore_index=True)
    tick = pd.concat([tick1, tick2], ignore_index=True)
    vx = pd.concat([vx1, vx2], ignore_index=True)

    cfg = EsNqSmtTickDivergenceConfig()
    frame = build_es_nq_smt_tick_divergence_signal_frame(
        nq, config=cfg, es_data=es, tick_data=tick, vx_data=vx
    )
    active = frame.loc[frame["signal"] != 0.0]
    assert len(active) == 2
    assert list(active["signal"]) == [1.0, -1.0]
    assert list(active["smt_leader"]) == ["nq_swept_es_held", "nq_swept_es_held"]

    exported = build_es_nq_smt_tick_divergence_signal_export(
        nq, config=cfg, es_data=es, tick_data=tick, vx_data=vx
    )
    assert int((exported["candidate_signal"] != 0.0).sum()) == 2


def test_no_lookahead_and_non_divergent_veto() -> None:
    nq, es, tick, vx = _make_synthetic_smt_session("2024-04-10", "long")
    cfg = EsNqSmtTickDivergenceConfig()

    base = build_es_nq_smt_tick_divergence_signal_frame(
        nq, config=cfg, es_data=es, tick_data=tick, vx_data=vx
    )
    sig_row = base.loc[base["signal"] != 0.0].iloc[0]
    sig_time = sig_row["time"]

    # Mutate future bars strictly after sig_time -> no effect on sig_time
    nq_mut = nq.copy()
    nq_mut.loc[nq_mut["time"] > sig_time, "close"] = 12000.0
    tick_mut = tick.copy()
    tick_mut.loc[tick_mut["time"] >= pd.Timestamp("2024-04-10 10:30:00"), "close"] = -900.0

    mut_frame = build_es_nq_smt_tick_divergence_signal_frame(
        nq_mut, config=cfg, es_data=es, tick_data=tick_mut, vx_data=vx
    )
    assert mut_frame.loc[mut_frame["time"] == sig_time, "signal"].iloc[0] == 1.0

    # If ES also sweeps its low (confirming the breakdown -> no SMT divergence), signal must be 0
    es_confirm = es.copy()
    es_confirm.loc[es_confirm["time"] == sig_time, "low"] = 5095.0
    veto_frame = build_es_nq_smt_tick_divergence_signal_frame(
        nq, config=cfg, es_data=es_confirm, tick_data=tick, vx_data=vx
    )
    assert int((veto_frame["signal"] != 0.0).sum()) == 0
