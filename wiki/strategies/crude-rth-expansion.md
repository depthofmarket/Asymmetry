---
title: "Candidate Strategy 5: Crude Oil Post-Fix Range Expansion (10:15 ET)"
tags:
  - strategy
  - candidate
  - commodities
  - energy
  - mcl
  - crude-oil
created: "2026-11-08"
updated: "2026-11-08"
status: active
strategies:
  - crude_rth_expansion_s5
related_pages:
  - "strategies/lucid-flex-ensemble.md"
  - "strategies/asian-evening-reversion.md"
  - "strategies/gold-london-fix.md"
  - "strategies/candidate-incubation-lifecycle.md"
  - "prop_firm/lucid-flex-25k.md"
  - "sizing/ratchet-and-cushion.md"
  - "provenance/provenance-protocol.md"
---

# Candidate Strategy 5: Crude Oil Post-Fix Range Expansion (10:15 ET)

## Executive Summary
Candidate Strategy 5 (`crude_rth_expansion_s5`, registered under `StrategyTier.CANDIDATE`) trades Micro WTI Crude Oil futures (`MCL`) on NYMEX during the **10:15–12:30 ET** US Regular Trading Hours window.

Earlier NYMEX energy hypotheses at the 09:00 ET pit open (Failed Idea #25), 09:40 ET transatlantic handover (Failed Idea #40), and 14:27 ET settlement auction (Failed Idea #33) failed because those windows are dominated by two-sided commercial hedging and tight-stop whipsaws where `$6.50` round-trip micro energy friction erodes expectancy. By contrast, between **09:30 and 10:14 ET**, cross-market macro flows (US 10:00 ET ISM/Consumer Confidence/JOLTS surveys and the 10:00–10:15 ET LBMA London Gold PM Fix USD clearing) are absorbed into a well-defined 45-minute compression box. When `MCL` is in an active high-volatility, high-participation macro uptrend (`lagged ATR(14) >= $2.00`, `lagged RVOL(20) >= 1.25`, `lagged SMA(20) > SMA(50)`), a bar-close breakout from a compressed 09:30–10:14 ET range (`$0.30` to `$1.20`) between `10:15` and `11:15 ET` captures institutional European energy desk trend continuation into the `11:30 ET` London/European close.

## Technical Specification
- **Strategy ID**: `crude_rth_expansion_s5` (`StrategyTier.CANDIDATE`)
- **Instrument**: `MCL` (Micro WTI Crude Oil Futures, `100` barrels, `$1.00` per `0.01` tick, `$100.00` per `$1.00/bbl` move)
- **Active Trading Window**: `10:15–12:30 ET` (entry window `10:15–11:15 ET`, mandatory flatten at `12:30:00 ET`)
- **Strict Point-in-Time Regime Filters** (computed exclusively from `.shift(1)` prior completed daily sessions — zero same-day lookahead):
  1. **Lagged Volatility Expansion**: Prior completed day's 14-day Average True Range `ATR(14) >= $2.00/bbl`.
  2. **Lagged Volume Participation**: Prior completed day's volume relative to 20-day rolling mean `RVOL(20) >= 1.25`.
  3. **Lagged Macro Trend Alignment**: Prior completed day's `SMA(20) > SMA(50)`.
  4. **Morning Consolidation Box (`09:30–10:14 ET`)**: Box width $R_{\text{box}} = H_{09:30\text{--}10:14} - L_{09:30\text{--}10:14} \in [\$0.30, \$1.20]$.
- **Entry Trigger**: First 1-minute bar between `10:15` and `11:15 ET` closing strictly outside $[L_{\text{box}}, H_{\text{box}}]$ triggers a next-bar open market entry (max 1 trade per session).
- **Cost Model**: 1-tick entry slippage (`$1.00`/contract), 2-tick adverse stop slippage (`$2.00`/contract), plus `$3.50` round-trip micro energy commission (`$6.50` total round-trip friction on stop-out, `$5.50` on target/time exit).
- **Bracket Geometry & Pareto Anti-Martingale Ratchet Sizing**:
  - **Base Bracket Distance**: Stop Loss = `$0.45/bbl` (`45` ticks = `$45.00`/micro gross, `$51.50`/micro net); Profit Target = `$0.90/bbl` (`90` ticks = `2.0R`, `$90.00`/micro gross, `$84.50`/micro net); Breakeven Ratchet at `+1.0R` (`+$0.45/bbl` favorable excursion locks stop at entry `+2` ticks); Mandatory Time Exit at `12:30:00 ET`.
  - **Execution Integrity & Parity Invariants**:
    - **Candidate Governance**: Automated trading defaults to `false` in `@StudyHeader` and settings; explicit user opt-in required; survives reloads.
    - **Bar Completion**: 09:30–10:14 box and 10:15–11:15 breakout candles must be complete (`series.isBarComplete(index)`) before signal confirmation.
    - **Conservative Intrabar Breakeven**: Intrabar conflicts on bar $k$ resolve to stop active at start of bar $k$; +1R breakeven ratchet activates on subsequent bars $k+1$ onwards.
    - **Broker Stop Management**: Working broker stop is modified in-place via `setAdjStopPrice` without cancelling; stop failure triggers protective policy.
    - **Fill Price Anchoring**: Bracket stop and target distances are anchored from actual fill price in `onOrderFilled`, with slippage logged.
  - **LucidFlex 25K Pareto Ratchet Scaling (`2 -> 3 -> 4` Micros)**:

| Ratchet Tier | Account Equity Band | Contracts | Net Risk / Trade (Stop) | Net Reward / Trade (Target) |
| :--- | :--- | :---: | :---: | :---: |
| **Tier 1 (Initial Seed)** | `$25,000 – $25,199` (`$0 to +$199`) | **2 MCL** | `-$103.00` | `+$169.00` |
| **Tier 2 (First Ratchet)** | `$25,200 – $25,549` (`+$200 to +$549`) | **3 MCL** | `-$154.50` | `+$253.50` |
| **Tier 3 (Full Velocity)** | `$25,550 – $26,149` (`+$550 to +$1,149`) | **4 MCL** | `-$206.00` | `+$338.00` |
| **Finish-Line Shield** | `>= $26,150` (`>= +$1,150`) | **1 MCL** | `-$51.50` | `+$84.50` |
| **Safe CPPI Defense** | Cushion `< $400` above Floor | **1 MCL** | `-$51.50` | `+$84.50` |

## Empirical Evidence & Provenance
Directly queried from `results/backtest_provenance.db`:

```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : run_canonical_s5_crude_rth_expansion_2021_2026
Strategy     : crude_rth_expansion_s5 — Crude Oil Post-Fix Range Expansion (10:15 ET)
Strategy Tier: CANDIDATE
Methodology  : MULTI_YEAR_WALKFORWARD
Date Range   : 2021-01-04 to 2026-10-30 (2125 days)
Data File    : data/raw/cl_1m_2020_2026_et.parquet
Data SHA-256 : 7f99fefece90be3114b7eb39060a5fe251038700a7238d3e1caac4f5909d1c90
Git Commit   : 344c671e38
Bundle (.obtf): results/bundles/run_canonical_s5_crude_rth_expansion_2021_2026.obtf
Cost Model   : 1-tick limit ($1.00) / 2-tick stop ($2.00) adverse parity | $3.50 RT micro energy [NET (Includes slippage & comms)]
Core Metrics : Trades: 102 | Win%: 36.27% | PF: 1.37 | Net: $791.00 | MaxDD: -$348.50
Warning Flags:
  ⚠️  CANDIDATE_TIER_QUARANTINED
────────────────────────────────────────────────────────────────────────────
```

### Adversarial Stress & Parameter Plateau Verification
- **Adverse Slippage Stress**: Retains positive expectancy under 3-tick adverse stop slippage (`PF 1.34`, `+$736.00`) and 4-tick adverse stop slippage (`PF 1.29`, `+$666.00`).
- **Parameter Sensitivity Plateau ($\pm 20\%$ across 4 parameters)**: `stop_pts`, `target_rr`, `min_atr14`, and `min_rvol20` maintain `PF 1.19` to `1.68` across all neighbors with zero cliff failures.
- **Empirical Daily PnL Correlations (1,515 Trading Days, 2021–2026)**:
  - $\rho(\text{S5}, \text{S1 Morning VA}) = +0.0361$
  - $\rho(\text{S5}, \text{S2 Macro Momentum}) = +0.0579$
  - $\rho(\text{S5}, \text{S3 Gold London Fix}) = -0.0369$
  - $\rho(\text{S5}, \text{S4 Asian Evening Reversion}) = +0.0108$
  - All pairwise correlations are strictly near zero ($|\rho| \le 0.0579 \ll 0.20$).

## Implementation & File Map
- **Strategy Engine**: `strategies/crude_rth_expansion_s5.py`
- **Canonical Backtest Runner**: `scripts/run_candidate_s5_backtest.py`
- **Unit & Lookahead Tests**: `tests/test_crude_rth_expansion_s5.py` (14/14 passing)
- **Portable Bundle**: `results/bundles/run_canonical_s5_crude_rth_expansion_2021_2026.obtf`

## Cross References
- [Multi-Asset Ensemble & 5-Strategy Expansion Architecture](lucid-flex-ensemble.md)
- [Candidate Strategy 4: Asian Evening Reversion](asian-evening-reversion.md)
- [Strategy 3: Gold London Fix Breakout](gold-london-fix.md)
- [Candidate Incubation Lifecycle](candidate-incubation-lifecycle.md)
- [LucidFlex 25K Compliance](../prop_firm/lucid-flex-25k.md)
- [Ratchet Sizing & Cushion Protection](../sizing/ratchet-and-cushion.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
