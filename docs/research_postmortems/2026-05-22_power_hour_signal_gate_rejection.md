# Power-Hour Signal Gate Rejection

Date: 2026-05-22

## Verdict

Reject the power-hour accepted-trend continuation hypothesis as a strategy-candidate input. Do not create a `CANDIDATE_CONFIGS` entry from this report.

## Evidence

- Temporal report: `results/research_master/signal_research/power_hour_continuation_temporal_gate_temporal.md`
- Prepared signal export: `results/research_master/signal_exports/power_hour_continuation_dev_2010_2024.csv`
- Exported rows: 4,912,414
- Active signal rows: 1,126 (0.02%)
- Gate result: no signal/horizon pair passed the temporal pre-candidate gate.
- Event-gate re-score: `results/research_master/signal_research/power_hour_continuation_event_temporal_gate_temporal.md`
- Event-gate result: no signal/horizon pair passed the temporal event-signal gate.

## Primary Split: 2021-2024

The recent-development split had 507 active signals and showed economically interesting 12/24-bar continuation:

- 24-bar mean signed return after cost: +4.1144 points.
- 24-bar hit rate: 58.58%.
- 24-bar positive signed-period share: 75.0%.
- 12-bar mean signed return after cost: +2.4255 points.

This still failed the gate because IC was far below threshold:

- 24-bar `candidate_signal` IC: 0.0041.
- 24-bar `power_hour_score` IC: 0.0051.
- Required absolute IC: 0.0200.

## Supporting Split: 2016-2020

The transition split did not provide enough support:

- 24-bar mean signed return after cost: +0.0850 points.
- 24-bar positive signed-period share: 50.0%.
- 12-bar mean signed return after cost: -0.9924 points.
- All IC values were far below the threshold.

The short-side 6-bar transition slice was positive, but it does not match the recent 12/24-bar aggregate continuation evidence.

## Legacy Context: 2010-2015

The legacy-context split was broadly negative:

- 24-bar mean signed return after cost: -1.2089 points.
- 12-bar mean signed return after cost: -1.0278 points.
- Positive signed-period share was only 21.74% for 12/24 bars.

This argues that the behavior is not a stable long-history edge.

## Diagnostic Slices

Recent 24-bar direction slices were positive:

- Long: +3.7404 points after cost, 286 active signals.
- Short: +4.5984 points after cost, 221 active signals.

These are diagnostic only. Promoting them directly would use the 2021-2024 development sample after seeing the result. If this branch is revisited, it must be framed as a new recent-regime hypothesis with a separate pre-registered protocol, not as a mutation of this report.

## Event-Gate Re-Score

The event-enhanced gate confirmed that the recent 12/24-bar events are real enough to notice in 2021-2024:

- Recent 24-bar `candidate_signal`: +4.1144 points after cost, bootstrap CI low +1.2332, placebo edge +5.5813, placebo p-value 0.0000.
- Recent 12-bar `candidate_signal`: +2.4255 points after cost, bootstrap CI low +0.3601, placebo edge +3.9160, placebo p-value 0.0000.
- Both recent 12/24-bar rows were `event_eligible_for_candidate=True`.

However, temporal event eligibility still failed:

- Transition 24-bar mean after cost was only +0.0850 points, bootstrap CI low -1.9538, positive signed-period share 50.0%.
- Transition 12-bar mean after cost was -0.9924 points.
- Legacy 12/24-bar rows remained negative.
- `temporal_event_eligible_for_candidate=False` for every row.

This means the event-gate issue was real, but it does not rescue power-hour. The recent effect is not supported by transition.

## Decision

Do not add a strategy candidate.

Do not spend the 2025+ holdout to rescue this exact branch. The temporal event gate did not pass, and using holdout to adjudicate a post-hoc recent-only interpretation would weaken the research process.
