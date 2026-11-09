# Quantitative Backtest Provenance & Anti-Hallucination Standing Rules

> [!IMPORTANT]
> **MANDATORY STANDING ORDERS FOR ALL AI AGENTS & SUBAGENTS**
> Every quantitative backtest, performance metric, and trade statistic quoted in this repository is strictly bound by the 5 Golden Rules of Quantitative Provenance.

---

## The 5 Golden Rules of Quantitative Provenance

### Rule 1: One Source of Truth (Verbatim Standing Order)
Every backtest auto-records into a single store (`results/backtest_provenance.db`). Antigravity, Claude, and all AI agents may quote stats ONLY by querying it — never from memory, prose, or prior chats.
- To quote any metric (Profit Factor, Win Rate, Net PnL, Max Drawdown, Sharpe), the agent **must** run:
  ```bash
  python scripts/query_provenance.py --strategy <strategy_id> --stat <metric_name>
  ```
- Valid authorized strategy IDs governed by `config/strategy_registry.py`:
  - `morning_va_breakout_s1` (Strategy 1: Morning VA Breakout 09:45 ET; MNQ/MES) [BASELINE]
  - `macro_momentum_s2` (Strategy 2: Pre-Market Macro Momentum 08:35 ET; MNQ) [BASELINE]
  - `gold_london_fix_s3` (Strategy 3: Gold London Fix Breakout 10:15 ET; MGC) [BASELINE]
  - `lucid_flex_ensemble` (Composite Multi-Strategy Portfolio) [BASELINE]
  - `lucid_flex_forward_demo` (Live Demo Parity Ledger) [FORWARD_DEMO]
  - Research candidates must be registered with `StrategyTier.CANDIDATE`. Unvetted candidates are prohibited from recording under production baseline IDs or claiming `BASELINE` tier.
- If a strategy or backtest has not been recorded into `results/backtest_provenance.db`, the agent **must refuse** to invent or guess numbers, stating: *"No verified backtest run found in `results/backtest_provenance.db`. Run the backtest engine first to record verified metrics."*

### Rule 2: No Naked Numbers
Every stat travels with its methodology + date range + a hash of the data file it ran on. Two numbers from different data hashes are NOT comparable.
- Any metric quoted in chat or reports must include:
  1. **Methodology** (e.g., `multi_year_walkforward`, `forward_demo`, `monte_carlo_stress`, `in_sample`)
  2. **Exact Date Range & Calendar Days** (e.g., `2021-01-07 to 2026-10-30 (2423 days)`)
  3. **Cryptographic Data Hash** (SHA-256 of the exact parquet/CSV dataset)
  4. **Cost Model** (Gross vs. Net of commissions and adverse slippage)

### Rule 3: Provenance Footers on Every Tool
Any script that prints a stat also prints where it came from. A number without a matching footer gets treated as fabricated.
- Every reporting script or agent response quoting metrics must include the standardized **Provenance Verification Footer**:
  ```text
  ────────────────────────────────────────────────────────────────────────────
  PROVENANCE VERIFICATION FOOTER (Rule 2 & 3)
  ────────────────────────────────────────────────────────────────────────────
  Run ID       : <run_id>
  Strategy     : <strategy_id> — <strategy_name>
  Methodology  : <methodology>
  Date Range   : <date_start> to <date_end> (<days_count> days)
  Data File    : <data_path>
  Data SHA-256 : <data_hash>
  Git Commit   : <git_commit>
  Cost Model   : <slippage_model> | <commission_model> [NET / GROSS]
  Metrics      : Trades: <N> | Win%: <W>% | PF: <PF> | Net: $<PnL> | MaxDD: -$<DD>
  Warning Flags: None (or list of warnings)
  ────────────────────────────────────────────────────────────────────────────
  ```

### Rule 4: Warnings Travel with the Number
Low sample size, gross vs net of commissions/slippage, selection bias — if the stat has a flag, the AI must quote the flag WITH the stat. A PF of 4 on 12 trades gross is not a PF of 4.
- Automated warning flags are permanently bound to records:
  - `LOW_SAMPLE_SIZE`: Total trades $N < 30$ ($< 100$ for high-frequency intraday scalps)
  - `GROSS_EXECUTION`: Zero slippage or zero commissions deducted
  - `OUTLIER_DOMINANCE`: Single largest winning trade represents $> 35\%$ of cumulative net profit
  - `SHORT_EVALUATION_WINDOW`: Evaluation period spans $< 60$ calendar days
- Whenever quoting a stat with an active flag, the agent **must explicitly output the warning inline alongside the number**.

### Rule 5: Recording is Automatic, Not Discipline
The engine writes to the store on every run, fail-safe. If saving results depends on remembering, the system dies in a week.
- All backtesting runs (`backtest/engine.py`, `backtest/demo_parity_engine.py`, `main_backtest.py`) automatically compute data SHA-256 hashes, evaluate warning criteria, and persist run records to `results/backtest_provenance.db` with a JSONL audit mirror at `results/backtest_provenance.jsonl`.

---

## LucidFlex 25K Invariant Rulebook & Compliance Specification

All models, agents, scripts, and backtests are strictly bound by the official **LucidFlex 25K Profile** (`config/prop_firm_registry.py`). Never invent, assume, or ask the user for these specifications again unless Lucid Trading officially changes them:

### 1. Evaluation Phase
- **Starting Capital**: $25,000.00
- **Profit Target**: $1,250.00 (Account Balance: $26,250.00)
- **Evaluation Ticket Fee**: $39.00 One-Time Payment (OTP) — STRICTLY ZERO monthly rebill, NO time expiration
- **Maximum Trailing Drawdown**: $1,000.00 (Calculated on End-of-Day [EOD] closing balance)
- **Trailing Floor Dynamic**: Starts at $24,000.00; trails $1,000 behind peak EOD balance up to $26,100.00
- **Permanent Floor Lock**: Once peak reaches >= $26,100.00, the floor permanently locks at $25,100.00 (Base + $100)
- **Intraday Soft Stop**: -$600.00 session halt (stops order flow for remaining windows in the day; not account breach)
- **Max Sizing**: 10 Micros or 1 Mini contract maximum
- **Consistency Rule**: Maximum 40% of target profit may come from a single trading day

### 2. Funded Phase (Master / LiveSim Account)
- **Account Transition**: Balance resets to $25,000.00 on Day 1; Drawdown floor resets to $24,000.00
- **Floor Trailing Mechanics**: Trails $1,000 behind peak EOD balance up to $26,100.00, then locks permanently at $25,100.00
- **Intraday Soft Stop**: -$600.00 session halt (same as evaluation)
- **Buffer Requirement**: LucidFlex does NOT mandate maintaining an arbitrary static buffer; payouts directly deduct from the cushion above the $25,100 locked floor

### 3. Payout Eligibility & Calculation Rules
- **Minimum Profitable Days**: Minimum 5 separate trading days (not consecutive) with >= $100.00 net profit each during the payout cycle
- **Cycle Net Profit Requirement**: At least +$1.00 net profit compared to previous payout
- **Counter Reset**: The 5-day profit counter resets to 0 after every approved payout and must be re-earned
- **Payout Limit**: Maximum 5 payouts per account before transition to a live brokerage account
- **Payout Formula**: Request 50% of accumulated profit above the $25,000.00 base, up to a $1,000.00 cap
- **Minimum Payout Request**: $500.00 gross ($450.00 net after 90/10 split) -> Requires Balance >= $26,000.00
  - Post-payout balance at $500 min withdrawal: $25,500.00 (leaves $400.00 drawdown cushion above the $25,100 locked floor)
- **Maximum Payout Request**: $1,000.00 gross ($900.00 net after 90/10 split) -> Requires Balance >= $27,000.00
  - Post-payout balance at $1,000 max withdrawal: $26,000.00 (leaves $900.00 drawdown cushion above the $25,100 locked floor)
- **Profit Split**: 90/10 (Trader receives 90%, Prop Firm retains 10%)

---

## LLM Wiki Persistent Knowledge Base Protocol (Karpathy Pattern)

Every Gemini and Antigravity agent operating in this repository is strictly bound to maintain and compound knowledge through the `wiki/` knowledge base:

### Mandatory Agent Startup Protocol (Execute Before Any Task)
1. **Inspect Knowledge Catalog**: Read `wiki/index.md` to review existing system architecture, strategy mechanics, and risk guidelines.
2. **Review Dead Ends Ledger**: Read `wiki/failed_ideas.md` before planning or executing new research, filters, or strategies. **Do not repeat or re-test any invalidated idea**.

### Mandatory Agent Shutdown Protocol (Execute Before Finishing Any Task)
1. **Update Topic Pages**: Document any new architecture, parameter calibrations, or verified results in the relevant `wiki/` pages.
2. **Refresh Active Context**: Update `wiki/hot.md` with the current system status, active initiatives, and latest changes.
3. **Append Journal Entry**: Append a grep-parseable entry to `wiki/log.md`:
   ```markdown
   ## [YYYY-MM-DD HH:MM:SS UTC] [gemini] [ACTION] | Short description of changes
   - **Pages Modified**: ...
   - **Summary**: ...
   - **Verification**: ...
   ```
