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

## Setup
1. Install: `pip install -r requirements.txt`
2. Add NQ data to `data/raw/`
3. Run: `python3 main_backtest.py`

## Candidate Runs
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
- Fast 2021+ signal-count scan: `python3 scripts/probe_candidate_frequency.py --signals-only --out results/research_master/2021_frequency_signal_probe.csv`
- 2021+ executed-trade frequency scan: `python3 scripts/probe_candidate_frequency.py --out results/research_master/2021_frequency_probe.csv`
- Full 2021+ frequency batch: `bash scripts/run_2021_frequency_candidates_batch.sh`

Each run writes `research/development_report.md` in its run folder.

## NQ Options Data
- Prepare raw Databento options archives: `python3 scripts/prepare_options_nq.py`
- Compressed statistics archives are supported directly as `*.statistics.csv.zst` members inside ZIP files.
- A lightweight symlink is enough for large archives under `data/raw/options_nq/statistics/`; the ZIP does not need to be duplicated.
- Build options-flow confluence features: `python3 scripts/build_options_flow_features.py --min-dte 0 --max-dte 120 --strike-window-points 600 --min-open-interest 1`
- Test gamma-environment confluence: `python3 main_backtest.py --candidate options_flow_gamma_environment`

## IBKR Markov Regime Monitor
- Optional dependency: install IBKR's `ibapi` package.
- Paper/default TWS port example: `python3 scripts/run_ib_markov_regime_bot.py --symbol NQ --sec-type FUT --exchange CME --last-trade-date-or-contract-month 202606`
- The IBKR runner streams and classifies regimes only; it does not place orders.
