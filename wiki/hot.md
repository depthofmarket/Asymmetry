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

- [x] **Milestone 8: Comprehensive Repository Reorganization & 5.04 GB Forensic Purge**:
  - **Reclaimed 5.04 GB of Disk Space**: Reduced `results/` from **5,069 MB down to 24 MB** by purging 5,014 MB of unreferenced raw CSV signal exports in `results/research_master/signal_exports/` and 53 MB of abandoned H4 exploration runs.
  - **Eliminated Broken Symlinks in VS Code Sidebar**: Permanently deleted `results/run_aliases/` containing 6 broken symlinks pointing to non-existent directories.
  - **Cleaned Repository Root**: Purged 36 loose, unreferenced scratchpad files and temporary parquets in `scratch/`.
  - **Cleaned Legacy Dumps in `results/`**: Deleted `results/walkforward_2asset_2021_2024/`, `results/audit/`, `results/research_dashboards.py`, and `results/visualize.py`.
  - **Preserved Active Calibration Files**: Maintained the ~2 MB of actively referenced calibration and audit files in `results/research_master/` (`execution_cost_assumptions/`, `research_protocol_audit.jsonl`, `signal_research/`).
  - **Relocated Python Code to `backtest/`**: Moved `heatmap.py`, `analysis.py`, and `research_animations.py` from `results/` into `backtest/`, updated their 4 import callers, and removed `results/__init__.py`. `results/` is now strictly an artifact vault.
  - **Zero Regressions**: Verified 48/48 tests green across all active test suites, pre-market readiness 100% green, and wiki integrity 15/15 checks green.

- [x] **Milestone 7: Investing Algorithm Framework Deep Architectural Extraction & Microstructure Expansion**:
  - **Option A: 143 Institutional Metrics Expansion (`backtest/metrics.py`)**: Extracted deep microstructure, excursion, and walk-forward stability families from `coding-kitties/investing-algorithm-framework`:
    1. *Directional Symmetry*: `long_win_rate`, `short_win_rate`, `long_profit_factor`, `short_profit_factor`, `winning_long_trades`, `losing_short_trades`, `long_net_pnl`, `short_net_pnl`, `long_short_edge_asymmetry`.
    2. *Excursions & Edge Efficiency*: `mean_mfe`, `mean_mae`, `max_mfe`, `max_mae`, `mfe_mae_ratio` ($\mathbb{E}[\text{MFE}] / \mathbb{E}[\text{MAE}]$), `edge_efficiency_ratio` ($\text{Net PnL} / \sum \text{MFE}$).
    3. *Temporal Duration & Discipline*: `avg_hold_time_mins`, `avg_win_duration_mins`, `avg_loss_duration_mins`, `holding_duration_asymmetry` ($\text{HDA} = \bar{\tau}_{\text{loss}} / \bar{\tau}_{\text{win}}$) quantifying loss-aversion discipline breakdown, `exposure_ratio` and `market_exposure_pct`.
    4. *Cadence & Frequency*: `trades_per_day`, `trades_per_week`, `trades_per_month`, `trades_per_year`.
    5. *Calendar Periodicity*: `percentage_winning_months`, `percentage_winning_years`, `avg_monthly_pnl_winning_months`, `avg_monthly_pnl_losing_months`, `best_month_pnl`, `worst_month_pnl`, `best_year_pnl`, `worst_year_pnl`.
    6. *Multi-Window Walk-Forward Stability*: `return_consistency`, `win_rate_consistency`, `sharpe_consistency`, `consistency_score`, `stability_score`.
  - **Option A: MotiveWave Java Study Single-Trade Session Cooldown Lock (`DAILY_SUBMITTED_DATES`)**:
    - Eliminated multi-trade triggers and chart recalculation re-entries across `LucidMacroMomentumStudy.java`, `LucidMorningVABreakoutStudy.java`, and `LucidGoldFixBreakoutStudy.java`.
    - Implemented JVM-static thread-safe session lock `DAILY_SUBMITTED_DATES = ConcurrentHashMap.newKeySet()` verifying `!DAILY_SUBMITTED_DATES.contains(today)` before any order submission and marking all session candidate trade structs as submitted.
    - Recompiled with JDK 25 (`tools/jdk25/Contents/Home/bin/javac`), packaged and deployed extension JAR `/Users/novo/MotiveWave Extensions/LucidPropEnsemble.jar` (64 KB).
    - Verified 100% green via `python scripts/check_morning_readiness.py`, `tests/test_institutional_metrics.py` (16/16), and MotiveWave test suites (28/28).
  - **Option B: Declarative Confluence Scoring Cards & Decision Trace Architecture (`backtest/confluence.py`)**:
    - Created modular, declarative rule engine inspired by IAF architecture: `Operator` enum, `EvaluationContext` with historical and current bar values, composable Boolean expressions (`Condition`, `AllOf`, `AnyOf`, `Not`, `AtLeast`).
    - Engineered multi-tier weighting and veto protection: `PrimaryGroup`, `SecondaryGroup`, and `VetoGroup`. Any triggered veto rule overrides total score and invalidates setup.
    - Designed explainable, audit-ready `DecisionTrace` with JSON serialization capturing all evaluated conditions, threshold diffs, rule scores, and veto flags.
    - Verified 5/5 unit tests in `tests/test_confluence.py`.
  - **Option B: Native Asymmetry Model Context Protocol (MCP) Server Expansion (`scripts/asymmetry_mcp_server.py`)**:
    - Doubled native MCP server tool registry from 5 to 10 tools, adding:
      1. `asymmetry_get_equity_curve`: Downsampled daily equity, HWM, and drawdown trajectory.
      2. `asymmetry_get_trades`: Filterable trade execution ledger (direction, outcome, limit, sort).
      3. `asymmetry_get_monthly_returns`: 12-month calendar return grid with annual totals and win rates.
      4. `asymmetry_rank_strategies`: Cross-sectional quantitative leaderboard ranking registered runs.
      5. `asymmetry_log_research_note`: Direct LLM agent logging to `wiki/log.md` with grep-parseable headers.
    - Verified 14/14 unit tests in `tests/test_asymmetry_mcp_server.py` under standard JSON-RPC 2.0 stdio streaming.
  - **Option B: Karpathy LLM Wiki Architecture Documentation**:
    - Authored comprehensive topic page `wiki/strategies/declarative-confluence-engine.md`.
    - Updated catalog `wiki/index.md` and active context `wiki/hot.md`.

- [x] **Milestone 6: Institutional Quantitative Framework Upgrade (98 Metrics, .obtf Bundles & MCP Server)**:
  - **Step 1: 98 Institutional Metrics Engine (`backtest/metrics.py`)**: Vectorized pure-Python analytics covering Return Dynamics (10 + Benchmark Relatives), Risk-Adjusted Ratios (14: Sortino, Calmar, Omega, Gain-to-Pain, UPI, Burke, Kappa 3), Drawdown Topology (12: CDD, Ulcer, Pain Index), Tail Risk (10: Cornish-Fisher VaR, CVaR 95/99), Microstructure (16: Expectancy, Trimmed PF ex-2%, Top 5 Win Dominance, Top 5% Adversarial Truncation), Statistical Moments (8: Skew, Kurtosis, SQN, Jarque-Bera), Multiple Testing (6: PSR, DSR, EVT SR*), Sizing/Ruin (8: Full/Half Kelly, Gambler's Ruin), and Passive Benchmark Relatives (Beta, Alpha, Correlation, Tracking Error, Up/Down Capture).
  - **Step 2: Adversarial Top 5% Winner Truncation Stress Test**: Proved that the economic edge holds strictly above breakeven ($PF > 1.00$, positive expectancy) across all 3 strategies and the ensemble even after permanently deleting the top 5% best winning trades (Ensemble Trimmed PF: 1.34 > 1.00 with +$9,082.76 net; S1 Trimmed PF: 1.40; S2 Trimmed PF: 1.28; S3 Trimmed PF: 1.30).
  - **Step 3: Passive NQ Buy & Hold Comparative Analytics**: Benchmarked the strategy against passive holding of NQ across 1,499 continuous exchange sessions (2021–2026). Proved market neutrality ($\beta = 0.01$, $\rho = 0.04$, Annual Jensen's $\alpha = +9.8\%$), 7.5x lower drawdown (-$1,511.51 vs -$11,273.88 / -35.2%), 3.6x higher Sortino (2.22 vs 0.62), and 12x lower Ulcer Index (1.06% vs 12.83%).
  - **Step 4: ACID SQLite Provenance Store Upgrade (`backtest/provenance.py`)**: Migrated `results/backtest_provenance.db` schema with indexed columns (`sortino_ratio`, `calmar_ratio`, `cvar_95`, `ulcer_index`, `half_kelly`, `bundle_path`, `trimmed_pf_5pct`, `edge_holds_5pct`, `beta`, `alpha`, `correlation`, etc.) and multi-key alias resolution in CLI.
  - **Step 5: Open Backtest Format (`.obtf`) Portable Containers (`backtest/bundle.py`)**: Implemented compressed ZIP container standard packaging `manifest.json`, `trades.parquet`, `equity.parquet`, and `audit_log.json`. Generated canonical `.obtf` bundles across all baseline strategies.
  - **Step 6: Native Asymmetry Model Context Protocol Server (`scripts/asymmetry_mcp_server.py`)**: Built standard JSON-RPC 2.0 stdio server exposing 5 tools (`asymmetry_query_stat`, `asymmetry_list_runs`, `asymmetry_compare_strategies`, `asymmetry_inspect_bundle`, `asymmetry_verify_data_hash`).
  - **Step 7: Dashboard Visual Tearsheet Synchronization & Benchmark Comparative Architecture**: Synchronized all visual PNG sheets (`01_strategy_equity_curves_and_drawdown.png`, `05_strategy_stress_tests_and_markov_regimes.png`, `06_strategy_comprehensive_scorecard_master.png`, master posters) and interactive HTML report. Engineered dedicated 3-tier, 4-panel comparative layout in Sheet 01 with solid `#475569` benchmark equity line, 2022 Tech Bear Market callout arrow, comparative overview badge, dual-curve percentage drawdown with -$1,000 prop floor, cumulative excess alpha spread, and 4-column Swiss scorecard table. Upgraded Master Poster with dual-axis drawdown resolution ($0 to -$2,000 left vs $0 to -$12,000 right).
  - **Testing & Verification**: 67/67 institutional tests passing (`tests/test_benchmark_and_trimming.py`, `tests/test_institutional_metrics.py`, `tests/test_bundle.py`, `tests/test_asymmetry_mcp_server.py`, `tests/test_provenance_system.py`). Full suite 820+ tests green. All 6 publication PNGs and master poster verified via direct visual inspection.

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

- **2026-11-07 (Session M6 - Portfolio Expansion & Non-News Candidate Falsification S4-S12)**:
  - Systematically evaluated 9 candidate trading strategies to expand portfolio from 3 to 5-6 strategies and increase trade frequency:
    1. Candidate S4 (Crude Oil 09:00 pit open `MCL`): Falsified (PF 0.93, -$1,380 net, 3.7x max DD breach). Failed Idea #25.
    2. Candidate S5 (4-Index Sector Rotation `MYM`/`M2K`): Falsified (PF 0.82, -$13,885 net). Failed Idea #26.
    3. Candidate S6 (COMEX Gold 08:20 Open `MGC`): Falsified (PF 0.81, -$11,427 net, dealer inventory trap). Failed Idea #27.
    4. Candidate S7 (10:30 Initial Balance Extension `MES`/`MNQ`): Falsified (PF 0.90, -$13,745 net, gamma pinning). Failed Idea #28.
    5. Candidate S8 (15:50 NYSE MOC Imbalance Drive `MNQ`/`MES`): Falsified (PF 0.89, -$5,848 net, 0DTE stop chop). Failed Idea #29.
    6. Candidate S9 / H26 (11:30 European Cash Close Rotation `MES`/`MNQ`): Falsified (Fade PF 0.78, -$11,018 net across 1,492 trades; Trend IS PF 1.03–1.09, failing Belfort Step 04 PF >= 1.25). Failed Idea #30.
    7. Candidate S10 / H27 (09:35 Dalton Overnight Inventory Imbalance Correction `MES`/`MNQ`): Falsified (566 trades, PF 0.71, Net -$6,330.59, negative across all 6 years; stops hit 2:1 over target). Failed Idea #31.
    8. Candidate S11 / H28 (09:45 Micro Gold Morning VA Breakout `MGC`): Falsified (367 trades, PF 1.02, Net $266.42, In-Sample negative at PF 0.91, 66.3% outlier dominance). Failed Idea #32.
    9. Candidate S12 / H29 (14:27 WTI Crude Oil NYMEX Settlement Auction `MCL`): Falsified (365 trades, Drive Into Settle PF 0.50, Net -$1,318.60; Post-Settle Fade PF 0.48, Net -$1,392.60; TAS block absorption). Failed Idea #33.
    10. Candidate S13 / H30 (10:00 ET Small-Cap Beta Diffusion Lag `M2K`): **Falsified & Vetoed by Red-Team Auditor**. Initial walkforward (52 trades, PF 1.33, Net +$326.10 over 5.8 yrs) broken under adversarial stress:
        - Parameter Plateau Cliff: Stop-loss sensitivity (+12.5% to 9.0 pts) dropped PnL to $220.60 (Stability Ratio 0.68x < 0.70x).
        - Statistical Insignificance: t-statistic = 0.92, p-value = 0.3578 (35.8% chance of pure random noise).
        - Severe Capital Inefficiency: 9 trades/year (0.75 tr/mo), EV = $0.15/day, 2 consecutive losing years (2024 PF 0.52, 2025 PF 0.84), 80.8% underwater time, 980-day recovery.
        - Outlier Dominance: Top 3 trades = 71.6% of net profit; ex-top 5% PF collapses to 1.09. Failed Idea #34.
    11. Candidate S14 / H32 (13:00 ET Post-Lunch Institutional Capital Deployment `MNQ`): **Falsified & Vetoed by Red-Team Auditor**. Full walkforward across 430 trades generated PF 0.75, Net -$2,711.00, Win Rate 32.6%, MaxDD -$2,849.00 (Sharpe -1.86). In-Sample PF 0.83 (-$1,213.00, failing Belfort Step 04 PF >= 1.25), Out-of-Sample PF 0.59 (-$1,498.00). Negative in 4 of 6 years. Stops hit 188 times vs targets 55 times (3.4:1 stop-to-target realization ratio). 13:00 false breakouts caused by midday liquidity vacuum and 0DTE gamma pinning. Failed Idea #35.
    12. Candidate S15 / H31 (10:15 ET Value vs Growth Factor Dispersion Momentum `MYM`): **Falsified & Vetoed by Red-Team Auditor**. Full walkforward across 198 trades generated PF 0.80, Net -$503.70, Win Rate 31.8%, MaxDD -$728.90 (Sharpe -1.46). In-Sample PF 0.88 (-$195.50, failing Belfort Step 04 PF >= 1.25), Out-of-Sample PF 0.69 (-$308.20). In 2026, win rate collapsed to 14.6% (PF 0.34, -$480.90). Stops hit 85 times vs targets 30 times (2.8:1 stop-to-target ratio). Intraday opening factor dispersion is mean-reverting due to quantitative stat-arb NQ/YM spread fading. Failed Idea #36.
    13. Candidate S16 / H33 (10:50 ET London 4 PM Global Benchmark Fix Equity Drive `MES`): **Falsified & Vetoed by Red-Team Auditor**. Full walkforward across 342 trades generated PF 0.72, Net -$1,692.55, Win Rate 34.8%, MaxDD -$1,967.35 (Sharpe -2.20). In-Sample PF 0.66 (-$1,414.05, failing Belfort Step 04 PF >= 1.25), Out-of-Sample PF 0.86 (-$278.50). Negative in 5 of 6 years (2022 PF 0.31, -$1,127.85). Stops hit 139 times vs targets 35 times (4.0:1 stop-to-target ratio). London 4 PM Fix is an FX hedging benchmark that transmits no directional drift to US equities; 10:50 ET buys the terminal exhaustion of morning drives ahead of European close book-squaring. Failed Idea #37.
    14. Candidate S17 / H38 (10:15 ET 0DTE Dealer Gamma Absorption & IB Re-entry Trap `MES`): **Catastrophically Falsified & Vetoed by Red-Team Auditor**. Full walkforward across 315 trades generated PF 0.54, Net -$2,870.04, Win Rate 29.5%, MaxDD -$2,843.04 (Sharpe -4.23). In-Sample (2021–2024) generated PF 0.43 (-$2,577.33, failing Belfort Step 04 PF >= 1.25), Out-of-Sample PF 0.84 (-$292.71). 100% calendar year failure (negative in all 6 years). Stops hit 155 times vs targets 87 times (nearly 2:1 stop penalty). Shallow IB re-entries are standard liquidity re-tests before trend continuation; dealer dynamic hedging acts as a trend accelerant rather than a pin. Failed Idea #38.
  - Recorded verified runs into `results/backtest_provenance.db` under quarantined `StrategyTier.CANDIDATE`. Baseline tier remains 100% untainted.

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
