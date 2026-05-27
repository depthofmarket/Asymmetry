# Script Map

Scripts are command-line entry points. Put reusable behavior in `backtest/`, then call it from here.

## Live And Paper

- `run_paper_trader.py`: historical replay through the live-style paper runtime.
- `run_amp_paper_trader.py`: AMP/CQG-oriented replay, tail, audit-broker, and guarded CQG scaffold.
- `run_live_paper.sh`: local delayed live-paper runner.
- `fetch_live_bars.py`: writes delayed live bars for tail mode.
- `check_live_parity.py`: compares backtest trades with paper replay trades.
- `check_cqg_setup.py`: validates local CQG environment setup.
- `check_prop_research_gate.py`: validates saved prop-firm research artifacts before approved/funded mode.
- `check_research_freeze.py`: writes/verifies the frozen candidate manifest and evaluates saved development or lockbox runs against pre-declared gates.
- `run_ib_markov_regime_bot.py`: IBKR regime monitor; does not place orders.

## Data Preparation

- `prepare_options_nq.py`: prepares raw NQ options archives.
- `build_options_flow_features.py`: builds daily options-flow confluence features, DTE-bucket dashboards, and by-date/by-strike GEX surfaces.
- `export_prepared_signal_csv.py`: exports point-in-time strategy signals and context to a prepared CSV for the pre-candidate signal gate; it does not execute trades.
- `export_liquidity_absorption_signal_csv.py`: exports the pre-candidate liquidity absorption / failed-continuation signal; it does not execute trades or create a candidate.
- `export_compression_breakout_signal_csv.py`: exports the pre-candidate opening compression breakout continuation signal; it does not execute trades or create a candidate.
- `export_gap_go_signal_csv.py`: exports the pre-candidate RTH gap-and-go opening-range continuation signal; it does not execute trades or create a candidate.
- `export_power_hour_signal_csv.py`: exports the pre-candidate power-hour accepted-trend continuation signal; it does not execute trades or create a candidate.
- `export_options_gamma_wall_signal_csv.py`: exports the pre-candidate positive-gamma wall reversion signal with point-in-time options-flow features; it does not execute trades or create a candidate.
- `build_aggressive_flow_stats.py`: builds realized trade-side aggressive-flow minute/daily stats from Databento `trades` archives. Keeps raw `A`/`B` side columns for bid/ask convention audit.

## Research And Diagnostics

- `probe_candidate_frequency.py`: signal/trade frequency scans.
- `audit_bar_exposure.py`: reconstructs saved-run signal-bar and execution-bar exposure from trade logs and bars to diagnose trade-PF vs bar-PF disagreement.
- `audit_fill_assumptions.py`: joins saved trades to execution bars to flag touch-only targets, same-minute exits, and lower-bound stop/target ordering ambiguity.
- `audit_execution_realism.py`: builds saved trade-log sensitivity reports for target-fill and slippage assumptions.
- `build_tbbo_execution_stats.py`: builds and optionally merges NQ futures TBBO spread/depth/trade-vs-mid execution stats for fill realism checks.
- `audit_tbbo_execution_baseline.py`: summarizes processed TBBO minute stats into active-contract execution-cost baseline reports without joining to strategy trades.
- `audit_trades_with_tbbo.py`: joins a saved run's `trades/trade_log.csv` to processed TBBO stats and writes execution-cost audit reports.
- `run_prop_attempt_portfolio.py`: turns saved prop-firm summary/funded-simulation artifacts into multi-account attempt economics and optional Kelly account sizing; it does not run a backtest.
- `check_research_protocol.py`: writes/verifies the agentic research-control manifest, LLM/evaluation blinding checks, config/file fingerprints, and saved-artifact protocol gate. It does not run a backtest.
- `run_feature_research_lab.py`: feature-event research reports.
- `run_signal_research_report.py`: pre-candidate IC, forward-return, event-signal, stability, context, and cost-stress signal gate from a prepared signal CSV. Use `--entry-price-col open --entry-lag-bars 1 --exit-price-col close` for next-bar-open research.
- `run_temporal_signal_research_report.py`: temporal pre-candidate gate across fixed eras; default splits are 2010-2015 legacy context, 2016-2020 transition support, and 2021-2024 recent development. Includes legacy IC eligibility, sparse-event eligibility, and cost-stress survival.
- `export_cusum_event_study.py`: CUSUM event-study export.
- `export_research_animations.py`: research animation export.
- `run_market_profile_placebo.py`: market-profile placebo test.
- `run_advanced_monte_carlo.py`: advanced Monte Carlo diagnostics.
- `backfill_run_research.py`: backfills research artifacts for existing runs.

## Batch Runs

- `run_edge_candidates_batch.sh`
- `run_next_vp_candidates_batch.sh`
- `run_2021_frequency_candidates_batch.sh`
- `run_market_profile_first_batch.sh`
- `run_market_profile_remaining_batch.sh`

Do not run backtests from automation without explicit user instruction. Broad batch scripts require `ALLOW_BACKTEST_BATCH=1` and should be treated as reproduction tools while the active validation queue is empty. When a backtest is useful, provide the command for the user to run.
