# NQ Scalper Backtest - Codebase Analysis Report
**Generated: May 27, 2026**

---

## Executive Summary

This is a **mature, production-grade NQ futures backtesting framework** (~49,500 LOC) with sophisticated anti-overfit validation, point-in-time feature engineering, and comprehensive research discipline gates. The codebase is in a **controlled research pause**: no active validation candidates, all major signal families rejected, and the validation queue intentionally empty pending fresh ex-ante hypothesis development.

### Key Statistics
- **Total Python modules**: 140 files
- **Backtest core**: 56 modules (~30,000 LOC)
- **Test coverage**: 39 test files
- **Configured candidates**: 83 variants
- **Active validation queue**: 0 candidates
- **Historical runs**: 9 completed backtests (May 2026)
- **Data span**: 2010-06-06 to 2026-04-28 (NQ 1-minute bars)

---

## 1. Architecture & Core Design

### 1.1 Engine Architecture (Mixin Pattern)

The backtest orchestration is **bar-by-bar simulation** with pluggable mixins:

```
BacktestEngine
├─ ExecutionMixin (fills, commissions, slippage)
├─ IndicatorMixin (technical indicators, aggregate features)
└─ SignalMixin (entry/exit signal generation)
```

**Key Design Decisions:**
- **Directional parametrization**: Params support `long_enabled`, `short_enabled`, `signal_type_long_threshold` patterns
- **Continuous contract handling**: `select_continuous_outright_contract()` rolls contracts using prior session volume to avoid lookahead
- **Asymmetric slippage**: Stop exits hit urgently (1.00 points), limit fills rest in book (0.25 points)
- **Markov regime filtering**: Optional volatility-regime gate applied post-signal with allowed/blocked state maps

### 1.2 Portfolio Management

`Portfolio` class tracks:
- Open/closed positions with fills at entry/exit
- Equity curve and peak tracking
- Trade logs with PnL, commissions, reason codes
- NQ-specific contract specs ($20 multiplier, $3.50 commission/round-trip)

### 1.3 Feature Engineering (Point-in-Time Safety)

All features **must be future-leak-free**:

| Module | Purpose | Time Windows |
|--------|---------|--------------|
| `auction_context.py` | Auction phase, opening imbalance | Pre/during/post 09:30-10:00 |
| `market_memory.py` | Hurst, entropy, Lempel-Ziv, drift | Lookback-based, historical |
| `market_profile.py` | Rolling support/resistance levels | Session-aligned |
| `market_structure.py` | Confirmed directional changes | Past bars only |
| `options_flow.py` | OI, volume, Greeks, GEX/DEX | Daily features, point-in-time |
| `markov_regime.py` | 3-state volatility regime | Online calibration, refits every 12 bars |
| `volume_spread.py` | VSA patterns, volume confirmation | Historical bars |

**Critical Protection**: `mask_columns_before_clock()` blanks feature columns before their trading hour.

### 1.4 Walk-Forward Validation (Anti-Overfit Core)

**Default strategy**: Rolling forward-chain with purge + embargo:
- `wf_purge_bars='auto'`: Removes train tail that overlaps next OOS fold via (max_hold + entry_delay)
- `wf_embargo_bars`: Adds serial-correlation gap between train end and OOS start
- Each fold generates walk-forward report with train metric vs OOS metric
- Flags sharp train optima (weak neighbors = overfitting), OOS fold failure

**Report outputs** per run:
- `research/optimization_stability.csv`: Train/OOS parity, fold details
- `research/development_report.csv/md`: Signal-bar PF, execution-bar PF, regime-weighted scoring
- `research/research_discipline_gate.csv`: **HARD GATE** (missing permutation, bar audit, execution audit, excessive family runs = non-promotable)

---

## 2. Validation Framework (Anti-Overfit Enforcement)

### 2.1 Multi-Testing Debt Tracking

Every configured candidate variant is a tested hypothesis:
- **Family-level run floors**: `RESEARCH_CONFIG["candidate_family_run_count_floors"]` prevents masquerading repeated searches as independent evidence
- **Effective family run count**: `max(saved_runs, floor)` — deleting result folders does NOT reduce debt
- **Family warning threshold**: Flags when effective count > configured max
- Export: `research/multiple_testing_debt.csv/md`

### 2.2 Research Discipline Gate (Promotion Blocker)

Before ANY candidate is eligible for funded/payout mode, it must pass:

| Gate | Requirement | Source |
|------|-------------|--------|
| **Permutation evidence** | Successful permutation test (random trade labels) | `research/monte_carlo_*.csv` |
| **Bar exposure audit** | Signal-bar PF ≠ execution-bar PF reconciliation | `audit_bar_exposure.py` output |
| **Execution realism** | Fill/slippage assumptions validated or audited | `audit_fill_assumptions.py` or TBBO comparison |
| **Multiple-testing debt** | Family run count ≤ configured threshold | `research/multiple_testing_debt.csv` |
| **No in-sample-only prop evidence** | Prop-firm sim includes calendar zero-PnL days | `prop_attempt_ledger.csv` |
| **5-minute signal-bar PF warning** | Signal-bar OHLC hindsight flag (diagnostic only) | `research/development_report.csv` |

**Gate verdict**: CSV marks `PASS` or `FAIL` with reason

### 2.3 Research Freeze & Lockbox

Before locked-box or forward-style run:
```bash
python3 scripts/check_research_freeze.py --manifest config/research_freeze.json --print-command
```

Freeze manifest (`config/research_freeze.json`):
- Snapshots candidate config + acceptance criteria
- SHA256 fingerprint prevents config drift
- Distinguishes **development** (allowed rejection) vs **lockbox** (untouched evidence)
- Current state: Archived rejected microstructure probe (reproducibility only, NOT active)

---

## 3. Research State & Validation Queue

### 3.1 Current Validation Status

**Active Queue**: **EMPTY** — No candidates in active validation

**Rejected Signal Families** (by postmortem):

| Family | Status | Reason | Postmortem |
|--------|--------|--------|-----------|
| **Failed-auction quality** | REJECTED | Accepted divergence & prop evidence weak | 2026-05-20 |
| **Microstructure liquidity-taking** | REJECTED | Stopped development run | (config) |
| **Liquidity absorption / failed continuation** | REJECTED | Pre-candidate gate failed; next-bar-open re-score also failed | 2026-05-21 |
| **Opening compression breakout** | REJECTED | Pre-candidate gate failed | 2026-05-21 |
| **RTH gap-and-go opening-range** | REJECTED | Temporal gate failed; recent 12/24-bar slice is diagnostic only | 2026-05-21 |
| **Power-hour accepted-trend** | REJECTED | Temporal gate + event gate passed recent 12/24 bars, but transition support failed & temporal event eligibility rejected all | 2026-05-22 |
| **Memory-impulse continuation** | REJECTED | Temporal gate failed; sparse recent events; transition/legacy failed | 2026-05-24 |
| **Options gamma-wall reversion** | REJECTED | Temporal event gate failed; no horizon pair passed | 2026-05-25 |

**Configured but not yet validated**: 75+ higher-frequency, market-profile, and variant probes (batch-ready, guarded)

### 3.2 Latest Rejection: Options Gamma-Wall Signal (2026-05-25)

- **Hypothesis**: Revert when price near positive-gamma wall with low market-memory regime
- **Evidence source**: Options flow + Markov regime + market memory
- **Gate result**: No signal/horizon pair passed temporal pre-candidate gate or temporal event-signal gate
- **Action**: Do NOT mine wall-distance, cooldown, hour/session, or options-age variants from same sample
- **Report**: `results/research_master/signal_research/options_gamma_wall_dev_2010_2024_event_temporal_gate_temporal.md`

### 3.3 TBBO Execution Baseline (2026-05-24)

Execution realism audit results:
- **Typical active-contract spread**: 1.5 points is acceptable
- **Tail trade-vs-mid cost**: 1.5 points is TOO LOW (wider spreads in low-liquidity windows)
- **Implication**: Future validation cost-stress should include `--stress-round-trip-cost-points 2.0,4.25`
- **Report**: `results/research_master/tbbo_execution_baseline/tbbo_execution_baseline.md`

---

## 4. Data & Feature Coverage

### 4.1 Raw Data

| Source | Size | Span | Location |
|--------|------|------|----------|
| **NQ 1-min bars** (Databento) | 754 MB | 2010-06-06 to 2026-04-28 | `data/raw/glbx-mdp3-20100606-20260428.ohlcv-1m.csv` |
| **NQ 1-min bars** (subset) | 69 MB | 2022-2025 | `data/raw/NQ_1min_2022-2025.csv` |

### 4.2 Processed Features

| Feature Set | Location | Purpose |
|-------------|----------|---------|
| **Options flow daily** | `data/processed/options_nq/options_flow_daily.csv` | OI, cleared vol, IV, Greeks, GEX/DEX |
| **Options flow dashboard** | `data/processed/options_nq/options_flow_dashboard.csv` | Split by 0DTE, 1-7DTE, 8-30DTE, 31-120DTE buckets |
| **Options by-strike levels** | `data/processed/options_nq/options_flow_strike_levels.csv` | Per-date/per-strike GEX surfaces |
| **TBBO execution stats** | `data/processed/tbbo/tbbo_minute_execution_stats.csv` | Spread, depth, trade-vs-mid baselines (audit-only) |
| **Aggressive flow** | `data/processed/orderflow/aggressive_flow_minute_stats.csv` | Realized A/B side flow from Databento trades |

### 4.3 Research Artifacts

| Location | Content |
|----------|---------|
| `results/research_master/signal_exports/` | ~18 exported signal CSVs (pre-candidate validation input) |
| `results/research_master/signal_research/` | ~92 temporal/event gate reports (per hypothesis rejection audit) |
| `results/research_master/microstructure_diagnostics/` | Real-time market microstructure for three contract types |
| `results/research_master/tbbo_execution_baseline/` | Cost model calibration from TBBO minute stats |
| `results/runs/` | 9 completed backtest runs with full research artifacts |

---

## 5. CLI Entry Points & Workflows

### 5.1 Backtest Execution

```bash
# List candidates
python3 main_backtest.py --list-candidates

# Run candidate (explicit user approval required)
caffeinate -dimsu python3 main_backtest.py --candidate <name>

# Historical replay via paper runner
python3 scripts/run_paper_trader.py --candidate <name> --start 2024-01-01 --end 2024-12-31 --warmup-bars 2500
```

### 5.2 Pre-Candidate Signal Research

```bash
# Export signal for validation
python3 scripts/export_prepared_signal_csv.py --start 2010-01-01 --end 2024-12-31 --artifact-name <name>_dev_2010_2024

# Run pre-candidate temporal gate
python3 scripts/run_temporal_signal_research_report.py \
  --signals-csv results/research_master/signal_exports/<name>_dev_2010_2024.csv \
  --signal-cols candidate_signal \
  --splits legacy_context:2010-01-01:2015-12-31,transition:2016-01-01:2020-12-31,recent_development:2021-01-01:2024-12-31 \
  --primary-split recent_development \
  --stress-round-trip-cost-points 2.0,4.25 \
  --artifact-name <name>_event_temporal_gate
```

### 5.3 Audit & Validation

```bash
# Freeze candidate
python3 scripts/check_research_freeze.py --manifest config/research_freeze.json --print-command

# Evaluate development run
python3 scripts/check_research_freeze.py --manifest config/research_freeze.json --run-dir results/runs/<label> --phase development

# Bar exposure audit (trade PF vs signal/execution bar PF)
python3 scripts/audit_bar_exposure.py --run-dir results/runs/<label>

# Fill assumption audit
python3 scripts/audit_fill_assumptions.py --run-dir results/runs/<label> --start 2021-01-01
```

### 5.4 Paper/Live Execution

```bash
# Dry-run AMP/CQG with audit broker (no orders sent)
python3 scripts/run_amp_paper_trader.py --feed replay --broker audit --candidate <name> \
  --start 2024-01-01 --end 2024-01-31 --warmup-bars 2500

# With prop-firm eval guard
python3 scripts/run_amp_paper_trader.py --feed replay --broker audit --candidate <name> \
  --prop-guard --prop-profile traders_launch_100k_nyc --prop-phase eval
```

---

## 6. Key Implementation Patterns

### 6.1 Directional Signal Parametrization

```python
# Strategy params support directional overrides
'long_enabled': True
'short_enabled': False
'signal_type_long_threshold': 0.5
'mean_reversion_long_profit_target_points': 3.5

# Query with engine helpers
enabled = engine.is_signal_direction_enabled('mean_reversion', 'long')
value = engine.get_signal_param('mean_reversion', 'long', 'profit_target_points', default=3.0)
```

### 6.2 Markov Regime Filtering

```python
# Online 3-state volatility calibration + state filtering
'markov_mode': 'require_low'  # Entry only in low volatility
'markov_allowed_states': {
    'mr': {0, 1},      # Mean reversion in low/mid volatility
    'trend': {1, 2},   # Trend in mid/high volatility
}
'markov_blocked_states': {'mr': {2}}  # Don't trade mean reversion in high vol
```

### 6.3 Signal Event Extraction

```python
from backtest.strategy_runtime import extract_signal_events

events = extract_signal_events(
    results_df,
    signal_col='entry_signal',
    direction_col='direction',
    time_col='time'
)
# Returns: List[SignalEvent] with time, direction, signal_type
```

### 6.4 Bar-Level Metrics Reconciliation

```python
from backtest.objectives import bar_objective_metrics, execution_bar_objective_metrics

# Entry signal bar OHLC (may include hindsight on same minute)
signal_pf = bar_objective_metrics(trade_df, bar_df, metric='profit_factor', bar_type='signal')

# Actual 1-minute execution bars (catches same-minute exit reality)
exec_pf = execution_bar_objective_metrics(trade_df, exec_df, metric='profit_factor')
```

---

## 7. Testing & Quality Assurance

### 7.1 Test Coverage

- **Unit tests**: `tests/test_*.py` (39 files)
- **Regression tests**: Saved run artifacts compared against baseline with audit scripts
- **Feature tests**: Point-in-time leakage checks, Markov calibration validation
- **Walk-forward tests**: Fold purge/embargo logic, parameter grid exploration

### 7.2 Continuous Quality Checks

```bash
# Run full test suite
pytest tests/

# Specific regression tests
pytest tests/test_backtest_regression.py

# Validation regression
pytest tests/test_validation_regression.py
```

### 7.3 Prop-Firm Simulation Specifics

- **Calendar days**: Includes zero-PnL days (no trades)
- **Active-day-only pass rates**: INVALID for sparse strategies
- **Ledger tracking**: Eval cost, profile, multiplier, day count, PnL, rule floor, consistency, payout eligibility, kill reason
- **Gate**: Validates prop-firm rules before `--prop-phase funded`

---

## 8. Code Organization & Key Files

### 8.1 Core Modules

```
backtest/
├── engine.py              # Main BacktestEngine (3 mixins, 1637 LOC)
├── portfolio.py           # Portfolio & Trade tracking
├── execution.py           # ExecutionMixin (fills, slippage, commissions)
├── indicators.py          # IndicatorMixin (RSI, Bollinger, ATR, etc.)
├── signals.py             # SignalMixin (entry/exit logic)
├── strategy_runtime.py    # Signal event extraction, shared backtest/live
├── walkforward.py         # Walk-forward framework (655 LOC)
├── validation.py          # Development/optimization/discipline reports (1068 LOC)
└── objectives.py          # Signal/execution bar metrics reconciliation
```

### 8.2 Feature Builders

```
backtest/
├── auction_context.py     # Pre/post ORB, opening imbalance
├── market_memory.py       # Hurst, entropy, Lempel-Ziv, drift
├── market_profile.py      # Rolling levels, point-of-control
├── market_structure.py    # Directional change confirmation
├── markov_regime.py       # Online volatility regime (655 LOC)
├── options_flow.py        # Options Greeks, GEX/DEX, DTE buckets
├── point_in_time.py       # Time masking, leakage prevention
└── volume_spread.py       # VSA, volume confirmation
```

### 8.3 Research & Validation

```
backtest/
├── research_freeze.py       # Candidate freezing & lockbox gates (380 LOC)
├── research_protocol.py     # Config fingerprinting, audit JSONL logging
├── validation.py            # Development/multiple-testing/discipline reports
├── permutation.py           # Monte Carlo random label tests
├── placebo.py               # Random timestamp/trade resampling
├── signal_research.py       # IC, forward-return, event-signal analysis
├── temporal_signal_research.py  # Temporal pre-candidate gate
└── prop_firm.py             # Prop-firm rule simulation & payout logic
```

### 8.4 Live/Paper Execution

```
backtest/
├── live.py                  # PaperTradingEngine, event model
├── live_feeds.py            # CsvReplayFeed, FileTailBarFeed, CQG adapter
├── live_brokers.py          # CsvOrderAuditBroker, CQG broker guard
├── live_prop_rules.py       # LivePropRuleGuard, funded/eval gate checks
└── live_parity.py           # Backtest-vs-paper trade log comparison
```

### 8.5 CLI Scripts

```
scripts/
├── run_paper_trader.py                    # Historical replay
├── run_amp_paper_trader.py               # AMP/CQG-oriented replay
├── run_signal_research_report.py         # Pre-candidate gate
├── run_temporal_signal_research_report.py # Temporal multi-era gate
├── audit_bar_exposure.py                 # Signal vs execution bar audit
├── audit_fill_assumptions.py             # Fill realism checks
├── build_tbbo_execution_stats.py         # TBBO processing
├── build_aggressive_flow_stats.py        # Aggressive flow extraction
├── build_options_flow_features.py        # Options feature building
└── check_research_freeze.py              # Freeze manifest validation
```

---

## 9. Configuration & Parametrization

### 9.1 Main Config Structure

```python
# config/backtest_config.py
FUTURES_SPECS = {              # NQ contract details
    'commission_per_round_trip': 3.50,
    'slippage_points': 0.75,
    'slippage_stop_points': 1.00,
    'slippage_limit_points': 0.25,
}

BACKTEST_CONFIG = {            # Runtime defaults
    'starting_capital': 100000,
    'continuous_contract_method': 'prior_session_volume',
}

STRATEGY_PARAMS = {}           # Strategy implementation params
CANDIDATE_CONFIGS = {}         # 83 variant overrides
EDGE_CANDIDATE_CONFIGS = {}    # Derived higher-frequency variants
RESEARCH_CONFIG = {            # Research gates, families, floors
    'next_validation_candidates': [],  # Empty queue
    'candidate_research_families': {...},
    'rejected_research_families': {...},
    'candidate_family_run_count_floors': {...},
}
VALIDATION_CONFIG = {}         # Discipline gate thresholds
```

### 9.2 Candidate Override Pattern

```python
CANDIDATE_CONFIGS['edge_vp_hf_gap'] = make_candidate(
    base=CANDIDATE_CONFIGS['higher_frequency_probe'],
    strategy_overrides={
        'signal_type_long_threshold': 0.6,
        'mean_reversion_long_profit_target_points': 3.5,
    },
    validation_overrides={
        'wf_n_folds': 8,
        'wf_embargo_bars': 300,
    },
)
```

---

## 10. Known Limitations & Pitfalls

### 10.1 Critical Safety Rules

1. **Future leakage in features**: Feature builders must ONLY use past/current bars
   - Use `mask_columns_before_clock()` to blank before trading hour
   - Options flow daily features are point-in-time; DTE buckets separate intraday gamma from longer OI

2. **Optimization bias**: Walk-forward with purge/embargo is MANDATORY
   - Missing permutation evidence, bar audit, or execution audit → promotion blocked
   - OOS fold failure or weak parameter neighbors → red flag

3. **TBBO data is auditing-only**: NOT for signal mining
   - Use bars for signal development
   - Use TBBO AFTER to validate fill/slippage assumptions

4. **Asymmetric slippage**: Must respect stop vs limit distinction
   - Stop exits hit urgently (1.00 points wider)
   - Limit fills rest passively (0.25 points tighter)
   - Do NOT use symmetric slippage for NQ futures

5. **No automation without approval**: Backtests require explicit user command
   - Batch scripts guarded by `ALLOW_BACKTEST_BATCH=1`
   - No "research loops" that self-approve

6. **Signal-bar vs execution-bar confusion**: 
   - Signal-bar PF uses entry signal bar OHLC (same-minute hindsight possible)
   - Execution-bar PF uses actual 1-minute bars filled into (realistic)
   - 5-minute signal-bar PF is diagnostic only

7. **Multiple-testing debt persists**: Deleting result folders does NOT reduce debt
   - Family run-count floors in RESEARCH_CONFIG are source of truth
   - Each configured candidate variant is a tested hypothesis

---

## 11. Recommendations for Next Steps

### Immediate (Data/Platform Integrity)

1. ✅ **Keep validation queue empty** until fresh ex-ante hypothesis exists
2. ✅ **Do NOT mine same-sample hour/horizon slices** into candidates (8+ signal families rejected for this)
3. ✅ **Use TBBO baseline verdict** for future cost-stress decisions (1.5 points acceptable, 2.0-4.25 for tail stress)

### Signal Development (if resuming)

1. **Write fresh hypothesis first** — ex-ante, not post-hoc
2. **Export prepared signal CSV** with point-in-time features only (2010-2024 development/context)
3. **Run temporal event-enhanced pre-candidate gate** with `--stress-round-trip-cost-points 2.0,4.25`
4. **Require forward-return IC, event-signal evidence, and period stability** before candidate creation
5. **Freeze exactly one candidate** AFTER signal report + hypothesis exist
6. **Keep 2025+ as recent holdout** (never inspect before development evidence passes)

### Execution/Live Path

1. **Audit TBBO parity** before deploying any new candidate
2. **Use audit broker mode** (`--broker audit`) to dry-run CQG integration
3. **Validate prop-firm profiles** before `--prop-phase funded`
4. **Monitor live parity** via `check_live_parity.py`

---

## 12. Conclusion

This codebase represents a **mature, disciplined research framework** with:
- ✅ Sophisticated anti-overfit validation (purge/embargo, permutation, bar audits)
- ✅ Execution realism modeling (asymmetric slippage, TBBO baselines)
- ✅ Point-in-time feature safety (leakage prevention, time masking)
- ✅ Research protocol enforcement (freeze, lockbox, discipline gates)
- ✅ Paper/live execution scaffold (ready for CQG/AMP integration)

**Current state**: Validation queue intentionally empty, all major signal hypotheses rejected, platform hardening complete. Ready for fresh ex-ante hypothesis development with strict pre-candidate evidence gates.

**No "quick wins"**: All time-of-day, horizon, and options-filter mutations of 8+ rejected signal families have failed. Future work should focus on structural innovations backed by prior-art literature or novel execution/cost insights.
