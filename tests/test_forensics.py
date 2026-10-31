"""Tests for forensic suite inspired by Rok Nyuton Quant-Analysis-Toolkit."""
import numpy as np
import pandas as pd
import pytest

from backtest.forensics import (
    compute_mfe_mae_efficiency,
    compute_risk_parity_weights,
    deep_drawdown_forensics,
    reconstruct_intrabar_equity,
)


def test_compute_mfe_mae_efficiency():
    trades = pd.DataFrame([
        {"pnl": 500.0, "mfe_dollars": 1000.0, "mae_dollars": 100.0},
        {"pnl": -300.0, "mfe_dollars": 200.0, "mae_dollars": 400.0},
        {"pnl": 800.0, "mfe_dollars": 1000.0, "mae_dollars": 50.0},
    ])
    res = compute_mfe_mae_efficiency(trades)
    assert res["total_trades"] == 3
    assert res["total_mfe_winners"] == 2000.0
    assert res["total_realized_winners"] == 1300.0
    assert res["move_capture_ratio"] == 65.0
    assert res["avg_mae_winners"] == 75.0
    assert res["avg_mae_losers"] == 400.0
    assert res["max_mae_survived_winner"] == 100.0


def test_reconstruct_intrabar_equity():
    trades = pd.DataFrame([
        {
            "entry_time": "2024-01-02 09:45:00",
            "exit_time": "2024-01-02 10:15:00",
            "direction": "long",
            "entry_price": 16000.0,
            "exit_price": 16020.0,
            "pnl": 400.0,
            "contracts": 1,
        }
    ])
    m1 = pd.DataFrame([
        {"time": "2024-01-02 09:45:00", "low": 15990.0, "high": 16005.0, "close": 16002.0},
        {"time": "2024-01-02 10:15:00", "low": 16010.0, "high": 16025.0, "close": 16020.0},
    ])
    res = reconstruct_intrabar_equity(trades, m1, initial_capital=100_000.0, point_value=20.0)
    assert res["total_trades_analyzed"] == 1
    # 15990 - 16000 = -10 pts * $20 = -$200 worst heat
    assert res["worst_single_trade_intrabar_heat"] == 200.0


def test_deep_drawdown_forensics():
    trades = pd.DataFrame([
        {"entry_time": "2024-01-01", "exit_time": "2024-01-01", "pnl": 500.0, "equity": 100500.0},
        {"entry_time": "2024-01-02", "exit_time": "2024-01-02", "pnl": -300.0, "equity": 100200.0},
        {"entry_time": "2024-01-03", "exit_time": "2024-01-03", "pnl": -400.0, "equity": 99800.0},
        {"entry_time": "2024-01-04", "exit_time": "2024-01-04", "pnl": 800.0, "equity": 100600.0},
    ])
    dd_df = deep_drawdown_forensics(trades, top_n=3)
    assert len(dd_df) == 1
    assert dd_df.iloc[0]["max_dd_dollars"] == 700.0
    assert dd_df.iloc[0]["trades_count"] == 2


def test_compute_risk_parity_weights():
    s1 = pd.Series([100, 200, -100, 150, 300])
    s2 = pd.Series([50, 60, -20, 40, 80])
    res = compute_risk_parity_weights({"leg1": s1, "leg2": s2})
    w = res["weights"]
    assert "leg1" in w and "leg2" in w
    assert pytest.approx(w["leg1"] + w["leg2"]) == 1.0
    # s2 has lower variance, so its risk parity weight should be higher
    assert w["leg2"] > w["leg1"]
