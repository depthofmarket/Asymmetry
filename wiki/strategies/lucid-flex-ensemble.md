---
title: "Tri-Asset Multi-Strategy Ensemble Architecture"
tags:
  - strategy
  - ensemble
  - portfolio
  - mnq
  - mes
  - mgc
created: "2026-11-05"
updated: "2026-11-05"
status: active
strategies:
  - lucid_flex_ensemble
related_pages:
  - "strategies/morning-va-breakout.md"
  - "strategies/macro-momentum.md"
  - "strategies/gold-london-fix.md"
  - "prop_firm/lucid-flex-25k.md"
  - "sizing/ratchet-and-cushion.md"
  - "provenance/provenance-protocol.md"
---

# Tri-Asset Multi-Strategy Ensemble Architecture

## Executive Summary
The LucidFlex Ensemble (`lucid_flex_ensemble`) is the primary production trading engine of the repository. It coordinates three temporally separated, uncorrelated quantitative trading strategies across three liquid asset classes:
1. **Strategy 2 (08:35 ET)**: Micro Nasdaq (`MNQ`) Pre-Market Macro Momentum following Tier-1 data releases.
2. **Strategy 1 (09:45 ET)**: Micro Nasdaq (`MNQ`) / Micro S&P (`MES`) Morning Value Area Breakout.
3. **Strategy 3 (10:15 ET)**: Micro Gold (`MGC`) London PM Fix Bullion Breakout.

By restricting trade initiation to distinct non-overlapping time windows and different market drivers (macro news repricing, cash equity auction acceptance, and international bullion clearing), the ensemble achieves superior risk-adjusted returns and drawdown smoothing compared to any single component strategy.

## Technical Specification
- **Portfolio Coordination Matrix**:

| Component Strategy | Instrument | Signal Window | Force Flat Cutoff | Edge Driver | Correlation to S1 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Strategy 2** (`macro_momentum_s2`) | `MNQ` | 08:35–09:25 ET | 09:25 ET | Macro News Surprise Repricing | +0.12 |
| **Strategy 1** (`morning_va_breakout_s1`) | `MNQ` / `MES` | 09:45–10:15 ET | 11:30 ET | Cash Open Profile Value Acceptance | 1.00 (Anchor) |
| **Strategy 3** (`gold_london_fix_s3`) | `MGC` | 10:15–11:00 ET | 11:45 ET | LBMA PM Bullion Auction Clearing | -0.04 |

- **Temporal Non-Overlap Invariant**: Signal windows never overlap. At most one strategy is actively seeking entry at any given minute.
- **Capital & Position Allocation**: Designed for the LucidFlex $25,000 evaluation and funded accounts. Max allowable aggregate exposure is 1 Mini or 10 Micros. Position sizes are governed by the dynamic 2->3->4 micro anti-martingale ratchet.
- **Combined Risk Safeguards**:
  - Daily account soft stop: -$600.00 cumulative loss halts trading across all strategies for the session.
  - Trailing floor lock at $25,100 once balance hits $26,100.
  - Finish-Line Shield: De-lever to 1 micro when account net profit reaches $\ge +\$1,150$ ($< \$100$ from passing).

## Empirical Evidence & Provenance
Directly queried from `results/backtest_provenance.db`:

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

Across the 5.8-year multi-year walkforward (1,499 calendar exchange sessions), 401 sessions had active trades and 1,098 sessions were flat, maintaining high discipline and strict selective participation.

## Implementation & File Map
- **Composite Runner**: `backtest/engine.py` (main ensemble walkforward loop)
- **Configuration Engine**: `config/backtest_config.py` (`lucid_flex_ensemble` composite profile)
- **Forward Demo Parity**: `backtest/demo_parity_engine.py`
- **MotiveWave Studies**: `src/motivewave/` (`LucidMorningVABreakoutStudy.java`, `LucidMacroMomentumStudy.java`, `LucidGoldFixBreakoutStudy.java`)
- **Unit Tests**: `tests/test_provenance_system.py`, `tests/test_prop_firm_ratchet.py`

## Invariant Rules & Failure Modes
1. **Rule 1: Portfolio Daily Soft Stop**: Once net realized and unrealized loss on the day crosses -$600.00, all active orders across all three strategies are cancelled, and positions are closed.
2. **Rule 2: No Correlation Spikes**: Strategies trade independent asset profiles (equity tech vs equity broad vs precious metals bullion). If cross-asset correlation exceeds 0.70 during a systemic crisis, position sizes are halved.
3. **Rule 3: Full Calendar Bootstrapping**: Ensemble performance must always be evaluated over the full calendar session bootstrap (including 0-trade flat days) to avoid trade-day survivorship bias.

## Cross References
- [Strategy 1: Morning VA Breakout](morning-va-breakout.md)
- [Strategy 2: Pre-Market Macro Momentum](macro-momentum.md)
- [Strategy 3: Gold London Fix Breakout](gold-london-fix.md)
- [LucidFlex 25K Compliance](../prop_firm/lucid-flex-25k.md)
- [Ratchet Sizing & Cushion Protection](../sizing/ratchet-and-cushion.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
