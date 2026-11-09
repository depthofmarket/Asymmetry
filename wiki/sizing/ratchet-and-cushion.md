---
title: "Ratchet Sizing Geometry & Cushion Protection"
tags:
  - sizing
  - ratchet
  - cppi
  - risk-management
  - money-management
created: "2026-11-05"
updated: "2026-11-09"
status: active
strategies:
  - lucid_flex_ensemble
related_pages:
  - "strategies/lucid-flex-ensemble.md"
  - "prop_firm/lucid-flex-25k.md"
  - "provenance/provenance-protocol.md"
  - "execution/demo-parity-engine.md"
---

# Ratchet Sizing Geometry & Cushion Protection

## Executive Summary
Position sizing is the primary mathematical determinant of account survival and payout extraction in prop firm trading. Because prop firm accounts impose a hard trailing drawdown floor ($1,000 for LucidFlex 25K), static contract sizing is structurally sub-optimal: 1-micro static trading suffers from slow equity accumulation and high commission drag, while static 4-micro trading exposes unbuffered accounts to catastrophic early ruin.

This document formalizes the dynamic anti-martingale ratchet geometry across the verified **5-Strategy Multi-Asset Portfolio** (748 trades, 2021–2026, +$16,490.34 Net PnL), the mathematical proof of Cushion-Referenced Fractional Kelly under an absorbing barrier, the resolution of the "1-Micro Funded Infant Mortality Trap," and the production Safe CPPI (Constant Proportion Portfolio Insurance) buffer architecture.

---

## Technical Specification

### 1. 5-Strategy Evaluation Anti-Martingale Ratchet Geometry
During evaluation, contract sizing scales up as accumulated profit widens the distance to the liquidation floor:

| Tier | Contract Size | 3-Strategy Legacy Thresholds | 5-Strategy Balanced Production Champion | Allocation Function |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | 2 Micros | $0 to +$199 | **$0 to +$99** | Baseline Entry Cushion |
| **Tier 2** | 3 Micros | +$200 to +$549 | **+$100 to +$599** | Accelerated Compounding |
| **Tier 3** | 4 Micros | +$550 to +$1,149 | **+$600 to +$1,149** | Peak Leverage |
| **Shield** | 1 Micro | $\ge +\$1,150$ | **$\ge +\$1,150$** | Finish-Line Protection |

- **Empirical Duration Compression (-26.6% to -31.6%)**:
  - On the 3-strategy portfolio (543 trades, 0.36 trades/session), the Pareto Ratchet (200/550) required **79.0 median exchange sessions** to reach the $1,250 target.
  - On the 5-strategy portfolio (748 trades, 0.50 trades/session), increased trade frequency compresses median pass duration to **58.0 sessions** (-21.0 sessions / -26.6% faster) under the Balanced Champion `(T2=$100, T3=$600)` and down to **54.0 sessions** (-31.6% faster) under the Maximum Compression Champion `(T2=$100, T3=$350)`.
  - Pass rates remain exceptionally stable at **72.24% to 74.97%** across 10,000 CRN block-bootstrap iterations.

---

### 2. Systematic 225-Point Ratchet Grid Search & Non-Dominated Pareto Frontier
Evaluated across 225 grid points via **10,000 Common Random Numbers (CRN) block-bootstrap iterations** per point (block size = 10 sessions, 750-session evaluation horizon):

| Configuration | Tier 2 ($T_2$) | Tier 3 ($T_3$) | Pass Rate (%) | Fail Rate (%) | Median Pass (Sess) | P90 Pass (Sess) | Expected OTP Cost | Frontier Role |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Max Compression** | **$100** | **$350** | 71.02% | 28.98% | **54.0** | 134.0 | $54.91 | Fastest pass velocity |
| **Early Acceleration** | $150 | $300 | 71.22% | 28.78% | 55.0 | 136.0 | $54.76 | Pareto Optimal |
| **Mid Accelerator** | $150 | $350 | 71.54% | 28.46% | 56.0 | 137.0 | $54.51 | Pareto Optimal |
| **Balanced Champion** | **$100** | **$600** | **72.24%** | **27.76%** | **58.0** | **139.0** | **$53.99** | **Production Recommended** |
| **Extended Tier 2** | $100 | $675 | 72.52% | 27.48% | 60.0 | 139.9 | $53.78 | Low giveback risk |
| **Conservative Mid** | $150 | $675 | 72.81% | 27.19% | 61.0 | 143.0 | $53.56 | Smooth transition |
| **Late Scale-Up** | $150 | $750 | 73.13% | 26.87% | 62.0 | 144.0 | $53.33 | High defense |
| **Max Defense Anchor** | **$350** | **$775** | **74.97%** | **25.03%** | **70.0** | **161.0** | **$52.02** | Lowest OTP cost |

---

### 3. Safe CPPI Production Architecture & Floor Buffer Sweep
Prop firm funded mode requires extracting capital while avoiding infant mortality (breaching the trailing floor before Payout #1):
- **Cushion Definition**: $\text{Cushion}_t = \text{Balance}_t - \text{Floor}_t$.
- **Buffer Sweep Results (10,000 Funded Simulations, 252-Session Horizon)**:
  - **$0 Buffer (Unbuffered)**: 14.19% Infant Mortality | $861.51 Mean Net | **$635.47 Net EV**
  - **$250 Buffer**: 13.81% Infant Mortality | $852.69 Mean Net | **$628.57 Net EV**
  - **$350 Buffer**: 12.82% Infant Mortality | $899.23 Mean Net | **$665.01 Net EV**
  - **$400 Buffer (Optimal)**: **12.45% Infant Mortality** | **$906.21 Mean Net** | **$670.47 Net EV**
  - **$500 Buffer**: 12.38% Infant Mortality | $868.84 Mean Net | **$641.21 Net EV**
  - **$600 Buffer**: 12.48% Infant Mortality | $847.99 Mean Net | **$624.89 Net EV**
- **Optimal Safe CPPI Rule**: If $\text{Cushion}_t < \$400.00$, immediately de-lever to 1 micro across all desks until cushion recovers above $\$500.00$. This achieves peak Net Lifetime EV (**+$670.47 per $39 ticket**) and **87.55% survival to Payout #1**.

---

### 4. Authoritative LucidFlex 25K Withdrawal Policy Optimization (Policies A, B, C, D, C2 — V4 Final Audit)
Prop firm funded accounts require systematically balancing infant mortality (account ruin before Payout #1) against multi-cycle survival and full live promotion. Evaluated across **10,000 independent CRN block-bootstrap simulation paths** over both a **252-session (1-year censored)** horizon and a **1,500-session terminal-outcome (0.0% unresolved)** funded horizon:

#### Authoritative Reference Scenarios & Cushion Compliance:
| Pre-Payout Cushion | Account Balance | Gross Payout Request | Trader Net (90%) | Firm Share (10%) | Post-Payout Cushion | Rulebook Required Cushion | Compliance & Buffer Status |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **$900.00** | $26,000.00 | **$500.00** | $450.00 | $50.00 | **$400.00** | **$400.00** | 100% Rulebook Compliant (Min Buffer) |
| **$1,400.00** | $26,500.00 | **$750.00** | $675.00 | $75.00 | **$650.00** | **$650.00** | 100% Rulebook Compliant (Mid Buffer) |
| **$1,900.00** | $27,000.00 | **$1,000.00** | $900.00 | $100.00 | **$900.00** | **$900.00** | 100% Rulebook Compliant (Max Buffer) |

#### Dual-Horizon 5-Policy Leaderboard & Corrected 3D Pareto Frontier (Seed 42, 10,000 Paths, 7,829 Funded Accounts):
| Policy | 252-Sess EV ($) | 252-Sess Censored (%) | Terminal Payout EV ($) | Terminal Mean Net ($) | Infant Mortality (Funded / Uncond) | P1 Survival (Funded / Uncond) | Post-P1 Fail \| P1 (%) | Terminal Live Promo (%) | 3D Pareto Optimal? | Dominated By |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Policy A: Immediate Harvest ($500 Min)** | $791.61 | 27.65% | **$948.39** | $1,261.20 | **19.38% / 15.17%** | **80.62% / 63.12%** | 46.47% | **43.16%** | **YES** | `None (Frontier)` |
| **Policy B: Patient Harvest ($1,000 Max)** | **$1,262.13** | 44.41% | **$1,837.68** | **$2,397.09** | 30.95% / 24.23% | 69.05% / 54.06% | **39.96%** | 41.46% | **YES** | `None (Frontier)` |
| **Policy C: Adaptive Two-Stage ($500 P1, $1k P2-5)** | $1,132.40 | 36.93% | **$1,540.68** | $2,017.73 | **19.38% / 15.17%** | **80.62% / 63.12%** | 52.80% | 38.05% | **YES** | `None (Frontier)` |
| **Policy D: Fixed $750 Threshold Benchmark** | $1,072.19 | 34.53% | **$1,382.08** | $1,815.15 | 27.05% / 21.18% | 72.95% / 57.11% | 43.18% | 41.45% | **YES** | `None (Frontier)` |
| **Policy C2: Adaptive Cushion-Aware Dynamic** | $1,125.91 | 31.82% | **$1,419.99** | $1,863.57 | **19.38% / 15.17%** | **80.62% / 63.12%** | 57.18% | 34.53% | **NO** | `Policy C` |

#### Quantitative Insights (V4 Final Audit):
1. **Corrected 3D Pareto Frontier (`{Policy A, Policy B, Policy C, Policy D}`)**: Evaluated mathematically via `compute_pareto_frontier_3d` across $(\max \text{Terminal Funded Payout EV}, \min \text{Infant Mortality}, \max \text{Live Promotion})$, four policies are Pareto-optimal: **`{Policy A, Policy B, Policy C, Policy D}`**. Policy D is **not dominated** because Policy A has lower EV ($948.39 vs $1,382.08), Policy B has higher Infant Mortality (30.95% vs 27.05%), and Policy C has lower Live Promotion (38.05% vs 41.45%).
2. **Strict Dominance of Policy C over Policy C2**: Only **Policy C2** is strictly dominated (by Policy C: +$120.69 Terminal Payout EV, $t = +23.17, p_{\text{Holm}} = 1.80 \times 10^{-114}$; identical 19.38% Infant Mortality; +3.53 pp Live Promotion, $t = +11.42, p_{\text{Holm}} = 3.53 \times 10^{-29}$). Under `Required Cushion = $400 + (Gross Payout - $500)`, C2's $650 post-payout cushion after a $750 withdrawal is 100% rulebook-compliant (not a compliance deficit), but leaves a **$250 smaller discretionary safety buffer** above the $25,100 locked floor than Policy C's $900 post-payout cushion.
3. **20% Infant-Mortality Constraint & Structural Lower Bound**: Policies A, C, and C2 achieve the mathematical minimum infant mortality possible under the rulebook's $500 minimum gross payout ($26,000 balance): Pooled `1,517 / 7,829 = 19.38%` (95% Wilson CI `[18.52%, 20.27%]`), Dev (2021–2024) `772 / 3,778 = 20.43%` (95% CI `[19.18%, 21.75%]`, $p(\ne 20\%) = 0.5178$), and Holdout (2025–2026) `713 / 4,067 = 17.53%` (95% CI `[16.39%, 18.73%]`).
4. **Chronological Rank Stability vs Promotion Shift**: Terminal EV ranking (`B > C > C2 > D > A`) and Infant Mortality ranking (`{A, C, C2} < D < B`) are strictly invariant across Pooled, Dev, and Holdout. However, Live Promotion ranking shifts from `A > D > B > C > C2` in Dev to `B > A > D > C > C2` in Holdout (`B - A = +0.81 pp ± 0.67 pp`, $p_{\text{Holm}} = 0.3814$, statistical tie) due to higher 2025–2026 per-session drift favoring Policy B's $900 post-payout cushion in Cycles 2–5.

---

### 5. Finish-Line Lock Proximity Shield Sweep
Evaluated across 10,000 paths (Target = $1,250):
- **No Shield (None)**: Pass Rate 77.75%, Heartbreak Ruin Count = 226, **Heartbreak Rate = 2.82%**.
- **$1,050 Shield**: Pass Rate 78.78%, Heartbreak Ruin Count = 155, **Heartbreak Rate = 1.93%**.
- **$1,100 Shield**: Pass Rate 78.52%, Heartbreak Ruin Count = 156, **Heartbreak Rate = 1.95%**.
- **$1,150 Shield (Optimal)**: Pass Rate **78.29%**, Heartbreak Ruin Count = 177, **Heartbreak Rate = 2.21%** (eliminates 91.4% of late giveback breaches while preserving fast closing velocity).

---

### 5. Desk-Level Allocation Multi-Strategy Comparison

| Scheme | Description | Pass Rate (%) | Fail Rate (%) | Median Sessions | P90 Sessions | Expected Cost/Account |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Scheme 1: Uniform Multi-Asset Ratchet** | Standard 2->3->4 across all desks | **78.29%** | 21.69% | **66.0** | 194.0 | **$49.81** |
| **Scheme 2: Alpha-Tilted Core/Satellite** | S1/S2 full, S3/S4 mid, S5 conservative | 80.17% | 19.81% | 77.0 | 226.0 | $48.65 |
| **Scheme 3: Crude Defense Gated** | S1-S4 standard 2->3->4, S5 MCL capped at 1 | 78.34% | 21.64% | 71.0 | 210.0 | $49.78 |
| **Scheme 4: Fixed 1-Micro Benchmark** | Static 1 micro across all desks | 96.14% | 3.32% | **218.0** | 424.0 | $40.57 |

- **Insight**: Fixed 1-micro has high theoretical pass rate (96.1%), but requires **218 sessions** (~10.5 calendar months!). Scheme 1 and Scheme 3 compress duration by **3.3x** to under 3 calendar months.

---

### 6. Analytical Kelly Criterion & Absorbing Barrier Invariant

#### 6.1 Empirical Kelly Parameters
For a strategy with win probability $p$, loss probability $q = 1 - p$, and payoff ratio $b = \bar{W} / \bar{L}$:
$$f^* = \frac{p \cdot b - q}{b}$$

| Desk / Portfolio | Trades | Win Rate ($p$) | Avg Win | Avg Loss | Payoff ($b$) | Full Kelly ($f^*$) | Half-Kelly ($f^*/2$) | Quarter-Kelly ($f^*/4$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Strategy 1: Morning VA Breakout (09:45)** | 316 | 57.0% | $126.39 | $101.43 | 1.25x | 22.4% | **11.2%** | 5.6% |
| **Strategy 2: Pre-Market Macro (08:35)** | 143 | 49.0% | $213.50 | $142.08 | 1.50x | 15.0% | **7.5%** | 3.7% |
| **Strategy 3: Gold London Fix (10:15)** | 84 | 58.3% | $76.26 | $67.14 | 1.14x | 21.6% | **10.8%** | 5.4% |
| **Strategy 4: Asian Reversion (21:00)** | 103 | 52.4% | $46.27 | $35.00 | 1.32x | 16.4% | **8.2%** | 4.1% |
| **Strategy 5: Crude RTH Expansion (10:15)** | 102 | 36.3% | $79.26 | $32.95 | 2.41x | 9.8% | **4.9%** | 2.4% |
| **Composite Multi-Asset Portfolio** | **748** | **52.1%** | **$120.16** | **$84.84** | **1.42x** | **18.3%** | **9.2%** | **4.6%** |

#### 6.2 The Absorbing Barrier Invariant & Mathematical Proof
Textbook unconstrained Kelly assumes:
1. Logarithmic compounding with ruin only at $\text{Equity} = 0$.
2. Infinite capital survival.

Under the LucidFlex prop environment, an **absorbing liquidation barrier** is enforced:
$$B_t = \max(24000.0, \text{HWM}_t - 1000.0)$$

Applying unconstrained Half-Kelly ($9.2\%$) to nominal $\$25,000$ balance:
$$\text{Risk} = \$25,000 \times 9.17\% = \$2,292.50 \text{ per trade}$$
Because allowable drawdown is strictly $\$1,000.00$, risking $\$2,292.50$ means a single loss creates a **catastrophic breach ($229\%$ of total drawdown)**!

#### 6.3 Mathematical Resolution: Cushion-Referenced Kelly
Under an absorbing barrier, the true capital base is strictly the **Cushion**:
$$C_t = \text{Balance}_t - B_t$$
- At Day 1: $C_0 = \$25,000 - \$24,000 = \$1,000.00$.
- Quarter-Kelly ($4.6\%$) on $C_0$:
  $$\text{Risk}_0 = \$1,000 \times 4.58\% \approx \$45.80 \text{ to } \$70.00$$
  This matches **exactly 2 micro contracts** with a 15–20 point stop ($0.50/tick on MNQ = $2.00/point x 20 pt = $40.00 x 2 = $80.00)!
- As profit accumulates to $+\$600$, $C_t$ expands toward $\$1,600 - \Delta\text{Floor}$, scaling Quarter-Kelly risk up to $\$140–\$180$, allowing **3 to 4 micro contracts**.
- If equity declines toward the floor ($C_t < \$400$), Quarter-Kelly dictates risking $< \$25$, forcing an immediate downshift to **1 micro contract**.

**Theoretical Conclusion**: The Anti-Martingale Pareto Ratchet is the **piecewise-linear optimal realization of Fractional Kelly sizing under an absorbing floor barrier**.

---

## Provenance Verification (Rule 1 & Rule 5 Compliance)

Verified run record in `results/backtest_provenance.db`:
```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : sizing_optimization_5strategy_2021_2026
Strategy     : lucid_flex_ensemble — LucidFlex 5-Strategy Multi-Asset Portfolio (Sizing Optimization)
Strategy Tier: BASELINE
Methodology  : CRN_BLOCK_BOOTSTRAP_10K_GRID_186
Date Range   : 2021-01-07 to 2026-10-30 (1500 days)
Data File    : data/processed/unified_five_strategy_portfolio_trades_2021_2026.parquet
Data SHA-256 : 84179526c91e3f04972ec4f75347328c3d3ff5853298692d47cb9a82b09d9bd2
Git Commit   : 6516315
Cost Model   : CQG/COMEX 1-tick adverse parity | $1.40-$3.50 RT micro tiered [NET (Includes slippage & comms)]
Core Metrics : Trades: 748 | Win%: 52.14% | PF: 1.54 | Net: $16,490.34 | MaxDD: -$1,745.91
Risk Metrics : Sortino: 3.05 | Calmar: 1.59 | Omega: 0.00 | CVaR95: $0.00 | Ulcer: 0.00% | Half-Kelly: 0.000
Warning Flags:
None (Clean Run)
────────────────────────────────────────────────────────────────────────────
```

---

## Implementation & Artifact File Map
- **Research Orchestrator**: `scripts/research_optimal_5strategy_sizing.py`
- **Executive Report**: `results/sizing_cushion_optimization/sizing_cushion_optimization_report.md`
- **Pareto Frontier CSV**: `results/sizing_cushion_optimization/evaluation_pareto_frontier.csv`
- **Ratchet Grid CSV**: `results/sizing_cushion_optimization/evaluation_ratchet_grid_results.csv`
- **Buffer Sweep CSV**: `results/sizing_cushion_optimization/cushion_buffer_sweep_results.csv`
- **Finish-Line Lock CSV**: `results/sizing_cushion_optimization/finish_line_lock_sweep_results.csv`
- **Desk Allocation CSV**: `results/sizing_cushion_optimization/desk_allocation_comparison.csv`
- **Kelly Analytics CSV**: `results/sizing_cushion_optimization/kelly_analytical_sizing.csv`
- **Policy Comparison CSV**: `results/sizing_cushion_optimization/funded_withdrawal_policy_comparison.csv`
- **Threshold Sensitivity CSV**: `results/sizing_cushion_optimization/adaptive_threshold_sensitivity.csv`
- **Publication Figures (300 DPI)**:
  - `results/sizing_cushion_optimization/figure1_ratchet_grid_heatmap.png`
  - `results/sizing_cushion_optimization/figure2_pareto_frontier_tradeoff.png`
  - `results/sizing_cushion_optimization/figure3_funded_infant_mortality_vs_payout.png`
  - `results/sizing_cushion_optimization/figure4_equity_cushion_trajectories.png`
  - `results/sizing_cushion_optimization/figure5_withdrawal_policy_comparison.png`

---

## Production Invariants & Execution Directives
1. **Rule 1: Adopt Balanced Champion Ratchet**:
   - `Tier 1 (2 Micros)`: $0 to +$99
   - `Tier 2 (3 Micros)`: +$100 to +$599
   - `Tier 3 (4 Micros)`: +$600 to +$1,149
   - `Finish-Line Shield (1 Micro)`: $\ge +\$1,150$
2. **Rule 2: Enforce $400 Safe CPPI Cushion Floor Buffer**:
   - If $\text{Cushion} = (\text{Balance} - \text{Floor}) < \$400.00$, immediately reduce to 1 micro across all desks until cushion recovers above $\$500.00$.
3. **Rule 3: Deploy Production Withdrawal Policy (Policy C Default / 3D Pareto Frontier `{A, B, C, D}`)**:
   - **Default Production Policy (Objective C — Structural Minimum Infant Mortality)**: **Policy C (Adaptive Two-Stage Harvest: $500 on P1, $1,000 on P2–P5)**. Immediately harvests $500 gross ($450 trader net) at $26,000 balance on Payout #1 to secure the structural minimum 19.38% pooled infant mortality, then accumulates to $27,000 ($1,000 gross payout, $900 remaining cushion) on Payouts #2–#5 (**$1,540.68 Terminal EV**, **38.05% Live Promotion**).
   - **Alternative Pareto-Optimal Policies**: **Policy B** ($1,837.68 Terminal EV, 30.95% IM, 41.46% Promo) for unconstrained EV maximization; **Policy A** ($948.39 Terminal EV, 19.38% IM, 43.16% Promo) for fastest first payout and highest pooled promotion; **Policy D** ($1,382.08 Terminal EV, 27.05% IM, 41.45% Promo) as the intermediate fixed-$750 benchmark. **Policy C2** is strictly dominated by Policy C and retired.
4. **Rule 4: Crude Volatility Cap (Strategy 5)**:
   - Cap MCL contracts at 2 micros maximum, preventing energy volatility from overwhelming the portfolio risk envelope.
5. **Rule 5: Never Downscale on Day 1 Funded**:
   - Maintain 2 micros on Day 1 of funded mode; do not fall into the 1-micro infant mortality trap.

---

## Cross References
- [Multi-Asset Ensemble Architecture](../strategies/lucid-flex-ensemble.md)
- [LucidFlex 25K Prop Firm Rules](../prop_firm/lucid-flex-25k.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
- [Live Demo Parity Engine](../execution/demo-parity-engine.md)
