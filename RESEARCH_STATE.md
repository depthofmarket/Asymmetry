# Research State

Date: 2026-05-25

## Current State

- Failed-auction quality is rejected. Keep those candidates only for reproducibility.
- Deleting old run folders does not reduce multiple-testing debt. Family run-count floors in `RESEARCH_CONFIG` remain the source of truth.
- The microstructure liquidity-taking trend probe is rejected after the stopped development run.
- The liquidity absorption / failed-continuation pre-candidate signal gate is rejected, including the stricter next-bar-open re-score. Do not create a candidate from it.
- The active validation queue is empty.
- `config/research_freeze.json` is an archived rejected-candidate snapshot, not an active freeze.
- The opening compression breakout continuation pre-candidate signal gate is rejected. Do not create a candidate from it.
- The RTH gap-and-go opening-range continuation pre-candidate signal gate is rejected. Do not create a candidate from it.
- The power-hour accepted-trend continuation pre-candidate signal gate is rejected. Do not create a candidate from it.
- The memory-impulse continuation pre-candidate signal gate is rejected. Do not create a candidate from it.
- The options gamma-wall reversion pre-candidate signal gate is rejected. Do not create a candidate from it.
- There is no active fresh hypothesis queued for execution.
- The signal gate now has an event-signal path for sparse signals: active-event mean/median after cost, bootstrap confidence interval, placebo comparison, hit rate, period stability, and temporal event eligibility.
- The power-hour event-gate re-score is also rejected. Recent 12/24-bar events passed the event gate, but transition support failed and no row passed temporal event eligibility.
- The 2026-05-22 bug/metric audit tightened gate verdict boolean parsing and event Monte Carlo implementation. This is platform hardening, not a reason to promote any rejected signal.
- Future signal work should use the temporal signal gate instead of a single 2021+ aggregate by default.
- Use 2010-2024 for development/context and keep 2025+ as recent holdout until a signal passes development evidence.
- TBBO data is execution-realism evidence only unless a separate, pre-registered data protocol says otherwise.
- Rejection map / feature inventory: `docs/research_postmortems/2026-05-24_signal_gate_rejection_map_and_feature_inventory.md`.
- Recommended next work is a TBBO execution-realism audit path, not another time-of-day or horizon mutation.
- TBBO execution baseline is implemented and generated at `results/research_master/tbbo_execution_baseline/tbbo_execution_baseline.md`.
- Current TBBO baseline verdict: 1.5 points is OK for typical active-contract spread, but too low for tail trade-vs-mid conditions.
- The signal and temporal signal gates now support stress-cost survival via `--stress-round-trip-cost-points`; current command templates use `2.0,4.25`.

## Process Guard

Codex may run code checks, unit tests, freeze checks, and artifact inspection. Codex should not run historical backtests, full-dataset signal scans, probes, or candidate sweeps unless explicitly told.

## Next User-Run Path

1. Use `--stress-round-trip-cost-points 2.0,4.25` on future signal gates.
2. Use the TBBO baseline report to decide whether future validation should stress cost above 1.5 points in tail-liquidity windows.
3. Audit execution realism with TBBO against saved trades only when enough trade overlap exists.
4. If choosing signal mining again, write a fresh ex-ante hypothesis first.
5. Build or export a prepared signal CSV with point-in-time columns only, normally over 2010-2024 development/context data.
6. Run the event-enhanced temporal pre-candidate signal gate on that CSV.
7. Write a candidate only if signal evidence justifies it before looking at 2025+.
8. Freeze exactly one candidate only after the signal report exists.

The current freeze manifest should pass reproducibility checks only. It should not be used to start a new validation run.

Latest rejected gap-and-go signal gate:

- Report: `results/research_master/signal_research/gap_go_temporal_gate_temporal.md`
- Verdict: no signal/horizon pair passed the temporal pre-candidate gate.
- Do not mine the recent long-side 12/24-bar diagnostic slice into a candidate.

Latest rejected power-hour signal gate:

- Report: `results/research_master/signal_research/power_hour_continuation_temporal_gate_temporal.md`
- Event re-score: `results/research_master/signal_research/power_hour_continuation_event_temporal_gate_temporal.md`
- Verdict: no signal/horizon pair passed the temporal pre-candidate gate.
- Event verdict: no signal/horizon pair passed the temporal event-signal gate.
- Do not mine the recent 12/24-bar continuation result into a candidate.

Latest rejected memory-impulse signal gate:

- Hypothesis doc: `docs/research_hypotheses/2026-05-22_memory_impulse_signal_gate.md`
- Postmortem: `docs/research_postmortems/2026-05-24_memory_impulse_signal_gate_rejection.md`
- Report: `results/research_master/signal_research/memory_impulse_event_temporal_gate_temporal.md`
- Verdict: no signal/horizon pair passed the temporal pre-candidate gate or temporal event-signal gate.
- Do not mine tiny recent `hour` / `session_bucket` wins into a candidate.

Rejected memory-impulse implementation artifacts:

- Exporter: `scripts/export_memory_impulse_signal_csv.py`
- Signal module: `backtest/memory_impulse_signal.py`
- Artifact name: `memory_impulse_dev_2010_2024`
- Gate artifact name: `memory_impulse_event_temporal_gate`
- Structural idea: CUSUM impulse continuation in prior persistent/low-complexity market-memory state, with no time-window filter.

Prepared signal export template for future development/context work:

```bash
python3.12 scripts/<export_fresh_hypothesis_signal>.py \
  --start 2010-01-01 \
  --end 2024-12-31 \
  --artifact-name <hypothesis>_dev_2010_2024
```

Template only. Do not paste this command literally until a concrete exporter and artifact name exist.

Latest rejected options gamma-wall signal gate:

- Hypothesis doc: `docs/research_hypotheses/2026-05-24_options_gamma_wall_signal_gate.md`
- Postmortem: `docs/research_postmortems/2026-05-25_options_gamma_wall_signal_gate_rejection.md`
- Report: `results/research_master/signal_research/options_gamma_wall_dev_2010_2024_event_temporal_gate_temporal.md`
- Verdict: no signal/horizon pair passed the temporal pre-candidate gate or temporal event-signal gate.
- Do not mine wall-distance, cooldown, `hour`, `session_bucket`, or options-age filters from this same sample.

Latest rejected signal gate:

- Report: `results/research_master/signal_research/liquidity_absorption_2021_signal_gate_next_bar_open.md`
- Verdict: no signal passed the pre-candidate gate.
- Do not mine the one positive hour-11 / 24-bar slice into a candidate without a separate pre-registered sample.

Latest rejected compression breakout signal gate:

- Report: `results/research_master/signal_research/compression_breakout_2021_signal_gate.md`
- Verdict: no signal passed the pre-candidate gate.
- Do not mine the short-side 24-bar context slice into a same-sample candidate.
