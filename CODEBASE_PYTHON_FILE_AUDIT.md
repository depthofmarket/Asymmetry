# Python File Audit

Generated: 2026-06-02

Scope: repository Python source layout, obvious dead weight, and cleanup candidates. This is not a backtest audit and did not run historical data.

## Current State

- Python files found: 200 total.
- Tracked Python files: 191.
- Untracked Python files: 3, all from the new L2 replay protocol work.
- Ignored Python files: 6, all under `results/`.
- Main source sizes:
  - `backtest/`: about 3.2 MB
  - `scripts/`: about 504 KB
  - `tests/`: about 724 KB
  - `config/`: about 192 KB
- Python bytecode/cache size:
  - `__pycache__` directories and `.pyc` files: about 1.9 MB

Conclusion: the Python files are not meaningful storage pressure. The real storage issue is market data, zip archives, decoded datasets, and result artifacts. The Python layout still needs cleanup because too many research, runtime, scripts, and artifact files are mixed together.

## Safe To Delete

These are generated and should not be kept:

- `backtest/__pycache__/`
- `scripts/__pycache__/`
- `tests/__pycache__/`
- `config/__pycache__/`
- `results/__pycache__/`
- Any `*.pyc` files

They will regenerate automatically when Python runs. Deleting them saves only about 1.9 MB, so this is hygiene, not a storage fix.

Suggested command when ready:

```bash
find . -type d -name '__pycache__' -prune -exec rm -rf {} +
```

## Misplaced Source Files

These ignored Python files are under `results/`:

- `results/analysis.py`
- `results/visualize.py`
- `results/research_dashboards.py`
- `results/research_animations.py`
- `results/heatmap.py`
- `results/__init__.py`

This is a repo hygiene problem. `results/` should contain generated outputs, not source code. These files are small, about 196 KB total, so they are not a storage problem. The right cleanup is to review whether they are still useful, then either:

1. Move useful files into a tracked tool/source location such as `scripts/` or `tools/visualization/`.
2. Delete them if they are obsolete.
3. Archive them if they are historical but not active.

Do not leave active source code inside ignored output folders.

## Untracked L2 Protocol Files

These are current intentional work and should not be deleted:

- `backtest/l2_replay_protocol.py`
- `scripts/check_l2_replay_protocol.py`
- `tests/test_l2_replay_protocol.py`

There is also one modified tracked file:

- `scripts/run_l2_orderflow_replay.py`

Recommendation: commit or deliberately discard the L2 replay protocol work before doing any larger file reorganization. Otherwise cleanup and feature work will get mixed together.

## Zero-Incoming Backtest Modules

Static import analysis found these `backtest/` modules with no direct incoming imports from other Python files:

- `backtest/feature_attribution.py`
- `backtest/meta_strategy.py`
- `backtest/online_regime_leakage.py`

This does not prove they are useless. It means they are not wired into the current Python dependency graph.

### `backtest/feature_attribution.py`

Purpose appears to be feature attribution diagnostics. It is referenced in documentation, but not imported by source code.

Recommendation: keep only if feature attribution is an active research workflow. Otherwise archive it until there is a script/test that makes it operational.

### `backtest/meta_strategy.py`

Purpose appears to be a meta-strategy or candidate selector. It is referenced in documentation, but not imported by source code.

Recommendation: strongest archive candidate. Meta-strategy code can easily become an overfit amplifier if it selects from many historical candidates without strict protocol controls. If kept, it needs tests and explicit research-governance gates.

### `backtest/online_regime_leakage.py`

Purpose appears to be point-in-time leakage auditing for regime classification. It is referenced in documentation, but not imported by source code.

Recommendation: conceptually useful, but currently unwired. Either wire it into an audit script/test or archive it. Do not delete blindly because leakage control is aligned with the repo's main goal.

## Parquet-Specific Legacy Files

Now that the working L2 path is CSV-based, these parquet-specific files should be reviewed:

- `backtest/l2_parquet_audit.py`
- `scripts/decode_l2_mbp_parquet.py`
- `scripts/ingest_l2_parquet_5year.py`
- `scripts/inspect_l2_parquet_dataset.py`
- `tests/test_l2_parquet_audit.py`

Recommendation: do not delete immediately unless CSV-only is final policy. If CSV-only is final, archive or delete these after confirming that no current L2 resolver, audit, or replay path depends on them.

## Keep

These are not wasted space even if they look numerous:

- `tests/`: tests are how the codebase avoids lying to us during refactors.
- `scripts/`: entrypoints are useful if they are thin wrappers around library code.
- L2 CSV/replay modules: this is the current direction for realistic orderflow backtesting.
- Execution-realism and research-protocol modules: these enforce honesty rather than generate edge directly.

## Recommended Organization Policy

Use this as the target layout:

- `backtest/`: importable research/runtime library code.
- `backtest/l2/`: future package for L2 source resolution, schema validation, replay, and execution simulation. This should be done as a deliberate refactor because imports will change.
- `scripts/`: command-line entrypoints only. Scripts should be thin and call `backtest/` code.
- `tests/`: unit and focused integration tests.
- `config/`: configuration only.
- `results/`: generated outputs only. No source `.py` files.
- `data/`: raw/processed market data only. No source `.py` files.

## Cleanup Plan

1. Commit the current L2 replay protocol changes.
2. Delete `__pycache__` and `.pyc` files.
3. Review and move/delete ignored `results/*.py` files.
4. Archive `backtest/meta_strategy.py` unless there is an active, governed use case.
5. Decide whether CSV-only is final for L2. If yes, archive/delete parquet-only scripts and tests.
6. Only then consider a package refactor such as `backtest/l2/`.

## Blunt Assessment

The repo does not have a Python storage problem. It has a boundary problem:

- output folders contain source code,
- some research modules are not wired into tests or scripts,
- old parquet tooling still exists after switching to CSV,
- and active L2 protocol changes are uncommitted.

The highest-value cleanup is not deleting lots of files. It is separating active research infrastructure from historical experiments, generated output, and abandoned tools.
