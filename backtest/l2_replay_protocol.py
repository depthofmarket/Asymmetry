from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import shlex
from typing import Any

import pandas as pd

from backtest.l2_dataset_qa import parse_yyyymmdd
from backtest.l2_source_resolver import resolve_l2_source_index


SCHEMA_VERSION = 1
DEFAULT_MANIFEST_PATH = Path("config/l2_replay_protocol.json")
ALLOWED_PURPOSES = {
    "data_quality_audit",
    "execution_realism",
    "fill_model_calibration",
    "strategy_plumbing_smoke",
    "strategy_development_replay",
    "strategy_lockbox_replay",
}
ALLOWED_PHASES = {"smoke", "development", "calibration", "lockbox"}
ALLOWED_DATA_ROLES = {"development", "calibration", "lockbox", "execution_audit"}
ALLOWED_EXECUTION_MODES = {"topbook_only", "full_depth"}
ALLOWED_LIMIT_FILL_MODELS = {"trade_through", "queue", "touch"}
SMOKE_ONLY_BUILTINS = {"topbook_imbalance"}
SIGNAL_CSV_STRATEGIES = {"bar_signal_csv"}
DEFAULT_MAX_REPLAY_DATES = 20
DEFAULT_MAX_AGENT_DATES = 1
DEFAULT_MAX_AGENT_ROWS_PER_SOURCE = 250_000
DEFAULT_MAX_ROWS_PER_SOURCE = 2_000_000
FORBIDDEN_SIGNAL_RESULT_TERMS = (
    "avg_fill_price",
    "exit_price",
    "exit_time",
    "fill_price",
    "order_id",
    "pnl",
    "profit_factor",
    "realized",
    "sharpe",
    "trade_id",
    "unrealized",
)
SUSPICIOUS_SIGNAL_RESEARCH_TERMS = ("future", "label", "target")


@dataclass(frozen=True)
class L2ReplayProtocolCheck:
    section: str
    check: str
    passed: bool
    value: Any
    threshold: str
    source: str
    notes: str = ""
    severity: str = "hard"

    @property
    def status(self) -> str:
        if self.severity == "warning":
            return "PASS" if self.passed else "WARN"
        return "PASS" if self.passed else "FAIL"


@dataclass(frozen=True)
class L2ReplayProtocolReport:
    manifest_path: Path
    checks: list[L2ReplayProtocolCheck]
    command: str

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks if check.severity == "hard")

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "section": check.section,
                    "check": check.check,
                    "severity": check.severity,
                    "status": check.status,
                    "value": check.value,
                    "threshold": check.threshold,
                    "source": check.source,
                    "notes": check.notes,
                }
                for check in self.checks
            ]
        )

    def summary(self) -> str:
        hard_fails = [check for check in self.checks if check.severity == "hard" and not check.passed]
        warnings = [check for check in self.checks if check.severity == "warning" and not check.passed]
        lines = [
            f"L2 replay protocol: {'PASS' if self.passed else 'FAIL'}",
            f"Manifest: {self.manifest_path}",
            f"Hard failures: {len(hard_fails)}",
            f"Warnings: {len(warnings)}",
        ]
        for check in self.checks:
            lines.append(
                f"- {check.status} {check.section}:{check.check} "
                f"value={_fmt(check.value)} threshold={check.threshold} source={check.source}"
            )
            if check.notes:
                lines.append(f"  {check.notes}")
        if self.command:
            lines.extend(["", "Replay command:", self.command])
        return "\n".join(lines)


@dataclass(frozen=True)
class L2ReplayProtocolReportPaths:
    csv_path: Path
    markdown_path: Path


def build_l2_replay_protocol_manifest(
    *,
    experiment_id: str,
    objective: str,
    purpose: str,
    source_index_path: str,
    trade_dates: list[str],
    strategy: str = "noop",
    strategy_kwargs: dict[str, Any] | None = None,
    phase: str = "smoke",
    data_role: str = "development",
    max_rows_per_source: int = 200_000,
    max_dates: int | None = None,
    out_dir: str = "results/research_master/l2_orderflow_replay",
    prefix: str = "l2_orderflow_replay",
    symbol: str = "NQ_L2",
    execution_mode: str = "topbook_only",
    tick_size: float = 0.25,
    contract_value: float = 20.0,
    policy: str = "auto",
    max_depth_levels: int = 10,
    coalesce_window: str = "100ms",
    max_spread_ticks: float = 40.0,
    latency: str = "0ms",
    limit_fill_model: str = "trade_through",
    allow_full_depth_unknown_limits: bool = False,
    agent_may_execute: bool = False,
    full_history_allowed: bool = False,
    full_history_approval_note: str = "",
) -> dict[str, Any]:
    normalized_dates = [_normalize_yyyymmdd(day) for day in trade_dates]
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "l2_replay_protocol",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "experiment_id": str(experiment_id),
        "objective": str(objective),
        "purpose": str(purpose),
        "phase": str(phase),
        "data_role": str(data_role),
        "data_use_boundary": {
            "l2_result_is_live_edge_proof": False,
            "l2_result_may_promote_candidate_alone": False,
            "allowed_use": "execution_replay_and_audit",
        },
        "source": {
            "type": "source_index",
            "source_index_path": str(source_index_path),
            "materialization": "zip_member_streaming",
            "expands_raw_csv": False,
        },
        "date_selection": {
            "explicit_trade_dates": normalized_dates,
            "start_date": "",
            "end_date": "",
            "allow_missing_dates": False,
            "allow_duplicate_dates": False,
        },
        "row_limits": {
            "max_dates": int(max_dates if max_dates is not None else max(len(normalized_dates), 1)),
            "max_rows_per_source": int(max_rows_per_source),
        },
        "strategy": {
            "name": str(strategy),
            "kwargs": dict(strategy_kwargs or {}),
            "role": "plumbing_smoke" if strategy in SMOKE_ONLY_BUILTINS or strategy == "noop" else "custom_strategy",
            "frozen_before_lockbox": False,
        },
        "execution": {
            "mode": str(execution_mode),
            "symbol": str(symbol),
            "tick_size": float(tick_size),
            "contract_value": float(contract_value),
            "policy": str(policy),
            "max_depth_levels": int(max_depth_levels),
            "coalesce_window": str(coalesce_window),
            "max_spread_ticks": float(max_spread_ticks),
            "latency": str(latency),
            "limit_fill_model": str(limit_fill_model),
            "allow_full_depth_unknown_limits": bool(allow_full_depth_unknown_limits),
            "depth_semantics_proof_path": "",
            "queue_proof_path": "",
        },
        "runner_contract": {
            "execution_owner": "user_terminal",
            "agent_may_execute": bool(agent_may_execute),
            "full_history_allowed": bool(full_history_allowed),
            "full_history_approval_note": str(full_history_approval_note),
            "max_agent_dates": DEFAULT_MAX_AGENT_DATES,
            "max_agent_rows_per_source": DEFAULT_MAX_AGENT_ROWS_PER_SOURCE,
        },
        "llm_visibility": {
            "evaluation_metrics_exposed_to_llm": False,
            "visible_artifacts": [],
        },
        "output": {
            "out_dir": str(out_dir),
            "prefix": str(prefix),
            "promotion_claimed": False,
        },
    }


def write_l2_replay_protocol_manifest(
    path: Path | str = DEFAULT_MANIFEST_PATH,
    **kwargs: Any,
) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = build_l2_replay_protocol_manifest(**kwargs)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_l2_replay_protocol_manifest(path: Path | str = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_l2_replay_protocol(
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    *,
    command_context: dict[str, Any] | None = None,
) -> L2ReplayProtocolReport:
    path = Path(manifest_path)
    manifest = load_l2_replay_protocol_manifest(path)
    command_context = dict(command_context or {})
    checks: list[L2ReplayProtocolCheck] = []

    def add(
        section: str,
        check: str,
        value: Any,
        threshold: str,
        ok: bool,
        source: Path | str,
        notes: str = "",
        severity: str = "hard",
    ) -> None:
        checks.append(
            L2ReplayProtocolCheck(
                section=section,
                check=check,
                passed=bool(ok),
                value=value,
                threshold=threshold,
                source=str(source),
                notes=notes,
                severity=severity,
            )
        )

    add("manifest", "schema_version", manifest.get("schema_version"), str(SCHEMA_VERSION), manifest.get("schema_version") == SCHEMA_VERSION, path)
    add("manifest", "manifest_type", manifest.get("manifest_type"), "l2_replay_protocol", manifest.get("manifest_type") == "l2_replay_protocol", path)
    add("manifest", "experiment_id", manifest.get("experiment_id", ""), "non-empty", bool(str(manifest.get("experiment_id", "")).strip()), path)
    add("manifest", "objective", manifest.get("objective", ""), "non-empty", bool(str(manifest.get("objective", "")).strip()), path)
    purpose = str(manifest.get("purpose", ""))
    phase = str(manifest.get("phase", ""))
    data_role = str(manifest.get("data_role", ""))
    add("manifest", "purpose", purpose, "|".join(sorted(ALLOWED_PURPOSES)), purpose in ALLOWED_PURPOSES, path)
    add("manifest", "phase", phase, "|".join(sorted(ALLOWED_PHASES)), phase in ALLOWED_PHASES, path)
    add("manifest", "data_role", data_role, "|".join(sorted(ALLOWED_DATA_ROLES)), data_role in ALLOWED_DATA_ROLES, path)

    boundary = _dict(manifest.get("data_use_boundary"))
    add(
        "boundary",
        "l2_result_is_not_live_edge_proof",
        boundary.get("l2_result_is_live_edge_proof"),
        "false",
        boundary.get("l2_result_is_live_edge_proof") is False,
        path,
        "L2 replay can disprove fills or audit execution; it is not live-edge proof by itself.",
    )
    add(
        "boundary",
        "l2_result_cannot_promote_candidate_alone",
        boundary.get("l2_result_may_promote_candidate_alone"),
        "false",
        boundary.get("l2_result_may_promote_candidate_alone") is False,
        path,
    )

    source = _dict(manifest.get("source"))
    source_index_path = Path(str(source.get("source_index_path", "")))
    add("source", "source_type", source.get("type"), "source_index", source.get("type") == "source_index", path)
    add("source", "source_index_exists", source_index_path.exists(), "true", source_index_path.exists(), source_index_path)
    add("source", "zip_member_streaming", source.get("materialization"), "zip_member_streaming", source.get("materialization") == "zip_member_streaming", path)
    add("source", "raw_csv_not_expanded", source.get("expands_raw_csv"), "false", source.get("expands_raw_csv") is False, path)

    dates = _date_selection(manifest)
    max_dates = _int(_dict(manifest.get("row_limits")).get("max_dates"), default=0)
    max_rows = _int(_dict(manifest.get("row_limits")).get("max_rows_per_source"), default=0)
    add("date_selection", "explicit_trade_dates", len(dates), ">=1", len(dates) > 0, path)
    add("date_selection", "dates_within_declared_cap", len(dates), f"<= {max_dates}", max_dates > 0 and len(dates) <= max_dates, path)
    add("date_selection", "full_history_not_requested", len(dates), f"<= {DEFAULT_MAX_REPLAY_DATES} unless full_history_allowed", _full_history_ok(manifest, len(dates)), path)
    add("row_limits", "max_rows_per_source", max_rows, f"1..{DEFAULT_MAX_ROWS_PER_SOURCE}", 0 < max_rows <= DEFAULT_MAX_ROWS_PER_SOURCE, path)

    if source_index_path.exists() and dates:
        try:
            selection = resolve_l2_source_index(
                source_index_path,
                trade_dates=dates,
                allow_missing_dates=bool(_dict(manifest.get("date_selection")).get("allow_missing_dates", False)),
                allow_duplicate_dates=bool(_dict(manifest.get("date_selection")).get("allow_duplicate_dates", False)),
            )
            add("source", "requested_dates_resolve", len(selection.resolved_sources), str(len(dates)), len(selection.resolved_sources) == len(dates), source_index_path)
            add("source", "missing_dates", ",".join(selection.missing_dates) if selection.missing_dates else "none", "none", not selection.missing_dates, source_index_path)
        except Exception as exc:
            add("source", "requested_dates_resolve", exc.__class__.__name__, "no exception", False, source_index_path, str(exc))

    strategy = _dict(manifest.get("strategy"))
    strategy_name = str(strategy.get("name", ""))
    strategy_role = str(strategy.get("role", ""))
    add("strategy", "name", strategy_name, "non-empty", bool(strategy_name.strip()), path)
    add(
        "strategy",
        "smoke_builtin_not_candidate",
        f"{strategy_name}:{strategy_role}",
        "built-in smoke strategies require role=plumbing_smoke",
        strategy_name not in SMOKE_ONLY_BUILTINS or strategy_role == "plumbing_smoke",
        path,
    )
    add(
        "strategy",
        "lockbox_strategy_frozen",
        strategy.get("frozen_before_lockbox"),
        "true when phase=lockbox",
        phase != "lockbox" or strategy.get("frozen_before_lockbox") is True,
        path,
    )
    _add_bar_signal_csv_checks(add, strategy, path)

    execution = _dict(manifest.get("execution"))
    mode = str(execution.get("mode", ""))
    fill_model = str(execution.get("limit_fill_model", ""))
    tick_size = _float(execution.get("tick_size"), default=0.0)
    contract_value = _float(execution.get("contract_value"), default=0.0)
    max_depth_levels = _int(execution.get("max_depth_levels"), default=0)
    add("execution", "mode", mode, "|".join(sorted(ALLOWED_EXECUTION_MODES)), mode in ALLOWED_EXECUTION_MODES, path)
    add("execution", "tick_size", tick_size, "> 0", tick_size > 0.0, path)
    add("execution", "contract_value", contract_value, "> 0", contract_value > 0.0, path)
    add("execution", "max_depth_levels", max_depth_levels, "1..10", 1 <= max_depth_levels <= 10, path)
    depth_proof_path = _resolve_protocol_path(execution.get("depth_semantics_proof_path"), base_path=path)
    depth_proof_ok, depth_proof_note = _depth_semantics_proof_accepts_full_depth(depth_proof_path)
    add(
        "execution",
        "topbook_only_until_depth_proven",
        str(depth_proof_path) if depth_proof_path is not None else "",
        "topbook_only or depth proof accepts full_depth",
        mode == "topbook_only" or depth_proof_ok,
        depth_proof_path or path,
        depth_proof_note,
    )
    add("execution", "limit_fill_model", fill_model, "|".join(sorted(ALLOWED_LIMIT_FILL_MODELS)), fill_model in ALLOWED_LIMIT_FILL_MODELS, path)
    queue_proof_path = _resolve_protocol_path(execution.get("queue_proof_path"), base_path=path)
    add("execution", "queue_model_requires_proof", fill_model, "non-queue or queue_proof_path exists", fill_model != "queue" or (queue_proof_path is not None and queue_proof_path.exists()), queue_proof_path or path)
    add("execution", "unknown_full_depth_limits_disabled", execution.get("allow_full_depth_unknown_limits"), "false", execution.get("allow_full_depth_unknown_limits") is False, path)

    runner = _dict(manifest.get("runner_contract"))
    agent_may_execute = bool(runner.get("agent_may_execute", False))
    add("runner_contract", "execution_owner", runner.get("execution_owner"), "user_terminal", runner.get("execution_owner") == "user_terminal", path)
    if agent_may_execute:
        add("runner_contract", "agent_date_cap", len(dates), f"<= {runner.get('max_agent_dates', DEFAULT_MAX_AGENT_DATES)}", len(dates) <= _int(runner.get("max_agent_dates"), DEFAULT_MAX_AGENT_DATES), path)
        add("runner_contract", "agent_row_cap", max_rows, f"<= {runner.get('max_agent_rows_per_source', DEFAULT_MAX_AGENT_ROWS_PER_SOURCE)}", max_rows <= _int(runner.get("max_agent_rows_per_source"), DEFAULT_MAX_AGENT_ROWS_PER_SOURCE), path)

    visibility = _dict(manifest.get("llm_visibility"))
    eval_exposed = bool(visibility.get("evaluation_metrics_exposed_to_llm", False))
    add("blinding", "evaluation_metrics_hidden_from_llm", eval_exposed, "false", not eval_exposed, path)
    visible_artifacts = [str(item).lower() for item in visibility.get("visible_artifacts", []) or []]
    leaked = sorted(term for term in ("lockbox", "oos", "pnl", "sharpe", "profit_factor") if any(term in item for item in visible_artifacts))
    add("blinding", "visible_artifacts_do_not_name_results", ",".join(leaked) if leaked else "none", "none", not leaked, path)

    output = _dict(manifest.get("output"))
    out_dir = str(output.get("out_dir", ""))
    add("output", "out_dir", out_dir, "non-empty", bool(out_dir.strip()), path)
    add("output", "not_saved_run_promotion_path", out_dir, "not results/runs unless promotion_claimed=false and protocol says no promotion", not out_dir.startswith("results/runs/"), path)
    add("output", "promotion_not_claimed", output.get("promotion_claimed"), "false", output.get("promotion_claimed") is False, path)

    _add_command_context_checks(add, manifest, command_context, path)
    command = render_l2_replay_command(manifest, manifest_path=path) if manifest.get("manifest_type") == "l2_replay_protocol" else ""
    return L2ReplayProtocolReport(manifest_path=path, checks=checks, command=command)


def export_l2_replay_protocol_report(
    report: L2ReplayProtocolReport,
    out_dir: Path | str,
    *,
    prefix: str = "l2_replay_protocol_gate",
) -> L2ReplayProtocolReportPaths:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    csv_path = out_path / f"{prefix}.csv"
    md_path = out_path / f"{prefix}.md"
    report.to_frame().to_csv(csv_path, index=False)
    md_path.write_text(render_l2_replay_protocol_markdown(report), encoding="utf-8")
    return L2ReplayProtocolReportPaths(csv_path=csv_path, markdown_path=md_path)


def render_l2_replay_protocol_markdown(report: L2ReplayProtocolReport) -> str:
    frame = report.to_frame()
    hard_fails = frame.loc[(frame["severity"] == "hard") & (frame["status"] == "FAIL")] if not frame.empty else frame
    warnings = frame.loc[frame["status"] == "WARN"] if not frame.empty else frame
    lines = [
        "# L2 Replay Protocol Gate",
        "",
        "This gate validates an event-driven L2 replay request. It reads manifests and source-index metadata only; it does not run a strategy backtest.",
        f"- Manifest: `{report.manifest_path}`",
        f"- Protocol status: `{'pass' if report.passed else 'fail'}`",
        f"- Hard failures: `{len(hard_fails)}`",
        f"- Warnings: `{len(warnings)}`",
        "",
        "## Checks",
    ]
    for check in report.checks:
        lines.append(
            f"- {check.status} | {check.section} | {check.check} | "
            f"value={_fmt(check.value)} | threshold={check.threshold}"
        )
        if check.notes:
            lines.append(f"  {check.notes}")
    if report.command:
        lines.extend(["", "## Replay Command", "", "```bash", report.command, "```", ""])
    return "\n".join(lines) + "\n"


def render_l2_replay_command(
    manifest: dict[str, Any],
    *,
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
) -> str:
    source = _dict(manifest.get("source"))
    dates = _date_selection(manifest)
    row_limits = _dict(manifest.get("row_limits"))
    strategy = _dict(manifest.get("strategy"))
    execution = _dict(manifest.get("execution"))
    output = _dict(manifest.get("output"))

    args = [
        "python3",
        "scripts/run_l2_orderflow_replay.py",
        "--protocol-manifest",
        str(manifest_path),
        "--source-index",
        str(source.get("source_index_path", "")),
    ]
    for day in dates:
        args.extend(["--trade-date", day])
    args.extend(
        [
            "--max-rows-per-member",
            str(_int(row_limits.get("max_rows_per_source"), 0)),
            "--strategy",
            str(strategy.get("name", "noop")),
            "--strategy-kwargs",
            json.dumps(strategy.get("kwargs", {}), sort_keys=True),
            "--symbol",
            str(execution.get("symbol", "NQ_L2")),
            "--execution-mode",
            str(execution.get("mode", "topbook_only")),
            "--tick-size",
            str(execution.get("tick_size", 0.25)),
            "--contract-value",
            str(execution.get("contract_value", 20.0)),
            "--policy",
            str(execution.get("policy", "auto")),
            "--max-depth-levels",
            str(execution.get("max_depth_levels", 10)),
            "--coalesce-window",
            str(execution.get("coalesce_window", "100ms")),
            "--max-spread-ticks",
            str(execution.get("max_spread_ticks", 40.0)),
            "--latency",
            str(execution.get("latency", "0ms")),
            "--limit-fill-model",
            str(execution.get("limit_fill_model", "trade_through")),
            "--out-dir",
            str(output.get("out_dir", "results/research_master/l2_orderflow_replay")),
            "--prefix",
            str(output.get("prefix", "l2_orderflow_replay")),
        ]
    )
    if bool(execution.get("allow_full_depth_unknown_limits", False)):
        args.append("--allow-full-depth-unknown-limits")
    return " ".join(shlex.quote(arg) for arg in args)


def command_context_from_replay_args(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "source_index_path": getattr(args, "source_index", None),
        "trade_dates": list(getattr(args, "trade_date", []) or []),
        "max_rows_per_source": getattr(args, "max_rows_per_member", None),
        "strategy": getattr(args, "strategy", None),
        "execution_mode": getattr(args, "execution_mode", None),
        "tick_size": getattr(args, "tick_size", None),
        "contract_value": getattr(args, "contract_value", None),
        "limit_fill_model": getattr(args, "limit_fill_model", None),
        "out_dir": getattr(args, "out_dir", None),
        "prefix": getattr(args, "prefix", None),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or create an L2 replay protocol manifest.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--out-dir", default="results/research_master/l2_replay_protocol")
    parser.add_argument("--prefix", default="l2_replay_protocol_gate")
    parser.add_argument("--write-template", action="store_true")
    parser.add_argument("--experiment-id", default="l2_replay_smoke")
    parser.add_argument("--objective", default="Validate a bounded L2 replay request before execution.")
    parser.add_argument("--purpose", default="strategy_plumbing_smoke", choices=sorted(ALLOWED_PURPOSES))
    parser.add_argument("--source-index", default="data/raw/l2_nq/manifests/l2_source_index.csv")
    parser.add_argument("--trade-date", action="append", default=["20201201"])
    parser.add_argument("--strategy", default="noop")
    parser.add_argument("--execution-mode", choices=sorted(ALLOWED_EXECUTION_MODES), default="topbook_only")
    parser.add_argument("--max-rows-per-source", type=int, default=1_000)
    parser.add_argument("--print-command", action="store_true")
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    if args.write_template:
        write_l2_replay_protocol_manifest(
            manifest_path,
            experiment_id=args.experiment_id,
            objective=args.objective,
            purpose=args.purpose,
            source_index_path=args.source_index,
            trade_dates=list(args.trade_date),
            strategy=args.strategy,
            execution_mode=args.execution_mode,
            max_rows_per_source=int(args.max_rows_per_source),
            out_dir="results/research_master/l2_orderflow_replay",
            prefix=args.experiment_id,
        )
        print(f"Wrote L2 replay protocol manifest: {manifest_path}")

    report = verify_l2_replay_protocol(manifest_path)
    paths = export_l2_replay_protocol_report(report, args.out_dir, prefix=args.prefix)
    print(report.summary())
    print(f"CSV report: {paths.csv_path}")
    print(f"Markdown report: {paths.markdown_path}")
    if args.print_command and report.command:
        print(report.command)
    return 0 if report.passed else 1


def _add_command_context_checks(
    add: Any,
    manifest: dict[str, Any],
    command_context: dict[str, Any],
    source: Path | str,
) -> None:
    if not command_context:
        return
    manifest_source = _dict(manifest.get("source"))
    manifest_rows = _dict(manifest.get("row_limits"))
    manifest_strategy = _dict(manifest.get("strategy"))
    manifest_execution = _dict(manifest.get("execution"))
    manifest_output = _dict(manifest.get("output"))
    checks = [
        ("source_index_path", str(manifest_source.get("source_index_path", "")), _optional_str(command_context.get("source_index_path"))),
        ("trade_dates", ",".join(_date_selection(manifest)), ",".join(_normalize_yyyymmdd(day) for day in command_context.get("trade_dates", []) or [])),
        ("max_rows_per_source", str(_int(manifest_rows.get("max_rows_per_source"), 0)), str(command_context.get("max_rows_per_source"))),
        ("strategy", str(manifest_strategy.get("name", "")), _optional_str(command_context.get("strategy"))),
        ("execution_mode", str(manifest_execution.get("mode", "")), _optional_str(command_context.get("execution_mode"))),
        ("tick_size", str(manifest_execution.get("tick_size", "")), _optional_str(command_context.get("tick_size"))),
        ("contract_value", str(manifest_execution.get("contract_value", "")), _optional_str(command_context.get("contract_value"))),
        ("limit_fill_model", str(manifest_execution.get("limit_fill_model", "")), _optional_str(command_context.get("limit_fill_model"))),
        ("out_dir", str(manifest_output.get("out_dir", "")), _optional_str(command_context.get("out_dir"))),
        ("prefix", str(manifest_output.get("prefix", "")), _optional_str(command_context.get("prefix"))),
    ]
    for name, expected, actual in checks:
        if actual == "":
            continue
        add("command_context", name, actual, expected, actual == expected, source)


def _add_bar_signal_csv_checks(add: Any, strategy: dict[str, Any], source: Path | str) -> None:
    strategy_name = str(strategy.get("name", ""))
    if strategy_name not in SIGNAL_CSV_STRATEGIES:
        return
    kwargs = _dict(strategy.get("kwargs"))
    raw_signals_csv = str(kwargs.get("signals_csv", "") or "").strip()
    signals_csv = _resolve_protocol_path(raw_signals_csv, base_path=source)
    add("strategy", "bar_signal_csv_signals_csv_declared", raw_signals_csv, "non-empty", bool(raw_signals_csv), source)
    add(
        "strategy",
        "bar_signal_csv_signals_csv_exists",
        str(signals_csv) if signals_csv is not None else "",
        "file exists",
        signals_csv is not None and signals_csv.exists(),
        signals_csv or source,
    )
    if signals_csv is None or not signals_csv.exists():
        return

    try:
        frame = pd.read_csv(signals_csv)
    except Exception as exc:
        add("strategy", "bar_signal_csv_readable", exc.__class__.__name__, "no exception", False, signals_csv, str(exc))
        return

    time_col = str(kwargs.get("time_col", "time") or "time")
    configured_signal_col = str(kwargs.get("signal_col", "candidate_signal") or "candidate_signal")
    signal_col = configured_signal_col if configured_signal_col in frame.columns else "signal"
    required = [time_col, signal_col]
    missing = [col for col in required if col not in frame.columns]
    add(
        "strategy",
        "bar_signal_csv_required_columns",
        ",".join(missing) if missing else "present",
        f"contains {time_col} and {configured_signal_col} or signal",
        not missing,
        signals_csv,
        "This proves only artifact shape, not that the signal was generated without overfit or leakage.",
    )
    lower_cols = {str(col).strip().lower(): str(col) for col in frame.columns}
    forbidden = sorted(
        original
        for lower, original in lower_cols.items()
        if any(term in lower for term in FORBIDDEN_SIGNAL_RESULT_TERMS)
    )
    add(
        "strategy",
        "bar_signal_csv_no_result_columns",
        ",".join(forbidden) if forbidden else "none",
        "no fill/result/PnL columns",
        not forbidden,
        signals_csv,
        "Signal inputs must not carry realized results or fill artifacts.",
    )
    suspicious = sorted(
        original
        for lower, original in lower_cols.items()
        if any(term in lower for term in SUSPICIOUS_SIGNAL_RESEARCH_TERMS)
    )
    add(
        "strategy",
        "bar_signal_csv_suspicious_research_columns",
        ",".join(suspicious) if suspicious else "none",
        "none preferred",
        not suspicious,
        signals_csv,
        "Columns named like labels or future targets are leakage-sensitive; verify they are not used by the adapter.",
        severity="warning",
    )
    if missing:
        return

    parsed_time = pd.to_datetime(frame[time_col], errors="coerce")
    invalid_times = int(parsed_time.isna().sum())
    add(
        "strategy",
        "bar_signal_csv_timestamps_parse",
        invalid_times,
        "0 invalid timestamps",
        invalid_times == 0,
        signals_csv,
    )
    clean_time = parsed_time.dropna()
    add(
        "strategy",
        "bar_signal_csv_timestamps_sorted",
        len(clean_time),
        "monotonic increasing",
        clean_time.is_monotonic_increasing,
        signals_csv,
        "The adapter schedules off these timestamps; unsorted rows make point-in-time review unreliable.",
    )
    signal_values = pd.to_numeric(frame[signal_col], errors="coerce").fillna(0.0)
    active_rows = int(signal_values.ne(0.0).sum())
    add(
        "strategy",
        "bar_signal_csv_active_signal_rows",
        active_rows,
        "> 0 for a non-smoke replay",
        active_rows > 0,
        signals_csv,
        "A no-signal CSV is allowed only for plumbing smoke, not execution-realism claims.",
        severity="warning",
    )


def _resolve_protocol_path(value: Any, *, base_path: Path | str) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    if candidate.exists():
        return candidate
    base_candidate = Path(base_path).parent / candidate
    if base_candidate.exists():
        return base_candidate
    return candidate


def _depth_semantics_proof_accepts_full_depth(path: Path | None) -> tuple[bool, str]:
    if path is None:
        return False, "missing depth_semantics_proof_path"
    if not path.exists():
        return False, "depth_semantics_proof_path does not exist"
    if path.suffix.lower() != ".csv":
        return False, "depth_semantics_proof_path must be a CSV decision/evidence artifact"
    try:
        proof = pd.read_csv(path)
    except Exception as exc:
        return False, f"could not read depth proof CSV: {exc.__class__.__name__}: {exc}"
    if proof.empty:
        return False, "depth proof CSV is empty"
    columns = {str(col).strip().lower(): str(col) for col in proof.columns}
    if "full_depth_allowed" in columns:
        allowed = proof[columns["full_depth_allowed"]].map(_truthy).fillna(False)
        if bool(allowed.any()):
            return True, "depth proof CSV contains full_depth_allowed=True"
    if "decision" in columns:
        decisions = proof[columns["decision"]].astype(str).str.strip().str.lower()
        if bool(decisions.eq("full_depth_allowed").any()):
            return True, "depth proof CSV decision includes full_depth_allowed"
    if "policy_proof_status" in columns:
        statuses = proof[columns["policy_proof_status"]].astype(str).str.strip().str.lower()
        if bool(statuses.eq("accepted").any()):
            return True, "depth proof CSV contains an accepted policy_proof_status"
    return False, "depth proof CSV does not accept full_depth"


def _date_selection(manifest: dict[str, Any]) -> list[str]:
    selection = _dict(manifest.get("date_selection"))
    explicit = selection.get("explicit_trade_dates", [])
    if isinstance(explicit, str):
        explicit = [explicit]
    dates = [_normalize_yyyymmdd(day) for day in explicit or []]
    start = str(selection.get("start_date", "") or "").strip()
    end = str(selection.get("end_date", "") or "").strip()
    if dates or not start or not end:
        return list(dict.fromkeys(dates))
    start_date = parse_yyyymmdd(_normalize_yyyymmdd(start))
    end_date = parse_yyyymmdd(_normalize_yyyymmdd(end))
    return [day.strftime("%Y%m%d") for day in pd.date_range(start_date, end_date, freq="D").date]


def _full_history_ok(manifest: dict[str, Any], date_count: int) -> bool:
    runner = _dict(manifest.get("runner_contract"))
    if date_count <= DEFAULT_MAX_REPLAY_DATES:
        return True
    if not bool(runner.get("full_history_allowed", False)):
        return False
    return bool(str(runner.get("full_history_approval_note", "")).strip())


def _path_exists(value: Any) -> bool:
    raw = str(value or "").strip()
    return bool(raw and Path(raw).exists())


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    return raw in {"1", "true", "t", "yes", "y", "accepted", "full_depth_allowed"}


def _normalize_yyyymmdd(value: object) -> str:
    return parse_yyyymmdd(str(value).strip()).strftime("%Y%m%d")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _optional_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


__all__ = [
    "L2ReplayProtocolCheck",
    "L2ReplayProtocolReport",
    "L2ReplayProtocolReportPaths",
    "build_l2_replay_protocol_manifest",
    "command_context_from_replay_args",
    "export_l2_replay_protocol_report",
    "load_l2_replay_protocol_manifest",
    "render_l2_replay_command",
    "render_l2_replay_protocol_markdown",
    "verify_l2_replay_protocol",
    "write_l2_replay_protocol_manifest",
]


if __name__ == "__main__":
    raise SystemExit(main())
