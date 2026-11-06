---
title: "Candidate Incubation Lifecycle & Strategy Governance"
tags:
  - governance
  - strategy-registry
  - lifecycle
  - provenance
  - candidate-incubation
created: "2026-11-06"
updated: "2026-11-06"
status: active
related_pages:
  - "strategies/lucid-flex-ensemble.md"
  - "strategies/morning-va-breakout.md"
  - "strategies/macro-momentum.md"
  - "strategies/gold-london-fix.md"
  - "provenance/provenance-protocol.md"
  - "execution/agent-execution-guardrails.md"
---

# Candidate Incubation Lifecycle & Strategy Governance

## Executive Summary
This document codifies the quantitative research governance and candidate incubation lifecycle across the repository. To eliminate research contamination and prevent unvetted algorithmic experiments from polluting production baseline backtest metrics, all quantitative strategies are programmatically registered into explicit tiers governed by `config/strategy_registry.py`.

Quantitative provenance records in `results/backtest_provenance.db` are strictly partitioned by strategy tier, ensuring that candidate evaluations and parameter explorations can never overwrite or distort verified production statistics.

---

## Strategy Tier Architecture

Every strategy within the ecosystem belongs to one of four mutually exclusive lifecycle tiers defined in `config/strategy_registry.py`:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Strategy Tier Taxonomy                          │
├─────────────────┬──────────────────────────────────────────────────────┤
│ BASELINE        │ Frozen production strategies running in production   │
│                 │ with verified multi-year walkforward provenance.     │
├─────────────────┼──────────────────────────────────────────────────────┤
│ FORWARD_DEMO    │ Active live demo or paper parity tracking ledgers    │
│                 │ accumulating empirical out-of-sample trade counts.  │
├─────────────────┼──────────────────────────────────────────────────────┤
│ CANDIDATE       │ Active research hypotheses undergoing point-in-time  │
│                 │ signal audits, walkforward tests, and red-team gates.│
├─────────────────┼──────────────────────────────────────────────────────┤
│ REJECTED        │ Falsified hypotheses permanently retired to          │
│                 │ wiki/failed_ideas.md. Re-testing is prohibited.      │
└─────────────────┴──────────────────────────────────────────────────────┘
```

### 1. Production Baselines (`StrategyTier.BASELINE`)
Production baseline strategies represent the verified, frozen production portfolio. These strategies are implemented in Java for live execution (`src/motivewave/*.java`), have passed 5.8-year walkforward evaluation with verified non-zero edge, and have demonstrated parameter robustness across ±25% plateau sweeps (Belfort Step 07):
- `morning_va_breakout_s1`: 09:45 ET Opening Range VA Breakout (MNQ/MES)
- `macro_momentum_s2`: 08:35 ET Tier-1 Macro Release Directional Momentum (MNQ)
- `gold_london_fix_s3`: 10:15 ET COMEX Micro Gold Bullion Fix Breakout (MGC)
- `lucid_flex_ensemble`: Composite Tri-Asset Multi-Strategy Portfolio

### 2. Live Forward Demo Parity (`StrategyTier.FORWARD_DEMO`)
Forward demo ledgers track real-time execution in paper or demo accounts to verify real-world fill parity and slippage drag:
- `lucid_flex_forward_demo`: Live demo trade tracking reconciling CQG fills against backtest fills

### 3. Research Candidates (`StrategyTier.CANDIDATE`)
New strategy hypotheses exploring new alpha mechanisms, order book features, or regime filters. All candidates must be registered via `register_candidate()` before being evaluated by `scripts/alpha_factory.py` or recorded into `results/backtest_provenance.db`. Candidates are quarantined under `strategy_tier="CANDIDATE"`.

### 4. Rejected Ideas (`StrategyTier.REJECTED`)
Falsified strategies that failed one or more incubation gates. Each rejected idea is permanently cataloged in [Failed Ideas & Invalidated Hypotheses Ledger](../failed_ideas.md) with empirical root cause analysis and negative standing invariants.

---

## The 6-Stage Candidate Incubation Gate

To graduate from an initial concept to a production baseline, a candidate strategy must pass all 6 consecutive gates without exception:

```
Stage 1: Pre-Registration & Dead-End Screening
   │
   ▼
Stage 2: Point-in-Time Signal & Feature Audit
   │
   ▼
Stage 3: Execution Realism & L2 Order Book Replay
   │
   ▼
Stage 4: Adversarial Red-Team (DSR + Monte Carlo + Plateau)
   │
   ▼
Stage 5: MotiveWave Java Study Implementation (JDK 25)
   │
   ▼
Stage 6: Live Forward Demo Parity Accumulation (N >= 30)
   │
   ▼
Promotion: Production Baseline Ingestion
```

### Stage 1: Pre-Registration & Dead-End Screening
- **Ex-Ante Hypothesis**: Research premise must be documented before running backtests.
- **Dead-End Ledger Audit**: Hypothesis must be screened against all documented failures in `wiki/failed_ideas.md`. Any concept matching an existing negative invariant is rejected immediately.
- **Registry Entry**: Registered into `config/strategy_registry.py` with `StrategyTier.CANDIDATE`.

### Stage 2: Point-in-Time Signal & Feature Audit
- **Causality Verification**: All indicator features (volatility targets, volume profiles, VWAP, Hawkes processes) must be computed strictly on historical bars ($t \le \tau$).
- **Lookahead Bias Falsification**: Entry and exit prices must be verified against intra-bar timing. Same-bar lookahead is strictly barred.

### Stage 3: Execution Realism & L2 Order Book Replay
- **Managed Stop Activation**: Must support `next_bar` managed stop activation to avoid intrabar excursion lookahead.
- **Fill Mode Enforcement**: Limit orders evaluated under trade-through fills (1 tick offset) rather than optimistic touch fills.
- **Gap-Through Stop Resolution**: Stop loss fills during price gaps must be penalized to `min(stop, open)` for longs and `max(stop, open)` for shorts.

### Stage 4: Adversarial Red-Team & Stress Testing
- **Parameter Plateau Sweep (Belfort Step 07)**: ±25% parameter sensitivity evaluation across 5 levels. Stability ratios must satisfy $0.85 \le \text{SR} \le 1.15$ with zero cliff fall-offs.
- **10,000-Path Monte Carlo Simulation (Belfort Step 08)**: Max drawdown at 99th percentile must not violate the account trailing drawdown limit ($1,000 under LucidFlex 25K).
- **Deflated Sharpe Ratio (DSR)**: Multi-testing deflation accounting for historical trials ($N \ge 25$). Must achieve $DSR \ge 0.05$.

### Stage 5: MotiveWave Java Study Implementation
- **JDK 25 Production Build**: Strategy logic authored in Java (`src/motivewave/*.java`) and compiled with JDK 25.
- **Non-Repainting Tags**: All chart plots and signal generations must use non-repainting bar calculations.
- **Safe CPPI Sizing**: Contract sizing must adhere to Safe CPPI cushion geometry ($<\$400 \implies 1\text{ micro}$, $\ge +\$1,150 \implies 1\text{ micro}$, ratchet at $+\$200 / +\$550$).

### Stage 6: Live Forward Demo Parity Accumulation
- **Sample Size Requirement**: Must accumulate a minimum of $N \ge 30$ live paper executions under active market conditions.
- **Slippage Drag Audit**: Realized fill prices via CQG must remain within 1.0 tick average adverse deviation from theoretical fill prices.

---

## Provenance Store Segregation

Under Rule 1 and Rule 5 of Quantitative Provenance:
1. **Schema Partitioning**: The `backtest_runs` table in `results/backtest_provenance.db` includes an indexed `strategy_tier` column (`BASELINE`, `FORWARD_DEMO`, `CANDIDATE`, `REJECTED`).
2. **Baseline Protection Invariant**: `ProvenanceStore.record_run()` strictly rejects attempts by unvetted strategies to record with `strategy_tier="BASELINE"`. Only strategies enumerated in `AUTHORIZED_BASELINE_STRATEGIES` may claim baseline tier.
3. **Query Filtering**: `scripts/query_provenance.py` displays the `TIER` for each run in `--list` output, and supports `--tier <TIER>` filtering.
