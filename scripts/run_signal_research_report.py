#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.signal_research import run_signal_research_report


def _csv_items(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _csv_ints(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _csv_floats(value: str) -> list[float]:
    return [float(item.strip()) for item in str(value or "").split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a pre-candidate signal research report from a prepared signal CSV. "
            "This does not replay strategy logic or create trades."
        )
    )
    parser.add_argument("--signals-csv", required=True, help="CSV with time, close, and one or more numeric signal columns.")
    parser.add_argument("--out-dir", default="results/research_master/signal_research")
    parser.add_argument("--artifact-name", default="signal_research")
    parser.add_argument("--signal-cols", default="", help="Comma-separated signal columns. If omitted, numeric non-price columns are inferred.")
    parser.add_argument("--context-cols", default="", help="Optional comma-separated context columns for grouped diagnostics.")
    parser.add_argument("--time-col", default="time")
    parser.add_argument("--price-col", default="close")
    parser.add_argument("--entry-price-col", default=None, help="Entry price column. Defaults to --price-col.")
    parser.add_argument("--exit-price-col", default=None, help="Exit price column. Defaults to --price-col.")
    parser.add_argument(
        "--entry-lag-bars",
        type=int,
        default=0,
        help="Bars after the signal row used for entry pricing. Use 1 for next-bar-open research.",
    )
    parser.add_argument("--horizons", default="1,3,6,12,24", help="Comma-separated forward horizons in rows/bars.")
    parser.add_argument("--period", default="Q", help="Pandas period alias for stability checks, e.g. M or Q.")
    parser.add_argument("--round-trip-cost-points", type=float, default=0.0)
    parser.add_argument(
        "--stress-round-trip-cost-points",
        default="2.0,4.25",
        help="Comma-separated higher round-trip costs that must also survive for candidate eligibility. Empty disables stress gating.",
    )
    parser.add_argument("--min-obs", type=int, default=100)
    parser.add_argument("--min-active-obs", type=int, default=30)
    parser.add_argument("--min-abs-ic", type=float, default=0.02)
    parser.add_argument("--min-positive-period-pct", type=float, default=55.0)
    parser.add_argument("--min-event-hit-rate-pct", type=float, default=52.0)
    parser.add_argument("--min-event-bootstrap-ci-low-points", type=float, default=0.0)
    parser.add_argument("--min-event-placebo-edge-points", type=float, default=0.0)
    parser.add_argument("--max-event-placebo-p-value", type=float, default=0.10)
    parser.add_argument("--event-bootstrap-samples", type=int, default=1000)
    parser.add_argument("--event-placebo-samples", type=int, default=1000)
    parser.add_argument("--event-random-seed", type=int, default=7)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = pd.read_csv(args.signals_csv)
    paths = run_signal_research_report(
        data,
        out_dir=Path(args.out_dir),
        artifact_name=args.artifact_name,
        signal_cols=_csv_items(args.signal_cols) or None,
        context_cols=_csv_items(args.context_cols),
        time_col=args.time_col,
        price_col=args.price_col,
        entry_price_col=args.entry_price_col,
        exit_price_col=args.exit_price_col,
        entry_lag_bars=int(args.entry_lag_bars),
        horizons_bars=_csv_ints(args.horizons),
        period=args.period,
        round_trip_cost_points=float(args.round_trip_cost_points),
        stress_round_trip_cost_points=_csv_floats(args.stress_round_trip_cost_points),
        min_obs=int(args.min_obs),
        min_active_obs=int(args.min_active_obs),
        min_abs_ic=float(args.min_abs_ic),
        min_positive_period_pct=float(args.min_positive_period_pct),
        min_event_hit_rate_pct=float(args.min_event_hit_rate_pct),
        min_event_bootstrap_ci_low_points=float(args.min_event_bootstrap_ci_low_points),
        min_event_placebo_edge_points=float(args.min_event_placebo_edge_points),
        max_event_placebo_p_value=float(args.max_event_placebo_p_value),
        event_bootstrap_samples=int(args.event_bootstrap_samples),
        event_placebo_samples=int(args.event_placebo_samples),
        event_random_seed=int(args.event_random_seed),
    )
    print(f"Saved summary:          {paths.summary_csv}")
    print(f"Saved period stability: {paths.period_stability_csv}")
    print(f"Saved context summary:  {paths.context_summary_csv}")
    print(f"Saved report:           {paths.report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
