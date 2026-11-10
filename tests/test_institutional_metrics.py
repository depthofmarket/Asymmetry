"""
Test Suite: Institutional Quantitative Performance & Risk Metrics Engine.

Verifies:
1. Full 88+ metric calculation via backtest.metrics.calculate_institutional_metrics.
2. Mathematical correctness of individual ratios (Sortino, Calmar, Omega, Gain-to-Pain,
   Ulcer Index, Burke, Kappa 3, Cornish-Fisher VaR, CVaR 95/99, Kelly fractions, SQN).
3. ACID Provenance store persistence and schema backwards-compatibility.
4. CLI query interface (query_provenance.py) quoting new institutional metrics.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backtest.metrics as bm
from backtest.provenance import ProvenanceRecord, ProvenanceStore


@pytest.fixture
def temp_store(tmp_path):
    db_file = tmp_path / "test_institutional_provenance.db"
    jsonl_file = tmp_path / "test_institutional_provenance.jsonl"
    return ProvenanceStore(db_path=db_file, jsonl_path=jsonl_file)


# =============================================================================
# 1. MATHEMATICAL FORMULATION TESTS
# =============================================================================

def test_norm_approximations():
    """Verifies standard normal CDF and Acklam quantile approximations."""
    assert abs(bm.norm_cdf(0.0) - 0.5) < 1e-7
    assert abs(bm.norm_cdf(1.96) - 0.975002) < 1e-4
    assert abs(bm.norm_ppf(0.5) - 0.0) < 1e-7
    assert abs(bm.norm_ppf(0.975) - 1.95996) < 1e-4
    assert abs(bm.norm_ppf(0.05) - (-1.644853)) < 1e-4


def test_sortino_ratio():
    """Sortino ratio should only penalize downside deviations."""
    returns = np.array([100.0, 200.0, -50.0, 150.0, -50.0])
    sortino = bm.sortino_ratio(returns, mar=0.0, annualization_factor=252.0)
    assert sortino > 0.0
    # If downside is zero, Sortino should be high/capped
    all_wins = np.array([10.0, 20.0, 30.0])
    assert bm.sortino_ratio(all_wins) == 999.0


def test_calmar_ratio():
    assert bm.calmar_ratio(1000.0, 500.0) == 2.0
    assert bm.calmar_ratio(1000.0, -500.0) == 2.0
    assert bm.calmar_ratio(1000.0, 0.0) == 999.0


def test_omega_ratio():
    returns = np.array([100.0, -50.0, 100.0, -50.0])
    # Gains = 200, Losses = 100 -> Omega = 2.0
    assert abs(bm.omega_ratio(returns, hurdle=0.0) - 2.0) < 1e-6


def test_gain_to_pain_ratio():
    returns = np.array([100.0, -50.0, 200.0, -50.0])
    # Net sum = 200, Pain = 100 -> GPR = 2.0
    assert abs(bm.gain_to_pain_ratio(returns) - 2.0) < 1e-6


def test_ulcer_index_and_upi():
    # Equity that drops 10% and stays down should have non-zero Ulcer Index
    equity = np.array([1000.0, 1000.0, 900.0, 900.0, 1000.0])
    ui = bm.ulcer_index(equity, capital=10000.0)
    assert ui > 0.0
    upi = bm.ulcer_performance_index(500.0, ui)
    assert upi > 0.0


def test_cornish_fisher_and_cvar():
    # Synthetic fat-tailed loss distribution
    np.random.seed(42)
    normal_returns = np.random.normal(loc=10.0, scale=50.0, size=500)
    cf_var = bm.cornish_fisher_var(normal_returns, alpha=0.05)
    cvar = bm.conditional_var(normal_returns, alpha=0.05)
    assert cf_var > 0.0
    assert cvar > 0.0
    assert cvar > abs(np.percentile(normal_returns, 5.0)) or abs(cvar - abs(np.percentile(normal_returns, 5.0))) < 50.0


def test_kelly_fractions():
    # 60% win rate, 1.5 payoff
    # Full Kelly: 0.6 - (1 - 0.6)/1.5 = 0.6 - 0.2667 = 0.3333
    full_k = bm.full_kelly_fraction(0.60, 1.50)
    assert abs(full_k - 0.3333) < 1e-3
    assert abs(bm.half_kelly_fraction(0.60, 1.50) - 0.1667) < 1e-3


def test_system_quality_number():
    pnl = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
    # Zero standard deviation returns 0.0
    assert bm.system_quality_number(pnl) == 0.0
    pnl_var = np.array([100.0, -50.0, 120.0, -40.0, 80.0])
    sqn = bm.system_quality_number(pnl_var)
    assert sqn > 0.0


def test_jarque_bera():
    normal_data = np.random.normal(0, 1, 1000)
    jb_stat, p_val = bm.jarque_bera_test(normal_data)
    assert jb_stat >= 0.0
    assert 0.0 <= p_val <= 1.0


def test_trimmed_profit_factor_and_dominance():
    # 10 trades: 8 normal wins ($100), 1 monster win ($5000), 5 normal losses ($100)
    trades = np.array([100.0] * 8 + [5000.0] + [-100.0] * 5)
    top1_dom = bm.top_n_dominance_pct(trades, n=1)
    assert top1_dom > 80.0  # Monster win dominates gross profit
    trimmed_pf = bm.trimmed_profit_factor(trades, trim_pct=0.15)
    # After trimming the monster win, PF should drop significantly
    assert trimmed_pf < 2.0


# =============================================================================
# 2. MASTER 88+ INSTITUTIONAL METRICS EVALUATION TEST
# =============================================================================

def test_calculate_institutional_metrics_full_suite():
    trades = np.array([
        150.0, -100.0, 200.0, -80.0, 300.0, -120.0, 180.0, 220.0, -90.0, 140.0,
        250.0, -110.0, 175.0, -95.0, 210.0, 160.0, -105.0, 190.0, 240.0, -85.0
    ])
    metrics = bm.calculate_institutional_metrics(trades, capital=25000.0)
    assert isinstance(metrics, dict)
    assert len(metrics) >= 88

    # Check key categories
    assert "sortino_ratio" in metrics
    assert "calmar_ratio" in metrics
    assert "omega_ratio" in metrics
    assert "cvar_95" in metrics
    assert "ulcer_index" in metrics
    assert "half_kelly" in metrics
    assert "sqn" in metrics
    assert "deflated_sharpe" in metrics
    assert "top_5_wins_pct" in metrics
    assert "trimmed_profit_factor" in metrics

    assert metrics["sortino_ratio"] > 0.0
    assert metrics["calmar_ratio"] > 0.0
    assert metrics["omega_ratio"] > 1.0
    assert metrics["total_trades"] == 20


# =============================================================================
# 3. PROVENANCE STORE ACID PERSISTENCE & ALIAS QUOTING
# =============================================================================

def test_provenance_store_extended_metrics_roundtrip(temp_store, tmp_path):
    data_file = tmp_path / "mock_dataset.parquet"
    data_file.write_bytes(b"MOCK_PARQUET_DATA_STREAM")

    trades = np.array([120.0, -60.0, 180.0, -70.0, 220.0, -50.0, 140.0])
    inst_metrics = bm.calculate_institutional_metrics(trades, capital=25000.0)

    record = temp_store.record_run(
        run_id="run_test_inst_001",
        strategy_id="test_candidate_s4",
        strategy_name="Test Candidate S4",
        methodology="walk_forward",
        date_start="2026-01-01",
        date_end="2026-06-30",
        data_path=data_file,
        total_trades=inst_metrics["total_trades"],
        win_rate=inst_metrics["win_rate"],
        profit_factor=inst_metrics["profit_factor"],
        gross_profit=inst_metrics["gross_profit"],
        net_profit=inst_metrics["net_pnl"],
        max_drawdown=inst_metrics["max_drawdown"],
        sharpe_ratio=inst_metrics["sharpe_ratio"],
        largest_win=inst_metrics["largest_win"],
        extended_metrics=inst_metrics,
    )

    assert record.sortino_ratio == inst_metrics["sortino_ratio"]
    assert record.calmar_ratio == inst_metrics["calmar_ratio"]
    assert record.cvar_95 == inst_metrics["cvar_95"]
    assert record.ulcer_index == inst_metrics["ulcer_index"]

    # Retrieve from DB
    fetched = temp_store.get_run("run_test_inst_001")
    assert fetched is not None
    assert fetched.sortino_ratio == inst_metrics["sortino_ratio"]
    assert fetched.calmar_ratio == inst_metrics["calmar_ratio"]

    # Test quote_stat with direct attribute and aliases
    quote_sortino = temp_store.quote_stat(fetched, "sortino")
    assert f"{inst_metrics['sortino_ratio']:.2f}" in quote_sortino
    assert "PROVENANCE VERIFICATION FOOTER" in quote_sortino

    quote_calmar = temp_store.quote_stat(fetched, "calmar")
    assert f"{inst_metrics['calmar_ratio']:.2f}" in quote_calmar

    quote_cvar = temp_store.quote_stat(fetched, "cvar95")
    assert f"{inst_metrics['cvar_95']:.2f}" in quote_cvar

    quote_trimmed = temp_store.quote_stat(fetched, "trimmed_profit_factor")
    assert f"{inst_metrics['trimmed_profit_factor']:.2f}" in quote_trimmed


@pytest.mark.generated_results
def test_cli_query_provenance_institutional_stats():
    """Verify scripts/query_provenance.py CLI quotes Sortino and Calmar on production baselines."""
    res_sortino = subprocess.run(
        [sys.executable, "scripts/query_provenance.py", "--strategy", "morning_va_breakout_s1", "--stat", "sortino"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert res_sortino.returncode == 0
    assert "Morning VA Breakout" in res_sortino.stdout
    assert "1.75" in res_sortino.stdout

    res_calmar = subprocess.run(
        [sys.executable, "scripts/query_provenance.py", "--strategy", "lucid_flex_ensemble", "--stat", "calmar"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert res_calmar.returncode == 0
    assert "LucidFlex 25K Multi-Strategy Ensemble" in res_calmar.stdout
    assert any(c in res_calmar.stdout for c in ["8.85", "1.03"])


# =============================================================================
# 4. IAF MICROSTRUCTURE, DIRECTIONAL SYMMETRY & CONSISTENCY TESTS
# =============================================================================

def test_iaf_directional_symmetry_and_excursion_metrics():
    """Verifies Long vs Short separation, holding duration asymmetry, and MFE/MAE."""
    df_trades = pd.DataFrame({
        "pnl": [150.0, -80.0, 200.0, -100.0, 300.0, -120.0, 180.0, -90.0],
        "direction": ["LONG", "LONG", "LONG", "LONG", "SHORT", "SHORT", "SHORT", "SHORT"],
        "hold_minutes": [25.0, 45.0, 30.0, 50.0, 20.0, 60.0, 35.0, 55.0],
        "mfe": [220.0, 20.0, 250.0, 15.0, 350.0, 30.0, 210.0, 10.0],
        "mae": [40.0, 95.0, 30.0, 110.0, 25.0, 130.0, 50.0, 105.0],
    })

    metrics = bm.calculate_institutional_metrics(df_trades, capital=25000.0)

    # 1. Long vs Short symmetry
    assert metrics["number_of_long_trades"] == 4
    assert metrics["number_of_short_trades"] == 4
    assert metrics["winning_long_trades"] == 2
    assert metrics["losing_long_trades"] == 2
    assert metrics["long_win_rate"] == 50.0
    assert metrics["short_win_rate"] == 50.0
    assert metrics["long_profit_factor"] == round(350.0 / 180.0, 2)
    assert metrics["short_profit_factor"] == round(480.0 / 210.0, 2)
    assert metrics["long_net_pnl"] == 170.0
    assert metrics["short_net_pnl"] == 270.0
    assert metrics["long_short_edge_asymmetry"] > 0.0

    # 2. Excursions
    assert metrics["mean_mfe"] > 0.0
    assert metrics["mean_mae"] > 0.0
    assert metrics["mfe_mae_ratio"] > 1.0
    assert metrics["edge_efficiency_ratio"] > 0.0

    # 3. Holding duration and asymmetry
    assert metrics["avg_hold_time_mins"] > 0.0
    assert metrics["avg_win_duration_mins"] > 0.0
    assert metrics["avg_loss_duration_mins"] > metrics["avg_win_duration_mins"]
    assert metrics["holding_duration_asymmetry"] > 1.0  # Losers held longer than winners


def test_iaf_walk_forward_consistency_and_stability():
    """Verifies rolling multi-window consistency and stability scores."""
    np.random.seed(42)
    daily = np.random.normal(50.0, 100.0, 252)
    metrics = bm.calculate_institutional_metrics(daily, capital=25000.0)

    assert "consistency_score" in metrics
    assert "stability_score" in metrics
    assert "return_consistency" in metrics
    assert "win_rate_consistency" in metrics
    assert "sharpe_consistency" in metrics

    assert 0.0 <= metrics["consistency_score"] <= 100.0
    assert 0.0 <= metrics["return_consistency"] <= 1.0
    assert 0.0 <= metrics["sharpe_consistency"] <= 1.0
