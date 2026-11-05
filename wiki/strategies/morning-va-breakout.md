---
title: "Strategy 1: Morning VA Breakout (09:45 ET)"
tags:
  - strategy
  - equities
  - mnq
  - mes
  - value-area
created: "2026-11-05"
updated: "2026-11-05"
status: active
strategies:
  - morning_va_breakout_s1
related_pages:
  - "strategies/lucid-flex-ensemble.md"
  - "prop_firm/lucid-flex-25k.md"
  - "sizing/ratchet-and-cushion.md"
  - "provenance/provenance-protocol.md"
  - "execution/motivewave-integration.md"
---

# Strategy 1: Morning VA Breakout (09:45 ET)

## Executive Summary
Strategy 1 (`morning_va_breakout_s1`) is an intraday breakout strategy designed for Micro E-mini Nasdaq-100 (`MNQ`) and Micro E-mini S&P 500 (`MES`). Operating strictly within the 09:45–10:15 ET opening window, the strategy identifies structural market acceptance outside the prior session's Market Profile Value Area (VAH/VAL) following the initial 15-minute cash equity price discovery.

By conditioning trade execution on rolling GARCH(1,1) volatility target envelopes and non-exhausted intraday expansion runaways, Strategy 1 avoids low-volume liquidity traps while capturing institutional morning trending drives.

## Technical Specification
- **Instrument**: `MNQ` (Micro E-mini Nasdaq-100) / `MES` (Micro E-mini S&P 500)
- **Time Window**: 09:45:00 to 10:15:00 ET (Order cancellation and force flat at 11:15 ET)
- **Entry Logic**:
  - Prior session Value Area High (`VAH`) and Value Area Low (`VAL`) computed from 70% volume distribution of prior RTH session.
  - Signal triggers if the 09:30–09:45 Opening Range accepts and closes outside the prior session VA.
  - Bullish Breakout: 1-minute close $> \text{VAH}$ and close $> \text{OR High}$.
  - Bearish Breakdown: 1-minute close $< \text{VAL}$ and close $< \text{OR Low}$.
- **Volatility Filter**: Point-in-time rolling GARCH(1,1) Model Volatility Target (MVT). Exclude entries if current bar range exceeds 2.5 standard deviations of instantaneous expected volatility (exhaustion spike).
- **Execution**: Limit order placed at the broken level or trailing bid/ask parity with 1-tick adverse slippage modeling.
- **Bracket Risk**:
  - Stop Loss: 28.00 index points (MNQ) / 7.00 index points (MES).
  - Profit Target: 56.00 index points (MNQ) / 14.00 index points (MES) (1:2 Risk/Reward).
  - Trailing Stop: Breakeven activation when unrealized PnL reaches $+1.0R$.

## Empirical Evidence & Provenance
Directly queried from the single canonical provenance database (`results/backtest_provenance.db`):

```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : run_canonical_s1_va_breakout_2021_2026
Strategy     : morning_va_breakout_s1 — Morning VA Breakout (09:45 ET)
Methodology  : multi_year_walkforward
Date Range   : 2021-01-07 to 2026-10-30 (2423 days)
Data File    : data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet
Data SHA-256 : ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca
Git Commit   : 7d63ca2a3e8
Cost Model   : CQG 1-Tick Adverse + Limit Fill Parity | $1.40 RT ($0.70/side micro) [NET]
Metrics      : Trades: 316 | Win%: 56.96% | PF: 1.65 | Net: $8,956.18 | MaxDD: -$1,475.99
Warning Flags: None
────────────────────────────────────────────────────────────────────────────
```

### Step 07 Sensitivity Analysis (The Plateau Principle)
Evaluated across +/-25% shifts (5 steps: -25%, -12.5%, 0%, +12.5%, +25%):
- `target_rr` (base 1.50, range [1.125 .. 1.875]): Stability Ratio **1.00x** | Min PnL: $3,301.54 | Verdict: `ROBUST_PLATEAU`
- `stop_loss_mult` (base 1.00, range [0.75 .. 1.25]): Stability Ratio **1.00x** | Min PnL: $5,521.78 | Verdict: `ROBUST_PLATEAU`
- `garch_mvt_exhaustion_sd` (base 2.50, range [1.875 .. 3.125]): Stability Ratio **1.02x** | Min PnL: $8,446.18 | Verdict: `ROBUST_PLATEAU`
- Provenance Run ID: `run_plateau_sweep_s1_va_breakout`
- Chart: `results/parameter_plateau_sweep/plateau_sweep_s1.png`

## Implementation & File Map
- **MotiveWave Java Study**: `src/motivewave/LucidMorningVABreakoutStudy.java`
- **Backtest Logic**: `backtest/engine.py`, `backtest/demo_parity_engine.py`
- **Configuration**: `config/backtest_config.py` (Strategy 1 parameters)
- **Watcher Daemon**: `scripts/watch_morning_demo_alerts.py`
- **Unit Tests**: `tests/test_provenance_system.py`, `tests/test_garch_volatility.py`

## Invariant Rules & Failure Modes
1. **Rule 1: No Chasing Exhaustion**: If price has already moved $> 3.5\sigma$ GARCH volatility runway prior to 09:45 ET, entry is aborted.
2. **Rule 2: Flat by Mid-Day**: Under no circumstances may an S1 position remain open past 11:30 ET. If neither target nor stop has triggered, the position is closed at market.
3. **Rule 3: Daily Soft Stop**: If cumulative day PnL reaches -$600 across the account, S1 orders are halted immediately.

## Cross References
- [Tri-Asset Ensemble Architecture](lucid-flex-ensemble.md)
- [LucidFlex 25K Compliance](../prop_firm/lucid-flex-25k.md)
- [Ratchet Sizing & Cushion Protection](../sizing/ratchet-and-cushion.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
- [MotiveWave Integration](../execution/motivewave-integration.md)
