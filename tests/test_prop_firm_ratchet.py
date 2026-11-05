"""Unit tests for dynamic Anti-Martingale ratchet sizing in prop firm simulations."""
import numpy as np
import pandas as pd
import pytest

from backtest.prop_firm import DEFAULT_PROFILE, simulate_ratchet_profile


def test_simulate_ratchet_profile_basic():
    # Construct a simple daily path dataframe
    daily_paths = pd.DataFrame([
        {"net_pnl": 500.0, "min_intraday_pnl": -50.0, "max_intraday_pnl": 600.0, "trade_count": 1},
        {"net_pnl": -300.0, "min_intraday_pnl": -400.0, "max_intraday_pnl": 50.0, "trade_count": 1},
        {"net_pnl": 800.0, "min_intraday_pnl": -100.0, "max_intraday_pnl": 900.0, "trade_count": 1},
    ])
    
    prof = DEFAULT_PROFILE.copy()
    prof["account_size"] = 25000.0
    prof["profit_target"] = 1250.0
    prof["max_drawdown"] = 1000.0
    prof["daily_loss_limit"] = 600.0
    prof["max_trading_days"] = 22
    prof["drawdown_mode"] = "eod_trailing"
    
    ratchet_tiers = [(0.0, 0.2), (200.0, 0.3), (500.0, 0.4)]
    
    res = simulate_ratchet_profile(daily_paths, prof, ratchet_tiers=ratchet_tiers, n_sims=100, seed=42)
    assert len(res) == 100
    assert "status" in res.columns
    assert "days" in res.columns
    assert "final_equity" in res.columns
    assert set(res["status"].unique()).issubset({"pass", "fail", "timeout"})


def test_simulate_ratchet_step_up_and_down():
    # Path that starts positive, triggers ratchet tier 2, then has a loss
    daily_paths = pd.DataFrame([
        {"net_pnl": 2000.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 2000.0, "trade_count": 1},  # At 0.2x = +400 -> unlocks 0.3x
        {"net_pnl": -1000.0, "min_intraday_pnl": -1000.0, "max_intraday_pnl": 0.0, "trade_count": 1}, # At 0.3x = -300 -> drops back to +100 (relocks 0.2x)
        {"net_pnl": 5000.0, "min_intraday_pnl": 0.0, "max_intraday_pnl": 5000.0, "trade_count": 1},  # At 0.2x = +1000 -> total +1100 -> passes
    ])
    
    prof = DEFAULT_PROFILE.copy()
    prof["account_size"] = 25000.0
    prof["profit_target"] = 1000.0
    prof["max_drawdown"] = 2000.0
    prof["daily_loss_limit"] = 1500.0
    prof["max_trading_days"] = 5
    
    ratchet_tiers = [(0.0, 0.2), (200.0, 0.3), (500.0, 0.4)]
    res = simulate_ratchet_profile(daily_paths, prof, ratchet_tiers=ratchet_tiers, n_sims=10, seed=42)
    assert (res["status"] == "pass").all()
