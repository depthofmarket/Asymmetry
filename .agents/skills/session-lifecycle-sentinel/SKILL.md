---
name: session-lifecycle-sentinel
description: "Orchestrates daily trading session routines: 08:15 ET pre-market readiness checks, 16:15 ET post-market demo parity and Monte Carlo corridor reconciliation, and Friday 17:00 ET weekly health digests."
---

# Session Lifecycle Sentinel Skill (`session-lifecycle-sentinel`)

Use this skill to inspect, verify, or execute the daily and weekly operational routines governing the LucidFlex prop trading account.

## Daily Schedule & Procedures

### 1. Pre-Market Readiness Sentinel (08:15 ET)
Execute before the 08:30 Tier-1 macro releases to ensure green lights across all components:
```bash
python scripts/check_morning_readiness.py
```
Checks verified:
- [x] Morning Watcher Daemon active in launchd (PID confirmed).
- [x] Account balance and distance to trailing floor ($bal - floor \ge \$400.00$).
- [x] Provenance SQLite database online.
- [x] MotiveWave CSV bar feeds fresh.
- [x] Extension JAR present in `/Users/novo/MotiveWave Extensions/`.

### 2. Post-Market Demo Parity & Monte Carlo Reconcile (16:15 ET)
Execute after the 16:00 ET cash market close:
```bash
python scripts/session_sentinel.py --mode postmarket
```
Actions executed:
- Parses new broker fills from MotiveWave / CQG export.
- Reconciles execution prices against theoretical research prices, computing slippage drag.
- Overlays live cumulative equity onto the 10,000-path Monte Carlo corridor.
- Assesses regime health: confirms equity remains above the 5th percentile ($P_{05}$) circuit breaker.

### 3. Weekly Alpha & Health Digest (Friday 17:00 ET)
Execute after the Friday European/US close:
```bash
python scripts/session_sentinel.py --mode weekly
```
Actions executed:
- Runs full automated pytest suite.
- Re-generates `results/forward_test/demo_parity_dashboard.html`.
- Audits wiki link and frontmatter integrity (`python scripts/verify_wiki_integrity.py`).
- Appends weekly summary entry to `wiki/log.md`.
