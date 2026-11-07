#!/usr/bin/env python3
"""
Asymmetry Native Model Context Protocol (MCP) Server.

Exposes Asymmetry quantitative backtest records, institutional metrics,
Open Backtest Format (.obtf) bundles, and strategy comparisons directly
to AI agents (Antigravity, Claude, Codex) over standard JSON-RPC 2.0 (stdio).

Tools provided:
1. asymmetry_query_stat: Query verified performance/risk stat with Rule 2/3 provenance footer.
2. asymmetry_list_runs: List all verified canonical backtest runs.
3. asymmetry_compare_strategies: Head-to-head multi-dimensional quant comparison.
4. asymmetry_inspect_bundle: Granular execution forensics from .obtf bundles.
5. asymmetry_verify_data_hash: Cryptographic SHA-256 dataset verification.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.bundle import BacktestBundle
from backtest.provenance import ProvenanceRecord, ProvenanceStore, default_store

SERVER_NAME = "asymmetry-quant-server"
SERVER_VERSION = "2.0.0"
PROTOCOL_VERSION = "2024-11-05"

# Configure logging to stderr (stdio is reserved strictly for JSON-RPC)
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [AsymmetryMCP] %(message)s",
)
logger = logging.getLogger("AsymmetryMCP")


# =============================================================================
# TOOL REGISTRY & SCHEMAS
# =============================================================================

TOOLS_METADATA = [
    {
        "name": "asymmetry_query_stat",
        "description": (
            "Query a specific performance or risk metric for an authorized trading strategy "
            "from the verified backtest provenance store (Rule 1). Returns metric with mandatory "
            "methodology, exact dates, dataset SHA-256 hash, and provenance verification footer (Rule 2 & 3). "
            "Supports 92 metrics: sortino, calmar, omega, cvar95, ulcer_index, half_kelly, "
            "trimmed_profit_factor, top_5_wins_pct, profit_factor, net_profit, max_drawdown, win_rate."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy_id": {
                    "type": "string",
                    "description": "Strategy ID (e.g. 'morning_va_breakout_s1', 'macro_momentum_s2', 'gold_london_fix_s3', 'lucid_flex_ensemble')",
                },
                "stat_name": {
                    "type": "string",
                    "description": "Metric name or alias (e.g. 'sortino', 'calmar', 'omega', 'cvar95', 'ulcer_index', 'half_kelly', 'profit_factor')",
                },
                "tier": {
                    "type": "string",
                    "description": "Optional strategy tier filter ('BASELINE', 'FORWARD_DEMO', 'CANDIDATE', 'ALL')",
                },
            },
            "required": ["strategy_id", "stat_name"],
        },
    },
    {
        "name": "asymmetry_list_runs",
        "description": "List all verified backtest runs stored in results/backtest_provenance.db with key performance metrics and warning flags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy_id": {
                    "type": "string",
                    "description": "Optional strategy filter",
                },
                "tier": {
                    "type": "string",
                    "description": "Optional tier filter ('BASELINE', 'FORWARD_DEMO', 'CANDIDATE', 'ALL')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max runs to return (default 20)",
                    "default": 20,
                },
            },
        },
    },
    {
        "name": "asymmetry_compare_strategies",
        "description": "Perform an institutional multi-dimensional comparison between two strategies or ensembles across 9 performance dimensions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy_a": {
                    "type": "string",
                    "description": "First strategy ID (e.g. 'morning_va_breakout_s1')",
                },
                "strategy_b": {
                    "type": "string",
                    "description": "Second strategy ID (e.g. 'lucid_flex_ensemble')",
                },
            },
            "required": ["strategy_a", "strategy_b"],
        },
    },
    {
        "name": "asymmetry_inspect_bundle",
        "description": "Inspect granular trade execution analytics, MFE/MAE excursions, and top wins/losses from an Open Backtest Format (.obtf) bundle.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy_id": {
                    "type": "string",
                    "description": "Strategy ID (inspects latest bundle for strategy)",
                },
                "run_id": {
                    "type": "string",
                    "description": "Explicit run ID to inspect",
                },
            },
        },
    },
    {
        "name": "asymmetry_verify_data_hash",
        "description": "Compute and verify the cryptographic SHA-256 hash of a data file against known provenance records.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative or absolute path to dataset file",
                },
            },
            "required": ["filepath"],
        },
    },
]


# =============================================================================
# TOOL HANDLERS
# =============================================================================

def handle_query_stat(args: Dict[str, Any]) -> str:
    strategy_id = args.get("strategy_id", "").strip()
    stat_name = args.get("stat_name", "").strip()
    tier = args.get("tier")
    include_candidates = bool(tier and tier.upper() in ("CANDIDATE", "ALL"))

    record = default_store.get_latest_run(strategy_id=strategy_id, include_candidates=include_candidates)
    if not record:
        return f"Error: No verified backtest run found for strategy '{strategy_id}' in results/backtest_provenance.db."

    return default_store.quote_stat(record, stat_name)


def handle_list_runs(args: Dict[str, Any]) -> str:
    strategy_id = args.get("strategy_id")
    tier = args.get("tier")
    limit = int(args.get("limit", 20))
    include_candidates = bool(tier and tier.upper() in ("CANDIDATE", "ALL"))

    runs = default_store.list_runs(
        strategy_id=strategy_id,
        tier=tier,
        include_candidates=include_candidates,
        limit=limit,
    )
    if not runs:
        return "No verified runs found matching criteria."

    lines = [
        f"{'RUN ID':<34} | {'STRATEGY':<22} | {'TIER':<10} | {'PF':<5} | {'SORTINO':<7} | {'NET PNL':<10} | {'WARN':<5}",
        "-" * 105,
    ]
    for r in runs:
        warn = "⚠️ " if r.warnings else "✅ "
        tier_str = getattr(r, "strategy_tier", "BASELINE") or "BASELINE"
        lines.append(
            f"{r.run_id:<34} | {r.strategy_id:<22} | {tier_str:<10} | {r.profit_factor:<5.2f} | "
            f"{r.sortino_ratio:<7.2f} | ${r.net_profit:<9,.2f} | {warn}"
        )

    return "\n".join(lines)


def handle_compare_strategies(args: Dict[str, Any]) -> str:
    strat_a = args.get("strategy_a", "").strip()
    strat_b = args.get("strategy_b", "").strip()

    rec_a = default_store.get_latest_run(strategy_id=strat_a, include_candidates=True)
    rec_b = default_store.get_latest_run(strategy_id=strat_b, include_candidates=True)

    if not rec_a:
        return f"Error: Strategy '{strat_a}' not found in provenance store."
    if not rec_b:
        return f"Error: Strategy '{strat_b}' not found in provenance store."

    def fmt_num(v: Any, prefix: str = "", suffix: str = "", decimals: int = 2) -> str:
        if isinstance(v, (int, float)):
            return f"{prefix}{v:,.{decimals}f}{suffix}"
        return str(v)

    rows = [
        ("Strategy Name", rec_a.strategy_name, rec_b.strategy_name),
        ("Strategy ID", rec_a.strategy_id, rec_b.strategy_id),
        ("Strategy Tier", rec_a.strategy_tier, rec_b.strategy_tier),
        ("Methodology", rec_a.methodology, rec_b.methodology),
        ("Evaluation Span", f"{rec_a.days_count} days", f"{rec_b.days_count} days"),
        ("Total Trades (N)", str(rec_a.total_trades), str(rec_b.total_trades)),
        ("Win Rate", fmt_num(rec_a.win_rate, suffix="%"), fmt_num(rec_b.win_rate, suffix="%")),
        ("Profit Factor", fmt_num(rec_a.profit_factor), fmt_num(rec_b.profit_factor)),
        ("Net Profit", fmt_num(rec_a.net_profit, prefix="$"), fmt_num(rec_b.net_profit, prefix="$")),
        ("Max Drawdown", fmt_num(abs(rec_a.max_drawdown), prefix="-$"), fmt_num(abs(rec_b.max_drawdown), prefix="-$")),
        ("Sharpe Ratio", fmt_num(rec_a.sharpe_ratio), fmt_num(rec_b.sharpe_ratio)),
        ("Sortino Ratio", fmt_num(rec_a.sortino_ratio), fmt_num(rec_b.sortino_ratio)),
        ("Calmar Ratio", fmt_num(rec_a.calmar_ratio), fmt_num(rec_b.calmar_ratio)),
        ("Omega Ratio", fmt_num(rec_a.omega_ratio), fmt_num(rec_b.omega_ratio)),
        ("CVaR 95% (Tail)", fmt_num(rec_a.cvar_95, prefix="$"), fmt_num(rec_b.cvar_95, prefix="$")),
        ("Ulcer Index", fmt_num(rec_a.ulcer_index, suffix="%"), fmt_num(rec_b.ulcer_index, suffix="%")),
        ("Half-Kelly Sizing", fmt_num(rec_a.half_kelly, decimals=3), fmt_num(rec_b.half_kelly, decimals=3)),
        ("Largest Win", fmt_num(rec_a.largest_win, prefix="$"), fmt_num(rec_b.largest_win, prefix="$")),
        ("Outlier Win % Net", fmt_num(rec_a.largest_win_pct_of_net, suffix="%"), fmt_num(rec_b.largest_win_pct_of_net, suffix="%")),
        ("Active Warnings", ", ".join(rec_a.warnings) or "None (Clean)", ", ".join(rec_b.warnings) or "None (Clean)"),
        ("Bundle (.obtf)", rec_a.bundle_path or "None", rec_b.bundle_path or "None"),
    ]

    out = [
        f"### Institutional Strategy Comparison: `{strat_a}` vs `{strat_b}`\n",
        f"| Metric | `{rec_a.strategy_id}` | `{rec_b.strategy_id}` |",
        f"| :--- | :--- | :--- |",
    ]
    for metric_name, val_a, val_b in rows:
        out.append(f"| **{metric_name}** | {val_a} | {val_b} |")

    return "\n".join(out)


def handle_inspect_bundle(args: Dict[str, Any]) -> str:
    run_id = args.get("run_id")
    strategy_id = args.get("strategy_id")

    record: Optional[ProvenanceRecord] = None
    if run_id:
        record = default_store.get_run(run_id)
    elif strategy_id:
        record = default_store.get_latest_run(strategy_id=strategy_id, include_candidates=True)
    else:
        record = default_store.get_latest_run(include_candidates=True)

    if not record:
        return "Error: No matching backtest run found."
    if not record.bundle_path:
        return f"Error: Run '{record.run_id}' has no associated .obtf bundle in store."

    bundle_path = REPO_ROOT / record.bundle_path
    if not bundle_path.exists():
        return f"Error: Bundle file '{bundle_path}' not found on disk."

    bundle = BacktestBundle.load(bundle_path)
    summary = bundle.get_summary()

    lines = [
        f"================================================================================",
        f"OPEN BACKTEST FORMAT (.obtf) BUNDLE INSPECTION",
        f"================================================================================",
        f"Run ID       : {summary['run_id']}",
        f"Strategy     : {summary['strategy_id']} ({summary['strategy_name']}) [{summary['tier']}]",
        f"Bundle File  : {record.bundle_path} ({bundle_path.stat().st_size:,} bytes)",
        f"Date Range   : {summary['date_range']} | Trades: {summary['trades_count']}",
        f"--------------------------------------------------------------------------------",
        f"CORE EXECUTION METRICS:",
    ]
    for k, v in summary["core_metrics"].items():
        lines.append(f"  {k:<22}: {v}")
    lines.append(f"--------------------------------------------------------------------------------")
    lines.append(f"INSTITUTIONAL RISK DYNAMICS:")
    for k, v in summary["institutional_risk"].items():
        lines.append(f"  {k:<25}: {v}")
    lines.append(f"--------------------------------------------------------------------------------")

    if not bundle.trades.empty:
        pnl_col = "research_pnl" if "research_pnl" in bundle.trades.columns else ("net_pnl" if "net_pnl" in bundle.trades.columns else "pnl")
        top_wins = bundle.trades.nlargest(3, pnl_col)[[pnl_col, "date"]].to_dict(orient="records")
        worst_losses = bundle.trades.nsmallest(3, pnl_col)[[pnl_col, "date"]].to_dict(orient="records")
        lines.append("TOP 3 WINNING TRADES:")
        for t in top_wins:
            lines.append(f"  +${t[pnl_col]:,.2f} on {t.get('date', 'N/A')}")
        lines.append("WORST 3 LOSING TRADES:")
        for t in worst_losses:
            lines.append(f"  -${abs(t[pnl_col]):,.2f} on {t.get('date', 'N/A')}")
    lines.append(f"================================================================================")

    return "\n".join(lines)


def handle_verify_data_hash(args: Dict[str, Any]) -> str:
    filepath = args.get("filepath", "").strip()
    if not filepath:
        return "Error: filepath argument is required."

    p = Path(filepath)
    if not p.is_absolute() and not p.exists() and (REPO_ROOT / p).exists():
        p = REPO_ROOT / p
    h = default_store.compute_data_hash(p)
    if h == "file_not_found":
        return f"Error: File '{filepath}' does not exist."

    canon_runs = default_store.list_runs(limit=100)
    matching_runs = [r.strategy_id for r in canon_runs if r.data_hash == h]

    match_str = f"Matches {len(matching_runs)} runs: {', '.join(set(matching_runs))}" if matching_runs else "No historical runs currently link to this hash."

    return (
        f"Dataset      : {filepath}\n"
        f"SHA-256 Hash : {h}\n"
        f"Status       : {match_str}"
    )


TOOL_DISPATCH = {
    "asymmetry_query_stat": handle_query_stat,
    "asymmetry_list_runs": handle_list_runs,
    "asymmetry_compare_strategies": handle_compare_strategies,
    "asymmetry_inspect_bundle": handle_inspect_bundle,
    "asymmetry_verify_data_hash": handle_verify_data_hash,
}


# =============================================================================
# JSON-RPC 2.0 PROTOCOL ENGINE
# =============================================================================

def process_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})

    logger.info(f"Incoming RPC: method='{method}' id={req_id}")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            },
        }

    elif method == "notifications/initialized":
        # Notification: no response required
        return None

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS_METADATA},
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        if tool_name not in TOOL_DISPATCH:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method/Tool '{tool_name}' not found",
                },
            }

        try:
            handler = TOOL_DISPATCH[tool_name]
            result_text = handler(tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": str(result_text)}],
                    "isError": False,
                },
            }
        except Exception as e:
            logger.exception(f"Error executing tool '{tool_name}': {e}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Tool Execution Error: {str(e)}"}],
                    "isError": True,
                },
            }

    elif method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"resources": []},
        }

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {
                "code": -32601,
                "message": f"Unrecognized JSON-RPC method: {method}",
            },
        }


def run_stdio_server():
    """Main event loop over standard input / output."""
    logger.info(f"Starting {SERVER_NAME} v{SERVER_VERSION} on stdio...")
    for line in sys.stdin:
        line_str = line.strip()
        if not line_str:
            continue
        try:
            req = json.loads(line_str)
            resp = process_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError as err:
            logger.error(f"Malformed JSON: {err}")
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()
        except Exception as e:
            logger.exception(f"Unhandled server exception: {e}")


def main():
    parser = argparse.ArgumentParser(description="Asymmetry Native Model Context Protocol (MCP) Server")
    parser.add_argument("--test", action="store_true", help="Run self-diagnostic test battery on all tools")
    parser.add_argument("--call", type=str, help="Call a specific tool directly (e.g. asymmetry_query_stat)")
    parser.add_argument("--args", type=str, default="{}", help="JSON arguments string for --call")
    args = parser.parse_args()

    if args.test:
        print("Running Asymmetry MCP Server Self-Diagnostic Battery...")
        # 1. Test tools/list
        res_list = process_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = res_list["result"]["tools"]
        print(f"  [PASS] Registered {len(tools)} tools: {[t['name'] for t in tools]}")

        # 2. Test asymmetry_query_stat
        res_query = process_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "asymmetry_query_stat", "arguments": {"strategy_id": "morning_va_breakout_s1", "stat_name": "sortino"}},
        })
        text = res_query["result"]["content"][0]["text"]
        assert "1.75" in text
        print(f"  [PASS] asymmetry_query_stat (Sortino: 1.75 verified)")

        # 3. Test asymmetry_inspect_bundle
        res_bundle = process_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "asymmetry_inspect_bundle", "arguments": {"strategy_id": "morning_va_breakout_s1"}},
        })
        b_text = res_bundle["result"]["content"][0]["text"]
        assert "OPEN BACKTEST FORMAT" in b_text
        print(f"  [PASS] asymmetry_inspect_bundle (OBTF bundle verified)")

        # 4. Test asymmetry_compare_strategies
        res_comp = process_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "asymmetry_compare_strategies", "arguments": {"strategy_a": "morning_va_breakout_s1", "strategy_b": "lucid_flex_ensemble"}},
        })
        c_text = res_comp["result"]["content"][0]["text"]
        assert "Institutional Strategy Comparison" in c_text
        print(f"  [PASS] asymmetry_compare_strategies (Side-by-side comparison verified)")

        print("All MCP Server Diagnostics Passed Cleanly (100% Operational)!")
        return

    if args.call:
        tool_args = json.loads(args.args)
        if args.call not in TOOL_DISPATCH:
            print(f"Error: Unknown tool '{args.call}'", file=sys.stderr)
            sys.exit(1)
        res = TOOL_DISPATCH[args.call](tool_args)
        print(res)
        return

    # Run standard I/O loop
    run_stdio_server()


if __name__ == "__main__":
    main()
