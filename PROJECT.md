# Project: LucidFlex 25K Quantitative Strategy Expansion (S4 & S5)

## Architecture
- **Strategy Engine**: Modular backtesting engine (`backtest/engine.py`, `backtest/portfolio.py`, `backtest/execution.py`, `backtest/indicators.py`, `backtest/signals.py`) supporting vectorized and event-driven simulation across CME/NYMEX/COMEX liquid futures.
- **Quantitative Provenance Store**: SQLite database (`results/backtest_provenance.db`) with JSONL audit trail (`results/backtest_provenance.jsonl`) enforcing the 5 Golden Rules of Quantitative Provenance, data file cryptographic SHA-256 caching, and automated warning flags.
- **Strategy Registry**: `config/strategy_registry.py` enforcing tier segregation (`StrategyTier.BASELINE`, `StrategyTier.FORWARD_DEMO`, `StrategyTier.CANDIDATE`, `StrategyTier.REJECTED`). New research strategies are strictly registered under `StrategyTier.CANDIDATE`.
- **Position Sizing & Risk Controls**: Pareto Anti-Martingale Ratchet (Tier 1: 2 micros, Tier 2: 3 micros, Tier 3: 4 micros, Finish-Line Shield: 1 micro, Safe CPPI de-lever to 1 micro if cushion < $400) calibrated against LucidFlex 25K account parameters ($25,000 balance, $1,250 profit target, $1,000 EOD trailing drawdown with $25,100 floor lock, -$600 intraday soft stop, 40% consistency cap).
- **Execution Windows**:
  - Baseline S1 (`morning_va_breakout_s1`): 09:45–11:30 ET (MNQ/MES)
  - Baseline S2 (`macro_momentum_s2`): 08:35–09:25 ET (MNQ)
  - Baseline S3 (`gold_london_fix_s3`): 10:15–11:45 ET (MGC)
  - Candidate S4 (`asian_evening_reversion_s4`): 21:00–23:00 ET (MNQ) — Tokyo cash open Globex drift reversion
  - Candidate S5 (`crude_rth_expansion_s5`): 10:15–12:30 ET (MCL) — Post-Fix morning consolidation range expansion into European close

## Code Layout
- `strategies/`: Strategy logic and signal generation definitions
- `config/strategy_registry.py`: Strategy registry and tier assignments
- `config/backtest_config.py`: Backtesting and risk configuration
- `backtest/engine.py`: Backtest execution engine
- `backtest/provenance.py`: Provenance store, SHA-256 calculation, and warning flags
- `backtest/dashboard_analytics.py`: Prop firm simulation and ratchet sizing
- `scripts/query_provenance.py`: Provenance CLI inspection tool
- `wiki/`: Knowledge catalog, strategy topic pages, active hot page, and log journal
- `results/`: Official SQLite provenance database and JSONL logs

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Candidate S4 Research & Implementation | Formulate and implement Asian Evening Mean Reversion (21:00–23:00 ET on MES/MNQ) avoiding SMT, 03:00 ET, and 45 failed ideas | M1 | Survey / ORIGINAL_REQUEST R1, R3 |
| 2 | Candidate S4 Registry & Provenance Backtest | Register S4 under StrategyTier.CANDIDATE in config/strategy_registry.py and record backtest in results/backtest_provenance.db | M1 | Survey / ORIGINAL_REQUEST R4 |
| 3 | Candidate S5 Research & Implementation | Formulate and implement US RTH Crude Oil Strategy (within 08:30–16:00 ET on MCL) avoiding SMT, 03:00 ET, and 45 failed ideas | M2 | Survey / ORIGINAL_REQUEST R1, R3 |
| 4 | Candidate S5 Registry & Provenance Backtest | Register S5 under StrategyTier.CANDIDATE in config/strategy_registry.py and record backtest in results/backtest_provenance.db | M2 | Survey / ORIGINAL_REQUEST R4 |
| 5 | Pareto Ratchet & Prop Firm Account Simulation | Calibrate Pareto Anti-Martingale Ratchet sizing (2->3->4 micros, 1 micro shield/cushion) and simulate pass/fail on LucidFlex 25K | M3 | Survey / ORIGINAL_REQUEST R2 |
| 6 | Portfolio Correlation Matrix & Risk Limit Verification | Verify all pairwise daily correlations between S1, S2, S3, S4, S5 are < 0.20; verify trailing DD and daily soft stop compliance | M3 | Survey / ORIGINAL_REQUEST R1, R2 |
| 7 | Wiki Knowledge Base & Final Reporting | Document new strategies in wiki/ topic pages, update wiki/hot.md, append to wiki/log.md, format final report with Provenance Footers | M4 | Survey / AGENTS.md, GEMINI.md |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Candidate Strategy S4 (Asian Evening Reversion) | Implement, register (CANDIDATE), backtest on MNQ 21:00–23:00 ET, record in provenance DB | none | DONE |
| M2 | Candidate Strategy S5 (US RTH Crude Oil) | Implement, register (CANDIDATE), backtest on MCL strictly within 08:30–16:00 ET, record in provenance DB | none | DONE |
| M3 | Sizing Calibration & Correlation Verification | Calibrate Pareto Ratchet sizing, simulate LucidFlex 25K pass/fail, compute 5x5 correlation matrix (< 0.20) | M1, M2 | DONE |
| M4 | Wiki Documentation & Provenance Finalization | Update wiki/ pages (strategy topics, hot.md, log.md) and generate final verified report | M3 | DONE |

## Interface Contracts
### Candidate Strategy ↔ Engine & Registry
- `StrategyRegistry`: Strategy must be registered with `tier=StrategyTier.CANDIDATE`, `strategy_id` (string), `strategy_name` (string), `asset_class` (string), `primary_instrument` (string), `timeframe` (string), `session_window` (string).
- `BacktestEngine`: Signals generated as pandas DataFrame or Series matching 1-minute timestamps, executed with conservative intrabar exit logic, net of commissions ($1.40/RT for MES/MNQ, $3.50/RT for MCL) and realistic slippage.
- `ProvenanceDB`: Runs recorded via `record_run()` returning `run_id`, writing to `results/backtest_provenance.db` with data SHA-256 hash.

### Portfolio & Sizing ↔ Prop Firm Simulator
- `PropFirmSimulator`: Account size $25,000, target $1,250, trailing max DD $1,000 (EOD trailing with $25,100 floor lock), daily soft stop -$600, consistency cap 40% ($500 max/day).
- `ParetoRatchet`: Dynamic sizing based on cumulative profit and cushion:
  - Cumulative PnL in [$0, +$199]: 2 micros
  - Cumulative PnL in [+$200, +$549]: 3 micros
  - Cumulative PnL in [+$550, +$1,149]: 4 micros
  - Cumulative PnL >= +$1,150: 1 micro (Finish-Line Shield)
  - Cushion (< balance - floor) < $400: de-lever to 1 micro (Safe CPPI)
