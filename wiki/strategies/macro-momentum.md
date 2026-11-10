---
title: "Strategy 2: Pre-Market Macro Momentum (08:35 ET)"
tags:
  - strategy
  - equities
  - mnq
  - macro
  - markov-regimes
created: "2026-11-05"
updated: "2026-11-05"
status: active
strategies:
  - macro_momentum_s2
related_pages:
  - "strategies/lucid-flex-ensemble.md"
  - "strategies/morning-va-breakout.md"
  - "prop_firm/lucid-flex-25k.md"
  - "sizing/ratchet-and-cushion.md"
  - "provenance/provenance-protocol.md"
---

# Strategy 2: Pre-Market Macro Momentum (08:35 ET)

## Executive Summary
Strategy 2 (`macro_momentum_s2`) exploits directional repricing in Micro E-mini Nasdaq-100 (`MNQ`) following 08:30:00 ET Tier-1 economic releases (Non-Farm Payrolls, CPI, PPI, Retail Sales, GDP). Rather than attempting to guess the release or enter into the initial spread explosion at 08:30:00, Strategy 2 waits 5 minutes until 08:35:00 ET for microstructure stabilization.

By coupling 5-minute directional momentum with a 3-state Gaussian Hidden Markov Model (HMM) regime classifier, Strategy 2 participates in macro trend continuation while dynamically halving contract sizing during high-volatility whipsaw regimes.

## Rejected 10:00 window

The 10:05–10:35 Tier-2 window is permanently unable to submit orders. `MacroTenAmOrderGate` returns false for that window, its signal ids, and its 10:35 flatten label. A saved or manually enabled `enable10amWindow` value is ignored. The 08:35 Tier-1 entry, stop, target, flatten, and sizing rules are unchanged. H45 in `wiki/failed_ideas.md` is the rejection record.

## Technical Specification
- **Instrument**: `MNQ` (Micro E-mini Nasdaq-100)
- **Time Window**: 08:35:00 to 09:25:00 ET (Order expiration at 09:25 ET before cash equity open)
- **Macro Catalyst Gate**: Active only on days with scheduled 08:30 ET Tier-1 macroeconomic releases or significant pre-market volume shock ($> 2.0\times$ 20-day median pre-market volume).
- **Entry Logic**:
  - Evaluate 5-minute displacement candle from 08:30:00 to 08:35:00 ET.
  - If displacement $> 1.2\times$ 15-minute ATR: enter in the direction of the displacement bar close relative to the 08:30:00 open.
  - Long: 08:35:00 close $> 08:30:00\text{ open} + \Delta_{\text{thresh}}$.
  - Short: 08:35:00 close $< 08:30:00\text{ open} - \Delta_{\text{thresh}}$.
- **Markov Regime Adaptation**:
  - Regime 0 (Low Vol): Full standard ratchet sizing.
  - Regime 1 (Normal Vol): Full standard ratchet sizing.
  - Regime 2 (High Vol): Dynamic de-leveraging to 0.5x contracts (halve size to 1 micro). Never widen stops (standing rule from Failed Idea #3).
- **Bracket Risk**:
  - Stop Loss: 35.00 index points.
  - Profit Target: 70.00 index points (1:2 Risk/Reward).
  - Trailing Stop: Activate at $+1.2R$ to lock $+0.5R$.

## Empirical Evidence & Provenance
Directly queried from `results/backtest_provenance.db`:

```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : run_canonical_s2_macro_momentum_2021_2026
Strategy     : macro_momentum_s2 — Pre-Market Macro Release Momentum (08:35 ET)
Methodology  : multi_year_walkforward
Date Range   : 2021-01-07 to 2026-10-30 (2423 days)
Data File    : data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet
Data SHA-256 : ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca
Git Commit   : 7d63ca2a3e8
Cost Model   : CQG 1-Tick Adverse Parity | $1.40 RT ($0.70/side micro) [NET]
Metrics      : Trades: 143 | Win%: 48.95% | PF: 1.44 | Net: $4,573.23 | MaxDD: -$1,300.49
Warning Flags: None
────────────────────────────────────────────────────────────────────────────
```

### Step 07 Sensitivity Analysis (The Plateau Principle)
Evaluated across +/-25% shifts (5 steps: -25%, -12.5%, 0%, +12.5%, +25%):
- `target_rr` (base 1.50, range [1.125 .. 1.875]): Stability Ratio **0.99x** | Min PnL: $873.67 | Verdict: `ROBUST_PLATEAU`
- `stop_points` (base 30.0, range [22.5 .. 37.5]): Stability Ratio **1.00x** | Min PnL: $1,981.68 | Verdict: `ROBUST_PLATEAU`
- `min_volume_mult` (base 1.50, range [1.125 .. 1.875]): Stability Ratio **1.00x** | Min PnL: $4,570.17 | Verdict: `ROBUST_PLATEAU`
- Provenance Run ID: `run_plateau_sweep_s2_macro_momentum`
- Chart: `results/parameter_plateau_sweep/plateau_sweep_s2.png`

## Implementation & File Map
- **MotiveWave Java Study**: `src/motivewave/LucidMacroMomentumStudy.java`
- **Backtest Engine**: `backtest/engine.py` (Markov transition and macro filter)
- **Configuration**: `config/backtest_config.py` (Strategy 2 parameter block)
- **Unit Tests**: `tests/test_provenance_system.py`, `tests/test_prop_firm_ratchet.py`

## Invariant Rules & Failure Modes
1. **Rule 1: Force Exit Before Cash Open**: All Strategy 2 positions must be closed by 09:25:00 ET. No open positions may be carried across the 09:30:00 ET cash open.
2. **Rule 2: No Stop Widening**: During high volatility regimes, never widen stops beyond 35.00 points; handle volatility exclusively by de-leveraging contract size.
3. **Rule 3: Single Entry**: Only one entry is allowed per morning macro event. No re-entries after stop hit.

## Cross References
- [Strategy 1: Morning VA Breakout](morning-va-breakout.md)
- [Tri-Asset Ensemble Architecture](lucid-flex-ensemble.md)
- [LucidFlex 25K Compliance](../prop_firm/lucid-flex-25k.md)
- [Ratchet Sizing & Cushion Protection](../sizing/ratchet-and-cushion.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
