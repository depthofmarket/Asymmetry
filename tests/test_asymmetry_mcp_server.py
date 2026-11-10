"""
Unit test suite for Asymmetry Native Model Context Protocol (MCP) Server.
Verifies JSON-RPC 2.0 dispatching, tool declarations, error handling,
and compliance with the 5 Golden Rules of Quantitative Provenance.
"""

import json
import subprocess
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.asymmetry_mcp_server import process_request, TOOLS_METADATA, SERVER_NAME


def test_mcp_initialize():
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "TestClient", "version": "1.0"},
        },
    }
    resp = process_request(req)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "result" in resp
    res = resp["result"]
    assert res["serverInfo"]["name"] == SERVER_NAME
    assert "tools" in res["capabilities"]


def test_mcp_tools_list():
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }
    resp = process_request(req)
    assert "result" in resp
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert len(tools) == 10

    expected_tools = [
        "asymmetry_query_stat",
        "asymmetry_list_runs",
        "asymmetry_compare_strategies",
        "asymmetry_inspect_bundle",
        "asymmetry_verify_data_hash",
        "asymmetry_get_equity_curve",
        "asymmetry_get_trades",
        "asymmetry_get_monthly_returns",
        "asymmetry_rank_strategies",
        "asymmetry_log_research_note",
    ]
    for et in expected_tools:
        assert et in tool_names

    # Check that schemas have required fields
    for t in tools:
        assert "inputSchema" in t
        assert t["inputSchema"]["type"] == "object"
        assert "properties" in t["inputSchema"]


@pytest.mark.generated_results
def test_mcp_query_stat():
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "asymmetry_query_stat",
            "arguments": {
                "strategy_id": "morning_va_breakout_s1",
                "stat_name": "sortino_ratio",
            },
        },
    }
    resp = process_request(req)
    assert "result" in resp
    assert resp["result"]["isError"] is False
    content = resp["result"]["content"][0]["text"]
    assert "morning_va_breakout_s1" in content
    assert "PROVENANCE VERIFICATION FOOTER" in content
    assert "1.75" in content


@pytest.mark.generated_results
def test_mcp_list_runs():
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "asymmetry_list_runs",
            "arguments": {},
        },
    }
    resp = process_request(req)
    assert "result" in resp
    assert resp["result"]["isError"] is False
    content = resp["result"]["content"][0]["text"]
    assert "lucid_flex_ensemble" in content
    assert "morning_va_breakout_s1" in content
    assert "BASELINE" in content


@pytest.mark.generated_results
def test_mcp_compare_strategies():
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "asymmetry_compare_strategies",
            "arguments": {
                "strategy_a": "morning_va_breakout_s1",
                "strategy_b": "macro_momentum_s2",
            },
        },
    }
    resp = process_request(req)
    assert "result" in resp
    assert resp["result"]["isError"] is False
    content = resp["result"]["content"][0]["text"]
    assert "Institutional Strategy Comparison" in content
    assert "morning_va_breakout_s1" in content
    assert "macro_momentum_s2" in content
    assert "Sortino Ratio" in content


@pytest.mark.generated_results
def test_mcp_inspect_bundle():
    req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "tools/call",
        "params": {
            "name": "asymmetry_inspect_bundle",
            "arguments": {
                "strategy_id": "lucid_flex_ensemble",
            },
        },
    }
    resp = process_request(req)
    assert "result" in resp
    assert resp["result"]["isError"] is False
    content = resp["result"]["content"][0]["text"]
    assert "OPEN BACKTEST FORMAT (.obtf) BUNDLE INSPECTION" in content
    assert "CORE EXECUTION METRICS" in content
    assert "TOP 3 WINNING TRADES" in content
    assert "WORST 3 LOSING TRADES" in content


@pytest.mark.generated_results
def test_mcp_verify_data_hash():
    req = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "asymmetry_verify_data_hash",
            "arguments": {
                "filepath": "data/processed/unified_three_strategy_markov_portfolio_trades_2021_2026.parquet",
            },
        },
    }
    resp = process_request(req)
    assert "result" in resp
    assert resp["result"]["isError"] is False
    content = resp["result"]["content"][0]["text"]
    assert "Dataset" in content
    assert "SHA-256 Hash" in content
    assert "ecad8d063caa18344491c5c3050211c35f7383b0e8802f1178e3902306b686ca" in content
    assert "Matches" in content


@pytest.mark.generated_results
def test_mcp_get_equity_curve():
    req = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "tools/call",
        "params": {
            "name": "asymmetry_get_equity_curve",
            "arguments": {
                "strategy_id": "morning_va_breakout_s1",
                "max_rows": 10,
            },
        },
    }
    resp = process_request(req)
    assert "result" in resp
    assert resp["result"]["isError"] is False
    content = resp["result"]["content"][0]["text"]
    assert "Equity Curve & Drawdown Trajectory" in content
    assert "morning_va_breakout_s1" in content
    assert "Session Date" in content
    assert "Equity ($)" in content
    assert "Drawdown ($)" in content


@pytest.mark.generated_results
def test_mcp_get_trades():
    req = {
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {
            "name": "asymmetry_get_trades",
            "arguments": {
                "strategy_id": "morning_va_breakout_s1",
                "direction": "LONG",
                "outcome": "WIN",
                "limit": 5,
            },
        },
    }
    resp = process_request(req)
    assert "result" in resp
    assert resp["result"]["isError"] is False
    content = resp["result"]["content"][0]["text"]
    assert "Trade Execution Ledger" in content
    assert "morning_va_breakout_s1" in content
    assert "Trade ID" in content
    assert "Net PnL ($)" in content
    assert "long" in content.lower()


@pytest.mark.generated_results
def test_mcp_get_monthly_returns():
    req = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "asymmetry_get_monthly_returns",
            "arguments": {
                "strategy_id": "morning_va_breakout_s1",
            },
        },
    }
    resp = process_request(req)
    assert "result" in resp
    assert resp["result"]["isError"] is False
    content = resp["result"]["content"][0]["text"]
    assert "Monthly Return Matrix" in content
    assert "morning_va_breakout_s1" in content
    assert "Jan" in content
    assert "Dec" in content
    assert "Total ($)" in content
    assert "Winning Months" in content


@pytest.mark.generated_results
def test_mcp_rank_strategies():
    req = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "asymmetry_rank_strategies",
            "arguments": {
                "metric": "profit_factor",
                "limit": 5,
            },
        },
    }
    resp = process_request(req)
    assert "result" in resp
    assert resp["result"]["isError"] is False
    content = resp["result"]["content"][0]["text"]
    assert "Quantitative Strategy Leaderboard" in content
    assert "Rank" in content
    assert "PROFIT_FACTOR" in content
    assert "Win Rate" in content


def test_mcp_log_research_note(tmp_path, monkeypatch):
    import scripts.asymmetry_mcp_server as server_module

    # Create dummy wiki directory and log file in tmp_path
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    log_file = wiki_dir / "log.md"
    log_file.write_text("# Quantitative Research Log\n\n---\n\n## Historical Entry\n- Note\n", encoding="utf-8")

    monkeypatch.setattr(server_module, "REPO_ROOT", tmp_path)

    req = {
        "jsonrpc": "2.0",
        "id": 12,
        "method": "tools/call",
        "params": {
            "name": "asymmetry_log_research_note",
            "arguments": {
                "topic": "Test Confluence Engine Calibration",
                "summary": "Verified all 10 MCP tools under unit tests",
                "agent_name": "quant-developer",
                "action": "TEST",
                "verification": "pytest pass 100%",
            },
        },
    }
    resp = process_request(req)
    assert "result" in resp
    assert resp["result"]["isError"] is False
    content = resp["result"]["content"][0]["text"]
    assert "Research note successfully logged" in content

    # Verify written file content
    written_log = log_file.read_text(encoding="utf-8")
    assert "Test Confluence Engine Calibration" in written_log
    assert "quant-developer" in written_log
    assert "TEST" in written_log


def test_mcp_invalid_methods_and_errors():
    # Unknown method
    req_unknown = {"jsonrpc": "2.0", "id": 13, "method": "non_existent_method", "params": {}}
    resp = process_request(req_unknown)
    assert "error" in resp
    assert resp["error"]["code"] == -32601

    # Unknown tool in tools/call
    req_tool = {
        "jsonrpc": "2.0",
        "id": 14,
        "method": "tools/call",
        "params": {"name": "fake_tool", "arguments": {}},
    }
    resp = process_request(req_tool)
    assert "error" in resp
    assert resp["error"]["code"] == -32601

    # Unknown strategy in asymmetry_query_stat
    req_bad_strat = {
        "jsonrpc": "2.0",
        "id": 15,
        "method": "tools/call",
        "params": {
            "name": "asymmetry_query_stat",
            "arguments": {"strategy_id": "unregistered_strategy_xyz", "stat_name": "profit_factor"},
        },
    }
    resp = process_request(req_bad_strat)
    assert "result" in resp
    assert "No verified backtest run found" in resp["result"]["content"][0]["text"]


def test_mcp_stdio_pipe_subprocess():
    """Verify that the MCP server binary handles stdin/stdout JSON-RPC streaming."""
    script_path = REPO_ROOT / "scripts" / "asymmetry_mcp_server.py"
    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    req = json.dumps({"jsonrpc": "2.0", "id": "test-1", "method": "tools/list", "params": {}})
    stdout, stderr = proc.communicate(input=req + "\n", timeout=10)
    assert proc.returncode == 0
    lines = stdout.strip().split("\n")
    resp = json.loads(lines[-1])
    assert resp["id"] == "test-1"
    assert len(resp["result"]["tools"]) == 10
