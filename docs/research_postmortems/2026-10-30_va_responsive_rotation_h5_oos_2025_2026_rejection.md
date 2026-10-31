# Postmortem: Value Area Responsive Rotation Out-of-Sample Holdout Test (H5-OOS, 2025–2026) — Rejected

**Date:** 2026-10-30  
**Pre-Registration:** [2026-10-30_va_responsive_rotation_h5_oos_2025_2026.md](file:///Users/novo/trading_strategy/nq-scalper-backtest/docs/research_hypotheses/2026-10-30_va_responsive_rotation_h5_oos_2025_2026.md)  
**OOS Gate Report:** [va_responsive_rotation_h5_oos_2025_2026_gate_oos_2025_2026.md](file:///Users/novo/trading_strategy/nq-scalper-backtest/results/research_master/signal_research/va_responsive_rotation_h5_oos_2025_2026_gate_oos_2025_2026.md)  
**Decision:** **FALSIFIED & REJECTED** — Do not promote `H5` to `CANDIDATE_CONFIGS`.

---

## 1. Out-of-Sample Empirical Results (`2025-01-01` to `2026-04-28`, $n = 76$)

| Horizon | Active ($n$) | Conditional `active_ic` (`score`) | Un-Stopped Net Return (`1.50`pt cost) | Median Net Return (pts) | Hit Rate | Positive Quarters | Mean MFE / MAE (pts) | Structural Barrier Net Return (pts) | Placebo Edge (pts) | Gate Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1 bar** | 76 | `+0.2350` | `+0.09` | `-1.25` | `50.00%` | `66.7%` (4/6) | `12.2 / 9.2` | `+0.10` | `+1.68` ($p=0.144$) | **FAIL** |
| **3 bars** | 76 | `+0.1242` | `-0.53` | `-3.13` | `48.68%` | `50.0%` (3/6) | `20.4 / 16.8` | `+0.18` | `+0.97` ($p=0.354$) | **FAIL** |
| **6 bars** | 76 | `+0.0214` | `-4.44` | `-9.25` | `42.11%` | `33.3%` (2/6) | `26.7 / 24.0` | `-1.82` | `-3.12` ($p=1.000$) | **FAIL** |
| **12 bars** | 76 | `+0.0970` | `-1.27` | `-9.00` | `42.11%` | `66.7%` (4/6) | `36.0 / 34.2` | `+1.47` | `+0.35` ($p=0.480$) | **FAIL** |
| **24 bars** | 76 | `-0.0116` | **`-4.53`** | `-1.63` | **`48.68%`** | **`83.3%` (5/6)** | `53.0 / 48.4` | **`+4.86`** | `-2.91` ($p=1.000$) | **FAIL** |
| **30 bars** | 76 | `-0.0562` | `-7.24` | `-2.50` | `48.68%` | `50.0%` (3/6) | `56.3 / 54.5` | **`+5.34`** | `-5.69` ($p=1.000$) | **FAIL** |

### Quarterly Breakdown at Primary 24-Bar Horizon (Un-Stopped Net Return)
- `2025Q1` ($n=8$): **`+9.91` pts net** (`62.50%` hit rate, `active_ic = +0.4876`)
- `2025Q2` ($n=13$): **`+10.81` pts net** (`53.85%` hit rate, `active_ic = +0.4614`)
- `2025Q3` ($n=21$): **`+1.56` pts net** (`38.10%` hit rate, `active_ic = +0.1931`)
- `2025Q4` ($n=15$): **`+6.02` pts net** (`66.67%` hit rate, `active_ic = +0.2147`)
- `2026Q1` ($n=16$): **`-43.28` pts net** (`31.25%` hit rate, `active_ic = -0.4367`)
- `2026Q2` ($n=3$): **`+1.92` pts net** (`66.67%` hit rate, `active_ic = +0.5429`)

### Directional Attribution at 24 Bars (`VAL` Long vs. `VAH` Short)
- **`VAL` Long (`n = 34`)**: **`-25.66` pts net** (`50.00%` hit rate) — severe reversal from `2021–2024` (`+5.89` pts net).
- **`VAH` Short (`n = 42`)**: **`+12.58` pts net** (`47.62%` hit rate).

---

## 2. Structural Root Cause Analysis

1. **Left-Tail Regime Vulnerability on Un-Stopped Fades (`2026Q1` Crash)**:
   - While `H5` was positive in **5 out of 6 quarters (`83.3%`)** at 24 bars (`+9.91`, `+10.81`, `+1.56`, `+6.02`, `+1.92` pts) and generated **`+4.86` pts net (24b) / `+5.34` pts net (30b)** when capped by its structural stop-loss/target barrier, its un-stopped fixed-horizon return collapsed in `2026Q1` (`-43.28` pts average across 16 trades) when inside-VA mornings transitioned into relentless downside liquidation drives through `VAL`.
2. **Directional Instability Across Eras**:
   - In `2021–2024`, `VAL` Longs carried the strategy (`+5.89` pts vs `+1.90` pts for `VAH` Shorts).
   - In `2025–2026`, `VAL` Longs suffered catastrophic un-stopped tail losses (`-25.66` pts) while `VAH` Shorts made `+12.58` pts.
   - A mean-reversion signal whose profitable side flips between `VAL` Long and `VAH` Short depending on the macro/volatility regime is too fragile for a `$1,000` trailing-drawdown prop account.
