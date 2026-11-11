---
title: "Multi-Asset Ensemble & 5-Strategy Expansion Architecture"
tags:
  - strategy
  - ensemble
  - portfolio
  - mnq
  - mes
  - mgc
  - mcl
created: "2026-11-05"
updated: "2026-11-11"
status: active
strategies:
  - lucid_flex_ensemble
  - morning_va_breakout_s1
  - macro_momentum_s2
  - gold_london_fix_s3
  - asian_evening_reversion_s4
  - crude_rth_expansion_s5
related_pages:
  - "strategies/morning-va-breakout.md"
  - "strategies/macro-momentum.md"
  - "strategies/gold-london-fix.md"
  - "strategies/asian-evening-reversion.md"
  - "strategies/crude-rth-expansion.md"
  - "prop_firm/lucid-flex-25k.md"
  - "sizing/ratchet-and-cushion.md"
  - "provenance/provenance-protocol.md"
---

# Multi-Asset Ensemble & 5-Strategy Expansion Architecture

## Executive Summary
The LucidFlex Ensemble (`lucid_flex_ensemble`) is the core multi-strategy quantitative portfolio of the repository, engineered specifically for the **LucidFlex 25K** prop firm evaluation and funded account structure (**$39 One-Time Payment [OTP] — zero monthly rebill, no time expiration**, $1,250 profit target, $1,000 EOD trailing drawdown locking permanently at $25,100 once balance reaches $26,100, -$600 daily soft stop, and 40% / $500 daily consistency guideline).

The architecture comprises:
- **3 Frozen Production Baseline Strategies (`StrategyTier.BASELINE`)**:
  1. **Strategy 2 (`macro_momentum_s2`, 08:35 ET on `MNQ`)**: Pre-market directional momentum following 08:30 ET Tier-1 macro releases (CPI/NFP/PPI/Retail Sales).
  2. **Strategy 1 (`morning_va_breakout_s1`, 09:45 ET on `MNQ`/`MES`)**: Opening Range acceptance outside prior session Value Area with GARCH MVT exhaustion filter.
  3. **Strategy 3 (`gold_london_fix_s3`, 10:15 ET on `MGC`)**: Post-LBMA PM Fix bullion auction clearing breakout on COMEX Micro Gold.
- **2 Verified Orthogonal Expansion Candidates (`StrategyTier.CANDIDATE`)**:
  4. **Candidate S4 (`asian_evening_reversion_s4`, 21:00–23:00 ET / 23:00–01:00 UTC-3 on `MNQ`)**: Tokyo cash open institutional liquidity rebalancing fading overextended 18:00–21:14 ET Globex drift upon 21:00–21:14 ET opening candle rejection, with mandatory 23:00 ET flatten.
  5. **Candidate S5 (`crude_rth_expansion_s5`, 10:15–12:30 ET on `MCL`)**: Post-LBMA Gold PM Fix / morning US survey consolidation breakout (`09:30–10:14 ET` box) on Micro WTI Crude Oil into the 11:30 ET European close.

---

## 5-Strategy Portfolio Coordination & Pareto Ratchet Risk Architecture

All five strategies are strictly governed by the **Pareto Anti-Martingale Ratchet (`2 -> 3 -> 4` micros)** and **Safe CPPI cushion protection** (`wiki/sizing/ratchet-and-cushion.md`). Static 1-micro sizing is strictly prohibited.

### Complete 5-Strategy Pareto Ratchet Risk & Reward Table (Net of Slippage & Commissions)

| # | Strategy ID | Tier | Asset | Active Window (ET / UTC-3) | Base Stop / Target (1 Micro) | Tier 1: 2 Micros (`$0 to +$199`) Risk / Target | Tier 2: 3 Micros (`+$200 to +$549`) Risk / Target | Tier 3: 4 Micros (`+$550 to +$1,149`) Risk / Target | Shield / Safe CPPI (1 Micro) |
| :- | :--- | :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| **S2** | `macro_momentum_s2` | `BASELINE` | `MNQ` | `08:35–09:25 ET` (`10:35–11:25`) | `20.0 pt / 30.0 pt` (`1.5R`) | `-$82.80 / +$117.20` | `-$124.20 / +$175.80` | `-$165.60 / +$234.40` | `-$41.40 / +$58.60` |
| **S1** | `morning_va_breakout_s1` | `BASELINE` | `MNQ/MES` | `09:45–11:30 ET` (`11:45–13:30`) | `15.0 pt / 22.5 pt` (`1.5R`) | `-$115.90 / +$173.84` | `-$173.85 / +$260.76` | `-$231.80 / +$347.68` | `-$57.95 / +$86.92` |
| **S3** | `gold_london_fix_s3` | `BASELINE` | `MGC` | `10:15–11:45 ET` (`12:15–13:45`) | `4.50 pt / 11.25 pt` (`2.5R`) | `-$92.80 / +$222.20` | `-$139.20 / +$333.30` | `-$185.60 / +$444.40` | `-$46.40 / +$111.10` |
| **S5** | `crude_rth_expansion_s5` | `CANDIDATE` | `MCL` | `10:15–12:30 ET` (`12:15–14:30`) | `$0.45 / $0.90` (`2.0R`) | `-$103.00 / +$169.00` | `-$154.50 / +$253.50` | `-$206.00 / +$338.00` | `-$51.50 / +$84.50` |
| **S4** | `asian_evening_reversion_s4` | `CANDIDATE` | `MNQ` | `21:00–23:00 ET` (`23:00–01:00`) | `35.0 pt / 37.5 pt` (`1.07R`) | `-$144.80 / +$146.20` | `-$217.20 / +$219.30` | `-$289.60 / +$292.40` | `-$72.40 / +$73.10` |

---

## Daily-return correlation (zero-padded weekday matrix — not independence)

The matrix below is copied from the **legacy M3 JSON** (`results/m3_portfolio_ratchet_simulation.json`). It is Pearson correlation of **1-micro daily P&L on all weekdays 2021-01-04 to 2026-10-30**, including days with no trades (zeros). It is **not** evidence of statistical independence. Pairwise days on which both strategies actually traded are few (typically n = 3–17).

| Strategy | S1 | S2 | S3 | S4 | S5 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **S1** | `1.0000` | `-0.0481` | `-0.0599` | `-0.0081` | `+0.0361` |
| **S2** | `-0.0481` | `1.0000` | `-0.0325` | `+0.0090` | `+0.0579` |
| **S3** | `-0.0599` | `-0.0325` | `1.0000` | `+0.0223` | `-0.0369` |
| **S4** | `-0.0081` | `+0.0090` | `+0.0223` | `1.0000` | `+0.0108` |
| **S5** | `+0.0361` | `+0.0579` | `-0.0369` | `+0.0108` | `1.0000` |

Max |ρ| on that zero-padded weekday matrix is `0.0599`. Do not treat `|ρ| ≪ 0.20` as a portfolio-construction proof.

---

## LucidFlex 25K evaluation (authoritative vs legacy)

Authoritative causal simulator: `backtest/lucidflex_eval.py` (`lucidflex_eval_v1`), artifact `results/lucidflex_eval_v1_portfolio_comparison.json`.

Data SHA-256 `84179526c91e3f04972ec4f75347328c3d3ff5853298692d47cb9a82b09d9bd2` (748 frozen trades). Equity model: **realized-close only** (S1–S3 have no intraday marks). Not an execution-validated backtest. Not a lifetime pass probability while unresolved paths remain.

S1 paired MNQ/MES legs share one pre-entry ratchet tier (tier 2 = 1+1, tier 3 = 1+2, tier 4 = 2+2). DLL blocks later entries without clipping P&L.

| Quantity (10,000 paths, seed 42, NQ 09:30 calendar) | S1–S3 | S1–S5 |
| :--- | :---: | :---: |
| **252-session pass / fail / unresolved** | 6904 / 1861 / 1235 | 7299 / 1946 / 755 |
| **252-session pass ÷ all paths** | 69.04% | 72.99% |
| **252-session fail ÷ all paths** | 18.61% | 19.46% |
| **252-session unresolved ÷ all paths** | 12.35% | 7.55% |
| **252-session pass ÷ resolved** | 78.77% | 78.95% |
| **260-session pass / fail / unresolved** | 6965 / 1887 / 1148 | 7351 / 1965 / 684 |
| **750-session pass / fail / unresolved** | 7711 / 2283 / 6 | 7834 / 2166 / 0 |
| **750-session pass ÷ all paths** | 77.11% | 78.34% |
| **OTP $ per funded (resolved attempts only, 252s)** | $49.51 | $49.40 |
| **Historical sequential pass / fail / unresolved** | 9 / 4 / 1 | 12 / 3 / 1 |
| **Historical median sessions among passes** | 81.0 | 89.5 |

Never call `100 − pass÷all` a bust rate. Unresolved paths are still active (no evaluation time limit) and are not a second $39 ticket.

```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Simulator    : lucidflex_eval_v1 1.0.0 (backtest/lucidflex_eval.py)
Artifact     : results/lucidflex_eval_v1_portfolio_comparison.json
Methodology  : Causal event eval; NQ 09:30 calendar; realized-close equity
Date Range   : 2021-01-04 to 2026-10-30
Data File    : data/processed/unified_five_strategy_portfolio_trades_2021_2026.parquet
Data SHA-256 : 84179526c91e3f04972ec4f75347328c3d3ff5853298692d47cb9a82b09d9bd2
Seed/Horizon : 42 / 252, 260, 750 sessions (censored; not lifetime)
Cost Model   : Frozen ledger unit_micro_pnl (NET as stored)
Warning Flags: REALIZED_CLOSE_ONLY, NOT_EXECUTION_VALIDATED, HORIZON_CENSORED
────────────────────────────────────────────────────────────────────────────
```

### Legacy M3 artifact (do not restate as current)

`results/m3_portfolio_ratchet_simulation.json` (SHA-256 `11410935d0b14f0d422c82fb4a753e7cdd79788eb960f15d02681bcb38267de2`) is a **prior-generation** simulator. Independent replay: 5-strat 7279 pass / 1983 fail / 738 unresolved (72.79% / 19.83% / 7.38%); 3-strat 6918 / 1950 / 1132 (69.18% / 19.50% / 11.32%). Wiki previously labeled 30.82% / 27.21% as “bust”; those figures were `100 − pass` and are **not** fail rates.

### Distinct sizing-grid experiment (also not M3)

`results/sizing_cushion_optimization/evaluation_pareto_frontier.csv` Balanced Champion `(T2=$100, T3=$600)` **72.24%** pass at 750 sessions is `dashboard_analytics.run_evaluation`, not `lucidflex_eval_v1` and not legacy M3 72.79%.

---

## Empirical Evidence & Provenance (3-Strategy Production Baseline)
Directly queried from `results/backtest_provenance.db`:

```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : run_canonical_lucid_flex_ensemble_2021_2026
Strategy     : lucid_flex_ensemble — LucidFlex 25K Multi-Strategy Ensemble
Strategy Tier: BASELINE
Methodology  : MULTI_YEAR_WALKFORWARD
Date Range   : 2021-01-07 to 2026-10-30 (2423 days)
Data File    : data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet
Data SHA-256 : ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca
Git Commit   : bfff4aac09
Bundle (.obtf): results/bundles/run_canonical_lucid_flex_ensemble_2021_2026.obtf
Cost Model   : Multi-Asset CQG Adverse Realism | $1.40 RT ($0.70/side micro) [NET (Includes slippage & comms)]
Core Metrics : Trades: 543 | Win%: 55.06% | PF: 1.56 | Net: $14,916.04 | MaxDD: -$1,511.51
Risk Metrics : Sortino: 2.22 | Calmar: 1.03 | Omega: 1.63 | CVaR95: $178.25 | Ulcer: 1.06% | Half-Kelly: 0.099
Warning Flags:
None (Clean Run)
────────────────────────────────────────────────────────────────────────────
```

## Implementation & File Map
- **3-Strategy Baseline Parquet**: `data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet`
- **Candidate Strategy Engines**:
  - `strategies/asian_evening_reversion_s4.py` (`run_canonical_s4_asian_evening_reversion_2021_2026`)
  - `strategies/crude_rth_expansion_s5.py` (`run_canonical_s5_crude_rth_expansion_2021_2026`)
- **Authoritative LucidFlex 25K evaluator**: `backtest/lucidflex_eval.py` / `scripts/run_lucidflex_eval_v1.py` (`results/lucidflex_eval_v1_portfolio_comparison.json`)
- **Legacy M3 (preserved, not source of truth)**: `scripts/run_m3_portfolio_ratchet_and_correlations.py` (`results/m3_portfolio_ratchet_simulation.json`)
- **MotiveWave Production Studies**: `src/motivewave/`
  - `LucidMorningVABreakoutStudy.java` (S1)
  - `LucidMacroMomentumStudy.java` (S2)
  - `LucidGoldFixBreakoutStudy.java` (S3)

## Cross References
- [Strategy 1: Morning VA Breakout](morning-va-breakout.md)
- [Strategy 2: Pre-Market Macro Momentum](macro-momentum.md)
- [Strategy 3: Gold London Fix Breakout](gold-london-fix.md)
- [Candidate Strategy 4: Asian Evening Reversion](asian-evening-reversion.md)
- [Candidate Strategy 5: Crude Oil Post-Fix Range Expansion](crude-rth-expansion.md)
- [LucidFlex 25K Compliance](../prop_firm/lucid-flex-25k.md)
- [Ratchet Sizing & Cushion Protection](../sizing/ratchet-and-cushion.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
