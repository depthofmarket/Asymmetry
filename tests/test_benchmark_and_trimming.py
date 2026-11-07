"""
Test Suite: Top 5% Adversarial Truncation & Passive Benchmark Relative Analytics.

Verifies:
1. Mathematical correctness of trim_winners_adversarial_test (5% trim, removed count,
   profit impact, expectancy, trimmed profit factor, edge_holds predicate).
2. Canonical strategy edge resilience: verifies that S1, S2, S3, and the Unified Ensemble
   all maintain positive expectancy and PF > 1.00 strictly when their top 5% of winners are removed.
3. Mathematical correctness of benchmark_relative_metrics (Beta, Jensen's Alpha, Correlation,
   Tracking Error, Information Ratio, Up/Down Capture).
4. Provenance Store and CLI query parity for trimmed_pf_5pct, edge_holds_5pct, beta, alpha.
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

from backtest import dashboard_analytics as da
import backtest.metrics as bm
from backtest.provenance import ProvenanceRecord, ProvenanceStore, default_store


# =============================================================================
# 1. ADVERSARIAL TRUNCATION (TOP 5% WINNERS REMOVED) TESTS
# =============================================================================

def test_trim_winners_synthetic():
    """Verifies that trim_winners_adversarial_test accurately trims the top 5% of wins."""
    # 100 trades: 60 wins of $100 each, plus 5 huge windfall wins of $1000 each; 35 losses of -$50
    wins_normal = [100.0] * 60
    wins_outlier = [1000.0] * 5
    losses = [-50.0] * 35
    trades = np.array(wins_normal + wins_outlier + losses)
    # Total wins = 65. 5% of 65 = ceil(3.25) = 4 trades
    res = bm.trim_winners_adversarial_test(trades, trim_pct=0.05)

    assert res["removed_count"] == 4
    # The 4 largest wins ($1000 each) should be removed
    assert abs(res["removed_profit"] - 4000.0) < 1e-4
    assert res["trimmed_pf"] > 1.0
    assert res["edge_holds"] is True
    assert res["trimmed_net"] == round(trades.sum() - 4000.0, 2)


def test_trim_winners_edge_cases():
    """Verifies edge case handling (empty, all losses, single win)."""
    # Empty
    res_empty = bm.trim_winners_adversarial_test(np.array([]))
    assert res_empty["trimmed_pf"] == 0.0
    assert res_empty["edge_holds"] is False

    # All losses
    res_losses = bm.trim_winners_adversarial_test(np.array([-50.0, -100.0, -20.0]))
    assert res_losses["trimmed_pf"] == 0.0
    assert res_losses["edge_holds"] is False
    assert res_losses["removed_count"] == 0

    # Single win
    res_single = bm.trim_winners_adversarial_test(np.array([100.0, -50.0]))
    assert res_single["removed_count"] == 1
    assert res_single["trimmed_pf"] == 0.0  # 0 profit / 50 loss
    assert res_single["edge_holds"] is False


def test_canonical_strategies_edge_holds_under_5pct_trimming():
    """
    CRITICAL EMPIRICAL PROOF:
    Every production baseline strategy (S1, S2, S3, Ensemble) MUST preserve an
    independent economic edge (PF > 1.00, positive expectancy) even when the
    top 5% of all winning trades are permanently excised.
    """
    trades = da.load_trades()
    assert len(trades) == 543

    # 1. Strategy 1 (09:45 VA Breakout)
    s1_pnl = trades[trades["strat"] == "S1"]["research_pnl"].to_numpy()
    s1_res = bm.trim_winners_adversarial_test(s1_pnl, trim_pct=0.05)
    assert s1_res["edge_holds"] is True
    assert s1_res["trimmed_pf"] >= 1.30, f"S1 Trimmed PF was {s1_res['trimmed_pf']}"
    assert s1_res["trimmed_expectancy"] > 0.0

    # 2. Strategy 2 (10:15 Gold Fix)
    s2_pnl = trades[trades["strat"] == "S2"]["research_pnl"].to_numpy()
    s2_res = bm.trim_winners_adversarial_test(s2_pnl, trim_pct=0.05)
    assert s2_res["edge_holds"] is True
    assert s2_res["trimmed_pf"] >= 1.25, f"S2 Trimmed PF was {s2_res['trimmed_pf']}"
    assert s2_res["trimmed_expectancy"] > 0.0

    # 3. Strategy 3 (08:35 Macro Momentum)
    s3_pnl = trades[trades["strat"] == "S3"]["research_pnl"].to_numpy()
    s3_res = bm.trim_winners_adversarial_test(s3_pnl, trim_pct=0.05)
    assert s3_res["edge_holds"] is True
    assert s3_res["trimmed_pf"] >= 1.20, f"S3 Trimmed PF was {s3_res['trimmed_pf']}"
    assert s3_res["trimmed_expectancy"] > 0.0

    # 4. Unified Composite Ensemble (All 3)
    comp_pnl = trades["research_pnl"].to_numpy()
    comp_res = bm.trim_winners_adversarial_test(comp_pnl, trim_pct=0.05)
    assert comp_res["edge_holds"] is True
    assert comp_res["trimmed_pf"] >= 1.30, f"Ensemble Trimmed PF was {comp_res['trimmed_pf']}"
    assert comp_res["trimmed_expectancy"] > 0.0
    assert comp_res["removed_count"] == 15
    assert comp_res["trimmed_net"] > 9000.0


# =============================================================================
# 2. BENCHMARK RELATIVE ANALYTICS (BETA, ALPHA, TRACKING ERROR) TESTS
# =============================================================================

def test_benchmark_relative_identity():
    """Strategy compared to itself should yield Beta=1.0, Corr=1.0, Alpha=0.0, TrackingError=0.0."""
    np.random.seed(42)
    series = np.random.normal(0.0005, 0.01, size=500)
    res = bm.benchmark_relative_metrics(series, series, annualization_factor=252.0)

    assert abs(res["beta"] - 1.0) < 1e-4
    assert abs(res["correlation"] - 1.0) < 1e-4
    assert abs(res["alpha"]) < 1e-4
    assert abs(res["tracking_error"]) < 1e-4
    assert abs(res["up_capture"] - 100.0) < 1e-4
    assert abs(res["down_capture"] - 100.0) < 1e-4


def test_benchmark_relative_uncorrelated():
    """Uncorrelated zero-mean series should have Beta~0.0, Correlation~0.0."""
    np.random.seed(42)
    s = np.random.normal(0.0, 0.01, size=1000)
    b = np.random.normal(0.0, 0.01, size=1000)
    res = bm.benchmark_relative_metrics(s, b, annualization_factor=252.0)

    assert abs(res["beta"]) < 0.10
    assert abs(res["correlation"]) < 0.10


def test_canonical_benchmark_relative_metrics():
    """
    CRITICAL PORTFOLIO STRUCTURAL PROOF:
    The quantitative ensemble exhibits market neutrality (Beta ~ 0.01, Correlation < 0.10)
    against the Nasdaq-100 benchmark, with positive annualized Jensen's Alpha (> +5%).
    """
    trades = da.load_trades()
    calendar = da.load_session_calendar(start=trades["date"].min(), end=trades["date"].max())

    nq_path = ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet"
    if not nq_path.exists():
        pytest.skip("NQ benchmark raw parquet not present")

    nq_df = pd.read_parquet(nq_path, columns=["time", "close"])
    nq_df["time"] = pd.to_datetime(nq_df["time"])
    nq_df["date"] = nq_df["time"].dt.strftime("%Y-%m-%d")
    nq_filt = nq_df[(nq_df["date"] >= trades["date"].min()) & (nq_df["date"] <= trades["date"].max())]
    nq_close = nq_filt.groupby("date")["close"].last()

    nq_s = pd.Series(index=calendar, dtype=float)
    for d in calendar:
        if d in nq_close.index:
            nq_s[d] = nq_close[d]
    nq_s = nq_s.ffill().bfill()
    nq_daily_returns = nq_s.pct_change().fillna(0.0).to_numpy(dtype=float)

    daily_comp = da.daily_series(trades, calendar, "research_pnl").to_numpy(dtype=float)

    m = bm.calculate_institutional_metrics(
        trades=trades["research_pnl"].to_numpy(),
        daily_returns=daily_comp,
        capital=25_000.0,
        benchmark_daily_returns=nq_daily_returns,
    )

    # 1. Market beta should be near zero (market neutral intraday scalper)
    assert abs(m["beta"]) < 0.05, f"Beta was {m['beta']}"
    assert abs(m["correlation"]) < 0.10, f"Correlation was {m['correlation']}"

    # 2. Annualized Alpha should be strongly positive
    assert m["alpha"] > 0.05, f"Alpha was {m['alpha']}"

    # 3. 5% Trimming fields populated
    assert m["trimmed_profit_factor_5pct"] >= 1.30
    assert m["edge_holds_5pct"] is True


# =============================================================================
# 3. PROVENANCE INTEGRATION & CLI QUERY TESTS
# =============================================================================

def test_provenance_store_retrieval():
    """Verifies that the canonical runs in provenance store contain the trimmed and benchmark stats."""
    rec = default_store.get_latest_run("lucid_flex_ensemble")
    assert rec is not None

    m = rec.metrics
    assert "trimmed_pf_5pct" in m or "trimmed_profit_factor_5pct" in m
    trimmed_val = m.get("trimmed_pf_5pct", m.get("trimmed_profit_factor_5pct"))
    assert float(trimmed_val) >= 1.30

    assert "beta" in m
    assert float(m["beta"]) < 0.05


def test_cli_query_trimmed_and_benchmark():
    """Verifies scripts/query_provenance.py CLI flags for trimmed_pf_5pct and beta."""
    res_trim = subprocess.run(
        [sys.executable, "scripts/query_provenance.py", "--strategy", "lucid_flex_ensemble", "--stat", "trimmed_pf_5pct"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert res_trim.returncode == 0
    assert "1.34" in res_trim.stdout
    assert "PROVENANCE VERIFICATION FOOTER" in res_trim.stdout

    res_beta = subprocess.run(
        [sys.executable, "scripts/query_provenance.py", "--strategy", "lucid_flex_ensemble", "--stat", "beta"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert res_beta.returncode == 0
    assert "0.01" in res_beta.stdout
    assert "PROVENANCE VERIFICATION FOOTER" in res_beta.stdout
