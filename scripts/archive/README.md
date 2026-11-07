# Scripts Archive

This directory contains historical, exploratory, and ad-hoc scripts from prior quantitative research phases. They are retained for provenance and auditability but are strictly segregated from active production and testing pipelines.

## Categories of Archived Scripts

1. **Ad-Hoc Signal Exporters (`export_*_signal_csv.py`)**: One-off scripts used to dump signal evaluation frames for specific candidate hypotheses into CSV.
2. **One-Off Hypothesis Evaluators (`evaluate_*`)**: Scratch scripts used during exploratory multi-asset or GARCH research.
3. **Exploratory Sweeps & Tests (`run_*`, `test_*`)**: Non-framework scratch runners and candidate frequency scans.

## Active Production Scripts
All production daemons, data pipelines, strategy governance tools, and provenance CLIs remain at the top level of `scripts/`:
- `alpha_factory.py`: The centralized research and graduation authority.
- `query_provenance.py`: Single source of truth provenance CLI.
- `check_morning_readiness.py`: 08:15 ET pre-market readiness auditor.
- `session_sentinel.py`: Daily session lifecycle daemon.
- `sync_cqg_executions.py`: MotiveWave/CQG broker fill reconciliation.
- `watch_morning_demo_alerts.py`: Real-time forward-test alert monitor.
- `verify_wiki_integrity.py`: Karpathy LLM Wiki validator.
- `wiki_sync.py`: Git auto-sync and commit daemon.
