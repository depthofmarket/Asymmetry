---
title: "Quantitative Provenance Protocol & Anti-Hallucination Standards"
tags:
  - provenance
  - anti-hallucination
  - reproducibility
  - sqlite
  - governance
created: "2026-11-05"
updated: "2026-11-07"
status: active
strategies:
  - morning_va_breakout_s1
  - macro_momentum_s2
  - gold_london_fix_s3
  - lucid_flex_ensemble
  - lucid_flex_forward_demo
related_pages:
  - "strategies/lucid-flex-ensemble.md"
  - "prop_firm/lucid-flex-25k.md"
  - "sizing/ratchet-and-cushion.md"
  - "execution/demo-parity-engine.md"
---

# Quantitative Provenance Protocol & Anti-Hallucination Standards

## Executive Summary
In quantitative algorithmic trading, AI agents and human researchers are prone to statistical hallucination, metric drift, selective cherry-picking, and memory distortion. The Quantitative Provenance Protocol eliminates these vulnerabilities by enforcing a single, auditable store of truth: `results/backtest_provenance.db`.

Under this protocol, all performance statistics (Profit Factor, Win Rate, Net PnL, Drawdown, Sharpe) must be queried directly from the verified database. Every quoted stat must travel with its evaluation methodology, date range, cryptographic data SHA-256 hash, and cost model. Quoting naked or unverified numbers is strictly prohibited across the repository.

## Technical Specification

### The 5 Golden Rules of Quantitative Provenance
1. **One Source of Truth**: Every backtest auto-records into a single store (`results/backtest_provenance.db`). Antigravity, Claude, and all AI agents may quote stats ONLY by querying it — never from memory, prose, or prior chats.
2. **No Naked Numbers**: Every stat travels with its methodology + date range + a hash of the data file it ran on. Two numbers from different data hashes are not comparable.
3. **Provenance Footers on Every Tool**: Any script that prints a stat also prints where it came from. A number without a matching footer gets treated as fabricated.
4. **Warnings Travel with the Number**: Low sample size, gross vs net of commissions/slippage, selection bias — if the stat has a flag, the AI must quote the flag WITH the stat. A PF of 4 on 12 trades gross is not a PF of 4.
5. **Recording is Automatic, Not Discipline**: The engine writes to the store fail-safe on every run. If saving results depends on remembering, the system dies in a week.

### CLI Query Interface
```bash
# List all verified canonical backtest runs
python scripts/query_provenance.py --list

# Query specific strategy metric (Core or Institutional 88+ Metrics)
python scripts/query_provenance.py --strategy morning_va_breakout_s1 --stat profit_factor
python scripts/query_provenance.py --strategy morning_va_breakout_s1 --stat sortino
python scripts/query_provenance.py --strategy macro_momentum_s2 --stat calmar
python scripts/query_provenance.py --strategy gold_london_fix_s3 --stat net_profit
python scripts/query_provenance.py --strategy lucid_flex_ensemble --stat cvar95
python scripts/query_provenance.py --strategy lucid_flex_ensemble --stat ulcer_index
python scripts/query_provenance.py --strategy lucid_flex_ensemble --stat half_kelly
python scripts/query_provenance.py --strategy lucid_flex_ensemble --stat trimmed_profit_factor
python scripts/query_provenance.py --strategy lucid_flex_ensemble --latest

# Compute or verify data file cryptographic SHA-256
python scripts/query_provenance.py --hash-file <filepath>
```

### Institutional 88+ Metrics Taxonomy & Schema (backtest/metrics.py)
In addition to the 9 scalar legacy metrics, the provenance database schema and `backtest/metrics.py` natively calculate and persist the complete 88+ institutional metric taxonomy:
- **Risk-Adjusted Ratios**: Sharpe, Sortino, Calmar, Omega, Gain-to-Pain (Schwager), Ulcer Performance Index (Martin), Sterling, Burke, Modified Burke, Kappa 3, Pezier Adjusted Sharpe.
- **Drawdown & Underwater Topology**: Max Drawdown ($ and %), Average Drawdown, Longest Drawdown Calendar Days (CDD), Longest Sessions Underwater, Average DD Duration, Ulcer Index, Pain Index, Underwater Exposure %, Recovery Factor.
- **Tail Risk & Value at Risk (VaR)**: Parametric VaR (95%, 99%), Historical VaR (95%, 99%), Cornish-Fisher expansion VaR (95%), Conditional VaR / Expected Shortfall (CVaR 95%, CVaR 99%), Traded-session CVaR 95%, Tail Risk Ratio (95th/5th percentile).
- **Trade Microstructure & Distribution**: Expectancy ($/trade), Expectancy Score / Edge Ratio, Payoff Ratio, Scratch Rate %, Trimmed Profit Factor (excluding top 2% outlier wins), Top 5 Wins Dominance %, Median Trade PnL.
- **Higher Statistical Moments & Tests**: Fisher-Pearson Skewness, Excess Kurtosis, Student's t-statistic, Edge P-value, Van Tharp System Quality Number (SQN), Jarque-Bera Normality Test Statistic & P-value.
- **Multiple Testing & Overfitting**: Probabilistic Sharpe Ratio (PSR), Deflated Sharpe Ratio (DSR), Expected Max Sharpe ($\text{SR}^*$), Minimum Track Record Length (MinTRL).
- **Capital Sizing & Ruin**: Full Kelly Criterion fraction, Half Kelly sizing, Analytical Gambler's Ruin, Max Win/Loss streaks.

### Automated Warning Flag Criteria
Warning flags are permanently attached to run records:
- `LOW_SAMPLE_SIZE`: Total trades $N < 30$ ($< 100$ for high-frequency intraday scalps).
- `GROSS_EXECUTION`: Zero slippage or zero commissions deducted.
- `OUTLIER_DOMINANCE`: Single largest winning trade represents $> 35\%$ of cumulative net profit.
- `SHORT_EVALUATION_WINDOW`: Evaluation period spans $< 60$ calendar days.

### Deflated Sharpe Ratio (DSR) & Multiple Testing Correction
To eliminate selection bias and data-mining overfitting across multiple strategy or parameter trials, the analytics engine implements the Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio:
- **Expected Maximum Sharpe ($\text{SR}^*$) under Extreme Value Theory (EVT)**:
  $$\text{SR}^* = \sqrt{V[\text{SR}]} \cdot \left((1 - \gamma) Z^{-1}\left(1 - \frac{1}{N}\right) + \gamma Z^{-1}\left(1 - \frac{1}{N e}\right)\right)$$
  where $\gamma \approx 0.5772156649$ (Euler-Mascheroni constant), $N = n\_trials$, and $V[\text{SR}]$ is the variance of Sharpe ratios across trials.
- **Deflation Mechanism**: The benchmark Sharpe ratio is elevated to $\max(\text{SR}_{\text{benchmark}}, \text{SR}^*)$, adjusting the Probabilistic Sharpe Ratio (PSR) for the selection bias of multiple trials.
- **Integration**: Available in `backtest/dashboard_analytics.py` via `deflated_sharpe_ratio()` and returned directly by `performance_metrics()` under keys `"dsr"` and `"sr_star"`.

### Open Backtest Format (.obtf) Portable Bundles (backtest/bundle.py)
To preserve complete vector and event-driven backtest results without bloating SQLite, Asymmetry implements the Open Backtest Format (`.obtf`). Each `.obtf` file is a ZIP-compressed container storing:
- `manifest.json`: JSON metadata, configuration parameters, data hashes, and the complete 92 institutional metrics snapshot.
- `trades.parquet`: Complete tick/bar level trade ledger with entry/exit timestamps, prices, commissions, slippage, and PnL.
- `equity.parquet`: High-resolution equity curve and drawdown trajectory across all evaluated trading sessions.
- `audit_log.json`: Chronological event log of order intents, fill confirmations, and risk guardrail interventions.

#### Tiered Storage & Sub-Millisecond Indexing
- High-level queries, strategy rankings, and multi-run sweeps query indexed columns in `results/backtest_provenance.db` in $< 1\text{ms}$.
- Granular post-trade inspection and trade log forensic analytics stream directly from `.obtf` bundles using `BacktestBundle.read_manifest()` or `BacktestBundle.load()`.
- CLI bundle inspection:
  ```bash
  python scripts/query_provenance.py --strategy lucid_flex_ensemble --latest --inspect-bundle
  ```

### Native Model Context Protocol (MCP) Server (scripts/asymmetry_mcp_server.py)
Asymmetry provides a native, pure-standard-library Model Context Protocol server operating over JSON-RPC 2.0 (stdio). AI agents (Antigravity, Claude, Codex) query backtest provenance, inspect `.obtf` bundles, and compare strategies directly through standard tool calls:
1. `asymmetry_query_stat`: Queries any of 92 institutional metrics for authorized strategies, automatically returning the mandatory Rule 2/3 provenance verification footer.
2. `asymmetry_list_runs`: Lists verified canonical backtest runs with strategy tiers, sample sizes, and warning flags.
3. `asymmetry_compare_strategies`: Side-by-side institutional tearsheet comparing risk-adjusted metrics, drawdown topologies, and tail risk.
4. `asymmetry_inspect_bundle`: Extracts granular trade metrics, top winning trades, and worst losses directly from `.obtf` containers.
5. `asymmetry_verify_data_hash`: Computes SHA-256 hashes of dataset files and cross-references them against recorded backtests.

## Empirical Evidence & Provenance
The active database contains exactly 9 canonical verified runs as of 2026-11-07:

```text
=========================================================================================================
RUN ID                           | STRATEGY               | TIER         | METHOD       | PF     | WIN%   | NET PNL    | WARN 
=========================================================================================================
run_canonical_forward_demo_live_parity | lucid_flex_forward_demo | FORWARD_DEMO | forward_demo | 99.00  | 100.0% | $145       | ⚠️ 
run_canonical_lucid_flex_ensemble_2021_2026 | lucid_flex_ensemble    | BASELINE     | multi_year_walkforward | 1.56   | 55.1 % | $14,916    | ✅ 
run_canonical_s3_gold_london_fix_2021_2026 | gold_london_fix_s3     | BASELINE     | multi_year_walkforward | 1.59   | 58.3 % | $1,387     | ✅ 
run_canonical_s2_macro_momentum_2021_2026 | macro_momentum_s2      | BASELINE     | multi_year_walkforward | 1.44   | 49.0 % | $4,573     | ✅ 
run_canonical_s1_va_breakout_2021_2026 | morning_va_breakout_s1 | BASELINE     | multi_year_walkforward | 1.65   | 57.0 % | $8,956     | ✅ 
run_alpha_factory_lucid_flex_ensemble_20261106_043319 | lucid_flex_ensemble    | BASELINE     | alpha_factory_adversarial_walkforward | 1.56   | 55.1 % | $14,916    | ✅ 
run_plateau_sweep_s3_gold_london_fix | gold_london_fix_s3     | BASELINE     | sensitivity_analysis_plateau | 1.59   | 58.3 % | $1,387     | ✅ 
run_plateau_sweep_s2_macro_momentum | macro_momentum_s2      | BASELINE     | sensitivity_analysis_plateau | 1.44   | 49.0 % | $4,573     | ✅ 
run_plateau_sweep_s1_va_breakout | morning_va_breakout_s1 | BASELINE     | sensitivity_analysis_plateau | 1.65   | 57.0 % | $8,956     | ✅ 
=========================================================================================================
```

Example verified provenance record for `lucid_flex_ensemble` with Institutional Risk Metrics:
```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : run_canonical_lucid_flex_ensemble_2021_2026
Strategy     : lucid_flex_ensemble — LucidFlex 25K Multi-Strategy Ensemble
Strategy Tier: BASELINE
Methodology  : MULTI_YEAR_WALKFORWARD
Date Range   : 2021-01-07 to 2026-10-30 (2423 days)
Data File    : data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet
Data SHA-256 : ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca
Git Commit   : 5b58930e15
Bundle (.obtf): results/bundles/run_canonical_lucid_flex_ensemble_2021_2026.obtf
Cost Model   : Multi-Asset CQG Adverse Realism | $1.40 RT ($0.70/side micro) [NET (Includes slippage & comms)]
Core Metrics : Trades: 543 | Win%: 55.06% | PF: 1.56 | Net: $14,916.04 | MaxDD: -$1,511.51
Risk Metrics : Sortino: 2.22 | Calmar: 1.03 | Omega: 1.63 | CVaR95: $178.25 | Ulcer: 1.06% | Half-Kelly: 0.099
Warning Flags:
None (Clean Run)
────────────────────────────────────────────────────────────────────────────
```

## Implementation & File Map
- **Query CLI**: `scripts/query_provenance.py` (Supports `--stat`, `--inspect-bundle`, `--hash-file`, `--tier`, `--list`)
- **Database Engine**: `backtest/provenance.py` (ACID SQLite schema + JSONL mirror)
- **Open Backtest Format Engine**: `backtest/bundle.py` (`.obtf` container packaging and extraction)
- **Institutional Metrics Engine**: `backtest/metrics.py` (92-metric vectorized analytics suite)
- **MCP Server**: `scripts/asymmetry_mcp_server.py` (JSON-RPC 2.0 stdio AI agent interface)
- **Autonomous Alpha Factory**: `scripts/alpha_factory.py` (gated `--record`, dynamic Git commit, dynamic dates, true `gross_profit`, and empirical DSR trials)
- **Primary Store**: `results/backtest_provenance.db`
- **Audit Mirror**: `results/backtest_provenance.jsonl`
- **Unit & Regression Tests**: `tests/test_provenance_system.py`, `tests/test_institutional_metrics.py`, `tests/test_bundle.py`, `tests/test_asymmetry_mcp_server.py`, `tests/test_alpha_factory_provenance.py`

## Invariant Rules & Failure Modes
1. **Rule 1: Never Fabricate Numbers**: If a strategy is not recorded in `results/backtest_provenance.db`, refuse to guess.
2. **Rule 2: Mandatory Inline Warnings**: Any stat carrying a warning flag must display the warning inline with the number.
3. **Rule 3: Dual-Write Audit Mirror**: Every database transaction must simultaneously write an un-indexed append-only JSONL record to `results/backtest_provenance.jsonl` to safeguard against SQLite corruption.
4. **Rule 4: Alpha Factory Provenance Gating**: `scripts/alpha_factory.py` executes dry-run evaluations without database mutation unless explicitly invoked with `--record`. All persistent records must bind actual Git HEAD commits, exact trade-derived date boundaries, authentic gross profit (`wins.sum()`), and empirical DSR trials ($N \ge 25$).

## Cross References
- [Tri-Asset Ensemble Architecture](../strategies/lucid-flex-ensemble.md)
- [LucidFlex 25K Compliance](../prop_firm/lucid-flex-25k.md)
- [Ratchet Sizing & Cushion Protection](../sizing/ratchet-and-cushion.md)
- [Demo Parity Engine](../execution/demo-parity-engine.md)
