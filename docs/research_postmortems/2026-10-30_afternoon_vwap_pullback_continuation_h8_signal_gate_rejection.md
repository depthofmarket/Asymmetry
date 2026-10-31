# Afternoon Trend Continuation via Session VWAP Pullback Scalp (H8) Signal Gate Rejection

Date: 2026-10-30
Status: Rejected under pre-registered institutional falsification criteria; no candidate authorized.

---

## 1. Hypothesis & Pre-Registration Context

- **Pre-Registration Document:** `docs/research_hypotheses/2026-10-30_afternoon_vwap_pullback_continuation_h8.md`
- **Thesis:** On sessions with directional move from the RTH open ($\ge 0.15\%$) aligned with Initial Balance midpoint (`IB_MID`) and cumulative `VWAP`, afternoon pullbacks (`13:30–15:15 ET`) into the `VWAP` value zone ($-0.50\sigma_t$ to $+0.75\sigma_t$) followed by a 1-minute trend-resumption bar breaking the prior bar's extreme should produce positive afternoon continuation expectancy.
- **Falsification Criteria:**
  1. Mean return after `1.50` points cost $\le 0$ across recent development sample (2021–2024).
  2. Failure under `2.00` points cost stress.
  3. Negative expectancy across transition era (2016–2020).

---

## 2. Artifacts & Inputs

- **Unified Signal Export (2016–2024):** `results/research_master/signal_exports/afternoon_vwap_pullback_continuation_h8_2016_2024.csv` (`3,142,047` bars, `1,403` signals)
- **Temporal Gate Summary:** `results/research_master/signal_research/afternoon_vwap_pullback_continuation_h8_gate_temporal.md`
- **Recent Development Report (2021–2024):** `results/research_master/signal_research/afternoon_vwap_pullback_continuation_h8_gate_recent_development.md` (`630` signals)
- **Transition Report (2016–2020):** `results/research_master/signal_research/afternoon_vwap_pullback_continuation_h8_gate_transition.md` (`773` signals)

---

## 3. Empirical Gate Results (After 1.50-Point Round-Trip Cost)

### A. Recent Development Era (2021–2024, $n = 630$)

| Horizon | Score Active IC | Signal Active IC | Net Return (pts) | Hit Rate | MFE / MAE (pts) | Positive Quarters | Placebo Edge (pts) | Placebo $p$-value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 bar | +0.0539 | +0.0134 | **-1.39** | 47.5% | 4.6 / 4.4 | 6.25% | +0.11 | 0.348 |
| 3 bar | +0.0186 | -0.0054 | **-1.51** | 47.5% | 7.7 / 7.5 | 25.00% | +0.00 | 0.483 |
| 6 bar | +0.0690 | +0.0120 | **-1.26** | 49.5% | 10.9 / 10.7 | 25.00% | +0.27 | 0.331 |
| 12 bar | +0.0460 | +0.0129 | **-1.24** | 50.0% | 15.3 / 15.2 | 25.00% | +0.29 | 0.365 |
| **24 bar** | **+0.0496** | **+0.0115** | **-1.19** | **51.0%** | **22.3 / 22.2** | **31.25%** | **+0.28** | **0.430** |

- **Context Breakdown (24 Bars):**
  - **Uptrend VWAP Pullback Longs (`n = 291`):** `-0.64` pts net after cost, `52.58%` hit rate.
  - **Downtrend VWAP Pullback Shorts (`n = 339`):** `-1.67` pts net after cost, `49.56%` hit rate.

---

### B. Transition Era (2016–2020, $n = 773$)

| Horizon | Score Active IC | Signal Active IC | Net Return (pts) | Hit Rate | MFE / MAE (pts) | Positive Quarters | Placebo Edge (pts) | Placebo $p$-value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 bar | +0.1111 | +0.0799 | **-1.27** | 46.3% | 2.0 / 1.9 | 0.0% | +0.23 | 0.048 |
| 3 bar | -0.0077 | -0.0112 | **-1.56** | 46.8% | 3.4 / 3.5 | 0.0% | -0.05 | 1.000 |
| 6 bar | -0.0059 | -0.0162 | **-1.61** | 48.9% | 5.0 / 5.2 | 10.0% | -0.11 | 1.000 |
| 12 bar | -0.0239 | -0.0171 | **-1.68** | 50.6% | 7.1 / 7.5 | 15.0% | -0.19 | 1.000 |
| **24 bar** | **+0.0681** | **+0.0422** | **-0.76** | **51.1%** | **10.8 / 10.3** | **25.0%** | **+0.72** | **0.132** |

- **Context Breakdown (24 Bars):**
  - **Uptrend VWAP Pullback Longs (`n = 405`):** `-0.64` pts net after cost, `55.80%` hit rate.
  - **Downtrend VWAP Pullback Shorts (`n = 368`):** `-0.90` pts net after cost, `45.92%` hit rate.

---

## 4. Root Cause Analysis & Microstructure Findings

1. **Failure of Pre-Registered Falsification Criteria 1, 3, 4, and 5:**
   While the continuous `afternoon_pullback_score` achieved positive conditional `active_ic` at 24 bars in both eras (`+0.0496` in 2021–2024 and `+0.0681` in 2016–2020) and slight positive gross returns (`+0.31` pts in 2021–2024, `+0.74` pts in 2016–2020), the gross edge is far too small to survive the `1.50`-point round-trip execution cost (`-1.19` pts and `-0.76` pts net).
2. **Adverse Selection of Afternoon VWAP Retracements:**
   The setup triggered on ~62% of all sessions (`1,403` out of ~2,250 trading days). On genuine institutional trend days, price separates from RTH `VWAP` during the morning and remains above `+1.0\sigma_t` throughout the afternoon. When price retraces all the way back to the `VWAP` zone (`-0.50\sigma_t` to `+0.75\sigma_t`) between `13:30` and `15:15 ET`, the morning trend has usually **failed and transitioned into two-sided rotational chop** around `VWAP`.
3. **Compressed Afternoon Excursion vs. Morning Opening Drive:**
   At `13:30–15:15 ET`, 24-bar MFE/MAE is symmetric and half the magnitude of the morning open (`22.3 / 22.2` pts vs `43.7 / 37.0` pts at 09:45), leaving insufficient volatility expansion per trade to overcome fixed execution friction.

---

## 5. Institutional Decision

**REJECTED.**
Candidate 4 (H8: Afternoon Trend Continuation via Session VWAP Pullback Scalp) is formally falsified.
