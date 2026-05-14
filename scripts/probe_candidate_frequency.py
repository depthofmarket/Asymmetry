#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backtest.engine import BacktestEngine
from backtest.portfolio import Portfolio
from backtest.strategy_runtime import extract_signal_events
from config.backtest_config import BACKTEST_CONFIG, CANDIDATE_CONFIGS, FUTURES_SPECS, STRATEGY_PARAMS
from main_backtest import load_data, resolve_max_drawdown_pct, years_covered


DEFAULT_CANDIDATES = [
    "edge_vp_scalp_frequency_gap_cusum_no_mr_long",
    "edge_vp_2021_frequency_open_throttle",
    "edge_vp_2021_frequency_trend_throttle",
    "edge_vp_2021_frequency_no_gap_guard",
    "edge_vp_2021_frequency_open_throttle_delay_1",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run lightweight 2021+ frequency probes for candidate configs. "
            "This skips the expensive research exports and reports only trade count/basic edge metrics."
        )
    )
    parser.add_argument(
        "candidates",
        nargs="*",
        default=DEFAULT_CANDIDATES,
        help="Candidate names to probe. Defaults to the 2021 frequency lab set.",
    )
    parser.add_argument(
        "--start",
        default="2021-01-01",
        help="Inclusive start date for the probe window.",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Inclusive end date for the probe window.",
    )
    parser.add_argument(
        "--strategy",
        default=None,
        help="Optional strategy_name override.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional CSV path for probe results.",
    )
    parser.add_argument(
        "--full-diagnostics",
        action="store_true",
        help="Keep non-signal diagnostic features enabled. Slower, but closer to a full run's preprocessing.",
    )
    parser.add_argument(
        "--signals-only",
        action="store_true",
        help="Count filtered signal events instead of executing trades. Fast upper-bound screen for frequency.",
    )
    parser.add_argument(
        "--list-candidates",
        action="store_true",
        help="Print available candidate names and exit.",
    )
    return parser.parse_args()


def fmt(value: object, digits: int = 2) -> str:
    if value is None:
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isinf(numeric):
        return "inf"
    if math.isnan(numeric):
        return ""
    return f"{numeric:.{digits}f}"


def active_day_metrics(trades: pd.DataFrame, data: pd.DataFrame) -> tuple[int, float, float]:
    if trades.empty or "entry_time" not in trades.columns:
        return 0, 0.0, 0.0

    entry_days = pd.to_datetime(trades["entry_time"]).dt.normalize()
    active_days = int(entry_days.nunique())
    if active_days <= 0:
        return 0, 0.0, 0.0

    data_start = pd.to_datetime(data["time"]).min().normalize()
    data_end = pd.to_datetime(data["time"]).max().normalize()
    business_days = len(pd.bdate_range(data_start, data_end))
    active_day_pct = active_days / business_days * 100 if business_days else 0.0
    trades_per_active_day = len(trades) / active_days
    return active_days, active_day_pct, trades_per_active_day


def cap_signal_events_by_day(
    signal_frame: pd.DataFrame,
    *,
    entry_mode: str,
    entry_delay_bars: int,
    max_trades_per_day: int,
) -> pd.DataFrame:
    events = extract_signal_events(
        signal_frame,
        entry_mode=entry_mode,
        entry_delay_bars=entry_delay_bars,
    )
    if not events:
        return pd.DataFrame(columns=["entry_time", "direction", "signal_type", "setup_tag"])

    events_df = pd.DataFrame(
        {
            "signal_time": [event.signal_time for event in events],
            "entry_time": [event.entry_time for event in events],
            "direction": [event.direction for event in events],
            "signal_type": [event.signal_type for event in events],
            "setup_tag": [event.setup_tag for event in events],
        }
    )
    if max_trades_per_day > 0:
        entry_day = pd.to_datetime(events_df["entry_time"]).dt.normalize()
        day_slot = events_df.groupby(entry_day).cumcount()
        events_df = events_df.loc[day_slot.lt(max_trades_per_day)].reset_index(drop=True)
    return events_df


def disable_unused_diagnostics(params: dict[str, object]) -> None:
    if str(params.get("vsa_filter", "off")).lower() in {"off", "none", "false", "0"}:
        params["vsa_enabled"] = False
    if not bool(params.get("hawkes_exit_enabled", False)):
        params["hawkes_enabled"] = False
    if str(params.get("markov_regime_filter", "off")).lower() in {"off", "none", "false", "0"}:
        params["markov_regime_enabled"] = False
    if str(params.get("market_memory_filter", "off")).lower() in {"off", "none", "false", "0"}:
        params["market_memory_enabled"] = False
    if str(params.get("options_flow_filter", "off")).lower() in {"off", "none", "false", "0"}:
        params["options_flow_enabled"] = False
    if (
        str(params.get("market_structure_filter", "off")).lower() in {"off", "none", "false", "0"}
        and not bool(params.get("market_structure_stop_enabled", False))
    ):
        params["market_structure_enabled"] = False


def probe_candidate(
    candidate_name: str,
    data: pd.DataFrame,
    strategy: str | None,
    *,
    full_diagnostics: bool,
    signals_only: bool,
    shared_pre_df: pd.DataFrame | None = None,
) -> dict[str, object]:
    if candidate_name not in CANDIDATE_CONFIGS:
        return {
            "candidate": candidate_name,
            "status": "unknown_candidate",
            "error": f"Unknown candidate: {candidate_name}",
        }

    params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG, **CANDIDATE_CONFIGS[candidate_name]}
    params["_candidate_name"] = candidate_name
    if strategy is not None:
        params["strategy_name"] = strategy
    if not full_diagnostics:
        disable_unused_diagnostics(params)

    portfolio = Portfolio(
        BACKTEST_CONFIG["starting_capital"],
        FUTURES_SPECS,
        max_drawdown_pct=resolve_max_drawdown_pct(params),
    )
    engine = BacktestEngine(data, portfolio, FUTURES_SPECS, params)
    pre_df = shared_pre_df if shared_pre_df is not None else engine.preprocess()
    if signals_only:
        signal_frame = engine.build_signal_frame(pre_df)
        signal_events = cap_signal_events_by_day(
            signal_frame,
            entry_mode=str(params.get("entry_mode", "next_bar_open")),
            entry_delay_bars=int(params.get("entry_delay_bars", 0) or 0),
            max_trades_per_day=int(params.get("max_trades_per_day", 0) or 0),
        )
        active_days, active_day_pct, signals_per_active_day = active_day_metrics(signal_events, data)
        covered_years = years_covered(data)
        signal_count = int(len(signal_events))
        long_signals = int(signal_events["direction"].eq("long").sum()) if not signal_events.empty else 0
        short_signals = int(signal_events["direction"].eq("short").sum()) if not signal_events.empty else 0
        return {
            "candidate": candidate_name,
            "status": "signals_only",
            "bars": int(len(pre_df)),
            "data_start": str(pd.to_datetime(data["time"]).min()),
            "data_end": str(pd.to_datetime(data["time"]).max()),
            "years": covered_years,
            "total_trades": signal_count,
            "trades_per_year": signal_count / covered_years,
            "active_trade_days": active_days,
            "active_day_pct": active_day_pct,
            "trades_per_active_day": signals_per_active_day,
            "total_pnl": float("nan"),
            "profit_factor": float("nan"),
            "bar_profit_factor": float("nan"),
            "max_drawdown_pct": float("nan"),
            "win_rate_pct": float("nan"),
            "long_trades": long_signals,
            "short_trades": short_signals,
            "hit_1000_trade_goal": signal_count >= 1000,
        }

    results = engine.run_on_preprocessed(pre_df)
    if "error" in results:
        return {
            "candidate": candidate_name,
            "status": "error",
            "error": results["error"],
        }

    trades = results["trades"]
    active_days, active_day_pct, trades_per_active_day = active_day_metrics(trades, data)
    covered_years = years_covered(data)
    total_trades = int(results.get("total_trades", len(trades)))

    return {
        "candidate": candidate_name,
        "status": "ok",
        "bars": int(len(pre_df)),
        "data_start": str(pd.to_datetime(data["time"]).min()),
        "data_end": str(pd.to_datetime(data["time"]).max()),
        "years": covered_years,
        "total_trades": total_trades,
        "trades_per_year": total_trades / covered_years,
        "active_trade_days": active_days,
        "active_day_pct": active_day_pct,
        "trades_per_active_day": trades_per_active_day,
        "total_pnl": float(results.get("total_pnl", 0.0)),
        "profit_factor": float(results.get("profit_factor", 0.0)),
        "bar_profit_factor": float(results.get("bar_profit_factor", 0.0)),
        "max_drawdown_pct": float(results.get("max_drawdown", 0.0)),
        "win_rate_pct": float(results.get("win_rate", 0.0)),
        "long_trades": int(results.get("long_trades", 0)),
        "short_trades": int(results.get("short_trades", 0)),
        "hit_1000_trade_goal": total_trades >= 1000,
    }


def print_table(rows: list[dict[str, object]]) -> None:
    headers = [
        "candidate",
        "trades",
        "tpy",
        "active_days",
        "pnl",
        "pf",
        "bar_pf",
        "dd_pct",
        "goal",
    ]
    print(
        f"{headers[0]:<48} {headers[1]:>7} {headers[2]:>7} {headers[3]:>11} "
        f"{headers[4]:>12} {headers[5]:>7} {headers[6]:>7} {headers[7]:>7} {headers[8]:>6}"
    )
    print("-" * 124)
    for row in rows:
        if row.get("status") not in {"ok", "signals_only"}:
            print(f"{str(row.get('candidate', '')):<48} ERROR {row.get('error', '')}")
            continue
        print(
            f"{str(row['candidate']):<48} "
            f"{int(row['total_trades']):>7} "
            f"{fmt(row['trades_per_year'], 1):>7} "
            f"{int(row['active_trade_days']):>11} "
            f"{fmt(row['total_pnl'], 0):>12} "
            f"{fmt(row['profit_factor'], 2):>7} "
            f"{fmt(row['bar_profit_factor'], 2):>7} "
            f"{fmt(row['max_drawdown_pct'], 2):>7} "
            f"{'yes' if row['hit_1000_trade_goal'] else 'no':>6}"
        )


def main() -> int:
    args = parse_args()
    if args.list_candidates:
        for name in sorted(CANDIDATE_CONFIGS):
            print(name)
        return 0

    unknown = [name for name in args.candidates if name not in CANDIDATE_CONFIGS]
    if unknown:
        print(f"Unknown candidate(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    data_path = BACKTEST_CONFIG.get("data_path", "data/raw/glbx-mdp3-20100606-20260428.ohlcv-1m.csv")
    print(f"Loading data: {data_path}")
    print(f"Window: {args.start or 'first bar'} -> {args.end or 'last bar'}")
    if not args.full_diagnostics:
        print("Mode: fast frequency scan (unused diagnostics disabled)")
    if args.signals_only:
        print("Execution: signals only (upper-bound frequency screen)")
    data = load_data(
        data_path,
        continuous_contract_method=BACKTEST_CONFIG.get("continuous_contract_method"),
        start=args.start,
        end=args.end,
    )
    if data.empty:
        print("No data after applying the requested date range.", file=sys.stderr)
        return 1
    print(f"Loaded {len(data):,} 1-min bars from {data['time'].min()} to {data['time'].max()}")
    print()

    shared_pre_df = None
    if args.signals_only:
        print("Preprocessing shared feature frame...")
        shared_params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG}
        if args.strategy is not None:
            shared_params["strategy_name"] = args.strategy
        if not args.full_diagnostics:
            disable_unused_diagnostics(shared_params)
        shared_portfolio = Portfolio(
            BACKTEST_CONFIG["starting_capital"],
            FUTURES_SPECS,
            max_drawdown_pct=resolve_max_drawdown_pct(shared_params),
        )
        shared_engine = BacktestEngine(data, shared_portfolio, FUTURES_SPECS, shared_params)
        shared_pre_df = shared_engine.preprocess()
        print(f"Shared bars: {len(shared_pre_df):,}")
        print()

    rows: list[dict[str, object]] = []
    for idx, candidate in enumerate(args.candidates, start=1):
        print(f"[{idx}/{len(args.candidates)}] Probing {candidate}...")
        rows.append(
            probe_candidate(
                candidate,
                data,
                args.strategy,
                full_diagnostics=args.full_diagnostics,
                signals_only=args.signals_only,
                shared_pre_df=shared_pre_df,
            )
        )

    print()
    print_table(rows)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(out_path, index=False)
        print(f"\nWrote probe CSV: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
