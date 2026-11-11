---
title: "LucidFlex 25K Rulebook & Compliance Architecture"
tags:
  - prop-firm
  - compliance
  - risk-management
  - drawdown
  - lucid-flex
  - funded-payouts
created: "2026-11-05"
updated: "2026-11-11"
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
The **LucidFlex 25K** account profile (`config/prop_firm_registry.py`) is the immutable single source of truth for all quantitative backtests, Monte Carlo simulations, execution watchdogs, and position sizing models in this repository. 

Prop firm evaluations and funded live simulation accounts enforce asymmetric boundary constraints—most notably trailing liquidation floors, daily soft stops, and payout eligibility mechanics. This document formalizes the exact rules, parameters, mathematical formulas, and failure modes so that no agent or script ever needs to guess or re-query these specifications.

---

## Technical Specification & Parameter Registry

### 1. Evaluation Phase
- **Starting Account Balance**: $25,000.00
- **Profit Target**: $1,250.00 (+5.0% gain to reach $26,250.00 target balance)
- **Fee Economics**:
  - Evaluation ticket fee: **$39.00 One-Time Payment (OTP)**
  - Monthly subscription: **STRICTLY $0.00** (Zero monthly rebill)
  - Time limit: **NO expiration** (trade at your own pace)
  - Activation fee: $0.00
  - Reset fee: $89.00 (optional, max 0 recommended per plan)
- **Maximum Trailing Drawdown**: $1,000.00
  - **Drawdown Mode**: `eod_trailing` (calculated strictly on End-of-Day closed balance, never intraday high-water mark peak)
  - **Initial Liquidation Floor**: $24,000.00 ($25,000.00 - $1,000.00)
  - **Trailing Dynamic**: Floor rises dollar-for-dollar with EOD account peak balance:
    $$\text{Floor}_t = \max(\$24,000.00, \text{Peak EOD Balance}_t - \$1,000.00)$$
- **Permanent Floor Lock**:
  - Once high-water mark reaches or exceeds **$26,100.00**, the floor locks permanently at **$25,100.00** (Starting Balance + $100.00):
    $$\text{If } \text{Peak Balance}_t \ge \$26,100.00 \implies \text{Floor}_t = \$25,100.00 \text{ (locked permanently)}$$
  - Above $26,100.00, the account retains open upside with a fixed $25,100.00 liquidation barrier.
- **Daily Loss Limit (base scenario ON, $600)**:
  - Soft breach: block **new entries** until the next exchange session.
  - Do **not** arithmetically clip a trade's realized P&L to -$600, and do not invent flatten fills.
  - Authoritative ledger simulator (`backtest/lucidflex_eval.py`) uses **realized-close** P&L only because S1–S3 bundles lack intraday marks.
- **Official LucidFlex 25K contract maximum**: 2 minis or **20 micros** ([evaluation account](https://support.lucidtrading.com/en/articles/12945790-lucidflex-evaluation-account), verified 2026-11-11).
- **Internal portfolio risk cap**: 10 micros. This is an intentional conservative desk limit (`INTERNAL_RISK_CAP_MICROS`), **not** Lucid's official account maximum. `MAX_MICRO_CONTRACTS` remains a backward-compatible alias of the internal cap.
- **Consistency Rule (evaluation, 40% standard)**:
  $$\frac{\text{largest single-day profit}}{\text{total evaluation account profit}} \le 0.40$$
  after the $1,250 target is reached. Equivalent implementation: total profit must be $\ge \max(\$1{,}250, \text{largest day}/0.40)$. A 50% add-on exists at checkout; this repository's base scenario is 40%. Funded LucidFlex accounts have **no** consistency rule.

---

### 2. Funded Phase (Master / LiveSim Account)
When an evaluation is passed, the account transitions into the Funded Master/LiveSim environment:
- **Starting Account Balance**: Resets to **$25,000.00**.
- **Drawdown Floor**: Resets to **$24,000.00** ($1,000.00 trailing drawdown allowance).
- **Floor Trailing Mechanics**: Trails $1,000.00 behind peak EOD balance up to **$26,100.00**, at which point the floor **permanently locks at $25,100.00** (Starting Balance + $100.00).
- **Daily Soft Stop Limit**: -$600.00 session halt (same as evaluation).
- **Consistency / Buffer**: Funded LucidFlex has **no consistency requirement** and **no mandatory payout buffer**. Post-payout leftover dollars above the $25,100 locked floor are arithmetic consequences of the payout size. Extra retained cushions used in `dashboard_analytics.run_funded` (e.g. Policy C waiting for a $900 leftover) are **optional portfolio policy**, not a Lucid rule.
- **Payout Deductions**: Payouts are deducted directly from the account balance, which directly reduces the remaining cushion above the $25,100.00 locked floor.

---

### 3. Payout Eligibility & Calculation Rules

#### 3.1 Eligibility Requirements
To request an approved withdrawal, an account must satisfy all four conditions:
1. **Minimum Profitable Days**: At least **5 separate trading days** (not required to be consecutive) with daily net profit $\ge +\$100.00$ each during the payout cycle.
2. **Cycle Net Profit Requirement**: Must have at least **+$1.00 net profit** during that cycle compared to the balance after the previous payout.
3. **Profit-Day Counter Reset**: The 5-day profit counter resets to 0 after EVERY approved payout and must be earned again.
4. **Account Lifetime Limit**: Up to **5 payouts maximum** per account before being transitioned to a live brokerage account.

#### 3.2 Payout Calculation Formula & Split
- **Gross Payout Formula**:
  $$\text{Eligible Payout} = \min\left(\$1,000.00, \, 0.50 \times (\text{Account Balance} - \$25,000.00)\right)$$
- **Minimum Payout Request**: **$500.00 gross**
  - Requires Account Balance $\ge \$26,000.00$ ($1,000.00 profit).
  - Trader Net (90/10 split): **$450.00** net payout.
  - Balance after payout: $25,500.00.
  - Remaining Drawdown Cushion above $25,100.00 locked floor: **$400.00**.
- **Maximum Payout Request**: **$1,000.00 gross**
  - Requires Account Balance $\ge \$27,000.00$ ($2,000.00 profit).
  - Trader Net (90/10 split): **$900.00** net payout.
  - Balance after payout: $26,000.00.
  - Remaining Drawdown Cushion above $25,100.00 locked floor: **$900.00**.
- **Profit Split**: **90/10** (Trader receives 90%, Prop Firm retains 10%).
- **Post-Payout leftover vs locked floor** (mechanical, not a mandated buffer):
  $$\text{Leftover} = 400.0 + (\text{Gross Payout} - 500.0) \quad \text{for } \text{Gross Payout} \in [500, 1000]$$
  Sizing research that *requires* this leftover before requesting a payout is optional policy.

#### 3.3 Authoritative Withdrawal Policy Comparison & Corrected 3D Pareto Frontier (10,000 CRN Paths, 7,829 Funded Accounts, 1,500-Session Terminal Completion)
- **Policy A (Immediate Harvest, $500 Min)** [`PARETO-OPTIMAL`]: Harvests as soon as balance reaches $26,000. Achieves **80.62% Payout #1 survival**, **19.38% infant mortality** (95% CI `[18.52%, 20.27%]`), highest pooled live promotion rate (**43.16%**; 26.72% at 252 sessions), and **$948.39 Terminal Funded-Lifecycle Payout EV** ($791.61 at 252 sessions).
- **Policy B (Patient Harvest, $1,000 Max)** [`PARETO-OPTIMAL`]: Waits for $27,000 balance ($900 post-payout cushion). Achieves the highest **Terminal Funded-Lifecycle Payout EV of $1,837.68** ($1,262.13 at 252 sessions) and **41.46% live promotion** (46.79% in Holdout 2025–2026), at the cost of **30.95% infant mortality** (69.05% P1 survival).
- **Policy C (Adaptive Two-Stage Default, $500 P1 -> $1,000 P2–P5)** [`PARETO-OPTIMAL`]: Harvests $500 on P1 (securing the structural minimum **19.38% infant mortality** and **80.62% P1 survival**), then accumulates to $1,000 ($900 post-payout cushion) on P2–P5. Achieves **$1,540.68 Terminal Funded-Lifecycle Payout EV** ($1,132.40 at 252 sessions) and **38.05% live promotion**.
- **Policy D (Fixed $750 Benchmark)** [`PARETO-OPTIMAL`]: Harvests fixed $750 at $26,500 balance ($650 post-payout cushion). Incurs **27.05% infant mortality**, **72.95% P1 survival**, **41.45% live promotion**, and **$1,382.08 Terminal Funded-Lifecycle Payout EV** ($1,072.19 at 252 sessions). Not dominated in 3D space because A has lower EV, B has higher IM, and C has lower live promotion.
- **Policy C2 (Adaptive Cushion-Aware Dynamic)** [`DOMINATED BY POLICY C`]: Harvests $500 on P1; dynamically harvests $750–$1,000 when cushion $\ge \$1,400$ on P2–P5. While its $650 post-payout cushion after a $750 withdrawal is 100% rulebook-compliant under `Required Cushion = $400 + (Gross Payout - $500)`, it leaves a $250 smaller discretionary safety buffer than Policy C's $900 cushion, resulting in **$1,419.99 Terminal EV** (-$120.69 vs C, $p_{\text{Holm}} = 1.80 \times 10^{-114}$) and **34.53% live promotion** (-3.53 pp vs C, $p_{\text{Holm}} = 3.53 \times 10^{-29}$) with identical **19.38% infant mortality**.

---

## Mathematical Specification & Python Registry

The entire specification is encapsulated in `config/prop_firm_registry.py`:

```python
from config.prop_firm_registry import LUCID_FLEX_25K

# EOD Floor Calculation
floor = LUCID_FLEX_25K.get_eod_floor(peak_balance)

# Remaining Cushion to Floor
cushion = LUCID_FLEX_25K.get_remaining_cushion(balance, peak_balance)

# Payout Eligibility Check
eligible = LUCID_FLEX_25K.is_payout_eligible(
    balance=current_balance,
    profitable_days_count=days_with_ge_100,
    cycle_net_profit=net_profit_this_cycle,
    payouts_completed=total_payouts_so_far,
)

# Payout Calculation
gross_payout, trader_net, post_balance = LUCID_FLEX_25K.calculate_payout(
    balance=current_balance,
    policy="immediate_minimum",  # or "patient_maximum"
)
```

---

## Production Invariant Rules & Failure Modes
1. **EOD trailing floor**: If realized account equity is at or below the active EOD floor, the evaluation is failed. Floor updates only at session close.
2. **Daily loss limit**: After realized session P&L reaches -$600, block new entries; do not clip open or closed trade P&L.
3. **Evaluation consistency (40% base)**: Pass only when total profit >= $1,250 and largest_day / total_profit <= 0.40.
4. **Contract caps**: Enforce Lucid's 20-micro official maximum and this desk's 10-micro internal cap as separate limits.
5. **Safe CPPI / finish-line 1-micro de-lever**: Optional portfolio sizing policy, not a Lucid funded-account rule.
6. **Authoritative evaluation path**: `backtest/lucidflex_eval.py`. Do not quote generic `prop_firm.py` profiles, dashboard-era grids, or legacy M3 JSON as the current LucidFlex result.

---

## Implementation & File Map
- Registry: `config/prop_firm_registry.py`
- Authoritative evaluation simulator: `backtest/lucidflex_eval.py`
- Runner: `scripts/run_lucidflex_eval_v1.py`
- Tests: `tests/test_lucidflex_eval_v1.py`, `tests/test_lucid_flex_rules_integrity.py`
- Corrected artifact: `results/lucidflex_eval_v1_portfolio_comparison.json`
- Legacy M3 artifact (preserved): `results/m3_portfolio_ratchet_simulation.json`

## Cross References
- [Python Prop Firm Registry](../../config/prop_firm_registry.py)
- [Ratchet Sizing & Cushion Protection](../sizing/ratchet-and-cushion.md)
- [Multi-Asset Ensemble Architecture](../strategies/lucid-flex-ensemble.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
- [Demo Parity Engine](../execution/demo-parity-engine.md)
