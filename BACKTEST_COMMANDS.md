# Backtest Commands

Run historical backtests yourself from:

```bash
cd /Users/novo/trading_strategy/nq-scalper-backtest
```

## Current Freeze Manifest

There is no active validation candidate. Do not run another historical candidate until a pre-candidate signal report and a written hypothesis justify one.

There is no active pre-candidate signal gate queued.

`config/research_freeze.json` is an archived rejected-candidate snapshot. A passing freeze check means reproducibility only; it is not an active run instruction.

The 2026-05-22 event-gate metric audit tightened report boolean handling and event Monte Carlo implementation. It did not create a new run instruction.

The 2026-05-24 rejection map / feature inventory is saved at:

```text
docs/research_postmortems/2026-05-24_signal_gate_rejection_map_and_feature_inventory.md
```

Recommended next work is a fresh ex-ante structural hypothesis or a narrow platform audit, not another historical candidate run.

Future signal gates should include cost-stress survival:

```text
--stress-round-trip-cost-points 2.0,4.25
```

Latest TBBO baseline report:

```text
results/research_master/tbbo_execution_baseline/tbbo_execution_baseline.md
```

Rejected latest branch:

```text
edge_microstructure_liquidity_taking_trend_probe
liquidity_absorption_2021_signal_gate
compression_breakout_2021_signal_gate
gap_go_temporal_gate
power_hour_continuation_temporal_gate
power_hour_continuation_event_temporal_gate
memory_impulse_event_temporal_gate
options_gamma_wall_dev_2010_2024_event_temporal_gate
```

## Pre-Run Checks

These do not run a backtest:

```bash
python3 main_backtest.py --list-candidates

python3 scripts/check_research_freeze.py \
  --manifest config/research_freeze.json
```

## Event-Enhanced Temporal Signal Gate

No pre-candidate signal gate is currently queued. For later hypotheses, use this event-enhanced temporal gate template only after replacing placeholders:

The report writes the legacy IC gate plus the event gate: active-event mean/median, bootstrap CI, placebo comparison, hit rate, period stability, and temporal event eligibility.

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

The gate should score from next-bar open to the horizon close, not signal-bar close to horizon close. Running the report over historical data is still a signal scan. Treat it as testing debt, not validation. Codex should not run it without explicit instruction.

Latest rejected signal gate:

```text
results/research_master/signal_research/liquidity_absorption_2021_signal_gate_next_bar_open.md
```

Latest rejected compression breakout signal gate:

```text
results/research_master/signal_research/compression_breakout_2021_signal_gate.md
```

Latest rejected gap-and-go signal gate:

```text
results/research_master/signal_research/gap_go_temporal_gate_temporal.md
```

Latest rejected power-hour signal gate:

```text
results/research_master/signal_research/power_hour_continuation_temporal_gate_temporal.md
results/research_master/signal_research/power_hour_continuation_event_temporal_gate_temporal.md
```

Latest rejected memory-impulse signal gate:

```text
results/research_master/signal_research/memory_impulse_event_temporal_gate_temporal.md
```

Latest rejected options gamma-wall signal gate:

```text
results/research_master/signal_research/options_gamma_wall_dev_2010_2024_event_temporal_gate_temporal.md
```

Do not rerun or mutate this into a candidate unless a real implementation bug is found or a new ex-ante hypothesis is written before touching the same sample again.

## Next Non-Backtest Work

Audit the existing TBBO trade-audit path:

```text
scripts/audit_tbbo_execution_baseline.py
scripts/audit_trades_with_tbbo.py
backtest/tbbo_trade_audit.py
data/processed/tbbo/tbbo_minute_execution_stats.csv
data/processed/tbbo/tbbo_daily_execution_stats.csv
```

This is for spread, depth, fill shortfall, and cost realism. Do not use TBBO as a filter-mining surface.

Regenerate the baseline report with:

```bash
python3.12 scripts/audit_tbbo_execution_baseline.py
```

## Saved-Run Audit Sequence

After the user-run backtest finishes:

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

## Paper Replay Observation

This is a live-style replay, not the main historical strategy backtest. Use it when you want execution observations, skipped-decision rows, and shortfall summaries:

```bash
python3 scripts/run_paper_trader.py \
  --candidate <candidate_name> \
  --start 2024-01-01 \
  --end 2024-01-31 \
  --warmup-bars 2500 \
  --quiet
```

Outputs include:

- `events.csv`
- `trades.csv`
- `execution_observations.csv`
- `execution_observation_summary.csv`

## Archived Branches

Failed-auction quality and failed-auction frequency candidates are archived for reproduction only. They are not active validation candidates, and deleting their result folders does not reduce multiple-testing debt.

The microstructure execution-first probe is also archived after rejection. Do not mine same-sample long/short, hour, or prop-rule variants from that run.
