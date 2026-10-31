from __future__ import annotations

import pandas as pd

from backtest.gold_london_fix_structural_breakout_signal import (
    GoldLondonFixBreakoutConfig,
    build_gold_london_fix_breakout_signal_export,
    build_gold_london_fix_breakout_signal_frame,
)


def _make_two_session_gc_frame() -> pd.DataFrame:
    rows = []
    # Day 1: Prior RTH session (08:20..13:30 ET) centered around 2000.0 (range 1995..2005)
    t1 = pd.date_range("2025-01-02 08:20:00", "2025-01-02 13:30:00", freq="1min")
    for t in t1:
        rows.append(
            {
                "time": t,
                "open": 2000.0,
                "high": 2002.0,
                "low": 1998.0,
                "close": 2000.0,
                "volume": 100,
            }
        )

    # Day 2: London session (03:00..08:19 ET) range 2001..2004
    t2_lon = pd.date_range("2025-01-03 03:00:00", "2025-01-03 08:19:00", freq="1min")
    for t in t2_lon:
        rows.append(
            {
                "time": t,
                "open": 2002.0,
                "high": 2004.0,
                "low": 2001.0,
                "close": 2003.0,
                "volume": 50,
            }
        )

    # Day 2: COMEX IB60 (08:20..09:59 ET) range 2002..2005
    t2_ib = pd.date_range("2025-01-03 08:20:00", "2025-01-03 09:59:00", freq="1min")
    for t in t2_ib:
        rows.append(
            {
                "time": t,
                "open": 2003.0,
                "high": 2005.0,
                "low": 2002.0,
                "close": 2004.5,
                "volume": 120,
            }
        )

    # Day 2: LBMA PM Fix (10:00..10:14 ET) breaks above 2005 -> closes at 2009.5 (open 2005.0, low 2004.5, high 2010.0)
    t2_fix = pd.date_range("2025-01-03 10:00:00", "2025-01-03 10:14:00", freq="1min")
    for i, t in enumerate(t2_fix):
        rows.append(
            {
                "time": t,
                "open": 2005.0 if i == 0 else 2007.0,
                "high": 2010.0 if i == len(t2_fix) - 1 else 2008.0,
                "low": 2004.5 if i == 0 else 2006.0,
                "close": 2009.5 if i == len(t2_fix) - 1 else 2007.5,
                "volume": 200,
            }
        )

    return pd.DataFrame(rows)


def test_gold_london_fix_breakout_fires_at_1014_without_lookahead() -> None:
    df = _make_two_session_gc_frame()
    cfg = GoldLondonFixBreakoutConfig()
    out = build_gold_london_fix_breakout_signal_frame(df, config=cfg)

    active = out[out["candidate_signal"] != 0.0]
    assert len(active) == 1
    row = active.iloc[0]
    assert row["time"] == pd.Timestamp("2025-01-03 10:14:00")
    assert row["candidate_signal"] == 1.0
    assert row["direction"] == "long"
    assert row["va_location"] == "above_vah"
    assert row["london_break_state"] == "above_london_high"
    assert row["stop_points"] == 5.5  # 2010.0 - 2004.5
    assert row["target_points"] == 5.5 * 1.50


def test_gold_london_fix_export_schema() -> None:
    df = _make_two_session_gc_frame()
    exp = build_gold_london_fix_breakout_signal_export(df)
    active = exp[exp["candidate_signal"] != 0.0]
    assert len(active) == 1
    assert "fix_breakout_score" in exp.columns
    assert "prior_rth_vah" in exp.columns
