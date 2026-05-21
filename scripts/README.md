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
- `build_options_flow_features.py`: builds options-flow confluence features.
- `export_prepared_signal_csv.py`: exports point-in-time strategy signals and context to a prepared CSV for the pre-candidate signal gate; it does not execute trades.

## Research And Diagnostics

- `probe_candidate_frequency.py`: signal/trade frequency scans.
- `audit_bar_exposure.py`: reconstructs saved-run signal-bar and execution-bar exposure from trade logs and bars to diagnose trade-PF vs bar-PF disagreement.
- `audit_fill_assumptions.py`: joins saved trades to execution bars to flag touch-only targets, same-minute exits, and lower-bound stop/target ordering ambiguity.
- `audit_execution_realism.py`: builds saved trade-log sensitivity reports for target-fill and slippage assumptions.
- `build_tbbo_execution_stats.py`: builds NQ futures TBBO spread/depth/trade-vs-mid execution stats for fill realism checks.
- `audit_trades_with_tbbo.py`: joins a saved run's `trades/trade_log.csv` to processed TBBO stats and writes execution-cost audit reports.
- `run_feature_research_lab.py`: feature-event research reports.
- `run_signal_research_report.py`: pre-candidate IC, forward-return, stability, and context signal gate from a prepared signal CSV.
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
