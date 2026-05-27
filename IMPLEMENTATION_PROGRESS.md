# Implementation Progress

Date: 2026-05-25
Status: Validation queue empty; options gamma-wall pre-candidate signal gate rejected.

## Current Truth

- There is no active validation candidate.
- `config/research_freeze.json` is an archived rejected-candidate snapshot for reproducibility, not a live permission slip to run or promote `edge_microstructure_liquidity_taking_trend_probe`.
- Failed-auction quality is rejected. The microstructure liquidity-taking trend probe is rejected. Same-sample long/short, hour, or prop-rule mutations from those branches are not valid next work.
- Liquidity absorption / failed continuation is rejected by the pre-candidate signal gate and the stricter next-bar-open re-score. Same-sample hour/horizon slices are diagnostic only.
- Opening compression breakout continuation is rejected by the pre-candidate signal gate. Same-sample short-side / 24-bar slices are diagnostic only.
- RTH gap-and-go opening-range continuation is rejected by the temporal pre-candidate signal gate. Same-sample recent long-side 12/24-bar slices are diagnostic only.
- Power-hour accepted-trend continuation is rejected by the temporal pre-candidate signal gate. Same-sample recent 12/24-bar continuation results are diagnostic only.
- The signal research gate includes a sparse event path: active-event mean/median after cost, bootstrap CI, random timestamp placebo comparison, hit rate, period stability, and temporal event eligibility.
- Power-hour passed the event gate in recent development at 12/24 bars, but transition support failed and temporal event eligibility rejected every row.
- The event-gate metric audit now explicitly coerces boolean verdict columns and bounds event bootstrap/placebo draw arrays. The placebo test preserves the active long/short mix instead of resampling directions independently.
- Memory-impulse continuation is rejected by the temporal pre-candidate signal gate. Recent positives were sparse and transition/legacy failed.
- Rejection map and feature inventory are saved at `docs/research_postmortems/2026-05-24_signal_gate_rejection_map_and_feature_inventory.md`.
- The repeated failure mode is same-sample context slices, recent-only behavior, weak IC, and cost-sensitive OHLCV signals. More time-of-day or horizon mutations are not justified.
- TBBO execution baseline is implemented and generated at `results/research_master/tbbo_execution_baseline/tbbo_execution_baseline.md`.
- TBBO baseline verdict: 1.5 points is acceptable for typical active-contract spread, but too low for tail trade-vs-mid execution conditions.
- Signal research and temporal signal research now include stress-cost survival columns and block candidate eligibility when configured stress costs fail.
- Options gamma-wall reversion is rejected by the temporal pre-candidate signal gate. Do not mine wall-distance, cooldown, hour/session, or options-age variants from the same sample.
- `RESEARCH_CONFIG["next_validation_candidates"]` is empty. Family run-count floors remain the source of multiple-testing debt even if old result folders are deleted.

## Completed Platform Work

- Historical backtest engine, research reports, stress tests, walk-forward outputs, prop-firm reports, paper runtime, and live-style audit paths exist.
- The pre-candidate signal workflow exists:
  - `scripts/export_prepared_signal_csv.py`
  - `scripts/export_liquidity_absorption_signal_csv.py`
  - `scripts/export_compression_breakout_signal_csv.py`
  - `scripts/export_gap_go_signal_csv.py`
  - `scripts/export_power_hour_signal_csv.py`
  - `scripts/export_options_gamma_wall_signal_csv.py`
  - `scripts/run_signal_research_report.py`
  - `scripts/run_temporal_signal_research_report.py`
  - `backtest/signal_export.py`
  - `backtest/liquidity_absorption_signal.py`
  - `backtest/compression_breakout_signal.py`
  - `backtest/gap_go_signal.py`
  - `backtest/power_hour_signal.py`
  - `backtest/memory_impulse_signal.py`
  - `backtest/options_gamma_wall_signal.py`
  - `backtest/signal_research.py`
  - `backtest/temporal_signal_research.py`
  - `scripts/audit_tbbo_execution_baseline.py`
  - `backtest/tbbo_execution_baseline.py`
- Broad candidate batch launchers are not active research queues; they are reproduction tools and should stay guarded.

## Immediate Work

1. Keep docs, config, and command files aligned around the empty validation queue.
2. Run no historical backtest, full-dataset probe, full-sample signal scan, or candidate sweep from automation without explicit user instruction.
3. Do not convert tiny memory-impulse recent `hour` / `session_bucket` slices into a candidate.
4. Write a fresh ex-ante structural hypothesis before any more signal mining.
5. Inspect `scripts/audit_trades_with_tbbo.py` and `backtest/tbbo_trade_audit.py` before any TBBO-linked saved-run validation.
6. Use 2010-2024 for development/context and keep 2025+ as recent holdout until development evidence passes.
7. Require raw IC, signed forward return after cost, and period stability before writing a candidate.
8. Freeze exactly one new candidate only after the signal report and hypothesis exist.

## User-Run Temporal Signal Gate

Future reports are not trade execution, but using historical data is still a signal scan and testing debt. Template only; replace placeholders before running:

Generic template:

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

Latest rejected gate: `results/research_master/signal_research/liquidity_absorption_2021_signal_gate_next_bar_open.md`.

Latest rejected compression breakout gate: `results/research_master/signal_research/compression_breakout_2021_signal_gate.md`.

Latest rejected gap-and-go gate: `results/research_master/signal_research/gap_go_temporal_gate_temporal.md`.

Latest rejected power-hour gate: `results/research_master/signal_research/power_hour_continuation_temporal_gate_temporal.md`.

Latest rejected power-hour event gate: `results/research_master/signal_research/power_hour_continuation_event_temporal_gate_temporal.md`.

Latest rejected memory-impulse gate: `results/research_master/signal_research/memory_impulse_event_temporal_gate_temporal.md`.

Latest rejected options gamma-wall gate: `results/research_master/signal_research/options_gamma_wall_dev_2010_2024_event_temporal_gate_temporal.md`.

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
