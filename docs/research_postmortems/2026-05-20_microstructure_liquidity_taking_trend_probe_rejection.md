# Microstructure Liquidity-Taking Trend Probe Rejection

Date: 2026-05-20

## Decision

Reject `edge_microstructure_liquidity_taking_trend_probe`.

The run was stopped early enough to avoid wasting more runtime, but late enough to show the failure mode clearly. Do not mine a same-sample long/short split, hour filter, or prop-rule variant from this result.

## Evidence

Saved run:

```text
results/runs/20260520_190728_edge_microstructure_liquidity_taking_trend_probe_long_short_next_bar_open_hybrid
```

Observed artifacts:

- Prop eval pass probability: `0.0%`
- Eval-to-first-payout probability: `0.0%`
- Extension-threshold failure probability: `99.34%`
- Trade profit factor: about `1.05`
- Median trade: about `-$92.50`
- Long setup total PnL: negative
- Short setup total PnL: positive but weak
- Random-walk/sign-flip PnL p-value: about `0.34`
- Random-walk/sign-flip Sharpe p-value: about `0.34`

## Interpretation

This is not a prop chart data problem. It is a weak-signal problem. The strategy does not produce enough calendar-time PnL to satisfy the eval structure, and the statistical evidence is not strong enough to justify another in-family variant.

## Next Rule

The next strategy idea must pass a pre-candidate signal report before it becomes a configured candidate. Required evidence should include raw IC, signed forward-return after cost, period stability, and context diagnostics.
