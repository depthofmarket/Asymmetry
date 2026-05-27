# Options Gamma Wall Signal Gate Rejection

Date: 2026-05-25

## Verdict

Reject the positive-gamma pinning-wall reversion hypothesis. Do not create a `CANDIDATE_CONFIGS` entry from it.

## Artifacts

- Export: `results/research_master/signal_exports/options_gamma_wall_dev_2010_2024.csv`
- Manifest: `results/research_master/signal_exports/options_gamma_wall_dev_2010_2024_manifest.md`
- Temporal report: `results/research_master/signal_research/options_gamma_wall_dev_2010_2024_event_temporal_gate_temporal.md`
- Recent development report: `results/research_master/signal_research/options_gamma_wall_dev_2010_2024_event_temporal_gate_recent_development.md`

## Key Evidence

- Export generated 4,912,414 rows and 75,744 active rows.
- Active rows by split: 51,706 legacy context, 19,553 transition, and 4,485 recent development.
- No signal/horizon pair passed the temporal pre-candidate gate.
- No signal/horizon pair passed the temporal event-signal gate.
- No row survived the configured `2.0` and `4.25` point stress costs.
- Best recent row was `options_gamma_wall_score` at 3 bars: IC `0.000416`, mean signed return after 1.5-point cost `-1.4793`, hit rate `48.52%`, bootstrap CI low `-1.7211`, placebo p-value `0.4065`.
- Transition support was also negative after cost. Best transition row at 1 bar had mean signed return after cost `-1.4885` and hit rate `41.05%`.

## Diagnosis

The hypothesis did not show predictive value. Before costs, the best recent evidence was only about `+0.0207` points per active event, which is far below even the base round-trip cost. The IC values are effectively zero and the hit rates do not clear the event gate.

Do not mine `hour`, `session_bucket`, options-age buckets, or wall-side slices from this same sample. Any future options-flow idea needs a different mechanism, not threshold tuning around this rejection.
