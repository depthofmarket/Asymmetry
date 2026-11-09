---
title: "Strategy & Prop-Firm Metrics Dashboard"
tags:
  - quantitative-metrics
  - dashboard
  - prop-firm
  - provenance
created: "2026-11-07"
updated: "2026-11-08"
status: active
strategies:
  - lucid_flex_ensemble
  - morning_va_breakout_s1
  - macro_momentum_s2
  - gold_london_fix_s3
related_pages:
  - "strategies/lucid-flex-ensemble.md"
  - "prop_firm/lucid-flex-25k.md"
  - "provenance/provenance-protocol.md"
---

# Strategy & Prop-Firm Metrics Dashboard

## Executive Summary
`scripts/generate_updated_strategy_prop_dashboard.py` creates a standalone PNG combining the quantitative strategy metric inventory with LucidFlex 25K evaluation and funded-phase model metrics. It writes timestamped outputs under `results/strategy_dashboard_v3/`, leaving existing strategy and prop dashboard images unchanged.

The inventory shows measured/derived values separately from aliases and metrics unsupported by the saved trade ledger. Prop evaluation simulation outcomes are model outputs; funded payout mechanics are explicitly labeled assumptions, not broker-observed results.

## Visual Validation Dashboard (v4)
`scripts/generate_visual_strategy_validation_dashboard.py` creates a separate, timestamped visual report in `results/strategy_dashboard_v4/`. The latest artifact is `visual_validation_dashboard_20261107_172024.png`; it does not overwrite the v3 inventory or pre-existing strategy and prop-firm dashboard images.

The visual report presents:
- Equity against the NQ benchmark with a separate underwater drawdown trace. The $1,000 trailing-loss line is a visual reference only; it is not an exact application of a firm's intraday/EOD rules to the normalized portfolio curve.
- Development/holdout comparison and chronological annual slices. These are not individual walk-forward fold results.
- Saved parameter-plateau sensitivity, trade-order Monte Carlo drawdown reshuffles, execution-cost sensitivity, top-winner truncation, and Markov-regime outcomes.
- Modeled prop evaluation and conditional payout views, with rule omissions and assumptions labeled.
- An evidence-gap panel: no fold-level walk-forward CSV or canonical walk-forward permutation/placebo report was available in `results/`. Those tests are not presented as passed or inferred from the saved evidence.

The dashboard uses the canonical NET trade ledger, saved parameter-plateau results, and reproducible simulation settings. Its simulated prop outcomes are scenario outputs, not live pass probabilities; current firm rules must be verified before use. It does not launch a backtest.

## Distinct Dashboard Sheets (v5)
The v4 timestamped images were successive revisions of a single combined poster, not separate dashboards. To avoid repeating the same panels, `scripts/generate_strategy_dashboard_suite.py` creates three purpose-specific PNGs in `results/strategy_dashboard_v5/`:

1. `01_strategy_performance_20261108_003359.png` — portfolio equity/drawdown, development vs temporal holdout, calendar-year context, and canonical component-strategy comparison.
2. `02_robustness_stress_20261108_003359.png` — parameter plateau, trade-order Monte Carlo drawdown, execution-friction and top-winner truncation sensitivity, and Markov-regime outcomes. It labels missing fold-level and permutation/placebo evidence.
3. `03_prop_firm_risk_20261108_003359.png` — modeled pass/breach/open outcomes, additional slippage sensitivity, evaluation duration, and conditional payout ladder, with rule assumptions and limitations.

The sheets share the canonical NET ledger provenance, but have different questions and chart content. They are timestamped and generated alongside the older v3/v4 images; those older comparison files are preserved.

## Technical Specification
- The strategy table covers 143 metric fields across return, risk-adjusted performance, drawdown, tail risk, trade edge, direction, statistical significance, selection bias, sizing, exposure, cadence, calendar periodicity, and stability.
- Daily risk metrics use the full exchange-session calendar, including flat sessions. Trade P&L is taken from the saved canonical NET ledger.
- Duplicate aliases do not claim independent evidence. Missing excursion, execution, and margin inputs are displayed as `NOT MEASURED`.
- The prop simulation uses a 10,000-path, 10-session block bootstrap with a 750-session evaluation horizon and fixed seed. The funded phase is conditional on evaluation pass and uses the payout assumptions shown on the image.
- The simulator does not enforce the 40% consistency cap or the firm contract cap. Verify live rule terms before using its funded estimates.

## Empirical Evidence & Provenance
The PNG is derived from the canonical saved baseline trade dataset. No backtest was run. A new prop bootstrap simulation is run when the generator executes; its model settings and the distinction from observed execution are printed in the PNG.

```text
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
Run IDs      : run_canonical_lucid_flex_ensemble_2021_2026;
               run_canonical_s1_va_breakout_2021_2026;
               run_canonical_s2_macro_momentum_2021_2026;
               run_canonical_s3_gold_london_fix_2021_2026
Methodology  : Multi-year walk-forward source ledger; derived quantitative metrics
Date Range   : 2021-01-07 to 2026-10-30 (2423 calendar days)
Data File    : data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet
Data SHA-256 : ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca
Git Commit   : bfff4aac09
Cost Model   : CQG/COMEX adverse execution and $1.40 RT micro commission [NET]
Warnings     : None on the verified canonical strategy runs; prop payout terms are assumptions
```

## Implementation & File Map
- Generator: `scripts/generate_updated_strategy_prop_dashboard.py`
- Output directory: `results/strategy_dashboard_v3/`
- Visual generator: `scripts/generate_visual_strategy_validation_dashboard.py`
- Visual output directory: `results/strategy_dashboard_v4/`
- Three-sheet generator: `scripts/generate_strategy_dashboard_suite.py`
- Three-sheet output directory: `results/strategy_dashboard_v5/`
- Strategy analytics: `backtest/dashboard_analytics.py`, `backtest/metrics.py`
- Prop simulation: `backtest/dashboard_analytics.py`
- Existing comparison images remain under `results/strategy_dashboard/`, `results/strategy_dashboard_v2/`, and `results/prop_firm_dashboard/`.

## Invariant Rules & Failure Modes
1. Do not treat aliases as independent measures or unsupported zero-filled fields as observed values.
2. Do not represent simulated evaluation outcomes as live pass rates or modeled payouts as actual firm payouts.
3. Keep the 40% consistency cap and contract cap visibly identified as unenforced in this simulator.
4. Preserve provenance, net execution-cost context, date range, and dataset hash with the rendered strategy metrics.

## Cross References
- [Tri-Asset Multi-Strategy Ensemble Architecture](lucid-flex-ensemble.md)
- [LucidFlex 25K Rulebook & Compliance Architecture](../prop_firm/lucid-flex-25k.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
