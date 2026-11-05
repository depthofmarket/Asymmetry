---
name: alpha-research-pipeline
description: "Governs the 5-stage systematic strategy research lifecycle: economic hypothesis formulation, point-in-time data investigation, vectorized backtest implementation, adversarial stress testing, and wiki documentation."
---

# Alpha Research Pipeline Skill (`alpha-research-pipeline`)

Use this skill when researching, implementing, or evaluating a candidate quantitative trading strategy from hypothesis to paper trading.

## The 5-Stage Alpha Lifecycle

### Stage 1: Economic Hypothesis Formulation
1. Consult `wiki/failed_ideas.md` to ensure the core hypothesis has not already been invalidated.
2. Formulate a document in `research/hypotheses/H<N>_<name>.md` detailing:
   - Economic / microstructure driver (e.g., liquidity imbalance, session open discovery, macro release drift).
   - Market instruments (MNQ, MES, MGC).
   - Expected market regime (Low Vol, Normal, High Vol Shock).

### Stage 2: Data Investigation & Bias Audit
1. Verify historical 1-minute parquet data is continuous and contains no bar gaps or duplicate timestamps.
2. Confirm features only consume information available at timestamp $t \le \tau-1$.
3. Compute dataset SHA-256 hash.

### Stage 3: Vectorized Implementation
1. Code strategy in `backtest/candidates/` adhering to standard vectorized API:
   - Signal indicator calculation.
   - Entry price, stop loss, profit target, and time stop logic.
   - Realistic transaction drag: $\$1.40/\text{RT}$ commissions + 1 tick adverse slippage on market/stop orders.

### Stage 4: Chronological Walk-Forward & Adversarial Audit
1. Run multi-year walkforward across 2021–2026.
2. Submit to the `adversarial_auditor` for:
   - $\pm 25\%$ parameter plateau sweep (Stability Ratio $\ge 0.70\text{x}$).
   - DSR multiple testing correction ($DSR > 0.0$).
   - Outlier dominance check (largest win $\le 35\%$ of net PnL).
   - Monte Carlo block-bootstrap pass rate.

### Stage 5: Wiki Documentation & Provenance Registration
- **If Vetoed / Failed**: Append autopsy to `wiki/failed_ideas.md` with failure metrics and negative invariant rules.
- **If Approved**:
  - Record into `results/backtest_provenance.db` via `ProvenanceStore.record_run()`.
  - Update `wiki/hot.md` and create strategy topic page under `wiki/strategies/`.
  - Log operational journal entry in `wiki/log.md`.
