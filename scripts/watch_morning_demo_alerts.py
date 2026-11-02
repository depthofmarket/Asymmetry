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
    resolve_instrument,
)
from scripts.run_demo_forward_test import (
    evaluate_gold_h14_signal,
    evaluate_macro_momentum_signal,
    evaluate_signal_for_asset,
    fetch_live_morning_bars,
    get_or15_direction,
)

ET_TZ = ZoneInfo("America/New_York")


def send_macos_alert(title: str, subtitle: str, message: str, speak_text: str | None = None) -> None:
    """Fires a native macOS Notification Center banner with Glass sound and optional TTS voice alert."""
    safe_title = title.replace('"', '\\"')
    safe_sub = subtitle.replace('"', '\\"')
    safe_msg = message.replace('"', '\\"')
    apple_script = (
        f'display notification "{safe_msg}" with title "{safe_title}" '
        f'subtitle "{safe_sub}" sound name "Glass"'
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


def auto_log_session_and_trades(
    journal: DemoParityJournal,
    session_date: str,
    fired_signals: list[tuple[dict, pd.DataFrame, str, int]],
    eval_state: AccountEvalState,
) -> None:
    """
    Automatically logs daily sessions and auto-resolves trades if holding window is complete.
    Zero manual logging required from user!
    """
    # Case 1: No trades fired today
    if not fired_signals:
        df_sessions = journal.load_sessions_df()
        already_recorded = False
        if not df_sessions.empty and "date" in df_sessions.columns:
            already_recorded = session_date in df_sessions["date"].astype(str).values

        if not already_recorded:
            rec = DailySessionRecord(
                date=session_date,
                setup_detected=False,
                setup_fired=False,
                diagnostic_reason="NO TRADE: Window 1 (MNQ/MES) flat/gated | Window 2 (MGC H14) flat/gated",
                end_of_day_balance=eval_state.balance,
            )
            journal.record_session(rec)
            print(f"  [AUTO-LOGGER] Recorded NO-TRADE session for {session_date} in demo_sessions_ledger.csv")
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

        # If window is complete (at least 15 bars), simulate order execution & auto-record
        if len(w_bars) >= 15:
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


def run_evaluation_and_notify(*, speak: bool = True, auto_log: bool = True) -> dict:
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

    w1_fires = []
    fired_tuples: list[tuple[dict, pd.DataFrame, str, int]] = []

    w_macro_fire = None
    if sig_macro:
        w_macro_fire = (
            f"{sig_macro['action']} {tier_contracts} MNQ @ {sig_macro['entry_price']:.2f} "
            f"(SL {sig_macro['stop_price']:.2f}, TP {sig_macro['target_price']:.2f})"
        )
        fired_tuples.append((sig_macro, bars_nq, "08:35", tier_contracts))

    nq_ok = bool(sig_nq and sig_nq.get("macro_pass"))
    es_ok = bool(sig_es and sig_es.get("macro_pass"))
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

    # Subprocess execution card display
    subprocess.run([sys.executable, str(ROOT / "scripts/run_demo_forward_test.py")], check=False)

    print("\n" + "=" * 88)
    print(
        f"  [MORNING WATCHER SUMMARY] Session {session_date} | "
        f"Balance: ${eval_state.balance:,.2f} | Tier: {tier_label} ({tier_contracts} Micros)"
    )
    print(f"  Window 1 (08:35 ET MNQ Macro): {w_macro_fire if w_macro_fire else 'NO TRADE (Filtered/Flat)'}")
    print(f"  Window 2 (09:45 ET MNQ+MES):   {', '.join(w1_fires) if w1_fires else 'NO TRADE (Filtered/Flat)'}")
    print(f"  Window 3 (10:15 ET MGC H14):   {w2_fire if w2_fire else 'NO TRADE (Filtered/Flat)'}")
    print(f"  HTML Parity Dashboard        : {DASHBOARD_HTML_PATH}")
    print("=" * 88)

    # Auto-log if enabled
    if auto_log:
        auto_log_session_and_trades(journal, session_date, fired_tuples, eval_state)

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
        )
    else:
        send_macos_alert(
            title=f"Prop Check Complete ({session_date})",
            subtitle="No Trade Triggered",
            message="08:35 ET (Macro), 09:45 ET (MNQ/MES) and 10:15 ET (MGC) gates are flat.",
            speak_text="Morning signal check complete. No trade triggered." if speak else None,
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
        run_evaluation_and_notify(speak=not args.no_voice, auto_log=not args.no_auto_log)
        return 0

    print("[Watcher] Armed in continuous morning watch mode (America/New_York).")
    print("[Watcher] Automatic logging is ENABLED: No-trade days and completed trades are logged without user input.")
    print("[Watcher] Will automatically evaluate and alert at 08:35 ET, 09:25 ET, 09:45 ET, 10:15 ET, and 11:00 ET.")
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

            w0_key = f"{d_str}_0835"
            w0_exit = f"{d_str}_0925"
            w1_key = f"{d_str}_0945"
            w2_key = f"{d_str}_1015"
            w3_key = f"{d_str}_1100"

            if "08:35:02" <= hhmmss <= "08:36:30" and w0_key not in fired_windows:
                fired_windows.add(w0_key)
                last_mtime = cur_mtime
                run_evaluation_and_notify(speak=not args.no_voice, auto_log=not args.no_auto_log)
            elif "09:25:02" <= hhmmss <= "09:26:30" and w0_exit not in fired_windows:
                fired_windows.add(w0_exit)
                last_mtime = cur_mtime
                # Auto-resolves any open Window 1 trade before cash open
                run_evaluation_and_notify(speak=not args.no_voice, auto_log=not args.no_auto_log)
            elif ("09:45:02" <= hhmmss <= "09:46:30" and w1_key not in fired_windows) or (
                last_mtime > 0 and cur_mtime > last_mtime
            ):
                fired_windows.add(w1_key)
                last_mtime = cur_mtime
                run_evaluation_and_notify(speak=not args.no_voice, auto_log=not args.no_auto_log)
            elif "10:15:02" <= hhmmss <= "10:16:30" and w2_key not in fired_windows:
                fired_windows.add(w2_key)
                last_mtime = cur_mtime
                run_evaluation_and_notify(speak=not args.no_voice, auto_log=not args.no_auto_log)
            elif "11:00:02" <= hhmmss <= "11:01:30" and w3_key not in fired_windows:
                fired_windows.add(w3_key)
                last_mtime = cur_mtime
                # 11:00 auto-resolves any open Window 2 trade and finalizes the day's session
                run_evaluation_and_notify(speak=not args.no_voice, auto_log=not args.no_auto_log)

            if last_mtime == 0.0:
                last_mtime = cur_mtime
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        print("\n[Watcher] Stopped by user.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
