# Multi-Agent Quantitative Rules & Provenance Protocol

This repository is governed by the 5 Golden Rules of Quantitative Provenance:
1. **One source of truth**: Every backtest auto-records into a single store (`results/backtest_provenance.db`). Antigravity, Claude, and all AI agents may quote stats ONLY by querying it — never from memory, prose, or prior chats.
2. **No naked numbers**: Every stat travels with its methodology + date range + a hash of the data file it ran on.
3. **Provenance footers on every tool**: Any script that prints a stat also prints where it came from.
4. **Warnings travel with the number**: Low sample size, gross vs net, outlier dominance quoted WITH the stat.
5. **Recording is automatic, not discipline**: The engine writes to the store fail-safe on every run.

## Available Provenance CLI Commands
- List verified backtest runs:
  ```bash
  python scripts/query_provenance.py --list
  ```
- Query specific strategy metrics:
  ```bash
  python scripts/query_provenance.py --strategy morning_va_breakout_s1 --stat profit_factor
  python scripts/query_provenance.py --strategy macro_momentum_s2 --stat win_rate
  python scripts/query_provenance.py --strategy gold_london_fix_s3 --stat net_profit
  python scripts/query_provenance.py --strategy lucid_flex_ensemble --latest
  ```
- Lookup or compute cryptographic data SHA-256:
  ```bash
  python scripts/query_provenance.py --hash-file <filepath>
  ```

## Authorized Strategy IDs & Tiers
All quantitative backtest records and queries are strictly governed by `config/strategy_registry.py`:

### Production Baseline Strategies (`StrategyTier.BASELINE`)
- `morning_va_breakout_s1` (Strategy 1: Morning VA Breakout 09:45 ET; MNQ/MES)
- `macro_momentum_s2` (Strategy 2: Pre-Market Macro Momentum 08:35 ET; MNQ)
- `gold_london_fix_s3` (Strategy 3: Gold London Fix Breakout 10:15 ET; MGC)
- `lucid_flex_ensemble` (Tri-Asset Multi-Strategy Composite Ensemble)

### Live Forward Demo Parity (`StrategyTier.FORWARD_DEMO`)
- `lucid_flex_forward_demo` (Live MotiveWave paper demo parity ledger)

### Research Candidates (`StrategyTier.CANDIDATE`)
- Any new research candidate must be registered via `config/strategy_registry.py` with `StrategyTier.CANDIDATE`. Research candidates are strictly segregated and prohibited from claiming `BASELINE` tier or contaminating production baseline provenance.

## Invariant Protocols
1. **Never quote naked numbers**: Every stat MUST include methodology, date range, data SHA-256 hash, and cost model.
2. **Never hide warning flags**: If a stat carries `LOW_SAMPLE_SIZE`, `GROSS_EXECUTION`, `OUTLIER_DOMINANCE`, or `SHORT_EVALUATION_WINDOW`, output the flag immediately adjacent to the metric.
3. **Always attach the Provenance Verification Footer**: Any metric without a verifiable footer is considered fabricated.

---

## LLM Wiki Persistent Knowledge Base Protocol

All AI agents operating in this repository must maintain and compound knowledge across sessions using `wiki/`:

### 1. Mandatory Startup Protocol (Before Starting Any Task)
1. **Read Knowledge Catalog**: Read `wiki/index.md` to identify relevant existing strategies, execution models, and architecture.
2. **Read Dead Ends Ledger**: Read `wiki/failed_ideas.md` to review invalidated hypotheses and negative constraints. **Never repeat or re-test a documented failure**.

### 2. Mandatory Shutdown Protocol (Before Concluding Any Task)
1. **Update Topic Pages**: Update existing pages or create new pages in `wiki/` for any modified code, new features, or research findings.
2. **Refresh Active State**: Update `wiki/hot.md` to reflect current project baseline, active initiatives, and recent changes.
3. **Append Journal Entry**: Append an entry to `wiki/log.md` with the standardized grep-parseable header:
   ```markdown
   ## [YYYY-MM-DD HH:MM:SS UTC] [AGENT_NAME] [ACTION] | Short description
   - **Pages Modified**: ...
   - **Summary**: ...
   - **Verification**: ...
   ```
