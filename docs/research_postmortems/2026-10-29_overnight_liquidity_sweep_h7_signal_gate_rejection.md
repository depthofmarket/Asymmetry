# Overnight High/Low Liquidity Sweep Scalp (H7) Signal Gate Rejection

Date: 2026-10-29
Status: Rejected under pre-registered institutional falsification criteria; no candidate authorized.

---

## 1. Hypothesis & Pre-Registration Context

- **Pre-Registration Document:** `docs/research_hypotheses/2026-10-29_overnight_high_low_liquidity_sweep_h7.md`
- **Thesis:** During the morning cash open (`09:35–10:30 ET`), probes beyond the Overnight High (`ONH`) or Overnight Low (`ONL`) by 1.0 to 25.0 points trigger retail resting stop orders. Once the stop run exhausts and price closes back inside the overnight range with an exhaustion wick, trapped breakout participants trigger a mean-reverting rotation back toward the Overnight Midpoint (`ON_MID = (ONH + ONL) / 2`).
- **Falsification Criteria:**
  1. Mean return after `1.50` points cost $\le 0$ across recent development sample (2021–2024).
  2. Failure under `2.00` points cost stress.
  3. Negative expectancy across transition era (2016–2020).

---

## 2. Artifacts & Inputs

- **Development Signal Export (2021–2024):** `results/research_master/signal_exports/overnight_liquidity_sweep_h7_dev_2021_2024.csv` (`1,415,947` bars, `626` signals)
- **Development Research Report (2021–2024):** `results/research_master/signal_research/overnight_liquidity_sweep_h7_dev_gate_recent_development.md`
- **Transition Signal Export (2016–2020):** `results/research_master/signal_exports/overnight_liquidity_sweep_h7_trans_2016_2020.csv` (`1,726,100` bars, `729` signals)
- **Transition Research Report (2016–2020):** `results/research_master/signal_research/overnight_liquidity_sweep_h7_trans_gate_transition.md`

---

## 3. Empirical Gate Results (After 1.50-Point Round-Trip Cost)

### A. Recent Development Era (2021–2024, $n = 626$)

| Horizon | Full IC | Active IC | Net Return (pts) | Hit Rate | MFE / MAE (pts) | Stress 2.00pt (pts) | Placebo Edge (pts) | Placebo $p$-value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 bar | +0.0013 | +0.0228 | **-1.18** | 48.9% | 9.0 / 8.4 | -1.68 | +0.32 | 0.219 |
| 3 bar | +0.0012 | +0.0219 | **-0.99** | 49.2% | 15.2 / 14.4 | -1.49 | +0.49 | 0.240 |
| 6 bar | +0.0010 | +0.0184 | **-0.87** | 50.6% | 21.8 / 21.0 | -1.37 | +0.64 | 0.259 |
| 12 bar | +0.0022 | +0.0456 | **+0.37** | 50.5% | 31.2 / 28.2 | **-0.13** | +1.80 | 0.098 |
| **24 bar** | **+0.0011** | **+0.0235** | **-0.10** | **51.4%** | **42.3 / 39.4** | **-0.60** | **+1.39** | **0.238** |

- **Context Breakdown (24 Bars):**
  - **ONL Longs (`n = 293`):** `-1.82` pts net after cost, `53.92%` hit rate.
  - **ONH Shorts (`n = 333`):** `+1.41` pts net after cost, `49.25%` hit rate.

---

### B. Transition Era (2016–2020, $n = 729$)

| Horizon | Full IC | Active IC | Net Return (pts) | Hit Rate | MFE / MAE (pts) | Positive Quarters | Placebo Edge (pts) | Placebo $p$-value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 bar | +0.0015 | +0.0359 | **-1.29** | 48.7% | 3.5 / 3.4 | 5.0% | +0.21 | 0.122 |
| 3 bar | +0.0022 | +0.0552 | **-0.96** | 48.6% | 6.3 / 5.7 | 20.0% | +0.54 | 0.050 |
| 6 bar | +0.0012 | +0.0340 | **-1.10** | 49.0% | 8.5 / 7.9 | 25.0% | +0.42 | 0.181 |
| 12 bar | +0.0021 | +0.0609 | **-0.47** | 48.7% | 11.8 / 10.9 | 45.0% | +1.05 | 0.055 |
| **24 bar** | **+0.0017** | **+0.0535** | **-0.33** | **49.4%** | **16.1 / 14.3** | **50.0%** | **+1.21** | **0.093** |

---

## 4. Root Cause Analysis & Microstructure Findings

1. **Failure of Pre-Registered Falsification Criteria 1, 4, and 5:**
   - In 2021–2024, net returns are negative across 1, 3, 6, and 24 bars. The sole positive horizon (12 bars at `+0.37` pts) has a win rate of only `50.48%` (failing the $\ge 52.0\%$ threshold) and turns negative under standard `2.00`-point cost stress (`-0.13` pts).
   - In 2016–2020, net returns are negative across **all multi-bar horizons** (`-0.33` to `-1.29` pts).
2. **Microstructure Driver — Sweep vs. Momentum Contagion:**
   On Nasdaq futures (NQ), an overnight high or low breakout during 09:35–10:30 ET is rarely a clean mean-reverting "fakeout". In an institutional index driven by large tech momentum, testing the overnight boundary frequently marks the start of an initiative trend run. Even when an individual 1-minute bar forms a rejection wick, the momentum orderflow resumes on subsequent bars, driving through the swept boundary and stopping out tight mean-reversion traders.
3. **Barrier Fragility:**
   The barrier evaluation shows a barrier hit rate of only `34%–40%` and negative expectancy (`-1.17` to `-1.47` pts) across both eras, demonstrating that resting orders beyond overnight extremes do not provide sufficient structural support for a stop loss.

---

## 5. Institutional Decision

**REJECTED.**
Per pre-registered rules, Candidate 3 (H7: Overnight High/Low Liquidity Sweep Scalp) is decisively falsified across the 9-year dataset.

Proceed to **Candidate 2: Mid-Day VWAP Mean Reversion Scalp (H6)**.
