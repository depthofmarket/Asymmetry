import argparse
import pandas as pd
import numpy as np
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config.backtest_config import (
    FUTURES_SPECS,
    BACKTEST_CONFIG,
    STRATEGY_PARAMS,
    RESEARCH_CONFIG,
    CANDIDATE_CONFIGS,
    VALIDATION_CONFIG,
)
from backtest.engine import BacktestEngine
from backtest.portfolio import Portfolio


OUTRIGHT_NQ_SYMBOL_RE = re.compile(r"^NQ[FGHJKMNQUVXZ]\d{1,2}$")


def _clock_ge(times: pd.Series, hour_min: str) -> pd.Series:
    dt = pd.to_datetime(times)
    hour, minute = [int(part) for part in hour_min.split(":", 1)]
    return (dt.dt.hour > hour) | ((dt.dt.hour == hour) & (dt.dt.minute >= minute))


def _futures_session_key(times: pd.Series) -> pd.Series:
    dt = pd.to_datetime(times)
    session = dt.dt.normalize()
    # CME equity index futures session starts at 18:00 ET; Sunday evening belongs
    # to Monday's trading session.
    session = session.mask(_clock_ge(dt, "18:00"), session + pd.Timedelta(days=1))
    return session


def select_continuous_outright_contract(df: pd.DataFrame, method: str = "prior_session_volume") -> pd.DataFrame:
    if "symbol" not in df.columns:
        return df

    work = df.copy()
    symbol = work["symbol"].astype(str)
    work = work.loc[symbol.str.match(OUTRIGHT_NQ_SYMBOL_RE)].copy()
    if work.empty:
        return work

    method = str(method or "session_volume").lower()

    def timestamp_volume_selection(frame: pd.DataFrame) -> pd.DataFrame:
        return (
            frame.sort_values(["time", "volume"], ascending=[True, False])
            .drop_duplicates(subset="time", keep="first")
            .reset_index(drop=True)
        )

    if method in ("timestamp_volume", "minute_volume", "per_timestamp"):
        return timestamp_volume_selection(work)

    if method in ("daily_volume", "prior_daily_volume", "previous_daily_volume"):
        work["_contract_bucket"] = pd.to_datetime(work["time"]).dt.normalize()
    else:
        work["_contract_bucket"] = _futures_session_key(work["time"])

    by_contract = (
        work.groupby(["_contract_bucket", "symbol"], sort=True)["volume"]
        .sum()
        .reset_index()
        .sort_values(["_contract_bucket", "volume", "symbol"], ascending=[True, False, True])
    )

    use_prior_bucket = method in (
        "prior_session_volume",
        "previous_session_volume",
        "prior_daily_volume",
        "previous_daily_volume",
    )
    if use_prior_bucket:
        ranked_symbols = {
            bucket: group["symbol"].astype(str).tolist()
            for bucket, group in by_contract.groupby("_contract_bucket", sort=True)
        }
        available_symbols = {
            bucket: set(group["symbol"].astype(str))
            for bucket, group in work.groupby("_contract_bucket", sort=True)
        }
        first_timestamp_fallback = (
            work.sort_values(["_contract_bucket", "time", "volume", "symbol"], ascending=[True, True, False, True])
            .drop_duplicates(subset="_contract_bucket", keep="first")
            .set_index("_contract_bucket")["symbol"]
            .astype(str)
            .to_dict()
        )

        selected_rows: list[dict[str, object]] = []
        buckets = list(ranked_symbols)
        for idx, bucket in enumerate(buckets):
            selected_symbol = None
            if idx > 0:
                prior_bucket = buckets[idx - 1]
                current_available = available_symbols.get(bucket, set())
                for candidate in ranked_symbols.get(prior_bucket, []):
                    if candidate in current_available:
                        selected_symbol = candidate
                        break
            if selected_symbol is None:
                selected_symbol = first_timestamp_fallback.get(bucket)
            if selected_symbol is not None:
                selected_rows.append({"_contract_bucket": bucket, "_selected_symbol": selected_symbol})
        selected = pd.DataFrame(selected_rows)
    else:
        selected = by_contract.drop_duplicates(subset="_contract_bucket", keep="first")
        selected = selected.rename(columns={"symbol": "_selected_symbol"})[["_contract_bucket", "_selected_symbol"]]

    if selected.empty:
        return timestamp_volume_selection(work.drop(columns=["_contract_bucket"], errors="ignore"))

    work = work.merge(selected, on="_contract_bucket", how="left")
    work = work.loc[work["symbol"].eq(work["_selected_symbol"])].copy()
    return (
        work.drop(columns=["_contract_bucket", "_selected_symbol"], errors="ignore")
        .sort_values(["time", "volume"], ascending=[True, False])
        .drop_duplicates(subset="time", keep="first")
        .reset_index(drop=True)
    )


def resolve_max_drawdown_pct(params: dict) -> float | None:
    if not params.get('enable_circuit_breaker', False):
        return None
    value = params.get('max_drawdown_pct')
    if value is None:
        return None
    return float(value)


def _configure_matplotlib() -> None:
    """
    Ensure matplotlib uses a writable config dir.
    This avoids hangs/slowdowns when the default dir isn't writable and/or when multiple
    processes build the font cache concurrently.
    """
    base = Path("results/.mplconfig")
    # Make this run-specific to avoid font-cache lock contention.
    run_dir = base / f"run_{os.getpid()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(run_dir.resolve()))


def slugify(value: str) -> str:
    return ''.join(char.lower() if char.isalnum() else '_' for char in str(value)).strip('_')


def build_run_label(data: pd.DataFrame, strategy_params: dict) -> str:
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if strategy_params['allow_long'] and strategy_params['allow_short']:
        sides = 'long_short'
    elif strategy_params['allow_long']:
        sides = 'long_only'
    elif strategy_params['allow_short']:
        sides = 'short_only'
    else:
        sides = 'no_sides'

    candidate_name = strategy_params.get('_candidate_name')
    if candidate_name and candidate_name != 'current':
        run_name = slugify(candidate_name)
    else:
        run_name = slugify(strategy_params.get('strategy_name', 'strategy'))

    parts = [
        timestamp,
        run_name,
        sides,
        slugify(strategy_params['entry_mode']),
        slugify(strategy_params['exit_mode']),
    ]
    return '_'.join(parts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the NQ backtest.")
    parser.add_argument(
        "--strategy",
        choices=[
            "amt_mean_reversion",
            "amt_trend",
            "amt_combined",
            "vwap_regime",
            "volume_profile_regime",
            "market_profile_cross",
            "hybrid_profile_regime_no_orb",
            "morning_va_breakout",
        ],
        help="Override strategy_name from config for this run.",
    )
    parser.add_argument(
        "--candidate",
        choices=sorted(CANDIDATE_CONFIGS),
        default="current",
        help="Apply a named research candidate override from config.",
    )
    parser.add_argument(
        "--list-candidates",
        action="store_true",
        help="Print available candidate toggles and exit.",
    )
    parser.add_argument(
        "--start",
        default=None,
        help="Optional inclusive start date for the backtest data, e.g. 2021-01-01.",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Optional inclusive end date for the backtest data, e.g. 2024-12-31.",
    )
    return parser.parse_args()


def years_covered(data: pd.DataFrame) -> float:
    times = pd.to_datetime(data['time'])
    days = (times.max() - times.min()).total_seconds() / (24 * 3600)
    return max(days / 365.25, 1.0 / 365.25)


def trades_per_year(results: dict, data: pd.DataFrame) -> float:
    if 'error' in results:
        return 0.0
    return float(results.get('total_trades', 0)) / years_covered(data)

def walk_forward_years(wf_result) -> float:
    folds = getattr(wf_result, "folds", []) if wf_result is not None else []
    total_seconds = 0.0
    for fold in folds:
        start = pd.Timestamp(fold.test_start)
        end = pd.Timestamp(fold.test_end)
        total_seconds += max(0.0, (end - start).total_seconds())
    return max(total_seconds / (365.25 * 24 * 3600), 1.0 / 365.25)

def walk_forward_trades_per_year(wf_result) -> float:
    if wf_result is None or "error" in getattr(wf_result, "stitched_results", {}):
        return 0.0
    return float(wf_result.stitched_results.get("total_trades", 0)) / walk_forward_years(wf_result)

def walk_forward_research_gate(wf_result, data: pd.DataFrame) -> tuple[bool, list[str]]:
    """
    Decide whether a candidate earned more expensive research steps.

    This deliberately uses blunt gates. If a candidate fails here, sweeps and
    permutations are usually compute theater rather than useful validation.
    """
    if wf_result is None:
        return True, []

    stitched = getattr(wf_result, "stitched_results", {})
    if not isinstance(stitched, dict) or "error" in stitched:
        reason = stitched.get("error", "walk-forward did not produce stitched results") if isinstance(stitched, dict) else "walk-forward unavailable"
        return False, [str(reason)]

    reasons: list[str] = []
    wf_tpy = walk_forward_trades_per_year(wf_result)
    min_tpy = float(VALIDATION_CONFIG.get("min_trades_per_year", 20.0))
    if wf_tpy < min_tpy:
        reasons.append(f"WF trades/year {wf_tpy:.1f} < {min_tpy:.1f}")

    wf_pf = float(stitched.get("profit_factor", 0.0))
    min_pf = float(VALIDATION_CONFIG.get("min_walk_forward_profit_factor", 1.05))
    if wf_pf < min_pf:
        reasons.append(f"WF profit factor {wf_pf:.2f} < {min_pf:.2f}")

    wf_bar_pf = float(stitched.get("bar_profit_factor", 0.0))
    min_bar_pf = float(VALIDATION_CONFIG.get("min_walk_forward_bar_profit_factor", 1.0))
    if wf_bar_pf < min_bar_pf:
        reasons.append(f"WF bar profit factor {wf_bar_pf:.2f} < {min_bar_pf:.2f}")

    wf_pnl = float(stitched.get("total_pnl", 0.0))
    min_pnl = float(VALIDATION_CONFIG.get("min_walk_forward_total_pnl", 0.0))
    if wf_pnl < min_pnl:
        reasons.append(f"WF total P&L ${wf_pnl:,.2f} < ${min_pnl:,.2f}")

    return len(reasons) == 0, reasons


def print_complete(label: str) -> None:
    print(f"{label}: complete!")


def load_data(
    filepath: str,
    continuous_contract_method: str | None = None,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    path = Path(filepath)
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        # For very large CSVs, keep parsing predictable and memory-friendly.
        df = pd.read_csv(
            path,
            low_memory=False,
        )

    # Databento format
    if 'ts_event' in df.columns:
        df['time'] = pd.to_datetime(df['ts_event'], utc=True)
        # Convert UTC to Eastern Time
        df['time'] = df['time'].dt.tz_convert('America/New_York').dt.tz_localize(None)
        if 'symbol' in df.columns:
            df = select_continuous_outright_contract(
                df,
                method=continuous_contract_method or BACKTEST_CONFIG.get("continuous_contract_method", "session_volume"),
            )
        df = df.rename(columns={'open': 'open', 'high': 'high', 'low': 'low',
                                 'close': 'close', 'volume': 'volume'})
    else:
        df.columns = df.columns.str.lower()
        if 'timestamp et' in df.columns:
            df['time'] = pd.to_datetime(df['timestamp et'])
        elif 'datetime' in df.columns:
            df['time'] = pd.to_datetime(df['datetime'])
        elif 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'])

    df = df[['time', 'open', 'high', 'low', 'close', 'volume']].sort_values('time').reset_index(drop=True)
    if start is not None:
        start_ts = pd.Timestamp(start)
        df = df.loc[df['time'].ge(start_ts)]
    if end is not None:
        end_ts = pd.Timestamp(end)
        if end_ts == end_ts.normalize():
            end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        df = df.loc[df['time'].le(end_ts)]
    df = df.reset_index(drop=True)

    # Optional cache: if user loaded CSV, write a parquet for faster subsequent loads.
    if path.suffix.lower() == ".csv":
        parquet_path = path.with_suffix(".parquet")
        if not parquet_path.exists():
            try:
                df.to_parquet(parquet_path, index=False)
                print_complete("   Cached parquet")
            except Exception:
                pass

    return df

def run_backtest(
    cli_strategy: str | None = None,
    candidate_name: str = "current",
    *,
    start: str | None = None,
    end: str | None = None,
):
    _configure_matplotlib()

    print("="*60)
    print("NQ Backtest - ORB on 5-min bars + Trend Filter")
    print("="*60)

    data_path = BACKTEST_CONFIG.get('data_path', 'data/raw/glbx-mdp3-20100606-20260428.ohlcv-1m.csv')
    if not Path(data_path).exists():
        print(f"\n❌ Data file not found: {data_path}")
        return

    print(f"\n📊 Loading data...")
    data = load_data(
        data_path,
        continuous_contract_method=BACKTEST_CONFIG.get("continuous_contract_method"),
        start=start,
        end=end,
    )
    print(f"✅ Loaded {len(data):,} 1-min bars")
    print(f"   From: {data['time'].min()}")
    print(f"   To:   {data['time'].max()}")
    if len(data) == 0:
        print("\n❌ No data after applying the requested date range.")
        return

    print(f"\n🔄 Running backtest...")
    base_params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG}
    if cli_strategy is not None:
        base_params["strategy_name"] = cli_strategy
    if candidate_name not in CANDIDATE_CONFIGS:
        raise ValueError(f"Unknown candidate: {candidate_name}")
    candidate_overrides = dict(CANDIDATE_CONFIGS[candidate_name])
    base_params = {**base_params, **candidate_overrides, "_candidate_name": candidate_name}
    print(f"  Candidate: {candidate_name}")
    if candidate_overrides:
        print(f"  Candidate overrides: {candidate_overrides}")
    print("  Preprocessing 5-min bars + indicators...")
    pre_portfolio = Portfolio(
        BACKTEST_CONFIG['starting_capital'],
        FUTURES_SPECS,
        max_drawdown_pct=resolve_max_drawdown_pct(base_params),
    )
    pre_engine = BacktestEngine(data, pre_portfolio, FUTURES_SPECS, base_params)
    pre_df = pre_engine.preprocess()
    print(f"  {len(pre_df):,} bars ready")

    def execute_scenario(label: str, overrides: dict | None = None):
        strategy_params = {**base_params, **(overrides or {})}
        portfolio = Portfolio(
            BACKTEST_CONFIG['starting_capital'],
            FUTURES_SPECS,
            max_drawdown_pct=resolve_max_drawdown_pct(strategy_params),
        )
        print(f"\n  Scenario: {label}")
        backtester = BacktestEngine(data, portfolio, FUTURES_SPECS, strategy_params)
        print("  Running execution loop...")
        results = backtester.run_on_preprocessed(pre_df)
        return strategy_params, results

    legacy_overrides = {
        'entry_mode': 'same_bar_close',
        'exit_mode': 'hybrid',
        'intrabar_exit_assumption': 'conservative',
    }

    strategy_name = str(base_params.get("strategy_name", "unknown"))
    _, baseline_results = execute_scenario(f"Legacy Baseline ({strategy_name})", legacy_overrides)
    strategy_params, results = execute_scenario(f"Improved Execution Model ({strategy_name})")

    if 'error' in results:
        print(f"\n❌ {results['error']}")
        return

    if 'error' not in baseline_results:
        print("\n" + "="*60)
        print("SCENARIO COMPARISON")
        print("="*60)
        print(f"{'Metric':<22} {'Baseline':>12} {'Improved':>12}")
        print(f"{'Total P&L':<22} ${baseline_results['total_pnl']:>11,.2f} ${results['total_pnl']:>11,.2f}")
        print(f"{'Win Rate':<22} {baseline_results['win_rate']:>11.2f}% {results['win_rate']:>11.2f}%")
        print(f"{'Profit Factor':<22} {baseline_results['profit_factor']:>12.2f} {results['profit_factor']:>12.2f}")
        print(f"{'Expectancy':<22} ${baseline_results['expectancy']:>11,.2f} ${results['expectancy']:>11,.2f}")
        print(f"{'Max Drawdown':<22} {baseline_results['max_drawdown']:>11.2f}% {results['max_drawdown']:>11.2f}%")
        print(f"{'Sharpe Ratio':<22} {baseline_results['sharpe_ratio']:>12.2f} {results['sharpe_ratio']:>12.2f}")
        print(f"{'Trades':<22} {baseline_results['total_trades']:>12} {results['total_trades']:>12}")
        print(f"{'Trades / Year':<22} {trades_per_year(baseline_results, data):>12.1f} {trades_per_year(results, data):>12.1f}")
        print("="*60)

    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    sizing_mode = strategy_params.get('position_sizing_mode', 'risk_based')
    sizing_label = sizing_mode
    if sizing_mode == 'fixed_contracts':
        sizing_label = f"{sizing_mode} ({strategy_params.get('fixed_contracts', 1)} contracts)"
    print(f"Entry Mode:          {strategy_params['entry_mode']}")
    print(f"Exit Mode:           {strategy_params['exit_mode']}")
    print(f"Intrabar Handling:   {strategy_params['intrabar_exit_assumption']}")
    print(f"Position Sizing:     {sizing_label}")
    print(f"Allowed Sides:       {'Long' if strategy_params['allow_long'] else ''}{' / ' if strategy_params['allow_long'] and strategy_params['allow_short'] else ''}{'Short' if strategy_params['allow_short'] else ''}")
    print(f"Total Trades:        {results['total_trades']}")
    print(f"Trades / Year:       {trades_per_year(results, data):.1f}")
    print(f"Winning Trades:      {results['winning_trades']}")
    print(f"Losing Trades:       {results['losing_trades']}")
    print(f"Win Rate:            {results['win_rate']:.2f}%")
    print(f"\nTotal P&L:           ${results['total_pnl']:,.2f}")
    print(f"Avg Win:             ${results['avg_win']:,.2f}")
    print(f"Avg Loss:            ${results['avg_loss']:,.2f}")
    print(f"Profit Factor:       {results['profit_factor']:.2f}")
    print(f"Expectancy:          ${results['expectancy']:,.2f}")
    print(f"Bar Profit Factor:   {results.get('bar_profit_factor', 0.0):.2f}")
    print(f"Bar Sharpe Ratio:    {results.get('bar_sharpe_ratio', 0.0):.2f}")
    print(f"Bar Exposure:        {results.get('bar_exposure_pct', 0.0):.2f}%")
    print(f"\nFinal Equity:        ${results['final_equity']:,.2f}")
    print(f"Return:              {results['return_pct']:.2f}%")
    print(f"Sharpe Ratio:        {results['sharpe_ratio']:.2f}")
    print(f"Calmar Ratio:        {results['calmar_ratio']:.2f}")
    print(f"Max Drawdown:        {results['max_drawdown']:.2f}%")
    print(f"\nBest Trade:          ${results['best_trade']:,.2f}")
    print(f"Worst Trade:         ${results['worst_trade']:,.2f}")
    print(f"Avg Hold Time:       {results['avg_hold_minutes']:.1f} mins")
    print(f"Max Consec. Wins:    {results['max_consec_wins']}")
    print(f"Max Consec. Losses:  {results['max_consec_losses']}")
    print(f"\nLong Trades:         {results['long_trades']} ({results['long_win_rate']:.1f}% win)")
    print(f"Long P&L:            ${results['long_total_pnl']:,.2f}  PF {results['long_profit_factor']:.2f}")
    print(f"Short Trades:        {results['short_trades']} ({results['short_win_rate']:.1f}% win)")
    print(f"Short P&L:           ${results['short_total_pnl']:,.2f}  PF {results['short_profit_factor']:.2f}")
    if results.get('circuit_breaker_triggered'):
        print(f"\n⚠️  CIRCUIT BREAKER TRIGGERED — trading halted at {strategy_params.get('max_drawdown_pct', 0.25)*100:.0f}% drawdown")
    print("="*60)

    run_label = build_run_label(data, strategy_params)
    run_dir = Path("results/runs") / run_label
    (run_dir / "trades").mkdir(parents=True, exist_ok=True)
    (run_dir / "charts").mkdir(parents=True, exist_ok=True)
    (run_dir / "simulations").mkdir(parents=True, exist_ok=True)
    (run_dir / "research").mkdir(parents=True, exist_ok=True)

    Path("results").mkdir(parents=True, exist_ok=True)
    Path("results/latest.txt").write_text(f"{run_label}\n", encoding="utf-8")

    trade_log_path = run_dir / "trades" / "trade_log.csv"
    results['trades'].to_csv(trade_log_path, index=False)
    print_complete("\nRun folder")
    print_complete("Trade log")

    from results.analysis import (
        export_conditional_distribution_report,
        export_robustness_reports,
        export_trade_summaries,
    )
    from backtest.market_memory import export_market_memory_report
    from backtest.vwap_research import export_vwap_repricing_report
    summary_paths = export_trade_summaries(
        results["trades"],
        out_dir=run_dir / "research" / "summaries",
        artifact_name="trade_summary",
    )
    print_complete("Trade summaries")

    try:
        from backtest.execution_realism import export_execution_realism_report

        export_execution_realism_report(
            results["trades"],
            out_dir=run_dir / "research" / "execution_realism",
            futures_specs=FUTURES_SPECS,
            strategy_params=strategy_params,
            artifact_name="execution_realism",
        )
        print_complete("Execution realism report")
    except Exception as e:
        print(f"   ⚠️ Execution realism report skipped: {e}")

    robustness_paths = export_robustness_reports(
        results["trades"],
        out_dir=run_dir / "research" / "robustness",
        artifact_name="robustness",
        starting_capital=BACKTEST_CONFIG["starting_capital"],
    )
    print_complete("Robustness diagnostics")

    if RESEARCH_CONFIG.get("enable_prop_firm_report", True):
        try:
            from backtest.prop_firm import export_prop_firm_report

            prop_paths = export_prop_firm_report(
                results["trades"],
                out_dir=run_dir / "research" / "prop_firm",
                artifact_name="prop_firm",
                sample_scope="development_in_sample",
                profiles=list(RESEARCH_CONFIG.get("prop_firm_profiles", [])),
                n_sims=int(RESEARCH_CONFIG.get("prop_firm_n_sims", 5000)),
                seed=int(RESEARCH_CONFIG.get("prop_firm_seed", 17)),
                enable_surfaces=bool(RESEARCH_CONFIG.get("enable_prop_firm_surfaces", True)),
                surface_n_sims=int(RESEARCH_CONFIG.get("prop_firm_surface_n_sims", 1000)),
            )
            print_complete("Prop-firm evaluation diagnostics")
        except Exception as e:
            print(f"   ⚠️ Prop-firm report skipped: {e}")

    if RESEARCH_CONFIG.get("enable_vwap_repricing_report", True):
        vwap_paths = export_vwap_repricing_report(
            pre_df,
            out_dir=run_dir / "research" / "vwap_repricing",
            artifact_name="vwap_repricing",
            rth_start=str(strategy_params.get("rth_start", "09:30")),
            rth_end=str(strategy_params.get("rth_end", "16:00")),
            period=str(RESEARCH_CONFIG.get("vwap_repricing_period", "Q")),
            midday_start=str(RESEARCH_CONFIG.get("vwap_repricing_midday_start", "12:00")),
            midday_end=str(RESEARCH_CONFIG.get("vwap_repricing_midday_end", "15:00")),
        )
        print_complete("VWAP repricing diagnostics")

    if RESEARCH_CONFIG.get("enable_market_memory_report", True):
        memory_paths = export_market_memory_report(
            pre_df,
            out_dir=run_dir / "research" / "market_memory",
            artifact_name="market_memory",
            period=str(RESEARCH_CONFIG.get("market_memory_report_period", "Q")),
            forward_horizon_bars=int(RESEARCH_CONFIG.get("market_memory_report_forward_horizon_bars", 3)),
            recent_fraction=float(RESEARCH_CONFIG.get("market_memory_report_recent_fraction", 0.25)),
            drift_warning_threshold=float(RESEARCH_CONFIG.get("market_memory_report_drift_warning_threshold", 0.75)),
        )
        print_complete("Market memory diagnostics")

    if RESEARCH_CONFIG.get("enable_conditional_distribution_reports", True):
        conditional_paths = export_conditional_distribution_report(
            results["trades"],
            out_dir=run_dir / "research" / "conditional_distributions",
            artifact_name="conditional_distributions",
            min_trades=int(RESEARCH_CONFIG.get("conditional_distribution_min_trades", 30)),
            min_periods=int(RESEARCH_CONFIG.get("conditional_distribution_min_periods", 3)),
            period=str(RESEARCH_CONFIG.get("conditional_distribution_period", "Q")),
            n_bootstrap=int(RESEARCH_CONFIG.get("conditional_distribution_bootstrap_samples", 300)),
            random_seed=int(RESEARCH_CONFIG.get("conditional_distribution_random_seed", 7)),
            max_groups_per_set=int(RESEARCH_CONFIG.get("conditional_distribution_max_groups_per_set", 80)),
        )
        print_complete("Conditional distribution diagnostics")

    if RESEARCH_CONFIG.get("enable_cusum_event_study", True):
        try:
            from backtest.event_sampling import export_cusum_event_study

            event_paths = export_cusum_event_study(
                pre_df,
                out_dir=run_dir / "research" / "events",
                artifact_name="cusum_events",
                horizons_bars=tuple(RESEARCH_CONFIG.get("cusum_event_study_horizons_bars", [1, 3, 6, 12, 24])),
                threshold_atr_multiple=float(strategy_params.get("cusum_event_atr_multiple", 1.0)),
                min_threshold_points=float(strategy_params.get("cusum_event_min_threshold_points", 0.25)),
                frequency_thresholds=tuple(RESEARCH_CONFIG.get("cusum_event_frequency_thresholds", [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0])),
                random_baseline_samples=int(RESEARCH_CONFIG.get("cusum_event_random_baseline_samples", 200)),
                random_seed=7,
            )
            print_complete("CUSUM candle-sampling study")
        except Exception as e:
            print(f"   ⚠️ CUSUM event study skipped: {e}")

    if RESEARCH_CONFIG.get("enable_feature_research_lab", True):
        try:
            from backtest.feature_research import run_feature_research_lab

            feature_paths = run_feature_research_lab(
                pre_df,
                out_dir=run_dir / "research" / "feature_lab",
                artifact_name="feature_research",
                horizons_bars=tuple(RESEARCH_CONFIG.get("feature_research_horizons_bars", [1, 3, 6, 12, 24])),
                target_atr_multiple=float(RESEARCH_CONFIG.get("feature_research_target_atr_multiple", 1.0)),
                stop_atr_multiple=float(RESEARCH_CONFIG.get("feature_research_stop_atr_multiple", 1.0)),
                max_hold_bars=int(RESEARCH_CONFIG.get("feature_research_max_hold_bars", 24)),
                bootstrap_samples=int(RESEARCH_CONFIG.get("feature_research_bootstrap_samples", 300)),
                min_events=int(RESEARCH_CONFIG.get("feature_research_min_events", 30)),
                random_seed=7,
            )
            print_complete("Feature research lab")
        except Exception as e:
            print(f"   ⚠️ Feature research lab skipped: {e}")

    print(f"\n📊 Generating charts...")
    from results.visualize import plot_results
    from results.visualize import plot_diagnostics
    plot_paths = plot_results(
        results,
        BACKTEST_CONFIG['starting_capital'],
        artifact_name="backtest",
        base_dir=run_dir,
    )
    diagnostics = plot_diagnostics(
        results,
        BACKTEST_CONFIG["starting_capital"],
        artifact_name=run_label,
        base_dir=run_dir,
    )
    print_complete("Charts")

    stress = None
    if RESEARCH_CONFIG.get("enable_monte_carlo", False):
        print(f"\n🎲 Running Monte Carlo simulations...")
        try:
            from backtest.simulations import (
                run_execution_delay_stress_tests,
                run_advanced_monte_carlo,
                run_monte_carlo,
                run_trade_stress_tests,
            )
            n_sims = int(RESEARCH_CONFIG.get("monte_carlo_n_sims", 2000))
            mc_modes = list(RESEARCH_CONFIG.get("monte_carlo_bootstrap_modes", ["trade", "day", "week", "month"]))
            mc_summaries = {}
            for mode in mc_modes:
                mc_summaries[str(mode)] = run_monte_carlo(
                    results,
                    starting_capital=BACKTEST_CONFIG['starting_capital'],
                    artifact_name="mc",
                    n_sims=n_sims,
                    bootstrap_mode=str(mode),
                    seed=7,
                    out_dir=run_dir / "simulations",
                    max_paths_to_plot=int(RESEARCH_CONFIG.get("monte_carlo_paths_shown", 200)),
                )

            advanced_mc = None
            if RESEARCH_CONFIG.get("enable_advanced_monte_carlo", True):
                advanced_mc = run_advanced_monte_carlo(
                    results,
                    starting_capital=BACKTEST_CONFIG["starting_capital"],
                    artifact_name="mc",
                    n_sims=int(RESEARCH_CONFIG.get("advanced_monte_carlo_n_sims", n_sims)),
                    seed=11,
                    out_dir=run_dir / "simulations",
                    regime_col=RESEARCH_CONFIG.get("advanced_monte_carlo_regime_col", "entry_day_regime"),
                    transition_smoothing=float(RESEARCH_CONFIG.get("advanced_monte_carlo_transition_smoothing", 1.0)),
                    student_t_df=float(RESEARCH_CONFIG.get("advanced_monte_carlo_student_t_df", 5.0)),
                    path_horizons=tuple(RESEARCH_CONFIG.get("advanced_monte_carlo_path_horizons", [40, 100, 250, 500, 1000])),
                    drawdown_barriers_pct=tuple(RESEARCH_CONFIG.get("advanced_monte_carlo_drawdown_barriers_pct", [5, 10, 15, 20, 25])),
                    profit_target_pct=float(RESEARCH_CONFIG.get("advanced_monte_carlo_profit_target_pct", 8.0)),
                    drawdown_limit_pct=float(RESEARCH_CONFIG.get("advanced_monte_carlo_drawdown_limit_pct", 5.0)),
                )

            if RESEARCH_CONFIG.get("enable_trade_stress_tests", True):
                stress = run_trade_stress_tests(
                    results,
                    starting_capital=BACKTEST_CONFIG['starting_capital'],
                    artifact_name="stress",
                    out_dir=run_dir / "simulations",
                )
            delay_stress = None
            if RESEARCH_CONFIG.get("enable_execution_delay_stress_tests", True):
                delay_stress = run_execution_delay_stress_tests(
                    pre_df=pre_df,
                    raw_data=data,
                    futures_specs=FUTURES_SPECS,
                    base_params=strategy_params,
                    starting_capital=BACKTEST_CONFIG["starting_capital"],
                    delay_bars=list(RESEARCH_CONFIG.get("execution_delay_stress_bars", [0, 1, 2, 3])),
                    artifact_name="stress",
                    out_dir=run_dir / "simulations",
                )

            print("\n" + "=" * 60)
            print("MONTE CARLO (BOOTSTRAP) SUMMARY")
            print("=" * 60)
            for mode, summary in mc_summaries.items():
                print(f"{mode.title()}-bootstrap final equity percentiles ($):", summary.final_equity_percentiles)
                print(f"{mode.title()}-bootstrap max drawdown percentiles (%):", summary.max_drawdown_percentiles)
            print_complete("Monte Carlo charts")
            if stress is not None:
                print_complete("Stress tests")
            if advanced_mc is not None:
                print_complete("Advanced Monte Carlo")
            if delay_stress is not None:
                print_complete("Execution delay stress")
        except Exception as e:
            print(f"   ⚠️ Monte Carlo skipped: {e}")

    wf_result = None
    insample_perm = None
    wf_perm = None
    wf_gate_passed = True
    wf_gate_reasons: list[str] = []

    # Research tooling: walk-forward, permutation tests, and/or parameter sweep heatmaps.
    try:
        if RESEARCH_CONFIG.get("enable_walk_forward", False):
            print(f"\n🧪 Running walk-forward analysis...")
            from backtest.walkforward import run_walk_forward

            wf_result = run_walk_forward(
                pre_df=pre_df,
                raw_data=data,
                futures_specs=FUTURES_SPECS,
                base_params=base_params,
                starting_capital=BACKTEST_CONFIG["starting_capital"],
                train_years=int(RESEARCH_CONFIG.get("wf_train_years", 4)),
                test_months=int(RESEARCH_CONFIG.get("wf_test_months", 6)),
                step_months=int(RESEARCH_CONFIG.get("wf_step_months", 6)),
                window_mode=str(RESEARCH_CONFIG.get("wf_window_mode", "rolling")),
                purge_bars=RESEARCH_CONFIG.get("wf_purge_bars", "auto"),
                embargo_bars=int(RESEARCH_CONFIG.get("wf_embargo_bars", 0)),
                metric=str(RESEARCH_CONFIG.get("wf_metric", "sharpe")),
                min_trades_train=int(RESEARCH_CONFIG.get("wf_min_trades_train", 40)),
                min_trades_test=int(RESEARCH_CONFIG.get("wf_min_trades_test", 5)),
                param_grid=base_params.get("wf_param_grid", RESEARCH_CONFIG.get("wf_param_grid")),
                seed=7,
                n_random_samples=base_params.get("wf_random_samples", RESEARCH_CONFIG.get("wf_random_samples", 50)),
                out_dir=run_dir / "research" / "walkforward",
                artifact_name="walkforward",
                selection_mode=str(base_params.get("wf_selection_mode", RESEARCH_CONFIG.get("wf_selection_mode", "stable"))),
            )

            if "error" in wf_result.stitched_results:
                print(f"   ⚠️ Walk-forward: {wf_result.stitched_results['error']}")
            else:
                print("\n" + "=" * 60)
                print("WALK-FORWARD (STITCHED OOS) SUMMARY")
                print("=" * 60)
                print(f"Folds:        {len(wf_result.folds)}")
                print(f"Trades:       {wf_result.stitched_results['total_trades']}")
                print(f"Trades/year:  {walk_forward_trades_per_year(wf_result):.1f}")
                print(f"Total P&L:    ${wf_result.stitched_results['total_pnl']:,.2f}")
                print(f"Final equity: ${wf_result.stitched_results['final_equity']:,.2f}")
                print(f"Win rate:     {wf_result.stitched_results['win_rate']:.2f}%")
                print(f"Profit factor:{wf_result.stitched_results['profit_factor']:.2f}")
                print(f"Sharpe ratio: {wf_result.stitched_results['sharpe_ratio']:.2f}")
                print(f"Bar PF:       {wf_result.stitched_results.get('bar_profit_factor', 0.0):.2f}")
                print(f"Bar Sharpe:   {wf_result.stitched_results.get('bar_sharpe_ratio', 0.0):.2f}")
                print(f"Max drawdown: {wf_result.stitched_results['max_drawdown']:.2f}%")
                print_complete("Walk-forward exports")
                wf_summary_paths = export_trade_summaries(
                    wf_result.stitched_trades,
                    out_dir=run_dir / "research" / "walkforward" / "summaries",
                    artifact_name="walkforward_stitched",
                )
                print_complete("WF trade summaries")
                wf_robustness_paths = export_robustness_reports(
                    wf_result.stitched_trades,
                    out_dir=run_dir / "research" / "walkforward" / "robustness",
                    artifact_name="walkforward_stitched",
                    starting_capital=BACKTEST_CONFIG["starting_capital"],
                )
                print_complete("WF robustness diagnostics")
                if RESEARCH_CONFIG.get("enable_conditional_distribution_reports", True):
                    wf_conditional_paths = export_conditional_distribution_report(
                        wf_result.stitched_trades,
                        out_dir=run_dir / "research" / "walkforward" / "conditional_distributions",
                        artifact_name="walkforward_stitched",
                        min_trades=int(RESEARCH_CONFIG.get("conditional_distribution_min_trades", 30)),
                        min_periods=int(RESEARCH_CONFIG.get("conditional_distribution_min_periods", 3)),
                        period=str(RESEARCH_CONFIG.get("conditional_distribution_period", "Q")),
                        n_bootstrap=int(RESEARCH_CONFIG.get("conditional_distribution_bootstrap_samples", 300)),
                        random_seed=int(RESEARCH_CONFIG.get("conditional_distribution_random_seed", 7)),
                        max_groups_per_set=int(RESEARCH_CONFIG.get("conditional_distribution_max_groups_per_set", 80)),
                    )
                    print_complete("WF conditional distributions")
                if RESEARCH_CONFIG.get("enable_prop_firm_report", True):
                    try:
                        from backtest.prop_firm import export_prop_firm_report

                        wf_prop_paths = export_prop_firm_report(
                            wf_result.stitched_trades,
                            out_dir=run_dir / "research" / "walkforward" / "prop_firm",
                            artifact_name="walkforward_stitched",
                            sample_scope="walkforward_oos",
                            profiles=list(RESEARCH_CONFIG.get("prop_firm_profiles", [])),
                            n_sims=int(RESEARCH_CONFIG.get("prop_firm_n_sims", 5000)),
                            seed=int(RESEARCH_CONFIG.get("prop_firm_seed", 17)),
                            enable_surfaces=bool(RESEARCH_CONFIG.get("enable_prop_firm_surfaces", True)),
                            surface_n_sims=int(RESEARCH_CONFIG.get("prop_firm_surface_n_sims", 1000)),
                        )
                        print_complete("WF prop-firm diagnostics")
                    except Exception as e:
                        print(f"   ⚠️ WF prop-firm report skipped: {e}")

            wf_gate_passed, wf_gate_reasons = walk_forward_research_gate(wf_result, data)
            if not wf_gate_passed:
                print("\n🚦 Walk-forward research gate: FAIL")
                for reason in wf_gate_reasons:
                    print(f"   - {reason}")
                print("   Expensive research steps can be skipped for this candidate.")
            else:
                print("\n🚦 Walk-forward research gate: PASS")

        if RESEARCH_CONFIG.get("enable_permutation_tests", False):
            if RESEARCH_CONFIG.get("skip_permutation_on_failed_walk_forward", True) and not wf_gate_passed:
                print("\n🧪 Permutation validation skipped: walk-forward research gate failed.")
            else:
                print(f"\n🧪 Running permutation validation...")
                from backtest.permutation import (
                    run_in_sample_permutation_test,
                    run_walk_forward_permutation_test,
                )

                permutation_metric = str(RESEARCH_CONFIG.get("permutation_metric", RESEARCH_CONFIG.get("wf_metric", "profit_factor")))
                permutation_dir = run_dir / "research" / "permutation"
                permutation_param_grid = base_params.get("wf_param_grid", RESEARCH_CONFIG.get("wf_param_grid"))
                if not permutation_param_grid:
                    raise ValueError("Permutation tests require RESEARCH_CONFIG['wf_param_grid'].")

                if RESEARCH_CONFIG.get("permutation_enable_in_sample", True):
                    print("   In-sample permutation test...")
                    insample_perm = run_in_sample_permutation_test(
                        raw_data=data,
                        futures_specs=FUTURES_SPECS,
                        base_params=base_params,
                        starting_capital=BACKTEST_CONFIG["starting_capital"],
                        param_grid=permutation_param_grid,
                        metric=permutation_metric,
                        min_trades=int(RESEARCH_CONFIG.get("wf_min_trades_train", 40)),
                        n_permutations=int(RESEARCH_CONFIG.get("permutation_in_sample_n", 100)),
                        seed=7,
                        n_random_samples=RESEARCH_CONFIG.get("wf_random_samples", 50),
                        out_dir=permutation_dir,
                        artifact_name="insample_permutation",
                        selection_mode=str(RESEARCH_CONFIG.get("wf_selection_mode", "stable")),
                    )
                    print(
                        f"   In-sample p={insample_perm.p_value:.4f} "
                        f"real_{permutation_metric}={insample_perm.real_metric:.4f}"
                    )
                    print_complete("   In-sample permutation")

                if RESEARCH_CONFIG.get("permutation_enable_walk_forward", True):
                    print("   Walk-forward permutation test...")
                    wf_perm = run_walk_forward_permutation_test(
                        raw_data=data,
                        pre_df=pre_df,
                        futures_specs=FUTURES_SPECS,
                        base_params=base_params,
                        starting_capital=BACKTEST_CONFIG["starting_capital"],
                        param_grid=permutation_param_grid,
                        real_walk_forward=wf_result,
                        train_years=int(RESEARCH_CONFIG.get("wf_train_years", 4)),
                        test_months=int(RESEARCH_CONFIG.get("wf_test_months", 6)),
                        step_months=int(RESEARCH_CONFIG.get("wf_step_months", 6)),
                        window_mode=str(RESEARCH_CONFIG.get("wf_window_mode", "rolling")),
                        purge_bars=RESEARCH_CONFIG.get("wf_purge_bars", "auto"),
                        embargo_bars=int(RESEARCH_CONFIG.get("wf_embargo_bars", 0)),
                        metric=permutation_metric,
                        min_trades_train=int(RESEARCH_CONFIG.get("wf_min_trades_train", 40)),
                        min_trades_test=int(RESEARCH_CONFIG.get("wf_min_trades_test", 5)),
                        min_trades_total=int(RESEARCH_CONFIG.get("permutation_min_trades_total", 30)),
                        n_permutations=int(RESEARCH_CONFIG.get("permutation_walk_forward_n", 25)),
                        seed=7,
                        n_random_samples=RESEARCH_CONFIG.get("wf_random_samples", 50),
                        out_dir=permutation_dir,
                        artifact_name="walkforward_permutation",
                        selection_mode=str(RESEARCH_CONFIG.get("wf_selection_mode", "stable")),
                    )
                    print(
                        f"   Walk-forward p={wf_perm.p_value:.4f} "
                        f"real_{permutation_metric}={wf_perm.real_metric:.4f}"
                    )
                    print_complete("   Walk-forward permutation")

        if RESEARCH_CONFIG.get("enable_param_sweep", False):
            if RESEARCH_CONFIG.get("skip_sweeps_on_failed_walk_forward", True) and not wf_gate_passed:
                print("\n🧪 Parameter sweeps skipped: walk-forward research gate failed.")
            else:
                print(f"\n🧪 Running parameter sweep heatmap...")
                from backtest.sweep import run_2d_sweep

                sweep_specs = base_params.get("sweep_specs", RESEARCH_CONFIG.get("sweep_specs"))
                if not sweep_specs:
                    sweep_specs = [
                        {
                            "name": "sweep",
                            "x_param": str(RESEARCH_CONFIG.get("sweep_x_param")),
                            "x_values": list(RESEARCH_CONFIG.get("sweep_x_values", [])),
                            "y_param": str(RESEARCH_CONFIG.get("sweep_y_param")),
                            "y_values": list(RESEARCH_CONFIG.get("sweep_y_values", [])),
                            "metric": str(RESEARCH_CONFIG.get("sweep_metric", "sharpe")),
                            "min_trades": int(RESEARCH_CONFIG.get("sweep_min_trades", 30)),
                        }
                    ]

                for spec in sweep_specs:
                    sweep = run_2d_sweep(
                        pre_df=pre_df,
                        raw_data=data,
                        futures_specs=FUTURES_SPECS,
                        base_params=base_params,
                        starting_capital=BACKTEST_CONFIG["starting_capital"],
                        x_param=str(spec.get("x_param")),
                        x_values=list(spec.get("x_values", [])),
                        y_param=str(spec.get("y_param")),
                        y_values=list(spec.get("y_values", [])),
                        metric=str(spec.get("metric", "sharpe")),
                        min_trades=int(spec.get("min_trades", RESEARCH_CONFIG.get("sweep_min_trades", 30))),
                        artifact_name=str(spec.get("name", "sweep")),
                        out_dir=run_dir / "research" / "sweeps" / str(spec.get("name", "sweep")),
                    )
                    print_complete(f"   Parameter sweep {spec.get('name', 'sweep')}")

    except Exception as e:
        print(f"\n   ⚠️ Research tooling skipped: {e}")

    try:
        from backtest.validation import export_development_report

        report = export_development_report(
            results=results,
            years=years_covered(data),
            out_dir=run_dir / "research",
            validation_config=VALIDATION_CONFIG,
            walk_forward_result=wf_result,
            walk_forward_years=walk_forward_years(wf_result) if wf_result is not None else None,
            in_sample_permutation=insample_perm,
            walk_forward_permutation=wf_perm,
            stress_summary_csv=getattr(stress, "summary_csv", None),
        )
        print_complete("\nDevelopment report")
    except Exception as e:
        print(f"\n   ⚠️ Development report skipped: {e}")

    try:
        if wf_result is not None:
            from backtest.validation import export_optimization_stability_report

            export_optimization_stability_report(
                wf_result,
                out_dir=run_dir / "research",
                validation_config=VALIDATION_CONFIG,
                metric=str(RESEARCH_CONFIG.get("wf_metric", "bar_profit_factor")),
            )
            print_complete("Optimization stability report")
    except Exception as e:
        print(f"\n   ⚠️ Optimization stability report skipped: {e}")

    try:
        from backtest.validation import export_multiple_testing_debt_report

        export_multiple_testing_debt_report(
            candidate_name=candidate_name,
            candidate_configs=CANDIDATE_CONFIGS,
            out_dir=run_dir / "research",
            research_config=RESEARCH_CONFIG,
            results_root=Path("results/runs"),
        )
        print_complete("Multiple-testing debt report")
    except Exception as e:
        print(f"\n   ⚠️ Multiple-testing debt report skipped: {e}")

    try:
        from backtest.validation import export_research_discipline_report

        export_research_discipline_report(
            run_dir=run_dir,
            validation_config=VALIDATION_CONFIG,
            research_config=RESEARCH_CONFIG,
        )
        print_complete("Research discipline gate")
    except Exception as e:
        print(f"\n   ⚠️ Research discipline gate skipped: {e}")

    try:
        from results.research_dashboards import export_research_dashboards

        export_research_dashboards(run_dir, results_root=Path("results/runs"))
        print_complete("\nResearch dashboards")
    except Exception as e:
        print(f"\n   ⚠️ Research dashboard export skipped: {e}")

    if RESEARCH_CONFIG.get("enable_research_animations", True):
        try:
            from results.research_animations import export_research_animations

            export_research_animations(
                run_dir,
                frames=int(RESEARCH_CONFIG.get("research_animation_frames", 48)),
                fps=int(RESEARCH_CONFIG.get("research_animation_fps", 12)),
                dpi=int(RESEARCH_CONFIG.get("research_animation_dpi", 110)),
            )
            print_complete("\nResearch animations")
        except Exception as e:
            print(f"\n   ⚠️ Research animation export skipped: {e}")

if __name__ == "__main__":
    args = parse_args()
    if args.list_candidates:
        print("Available candidates:")
        for name, overrides in sorted(CANDIDATE_CONFIGS.items()):
            print(f"  {name}: {overrides}")
    else:
        run_backtest(
            cli_strategy=args.strategy,
            candidate_name=args.candidate,
            start=args.start,
            end=args.end,
        )
