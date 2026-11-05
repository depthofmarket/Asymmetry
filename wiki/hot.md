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

- [x] **Milestone 1**: Karpathy LLM Wiki Architecture Implementation
  - Full `wiki/` directory layout created with `SCHEMA.md`, `index.md`, `log.md`, `hot.md`, `failed_ideas.md`.
  - 9 domain seed pages initialized across strategies, prop firm, sizing, provenance, and execution.
  - Root agent instruction files (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`) integrated with startup/shutdown wiki rules.
  - Git synchronization daemon (`scripts/wiki_sync.py`, `scripts/sync_wiki.sh`) and hook automation installed.
  - Hardened in Iteration 2: Git staging isolation (`-- wiki/`), porcelain whitespace preservation, CWD external invocation resilience, code fence link filtering, and quote-aware frontmatter parser.
  - Automated verification test suites (`tests/test_wiki_integrity.py`, `tests/test_wiki_adversarial_stress.py`) with 40/40 passing tests.
- [ ] **Milestone 2**: Live Forward Demo Sample Accumulation
  - Continue background monitoring daemon (`scripts/watch_morning_demo_alerts.py`) on live MotiveWave chart alerts.
  - Expand forward demo trade count from $N=1$ toward $N \ge 30$ to clear the `LOW_SAMPLE_SIZE` warning flag.
- [ ] **Milestone 3**: Safe CPPI Sizing Integration in MotiveWave Studies
  - Mirror Python CPPI cushion math directly into Java studies for automated real-time contract scaling.

---

## Recent Changes (Last 3–5 Sessions)

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
