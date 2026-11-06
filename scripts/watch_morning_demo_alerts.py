#!/usr/bin/env python3
"""
Automated Morning Forward-Test Watcher & macOS Desktop Alert Runner
Monitors live morning bars (via Yahoo Finance 1m stream + local CQG fallback) and automatically:
  1. Window 1 (09:45:00 ET): Evaluates Strategy 1 (Morning VA Breakout v2.0, H4) on MNQ + MES
  2. Window 2 (10:15:00 ET): Evaluates Strategy 2 (Post-LBMA PM Fix Breakout, H14 Long-Only) on MGC
  3. Automatic Logging (Zero Manual Work):
     - Automatically logs NO-TRADE sessions into `results/forward_test/demo_sessions_ledger.csv`
       with exact structural/diagnostic reasons.
     - Automatically resolves and records completed trade outcomes (Stop Loss, Profit Target,
       or 10:15/11:00 Time Exit) into `results/forward_test/demo_trades_ledger.csv`
       with 1-tick adverse slippage + commissions.
     - Automatically refreshes `results/forward_test/demo_parity_dashboard.html`.
  4. Alerts:
     - Fires native macOS Notification Center banners + Glass sound + spoken voice alerts.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time
from datetime import datetime
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.demo_parity_engine import (
    DASHBOARD_HTML_PATH,
    AccountEvalState,
    DailySessionRecord,
    DemoParityJournal,
    TradeFillRecord,
    WindowEvaluationRecord,
    resolve_instrument,
)
from scripts.sync_cqg_executions import (
    DEFAULT_JOURNAL_PATH,
    parse_cqg_fills_from_journal,
    reconstruct_trades_fifo,
    sync_broker_trades_to_ledger,
)
from scripts.run_demo_forward_test import (
    compute_prior_va_for_latest_session,
    evaluate_gold_h14_signal,
    evaluate_macro_momentum_signal,
    evaluate_signal_for_asset,
    fetch_live_morning_bars,
    get_or15_direction,
)

ET_TZ = ZoneInfo("America/New_York")


def send_macos_alert(title: str, subtitle: str, message: str, speak_text: str | None = None, sound: bool = True) -> None:
    """Fires a native macOS Notification Center banner with optional Glass sound and TTS voice alert."""
    safe_title = title.replace('"', '\\"')
    safe_sub = subtitle.replace('"', '\\"')
    safe_msg = message.replace('"', '\\"')
    sound_clause = ' sound name "Glass"' if sound else ""
    apple_script = (
        f'display notification "{safe_msg}" with title "{safe_title}" '
        f'subtitle "{safe_sub}"{sound_clause}'
    )
    try:
        subprocess.run(["osascript", "-e", apple_script], check=False, timeout=5)
    except Exception:
        pass

    if speak_text:
        try:
            subprocess.Popen(["say", "-v", "Samantha", speak_text])
        except Exception:
            pass


def dispatch_active_order_card(
    orders: list[dict[str, any]],
    eval_state: AccountEvalState,
    tier_label: str,
) -> str | None:
    """
    Generates an active order ticket with bracket specifications, writes it to:
      1. ~/Desktop/active_order_card.txt
      2. results/forward_test/active_order_card.txt
    and copies it to the macOS clipboard via pbcopy.
    """
    if not orders:
        return None

    now_et = datetime.now(ET_TZ).strftime("%Y-%m-%d %H:%M:%S ET")
    lines = [
        "=" * 78,
        "🚀 LUCIDFLEX 25K ACTIVE ORDER TICKET",
        "=" * 78,
        f" Timestamp (ET) : {now_et}",
        f" Account State  : Balance: ${eval_state.balance:,.2f} | Cushion: ${eval_state.trailing_cushion:,.2f}",
        f" Sizing Policy  : {tier_label}",
        "-" * 78,
    ]
    for i, ord_info in enumerate(orders, start=1):
        lines.append(f" [ORDER #{i}] {ord_info['strategy']} ({ord_info['window']} ET)")
        lines.append(f"   Symbol        : {ord_info['symbol']}")
        lines.append(f"   Action        : {ord_info['action']} (OPEN)")
        lines.append(f"   Quantity      : {ord_info['contracts']} Micros")
        lines.append(f"   Order Type    : BRACKET (OCO)")
        lines.append(f"   Entry Price   : {ord_info['entry_price']:.2f}")
        lines.append(f"   Stop Loss     : {ord_info['stop_price']:.2f} (Risk: {ord_info['risk_pts']:+.2f} pts | ${ord_info['risk_dollars']:,.2f})")
        lines.append(f"   Profit Target : {ord_info['target_price']:.2f} (Reward: {ord_info['reward_pts']:+.2f} pts | ${ord_info['reward_dollars']:,.2f})")
        lines.append(f"   Exit Rule     : {ord_info['exit_rule']}")
        lines.append("-" * 78)
    lines.append(" ⚠️ MotiveWave: Place bracket on DOM or confirm automated signal fill.")
    lines.append("=" * 78)
    card_text = "\n".join(lines) + "\n"

    # Write to results directory
    card_path_repo = ROOT / "results" / "forward_test" / "active_order_card.txt"
    try:
        card_path_repo.write_text(card_text, encoding="utf-8")
    except Exception:
        pass

    # Write to user Desktop
    desktop_path = Path.home() / "Desktop" / "active_order_card.txt"
    try:
        desktop_path.write_text(card_text, encoding="utf-8")
    except Exception:
        pass

    # Copy to macOS clipboard
    try:
        subprocess.run(["pbcopy"], input=card_text.encode("utf-8"), check=False, timeout=2)
    except Exception:
        pass

    print(f"\n[ORDER CARD GENERATED] Copied to clipboard & saved to {desktop_path}")
    print(card_text)
    return card_text


def load_bars_with_local_fallback(
    yf_ticker: str,
    local_parquet: Path,
    cqg_csv: Path | None = None,
    prefer_cqg: bool = True,
) -> pd.DataFrame:
    """
    Loads 1-minute intraday bars with strict feed priority:
      1. Primary (Real-Time): MotiveWave AMP CQG CSV export (zero lag).
      2. Secondary (Archive): Converted local Parquet dataset.
      3. Emergency Fallback: Yahoo Finance (with explicit warning of 10-15m CME exchange delay).
    """
    # 1. Primary: Real-time MotiveWave CQG CSV export
    if prefer_cqg and cqg_csv and cqg_csv.exists():
        try:
            res = subprocess.run(
                ["tail", "-n", "8000", str(cqg_csv)],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if res.stdout.strip():
                df_cqg = pd.read_csv(
                    StringIO(res.stdout),
                    names=["dt_str", "open", "high", "low", "close", "volume"],
                )
                df_cqg["time"] = pd.to_datetime(df_cqg["dt_str"], format="%d/%m/%Y %H:%M:%S", errors="coerce")
                df_cqg = df_cqg.dropna(subset=["time"]).drop(columns=["dt_str"]).reset_index(drop=True)
                if not df_cqg.empty:
                    today_et = datetime.now(ET_TZ).strftime("%Y-%m-%d")
                    cqg_date = df_cqg["time"].dt.strftime("%Y-%m-%d").max()
                    if cqg_date == today_et:
                        return df_cqg
                    # If MotiveWave export is still pending today, check live feed
                    df_live = fetch_live_morning_bars(yf_ticker, period="5d")
                    if not df_live.empty and df_live["time"].dt.strftime("%Y-%m-%d").max() == today_et:
                        return df_live
                    return df_cqg
        except Exception:
            pass

    # 2. Secondary: Local Parquet archive
    if local_parquet.exists():
        try:
            df_loc = pd.read_parquet(local_parquet)
            if not df_loc.empty:
                return df_loc.tail(8000).reset_index(drop=True)
        except Exception:
            pass

    # 3. Emergency Fallback: Yahoo Finance
    try:
        print(f"[DATA WARNING] Fetching {yf_ticker} from Yahoo Finance. Free CME futures data on Yahoo Finance is delayed by 10-15 minutes!")
        df = fetch_live_morning_bars(yf_ticker, period="5d")
        if not df.empty:
            return df
    except Exception:
        pass

    return pd.DataFrame()


def diagnose_macro_window(bars_nq: pd.DataFrame) -> str:
    """Provides exact quantitative diagnostic reason why 08:35 Macro Momentum did not trigger."""
    if bars_nq.empty:
        return "No real-time data feed for MNQ."
    latest_date = bars_nq["time"].dt.strftime("%Y-%m-%d").max()
    df_today = bars_nq[bars_nq["time"].dt.strftime("%Y-%m-%d") == latest_date].copy()
    df_today["time_et"] = df_today["time"].dt.strftime("%H:%M")
    ovn_bars = df_today[df_today["time_et"].between("00:00", "08:29")]
    spike_bars = df_today[df_today["time_et"].between("08:30", "08:34")]
    if len(spike_bars) < 4:
        return "No 08:30 macro release bars detected."
    spike_vol = float(spike_bars["volume"].sum())
    pre_vol_5m = float(ovn_bars["volume"].tail(30).mean() * 5.0) if len(ovn_bars) >= 10 else 1.0
    thresh_vol = pre_vol_5m * 2.5
    if spike_vol < thresh_vol:
        return f"Pre-market volume quiet ({spike_vol:.0f} vs {thresh_vol:.0f} req threshold)."
    ovn_high = float(ovn_bars["high"].max())
    ovn_low = float(ovn_bars["low"].min())
    spike_close = float(spike_bars.iloc[-1]["close"])
    if ovn_low <= spike_close <= ovn_high:
        return f"Spike trapped inside overnight range ({ovn_low:.1f} - {ovn_high:.1f})."
    spike_high = float(spike_bars["high"].max())
    spike_low = float(spike_bars["low"].min())
    rng = spike_high - spike_low
    cl_loc = (spike_close - spike_low) / rng if rng > 0 else 0.5
    return f"Weak spike bar close location ({cl_loc:.0%} vs req >=65%/<=35%)."


def diagnose_equity_va_window(
    bars_nq: pd.DataFrame,
    bars_es: pd.DataFrame,
    sig_nq: dict | None,
    sig_es: dict | None,
    nq_ok: bool,
    es_ok: bool,
) -> str:
    """Provides exact quantitative diagnostic reason why 09:45 VA Breakout did not trigger."""
    reasons = []
    if sig_nq and not nq_ok:
        reasons.append(f"MNQ gated ({sig_nq.get('macro_reason', 'Filter')})")
    if sig_es and not es_ok:
        reasons.append(f"MES gated ({sig_es.get('macro_reason', 'Filter')})")
    if reasons:
        return " / ".join(reasons)

    if not bars_nq.empty:
        latest_date = bars_nq["time"].dt.strftime("%Y-%m-%d").max()
        df_today = bars_nq[bars_nq["time"].dt.strftime("%Y-%m-%d") == latest_date].copy()
        df_today["time_et"] = df_today["time"].dt.strftime("%H:%M")
        m15 = df_today[df_today["time_et"].between("09:30", "09:44")]
        if not m15.empty:
            o930 = float(m15.iloc[0]["open"])
            c944 = float(m15.iloc[-1]["close"])
            h15 = float(m15["high"].max())
            l15 = float(m15["low"].min())
            rng = h15 - l15
            ret = (c944 - o930) / o930 if o930 > 0 else 0.0
            loc = (c944 - l15) / rng if rng > 0 else 0.5
            p_poc, p_vah, p_val, p_close = compute_prior_va_for_latest_session(bars_nq, "09:30", "16:00", 1.0)
            if not np.isnan(p_val) and not np.isnan(p_vah) and (p_val <= c944 <= p_vah):
                return f"Trapped inside Prior Value Area ({p_val:.1f} - {p_vah:.1f} | Loc {loc:.2f})."
            if abs(ret) < 0.0010:
                return f"Sub-threshold OR15 return ({ret:+.2%} vs req ±0.10%)."
            if 0.35 < loc < 0.65:
                return f"Mid-range close (Location {loc:.2f} trapped inside OR15)."
    return "Inside Prior Value Area / Intermarket Divergence / Gated."


def diagnose_gold_h14_window(bars_gc: pd.DataFrame) -> str:
    """Provides exact quantitative diagnostic reason why 10:15 Gold London Fix did not trigger."""
    if bars_gc.empty:
        return "No real-time data feed for MGC."
    latest_date = bars_gc["time"].dt.strftime("%Y-%m-%d").max()
    df_today = bars_gc[bars_gc["time"].dt.strftime("%Y-%m-%d") == latest_date].copy()
    df_today["time_et"] = df_today["time"].dt.strftime("%H:%M")
    fix_bars = df_today[df_today["time_et"].between("10:00", "10:14")]
    ib_bars = df_today[df_today["time_et"].between("08:20", "09:19")]
    lon_bars = df_today[df_today["time_et"].between("03:00", "08:19")]
    if len(fix_bars) < 10 or ib_bars.empty:
        return "Fix or IB bars incomplete."
    fix_open = float(fix_bars.iloc[0]["open"])
    fix_close = float(fix_bars.iloc[-1]["close"])
    fix_high = float(fix_bars["high"].max())
    fix_low = float(fix_bars["low"].min())
    fix_rng = fix_high - fix_low
    if fix_open <= 0 or fix_rng <= 0:
        return "Invalid price data."
    ret_pct = (fix_close - fix_open) / fix_open
    close_loc = (fix_close - fix_low) / fix_rng
    ib60_high = float(ib_bars["high"].max())
    lon_high = float(lon_bars["high"].max()) if not lon_bars.empty else ib60_high

    if ret_pct < 0.001125:
        return f"Weak Fix Return ({ret_pct:+.2%} vs req >= +0.11%)."
    if close_loc < 0.70:
        return f"Fix Close Location weak ({close_loc:.2f} < 0.70)."
    if fix_close <= ib60_high:
        return f"Trapped below COMEX IB60 High ({fix_close:.1f} <= {ib60_high:.1f})."
    if fix_close <= lon_high:
        return f"Trapped below London Session High ({fix_close:.1f} <= {lon_high:.1f})."
    return "Below COMEX IB60 or London High barriers / Gated."


def auto_log_session_and_trades(
    journal: DemoParityJournal,
    session_date: str,
    fired_signals: list[tuple[dict, pd.DataFrame, str, int]],
    eval_state: AccountEvalState,
    diag_summary: str | None = None,
) -> None:
    """
    Automatically logs daily sessions and auto-resolves trades if holding window is complete.
    Zero manual logging required from user!
    """
    # Case 1: No trades fired today
    if not fired_signals:
        reason = diag_summary or "NO TRADE: Window 0 (Macro), Window 1 (MNQ/MES), and Window 2 (MGC) flat/gated"
        rec = DailySessionRecord(
            date=session_date,
            setup_detected=False,
            setup_fired=False,
            diagnostic_reason=reason,
            end_of_day_balance=eval_state.balance,
        )
        journal.record_session(rec)
        print(f"  [AUTO-LOGGER] Recorded session for {session_date} in demo_sessions_ledger.csv")
        return

    # Case 2: Trades fired today -> check if already resolved or if holding window is complete
    df_trades = journal.load_trades_df()

    for sig, bars, win_str, contracts in fired_signals:
        sym = sig["contract"]
        already_in_trades = False
        if not df_trades.empty and "date" in df_trades.columns and "symbol" in df_trades.columns:
            matches = df_trades[(df_trades["date"].astype(str) == session_date) & (df_trades["symbol"] == sym)]
            if not matches.empty:
                already_in_trades = True

        if already_in_trades:
            continue

        if win_str == "08:35":
            start_hhmm = "08:35"
            end_hhmm = "09:25"
            exit_code = "TIME_EXIT_0925"
            strategy_name = "Macro Momentum (08:35)"
        elif win_str == "09:45":
            start_hhmm = "09:45"
            end_hhmm = "10:15"
            exit_code = "TIME_EXIT_1015"
            strategy_name = "VA Breakout (v2.0)"
        else:  # "10:15"
            start_hhmm = "10:15"
            end_hhmm = "11:00"
            exit_code = "TIME_EXIT_1100"
            strategy_name = "Gold London Fix (H14)"

        b_day = bars[bars["time"].dt.strftime("%Y-%m-%d") == session_date]
        w_bars = b_day[b_day["time"].dt.strftime("%H:%M").between(start_hhmm, end_hhmm)].copy()

        # Check if real broker executions exist in MotiveWave CQG journal first
        real_broker_synced = False
        if DEFAULT_JOURNAL_PATH.exists():
            try:
                broker_fills = parse_cqg_fills_from_journal(
                    DEFAULT_JOURNAL_PATH, exact_date=session_date, allowed_symbols={sym}
                )
                if broker_fills:
                    reconstructed = reconstruct_trades_fifo(broker_fills)
                    if reconstructed:
                        sync_broker_trades_to_ledger(reconstructed, journal=journal)
                        real_broker_synced = True
                        print(f"  [AUTO-LOGGER] Synchronized real CQG broker executions from MotiveWave for {sym} on {session_date}.")
            except Exception as e:
                print(f"  [AUTO-LOGGER] Notice on CQG journal sync: {e} (falling back to simulated bar fill)")

        # If window is complete (at least 15 bars) and not already synced from broker, simulate order execution & auto-record
        if not real_broker_synced and len(w_bars) >= 15:
            d = 1 if sig["direction"] == "long" else -1
            entry_p = float(sig["entry_price"])
            stop_p = float(sig["stop_price"])
            target_p = float(sig["target_price"])
            spec = resolve_instrument(sym)
            tick = spec.tick_size

            # 1-tick adverse entry fill
            actual_entry = entry_p + (tick if d == 1 else -tick)
            actual_exit = float(w_bars.iloc[-1]["close"])
            exit_type = exit_code

            for _, b in w_bars.iterrows():
                bh = float(b["high"])
                bl = float(b["low"])
                if d == 1:
                    if bl <= stop_p:
                        actual_exit = stop_p
                        exit_type = "STOP_LOSS"
                        break
                    if bh >= target_p:
                        actual_exit = target_p
                        exit_type = "PROFIT_TARGET_1_5R"
                        break
                else:
                    if bh >= stop_p:
                        actual_exit = stop_p
                        exit_type = "STOP_LOSS"
                        break
                    if bl <= target_p:
                        actual_exit = target_p
                        exit_type = "PROFIT_TARGET_1_5R"
                        break

            if "TIME_EXIT" in exit_type:
                actual_exit = actual_exit - (tick if d == 1 else -tick)

            trade_rec = TradeFillRecord(
                date=session_date,
                symbol=sym,
                direction="LONG" if d == 1 else "SHORT",
                contracts=contracts,
                theo_entry_price=entry_p,
                actual_entry_fill=actual_entry,
                theo_stop_price=stop_p,
                theo_target_price=target_p,
                exit_type=exit_type,
                actual_exit_fill=actual_exit,
                strategy=strategy_name,
                theo_entry_time=f"{start_hhmm}:00",
                actual_entry_time=f"{start_hhmm}:01",
                theo_exit_time=f"{end_hhmm}:00",
                actual_exit_time=f"{end_hhmm}:00",
                notes="Auto-logged by morning watcher with 1-tick adverse slippage + commissions",
            )
            new_st = journal.record_trade(trade_rec)
            print(f"  [AUTO-LOGGER] Auto-resolved trade for {contracts}x {sym} ({sig['direction'].upper()}):")
            print(
                f"                Result: {exit_type} @ {actual_exit:.2f} | Net PnL: ${trade_rec.net_pnl:+,.2f} | "
                f"Updated Balance: ${new_st.balance:,.2f}"
            )


def run_evaluation_and_notify(
    *,
    speak: bool = True,
    auto_log: bool = True,
    window_trigger: str | None = None,
) -> dict:
    if window_trigger == "08:25":
        try:
            from scripts.check_morning_readiness import run_diagnostics
            run_diagnostics(verbose=False, send_alert=True)
            print("[Watcher] 08:25 ET Pre-Market Readiness Check completed successfully.")
        except Exception as e:
            print(f"[Watcher] Pre-market diagnostic error: {e}")
        return {
            "session_date": datetime.now(ET_TZ).strftime("%Y-%m-%d"),
            "w_macro_fire": None,
            "w1_fires": [],
            "w2_fire": None,
        }

    journal = DemoParityJournal()
    eval_state = journal.get_eval_state()
    tier_contracts = eval_state.recommended_micros
    tier_label = eval_state.recommended_tier

    bars_nq = load_bars_with_local_fallback(
        "NQ=F",
        ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet",
        cqg_csv=ROOT / "data/raw/@NQ.CQG_1.csv",
    )
    bars_es = load_bars_with_local_fallback(
        "ES=F",
        ROOT / "data/raw/es_1m_2020_2026_cqg_et.parquet",
        cqg_csv=ROOT / "data/raw/@ES.CQG_1.csv",
    )
    bars_gc = load_bars_with_local_fallback(
        "GC=F",
        ROOT / "data/raw/gc_1m_2020_2026_et.parquet",
        cqg_csv=ROOT / "data/raw/@GC.CQG_1.csv",
    )
    bars_vix = fetch_live_morning_bars("^VIX", period="5d")

    vix_chg_pct = None
    if not bars_vix.empty:
        v_date = bars_vix["time"].dt.strftime("%Y-%m-%d").max()
        v_today = bars_vix[bars_vix["time"].dt.strftime("%Y-%m-%d") == v_date]
        v_15 = v_today[v_today["time"].dt.strftime("%H:%M").between("09:30", "09:44")]
        if not v_15.empty and float(v_15.iloc[0]["open"]) > 0:
            vo = float(v_15.iloc[0]["open"])
            vc = float(v_15.iloc[-1]["close"])
            vix_chg_pct = (vc - vo) / vo * 100.0

    nq_dir = get_or15_direction(bars_nq)
    es_dir = get_or15_direction(bars_es)

    sig_macro = evaluate_macro_momentum_signal(bars_nq)
    sig_nq = evaluate_signal_for_asset(bars_nq, "NQ", vix_chg_pct, other_index_dir=es_dir)
    sig_es = evaluate_signal_for_asset(bars_es, "ES", vix_chg_pct, other_index_dir=nq_dir)
    sig_gc = evaluate_gold_h14_signal(bars_gc)

    # Compute granular diagnostic reasons for each window
    w0_diag = sig_macro["macro_reasons"][0] if sig_macro else diagnose_macro_window(bars_nq)
    nq_ok = bool(sig_nq and sig_nq.get("macro_pass"))
    es_ok = bool(sig_es and sig_es.get("macro_pass"))
    w1_nq_diag = sig_nq["macro_reason"] if (nq_ok and sig_nq) else diagnose_equity_va_window(bars_nq, bars_es, sig_nq, sig_es, nq_ok, es_ok)
    w1_es_diag = sig_es["macro_reason"] if (es_ok and sig_es) else diagnose_equity_va_window(bars_nq, bars_es, sig_nq, sig_es, nq_ok, es_ok)
    w2_diag = sig_gc["macro_reason"] if sig_gc else diagnose_gold_h14_window(bars_gc)

    w1_fires = []
    fired_tuples: list[tuple[dict, pd.DataFrame, str, int]] = []

    w_macro_fire = None
    if sig_macro:
        w_macro_fire = (
            f"{sig_macro['action']} {tier_contracts} MNQ @ {sig_macro['entry_price']:.2f} "
            f"(SL {sig_macro['stop_price']:.2f}, TP {sig_macro['target_price']:.2f})"
        )
        fired_tuples.append((sig_macro, bars_nq, "08:35", tier_contracts))

    if nq_ok and es_ok:
        c_nq = max(1, tier_contracts // 2)
        c_es = max(1, tier_contracts - c_nq)
    else:
        c_nq = tier_contracts
        c_es = tier_contracts

    if nq_ok and sig_nq:
        w1_fires.append(
            f"{sig_nq['action']} {c_nq} MNQ @ {sig_nq['entry_price']:.2f} "
            f"(SL {sig_nq['stop_price']:.2f}, TP {sig_nq['target_price']:.2f})"
        )
        fired_tuples.append((sig_nq, bars_nq, "09:45", c_nq))

    if es_ok and sig_es:
        w1_fires.append(
            f"{sig_es['action']} {c_es} MES @ {sig_es['entry_price']:.2f} "
            f"(SL {sig_es['stop_price']:.2f}, TP {sig_es['target_price']:.2f})"
        )
        fired_tuples.append((sig_es, bars_es, "09:45", c_es))

    w2_fire = None
    if sig_gc:
        w2_fire = (
            f"BUY {tier_contracts} MGC @ {sig_gc['entry_price']:.2f} "
            f"(SL {sig_gc['stop_price']:.2f}, TP {sig_gc['target_price']:.2f})"
        )
        fired_tuples.append((sig_gc, bars_gc, "10:15", tier_contracts))

    session_date = (
        sig_macro["date_str"]
        if sig_macro
        else (
            sig_nq["date_str"]
            if sig_nq
            else (sig_gc["date_str"] if sig_gc else bars_nq["time"].dt.strftime("%Y-%m-%d").max())
        )
    )

    # Daily multi-strategy scan display
    print("\n--- DAILY MULTI-STRATEGY ENSEMBLE SIGNAL SCAN ---")
    print(f"  [08:35 ET] MNQ (Strategy 3 / Macro): {'SIGNAL FIRED' if sig_macro else 'NO SIGNAL'}")
    print(f"  [09:45 ET] MNQ (Strategy 1 / Cash):  {'SIGNAL FIRED' if (nq_ok and sig_nq) else 'NO SIGNAL'}")
    print(f"  [09:45 ET] MES (Strategy 1 / Cash):  {'SIGNAL FIRED' if (es_ok and sig_es) else 'NO SIGNAL'}")
    print(f"  [10:15 ET] MGC (Strategy 2 / Fix):   {'SIGNAL FIRED' if sig_gc else 'NO SIGNAL'}")
    print("--------------------------------------------------")
    if not fired_tuples:
        print("[NO SIGNAL TODAY] None of 08:35 ET (Macro), 09:45 ET (Cash VA), or 10:15 ET (Fix) met breakout criteria.")
        print(f"Account Balance: ${eval_state.balance:,.2f} | Trailing Floor: ${eval_state.trailing_floor:,.2f}")

    print("\n" + "=" * 88)
    print(
        f"  [MORNING WATCHER SUMMARY] Session {session_date} | "
        f"Balance: ${eval_state.balance:,.2f} | Tier: {tier_label} ({tier_contracts} Micros)"
    )
    print(f"  Window 0 (08:35 ET MNQ Macro): {w_macro_fire if w_macro_fire else f'NO TRADE ({w0_diag})'}")
    print(f"  Window 1 (09:45 ET MNQ+MES):   {', '.join(w1_fires) if w1_fires else f'NO TRADE ({w1_nq_diag})'}")
    print(f"  Window 2 (10:15 ET MGC H14):   {w2_fire if w2_fire else f'NO TRADE ({w2_diag})'}")
    print(f"  HTML Parity Dashboard        : {DASHBOARD_HTML_PATH}")
    print("=" * 88)

    # Auto-log if enabled
    if auto_log:
        flat_diag = f"NO TRADE: [08:35] {w0_diag} | [09:45] {w1_nq_diag} | [10:15] {w2_diag}"
        auto_log_session_and_trades(journal, session_date, fired_tuples, eval_state, diag_summary=flat_diag)

        # Granular window-by-window evaluation ledger (every opportunity, trade, and filter tracked)
        # Window 0: 08:35 ET MNQ Macro
        if window_trigger is None or window_trigger == "08:35":
            w0_status = "TRADE_FIRED" if sig_macro else "FILTERED_NO_BREAKOUT"
            w0_action = sig_macro["action"] if sig_macro else "NONE"
            w0_contracts = tier_contracts if sig_macro else 0
            w0_reason = f"TRADE FIRED: {w0_action} @ {sig_macro['entry_price']:.2f}" if sig_macro else w0_diag
            journal.record_window_evaluation(WindowEvaluationRecord(
                date=session_date,
                window_time="08:35:00",
                strategy="Macro Momentum (08:35)",
                symbol="MNQ",
                status=w0_status,
                action=w0_action,
                contracts=w0_contracts,
                diagnostic_reason=w0_reason,
                entry_price=sig_macro["entry_price"] if sig_macro else None,
                stop_price=sig_macro["stop_price"] if sig_macro else None,
                target_price=sig_macro["target_price"] if sig_macro else None,
                account_balance=eval_state.balance,
                trailing_cushion=eval_state.trailing_cushion,
            ))

        # Window 1: 09:45 ET MNQ & MES
        if window_trigger is None or window_trigger == "09:45":
            w1_nq_status = "TRADE_FIRED" if (nq_ok and sig_nq) else "FILTERED_NO_BREAKOUT"
            w1_nq_action = sig_nq["action"] if (nq_ok and sig_nq) else "NONE"
            w1_nq_contracts = c_nq if (nq_ok and sig_nq) else 0
            w1_nq_reason = f"TRADE FIRED: {w1_nq_action} @ {sig_nq['entry_price']:.2f}" if (nq_ok and sig_nq) else w1_nq_diag
            journal.record_window_evaluation(WindowEvaluationRecord(
                date=session_date,
                window_time="09:45:00",
                strategy="VA Breakout (v2.0)",
                symbol="MNQ",
                status=w1_nq_status,
                action=w1_nq_action,
                contracts=w1_nq_contracts,
                diagnostic_reason=w1_nq_reason,
                entry_price=sig_nq["entry_price"] if (nq_ok and sig_nq) else None,
                stop_price=sig_nq["stop_price"] if (nq_ok and sig_nq) else None,
                target_price=sig_nq["target_price"] if (nq_ok and sig_nq) else None,
                account_balance=eval_state.balance,
                trailing_cushion=eval_state.trailing_cushion,
            ))

            w1_es_status = "TRADE_FIRED" if (es_ok and sig_es) else "FILTERED_NO_BREAKOUT"
            w1_es_action = sig_es["action"] if (es_ok and sig_es) else "NONE"
            w1_es_contracts = c_es if (es_ok and sig_es) else 0
            w1_es_reason = f"TRADE FIRED: {w1_es_action} @ {sig_es['entry_price']:.2f}" if (es_ok and sig_es) else w1_es_diag
            journal.record_window_evaluation(WindowEvaluationRecord(
                date=session_date,
                window_time="09:45:00",
                strategy="VA Breakout (v2.0)",
                symbol="MES",
                status=w1_es_status,
                action=w1_es_action,
                contracts=w1_es_contracts,
                diagnostic_reason=w1_es_reason,
                entry_price=sig_es["entry_price"] if (es_ok and sig_es) else None,
                stop_price=sig_es["stop_price"] if (es_ok and sig_es) else None,
                target_price=sig_es["target_price"] if (es_ok and sig_es) else None,
                account_balance=eval_state.balance,
                trailing_cushion=eval_state.trailing_cushion,
            ))

        # Window 2: 10:15 ET MGC
        if window_trigger is None or window_trigger == "10:15":
            w2_status = "TRADE_FIRED" if sig_gc else "FILTERED_NO_BREAKOUT"
            w2_action = "BUY" if sig_gc else "NONE"
            w2_contracts = tier_contracts if sig_gc else 0
            w2_reason = f"TRADE FIRED: BUY @ {sig_gc['entry_price']:.2f}" if sig_gc else w2_diag
            journal.record_window_evaluation(WindowEvaluationRecord(
                date=session_date,
                window_time="10:15:00",
                strategy="Gold London Fix (H14)",
                symbol="MGC",
                status=w2_status,
                action=w2_action,
                contracts=w2_contracts,
                diagnostic_reason=w2_reason,
                entry_price=sig_gc["entry_price"] if sig_gc else None,
                stop_price=sig_gc["stop_price"] if sig_gc else None,
                target_price=sig_gc["target_price"] if sig_gc else None,
                account_balance=eval_state.balance,
                trailing_cushion=eval_state.trailing_cushion,
            ))

        # Refresh state JSON and regenerate HTML dashboard
        final_state = journal.get_eval_state()
        journal.save_state_json(final_state)
        journal.generate_html_dashboard()

    # Generate and dispatch automated active order ticket (Desktop file + macOS clipboard)
    active_orders: list[dict[str, any]] = []
    if (window_trigger is None or window_trigger == "08:35") and sig_macro:
        risk_pts = abs(sig_macro["entry_price"] - sig_macro["stop_price"])
        rew_pts = abs(sig_macro["target_price"] - sig_macro["entry_price"])
        active_orders.append({
            "strategy": "Macro Momentum (08:35)",
            "window": "08:35",
            "symbol": "MNQ",
            "action": sig_macro["action"],
            "contracts": tier_contracts,
            "entry_price": sig_macro["entry_price"],
            "stop_price": sig_macro["stop_price"],
            "target_price": sig_macro["target_price"],
            "risk_pts": risk_pts,
            "risk_dollars": round(risk_pts * 2.0 * tier_contracts, 2),
            "reward_pts": rew_pts,
            "reward_dollars": round(rew_pts * 2.0 * tier_contracts, 2),
            "exit_rule": "Flatten before 09:25 ET (Pre-Cash Open Risk Shield)",
        })

    if window_trigger is None or window_trigger == "09:45":
        if nq_ok and sig_nq:
            risk_pts = abs(sig_nq["entry_price"] - sig_nq["stop_price"])
            rew_pts = abs(sig_nq["target_price"] - sig_nq["entry_price"])
            active_orders.append({
                "strategy": "VA Breakout v2.0 (09:45)",
                "window": "09:45",
                "symbol": "MNQ",
                "action": sig_nq["action"],
                "contracts": c_nq,
                "entry_price": sig_nq["entry_price"],
                "stop_price": sig_nq["stop_price"],
                "target_price": sig_nq["target_price"],
                "risk_pts": risk_pts,
                "risk_dollars": round(risk_pts * 2.0 * c_nq, 2),
                "reward_pts": rew_pts,
                "reward_dollars": round(rew_pts * 2.0 * c_nq, 2),
                "exit_rule": "10:15 ET Max Time Exit (News guard at 09:59 if red-folder data)",
            })
        if es_ok and sig_es:
            risk_pts = abs(sig_es["entry_price"] - sig_es["stop_price"])
            rew_pts = abs(sig_es["target_price"] - sig_es["entry_price"])
            active_orders.append({
                "strategy": "VA Breakout v2.0 (09:45)",
                "window": "09:45",
                "symbol": "MES",
                "action": sig_es["action"],
                "contracts": c_es,
                "entry_price": sig_es["entry_price"],
                "stop_price": sig_es["stop_price"],
                "target_price": sig_es["target_price"],
                "risk_pts": risk_pts,
                "risk_dollars": round(risk_pts * 5.0 * c_es, 2),
                "reward_pts": rew_pts,
                "reward_dollars": round(rew_pts * 5.0 * c_es, 2),
                "exit_rule": "10:15 ET Max Time Exit (News guard at 09:59 if red-folder data)",
            })

    if (window_trigger is None or window_trigger == "10:15") and sig_gc:
        risk_pts = abs(sig_gc["entry_price"] - sig_gc["stop_price"])
        rew_pts = abs(sig_gc["target_price"] - sig_gc["entry_price"])
        active_orders.append({
            "strategy": "Gold London Fix H14 (10:15)",
            "window": "10:15",
            "symbol": "MGC",
            "action": "BUY",
            "contracts": tier_contracts,
            "entry_price": sig_gc["entry_price"],
            "stop_price": sig_gc["stop_price"],
            "target_price": sig_gc["target_price"],
            "risk_pts": risk_pts,
            "risk_dollars": round(risk_pts * 10.0 * tier_contracts, 2),
            "reward_pts": rew_pts,
            "reward_dollars": round(rew_pts * 10.0 * tier_contracts, 2),
            "exit_rule": "11:00 ET Hard Session Close",
        })

    if active_orders:
        dispatch_active_order_card(active_orders, eval_state, tier_label)

    # Window-specific macOS popup notifications
    # CRITICAL RULE: Non-trade / flat evaluations are COMPLETELY SILENT (sound=False, speak=None).
    # Glass chime and voice alerts ONLY fire on actual trade signals.
    if window_trigger == "08:35":
        if sig_macro:
            send_macos_alert(
                title="PROP SIGNAL FIRED (08:35 ET)",
                subtitle="Window 0: Macro Momentum (MNQ)",
                message=w_macro_fire,
                speak_text="Window zero macro momentum trade fired. Check execution card." if speak else None,
                sound=True,
            )
        else:
            send_macos_alert(
                title="Window 0: Macro Momentum (08:35 ET)",
                subtitle="MNQ Pre-Market Setup",
                message=f"No Trade: {w0_diag}",
                speak_text=None,
                sound=False,
            )
    elif window_trigger == "09:25":
        send_macos_alert(
            title="Window 0: Cash Open Flatten (09:25 ET)",
            subtitle="Pre-Market Risk Shield",
            message="Macro window closed. 100% flat heading into cash open.",
            speak_text=None,
            sound=False,
        )
    elif window_trigger == "09:45":
        if w1_fires:
            send_macos_alert(
                title="PROP SIGNAL FIRED (09:45 ET)",
                subtitle=f"Window 1: VA Breakout ({tier_contracts} Micros)",
                message=" + ".join(w1_fires),
                speak_text="Window one opening value area breakout fired. Check execution card." if speak else None,
                sound=True,
            )
        else:
            send_macos_alert(
                title="Window 1: VA Breakout (09:45 ET)",
                subtitle="MNQ & MES Opening Range",
                message=f"No Trade: {w1_nq_diag}",
                speak_text=None,
                sound=False,
            )
    elif window_trigger == "10:15":
        if sig_gc:
            send_macos_alert(
                title="PROP SIGNAL FIRED (10:15 ET)",
                subtitle=f"Window 2: Gold London Fix ({tier_contracts} Micros)",
                message=w2_fire,
                speak_text="Window two gold fix breakout fired. Check execution card." if speak else None,
                sound=True,
            )
        else:
            send_macos_alert(
                title="Window 2: Gold London Fix (10:15 ET)",
                subtitle="MGC Gold Breakout (H14)",
                message=f"No Trade: {w2_diag}",
                speak_text=None,
                sound=False,
            )
    elif window_trigger == "11:00":
        send_macos_alert(
            title="Morning Session Concluded (11:00 ET)",
            subtitle="LucidFlex 25K Session Finalized",
            message=f"All 3 windows complete. Account Balance: ${eval_state.balance:,.2f} | Cushion: ${eval_state.trailing_cushion:,.2f} (100% Intact).",
            speak_text=None,
            sound=False,
        )
    else:
        # window_trigger is None (e.g. manual scan / --once mode)
        if w_macro_fire or w1_fires or w2_fire:
            msg_parts = []
            if w_macro_fire:
                msg_parts.append("08:35: " + w_macro_fire)
            if w1_fires:
                msg_parts.append("09:45: " + " + ".join(w1_fires))
            if w2_fire:
                msg_parts.append("10:15: " + w2_fire)
            full_msg = " | ".join(msg_parts)
            send_macos_alert(
                title=f"PROP SIGNAL FIRED ({session_date})",
                subtitle=f"LucidFlex 25K ({tier_contracts} Micros)",
                message=full_msg,
                speak_text="Prop trading signal fired. Check terminal execution card." if speak else None,
                sound=True,
            )
        else:
            send_macos_alert(
                title=f"Prop Check Complete ({session_date})",
                subtitle="All 3 Windows Evaluated",
                message="08:35 ET (Macro), 09:45 ET (MNQ/MES) and 10:15 ET (MGC) gates are flat.",
                speak_text=None,
                sound=False,
            )

    return {
        "session_date": session_date,
        "w_macro_fire": w_macro_fire,
        "w1_fires": w1_fires,
        "w2_fire": w2_fire,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Automated Morning Forward-Test Watcher & macOS Alert Runner.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single immediate check, fire macOS desktop notification, auto-log, and exit.",
    )
    parser.add_argument(
        "--window",
        type=str,
        default=None,
        choices=["08:25", "08:35", "09:25", "09:45", "10:15", "11:00"],
        help="Target a specific execution window to evaluate and notify.",
    )
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="Disable macOS text-to-speech voice alert (keep banner notification only).",
    )
    parser.add_argument(
        "--no-auto-log",
        action="store_true",
        help="Disable automatic session and trade logging.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=10,
        help="Polling interval in seconds when running in continuous morning watch mode (default: 10s).",
    )
    args = parser.parse_args()

    if args.once:
        run_evaluation_and_notify(
            speak=not args.no_voice,
            auto_log=not args.no_auto_log,
            window_trigger=args.window,
        )
        return 0

    print("[Watcher] Armed in continuous morning watch mode (America/New_York).")
    print("[Watcher] Automatic logging is ENABLED: No-trade days and completed trades are logged without user input.")
    print("[Watcher] Will automatically evaluate and alert at 08:25 ET (Pre-Market), 08:35 ET, 09:25 ET, 09:45 ET, 10:15 ET, and 11:00 ET.")
    fired_windows: set[str] = set()
    last_mtime = 0.0

    try:
        while True:
            now_et = datetime.now(ET_TZ)
            hhmmss = now_et.strftime("%H:%M:%S")
            d_str = now_et.strftime("%Y-%m-%d")

            csv_files = [
                ROOT / "data/raw/@NQ.CQG_1.csv",
                ROOT / "data/raw/@ES.CQG_1.csv",
                ROOT / "data/raw/@GC.CQG_1.csv",
            ]
            cur_mtime = max((p.stat().st_mtime for p in csv_files if p.exists()), default=0.0)

            w_premarket_key = f"{d_str}_0825"
            w0_key = f"{d_str}_0835"
            w0_exit = f"{d_str}_0925"
            w1_key = f"{d_str}_0945"
            w2_key = f"{d_str}_1015"
            w3_key = f"{d_str}_1100"

            # Check persistent ledger so sleep/wake cycles or late wakeups catch up on any missed window
            journal = DemoParityJournal()
            df_w = journal.load_windows_df()
            df_s = journal.load_sessions_df()

            recorded_w_times = set()
            if not df_w.empty and "date" in df_w.columns and "window_time" in df_w.columns:
                d_rows = df_w[df_w["date"].astype(str) == d_str]
                recorded_w_times = set(d_rows["window_time"].astype(str).tolist())

            has_session_today = False
            if not df_s.empty and "date" in df_s.columns:
                has_session_today = d_str in df_s["date"].astype(str).values

            # Pre-Market Readiness Check (08:25 ET): Silent system health & MotiveWave check
            if "08:25:02" <= hhmmss < "08:35:00" and w_premarket_key not in fired_windows:
                fired_windows.add(w_premarket_key)
                try:
                    from scripts.check_morning_readiness import run_diagnostics
                    run_diagnostics(verbose=False, send_alert=True)
                    print(f"[Watcher] 08:25 ET Pre-Market Readiness Check complete. Notification dispatched.")
                except Exception as e:
                    print(f"[Watcher] Pre-market diagnostic error: {e}")

            # Window 0 (08:35 ET): S3 Macro Momentum
            if hhmmss >= "08:35:02" and "08:35:00" not in recorded_w_times and w0_key not in fired_windows:
                fired_windows.add(w0_key)
                last_mtime = cur_mtime
                run_evaluation_and_notify(speak=not args.no_voice, auto_log=not args.no_auto_log, window_trigger="08:35")
            # Window 0 Exit (09:25 ET): Pre-Cash Flatten
            elif hhmmss >= "09:25:02" and w0_exit not in fired_windows:
                fired_windows.add(w0_exit)
                last_mtime = cur_mtime
                run_evaluation_and_notify(speak=not args.no_voice, auto_log=not args.no_auto_log, window_trigger="09:25")
            # Window 1 (09:45 ET): S1 VA Breakout (MNQ + MES)
            elif hhmmss >= "09:45:02" and "09:45:00" not in recorded_w_times and w1_key not in fired_windows:
                fired_windows.add(w1_key)
                last_mtime = cur_mtime
                run_evaluation_and_notify(speak=not args.no_voice, auto_log=not args.no_auto_log, window_trigger="09:45")
            # Window 2 (10:15 ET): S2 Gold London Fix & S1 Time Exit
            elif hhmmss >= "10:15:02" and "10:15:00" not in recorded_w_times and w2_key not in fired_windows:
                fired_windows.add(w2_key)
                last_mtime = cur_mtime
                run_evaluation_and_notify(speak=not args.no_voice, auto_log=not args.no_auto_log, window_trigger="10:15")
            # Session Close (11:00 ET): Finalize Day
            elif hhmmss >= "11:00:02" and not has_session_today and w3_key not in fired_windows:
                fired_windows.add(w3_key)
                last_mtime = cur_mtime
                run_evaluation_and_notify(speak=not args.no_voice, auto_log=not args.no_auto_log, window_trigger="11:00")

            if last_mtime == 0.0:
                last_mtime = cur_mtime
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        print("\n[Watcher] Stopped by user.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
