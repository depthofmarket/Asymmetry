#!/usr/bin/env python3
"""Regenerate in-sample study trade lists through 2024-12-31.

S1-S3 use the Java chart-tracker rules in backtest.study_chart_replay.
S5 uses the current crude simulator and its stated commission and slippage.
No bar at or after 2025-01-01 is read. This is not a walk-forward test and
it does not replace the historical provenance rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.provenance import ProvenanceStore, default_store
from backtest.study_chart_replay import (
    OOS_START,
    ReplaySpec,
    frozen_parameters,
    load_insample_bars,
    replay_gold_fix,
    replay_macro_0835,
    replay_morning_va,
    parameter_sha256,
    summarize,
    trade_list_sha256,
)
from config.strategy_registry import StrategyTier
from strategies.crude_rth_expansion_s5 import CrudeRthExpansionParams, CrudeRthExpansionS5

INSAMPLE_END = "2024-12-31"
OLD_S5_RUN_ID = "run_canonical_s5_crude_rth_expansion_2021_2026"
NEW_S5_RUN_ID = "run_insample_s5_current_simulator_2021_2024"
DATA = {
    "nq": REPO_ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet",
    "es": REPO_ROOT / "data/raw/es_1m_2020_2026_cqg_et.parquet",
    "gc": REPO_ROOT / "data/raw/gc_1m_2020_2026_et.parquet",
    "cl": REPO_ROOT / "data/raw/cl_1m_2020_2026_et.parquet",
}
def full_git_sha() -> str:
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip()


def slice_sha256(frame: pd.DataFrame) -> str:
    """Hash only the bars the replay sees. The source files continue past 2024."""
    out = frame.loc[:, ["time", "open", "high", "low", "close", "volume"]].copy()
    out["time"] = pd.to_datetime(out["time"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = out[col].map(lambda v: f"{float(v):.10f}")
    return hashlib.sha256(out.to_csv(index=False).encode("utf-8")).hexdigest()


def reject_oos_end(end: str) -> None:
    if end > INSAMPLE_END:
        raise SystemExit(
            f"Refusing end date {end}. Dates after {INSAMPLE_END} are protected and are not read."
        )


def s5_bars() -> pd.DataFrame:
    frame = pd.read_parquet(DATA["cl"], columns=["time", "open", "high", "low", "close", "volume"])
    frame["time"] = pd.to_datetime(frame["time"])
    frame = frame.loc[frame["time"] < OOS_START].sort_values("time").reset_index(drop=True)
    if frame.empty or frame["time"].max() >= OOS_START:
        raise SystemExit("S5 in-sample slice is empty or contains a protected bar.")
    return frame


def s5_frame(end: str) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    reject_oos_end(end)
    bars = s5_bars()
    strategy = CrudeRthExpansionS5(params=CrudeRthExpansionParams())
    trades, metrics = strategy.backtest(
        data=bars,
        start_date="2021-01-04",
        end_date=end,
    )
    if not trades.empty:
        if pd.to_datetime(trades["entry_time"]).max() >= OOS_START:
            raise SystemExit("S5 backtest emitted a protected-period entry.")
    return trades, metrics, bars


def s5_trade_hash(trades: pd.DataFrame) -> str:
    cols = [
        "date", "direction", "entry_time", "exit_time", "entry_price", "exit_price",
        "contracts", "gross_pnl", "commission", "slippage", "net_pnl", "exit_reason",
    ]
    frame = trades.loc[:, cols].copy()
    frame["entry_time"] = pd.to_datetime(frame["entry_time"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    frame["exit_time"] = pd.to_datetime(frame["exit_time"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    for col in ("entry_price", "exit_price", "gross_pnl", "commission", "slippage", "net_pnl"):
        frame[col] = frame[col].map(lambda v: f"{float(v):.10f}")
    return hashlib.sha256(frame.to_csv(index=False).encode("utf-8")).hexdigest()


def record_new_run(store: ProvenanceStore, run_id: str, **kwargs) -> None:
    existing = store.get_run(run_id)
    if existing is not None:
        previous = (existing.params or {}).get("trade_list_sha256")
        current = (kwargs.get("params") or {}).get("trade_list_sha256")
        if previous != current:
            raise SystemExit(f"{run_id} already exists with a different trade-list hash. It was not overwritten.")
        print(f"Record {run_id} already matches this trade list. Historical rows were not rewritten.")
        return
    if store.get_run(OLD_S5_RUN_ID) is None:
        raise SystemExit(f"Missing historical record {OLD_S5_RUN_ID}.")
    before = store.get_run(OLD_S5_RUN_ID)
    store.record_run(run_id=run_id, git_commit=full_git_sha(), **kwargs)
    after = store.get_run(OLD_S5_RUN_ID)
    if before.total_trades != after.total_trades or before.net_profit != after.net_profit:
        raise SystemExit("Historical S5 provenance changed. This command must not do that.")


def replay_charts() -> list[dict]:
    bars = {key: load_insample_bars(path) for key, path in DATA.items() if key != "cl"}
    jobs = [
        (ReplaySpec("morning_va_breakout_s1", "MNQ", 2.0, 0.25, "LucidMorningVABreakoutStudy"), bars["nq"], replay_morning_va),
        (ReplaySpec("morning_va_breakout_s1", "MES", 5.0, 0.25, "LucidMorningVABreakoutStudy"), bars["es"], replay_morning_va),
        (ReplaySpec("macro_momentum_s2", "MNQ", 2.0, 0.25, "LucidMacroMomentumStudy"), bars["nq"], replay_macro_0835),
        (ReplaySpec("gold_london_fix_s3", "MGC", 1.0, 0.10, "LucidGoldFixBreakoutStudy"), bars["gc"], replay_gold_fix),
    ]
    reports = []
    for spec, frame, fn in jobs:
        trades = fn(frame, spec)
        stats = summarize(trades)
        params = frozen_parameters(spec)
        digest = trade_list_sha256(trades) if not trades.empty else hashlib.sha256(b"").hexdigest()
        data_key = {"MNQ": "nq", "MES": "es", "MGC": "gc"}[spec.instrument]
        reports.append({
            "spec": spec,
            "bars": frame,
            "trades": trades,
            "stats": stats,
            "params": params,
            "trade_hash": digest,
            "data_path": DATA[data_key],
            "data_hash": slice_sha256(frame),
        })
    return reports


def print_report(row: dict, sha: str) -> None:
    stats = row["stats"]
    print(
        f"{row['spec'].strategy_id} {row['spec'].instrument} | trades {stats['trades']} | "
        f"gross ${stats['gross_pnl']:.2f} | commission ${stats['commission_usd']:.2f} | "
        f"slippage ${stats['slippage_usd']:.2f} | net ${stats['net_pnl']:.2f} | "
        f"PF {stats['profit_factor']:.4f} | maxDD {stats['max_drawdown']:.2f}"
    )
    print(f"  data_sha256 {row['data_hash']}")
    print(f"  parameter_sha256 {row['params']['parameter_sha256']}")
    print(f"  trade_list_sha256 {row['trade_hash']}")
    print(f"  git {sha}")
    print("  costs: Java chart tracker deducts neither commission nor slippage. Both are 0.")
    print("  fill: target is tested before stop on a later bar. Live market slippage is not modeled.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate in-sample study trades through 2024-12-31.")
    parser.add_argument("--end", default=INSAMPLE_END)
    parser.add_argument("--record", action="store_true", help="Insert new provenance rows. Does not update old run ids.")
    args = parser.parse_args()
    reject_oos_end(args.end)
    sha = full_git_sha()
    print(f"In-sample rebuild through {args.end}. Bars at or after 2025-01-01 are not read.")
    print(f"Git {sha}")

    reports = replay_charts()
    for row in reports:
        print_report(row, sha)
        if args.record:
            spec = row["spec"]
            stats = row["stats"]
            params = dict(row["params"])
            params["trade_list_sha256"] = row["trade_hash"]
            params["insample_slice_sha256"] = row["data_hash"]
            params["source_file"] = str(row["data_path"].relative_to(REPO_ROOT))
            slice_path = REPO_ROOT / "results" / "insample_rebuild" / f"{spec.strategy_id}_{spec.instrument.lower()}_bars_through_2024.parquet"
            slice_path.parent.mkdir(parents=True, exist_ok=True)
            row["bars"].to_parquet(slice_path, index=False)
            run_id = f"run_insample_{spec.strategy_id}_{spec.instrument.lower()}_chart_tracker_2021_2024"
            record_new_run(
                default_store,
                run_id,
                strategy_id=spec.strategy_id,
                strategy_name=f"{spec.strategy_id} chart tracker {spec.instrument}",
                methodology="insample_java_chart_tracker",
                date_start="2021-01-01",
                date_end=args.end,
                data_path=str(slice_path.relative_to(REPO_ROOT)),
                total_trades=stats["trades"],
                win_rate=stats["win_rate"],
                profit_factor=stats["profit_factor"],
                gross_profit=float(row["trades"].loc[row["trades"]["net_pnl"] > 0, "net_pnl"].sum()) if stats["trades"] else 0.0,
                net_profit=stats["net_pnl"],
                max_drawdown=stats["max_drawdown"],
                sharpe_ratio=0.0,
                largest_win=stats["largest_win"],
                strategy_tier=StrategyTier.BASELINE,
                slippage_model="none: Java chart tracker fills exact stop, target, or close",
                commission_model="none: Java chart tracker does not deduct commission",
                is_net=False,
                params=params,
                notes=(
                    "Deterministic in-sample chart-tracker replay of the current Java study. "
                    "Not a verification of the frozen trade parquet and not a profitability claim. "
                    f"trade_list_sha256={row['trade_hash']}"
                ),
                explicit_warnings=["GROSS_EXECUTION: Java chart tracker applies no commission or slippage"],
            )

    trades, metrics, cl_bars = s5_frame(args.end)
    digest = s5_trade_hash(trades) if not trades.empty else hashlib.sha256(b"").hexdigest()
    gross = float(trades["gross_pnl"].sum()) if not trades.empty else 0.0
    commission = float(trades["commission"].sum()) if not trades.empty else 0.0
    slippage = float(trades["slippage"].sum()) if not trades.empty else 0.0
    print(
        f"crude_rth_expansion_s5 MCL | trades {metrics['total_trades']} | "
        f"gross ${gross:.2f} | commission ${commission:.2f} | slippage ${slippage:.2f} | "
        f"net ${metrics['net_profit']:.2f} | PF {metrics['profit_factor']:.4f} | "
        f"maxDD {metrics['max_drawdown']:.2f}"
    )
    data_hash = slice_sha256(cl_bars)
    params = CrudeRthExpansionParams()
    param_hash = parameter_sha256(asdict(params))
    print(f"  data_sha256 {data_hash}")
    print(f"  parameter_sha256 {param_hash}")
    print(f"  trade_list_sha256 {digest}")
    print(f"  git {sha}")
    print("  costs: current simulator, $3.50 round turn, 1-tick entry, 2-tick stop, 1-tick target.")
    print("  This in-sample run is not the historical 102-trade record.")
    if args.record:
        cl_slice = REPO_ROOT / "results" / "insample_rebuild" / "crude_rth_expansion_s5_bars_through_2024.parquet"
        cl_slice.parent.mkdir(parents=True, exist_ok=True)
        cl_bars.to_parquet(cl_slice, index=False)
        record_new_run(
            default_store,
            NEW_S5_RUN_ID,
            strategy_id="crude_rth_expansion_s5",
            strategy_name="Crude Oil Post-Fix Range Expansion (10:15 ET)",
            methodology="insample_current_simulator",
            date_start="2021-01-04",
            date_end=args.end,
            data_path=str((REPO_ROOT / "results" / "insample_rebuild" / "crude_rth_expansion_s5_bars_through_2024.parquet").relative_to(REPO_ROOT)),
            total_trades=int(metrics["total_trades"]),
            win_rate=float(metrics["win_rate"]),
            profit_factor=float(metrics["profit_factor"]),
            gross_profit=float(metrics["gross_profit"]),
            net_profit=float(metrics["net_profit"]),
            max_drawdown=float(metrics["max_drawdown"]),
            sharpe_ratio=float(metrics["sharpe_ratio"]),
            largest_win=float(metrics["largest_win"]),
            strategy_tier=StrategyTier.CANDIDATE,
            slippage_model="1-tick entry and target, 2-tick stop or flatten, next-bar breakeven",
            commission_model="$3.50 RT micro energy",
            is_net=True,
            params={
                "trade_list_sha256": digest,
                "parameter_sha256": param_hash,
                "insample_slice_sha256": data_hash,
                "source_file": str(DATA["cl"].relative_to(REPO_ROOT)),
                "frozen_parameters": {
                    "stop_loss_pts": params.stop_loss_pts,
                    "profit_target_pts": params.profit_target_pts,
                    "breakeven_trigger_pts": params.breakeven_trigger_pts,
                    "breakeven_lock_pts": params.breakeven_lock_pts,
                    "commission_round_trip": params.commission_round_trip,
                },
            },
            notes=(
                "Current simulator on bars through 2024-12-31 only. "
                "On that slice, ec17df0 produced 72 trades and this code produced 60. "
                "963dec1 delays entry until 30 observed trade-window bars: 12 dates disappear and 40 shared dates enter later. "
                "7da64ec applies breakeven on the next bar; no in-sample trade with the same entry timestamp changed exit. "
                "Does not replace run_canonical_s5_crude_rth_expansion_2021_2026. "
                f"trade_list_sha256={digest}"
            ),
        )
    print(json.dumps({"s5_trade_list_sha256": digest, "git": sha}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
