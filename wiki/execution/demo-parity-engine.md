---
title: "Live Demo Parity Engine & Execution Auditing"
tags:
  - execution
  - forward-demo
  - parity
  - slippage
  - cqg
created: "2026-11-05"
updated: "2026-11-06"
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
The Demo Parity Engine (`backtest/demo_parity_engine.py`) and CQG Broker Execution Synchronizer (`scripts/sync_cqg_executions.py`) form the real-time operational bridge between theoretical strategy models and live broker execution. While backtests assume idealized fills or fixed slippage constants, live trading via CQG and MotiveWave encounters queue latency, orderbook voids, and partial fills.

The parity pipeline supports two complementary ingestion pathways:
1. **Real-Time Study Logging**: MotiveWave Java studies stream order lifecycle tags (`ORDER_SUBMITTED`, `ORDER_FILLED`) into `results/forward_test/motivewave_alerts.log`.
2. **Broker-Authoritative Journal Ingestion**: The CQG WebAPI execution audit trail is ingested directly from MotiveWave's persistent journal (`~/Library/MotiveWave/workspaces/Mota/config/journal.csv`), reconstructed using FIFO lot-matching, reconciled with theoretical signals, and committed to `results/forward_test/demo_trades_ledger.csv`.

## Technical Specification
- **Engine Core**: `backtest/demo_parity_engine.py`
- **Execution Synchronizer**: `scripts/sync_cqg_executions.py`
- **Broker Journal Source**: `~/Library/MotiveWave/workspaces/Mota/config/journal.csv` (CQG WebAPI persistent ledger)
- **Trade History Map**: `~/Library/MotiveWave/workspaces/Mota/config/trade_history.csv`
- **Audit Ledger**: `results/forward_test/demo_trades_ledger.csv`
- **Session Ledger**: `results/forward_test/demo_sessions_ledger.csv`
- **State Store**: `results/forward_test/demo_parity_state.json`
- **HTML Dashboard**: `results/forward_test/demo_parity_dashboard.html`

### Canonical State Store & Fail-Closed Interface
The state interface (`results/forward_test/demo_parity_state.json`) is the single canonical source of truth for prop account risk state:
- **Canonical Filename**: Strictly `demo_parity_state.json`. Any legacy or incorrect filename (`account_state.json`) is rejected with `ORDER_BLOCKED_UNVERIFIED_ACCOUNT`.
- **Configurable Location**: Resolved via `ASYMMETRY_FORWARD_TEST_DIR` or `LUCIDFLEX_FORWARD_TEST_DIR` environment variables, system properties, or relative repo path.
- **Fail-Closed Validation**:
  - Missing file, corrupt JSON, missing required fields, or non-finite numbers (`NaN`, `null`, `Infinity`) immediately cause `verify_and_load_account_state` to return `verified = False` and block order execution.
  - Timestamp staleness check: `updated_at` must be valid ISO-8601 UTC within the last 24 hours. Stale state blocks automated trading.
- **Monotonic High-Water Mark & Locked Floor**:
  - Preserves historical peak balance during drawdowns (does not reset peak down to current balance).
  - Trailing floor locks permanently at $\$25,100$ once peak balance reaches $\ge \$26,100$.

### Broker Journal Ingestion & FIFO Lot-Matching
`scripts/sync_cqg_executions.py` provides automated ingestion with the following architecture:
- **Filtering**: Filters journal records where `Record Type == 'ORDER'` and `Action == 'ORDER_FILLED'`.
- **Symbol Normalization**: Maps CQG contract tickers (e.g. `MESZ26.CQG` -> `MES`, `MNQZ26.CQG` -> `MNQ`, `MGCZ26.CQG` -> `MGC`).
- **FIFO Multi-Lot Queue**: Matches opposite-side orders (BUY vs SELL) chronologically per instrument, accurately handling multi-contract brackets, scale-outs, and partial fills.
- **Strategy & Exit Classification**:
  - `08:30–09:25 ET` on MNQ: `Macro Momentum (08:35)`
  - `09:44–10:15 ET` on MNQ/MES: `VA Breakout (v2.0)`
  - `10:14–11:00 ET` on MGC: `Gold London Fix (H14)`
  - Order type `STP` -> `STOP_LOSS`, `LMT` -> `PROFIT_TARGET`, window close -> `TIME_EXIT`.
- **Deduplication Engine**: Reconstructs trades and verifies against existing entries in `demo_trades_ledger.csv` by date, symbol, direction, entry time, and fill prices.

### Operational CLI Modes
```bash
# List all reconstructed CQG broker trades in terminal table
python scripts/sync_cqg_executions.py --list

# Filter for systematic ensemble strategies only (MES, MNQ, MGC)
python scripts/sync_cqg_executions.py --list --systematic-only --symbols MES,MNQ,MGC

# Sync completed trades into demo_trades_ledger.csv and update dashboard
python scripts/sync_cqg_executions.py --sync --systematic-only --symbols MES,MNQ,MGC

# Real-time watcher daemon tailing journal.csv for instant fill notifications
python scripts/sync_cqg_executions.py --watch
```
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
- **CQG Execution Synchronizer**: `scripts/sync_cqg_executions.py`
- **Alert Watcher**: `scripts/watch_morning_demo_alerts.py`
- **Process Manager**: `scripts/start_morning_watcher.sh`, `scripts/stop_morning_watcher.sh`
- **Output Ledger**: `results/forward_test/demo_trades_ledger.csv`
- **Unit Tests**: `tests/test_cqg_execution_sync.py`, `tests/test_provenance_system.py`, `tests/test_prop_firm_ratchet.py`

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
