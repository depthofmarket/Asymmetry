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
updated: "2026-11-08"
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

## Empirical $5 \times 5$ Daily Return Correlation Matrix (2021–2026)

Computed across **1,515 active trading sessions** (`2021-01-04` to `2026-10-30`, saved in `results/m3_portfolio_ratchet_simulation.json`):

| Strategy | `morning_va_breakout_s1` | `macro_momentum_s2` | `gold_london_fix_s3` | `asian_evening_reversion_s4` | `crude_rth_expansion_s5` |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **`morning_va_breakout_s1` (S1)** | `1.0000` | `-0.0119` | `-0.0599` | `-0.0081` | `+0.0361` |
| **`macro_momentum_s2` (S2)** | `-0.0119` | `1.0000` | `+0.0383` | `+0.0090` | `+0.0579` |
| **`gold_london_fix_s3` (S3)** | `-0.0599` | `+0.0383` | `1.0000` | `+0.0223` | `-0.0369` |
| **`asian_evening_reversion_s4` (S4)** | `-0.0081` | `+0.0090` | `+0.0223` | `1.0000` | `+0.0108` |
| **`crude_rth_expansion_s5` (S5)** | `+0.0361` | `+0.0579` | `-0.0369` | `+0.0108` | `1.0000` |

- **Maximum Absolute Pairwise Correlation**: $|\rho|_{\max} = 0.0599 \ll 0.20$ (strictly orthogonal across all 10 strategy pairs).

---

## LucidFlex 25K Evaluation Velocity & 10,000-Path Monte Carlo Comparison

Simulated under exact LucidFlex 25K rules (`$1,250` profit target, `$1,000` EOD trailing drawdown locking at `$25,100` once balance hits `$26,100`, `-$600` daily soft stop, `40%` consistency cap, `$39` One-Time Payment [OTP] with **zero monthly rebill**, and Pareto Anti-Martingale Ratchet `2 -> 3 -> 4` micros) via `scripts/run_m3_portfolio_ratchet_and_correlations.py` (`results/m3_portfolio_ratchet_simulation.json`):

| Evaluation Metric | 3-Strategy Baseline (`S1 + S2 + S3`) | 5-Strategy Expanded (`S1 + S2 + S3 + S4 + S5`) | Expansion Delta ($\Delta$) |
| :--- | :---: | :---: | :---: |
| **Total Verified Trades (2021–2026)** | `543` (`93.6/yr`) | `748` (`129.0/yr`) | **`+205 trades (+37.8%)`** |
| **Active Trading Days (2021–2026)** | `358 days` | `512 days` | **`+154 active days (+43.0%)`** |
| **Historical Sequential Campaigns Passed** | `8 / 10` (`80.0%`) | `12 / 15` (`80.0%`) | **`+4 passed evals (+50.0% volume)`** |
| **Historical Median Calendar Days to Pass** | `142.5 calendar days` | `98.0 calendar days` | **`-44.5 calendar days faster (-31.2%)`** |
| **10,000-Path Monte Carlo Pass Rate** | **`69.18%`** | **`72.79%`** | **`+3.61 pp higher pass rate`** |
| **10,000-Path Monte Carlo Bust Rate** | `30.82%` | `27.21%` | **`-3.61 pp lower bust rate`** |
| **MC Median Exchange Sessions to Pass** | `82.0 sessions` (`21.0` active days) | `75.0 sessions` (`27.0` active days) | **`-7.0 exchange sessions faster`** |
| **MC Median Max Drawdown** | `-$684.92` | `-$691.30` | `+$6.38` (well inside `$1,000` limit) |
| **Expected OTP Cost per Funded Account ($39 OTP, $0 Rebill)** | **`$56.37`** (`1.45` attempts) | **`$53.58`** (`1.37` attempts) | **`-$2.79 cheaper per funded account`** |

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
- **5-Strategy Pareto Ratchet & Monte Carlo Engine**: `scripts/run_m3_portfolio_ratchet_and_correlations.py` (`results/m3_portfolio_ratchet_simulation.json`)
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
