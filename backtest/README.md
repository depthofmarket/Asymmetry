# Backtest Package Map

This package is organized by runtime responsibility. Keep reusable logic here and keep `scripts/` as thin command-line entry points.

## Core Engine

- `engine.py`: `BacktestEngine` orchestration and signal-frame contract.
- `portfolio.py`: positions, fills, equity, and trade log state.
- `execution.py`, `signals.py`, `indicators.py`: engine mixins.
- `bar_exposure_audit.py`: saved-run signal-bar and execution-bar exposure reconstruction for trade-PF vs bar-PF diagnostics.
- `execution_realism.py`: saved trade-log sensitivity and bar-joined fill-assumption checks for target-fill, same-minute exits, and lower-bound ordering ambiguity.
- `strategy_runtime.py`: signal-event extraction shared by backtest and live-style paper execution.
- `objectives.py`: signal-bar, execution-bar, and regime-weighted scoring helpers.
- `tbbo_execution.py`: TBBO spread/depth/trade-vs-mid aggregation for execution realism checks.
- `tbbo_trade_audit.py`: joins saved trade logs to processed TBBO stats to test fill/slippage assumptions.

## Live And Paper Runtime

Keep live/paper code flat in `backtest/` unless there is a stronger reason to split it.

- `live.py`: bar-driven paper execution loop, event model, and paper config.
- `live_feeds.py`: replay, file-tail, and CQG feed setup adapters.
- `live_brokers.py`: audit broker, CQG broker guard, and order-intent bridge.
- `live_prop_rules.py`: live prop-firm guard and funded/eval gate checks.
- `live_parity.py`: backtest-vs-paper trade-log comparison helpers.

## Feature Builders

Feature code that adds columns to bar data currently lives in:

- `auction_context.py`
- `event_sampling.py`
- `hawkes.py`
- `market_memory.py`
- `market_profile.py`
- `market_structure.py`
- `markov_regime.py`
- `options_flow.py`
- `point_in_time.py`
- `volume_spread.py`

Keep these point-in-time and free of future-data leakage. If a module starts owning external data ingestion, split the ingestion into a separate helper instead of hiding it in the engine.

## Research And Validation

Research, diagnostics, and experiment reporting currently live in:

- `feature_research.py`
- `feature_attribution.py`
- `online_regime_leakage.py`
- `permutation.py`
- `placebo.py`
- `prop_firm.py`
- `simulations.py`
- `sweep.py`
- `validation.py`
- `vwap_research.py`
- `walkforward.py`

Keep these as analysis/reporting code. If a research result becomes part of execution, move only the reusable runtime primitive into core or the flat live runtime modules.

`validation.py` owns the saved anti-overfit reports: development gates, optimization stability, and multiple-testing debt. These reports should consume completed run artifacts or existing walk-forward objects; they should not launch new backtests.

`walkforward.py` owns time-series validation. Its default format is rolling forward-chain with a purged train tail and an embargo gap before each OOS fold. Use the anchored mode only when the relationship is intentionally assumed to be stable across the full history.
