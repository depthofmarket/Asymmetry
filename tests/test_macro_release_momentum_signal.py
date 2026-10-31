import pandas as pd
import numpy as np
import pytest

from backtest.macro_release_momentum_signal import (
    MacroReleaseMomentumConfig,
    build_macro_release_momentum_signal_frame,
    build_macro_release_momentum_signal_export,
)


def _generate_synthetic_macro_day(
    date_str: str = "2026-10-30",
    spike_direction: int = 1,
    volume_mult: float = 3.0,
) -> pd.DataFrame:
    """Generate 1-minute bars from 00:00 to 09:30 ET."""
    times = pd.date_range(f"{date_str} 00:00:00", f"{date_str} 09:30:00", freq="1min")
    n = len(times)
    
    # Baseline overnight: 18000 to 18050
    opens = np.full(n, 18025.0)
    highs = np.full(n, 18035.0)
    lows = np.full(n, 18015.0)
    closes = np.full(n, 18025.0)
    vols = np.full(n, 100.0)
    
    df = pd.DataFrame({
        "time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": vols,
    })
    
    # Overnight range: 00:00 to 08:29
    # High: 18050, Low: 18000
    df.loc[df["time"].dt.strftime("%H:%M") == "04:00", "high"] = 18050.0
    df.loc[df["time"].dt.strftime("%H:%M") == "05:00", "low"] = 18000.0
    
    # Spike bars: 08:30 - 08:34
    spike_mask = (df["time"].dt.strftime("%H:%M") >= "08:30") & (df["time"].dt.strftime("%H:%M") <= "08:34")
    # Total volume in spike: 100 * 5 * volume_mult
    df.loc[spike_mask, "volume"] = 100.0 * volume_mult
    
    if spike_direction == 1:
        # Bullish breakout above 18050
        df.loc[spike_mask, "high"] = 18100.0
        df.loc[df["time"].dt.strftime("%H:%M") == "08:34", "close"] = 18090.0 # cl_loc >= 0.65
        df.loc[spike_mask, "low"] = 18040.0
    elif spike_direction == -1:
        # Bearish breakout below 18000
        df.loc[spike_mask, "low"] = 17950.0
        df.loc[df["time"].dt.strftime("%H:%M") == "08:34", "close"] = 17960.0 # cl_loc <= 0.35
        df.loc[spike_mask, "high"] = 18010.0
        
    return df


def test_macro_signal_bullish_breakout():
    df = _generate_synthetic_macro_day(spike_direction=1, volume_mult=3.5)
    sig_df = build_macro_release_momentum_signal_frame(df)
    
    sig_bar = sig_df[sig_df["time"].dt.strftime("%H:%M") == "08:35"].iloc[0]
    assert sig_bar["candidate_signal"] == 1.0
    assert sig_bar["direction"] == "long"
    assert sig_bar["stop_points"] >= 20.0
    assert sig_bar["target_points"] == sig_bar["stop_points"] * 1.50
    assert sig_bar["break_state"] == "above_ovn_high"


def test_macro_signal_bearish_breakout():
    df = _generate_synthetic_macro_day(spike_direction=-1, volume_mult=3.5)
    sig_df = build_macro_release_momentum_signal_frame(df)
    
    sig_bar = sig_df[sig_df["time"].dt.strftime("%H:%M") == "08:35"].iloc[0]
    assert sig_bar["candidate_signal"] == -1.0
    assert sig_bar["direction"] == "short"
    assert sig_bar["stop_points"] >= 20.0
    assert sig_bar["target_points"] == sig_bar["stop_points"] * 1.50
    assert sig_bar["break_state"] == "below_ovn_low"


def test_macro_signal_low_volume_filtered():
    # Only 1.2x volume mult (below min_volume_mult 2.5)
    df = _generate_synthetic_macro_day(spike_direction=1, volume_mult=1.2)
    sig_df = build_macro_release_momentum_signal_frame(df)
    
    sig_bar = sig_df[sig_df["time"].dt.strftime("%H:%M") == "08:35"].iloc[0]
    assert sig_bar["candidate_signal"] == 0.0
    assert sig_bar["direction"] == "flat"


def test_macro_signal_export_format():
    df = _generate_synthetic_macro_day(spike_direction=1, volume_mult=3.0)
    exp_df = build_macro_release_momentum_signal_export(df)
    
    assert "candidate_signal" in exp_df.columns
    assert "spike_volume_mult" in exp_df.columns
    assert "break_state" in exp_df.columns
    assert len(exp_df) == len(df)
