---
title: "Strategy 3: Gold London Fix Breakout (10:15 ET)"
tags:
  - strategy
  - commodities
  - mgc
  - gold
  - london-fix
created: "2026-11-05"
updated: "2026-11-05"
status: active
strategies:
  - gold_london_fix_s3
related_pages:
  - "strategies/lucid-flex-ensemble.md"
  - "strategies/morning-va-breakout.md"
  - "prop_firm/lucid-flex-25k.md"
  - "sizing/ratchet-and-cushion.md"
  - "provenance/provenance-protocol.md"
---

# Strategy 3: Gold London Fix Breakout (10:15 ET)

## Executive Summary
Strategy 3 (`gold_london_fix_s3`) trades Micro Gold futures (`MGC`) on the COMEX exchange, targeting structural orderflow imbalances following the London Bullion Market Association (LBMA) Gold Price PM fixing auction (15:00 London time / 10:00–10:15 ET). 

During the auction fixing, major bullion banks accumulate and match commercial physical orders. Once the PM fix price is officially declared at approximately 10:15 ET, institutional inventory imbalances cascade into the US futures market, generating high-velocity directional breakouts that exhibit strong uncorrelated returns relative to US equity indices.

## Technical Specification
- **Instrument**: `MGC` (Micro Gold Futures, $10.00 per 1.00 price move, $1.00 per 0.10 tick). Full-size `GC` is $100.00 per 1.00. An unrecognized symbol is not treated as `MGC` and cannot submit an order. This multiplier is display and chart P&L only; contract quantity comes from the account-state sizer.
- **Time Window**: 10:15:00 to 11:00:00 ET (Order cancellation and force exit at 11:45 ET)
- **Direction**: Long-Only structural bias (empirically validated institutional gold accumulation bias following physical auction resolution).
- **Entry Logic**:
  - Compute 15-minute price range established during the LBMA fixing window (10:00:00 to 10:14:59 ET).
  - High of Fix Range = $H_{\text{fix}}$, Low of Fix Range = $L_{\text{fix}}$.
  - Signal triggers if 1-minute bar closes above $H_{\text{fix}} + 0.30$ pts before 10:45 ET.
- **Cost Model**: COMEX 1-Tick Adverse Fill Parity ($0.10 / pt slippage) plus $1.40 round-trip micro commission.
- **Bracket Risk**:
  - Stop Loss: 4.50 gold points ($45.00 per micro contract).
  - Profit Target: 11.25 gold points ($112.50 per micro contract) (1:2.5 Risk/Reward).
  - Trailing Stop: Breakeven activation when trade reaches $+1.0R$ ($+4.50$ pts).

## Empirical Evidence & Provenance
Directly queried from `results/backtest_provenance.db`:

```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : run_canonical_s3_gold_london_fix_2021_2026
Strategy     : gold_london_fix_s3 — Gold London Fix Breakout (10:15 ET)
Methodology  : multi_year_walkforward
Date Range   : 2021-01-07 to 2026-10-30 (2423 days)
Data File    : data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet
Data SHA-256 : ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca
Git Commit   : 7d63ca2a3e8
Cost Model   : COMEX 1-Tick Adverse Parity | $1.40 RT ($0.70/side micro) [NET]
Metrics      : Trades: 84 | Win%: 58.33% | PF: 1.59 | Net: $1,386.62 | MaxDD: -$693.00
Warning Flags: None
────────────────────────────────────────────────────────────────────────────
```

### Step 07 Sensitivity Analysis (The Plateau Principle)
Evaluated across +/-25% shifts (5 steps: -25%, -12.5%, 0%, +12.5%, +25%):
- `target_rr` (base 1.50, range [1.125 .. 1.875]): Stability Ratio **1.00x** | Min PnL: $454.66 | Verdict: `ROBUST_PLATEAU`
- `stop_ticks` (base 25, range [19 .. 31]): Stability Ratio **1.00x** | Min PnL: $801.47 | Verdict: `ROBUST_PLATEAU`
- `min_fix_return` (base 0.0010, range [0.00075 .. 0.00125]): Stability Ratio **1.00x** | Min PnL: $1,381.37 | Verdict: `ROBUST_PLATEAU`
- Provenance Run ID: `run_plateau_sweep_s3_gold_london_fix`
- Chart: `results/parameter_plateau_sweep/plateau_sweep_s3.png`

## Implementation & File Map
- **MotiveWave Java Study**: `src/motivewave/LucidGoldFixBreakoutStudy.java`
- **Backtest Logic**: `backtest/engine.py` (Strategy 3 runner)
- **Configuration**: `config/backtest_config.py` (Strategy 3 block)
- **Unit Tests**: `tests/test_provenance_system.py`

## Invariant Rules & Failure Modes
1. **Rule 1: Fixed Cutoff at 11:45 ET**: All open MGC positions must be liquidated by 11:45 ET prior to the European market close and afternoon liquidity thinning.
2. **Rule 2: Long-Only Restriction**: Short entries are structurally prohibited based on 5-year empirical failure of post-fix gold shorting.
3. **Rule 3: Non-Overlapping Window**: S3 executes at 10:15 ET, providing temporal separation from S1 (09:45 ET) and S2 (08:35 ET), preventing simultaneous margin drawdowns.

## Cross References
- [Tri-Asset Ensemble Architecture](lucid-flex-ensemble.md)
- [Strategy 1: Morning VA Breakout](morning-va-breakout.md)
- [LucidFlex 25K Compliance](../prop_firm/lucid-flex-25k.md)
- [Ratchet Sizing & Cushion Protection](../sizing/ratchet-and-cushion.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
