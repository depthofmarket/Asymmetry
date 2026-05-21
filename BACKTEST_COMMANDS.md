# Backtest Commands

Run historical backtests yourself from:

```bash
cd /Users/novo/trading_strategy/nq-scalper-backtest
```

## Current Freeze Manifest

There is no active validation candidate. Do not run another historical candidate until a pre-candidate signal report and a written hypothesis exist.

`config/research_freeze.json` is an archived rejected-candidate snapshot. A passing freeze check means reproducibility only; it is not an active run instruction.

Rejected latest branch:

```text
edge_microstructure_liquidity_taking_trend_probe
```

## Pre-Run Checks

These do not run a backtest:

```bash
python3 main_backtest.py --list-candidates

python3 scripts/check_research_freeze.py \
  --manifest config/research_freeze.json
```

## Pre-Candidate Signal Gate

First export a prepared point-in-time signal CSV. This builds signal rows and context from the existing strategy-brain seam, but it does not execute trades:

```bash
python3 scripts/export_prepared_signal_csv.py \
  --candidate <candidate_name> \
  --start 2021-01-01
```

Then run the signal gate. It reads the prepared CSV and writes IC, forward-return, period-stability, and context diagnostics. It does not replay strategy logic or create trades.

```bash
python3 scripts/run_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/<artifact>.csv \
  --signal-cols candidate_signal \
  --context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side \
  --round-trip-cost-points 1.5
```

Running the export over a full historical range is still a full-sample signal scan. Treat it as testing debt, not validation. Codex should not run it without explicit instruction.

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
