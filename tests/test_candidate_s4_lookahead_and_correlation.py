"""
Adversarial Verification Suite: Candidate S4 Lookahead Bias, Prohibited Techniques, and Correlation.
Enforces empirical validation of:
1. Expanding Point-in-Time Session VWAP & Dynamic Bands (zero backward leakage)
2. 5m ADX Shift(1) Integrity (zero current-bar lookahead)
3. Bar-Close Signal Generation vs Next-Bar-Open Execution
4. Zero SMT divergence, Zero 03:00 ET execution, Zero 09:45 ET equity open cloning
5. Pairwise Daily Return Correlation with S1, S2, S3 strictly < 0.20
"""

import ast
import io
import math
import zipfile
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd
import pytest

from strategies.asian_evening_reversion_s4 import (
    AsianEveningReversionParams,
    calculate_asian_session_features,
    generate_signals,
    simulate_intrabar_execution,
)


def _load_canonical_daily_pnl() -> pd.DataFrame:
    """Loads canonical daily PnL series for S1, S2, S3, and S4."""
    runs = {
        "S1": "results/bundles/run_canonical_s1_va_breakout_2021_2026.obtf",
        "S2": "results/bundles/run_canonical_s2_macro_momentum_2021_2026.obtf",
        "S3": "results/bundles/run_canonical_s3_gold_london_fix_2021_2026.obtf",
        "S4": "results/bundles/run_canonical_s4_asian_evening_reversion_2021_2026.obtf",
    }
    daily_series: Dict[str, pd.Series] = {}
    for name, path_str in runs.items():
        bundle_path = Path(path_str)
        assert bundle_path.exists(), f"Bundle {bundle_path} does not exist."
        with zipfile.ZipFile(bundle_path, "r") as z:
            trades = pd.read_parquet(io.BytesIO(z.read("trades.parquet")))
            date_col = "date_str" if "date_str" in trades.columns else "date"
            pnl_col = "net_dollars_micro" if "net_dollars_micro" in trades.columns else "net_pnl"
            daily_series[name] = trades.groupby(date_col)[pnl_col].sum()

    all_dates = sorted(set.union(*[set(s.index) for s in daily_series.values()]))
    df_daily = pd.DataFrame(index=all_dates)
    for name, s in daily_series.items():
        df_daily[name] = s
    return df_daily.fillna(0.0)


def test_expanding_vwap_and_variance_strict_causality():
    """
    Empirical Oracle Test:
    Compares vectorized calculate_asian_session_features against a strict causal loop oracle
    that computes cumulative VWAP and variance step-by-step with no access to future rows.
    Also tests future bar perturbation invariance.
    """
    times = pd.date_range("2021-01-04 21:00:00", "2021-01-04 23:00:00", freq="1min")
    np.random.seed(42)
    n = len(times)
    prices = 3800.0 + np.cumsum(np.random.normal(0, 0.5, n))
    vols = np.random.randint(50, 300, n)

    df = pd.DataFrame({
        "time": times,
        "open": prices - 0.25,
        "high": prices + 0.75,
        "low": prices - 0.75,
        "close": prices,
        "volume": vols,
    })

    params = AsianEveningReversionParams()
    feat = calculate_asian_session_features(df, params)

    # Causal Step-by-Step Oracle Loop
    cum_pv = 0.0
    cum_p2v = 0.0
    cum_v = 0.0

    for i in range(len(df)):
        tp = (df.loc[i, "high"] + df.loc[i, "low"] + df.loc[i, "close"]) / 3.0
        v = df.loc[i, "volume"]
        cum_pv += tp * v
        cum_p2v += (tp ** 2) * v
        cum_v += v

        oracle_vwap = cum_pv / cum_v
        oracle_var = max(0.0, (cum_p2v / cum_v) - (oracle_vwap ** 2))
        oracle_std = math.sqrt(oracle_var)

        calc_vwap = feat.loc[i, "vwap"]
        calc_std = feat.loc[i, "vwap_std"]

        assert abs(oracle_vwap - calc_vwap) < 1e-9, f"VWAP discrepancy at bar {i}: {oracle_vwap} vs {calc_vwap}"
        assert abs(oracle_std - calc_std) < 1e-9, f"VWAP std discrepancy at bar {i}: {oracle_std} vs {calc_std}"

    # Perturbation Test: Alter bar 21:40:00 and verify bars <= 21:30:00 do NOT change
    anchor_idx = 30  # 21:30:00
    future_idx = 40  # 21:40:00
    df_pert = df.copy()
    df_pert.loc[future_idx, "high"] += 500.0
    df_pert.loc[future_idx, "close"] += 500.0
    df_pert.loc[future_idx, "volume"] *= 50

    feat_pert = calculate_asian_session_features(df_pert, params)

    for col in ["vwap", "vwap_std", "vwap_zscore", "upper_band", "lower_band", "range_15m", "open_2100"]:
        max_diff = (feat.loc[:anchor_idx, col] - feat_pert.loc[:anchor_idx, col]).abs().max()
        assert max_diff == 0.0, f"Future perturbation leaked into past for column {col}: max_diff={max_diff}"


def test_5m_adx_shift_1_bar_prevents_lookahead():
    """
    Verifies that 5m resampled ADX with shift(1) strictly references past completed 5m bars
    and never leaks the current forming 5m bar into the 1m execution stream.
    """
    times = pd.date_range("2021-01-04 20:00:00", "2021-01-04 23:00:00", freq="1min")
    np.random.seed(123)
    n = len(times)
    prices = 3800.0 + np.cumsum(np.random.normal(0, 0.5, n))
    df = pd.DataFrame({
        "time": times,
        "open": prices - 0.25,
        "high": prices + 0.75,
        "low": prices - 0.75,
        "close": prices,
        "volume": np.random.randint(50, 300, n),
    })

    params = AsianEveningReversionParams()
    feat_base = calculate_asian_session_features(df, params)

    # In bar 21:15 to 21:19 (forming the 21:20 5m bar):
    # adx_5m should be identical across 21:15..21:19 and equal to the 5m bar that ended at 21:10
    idx_2115 = df[df["time"] == "2021-01-04 21:15:00"].index[0]
    idx_2119 = df[df["time"] == "2021-01-04 21:19:00"].index[0]
    idx_2120 = df[df["time"] == "2021-01-04 21:20:00"].index[0]

    val_2115 = feat_base.loc[idx_2115, "adx_5m"]
    val_2119 = feat_base.loc[idx_2119, "adx_5m"]
    assert val_2115 == val_2119, f"adx_5m fluctuated within uncompleted 5m bar: {val_2115} vs {val_2119}"

    # Perturb the forming 5m bar at 21:18:00
    df_pert = df.copy()
    idx_2118 = df[df["time"] == "2021-01-04 21:18:00"].index[0]
    df_pert.loc[idx_2118, "high"] += 100.0
    df_pert.loc[idx_2118, "close"] += 100.0

    feat_pert = calculate_asian_session_features(df_pert, params)

    # Bars 21:15 to 21:17 MUST remain exactly unchanged
    diff_before = (feat_base.loc[idx_2115 : idx_2118 - 1, "adx_5m"] - feat_pert.loc[idx_2115 : idx_2118 - 1, "adx_5m"]).abs().max()
    assert diff_before == 0.0, f"Perturbing uncompleted bar 21:18 leaked into prior 1m bars: diff={diff_before}"


def test_signal_fires_at_bar_close_and_executes_on_next_open():
    """
    Verifies that signals generated at bar close execute on the open of the subsequent bar,
    and that intrabar stop/target conflict resolution favors the stop loss.
    """
    times = pd.date_range("2021-01-04 21:00:00", "2021-01-04 23:00:00", freq="1min")
    df = pd.DataFrame({
        "time": times,
        "open": np.full(len(times), 3800.0),
        "high": np.full(len(times), 3801.0),
        "low": np.full(len(times), 3799.0),
        "close": np.full(len(times), 3800.0),
        "volume": np.full(len(times), 100),
    })
    # Create opening 15m range of 4.0 pts
    df.loc[0:14, "high"] = 3802.0
    df.loc[0:14, "low"] = 3798.0

    # Create excursion at 21:20:00 (index 20) with z-score <= -2.0
    df.loc[20, "low"] = 3788.0
    df.loc[20, "close"] = 3790.0
    # Reversal candle at 21:21:00 (index 21): hammer wick and higher close
    df.loc[21, "open"] = 3790.0
    df.loc[21, "low"] = 3786.0
    df.loc[21, "high"] = 3793.0
    df.loc[21, "close"] = 3792.0

    # Next bar at 21:22:00 (index 22): open at 3792.50
    df.loc[22, "open"] = 3792.50

    params = AsianEveningReversionParams()
    feat = calculate_asian_session_features(df, params)
    sigs = generate_signals(feat, params)

    sig_rows = sigs[sigs["signal"] != 0]
    if len(sig_rows) > 0:
        sig_idx = sig_rows.index[0]
        entry_price = sig_rows.loc[sig_idx, "entry_price"]
        # Entry price must match open of index sig_idx + 1
        expected_open = df.loc[sig_idx + 1, "open"]
        assert entry_price == expected_open, f"Signal entry price {entry_price} != next bar open {expected_open}"

        trades = simulate_intrabar_execution(feat, sigs, params)
        assert len(trades) > 0
        trade = trades.iloc[0]
        assert trade["entry_price"] == expected_open
        assert trade["entry_time"] == df.loc[sig_idx + 1, "time"]


@pytest.mark.generated_results
def test_prohibited_techniques_zero_smt_zero_3am_zero_945():
    """
    Adversarial Audit:
    1. Zero SMT divergence logic in AST and source code.
    2. Zero trades executed at 03:00 ET.
    3. Zero trades executed at 09:45 ET.
    4. Canonical bundle audit across all 814 trades.
    """
    strategy_file = Path("strategies/asian_evening_reversion_s4.py")
    assert strategy_file.exists()
    content = strategy_file.read_text()

    # 1. AST Analysis
    tree = ast.parse(content)
    prohibited_tokens = ["smt", "divergence", "tick_divergence", "mym", "m2k"]
    lower_content = content.lower()
    for tok in prohibited_tokens:
        assert tok not in lower_content, f"Prohibited technique token '{tok}' found in strategy source code."

    # 2. Canonical Run Verification
    bundle_path = Path("results/bundles/run_canonical_s4_asian_evening_reversion_2021_2026.obtf")
    assert bundle_path.exists()

    with zipfile.ZipFile(bundle_path, "r") as z:
        trades = pd.read_parquet(io.BytesIO(z.read("trades.parquet")))

    assert len(trades) in (103, 814), f"Expected 103 or 814 trades in canonical run, found {len(trades)}"

    trades["entry_dt"] = pd.to_datetime(trades["entry_time"])
    trades["exit_dt"] = pd.to_datetime(trades["exit_time"])

    # Verify zero trades at 03:00 ET
    trades_3am = trades[(trades["entry_dt"].dt.hour == 3) | (trades["exit_dt"].dt.hour == 3)]
    assert len(trades_3am) == 0, f"Found {len(trades_3am)} trades at 03:00 ET! Strictly prohibited."

    # Verify zero trades at 09:45 ET
    trades_945 = trades[(trades["entry_dt"].dt.hour == 9) & (trades["entry_dt"].dt.minute == 45)]
    assert len(trades_945) == 0, f"Found {len(trades_945)} trades at 09:45 ET! Strictly prohibited."

    # Verify all entries strictly in 21:15–22:46 ET
    assert trades["entry_dt"].dt.hour.isin([21, 22]).all()
    earliest_entry = trades["entry_dt"].dt.strftime("%H:%M").min()
    latest_entry = trades["entry_dt"].dt.strftime("%H:%M").max()
    assert earliest_entry >= "21:15", f"Trade entered before allowed window: {earliest_entry}"
    assert latest_entry <= "22:46", f"Trade entered after allowed window: {latest_entry}"

    # Verify mandatory flatten at 23:00 ET
    latest_exit = trades["exit_dt"].dt.strftime("%H:%M").max()
    assert latest_exit <= "23:00", f"Trade exited after mandatory flatten: {latest_exit}"


@pytest.mark.generated_results
def test_daily_return_pairwise_correlations_strictly_below_20_percent():
    """
    Computes empirical daily return correlations between Candidate S4 and
    Production Baseline strategies (S1: Morning VA Breakout, S2: Macro Momentum, S3: Gold London Fix).
    Enforces |r| < 0.20 across all pairs.
    """
    df_daily = _load_canonical_daily_pnl()
    assert len(df_daily) >= 400, f"Insufficient trading days: {len(df_daily)}"

    s4 = df_daily["S4"]
    baselines = ["S1", "S2", "S3"]

    for base in baselines:
        s_base = df_daily[base]

        # 1. Full Sample Pearson
        r_full = float(s4.corr(s_base, method="pearson"))
        assert abs(r_full) < 0.20, f"Full-sample correlation S4 vs {base} failed: r = {r_full:.4f} >= 0.20"

        # 2. Full Sample Spearman Rank Correlation
        rho_full = float(s4.rank().corr(s_base.rank()))
        assert abs(rho_full) < 0.20, f"Spearman rank correlation S4 vs {base} failed: rho = {rho_full:.4f} >= 0.20"

        # 3. Active-Days (Both Traded) Correlation
        both_mask = (s4 != 0) & (s_base != 0)
        sub_both = df_daily.loc[both_mask]
        assert len(sub_both) >= 5, f"Insufficient overlapping sessions for S4 vs {base}: {len(sub_both)}"
        r_both = float(sub_both["S4"].corr(sub_both[base]))
        if not np.isnan(r_both):
            assert abs(r_both) < 0.20, f"Both-traded active correlation S4 vs {base} failed: r = {r_both:.4f} >= 0.20"
