#!/usr/bin/env python3
"""Run the authoritative LucidFlex 25K causal evaluator (lucidflex_eval_v1).

Writes a new comparison artifact. Does not modify results/m3_portfolio_ratchet_simulation.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.dashboard_analytics import load_session_calendar, load_trades
from backtest.lucidflex_eval import (
    EQUITY_MODEL,
    SIMULATOR_ID,
    SIMULATOR_VERSION,
    LucidFlexEvalConfig,
    build_session_index,
    compile_trades,
    filter_strats,
    monte_carlo_block_bootstrap,
    sequential_campaigns,
)
from backtest.provenance import default_store
from config.prop_firm_registry import LUCID_FLEX_25K

CANONICAL_PARQUET = REPO_ROOT / "data/processed/unified_five_strategy_portfolio_trades_2021_2026.parquet"
EXPECTED_PARQUET_SHA256 = "84179526c91e3f04972ec4f75347328c3d3ff5853298692d47cb9a82b09d9bd2"
LEGACY_M3 = REPO_ROOT / "results/m3_portfolio_ratchet_simulation.json"
OUT_PATH = REPO_ROOT / "results/lucidflex_eval_v1_portfolio_comparison.json"

STRAT3 = ("S1", "S2", "S3")
STRAT5 = ("S1", "S2", "S3", "S4", "S5")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pack_portfolio(name: str, trades, calendar, cfg, n_paths, block_size, horizons, seed):
    compiled = compile_trades(trades)
    sessions, events = build_session_index(compiled, calendar)
    seq = sequential_campaigns(compiled, events, cfg)
    mc = monte_carlo_block_bootstrap(
        compiled, events, n_paths=n_paths, block_size=block_size, horizons=horizons, seed=seed, config=cfg,
    )
    return {
        "portfolio": name,
        "n_trades": int(len(trades)),
        "n_calendar_sessions": len(sessions),
        "sequential_historical": seq,
        "monte_carlo": mc,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Authoritative LucidFlex 25K causal evaluation")
    p.add_argument("--n-paths", type=int, default=10_000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--block-size", type=int, default=5)
    p.add_argument("--horizons", type=str, default="252,260,750")
    args = p.parse_args()
    horizons = tuple(int(x) for x in args.horizons.split(",") if x.strip())

    data_hash = sha256_file(CANONICAL_PARQUET)
    if data_hash != EXPECTED_PARQUET_SHA256:
        print(f"WARNING: parquet hash {data_hash} != expected {EXPECTED_PARQUET_SHA256}")

    trades = load_trades(CANONICAL_PARQUET)
    calendar = load_session_calendar(start="2021-01-04", end="2026-10-30")
    cfg = LucidFlexEvalConfig()
    git = default_store.get_git_commit()

    print(f"{SIMULATOR_ID} {SIMULATOR_VERSION}  n_paths={args.n_paths}  seed={args.seed}")
    print(f"equity_model={EQUITY_MODEL}  calendar_sessions={len(calendar)}")
    print("Running 3-strategy...")
    three = pack_portfolio("S1-S3", filter_strats(trades, STRAT3), calendar, cfg, args.n_paths, args.block_size, horizons, args.seed)
    print("Running 5-strategy...")
    five = pack_portfolio("S1-S5", filter_strats(trades, STRAT5), calendar, cfg, args.n_paths, args.block_size, horizons, args.seed)

    payload = {
        "simulator_id": SIMULATOR_ID,
        "simulator_version": SIMULATOR_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": git,
        "data_path": str(CANONICAL_PARQUET.relative_to(REPO_ROOT)),
        "data_sha256": data_hash,
        "random_seed": args.seed,
        "block_size_sessions": args.block_size,
        "horizons_sessions": list(horizons),
        "n_paths": args.n_paths,
        "equity_model": EQUITY_MODEL,
        "equity_model_limitation": (
            "S1-S3 bundles have no intraday marks. DLL and trailing-floor checks use "
            "realized P&L at recorded exit_time only. Not an execution-validated backtest."
        ),
        "config": {
            "product": "LucidFlex 25K",
            "starting_balance": cfg.starting_balance,
            "profit_target": cfg.profit_target,
            "max_loss_limit": cfg.max_loss_limit,
            "drawdown": "EOD trailing; floor updates only at session close",
            "consistency_pct": cfg.consistency_pct,
            "consistency_formula": "largest_single_day_profit / total_account_profit",
            "dll_enabled": cfg.dll_enabled,
            "daily_loss_limit": cfg.daily_loss_limit,
            "dll_behavior": "Soft halt of new entries; no P&L clipping; open trades settle at recorded exits",
            "evaluation_time_limit": None,
            "official_firm_max_micros": cfg.official_firm_max_micros,
            "official_firm_max_minis": cfg.official_firm_max_minis,
            "internal_risk_cap_micros": cfg.internal_risk_cap_micros,
            "internal_risk_cap_note": "Conservative portfolio policy, not Lucid official max",
            "ratchet": {
                "t2": cfg.ratchet_t2,
                "t3": cfg.ratchet_t3,
                "safe_cppi": cfg.enable_safe_cppi,
                "cppi_buffer": cfg.cppi_buffer,
                "finish_line_shield": cfg.enable_finish_line_shield,
                "finish_line_profit": cfg.finish_line_profit,
                "note": "Optional portfolio sizing policy, not a Lucid firm rule",
            },
            "eval_ticket_cost": cfg.eval_ticket_cost,
            "registry_ticket": LUCID_FLEX_25K.EVAL_TICKET_COST,
        },
        "legacy_m3_comparison_only": {
            "artifact": "results/m3_portfolio_ratchet_simulation.json",
            "sha256": sha256_file(LEGACY_M3) if LEGACY_M3.exists() else None,
            "five_strategy_pass_pct": 72.79,
            "three_strategy_pass_pct": 69.18,
            "five_strategy_fail_pct": 19.83,
            "three_strategy_fail_pct": 19.50,
            "five_strategy_unresolved_pct": 7.38,
            "three_strategy_unresolved_pct": 11.32,
            "note": "Historical M3 outputs. Not targets and not lifetime probabilities.",
        },
        "sizing_grid_not_this_simulator": {
            "artifact": "results/sizing_cushion_optimization/evaluation_pareto_frontier.csv",
            "balanced_champion_pass_pct": 72.24,
            "note": "dashboard_analytics.run_evaluation grid (T2=$100,T3=$600, 750 sessions). Distinct experiment.",
        },
        "three_strategy": three,
        "five_strategy": five,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")

    def brief(tag, block):
        seq = block["sequential_historical"]
        print(f"\n{tag} sequential: pass={seq['n_pass']} fail={seq['n_fail']} unresolved={seq['n_unresolved']}")
        for h, row in block["monte_carlo"]["horizons"].items():
            print(
                f"  h={h}: pass={row['n_pass']} fail={row['n_fail']} unresolved={row['n_unresolved']} "
                f"pass/all={row['pass_div_all_paths_pct']}% pass/resolved={row['pass_div_resolved_pct']}%"
            )

    brief("S1-S3", three)
    brief("S1-S5", five)
    print("\nUnresolved paths are not failed and are not a new evaluation fee.")
    print("Results are not a lifetime pass probability while unresolved remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
