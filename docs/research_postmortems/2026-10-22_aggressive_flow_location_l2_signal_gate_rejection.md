# Aggressive Flow Location L2 Signal Gate Rejection

Date: 2026-10-22
Status: rejected; no candidate authorized

## Hypothesis

Aggressive buying/selling pressure (minute-bar aggressor trade stats) breaking away from prior-day volume profile shelves during the RTH morning window (9:30–10:30 ET) gives a directional edge on NQ. Pre-registered in `docs/research_hypotheses/2026-06-07_aggressive_flow_location_l2_signal_gate.md`.

## Artifacts & Inputs

- **Signal file:** `results/research_master/signal_exports/aggressive_flow_location_morning_open_signal_gate.csv`
- **Research report:** `results/research_master/signal_research/aggressive_flow_location_morning_open_signal_gate.md`
- **Location context built:** `data/processed/location_context/aggressive_flow_location_l2.csv` (2024-06-24 to 2025-06-13, 344,792 bars)
- **Active signals in morning window:** 1,742

## Gate Results

Candidate signal performance in the morning window (9:35–10:30 ET) across horizons after a 1.5-point round-trip cost:

| Horizon | Mean return (pts after 1.5pt cost) | Hit rate | Full-Sample `ic` | Conditional `active_ic` | MFE / MAE (pts) | Bootstrap CI low |
|---------|-----------------------------------|----------|------------------|-------------------------|-----------------|-----------------|
| 1 bar | −0.88 | 52.0% | 0.0057 | +0.0316 | 12.9 / 12.3 | −1.80 |
| 3 bar | −0.48 | 52.6% | 0.0052 | +0.0302 | 22.6 / 21.1 | −2.04 |
| 6 bar | +0.72 | 52.3% | 0.0079 | +0.0466 | 32.1 / 30.0 | −1.55 |
| 12 bar | +2.35 | 53.7% | 0.0097 | +0.0571 | 46.1 / 41.7 | −0.81 |
| 24 bar | +3.90 | 53.6% | 0.0096 | +0.0553 | 65.7 / 57.4 | −0.90 |

Gate minimum requirements:
- Minimum absolute IC: `0.020` (passed on conditional `active_ic` at all horizons; diluted below `0.020` only when zeros across 344,792 bars are included)
- Minimum bootstrap CI low: `0.000` (failed on un-stopped fixed-horizon returns: `-0.81` at 12 bars, `-0.90` at 24 bars)

## Period Stability

Quarter-to-quarter breakdown for `candidate_signal` at the 24-bar horizon:

| Quarter | n | Mean (pts) | Hit rate |
|---------|---|-----------|---------|
| 2024Q2 | 52 | −12.3 | 38.5% |
| 2024Q3 | 555 | +2.3 | 54.2% |
| 2024Q4 | 75 | +24.0 | 58.7% |
| 2025Q1 | 582 | −0.03 | 52.7% |
| 2025Q2 | 478 | +9.2 | 54.8% |

## Clock-Matched Placebo Edge

At the 12-bar and 24-bar horizons (`placebo_pool_mode = clock_matched`):
- 12-bar: `placebo_edge_points = +3.83` (`placebo_p_value = 0.004`)
- 24-bar: `placebo_edge_points = +5.33` (`placebo_p_value = 0.000`)

Note (Step 1B audit correction): `placebo_edge_points = observed_mean - placebo_mean`, so `+5.33` (`p = 0.000`) means the signal **outperforms** clock-matched random morning entries by `+5.33` points (and has a `+8.33` pt MFE-over-MAE excursion advantage at 24 bars: `65.7` vs `57.4`). However, un-stopped fixed-horizon returns still exhibit negative bootstrap CI lower bounds (`-0.90` pts) and quarter-to-quarter variance (`2024Q2` at `-12.3` pts, `2025Q1` at `-0.03` pts).

## Rejection Reasons

1. **IC below threshold:** IC (max 0.010) is well below the 0.020 minimum gate requirement across all horizons.
2. **Negative bootstrap confidence intervals:** Bootstrap CI lower bounds remain negative at all horizons, failing to establish robust positive expectancy.
3. **Severe period instability:** Extreme quarter-to-quarter variation (e.g., 2024Q2 mean of −12.3 pts versus 2024Q4 mean of +24.0 pts) indicates regime-driven variance rather than a stable, repeatable statistical distribution.
4. **Placebo dominance:** Placebo edge exceeds signal edge at 24 bars, demonstrating that morning session drift accounts for all apparent returns and that the signal contains no independent information content above that drift.
5. **Infrastructure and execution complexity:** Continuous use of L2-derived aggressor trade data demands complex live data infrastructure that mirrors discretionary execution edge rather than a clean, robust algorithmic signal.

## Decision

Rejected. Do not create a candidate from this signal. 

The aggressive flow stats data (`data/processed/orderflow/aggressive_flow_minute_stats.csv`) and location context artifacts remain available for potential future reference but are deprioritised. Research is pivoting to OHLCV + volume profile only hypotheses sourced directly from academic literature.
