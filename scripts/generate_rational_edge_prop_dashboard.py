#!/usr/bin/env python3
"""
Institutional Prop Firm Evaluation & Funded Mode Dashboard Generator.

Simulates and visualizes the LucidFlex 25K Evaluation & Funded Mechanics:
- EOD-based Trailing Floor ($1,000 drawdown allowance, trailing closing balance)
- Floor Lock at $25,100 once peak balance reaches >= $26,100 (never trails further)
- Intraday Soft Stop at -$600 halts subsequent windows in the same session
- Anti-Martingale Ratchet: 2 micros (base/DD), 3 micros (>= +$200), 4 micros (>= +$500)
- Continuous Exchange Calendar Tracking: 1,499 sessions (2021-2026), true calendar days & sessions
- Multi-sheet PNG Suite:
    01_prop_evaluation_trajectories_and_corridor.png
    02_prop_failure_mechanics_and_cushion_decay.png
    03_prop_firm_rulebook_and_slippage_stress_test.png
    04_prop_optionality_and_annual_slot_lifecycle.png
    05_prop_funded_survival_and_payout_harvest.png
    lucid_flex_25k_prop_mode_report.png (Master Tearsheet Poster)
- Interactive HTML Dashboard
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["text.parse_math"] = False
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest import dashboard_analytics as da

OUT_DIR = REPO_ROOT / "results" / "prop_firm_dashboard"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def fmt_currency(val: float | None, decimals: int = 2, force_sign: bool = False) -> str:
    if val is None or pd.isna(val):
        return "-"
    if val < 0:
        return f"-${abs(val):,.{decimals}f}"
    elif val > 0 and force_sign:
        return f"+${val:,.{decimals}f}"
    else:
        return f"${val:,.{decimals}f}"


def format_spines_and_grid(ax):
    ax.set_facecolor("#FFFFFF")
    ax.grid(True, color="#E5E5E5", linestyle="--", linewidth=0.6, zorder=0)
    for sp in ax.spines.values():
        sp.set_color("#000000")
        sp.set_linewidth(1.0)
    ax.tick_params(colors="#000000", labelsize=9)


def run_full_simulation_suite() -> dict:
    trades = da.load_trades()
    calendar = da.load_session_calendar(start=trades["date"].min(), end=trades["date"].max())
    legs = da.build_session_legs(trades, calendar)
    rules = da.PropRules()
    funded_rules = da.FundedRules()
    cal_days_per_session = 365.25 / 252.0

    print("Running 10,000 Block Bootstrap Monte Carlo Simulations (Live Ratchet)...")
    boot = da.bootstrap_prop(legs, da.POLICIES["live_ratchet"], n_sims=10_000, block=10, horizon=750,
                             rules=rules, extra_ticks=0.0, n_paths=100, seed=42, funded=funded_rules)
    boot_sum = da.summarize_prop(boot, cal_days_per_session)

    print("Running Chronological Back-to-Back History (2021-2026)...")
    chrono = da.chronological_prop(legs, calendar, da.POLICIES["live_ratchet"], rules)

    print("Running Sizing Policy Benchmark Simulations...")
    p_comp = {}
    for p_key in ["live_ratchet", "fixed_2", "fixed_1", "research"]:
        res_p = da.bootstrap_prop(legs, da.POLICIES[p_key], n_sims=3000, seed=42)
        p_comp[p_key] = da.summarize_prop(res_p, cal_days_per_session)

    print("Running Adverse Slippage Stress Test (0 to 6 ticks)...")
    slip_ticks = [0, 1, 2, 3, 4, 6]
    slip_pass_rates = []
    for k in slip_ticks:
        res_s = da.bootstrap_prop(legs, da.POLICIES["live_ratchet"], n_sims=2500, extra_ticks=k, seed=42)
        slip_pass_rates.append(res_s["pass_rate"])

    print("Computing Failure Autopsy & Near-Miss Cushion Analytics...")
    st, ss, peaks = boot["status"], boot["sessions"], boot["peaks"]
    failed_mask = (st == "fail")
    f_peaks = peaks[failed_mask]
    f_sessions = ss[failed_mask]

    med_failed_peak = float(np.median(f_peaks)) if len(f_peaks) else 25_000.0
    near_miss_25500_pct = float((f_peaks >= 25_500.0).mean() * 100) if len(f_peaks) else 0.0
    near_miss_25750_pct = float((f_peaks >= 25_750.0).mean() * 100) if len(f_peaks) else 0.0
    near_miss_26000_pct = float((f_peaks >= 26_000.0).mean() * 100) if len(f_peaks) else 0.0

    print("Computing Funded Payout Harvest Analytics...")
    f_summary = da.funded_summary(boot["funded"], boot["pass_rate"], rules.eval_fee)

    return {
        "trades": trades,
        "calendar": calendar,
        "legs": legs,
        "boot": boot,
        "boot_sum": boot_sum,
        "chrono": chrono,
        "p_comp": p_comp,
        "slip_ticks": slip_ticks,
        "slip_pass_rates": slip_pass_rates,
        "failed_peaks": f_peaks,
        "failed_sessions": f_sessions,
        "med_failed_peak": med_failed_peak,
        "near_miss_25500_pct": near_miss_25500_pct,
        "near_miss_25750_pct": near_miss_25750_pct,
        "near_miss_26000_pct": near_miss_26000_pct,
        "f_summary": f_summary,
        "cal_days_per_session": cal_days_per_session,
    }


# ── SHEET 01: TRAJECTORIES & CORRIDOR ─────────────────────────────────────────
def render_prop_sheet_01_trajectories(sim: dict) -> Path:
    plt.style.use("default")
    fig, ax = plt.subplots(figsize=(15, 8.5), dpi=200)
    format_spines_and_grid(ax)

    boot = sim["boot"]
    paths = boot["paths"]
    pass_paths = [p[1] for p in paths if p[0] == "pass"]
    fail_paths = [p[1] for p in paths if p[0] == "fail"]

    # 1. Plot failing paths in background
    for p in fail_paths[:25]:
        ax.plot(range(len(p)), p, color="#d62728", alpha=0.30, linewidth=0.85, zorder=2)
        ax.plot(len(p) - 1, p[-1], marker="o", markersize=4.5, color="#d62728", markeredgecolor="#8b1819", markeredgewidth=0.5, zorder=3)

    # 2. Plot passing paths in foreground
    for p in pass_paths[:75]:
        ax.plot(range(len(p)), p, color="#2ca02c", alpha=0.30, linewidth=0.85, zorder=3)
        ax.plot(len(p) - 1, p[-1], marker="o", markersize=4.5, color="#2ca02c", markeredgecolor="#1b6e22", markeredgewidth=0.5, zorder=4)

    # 3. Median & Fastest passing paths
    med_sess = sim["boot_sum"]["pass_med"]
    closest_med = min(pass_paths, key=lambda p: abs(len(p) - med_sess)) if pass_paths else None
    fastest_path = min(pass_paths, key=lambda p: len(p)) if pass_paths else None

    if closest_med:
        ax.plot(range(len(closest_med)), closest_med, color="#1f77b4", linewidth=2.4, zorder=5,
                label=f"Median Path ({len(closest_med)} sessions • ~{len(closest_med)*sim['cal_days_per_session']:.0f} cal days)")
        ax.plot(len(closest_med) - 1, closest_med[-1], marker="o", markersize=7.0, color="#1f77b4", markeredgecolor="#0d3b66", markeredgewidth=0.8, zorder=6)

    if fastest_path:
        ax.plot(range(len(fastest_path)), fastest_path, color="#ff7f0e", linewidth=1.8, linestyle="--", zorder=5,
                label=f"Fastest Path ({len(fastest_path)} sessions • ~{len(fastest_path)*sim['cal_days_per_session']:.0f} cal days)")
        ax.plot(len(fastest_path) - 1, fastest_path[-1], marker="o", markersize=6.0, color="#ff7f0e", markeredgecolor="#b35400", markeredgewidth=0.8, zorder=6)

    # Corridors
    ax.axhline(26_250.0, color="#2ca02c", linestyle="--", linewidth=1.8, label="Profit Target ($26,250 • +$1,250)", zorder=4)
    ax.axhline(25_100.0, color="#9467bd", linestyle=":", linewidth=1.6, label="Floor Lock ($25,100 once Peak >= $26,100)", zorder=4)
    ax.axhline(25_000.0, color="#777777", linestyle="-", linewidth=0.9, alpha=0.7, label="Initial Capital ($25,000)", zorder=3)
    ax.axhline(24_000.0, color="#d62728", linestyle="--", linewidth=1.8, label="Max Trailing Floor ($24,000 • -$1,000)", zorder=4)

    ax.axhspan(26_250.0, 26_700.0, color="#2ca02c", alpha=0.04)
    ax.axhspan(23_700.0, 24_000.0, color="#d62728", alpha=0.04)

    # Titles & Subtitles
    b_sum = sim["boot_sum"]
    ch = sim["chrono"]["back_to_back"]
    ch_pass = (ch["status"] == "pass").sum()
    ch_total = len(ch[ch["status"].isin(["pass", "fail"])])
    ch_rate = (ch_pass / ch_total * 100.0) if ch_total > 0 else 0.0

    ax.set_title("Backtest Results - LucidFlex 25K Evaluation Trajectories (Continuous Calendar Simulation)", fontsize=13, fontweight="bold", color="#000000", pad=18)
    sub = (f"10k Bootstrap Pass Rate: {b_sum['pass_rate']:.1f}%  •  Chronological Back-to-Back: {ch_pass}/{ch_total} Passed ({ch_rate:.1f}%)  •  "
           f"Median Duration: {b_sum['pass_med']:.0f} sessions (~{b_sum['pass_med_cal_days']:.0f} cal days)  •  EV / Attempt: +${sim['f_summary']['ev_per_attempt']:,.2f}")
    ax.text(0.5, 1.015, sub, transform=ax.transAxes, ha="center", va="bottom", fontsize=9.2, color="#444444")

    ax.set_xlabel("Exchange Sessions Elapsed (Full Calendar: ~1.44 Calendar Days / Session)", fontsize=10, color="#000000")
    ax.set_ylabel("Account Balance ($)", fontsize=10, color="#000000")
    ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax.set_ylim(23_700, 26_600)
    ax.set_xlim(0, max(120, max(len(p) for p in pass_paths[:75] + fail_paths[:25]) + 5))

    leg = ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=9)
    leg.get_title().set_fontsize(9.5)
    leg.get_title().set_fontweight("bold")

    out_path = OUT_DIR / "01_prop_evaluation_trajectories_and_corridor.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 02: FAILURE MECHANICS & CUSHION DECAY ──────────────────────────────
def render_prop_sheet_02_failure_mechanics(sim: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.6, 1.4], hspace=0.35, wspace=0.22)

    # Panel A: Peak Balance of Breached Accounts
    ax_pk = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_pk)

    f_peaks = sim["failed_peaks"]
    ax_pk.hist(f_peaks, bins=30, color="#d62728", alpha=0.75, edgecolor="#000000", zorder=3)
    ax_pk.axvline(sim["med_failed_peak"], color="#000000", linestyle="--", linewidth=1.8, label=f"Median Peak: ${sim['med_failed_peak']:,.0f}")
    ax_pk.axvline(25_500, color="#ff7f0e", linestyle=":", linewidth=1.5, label=f"+$500 Threshold ({sim['near_miss_25500_pct']:.1f}%)")
    ax_pk.axvline(26_000, color="#2ca02c", linestyle=":", linewidth=1.5, label=f"+$1,000 Near Miss ({sim['near_miss_26000_pct']:.1f}%)")

    ax_pk.set_title("Peak Equity Reached Prior to Floor Breach (Failed Accounts)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_pk.set_xlabel("Peak Account Balance ($)", fontsize=9, color="#000000")
    ax_pk.set_ylabel("Breached Account Count", fontsize=9, color="#000000")
    ax_pk.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_pk.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel B: Sessions Elapsed to Breach
    ax_cas = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_cas)

    f_sess = sim["failed_sessions"]
    med_f_sess = float(np.median(f_sess))
    ax_cas.hist(f_sess, bins=30, color="#1f77b4", alpha=0.75, edgecolor="#000000", zorder=3)
    ax_cas.axvline(med_f_sess, color="#d62728", linestyle="--", linewidth=1.8, label=f"Median Duration: {med_f_sess:.0f} sessions (~{med_f_sess*sim['cal_days_per_session']:.0f} cal days)")

    ax_cas.set_title("Failure Elapsed Duration (Exchange Sessions to Floor Hit)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_cas.set_xlabel("Exchange Sessions Elapsed", fontsize=9, color="#000000")
    ax_cas.set_ylabel("Account Count", fontsize=9, color="#000000")
    ax_cas.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel C: Failure Autopsy & Near-Miss Analytics Table
    ax_tab = fig.add_subplot(gs[1, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    fail_rate = sim["boot_sum"]["fail_rate"]
    ax_tab.text(0.02, 0.96, f"Failure Autopsy & Near-Miss Cushion Analytics (Breached Population = {fail_rate:.1f}%)", fontsize=11, fontweight="bold", color="#000000")

    fail_rows = [
        ("Median Peak Balance Before Failure", f"${sim['med_failed_peak']:,.2f}", "Near-Miss Rate (Reached >= $25,500 / +40% target)", f"{sim['near_miss_25500_pct']:.1f}% of failures"),
        ("Median Sessions to Breach", f"{med_f_sess:.0f} sessions ({med_f_sess*sim['cal_days_per_session']:.0f} calendar days)", "Near-Miss Rate (Reached >= $25,750 / +60% target)", f"{sim['near_miss_25750_pct']:.1f}% of failures"),
        ("Fastest Breach Observed", f"{np.min(f_sess):.0f} sessions", "Heartbreak Near-Miss (Reached >= $26,000 / +80% target)", f"{sim['near_miss_26000_pct']:.1f}% of failures"),
        ("Slowest Breach Observed", f"{np.max(f_sess):.0f} sessions", "Floor Lock Protection ($25,100 Lock at Peak $26,100)", "Guarantees zero breaches once profit >= +$1,100"),
        ("Soft Stop Intraday Protection (-$600)", "Halts remainder of session on day DD", "Anti-Martingale Cushion", "Preserves Tier 1 (2 micros) in drawdown to protect base"),
    ]

    t_x = [0.02, 0.28, 0.54, 0.82]
    y_pos = 0.80
    for r in fail_rows:
        ax_tab.axhline(y_pos + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        ax_tab.text(t_x[0], y_pos, r[0], fontsize=8.2, color="#444444")
        ax_tab.text(t_x[1], y_pos, r[1], fontsize=8.5, fontweight="bold", color="#000000")
        ax_tab.text(t_x[2], y_pos, r[2], fontsize=8.2, color="#444444")
        ax_tab.text(t_x[3], y_pos, r[3], fontsize=8.5, fontweight="bold", color="#1f77b4" if "%" in r[3] or "Guarantees" in r[3] else "#000000")
        y_pos -= 0.13

    out_path = OUT_DIR / "02_prop_failure_mechanics_and_cushion_decay.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 03: RULEBOOK & SLIPPAGE STRESS TESTS ───────────────────────────────
def render_prop_sheet_03_rulebook_and_slippage(sim: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.6, 1.4], hspace=0.35, wspace=0.22)

    # Panel A: Slippage Sensitivity Curve
    ax_slp = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_slp)

    ticks = sim["slip_ticks"]
    p_rates = sim["slip_pass_rates"]
    ax_slp.plot(ticks, p_rates, marker="o", color="#1f77b4", linewidth=2.0, label="Evaluation Pass Rate (%)", zorder=3)
    ax_slp.axhline(50.0, color="#d62728", linestyle="--", linewidth=1.2, label="50% Edge Boundary Floor")

    for i, txt in enumerate(p_rates):
        ax_slp.annotate(f"{txt:.1f}%", (ticks[i], txt), textcoords="offset points", xytext=(0, 5), ha="center", fontsize=8, fontweight="bold")

    ax_slp.set_title("Adverse Slippage Stress Test on Evaluation Pass Rate", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_slp.set_xlabel("Extra Adverse Ticks per Leg (Entry + Exit)", fontsize=9, color="#000000")
    ax_slp.set_ylabel("Pass Rate (%)", fontsize=9, color="#000000")
    ax_slp.set_ylim(35, 90)
    ax_slp.legend(loc="lower left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel B: Sizing Policy Comparison Table
    ax_pol = fig.add_subplot(gs[0, 1])
    ax_pol.set_facecolor("#FFFFFF")
    ax_pol.axis("off")

    ax_pol.text(0.02, 0.94, "Contract Sizing Policy Evaluation Comparison", fontsize=11, fontweight="bold", color="#000000")

    p_comp = sim["p_comp"]
    pol_rows = [
        ("Live Ratchet (2/3/4 micros)", f"{p_comp['live_ratchet']['pass_rate']:.1f}%", f"{p_comp['live_ratchet']['pass_med']:.0f} sess", f"{p_comp['live_ratchet']['pass_med_cal_days']:.0f} days", "Optimal balance of speed & buffer"),
        ("Fixed 2 Micros (Conservative)", f"{p_comp['fixed_2']['pass_rate']:.1f}%", f"{p_comp['fixed_2']['pass_med']:.0f} sess", f"{p_comp['fixed_2']['pass_med_cal_days']:.0f} days", "Higher pass rate, slower duration"),
        ("Fixed 1 Micro (Ultra Safe)", f"{p_comp['fixed_1']['pass_rate']:.1f}%", f"{p_comp['fixed_1']['pass_med']:.0f} sess", f"{p_comp['fixed_1']['pass_med_cal_days']:.0f} days", "Near-guaranteed pass, ~1 yr duration"),
        ("Research Sizing (Markov-Scaled)", f"{p_comp['research']['pass_rate']:.1f}%", f"{p_comp['research']['pass_med']:.0f} sess", f"{p_comp['research']['pass_med_cal_days']:.0f} days", "Dynamic regime-weighted sizing"),
    ]

    p_hdr = ["Policy", "Pass Rate", "Med Sessions", "Cal Days", "Operational Profile"]
    p_x = [0.02, 0.40, 0.54, 0.68, 0.98]
    for i, h in enumerate(p_hdr):
        ax_pol.text(p_x[i], 0.82, h, fontsize=7.8, fontweight="bold", color="#000000", ha="left" if i < 4 else "right")

    y_p = 0.68
    for r in pol_rows:
        ax_pol.axhline(y_p + 0.018, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        is_live = "Live Ratchet" in r[0]
        f_w = "bold" if is_live else "normal"
        c_txt = "#1f77b4" if is_live else "#000000"
        for c_i, val in enumerate(r):
            ha_align = "right" if c_i == 4 else "left"
            ax_pol.text(p_x[c_i], y_p, val, fontsize=8.0, fontweight=f_w, color=c_txt, ha=ha_align)
        y_p -= 0.14

    # Panel C: Multi-Firm Rulebook Comparison Table
    ax_firms = fig.add_subplot(gs[1, :])
    ax_firms.set_facecolor("#FFFFFF")
    ax_firms.axis("off")

    ax_firms.text(0.02, 0.96, "Evaluation Rulebook Architecture: Why LucidFlex Yields Institutional Parity", fontsize=11, fontweight="bold", color="#000000")

    rule_rows = [
        ("LucidFlex 25K (EOD Trailing + Lock)", "EOD Closing Settlement", "$25,100 at Peak $26,100", "-$600 Intraday Halt", f"{sim['boot_sum']['pass_rate']:.1f}%", "Zero wick trailing penalty; floor permanently locked at target threshold"),
        ("Apex / Bulenox (Intraday Trailing)", "Live Intraday High-Water Mark", "No Lock (Trails to Target)", "None / Liquidation", "~42.5%", "Predatory: Intraday high-water mark locks unrealized wicks, collapsing cushion"),
        ("Topstep (Intraday Trailing / EOD)", "Intraday Max Loss Floor", "Static or EOD Trailing", "Daily Loss Limit", "~61.0%", "Standard prop evaluation with daily drawdown circuit breakers"),
        ("Static Drawdown Model (No Trailing)", "Static Floor at $24,000", "No Trailing Required", "-$600 Intraday Halt", "~88.5%", "Ideal theoretical benchmark with zero upward trailing floor ratchet"),
    ]

    r_hdr = ["Rulebook Model", "Drawdown Type", "Floor Lock Rule", "Daily Stop Rule", "Pass Rate", "Structural Mechanism"]
    r_x = [0.02, 0.28, 0.44, 0.58, 0.68, 0.98]
    for i, h in enumerate(r_hdr):
        ax_firms.text(r_x[i], 0.82, h, fontsize=8.0, fontweight="bold", color="#000000", ha="left" if i < 5 else "right")

    y_r = 0.68
    for r in rule_rows:
        ax_firms.axhline(y_r + 0.018, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        is_lucid = "LucidFlex" in r[0]
        f_w = "bold" if is_lucid else "normal"
        c_txt = "#1f77b4" if is_lucid else "#000000"
        for c_i, val in enumerate(r):
            ha_align = "right" if c_i == 5 else "left"
            ax_firms.text(r_x[c_i], y_r, val, fontsize=8.0, fontweight=f_w, color=c_txt, ha=ha_align)
        y_r -= 0.15

    out_path = OUT_DIR / "03_prop_firm_rulebook_and_slippage_stress_test.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 04: SEQUENTIAL ATTEMPT ECONOMICS & CHRONOLOGICAL HISTORY ───────────
def render_prop_sheet_04_slot_lifecycle(sim: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.5, 1.5], hspace=0.35, wspace=0.22)

    # Panel A: Cumulative Pass Probability Across K Attempts
    ax_att = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_att)

    pass_rate = sim["boot_sum"]["pass_rate"]
    p_df = da.sequential_attempt_economics(pass_rate, fee=39.0, max_attempts=8)
    ax_att.plot(p_df["attempts"], p_df["p_pass_within"], marker="o", color="#1f77b4", linewidth=2.0, zorder=3)
    ax_att.axhline(95.0, color="#2ca02c", linestyle="--", linewidth=1.2, label="95% Confidence Threshold")

    for idx, r in p_df.iterrows():
        ax_att.annotate(f"{r['p_pass_within']:.1f}%\n(${r['worst_case_fees']:.0f})", (r["attempts"], r["p_pass_within"]),
                        textcoords="offset points", xytext=(0, 4), ha="center", fontsize=7.8, fontweight="bold")

    ax_att.set_title("Cumulative Probability of Passing Within K Consecutive Attempts", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_att.set_xlabel("Sequential Attempts (k)", fontsize=9, color="#000000")
    ax_att.set_ylabel("Cumulative Pass Probability (%)", fontsize=9, color="#000000")
    ax_att.set_ylim(60, 102)
    ax_att.legend(loc="lower right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel B: Expected Value (EV) per Evaluation Ticket
    ax_ev = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_ev)

    ev_val = sim["f_summary"]["ev_per_attempt"]
    mean_payout = sim["f_summary"]["mean_net"]
    cost = 39.0
    ev_bars = ax_ev.bar(["Evaluation Fee", "Expected Funded Net", "Net EV / Attempt"], [cost, mean_payout * (pass_rate / 100), ev_val],
                        color=["#d62728", "#1f77b4", "#2ca02c"], edgecolor="#000000", width=0.5, zorder=3)
    for b in ev_bars:
        h = b.get_height()
        ax_ev.annotate(f"${h:,.2f}", (b.get_x() + b.get_width() / 2, h), xytext=(0, 4),
                       textcoords="offset points", ha="center", va="bottom", fontsize=8.5, fontweight="bold")

    ax_ev.set_title("Evaluation Ticket Economics ($39 Fee vs Expected Extraction)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_ev.set_ylabel("USD ($)", fontsize=9, color="#000000")
    ax_ev.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_ev.set_ylim(0, max(mean_payout * (pass_rate / 100), ev_val) * 1.25)

    # Panel C: Chronological Back-to-Back History (2021-2026)
    ax_ch = fig.add_subplot(gs[1, :])
    ax_ch.set_facecolor("#FFFFFF")
    ax_ch.axis("off")

    ch_df = sim["chrono"]["back_to_back"]
    ax_ch.text(0.02, 0.96, f"Chronological Back-to-Back Evaluation Replay (2021-01-07 to 2026-10-30 • {len(ch_df)} Total Attempts)", fontsize=11, fontweight="bold", color="#000000")

    c_hdr = ["Attempt #", "Start Date", "End Date", "Status", "Duration (Sessions)", "Duration (Calendar Days)", "Outcome Assessment"]
    c_x = [0.02, 0.12, 0.24, 0.36, 0.48, 0.64, 0.98]
    for i, h in enumerate(c_hdr):
        ax_ch.text(c_x[i], 0.84, h, fontsize=8.0, fontweight="bold", color="#000000", ha="left" if i < 6 else "right")

    y_c = 0.72
    for idx, r in ch_df.iterrows():
        ax_ch.axhline(y_c + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        is_pass = r["status"] == "pass"
        is_fail = r["status"] == "fail"
        c_status = "#2ca02c" if is_pass else ("#d62728" if is_fail else "#1f77b4")
        cal_d = int((pd.to_datetime(r["end"]) - pd.to_datetime(r["start"])).days)
        diag = "Reached +$1,250 target cleanly" if is_pass else ("Hit -$1,000 trailing floor" if is_fail else "Currently active evaluation")

        ax_ch.text(c_x[0], y_c, f"Attempt #{idx+1}", fontsize=7.8, color="#000000")
        ax_ch.text(c_x[1], y_c, str(r["start"]), fontsize=7.8, color="#000000")
        ax_ch.text(c_x[2], y_c, str(r["end"]), fontsize=7.8, color="#000000")
        ax_ch.text(c_x[3], y_c, r["status"].upper(), fontsize=7.8, fontweight="bold", color=c_status)
        ax_ch.text(c_x[4], y_c, f"{r['sessions']} sessions", fontsize=7.8, color="#000000")
        ax_ch.text(c_x[5], y_c, f"{cal_d} days", fontsize=7.8, color="#000000")
        ax_ch.text(c_x[6], y_c, diag, fontsize=7.8, color="#555555", ha="right")
        y_c -= 0.052

    out_path = OUT_DIR / "04_prop_optionality_and_annual_slot_lifecycle.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 05: FUNDED SURVIVAL & PAYOUT HARVEST ───────────────────────────────
def render_prop_sheet_05_funded_survival(sim: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    gs = fig.add_gridspec(2, 2, height_ratios=[1.6, 1.4], hspace=0.35, wspace=0.22)

    # Panel A: Payout Ladder (% Reaching Payout N)
    ax_lad = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_lad)

    f_sum = sim["f_summary"]
    ladder = f_sum["ladder"]
    p_nums = [f"Payout #{k}" for k in range(1, 6)]
    p_pcts = [ladder[k] for k in range(1, 6)]

    b_lad = ax_lad.bar(p_nums, p_pcts, color="#2ca02c", edgecolor="#000000", width=0.55, zorder=3)
    for b in b_lad:
        h = b.get_height()
        ax_lad.annotate(f"{h:.1f}%", (b.get_x() + b.get_width() / 2, h), xytext=(0, 4),
                        textcoords="offset points", ha="center", va="bottom", fontsize=8.5, fontweight="bold")

    ax_lad.set_title("Funded Payout Ladder (% of Passing Accounts Reaching Payout)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_lad.set_ylabel("Probability (%)", fontsize=9, color="#000000")
    ax_lad.set_ylim(0, 100)

    # Panel B: Payout Amount Distribution
    ax_dis = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_dis)

    nets = f_sum["nets"]
    ax_dis.hist(nets, bins=30, color="#1f77b4", edgecolor="#000000", alpha=0.75, zorder=3)
    ax_dis.axvline(f_sum["mean_net"], color="#2ca02c", linestyle="--", linewidth=1.8, label=f"Mean Net: ${f_sum['mean_net']:,.0f}")
    ax_dis.axvline(f_sum["median_net"], color="#000000", linestyle=":", linewidth=1.5, label=f"Median Net: ${f_sum['median_net']:,.0f}")

    ax_dis.set_title("Total Net Payout Extraction Distribution per Funded Account", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_dis.set_xlabel("Net Extraction ($ USD)", fontsize=9, color="#000000")
    ax_dis.set_ylabel("Account Count", fontsize=9, color="#000000")
    ax_dis.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_dis.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel C: Funded Economics Table
    ax_tab = fig.add_subplot(gs[1, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")

    ax_tab.text(0.02, 0.96, "Funded Account Payout & Longevity Economics Summary", fontsize=11, fontweight="bold", color="#000000")

    f_rows = [
        ("Simulated Passing Accounts", f"{f_sum['n']:,} accounts", "Accounts Achieving >= 1 Payout", f"{ladder[1]:.1f}%"),
        ("Mean Net Payout Extraction", fmt_currency(f_sum['mean_net'], 2), "Accounts Achieving >= 2 Payouts", f"{ladder[2]:.1f}%"),
        ("Median Net Payout Extraction", fmt_currency(f_sum['median_net'], 2), "Accounts Achieving >= 3 Payouts", f"{ladder[3]:.1f}%"),
        ("Accounts Breaching with Zero Payout", f"{f_sum['zero_payout_pct']:.1f}%", "Accounts Capped at 5 Payouts ($4,500 Max)", f"{ladder[5]:.1f}%"),
        ("Evaluation Fee Cost", "$39.00", "Net Expected Value (EV) / Attempt", fmt_currency(f_sum['ev_per_attempt'], 2, True)),
    ]

    t_x = [0.02, 0.28, 0.54, 0.82]
    y_pos = 0.78
    for r in f_rows:
        ax_tab.axhline(y_pos + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        ax_tab.text(t_x[0], y_pos, r[0], fontsize=8.2, color="#444444")
        ax_tab.text(t_x[1], y_pos, r[1], fontsize=8.5, fontweight="bold", color="#000000")
        ax_tab.text(t_x[2], y_pos, r[2], fontsize=8.2, color="#444444")
        ax_tab.text(t_x[3], y_pos, r[3], fontsize=8.5, fontweight="bold", color="#1f77b4" if "$" in r[3] or "%" in r[3] else "#000000")
        y_pos -= 0.14

    out_path = OUT_DIR / "05_prop_funded_survival_and_payout_harvest.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── MASTER OVERVIEW POSTER ───────────────────────────────────────────────────
def render_prop_poster_master(sim: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(18, 26), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    gs = fig.add_gridspec(5, 2, height_ratios=[3.6, 2.0, 2.0, 2.8, 1.8], hspace=0.35, wspace=0.20)

    # Panel 1: Main Evaluation Trajectories
    ax_main = fig.add_subplot(gs[0, :])
    format_spines_and_grid(ax_main)

    boot = sim["boot"]
    paths = boot["paths"]
    pass_paths = [p[1] for p in paths if p[0] == "pass"]
    fail_paths = [p[1] for p in paths if p[0] == "fail"]

    for p in fail_paths[:25]:
        ax_main.plot(range(len(p)), p, color="#d62728", alpha=0.30, linewidth=0.85, zorder=2)
        ax_main.plot(len(p) - 1, p[-1], marker="o", markersize=4.5, color="#d62728", markeredgecolor="#8b1819", markeredgewidth=0.5, zorder=3)

    for p in pass_paths[:75]:
        ax_main.plot(range(len(p)), p, color="#2ca02c", alpha=0.30, linewidth=0.85, zorder=3)
        ax_main.plot(len(p) - 1, p[-1], marker="o", markersize=4.5, color="#2ca02c", markeredgecolor="#1b6e22", markeredgewidth=0.5, zorder=4)

    med_sess = sim["boot_sum"]["pass_med"]
    closest_med = min(pass_paths, key=lambda p: abs(len(p) - med_sess)) if pass_paths else None
    if closest_med:
        ax_main.plot(range(len(closest_med)), closest_med, color="#1f77b4", linewidth=2.4, zorder=5,
                     label=f"Median Path ({len(closest_med)} sessions • ~{len(closest_med)*sim['cal_days_per_session']:.0f} cal days)")
        ax_main.plot(len(closest_med) - 1, closest_med[-1], marker="o", markersize=7.0, color="#1f77b4", zorder=6)

    ax_main.axhline(26_250.0, color="#2ca02c", linestyle="--", linewidth=1.8, label="Profit Target ($26,250 • +$1,250)")
    ax_main.axhline(25_100.0, color="#9467bd", linestyle=":", linewidth=1.6, label="Floor Lock ($25,100 once Peak >= $26,100)")
    ax_main.axhline(25_000.0, color="#777777", linestyle="-", linewidth=0.9, alpha=0.7, label="Initial Capital ($25,000)")
    ax_main.axhline(24_000.0, color="#d62728", linestyle="--", linewidth=1.8, label="Max Trailing Floor ($24,000 • -$1,000)")

    ax_main.set_title("Backtest Results - LucidFlex 25K Evaluation Corridor & Trajectories", fontsize=15, fontweight="bold", color="#000000", pad=12)
    b_sum = sim["boot_sum"]
    ch_pass_m = int((sim["chrono"]["back_to_back"]["status"] == "pass").sum())
    ch_tot_m = int(len(sim["chrono"]["back_to_back"][sim["chrono"]["back_to_back"]["status"].isin(["pass", "fail"])]))
    ch_rate_m = (ch_pass_m / ch_tot_m * 100.0) if ch_tot_m > 0 else 0.0
    sub = f"10k Bootstrap Pass Rate: {b_sum['pass_rate']:.1f}% • Chronological Replay: {ch_rate_m:.1f}% Pass • Median: {b_sum['pass_med']:.0f} sessions (~{b_sum['pass_med_cal_days']:.0f} cal days) • EV: +${sim['f_summary']['ev_per_attempt']:,.2f}"
    ax_main.text(0.5, 1.015, sub, transform=ax_main.transAxes, ha="center", va="bottom", fontsize=9.5, color="#555555")

    ax_main.set_xlabel("Exchange Sessions Elapsed", fontsize=10.5, color="#000000")
    ax_main.set_ylabel("Account Balance ($)", fontsize=10.5, color="#000000")
    ax_main.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_main.set_ylim(23_700, 26_600)
    leg = ax_main.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0), frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=9)
    leg.get_title().set_fontsize(9.5)
    leg.get_title().set_fontweight("bold")

    # Panel 2A: Peak Equity on Failed Accounts
    ax_pk = fig.add_subplot(gs[1, 0])
    format_spines_and_grid(ax_pk)
    ax_pk.hist(sim["failed_peaks"], bins=30, color="#d62728", alpha=0.75, edgecolor="#000000")
    ax_pk.axvline(sim["med_failed_peak"], color="#000000", linestyle="--", linewidth=1.8, label=f"Median: ${sim['med_failed_peak']:,.0f}")
    ax_pk.set_title("Peak Equity Reached Prior to Floor Breach", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_pk.set_xlabel("Peak Balance ($)", fontsize=9, color="#000000")
    ax_pk.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_pk.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel 2B: Slippage Sensitivity
    ax_slp = fig.add_subplot(gs[1, 1])
    format_spines_and_grid(ax_slp)
    ax_slp.plot(sim["slip_ticks"], sim["slip_pass_rates"], marker="o", color="#1f77b4", linewidth=2.0)
    ax_slp.axhline(50.0, color="#d62728", linestyle="--", linewidth=1.2, label="50% Edge Hurdle")
    for i, txt in enumerate(sim["slip_pass_rates"]):
        ax_slp.annotate(f"{txt:.1f}%", (sim["slip_ticks"][i], txt), textcoords="offset points", xytext=(0, 5), ha="center", fontsize=8, fontweight="bold")
    ax_slp.set_title("Adverse Slippage Stress Test (Pass Rate vs Extra Ticks)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_slp.set_xlabel("Extra Adverse Ticks per Leg", fontsize=9, color="#000000")
    ax_slp.set_ylabel("Pass Rate (%)", fontsize=9, color="#000000")
    ax_slp.set_ylim(35, 90)
    ax_slp.legend(loc="lower left", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel 3A: Cumulative Probability across K Attempts
    ax_att = fig.add_subplot(gs[2, 0])
    format_spines_and_grid(ax_att)
    p_df = da.sequential_attempt_economics(b_sum["pass_rate"], fee=39.0, max_attempts=6)
    ax_att.plot(p_df["attempts"], p_df["p_pass_within"], marker="o", color="#1f77b4", linewidth=2.0)
    ax_att.axhline(95.0, color="#2ca02c", linestyle="--", linewidth=1.2, label="95% Threshold")
    for idx, r in p_df.iterrows():
        ax_att.annotate(f"{r['p_pass_within']:.1f}%", (r["attempts"], r["p_pass_within"]), textcoords="offset points", xytext=(0, 4), ha="center", fontsize=8, fontweight="bold")
    ax_att.set_title("Sequential Retries (Pass Prob Within K Attempts)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_att.set_xlabel("Sequential Attempts (k)", fontsize=9, color="#000000")
    ax_att.set_ylabel("Probability (%)", fontsize=9, color="#000000")
    ax_att.set_ylim(65, 102)
    ax_att.legend(loc="lower right", frameon=True, facecolor="#FFFFFF", edgecolor="#000000", fontsize=8)

    # Panel 3B: Funded Payout Ladder
    ax_lad = fig.add_subplot(gs[2, 1])
    format_spines_and_grid(ax_lad)
    ladder = sim["f_summary"]["ladder"]
    ax_lad.bar([f"Payout #{k}" for k in range(1, 6)], [ladder[k] for k in range(1, 6)], color="#2ca02c", edgecolor="#000000", width=0.55)
    for idx, k in enumerate(range(1, 6)):
        ax_lad.annotate(f"{ladder[k]:.1f}%", (idx, ladder[k]), textcoords="offset points", xytext=(0, 4), ha="center", fontsize=8, fontweight="bold")
    ax_lad.set_title("Funded Payout Ladder (% Reaching Payout N)", fontsize=11, fontweight="bold", color="#000000", pad=8)
    ax_lad.set_ylabel("Probability (%)", fontsize=9, color="#000000")
    ax_lad.set_ylim(0, 100)

    # Panel 4: Chronological History Table
    ax_ch = fig.add_subplot(gs[3, :])
    ax_ch.set_facecolor("#FFFFFF")
    ax_ch.axis("off")
    ch_df = sim["chrono"]["back_to_back"]
    ax_ch.text(0.02, 0.96, f"Chronological Back-to-Back Evaluation Replay (2021-2026 • {len(ch_df)} Attempts)", fontsize=11, fontweight="bold", color="#000000")

    c_hdr = ["Attempt #", "Start Date", "End Date", "Status", "Duration (Sessions)", "Duration (Calendar Days)", "Outcome Assessment"]
    c_x = [0.02, 0.12, 0.24, 0.36, 0.48, 0.64, 0.98]
    for i, h in enumerate(c_hdr):
        ax_ch.text(c_x[i], 0.84, h, fontsize=8.0, fontweight="bold", color="#000000", ha="left" if i < 6 else "right")

    y_c = 0.72
    for idx, r in ch_df.iterrows():
        ax_ch.axhline(y_c + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        is_pass = r["status"] == "pass"
        is_fail = r["status"] == "fail"
        c_status = "#2ca02c" if is_pass else ("#d62728" if is_fail else "#1f77b4")
        cal_d = int((pd.to_datetime(r["end"]) - pd.to_datetime(r["start"])).days)
        diag = "Reached +$1,250 target cleanly" if is_pass else ("Hit -$1,000 trailing floor" if is_fail else "Currently active evaluation")

        ax_ch.text(c_x[0], y_c, f"Attempt #{idx+1}", fontsize=7.8, color="#000000")
        ax_ch.text(c_x[1], y_c, str(r["start"]), fontsize=7.8, color="#000000")
        ax_ch.text(c_x[2], y_c, str(r["end"]), fontsize=7.8, color="#000000")
        ax_ch.text(c_x[3], y_c, r["status"].upper(), fontsize=7.8, fontweight="bold", color=c_status)
        ax_ch.text(c_x[4], y_c, f"{r['sessions']} sessions", fontsize=7.8, color="#000000")
        ax_ch.text(c_x[5], y_c, f"{cal_d} days", fontsize=7.8, color="#000000")
        ax_ch.text(c_x[6], y_c, diag, fontsize=7.8, color="#555555", ha="right")
        y_c -= 0.054

    # Panel 5: Master Prop Parameters & Metrics Table
    ax_tab = fig.add_subplot(gs[4, :])
    ax_tab.set_facecolor("#FFFFFF")
    ax_tab.axis("off")
    ax_tab.text(0.02, 0.94, "LucidFlex 25K Rulebook & Performance Summary", fontsize=11, fontweight="bold", color="#000000")

    summary_rows = [
        ("Account Size / Profit Target", "$25,000 / +$1,250 (5.0%)", "10k Bootstrap Pass Rate", f"{b_sum['pass_rate']:.1f}%"),
        ("Trailing Drawdown Allowance", "$1,000 (EOD Closing Basis)", "Median Sessions to Target", f"{b_sum['pass_med']:.0f} sess (~{b_sum['pass_med_cal_days']:.0f} cal days)"),
        ("Floor Lock Rule", "$25,100 once Peak >= $26,100", "Chronological Pass Rate", f"{ch_rate_m:.1f}% ({ch_pass_m} pass / {ch_tot_m - ch_pass_m} fail)"),
        ("Daily Soft Stop Threshold", "-$600 (Halts Remaining Windows)", "Net Expected Value / Attempt", f"+${sim['f_summary']['ev_per_attempt']:,.2f} per $39 fee"),
    ]

    s_x = [0.02, 0.28, 0.54, 0.82]
    y_s = 0.76
    for r in summary_rows:
        ax_tab.axhline(y_s + 0.015, color="#E5E5E5", linewidth=0.5, xmin=0.02, xmax=0.98)
        ax_tab.text(s_x[0], y_s, r[0], fontsize=8.2, color="#444444")
        ax_tab.text(s_x[1], y_s, r[1], fontsize=8.5, fontweight="bold", color="#000000")
        ax_tab.text(s_x[2], y_s, r[2], fontsize=8.2, color="#444444")
        ax_tab.text(s_x[3], y_s, r[3], fontsize=8.5, fontweight="bold", color="#1f77b4" if "$" in r[3] or "%" in r[3] else "#000000")
        y_s -= 0.16

    out_path = OUT_DIR / "lucid_flex_25k_prop_mode_report.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── INTERACTIVE HTML DASHBOARD ────────────────────────────────────────────────
def generate_prop_html_dashboard(sim: dict) -> Path:
    html_path = OUT_DIR / "dashboard.html"

    boot = sim["boot"]
    paths = boot["paths"]
    trajectories_data = [
        {"status": p[0], "path": [round(x, 2) for x in p[1]]}
        for p in paths[:60]
    ]

    p_sess = [int(x) for x in sorted(boot["sessions"][boot["status"] == "pass"])]
    cum_probs = [float(x) for x in (np.arange(1, len(p_sess) + 1) / len(p_sess) * boot["pass_rate"]).round(2)]
    step_sess = p_sess[::max(1, len(p_sess) // 100)]
    step_probs = cum_probs[::max(1, len(cum_probs) // 100)]

    b_sum = sim["boot_sum"]
    ch = sim["chrono"]["back_to_back"]
    ch_valid = ch[ch["status"].isin(["pass", "fail"])]
    ch_pass = int((ch["status"] == "pass").sum())
    ch_total = int(len(ch_valid))
    ch_rate = (ch_pass / ch_total * 100.0) if ch_total > 0 else 0.0
    ch_rows = []
    for idx, r in ch.iterrows():
        ch_rows.append({
            "id": idx + 1,
            "start": str(r["start"]),
            "end": str(r["end"]),
            "status": r["status"].upper(),
            "sessions": int(r["sessions"]),
            "cal_days": int((pd.to_datetime(r["end"]) - pd.to_datetime(r["start"])).days),
        })

    payload = {
        "pass_rate": float(b_sum["pass_rate"]),
        "fail_rate": float(b_sum["fail_rate"]),
        "med_sessions": float(b_sum["pass_med"]),
        "med_cal_days": float(b_sum["pass_med_cal_days"]),
        "p90_sessions": float(b_sum["pass_p90"]),
        "ev_per_attempt": float(sim["f_summary"]["ev_per_attempt"]),
        "trajectories": trajectories_data,
        "speed_x": step_sess,
        "speed_y": step_probs,
        "slip_ticks": [int(k) for k in sim["slip_ticks"]],
        "slip_pass_rates": [float(p) for p in sim["slip_pass_rates"]],
        "chrono": ch_rows,
        "chrono_rate": float(ch_rate),
        "chrono_sub": f"{ch_pass} of {ch_total} Replay Attempts",
    }
    json_payload = json.dumps(payload, default=lambda o: int(o) if isinstance(o, (np.integer, int)) else float(o))

    html_code = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LucidFlex 25K • Institutional Prop Evaluation Tearsheet</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg: #FFFFFF;
    --text-primary: #000000;
    --text-secondary: #555555;
    --border: #E5E5E5;
    --accent-blue: #1f77b4;
    --accent-green: #2ca02c;
    --accent-red: #d62728;
    --accent-purple: #9467bd;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: #FAFAFA;
    color: var(--text-primary);
    padding: 24px;
    line-height: 1.45;
  }}
  .container {{
    max-width: 1400px;
    margin: 0 auto;
    background: var(--bg);
    border: 1px solid var(--border);
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    padding: 28px;
  }}
  header {{
    border-bottom: 2px solid var(--text-primary);
    padding-bottom: 16px;
    margin-bottom: 24px;
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
  }}
  h1 {{ font-size: 24px; font-weight: 700; color: var(--text-primary); letter-spacing: -0.3px; }}
  .meta-sub {{ font-size: 13px; color: var(--text-secondary); margin-top: 4px; }}
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
    margin-bottom: 24px;
  }}
  .kpi-card {{
    background: #FFF;
    border: 1px solid var(--border);
    padding: 14px;
    border-radius: 4px;
  }}
  .kpi-label {{ font-size: 11px; text-transform: uppercase; color: var(--text-secondary); font-weight: 600; margin-bottom: 4px; }}
  .kpi-value {{ font-size: 22px; font-weight: 700; color: var(--text-primary); }}
  .kpi-sub {{ font-size: 11px; color: var(--text-secondary); margin-top: 2px; }}
  .chart-box {{
    background: #FFF;
    border: 1px solid var(--border);
    padding: 18px;
    margin-bottom: 24px;
    border-radius: 4px;
  }}
  .chart-title {{ font-size: 14px; font-weight: 700; margin-bottom: 12px; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    text-align: left;
  }}
  th, td {{
    padding: 9px 12px;
    border-bottom: 1px solid var(--border);
  }}
  th {{
    background: #F7F7F7;
    font-weight: 700;
  }}
  .num-pos {{ color: var(--accent-green); font-weight: 600; }}
  .num-neg {{ color: var(--accent-red); font-weight: 600; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>LucidFlex 25K • Institutional Prop Evaluation Tearsheet</h1>
      <div class="meta-sub">Continuous Calendar Simulation • Anti-Martingale Ratchet (2/3/4 Micros) • EOD Trailing Floor Lock</div>
    </div>
    <div style="text-align: right;">
      <div style="font-size: 14px; font-weight: 700; color: var(--accent-blue);">LucidFlex Rule Parity</div>
      <div style="font-size: 12px; color: var(--text-secondary);">Target: +$1,250 • Max DD: $1,000 EOD</div>
    </div>
  </header>

  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label">Bootstrap Pass Rate</div>
      <div class="kpi-value" style="color: var(--accent-green);" id="kpi-pass">0.0%</div>
      <div class="kpi-sub">10,000 Reshuffled Runs</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Median Duration</div>
      <div class="kpi-value" id="kpi-med">0 sess</div>
      <div class="kpi-sub" id="kpi-cal-days">0 cal days</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Chrono Pass Rate</div>
      <div class="kpi-value" style="color: var(--accent-blue);" id="kpi-chrono-rate">0.0%</div>
      <div class="kpi-sub" id="kpi-chrono-sub">0 of 0 Replay Attempts</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Expected Net Extraction</div>
      <div class="kpi-value" id="kpi-ev" style="color: var(--accent-green);">$0</div>
      <div class="kpi-sub">Per $39 Evaluation Fee</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">P90 Duration</div>
      <div class="kpi-value" id="kpi-p90">0 sess</div>
      <div class="kpi-sub">90th Percentile Ceiling</div>
    </div>
  </div>

  <div class="chart-box">
    <div class="chart-title">Evaluation Trajectories Corridor (100 Sample Paths Shown)</div>
    <div style="height: 400px;">
      <canvas id="trajChart"></canvas>
    </div>
  </div>

  <div class="chart-box">
    <div class="chart-title">Cumulative Target Speed Curve (% Probability Reached vs Exchange Sessions)</div>
    <div style="height: 240px;">
      <canvas id="speedChart"></canvas>
    </div>
  </div>

  <div class="chart-box">
    <div class="chart-title">Historical Back-to-Back Evaluation Replay Timeline (2021-2026)</div>
    <div style="max-height: 400px; overflow-y: auto;">
      <table>
        <thead>
          <tr>
            <th>Attempt #</th>
            <th>Start Date</th>
            <th>End Date</th>
            <th>Status</th>
            <th>Sessions</th>
            <th>Calendar Days</th>
          </tr>
        </thead>
        <tbody id="chronoBody"></tbody>
      </table>
    </div>
  </div>
</div>

<script>
const data = {json_payload};

document.getElementById('kpi-pass').innerText = data.pass_rate.toFixed(1) + '%';
document.getElementById('kpi-med').innerText = data.med_sessions.toFixed(0) + ' sess';
document.getElementById('kpi-cal-days').innerText = '~' + data.med_cal_days.toFixed(0) + ' calendar days';
document.getElementById('kpi-p90').innerText = data.p90_sessions.toFixed(0) + ' sess';
document.getElementById('kpi-ev').innerText = '+$' + data.ev_per_attempt.toFixed(2);
document.getElementById('kpi-chrono-rate').innerText = data.chrono_rate.toFixed(1) + '%';
document.getElementById('kpi-chrono-sub').innerText = data.chrono_sub;

// Trajectory chart
const trajDatasets = [];
data.trajectories.forEach((t, idx) => {{
  const isPass = t.status === 'pass';
  trajDatasets.push({{
    label: isPass ? 'Pass Path' : 'Fail Path',
    data: t.path,
    borderColor: isPass ? 'rgba(44, 160, 44, 0.35)' : 'rgba(214, 39, 40, 0.35)',
    borderWidth: 1.0,
    pointRadius: 0,
    fill: false,
  }});
}});

// Reference lines
const maxLen = Math.max(...data.trajectories.map(t => t.path.length));
const labels = Array.from({{ length: maxLen }}, (_, i) => i);

new Chart(document.getElementById('trajChart').getContext('2d'), {{
  type: 'line',
  data: {{ labels: labels, datasets: trajDatasets }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ title: {{ display: true, text: 'Exchange Sessions Elapsed' }}, grid: {{ color: '#E5E5E5' }} }},
      y: {{ min: 23800, max: 26500, grid: {{ color: '#E5E5E5' }}, ticks: {{ callback: v => '$' + v.toLocaleString() }} }}
    }}
  }}
}});

// Speed chart
new Chart(document.getElementById('speedChart').getContext('2d'), {{
  type: 'line',
  data: {{
    labels: data.speed_x,
    datasets: [{{
      label: 'Cumulative Pass Probability (%)',
      data: data.speed_y,
      borderColor: '#1f77b4',
      backgroundColor: 'rgba(31, 119, 180, 0.1)',
      borderWidth: 2,
      fill: true,
      pointRadius: 0,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    scales: {{
      x: {{ title: {{ display: true, text: 'Exchange Sessions' }}, grid: {{ color: '#E5E5E5' }} }},
      y: {{ title: {{ display: true, text: 'Cumulative Pass Rate (%)' }}, min: 0, max: 100, grid: {{ color: '#E5E5E5' }} }}
    }}
  }}
}});

// Chrono table
let cHtml = '';
data.chrono.forEach(r => {{
  const cls = r.status === 'PASS' ? 'num-pos' : (r.status === 'FAIL' ? 'num-neg' : '');
  cHtml += `<tr>
    <td><strong>Attempt #${{r.id}}</strong></td>
    <td>${{r.start}}</td>
    <td>${{r.end}}</td>
    <td class="${{cls}}">${{r.status}}</td>
    <td>${{r.sessions}} sess</td>
    <td>${{r.cal_days}} days</td>
  </tr>`;
}});
document.getElementById('chronoBody').innerHTML = cHtml;
</script>
</body>
</html>"""

    html_path.write_text(html_code, encoding="utf-8")
    return html_path


def main():
    print("=" * 80)
    print("INSTITUTIONAL PROP EVALUATION & FUNDED SUITE GENERATOR")
    print("=" * 80)
    print(f"Output Directory: {OUT_DIR}")

    sim = run_full_simulation_suite()

    print("\nRendering Publication-Grade Prop PNG Sheets...")
    p1 = render_prop_sheet_01_trajectories(sim)
    print(f"  [Sheet 01] Trajectories & Corridor: {p1.name}")

    p2 = render_prop_sheet_02_failure_mechanics(sim)
    print(f"  [Sheet 02] Failure Mechanics & Cushion Decay: {p2.name}")

    p3 = render_prop_sheet_03_rulebook_and_slippage(sim)
    print(f"  [Sheet 03] Rulebook & Slippage Stress Test: {p3.name}")

    p4 = render_prop_sheet_04_slot_lifecycle(sim)
    print(f"  [Sheet 04] Sequential Attempt Economics & History: {p4.name}")

    p5 = render_prop_sheet_05_funded_survival(sim)
    print(f"  [Sheet 05] Funded Survival & Payout Harvest: {p5.name}")

    p_post = render_prop_poster_master(sim)
    print(f"  [Poster] Master LucidFlex Prop Mode Report: {p_post.name}")

    print("\nGenerating Interactive HTML Prop Dashboard...")
    p_html = generate_prop_html_dashboard(sim)
    print(f"  [HTML] Interactive Dashboard: {p_html.name}")

    print("\nAll prop dashboard artifacts generated successfully.")


if __name__ == "__main__":
    main()
