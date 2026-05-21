# Action Plan

Date: 2026-05-20

## Current Decision

Failed-auction quality is rejected. Do not create more variants from that branch unless a real implementation or metric bug is found. Deleted result folders do not erase testing debt; configured family run-count floors remain the source of truth.

## Active Queue

No candidate is active. `edge_microstructure_liquidity_taking_trend_probe` is rejected after the stopped development run.

## Freeze Manifest

`config/research_freeze.json` is archived for the rejected microstructure probe. A passing manifest hash means the rejected snapshot is reproducible; it does not mean there is an active candidate to run or promote.

## Immediate Work

1. Keep the repo inspectable and the validation queue empty.
2. Use pre-candidate signal research before any new `CANDIDATE_CONFIGS` entry.
3. Require raw IC, signed forward-return, and period-stability evidence before writing a fresh hypothesis.
4. Freeze exactly one candidate only after the signal report and hypothesis exist.

## Pre-Candidate Signal Gate

Export a prepared point-in-time signal CSV before running the gate. The export builds signal rows and context only; it does not execute trades.

```bash
python3 scripts/export_prepared_signal_csv.py \
  --candidate <candidate_name> \
  --start 2021-01-01
```

Then run the gate on the exported CSV:

```bash
python3 scripts/run_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/<artifact>.csv \
  --signal-cols candidate_signal \
  --context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side \
  --round-trip-cost-points 1.5
```

Running the export over the full historical file is still a full-sample signal scan, so count it as testing debt.

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
