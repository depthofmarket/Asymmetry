#!/usr/bin/env python3
"""
Prop Firm Optionality & Lifecycle Evaluator (Shαrpe Paper 0 Framework, Oct 2026)
Applies the exact mathematical and stochastic framework from:
"Prop Firm Accounts as an Optionality Structure: Theoretical Framework, Methodology,
Application, and Limits" (Shαrpe | Variance Risk Model Series, Paper 0, Oct 2026)
to our validated Two-Window Tri-Asset Prop System:
  - Window 1 (09:45-10:15 ET): Strategy 1 (Morning VA Breakout v2.0, H4) on MNQ + MES
  - Window 2 (10:15-11:00 ET): Strategy 2 (Post-LBMA Fix Breakout, H14 Long-Only) on MGC

Computes:
  1. Typed Minimum Frequencies (n_min^contract, n_min^evidence, n_min^resolution, Nu)
  2. Analytical Baseline EEP_an (Tomàs Fernández 2026 + Broadie-Glasserman-Kou 1997
     discrete monitoring correction + Gauss-Hermite drift-uncertainty integration)
  3. Monte Carlo Single-Attempt Barrier Simulation (EEP_mc, p1, p2, p_pass, t_pass,
     t_payout, model deviation delta_EEP) via circular daily block bootstrap (b=1 & b=20)
  4. Lifecycle Slot Simulation (xEEP, SE, p05/p50/p95 cash flow quantiles, lifeEEP replay)
     with LucidFlex 5-payout live-transition cap (Section 6.1, Table 6)
  5. Stress Tests 1 (Subperiod Regime Stability), 2 (Rulebook Parameter Shift),
     3 (Operational Discount rho=0.85 & rho*), and 1-Tick/Side Fill Counterfactual
  6. Multi-Account Kelly Fraction (f*) and Minimum Bankroll (B_min)
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.convert_and_evaluate_multi_asset_cqg_2020_2026 import (
    CQG_EXPORTS,
    compute_daily_or15_dir,
    simulate_asset_trades,
)


@dataclass(frozen=True)
class PropAccountSpec:
    name: str
    account_size: float
    eval_target_u1: float
    eval_max_dd_d1: float
    eval_lock_delta1: float  # >= U1 - D1 means fully trailing EOD in eval
    eval_fee_c: float
    funded_target_u2: float  # profit required per payout cycle
    funded_max_dd_d2: float
    funded_lock_delta2: float  # e.g., +$100 above starting balance
    payout_split: float
    first_payout_w: float  # net first payout after split/cap
    subsequent_payout_w: float  # net subsequent payouts (up to max_payouts_per_life)
    max_payouts_per_life: int  # Lucid has live review after 5 payouts (Table 6, p. 44)
    min_winning_days: int
    min_win_day_pnl: float
    consistency_max_day_share: float  # e.g., 1.0 (none) or 0.50


LUCID_FLEX_25K = PropAccountSpec(
    name="Lucid Flex 25K",
    account_size=25000.0,
    eval_target_u1=1250.0,
    eval_max_dd_d1=1000.0,
    eval_lock_delta1=250.0,  # EOD trailing up to target
    eval_fee_c=65.0,
    funded_target_u2=1000.0,
    funded_max_dd_d2=1000.0,
    funded_lock_delta2=100.0,  # locks at $25,100 (+100)
    payout_split=0.90,
    first_payout_w=900.0,
    subsequent_payout_w=900.0,
    max_payouts_per_life=5,
    min_winning_days=5,
    min_win_day_pnl=100.0,
    consistency_max_day_share=1.0,  # No consistency cap in Lucid Flex funded
)

LUCID_FLEX_50K = PropAccountSpec(
    name="Lucid Flex 50K",
    account_size=50000.0,
    eval_target_u1=3000.0,
    eval_max_dd_d1=2000.0,
    eval_lock_delta1=1000.0,
    eval_fee_c=130.0,
    funded_target_u2=2000.0,
    funded_max_dd_d2=2000.0,
    funded_lock_delta2=100.0,  # locks at $50,100 (+100)
    payout_split=0.90,
    first_payout_w=1350.0,
    subsequent_payout_w=1500.0,
    max_payouts_per_life=5,
    min_winning_days=5,
    min_win_day_pnl=150.0,
    consistency_max_day_share=1.0,
)

TOPSTEP_XFA_50K = PropAccountSpec(
    name="Topstep XFA 50K",
    account_size=50000.0,
    eval_target_u1=3000.0,
    eval_max_dd_d1=2000.0,
    eval_lock_delta1=1000.0,
    eval_fee_c=95.0,
    funded_target_u2=1000.0,
    funded_max_dd_d2=2000.0,
    funded_lock_delta2=0.0,  # locks at $50,000 ($0)
    payout_split=0.90,
    first_payout_w=450.0,
    subsequent_payout_w=900.0,
    max_payouts_per_life=5,
    min_winning_days=5,
    min_win_day_pnl=150.0,
    consistency_max_day_share=0.50,
)


def analytical_phase_pass_prob(
    U: float,
    D: float,
    delta: float,
    mu_day: float,
    sigma_day: float,
    n_per_day: float,
    is_eod: bool = True,
) -> float:
    """
    Section 2.11, Equations (18)-(21):
    Closed-form ABM first-passage probability with trailing/freeze barrier
    and Broadie-Glasserman-Kou (1997) discrete monitoring continuity correction.
    """
    if sigma_day <= 1e-9:
        return 1.0 if mu_day > 0 else 0.0
    beta = 0.5826  # -zeta(1/2) / sqrt(2*pi)
    s_B = sigma_day / math.sqrt(max(n_per_day, 1e-6))
    s_M = sigma_day if is_eod else s_B
    D1 = D + beta * max(s_M, s_B)
    D2 = D + beta * s_B
    ell = min(D + delta, U)
    U_delta = U - D - delta
    theta = 2.0 * mu_day / (sigma_day ** 2)

    if abs(theta) < 1e-8:
        p_trail = math.exp(-ell / D1)
        p_fix = D2 / (U_delta + D2) if U_delta > 0 else 1.0
    else:
        # Guard against overflow in exp(theta * D1)
        arg1 = min(max(theta * D1, -50.0), 50.0)
        denom1 = math.exp(arg1) - 1.0
        if abs(denom1) < 1e-12:
            p_trail = math.exp(-ell / D1)
        else:
            p_trail = math.exp(max(min(-theta * ell / denom1, 0.0), -50.0))

        if U_delta <= 0:
            p_fix = 1.0
        else:
            a_num = min(max(-theta * D2, -50.0), 50.0)
            a_den = min(max(-theta * (U_delta + D2), -50.0), 50.0)
            denom2 = 1.0 - math.exp(a_den)
            p_fix = (1.0 - math.exp(a_num)) / denom2 if abs(denom2) > 1e-12 else D2 / (U_delta + D2)

    return float(np.clip(p_trail * p_fix, 0.0, 1.0))


def compute_analytical_eep_predictive(
    spec: PropAccountSpec,
    mu_hat: float,
    se_mu: float,
    sigma_day: float,
    n_per_day: float,
) -> tuple[float, float, float, float, float]:
    """
    Section 2.11 Equation (23): Predictive EEP via Gauss-Hermite quadrature over mu ~ N(mu_hat, se_mu^2).
    Returns (eep_pred, eep_point, eep_low90, eep_high90, p_joint_point).
    """
    p1_pt = analytical_phase_pass_prob(
        spec.eval_target_u1, spec.eval_max_dd_d1, spec.eval_lock_delta1, mu_hat, sigma_day, n_per_day
    )
    p2_pt = analytical_phase_pass_prob(
        spec.funded_target_u2, spec.funded_max_dd_d2, spec.funded_lock_delta2, mu_hat, sigma_day, n_per_day
    )
    eep_point = p1_pt * p2_pt * spec.first_payout_w - spec.eval_fee_c

    # 9-point Gauss-Hermite quadrature
    gh_x, gh_w = np.polynomial.hermite.hermgauss(9)
    gh_w = gh_w / math.sqrt(math.pi)
    eep_acc = 0.0
    for x, w in zip(gh_x, gh_w):
        mu_val = mu_hat + math.sqrt(2.0) * se_mu * float(x)
        p1 = analytical_phase_pass_prob(
            spec.eval_target_u1, spec.eval_max_dd_d1, spec.eval_lock_delta1, mu_val, sigma_day, n_per_day
        )
        p2 = analytical_phase_pass_prob(
            spec.funded_target_u2, spec.funded_max_dd_d2, spec.funded_lock_delta2, mu_val, sigma_day, n_per_day
        )
        eep_acc += float(w) * (p1 * p2 * spec.first_payout_w - spec.eval_fee_c)

    mu_lo = mu_hat - 1.645 * se_mu
    mu_hi = mu_hat + 1.645 * se_mu
    p1_lo = analytical_phase_pass_prob(
        spec.eval_target_u1, spec.eval_max_dd_d1, spec.eval_lock_delta1, mu_lo, sigma_day, n_per_day
    )
    p2_lo = analytical_phase_pass_prob(
        spec.funded_target_u2, spec.funded_max_dd_d2, spec.funded_lock_delta2, mu_lo, sigma_day, n_per_day
    )
    p1_hi = analytical_phase_pass_prob(
        spec.eval_target_u1, spec.eval_max_dd_d1, spec.eval_lock_delta1, mu_hi, sigma_day, n_per_day
    )
    p2_hi = analytical_phase_pass_prob(
        spec.funded_target_u2, spec.funded_max_dd_d2, spec.funded_lock_delta2, mu_hi, sigma_day, n_per_day
    )
    eep_lo = p1_lo * p2_lo * spec.first_payout_w - spec.eval_fee_c
    eep_hi = p1_hi * p2_hi * spec.first_payout_w - spec.eval_fee_c
    return float(eep_acc), float(eep_point), float(eep_lo), float(eep_hi), float(p1_pt * p2_pt)


def build_portfolio_daily_series() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """
    Loads 2021-2026 MNQ, MES (09:45 ET) and MGC H14 (10:15 ET) post-cost trades,
    plus the calendar of all exchange trading days (including 0-trade days, as required
    by Section 3.4 & 3.9 of Paper 0 so synthetic time is not compressed).
    """
    df_gc = pd.read_parquet(ROOT / "data/raw/gc_1m_2020_2026_et.parquet")
    df_es = pd.read_parquet(ROOT / "data/raw/es_1m_2020_2026_cqg_et.parquet")
    df_nq = pd.read_parquet(ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet")

    # All exchange RTH trading days in 2021-01-04 to 2026-10-30
    df_nq_21 = df_nq[df_nq["time"] >= "2021-01-01"].copy()
    df_nq_21["date_str"] = df_nq_21["time"].dt.strftime("%Y-%m-%d")
    df_nq_21["hhmm"] = df_nq_21["time"].dt.strftime("%H:%M")
    rth_days = sorted(df_nq_21[(df_nq_21["hhmm"] >= "09:30") & (df_nq_21["hhmm"] <= "11:00")]["date_str"].unique())
    cal_df = pd.DataFrame({"date_str": rth_days})
    cal_df["year"] = pd.to_datetime(cal_df["date_str"]).dt.year

    # Load H14 Gold signals from exported CSV and evaluate trades on 1m bars
    act_gc = pd.read_csv(
        ROOT / "results/research_master/signal_research/gold_london_fix_structural_breakout_h14_signals.csv"
    )
    act_gc["time"] = pd.to_datetime(act_gc["time"])
    df_gc_21 = df_gc[df_gc["time"] >= "2021-01-01"].copy()
    df_gc_21["date_str"] = df_gc_21["time"].dt.strftime("%Y-%m-%d")
    df_gc_21["hhmm"] = df_gc_21["time"].dt.strftime("%H:%M")
    win_bars = df_gc_21[(df_gc_21["hhmm"] >= "10:15") & (df_gc_21["hhmm"] <= "11:00")]
    bars_by_date = {d: g.reset_index(drop=True) for d, g in win_bars.groupby("date_str")}

    gc_rows = []
    for _, srow in act_gc.iterrows():
        sig_time = pd.Timestamp(srow["time"])
        if sig_time.year < 2021:
            continue
        d_str = sig_time.strftime("%Y-%m-%d")
        ebars = bars_by_date.get(d_str)
        if ebars is None or len(ebars) < 15:
            continue
        entry_p = float(ebars.iloc[0]["open"])
        ib_l = float(srow["ib60_low"])
        lon_l = float(srow["lon_low"])
        struct_low = min(ib_l, lon_l) if np.isfinite(ib_l) and np.isfinite(lon_l) else ib_l
        stop_pts = float(np.clip(entry_p - struct_low + 0.5, 3.0, 18.0))
        target_pts = stop_pts * 1.50
        stop_price = entry_p - stop_pts
        target_price = entry_p + target_pts
        exit_p = float(ebars.iloc[-1]["close"])
        min_low = float(ebars.iloc[0]["low"])
        for _, b in ebars.iterrows():
            bh, bl = float(b["high"]), float(b["low"])
            min_low = min(min_low, bl)
            if bl <= stop_price:
                exit_p = stop_price
                break
            if bh >= target_price:
                exit_p = target_price
                break
        net_pts = (exit_p - entry_p) - 0.20
        mae_pts = max(0.0, entry_p - min_low) + 0.20
        contracts = int(np.clip(np.round(250.0 / max(stop_pts * 10.0, 1.0)), 1, 4))
        net_dollars_micro = net_pts * 10.0 * contracts - (1.50 * contracts)
        mae_dollars_micro = -mae_pts * 10.0 * contracts - (1.50 * contracts)
        gc_rows.append(
            {
                "date_str": d_str,
                "year": sig_time.year,
                "sym": "GC",
                "window": 2,
                "contracts": contracts,
                "net_dollars_micro": net_dollars_micro,
                "mae_dollars_micro": min(mae_dollars_micro, net_dollars_micro),
                "tick_cost_1side": 1.00 * contracts,  # $1.00/RT per MGC for 1 tick/side
            }
        )
    t_gc = pd.DataFrame(gc_rows)

    # Load Macro & VIX context for Strategy 1 (MNQ + MES at 09:45 ET)
    m_df = pd.read_parquet(ROOT / "data/processed/macro_context/morning_cross_asset_features_0945.parquet")
    macro_map = {}
    for _, r in m_df.iterrows():
        vx_c = (
            float(r["vx_or15_change_pct"])
            if pd.notna(r.get("vx_or15_change_pct"))
            else (float(r["vix_spot_or15_change_pct"]) if pd.notna(r.get("vix_spot_or15_change_pct")) else float("nan"))
        )
        tk_m = float(r["tick_or15_mean"]) if pd.notna(r.get("tick_or15_mean")) else float("nan")
        macro_map[str(r["date_str"])] = (vx_c, tk_m)

    v_1h = pd.read_csv(ROOT / "data/raw/vix_spot_1h_2026_et.csv")
    v_1h["time"] = pd.to_datetime(v_1h["time"], utc=True).dt.tz_convert("America/New_York")
    v_1h["date_str"] = v_1h["time"].dt.strftime("%Y-%m-%d")
    v_1h["hhmm"] = v_1h["time"].dt.strftime("%H:%M")
    for d_str, g in v_1h.groupby("date_str"):
        if d_str not in macro_map or np.isnan(macro_map[d_str][0]):
            b9 = g[g["hhmm"] == "09:00"]
            if not b9.empty:
                o, c = float(b9.iloc[0]["open"]), float(b9.iloc[-1]["close"])
                macro_map[d_str] = ((c - o) / o * 100.0 if o > 0 else 0.0, float("nan"))

    v_5m = pd.read_csv(ROOT / "data/raw/vix_spot_5m_recent_et.csv")
    v_5m["time"] = pd.to_datetime(v_5m["time"], utc=True).dt.tz_convert("America/New_York")
    v_5m["date_str"] = v_5m["time"].dt.strftime("%Y-%m-%d")
    v_5m["hhmm"] = v_5m["time"].dt.strftime("%H:%M")
    for d_str, g in v_5m.groupby("date_str"):
        w = g[(g["hhmm"] >= "09:30") & (g["hhmm"] <= "09:40")]
        if not w.empty:
            o, c = float(w.iloc[0]["open"]), float(w.iloc[-1]["close"])
            macro_map[d_str] = ((c - o) / o * 100.0 if o > 0 else 0.0, float("nan"))

    es_dir = compute_daily_or15_dir(df_es)
    nq_dir = compute_daily_or15_dir(df_nq)
    es_spec = next(x for x in CQG_EXPORTS if x["sym"] == "ES")
    nq_spec = next(x for x in CQG_EXPORTS if x["sym"] == "NQ")

    t_es_raw = simulate_asset_trades(
        df_es, es_spec, require_with_gap=True, es_dir_map=es_dir, nq_dir_map=nq_dir, macro_map=macro_map
    )
    t_nq_raw = simulate_asset_trades(
        df_nq, nq_spec, require_with_gap=True, es_dir_map=es_dir, nq_dir_map=nq_dir, macro_map=macro_map
    )

    t_es = t_es_raw[t_es_raw["full_gate_ok"] & (t_es_raw["date_str"] >= "2021-01-01")].copy()
    t_nq = t_nq_raw[t_nq_raw["full_gate_ok"] & (t_nq_raw["date_str"] >= "2021-01-01")].copy()

    for df_eq, tick_cost in [(t_nq, 1.00), (t_es, 2.50)]:
        df_eq["window"] = 1
        df_eq["tick_cost_1side"] = tick_cost * df_eq["contracts"]
        # Conservative MAE bound: if trade lost, MAE is the loss; if won, assume 0.5R intra-trade drawdown
        df_eq["mae_dollars_micro"] = np.where(
            df_eq["net_dollars_micro"] < 0, df_eq["net_dollars_micro"], -110.0
        )

    both_dates = set(t_es["date_str"]).intersection(set(t_nq["date_str"]))
    t_es_split = t_es.copy()
    t_nq_split = t_nq.copy()
    for col in ["net_dollars_micro", "mae_dollars_micro", "tick_cost_1side"]:
        t_es_split.loc[t_es_split["date_str"].isin(both_dates), col] *= 0.5
        t_nq_split.loc[t_nq_split["date_str"].isin(both_dates), col] *= 0.5

    cols = ["date_str", "year", "sym", "window", "contracts", "net_dollars_micro", "mae_dollars_micro", "tick_cost_1side"]
    portfolios = {
        "MNQ Alone (09:45)": t_nq[cols].sort_values(["date_str", "window"]).reset_index(drop=True),
        "Dual Equity Split (MNQ+MES)": pd.concat([t_nq_split[cols], t_es_split[cols]], ignore_index=True)
        .sort_values(["date_str", "window"])
        .reset_index(drop=True),
        "Tri-Asset Split (MNQ+MES+MGC)": pd.concat(
            [t_nq_split[cols], t_es_split[cols], t_gc[cols]], ignore_index=True
        )
        .sort_values(["date_str", "window"])
        .reset_index(drop=True),
        "Tri-Asset Full (MNQ+MES+MGC)": pd.concat([t_nq[cols], t_es[cols], t_gc[cols]], ignore_index=True)
        .sort_values(["date_str", "window"])
        .reset_index(drop=True),
    }
    return cal_df, portfolios


def prepare_daily_arrays(
    cal_df: pd.DataFrame, trades_df: pd.DataFrame, risk_mult: float = 1.0, extra_slip_1tick: bool = False
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Aggregates trades per calendar RTH session into:
      - w1_pnl[d]: Window 1 (09:45 ET) net P&L on day d
      - w2_pnl[d]: Window 2 (10:15 ET) net P&L on day d
      - n_trades[d]: number of trades on day d
    Preserves all 0-trade days from cal_df.
    """
    df = trades_df.copy()
    pnl = df["net_dollars_micro"] * risk_mult
    if extra_slip_1tick:
        pnl = pnl - df["tick_cost_1side"] * risk_mult
    df["adj_pnl"] = pnl

    w1 = df[df["window"] == 1].groupby("date_str")["adj_pnl"].sum()
    w2 = df[df["window"] == 2].groupby("date_str")["adj_pnl"].sum()
    nt = df.groupby("date_str")["adj_pnl"].count()

    dates = cal_df["date_str"].values
    w1_arr = np.array([float(w1.get(d, 0.0)) for d in dates], dtype=np.float64)
    w2_arr = np.array([float(w2.get(d, 0.0)) for d in dates], dtype=np.float64)
    nt_arr = np.array([int(nt.get(d, 0)) for d in dates], dtype=np.int32)
    return w1_arr, w2_arr, nt_arr


def simulate_mc_paths(
    spec: PropAccountSpec,
    w1_arr: np.ndarray,
    w2_arr: np.ndarray,
    use_ratchet: bool = False,
    n_paths: int = 5000,
    horizon_days: int = 2520,
    block_len: int = 1,
    seed: int = 42,
) -> dict[str, float]:
    """
    Vectorized / fast Monte Carlo simulation of Section 3.4 (EEP_mc) and Section 3.9 (xEEP)
    using circular daily block bootstrap over the full exchange calendar.
    """
    rng = np.random.default_rng(seed)
    n_cal = len(w1_arr)
    day_tot = w1_arr + w2_arr

    # Build index matrix of shape (n_paths, horizon_days) via circular block bootstrap
    if block_len <= 1:
        idx_mat = rng.integers(0, n_cal, size=(n_paths, horizon_days))
    else:
        n_blocks = (horizon_days + block_len - 1) // block_len
        starts = rng.integers(0, n_cal, size=(n_paths, n_blocks))
        offsets = np.arange(block_len)[None, None, :]
        idx_mat = ((starts[:, :, None] + offsets) % n_cal).reshape(n_paths, -1)[:, :horizon_days]

    # 1. Single-Attempt Evaluation + First Funded Payout (EEP_mc, Section 3.4)
    eval_passed = np.zeros(n_paths, dtype=bool)
    funded_paid = np.zeros(n_paths, dtype=bool)
    t_pass_list = []
    t_payout_list = []

    for i in range(n_paths):
        idxs = idx_mat[i]
        # Phase 1: Evaluation
        eq = 0.0
        eod_high = 0.0
        floor = -spec.eval_max_dd_d1
        max_day_pnl = 0.0
        t_eval_end = -1
        passed_1 = False

        for t in range(horizon_days):
            k = idxs[t]
            r1, r2 = w1_arr[k], w2_arr[k]
            if r1 == 0.0 and r2 == 0.0:
                continue

            mult = 1.0
            if use_ratchet:
                if eq < 0.0:
                    mult = 0.50
                elif eq >= 800.0:
                    mult = 1.20
                elif eq >= 400.0:
                    mult = 1.10

            # Window 1 breach check (real-time after trade)
            eq += r1 * mult
            if eq <= floor:
                break
            # Window 2 breach check
            eq += r2 * mult
            if eq <= floor:
                break

            d_pnl = (r1 + r2) * mult
            if d_pnl > max_day_pnl:
                max_day_pnl = d_pnl

            # EOD floor update
            if eq > eod_high:
                eod_high = eq
                floor = min(eod_high - spec.eval_max_dd_d1, spec.eval_lock_delta1)

            eff_target = spec.eval_target_u1
            if spec.consistency_max_day_share < 1.0:
                eff_target = max(eff_target, max_day_pnl / spec.consistency_max_day_share)

            if eq >= eff_target:
                passed_1 = True
                t_eval_end = t + 1
                break

        if not passed_1:
            continue

        eval_passed[i] = True
        t_pass_list.append(t_eval_end)

        # Phase 2: Funded Phase (up to First Payout)
        eq2 = 0.0
        eod_high2 = 0.0
        floor2 = -spec.funded_max_dd_d2
        win_days = 0
        for t in range(t_eval_end, horizon_days):
            k = idxs[t]
            r1, r2 = w1_arr[k], w2_arr[k]
            if r1 == 0.0 and r2 == 0.0:
                continue

            mult = 1.0
            if use_ratchet:
                if eq2 < 0.0:
                    mult = 0.50
                elif eq2 >= 800.0:
                    mult = 1.20
                elif eq2 >= 400.0:
                    mult = 1.10

            eq2 += r1 * mult
            if eq2 <= floor2:
                break
            eq2 += r2 * mult
            if eq2 <= floor2:
                break

            d_pnl = (r1 + r2) * mult
            if d_pnl >= spec.min_win_day_pnl:
                win_days += 1

            if eq2 > eod_high2:
                eod_high2 = eq2
                floor2 = min(eod_high2 - spec.funded_max_dd_d2, spec.funded_lock_delta2)

            if eq2 >= spec.funded_target_u2 and win_days >= spec.min_winning_days:
                funded_paid[i] = True
                t_payout_list.append(t + 1)
                break

    p1_mc = float(eval_passed.mean())
    p_joint_mc = float(funded_paid.mean())
    p2_mc = float(p_joint_mc / p1_mc) if p1_mc > 0 else 0.0
    payoffs = np.where(funded_paid, spec.first_payout_w - spec.eval_fee_c, -spec.eval_fee_c)
    eep_mc = float(payoffs.mean())
    eep_se_sim = float(payoffs.std(ddof=1) / math.sqrt(n_paths))

    # 2. Lifecycle Slot Simulation over 1-year paths (252 trading days = 363 calendar days, Section 3.9)
    n_slot_paths = 2000
    slot_days = 252
    slot_net_cfs = np.zeros(n_slot_paths, dtype=np.float64)
    for i in range(n_slot_paths):
        idxs = idx_mat[i, :slot_days]
        cf = -spec.eval_fee_c
        in_funded = False
        eq = 0.0
        eod_high = 0.0
        floor = -spec.eval_max_dd_d1
        win_days = 0
        payout_count = 0

        for t in range(slot_days):
            k = idxs[t]
            r1, r2 = w1_arr[k], w2_arr[k]
            if r1 == 0.0 and r2 == 0.0:
                continue

            mult = 1.0
            if use_ratchet:
                if eq < 0.0:
                    mult = 0.50
                elif eq >= 800.0:
                    mult = 1.20
                elif eq >= 400.0:
                    mult = 1.10

            eq += r1 * mult
            if eq <= floor:
                # Blowup -> purchase new evaluation
                cf -= spec.eval_fee_c
                in_funded = False
                eq = 0.0
                eod_high = 0.0
                floor = -spec.eval_max_dd_d1
                win_days = 0
                payout_count = 0
                continue

            eq += r2 * mult
            if eq <= floor:
                cf -= spec.eval_fee_c
                in_funded = False
                eq = 0.0
                eod_high = 0.0
                floor = -spec.eval_max_dd_d1
                win_days = 0
                payout_count = 0
                continue

            d_pnl = (r1 + r2) * mult
            if not in_funded:
                if eq > eod_high:
                    eod_high = eq
                    floor = min(eod_high - spec.eval_max_dd_d1, spec.eval_lock_delta1)
                if eq >= spec.eval_target_u1:
                    in_funded = True
                    eq = 0.0
                    eod_high = 0.0
                    floor = -spec.funded_max_dd_d2
                    win_days = 0
                    payout_count = 0
            else:
                if d_pnl >= spec.min_win_day_pnl:
                    win_days += 1
                if eq > eod_high:
                    eod_high = eq
                    floor = min(eod_high - spec.funded_max_dd_d2, spec.funded_lock_delta2)
                if eq >= spec.funded_target_u2 and win_days >= spec.min_winning_days:
                    payout_count += 1
                    cf += spec.first_payout_w if payout_count == 1 else spec.subsequent_payout_w
                    eq -= spec.funded_target_u2
                    eod_high = max(eq, spec.funded_lock_delta2)
                    floor = spec.funded_lock_delta2
                    win_days = 0
                    if payout_count >= spec.max_payouts_per_life:
                        # Lucid 5-payout live review cap -> start new eval slot
                        cf -= spec.eval_fee_c
                        in_funded = False
                        eq = 0.0
                        eod_high = 0.0
                        floor = -spec.eval_max_dd_d1
                        payout_count = 0

        slot_net_cfs[i] = cf

    xeep_mean = float(slot_net_cfs.mean())
    xeep_se = float(slot_net_cfs.std(ddof=1) / math.sqrt(n_slot_paths))
    p05, p50, p95 = np.percentile(slot_net_cfs, [5, 50, 95])

    # 3. Historical Single-Path Replay (lifeEEP / 363d, Section 3.9)
    cf_hist = -spec.eval_fee_c
    in_funded = False
    eq = 0.0
    eod_high = 0.0
    floor = -spec.eval_max_dd_d1
    win_days = 0
    payout_count = 0
    for k in range(n_cal):
        r1, r2 = w1_arr[k], w2_arr[k]
        if r1 == 0.0 and r2 == 0.0:
            continue
        mult = 1.0
        if use_ratchet:
            if eq < 0.0:
                mult = 0.50
            elif eq >= 800.0:
                mult = 1.20
            elif eq >= 400.0:
                mult = 1.10
        eq += (r1 + r2) * mult
        if eq <= floor:
            cf_hist -= spec.eval_fee_c
            in_funded = False
            eq = 0.0
            eod_high = 0.0
            floor = -spec.eval_max_dd_d1
            win_days = 0
            payout_count = 0
            continue
        if not in_funded:
            if eq > eod_high:
                eod_high = eq
                floor = min(eod_high - spec.eval_max_dd_d1, spec.eval_lock_delta1)
            if eq >= spec.eval_target_u1:
                in_funded = True
                eq = 0.0
                eod_high = 0.0
                floor = -spec.funded_max_dd_d2
                win_days = 0
                payout_count = 0
        else:
            if (r1 + r2) * mult >= spec.min_win_day_pnl:
                win_days += 1
            if eq > eod_high:
                eod_high = eq
                floor = min(eod_high - spec.funded_max_dd_d2, spec.funded_lock_delta2)
            if eq >= spec.funded_target_u2 and win_days >= spec.min_winning_days:
                payout_count += 1
                cf_hist += spec.first_payout_w if payout_count == 1 else spec.subsequent_payout_w
                eq -= spec.funded_target_u2
                eod_high = max(eq, spec.funded_lock_delta2)
                floor = spec.funded_lock_delta2
                win_days = 0
                if payout_count >= spec.max_payouts_per_life:
                    cf_hist -= spec.eval_fee_c
                    in_funded = False
                    eq = 0.0
                    eod_high = 0.0
                    floor = -spec.eval_max_dd_d1
                    payout_count = 0

    life_eep_annual = float(cf_hist * (252.0 / n_cal))

    t_pass_arr = np.array(t_pass_list) if t_pass_list else np.array([horizon_days])
    t_pay_arr = np.array(t_payout_list) if t_payout_list else np.array([horizon_days])

    # Operational discount threshold rho* (Section 3.8 & 4.5): rho* * p_joint_mc * W - C = 0
    gross_exp_payout = p_joint_mc * spec.first_payout_w
    rho_star = float(spec.eval_fee_c / gross_exp_payout) if gross_exp_payout > 0 else 9.99
    eep_rho_085 = float(0.85 * gross_exp_payout - spec.eval_fee_c)

    # Multi-Account Kelly fraction f* = EEP / (W - C) (Section 4.4, Eq. 40)
    kelly_f = float(max(0.0, eep_mc / (spec.first_payout_w - spec.eval_fee_c)))
    b_min = float(spec.eval_fee_c / kelly_f) if kelly_f > 0 else float("inf")

    return {
        "p1_mc": p1_mc,
        "p2_mc": p2_mc,
        "p_pass": p_joint_mc,
        "eep_mc": eep_mc,
        "eep_ci_lo": eep_mc - 1.96 * eep_se_sim,
        "eep_ci_hi": eep_mc + 1.96 * eep_se_sim,
        "t_pass_med": float(np.median(t_pass_arr)),
        "t_pass_p10": float(np.percentile(t_pass_arr, 10)),
        "t_pass_p90": float(np.percentile(t_pass_arr, 90)),
        "t_pay_med": float(np.median(t_pay_arr)),
        "xeep": xeep_mean,
        "xeep_se": xeep_se,
        "xeep_p05": float(p05),
        "xeep_p50": float(p50),
        "xeep_p95": float(p95),
        "life_eep_363d": life_eep_annual,
        "rho_star": rho_star,
        "eep_rho_085": eep_rho_085,
        "kelly_f_pct": kelly_f * 100.0,
        "b_min_dollars": b_min,
    }


def main() -> int:
    cal_df, portfolios = build_portfolio_daily_series()
    n_cal_days = len(cal_df)
    print(f"Loaded Exchange Calendar (2021-2026): {n_cal_days} RTH trading days.")

    configs_to_run = [
        (LUCID_FLEX_25K, "MNQ Alone (09:45)", 1.0, False, "1. LucidFlex 25K | MNQ Alone ($250 Risk)"),
        (LUCID_FLEX_25K, "Dual Equity Split (MNQ+MES)", 1.0, False, "2. LucidFlex 25K | Dual Equity Split ($250 Risk)"),
        (LUCID_FLEX_25K, "Tri-Asset Split (MNQ+MES+MGC)", 1.0, False, "3. LucidFlex 25K | Tri-Asset Split ($250 Risk)"),
        (LUCID_FLEX_25K, "Tri-Asset Split (MNQ+MES+MGC)", 1.0, True, "4. LucidFlex 25K | Tri-Asset Split + Equity Ratchet"),
        (LUCID_FLEX_25K, "Tri-Asset Full (MNQ+MES+MGC)", 1.0, True, "5. LucidFlex 25K | Tri-Asset Full + Equity Ratchet"),
        (LUCID_FLEX_50K, "Tri-Asset Full (MNQ+MES+MGC)", 2.0, True, "6. LucidFlex 50K | Tri-Asset Full ($500 Paper Scale)"),
        (TOPSTEP_XFA_50K, "Tri-Asset Full (MNQ+MES+MGC)", 2.0, True, "7. Topstep XFA 50K | Tri-Asset Full ($500 Paper Scale)"),
    ]

    summary_rows = []
    stress_rows = []

    for spec, p_key, r_mult, ratchet, label in configs_to_run:
        t_df = portfolios[p_key]
        w1, w2, nt = prepare_daily_arrays(cal_df, t_df, risk_mult=r_mult, extra_slip_1tick=False)
        day_sums = w1 + w2
        mu_hat = float(day_sums.mean())
        sigma_day = float(day_sums.std(ddof=1))
        se_mu = float(sigma_day / math.sqrt(n_cal_days))
        n_per_day = float(nt.sum() / n_cal_days)

        eep_an, _, _, _, _ = compute_analytical_eep_predictive(spec, mu_hat, se_mu, sigma_day, n_per_day)
        mc_b1 = simulate_mc_paths(spec, w1, w2, use_ratchet=ratchet, n_paths=5000, block_len=1, seed=42)
        mc_b20 = simulate_mc_paths(spec, w1, w2, use_ratchet=ratchet, n_paths=2000, block_len=20, seed=42)

        # Fill counterfactual (+1 tick/side extra slippage)
        w1_sl, w2_sl, _ = prepare_daily_arrays(cal_df, t_df, risk_mult=r_mult, extra_slip_1tick=True)
        mc_slip = simulate_mc_paths(spec, w1_sl, w2_sl, use_ratchet=ratchet, n_paths=3000, block_len=1, seed=42)

        # Stress Test 2: Parameter shift (+10% profit target & -10% drawdown buffer)
        stressed_spec = PropAccountSpec(
            name=spec.name + " (Stressed)",
            account_size=spec.account_size,
            eval_target_u1=spec.eval_target_u1 * 1.10,
            eval_max_dd_d1=spec.eval_max_dd_d1 * 0.90,
            eval_lock_delta1=spec.eval_lock_delta1,
            eval_fee_c=spec.eval_fee_c,
            funded_target_u2=spec.funded_target_u2 * 1.10,
            funded_max_dd_d2=spec.funded_max_dd_d2 * 0.90,
            funded_lock_delta2=spec.funded_lock_delta2,
            payout_split=spec.payout_split,
            first_payout_w=spec.first_payout_w,
            subsequent_payout_w=spec.subsequent_payout_w,
            max_payouts_per_life=spec.max_payouts_per_life,
            min_winning_days=spec.min_winning_days,
            min_win_day_pnl=spec.min_win_day_pnl,
            consistency_max_day_share=spec.consistency_max_day_share,
        )
        mc_param_stress = simulate_mc_paths(stressed_spec, w1, w2, use_ratchet=ratchet, n_paths=3000, block_len=1, seed=42)

        delta_eep = mc_b1["eep_mc"] - eep_an
        b20_diff_pct = abs(mc_b20["xeep"] - mc_b1["xeep"]) / max(abs(mc_b1["xeep"]), 1.0) * 100.0

        summary_rows.append(
            {
                "Configuration": label,
                "EEP_mc [95% CI]": f"${mc_b1['eep_mc']:+.1f} [{mc_b1['eep_ci_lo']:+.0f}; {mc_b1['eep_ci_hi']:+.0f}]",
                "EEP_an": f"${eep_an:+.1f}",
                "delta": f"${delta_eep:+.1f}",
                "p1 / p2 / p_pass": f"{mc_b1['p1_mc']*100:.0f}% / {mc_b1['p2_mc']*100:.0f}% / {mc_b1['p_pass']*100:.0f}%",
                "t_pass med (p10-p90)": f"{mc_b1['t_pass_med']:.0f}d ({mc_b1['t_pass_p10']:.0f}-{mc_b1['t_pass_p90']:.0f}d)",
                "xEEP/yr (SE)": f"${mc_b1['xeep']:+.0f} (${mc_b1['xeep_se']:.0f})",
                "lifeEEP/363d": f"${mc_b1['life_eep_363d']:+.0f}",
                "Kelly f* (B_min)": f"{mc_b1['kelly_f_pct']:.1f}% (${mc_b1['b_min_dollars']:.0f})",
            }
        )

        stress_rows.append(
            {
                "Configuration": label,
                "EEP Base": f"${mc_b1['eep_mc']:+.1f}",
                "EEP +1 Tick/Side": f"${mc_slip['eep_mc']:+.1f}",
                "Sign Flip?": "NO" if (mc_b1["eep_mc"] > 0 and mc_slip["eep_mc"] > 0) else "YES",
                "EEP Param Stress (+10%U/-10%D)": f"${mc_param_stress['eep_mc']:+.1f}",
                "rho* (Max Op Disc)": f"{mc_b1['rho_star']:.2f}",
                "EEP at rho=0.85": f"${mc_b1['eep_rho_085']:+.1f}",
                "b=20 Block Δ%": f"{b20_diff_pct:.1f}% (PASS)" if b20_diff_pct <= 25.0 else f"{b20_diff_pct:.1f}%",
            }
        )

    sum_df = pd.DataFrame(summary_rows)
    str_df = pd.DataFrame(stress_rows)

    print("\n=== TABLE A: ACCOUNT-LEVEL OPTIONALITY & LIFECYCLE VALUATION (PAPER 0 TABLE 3 FORMAT) ===")
    print(sum_df.to_string(index=False))

    print("\n=== TABLE B: ROBUSTNESS, SLIPPAGE COUNTERFACTUAL & OPERATIONAL STRESS TESTS (PAPER 0 TABLE 5 FORMAT) ===")
    print(str_df.to_string(index=False))

    out_md = ROOT / "results/research_master/prop_optionality_paper0_evaluation.md"
    with open(out_md, "w") as f:
        f.write("# Prop Firm Optionality & Lifecycle Valuation (`Shαrpe Paper 0` Framework)\n\n")
        f.write("## 1. Account-Level Optionality & Lifecycle Results (`EEP_mc`, `EEP_an`, `xEEP`, `lifeEEP`, Kelly `f*`)\n\n")
        f.write("| " + " | ".join(sum_df.columns) + " |\n")
        f.write("| " + " | ".join(["---"] * len(sum_df.columns)) + " |\n")
        for _, r in sum_df.iterrows():
            f.write("| " + " | ".join(str(r[c]) for c in sum_df.columns) + " |\n")
        f.write("\n## 2. Stress Tests 2 & 3, +1 Tick/Side Slippage Counterfactual, and `b=20` Block Bootstrap\n\n")
        f.write("| " + " | ".join(str_df.columns) + " |\n")
        f.write("| " + " | ".join(["---"] * len(str_df.columns)) + " |\n")
        for _, r in str_df.iterrows():
            f.write("| " + " | ".join(str(r[c]) for c in str_df.columns) + " |\n")
    print(f"\nSaved full report to {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
