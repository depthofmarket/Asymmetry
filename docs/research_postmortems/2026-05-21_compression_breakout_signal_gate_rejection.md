# Opening Compression Breakout Signal Gate Rejection

Date: 2026-05-21

## Verdict

Reject the opening compression breakout continuation pre-candidate signal gate. Do not create a `CANDIDATE_CONFIGS` entry from this result.

## Artifact

Signal report:

`results/research_master/signal_research/compression_breakout_2021_signal_gate.md`

Export manifest:

`results/research_master/signal_exports/compression_breakout_2021_signal_gate_manifest.md`

## Evidence

- Active signal rows: 195 out of 1,881,973 rows.
- No signal passed the configured gate.
- `candidate_signal` and `compression_breakout_score` IC were near zero across all tested horizons.
- The 24-bar horizon had positive signed return after 1.5 points round-trip cost, but still failed on IC and eligibility.
- Positive signed-period share at 24 bars was 54.55 percent, just below the 55 percent threshold.
- The short-side 24-bar context slice had 101 active observations and +5.00 points after cost, but it is a same-sample diagnostic.

## Decision

The short-side / 24-bar slice is not permission to build a candidate. It can only become a future hypothesis if it is pre-registered against a separate sample or tied to a real implementation bug.

Next work should be hypothesis design or implementation audit, not variant generation from this result.
