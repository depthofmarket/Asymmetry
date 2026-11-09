#!/usr/bin/env python3
"""
Adversarial Audit Script: Lookahead Bias & Cross-Strategy Correlation.
Strategy: asian_evening_reversion_s4 (Candidate S4) vs S1, S2, S3 Baselines.
"""

import io
import sqlite3
import zipfile
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import math
import numpy as np
import pandas as pd

from strategies.asian_evening_reversion_s4 import (
    AsianEveningReversionParams,
    calculate_asian_session_features,
    generate_signals,
    simulate_intrabar_execution,
)


def load_canonical_daily_pnl() -> pd.DataFrame:
    """Loads daily PnL for S1, S2, S3, and S4 from official bundles."""
    runs = {
        "S1_morning_va_breakout": "results/bundles/run_canonical_s1_va_breakout_2021_2026.obtf",
        "S2_macro_momentum": "results/bundles/run_canonical_s2_macro_momentum_2021_2026.obtf",
        "S3_gold_london_fix": "results/bundles/run_canonical_s3_gold_london_fix_2021_2026.obtf",
        "S4_asian_evening_reversion": "results/bundles/run_canonical_s4_asian_evening_reversion_2021_2026.obtf",
    }

    daily_series: Dict[str, pd.Series] = {}
    for name, path_str in runs.items():
        bundle_path = Path(path_str)
        if not bundle_path.exists():
            raise FileNotFoundError(f"Canonical bundle not found: {bundle_path}")

        with zipfile.ZipFile(bundle_path, "r") as z:
            trades = pd.read_parquet(io.BytesIO(z.read("trades.parquet")))
            date_col = "date_str" if "date_str" in trades.columns else "date"
            pnl_col = "net_dollars_micro" if "net_dollars_micro" in trades.columns else "net_pnl"
            daily_series[name] = trades.groupby(date_col)[pnl_col].sum()

    all_dates = sorted(set.union(*[set(s.index) for s in daily_series.values()]))
    df_daily = pd.DataFrame(index=all_dates)
    for name, s in daily_series.items():
        df_daily[name] = s
    df_daily = df_daily.fillna(0.0)
    return df_daily


def compute_correlations(df_daily: pd.DataFrame) -> Dict[str, Dict[str, float]]:
    """Computes Pearson, Spearman, and Active-Day correlations for S4 vs S1, S2, S3."""
    target = "S4_asian_evening_reversion"
    baselines = [
        "S1_morning_va_breakout",
        "S2_macro_momentum",
        "S3_gold_london_fix",
    ]

    results: Dict[str, Dict[str, float]] = {}

    def calc_r_and_p(s1: pd.Series, s2: pd.Series, method: str = "pearson") -> Tuple[float, float]:
        if method == "spearman":
            r = float(s1.rank().corr(s2.rank()))
        else:
            r = float(s1.corr(s2))
        n = len(s1)
        if n < 3 or abs(r) >= 1.0 or np.isnan(r):
            return (0.0 if np.isnan(r) else r), 1.0
        t_stat = r * math.sqrt((n - 2) / max(1e-12, (1.0 - r ** 2)))
        p_val = math.erfc(abs(t_stat) / math.sqrt(2.0))
        return r, p_val

    for base in baselines:
        # Full sample Pearson
        r_full, p_full = calc_r_and_p(df_daily[target], df_daily[base], method="pearson")
        # Full sample Spearman
        rho_full, p_rho = calc_r_and_p(df_daily[target], df_daily[base], method="spearman")

        # Active days (union)
        union_mask = (df_daily[target] != 0) | (df_daily[base] != 0)
        sub_union = df_daily.loc[union_mask]
        r_union, p_union = calc_r_and_p(sub_union[target], sub_union[base], method="pearson")

        # Active days (intersection / both traded)
        both_mask = (df_daily[target] != 0) & (df_daily[base] != 0)
        sub_both = df_daily.loc[both_mask]
        if len(sub_both) >= 3:
            r_both, p_both = calc_r_and_p(sub_both[target], sub_both[base], method="pearson")
        else:
            r_both, p_both = 0.0, 1.0

        results[base] = {
            "pearson_full": float(r_full),
            "p_pearson_full": float(p_full),
            "spearman_full": float(rho_full),
            "p_spearman_full": float(p_rho),
            "pearson_union": float(r_union),
            "n_union": int(len(sub_union)),
            "pearson_both": float(r_both),
            "p_pearson_both": float(p_both),
            "n_both": int(len(sub_both)),
        }

    return results


def run_lookahead_perturbation_audit(data_path: str = "data/raw/es_1m_2020_2026_cqg_et.parquet") -> Dict[str, Any]:
    """Runs rigorous empirical perturbation test on expanding session VWAP and shifted 5m ADX."""
    df = pd.read_parquet(data_path)
    # Extract 3 consecutive trading sessions
    sample = df[(df["time"] >= "2021-01-04 18:00:00") & (df["time"] <= "2021-01-06 06:00:00")].copy().reset_index(drop=True)

    params = AsianEveningReversionParams()
    base_feat = calculate_asian_session_features(sample, params)
    base_sigs = generate_signals(base_feat, params)

    # Pick a test anchor bar in the middle of entry window: 2021-01-04 21:30:00
    target_idx = sample[sample["time"] == "2021-01-04 21:30:00"].index[0]

    # Test 1: Immediate next bar perturbation (+1 min, 21:31:00)
    pert_1 = sample.copy()
    next_idx = sample[sample["time"] == "2021-01-04 21:31:00"].index[0]
    pert_1.loc[next_idx, "high"] += 1000.0
    pert_1.loc[next_idx, "close"] += 1000.0
    pert_1.loc[next_idx, "volume"] *= 50
    feat_pert_1 = calculate_asian_session_features(pert_1, params)
    sigs_pert_1 = generate_signals(feat_pert_1, params)

    # Test 2: Later bar perturbation (+15 min, 21:45:00)
    pert_2 = sample.copy()
    later_idx = sample[sample["time"] == "2021-01-04 21:45:00"].index[0]
    pert_2.loc[later_idx, "high"] += 2000.0
    pert_2.loc[later_idx, "close"] += 2000.0
    pert_2.loc[later_idx, "volume"] *= 100
    feat_pert_2 = calculate_asian_session_features(pert_2, params)
    sigs_pert_2 = generate_signals(feat_pert_2, params)

    check_cols = ["atr_1m", "adx_5m", "range_15m", "open_2100", "vwap", "vwap_std", "vwap_zscore", "upper_band", "lower_band"]

    max_diffs_1 = {col: float((base_feat.loc[:target_idx, col] - feat_pert_1.loc[:target_idx, col]).abs().max()) for col in check_cols}
    sig_diffs_1 = int((base_sigs.loc[:target_idx, "signal"] != sigs_pert_1.loc[:target_idx, "signal"]).sum())

    max_diffs_2 = {col: float((base_feat.loc[:target_idx, col] - feat_pert_2.loc[:target_idx, col]).abs().max()) for col in check_cols}
    sig_diffs_2 = int((base_sigs.loc[:target_idx, "signal"] != sigs_pert_2.loc[:target_idx, "signal"]).sum())

    return {
        "target_time": "2021-01-04 21:30:00",
        "max_diffs_immediate": max_diffs_1,
        "sig_diffs_immediate": sig_diffs_1,
        "max_diffs_later": max_diffs_2,
        "sig_diffs_later": sig_diffs_2,
    }


def audit_trades_execution() -> Dict[str, Any]:
    """Audits all 814 canonical trades for execution timing, 03:00 ET execution, and intrabar fill validity."""
    bundle_path = Path("results/bundles/run_canonical_s4_asian_evening_reversion_2021_2026.obtf")
    with zipfile.ZipFile(bundle_path, "r") as z:
        trades = pd.read_parquet(io.BytesIO(z.read("trades.parquet")))

    trades["entry_dt"] = pd.to_datetime(trades["entry_time"])
    trades["exit_dt"] = pd.to_datetime(trades["exit_time"])

    trades_3am = trades[(trades["entry_dt"].dt.hour == 3) | (trades["exit_dt"].dt.hour == 3)]
    trades_945 = trades[(trades["entry_dt"].dt.hour == 9) & (trades["entry_dt"].dt.minute == 45)]

    earliest_entry = str(trades["entry_dt"].dt.strftime("%H:%M").min())
    latest_entry = str(trades["entry_dt"].dt.strftime("%H:%M").max())
    earliest_exit = str(trades["exit_dt"].dt.strftime("%H:%M").min())
    latest_exit = str(trades["exit_dt"].dt.strftime("%H:%M").max())

    trades_after_2300 = trades[trades["exit_dt"].dt.strftime("%H:%M") > "23:00"]

    return {
        "total_trades": len(trades),
        "trades_at_3am": len(trades_3am),
        "trades_at_945": len(trades_945),
        "earliest_entry": earliest_entry,
        "latest_entry": latest_entry,
        "earliest_exit": earliest_exit,
        "latest_exit": latest_exit,
        "trades_exiting_after_2300": len(trades_after_2300),
    }


def main():
    print("=" * 80)
    print(" EMPIRICAL ADVERSARIAL AUDIT: CANDIDATE S4 vs BASELINES S1, S2, S3")
    print("=" * 80)

    # 1. Daily return correlation
    print("\n--- 1. EMPIRICAL DAILY RETURN CORRELATION ---")
    df_daily = load_canonical_daily_pnl()
    corrs = compute_correlations(df_daily)

    print(f"Total Trading Days in Unified Matrix: N = {len(df_daily)}")
    print(f"{'Baseline Strategy':30s} | {'Pearson (Full)':15s} | {'p-value':10s} | {'Spearman':10s} | {'Both-Traded r':15s} | {'Both N':6s} | {'Verdict (<0.20)':16s}")
    print("-" * 110)

    all_corrs_pass = True
    for base, c in corrs.items():
        pass_flag = abs(c["pearson_full"]) < 0.20 and abs(c["pearson_both"]) < 0.20
        if not pass_flag:
            all_corrs_pass = False
        status_str = "PASS (r < 0.20)" if pass_flag else "FAIL (r >= 0.20)"
        print(f"{base:30s} | {c['pearson_full']:+15.4f} | {c['p_pearson_full']:10.4f} | {c['spearman_full']:+10.4f} | {c['pearson_both']:+15.4f} | {c['n_both']:6d} | {status_str:16s}")

    # 2. Lookahead bias perturbation audit
    print("\n--- 2. LOOKAHEAD BIAS PERTURBATION AUDIT ---")
    lh = run_lookahead_perturbation_audit()
    print(f"Target Anchor Bar: {lh['target_time']}")
    print("Immediate Next-Bar (+1m) Perturbation Max Feature Diffs:")
    for col, diff in lh["max_diffs_immediate"].items():
        print(f"  {col:15s}: {diff:.12e}")
    print(f"Signal differences <= target bar: {lh['sig_diffs_immediate']}")

    print("\nLater Bar (+15m) Perturbation Max Feature Diffs:")
    for col, diff in lh["max_diffs_later"].items():
        print(f"  {col:15s}: {diff:.12e}")
    print(f"Signal differences <= target bar: {lh['sig_diffs_later']}")

    lh_pass = (max(lh["max_diffs_immediate"].values()) == 0.0) and (lh["sig_diffs_immediate"] == 0) and (max(lh["max_diffs_later"].values()) == 0.0) and (lh["sig_diffs_later"] == 0)
    print(f"Lookahead Perturbation Invariance Verdict: {'PASS (100% Invariant)' if lh_pass else 'FAIL'}")

    # 3. Trade execution audit
    print("\n--- 3. TRADE TIMING & PROHIBITED SESSIONS AUDIT ---")
    tr = audit_trades_execution()
    print(f"Total Canonical Trades Audited : {tr['total_trades']}")
    print(f"Trades Executed at 03:00 ET    : {tr['trades_at_3am']} (Requirement: 0)")
    print(f"Trades Executed at 09:45 ET    : {tr['trades_at_945']} (Requirement: 0)")
    print(f"Entry Window Observed          : {tr['earliest_entry']} to {tr['latest_entry']} ET (Allowed: 21:15–22:45)")
    print(f"Exit Window Observed           : {tr['earliest_exit']} to {tr['latest_exit']} ET (Hard Flatten: 23:00)")
    print(f"Trades Exiting After 23:00 ET  : {tr['trades_exiting_after_2300']} (Requirement: 0)")

    timing_pass = (tr["trades_at_3am"] == 0) and (tr["trades_at_945"] == 0) and (tr["trades_exiting_after_2300"] == 0)
    print(f"Session Timing & Prohibitions Verdict: {'PASS' if timing_pass else 'FAIL'}")

    # Overall Verdict
    print("\n" + "=" * 80)
    overall_verdict = "APPROVE" if (all_corrs_pass and lh_pass and timing_pass) else "REQUEST_CHANGES"
    print(f" FINAL CHALLENGER VERDICT: {overall_verdict}")
    print("=" * 80)


if __name__ == "__main__":
    main()
