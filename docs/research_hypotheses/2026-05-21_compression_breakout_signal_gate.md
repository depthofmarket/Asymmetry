# Opening Compression Breakout Signal Gate

Date: 2026-05-21

Status: rejected pre-candidate signal hypothesis

## Hypothesis

NQ short-horizon edge, if present in the current research direction, is more likely to come from continuation after volatility compression resolves into a high-range, high-volume opening breakout than from another failed-continuation or failed-auction variant.

This tests a completed-bar opening drive continuation premise before any `CANDIDATE_CONFIGS` entry exists.

## Fixed Pre-Run Assumptions

- This is not a strategy candidate.
- The signal uses completed bars only.
- The prior compression window must have lower median true range than the longer reference window.
- A signal requires a breakout beyond the prior compression box, range expansion, volume expansion, and a close near the breakout-side extreme.
- VWAP alignment is a pressure filter, not a same-sample optimization target.
- The signal gate must use next-bar-open entry timing.
- Running the export or report over the full historical range is a full-sample signal scan and testing debt.

## User-Run Commands

```bash
python3 scripts/export_compression_breakout_signal_csv.py \
  --start 2021-01-01 \
  --artifact-name compression_breakout_2021_signal_gate
```

Then:

```bash
python3 scripts/run_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/compression_breakout_2021_signal_gate.csv \
  --signal-cols candidate_signal,compression_breakout_score \
  --context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side,compression_breakout_side,compression_pattern \
  --entry-price-col open \
  --entry-lag-bars 1 \
  --exit-price-col close \
  --round-trip-cost-points 1.5 \
  --artifact-name compression_breakout_2021_signal_gate
```

## Promotion Rule

Do not create a strategy candidate unless the signal report shows raw IC, signed forward return after cost, and period stability. Winning context slices from this report are diagnostic only unless they survive a separate pre-registered sample.

## Result

Artifact: `results/research_master/signal_research/compression_breakout_2021_signal_gate.md`

Verdict: no signal passed the pre-candidate gate. The 24-bar aggregate had positive signed return after cost, but IC was near zero and active observations were sparse. The short-side / 24-bar context slice is diagnostic only and must not be promoted into a same-sample candidate.
