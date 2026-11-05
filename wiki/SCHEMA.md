# Wiki Schema & Governance Specification (SCHEMA.md)

This document defines the rules, formats, conventions, and maintenance protocols for the `wiki/` directory.

## 1. Directory Structure & Layout
The wiki is organized into standardized domain directories:
```text
wiki/
├── SCHEMA.md               # This rulebook
├── index.md                # Categorized catalog of all wiki pages
├── log.md                  # Chronological, append-only journal of agent actions
├── hot.md                  # Active project state, ongoing tasks, recent changes
├── failed_ideas.md         # Dead ends ledger of invalidated hypotheses
├── strategies/             # Strategy profiles and ensemble specifications
│   ├── morning-va-breakout.md
│   ├── macro-momentum.md
│   ├── gold-london-fix.md
│   └── lucid-flex-ensemble.md
├── prop_firm/              # Prop firm compliance and account specifications
│   └── lucid-flex-25k.md
├── sizing/                 # Position sizing, ratchet geometry, and cushion protection
│   └── ratchet-and-cushion.md
├── provenance/             # Provenance protocol, audit store, and warning flags
│   └── provenance-protocol.md
└── execution/              # Broker bridges, MotiveWave studies, parity engines
    ├── motivewave-integration.md
    └── demo-parity-engine.md
```

## 2. Page Naming Conventions
- Filenames must use lowercase kebab-case: `^[a-z0-9_-]+\.md$`.
- No uppercase characters, spaces, or special characters.
- Must be placed in the appropriate category subdirectory or root (for core meta-pages).

## 3. Frontmatter Schema
Every content page in `wiki/` (excluding `index.md`, `log.md`, `hot.md`, `SCHEMA.md`, `failed_ideas.md`) MUST begin with YAML frontmatter conforming to this schema:

```yaml
---
title: "Human Readable Page Title"
tags:
  - domain-tag-1
  - domain-tag-2
created: "YYYY-MM-DD"
updated: "YYYY-MM-DD"
status: active # Allowed: active | experimental | candidate | archived | rejected | stable | draft
strategies: # Optional: strategy ID strings if applicable
  - morning_va_breakout_s1
related_pages: # Relative links to associated wiki pages
  - "strategies/lucid-flex-ensemble.md"
  - "prop_firm/lucid-flex-25k.md"
---
```

## 4. Standard Page Anatomy
Each topic page must follow this section structure:
1. `# <Page Title>` (Top-level H1 matching frontmatter title)
2. `## Executive Summary`: 1–2 paragraphs defining the concept, strategy, or subsystem.
3. `## Technical Specification`: Detailed mathematical formulas, parameter tables, timing rules, state machines.
4. `## Empirical Evidence & Provenance`: If quantitative metrics are quoted, they MUST be queried from `results/backtest_provenance.db` and include the mandatory Provenance Verification Footer (Rule 2 & 3). Naked numbers are strictly prohibited.
5. `## Implementation & File Map`: Relative file paths to code (`src/motivewave/`, `backtest/`, `scripts/`, `tests/`).
6. `## Invariant Rules & Failure Modes`: Edge cases, risk constraints, and conditions under which the system must abort.
7. `## Cross References`: Relative links to related pages.

## 5. Log Entry Schema (`wiki/log.md`)
`wiki/log.md` is append-only. Every entry must start with a line-anchored, grep-parseable header:
`## [YYYY-MM-DD HH:MM:SS UTC] [AGENT] [ACTION] | Short description`

- **Allowed AGENT values**: `[claude]`, `[gemini]`, `[codex]`, `[orchestrator]`, `[explorer]`, `[worker]`, `[auditor]`, `[human]`, `[hook]`.
- **Allowed ACTION values**: `[INGEST]`, `[QUERY]`, `[LINT]`, `[UPDATE]`, `[SYNC]`, `[REVISE]`, `[SETUP]`.

Example Entry:
```markdown
## [2026-11-05 19:15:00 UTC] [worker] [INGEST] | Initialized Strategy 1 Morning VA Breakout
- **Pages Modified**:
  - `wiki/strategies/morning-va-breakout.md` (created)
  - `wiki/index.md` (catalog updated)
  - `wiki/hot.md` (active context updated)
- **Summary**: Transferred Strategy 1 specifications, parameters, and verified backtest metrics into wiki.
- **Verification**: Ran `python scripts/query_provenance.py --strategy morning_va_breakout_s1 --stat profit_factor`.
```

CLI Query Syntax:
- Last 5 entries: `grep "^## \[" wiki/log.md | tail -5`
- Filter by action: `grep "^## \[.*\] \[INGEST\]" wiki/log.md`

## 6. Failed Ideas Ledger Schema (`wiki/failed_ideas.md`)
The Failed Ideas ledger prevents re-testing invalidated hypotheses. Every rejected idea must be logged with:
- `### [FI-XXX] Hypothesis / Idea Title`
- **Evaluation Date**: `YYYY-MM-DD`
- **Author / Agent**: Identity of researcher/agent
- **Core Premise**: What was the hypothesis and theoretical edge?
- **Empirical Failure Evidence**: Quantitative gate metrics (e.g., net PnL, win rate, adverse slippage stress).
- **Structural Root Cause**: Why the idea failed (e.g. regime dependency, fee drag, program exhaustion).
- **Postmortem Artifact**: Relative link to postmortem in `docs/research_postmortems/`.
- **Negative Invariant Generated**: The explicit permanent rule (e.g., "RULE: Do not fade Value Area extremes when overnight range > 1.5x ATR").

## 7. Structure for `wiki/index.md` and `wiki/hot.md`
- `index.md`: Catalog table of contents listing every wiki page grouped into domain sections (`Strategies & Ensembles`, `Prop Firm & Account Rules`, `Position Sizing & Risk`, `Provenance & Integrity`, `Execution & Engine Architecture`). Format example:
  `- [Page Title](strategies/morning-va-breakout.md) — Concise one-line summary. \`[status]\``
- `hot.md`: Dynamic active context tracker containing:
  - `## Production Baseline & Verified Status`
  - `## Active Tasks & Work in Progress`
  - `## Recent Changes (Last 3–5 Sessions)`
  - `## Immediate Next Steps & Known Blockers`
 