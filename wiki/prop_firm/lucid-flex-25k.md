---
title: "LucidFlex 25K Rulebook & Compliance Architecture"
tags:
  - prop-firm
  - compliance
  - risk-management
  - drawdown
  - lucid-flex
created: "2026-11-05"
updated: "2026-11-05"
status: active
strategies:
  - lucid_flex_ensemble
related_pages:
  - "strategies/lucid-flex-ensemble.md"
  - "sizing/ratchet-and-cushion.md"
  - "provenance/provenance-protocol.md"
  - "execution/demo-parity-engine.md"
---

# LucidFlex 25K Rulebook & Compliance Architecture

## Executive Summary
The LucidFlex 25K account profile is the central target specification for the trading systems in this repository. Prop firm evaluations enforce strict asymmetric boundary constraints—most notably trailing liquidation floors, daily loss limits, and profit consistency caps. 

Standard unconstrained backtests are invalid in this domain; algorithmic strategies must be simulated with tick-by-tick and end-of-day compliance state machines to model real survival, pass probabilities, and payout harvest expectancy.

## Technical Specification
- **Account Starting Balance**: $25,000.00
- **Profit Target**: $1,250.00 (+5.0% gain to reach $26,250.00)
- **Maximum Trailing Drawdown**: $1,000.00
  - **Drawdown Mode**: `eod_trailing` (calculated on End-of-Day closed balance, not intraday high-water mark peak)
  - **Trailing Floor Dynamic**: Trailing floor rises dollar-for-dollar with EOD account balance gains until it locks.
- **Trailing Floor Permanent Lock**:
  - Once high-water mark reaches or exceeds **$26,100.00** ($bal \ge \text{PEAK\_FOR\_FLOOR\_LOCK}$), the floor locks permanently at **$25,100.00** (`trailing_drawdown_lock_floor = 25_100`).
  - Above $26,100.00, the account retains open upside with a fixed $25,100 liquidation barrier.
- **Daily Soft Stop Limit**: -$600.00. If net realized plus unrealized losses reach -$600 within any single exchange session, trading is halted until the next session.
- **Contract Sizing Cap**: 1 Mini contract or 10 Micro contracts maximum.
- **Consistency Rule**: Maximum 40% of total accumulated profit may originate from a single trading day (`consistency_profit_limit_pct = 40`).
- **Fee Economics**:
  - Evaluation ticket fee: $39.00
  - Activation fee: $0.00
  - Reset fee: $89.00
- **Funded Payout Mechanics**:
  - Minimum profitable days: 3–5 sessions with daily PnL $\ge +\$50.00$
  - Minimum payout threshold: Requires accumulating $\ge +\$600.00$ profit above the $25,100 floor
  - Payout split: 50% fraction of requested payout
  - Minimum withdrawal: $300.00 to $500.00

## Empirical Evidence & Provenance
Evaluation pass probability and funded harvest simulations under full calendar bootstrapping from `results/sizing_cushion_optimization/sizing_cushion_optimization_report.md`:

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

Under 5,000 Common Random Numbers (CRN) block-bootstrap paths:
- Evaluation Pass Rate: 74.42% (Pareto ratchet) / 75.34% (Baseline)
- Median Evaluation Duration: 79.0 sessions (Pareto ratchet) vs 90.0 sessions (Baseline)
- Net Expected Value per evaluation ticket: $588.20 (Safe CPPI) vs $473.24 (Conservative 1-micro trap)

## Implementation & File Map
- **Config Rulebook**: `config/backtest_config.py` (`PropFirmConfig` class and `LUCID_FLEX_25K` profile)
- **Engine Compliance Auditor**: `backtest/demo_parity_engine.py` (lines 39–50, 258–275)
- **Bootstrap Simulation Engine**: `backtest/engine.py`
- **Unit Tests**: `tests/test_prop_firm_ratchet.py`

## Invariant Rules & Failure Modes
1. **Rule 1: Never Violate the EOD Floor**: If account balance drops below the active trailing floor ($bal < \text{floor}$), the account is breached. Simulation terminates immediately.
2. **Rule 2: Daily Soft Stop Disarm**: Reaching -$600.00 daily loss mandates a complete cessation of order flow for that day.
3. **Rule 3: Consistency Cap Compliance**: If a single home-run trade generates $> 40\%$ of the profit target, subsequent sessions must be traded until the 40% cap condition is satisfied before declaring an evaluation pass.

## Cross References
- [Tri-Asset Ensemble Architecture](../strategies/lucid-flex-ensemble.md)
- [Ratchet Sizing & Cushion Protection](../sizing/ratchet-and-cushion.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
- [Demo Parity Engine](../execution/demo-parity-engine.md)
