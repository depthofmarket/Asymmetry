#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.volatility_context_diagnostics import (  # noqa: E402
    DEFAULT_FUTURE_RV_HORIZONS_BARS,
    DEFAULT_REGIME_COLUMNS,
    DEFAULT_SPREAD_REVERSION_HORIZONS_MINUTES,
    build_volatility_context_diagnostics,
    write_volatility_context_diagnostics,
)


def _csv_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in str(value or "").split(",") if item.strip()]


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _default_ints(values: tuple[int, ...]) -> str:
    return ",".join(str(value) for value in values)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build artifact-only volatility context diagnostics from prepared bars, "
            "optional volatility-state CSV, processed TBBO minute stats, and optional prepared signals. "
            "This does not replay strategy logic or create trades."
        )
    )
    parser.add_argument(
        "--bars-csv",
        required=True,
        help="CSV with at least time/open/high/low/close/volume, or time/close when --volatility-state-csv is supplied.",
    )
    parser.add_argument(
        "--volatility-state-csv",
        default="",
        help="Optional CSV previously produced from backtest.volatility_state. If omitted, state is built from --bars-csv.",
    )
    parser.add_argument(
        "--tbbo-minute",
        default="data/processed/tbbo/tbbo_minute_execution_stats.csv",
        help="Processed TBBO minute stats CSV. Missing file leaves TBBO sections empty.",
    )
    parser.add_argument(
        "--aggressive-flow-minute",
        default="data/processed/orderflow/aggressive_flow_minute_stats.csv",
        help="Optional processed aggressive-flow minute stats CSV.",
    )
    parser.add_argument(
        "--signals-csv",
        default="",
        help="Optional prepared signal CSV for signal-aligned adverse-selection diagnostics.",
    )
    parser.add_argument("--out-dir", default="results/research_master/volatility_context_diagnostics")
    parser.add_argument("--artifact-name", default="volatility_context_diagnostics")
    parser.add_argument("--future-rv-horizons-bars", default=_default_ints(DEFAULT_FUTURE_RV_HORIZONS_BARS))
    parser.add_argument("--spread-reversion-horizons-minutes", default=_default_ints(DEFAULT_SPREAD_REVERSION_HORIZONS_MINUTES))
    parser.add_argument(
        "--regime-cols",
        default=",".join(DEFAULT_REGIME_COLUMNS),
        help="Comma-separated context columns used for split summaries when present.",
    )
    return parser.parse_args()


def _read_optional_csv(path_text: str) -> pd.DataFrame:
    if not path_text:
        return pd.DataFrame()
    path = Path(path_text)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def main() -> int:
    args = parse_args()
    bars_path = Path(args.bars_csv)
    if not bars_path.exists():
        raise SystemExit(f"Bars CSV not found: {bars_path}")
    bars = pd.read_csv(bars_path, low_memory=False)
    volatility_state = _read_optional_csv(args.volatility_state_csv)
    tbbo_minute = _read_optional_csv(args.tbbo_minute)
    aggressive_minute = _read_optional_csv(args.aggressive_flow_minute)
    signals = _read_optional_csv(args.signals_csv)

    diagnostics = build_volatility_context_diagnostics(
        bars,
        volatility_state=volatility_state if not volatility_state.empty else None,
        tbbo_minute_stats=tbbo_minute if not tbbo_minute.empty else None,
        aggressive_flow_minute_stats=aggressive_minute if not aggressive_minute.empty else None,
        signals=signals if not signals.empty else None,
        future_rv_horizons_bars=_csv_ints(args.future_rv_horizons_bars),
        spread_reversion_horizons_minutes=_csv_ints(args.spread_reversion_horizons_minutes),
        regime_cols=_csv_items(args.regime_cols),
    )
    paths = write_volatility_context_diagnostics(
        diagnostics,
        args.out_dir,
        artifact_name=args.artifact_name,
    )

    print(f"Volatility context report:          {paths.report_md}")
    print(f"Future RV by vol state:             {paths.future_realized_vol_by_state_csv}")
    print(f"Future RV year/regime splits:       {paths.future_realized_vol_splits_csv}")
    print(f"TBBO cost state by vol state:       {paths.tbbo_cost_state_by_vol_state_csv}")
    print(f"TBBO cost year/regime splits:       {paths.tbbo_cost_state_splits_csv}")
    print(f"Spread reversion during expansion:  {paths.spread_reversion_during_expansion_csv}")
    print(f"Signal adverse selection by state:  {paths.signal_adverse_selection_by_vol_state_csv}")
    print(f"Signal adverse year/regime splits:  {paths.signal_adverse_selection_splits_csv}")
    if tbbo_minute.empty:
        print("TBBO minute stats were not found; TBBO cost and spread/reversion sections are empty.")
    if signals.empty:
        print("No prepared signal CSV supplied; signal adverse-selection sections are empty.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
