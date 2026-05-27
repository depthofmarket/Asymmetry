# Market-Memory Impulse Signal Gate Rejection

Date: 2026-05-24

Status: rejected

## Hypothesis

CUSUM impulse continuation might have short-horizon edge when the prior tape is persistent, low entropy, low sign-change complexity, and the impulse aligns with the prior trend direction.

## Artifacts

- Export: `results/research_master/signal_exports/memory_impulse_dev_2010_2024.csv`
- Export manifest: `results/research_master/signal_exports/memory_impulse_dev_2010_2024_manifest.md`
- Temporal report: `results/research_master/signal_research/memory_impulse_event_temporal_gate_temporal.md`
- Temporal summary: `results/research_master/signal_research/memory_impulse_event_temporal_gate_temporal_summary.csv`

## Verdict

No signal/horizon pair passed the temporal pre-candidate gate.

No signal/horizon pair passed the temporal event-signal gate.

Do not create a candidate from this branch.

## Evidence

- Export rows: 4,912,414.
- Active signal rows: 355, or 0.01% of rows.
- Recent development active rows: 28, below the 30-row minimum.
- Recent development had positive mean at 3/6/12/24 bars, but the evidence was too sparse and unstable:
  - 6-bar mean after cost: +8.8214 points, median -1.25, bootstrap CI low -4.4413.
  - 24-bar mean after cost: +6.0536 points, median -3.125, bootstrap CI low -9.7955.
- Transition support failed across every horizon:
  - 1-bar mean after cost: -2.0191 points.
  - 3-bar mean after cost: -3.1568 points.
  - 6-bar mean after cost: -4.4894 points.
  - 12-bar mean after cost: -8.0318 points.
  - 24-bar mean after cost: -8.7140 points.
- Legacy context also failed across every horizon.

## Context Notes

The largest recent context wins were tiny clock slices, especially five `hour=15` / `rth_late` rows. That is not acceptable promotion evidence. If a structurally non-time hypothesis only looks good after filtering to tiny time buckets, it becomes time-of-day tweaking and should be rejected.

## Decision

Archive this as rejection evidence.

Do not tune `min_persistence`, `max_entropy`, `max_complexity`, `cooldown_bars`, or CUSUM thresholds on the same 2010-2024 sample.

The next idea should be structurally new or should address execution realism/measurement quality, not rescue memory impulse by threshold mutation.
