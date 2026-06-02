# NQ Scalper Backtest

Production-grade backtesting framework for NQ futures trading strategies.

## Features
- Mean reversion & breakout strategies
- Monte Carlo stress testing
- Walk-forward analysis
- In-sample and walk-forward permutation validation
- Bar-level objective metrics for denser strategy scoring
- Development pass/fail reports for validation gates
- Conditional PnL distribution diagnostics with bootstrap and period-stability checks
- Paper-style VWAP repricing diagnostics using prior-bar close vs RTH VWAP
- Point-in-time Markov volatility-regime overlay
- Point-in-time market-memory diagnostics: Hurst, entropy, Lempel-Ziv, tail risk, and Wasserstein drift
- Point-in-time options-flow features: OI, cleared volume, IV, Greeks, GEX/DEX, gamma-wall confluence
- Confirmed directional-change market-structure features
- Rolling market-profile support/resistance levels
- Realistic commissions & slippage
- Performance metrics (Sharpe, Sortino, max drawdown)
- Live-style paper execution runtime with simulated local fills
- Execution-observation logs for paper/replay decisions, skipped entries, and shortfall summaries
- Pre-candidate signal research gate for IC, forward-return, stability, and context evidence
- Live prop-firm guard/ledger for compliant eval and payout-rule paper runs

## Setup
1. Install: `pip install -r requirements.txt`
2. Add NQ data to `data/raw/`
3. For orientation, run `python3 main_backtest.py --list-candidates`; run historical backtests only from an explicit research command.

## Codebase Layout
- Start with `docs/codebase_map.md` for the repo map.
- Reusable strategy and runtime code lives under `backtest/`; see `backtest/README.md`.
- Command-line entry points live under `scripts/`; see `scripts/README.md`.
- Live-style paper execution code lives in `backtest/live.py` and the related `backtest/live_*.py` adapters.
- Historical backtest commands are listed below for you to run in your terminal when needed.

## Candidate Runs
There is currently no active validation candidate. Commands below are historical/reproduction entry points, not an active research queue.
Backtests, full-dataset probes, full-sample signal scans, and candidate sweeps are user-run only unless explicitly approved for automation.

- List variants: `python3 main_backtest.py --list-candidates`
- Run a variant: `caffeinate -dimsu python3 main_backtest.py --candidate mr_long_only`
- Frequency probe: `caffeinate -dimsu python3 main_backtest.py --candidate higher_frequency_probe`
- Structure swing filter: `caffeinate -dimsu python3 main_backtest.py --candidate structure_swing_filter`
- Structure + frequency probe: `caffeinate -dimsu python3 main_backtest.py --candidate higher_frequency_structure_probe`
- Market-profile crossing signal probe: `caffeinate -dimsu python3 main_backtest.py --candidate market_profile_cross_signal_probe`
- Market-profile room filter: `caffeinate -dimsu python3 main_backtest.py --candidate market_profile_room_filter`
- Market-profile + frequency probe: `caffeinate -dimsu python3 main_backtest.py --candidate higher_frequency_market_profile_probe`
- Markov volatility overlay: `caffeinate -dimsu python3 main_backtest.py --candidate markov_regime_overlay`
- Market-memory context probe: `caffeinate -dimsu python3 main_backtest.py --candidate market_memory_context_probe`
- Market-memory fragile-state avoidance: `caffeinate -dimsu python3 main_backtest.py --candidate market_memory_avoid_fragile`
- VWAP time-of-day probe: `caffeinate -dimsu python3 main_backtest.py --candidate vwap_time_of_day_probe`
- Refined edge batch: `bash scripts/run_edge_candidates_batch.sh`
- Next VP edge batch: `bash scripts/run_next_vp_candidates_batch.sh`
- Quality cleanup: `caffeinate -dimsu python3 main_backtest.py --candidate edge_vp_hf_gap_cusum_no_mr_long`
- Delay robustness: `caffeinate -dimsu python3 main_backtest.py --candidate edge_vp_hf_gap_cusum_no_mr_long_delay_1`
- Frequency probe: `caffeinate -dimsu python3 main_backtest.py --candidate edge_vp_scalp_frequency_gap_cusum_no_mr_long`
- Archived failed-auction high-frequency observation probe: `caffeinate -dimsu python3 main_backtest.py --candidate edge_vp_mr_trend_failed_auction_hf_observation_probe --start 2021-01-01`
- Fast 2021+ signal-count scan: `python3 scripts/probe_candidate_frequency.py --signals-only --out results/research_master/2021_frequency_signal_probe.csv`
- 2021+ executed-trade frequency scan: `python3 scripts/probe_candidate_frequency.py --out results/research_master/2021_frequency_probe.csv`
- Full 2021+ frequency batch: `bash scripts/run_2021_frequency_candidates_batch.sh`
- Rejected execution-first microstructure probe: `edge_microstructure_liquidity_taking_trend_probe`

Each run writes `research/development_report.md` and `research/research_discipline_gate.md` in its run folder.
Broad batch scripts are guarded reproduction tools; they are not active research queues while `next_validation_candidates` is empty.

## Anti-Overfit Validation
- Treat optimization as hypothesis generation, not proof. A candidate must survive OOS walk-forward, bar-level PF, stress tests, and prop-firm random-walk checks before it is eligible for funded-style behavior.
- Walk-forward validation is now purged and embargoed by default. `wf_purge_bars='auto'` removes the train bars that could overlap the next OOS fold through max hold plus entry delay, and `wf_embargo_bars` adds an extra serial-correlation gap.
- Each run now writes `research/optimization_stability.csv` when walk-forward runs. This flags sharp train optima, weak neighboring parameter sets, and OOS fold failure.
- Each run writes `research/multiple_testing_debt.csv`. This records the configured candidate family and saved run count so broad search does not masquerade as independent evidence.
- Each run writes `research/research_discipline_gate.csv`. This is the strict promotion gate: missing permutation evidence, missing bar-exposure audit, missing execution-realism audit, in-sample-only prop evidence, or excessive family run count makes the candidate non-promotable.
- `research/development_report.csv` treats 5-minute signal-bar PF and `combined_mild` trade stress as hard warnings. The 1-minute `execution_bar_profit_factor` is diagnostic only; it helps separate execution-path edge from signal-bar hindsight.
- Prop-firm simulations sample calendar-day paths from the first active trade day and include zero-PnL no-trade days. Active-day-only pass rates are not valid eval evidence for sparse strategies.
- `config/research_freeze.json` currently archives a rejected candidate for reproducibility. A passing freeze check is not an active validation signal until a new signal report, hypothesis, and one-candidate freeze exist.
- Freeze the candidate before any lockbox or forward-style run:
  `python3 scripts/check_research_freeze.py --manifest config/research_freeze.json --print-command`
- After a saved development run of the frozen candidate, evaluate it against the pre-declared gates:
  `python3 scripts/check_research_freeze.py --manifest config/research_freeze.json --run-dir results/runs/<run_label> --phase development`
- After a saved untouched lockbox/forward run, evaluate it as lockbox evidence:
  `python3 scripts/check_research_freeze.py --manifest config/research_freeze.json --run-dir results/runs/<run_label> --phase lockbox`
- Diagnose trade-PF vs signal/execution bar-PF disagreement from a saved run without replaying strategy logic:
  `python3 scripts/audit_bar_exposure.py --run-dir results/runs/<run_label>`
- Re-check the strict saved-run discipline gate after audits are available:
  `python3 scripts/check_research_discipline.py --run-dir results/runs/<run_label>`
- Audit fill assumptions from saved trades plus execution bars:
  `python3 scripts/audit_fill_assumptions.py --run-dir results/runs/<run_label> --start 2021-01-01`
- TBBO-only data is an execution-realism lockbox unless it is converted into bars through the same point-in-time feature pipeline. Use it to audit spread/depth/fill assumptions, not to mine fresh signal filters.
- The failed-auction quality branch is rejected and removed from the active validation queue. See `docs/research_postmortems/2026-05-20_failed_auction_quality_rejection.md`.
- The microstructure liquidity-taking trend probe is rejected and removed from the active validation queue.
- Before creating another candidate, re-score the saved power-hour export with the event-enhanced temporal signal gate:
  `python3.12 scripts/run_temporal_signal_research_report.py --signals-csv results/research_master/signal_exports/power_hour_continuation_dev_2010_2024.csv --signal-cols candidate_signal,power_hour_score --context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side,closing_flow_side,close_location,momentum_state,power_hour_pattern --splits legacy_context:2010-01-01:2015-12-31,transition:2016-01-01:2020-12-31,recent_development:2021-01-01:2024-12-31 --primary-split recent_development --supporting-splits transition --entry-price-col open --entry-lag-bars 1 --exit-price-col close --round-trip-cost-points 1.5 --event-bootstrap-samples 2000 --event-placebo-samples 2000 --artifact-name power_hour_continuation_event_temporal_gate`
- The opening compression breakout signal gate is rejected. See `docs/research_postmortems/2026-05-21_compression_breakout_signal_gate_rejection.md`.
- The RTH gap-and-go signal gate is rejected. See `docs/research_postmortems/2026-05-21_gap_go_signal_gate_rejection.md`.
- The power-hour signal gate is rejected. See `docs/research_postmortems/2026-05-22_power_hour_signal_gate_rejection.md`.
- After each approved run, check the saved gate:
  `python3 scripts/check_prop_research_gate.py`

## Paper Trading Runtime
- Historical replay through the live-style paper executor:
  `python3 scripts/run_paper_trader.py --candidate <candidate_name> --start 2024-01-01 --end 2024-01-31 --warmup-bars 2500`
- Fast quiet replay with custom warmup:
  `python3 scripts/run_paper_trader.py --candidate <candidate_name> --start 2021-01-01 --quiet --warmup-bars 1000`
- The paper runner simulates fills locally through the same portfolio/execution rules as the backtest; it does not submit broker orders.
- Paper event, trade, execution-observation, and execution-summary logs are written under `results/paper/`.

## AMP/CQG Live Paper Path
- Dry-run the AMP-style runner with order-intent audit:
  `python3 scripts/run_amp_paper_trader.py --feed replay --broker audit --candidate <candidate_name> --start 2024-01-01 --end 2024-01-31 --warmup-bars 2500`
- Dry-run with prop eval guard and attempt ledger:
  `python3 scripts/run_amp_paper_trader.py --feed replay --broker audit --candidate <candidate_name> --start 2024-01-01 --end 2024-01-31 --warmup-bars 2500 --prop-guard --prop-profile traders_launch_100k_nyc --prop-phase eval`
- Tail an externally written live bar file:
  `python3 scripts/run_amp_paper_trader.py --feed tail --bar-file data/live/latest_1m_bars.csv --broker audit --prop-guard`
- Run the delayed Yahoo Finance live loop locally:
  `bash scripts/run_live_paper.sh <candidate_name>`
- Create the printed `STOP_TRADING` file to block new entries and flatten an open paper position. The loop also persists restart state to `results/live_paper_state_<candidate>.json`.
- Prop-guarded runs write `prop_attempt_ledger.csv` with eval cost, profile, multiplier, day count, realized/MTM PnL, rule floor, consistency state, payout eligibility, and kill reason.
- Validate saved research artifacts before funded/payout mode:
  `python3 scripts/check_prop_research_gate.py --run-dir results/runs/<run_label>`
- Check replay parity before trusting live-mode changes:
  `python3 scripts/check_live_parity.py --candidate <candidate_name> --start 2024-01-01 --end 2024-12-31 --warmup-bars 2500`
- Check local CQG environment variables after AMP/CQG replies:
  `python3 scripts/check_cqg_setup.py --require-account --validate-samples`
- `--broker audit` writes the exact intended BUY/SELL market orders to `orders_intended.csv`; MotiveWave will not show these because they are not sent to CQG.
- `--prop-phase funded` requires the saved prop research gate unless `--allow-unapproved-funded` is passed. The current recommended candidate is for paper/eval validation, not funded cash deployment.
- To see trades in MotiveWave, the runner must use CQG order routing into the same AMP/CQG demo or paper account that MotiveWave is connected to.
- Copy `config/live_trading.example.env` to a private location and ask AMP/CQG for WebAPI/demo order-routing access, the exact CQG contract symbol, and the account ID.

## NQ Options Data
- Prepare raw Databento options archives: `python3 scripts/prepare_options_nq.py`
- Compressed statistics archives are supported directly as `*.statistics.csv.zst` members inside ZIP files.
- A lightweight symlink is enough for large archives under `data/raw/options_nq/statistics/`; the ZIP does not need to be duplicated.
- Build daily options-flow confluence features plus GEX-service-style strike surfaces: `python3 scripts/build_options_flow_features.py --min-dte 0 --max-dte 120 --strike-window-points 600 --min-open-interest 1`
- The daily file is the compact backtest join artifact; `options_flow_strike_levels.csv` is the all-expiry per-date/per-strike surface.
- `options_flow_dashboard.csv` and `options_flow_dashboard_strike_levels.csv` split the same features into `0dte`, `1_7dte`, `8_30dte`, `31_120dte`, and `all` buckets so intraday 0DTE gamma is not mixed with longer OI/DEX context.
- Test gamma-environment confluence: `python3 main_backtest.py --candidate options_flow_gamma_environment`

## NQ TBBO Execution Data
- TBBO futures data is for execution realism, not edge mining. Use it to audit spread, top-book depth, and trade-price-vs-mid assumptions around candidate signals.
- Build minute and daily execution stats from a Databento `tbbo` archive:
  `python3 scripts/build_tbbo_execution_stats.py --source /Users/novo/Downloads/GLBX-20260513-FXJ4VJE8JE.zip`
- Merge a new TBBO archive into existing processed stats:
  `python3.12 -u scripts/build_tbbo_execution_stats.py --source /Users/novo/Downloads/<tbbo>.zip --merge-existing`
- Smoke a single member before processing the full archive:
  `python3 scripts/build_tbbo_execution_stats.py --source /Users/novo/Downloads/GLBX-20260513-FXJ4VJE8JE.zip --max-files 1 --rows-per-file 50000 --out /tmp/tbbo_minute_smoke.csv --daily-out /tmp/tbbo_daily_smoke.csv`
- The builder defaults to NQ outright futures symbols and excludes calendar spreads; use `--symbol-regex` to override.
- Outputs default to `data/processed/tbbo/tbbo_minute_execution_stats.csv` and `data/processed/tbbo/tbbo_daily_execution_stats.csv`.
- Build realized aggressive-flow stats from Databento `trades` archives:
  `python3.12 -u scripts/build_aggressive_flow_stats.py --source /Users/novo/Downloads/<trades>.zip --merge-existing`
- Aggressive-flow stats keep raw Databento `A`/`B` side columns. Verify the exchange/vendor convention before mapping them to human labels like at-bid or at-ask in a strategy.
- Build a baseline execution-cost report from processed TBBO stats:
  `python3.12 scripts/audit_tbbo_execution_baseline.py`
- Audit a completed run's trade log against the processed TBBO minute stats:
  `python3 scripts/audit_trades_with_tbbo.py --run-dir results/runs/<run_label>`
- Audit target-fill cost sensitivity on a completed run without rerunning the strategy:
  `python3 scripts/audit_execution_realism.py --run-dir results/runs/<run_label> --candidate <candidate_name>`

## Research Protocol Control
- The agentic research-control layer lives in `backtest/research_protocol.py` with the CLI wrapper `scripts/check_research_protocol.py`.
- Use it to write and verify experiment manifests, config/file fingerprints, LLM/evaluation blinding rules, and saved-artifact gates. It does not run a backtest.
- Every manifest must include a structured edge thesis: edge type, mechanism, counterparty, persistence reason, at least two falsification tests, and known failure modes. Metric-only stories like "the backtest looks good" fail the gate.
- TBBO sources should be declared with `sample_role=tbbo` and `purpose=execution_audit`; declaring TBBO as alpha-mining evidence fails the protocol gate.
- Example manifest creation:
  ```bash
  python3 scripts/check_research_protocol.py --write-manifest \
    --manifest config/research_protocol.json \
    --phase hypothesis \
    --data-source tbbo_minute_stats:data/processed/tbbo/tbbo_minute_execution_stats.csv:tbbo:execution_audit:false \
    --edge-type execution_realism \
    --edge-mechanism "Short-horizon NQ backtests can look profitable when target fills, spread, and adverse selection are understated; the research edge is avoiding false positives before strategy promotion." \
    --edge-counterparty "Liquidity providers, fast participants, and the bid-ask spread capture costs from impatient liquidity-taking orders and optimistic resting-limit assumptions." \
    --edge-persistence-reason "Spread, depth, queue priority, and adverse selection are structural microstructure costs that should persist across NQ scalping strategies." \
    --edge-falsification-test "Reject promotion if saved trades only survive optimistic target-fill assumptions." \
    --edge-falsification-test "Reject promotion if TBBO spread or trade-vs-mid evidence shows configured costs are too low." \
    --edge-failure-mode "Execution audit is mistaken for directional alpha." \
    --edge-failure-mode "A short TBBO sample is mined for signal filters instead of used as cost evidence."
  ```
- Check a saved run against the manifest without replaying strategy logic:
  `python3 scripts/check_research_protocol.py --manifest config/research_protocol.json --run-dir results/runs/<run_label> --out-dir results/runs/<run_label>/research`

## Conservative Target-Fill Validation
- Target fills default to legacy touch behavior. Validation candidates can use `target_fill_mode='trade_through'` with `target_fill_trade_through_ticks=1` to require one NQ tick beyond the target before assuming a resting target order was filled.
- Managed stops default to legacy same-bar activation. Strict validation can use `managed_stop_activation_mode='next_bar'` so only prior completed execution-bar MFE can activate a managed stop on the current bar.
- Failed-auction managed-stop variants are archived for reproducibility only. They are not the frozen validation test.

## IBKR Markov Regime Monitor
- Optional dependency: install IBKR's `ibapi` package.
- Paper/default TWS port example: `python3 scripts/run_ib_markov_regime_bot.py --symbol NQ --sec-type FUT --exchange CME --last-trade-date-or-contract-month 202606`
- The IBKR runner streams and classifies regimes only; it does not place orders.
