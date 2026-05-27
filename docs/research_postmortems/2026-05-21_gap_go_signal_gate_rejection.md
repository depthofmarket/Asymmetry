# RTH Gap-And-Go Signal Gate Rejection

Date: 2026-05-21

## Verdict

Reject the RTH gap-and-go opening-range continuation hypothesis. Do not create a strategy candidate from this signal.

## Evidence

- Temporal report: `results/research_master/signal_research/gap_go_temporal_gate_temporal.md`
- Prepared signal export: `results/research_master/signal_exports/gap_go_dev_2010_2024.csv`
- Exported rows: 4,912,414
- Active signal rows: 929 (0.02%)
- Gate result: no signal/horizon pair passed the temporal pre-candidate gate.

## Primary Split: 2021-2024

The recent-development split had 413 active signals.

- Best aggregate horizon was 24 bars: mean signed return after cost was +0.2167 points, but IC was only about 0.0011.
- 1, 3, 6, and 12 bar horizons were negative after cost except the diagnostic long-side context slice.
- `candidate_signal` and `gap_go_score` both failed the required IC threshold and were not eligible for candidate promotion.

## Supporting Split: 2016-2020

The transition split had 360 active signals and failed support.

- All aggregate horizons were negative after cost.
- The best IC was far below the required threshold.
- The apparent short-side 3-bar context slice was not enough to support the recent long-side behavior.

## Diagnostic Slices

The recent long-side slice was positive at 12 and 24 bars:

- 12-bar long-side recent-development mean signed return after cost: +0.8676 points, 219 active signals.
- 24-bar long-side recent-development mean signed return after cost: +0.7922 points, 219 active signals.

This is diagnostic only. The same long-side slice was negative in transition and only barely positive at 24 bars in legacy context. Promoting it would be same-sample filtering after seeing the report.

## Decision

Do not add a `CANDIDATE_CONFIGS` entry.

Do not use 2025+ holdout to rescue this branch. The signal did not pass development evidence, so spending holdout on a mined long-only variant would increase testing debt without a justified candidate.

