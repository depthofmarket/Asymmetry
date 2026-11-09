# Karpathy LLM Wiki Knowledge Base Catalog (index.md)

Welcome to the `nq-scalper-backtest` persistent knowledge base. This wiki serves as the compounding institutional memory across AI agent sessions, preserving verified backtest parameters, market mechanics, risk compliance constraints, and empirical postmortems.

> [!NOTE]
> **Agent Protocol**: Consult this catalog before starting any research or implementation task. Consult [Failed Ideas & Invalidated Hypotheses](failed_ideas.md) to ensure candidate concepts have not been ruled out.

---

## 1. Meta & Governance
- [Wiki Schema & Governance Specification](SCHEMA.md) — The rulebook defining page layout standards, frontmatter schemas, grep-parseable log formats, and lifecycle rules. `[active]`
- [Agent Operational Journal](log.md) — Chronological, append-only record of ingestion, queries, and wiki maintenance events. `[active]`
- [Active Project State & Focus](hot.md) — Dynamic situational awareness dashboard summarizing active forward testing, active candidates, and recent commits. `[active]`
- [Failed Ideas & Invalidated Hypotheses Ledger](failed_ideas.md) — Comprehensive ledger of 47 ruled-out ideas, failure metrics, and permanent standing negative invariants. `[active]`

---

## 2. Strategies & Ensembles
- [Multi-Asset Ensemble & 5-Strategy Expansion Architecture](strategies/lucid-flex-ensemble.md) — System architecture coordinating Production Baselines S1 (09:45 ET), S2 (08:35 ET), and S3 (10:15 ET) alongside Verified Orthogonal Candidates S4 (21:00 ET MNQ) and S5 (10:15 ET MCL) under the Pareto Anti-Martingale Ratchet. `[active]`
- [Strategy 1: Morning VA Breakout (09:45 ET)](strategies/morning-va-breakout.md) — Dual-asset (MNQ/MES) opening range acceptance outside prior session Value Area with GARCH MVT exhaustion filter. `[active]`
- [Strategy 2: Pre-Market Macro Momentum (08:35 ET)](strategies/macro-momentum.md) — MNQ pre-market directional momentum following 08:30 Tier-1 macro releases with Markov high-vol adaptive sizing. `[active]`
- [Strategy 3: Gold London Fix Breakout (10:15 ET)](strategies/gold-london-fix.md) — Long-only COMEX MGC structural breakout following LBMA PM bullion fixing auction clearing. `[active]`
- [Candidate Strategy 4: Asian Evening Reversion (21:00 ET)](strategies/asian-evening-reversion.md) — MNQ Tokyo cash open Globex drift reversion (21:00–23:00 ET / 23:00–01:00 UTC-3) with 35.0 pt stop, 37.5 pt target, and mandatory 23:00 ET flatten (`StrategyTier.CANDIDATE`). `[active]`
- [Candidate Strategy 5: Crude Oil Post-Fix Range Expansion (10:15 ET)](strategies/crude-rth-expansion.md) — Micro WTI Crude Oil (MCL) 09:30–10:14 ET consolidation breakout (10:15–12:30 ET) into the 11:30 ET European close (`StrategyTier.CANDIDATE`). `[active]`
- [Candidate Incubation Lifecycle & Strategy Governance](strategies/candidate-incubation-lifecycle.md) — Strategy tier governance (BASELINE, FORWARD_DEMO, CANDIDATE, REJECTED), 6-stage incubation gates, and provenance store segregation. `[active]`
- [Declarative Confluence Engine & Decision Trace Architecture](strategies/declarative-confluence-engine.md) — Composable Boolean condition trees, multi-group scoring cards, veto overrides, decision traces, and 10-tool MCP server. `[active]`
- [Strategy & Prop-Firm Metrics Dashboard](strategies/strategy-prop-metrics-dashboard.md) — Metric inventory and three distinct visual sheets for performance, robustness/stress, and prop-account risk. `[active]`

---

## 3. Prop Firm & Account Compliance
- [LucidFlex 25K Rulebook & Compliance Architecture](prop_firm/lucid-flex-25k.md) — Specifications for $25K account, $39 One-Time Payment (OTP, zero monthly rebill), $1,250 target, $1,000 trailing DD, $25,100 floor lock, $600 daily soft stop, and payout terms. `[active]`

---

## 4. Position Sizing & Cushion Protection
- [Ratchet Sizing Geometry & Cushion Protection](sizing/ratchet-and-cushion.md) — Anti-martingale 2->3->4 micro ratchet, Pareto frontier optimization, Safe CPPI floor buffer, and resolution of the 1-micro infant mortality trap. `[active]`

---

## 5. Quantitative Provenance & Anti-Hallucination
- [Quantitative Provenance Protocol & Anti-Hallucination Standards](provenance/provenance-protocol.md) — Standing orders for results/backtest_provenance.db, data SHA-256 hashes, query CLI, and standardized verification footers. `[active]`

---

## 6. Execution Architecture & Broker Integration
- [MotiveWave Custom Studies & Java Execution Integration](execution/motivewave-integration.md) — Java custom studies SDK, non-repainting execution tags, trailing floor tracking, and CQG feed routing. `[active]`
- [Live Demo Parity Engine & Execution Auditing](execution/demo-parity-engine.md) — Real-time demo parity tracking, slippage drag calculation, morning watcher daemon, and order intent auditing. `[active]`
- [Agent Execution Guardrails & Subprocess Security](execution/agent-execution-guardrails.md) — Runtime command validation, dangerous binary blocking, exploratory backtest gates, and safe subprocess execution. `[active]`
