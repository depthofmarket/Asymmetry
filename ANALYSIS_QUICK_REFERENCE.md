# Codebase Analysis Summary - Quick Reference

## 📊 Project Metrics at a Glance

```
CODEBASE SIZE
├─ Total Python modules: 140 files
├─ Backtest package: 56 modules (30,000 LOC)
├─ Test suite: 39 test files
└─ Total LOC: 49,535

DATA & INFRASTRUCTURE
├─ Historical bars: 2010-06-06 to 2026-04-28 (16 years)
├─ Contract coverage: NQ continuous outright
├─ Feature builders: 8 point-in-time modules
├─ Research artifacts: 92+ signal gate reports
└─ Completed backtests: 9 (May 2026)

CANDIDATE LIBRARY
├─ Configured variants: 83
├─ Active validation queue: 0 (empty by design)
├─ Rejected signal families: 8
└─ Status: Controlled research pause
```

---

## 🏗️ Architecture Overview

### Core Stack
```
main_backtest.py (1050 LOC)
    ↓
BacktestEngine (3 mixins)
├─ ExecutionMixin: fills, commissions, slippage
├─ IndicatorMixin: RSI, Bollinger, ATR, aggregates
└─ SignalMixin: entry/exit signal generation
    ↓
Portfolio: positions, equity, trade logs
    ↓
Walk-Forward Validator: purge/embargo, OOS testing
    ↓
Research Gates: discipline checks, prop-firm rules
```

### Feature Engineering Pipeline
```
Point-in-Time Features (Anti-Leakage Protected)
├─ Auction context (opening imbalance, ORB phases)
├─ Market memory (Hurst, entropy, Lempel-Ziv, drift)
├─ Market profile (rolling support/resistance)
├─ Market structure (directional changes)
├─ Markov regime (3-state volatility, online calibration)
├─ Options flow (OI, Greeks, GEX/DEX, DTE buckets)
├─ Volume spread (VSA patterns)
└─ mask_columns_before_clock() → prevents time-based leakage
```

---

## 🎯 Validation Framework (Anti-Overfit Core)

### Research Discipline Gate (Promotion Blocker)
Candidate must pass **ALL**:
- ✅ **Permutation evidence**: Random label test via Monte Carlo
- ✅ **Bar audit**: Signal-bar PF ≠ execution-bar PF reconciliation
- ✅ **Execution audit**: Fill/slippage assumptions validated
- ✅ **Multiple-testing debt**: Family run count ≤ threshold
- ✅ **No in-sample-only prop**: Calendar days include zero-PnL
- ✅ **5-min signal-bar warning**: Same-minute hindsight flag

*FAIL ANY GATE → Candidate non-promotable*

### Walk-Forward Strategy
```
Rolling Forward-Chain
├─ Purge: Remove train bars overlapping next OOS via max_hold + entry_delay
├─ Embargo: Add serial-correlation gap between train end + OOS start
├─ Output: optimization_stability.csv (detects overfitting)
└─ OOS fold failure or weak neighbors → red flag
```

---

## 📋 Research State (May 27, 2026)

### Active Validation
- **Queue**: Empty (intentional pause)
- **Reason**: All major signal families rejected via temporal pre-candidate gate

### Rejected Signal Families (8 total)

| Signal Family | Status | Latest Reason |
|---------------|--------|---------------|
| Failed-auction quality | ❌ | Accepted divergence weak |
| Microstructure liquidity | ❌ | Stopped development |
| Liquidity absorption | ❌ | Pre-candidate gate failed |
| Compression breakout | ❌ | Pre-candidate gate failed |
| Gap-and-go (ORB) | ❌ | Temporal gate failed; recent slice diagnostic |
| Power-hour trend | ❌ | Transition support failed; temporal event eligibility rejected |
| Memory-impulse | ❌ | Temporal gate failed; sparse events |
| Options gamma-wall | ❌ | **LATEST (2026-05-25)** Temporal event gate failed |

**Common failure mode**: Same-sample context slices, weak IC, cost-sensitive hindsight

### Latest Finding: TBBO Execution Baseline (2026-05-24)

```
Typical Active-Contract Spread
├─ Inside typical range: 1.5 points
└─ Tail trade-vs-mid: TOO LOW (wider spreads in low-liquidity)

Future Cost-Stress Template
└─ --stress-round-trip-cost-points 2.0,4.25
```

---

## 🔧 Key Development Workflows

### Backtest Candidate (User-Approved)
```bash
# List available
python3 main_backtest.py --list-candidates

# Run (requires explicit approval)
caffeinate -dimsu python3 main_backtest.py --candidate <name>
```

### Pre-Candidate Signal Research
```bash
# 1. Export signal with point-in-time features
python3 scripts/export_prepared_signal_csv.py \
  --start 2010-01-01 --end 2024-12-31 \
  --artifact-name <hypothesis>_dev_2010_2024

# 2. Run temporal event-enhanced gate
python3 scripts/run_temporal_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/<hypothesis>_dev_2010_2024.csv \
  --splits legacy_context:2010-2015,transition:2016-2020,recent_development:2021-2024 \
  --primary-split recent_development \
  --stress-round-trip-cost-points 2.0,4.25 \
  --artifact-name <hypothesis>_event_temporal_gate
```

### Freeze & Validation
```bash
# Freeze before lockbox run
python3 scripts/check_research_freeze.py --manifest config/research_freeze.json --print-command

# Evaluate development run
python3 scripts/check_research_freeze.py --run-dir results/runs/<label> --phase development

# Audit bar exposure
python3 scripts/audit_bar_exposure.py --run-dir results/runs/<label>
```

### Paper/Live Execution
```bash
# Dry-run with audit broker (no real orders)
python3 scripts/run_amp_paper_trader.py --feed replay --broker audit \
  --candidate <name> --start 2024-01-01 --end 2024-12-31

# With prop-firm guard
python3 scripts/run_amp_paper_trader.py --feed replay --broker audit \
  --candidate <name> --prop-guard --prop-phase eval
```

---

## 💾 Code Organization

### Where to Add New Code

| Code Type | Location | Example Module |
|-----------|----------|-----------------|
| **Point-in-time features** | `backtest/` | `auction_context.py`, `market_memory.py` |
| **Live/paper execution** | `backtest/live*.py` (flat) | `live.py`, `live_feeds.py`, `live_brokers.py` |
| **Research/diagnostics** | `backtest/` | `validation.py`, `signal_research.py` |
| **CLI entry points** | `scripts/` (thin) | Keep reusable logic in `backtest/` |
| **Strategy parameters** | `config/backtest_config.py` | NOT in scripts |
| **Tests** | `tests/test_*.py` | Beside behavior protected |

### Key Module Sizes

```
backtest/
├─ engine.py (1,637 LOC) - Main orchestration
├─ validation.py (1,068 LOC) - Research gates
├─ walkforward.py (655 LOC) - Anti-overfit framework
├─ markov_regime.py (655 LOC) - Volatility regime
├─ research_freeze.py (380 LOC) - Candidate freezing
├─ strategy_runtime.py - Signal extraction (shared backtest/live)
└─ portfolio.py - Position & equity tracking
```

---

## ⚠️ Critical Safety Rules (Do NOT Violate)

1. **🔒 Point-in-time safety**: All features must use only past/current bars
   - Use `mask_columns_before_clock()` before trading hour
   - Options DTE buckets separate intraday gamma from longer OI

2. **📊 Walk-forward mandatory**: Cannot optimize on train set alone
   - Purge + embargo required; OOS fold failure = red flag
   - Missing permutation/bar/execution audit → promotion blocked

3. **🚫 TBBO is auditing-only**: Do NOT mine TBBO for signals
   - Use bars for development
   - Use TBBO AFTER to validate fill assumptions

4. **💰 Asymmetric slippage**: Stop vs limit distinction critical
   - Stop exits: 1.00 points (urgent, wider spread)
   - Limit fills: 0.25 points (passive, tighter)
   - NO symmetric slippage for NQ

5. **🤖 No automation without approval**: All backtests require explicit user command
   - Batch scripts need `ALLOW_BACKTEST_BATCH=1`
   - No self-approving research loops

6. **📈 Signal-bar ≠ execution-bar PF**:
   - Signal-bar: Entry bar OHLC (same-minute hindsight possible)
   - Execution-bar: Actual 1-min bars filled into (realistic)
   - 5-minute signal-bar PF is diagnostic only

7. **🎲 Multiple-testing debt persists**: Deleting results ≠ reducing debt
   - Family run-count floors in `RESEARCH_CONFIG` are source of truth
   - Each variant is a tested hypothesis

---

## 📚 Key Files & References

### Documentation
- `CODEBASE_ANALYSIS_2026-05-27.md` ← Full analysis (this file's details)
- `docs/codebase_map.md` - Navigation layer
- `backtest/README.md` - Module-by-module map
- `scripts/README.md` - CLI entry point map
- `RESEARCH_STATE.md` - Research pause details
- `ACTION_PLAN.md` - Next steps guidance

### Configuration
- `config/backtest_config.py` - 1,920 LOC, all params
- `config/research_freeze.json` - Archived rejected candidate (reproducibility)
- `config/live_trading.example.env` - CQG/AMP template

### Research Artifacts
- `results/research_master/signal_research/` - 92+ gate reports
- `results/research_master/signal_exports/` - 18+ pre-candidate CSVs
- `results/research_master/tbbo_execution_baseline/` - Cost models
- `results/runs/` - 9 completed backtest runs
- `docs/research_postmortems/` - Why candidates rejected

### Live/Paper Integration
- `backtest/live.py` - Paper trading engine
- `backtest/live_feeds.py` - Feed adapters
- `backtest/live_brokers.py` - Broker integration
- `backtest/live_prop_rules.py` - Prop-firm rules

---

## ✅ Recommended Next Steps

### If Resuming Signal Development
1. **Write ex-ante hypothesis FIRST** (before looking at data)
2. Export prepared signal CSV (2010-2024 context)
3. Run temporal event-enhanced pre-candidate gate with cost stress
4. Require IC, forward-return, period-stability evidence
5. Keep 2025+ as held-out test set (never inspect early)
6. Freeze exactly one candidate after signal report + hypothesis exist

### If Auditing Execution
1. Compare saved trades to TBBO minute stats
2. Verify fill/slippage assumptions
3. Use `audit_fill_assumptions.py` for same-minute exit checks
4. Apply TBBO baseline verdict (1.5 points typical, 2.0-4.25 for stress)

### If Preparing Live Deployment
1. Dry-run with `--broker audit` mode (no real orders)
2. Validate prop-firm profiles before `--prop-phase funded`
3. Check live parity via `check_live_parity.py`
4. Monitor CQG/AMP integration via `check_cqg_setup.py`

---

## 🎯 Conclusion

**Maturity Level**: Production-grade with disciplined research controls

**Current State**: Intentional pause (no active candidates, all major signals rejected)

**Readiness**: 
- ✅ Ready for fresh ex-ante hypothesis with strict pre-candidate gates
- ✅ Ready for execution realism audits (TBBO integrated)
- ✅ Ready for paper/live deployment (AMP/CQG scaffold ready)
- ❌ NOT ready for time-of-day/horizon mutations (8 families failed this)

**Next Milestone**: New structural hypothesis + temporal event-enhanced pre-candidate gate
