# Microstructure Execution-First Research Track

Date: 2026-05-20

## Purpose

Start the next branch from market mechanics rather than from the failed-auction result set. The first question is not "which filter improves the backtest?" It is:

Would this signal still have expectancy after paying the spread, slippage, timing risk, and adverse selection a real order would face?

## Ex-Ante Hypothesis

Short-horizon NQ strategies should only be considered viable when the signal has enough directional expectancy to survive an execution model that penalizes liquidity taking.

The research target is therefore an execution-first signal family:

- Entry logic must be defined before testing.
- Features must use only information available at decision time.
- Fill assumptions must be stated before the run.
- Costs should be biased high, not optimistic.
- Prop-firm pass rates are research-only until they come from scoped OOS, lockbox, or paper evidence.

## What This Is Not

- Not another failed-auction quality variant.
- Not a broad search over time filters, stop values, or context exclusions.
- Not a prop-firm pass-rate optimizer on in-sample results.
- Not a TBBO edge-mining exercise. The 81-day TBBO set is execution-realism evidence unless a separate holdout protocol is written first.

## Required Evidence

Before any candidate from this track can be promoted:

1. Point-in-time feature construction is documented.
2. Transaction-cost assumptions include commission, spread/slippage proxy, and stop-like adverse fill stress.
3. The saved run passes the research discipline gate.
4. Purged/embargoed walk-forward output exists.
5. Multiple-testing debt is within the configured family limit or the next evidence comes from untouched holdout/paper.
6. Prop-firm approval uses OOS or lockbox scope, not development in-sample scope.

## Current Practical Work

The first candidate from this track, `edge_microstructure_liquidity_taking_trend_probe`, is rejected. The next step is not a second candidate. The next step is a pre-candidate signal report:

- Export a prepared point-in-time signal CSV with `scripts/export_prepared_signal_csv.py`.
- Measure raw IC against forward returns.
- Measure signed forward return after conservative cost assumptions.
- Check period stability before trusting aggregate expectancy.
- Group by context only as diagnosis; do not turn a winning slice into a same-sample candidate.

Do not add another candidate from this track until a signal report and a fresh ex-ante hypothesis both exist.
