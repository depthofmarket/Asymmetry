# Temporal Signal Gate Protocol

Date: 2026-05-21

Status: active research protocol

## Purpose

Use the full historical record without pretending old edge is equal to recent edge. A signal that only works in 2010-2015 should not become a modern NQ scalper candidate. A signal that works in recent data but collapses in the transition era should be treated cautiously. The latest data must not be consumed casually during idea search.

## Default Windows

- `legacy_context`: 2010-01-01 through 2015-12-31. Historical context only.
- `transition`: 2016-01-01 through 2020-12-31. Supporting evidence.
- `recent_development`: 2021-01-01 through 2024-12-31. Primary development gate.
- `recent_holdout`: 2025-01-01 onward. Reserved until a signal passes development evidence.

## Promotion Standard

A pre-candidate signal should not become a strategy candidate unless:

- The recent development split passes the raw signal gate.
- The transition split has enough active observations, positive signed return after cost, and non-trivial IC.
- Context slices are treated as diagnostics, not candidate definitions.
- The 2025+ holdout is untouched until the signal has passed development evidence and a candidate/hypothesis is written.

## Command Template

```bash
python3 scripts/<export_fresh_hypothesis_signal>.py \
  --start 2010-01-01 \
  --end 2024-12-31 \
  --artifact-name <hypothesis>_dev_2010_2024

python3 scripts/run_temporal_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/<hypothesis>_dev_2010_2024.csv \
  --signal-cols candidate_signal,<score_column> \
  --context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side \
  --splits legacy_context:2010-01-01:2015-12-31,transition:2016-01-01:2020-12-31,recent_development:2021-01-01:2024-12-31 \
  --primary-split recent_development \
  --supporting-splits transition \
  --entry-price-col open \
  --entry-lag-bars 1 \
  --exit-price-col close \
  --round-trip-cost-points 1.5 \
  --stress-round-trip-cost-points 2.0,4.25 \
  --artifact-name <hypothesis>_temporal_gate
```

Running this over historical data is still a signal scan and testing debt. Do not run it from automation without explicit user instruction.
