---
title: "Agent Execution Guardrails & Subprocess Security"
tags:
  - security
  - guardrails
  - subprocess
  - agent-permissions
  - timeouts
created: "2026-11-06"
updated: "2026-11-06"
status: active
strategies:
  - morning_va_breakout_s1
  - macro_momentum_s2
  - gold_london_fix_s3
  - lucid_flex_ensemble
related_pages:
  - "provenance/provenance-protocol.md"
  - "execution/demo-parity-engine.md"
---

# Agent Execution Guardrails & Subprocess Security

## Executive Summary
Autonomous AI agents operating in quantitative trading environments must be strictly bounded to prevent unauthorized modifications, runaway exploratory backtests, process starvation, and shell injection vulnerabilities. The Agent Execution Guardrails subsystem (`backtest/agent_guardrails.py`, `backtest/research_protocol.py`) establishes runtime execution security, command validation, shell chaining prevention, and mandatory wall-clock timeouts for all subprocess operations.

By promoting declarative protocol checks to hard gates and enforcing active validation before process creation, this architecture prevents unvetted agents from consuming unbounded resources, running dangerous shell binaries, or executing unauthorized batch backtest loops against production infrastructure.

## Technical Specification

### 1. Runtime Command Validator (`validate_command`)
The `validate_command(cmd: str | Sequence[str]) -> Tuple[bool, Optional[str]]` function enforces three layers of pre-execution verification:

1. **Shell Chaining & Injection Detection**:
   Blocks commands containing shell operators: `&&`, `||`, `;`, `|`, `$()`, `` ` ``, `\n`, `\r`. Semicolons in arguments are permitted only when explicitly passed to Python via `-c` without shell expansion.
2. **Dangerous Binary Blocking**:
   Blocks destructive system utilities and subshells: `rm`, `sudo`, `su`, `curl`, `wget`, `chmod`, `chown`, `chgrp`, `kill`, `pkill`, `killall`, `dd`, `mkfs`, `fdisk`, `parted`, `shutdown`, `reboot`, `poweroff`, `init`, `telnet`, `nc`, `netcat`, `bash`, `sh`, `zsh`, `csh`, `tcsh`, `dash`.
3. **Exploratory Script Blocking**:
   Blocks direct or indirect execution of unauthorized exploratory backtests and batch loops:
   - `main_backtest.py`
   - `scripts/probe_candidate_frequency.py`
   - `scripts/run_edge_candidates_batch.sh`
   - `scripts/run_next_vp_candidates_batch.sh`
   - `scripts/run_2021_frequency_candidates_batch.sh`
   Also blocks invocation via `python -m <module>` or within `python -c` code strings.

### 2. Safe Subprocess Execution (`safe_subprocess_run`)
The `safe_subprocess_run(cmd, timeout=300, **kwargs)` wrapper replaces direct `subprocess.run` calls:
- Pre-validates command through `validate_command`. Raises `PermissionError` if blocked.
- Enforces a mandatory, positive wall-clock timeout (default 300s) to prevent runaway execution.
- Emits structured log entries (`logging.getLogger(__name__)`) for tracking and auditability.
- Provides clean exception handling for `subprocess.TimeoutExpired` and `subprocess.CalledProcessError`.

### 3. Research Protocol Hard Verification Gate
In `backtest/research_protocol.py`, manifest verification of `DEFAULT_BLOCKED_AGENT_COMMANDS` is promoted from advisory `severity="warning"` to mandatory `severity="hard"`:
- Manifests omitting any of the 5 blocked commands fail protocol verification (`report.passed == False`).
- Protects the research protocol pipeline against accidental or intentional agent permission tampering.

### 4. Codebase Subprocess Hardening
Explicit timeouts are enforced across all operational and maintenance scripts:
- `scripts/generate_all_dashboards.py`: `timeout=300`
- `scripts/session_sentinel.py`: `timeout=60`
- `scripts/check_morning_readiness.py`: `timeout=30`
- `scripts/ingest_l2_parquet_5year.py`: `timeout=600`
- `scripts/launch_monday_forward_test.py`: `timeout=300`

## Empirical Evidence & Provenance
The guardrail and security implementation is programmatically verified through 28 unit tests in `tests/test_agent_guardrails.py` and `tests/test_research_protocol.py`:
- 15 guardrail test cases covering benign commands, injection vectors, dangerous binaries, exploratory backtests, timeout timeouts, and permission exceptions.
- 13 protocol test cases verifying deterministic hashing, edge theses, blinding checks, and hard-severity blocked command enforcement.
