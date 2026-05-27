# Power-Hour Accepted-Trend Continuation Signal Gate

Date: 2026-05-21

Status: rejected pre-candidate signal hypothesis

## Hypothesis

NQ short-horizon edge, if present, may appear late in the RTH session after the market has already accepted a strong intraday direction. If price is near the session extreme, on the same side of RTH VWAP, and still moving in that direction during the 15:00-15:30 ET window, continuation into the close may be driven by risk reduction, hedging, and closing-flow pressure.

This is not a failed-auction branch, not a gap-and-go branch, and not an opening compression breakout branch. It tests late-day accepted trend persistence before any strategy candidate exists.

## Fixed Pre-Run Assumptions

- This is not a `CANDIDATE_CONFIGS` entry.
- The signal uses completed bars only.
- RTH open, high, low, VWAP, session move, and close location are computed point-in-time through the current completed bar.
- A signal requires a minimum accepted session move, a close near the current RTH extreme, VWAP alignment, and recent momentum in the same direction.
- Only the first qualifying signal per RTH session is active.
- The signal gate must use next-bar-open entry timing.
- Use 2010-2024 for development/context and reserve 2025+ as recent holdout until development evidence passes.

## User-Run Commands

```bash
python3.12 scripts/export_power_hour_signal_csv.py \
  --start 2010-01-01 \
  --end 2024-12-31 \
  --artifact-name power_hour_continuation_dev_2010_2024
```

Then:

```bash
python3.12 scripts/run_temporal_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/power_hour_continuation_dev_2010_2024.csv \
  --signal-cols candidate_signal,power_hour_score \
  --context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side,closing_flow_side,close_location,momentum_state,power_hour_pattern \
  --splits legacy_context:2010-01-01:2015-12-31,transition:2016-01-01:2020-12-31,recent_development:2021-01-01:2024-12-31 \
  --primary-split recent_development \
  --supporting-splits transition \
  --entry-price-col open \
  --entry-lag-bars 1 \
  --exit-price-col close \
  --round-trip-cost-points 1.5 \
  --artifact-name power_hour_continuation_temporal_gate
```

## Promotion Rule

Do not create a strategy candidate unless the temporal signal report shows recent-development raw IC, signed forward return after cost, period stability, and enough transition-era support. Winning direction or hour slices from this report are diagnostic only unless they survive a separate pre-registered sample.

## Result

Rejected. The temporal report found no signal/horizon pair that passed the pre-candidate gate.

- Report: `results/research_master/signal_research/power_hour_continuation_temporal_gate_temporal.md`
- Event re-score: `results/research_master/signal_research/power_hour_continuation_event_temporal_gate_temporal.md`
- Postmortem: `docs/research_postmortems/2026-05-22_power_hour_signal_gate_rejection.md`
