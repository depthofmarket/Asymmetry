# Test Infrastructure Specification: Sizing Math & Cushion Optimization

## 1. Overview & Test Mission

This document defines the comprehensive test infrastructure, verification methodology, and test architecture for the **LucidFlex 25K Prop Evaluation & Funded Cushion Optimization** research project.

The test suite enforces opaque-box and functional verification across all four core requirements defined in `ORIGINAL_REQUEST.md` and `PROJECT.md`:
* **R1: Frozen Signal Strategy Mandate**: Ensuring 100% frozen strategy signals (S1 09:45 VA Breakout, S2 10:15 Gold Fix, S3 08:35 Macro Momentum) across 543 historical trades (2021–2026) with zero modifications to entry, exit, stop, or contract multiplier logic.
* **R2: Evaluation Ratchet Optimization**: Testing grid search mechanics over Tier 2 ($200–$400) and Tier 3 ($500–$850) using Common Random Numbers (CRN) block-bootstrap Monte Carlo on the 1,499 continuous session calendar, extracting the Pareto frontier to compress median pass duration below 90 sessions while maintaining $\ge 72-75\%$ pass rate.
* **R3: Funded Mode Transition & Infant Mortality Analysis**: Testing transition policies (conservative 1-micro staging, standard ratchet Day 1, progressive dynamic cushion models), verifying infant mortality rate calculation ($0 payout failure rate), and lifetime net payout extraction.
* **R4: Deliverables and Output Artifacts**: Validating the presence, schemas, non-emptiness, and semantic integrity of the 4 deliverable CSVs, 4 high-DPI visualization figures, and the executive markdown report in `results/sizing_cushion_optimization/`.

---

## 2. Test Execution Environment & Framework

* **Test Framework**: `pytest` ($\ge 8.0$)
* **Python Runtime**: Python 3.12 (via pyenv/system)
* **Execution Command**:
  ```bash
  python -m pytest tests/test_sizing_cushion_optimization_e2e.py -v
  ```
* **Performance Budget**:
  - Full suite execution time: $\le 45$ seconds.
  - Test isolation: Each test is strictly isolated, deterministic, and self-contained.
  - Seed determinism: Fixed seeds (`seed=42`, `seed=7`) ensure reproducible Monte Carlo paths and Common Random Numbers (CRN) arrays.

---

## 3. Four-Tier Testing Methodology

The test suite is structured strictly under the 4-tier methodology:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        4-TIER TEST ARCHITECTURE                        │
├────────────────────────────────────────────────────────────────────────┤
│ Tier 1: Feature Coverage (>=5 tests per feature)                       │
│   - F1: Frozen Signal Strategy Integrity (5 tests)                     │
│   - F2/F3: Ratchet Grid Search & CRN Engine (5 tests)                  │
│   - F4: Pareto Frontier Extraction (5 tests)                           │
│   - F5-F9: Funded Transition & Infant Mortality Engine (5 tests)       │
│   - F10-F13: Deliverables & Pipeline Contracts (5 tests)               │
├────────────────────────────────────────────────────────────────────────┤
│ Tier 2: Boundary & Corner Cases (>=5 tests per feature)                │
│   - B1: Signal & Calendar Boundary Conditions (5 tests)                │
│   - B2: Simulation & Trailing Floor Drawdown Boundaries (5 tests)       │
│   - B3: Pareto Frontier Boundary & Edge Conditions (5 tests)           │
│   - B4: Funded Transition & Payout Boundaries (5 tests)                │
├────────────────────────────────────────────────────────────────────────┤
│ Tier 3: Cross-Feature Combinations (Pairwise Interactions)             │
│   - C1: CRN Grid Search -> Pareto Frontier Extraction (End-to-End)     │
│   - C2: Optimal Eval Policy -> Decoupled Funded Transition Pipeline    │
│   - C3: Soft Stop Intraday Halts -> Ratchet Contract Size Escalation   │
│   - C4: Adverse Slippage Stress -> Ratchet & Payout Sensitivity        │
│   - C5: Decoupled Policy Isolation -> State & Contract Independence    │
├────────────────────────────────────────────────────────────────────────┤
│ Tier 4: Real-World Application Scenarios                               │
│   - S1: Chronological Historical Replay (1,499 sessions, 2021–2026)    │
│   - S2: Full Lifecycle Simulation: Eval Pass -> Funded Graduation      │
│   - S3: Empirical Proof of Infant Mortality Paradox                    │
│   - S4: Monte Carlo CRN Distribution & Variance Reduction Convergence  │
│   - S5: Research Runner Pipeline & Artifact Schema Verification        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Requirements Traceability Matrix

| Requirement | Feature ID | Test Class / Function | Verification Focus |
|---|---|---|---|
| **R1** | F1 | `test_tier1_f1_*`<br>`test_tier2_b1_*` | Exact 543 trades, 22 columns, 0 nulls, S1/S2/S3 splits, 1,499 continuous exchange sessions, base PnL sum $12,947.18, immutable returns. |
| **R2** | F2, F3, F4 | `test_tier1_f2_*`<br>`test_tier1_f3_*`<br>`test_tier2_b2_*`<br>`test_tier2_b3_*`<br>`test_tier3_c1_*` | Grid bounds ($200–$400, $500–$850, step $25 = 135 pts), CRN block-bootstrap variance reduction, Pareto dominance logic, pass rate $\ge 72-75\%$, median duration compression from 90 sessions down to 78–87 sessions. |
| **R3** | F5, F6, F7, F8, F9 | `test_tier1_f4_*`<br>`test_tier2_b4_*`<br>`test_tier3_c2_*`<br>`test_tier4_s2_*`<br>`test_tier4_s3_*` | Decoupled eval/funded policies, conservative 1-micro staging, standard ratchet Day 1, dynamic CPPI cushion scaling ($400 floor buffer de-leveraging), zero-payout infant mortality calculation, lifetime net payout extraction. |
| **R4** | F10, F11, F12, F13 | `test_tier1_f5_*`<br>`test_tier3_c5_*`<br>`test_tier4_s5_*` | 4 deliverable CSVs, 4 high-DPI figures, executive report markdown schema and headers in `results/sizing_cushion_optimization/`, runner script CLI interface. |

---

## 5. Test Suite Implementation File

All test logic is consolidated in:
`tests/test_sizing_cushion_optimization_e2e.py`

### Test Runner Invocation:
```bash
# Standard test run
python -m pytest tests/test_sizing_cushion_optimization_e2e.py -v

# Run specific tier
python -m pytest tests/test_sizing_cushion_optimization_e2e.py -k "tier1" -v
python -m pytest tests/test_sizing_cushion_optimization_e2e.py -k "tier2" -v
python -m pytest tests/test_sizing_cushion_optimization_e2e.py -k "tier3" -v
python -m pytest tests/test_sizing_cushion_optimization_e2e.py -k "tier4" -v
```

---

## 6. Invariants & Data Integrity Assertions

1. **Trade Record Invariant**:
   - Total rows: 543
   - Strategies: `Strategy 1: Morning VA Breakout (09:45 ET)` (316), `Strategy 2: Gold London Fix (10:15 ET)` (84), `Strategy 3: Macro Release Momentum (08:35 ET)` (143).
   - Instruments: MNQ, MES, MGC.
   - Base PnL sum: exactly `$12,947.18`.
   - Null count: 0 across all 22 columns.
2. **Session Calendar Invariant**:
   - Exactly 1,499 continuous exchange sessions (09:30 ET prints) between 2021-01-07 and 2026-10-30.
   - Traded sessions: 400 (or 401 including 2023-04-07 Good Friday quirk).
   - Zero-trade sessions: $\ge 1,098$.
3. **Prop Evaluation Rule Invariants**:
   - Starting Capital: $25,000.00
   - Profit Target: $1,250.00 (+5.0% -> $26,250.00)
   - Max Trailing Drawdown: $1,000.00 (trailing floor from peak balance)
   - Floor Lock: $25,100.00 (locks permanently once peak $\ge \$26,100.00$)
   - Daily Soft Stop: -$600.00 (halts subsequent windows for remainder of day)
4. **Funded Mode Invariants**:
   - Cycle: 5 sessions, $\ge 3$ profit days with daily PnL $\ge \$50.00$.
   - Payout: 50% profit fraction, $\ge \$300.00$ minimum request (requires $\ge \$600.00$ accumulated profit).
   - Trader split: 90%.
   - Post-payout floor: $\max(\text{floor}, \$25,100.00)$.
   - Maximum lifetime payouts: 5 payouts.
