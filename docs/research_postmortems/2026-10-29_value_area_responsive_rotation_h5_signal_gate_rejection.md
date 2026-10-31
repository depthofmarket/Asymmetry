# Prior Session Value Area Responsive Rotation Scalp (H5) Signal Gate Rejection

Date: 2026-10-29
Status: Rejected under pre-registered institutional falsification criteria; no candidate authorized.

---

## 1. Hypothesis & Pre-Registration Context

- **Pre-Registration Document:** `docs/research_hypotheses/2026-10-29_value_area_responsive_rotation_h5.md`
- **Thesis:** On days where the 09:30–09:44 Opening Range closes inside the prior session Value Area (`prior_val <= close_0944 <= prior_vah`), the market is in an equilibrium/rotational regime (Strategy 1 outputs `NO TRADE`). Directional probes between 10:00 and 11:30 ET toward prior `VAH` or `VAL` face responsive institutional absorption, mean-reverting back toward prior `POC`.
- **Pre-Registered Falsification Criterion 5:** *"Transition era (2016–2020) shows negative expectancy across all multi-bar horizons."*

---

## 2. Artifacts & Inputs

- **Development Signal Export (2021–2024):** `results/research_master/signal_exports/va_responsive_rotation_h5_dev_2021_2024.csv` (`1,415,947` bars, `259` signals)
- **Development Research Report (2021–2024):** `results/research_master/signal_research/va_responsive_rotation_h5_dev_gate_recent_development.md`
- **Transition Signal Export (2016–2020):** `results/research_master/signal_exports/va_responsive_rotation_h5_trans_2016_2020.csv` (`1,726,100` bars, `301` signals)
- **Transition Research Report (2016–2020):** `results/research_master/signal_research/va_responsive_rotation_h5_trans_gate_transition.md`

---

## 3. Empirical Gate Results (After 1.50-Point Round-Trip Cost)

### A. Recent Development Era (2021–2024)

| Horizon | Active ($n$) | Full IC | Active IC | Net Return (pts) | Hit Rate | MFE / MAE (pts) | Stress 4.25pt Net (pts) | Placebo Edge (pts) | Placebo $p$-value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 bar | 259 | +0.0002 | +0.0069 | -1.43 | 50.6% | 8.0 / 7.6 | -4.18 | +0.08 | 0.443 |
| 3 bar | 259 | +0.0028 | +0.1137 | +0.42 | 55.6% | 14.1 / 12.5 | -2.33 | +1.94 | 0.022 |
| 6 bar | 259 | +0.0019 | +0.0751 | +0.34 | 53.7% | 20.0 / 17.2 | -2.41 | +1.86 | 0.063 |
| 12 bar | 259 | +0.0015 | +0.0594 | +0.49 | 54.4% | 27.4 / 23.5 | -2.26 | +1.96 | 0.161 |
| **24 bar** | **259** | **+0.0028** | **+0.1188** | **+3.90** | **53.7%** | **38.1 / 30.8** | **+1.15** | **+5.28** | **0.027** |

- **Context Breakdown (24 Bars):**
  - **VAL Long (`n = 130`):** `+5.89` pts net after cost, `59.23%` hit rate.
  - **VAH Short (`n = 129`):** `+1.90` pts net after cost, `48.06%` hit rate.

---

### B. Transition Era (2016–2020)

| Horizon | Active ($n$) | Full IC | Active IC | Net Return (pts) | Hit Rate | MFE / MAE (pts) | Positive Quarters | Placebo Edge (pts) | Placebo $p$-value |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 bar | 301 | +0.0019 | +0.1035 | -1.09 | 50.8% | 3.0 / 2.8 | 10.0% | +0.41 | 0.066 |
| 3 bar | 301 | +0.0015 | +0.0784 | -0.93 | 48.5% | 5.4 / 4.8 | 20.0% | +0.58 | 0.094 |
| 6 bar | 301 | +0.0018 | +0.0819 | -0.54 | 47.5% | 7.8 / 6.7 | 30.0% | +0.97 | 0.060 |
| 12 bar | 301 | +0.0003 | +0.0158 | -1.30 | 42.9% | 10.5 / 9.8 | 30.0% | +0.23 | 0.386 |
| **24 bar** | **301** | **+0.0002** | **+0.0172** | **-1.25** | **43.9%** | **13.9 / 13.8** | **20.0%** | **+0.24** | **0.432** |

- **Context Breakdown (24 Bars):**
  - **VAL Long (`n = 135`):** `+0.18` pts net after cost, `45.19%` hit rate.
  - **VAH Short (`n = 166`):** `-2.42` pts net after cost, `42.77%` hit rate.

---

## 4. Root Cause Analysis & Microstructure Findings

1. **Failure of Pre-Registered Falsification Criterion 5:**
   In the 2016–2020 transition era, the symmetric candidate generated negative net returns after 1.50-point round-trip costs across **every single measured horizon** (`-0.54` to `-1.30` pts), with quarterly consistency collapsing to only 10%–30% positive quarters.
2. **Structural Asymmetry (The Secular Trend Drag):**
   In both market eras, fading `VAH` (shorting the upper value perimeter) performed poorly (`+1.90` pts with `48%` hit rate in 2021–2024; `-2.42` pts with `42.8%` hit rate in 2016–2020). Even on days opening inside value, NQ's persistent upward drift causes upside probes to break out into trend extension rather than mean-reverting.
3. **Volatility Compression & Execution Friction in the Transition Era:**
   During 2016–2020, NQ index levels were lower (4,500 to 9,000) and daily value area spans were much narrower (15–35 pts) than during 2021–2024 (12,000 to 21,000, 80–200 pt value areas). In narrow ranges, the gross distance between `VAH`/`VAL` and `POC` was often only 4–8 points, leaving insufficient margin to survive realistic institutional round-trip slippage and commissions (1.50–2.00 pts).

---

## 5. Institutional Decision

**REJECTED.**
Per pre-registered rules, we do not perform post-hoc modifications (such as dropping short trades or adjusting tolerance thresholds) to retroactively force candidate promotion. Candidate 1 (H5) is formally logged as falsified.

Proceed immediately to **Candidate 2: Mid-Day VWAP Mean Reversion Scalp (H6)** or **Candidate 3: Overnight High/Low Liquidity Sweep Scalp (H7)**.
