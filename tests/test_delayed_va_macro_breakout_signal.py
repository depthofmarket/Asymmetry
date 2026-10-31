from __future__ import annotations

import pandas as pd

from backtest.delayed_va_macro_breakout_signal import (
    DelayedVaMacroBreakoutConfig,
    build_delayed_va_macro_breakout_signal_export,
    build_delayed_va_macro_breakout_signal_frame,
)
from backtest.morning_value_area_breakout_signal import (
    build_morning_value_area_breakout_signal_frame,
)


def _make_two_day_inside_to_breakout_data() -> pd.DataFrame:
    rows = []
    # Day 1 (2024-01-02): Balanced RTH session around 15000 (VAL ~14995, POC ~15000, VAH ~15005)
    t_day1 = pd.date_range("2024-01-02 09:30", "2024-01-02 10:30", freq="1min")
    for i, ts in enumerate(t_day1):
        price = 15000.0 + ((i % 5) - 2) * 2.0
        rows.append(
            {
                "time": ts,
                "open": price - 1.0,
                "high": price + 2.0,
                "low": price - 2.0,
                "close": price,
                "volume": 1000.0,
            }
        )

    # Day 2 (2024-01-03):
    # - 09:30..09:44 opens and stays INSIDE prior VA (around 15000, high=15003, low=14997, close_0944=15001)
    #   -> Strategy 1 (H4) is strictly FLAT at 09:44!
    # - 09:45..10:04 breaks out above OR15 high (15003) and above prior VAH (15006), closing at 15025 at 10:04!
    t_day2 = pd.date_range("2024-01-03 09:30", "2024-01-03 10:30", freq="1min")
    for ts in t_day2:
        hm = ts.strftime("%H:%M")
        if hm <= "09:44":
            rows.append(
                {
                    "time": ts,
                    "open": 15000.0,
                    "high": 15003.0,
                    "low": 14997.0,
                    "close": 15001.0,
                    "volume": 800.0,
                }
            )
        elif hm <= "10:04":
            rows.append(
                {
                    "time": ts,
                    "open": 15002.0,
                    "high": 15028.0,
                    "low": 15001.0,
                    "close": 15025.0,
                    "volume": 2000.0,
                }
            )
        else:
            rows.append(
                {
                    "time": ts,
                    "open": 15025.0,
                    "high": 15040.0,
                    "low": 15022.0,
                    "close": 15035.0,
                    "volume": 1200.0,
                }
            )
    return pd.DataFrame(rows)


def test_delayed_va_macro_breakout_fires_when_h4_is_flat():
    df = _make_two_day_inside_to_breakout_data()
    h4 = build_morning_value_area_breakout_signal_frame(df)
    assert (h4["candidate_signal"] == 0.0).all()

    h9 = build_delayed_va_macro_breakout_signal_frame(df)
    active = h9.loc[h9["candidate_signal"] != 0.0]
    assert len(active) == 1
    row = active.iloc[0]
    assert row["time"] == pd.Timestamp("2024-01-03 10:04:00")
    assert row["candidate_signal"] == 1.0
    assert row["direction"] == "long"
    assert row["breakout_type"] == "inside_va_to_above_vah"
    assert row["or15_va_regime"] == "or15_inside_va"
    assert row["delayed_va_breakout_score"] > 0.0


def test_delayed_va_macro_breakout_skips_when_h4_fired():
    df = _make_two_day_inside_to_breakout_data()
    # Force Day 2 09:30..09:44 to already be a gap-up breakout above VAH so H4 fires at 09:44
    day2_or15 = (df["time"] >= "2024-01-03 09:30") & (df["time"] <= "2024-01-03 09:44")
    df.loc[day2_or15, "open"] = 15010.0
    df.loc[day2_or15, "low"] = 15008.0
    df.loc[day2_or15, "high"] = 15030.0
    df.loc[day2_or15, "close"] = 15028.0

    # Even if 10:04 continues higher to 15045, H9 must skip because H4 already fired at 09:44
    day2_wave2 = (df["time"] >= "2024-01-03 09:45") & (df["time"] <= "2024-01-03 10:04")
    df.loc[day2_wave2, "open"] = 15028.0
    df.loc[day2_wave2, "low"] = 15025.0
    df.loc[day2_wave2, "high"] = 15048.0
    df.loc[day2_wave2, "close"] = 15045.0

    h4 = build_morning_value_area_breakout_signal_frame(df)
    assert (h4["candidate_signal"] == 1.0).sum() == 1

    h9 = build_delayed_va_macro_breakout_signal_export(df, config=DelayedVaMacroBreakoutConfig())
    assert (h9["candidate_signal"] == 0.0).all()
