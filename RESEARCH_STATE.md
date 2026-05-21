# Research State

Date: 2026-05-20

## Current State

- Failed-auction quality is rejected. Keep those candidates only for reproducibility.
- Deleting old run folders does not reduce multiple-testing debt. Family run-count floors in `RESEARCH_CONFIG` remain the source of truth.
- The microstructure liquidity-taking trend probe is rejected after the stopped development run.
- The active validation queue is empty.
- `config/research_freeze.json` is an archived rejected-candidate snapshot, not an active freeze.
- The next work is pre-candidate signal research, not another strategy variant.
- TBBO data is execution-realism evidence only unless a separate, pre-registered data protocol says otherwise.

## Process Guard

Codex may run code checks, unit tests, freeze checks, and artifact inspection. Codex should not run historical backtests, full-dataset signal scans, probes, or candidate sweeps unless explicitly told.

## Next User-Run Path

1. Build or export a prepared signal CSV with point-in-time columns only.
2. Run the pre-candidate signal research gate on that CSV.
3. Write a fresh hypothesis only if raw IC, signed forward returns, and period stability justify a candidate.
4. Freeze exactly one candidate only after the signal report exists.

The current freeze manifest should pass reproducibility checks only. It should not be used to start a new validation run.

Prepared signal export command:

```bash
python3 scripts/export_prepared_signal_csv.py \
  --candidate <candidate_name> \
  --start 2021-01-01
```

This is not trade execution, but using the full historical range is still a full-sample signal scan.
