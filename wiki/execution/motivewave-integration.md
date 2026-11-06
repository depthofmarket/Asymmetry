---
title: "MotiveWave Custom Studies & Java Execution Integration"
tags:
  - execution
  - motivewave
  - java
  - cqg
  - broker-bridge
created: "2026-11-05"
updated: "2026-11-06"
status: active
strategies:
  - morning_va_breakout_s1
  - macro_momentum_s2
  - gold_london_fix_s3
  - lucid_flex_ensemble
related_pages:
  - "strategies/morning-va-breakout.md"
  - "strategies/macro-momentum.md"
  - "strategies/gold-london-fix.md"
  - "strategies/lucid-flex-ensemble.md"
  - "execution/demo-parity-engine.md"
  - "provenance/provenance-protocol.md"
---

# MotiveWave Custom Studies & Java Execution Integration

## Executive Summary
Real-time trade execution and charting in this repository are powered by custom Java studies deployed within the MotiveWave desktop platform. MotiveWave connects directly to institutional market data and execution feeds via the CQG broker bridge.

To bridge the gap between high-level Python econometric research and real-time execution, three core custom Java studies implement strict non-repainting execution tags, trailing prop-firm floor visualizers, point-in-time GARCH envelopes, and automated export hooks that sync live fills with the Python demo parity engine.

## Technical Specification

### Custom Java Studies in `src/motivewave/`
1. **`LucidMorningVABreakoutStudy.java`** (52 KB):
   - Computes rolling 70% Value Area (VAH/VAL) from prior RTH session.
   - Overlays GARCH(1,1) Model Volatility Target (MVT 0) and standard deviation envelope bands.
   - Evaluates opening range breakout acceptance at 09:45:00 ET.
   - Dynamic sizing via `resolveContracts(OrderContext ctx, int fallbackContracts)`.
   - Emits non-repainting live entry, stop loss, and profit target markers.
2. **`LucidMacroMomentumStudy.java`** (56 KB):
   - Monitors 08:30:00 ET economic release displacement.
   - Evaluates 5-minute displacement bar at 08:35:00 ET.
   - Incorporates Markov regime indicator to signal high-volatility sizing reductions.
   - Dynamic sizing via `resolveContracts(OrderContext ctx, int fallbackContracts)`.
3. **`LucidGoldFixBreakoutStudy.java`** (33 KB):
   - Calculates 10:00–10:15 ET LBMA PM fixing price range on COMEX `MGC`.
   - Triggers long-only structural breakout signals upon 10:15:00 ET auction resolution.
   - Dynamic sizing via `resolveContracts(OrderContext ctx, int fallbackContracts)`.

### Safe CPPI & Dynamic Account Sizing Resolution (`resolveContracts`)
All three Java studies integrate native dynamic contract resolution pulling real-time account equity (`cash + realizedPnL + unrealizedPnL`) directly from the MotiveWave `OrderContext`:
- **Balance & Floor Calculation**: High-water mark trailing floor ($hwm - \$1,000$, locked at $\$25,100$ when $hwm \ge \$26,100$).
- **Trailing Cushion**: $\text{cushion} = \text{balance} - \text{floor}$.
- **Finish-Line Shield**: If net profit $\ge +\$1,150.00$, lock to **1 micro** to guarantee passing evaluation.
- **Floor Buffer De-lever**: If trailing cushion $<\$400.00$, de-lever to **1 micro** (infant mortality avoidance).
- **Compounding Tier 3**: If net profit $\ge +\$550.00$, size **4 micros**.
- **Compounding Tier 2**: If net profit $\ge +\$200.00$, size **3 micros**.
- **Base Tier 1**: Size **2 micros**.
- **Daily Loss Circuit Breaker**: Hard-coded soft stop updated to **-\$600.00** daily PnL threshold.

### Real-Time Alert & File Export Protocol
- Each Java study formats triggered trades and bracket orders into structured alert lines written to a local export directory (`results/forward_test/motivewave_alerts.log`).
- Alerts include: `TIMESTAMP`, `STUDY_ID`, `SYMBOL`, `ACTION`, `PRICE`, `STOP_LOSS`, `TAKE_PROFIT`, `CONTRACTS`, `REASON`.
- Python monitoring daemons parse this log in real time to reconcile MotiveWave study intent against CQG broker order receipts.

## Empirical Evidence & Provenance
Verified against MotiveWave trade exports reconciled into `results/backtest_provenance.db`:

```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : run_canonical_forward_demo_live_parity
Strategy     : lucid_flex_forward_demo — Forward Demo Parity Ledger
Methodology  : forward_demo
Date Range   : 2026-10-30 to 2026-10-30 (8 days)
Data File    : results/forward_test/demo_trades_ledger.csv
Data SHA-256 : 696515c0e649bc3371ea13e9a4f66a7071720d297ffb12db9845d4a13824bbcd
Git Commit   : 7d63ca2a3e8
Cost Model   : CQG Live Fill Parity [NET]
Metrics      : Trades: 1 | Win%: 100.00% | PF: 99.00 | Net: $144.70 | MaxDD: $0.00
Warning Flags: LOW_SAMPLE_SIZE, OUTLIER_DOMINANCE, SHORT_EVALUATION_WINDOW
────────────────────────────────────────────────────────────────────────────
```

## Implementation & File Map
- **Strategy 1 Study**: `src/motivewave/LucidMorningVABreakoutStudy.java`
- **Strategy 2 Study**: `src/motivewave/LucidMacroMomentumStudy.java`
- **Strategy 3 Study**: `src/motivewave/LucidGoldFixBreakoutStudy.java`
- **Bytecode & Context Recovery**: `backtest/motivewave_context.py`, `backtest/motivewave_ead.py`
- **Watcher Daemon**: `scripts/watch_morning_demo_alerts.py`, `scripts/start_morning_watcher.sh`

## Invariant Rules & Failure Modes
1. **Rule 1: Non-Repainting Calculation**: Java study indicators must compute strictly on closed bars or locked historical states. Under no circumstances may an indicator re-paint past entry signals based on subsequent price action.
2. **Rule 2: Heartbeat Verification**: If the MotiveWave alert log timestamp falls $> 60$ seconds behind wall-clock time during market hours, the watcher daemon flags an execution desynchronization alarm.
3. **Rule 3: Bracket Order Coupling**: Every market entry signal emitted by the study must include linked stop-loss and take-profit parameters; un-bracketed entry intents are rejected.

## Cross References
- [Demo Parity Engine](demo-parity-engine.md)
- [Strategy 1: Morning VA Breakout](../strategies/morning-va-breakout.md)
- [Strategy 2: Pre-Market Macro Momentum](../strategies/macro-momentum.md)
- [Strategy 3: Gold London Fix Breakout](../strategies/gold-london-fix.md)
- [Tri-Asset Ensemble Architecture](../strategies/lucid-flex-ensemble.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
