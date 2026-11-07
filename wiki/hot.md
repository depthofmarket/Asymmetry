# Active Project State & Focus Dashboard (hot.md)

This page tracks the dynamic operational state of the repository, active testing initiatives, recent changes, and immediate milestones. Updated at the conclusion of every agent session.

---

## Production Baseline & Verified Status

The active production baseline is the **LucidFlex Tri-Asset Ensemble** (`lucid_flex_ensemble`), coordinating three uncorrelated strategies under the LucidFlex 25K prop firm profile:

| Subsystem | Target Profile | Active Methodology | Net PnL (5.8 Yr) | Profit Factor | Win Rate | Active Flags |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Ensemble Walkforward** | `lucid_flex_ensemble` | Multi-Year Walkforward | $14,916.04 | 1.56 | 55.06% | ✅ None |
| **Strategy 1 (09:45 ET)** | `morning_va_breakout_s1` | Multi-Year Walkforward | $8,956.18 | 1.65 | 56.96% | ✅ None |
| **Strategy 2 (08:35 ET)** | `macro_momentum_s2` | Multi-Year Walkforward | $4,573.23 | 1.44 | 48.95% | ✅ None |
| **Strategy 3 (10:15 ET)** | `gold_london_fix_s3` | Multi-Year Walkforward | $1,386.62 | 1.59 | 58.33% | ✅ None |
| **Forward Demo Parity** | `lucid_flex_forward_demo`| Live Demo Paper Parity | $144.70 | 99.00 | 100.0% | ⚠️ `LOW_SAMPLE_SIZE` |

- **Current Repository Branch**: `main`
- **Canonical Provenance Store**: `results/backtest_provenance.db` (9 verified runs recorded: 4 canonical baseline, 3 parameter plateau sweeps, 1 alpha factory walkforward, 1 forward demo)
- **Data Source Parquet**: `data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet`
- **Data SHA-256**: `ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca`
- **Step 07 Sensitivity Status**: All 9 core parameters confirmed `ROBUST_PLATEAU` (Stability Ratios: 0.99x–1.02x, zero cliff fall-offs across 45 evaluations)
- **Agent Swarm & Skills Status**: 5 permanent specialized agents configured in `.agents/agents/` and 5 modular skills active in `.agents/skills/`

---

## Active Tasks & Work in Progress

- [x] **Milestone 6: Institutional 88+ Quantitative Metrics Engine & Provenance Protocol Upgrade**:
  - Implemented `backtest/metrics.py` computing 92 distinct institutional metrics across 9 dimensions:
    1. Return & Capital Growth (10 metrics: Net PnL, Gross Profit/Loss, Annual PnL, CAGR, Daily & Traded Session Avg, Benchmark Relative).
    2. Risk-Adjusted Ratios (14 metrics: Sharpe, Sortino, Calmar, Omega, Gain-to-Pain, UPI/Martin, Sterling, Burke, Modified Burke, Kappa 3, Pezier Adjusted Sharpe).
    3. Drawdown Topology (12 metrics: Max DD $ & %, Avg DD, CDD Calendar Days, Underwater Exposure %, Ulcer Index, Pain Index, Recovery Factor).
    4. Tail Risk & EVT (10 metrics: Parametric & Historical VaR 95/99, Cornish-Fisher VaR 95, CVaR/Expected Shortfall 95/99, Tail Risk Ratio).
    5. Trade Microstructure & Edge Distribution (16 metrics: Expectancy, Payoff Ratio, Edge Ratio, Scratch Rate, Trimmed PF top 2%, Top 5 Dominance %).
    6. Higher Statistical Moments & Tests (8 metrics: Skewness, Kurtosis, SQN, Student's t-stat, P-value, Jarque-Bera Normality Test).
    7. Multiple Testing & Selection Bias (6 metrics: PSR, DSR, EVT Expected Max Sharpe SR*, MinTRL Track Record Length).
    8. Capital Sizing & Ruin (8 metrics: Full Kelly, Half Kelly, Analytical Gambler's Ruin, Max Win/Loss streaks).
    9. Market Microstructure (8 metrics: MFE, MAE, Edge Efficiency, Exposure %).
  - Upgraded SQLite store `results/backtest_provenance.db` schema with 13 new dedicated indexed columns + JSON extended metrics payload.
  - Upgraded `backtest/provenance.py` and `scripts/query_provenance.py` with alias resolution (`sortino`, `calmar`, `omega`, `cvar95`, `ulcer_index`, `half_kelly`, `trimmed_profit_factor`, etc.).
  - Re-ingested canonical runs in `scripts/ingest_historical_provenance.py` recording full institutional metrics.
  - Implemented comprehensive test suite in `tests/test_institutional_metrics.py` (14/14 passing).

- [x] **Milestone 1**: Karpathy LLM Wiki Architecture Implementation
  - Full `wiki/` directory layout created with `SCHEMA.md`, `index.md`, `log.md`, `hot.md`, `failed_ideas.md`.
  - 9 domain seed pages initialized across strategies, prop firm, sizing, provenance, and execution.
  - Root agent instruction files (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`) integrated with startup/shutdown wiki rules.
  - Git synchronization daemon (`scripts/wiki_sync.py`, `scripts/sync_wiki.sh`) and hook automation installed.
  - Hardened in Iteration 2: Git staging isolation (`-- wiki/`), porcelain whitespace preservation, CWD external invocation resilience, code fence link filtering, and quote-aware frontmatter parser.
  - Automated verification test suites (`tests/test_wiki_integrity.py`, `tests/test_wiki_adversarial_stress.py`) with 40/40 passing tests.
- [x] **Milestone 2**: Live Forward Demo Sample Accumulation
  - Background monitoring daemon (`com.lucidflex.morningwatcher`) active on live MotiveWave chart alerts.
  - Lifecycle sentinel daemon (`com.lucidflex.lifecycle_sentinel`) active managing daily pre-market (08:15 ET), post-market (16:15 ET), and weekly (Fri 17:00 ET) routines.
  - Forward demo trade count stands at $N=1$ ($+\$144.70$, 100% win rate), accumulating toward $N \ge 30$.
- [x] **Milestone 3**: Safe CPPI Sizing Integration in MotiveWave Studies
  - Mirrored Python CPPI cushion math directly into Java studies (`src/motivewave/*.java`) via `resolveContracts(OrderContext ctx, int fallbackContracts)`.
  - Recompiled with JDK 25 and packaged extension JAR deployed to `/Users/novo/MotiveWave Extensions/LucidPropEnsemble.jar`.
  - Hardened -$600 soft stop, <$400 cushion buffer, Finish-Line Shield (1 micro at >=+$1,150), and Pareto ratchet (+200 / +550).
- [x] **Milestone 4**: Live Execution Hardening & MotiveWave CQG Auto-Order Entry Resolution
  - Fixed missing `autoEntry = true` and `manualEntry = false` in `@StudyHeader` across all three studies.
  - Resolved `java.util.UnknownFormatConversionException: Conversion = '+'` crash caused by illegal `%+$%.2f` specifier in MotiveWave log (`StudyWrapper::setData()`).
  - Switched default `ENABLE_LIVE_AUTOTRADE` descriptor to `true` across all studies.
  - Implemented sequential bracket execution for CQG broker routing (Market entry submitted first; Stop Loss and Profit Target brackets submitted upon fill confirmation in `onOrderFilled`).
  - Implemented real-time order intent and lifecycle logging to `results/forward_test/motivewave_alerts.log`.
  - Recompiled with JDK 25 and hot-deployed packaged extension JAR to `/Users/novo/MotiveWave Extensions/LucidPropEnsemble.jar`.
- [x] **Milestone 5**: Strategy Registry, Provenance Tiers & Governance Sync (Audit Remediation Priority 4)
  - Implemented `config/strategy_registry.py` with `StrategyTier` enum (`BASELINE`, `FORWARD_DEMO`, `CANDIDATE`, `REJECTED`) and canonical production baseline registration.
  - Hardened `backtest/provenance.py` with `strategy_tier` column, index, backward compatibility migration, and strict rejection of unauthorized baseline registration.
  - Updated `scripts/query_provenance.py` displaying strategy tiers in `--list` output and supporting `--tier` filtering.
  - Synchronized root agent instructions (`AGENTS.md`, `GEMINI.md`, `CLAUDE.md`) enumerating authorized baseline strategy IDs and tiers.
  - Created candidate incubation documentation at `wiki/strategies/candidate-incubation-lifecycle.md` and cataloged in `wiki/index.md`.
- [x] **Milestone 6**: CQG Broker Execution Synchronizer & Real Trade Ledger Ingestion
  - Discovered MotiveWave's persistent CQG WebAPI journal at `~/Library/MotiveWave/workspaces/Mota/config/journal.csv`.
  - Built `scripts/sync_cqg_executions.py` with FIFO lot matching, symbol mapping (`MES`, `MNQ`, `MGC`, `ENQ`), window classification, and ledger deduplication.
  - Integrated anti-selection-bias model gate: detects and excludes manual/gated fills from contaminating the systematic baseline.
  - Integrated into `scripts/watch_morning_demo_alerts.py` and `scripts/session_sentinel.py`.
  - Built unit test battery in `tests/test_cqg_execution_sync.py` (6/6 passing).
- [x] **Milestone 7**: Repository Audit Verification & Production-Grade Remediation (Priorities 1–4)
  - **Priority 1 (Alpha Factory Provenance)**: Fixed `--record` flag handling, dynamic Git commit resolution, dynamic trade date ranges, authentic `gross_profit` ($41,432.71 vs fabricated $15,916.04), and dynamic DSR trial accounting. Cleansed tainted database record `run_alpha_factory_lucid_flex_ensemble_20261105_200901` from `results/backtest_provenance.db`.
  - **Priority 2 (Execution Realism Engine)**: Implemented gap-through stop resolution (`min`/`max` with `bar_open`), next-bar stop activation default, clean 3-tier fill mode hierarchy (`specific -> top-level -> touch`) without private scaffolding flags, and engine cache hardening (`weakref.ref(self.data)`).
  - **Priority 3 (Agent Permissions & Guardrails)**: Promoted blocked commands check in `backtest/research_protocol.py` to `severity="hard"`, created `backtest/agent_guardrails.py` with runtime command validation and safe subprocess execution with mandatory 300s timeout, and added explicit timeouts to operational scripts.
  - **Priority 4 (Research Governance & Strategy Registry)**: Created `config/strategy_registry.py` formalizing strategy tiers (`BASELINE`, `FORWARD_DEMO`, `CANDIDATE`, `REJECTED`), guarded baseline provenance in `backtest/provenance.py`, synchronized `AGENTS.md` and `GEMINI.md`, and documented candidate lifecycle at `wiki/strategies/candidate-incubation-lifecycle.md`.
  - **Verification**: 162/162 priority & regression tests passed, 731/731 full test suite passed with 0 errors, and unanimous gate approval achieved.
- [x] **Milestone 8**: Conservative Execution Stress & MotiveWave Sizing Safeguards Test Suites
  - Implemented `tests/test_conservative_execution_stress.py` (25 tests): 1-tick/2-tick target trade-through, touch stops, conservative/pessimistic intrabar exit normalization, gap-through stop open fills, next-bar managed stop activation, and full backtest execution stress tests ($PF \ge 1.0$).
  - Implemented `tests/test_motivewave_sizing_safeguards.py` (18 tests): true historical peak balance persistence across drawdowns, trailing floor locking at $25,100 once peak reaches $26,100, cushion calculation & Safe CPPI de-leveraging to 1 contract when cushion < $400, fail-closed contract sizing (0 contracts on null ctx, balance <= 10,000, or exceptions), and fail-closed order execution (`ORDER_BLOCKED_UNVERIFIED_ACCOUNT`).
  - Added targeted regression tests across `tests/test_agent_guardrails.py`, `tests/test_strategy_registry.py`, and `tests/test_alpha_factory_provenance.py`.
  - **Verification**: 145/145 tests passed cleanly in 14.97s; 100% wiki compliance confirmed.

---

## Recent Changes (Last 3–5 Sessions)

- **2026-11-06 (Session M5 - CQG Broker Execution Synchronizer & Real Trade Ingestion)**:
  - Built `scripts/sync_cqg_executions.py`:
    1. Ingests millisecond-accurate CQG order fills from `~/Library/MotiveWave/workspaces/Mota/config/journal.csv`.
    2. Reconstructs multi-lot round-turn trades using chronological FIFO lot matching.
    3. Infers systematic strategy windows (`Macro Momentum 08:35`, `VA Breakout v2.0 09:45`, `Gold London Fix 10:15`) and exit types (`STP`, `LMT`, `TIME_EXIT`).
    4. Reconciles with theoretical signals, computes slippage drag, updates running balance and trailing floor, and deduplicates against `results/forward_test/demo_trades_ledger.csv`.
    5. Supported CLI modes: `--list`, `--sync`, `--watch` (real-time tail daemon), `--since`, `--date`, `--systematic-only`, `--symbols`.
  - Validated anti-selection-bias model gate against 2026-11-04 MES broker fill (BUY 2 @ 7731.00 -> 7736.00): correctly detected that the strategy model had gated this setup (GARCH exhaustion 2.62 SD > 2.50 SD) and prevented the false-positive study bracket fill from contaminating the systematic baseline ($N=1$ trade preserved at +$144.70).
  - Wired CQG sync into `scripts/watch_morning_demo_alerts.py` (prioritizes real CQG broker fills over synthetic bar simulation) and `scripts/session_sentinel.py` (16:15 ET post-market broker sync).
  - Implemented unit tests in `tests/test_cqg_execution_sync.py` (6/6 passing). Updated `wiki/execution/demo-parity-engine.md`.

- **2026-11-06 (Session M4 - Priority 4 Strategy Registry & Provenance Tiers)**:
  - Created `config/strategy_registry.py`:
    1. Defined `StrategyTier` enum (`BASELINE`, `FORWARD_DEMO`, `CANDIDATE`, `REJECTED`).
    2. Registered production baselines: `morning_va_breakout_s1` (BASELINE), `macro_momentum_s2` (BASELINE), `gold_london_fix_s3` (BASELINE), `lucid_flex_ensemble` (BASELINE), `lucid_flex_forward_demo` (FORWARD_DEMO).
    3. Provided utility functions: `get_strategy_tier()`, `is_production_baseline()`, `validate_strategy_id()`, `list_strategies_by_tier()`, `register_candidate()`.
  - Integrated into `backtest/provenance.py`:
    1. Added `strategy_tier` column to SQLite `backtest_runs` table with automatic migration and backward compatibility for all 9 verified runs.
    2. Enforced strategy identity validation in `record_run()`.
    3. Blocked research candidates from masquerading as production baselines (`BASELINE` tier).
  - Updated `scripts/query_provenance.py`: displayed `TIER` column in `--list` output and added `--tier` filter.
  - Synchronized `AGENTS.md` and `GEMINI.md` with `CLAUDE.md` to enumerate authorized baseline strategy IDs and tiers.
  - Authored `wiki/strategies/candidate-incubation-lifecycle.md` documenting the 6-stage candidate gate and provenance segregation.
- **2026-11-06 (Session M3 - Priority 3 Execution Security & Agent Guardrails)**:
  - Hardened `backtest/research_protocol.py`: promoted `blocked_commands_for_agent` check from `severity="warning"` to `severity="hard"` and expanded verification to all 5 `DEFAULT_BLOCKED_AGENT_COMMANDS`. Fixed empty-list parameter fallback bug.
  - Implemented `backtest/agent_guardrails.py`:
    1. `validate_command()` runtime command validator blocking dangerous binaries (`rm`, `sudo`, `curl`, `wget`, `chmod`, `chown`, `kill`, etc.), unauthorized exploratory backtests (`main_backtest.py`, `probe_candidate_frequency.py`, batch shell runners), and shell injection/chaining attempts (`&&`, `;`, `|`, `$(`, `` ` ``, `||`).
    2. `safe_subprocess_run()` enforcing pre-execution validation, mandatory wall-clock timeouts (default 300s), structured error logging, and clean exception handling.
  - Hardened subprocess invocations with explicit timeouts in `scripts/generate_all_dashboards.py` (300s), `scripts/session_sentinel.py` (60s), `scripts/check_morning_readiness.py` (30s), `scripts/ingest_l2_parquet_5year.py` (600s), and `scripts/launch_monday_forward_test.py` (300s).
  - Authored comprehensive test suites in `tests/test_agent_guardrails.py` (15 tests) and `tests/test_research_protocol.py` (13 tests) (28/28 passing).
  - Created wiki documentation at `wiki/execution/agent-execution-guardrails.md`.
- **2026-11-06 (Session M1 - Priority 1 Alpha Factory Provenance Remediation)**:
  - Remediated all 5 confirmed Priority 1 flaws in `scripts/alpha_factory.py`:
    1. Gated database persistence behind `--record`; dry-run default prints standardized verification footer and dry-run notice without writing to SQLite or JSONL.
    2. Dynamically resolved Git commit hash from current HEAD via `store.get_git_commit()`, removing hardcoded `"8cb04d68a9"`.
    3. Derived date boundaries (`date_start`, `date_end`) dynamically from trade dataframe min/max timestamps.
    4. Replaced fabricated gross profit formula (`net_pnl + 1000.0`) with authentic sum of winning trades (`m["gross_profit"]` = $41,432.71).
    5. Dynamically accounted for Deflated Sharpe Ratio (DSR) trials ($N \ge 25$, loaded from `wiki/failed_ideas.md`).
  - Cleansed corrupted run `run_alpha_factory_lucid_flex_ensemble_20261105_200901` from `results/backtest_provenance.db` and synchronized `results/backtest_provenance.jsonl`.
  - Recorded verified authentic run `run_alpha_factory_lucid_flex_ensemble_20261106_043319` with true gross profit ($41,432.71), current HEAD commit, and exact date span.
  - Implemented comprehensive regression test suite in `tests/test_alpha_factory_provenance.py` covering all 5 remediated flaws (11/11 passing).
- **2026-11-05 (Session M4 - Iteration 2 Wiki Hardening & Safety Invariants)**:
  - Enforced Git staging isolation in `scripts/wiki_sync.py:cmd_stop()` using `["--", "wiki/"]`, preventing uncommitted or staged production code from being swept into automated wiki commits.
  - Fixed Git porcelain path truncation by changing `run_git` to `rstrip("\r\n")` and adding defensive prefix parsing in `get_wiki_changes()`.
  - Fixed CWD crash when `scripts/sync_wiki.sh` is invoked from external working directories (added `cd "$REPO_DIR"` and repo root fallback in `wiki_sync.py`).
  - Added fenced code block (``` / ~~~) and inline backtick code span stripping in `scripts/verify_wiki_integrity.py` so illustrative example links in docs do not trigger false positive broken-link errors.
  - Implemented quote-aware comment stripping (`strip_yaml_comment` / `clean_scalar`) so frontmatter titles containing `" #"` are preserved intact.
  - Added 5 regression tests in `tests/test_wiki_integrity.py` and updated `tests/test_wiki_adversarial_stress.py`. All 40 test cases pass cleanly.
- **2026-11-05 (Session M3 - Belfort Step 07 Parameter Plateau Sweep)**:
  - Built and executed `scripts/run_parameter_plateau_sweep.py` in accordance with Step 07 of the Belfort Systematic Trading Framework (2026).
  - Evaluated 9 core parameters across 5 levels (-25%, -12.5%, 0%, +12.5%, +25%) across 543 unified trades (2021-2026).
  - Generated dark-mode sensitivity charts (`plateau_sweep_s1.png`, `plateau_sweep_s2.png`, `plateau_sweep_s3.png`, and `composite_parameter_plateau_overview.png`).
  - Recorded 3 official plateau sweep runs into `results/backtest_provenance.db`.
  - Exported comprehensive research report (`results/parameter_plateau_sweep/parameter_plateau_sensitivity_report.md`). All 9 parameters confirmed `ROBUST_PLATEAU` with stability ratios between 0.99x and 1.02x, and zero cliff fall-offs.
- **2026-11-05 (Session M2 - DSR Implementation)**:
  - Implemented Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio (`deflated_sharpe_ratio`) and EVT expected maximum Sharpe (`expected_max_sharpe`) in `backtest/dashboard_analytics.py`.
  - Added `"dsr"` and `"sr_star"` diagnostics to `performance_metrics()`.
  - Added comprehensive unit test suite in `tests/test_deflated_sharpe.py` verifying PSR reduction ($N=1$), monotonic multiple-testing deflation penalty, unit interval validity, small samples/zero-variance edge cases, and end-to-end `performance_metrics()` integration.
- **2026-11-05 (Session M1)**:
  - Initialized complete Karpathy LLM Wiki pattern in `wiki/`.
  - Documented 24 empirical failed ideas and negative invariants in `wiki/failed_ideas.md`.
  - Integrated startup catalog inspection and shutdown log update protocols in `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`.
  - Implemented zero-dependency `verify_wiki_integrity.py` and comprehensive 10-test pytest suite.
  - Installed git pre-commit hook fast-path validating staged wiki changes.
- **2026-11-03**:
  - Completed Sizing Cushion Optimization and Monte Carlo block-bootstrap simulation (5,000 CRN paths).
  - Empirically discovered the "1-Micro Funded Infant Mortality Trap" and formulated Safe CPPI ($400 floor buffer).
  - Verified Pareto ratchet thresholds (+200 / +550) compressing pass duration by 11 exchange sessions.
- **2026-11-01**:
  - Implemented 3-State Gaussian Hidden Markov Model (HMM) regime switching for Strategy 2 macro momentum.
  - Tested and ruled out high-volatility stop widening (Failed Idea #3) and opposing macro shock pruning (Failed Idea #4).
- **2026-10-30**:
  - Deployed MotiveWave Java custom studies (`LucidMorningVABreakoutStudy`, `LucidMacroMomentumStudy`, `LucidGoldFixBreakoutStudy`).
  - Executed first live forward demo parity trade on MNQ ($144.70 net profit).

---

## Immediate Next Steps & Known Blockers

- **Immediate Next Steps**:
  1. Run `python3 scripts/verify_wiki_integrity.py` to confirm 100% compliance across all wiki documents.
  2. Run `pytest tests/test_wiki_integrity.py` and `pytest tests/test_provenance_system.py`.
  3. Verify git sync script status via `bash scripts/sync_wiki.sh status`.
- **Known Blockers**: None. Local environment is fully functional with Python 3.12, Pytest 9.0.3, and active git branch `main`.
