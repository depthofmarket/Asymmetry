# Liquidity Absorption Failed-Continuation Signal Gate

Date: 2026-05-21

Status: rejected pre-candidate signal hypothesis

## Hypothesis

NQ short-horizon edge, if present, is more likely after a liquidity sweep with range and volume expansion that fails to continue within the next few completed bars. Static market-profile room or cross levels did not show raw signal evidence, so this branch tests post-sweep absorption before any candidate is created.

## Fixed Pre-Run Assumptions

- This is not a `CANDIDATE_CONFIGS` entry.
- The signal uses completed bars only.
- A sweep event must break a prior rolling high or low after range and volume expansion.
- A signal is emitted only after the configured confirmation bars show failed follow-through and reentry back inside the event extreme.
- VWAP distance is a configurable pressure filter, not a same-sample optimization target.
- Running the export over the full historical range is a full-sample signal scan and testing debt.

## User-Run Commands

```bash
python3 scripts/export_liquidity_absorption_signal_csv.py \
  --start 2021-01-01 \
  --artifact-name liquidity_absorption_2021_signal_gate
```

Then:

```bash
python3 scripts/run_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/liquidity_absorption_2021_signal_gate.csv \
  --signal-cols candidate_signal,absorption_score \
  --context-cols setup_tag,direction,signal_type,hour,session_bucket,vwap_side,liquidity_expansion_side,absorption_pattern \
  --entry-price-col open \
  --entry-lag-bars 1 \
  --exit-price-col close \
  --round-trip-cost-points 1.5 \
  --artifact-name liquidity_absorption_2021_signal_gate
```

## Promotion Rule

Do not create a strategy candidate unless the signal report shows raw IC, signed forward return after cost, and period stability. Winning context slices from this report are diagnostic only unless they survive a separate pre-registered sample.

## Result

Artifact: `results/research_master/signal_research/liquidity_absorption_2021_signal_gate.md`

Verdict: no signal passed the pre-candidate gate. `candidate_signal` and `absorption_score` both failed raw IC, signed forward return after cost, and period stability. The only positive context slice was hour 11 at the 24-bar horizon; it is diagnostic only and must not be promoted into a same-sample candidate.

Implementation audit note: the original saved report used the earlier close-to-close signal gate. The stricter next-bar-open re-score also failed:

`results/research_master/signal_research/liquidity_absorption_2021_signal_gate_next_bar_open.md`
