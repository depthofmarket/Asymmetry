# RTH Gap-And-Go Opening-Range Signal Gate

Date: 2026-05-21

Status: rejected pre-candidate signal hypothesis

## Hypothesis

NQ short-horizon edge, if present, may appear when a meaningful RTH gap does not fill during the opening range and then breaks the opening range in the gap direction. This is a continuation premise: the overnight repricing is accepted, the opening auction fails to mean-revert, and the first post-opening-range break may attract directional flow.

This is not a failed-auction salvage branch, not a liquidity-absorption failed-continuation branch, and not a compression-breakout variant. It explicitly tests gap acceptance and opening-range continuation before any strategy candidate exists.

## Fixed Pre-Run Assumptions

- This is not a `CANDIDATE_CONFIGS` entry.
- The signal uses completed bars only.
- Prior RTH close and prior RTH range come from the prior completed RTH session.
- A signal requires a minimum absolute gap, a minimum gap-to-prior-range ratio, an opening range that does not fill the gap, and a post-opening-range breakout in the gap direction.
- VWAP alignment is a pressure filter, not a same-sample optimization target.
- The signal gate must use next-bar-open entry timing.
- Use 2010-2024 for development/context and reserve 2025+ as recent holdout until development evidence passes.

## User-Run Commands

```bash
python3.12 scripts/export_gap_go_signal_csv.py \
  --start 2010-01-01 \
  --end 2024-12-31 \
  --artifact-name gap_go_dev_2010_2024
```

Then:

```bash
python3.12 scripts/run_temporal_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/gap_go_dev_2010_2024.csv \
  --signal-cols candidate_signal,gap_go_score \
  --context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side,gap_direction,gap_hold_status,opening_range_breakout_side,gap_go_pattern \
  --splits legacy_context:2010-01-01:2015-12-31,transition:2016-01-01:2020-12-31,recent_development:2021-01-01:2024-12-31 \
  --primary-split recent_development \
  --supporting-splits transition \
  --entry-price-col open \
  --entry-lag-bars 1 \
  --exit-price-col close \
  --round-trip-cost-points 1.5 \
  --artifact-name gap_go_temporal_gate
```

## Promotion Rule

Do not create a strategy candidate unless the temporal signal report shows recent-development raw IC, signed forward return after cost, period stability, and enough transition-era support. Winning context slices from this report are diagnostic only unless they survive a separate pre-registered sample.

## Result

Rejected. The temporal report found no signal/horizon pair that passed the pre-candidate gate.

- Report: `results/research_master/signal_research/gap_go_temporal_gate_temporal.md`
- Postmortem: `docs/research_postmortems/2026-05-21_gap_go_signal_gate_rejection.md`
