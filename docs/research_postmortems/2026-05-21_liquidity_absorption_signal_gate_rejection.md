# Liquidity Absorption Signal Gate Rejection

Date: 2026-05-21

## Verdict

Reject the liquidity absorption / failed-continuation pre-candidate signal gate. Do not create a `CANDIDATE_CONFIGS` entry from this result.

## Artifact

Signal report:

`results/research_master/signal_research/liquidity_absorption_2021_signal_gate_next_bar_open.md`

Export manifest:

`results/research_master/signal_exports/liquidity_absorption_2021_signal_gate_manifest.md`

## Evidence

- Active signal rows: 1,976 out of 1,881,973 rows.
- `candidate_signal` IC was near zero across all tested horizons.
- `absorption_score` IC was near zero across all tested horizons.
- Signed forward returns after 1.5 points round-trip cost were negative at every full-sample horizon under next-bar-open entry timing.
- Positive signed-period share was far below the 55 percent gate threshold.
- The only positive context slice was hour 11 at the 24-bar horizon, with 225 active observations and +1.84 points after cost.

## Decision

The hour-11 / 24-bar slice is not permission to build a candidate. It is a same-sample diagnostic and should only become a future hypothesis if it is pre-registered against a separate sample or tied to a real implementation bug.

Implementation audit note: the original saved report was generated with the earlier close-to-close signal gate. The stricter next-bar-open re-score also failed, so this is not an execution-timing rescue.

Next work should be hypothesis design, stricter re-scoring of an existing prepared export if explicitly chosen, or implementation audit, not variant generation from this result.
