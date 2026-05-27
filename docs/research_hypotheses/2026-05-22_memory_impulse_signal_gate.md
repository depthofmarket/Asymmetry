# Market-Memory Impulse Continuation Signal Gate

Date: 2026-05-22

Status: rejected pre-candidate signal hypothesis

## Hypothesis

NQ short-horizon edge, if present here, comes from volatility-normalized price impulses that occur while the recent tape is persistent and low-complexity. A CUSUM displacement aligned with that prior state may represent directional order-flow continuation rather than random noise.

This is intentionally not a time-of-day hypothesis. `hour` and `session_bucket` are retained only as audit context so we can reject the idea if the result is secretly just a clock effect.

## Fixed Pre-Run Assumptions

- This is not a `CANDIDATE_CONFIGS` entry.
- The signal uses completed bars only.
- Entry scoring should use next-bar open to horizon close.
- A signal requires a CUSUM movement event.
- The market-memory regime is measured before the impulse bar with vectorized rolling features shifted out of the event row.
- Required state: high directional persistence, bounded binary entropy, bounded sign-change complexity, and impulse direction aligned with the prior trend direction.
- No time window filter is part of the signal.
- Running the export over 2010-2024 is a full-sample signal scan and testing debt.
- 2025+ remains untouched holdout unless the 2010-2024 temporal gate passes.

## User-Run Commands

Export prepared point-in-time signals:

```bash
python3.12 scripts/export_memory_impulse_signal_csv.py \
  --start 2010-01-01 \
  --end 2024-12-31 \
  --artifact-name memory_impulse_dev_2010_2024
```

Then run the event-enhanced temporal gate:

```bash
python3.12 scripts/run_temporal_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/memory_impulse_dev_2010_2024.csv \
  --signal-cols candidate_signal,memory_impulse_score \
  --context-cols setup_tag,direction,signal_type,hour,session_bucket,prior_memory_state,prior_memory_persistence_regime,prior_memory_entropy_regime,prior_memory_complexity_regime,memory_impulse_side,memory_impulse_pattern \
  --splits legacy_context:2010-01-01:2015-12-31,transition:2016-01-01:2020-12-31,recent_development:2021-01-01:2024-12-31 \
  --primary-split recent_development \
  --supporting-splits transition \
  --entry-price-col open \
  --entry-lag-bars 1 \
  --exit-price-col close \
  --round-trip-cost-points 1.5 \
  --event-bootstrap-samples 2000 \
  --event-placebo-samples 2000 \
  --artifact-name memory_impulse_event_temporal_gate
```

## Promotion Rule

Do not create a candidate unless the temporal report passes the event gate in recent development and transition support. If the only good slices are `hour` or `session_bucket`, reject it as a disguised time-of-day effect.

## Result

Artifact: `results/research_master/signal_research/memory_impulse_event_temporal_gate_temporal.md`

Verdict: no signal/horizon pair passed the temporal pre-candidate gate or the temporal event-signal gate.

Key evidence:

- Export generated 4,912,414 rows and only 355 active signal rows.
- Recent development had only 28 active rows, below the 30-row minimum; its positive means had negative bootstrap CI lows and negative medians.
- Transition support failed hard: every horizon was negative after costs, from -2.0191 points at 1 bar to -8.7140 points at 24 bars.
- Legacy context was also negative across every horizon.
- The strongest recent context slices were tiny `hour` / `session_bucket` groups, especially five late-RTH rows. Those are diagnostic only and violate the no-time-tweaking stop rule.

Conclusion: do not create a candidate and do not tune thresholds on this same sample.
