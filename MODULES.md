# 📦 Backtest Module Directory

**Total Modules:** 66 Python files | **Purpose:** Your complete trading strategy system

---

## 🎯 Core Engine (Start Here)

These are the fundamental components that drive everything:

| Module | Purpose | Key Classes/Functions |
|--------|---------|----------------------|
| **engine.py** | Main backtest engine | `BacktestEngine`, `run_backtest()` |
| **execution.py** | Order execution logic | `ExecutionModel`, `execute_orders()` |
| **indicators.py** | Technical indicators | `SMA`, `EMA`, `RSI`, etc. |
| **signals.py** | Signal aggregation | `SignalManager`, `combine_signals()` |
| **portfolio.py** | Position tracking | `Portfolio`, `calculate_pnl()` |

---

## 📊 Signal Modules (15 signals)

Your trading signals - each detects a specific market pattern:

| Signal Name | File | What It Detects |
|------------|------|-----------------|
| **Compression Breakout** | `compression_breakout_signal.py` | Price compression followed by volatility breakout |
| **Gap Go** | `gap_go_signal.py` | Opening gaps that continue intraday |
| **Liquidity Absorption** | `liquidity_absorption_signal.py` | Large orders hitting bids/asks |
| **Memory Impulse** | `memory_impulse_signal.py` | Price momentum from previous levels |
| **Options Gamma Wall** | `options_gamma_wall_signal.py` | Options gamma hedging driving prices |
| **Power Hour** | `power_hour_signal.py` | End-of-day volume & trend patterns |
| **Market Profile Cross** | `market_profile.py` | Volume profile extremes (integrated) |
| **Aggressive Flow** | `aggressive_flow.py` | Order flow imbalance detection |
| **TBBO Execution** | `tbbo_execution.py` | Top-of-book execution gaps *(DEPRECATED - use L2)* |
| **Markov Regime** | `markov_regime.py` | Hidden Markov state detection |
| **Hawkes** | `hawkes.py` | Self-exciting point process signals |
| **Event Sampling** | `event_sampling.py` | Rare event detection |
| **Temporal Signal** | `temporal_signal_research.py` | Time-based signal research |
| **VWAP Research** | `vwap_research.py` | VWAP deviation patterns |
| **Volume Spread** | `volume_spread.py` | Volume-weighted spread analysis |

---

## 📈 Market Context Modules

Understanding market regime and conditions:

| Module | Purpose |
|--------|---------|
| **market_structure.py** | Identifies bull/bear/range markets |
| **market_memory.py** | Price mean-reversion and momentum |
| **volatility_state.py** | Current volatility regime (VIX-like) |
| **volatility_context_diagnostics.py** | Detailed volatility analysis |
| **markov_regime.py** | Hidden Markov chain state detection |
| **online_regime_leakage.py** | Regime detection with live data |
| **auction_context.py** | Market session context (open/close auctions) |

---

## 🔍 L2 Data Modules (Your New Data)

Level 2 order book processing - **critical for your new dataset:**

| Module | Purpose |
|--------|---------|
| **l2_mbp.py** | L2 market by price parsing |
| **l2_book_validation.py** | L2 data quality validation |
| **l2_parquet_audit.py** | Audit parquet L2 files |
| **l2_semantic_diagnostics.py** | Semantic validation of L2 data |
| **l2_archive_inventory.py** | L2 archive organization |

---

## 📊 Options Data Modules

Options flow and gamma analysis:

| Module | Purpose |
|--------|---------|
| **options_flow.py** | Options flow parsing & analysis |
| **options_gamma_wall_signal.py** | Gamma wall signal (combines with spot) |
| **options_surface_state.py** | Implied volatility surface |
| **options_ingestion.py** | Options data ingestion pipeline |

---

## 🧪 Research & Analysis Modules

For researching new signals and strategies:

| Module | Purpose |
|--------|---------|
| **feature_research.py** | Feature engineering & testing |
| **feature_attribution.py** | Which features drive returns |
| **signal_research.py** | Test new signal ideas |
| **temporal_signal_research.py** | Time-based signal research |
| **research_protocol.py** | Research workflow framework |
| **research_freeze.py** | Freeze parameters to prevent overfitting |

---

## 🔧 Execution & Validation

Making sure everything works correctly:

| Module | Purpose |
|--------|---------|
| **execution_realism.py** | Realistic execution simulation (slippage, fees) |
| **execution_cost_stress.py** | Execution cost stress testing |
| **point_in_time.py** | Point-in-time data integrity (no lookahead) |
| **validation.py** | General validation utilities |
| **bar_exposure_audit.py** | Check position exposure at bar level |
| **simulation.py** | Monte Carlo & simulation tools |

---

## 📤 Output & Export

Saving results and signals:

| Module | Purpose |
|--------|---------|
| **signal_export.py** | Export signals to CSV/files |
| **strategy_runtime.py** | Runtime execution tracking |
| **sweep.py** | Parameter sweep utilities |
| **permutation.py** | Permutation testing |

---

## 🏢 Live Trading & Props

Live execution and prop firm integration:

| Module | Purpose |
|--------|---------|
| **live.py** | Live trading orchestration |
| **live_feeds.py** | Live data feed connection |
| **live_brokers.py** | Broker connectivity |
| **live_parity.py** | Live/backtest parity checking |
| **live_prop_rules.py** | Prop firm rules enforcement |
| **prop_firm.py** | Prop firm integration |
| **prop_attempt_portfolio.py** | Multiple prop accounts management |
| **prop_volatility.py** | Volatility constraints for props |

---

## 🎛️ Advanced/Meta Modules

Higher-level strategy composition:

| Module | Purpose |
|--------|---------|
| **meta_strategy.py** | Meta-strategy composition (combining signals) |
| **objectives.py** | Strategy objectives & constraints |
| **walkforward.py** | Walk-forward testing (time-series CV) |
| **placebo.py** | Placebo signal testing (sanity check) |

---

## 📊 Deprecated (Ignore)

These are marked for removal (replaced by L2 data):

| Module | Reason |
|--------|--------|
| **tbbo_execution.py** | Replaced by L2 order book |
| **tbbo_execution_baseline.py** | Replaced by L2 order book |
| **tbbo_trade_audit.py** | Replaced by L2 analysis |
| **tbbo_dbn.py** | Replaced by L2 data |

---

## 🚀 Quick Start Workflows

### To Build a New Signal:
1. Start with `signal_research.py`
2. Use `feature_research.py` for feature engineering
3. Reference existing signals (e.g., `gap_go_signal.py`)
4. Integrate into `signals.py`
5. Export with `signal_export.py`

### To Run a Backtest:
1. `engine.py` - main orchestrator
2. `portfolio.py` - tracks positions
3. `execution.py` - executes orders
4. `validation.py` - validates results

### To Use L2 Data:
1. `l2_mbp.py` - parse L2 snapshots
2. `l2_book_validation.py` - validate data
3. `l2_semantic_diagnostics.py` - check for errors
4. Reference in your signal logic

---

## 📊 Module Dependency Tree

```
CORE
├── engine.py
│   ├── signals.py
│   │   ├── [All 15 signal files]
│   │   ├── market_structure.py
│   │   └── market_memory.py
│   ├── execution.py
│   │   └── execution_realism.py
│   ├── portfolio.py
│   └── validation.py
└── indicators.py

L2 DATA
├── l2_mbp.py
├── l2_book_validation.py
└── [signals using L2]

RESEARCH
├── signal_research.py
├── feature_research.py
└── walkforward.py

LIVE
├── live.py
├── live_feeds.py
└── live_brokers.py
```

---

## 💡 Navigation Tips

**Finding a signal?** Look for `*_signal.py`  
**Need to validate?** Use `validation.py` or `l2_book_validation.py`  
**Want to run backtest?** Start with `engine.py`  
**Research new idea?** Use `signal_research.py` + `feature_research.py`  
**Going live?** `live.py` + `live_brokers.py`  

---

## ✅ Checklist for New Development

- [ ] Check if module already exists
- [ ] Use `research_freeze.py` to prevent overfitting
- [ ] Use `point_in_time.py` for data integrity
- [ ] Validate with `validation.py`
- [ ] Test with `simulation.py`
- [ ] Check live parity with `live_parity.py`

