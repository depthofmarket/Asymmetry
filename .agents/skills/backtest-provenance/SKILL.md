---
name: backtest-provenance
description: "Enforces the 5 Golden Rules of Quantitative Provenance, queries the official backtest store (results/backtest_provenance.db), verifies dataset SHA-256 cryptographic hashes, and formats standardized provenance verification footers."
---

# Quantitative Backtest Provenance Skill (`backtest-provenance`)

Use this skill whenever you need to quote, verify, compare, or record backtest performance statistics, win rates, profit factors, net PnL, or drawdowns.

## The 5 Golden Rules of Quantitative Provenance
1. **One Source of Truth**: All stats live in `results/backtest_provenance.db`. Query the store; never quote from memory or prose.
2. **No Naked Numbers**: Every number must specify methodology, date range, dataset SHA-256 hash, and cost model.
3. **Provenance Footers**: Every reporting tool or chat output must include the standardized Provenance Verification Footer.
4. **Warnings Travel With the Number**: Always quote warning flags (`LOW_SAMPLE_SIZE`, `GROSS_EXECUTION`, `OUTLIER_DOMINANCE`, `SHORT_EVALUATION_WINDOW`) inline with the metric.
5. **Fail-Safe Automatic Recording**: All backtest scripts automatically write run records to SQLite on completion.

## CLI Commands
- List verified runs:
  ```bash
  python scripts/query_provenance.py --list
  ```
- Query specific strategy metrics:
  ```bash
  python scripts/query_provenance.py --strategy morning_va_breakout_s1 --stat profit_factor
  python scripts/query_provenance.py --strategy macro_momentum_s2 --latest
  python scripts/query_provenance.py --strategy gold_london_fix_s3 --stat net_profit
  python scripts/query_provenance.py --strategy lucid_flex_ensemble --stat sharpe_ratio
  ```
- Verify dataset cryptographic hash:
  ```bash
  python scripts/query_provenance.py --hash-file data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet
  ```

## Standard Provenance Verification Footer Template
```text
────────────────────────────────────────────────────────────────────────────
PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
────────────────────────────────────────────────────────────────────────────
Run ID       : <run_id>
Strategy     : <strategy_id> — <strategy_name>
Methodology  : <methodology>
Date Range   : <start_date> to <end_date> (<calendar_days> days)
Data File    : <data_path>
Data SHA-256 : <sha256_hash>
Git Commit   : <git_commit>
Cost Model   : <slippage_model> | <commission_model> [NET / GROSS]
Metrics      : Trades: <N> | Win%: <WR>% | PF: <PF> | Net: $<PnL> | MaxDD: -$<DD>
Warning Flags: None (or list of active flags)
────────────────────────────────────────────────────────────────────────────
```
