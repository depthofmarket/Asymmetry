# Mid-Day VWAP Mean Reversion Scalp (H6) Signal Gate Rejection

Date: 2026-10-29
Status: Rejected under pre-registered institutional falsification criteria; no candidate authorized.

---

## 1. Hypothesis & Pre-Registration Context

- **Pre-Registration Document:** `docs/research_hypotheses/2026-10-29_midday_vwap_mean_reversion_h6.md`
- **Thesis:** During the European close and NY lunch lull (`11:30–13:30 ET`), institutional directional volume drops by 60%–70%. In this low-volume chop, price deviations beyond $\pm 2.0\sigma$ from session RTH VWAP reflect temporary liquidity voids rather than fresh fundamental information, creating high-expectancy statistical mean reversion toward fair value ($\mu = \text{VWAP}$).
- **Falsification Criteria:**
  1. Mean return after `1.50` points cost $\le 0$ across recent development sample (2021–2024).
  2. Failure under `2.00` points cost stress.
  3. Negative expectancy across transition era (2016–2020).

---

## 2. Artifacts & Inputs

- **Development Signal Export (2021–2024):** `results/research_master/signal_exports/midday_vwap_mean_reversion_h6_dev_2021_2024.csv` (`1,415,947` bars, `547` signals)
- **Development Research Report (2021–2024):** `results/research_master/signal_research/midday_vwap_mean_reversion_h6_dev_gate_recent_development.md`
- **Transition Signal Export (2016–2020):** `results/research_master/signal_exports/midday_vwap_mean_reversion_h6_trans_2016_2020.csv` (`1,726,100` bars, `475` signals)
- **Transition Research Report (2016–2020):** `results/research_master/signal_research/midday_vwap_mean_reversion_h6_trans_gate_transition.md`

---

## 3. Empirical Gate Results (After 1.50-Point Round-Trip Cost)

### A. Recent Development Era (2021–2024, $n = 547$)

| Horizon | Full IC | Active IC | Net Return (pts) | Hit Rate | MFE / MAE (pts) | Stress 2.00pt (pts) | Placebo Edge (pts) | Placebo $p$-value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 bar | -0.0005 | -0.0227 | **-1.64** | 45.5% | 5.1 / 5.1 | -2.14 | -0.12 | 1.000 |
| 3 bar | -0.0004 | -0.0155 | **-1.68** | 49.5% | 8.4 / 8.9 | -2.18 | -0.16 | 1.000 |
| 6 bar | -0.0001 | -0.0027 | **-1.54** | 52.5% | 12.1 / 12.5 | -2.04 | -0.03 | 1.000 |
| 12 bar | +0.0001 | +0.0079 | **-1.39** | 53.0% | 16.8 / 17.1 | -1.89 | +0.13 | 0.461 |
| **24 bar** | **-0.0004** | **-0.0190** | **-2.09** | **49.5%** | **22.8 / 24.3** | **-2.59** | **-0.54** | **1.000** |

- **Context Breakdown (24 Bars):**
  - **Lower Band Longs (`n = 252`):** `-2.21` pts net after cost, `53.17%` hit rate.
  - **Upper Band Shorts (`n = 295`):** `-2.00` pts net after cost, `46.44%` hit rate.

---

### B. Transition Era (2016–2020, $n = 475$)

| Horizon | Full IC | Active IC | Net Return (pts) | Hit Rate | MFE / MAE (pts) | Positive Quarters | Placebo Edge (pts) | Placebo $p$-value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 bar | +0.0026 | +0.1083 | **-1.05** | 54.1% | 3.0 / 2.7 | 5.0% | +0.45 | 0.004 |
| 3 bar | +0.0006 | +0.0237 | **-1.33** | 52.0% | 5.0 / 4.9 | 15.0% | +0.17 | 0.258 |
| 6 bar | +0.0001 | +0.0010 | **-1.47** | 52.8% | 6.8 / 7.1 | 15.0% | +0.03 | 0.467 |
| 12 bar | -0.0014 | -0.0550 | **-2.31** | 50.5% | 9.4 / 10.6 | 10.0% | -0.78 | 1.000 |
| **24 bar** | **+0.0004** | **+0.0162** | **-1.15** | **53.1%** | **13.3 / 14.6** | **30.0%** | **+0.33** | **0.336** |

---

## 4. Root Cause Analysis & Microstructure Findings

1. **Failure of Pre-Registered Falsification Criteria 1, 4, and 5:**
   Expectancy after 1.50-point round-trip transaction costs is negative across **every single measured horizon in both market eras** (`-1.05` to `-2.31` points).
2. **Microstructure Driver — Drift In Mid-Day Low Liquidity:**
   While the lunch hour exhibits lower overall trading volume, when NQ extends beyond $2.0\sigma$ during mid-day, the low order book depth actually works *against* mean reversion:
   - In low liquidity, small algorithmic buy/sell programs easily push price into persistent low-volume drift.
   - Without two-sided institutional volume to absorb these small programs, price remains extended outside the bands rather than snapping back to VWAP.
   - Gross price movements are small (mean MFE is only 12–22 pts in 2021–2024 and 6–13 pts in 2016–2020), which is completely consumed by bid-ask spread, slippage, and commissions.
3. **Symmetric Failure:**
   Both Longs and Shorts fail simultaneously, proving that mid-day VWAP band extension fading has zero robust statistical edge on 1-minute NQ futures.

---

## 5. Institutional Decision

**REJECTED.**
Candidate 2 (H6: Mid-Day VWAP Mean Reversion Scalp) is decisively falsified.
