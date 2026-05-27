# Options Gamma Wall Reversion Signal Gate

Date: 2026-05-24

Status: rejected pre-candidate signal hypothesis

## Hypothesis

In positive-gamma option regimes, the dominant gamma wall may behave like a pinning level. When NQ trades a moderate distance away from the last-known gamma wall, short-horizon returns may mean-revert back toward that wall.

This is structurally different from the rejected time-of-day, gap, compression, failed-continuation, power-hour, and memory-impulse ideas. It uses external options positioning context, not only intraday price geometry.

## Fixed Pre-Run Assumptions

- This is not a `CANDIDATE_CONFIGS` entry.
- The signal uses only completed bar prices and options-flow rows with `options_available_time <= bar time`.
- The gamma wall distance is recomputed from the current bar close and the last-known wall strike; it does not use the stale distance from the options snapshot as the trading distance.
- Required regime: `options_gamma_environment == positive_gamma` and `options_gamma_wall_role == pinning_wall`.
- Direction is reversion toward the wall: below wall is long, above wall is short.
- Default distance band is 10 to 100 NQ points from the wall.
- Default options-flow freshness cutoff is 120 days.
- Default cooldown is 15 bars to reduce duplicate signals during one excursion.
- `hour`, `session_bucket`, and `vwap_side` are retained only as audit context.
- Running the export over 2010-2024 is a full-sample signal scan and testing debt.
- 2025+ remains untouched holdout unless the 2010-2024 temporal gate passes.

## User-Run Commands

Export prepared point-in-time signals:

```bash
python3.12 scripts/export_options_gamma_wall_signal_csv.py \
  --start 2010-01-01 \
  --end 2024-12-31 \
  --artifact-name options_gamma_wall_dev_2010_2024
```

Then run the event-enhanced temporal gate:

```bash
python3.12 scripts/run_temporal_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/options_gamma_wall_dev_2010_2024.csv \
  --signal-cols candidate_signal,options_gamma_wall_score \
  --context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side,options_gamma_environment,options_gex_regime,options_gamma_wall_role,options_call_wall_role,options_put_wall_role,options_flow_age_bucket,gamma_wall_side,options_gamma_wall_pattern \
  --splits legacy_context:2010-01-01:2015-12-31,transition:2016-01-01:2020-12-31,recent_development:2021-01-01:2024-12-31 \
  --primary-split recent_development \
  --supporting-splits transition \
  --entry-price-col open \
  --entry-lag-bars 1 \
  --exit-price-col close \
  --round-trip-cost-points 1.5 \
  --stress-round-trip-cost-points 2.0,4.25 \
  --event-bootstrap-samples 2000 \
  --event-placebo-samples 2000 \
  --artifact-name options_gamma_wall_dev_2010_2024_event_temporal_gate
```

## Promotion Rule

Do not create a candidate unless the temporal event gate passes recent development, transition support, and the 2.0 / 4.25 point cost-stress checks. If the only positive slices are `hour`, `session_bucket`, or tiny options age buckets, reject it as overfit diagnostics rather than edge.

## Result

Artifact: `results/research_master/signal_research/options_gamma_wall_dev_2010_2024_event_temporal_gate_temporal.md`

Postmortem: `docs/research_postmortems/2026-05-25_options_gamma_wall_signal_gate_rejection.md`

Verdict: no signal/horizon pair passed the temporal pre-candidate gate or temporal event-signal gate.

Key evidence:

- Export generated 4,912,414 rows and 75,744 active rows.
- Recent development had 4,485 active rows, enough to evaluate.
- Best recent row was `options_gamma_wall_score` at 3 bars: IC `0.000416`, mean signed return after 1.5-point cost `-1.4793`, hit rate `48.52%`, bootstrap CI low `-1.7211`, and placebo p-value `0.4065`.
- Transition support also failed: best transition row at 1 bar had mean signed return after cost `-1.4885` and hit rate `41.05%`.
- No row survived the 2.0 / 4.25 point cost-stress checks.

Conclusion: reject the hypothesis and do not tune wall-distance, cooldown, hour, session, or options-age filters on this same sample.
