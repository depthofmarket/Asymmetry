---
title: "Declarative Confluence Engine & Decision Trace Architecture"
tags:
  - confluence
  - decision-traces
  - mcp-server
  - microstructure
  - auditability
created: "2026-11-07"
updated: "2026-11-07"
status: active
strategies:
  - lucid_flex_ensemble
  - morning_va_breakout_s1
  - macro_momentum_s2
  - gold_london_fix_s3
related_pages:
  - "strategies/lucid-flex-ensemble.md"
  - "provenance/provenance-protocol.md"
---

# Declarative Confluence Engine & Decision Trace Architecture

## Executive Summary

The **Declarative Confluence Engine** (`backtest/confluence.py`) introduces a modular, explainable decision-making framework to the quantitative trading stack. Inspired by modern institutional algorithm frameworks, trading signals are decoupled from hardcoded conditional branches and expressed as composable, human-readable **Confluence Scoring Cards**. 

Every trade decision generates a comprehensive, audit-ready **Decision Trace** capturing all evaluated conditions, numerical thresholds, assigned weights, categorical groups (Primary, Secondary, Veto), and total confidence scores. Coupled with the expanded 10-tool **Asymmetry Model Context Protocol (MCP) Server** (`scripts/asymmetry_mcp_server.py`), external AI agents (Antigravity, Claude, Codex) can dynamically inspect equity trajectories, individual trade executions, calendar return matrices, and relative strategy rankings via standard JSON-RPC 2.0.

## Technical Specification

### 1. Composable Boolean Expression Tree

Signal conditions are modeled as algebraic expression trees evaluated against a dynamic `EvaluationContext` containing both current bar attributes and previous historical values:

$$\text{Context} = \{\mathbf{x}_t, \mathbf{x}_{t-1}\}$$

The engine supports the following composable logic primitives:
- `Condition(field, operator, value, value_high)`: Atomic comparison between context values and static or dynamic thresholds.
- `AllOf([expr_1, expr_2, ...])`: Logical AND gate ($\bigwedge_{i} E_i$).
- `AnyOf([expr_1, expr_2, ...])`: Logical OR gate ($\bigvee_{i} E_i$).
- `Not(expr)`: Logical negation ($\neg E$).
- `AtLeast(min_count, [expr_1, ...])`: $K$-of-$N$ quorum operator ($\sum_{i} \mathbb{I}(E_i) \ge K$).

Supported comparison operators (`Operator`):
- Relational: `gt` ($>$), `gte` ($\ge$), `lt` ($<$), `lte` ($\le$), `eq` ($=$), `neq` ($\ne$), `between` ($[v_{low}, v_{high}]$).
- Microstructure Crossings: `cross_above` ($x_{t-1} \le v \land x_t > v$), `cross_below` ($x_{t-1} \ge v \land x_t < v$).

### 2. Multi-Tier Confluence Scoring & Veto Overrides

Rules are organized into functional tiers:
1. **Primary Group**: Core setup preconditions (e.g., Value Area displacement, macro release direction).
2. **Secondary Group**: Confirmation filters (e.g., GARCH volatility regime, volume delta, order book imbalance).
3. **Veto Group**: Hard invalidation conditions (e.g., FOMC blackout window, excessive spread, trailing drawdown floor breach).

The total confidence score is computed as:

$$\text{Score} = \sum_{i \in \text{Passed Rules}} w_i$$

A setup triggers an execution candidate if and only if:
1. No active rule in the **Veto Group** is satisfied ($\forall v \in \text{Vetoes}: v = \text{False}$).
2. $\text{Score} \ge \text{Threshold}$.
3. Mandatory primary preconditions are satisfied.

### 3. Decision Trace Serialization & Forensics

Whenever `card.evaluate(ctx)` executes, it returns a boolean decision accompanied by a serialized `DecisionTrace`:

```json
{
  "card_name": "S1_Morning_VA_Breakout_Long",
  "passed": true,
  "total_score": 85.0,
  "threshold": 70.0,
  "veto_triggered": false,
  "veto_reasons": [],
  "evaluated_rules": [
    {"rule_name": "VAH_Breakout", "group": "primary", "weight": 40.0, "passed": true, "details": "close (20150.0) gt vah (20120.0)"},
    {"rule_name": "MVT_Exhaustion_Filter", "group": "secondary", "weight": 25.0, "passed": true, "details": "mvt_exhaustion (0.12) lt 0.35"},
    {"rule_name": "GARCH_Vol_Filter", "group": "secondary", "weight": 20.0, "passed": true, "details": "garch_sigma (14.2) between [10.0, 25.0]"},
    {"rule_name": "Cushion_Hard_Floor", "group": "veto", "weight": -1000.0, "passed": false, "details": "cushion (850.0) lt 400.0"}
  ]
}
```

### 4. Expanded Native MCP Server (10 Institutional Tools)

The Native Asymmetry MCP Server (`scripts/asymmetry_mcp_server.py`) provides 10 standard JSON-RPC 2.0 tools:

| Tool Name | Parameters | Institutional Functionality |
| :--- | :--- | :--- |
| `asymmetry_query_stat` | `strategy_id`, `stat_name`, `run_id` | Provenance-locked single metric lookup with Rule 2 & 3 footer |
| `asymmetry_list_runs` | `tier`, `limit`, `include_candidates` | Catalog of canonical verified backtest runs in ACID SQLite store |
| `asymmetry_compare_strategies` | `strategy_a`, `strategy_b` | Multi-dimensional side-by-side quant comparison |
| `asymmetry_inspect_bundle` | `strategy_id`, `run_id` | Unpacks `.obtf` bundle for deep trade, equity, and audit inspection |
| `asymmetry_verify_data_hash` | `filepath` | Computes SHA-256 cryptographic dataset hash and checks registry |
| `asymmetry_get_equity_curve` | `strategy_id`, `max_rows`, `sample_step` | Downsampled daily equity, high-water mark, and drawdown trajectory |
| `asymmetry_get_trades` | `strategy_id`, `direction`, `outcome`, `limit` | Granular trade execution ledger with hold duration and cumulative PnL |
| `asymmetry_get_monthly_returns`| `strategy_id`, `run_id` | 12-month calendar return grid with annual totals and monthly win % |
| `asymmetry_rank_strategies` | `metric`, `tier`, `ascending`, `limit` | Cross-sectional leaderboard ranking all registered strategies |
| `asymmetry_log_research_note` | `topic`, `summary`, `agent_name`, `action` | Direct agent writing to `wiki/log.md` with grep-parseable headers |

## Empirical Evidence & Provenance

All data surfaces queried by the Confluence Engine and MCP tools trace directly to verified `.obtf` bundles and the canonical provenance database:

```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : run_canonical_lucid_flex_ensemble_2021_2026
Strategy     : lucid_flex_ensemble — LucidFlex Tri-Asset Ensemble
Methodology  : multi_year_walkforward
Date Range   : 2021-01-07 to 2026-10-30 (2122 days)
Data File    : data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet
Data SHA-256 : ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca
Git Commit   : b25fb22b9b4f910ba69cf808a3d5b0ae14b98d24
Cost Model   : conservative_slippage | commissions_included [NET]
Metrics      : Trades: 445 | Win%: 55.1% | PF: 1.56 | Net: $14,916.04 | MaxDD: -$1,511.51
Warning Flags: None
────────────────────────────────────────────────────────────────────────────
```

## Implementation & File Map

- `backtest/confluence.py`: Core declarative confluence classes (`Operator`, `EvaluationContext`, `Condition`, `ScoreRule`, `VetoRule`, `ConfluenceCard`, `DecisionTrace`).
- `tests/test_confluence.py`: Comprehensive test suite verifying logic gates, cross operators, veto overrides, and JSON serialization.
- `scripts/asymmetry_mcp_server.py`: Native MCP server with 10 tools, schema definitions, and JSON-RPC stdio dispatcher.
- `tests/test_asymmetry_mcp_server.py`: 14 unit tests verifying all 10 MCP tools, protocol initialization, and stdio streaming.

## Invariant Rules & Failure Modes

1. **Veto Supremacy Invariant**: Any triggered `VetoRule` forces `passed = False` and sets total score to $\le -999.0$, regardless of primary or secondary scores.
2. **Missing Field Fail-Safe**: If a condition queries a context field not present in `EvaluationContext`, it evaluates to `False` and logs a warning without crashing.
3. **No Unformatted Provenance via MCP**: Any performance or trade metric output via MCP must include the standardized Provenance Verification Footer.
4. **Acids-Compliant Persistence**: Research notes appended via `asymmetry_log_research_note` must adhere strictly to the grep-parseable header format defined in `wiki/SCHEMA.md`.

## Cross References

- [Tri-Asset Multi-Strategy Ensemble Architecture](lucid-flex-ensemble.md)
- [Quantitative Provenance Protocol & Anti-Hallucination Standards](../provenance/provenance-protocol.md)
- [MotiveWave Custom Studies & Java Execution Integration](../execution/motivewave-integration.md)
