---
title: "Ratchet Sizing Geometry & Cushion Protection"
tags:
  - sizing
  - ratchet
  - cppi
  - risk-management
  - money-management
created: "2026-11-05"
updated: "2026-11-05"
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

This document formalizes the dynamic anti-martingale ratchet geometry, the mathematical resolution of the "1-Micro Funded Infant Mortality Trap," and the production Safe CPPI (Constant Proportion Portfolio Insurance) buffer architecture.

## Technical Specification

### 1. Evaluation Anti-Martingale Ratchet Geometry
During evaluation, contract sizing scales up as accumulated profit widens the distance to the liquidation floor:

| Tier | Contract Size | Baseline Profit Threshold | Pareto Frontier Threshold | Allocation Function |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | 2 Micros | $0 to +$199 | $0 to +$199 | Baseline Entry Cushion |
| **Tier 2** | 3 Micros | +$350 to +$749 | **+$200 to +$549** | Accelerated Compounding |
| **Tier 3** | 4 Micros | +$750 to +$1,149 | **+$550 to +$1,149** | Peak Leverage |
| **Shield** | 1 Micro | $\ge +\$1,150$ | $\ge +\$1,150$ | Finish-Line Protection |

- **Pareto Efficiency Gain**: Shifting the thresholds to +$200 and +$550 compresses the median evaluation duration by **11.0 exchange sessions** (~16 calendar days / 2.3 calendar weeks) while maintaining a 74.42% pass rate.

### 2. The 1-Micro Funded Infant Mortality Trap
Conventional retail wisdom prescribes dropping contract size to 1 micro upon entering funded status ("conservative staging until a $500 cushion is built"). Rigorous Monte Carlo block-bootstrap simulation proved this to be an empirical trap:
- **Zero-Payout Infant Mortality**: Jumps from **13.94% up to 21.34%** (+7.41 pp).
- **Mean Lifetime Payout**: Falls from $847.04 down to $679.91 (-$167.14).
- **Net EV per Ticket**: Collapses from $599.16 to $473.24 (-$125.92).
- **Mathematical Root Cause**: LucidFlex requires accumulating $\ge +\$600$ profit to request a minimum withdrawal ($300). At 1 micro, winning days average only +$20 to +$45. Needing 40+ sessions to reach the threshold extends exposure to trailing drawdown drift and fixed transaction costs, resulting in premature ruin before the first withdrawal.

### 3. Safe CPPI Production Architecture
Instead of static de-leveraging upon funding, the system deploys **Safe CPPI**:
- **Day 1 Funded Sizing**: Maintain normal ratchet (2 micros base).
- **Cushion Definition**: $\text{Cushion} = \text{Account Balance} - \text{Trailing Floor}$.
- **Dynamic Floor Protection**: If $\text{Cushion} < \$400.00$, immediately de-lever to 1 micro until cushion recovers above $500.00.
- **Finish-Line Shield**: In evaluation mode, once profit reaches $\ge +\$1,150$ (within $100 of the $1,250 target), de-lever to 1 micro to prevent giving back the pass on a late draw.
- **Volatility Sizing Filter**: Halve contracts if point-in-time GARCH volatility drops into the lowest decile ($< 0.898\%$), where directional persistence is absent.

## Empirical Evidence & Provenance
From `results/sizing_cushion_optimization/sizing_cushion_optimization_report.md` (5,000 CRN block-bootstrap paths over 252 sessions):

| Policy | Pass Rate | Median Pass Duration | Funded Infant Mortality | Lifetime Payout | Net Ticket EV |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline Ratchet (350/750)** | 75.34% | 90.0 days | 13.94% | $847.04 | $599.16 |
| **Pareto Ratchet (200/550)** | 74.42% | **79.0 days** | 14.12% | $839.20 | $586.10 |
| **1-Micro Conservative Trap** | 74.42% | 79.0 days | **21.34%** | $679.91 | $473.24 |
| **Safe CPPI ($400 Buffer)** | **74.42%** | **79.0 days** | **14.63%** | **$828.32** | **$588.20** |
| **Fixed 1-Micro Benchmark** | 58.12% | 142.0 days | 17.39% | $512.40 | $399.39 |

Verified run record in `results/backtest_provenance.db`:
```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : run_canonical_lucid_flex_ensemble_2021_2026
Strategy     : lucid_flex_ensemble — LucidFlex 25K Multi-Strategy Ensemble
Methodology  : multi_year_walkforward
Date Range   : 2021-01-07 to 2026-10-30 (2423 days)
Data File    : data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet
Data SHA-256 : ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca
Git Commit   : 7d63ca2a3e8
Cost Model   : CQG/COMEX 1-Tick Adverse Parity + Commission ($1.40 RT micro) [NET]
Metrics      : Trades: 543 | Win%: 55.06% | PF: 1.56 | Net: $14,916.04 | MaxDD: -$1,511.51
Warning Flags: None
────────────────────────────────────────────────────────────────────────────
```

## Implementation & File Map
- **Ratchet Engine**: `backtest/demo_parity_engine.py` (lines 258–275)
- **Bootstrap Optimization**: `results/sizing_cushion_optimization/sizing_cushion_optimization_report.md`
- **Data Table**: `results/sizing_cushion_optimization/funded_transition_policy_comparison.csv`
- **Unit Tests**: `tests/test_prop_firm_ratchet.py`

## Invariant Rules & Failure Modes
1. **Rule 1: Never Downscale Sizing on Day 1 Funded**: Respect the empirical proof of Failed Idea #1; maintain 2 micros base on Day 1 of funded mode.
2. **Rule 2: Cushion Floor $< \$400$ Mandate**: If distance to floor is $< \$400$, contracts must immediately be reduced to 1 micro without exception.
3. **Rule 3: Finish-Line Lock**: At $+\$1,150$ profit in evaluation mode, contract size must drop to 1 micro to seal the pass.

## Cross References
- [Tri-Asset Ensemble Architecture](../strategies/lucid-flex-ensemble.md)
- [LucidFlex 25K Compliance](../prop_firm/lucid-flex-25k.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
- [Demo Parity Engine](../execution/demo-parity-engine.md)
- [Failed Ideas Ledger](../failed_ideas.md)
