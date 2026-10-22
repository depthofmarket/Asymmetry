# AI Coding Agent Guide: NQ Scalper Backtest

## Architecture Overview

This is a **production-grade NQ futures backtesting framework** with strict anti-overfit validation, point-in-time features, and real execution/paper-trading simulation.

### Core Stack
- **Engine**: `BacktestEngine` (mixins: ExecutionMixin, IndicatorMixin, SignalMixin) orchestrates bar-by-bar simulation
- **Portfolio**: `Portfolio` tracks positions, fills, equity, and trade logs with NQ-specific commissions/slippage
- **Config**: `config/backtest_config.py` centralizes all strategy params, candidate overrides, and validation gates
- **Entry Points**: `main_backtest.py` (orchestration), `scripts/` (CLI thin-wrappers calling `backtest/` modules)

### Data Flow
1. Load continuous NQ contract bars → `select_continuous_outright_contract()` picks highest-volume symbol per session
2. Add point-in-time features (auction context, market memory, options flow, Markov regime, etc.)
3. Extract signal events → `extract_signal_events()` returns time/direction/type for each trigger
4. Execute bars → apply fills, commissions, slippage; update portfolio equity
5. Validate results → walk-forward, permutation tests, discipline gate, prop-firm sim

## Critical Patterns & Conventions

### Point-in-Time Feature Safety
**All feature columns must be future-leak-free.** Reference `/backtest/README.md`:
- Feature builders (`auction_context.py`, `market_memory.py`, `options_flow.py`, etc.) live in `backtest/`
- Features must use only past/current bars, never forward-looking data
- Intraday options flow (`0dte` bucket) mixes with longer OI/DEX separately in `options_flow_dashboard.csv`
- Use `mask_columns_before_clock()` from `point_in_time.py` to blank columns before their trading hour

### Walk-Forward & Anti-Overfit Enforcement
- Default: **rolling forward-chain** with purged train tail + embargo gap before each OOS fold
- `wf_purge_bars='auto'` removes train bars that could overlap next OOS fold through max hold + entry delay
- `wf_embargo_bars` adds serial-correlation gap; treat optimization as hypothesis generation, not proof
- Each run writes:
  - `research/development_report.csv` + `.md`: signal-bar, execution-bar, regime-weighted scoring
  - `research/optimization_stability.csv`: flags sharp train optima, weak neighbors, OOS fold failure
  - `research/multiple_testing_debt.csv`: candidate family + run count to prevent masquerading searches as independent
  - `research/research_discipline_gate.csv`: **strict promotion gate** (missing permutation evidence, execution audit, or excessive family run count = non-promotable)

### Execution Realism
- **Asymmetric slippage**: stop exits hit urgently (wider spread), limit fills rest in book (tighter/zero)
- Commissions/slippage configured per contract in `FUTURES_SPECS`
- TBBO execution data is **auditing-only** (not for signal mining): `build_tbbo_execution_stats.py`, `audit_fill_assumptions.py`
- 5-minute signal-bar PF + `combined_mild` trade stress are **hard warnings** in development_report

### Candidate Lifecycle & Freezing
- **Freeze before any locked-box or forward run:** `python3 scripts/check_research_freeze.py --manifest config/research_freeze.json --print-command`
- Development vs lockbox distinction is enforced: development runs may show in-sample bias; lockbox is untouched evidence
- Reject with postmortem: `docs/research_postmortems/YYYY-MM-DD_*.md` explains why candidate was discarded
- Current state: No active validation candidate; `config/research_freeze.json` archives a rejected candidate for reproducibility

### Paper/Live Execution Model
- **Paper runner**: `run_paper_trader.py --candidate <name> --start DATE --end DATE --warmup-bars 2500`
- Simulates fills locally through same portfolio/execution rules as backtest (does NOT submit broker orders)
- Paper event/trade/execution logs written to `results/paper/`
- **AMP/CQG path**: `run_amp_paper_trader.py --feed replay|tail --broker audit|cqg --prop-guard --prop-profile traders_launch_100k_nyc`
- Audit broker (`--broker audit`) writes intended BUY/SELL orders to `orders_intended.csv`; use for dry-run validation before CQG integration
- Prop guard checks eval cost, profile, multiplier, day count, PnL, rule floor, consistency, payout eligibility, kill reason

## Code Organization & File Placement

### Where New Code Goes
- **Point-in-time features**: Add columns near existing feature builders in `backtest/auction_context.py`, `backtest/market_memory.py`, etc.
- **Live/paper execution**: Flat modules `backtest/live.py`, `backtest/live_feeds.py`, `backtest/live_brokers.py`, `backtest/live_prop_rules.py`
- **Research/diagnostics**: Existing modules `backtest/validation.py`, `backtest/research_protocol.py`, `backtest/simulations.py`; keep artifact-based (audit completed runs, don't launch new backtests)
- **CLI entry points**: `scripts/`, keep them thin wrappers; reusable logic stays in `backtest/`
- **Strategy parameters**: `config/backtest_config.py` (not in scripts)
- **Tests**: Beside behavior they protect (`tests/test_live_*.py`, `tests/test_*research*.py`)

### Key Module Imports
```python
from backtest.engine import BacktestEngine
from backtest.portfolio import Portfolio
from backtest.live import PaperTradingEngine, PaperTradingConfig
from backtest.live_feeds import CsvReplayFeed, FileTailBarFeed
from backtest.live_brokers import CsvOrderAuditBroker
from backtest.live_prop_rules import LivePropRuleGuard
from backtest.live_parity import compare_trade_logs
from backtest.strategy_runtime import SignalEvent, extract_signal_events
from backtest.walkforward import WalkForwardFoldResult
from backtest.validation import DevelopmentReportPaths
```

## Developer Workflows

### Running a Backtest Candidate
```bash
# List available candidates
python3 main_backtest.py --list-candidates

# Run a candidate (keeps user in control; no automation without explicit approval)
caffeinate -dimsu python3 main_backtest.py --candidate mr_long_only

# Paper-style replay of a candidate
python3 scripts/run_paper_trader.py --candidate edge_vp_hf_gap --start 2024-01-01 --end 2024-12-31 --warmup-bars 2500
```

### Validating Research Freeze & Gates
```bash
# Freeze candidate before locked-box run
python3 scripts/check_research_freeze.py --manifest config/research_freeze.json --print-command

# Evaluate saved development run against pre-declared gates
python3 scripts/check_research_freeze.py --manifest config/research_freeze.json --run-dir results/runs/<label> --phase development

# Evaluate saved lockbox run
python3 scripts/check_research_freeze.py --manifest config/research_freeze.json --run-dir results/runs/<label> --phase lockbox
```

### Auditing Trade-vs-Signal Bar PF Disagreement
```bash
# Reconstruct exposure from saved run without replaying strategy logic
python3 scripts/audit_bar_exposure.py --run-dir results/runs/<label>

# Re-check discipline gate after audits available
python3 scripts/check_research_discipline.py --run-dir results/runs/<label>

# Audit fill assumptions (target-fill, same-minute exits, ordering ambiguity)
python3 scripts/audit_fill_assumptions.py --run-dir results/runs/<label> --start 2021-01-01
```

### Building & Testing Features
```bash
# NQ options-flow features (point-in-time, no leakage)
python3 scripts/build_options_flow_features.py --min-dte 0 --max-dte 120 --strike-window-points 600

# Aggressive trade-flow stats from Databento trades
python3 scripts/build_aggressive_flow_stats.py --source /path/to/<trades>.zip --merge-existing

# TBBO execution baseline (cost model calibration)
python3 scripts/build_tbbo_execution_stats.py --source /path/to/<tbbo>.zip --max-files 1 --rows-per-file 50000
```

### Signal Research Gate
```bash
# Pre-candidate IC, forward-return, stability, context evidence
python3 scripts/run_signal_research_report.py --signals-csv results/research_master/signal_exports/my_signal.csv \
  --signal-cols candidate_signal \
  --entry-price-col open --entry-lag-bars 1 --exit-price-col close \
  --round-trip-cost-points 1.5 \
  --event-bootstrap-samples 2000 --event-placebo-samples 2000

# Temporal gate across legacy/transition/recent eras
python3 scripts/run_temporal_signal_research_report.py --signals-csv results/research_master/power_hour_signal.csv \
  --splits legacy_context:2010-01-01:2015-12-31,transition:2016-01-01:2020-12-31,recent_development:2021-01-01:2024-12-31 \
  --primary-split recent_development
```

## Frequently Used Patterns

### Directional Signal Parametrization
Strategy params support directional overrides via naming convention:
```python
# Examples from backtest_config.py
'long_enabled': True,  # directional override
'short_enabled': False,
'signal_type_long_threshold': 0.5,  # signal-type + directional override
'mean_reversion_long_profit_target_points': 3.5
```
Query with engine helpers:
```python
enabled = engine.is_signal_direction_enabled('mean_reversion', 'long')
value = engine.get_signal_param('mean_reversion', 'long', 'profit_target_points', default=3.0)
```

### Extracting Signal Events
```python
from backtest.strategy_runtime import extract_signal_events
events = extract_signal_events(
    results_df,  # post-run engine output
    signal_col='entry_signal',
    direction_col='direction',
    time_col='time'
)
# Returns: List[SignalEvent] with time, direction, signal_type for analysis
```

### Bar-Level Metrics (Signal vs Execution)
```python
from backtest.objectives import bar_objective_metrics, execution_bar_objective_metrics

# Signal bar: OHLC from entry signal bar
signal_pf = bar_objective_metrics(trade_df, bar_df, metric='profit_factor', bar_type='signal')

# Execution bar: OHLC from 1min execution bars (catches same-minute exit hindsight)
exec_pf = execution_bar_objective_metrics(trade_df, exec_df, metric='profit_factor')
```

### Walk-Forward Folds Inspection
```python
from backtest.walkforward import WalkForwardResult
result: WalkForwardResult  # returned from run

for fold in result.folds:
    print(f"Fold {fold.fold_idx}: train {fold.train_start} → test {fold.test_start}")
    print(f"  Train: {fold.train_metric:.4f} | Test: {fold.test_results.get('profit_factor', 'N/A')}")
    print(f"  Purge: {fold.purge_bars} bars | Embargo: {fold.embargo_bars} bars | OK: {fold.purge_embargo_ok}")
```

## Data Paths & Conventions

- **1-minute NQ bars**: `data/raw/glbx-mdp3-20100606-20260428.ohlcv-1m.csv`
- **Options flow (daily)**: `data/processed/options_nq/options_flow_daily.csv`
- **Options GEX/DEX strike levels**: `data/processed/options_nq/options_flow_strike_levels.csv`
- **TBBO execution stats**: `data/processed/tbbo/tbbo_minute_execution_stats.csv` (not for mining; audit-only)
- **Aggressive flow stats**: `data/processed/orderflow/aggressive_flow_minute_stats.csv`
- **Results**: `results/runs/<timestamp>_<candidate_name>/` with run config, trade_log.csv, reports
- **Paper**: `results/paper_<candidate>_<date>.json` + `results/paper_<candidate>_trades.csv`

## Testing & Validation Expectations

- **Unit tests**: beside behavior they protect (`tests/`); run with `pytest`
- **Regression tests**: saved run artifacts; compare new runs to baseline with `audit_*.py` scripts
- **Prop-firm simulation**: includes zero-PnL calendar days; active-day-only pass rates are invalid for sparse strategies
- **Monte Carlo**: permutation tests + stress tests (cost, regime) required before promotion

## Common Pitfalls to Avoid

1. **Future leakage in features**: All feature builders must use only past/current bars. Use `mask_columns_before_clock()` to blank columns before their trading hour.
2. **Optimizing on train set only**: Walk-forward with purge/embargo is mandatory. OOS fold failure or missing permutation evidence blocks promotion.
3. **Mining TBBO data for signals**: TBBO is execution-realism auditing only. Use bars for signal development; use TBBO to validate fill/slippage assumptions afterward.
4. **Ignoring asymmetric slippage**: Stops exit urgently (wider slippage); limits fill passively (lower slippage). Set separately in `FUTURES_SPECS`.
5. **Running backtests from automation**: User must explicitly approve each run. Batch scripts require `ALLOW_BACKTEST_BATCH=1` environment variable.
6. **Confusing signal-bar vs execution-bar PF**: Signal-bar uses entry signal bar OHLC (may include hindsight). Execution-bar uses actual 1min bars filled into. 5-minute signal-bar PF is diagnostic only.
7. **Missing discipline gate checks**: Before promotion, ensure: permutation evidence, bar-exposure audit, execution-realism audit, not in-sample-only prop evidence, and low family run count.

## Links & References

- **Architecture**: `docs/codebase_map.md` (navigation), `backtest/README.md` (module map)
- **Commands**: `BACKTEST_COMMANDS.md` (historical reproduce entry points), `scripts/README.md` (CLI map)
- **Config**: `config/backtest_config.py` (all params + candidate overrides)
- **Live**: `config/live_trading.example.env` (CQG/AMP template)
- **Postmortems**: `docs/research_postmortems/` (why candidates were rejected)
- **State**: `RESEARCH_STATE.md` (current active work), `ACTION_PLAN.md` (next steps)

# Copilot Instructions for this repo

## Big picture
- This repo is an NQ futures research/backtest engine, not a generic trading app. The core flow is: raw 1m futures bars -> continuous-contract selection -> point-in-time feature generation -> signal extraction -> portfolio execution -> validation artifacts.
- The central orchestrator is `main_backtest.py`; the reusable logic lives under `backtest/`, and thin CLIs live under `scripts/`.
- `config/backtest_config.py` is the source of truth for strategy defaults, candidate overrides, execution assumptions, and research gates. Most new strategy parameters belong there, not in script code.
- `backtest/engine.py` assembles the pipeline: `BacktestEngine` combines execution, indicators, and signal mixins and applies feature filters with `mask_columns_before_clock()` and other point-in-time guards.

## Key architecture patterns
- Data selection is intentionally contract-aware: `select_continuous_outright_contract()` in `main_backtest.py` chooses the appropriate NQ outright symbol by prior-session volume to avoid future leakage from rolling contracts.
- Feature modules are modular (`auction_context.py`, `market_memory.py`, `markov_regime.py`, `options_flow.py`, `market_profile.py`, etc.) and are designed to be swap-in/out without changing the strategy loop.
- Live/paper execution is a separate path: `backtest/live*.py`, `backtest/live_feeds.py`, `backtest/live_brokers.py`, `backtest/live_prop_rules.py` implement replay + audit flows, not the historical backtest path.
- Execution realism is treated as first-class: slippage/commissions are configured in `FUTURES_SPECS`, and TBBO execution artifacts are for auditing cost assumptions rather than mining alpha.

## Project-specific conventions
- Treat all signal features as point-in-time and leakage-safe. If a feature is time-sensitive, it must be masked before its valid clock window (`mask_columns_before_clock()` is the normal pattern).
- Candidate rules are config-driven. Prefer adding new candidate parameters in `config/backtest_config.py` and hooking them through `BacktestEngine.get_signal_param()` / `is_signal_direction_enabled()` instead of branching in scripts.
- Research artifacts are saved under `results/runs/<label>/` and must be validated via audit/check scripts instead of trusting eyeballing or an isolated backtest printout.
- Keep reusable logic in `backtest/`; keep one-off CLI experiments in `scripts/`.

## Validation and anti-overfit workflow
- The repo has a strict anti-overfit culture: walk-forward, discipline gates, and frozen candidate checks are expected before promoting a strategy.
- Use the freeze gate before any lockbox/forward run: `python3 scripts/check_research_freeze.py --manifest config/research_freeze.json --print-command`.
- After a saved run, verify artifacts with the repo’s audit tooling, e.g. `scripts/audit_bar_exposure.py`, `scripts/check_research_discipline.py`, `scripts/check_prop_research_gate.py`, and `scripts/check_research_protocol.py`.
- `research/development_report.csv` / `.md`, `optimization_stability.csv`, and `research_discipline_gate.csv` are not optional decoration; they are part of the evidence pipeline.

## Developer workflows
- List available candidates: `python3 main_backtest.py --list-candidates`.
- Run a candidate: `caffeinate -dimsu python3 main_backtest.py --candidate mr_long_only`.
- Replay paper execution: `python3 scripts/run_paper_trader.py --candidate <candidate_name> --start 2024-01-01 --end 2024-01-31 --warmup-bars 2500`.
- AMP/CQG dry-run: `python3 scripts/run_amp_paper_trader.py --feed replay --broker audit --candidate <candidate_name> --start 2024-01-01 --end 2024-01-31 --warmup-bars 2500`.
- Build options-flow features: `python3 scripts/build_options_flow_features.py --min-dte 0 --max-dte 120 --strike-window-points 600`.
- Build TBBO execution stats: `python3 scripts/build_tbbo_execution_stats.py --source /path/to/archive.zip --max-files 1 --rows-per-file 50000`.

## Working style for this repo
- Prefer adding a reusable feature or engine hook over a special-case branch in a script.
- When touching strategy behavior, inspect the existing config and feature modules before changing execution logic; this repo patches research logic in a modular, parameter-driven way.
- Don’t treat TBBO as signal data; it is for execution realism and fill-cost audits.
- Don’t treat options-flow or other feature datasets as “free” context; their valid usage is specific, time-bounded, and documented by the feature modules and configs.

## Good examples to follow
- `main_backtest.py`: orchestration and contract selection.
- `backtest/engine.py`: model assembly and point-in-time filtering.
- `config/backtest_config.py`: canonical params and research controls.
- `backtest/live.py` + `backtest/live_*.py`: broker-neutral live/paper execution path.
- `scripts/check_research_*` and `scripts/audit_*`: the repo’s preferred artifact-validation flow.
