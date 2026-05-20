from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.live import PaperTradingConfig, PaperTradingEngine
from backtest.portfolio import Portfolio


@dataclass(frozen=True)
class TradeMismatch:
    row: int
    field: str
    backtest_value: Any
    paper_value: Any


@dataclass(frozen=True)
class LiveParityReport:
    passed: bool
    backtest_trades: int
    paper_trades: int
    mismatches: list[TradeMismatch] = field(default_factory=list)

    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"{status}: backtest_trades={self.backtest_trades}, "
            f"paper_trades={self.paper_trades}, mismatches={len(self.mismatches)}"
        )


DEFAULT_COMPARE_COLUMNS = (
    "entry_time",
    "exit_time",
    "direction",
    "signal_type",
    "setup_tag",
    "entry_price",
    "exit_price",
    "contracts",
    "reason",
)


def run_backtest_trade_log(
    data: pd.DataFrame,
    *,
    futures_specs: dict,
    strategy_params: dict,
    starting_capital: float,
    max_drawdown_pct: float | None = None,
) -> pd.DataFrame:
    portfolio = Portfolio(starting_capital, futures_specs, max_drawdown_pct=max_drawdown_pct)
    engine = BacktestEngine(data, portfolio, futures_specs, strategy_params)
    pre_df = engine.preprocess()
    results = engine.run_on_preprocessed(pre_df)
    if "error" in results:
        return pd.DataFrame()
    return results["trades"].copy()


def run_paper_replay_trade_log(
    data: pd.DataFrame,
    *,
    futures_specs: dict,
    strategy_params: dict,
    starting_capital: float,
    max_drawdown_pct: float | None = None,
    warmup_1m_bars: int = 0,
) -> pd.DataFrame:
    engine = PaperTradingEngine(
        futures_specs=futures_specs,
        strategy_params=strategy_params,
        config=PaperTradingConfig(
            starting_capital=starting_capital,
            max_drawdown_pct=max_drawdown_pct,
            warmup_1m_bars=max(0, int(warmup_1m_bars)),
            persist_state=False,
        ),
    )
    work = data.copy()
    work["time"] = pd.to_datetime(work["time"])
    work = work.sort_values("time").reset_index(drop=True)
    for _, row in work.iterrows():
        engine.on_bar(row)
    return engine.trade_log()


def compare_trade_logs(
    backtest_trades: pd.DataFrame,
    paper_trades: pd.DataFrame,
    *,
    columns: tuple[str, ...] = DEFAULT_COMPARE_COLUMNS,
    price_tolerance: float = 1e-9,
    pnl_tolerance: float = 1e-6,
) -> LiveParityReport:
    left = _normalize_trade_log(backtest_trades)
    right = _normalize_trade_log(paper_trades)
    mismatches: list[TradeMismatch] = []

    if len(left) != len(right):
        mismatches.append(
            TradeMismatch(
                row=-1,
                field="trade_count",
                backtest_value=len(left),
                paper_value=len(right),
            )
        )

    n = min(len(left), len(right))
    compare_columns = tuple(col for col in columns if col in left.columns or col in right.columns)
    for row_idx in range(n):
        for column in compare_columns:
            if column not in left.columns or column not in right.columns:
                mismatches.append(
                    TradeMismatch(
                        row=row_idx,
                        field=column,
                        backtest_value="<missing>" if column not in left.columns else left.at[row_idx, column],
                        paper_value="<missing>" if column not in right.columns else right.at[row_idx, column],
                    )
                )
                continue
            a = left.at[row_idx, column]
            b = right.at[row_idx, column]
            if not _values_equal(a, b, price_tolerance=price_tolerance, pnl_tolerance=pnl_tolerance, column=column):
                mismatches.append(
                    TradeMismatch(row=row_idx, field=column, backtest_value=a, paper_value=b)
                )

    return LiveParityReport(
        passed=len(mismatches) == 0,
        backtest_trades=len(left),
        paper_trades=len(right),
        mismatches=mismatches,
    )


def _normalize_trade_log(trades: pd.DataFrame) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame()
    out = trades.copy()
    for col in ("entry_time", "exit_time"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col])
    sort_cols = [col for col in ("entry_time", "exit_time", "setup_tag") if col in out.columns]
    if sort_cols:
        out = out.sort_values(sort_cols)
    return out.reset_index(drop=True)


def _values_equal(
    a: Any,
    b: Any,
    *,
    price_tolerance: float,
    pnl_tolerance: float,
    column: str,
) -> bool:
    if _is_missing(a) and _is_missing(b):
        return True
    if column.endswith("_time"):
        return pd.Timestamp(a) == pd.Timestamp(b)
    if column in {"entry_price", "exit_price", "contracts"}:
        return abs(float(a) - float(b)) <= price_tolerance
    if column == "pnl":
        return abs(float(a) - float(b)) <= pnl_tolerance
    if isinstance(a, (int, float, np.number)) or isinstance(b, (int, float, np.number)):
        try:
            return abs(float(a) - float(b)) <= price_tolerance
        except (TypeError, ValueError):
            return False
    return str(a) == str(b)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False
