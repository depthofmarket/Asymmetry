# Implementation Progress

Date: 2026-05-21
Status: Research queue empty; infrastructure usable; evidence gate is the blocker.

## Current Truth

- There is no active validation candidate.
- `config/research_freeze.json` is an archived rejected-candidate snapshot for reproducibility, not a live permission slip to run or promote `edge_microstructure_liquidity_taking_trend_probe`.
- Failed-auction quality is rejected. The microstructure liquidity-taking trend probe is rejected. Same-sample long/short, hour, or prop-rule mutations from those branches are not valid next work.
- `RESEARCH_CONFIG["next_validation_candidates"]` is empty. Family run-count floors remain the source of multiple-testing debt even if old result folders are deleted.

## Completed Platform Work

- Historical backtest engine, research reports, stress tests, walk-forward outputs, prop-firm reports, paper runtime, and live-style audit paths exist.
- The pre-candidate signal workflow exists:
  - `scripts/export_prepared_signal_csv.py`
  - `scripts/run_signal_research_report.py`
  - `backtest/signal_export.py`
  - `backtest/signal_research.py`
- Broad candidate batch launchers are not active research queues; they are reproduction tools and should stay guarded.

## Immediate Work

1. Keep docs, config, and command files aligned around the empty queue.
2. Run no historical backtest, full-dataset probe, full-sample signal scan, or candidate sweep from automation without explicit user instruction.
3. Use pre-candidate signal research before adding any new `CANDIDATE_CONFIGS` entry.
4. Require raw IC, signed forward return after cost, and period stability before writing a fresh hypothesis.
5. Freeze exactly one new candidate only after the signal report and hypothesis exist.

## User-Run Signal Gate

This export is not trade execution, but using the full historical range is still a full-sample signal scan and testing debt:

```bash
python3 scripts/export_prepared_signal_csv.py \
  --candidate <candidate_name> \
  --start 2021-01-01
```

Then:

```bash
python3 scripts/run_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/<artifact>.csv \
  --signal-cols candidate_signal \
  --context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side \
  --round-trip-cost-points 1.5
```

## Stop Rules

- Do not run "5-10 candidates" just to find a winner.
- Do not revive failed-auction quality unless a real implementation or metric bug is found.
- Do not use TBBO to mine edge; use it for spread, depth, and fill-realism checks.
- Treat in-sample prop-firm pass probability as rejection evidence only, not approval evidence.

## Verification Baseline

Non-backtest checks for this state:

```bash
python3.12 -m unittest tests.test_signal_export tests.test_signal_research tests.test_research_freeze
python3.12 main_backtest.py --list-candidates
python3.12 scripts/check_research_freeze.py --manifest config/research_freeze.json
```
