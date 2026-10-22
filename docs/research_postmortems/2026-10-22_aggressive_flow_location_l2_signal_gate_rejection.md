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

| Horizon | Mean return (pts after 1.5pt cost) | Hit rate | IC | Bootstrap CI low |
|---------|-----------------------------------|----------|----|-----------------|
| 1 bar | −0.88 | 52.0% | 0.006 | −1.80 |
| 3 bar | −0.48 | 52.6% | 0.005 | −2.04 |
| 6 bar | +0.72 | 52.3% | 0.008 | −1.55 |
| 12 bar | +2.35 | 53.7% | 0.010 | −0.81 |
| 24 bar | +3.90 | 53.6% | 0.010 | −0.90 |

Gate minimum requirements:
- Minimum absolute IC: `0.020`
- Minimum bootstrap CI low: `0.000`

All horizons fail both gate thresholds.

## Period Stability

Quarter-to-quarter breakdown for `candidate_signal` at the 24-bar horizon:

| Quarter | n | Mean (pts) | Hit rate |
|---------|---|-----------|---------|
| 2024Q2 | 52 | −12.3 | 38.5% |
| 2024Q3 | 555 | +2.3 | 54.2% |
| 2024Q4 | 75 | +24.0 | 58.7% |
| 2025Q1 | 582 | −0.03 | 52.7% |
| 2025Q2 | 478 | +9.2 | 54.8% |

## Placebo Edge

At the 24-bar horizon:
- `placebo_edge_points = 5.38`
- `placebo_p_value = 0.000`

The morning window exhibits positive drift on its own; the signal adds nothing above random market drift.

## Rejection Reasons

1. **IC below threshold:** IC (max 0.010) is well below the 0.020 minimum gate requirement across all horizons.
2. **Negative bootstrap confidence intervals:** Bootstrap CI lower bounds remain negative at all horizons, failing to establish robust positive expectancy.
3. **Severe period instability:** Extreme quarter-to-quarter variation (e.g., 2024Q2 mean of −12.3 pts versus 2024Q4 mean of +24.0 pts) indicates regime-driven variance rather than a stable, repeatable statistical distribution.
4. **Placebo dominance:** Placebo edge exceeds signal edge at 24 bars, demonstrating that morning session drift accounts for all apparent returns and that the signal contains no independent information content above that drift.
5. **Infrastructure and execution complexity:** Continuous use of L2-derived aggressor trade data demands complex live data infrastructure that mirrors discretionary execution edge rather than a clean, robust algorithmic signal.

## Decision

Rejected. Do not create a candidate from this signal. 

The aggressive flow stats data (`data/processed/orderflow/aggressive_flow_minute_stats.csv`) and location context artifacts remain available for potential future reference but are deprioritised. Research is pivoting to OHLCV + volume profile only hypotheses sourced directly from academic literature.
