---
title: "Live Demo Parity Engine & Execution Auditing"
tags:
  - execution
  - forward-demo
  - parity
  - slippage
  - cqg
created: "2026-11-05"
updated: "2026-11-05"
status: active
strategies:
  - lucid_flex_forward_demo
  - lucid_flex_ensemble
related_pages:
  - "execution/motivewave-integration.md"
  - "strategies/lucid-flex-ensemble.md"
  - "prop_firm/lucid-flex-25k.md"
  - "sizing/ratchet-and-cushion.md"
  - "provenance/provenance-protocol.md"
---

# Live Demo Parity Engine & Execution Auditing

## Executive Summary
The Demo Parity Engine (`backtest/demo_parity_engine.py`) is the real-time operational bridge between simulation assumptions and live broker execution. While backtests typically assume idealized fills or fixed slippage constants, live trading via CQG and MotiveWave encounters queue latency, orderbook voids, and partial fills.

The parity engine ingests live trade signals from MotiveWave alerts and matches them against CQG fill confirmations. It computes tick-level slippage drag, updates the active LucidFlex account balance and trailing floor, evaluates compliance shields, and records trades to the audited demo ledger (`results/forward_test/demo_trades_ledger.csv`).

## Technical Specification
- **Engine Core**: `backtest/demo_parity_engine.py`
- **Audit Ledger**: `results/forward_test/demo_trades_ledger.csv`
- **Signal Ingestion**: Real-time tailing of MotiveWave export alerts.
- **Slippage Reconciliation**:
  $$\text{Slippage (ticks)} = \frac{|\text{Fill Price} - \text{Signal Price}|}{\text{Tick Size}}$$
  $$\text{Adverse Drag (\%)} = \frac{\text{Actual PnL} - \text{Theoretical PnL}}{\text{Theoretical PnL}}$$
- **Active Prop Account State Machine**:
  - Maintains starting balance ($25,000.00).
  - Trailing floor tracking: floor tracks EOD closed balance up to $25,100 peak lock at $26,100.
  - Soft stop monitor: halts session orders if net intraday loss $\le -\$600.00$.
- **Integrated Sizing Shields**:
  - **Finish-Line Shield**: If profit $\ge +\$1,150.00$, forces contracts to 1 micro.
  - **Defensive Cushion De-lever**: If cushion ($bal - floor$) $< \$500.00$, reduces contracts to 1 micro.
  - **Low Volatility Halving**: If rolling GARCH(1,1) volatility $< 0.898\%$, halves standard sizing.

## Empirical Evidence & Provenance
Verified against live forward demo execution in `results/backtest_provenance.db`:

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

*Note*: Because this forward test represents live forward demo paper trading initiated on 2026-10-30, it appropriately carries the mandatory provenance warning flags `LOW_SAMPLE_SIZE` ($N=1 < 30$), `OUTLIER_DOMINANCE` (top trade 100%), and `SHORT_EVALUATION_WINDOW` (8 days $< 60$).

## Implementation & File Map
- **Parity Engine**: `backtest/demo_parity_engine.py`
- **Alert Watcher**: `scripts/watch_morning_demo_alerts.py`
- **Process Manager**: `scripts/start_morning_watcher.sh`, `scripts/stop_morning_watcher.sh`
- **Output Ledger**: `results/forward_test/demo_trades_ledger.csv`
- **Unit Tests**: `tests/test_provenance_system.py`, `tests/test_prop_firm_ratchet.py`

## Invariant Rules & Failure Modes
1. **Rule 1: Fail-Safe Ledger Persistence**: Every completed trade fill must be immediately appended to `results/forward_test/demo_trades_ledger.csv` and auto-recorded into `results/backtest_provenance.db`.
2. **Rule 2: Slippage Alarm**: If adverse execution slippage exceeds 3 ticks on Micro Nasdaq (`MNQ`) or 2 ticks on Micro Gold (`MGC`), an execution alert is raised.
3. **Rule 3: Non-Overwriting Audit**: Historical trade entries in `demo_trades_ledger.csv` are strictly immutable and append-only.

## Cross References
- [MotiveWave Custom Studies Integration](motivewave-integration.md)
- [Tri-Asset Ensemble Architecture](../strategies/lucid-flex-ensemble.md)
- [LucidFlex 25K Compliance](../prop_firm/lucid-flex-25k.md)
- [Ratchet Sizing & Cushion Protection](../sizing/ratchet-and-cushion.md)
- [Quantitative Provenance Protocol](../provenance/provenance-protocol.md)
