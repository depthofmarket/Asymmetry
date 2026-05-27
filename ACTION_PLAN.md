# Action Plan

Date: 2026-05-25

## Current Decision

Failed-auction quality, the microstructure liquidity-taking probe, liquidity absorption failed-continuation, opening compression breakout continuation, RTH gap-and-go opening-range continuation, power-hour accepted-trend continuation, memory impulse, and options gamma-wall reversion are rejected. Do not create more variants from those branches unless a real implementation or metric bug is found. Deleted result folders do not erase testing debt; configured family run-count floors remain the source of truth.

The rejection map is saved at `docs/research_postmortems/2026-05-24_signal_gate_rejection_map_and_feature_inventory.md`.

The TBBO baseline report is saved at `results/research_master/tbbo_execution_baseline/tbbo_execution_baseline.md`.

The signal gates now enforce optional cost-stress survival. Current templates use `--stress-round-trip-cost-points 2.0,4.25`.

## Active Queue

No validation candidate is active. No pre-candidate signal gate is currently queued.

Recommended next work is a new ex-ante structural hypothesis or a narrow platform audit, not another time-of-day, horizon, wall-distance, cooldown, or options-age mutation.

## Freeze Manifest

`config/research_freeze.json` is archived for the rejected microstructure probe. A passing manifest hash means the rejected snapshot is reproducible; it does not mean there is an active candidate to run or promote.

## Immediate Work

1. Keep the repo inspectable and the validation queue empty.
2. Do not convert the liquidity absorption hour-11 / 24-bar slice into a candidate from the same sample.
3. Do not convert the compression breakout short-side / 24-bar slice into a candidate from the same sample.
4. Do not convert the gap-and-go recent long-side 12/24-bar slice into a candidate from the same sample.
5. Do not convert the power-hour recent 12/24-bar continuation result into a candidate from the same sample.
6. Do not convert the power-hour recent 12/24-bar event-gate pass into a candidate; temporal event eligibility failed.
7. Do not convert the memory-impulse recent positive rows into a candidate; temporal event eligibility failed.
8. Keep 2025+ as recent holdout until a signal passes development evidence.
9. Require event-gate, signed forward-return, and period-stability evidence before writing a candidate.
10. Freeze exactly one candidate only after the signal report and hypothesis exist.
11. Treat the 2026-05-22 event-gate metric audit as infrastructure hardening only; it did not create an active candidate.
12. Treat memory-impulse tiny `hour` / `session_bucket` wins as rejection evidence, not a filter to mine.
13. Inspect the TBBO trade-audit path and verify whether it can align saved trades to processed TBBO minute stats without look-ahead.
14. Use options-flow only as a pre-registered regime context if signal mining resumes.
15. Use the TBBO baseline verdict when choosing future validation cost stress: typical active-contract spread is inside 1.5 points, but tail trade-vs-mid cost is not.
16. Do not promote a signal that passes at 1.5 points but fails the configured stress-cost columns.
17. Do not convert the options gamma-wall idea into a candidate; the temporal event gate rejected it.

## Latest Rejected Signal

Hypothesis doc:

```text
docs/research_hypotheses/2026-05-24_options_gamma_wall_signal_gate.md
```

Postmortem:

```text
docs/research_postmortems/2026-05-25_options_gamma_wall_signal_gate_rejection.md
```

Report:

```text
results/research_master/signal_research/options_gamma_wall_dev_2010_2024_event_temporal_gate_temporal.md
```

## Temporal Pre-Candidate Signal Gate

Future hypotheses should use the event-enhanced temporal signal gate. Template only; do not paste this literally until a concrete exporter and artifact name exist:

```bash
python3.12 scripts/run_temporal_signal_research_report.py \
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
  --event-bootstrap-samples 2000 \
  --event-placebo-samples 2000 \
  --artifact-name <hypothesis>_event_temporal_gate
```

The gate should score from next-bar open to the horizon close, not signal-bar close to horizon close. Running the report over historical data is still a signal scan, so count it as testing debt.

Latest rejected signal report:

```text
results/research_master/signal_research/liquidity_absorption_2021_signal_gate_next_bar_open.md
```

Latest rejected compression breakout report:

```text
results/research_master/signal_research/compression_breakout_2021_signal_gate.md
```

Latest rejected gap-and-go report:

```text
results/research_master/signal_research/gap_go_temporal_gate_temporal.md
```

Latest rejected power-hour report:

```text
results/research_master/signal_research/power_hour_continuation_temporal_gate_temporal.md
results/research_master/signal_research/power_hour_continuation_event_temporal_gate_temporal.md
```

Latest rejected memory-impulse report:

```text
results/research_master/signal_research/memory_impulse_event_temporal_gate_temporal.md
```

## Saved-Run Audits

Use these only after a future frozen candidate run exists:

```bash
python3 scripts/check_research_freeze.py \
  --manifest config/research_freeze.json \
  --run-dir results/runs/<run_label> \
  --phase development

python3 scripts/check_research_discipline.py \
  --run-dir results/runs/<run_label>

python3 scripts/audit_execution_realism.py \
  --run-dir results/runs/<run_label> \
  --candidate <candidate_name>

python3 scripts/audit_bar_exposure.py \
  --run-dir results/runs/<run_label>

python3 scripts/check_prop_research_gate.py \
  --run-dir results/runs/<run_label>
```

## Stop Rules

- Reject if trade PF, bar PF, execution realism, or walk-forward evidence fails broadly.
- Treat any promising slice as a future hypothesis only.
- Do not add any candidate until the pre-candidate signal report passes.
- Do not use TBBO to mine filters; use it only for spread, depth, and fill realism.
- Use prop-firm reports for Balanced EV triage after research gates exist, not as in-sample approval evidence.
