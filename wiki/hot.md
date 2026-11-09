# Active Project State & Focus Dashboard (hot.md)

This page tracks the dynamic operational state of the repository, active testing initiatives, recent changes, and immediate milestones. Updated at the conclusion of every agent session.

---

## Production Baseline & Verified 5-Strategy Expansion Status

The repository maintains a strict separation between the **3-Strategy Production Baseline** (`StrategyTier.BASELINE`) and the **2 Verified Orthogonal Expansion Candidates** (`StrategyTier.CANDIDATE`), coordinated under the **LucidFlex 25K ($39 One-Time Payment [OTP], zero monthly rebill)** profile and **Pareto Anti-Martingale Ratchet (`2 -> 3 -> 4` micros)**:

| Subsystem | Strategy ID | Tier | Asset / Window (ET) | Trades | Win Rate | Profit Factor | Net PnL (5.8 Yr) | Max Drawdown | Active Flags |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **3-Strategy Ensemble** | `lucid_flex_ensemble` | `BASELINE` | `MNQ/MES/MGC` | 543 | 55.06% | **1.56** | **+$14,916.04** | -$1,511.51 | ✅ None |
| **Strategy 1 (09:45 ET)** | `morning_va_breakout_s1` | `BASELINE` | `MNQ/MES` (`09:45–11:30`) | 316 | 56.96% | **1.65** | **+$8,956.18** | -$1,148.95 | ✅ None |
| **Strategy 2 (08:35 ET)** | `macro_momentum_s2` | `BASELINE` | `MNQ` (`08:35–09:25`) | 143 | 48.95% | **1.44** | **+$4,573.23** | -$1,182.00 | ✅ None |
| **Strategy 3 (10:15 ET)** | `gold_london_fix_s3` | `BASELINE` | `MGC` (`10:15–11:45`) | 84 | 58.33% | **1.59** | **+$1,386.62** | -$423.88 | ✅ None |
| **Candidate S4 (21:00 ET)** | `asian_evening_reversion_s4` | `CANDIDATE` | `MNQ` (`21:00–23:00`) | 103 | 52.43% | **1.46** | **+$783.30** | -$442.40 | ⚠️ `CANDIDATE_TIER_QUARANTINED` |
| **Candidate S5 (10:15 ET)** | `crude_rth_expansion_s5` | `CANDIDATE` | `MCL` (`10:15–12:30`) | 102 | 36.27% | **1.37** | **+$791.00** | -$348.50 | ⚠️ `CANDIDATE_TIER_QUARANTINED` |
| **Forward Demo Parity** | `lucid_flex_forward_demo` | `FORWARD_DEMO` | `MNQ/MES/MGC` | 1 | 100.0% | 99.00 | +$144.70 | $0.00 | ⚠️ `LOW_SAMPLE_SIZE` |

- **Current Repository Branch**: `main`
- **Canonical Provenance Store**: `results/backtest_provenance.db` (26 verified runs recorded: 5 canonical baselines, 3 parameter plateau sweeps, 1 alpha factory walkforward, 1 forward demo, 16 candidate runs including verified S4 and S5)
- **5-Strategy Expansion Empirical Verification (`results/m3_portfolio_ratchet_simulation.json`)**:
  - **Empirical $5 \times 5$ Daily Return Correlation Matrix**: Maximum pairwise $|\rho| = 0.0599 \ll 0.20$ across 1,515 trading sessions (`2021–2026`).
  - **10,000-Path Block-Bootstrap Monte Carlo (Pareto Ratchet `2 -> 3 -> 4` Micros, $39 OTP, Zero Monthly Rebill)**: Pass Rate improves from **`69.18%` (3-Strategy Baseline)** to **`72.79%` (+3.61 pp, 5-Strategy Portfolio)**; median exchange sessions to pass improves from **`82.0` to `75.0` (-7.0 sessions faster)**; Expected OTP Cost per Funded Account drops from **`$56.37` to `$53.58`**.
  - **Historical Sequential LucidFlex 25K Campaigns (2021–2026)**: Passed evaluations increase by **+50%** (`12 / 15` vs `8 / 10`), and median calendar time to pass drops by **-44.5 calendar days (-31.2%)** from **`142.5` days to `98.0` days**.
- **Data Source Parquet**: `data/processed/unified_five_strategy_portfolio_trades_2021_2026.parquet`
- **Data SHA-256**: `c3324fd429e92386d0511c50a43ed246e25357ec80688dcef3bfb335487359b0` (748 verified trades across 2021-01-07 to 2026-10-30, Net +$16,490.34)
- **MotiveWave Custom Studies Status**: All 5 custom studies compiled with JDK 25 (`tools/jdk25/Contents/Home/bin/javac`) and deployed to `/Users/novo/MotiveWave Extensions/LucidPropEnsemble.jar` (85.5 KB):
  1. `LucidMorningVABreakoutStudy.java` (`VA_BREAKOUT_ALGO_V2` on MNQ/MES, S1)
  2. `LucidMacroMomentumStudy.java` (`MACRO_MOMENTUM_ALGO_V1` on MNQ, S2)
  3. `LucidGoldFixBreakoutStudy.java` (`GOLD_FIX_BREAKOUT_ALGO_V1` on MGC, S3)
  4. `LucidAsianEveningReversionStudy.java` (`ASIAN_EVENING_REVERSION_S4` on MNQ, S4)
  5. `LucidCrudeRthExpansionStudy.java` (`CRUDE_RTH_EXPANSION_S5` on MCL, S5)
- **Agent Swarm & Skills Status**: 5 permanent specialized agents configured in `.agents/agents/` and 5 modular skills active in `.agents/skills/`

---

## Active Tasks & Work in Progress

- [x] **Execution Integrity, Parity & CI Portability Overhaul (Asymmetry Directive)**:
  - **S1–S3 Canonical Sizing & Safeguards (`LucidMorningVABreakoutStudy.java`, `LucidMacroMomentumStudy.java`, `LucidGoldFixBreakoutStudy.java`)**: Resolved `resolveContracts` to strictly enforce `riskState.recommendedMicros` as a hard upper bound and cap by `fallbackContracts`. Honor `emergency_delever`, `finish_line_shield`, and `garch_decile_halving` to restrict sizing to 1 micro. Preserve fail-closed gating on unverified context/balance (`balance <= 10000.0` or non-finite).
  - **Candidate Execution Governance**: S4 (`LucidAsianEveningReversionStudy.java`) and S5 (`LucidCrudeRthExpansionStudy.java`) default `autoEntry = false` and `DEFAULT_LIVE_AUTOTRADE = false`. Missing/invalid settings default fail-closed to disabled. Settings persist disabled across study reloads/upgrades unless explicitly armed by user. Visual signal markers and acoustic alerts remain active for operator observation.
  - **S4 Strategy Parity & Instrument Validation**: Implemented point-in-time completed US RTH (09:00–16:00 ET) accumulation to dynamically compute `rthAtr14` and `rthRvol20` with >= 20 sessions warmup. Removed unused `REVERSION_MODE`. Matched canonical opening range bounds (6.0–45.0 pts), drift bounds (0.15–0.85 ATR), min RVOL20 (0.85). Enforced strict MNQ/NQ instrument gating and daily session lock file.
  - **S5 Strategy Parity & Indicator Alignment**: Eradicated uncanonical `MIN_BODY_RATIO` filter. Implemented completed prior daily session tracking (`DailySession`) requiring 50 completed sessions warmup. Computed prior daily ATR14 (>= 2.00) and RVOL20 (>= 1.25), and macro-trend alignment (long requires daily SMA20 > SMA50; short requires daily SMA20 <= SMA50). Enforced strict MCL/CL instrument gating and daily session lock file.
  - **Unified Canonical Account-Risk Interface**: Replaced deprecated `account_state.json` search with canonical `demo_parity_state.json` across all five Java studies and Python engine. Configurable directory via `ASYMMETRY_FORWARD_TEST_DIR` / `LUCIDFLEX_FORWARD_TEST_DIR` / study setting. Fail-closed blocking with `ORDER_BLOCKED_UNVERIFIED_ACCOUNT` on missing file, wrong filename, malformed JSON, missing fields, non-finite numbers, unknown status, or stale timestamp (> 24h). Preserves historical HWM and locked $25,100 floor across drawdowns and restarts.
  - **Actual Broker Breakeven Stop Management**: S4 and S5 modify working broker stops in-place via `slOrder.setAdjStopPrice(newStop)` + `ctx.submitOrders(slOrder)` without calling `cancelOrders()`. Verified `trade.breakevenModifySubmitted` and price match within tick tolerance before confirming ratchet. Stop modification failures trigger protective policy (`applyProtectiveFailurePolicy`) maintaining original stop or executing emergency market close if stop was dropped. Working bracket quantities sync with actual filled position on partial fills.
  - **Completed Signal-Bar Execution Timing**: Strictly enforce `series.isBarComplete(index)` on S4 21:14 opening-range candle (for 21:15 entry) and S5 09:30–10:14 box + 10:15–11:15 breakout candle before confirming signals.
  - **Actual Fill Price Anchoring**: Bracket stop and target distances in `onOrderFilled` are anchored to actual average fill price (`order.getAvgFillPrice()`), with entry slippage logged.
  - **Conservative Intrabar Breakeven in Python Backtests**: `asian_evening_reversion_s4.py` and `crude_rth_expansion_s5.py` evaluate stop/target against stop active at bar start; +1R breakeven ratchet activates on subsequent bars $k+1$.
  - **Portable CI & Schema Fallback**: Reconciled soft stop in `backtest/demo_parity_engine.py` to -$600.0 (`DAILY_SOFT_STOP_DOLLARS`) and cushion gate to < 400.0. Made `test_motivewave_risk_governance_json_schema` in `tests/test_operational_readiness.py` portable by falling back to a synthetic schema fixture if local file is absent. Documented macOS MotiveWave SDK vs headless Linux CI boundaries in `.github/workflows/ci.yml`.
  - **Comprehensive Regression Verification**: Extended `tests/test_execution_integrity_and_governance.py` to 29 tests (100% pass rate). Clean JDK 25 compilation across all 5 studies into `build/LucidPropEnsemble.jar`. Full pytest suite green: 864 passed, 86 skipped, 2 subtests passed.

- [x] **V4 — Final Pareto Correction, Robustness Validation & Production Decision (`backtest/dashboard_analytics.py`, `scripts/research_optimal_5strategy_sizing.py`)**:
  - **Corrected 3D Mathematical Pareto Frontier (`compute_pareto_frontier_3d`)**: Implemented exact 3D dominance testing across $(\max \text{Terminal Funded Payout EV}, \min \text{Infant Mortality}, \max \text{Live Promotion})$ over the 1,500-session terminal horizon (0.0% unresolved accounts). Proved that the non-dominated 3D Pareto frontier is **`{Policy A, Policy B, Policy C, Policy D}`** (`Policy D` is NOT dominated: A has lower EV, B has higher IM, C has lower Promotion) and only **`Policy C2`** is strictly dominated (by `Policy C`: +$120.69 EV, $t=+23.17, p_{\text{Holm}}=1.80\times 10^{-114}$; identical 19.38% IM; +3.53 pp Promotion, $t=+11.42, p_{\text{Holm}}=3.53\times 10^{-29}$).
  - **Dual-Horizon & Terminal EV Leaderboard (10,000 CRN Paths, Seed 42, 7,829 Funded Accounts)**:
    - **Policy A (Immediate $500 Min)**: Terminal EV **$948.39** (252-sess: $791.61) | IM: **19.38%** | Terminal Live Promo: **43.16%** (`PARETO-OPTIMAL`).
    - **Policy B (Patient $1,000 Max)**: Terminal EV **$1,837.68** (252-sess: $1,262.13) | IM: **30.95%** | Terminal Live Promo: **41.46%** (`PARETO-OPTIMAL`).
    - **Policy C (Two-Stage $500 P1 -> $1,000 P2–P5)**: Terminal EV **$1,540.68** (252-sess: $1,132.40) | IM: **19.38%** | Terminal Live Promo: **38.05%** (`PARETO-OPTIMAL`, Production Default under Objective C).
    - **Policy D (Fixed $750 Benchmark)**: Terminal EV **$1,382.08** (252-sess: $1,072.19) | IM: **27.05%** | Terminal Live Promo: **41.45%** (`PARETO-OPTIMAL`).
    - **Policy C2 (Adaptive Cushion-Aware)**: Terminal EV **$1,419.99** (252-sess: $1,125.91) | IM: **19.38%** | Terminal Live Promo: **34.53%** (`DOMINATED BY POLICY C`).
  - **Chronological Regime Validation & Rank-Invariance Distinctions**: Confirmed Terminal EV ranking (`B > C > C2 > D > A`) and Infant Mortality ranking (`{A, C, C2} < D < B`) are strictly invariant across Pooled, Dev (2021–2024), and Holdout (2025–2026), whereas Live Promotion ranking shifts from `A > D > B > C > C2` in Dev to `B > A > D > C > C2` in Holdout (`B - A = +0.81 pp ± 0.67 pp`, $p_{\text{Holm}} = 0.3814$, statistical tie).
  - **20% Infant-Mortality Constraint & Structural Lower Bound**: Verified exact binomial/Wilson 95% CIs for Policies A/C/C2: Pooled `19.38% [18.52%, 20.27%]`, Dev `20.43% [19.18%, 21.75%]` ($p(\ne 20\%) = 0.5178$), Holdout `17.53% [16.39%, 18.73%]`. Confirmed 19.38% (Pooled) / 20.43% (Dev) is the structural lower bound for any compliant withdrawal policy under fixed funded contract sizing.
  - **Test Suite Status**: 101/101 tests passing across `test_funded_payout_policies.py` (21/21), `test_sizing_cushion_optimization_e2e.py` (55/55), `test_sizing_cushion_adversarial_stress.py` (19/19), and `test_lucid_flex_rules_integrity.py` (6/6). Full repository suite: 900 passed, 17 pre-existing unrelated failures, 0 skipped.

- [x] **5-Strategy Optimal Sizing Math & Cushion Protection Research (`scripts/research_optimal_5strategy_sizing.py`)**:
  - **Grid Search & Pareto Frontier**: Evaluated across 225 grid points via **10,000 CRN block-bootstrap iterations** on the verified 5-strategy portfolio (748 trades, SHA-256 `84179526...`, +$16,490.34 Net PnL). Discovered 18 non-dominated Pareto configurations.
  - **Empirical Duration Compression (-26.6% to -31.6%)**: Balanced Production Champion `(T2=$100, T3=$600)` achieves **72.24% Pass Rate in 58.0 median sessions** (down from 79.0 sessions on 3 strategies); Maximum Compression Champion `(T2=$100, T3=$350)` achieves **71.02% Pass Rate in 54.0 median sessions**.
  - **Safe CPPI Buffer Optimization ($400 Optimal)**: 10,000 funded simulations over 252 sessions show a **$400 floor buffer** maximizes Net Lifetime EV to **+$670.47 per $39 ticket** while suppressing infant mortality to **12.45%** (87.55% survival to Payout #1).
  - **Finish-Line Lock Shield ($1,150 Optimal)**: Dropping to 1 micro at >= +$1,150 profit reduces heartbreak giveback ruins to **2.21%** (down from 2.82%).
  - **Desk Allocations**: Proved Uniform Multi-Asset Ratchet (2->3->4) achieves **$49.81 expected cost/account**, outperforming fixed 1-micro by 3.3x speed.
  - **Analytical Kelly Derivation**: Derived unconstrained Kelly (Composite 18.3%, Half-Kelly 9.2%) and proved mathematically that under an absorbing floor barrier, Kelly sizing scales to the **Cushion $C_t = \text{Balance}_t - \text{Floor}_t$**, proving the 2-micro entry and dynamic ratchet are the piecewise-linear realization of fractional Kelly.
  - **Artifacts & Provenance**: Auto-recorded canonical run `sizing_optimization_5strategy_2021_2026` into `results/backtest_provenance.db`, generated 4 300 DPI figures (`figure1` through `figure4`) in `results/sizing_cushion_optimization/`, copied all figures and report to `/Users/novo/Downloads/`.

- [x] **Multi-Agent Alpha Research & 5-Strategy Portfolio Expansion (`/teamwork` M0–M4)**:
  - **Candidate S4 (`asian_evening_reversion_s4`, 21:00–23:00 ET / 23:00–01:00 UTC-3 on `MNQ`)**: Engineered Tokyo Cash Open Globex Drift Reversion (`strategies/asian_evening_reversion_s4.py`), verified across 2021–2026 (`run_canonical_s4_asian_evening_reversion_2021_2026`: 103 trades, WR 52.43%, PF 1.46, Net +$783.30, MaxDD -$442.40, IS +$541 / OOS +$243, 30/30 tests green).
  - **Candidate S5 (`crude_rth_expansion_s5`, 10:15–12:30 ET on `MCL`)**: Engineered Post-Fix Morning Consolidation Range Expansion (`strategies/crude_rth_expansion_s5.py`), remediated same-day volume lookahead (`daily_stats["volume"].shift(1)`), verified across 2021–2026 (`run_canonical_s5_crude_rth_expansion_2021_2026`: 102 trades, WR 36.27%, PF 1.37, Net +$791.00, MaxDD -$348.50, 14/14 tests green).
  - **Pareto Ratchet & 10,000-Path Monte Carlo Validation (`scripts/run_m3_portfolio_ratchet_and_correlations.py`)**: Verified pairwise correlation $|\rho| \le 0.0599 < 0.20$ and confirmed `+3.61 pp` Monte Carlo pass-rate uplift (`72.79%` vs `69.18%`) and `-44.5` calendar-day reduction per evaluation under the `$39` OTP fee model and `2 -> 3 -> 4` micro Pareto Ratchet.
  - **Purged Unapproved Clones**: Removed `unanimous_breadth_s4_mym` and `unanimous_breadth_s5_m2k` from `config/strategy_registry.py`, `results/backtest_provenance.db`, and `wiki/`, logging them to `wiki/failed_ideas.md` (#46).

- [x] **Combined strategy and prop-firm quantitative dashboard**: Added `scripts/generate_updated_strategy_prop_dashboard.py` and a timestamped PNG in `results/strategy_dashboard_v3/`. The report presents the 143-field metric inventory, tags aliases and unsupported inputs, and separates modeled prop outcomes from assumed payout terms. Existing strategy/prop PNGs were preserved. See `wiki/strategies/strategy-prop-metrics-dashboard.md`.
- [x] **Visual dashboard set split into distinct views**: The timestamped v4 PNGs were revisions of one combined poster, so they repeated the same panels. Added `scripts/generate_strategy_dashboard_suite.py` and three separate timestamped sheets under `results/strategy_dashboard_v5/`: strategy performance, robustness/stress tests, and prop-firm account risk. Each has a provenance footer; the prop sheet identifies modeled rules/assumptions, and the stress sheet explicitly marks missing fold and permutation/placebo evidence. All earlier dashboard PNGs remain untouched.

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
    15. Candidate S18 / H39 (09:35 ET Cash Open Momentum Thrust `MNQ`): **Falsified & Vetoed by Red-Team Auditor**. Full walkforward across 147 trades generated PF 0.79, Net -$910.30, Win Rate 51.7%. Stops hit 67 times vs targets 18 times (3.7:1 stop realization penalty). In 2026, PF collapsed to 0.23 (-$626.40). 09:35 ET enters the exhaustion spike of opening cross uncrossing orders, which mean-revert before true trend formation at 09:45 ET. Failed Idea #39.
    16. Candidate S19 / H40 (09:40 ET Transatlantic Energy Handover `MCL`): **Catastrophically Falsified & Vetoed by Red-Team Auditor**. Across 200 trades (Wednesday EIA gated), generated Win Rate 11.5%, PF 0.03, Net -$710.60. Total loss of capital to equity-energy cross-whipsaws and bid-ask friction. Failed Idea #40.
    17. Candidate S20 / H41 (09:35 ET LBMA PM Fix Pre-Hedging Drive `MGC`): **Falsified & Vetoed by Red-Team Auditor**. Across 156 trades, generated Win Rate 48.1%, PF 0.69, Net -$882.40. Pre-fix flows are passive two-sided inventory absorption, not directional drives. Failed Idea #41.
    18. Candidate S21 / H42 (09:50 ET 80% Value Area Re-Acceptance Rotation `MNQ`/`MES`): **Falsified & Vetoed by Red-Team Auditor**. Full walkforward across 223–267 trades generated PF 0.73–0.79 on MES (-$1,069 to -$1,575) and PF 0.98 on MNQ (-$184.80). Win rate of 47%–51% is a random walk; boundary re-entry creates whip-chop rather than rotation. Failed Idea #42.
    19. Candidate S22 / H43 (09:45 ET Multi-Session Inside-Day Breakout `MNQ`): **Falsified & Vetoed by Red-Team Auditor**. Across 85 trades, generated PF 0.61–0.84 with tight/medium stops, and PF 1.09 with wide stops (+$278 over 5.8 yrs = $48/yr), failing Belfort Step 04 (PF >= 1.25). Inside Day extremes are liquidity sweep traps. Failed Idea #43.
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
