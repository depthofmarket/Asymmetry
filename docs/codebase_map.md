# Codebase Map

Use this as the navigation layer for the repo.

## Top-Level Entry Points

- `main_backtest.py`: main historical backtest runner and research-report orchestration.
- `config/backtest_config.py`: strategy defaults, candidate overrides, validation, and research config.
- `config/live_trading.example.env`: CQG/AMP setup template.
- `scripts/`: runnable CLI entry points grouped in `scripts/README.md`.
- `tests/`: focused unit and regression coverage.

## Package Layout

- `backtest/`: reusable strategy, research, validation, and runtime code.
- `backtest/live.py` and `backtest/live_*.py`: live-style paper execution, feeds, brokers, prop guard, and parity helpers.
- `backtest/README.md`: module-by-module map for where new logic belongs.

## Where New Code Should Go

- Add broker-neutral paper/live execution code in the flat `backtest/live*.py` modules.
- Add one-off CLIs in `scripts/`, but keep reusable logic in `backtest/`.
- Add point-in-time feature columns near the existing feature builders in `backtest/`.
- Add research reports and diagnostics near the existing research modules in `backtest/`.
- Add validation gates and saved anti-overfit reports in `backtest/validation.py`; keep them artifact-based so they can audit completed runs without launching new backtests.
- Add candidate parameters in `config/backtest_config.py`, not inside scripts.
- Add tests beside the behavior they protect, using existing `tests/test_live_*.py`, `tests/test_*research*.py`, or regression-test patterns.

## Import Style

Prefer these paths for new live/paper code:

```python
from backtest.live import PaperTradingConfig, PaperTradingEngine
from backtest.live_feeds import CsvReplayFeed, FileTailBarFeed
from backtest.live_brokers import CsvOrderAuditBroker, PaperEventOrderBridge
from backtest.live_prop_rules import LivePropRuleGuard
from backtest.live_parity import compare_trade_logs
```
