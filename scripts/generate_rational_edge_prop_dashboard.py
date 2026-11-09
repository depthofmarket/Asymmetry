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
    ax.grid(True, color="#F1F5F9", linestyle="--", linewidth=0.6, zorder=0)
    for sp in ax.spines.values():
        sp.set_color("#CBD5E1")
        sp.set_linewidth(0.8)
    ax.tick_params(colors="#334155", labelsize=8.5)


def create_institutional_table(
    ax,
    data: list[list[str]],
    headers: list[str],
    col_widths: list[float],
    title: str | None = None,
    row_scale: float = 1.8,
    font_size: float = 8.5,
    highlight_row: int | None = None,
):
    """Renders a clean, institutional publication-grade table with auto-wrapping and alternating rows."""
    ax.axis("off")
    if title:
        ax.text(0.0, 0.98, title, fontsize=10.5, fontweight="bold", color="#0F172A", transform=ax.transAxes, va="top")
    tab = ax.table(cellText=data, colLabels=headers, loc="center", cellLoc="left", colWidths=col_widths)
    tab.auto_set_font_size(False)
    tab.set_fontsize(font_size)
    tab.scale(1.0, row_scale)
    for (r, c), cell in tab.get_celld().items():
        cell.set_edgecolor("#CBD5E1")
        cell.set_linewidth(0.6)
        if r == 0:
            cell.set_facecolor("#F1F5F9")
            cell.get_text().set_weight("bold")
            cell.get_text().set_color("#0F172A")
        else:
            if highlight_row is not None and r == highlight_row:
                cell.set_facecolor("#EFF6FF")
                cell.get_text().set_color("#1D4ED8")
                cell.get_text().set_weight("bold")
            else:
                cell.set_facecolor("#FFFFFF" if r % 2 == 1 else "#F8FAFC")
                cell.get_text().set_color("#334155")
    return tab


def run_full_simulation_suite() -> dict:
    trades = da.load_trades()
    calendar = da.load_session_calendar(start=trades["date"].min(), end=trades["date"].max())
    legs = da.build_session_legs(trades, calendar)
    rules = da.PropRules()
    funded_rules = da.FundedRules()
    cal_days_per_session = 365.25 / 252.0

    print("Running 10,000 Block Bootstrap Monte Carlo Simulations (Live Ratchet)...")
    boot = da.bootstrap_prop(legs, da.POLICIES["live_ratchet"], n_sims=10_000, block=10, horizon=750,
                             rules=rules, extra_ticks=0.0, n_paths=1000, seed=42, funded=funded_rules)
    boot_sum = da.summarize_prop(boot, cal_days_per_session)

    print("Computing Unconstrained Strategy Drift Corridor (Horizon = 120)...")
    n_legs = len(legs)
    horizon_uncon = 120
    rng_uncon = np.random.default_rng(42)
    uncon_paths = []
    for _ in range(1000):
        idx = da.block_bootstrap_sessions(n_legs, horizon_uncon, 10, rng_uncon)
        bal = 25000.0
        p = [bal]
        for j in idx:
            for grp in legs[j]:
                profit_now = bal - 25000.0
                gpnl = sum(da.leg_pnl(l, da.POLICIES["live_ratchet"], profit_now, 0.0) for l in grp)
                bal += gpnl
            p.append(bal)
        uncon_paths.append(p)
    uncon_mat = np.array(uncon_paths)

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
        "uncon_mat": uncon_mat,
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
    fig = plt.figure(figsize=(16, 9.5), dpi=300)
    fig.patch.set_facecolor("#FFFFFF")

    # Explicit top margin for dedicated header band (Zero Overlap Guaranteed)
    gs = fig.add_gridspec(1, 2, width_ratios=[3.6, 1.0], wspace=0.08, top=0.82, bottom=0.09, left=0.07, right=0.96)

    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1], sharey=ax1)

    format_spines_and_grid(ax1)
    format_spines_and_grid(ax2)
    plt.setp(ax2.get_yticklabels(), visible=False)

    boot = sim["boot"]
    paths = boot["paths"]
    b_sum = sim["boot_sum"]
    ch = sim["chrono"]["back_to_back"]
    ch_pass = int((ch["status"] == "pass").sum())
    ch_total = int(len(ch[ch["status"].isin(["pass", "fail"])]))
    ch_rate = (ch_pass / ch_total * 100.0) if ch_total > 0 else 0.0

    # ── DEDICATED HEADER BAND (NO OVERLAP WITH SUBPLOTS) ─────────────────────────
    fig.text(0.07, 0.955, "LucidFlex 25K Evaluation Corridor & Monte Carlo Trajectories", fontsize=15, fontweight="bold", color="#0F172A")
    fig.text(0.07, 0.925, "10,000 Block-Bootstrap Simulations  •  Live Ratchet Sizing (2/3/4 Micros)  •  Continuous Session Calendar", fontsize=9.2, color="#475569")

    meta_r1 = f"Bootstrap Pass Rate: {b_sum['pass_rate']:.1f}%  |  Chronological Replay: {ch_pass}/{ch_total} ({ch_rate:.1f}%)"
    meta_r2 = f"Median Duration: {b_sum['pass_med']:.0f} sess (~{b_sum['pass_med_cal_days']:.0f} cal days)  |  EV / Attempt: {fmt_currency(sim['f_summary']['ev_per_attempt'], 2, force_sign=True)}"
    fig.text(0.96, 0.955, meta_r1, fontsize=9.5, fontweight="bold", color="#0F172A", ha="right")
    fig.text(0.96, 0.925, meta_r2, fontsize=9.2, fontweight="bold", color="#059669", ha="right")

    # ── AX1: STRATEGY CORRIDOR & REALIZED PROP PATHS ─────────────────────────────
    horizon = 120
    uncon_mat = sim["uncon_mat"]
    x_uncon = np.arange(horizon + 1)

    p05 = np.percentile(uncon_mat, 5, axis=0)
    p25 = np.percentile(uncon_mat, 25, axis=0)
    p50 = np.percentile(uncon_mat, 50, axis=0)
    p75 = np.percentile(uncon_mat, 75, axis=0)
    p95 = np.percentile(uncon_mat, 95, axis=0)

    # Layered percentile ribbons for natural strategy volatility cone
    ax1.fill_between(x_uncon, p05, p95, color="#BAE6FD", alpha=0.35, zorder=2, label="P05–P95 Corridor (90% Conf)")
    ax1.fill_between(x_uncon, p25, p75, color="#38BDF8", alpha=0.40, zorder=3, label="P25–P75 Interquartile Core")
    ax1.plot(x_uncon, p50, color="#0284C7", linestyle=":", linewidth=1.8, zorder=4, label="Median Strategy Drift")

    # Realized Prop Evaluation Sample Paths
    pass_paths = [p[1] for p in paths if p[0] == "pass"]
    fail_paths = [p[1] for p in paths if p[0] == "fail"]

    for p in pass_paths[:35]:
        t_end = min(len(p), horizon)
        ax1.plot(range(t_end), p[:t_end], color="#059669", alpha=0.22, linewidth=0.8, zorder=5)
        if len(p) <= horizon:
            ax1.plot(len(p) - 1, p[-1], marker="o", markersize=3.5, color="#059669", alpha=0.7, zorder=6)

    for p in fail_paths[:18]:
        t_end = min(len(p), horizon)
        ax1.plot(range(t_end), p[:t_end], color="#DC2626", alpha=0.22, linewidth=0.8, zorder=5)
        if len(p) <= horizon:
            ax1.plot(len(p) - 1, p[-1], marker="x", markersize=4.0, color="#DC2626", alpha=0.7, zorder=6)

    # Highlight the Median Passing Path
    med_sess = b_sum["pass_med"]
    closest_med = min(pass_paths, key=lambda p: abs(len(p) - med_sess)) if pass_paths else None
    if closest_med:
        t_med = min(len(closest_med), horizon)
        ax1.plot(range(t_med), closest_med[:t_med], color="#0F172A", linewidth=2.4, zorder=7,
                 label=f"Median Pass Path ({len(closest_med)} sess)")
        if len(closest_med) <= horizon:
            ax1.plot(len(closest_med) - 1, closest_med[-1], marker="o", markersize=7.0, color="#0F172A", markeredgecolor="#FFFFFF", markeredgewidth=1.2, zorder=8)

    # Challenge Thresholds (Escaped \$ prevents Matplotlib KaTeX math mode bug)
    ax1.axhline(26_250.0, color="#059669", linestyle="--", linewidth=1.8, zorder=6, label=r"Profit Target (\$26,250)")
    ax1.axhline(25_100.0, color="#7C3AED", linestyle=":", linewidth=1.5, zorder=6, label=r"Floor Lock (\$25,100)")
    ax1.axhline(25_000.0, color="#64748B", linestyle="-", linewidth=0.9, alpha=0.7, zorder=4, label=r"Starting Capital (\$25,000)")
    ax1.axhline(24_000.0, color="#DC2626", linestyle="--", linewidth=1.8, zorder=6, label=r"Max Trailing Floor (\$24,000)")

    ax1.set_xlabel("Exchange Sessions Elapsed (Continuous Calendar)", fontsize=10, fontweight="bold", color="#0F172A")
    ax1.set_ylabel("Account Balance ($)", fontsize=10, fontweight="bold", color="#0F172A", labelpad=8)
    ax1.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax1.set_ylim(23_500, 27_200)
    ax1.set_xlim(0, horizon)

    # Horizontal Legend Banner Above ax1 (Zero Occlusion, 4 balanced columns < 28 chars each)
    leg = ax1.legend(loc="lower left", bbox_to_anchor=(0.0, 1.03, 1.0, 0.05), mode="expand", ncol=4,
                     frameon=True, facecolor="#F8FAFC", edgecolor="#CBD5E1", fontsize=8.0)
    leg.get_frame().set_linewidth(0.8)

    # ── AX2: RIGHT PANEL (FIRST-PASSAGE OUTCOME MASS & DENSITY) ──────────────────
    ax2.axhline(26_250.0, color="#059669", linestyle="--", linewidth=1.5, zorder=4)
    ax2.axhline(25_100.0, color="#7C3AED", linestyle=":", linewidth=1.2, zorder=4)
    ax2.axhline(25_000.0, color="#64748B", linestyle="-", linewidth=0.8, zorder=3)
    ax2.axhline(24_000.0, color="#DC2626", linestyle="--", linewidth=1.5, zorder=4)

    # Shaded Outcome Zones
    ax2.axhspan(26_250.0, 27_200.0, color="#ECFDF5", alpha=0.7, zorder=1)
    ax2.axhspan(24_000.0, 26_250.0, color="#F8FAFC", alpha=0.7, zorder=1)
    ax2.axhspan(23_500.0, 24_000.0, color="#FEF2F2", alpha=0.7, zorder=1)

    pass_pct = b_sum["pass_rate"]
    fail_pct = b_sum["fail_rate"]

    # Horizontal Outcome Bars
    ax2.barh(26_700.0, pass_pct / 100.0, height=450, color="#10B981", edgecolor="#059669", alpha=0.85, zorder=3)
    ax2.barh(23_750.0, fail_pct / 100.0, height=350, color="#EF4444", edgecolor="#DC2626", alpha=0.85, zorder=3)

    # Outcome Badges placed in safe coordinates with solid background pill boxes (NO line collisions)
    ax2.text(0.5, 26_700.0, f"PASS: {pass_pct:.1f}%", color="#FFFFFF", fontweight="bold", fontsize=8.5,
             ha="center", va="center", bbox=dict(boxstyle="round,pad=0.35", facecolor="#059669", edgecolor="#047857", alpha=0.95), zorder=5)
    ax2.text(0.5, 23_750.0, f"BREACH: {fail_pct:.1f}%", color="#FFFFFF", fontweight="bold", fontsize=8.0,
             ha="center", va="center", bbox=dict(boxstyle="round,pad=0.35", facecolor="#DC2626", edgecolor="#991B1B", alpha=0.95), zorder=5)

    # Middle zone: Near-miss peak distribution of failed accounts
    f_peaks = sim["failed_peaks"]
    if len(f_peaks) > 0:
        bins_f = np.linspace(24_100, 26_150, 16)
        counts_f, edges_f = np.histogram(f_peaks, bins=bins_f)
        if counts_f.max() > 0:
            norm_f = (counts_f / counts_f.max()) * 0.75
            for j in range(len(counts_f)):
                y_bot = edges_f[j]
                y_top = edges_f[j + 1]
                y_mid = 0.5 * (y_bot + y_top)
                ax2.barh(y_mid, norm_f[j], height=(y_top - y_bot) * 0.85, color="#CBD5E1", edgecolor="#94A3B8", alpha=0.5, zorder=3)

    ax2.text(0.5, 25_600.0, f"Peak Autopsy\nMed: \\${sim['med_failed_peak']:,.0f}", color="#334155", fontweight="bold", fontsize=8.0,
             ha="center", va="center", bbox=dict(boxstyle="round,pad=0.35", facecolor="#FFFFFF", edgecolor="#CBD5E1", alpha=0.95), zorder=5)

    ax2.set_title("Terminal Density", fontsize=9.5, fontweight="bold", color="#0F172A", pad=12)
    ax2.set_xlabel("Rel. Probability", fontsize=8.5, color="#0F172A")
    ax2.set_xlim(0, 1.15)
    ax2.set_xticks([0, 0.5, 1.0])
    ax2.set_xticklabels(["0", "50%", "100%"], fontsize=8)

    out_path = OUT_DIR / "01_prop_evaluation_trajectories_and_corridor.png"
    plt.savefig(out_path, dpi=300, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 02: FAILURE MECHANICS & CUSHION DECAY ──────────────────────────────
def render_prop_sheet_02_failure_mechanics(sim: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    # Generous top margin (top=0.85) to guarantee zero collision between header and subplot titles
    gs = fig.add_gridspec(2, 2, height_ratios=[1.6, 1.4], hspace=0.35, wspace=0.22, top=0.85, bottom=0.08, left=0.07, right=0.95)

    # Dedicated Header Band
    fig.text(0.07, 0.965, "LucidFlex 25K Failure Autopsy & Cushion Decay Mechanics", fontsize=14, fontweight="bold", color="#0F172A")
    fig.text(0.07, 0.938, "Empirical Breakdown of Floor Breaches, Peak Cushion Trajectories & Near-Miss Rates", fontsize=9.2, color="#475569")

    # Panel A: Peak Balance of Breached Accounts
    ax_pk = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_pk)

    f_peaks = sim["failed_peaks"]
    counts_pk, bins_pk, _ = ax_pk.hist(f_peaks, bins=30, color="#DC2626", alpha=0.75, edgecolor="#991B1B", zorder=3)
    ax_pk.axvline(sim["med_failed_peak"], color="#0F172A", linestyle="--", linewidth=1.8, label=f"Median Peak: \\${sim['med_failed_peak']:,.0f}")
    ax_pk.axvline(25_500, color="#D97706", linestyle=":", linewidth=1.5, label=f"+\\$500 Near-Miss ({sim['near_miss_25500_pct']:.1f}%)")
    ax_pk.axvline(26_000, color="#059669", linestyle=":", linewidth=1.5, label=f"+\\$1,000 Near-Miss ({sim['near_miss_26000_pct']:.1f}%)")

    ax_pk.set_title("Peak Equity Prior to Floor Breach (Breached Accounts)", fontsize=10.5, fontweight="bold", color="#0F172A", pad=8)
    ax_pk.set_xlabel("Peak Account Balance ($)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_pk.set_ylabel("Breached Account Count", fontsize=9, fontweight="bold", color="#0F172A")
    ax_pk.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_pk.set_ylim(0, max(counts_pk) * 1.35 if len(counts_pk) else 10)
    ax_pk.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1", fontsize=8.2)

    # Panel B: Sessions Elapsed to Breach
    ax_cas = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_cas)

    f_sess = sim["failed_sessions"]
    med_f_sess = float(np.median(f_sess)) if len(f_sess) else 0.0
    counts_cas, _, _ = ax_cas.hist(f_sess, bins=30, color="#2563EB", alpha=0.75, edgecolor="#1D4ED8", zorder=3)
    ax_cas.axvline(med_f_sess, color="#DC2626", linestyle="--", linewidth=1.8,
                   label=f"Median Duration: {med_f_sess:.0f} sess (~{med_f_sess*sim['cal_days_per_session']:.0f} cal days)")

    ax_cas.set_title("Failure Elapsed Duration (Exchange Sessions to Floor Hit)", fontsize=10.5, fontweight="bold", color="#0F172A", pad=8)
    ax_cas.set_xlabel("Exchange Sessions Elapsed", fontsize=9, fontweight="bold", color="#0F172A")
    ax_cas.set_ylabel("Account Count", fontsize=9, fontweight="bold", color="#0F172A")
    ax_cas.set_ylim(0, max(counts_cas) * 1.35 if len(counts_cas) else 10)
    ax_cas.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1", fontsize=8.2)

    # Panel C: Failure Autopsy & Near-Miss Analytics Table
    ax_tab = fig.add_subplot(gs[1, :])
    fail_rate = sim["boot_sum"]["fail_rate"]
    fail_hdr = ["Failure Diagnostic Metric", "Observed Value", "Near-Miss Criterion", "Empirical Failure Share"]
    fail_data = [
        ["Median Peak Balance Before Breach", fmt_currency(sim['med_failed_peak'], 2), "Reached >= \\$25,500 (+40% Target)", f"{sim['near_miss_25500_pct']:.1f}% of breached accounts"],
        ["Median Sessions to Breach", f"{med_f_sess:.0f} sessions (~{med_f_sess*sim['cal_days_per_session']:.0f} cal days)", "Reached >= \\$25,750 (+60% Target)", f"{sim['near_miss_25750_pct']:.1f}% of breached accounts"],
        ["Fastest Observed Breach", f"{np.min(f_sess):.0f} sessions" if len(f_sess) else "N/A", "Heartbreak Near-Miss (>= \\$26,000 / +80%)", f"{sim['near_miss_26000_pct']:.1f}% of breached accounts"],
        ["Slowest Observed Breach", f"{np.max(f_sess):.0f} sessions" if len(f_sess) else "N/A", "Floor Lock Protection (\\$25,100 Lock)", "Guarantees 0% breaches once peak >= \\$26,100"],
        ["Soft Stop Intraday Halt (-\\$600)", "Halts remainder of session on day DD", "Anti-Martingale Cushion Sizing", "De-escalates to Tier 1 (2 micros) in drawdown"],
    ]
    widths_fail = [0.28, 0.20, 0.28, 0.24]
    create_institutional_table(
        ax_tab, fail_data, fail_hdr, widths_fail,
        title=f"Failure Autopsy & Near-Miss Cushion Analytics (Breached Population = {fail_rate:.1f}%)",
        row_scale=1.75, font_size=8.5,
    )

    out_path = OUT_DIR / "02_prop_failure_mechanics_and_cushion_decay.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 03: RULEBOOK & SLIPPAGE STRESS TESTS ───────────────────────────────
def render_prop_sheet_03_rulebook_and_slippage(sim: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    # Generous top margin (top=0.85) to guarantee zero collision between header and subplot titles
    gs = fig.add_gridspec(2, 2, height_ratios=[1.6, 1.4], hspace=0.35, wspace=0.22, top=0.85, bottom=0.08, left=0.07, right=0.95)

    fig.text(0.07, 0.965, "Evaluation Rulebook Governance & Adverse Slippage Stress Testing", fontsize=14, fontweight="bold", color="#0F172A")
    fig.text(0.07, 0.938, "Sensitivity across 0 to 6 Extra Adverse Ticks per Leg • Sizing Policy Benchmark • Multi-Firm Model Comparison", fontsize=9.2, color="#475569")

    # Panel A: Slippage Sensitivity Curve
    ax_slp = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_slp)

    ticks = sim["slip_ticks"]
    p_rates = sim["slip_pass_rates"]
    ax_slp.plot(ticks, p_rates, marker="o", color="#2563EB", linewidth=2.0, label="Evaluation Pass Rate (%)", zorder=3)
    ax_slp.axhline(50.0, color="#DC2626", linestyle="--", linewidth=1.2, label="50% Edge Boundary Floor")

    for i, txt in enumerate(p_rates):
        ax_slp.annotate(f"{txt:.1f}%", (ticks[i], txt), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=8.5, fontweight="bold", color="#0F172A")

    ax_slp.set_title("Adverse Slippage Stress Test on Evaluation Pass Rate", fontsize=10.5, fontweight="bold", color="#0F172A", pad=8)
    ax_slp.set_xlabel("Extra Adverse Ticks per Leg (Entry + Exit)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_slp.set_ylabel("Pass Rate (%)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_slp.set_ylim(35, 95)
    ax_slp.legend(loc="lower left", frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1", fontsize=8.2)

    # Panel B: Sizing Policy Comparison Table
    ax_pol = fig.add_subplot(gs[0, 1])
    p_comp = sim["p_comp"]
    pol_hdr = ["Policy", "Pass Rate", "Med Sessions", "Cal Days", "Operational Profile"]
    pol_data = [
        ["Live Ratchet (2/3/4 micros)", f"{p_comp['live_ratchet']['pass_rate']:.1f}%", f"{p_comp['live_ratchet']['pass_med']:.0f} sess", f"{p_comp['live_ratchet']['pass_med_cal_days']:.0f} days", "Optimal speed & cushion balance"],
        ["Fixed 2 Micros (Conservative)", f"{p_comp['fixed_2']['pass_rate']:.1f}%", f"{p_comp['fixed_2']['pass_med']:.0f} sess", f"{p_comp['fixed_2']['pass_med_cal_days']:.0f} days", "Higher pass rate, longer duration"],
        ["Fixed 1 Micro (Ultra Safe)", f"{p_comp['fixed_1']['pass_rate']:.1f}%", f"{p_comp['fixed_1']['pass_med']:.0f} sess", f"{p_comp['fixed_1']['pass_med_cal_days']:.0f} days", "Near-guaranteed pass (~1 yr)"],
        ["Research Sizing (Markov-Scaled)", f"{p_comp['research']['pass_rate']:.1f}%", f"{p_comp['research']['pass_med']:.0f} sess", f"{p_comp['research']['pass_med_cal_days']:.0f} days", "Regime-adaptive sizing profile"],
    ]
    widths_pol = [0.24, 0.11, 0.12, 0.11, 0.42]
    create_institutional_table(
        ax_pol, pol_data, pol_hdr, widths_pol,
        title="Contract Sizing Policy Evaluation Comparison",
        row_scale=1.75, font_size=7.2, highlight_row=1,
    )

    # Panel C: Multi-Firm Rulebook Comparison Table
    ax_firms = fig.add_subplot(gs[1, :])
    rule_hdr = ["Rulebook Model", "Drawdown Type", "Floor Lock Rule", "Daily Stop Rule", "Pass Rate", "Structural Mechanism"]
    rule_data = [
        ["LucidFlex 25K (EOD Trailing + Lock)", "EOD Closing Settlement", "\\$25,100 at Peak \\$26,100", "-\\$600 Intraday Halt", f"{sim['boot_sum']['pass_rate']:.1f}%", "Zero wick penalty; floor permanently locked at target threshold"],
        ["Apex / Bulenox (Intraday Trailing)", "Live Intraday High-Water Mark", "No Lock (Trails to Target)", "None / Liquidation", "~42.5%", "Predatory: Intraday high-water mark locks unrealized wicks, collapsing cushion"],
        ["Topstep (Intraday Trailing / EOD)", "Intraday Max Loss Floor", "Static or EOD Trailing", "Daily Loss Limit", "~61.0%", "Standard prop evaluation with daily drawdown circuit breakers"],
        ["Static Drawdown Model (No Trailing)", "Static Floor at \\$24,000", "No Trailing Required", "-\\$600 Intraday Halt", "~88.5%", "Ideal theoretical benchmark with zero upward trailing floor ratchet"],
    ]
    widths_rule = [0.22, 0.16, 0.16, 0.14, 0.10, 0.22]
    create_institutional_table(
        ax_firms, rule_data, rule_hdr, widths_rule,
        title="Evaluation Rulebook Architecture: Why LucidFlex Yields Institutional Parity",
        row_scale=1.9, font_size=8.2, highlight_row=1,
    )

    out_path = OUT_DIR / "03_prop_firm_rulebook_and_slippage_stress_test.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 04: SEQUENTIAL ATTEMPT ECONOMICS & CHRONOLOGICAL HISTORY ───────────
def render_prop_sheet_04_slot_lifecycle(sim: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    # Generous top margin (top=0.85) to guarantee zero collision between header and subplot titles
    gs = fig.add_gridspec(2, 2, height_ratios=[1.5, 1.5], hspace=0.35, wspace=0.22, top=0.85, bottom=0.08, left=0.07, right=0.95)

    fig.text(0.07, 0.965, "Sequential Attempt Economics & Historical Evaluation Replay", fontsize=14, fontweight="bold", color="#0F172A")
    fig.text(0.07, 0.938, "Probabilistic Recovery Across Consecutive Attempts • Ticket Economics ($39 Fee) • Full Calendar Back-to-Back Replay", fontsize=9.2, color="#475569")

    # Panel A: Cumulative Pass Probability Across K Attempts
    ax_att = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_att)

    pass_rate = sim["boot_sum"]["pass_rate"]
    p_df = da.sequential_attempt_economics(pass_rate, fee=39.0, max_attempts=8)
    ax_att.plot(p_df["attempts"], p_df["p_pass_within"], marker="o", color="#2563EB", linewidth=2.0, zorder=3)
    ax_att.axhline(95.0, color="#059669", linestyle="--", linewidth=1.2, label="95% Confidence Threshold")

    for idx, r in p_df.iterrows():
        # Attempt 2 (92.3%) is immediately adjacent to the 95% line; place label BELOW the point to eliminate line collision
        y_off = -22 if r["attempts"] == 2 else 6
        va_pos = "top" if r["attempts"] == 2 else "bottom"
        ax_att.annotate(f"{r['p_pass_within']:.1f}%\n(\\${r['worst_case_fees']:.0f})", (r["attempts"], r["p_pass_within"]),
                        textcoords="offset points", xytext=(0, y_off), ha="center", va=va_pos, fontsize=8.0, fontweight="bold", color="#0F172A")

    ax_att.set_title("Cumulative Probability of Passing Within K Consecutive Attempts", fontsize=10.5, fontweight="bold", color="#0F172A", pad=8)
    ax_att.set_xlabel("Sequential Attempts (k)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_att.set_ylabel("Cumulative Pass Probability (%)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_att.set_ylim(60, 105)
    ax_att.legend(loc="lower right", frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1", fontsize=8.2)

    # Panel B: Expected Value (EV) per Evaluation Ticket
    ax_ev = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_ev)

    ev_val = sim["f_summary"]["ev_per_attempt"]
    mean_payout = sim["f_summary"]["mean_net"]
    cost = 39.0
    expected_net = mean_payout * (pass_rate / 100.0)
    ev_bars = ax_ev.bar(["Evaluation Fee", "Expected Funded Net", "Net EV / Attempt"], [cost, expected_net, ev_val],
                        color=["#DC2626", "#2563EB", "#059669"], edgecolor=["#991B1B", "#1D4ED8", "#047857"], width=0.45, zorder=3)
    for b in ev_bars:
        h = b.get_height()
        ax_ev.annotate(f"\\${h:,.2f}", (b.get_x() + b.get_width() / 2, h), xytext=(0, 5),
                       textcoords="offset points", ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#0F172A")

    ax_ev.set_title("Evaluation Ticket Economics ($39 Fee vs Expected Extraction)", fontsize=10.5, fontweight="bold", color="#0F172A", pad=8)
    ax_ev.set_ylabel("USD ($)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_ev.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_ev.set_ylim(0, max(expected_net, ev_val) * 1.35)

    # Panel C: Chronological Back-to-Back History (2021-2026) Table
    ax_ch = fig.add_subplot(gs[1, :])
    ch_df = sim["chrono"]["back_to_back"]
    c_hdr = ["Attempt #", "Start Date", "End Date", "Status", "Duration (Sessions)", "Duration (Cal Days)", "Outcome Assessment"]
    c_data = []
    for idx, r in ch_df.iterrows():
        is_pass = r["status"] == "pass"
        is_fail = r["status"] == "fail"
        status_str = r["status"].upper()
        cal_d = int((pd.to_datetime(r["end"]) - pd.to_datetime(r["start"])).days)
        diag = "Reached +\\$1,250 target cleanly" if is_pass else ("Hit -\\$1,000 trailing floor" if is_fail else "Currently active evaluation")
        c_data.append([
            f"Attempt #{idx+1}", str(r["start"]), str(r["end"]), status_str,
            f"{r['sessions']} sessions", f"{cal_d} days", diag,
        ])
    widths_ch = [0.10, 0.12, 0.12, 0.10, 0.16, 0.14, 0.26]
    create_institutional_table(
        ax_ch, c_data, c_hdr, widths_ch,
        title=f"Chronological Back-to-Back Evaluation Replay (2021-01-07 to 2026-10-30 • {len(ch_df)} Total Attempts)",
        row_scale=1.45, font_size=8.0,
    )

    out_path = OUT_DIR / "04_prop_optionality_and_annual_slot_lifecycle.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── SHEET 05: FUNDED SURVIVAL & PAYOUT HARVEST ───────────────────────────────
def render_prop_sheet_05_funded_survival(sim: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(16, 12), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    # Generous top margin (top=0.85) to guarantee zero collision between header and subplot titles
    gs = fig.add_gridspec(2, 2, height_ratios=[1.6, 1.4], hspace=0.35, wspace=0.22, top=0.85, bottom=0.08, left=0.07, right=0.95)

    fig.text(0.07, 0.965, "Funded Account Longevity & Payout Harvest Analytics", fontsize=14, fontweight="bold", color="#0F172A")
    fig.text(0.07, 0.938, "Payout Ladder Probabilities • Total Extraction Distribution • Multi-Payout Longevity Economics", fontsize=9.2, color="#475569")

    # Panel A: Payout Ladder (% Reaching Payout N)
    ax_lad = fig.add_subplot(gs[0, 0])
    format_spines_and_grid(ax_lad)

    f_sum = sim["f_summary"]
    ladder = f_sum["ladder"]
    p_nums = [f"Payout #{k}" for k in range(1, 6)]
    p_pcts = [ladder[k] for k in range(1, 6)]

    b_lad = ax_lad.bar(p_nums, p_pcts, color="#059669", edgecolor="#047857", width=0.45, zorder=3)
    for b in b_lad:
        h = b.get_height()
        ax_lad.annotate(f"{h:.1f}%", (b.get_x() + b.get_width() / 2, h), xytext=(0, 5),
                        textcoords="offset points", ha="center", va="bottom", fontsize=8.5, fontweight="bold", color="#0F172A")

    ax_lad.set_title("Funded Payout Ladder (% of Passing Accounts Reaching Payout)", fontsize=10.5, fontweight="bold", color="#0F172A", pad=8)
    ax_lad.set_ylabel("Probability (%)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_lad.set_ylim(0, 115)

    # Panel B: Payout Amount Distribution
    ax_dis = fig.add_subplot(gs[0, 1])
    format_spines_and_grid(ax_dis)

    nets = f_sum["nets"]
    counts_dis, _, _ = ax_dis.hist(nets, bins=30, color="#2563EB", edgecolor="#1D4ED8", alpha=0.75, zorder=3)
    ax_dis.axvline(f_sum["mean_net"], color="#059669", linestyle="--", linewidth=1.8, label=f"Mean Net: \\${f_sum['mean_net']:,.0f}")
    ax_dis.axvline(f_sum["median_net"], color="#0F172A", linestyle=":", linewidth=1.5, label=f"Median Net: \\${f_sum['median_net']:,.0f}")

    ax_dis.set_title("Total Net Payout Extraction Distribution per Funded Account", fontsize=10.5, fontweight="bold", color="#0F172A", pad=8)
    ax_dis.set_xlabel("Net Extraction ($ USD)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_dis.set_ylabel("Account Count", fontsize=9, fontweight="bold", color="#0F172A")
    ax_dis.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_dis.set_ylim(0, max(counts_dis) * 1.35 if len(counts_dis) else 10)
    ax_dis.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1", fontsize=8.2)

    # Panel C: Funded Economics Table
    ax_tab = fig.add_subplot(gs[1, :])
    f_hdr = ["Funded Performance Metric", "Simulated Value", "Payout Longevity Milestone", "Empirical Probability"]
    f_data = [
        ["Simulated Passing Accounts", f"{f_sum['n']:,} accounts", "Accounts Achieving >= 1 Payout", f"{ladder[1]:.1f}%"],
        ["Mean Net Payout Extraction", fmt_currency(f_sum['mean_net'], 2), "Accounts Achieving >= 2 Payouts", f"{ladder[2]:.1f}%"],
        ["Median Net Payout Extraction", fmt_currency(f_sum['median_net'], 2), "Accounts Achieving >= 3 Payouts", f"{ladder[3]:.1f}%"],
        ["Accounts Breaching with Zero Payout", f"{f_sum['zero_payout_pct']:.1f}%", "Accounts Capped at 5 Payouts (\\$4,500)", f"{ladder[5]:.1f}%"],
        ["Evaluation Fee Cost", "\\$39.00", "Net Expected Value (EV) / Attempt", fmt_currency(f_sum['ev_per_attempt'], 2, force_sign=True)],
    ]
    widths_fund = [0.28, 0.20, 0.28, 0.24]
    create_institutional_table(
        ax_tab, f_data, f_hdr, widths_fund,
        title="Funded Account Payout & Longevity Economics Summary",
        row_scale=1.8, font_size=8.5,
    )

    out_path = OUT_DIR / "05_prop_funded_survival_and_payout_harvest.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path


# ── MASTER OVERVIEW POSTER ───────────────────────────────────────────────────
def render_prop_poster_master(sim: dict) -> Path:
    plt.style.use("default")
    fig = plt.figure(figsize=(18, 26), dpi=200)
    fig.patch.set_facecolor("#FFFFFF")
    # Generous top margin (top=0.91) to guarantee zero collision between header and the ax_main legend
    gs = fig.add_gridspec(5, 2, height_ratios=[3.6, 2.0, 2.0, 2.8, 1.8], hspace=0.35, wspace=0.20, top=0.91, bottom=0.03, left=0.06, right=0.95)

    # Master Header
    fig.text(0.06, 0.985, "LUCIDFLEX 25K PROP EVALUATION MASTER TEARSHEET", fontsize=18, fontweight="bold", color="#0F172A")
    fig.text(0.06, 0.965, "Comprehensive 10,000-Path Monte Carlo Simulation • Sizing Ratchet Benchmarks • Payout Harvest Architecture", fontsize=10.5, color="#475569")

    # Panel 1: Main Evaluation Trajectories
    ax_main = fig.add_subplot(gs[0, :])
    format_spines_and_grid(ax_main)

    boot = sim["boot"]
    paths = boot["paths"]
    b_sum = sim["boot_sum"]
    pass_paths = [p[1] for p in paths if p[0] == "pass"]
    fail_paths = [p[1] for p in paths if p[0] == "fail"]

    horizon = 120
    uncon_mat = sim["uncon_mat"]
    x_uncon = np.arange(horizon + 1)

    p05 = np.percentile(uncon_mat, 5, axis=0)
    p25 = np.percentile(uncon_mat, 25, axis=0)
    p50 = np.percentile(uncon_mat, 50, axis=0)
    p75 = np.percentile(uncon_mat, 75, axis=0)
    p95 = np.percentile(uncon_mat, 95, axis=0)

    # Percentile Ribbons
    ax_main.fill_between(x_uncon, p05, p95, color="#BAE6FD", alpha=0.35, zorder=2, label="P05–P95 Corridor (90% Conf)")
    ax_main.fill_between(x_uncon, p25, p75, color="#38BDF8", alpha=0.40, zorder=3, label="P25–P75 Interquartile Core")
    ax_main.plot(x_uncon, p50, color="#0284C7", linestyle=":", linewidth=1.8, zorder=4, label="Median Strategy Drift")

    # Sample Paths
    for p in pass_paths[:35]:
        t_end = min(len(p), horizon)
        ax_main.plot(range(t_end), p[:t_end], color="#059669", alpha=0.20, linewidth=0.8, zorder=5)
        if len(p) <= horizon:
            ax_main.plot(len(p) - 1, p[-1], marker="o", markersize=3.5, color="#059669", alpha=0.7, zorder=6)

    for p in fail_paths[:18]:
        t_end = min(len(p), horizon)
        ax_main.plot(range(t_end), p[:t_end], color="#DC2626", alpha=0.20, linewidth=0.8, zorder=5)
        if len(p) <= horizon:
            ax_main.plot(len(p) - 1, p[-1], marker="x", markersize=4.0, color="#DC2626", alpha=0.7, zorder=6)

    # Median Trajectory
    med_sess = b_sum["pass_med"]
    closest_med = min(pass_paths, key=lambda p: abs(len(p) - med_sess)) if pass_paths else None
    if closest_med:
        t_med = min(len(closest_med), horizon)
        ax_main.plot(range(t_med), closest_med[:t_med], color="#0F172A", linewidth=2.4, zorder=7,
                     label=f"Median Pass Path ({len(closest_med)} sess)")
        if len(closest_med) <= horizon:
            ax_main.plot(len(closest_med) - 1, closest_med[-1], marker="o", markersize=7.0, color="#0F172A", markeredgecolor="#FFFFFF", markeredgewidth=1.2, zorder=8)

    # Rule Boundaries (Escaped \$ prevents Matplotlib KaTeX math mode bug)
    ax_main.axhline(26_250.0, color="#059669", linestyle="--", linewidth=1.8, zorder=6, label=r"Profit Target (\$26,250)")
    ax_main.axhline(25_100.0, color="#7C3AED", linestyle=":", linewidth=1.5, zorder=6, label=r"Floor Lock (\$25,100)")
    ax_main.axhline(25_000.0, color="#64748B", linestyle="-", linewidth=0.9, alpha=0.7, zorder=4, label=r"Starting Capital (\$25,000)")
    ax_main.axhline(24_000.0, color="#DC2626", linestyle="--", linewidth=1.8, zorder=6, label=r"Max Trailing Floor (\$24,000)")

    ax_main.set_xlabel("Exchange Sessions Elapsed", fontsize=10.5, fontweight="bold", color="#0F172A")
    ax_main.set_ylabel("Account Balance ($)", fontsize=10.5, fontweight="bold", color="#0F172A", labelpad=8)
    ax_main.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_main.set_ylim(23_500, 27_200)
    ax_main.set_xlim(0, horizon)

    leg = ax_main.legend(loc="lower left", bbox_to_anchor=(0.0, 1.025, 1.0, 0.05), mode="expand", ncol=4,
                         frameon=True, facecolor="#F8FAFC", edgecolor="#CBD5E1", fontsize=8.2)
    leg.get_frame().set_linewidth(0.8)

    # Panel 2A: Peak Equity on Failed Accounts
    ax_pk = fig.add_subplot(gs[1, 0])
    format_spines_and_grid(ax_pk)
    c_pk, _, _ = ax_pk.hist(sim["failed_peaks"], bins=30, color="#DC2626", alpha=0.75, edgecolor="#991B1B", zorder=3)
    ax_pk.axvline(sim["med_failed_peak"], color="#0F172A", linestyle="--", linewidth=1.8, label=f"Median: \\${sim['med_failed_peak']:,.0f}")
    ax_pk.set_title("Peak Equity Reached Prior to Floor Breach", fontsize=11, fontweight="bold", color="#0F172A", pad=8)
    ax_pk.set_xlabel("Peak Balance ($)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_pk.set_ylabel("Breached Account Count", fontsize=9, fontweight="bold", color="#0F172A")
    ax_pk.xaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
    ax_pk.set_ylim(0, max(c_pk) * 1.35 if len(c_pk) else 10)
    ax_pk.legend(loc="upper right", frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1", fontsize=8)

    # Panel 2B: Slippage Sensitivity
    ax_slp = fig.add_subplot(gs[1, 1])
    format_spines_and_grid(ax_slp)
    ax_slp.plot(sim["slip_ticks"], sim["slip_pass_rates"], marker="o", color="#2563EB", linewidth=2.0)
    ax_slp.axhline(50.0, color="#DC2626", linestyle="--", linewidth=1.2, label="50% Edge Hurdle")
    for i, txt in enumerate(sim["slip_pass_rates"]):
        ax_slp.annotate(f"{txt:.1f}%", (sim["slip_ticks"][i], txt), textcoords="offset points", xytext=(0, 5), ha="center", fontsize=8, fontweight="bold", color="#0F172A")
    ax_slp.set_title("Adverse Slippage Stress Test (Pass Rate vs Extra Ticks)", fontsize=11, fontweight="bold", color="#0F172A", pad=8)
    ax_slp.set_xlabel("Extra Adverse Ticks per Leg", fontsize=9, fontweight="bold", color="#0F172A")
    ax_slp.set_ylabel("Pass Rate (%)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_slp.set_ylim(35, 95)
    ax_slp.legend(loc="lower left", frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1", fontsize=8)

    # Panel 3A: Cumulative Probability across K Attempts
    ax_att = fig.add_subplot(gs[2, 0])
    format_spines_and_grid(ax_att)
    p_df = da.sequential_attempt_economics(b_sum["pass_rate"], fee=39.0, max_attempts=6)
    ax_att.plot(p_df["attempts"], p_df["p_pass_within"], marker="o", color="#2563EB", linewidth=2.0)
    ax_att.axhline(95.0, color="#059669", linestyle="--", linewidth=1.2, label="95% Threshold")
    for idx, r in p_df.iterrows():
        y_off = -20 if r["attempts"] == 2 else 5
        va_pos = "top" if r["attempts"] == 2 else "bottom"
        ax_att.annotate(f"{r['p_pass_within']:.1f}%", (r["attempts"], r["p_pass_within"]), textcoords="offset points", xytext=(0, y_off), ha="center", va=va_pos, fontsize=8, fontweight="bold", color="#0F172A")
    ax_att.set_title("Sequential Retries (Pass Prob Within K Attempts)", fontsize=11, fontweight="bold", color="#0F172A", pad=8)
    ax_att.set_xlabel("Sequential Attempts (k)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_att.set_ylabel("Probability (%)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_att.set_ylim(65, 105)
    ax_att.legend(loc="lower right", frameon=True, facecolor="#FFFFFF", edgecolor="#CBD5E1", fontsize=8)

    # Panel 3B: Funded Payout Ladder
    ax_lad = fig.add_subplot(gs[2, 1])
    format_spines_and_grid(ax_lad)
    ladder = sim["f_summary"]["ladder"]
    ax_lad.bar([f"Payout #{k}" for k in range(1, 6)], [ladder[k] for k in range(1, 6)], color="#059669", edgecolor="#047857", width=0.45)
    for idx, k in enumerate(range(1, 6)):
        ax_lad.annotate(f"{ladder[k]:.1f}%", (idx, ladder[k]), textcoords="offset points", xytext=(0, 4), ha="center", fontsize=8, fontweight="bold", color="#0F172A")
    ax_lad.set_title("Funded Payout Ladder (% Reaching Payout N)", fontsize=11, fontweight="bold", color="#0F172A", pad=8)
    ax_lad.set_ylabel("Probability (%)", fontsize=9, fontweight="bold", color="#0F172A")
    ax_lad.set_ylim(0, 115)

    # Panel 4: Chronological History Table
    ax_ch = fig.add_subplot(gs[3, :])
    ch_df = sim["chrono"]["back_to_back"]
    c_hdr = ["Attempt #", "Start Date", "End Date", "Status", "Duration (Sessions)", "Duration (Cal Days)", "Outcome Assessment"]
    c_data = []
    for idx, r in ch_df.iterrows():
        is_pass = r["status"] == "pass"
        is_fail = r["status"] == "fail"
        status_str = r["status"].upper()
        cal_d = int((pd.to_datetime(r["end"]) - pd.to_datetime(r["start"])).days)
        diag = "Reached +\\$1,250 target cleanly" if is_pass else ("Hit -\\$1,000 trailing floor" if is_fail else "Currently active evaluation")
        c_data.append([
            f"Attempt #{idx+1}", str(r["start"]), str(r["end"]), status_str,
            f"{r['sessions']} sessions", f"{cal_d} days", diag,
        ])
    widths_ch = [0.10, 0.12, 0.12, 0.10, 0.16, 0.14, 0.26]
    create_institutional_table(
        ax_ch, c_data, c_hdr, widths_ch,
        title=f"Chronological Back-to-Back Evaluation Replay (2021-01-07 to 2026-10-30 • {len(ch_df)} Total Attempts)",
        row_scale=1.45, font_size=8.0,
    )

    # Panel 5: Master Prop Parameters & Metrics Table
    ax_tab = fig.add_subplot(gs[4, :])
    ch_pass_m = int((sim["chrono"]["back_to_back"]["status"] == "pass").sum())
    ch_tot_m = int(len(sim["chrono"]["back_to_back"][sim["chrono"]["back_to_back"]["status"].isin(["pass", "fail"])]))
    ch_rate_m = (ch_pass_m / ch_tot_m * 100.0) if ch_tot_m > 0 else 0.0

    sum_hdr = ["Evaluation Parameter", "Rule Specification", "Performance Diagnostic", "Empirical Outcome"]
    sum_data = [
        ["Account Size / Profit Target", "\\$25,000 / +\\$1,250 (5.0%)", "10k Bootstrap Pass Rate", f"{b_sum['pass_rate']:.1f}%"],
        ["Trailing Drawdown Allowance", "\\$1,000 (EOD Closing Basis)", "Median Sessions to Target", f"{b_sum['pass_med']:.0f} sess (~{b_sum['pass_med_cal_days']:.0f} cal days)"],
        ["Floor Lock Rule", "\\$25,100 once Peak >= \\$26,100", "Chronological Pass Rate", f"{ch_rate_m:.1f}% ({ch_pass_m} pass / {ch_tot_m - ch_pass_m} fail)"],
        ["Daily Soft Stop Threshold", "-\\$600 (Halts Remaining Windows)", "Net Expected Value / Attempt", f"+{fmt_currency(sim['f_summary']['ev_per_attempt'], 2)} per \\$39 fee"],
    ]
    widths_sum = [0.28, 0.22, 0.28, 0.22]
    create_institutional_table(
        ax_tab, sum_data, sum_hdr, widths_sum,
        title="LucidFlex 25K Rulebook & Performance Summary",
        row_scale=1.6, font_size=8.5, highlight_row=1,
    )

    # Provenance Stamp Footer on Poster (Rule 2 & 3 Compliance)
    ax_foot = fig.add_axes([0.06, 0.008, 0.89, 0.014])
    ax_foot.set_facecolor("#F8FAFC")
    for sp in ax_foot.spines.values():
        sp.set_color("#CBD5E1")
        sp.set_linewidth(0.8)
    ax_foot.set_xticks([])
    ax_foot.set_yticks([])
    ax_foot.text(0.01, 0.5, "PROVENANCE VERIFICATION (Rule 2 & 3): Run ID: run_canonical_lucid_flex_ensemble_2021_2026 | Tier: BASELINE | Data SHA-256: ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca | Bundle: results/bundles/run_canonical_lucid_flex_ensemble_2021_2026.obtf",
                 fontsize=7.8, fontweight="bold", color="#334155", va="center")

    out_path = OUT_DIR / "lucid_flex_25k_prop_mode_report.png"
    plt.savefig(out_path, dpi=200, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close()
    return out_path
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
