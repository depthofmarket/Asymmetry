# Claude Instructions & Quantitative Provenance Protocol

## The 5 Rules of Quantitative Provenance (Standing Orders)

1. **One source of truth.** Every backtest auto-records into a single store (results/backtest_provenance.db). Claude may quote stats ONLY by querying it — never from memory, prose, or prior chats.

2. **No naked numbers.** Every stat travels with its methodology + date range + a hash of the data file it ran on. Two numbers from different data hashes are NOT comparable.

3. **Provenance footers on every tool.** Any script that prints a stat also prints where it came from. A number without a matching footer gets treated as fabricated.

4. **Warnings travel with the number.** Low sample size, gross vs net of commissions/slippage, selection bias — if the stat has a flag, Claude must quote the flag WITH the stat. A PF of 4 on 12 trades gross is not a PF of 4.

5. **Recording is automatic, not discipline.** The engine writes to the store on every run, fail-safe. If saving results depends on you remembering, the system dies in a week.

## How to Query Stats
Whenever asked about strategy performance, profit factor, win rates, or drawdowns:
```bash
python scripts/query_provenance.py --strategy <strategy_id> --stat <metric_name>
```
Valid strategy IDs:
- `morning_va_breakout_s1` (Strategy 1: Morning VA Breakout 09:45 ET)
- `macro_momentum_s2` (Strategy 2: Macro Release Momentum 08:35 ET)
- `gold_london_fix_s3` (Strategy 3: Gold London Fix 10:15 ET)
- `lucid_flex_ensemble` (Composite Multi-Strategy Portfolio)
- `lucid_flex_forward_demo` (Live Demo Parity Ledger)

---

## LLM Wiki Persistent Knowledge Base Protocol (Karpathy Pattern)

This repository maintains a persistent, compounding production knowledge base in `wiki/`.
Claude must strictly adhere to the following startup and shutdown protocols across all sessions:

### 1. Mandatory Startup Protocol (Before Starting Any Task)
1. **Catalog Survey**: Read `wiki/index.md` to locate existing domain documentation, strategy specifications, and architecture notes.
2. **Dead Ends Check**: Read `wiki/failed_ideas.md` before proposing, coding, or optimizing any strategy, filter, or parameter set. If an idea or variation is documented as a dead end, **do not re-test it**.

### 2. Mandatory Shutdown Protocol (Before Concluding Any Task)
1. **Update Topic Pages**: Document any architectural decisions, new strategy logic, or verified findings in the appropriate `wiki/` topic pages.
2. **Refresh Active State**: Update `wiki/hot.md` with the latest system state, completed work, and current active tasks.
3. **Append Journal Entry**: Append a structured, grep-parseable entry to `wiki/log.md`:
   ```markdown
   ## [YYYY-MM-DD HH:MM:SS UTC] [claude] [ACTION] | Short description of task
   - **Pages Modified**: list of modified wiki pages
   - **Summary**: summary of changes and operational results
   - **Verification**: verification commands executed and results
   ```
