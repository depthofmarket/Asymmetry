# Aggressive-Flow Location Context L2 Signal Gate

Date: 2026-06-07

Status: pre-registered hypothesis; no candidate backtest is authorized yet.

## Hypothesis

NQ short-horizon continuation may have positive expectancy when completed-minute aggressive-flow imbalance aligns with accepted location context, and L2 replay does not show immediate adverse selection or unrealistic fills.

The proposed signal is directional only after the market shows both:

- aggressive flow pressure in the same direction as the proposed entry,
- acceptance away from nearby profile/value-area shelves rather than rejection back into them,
- enough L2 execution realism to survive spread, latency, and trade-through fill assumptions.

## Mechanism

Urgent liquidity takers can force short-term repricing when passive liquidity providers are consumed or forced to reprice. Location matters because the same aggressive print near a profile shelf can mean absorption, while aggressive flow that pushes away from accepted value can mean continuation.

L2 data is not the edge by itself. It is the execution and adverse-selection audit for any bar-level signal created from completed aggressive-flow and location-context artifacts.

## Fixed Pre-Run Assumptions

- This is not a `CANDIDATE_CONFIGS` entry.
- The first artifact is a pre-candidate signal report, not a strategy backtest.
- Features must be known before entry; completed-minute flow can only affect later rows.
- Entry pricing must use next-bar open, not signal-bar close.
- L2 replay is used for fills, spread, latency, depth, and adverse-selection checks, not for same-sample filter mining.
- Raw Databento `A`/`B` side codes must not be renamed buyer/seller aggression until the convention is proven against source semantics.
- Winning context slices are diagnostic only unless re-registered before a separate sample.

## Required Artifacts Before Backtest

1. Location context built from point-in-time bars and completed aggressive-flow minute stats.
2. A deterministic signal export that includes `candidate_signal`, a continuous flow/location score, entry/exit prices, and context columns.
3. A pre-candidate signal report with next-bar-open entry, cost stress, bootstrap, placebo, and period stability.
4. L2 replay protocol pass for the execution-realism source.
5. Written decision notes explaining whether the signal survived before any candidate is added.

## Initial Build Command

This builds context only. It does not run a backtest.

```bash
python3 scripts/build_location_context.py \
  --orderflow-minute-stats data/processed/orderflow/aggressive_flow_minute_stats.csv \
  --out-dir data/processed/location_context \
  --prefix aggressive_flow_location_l2
```

## Signal Export Command

This exports point-in-time signal rows only. It does not run a backtest.

```bash
python3 scripts/export_aggressive_flow_location_signal_csv.py \
  --location-context data/processed/location_context/aggressive_flow_location_l2.csv \
  --artifact-name aggressive_flow_location_l2_signal_gate
```

## Signal Gate Template

Use this only after the deterministic signal CSV exists.

```bash
python3 scripts/run_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/aggressive_flow_location_l2_signal_gate.csv \
  --signal-cols candidate_signal,aggressive_flow_location_score \
  --context-cols direction,hour,session_bucket,vwap_side,profile_acceptance_state,orderflow_state,flow_price_state \
  --entry-price-col open \
  --entry-lag-bars 1 \
  --exit-price-col close \
  --round-trip-cost-points 1.5 \
  --stress-round-trip-cost-points 2.0,4.25 \
  --artifact-name aggressive_flow_location_l2_signal_gate
```

## Falsification Tests

- Reject if the signal report fails raw IC, signed forward return after cost, bootstrap CI, placebo edge, or period stability.
- Reject if the result only appears after same-sample hour, regime, shelf, or side-code filtering.
- Reject if L2 replay erases apparent expectancy through spread, latency, depth, or trade-through fill assumptions.
- Reject if the signal depends on treating raw `A`/`B` side codes as human-labeled aggressor direction without proof.

## Promotion Rule

Do not create or run a strategy candidate from this branch unless the pre-candidate report passes first and the candidate is frozen before any broader historical run.
