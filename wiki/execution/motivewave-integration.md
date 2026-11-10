---
title: "MotiveWave Custom Studies & Java Execution Integration"
tags:
  - execution
  - motivewave
  - java
  - cqg
  - broker-bridge
created: "2026-11-05"
updated: "2026-11-10"
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
1. **`LucidMorningVABreakoutStudy.java`** (Production Baseline S1):
   - Computes rolling 70% Value Area (VAH/VAL) from prior RTH session.
   - Overlays GARCH(1,1) Model Volatility Target (MVT 0) and standard deviation envelope bands.
   - Evaluates opening range breakout acceptance at 09:45:00 ET.
   - Dynamic sizing via `resolveContracts(OrderContext ctx, int fallbackContracts)`.
   - Emits non-repainting live entry, stop loss, and profit target markers.
2. **`LucidMacroMomentumStudy.java`** (Production Baseline S2):
   - Monitors 08:30:00 ET economic release displacement.
   - Evaluates 5-minute displacement bar at 08:35:00 ET.
   - Dynamic sizing via `resolveContracts(OrderContext ctx, int fallbackContracts)`.
3. **`LucidGoldFixBreakoutStudy.java`** (Production Baseline S3):
   - Calculates 10:00–10:15 ET LBMA PM fixing price range on COMEX `MGC`.
   - Triggers long-only structural breakout signals upon 10:15:00 ET auction resolution.
   - Dynamic sizing via `resolveContracts(OrderContext ctx, int fallbackContracts)`.
4. **`LucidAsianEveningReversionStudy.java`** (Candidate S4):
   - Evaluates Tokyo session open liquidity sweep and mean reversion (21:00–23:00 ET) on MES/MNQ.
   - Candidate execution governance: automated execution defaults to `false` (`autoEntry = false`, `DEFAULT_LIVE_AUTOTRADE = false`).
   - Requires completed 21:14 opening-range candle (`series.isBarComplete(index)`) before signal confirmation for 21:15 entry.
   - Modifies working broker stop in-place via `setAdjStopPrice` + `submitOrders` at +1R breakeven trigger.
   - Re-anchors bracket stop and target distances from actual average fill price in `onOrderFilled`.
5. **`LucidCrudeRthExpansionStudy.java`** (Candidate S5):
   - Evaluates post-European-fixing range expansion on Micro WTI Crude Oil (MCL / CME NYMEX).
   - Candidate execution governance: automated execution defaults to `false` (`autoEntry = false`, `DEFAULT_LIVE_AUTOTRADE = false`).
   - Verifies 09:30–10:14 range box and 10:15–11:15 breakout strictly on completed candles (`series.isBarComplete(index)`).
   - In-place working stop modification to breakeven (+2 ticks) at +1R excursion without cancelling working brackets.
   - Mandatory 12:30 ET session flatten and EIA Wednesday inventory report filter.

### Safe CPPI & Dynamic Account Sizing Resolution (`resolveContracts`)
All five Java studies integrate native dynamic contract resolution pulling real-time account equity (`cash + realizedPnL + unrealizedPnL`) directly from the MotiveWave `OrderContext`, while strictly enforcing the canonical daemon recommendation as an unbreakable ceiling:
- **Canonical Daemon Risk Recommendation Ceiling**: The executable contract count is capped by `riskState.recommendedMicros`. Upstream risk decisions, pair-split allocations, or emergency de-escalations can never be inflated by local study sizing tiers.
- **Upstream Risk Budget Ceiling**: Sizing honors `fallbackContracts` as a hard upper bound: `maxAllowed = Math.min(riskState.recommendedMicros, fallbackContracts)`.
- **Balance & Floor Calculation**: High-water mark trailing floor ($hwm - \$1,000$, locked permanently at $\$25,100$ when $hwm \ge \$26,100$).
- **Trailing Cushion**: $\text{cushion} = \text{balance} - \text{floor}$.
- **Finish-Line Shield**: If net profit $\ge +\$1,150.00$ or `riskState.finishLineShield == true`, lock to **1 micro** to guarantee passing evaluation.
- **Floor Buffer De-lever**: If trailing cushion $<\$400.00$ or `riskState.emergencyDelever == true`, de-lever to **1 micro** (infant mortality avoidance).
- **GARCH Volatility Halving**: If `riskState.garchDecileHalving == true`, constrain sizing to **1 micro**.
- **Daily Loss Circuit Breaker**: Canonical daily soft stop at **-\$600.00** daily PnL threshold (`DAILY_SOFT_STOP_DOLLARS`).
- **Safe Deactivation Protocol**: On strategy deactivation (`onDeactivate`), if position is flat (`ctx.getPosition() == 0`), pending orders are cancelled; if a live position remains open, working protective stop orders are preserved to eliminate naked position risk.

### Exact Micro Instrument Validation (S4 & S5)
Candidate strategies must strictly reject full-size contracts that share root substrings:
- **`isAcceptedMnqSymbol(rawSymbol)`**: Strips exchange/broker prefixes (`CME:`, `NYMEX:`, `CME/`), verifies root starts with `MNQ`, followed by valid delimiter or month-year token (e.g. `MNQ`, `MNQH25`, `MNQ 03-25`, `MNQ.CME`, `MNQ#`). Rejects full-size `NQ`, `NQH25`, `CME:NQ`, and unrecognized symbols.
- **`isAcceptedMclSymbol(rawSymbol)`**: Verifies root starts with `MCL`, rejecting full-size `CL`, `CLH25`, `NYMEX:CL`, `QM`, and ambiguous symbols.
- **Fail-Closed Gate**: Instrument validation is executed in both `calculate()` and `executeAutoTradeIfArmed()`, preventing chart signals or order submissions on wrong instruments.

### Confirmed Flat State Lifecycle & Order Management
To eliminate phantom trade closures and unprotected positions:
- **No Premature Closed State**: A flatten request is not a fill. S1–S5 keep the active trade pending until a zero position is observed; submission, cancellation request, rejection, or partial fill alone does not close it.
- **Tracked Flatten Orders**: Rejection/cancellation callbacks are correlated to the submitted flatten order identity. Unrelated rejected orders do not reset flatten state; a rejected flatten remains pending for retry while position remains open.
- **Cancellation Before Flatten**: Before submitting a market flatten, tracked entry and bracket orders must be observed cancelled/filled. Cancellation requests are not treated as confirmation; order callbacks resume the transition.
- **Independent Bracket Attempts (S4 & S5)**: Stop and target creation/submission failures are handled independently. A missing/unconfirmed protective stop follows the emergency flatten policy; a rejected target is recorded while a confirmed stop is retained where possible.
- **`onPositionClosed(OrderContext ctx)`**: On confirmed zero position, residual orders are cancelled, flatten state is reset, and the active trade is closed.
- **Replay vs Live Calculation**: `calculate()` marks `trade.closed = true` strictly on historical replay bars (`series.size() - 1 > index`). Live bars rely on `onPositionClosed` or confirmed `onOrderFilled` (`ctx.getPosition() == 0`).
- **Emergency Stop-Out Protection**: In `onOrderRejected` and `onOrderCancelled`, if a protective stop order (`trade.slOrderId`) is rejected or cancelled while an open position exists (`ctx.getPosition() != 0`), an emergency market flatten (`ctx.closeAtMarket()`) is triggered immediately.

### S1–S3 Order Identity & Fill-Anchored Brackets
Baseline studies (S1, S2, S3) enforce strict order attribution:
- **Strict Order ID Matching**: Removed loose boolean order matching; `onOrderFilled` verifies `trade.entryOrderId.equals(order.getOrderId())`.
- **Cumulative Fill Reconciliation**: Uses the position's average entry price when available, retains fill-distance geometry, and updates working bracket prices and quantities to match cumulative fills.
- **Partial Entry Rejection**: Reconciles the remaining position and protective quantity; if protection cannot be confirmed, requests a fail-closed flatten.

### Cross-Process Atomic Daily Locks
- **File-Based Lock**: Prior to order submission, studies atomically create a lock file (`results/forward_test/.locks/<study>_<symbol>_<date>.lock`) via `lockFile.createNewFile()`. If the file exists, execution aborts.
- **Restart Recovery**: On study reload, if `ctx.getPosition() != 0`, the daily set `DAILY_SUBMITTED_DATES` and filesystem lock file are reconstituted to prevent double-entry.

### Account State Verification & Canonical Cushion Constant
- **Fail-Closed Status Validation**: Account state must include a valid `status` string (`ACTIVE`, `PASSED`, `DAILY_HALTED`, `TRAILED_OUT`). Missing, malformed, or unknown statuses fail closed with `ORDER_BLOCKED_UNVERIFIED_ACCOUNT`.
- **Canonical Cushion Floor**: Unified `DEFENSIVE_DELEVER_CUSHION_DOLLARS = 400.0` across Python parity engine and Java studies. If trailing cushion falls below $400.00, contract sizing de-escalates to 1 micro.

### Real-Time Alert & File Export Protocol
- Each Java study formats triggered trades, order lifecycle events, and bracket orders into structured alert lines written to a local export directory (`results/forward_test/motivewave_alerts.log`).
- Alerts include: `TIMESTAMP`, `STUDY_ID`, `SYMBOL`, `ACTION`, `PRICE`, `STOP_LOSS`, `TAKE_PROFIT`, `CONTRACTS`, `REASON`.
- Python monitoring daemons parse this log in real time to reconcile MotiveWave study intent against CQG broker order receipts.

### Candidate Tier Execution Governance & Invariants (S4 & S5)
Candidate strategies are segregated from baseline production trading:
1. **Disabled Auto-Trade by Default**: `@StudyHeader` declares `autoEntry = false`. Constant `DEFAULT_LIVE_AUTOTRADE = false`. Setting `ENABLE_LIVE_AUTOTRADE` defaults to `Boolean.FALSE`.
2. **Explicit User Opt-In Required**: `isCandidateAutoTradeAuthorized()` requires `isCandidateTier()` and explicit `settings.getBoolean(ENABLE_LIVE_AUTOTRADE)` set by user action.
3. **Reload Safety**: `onLoad(defaults)` and `initialize(desc)` explicitly sanitize execution state to disabled (`userExplicitlyAuthorizedAutoTrade = false; settings.setAutoEntry(false); settings.setBoolean(ENABLE_LIVE_AUTOTRADE, false);`). Upgrades or workspace reloads cannot silently flip candidate execution to enabled.
4. **Visual & Acoustic Signals Preserved**: Chart markers, levels, and sound alerts (`ctx.signal` and `Toolkit.beep()`) remain active even when automated execution is disabled, enabling live operator observation.

### Restart Recovery Limit

Restart handling restores daily locks and reports an open position or unverified protective coverage when active trade/order identities cannot be recovered. It deliberately does not recreate protective orders blindly. Broker-position, working-order, and active-trade reconciliation across a restart remains limited by the order state available to the current study instance. The current worktree's Java changes have not been compiled or deployed; prior extension artifacts do not contain or verify these edits.

### Unified Account-Risk State Interface & Fail-Closed Enforcement
All five Java studies load canonical risk state from `demo_parity_state.json`:
- **Configurable Path**: Resolves forward-test directory via MotiveWave study setting (`forwardTestDir`), Java System property (`-Dasymmetry.forwardTestDir=...`), environment variable (`ASYMMETRY_FORWARD_TEST_DIR`), local relative path `results/forward_test`, or user home fallback.
- **Strict File Name**: Reject any non-canonical filename (e.g. `account_state.json`) with `ORDER_BLOCKED_UNVERIFIED_ACCOUNT`.
- **Validation**: JSON root must be an object; all required numeric fields (`balance`, `peak_balance`, `trailing_floor`, `trailing_cushion`, `current_date_pnl`, `recommended_micros`) must exist and contain finite numbers (`!Double.isNaN() && !Double.isInfinite()`).
- **Timestamp Staleness Check**: Validates ISO-8601 UTC `updated_at`. If state age exceeds 24 hours (`DEFAULT_MAX_STATE_AGE_MS = 86_400_000L`), automated orders are blocked.
- **Persistent HWM & Floor Lock**: Preserves historical peak balance and permanent $25,100 floor lock across restarts without resetting to current balance during drawdowns.

### In-Place Broker Breakeven Stop Management
- **In-Place Modification**: At +1R excursion, the study adjusts the working stop order in-place:
  ```java
  trade.slOrder.setAdjStopPrice(newStop);
  ctx.submitOrders(trade.slOrder);
  ```
  Studies NEVER cancel the working stop order when adjusting to breakeven (`ctx.cancelOrders(trade.slOrder)` is prohibited).
- **Protective Failure Policy (`applyProtectiveFailurePolicy`)**: If modification fails or is rejected, the study verifies whether the original stop order is still working. If working, it retains the original stop and does NOT pretend a tighter stop is active. If the working stop order was dropped, it executes an emergency position flatten (`ctx.closeAtMarket()`).
- **Partial Fill Quantity Synchronization**: `trade.slOrder.setAdjQuantity(posQty)` and `trade.tpOrder.setAdjQuantity(posQty)` keep bracket sizes strictly aligned with actual filled position.

### MotiveWave Java SDK Automated Order Execution Invariants (CQG Routing)
Deep forensic bytecode analysis of MotiveWave runtime (`MotiveWave.jar`, `mwave_sdk.jar`) identified five critical architectural requirements for live automated trading:
1. **`autoEntry = true` in `@StudyHeader`**:
   - MotiveWave SDK defaults `autoEntry` to `false`. Without explicit `autoEntry = true` and `manualEntry = false`, MotiveWave treats the strategy as manual-entry only and suppresses automated order generation.
2. **Strategy Activation State Guard (`study.getState() == ACTIVE`)**:
   - `bo.am.onBarClose` and `bo.am.onBarOpen` check `if (!this.N()) { this.K(); return; }`, where `N()` verifies `study.getState() == Enums$StrategyState.ACTIVE`. If inactive, MotiveWave purges all pending signals and returns.
   - The strategy must be added via the **Strategies** panel (or tab) and activated, setting `study.setState(ACTIVE)`.
3. **Sequential Bracket Execution for CQG Brokers**:
   - Submitting simultaneous raw `[entry, sl, tp]` orders while flat causes CQG to reject Stop/Limit orders (no open position / margin check failure).
   - The verified execution sequence is:
     1. Submit market entry (`ctx.createMarketOrder(action, contracts)`).
     2. Wait for fill confirmation in `onOrderFilled(ctx, order)`.
     3. Once the position is confirmed open (`ctx.getPosition() != 0`), submit linked Stop Loss (`createStopOrder`) and Profit Target (`createLimitOrder`).
     4. When position returns to flat (`ctx.getPosition() == 0`), cancel remaining bracket orders (`ctx.cancelOrders()`).
4. **Time & News Guard Flattens**:
   - Managed automatically in `onBarClose(OrderContext ctx)`:
     - Strategy 1: Hard max exit at 10:15 ET; 09:59 ET flatten on red-folder news days.
     - Strategy 2: Pre-cash flatten at 09:25 ET (or 10:35 ET for 10am window).
     - Strategy 3: Post-fix session boundary flatten at 11:00 ET.
5. **No Illegal String Format Specifiers**:
   - `%+$%.2f` is illegal in `java.util.Formatter` and throws `UnknownFormatConversionException`, crashing MotiveWave's chart calculation thread. All dollar displays use `(pts >= 0 ? "+$" : "-$") + String.format("%.2f", Math.abs(netDollars))`.
6. **Strict Single-Trade-Per-Day Session Cooldown (`DAILY_SUBMITTED_DATES`)**:
   - To eliminate cascading multi-entries or re-triggers following chart recalculations (`calculate(0, ctx)` resetting instance variables) or stop-outs within the same session window, all three studies enforce a thread-safe JVM-static session set `DAILY_SUBMITTED_DATES = ConcurrentHashMap.newKeySet()`.
   - Before order submission, `executeAutoTradeIfArmed` verifies `!DAILY_SUBMITTED_DATES.contains(today)` and immediately locks `today` upon order dispatch, marking all daily candidate trade structs as submitted. `onBarClose(ctx)` short-circuits entry evaluation when `DAILY_SUBMITTED_DATES.contains(today)`, mathematically guaranteeing at most 1 trade per study per calendar day.

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
