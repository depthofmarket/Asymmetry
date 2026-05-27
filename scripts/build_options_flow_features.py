#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.options_flow import OptionsFlowBuildConfig, build_options_flow_feature_sets_from_source
from config.backtest_config import BACKTEST_CONFIG, OPTIONS_FLOW_CONFIG
from main_backtest import load_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build daily NQ options-flow features, DTE dashboards, and by-strike GEX surfaces."
    )
    parser.add_argument("--statistics-source", default=OPTIONS_FLOW_CONFIG["statistics_source"])
    parser.add_argument("--definition-source", default=OPTIONS_FLOW_CONFIG.get("definition_source"))
    parser.add_argument("--futures-path", default=BACKTEST_CONFIG["data_path"])
    parser.add_argument("--out", default=OPTIONS_FLOW_CONFIG["features_path"])
    parser.add_argument(
        "--strike-levels-out",
        default=OPTIONS_FLOW_CONFIG["strike_levels_path"],
        help="Output CSV for the by-date/by-strike GEX surface.",
    )
    parser.add_argument("--dashboard-out", default=OPTIONS_FLOW_CONFIG.get("dashboard_path"))
    parser.add_argument(
        "--dashboard-strike-levels-out",
        default=OPTIONS_FLOW_CONFIG.get("dashboard_strike_levels_path"),
    )
    parser.add_argument("--start", default=None, help="Optional statistics member start date.")
    parser.add_argument("--end", default=None, help="Optional statistics member end date.")
    parser.add_argument("--max-files", type=int, default=None, help="Limit daily statistics members for smoke tests.")
    parser.add_argument("--rows-per-file", type=int, default=None, help="Limit rows per statistics file for smoke tests.")
    parser.add_argument("--progress-every", type=int, default=100, help="Print progress every N statistics members.")
    parser.add_argument("--min-dte", type=int, default=int(OPTIONS_FLOW_CONFIG["min_dte"]))
    parser.add_argument("--max-dte", type=int, default=int(OPTIONS_FLOW_CONFIG["max_dte"]))
    parser.add_argument("--strike-window-points", type=float, default=float(OPTIONS_FLOW_CONFIG["strike_window_points"]))
    parser.add_argument("--min-open-interest", type=int, default=int(OPTIONS_FLOW_CONFIG["min_open_interest"]))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    futures = load_data(
        args.futures_path,
        continuous_contract_method=BACKTEST_CONFIG.get("continuous_contract_method"),
    )
    config = OptionsFlowBuildConfig(
        contract_multiplier=float(OPTIONS_FLOW_CONFIG["contract_multiplier"]),
        risk_free_rate=float(OPTIONS_FLOW_CONFIG["risk_free_rate"]),
        min_dte=int(args.min_dte),
        max_dte=int(args.max_dte),
        strike_window_points=float(args.strike_window_points),
        min_open_interest=int(args.min_open_interest),
        iv_floor=float(OPTIONS_FLOW_CONFIG["iv_floor"]),
        iv_cap=float(OPTIONS_FLOW_CONFIG["iv_cap"]),
        gex_neutral_threshold=float(OPTIONS_FLOW_CONFIG["gex_neutral_threshold"]),
        put_gamma_sign=float(OPTIONS_FLOW_CONFIG["put_gamma_sign"]),
    )
    feature_sets = build_options_flow_feature_sets_from_source(
        args.statistics_source,
        futures,
        config,
        definition_source=args.definition_source,
        start=args.start,
        end=args.end,
        max_files=args.max_files,
        rows_per_file=args.rows_per_file,
        progress_every=args.progress_every,
    )
    daily = feature_sets["daily"]
    strike_levels = feature_sets["strike_levels"]
    dashboard = feature_sets["dashboard"]
    dashboard_strike_levels = feature_sets["dashboard_strike_levels"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(out, index=False)
    strike_out = Path(args.strike_levels_out)
    strike_out.parent.mkdir(parents=True, exist_ok=True)
    strike_levels.to_csv(strike_out, index=False)
    dashboard_out = Path(args.dashboard_out) if args.dashboard_out else None
    if dashboard_out is not None:
        dashboard_out.parent.mkdir(parents=True, exist_ok=True)
        dashboard.to_csv(dashboard_out, index=False)
    dashboard_strike_out = Path(args.dashboard_strike_levels_out) if args.dashboard_strike_levels_out else None
    if dashboard_strike_out is not None:
        dashboard_strike_out.parent.mkdir(parents=True, exist_ok=True)
        dashboard_strike_levels.to_csv(dashboard_strike_out, index=False)

    print(f"Options-flow features: {out} ({len(daily):,} rows)")
    print(f"Options GEX strike surface: {strike_out} ({len(strike_levels):,} rows)")
    if dashboard_out is not None:
        print(f"Options DTE dashboard: {dashboard_out} ({len(dashboard):,} rows)")
    if dashboard_strike_out is not None:
        print(
            f"Options DTE dashboard strike surface: {dashboard_strike_out} "
            f"({len(dashboard_strike_levels):,} rows)"
        )
    if not daily.empty:
        cols = [
            "options_trade_date",
            "options_available_time",
            "options_total_oi",
            "options_net_gex",
            "options_gex_regime",
            "options_gamma_wall_strike",
        ]
        print(daily[[col for col in cols if col in daily.columns]].tail(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
