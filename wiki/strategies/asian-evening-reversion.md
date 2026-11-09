---
title: "Candidate Strategy 4: Asian Evening Reversion (21:00 ET)"
tags:
  - strategy
  - candidate
  - equity-index
  - mnq
  - globex
  - tokyo-open
created: "2026-11-08"
updated: "2026-11-08"
status: active
strategies:
  - asian_evening_reversion_s4
related_pages:
  - "strategies/lucid-flex-ensemble.md"
  - "strategies/crude-rth-expansion.md"
  - "strategies/candidate-incubation-lifecycle.md"
  - "prop_firm/lucid-flex-25k.md"
  - "sizing/ratchet-and-cushion.md"
  - "provenance/provenance-protocol.md"
---

# Candidate Strategy 4: Asian Evening Reversion (21:00 ET)

## Executive Summary
Candidate Strategy 4 (`asian_evening_reversion_s4`, registered under `StrategyTier.CANDIDATE`) trades Micro Nasdaq-100 futures (`MNQ`) during the **21:00–23:00 ET (23:00–01:00 UTC-3)** evening Globex session.

Between the 18:00 ET CME Globex reopen and 21:00 ET, US equity index futures trade in a thin retail/algorithmic liquidity regime that frequently drifts directionally on low volume without institutional participation. At **20:00–21:00 ET**, Tokyo cash equities (TSE) and Asian institutional desks open and rebalance cross-Pacific equity index hedges against the prior US RTH settlement. When the pre-Tokyo Globex session (18:00–21:14 ET) has drifted moderately (`0.15` to `0.85` of completed same-day US RTH `ATR(14)`) following an active US RTH session (`RVOL(20) >= 0.85`), and the initial 15-minute Tokyo cash opening range (`21:00–21:14 ET`) actively rejects that drift direction, institutional liquidity providers fade the overextended Globex drift back toward the 18:00 ET reopen equilibrium prior to the 23:00 ET Tokyo midday break.

Why `MNQ` instead of `MES`? Empirical microstructure testing demonstrated that unconditioned `MES` evening mean-reversion fails (`PF 0.62`, Failed Idea #46) because `MES` carries a `$1.25` tick (`$2.50` per 2-tick adverse stop), which consumes over 10% of the median 9-point evening S&P range. `MNQ` carries a `$0.50` tick (`$1.00` per 2-tick adverse stop) across a 35–40 point evening range, cutting tick-friction drag by more than 65%.

## Technical Specification
- **Strategy ID**: `asian_evening_reversion_s4` (`StrategyTier.CANDIDATE`)
- **Instrument**: `MNQ` (Micro E-mini Nasdaq-100 Futures, `$2.00/pt` multiplier, `$0.50` per `0.25` tick)
- **Active Trading Window**: `21:00–23:00 ET` (`23:00–01:00 UTC-3`, user's awake local evening window; zero overnight holding after `23:00 ET`)
- **Point-in-Time Signal Conditions** (evaluated at `21:14:59 ET` bar close, executed at `21:15:00 ET` bar open):
  1. **Completed Same-Day US RTH Participation Gate**: Prior completed 09:30–16:00 ET session relative volume `RVOL(20) >= 0.85` and `ATR(14) <= 650.0` pts.
  2. **Pre-Tokyo Globex Drift Bounds**: Normalized Globex drift $\Delta_{\text{globex}} = \text{Close}_{21:14} - \text{Open}_{18:00}$ satisfies $0.15 \times \text{RTH\_ATR}_{14} \le |\Delta_{\text{globex}}| \le 0.85 \times \text{RTH\_ATR}_{14}$ (filters out both dead flat tape and runaway overnight macro shocks).
  3. **Tokyo Opening 15m Range Filter (`21:00–21:14 ET`)**: Range $H_{21:00\text{--}21:14} - L_{21:00\text{--}21:14} \in [6.0, 45.0]$ MNQ points.
  4. **Opening Candle Rejection Trigger**:
     - **Short Reversion**: $\Delta_{\text{globex}} > 0$ (upward drift from 18:00 ET) AND $\text{Close}_{21:14} < \text{Open}_{21:00}$ (bearish Tokyo opening 15m candle rejecting the upward drift).
     - **Long Reversion**: $\Delta_{\text{globex}} < 0$ (downward drift from 18:00 ET) AND $\text{Close}_{21:14} > \text{Open}_{21:00}$ (bullish Tokyo opening 15m candle rejecting the downward drift).
  5. **Defensive Runaway Trend Veto**: 5-minute `ADX(14) <= 45.0` and normalized displacement $\le 3.5$.
- **Cost Model**: 1-tick limit/market entry (`$0.50`/contract), 2-tick adverse stop slippage (`$1.00`/contract), plus `$1.40` round-trip micro commission (`$2.40` total friction on stop-out, `$1.90` on target/time exit).
- **Bracket Geometry & Pareto Anti-Martingale Ratchet Sizing**:
  - **Base Bracket Distance**: Stop Loss = `35.0` pts (`$70.00`/micro gross, `$72.40`/micro net); Profit Target = `37.5` pts (`1.07R`, `$75.00`/micro gross, `$73.10`/micro net); Breakeven Ratchet at `+1.0R` (`+35.0` pts favorable excursion locks stop at entry `+2` ticks); Mandatory Time Exit at `23:00:00 ET`.
  - **Execution Integrity & Parity Invariants**:
    - **Candidate Governance**: Automated trading defaults to `false` in `@StudyHeader` and settings; explicit user opt-in required; survives reloads.
    - **Bar Completion**: Signal candle (21:14 ET) must be complete (`series.isBarComplete(index)`) before signal confirmation for 21:15 entry.
    - **Conservative Intrabar Breakeven**: Intrabar conflicts on bar $k$ resolve to stop active at start of bar $k$; +1R breakeven ratchet activates on subsequent bars $k+1$ onwards.
    - **Broker Stop Management**: Working broker stop is modified in-place via `setAdjStopPrice` without cancelling; stop failure triggers protective policy.
    - **Fill Price Anchoring**: Bracket stop and target distances are anchored from actual fill price in `onOrderFilled`, with slippage logged.
  - **LucidFlex 25K Pareto Ratchet Scaling (`2 -> 3 -> 4` Micros)**:

| Ratchet Tier | Account Equity Band | Contracts | Net Risk / Trade (Stop) | Net Reward / Trade (Target) |
| :--- | :--- | :---: | :---: | :---: |
| **Tier 1 (Initial Seed)** | `$25,000 – $25,199` (`$0 to +$199`) | **2 MNQ** | `-$144.80` | `+$146.20` |
| **Tier 2 (First Ratchet)** | `$25,200 – $25,549` (`+$200 to +$549`) | **3 MNQ** | `-$217.20` | `+$219.30` |
| **Tier 3 (Full Velocity)** | `$25,550 – $26,149` (`+$550 to +$1,149`) | **4 MNQ** | `-$289.60` | `+$292.40` |
| **Finish-Line Shield** | `>= $26,150` (`>= +$1,150`) | **1 MNQ** | `-$72.40` | `+$73.10` |
| **Safe CPPI Defense** | Cushion `< $400` above Floor | **1 MNQ** | `-$72.40` | `+$73.10` |

## Empirical Evidence & Provenance
Directly queried from `results/backtest_provenance.db`:

```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : run_canonical_s4_asian_evening_reversion_2021_2026
Strategy     : asian_evening_reversion_s4 — Asian Evening Reversion (21:00 ET)
Strategy Tier: CANDIDATE
Methodology  : MULTI_YEAR_WALKFORWARD
Date Range   : 2021-01-04 to 2026-10-30 (2125 days)
Data File    : data/raw/nq_1m_2017_2026_cqg_et.parquet
Data SHA-256 : c9d78a716f5afe040c590fc974e980edfee029081ba47875f041b034c38b737a
Git Commit   : 344c671e38
Bundle (.obtf): results/bundles/run_canonical_s4_asian_evening_reversion_2021_2026.obtf
Cost Model   : 1-tick limit (50c) / 2-tick stop ($1.00) adverse parity | $1.40 RT micro [NET (Includes slippage & comms)]
Core Metrics : Trades: 103 | Win%: 52.43% | PF: 1.46 | Net: $783.30 | MaxDD: -$442.40
Warning Flags:
  ⚠️  CANDIDATE_TIER_QUARANTINED
────────────────────────────────────────────────────────────────────────────
```

### Walk-Forward & Structural Independence Verification
- **In-Sample (2021–2024)**: `+$541.00` net profit (`PF > 1.35`).
- **Out-of-Sample (2025–2026)**: `+$243.00` net profit (`PF > 1.35`).
- **Empirical Daily PnL Correlations (1,515 Trading Days, 2021–2026)**:
  - $\rho(\text{S4}, \text{S1 Morning VA}) = -0.0081$
  - $\rho(\text{S4}, \text{S2 Macro Momentum}) = +0.0090$
  - $\rho(\text{S4}, \text{S3 Gold London Fix}) = +0.0223$
  - $\rho(\text{S4}, \text{S5 Crude RTH Expansion}) = +0.0108$
  - All pairwise correlations are strictly near zero ($|\rho| \le 0.0223 \ll 0.20$).

## Implementation & File Map
- **Strategy Engine**: `strategies/asian_evening_reversion_s4.py`
- **Canonical Backtest Runner**: `scripts/run_candidate_s4_backtest.py`
- **Unit & Adversarial Tests**: `tests/test_asian_evening_reversion_s4.py`, `tests/test_adversarial_asian_reversion_s4.py` (30/30 passing)
- **Portable Bundle**: `results/bundles/run_canonical_s4_asian_evening_reversion_2021_2026.obtf`

## Cross References
- [Multi-Asset Ensemble & 5-Strategy Expansion Architecture](lucid-flex-ensemble.md)
- [Candidate Strategy 5: Crude Oil Post-Fix Range Expansion](crude-rth-expansion.md)
- [Candidate Incubation Lifecycle](candidate-incubation-lifecycle.md)
- [LucidFlex 25K Compliance](../prop_firm/lucid-flex-25k.md)
- [Ratchet Sizing & Cushion Protection](../sizing/ratchet-and-cushion.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
