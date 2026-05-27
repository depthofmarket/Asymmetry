from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from config.backtest_config import (
    BACKTEST_CONFIG,
    CANDIDATE_CONFIGS,
    FUTURES_SPECS,
    RESEARCH_CONFIG,
    STRATEGY_PARAMS,
)


SCHEMA_VERSION = 1
DEFAULT_MANIFEST_PATH = Path("config/research_protocol.json")
ALLOWED_PHASES = {"hypothesis", "development", "lockbox", "paper", "funded"}
EXECUTION_AUDIT_PURPOSES = {
    "execution_audit",
    "cost_model_calibration",
    "fill_realism_audit",
    "data_quality_audit",
}
TBBO_SAMPLE_ROLES = {"tbbo", "execution_audit", "cost_model_lockbox"}
FORBIDDEN_LLM_EVALUATION_TERMS = {
    "lockbox",
    "holdout",
    "test_profit_factor",
    "test_pnl",
    "oos_profit_factor",
    "oos_pnl",
    "sharpe",
    "calmar",
    "prop_pass_rate",
    "payout",
}
DEFAULT_AGENT_ROLES = [
    "planner",
    "data",
    "alpha",
    "risk",
    "execution",
    "audit",
    "memory",
]
DEFAULT_BLOCKED_AGENT_COMMANDS = [
    "main_backtest.py",
    "scripts/probe_candidate_frequency.py",
    "scripts/run_edge_candidates_batch.sh",
    "scripts/run_next_vp_candidates_batch.sh",
    "scripts/run_2021_frequency_candidates_batch.sh",
]


@dataclass(frozen=True)
class ResearchProtocolCheck:
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
class ResearchProtocolReport:
    manifest_path: Path
    run_dir: Path | None
    checks: list[ResearchProtocolCheck]

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
            f"Research protocol gate: {'PASS' if self.passed else 'FAIL'}",
            f"Manifest: {self.manifest_path}",
            f"Run: {self.run_dir if self.run_dir is not None else 'not supplied'}",
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
        return "\n".join(lines)


@dataclass(frozen=True)
class ResearchProtocolReportPaths:
    csv_path: Path
    markdown_path: Path


def build_research_protocol_manifest(
    *,
    experiment_id: str,
    objective: str,
    hypothesis: str,
    candidate: str | None = None,
    phase: str = "hypothesis",
    data_sources: list[dict[str, Any]] | None = None,
    llm_visible_artifacts: list[str] | None = None,
    evaluation_metrics_exposed_to_llm: bool = False,
    agent_roles: list[str] | None = None,
    blocked_agent_commands: list[str] | None = None,
    audit_requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    phase = str(phase)
    payload = current_research_payload(candidate)
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": "research_protocol",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "draft",
        "experiment_id": str(experiment_id),
        "objective": str(objective),
        "hypothesis": str(hypothesis),
        "candidate": candidate,
        "phase": phase,
        "config_payload_sha256": stable_payload_sha256(payload),
        "config_payload": payload,
        "agent_architecture": {
            "roles": list(agent_roles or DEFAULT_AGENT_ROLES),
            "llm_contract": (
                "LLMs may propose hypotheses and inspect approved research artifacts, but deterministic "
                "code owns features, fills, costs, labels, metrics, and promotion gates."
            ),
            "blocked_commands_for_agent": list(blocked_agent_commands or DEFAULT_BLOCKED_AGENT_COMMANDS),
            "backtest_execution_owner": "user_terminal",
        },
        "llm_visibility": {
            "visible_artifacts": list(llm_visible_artifacts or []),
            "evaluation_metrics_exposed_to_llm": bool(evaluation_metrics_exposed_to_llm),
            "forbidden_terms": sorted(FORBIDDEN_LLM_EVALUATION_TERMS),
        },
        "data_sources": [_normalize_data_source(source) for source in (data_sources or [])],
        "audit_requirements": _default_audit_requirements(audit_requirements),
        "promotion_rule": (
            "No candidate promotion if lockbox metrics were exposed to the LLM, if TBBO was used to mine "
            "signal filters, or if required saved-run execution and research-discipline artifacts are missing."
        ),
    }


def write_research_protocol_manifest(
    path: Path | str = DEFAULT_MANIFEST_PATH,
    **kwargs: Any,
) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = build_research_protocol_manifest(**kwargs)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_research_protocol_manifest(path: Path | str = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_research_protocol(
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    *,
    run_dir: Path | str | None = None,
) -> ResearchProtocolReport:
    path = Path(manifest_path)
    manifest = load_research_protocol_manifest(path)
    resolved_run_dir = Path(run_dir) if run_dir is not None else None
    checks: list[ResearchProtocolCheck] = []

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
            ResearchProtocolCheck(
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
    add("manifest", "manifest_type", manifest.get("manifest_type"), "research_protocol", manifest.get("manifest_type") == "research_protocol", path)
    add("manifest", "experiment_id", manifest.get("experiment_id", ""), "non-empty", bool(str(manifest.get("experiment_id", "")).strip()), path)
    add("manifest", "objective", manifest.get("objective", ""), "non-empty", bool(str(manifest.get("objective", "")).strip()), path)
    hypothesis = str(manifest.get("hypothesis", "")).strip()
    add("manifest", "hypothesis", hypothesis, ">= 20 characters", len(hypothesis) >= 20, path)
    phase = str(manifest.get("phase", ""))
    add("manifest", "phase", phase, "|".join(sorted(ALLOWED_PHASES)), phase in ALLOWED_PHASES, path)

    candidate = manifest.get("candidate")
    if candidate:
        add(
            "manifest",
            "candidate_exists",
            candidate,
            "candidate in config.CANDIDATE_CONFIGS",
            str(candidate) in CANDIDATE_CONFIGS,
            "config.backtest_config.CANDIDATE_CONFIGS",
        )

    stored_hash = str(manifest.get("config_payload_sha256", ""))
    try:
        current_hash = stable_payload_sha256(current_research_payload(str(candidate) if candidate else None))
        hash_ok = bool(stored_hash and current_hash == stored_hash)
    except KeyError as exc:
        current_hash = str(exc)
        hash_ok = False
    add(
        "fingerprint",
        "config_payload_sha256",
        current_hash,
        stored_hash,
        hash_ok,
        path,
        "Config drift means old results and current code/config are no longer the same experiment.",
    )

    architecture = manifest.get("agent_architecture", {}) if isinstance(manifest.get("agent_architecture"), dict) else {}
    blocked_commands = [str(item) for item in architecture.get("blocked_commands_for_agent", [])]
    add(
        "agent_contract",
        "backtest_execution_owner",
        architecture.get("backtest_execution_owner"),
        "user_terminal",
        architecture.get("backtest_execution_owner") == "user_terminal",
        path,
        "The research agent may prepare commands, but should not own historical execution.",
    )
    for command in ["main_backtest.py", "scripts/probe_candidate_frequency.py"]:
        add(
            "agent_contract",
            f"blocked_for_agent:{command}",
            command in blocked_commands,
            "true",
            command in blocked_commands,
            path,
            severity="warning",
        )

    visibility = manifest.get("llm_visibility", {}) if isinstance(manifest.get("llm_visibility"), dict) else {}
    eval_exposed = bool(visibility.get("evaluation_metrics_exposed_to_llm", False))
    add(
        "blinding",
        "evaluation_metrics_hidden_from_llm",
        eval_exposed,
        "false",
        not eval_exposed,
        path,
        "If the LLM saw evaluation metrics before freeze, promotion evidence is contaminated.",
    )
    visible_artifacts = [str(item).lower() for item in visibility.get("visible_artifacts", [])]
    leaked_terms = sorted(
        term for term in FORBIDDEN_LLM_EVALUATION_TERMS if any(term in artifact for artifact in visible_artifacts)
    )
    add(
        "blinding",
        "visible_artifacts_do_not_include_evaluation_terms",
        ",".join(leaked_terms) if leaked_terms else "none",
        "none",
        not leaked_terms,
        path,
        "LLM-visible artifacts should not include lockbox/OOS/performance-result labels.",
    )

    for idx, source in enumerate(manifest.get("data_sources", []) or []):
        source_path = Path(str(source.get("path", ""))) if isinstance(source, dict) else Path("")
        sample_role = str(source.get("sample_role", "")) if isinstance(source, dict) else ""
        purpose = str(source.get("purpose", "")) if isinstance(source, dict) else ""
        llm_visible = bool(source.get("llm_visible", False)) if isinstance(source, dict) else False
        source_id = str(source.get("name", f"source_{idx}")) if isinstance(source, dict) else f"source_{idx}"
        source_ref = source_path if str(source_path) else path
        is_tbbo = _is_tbbo_source(source_id, source_path, sample_role)
        add("data_source", f"{source_id}:path_exists", source_path.exists(), "true", source_path.exists(), source_ref, severity="warning")
        if sample_role in {"lockbox", "holdout"}:
            add(
                "blinding",
                f"{source_id}:lockbox_not_llm_visible",
                llm_visible,
                "false",
                not llm_visible,
                source_ref,
            )
        if is_tbbo:
            add(
                "data_source",
                f"{source_id}:tbbo_execution_only",
                purpose,
                "|".join(sorted(EXECUTION_AUDIT_PURPOSES)),
                purpose in EXECUTION_AUDIT_PURPOSES,
                source_ref,
                "TBBO is execution-realism evidence unless a separate point-in-time signal protocol is written first.",
            )

    if resolved_run_dir is not None:
        _add_run_artifact_checks(add, resolved_run_dir, manifest)

    return ResearchProtocolReport(manifest_path=path, run_dir=resolved_run_dir, checks=checks)


def export_research_protocol_report(
    report: ResearchProtocolReport,
    out_dir: Path | str,
    *,
    prefix: str = "research_protocol_gate",
) -> ResearchProtocolReportPaths:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    csv_path = out_path / f"{prefix}.csv"
    md_path = out_path / f"{prefix}.md"
    report.to_frame().to_csv(csv_path, index=False)
    md_path.write_text(render_research_protocol_markdown(report), encoding="utf-8")
    return ResearchProtocolReportPaths(csv_path=csv_path, markdown_path=md_path)


def render_research_protocol_markdown(report: ResearchProtocolReport) -> str:
    frame = report.to_frame()
    hard_fails = frame.loc[(frame["severity"] == "hard") & (frame["status"] == "FAIL")] if not frame.empty else frame
    warnings = frame.loc[frame["status"] == "WARN"] if not frame.empty else frame
    lines = [
        "# Research Protocol Gate",
        "",
        "This gate checks the agentic research-control layer. It reads manifests and saved artifacts only; it does not run a strategy backtest.",
        f"- Manifest: `{report.manifest_path}`",
        f"- Run: `{report.run_dir if report.run_dir is not None else 'not supplied'}`",
        f"- Promotion-control status: `{'pass' if report.passed else 'fail'}`",
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
    return "\n".join(lines) + "\n"


def append_research_audit_event(
    audit_log_path: Path | str,
    *,
    actor: str,
    event_type: str,
    action: str,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    path = Path(audit_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "actor": str(actor),
        "event_type": str(event_type),
        "action": str(action),
        "inputs": _normalize(inputs or {}),
        "outputs": _normalize(outputs or {}),
        "notes": str(notes),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def current_research_payload(candidate: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "strategy_params": STRATEGY_PARAMS,
        "backtest_config": BACKTEST_CONFIG,
        "futures_specs": FUTURES_SPECS,
        "research_config": RESEARCH_CONFIG,
    }
    if candidate:
        if candidate not in CANDIDATE_CONFIGS:
            raise KeyError(f"Unknown candidate: {candidate}")
        payload["candidate"] = candidate
        payload["candidate_config"] = CANDIDATE_CONFIGS[candidate]
    return _normalize(payload)


def stable_payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(_normalize(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fingerprint_file(path: Path | str, *, mode: str = "metadata") -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {"path": str(file_path), "exists": False, "fingerprint_mode": mode}
    stat = file_path.stat()
    fingerprint: dict[str, Any] = {
        "path": str(file_path),
        "exists": True,
        "fingerprint_mode": mode,
        "size_bytes": int(stat.st_size),
        "modified_ns": int(stat.st_mtime_ns),
    }
    if mode == "sha256":
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        fingerprint["sha256"] = digest.hexdigest()
    elif mode not in {"metadata", "none"}:
        raise ValueError("fingerprint mode must be metadata, sha256, or none")
    return fingerprint


def _default_audit_requirements(overrides: dict[str, Any] | None) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "require_development_report": True,
        "require_research_discipline_gate": True,
        "require_bar_exposure_audit": True,
        "require_execution_realism": True,
        "require_prop_walkforward": True,
        "require_tbbo_baseline_when_tbbo_used": True,
        "tbbo_baseline_summary_path": "results/research_master/tbbo_execution_baseline/tbbo_execution_baseline_summary.csv",
    }
    if overrides:
        defaults.update(overrides)
    return defaults


def _normalize_data_source(source: dict[str, Any]) -> dict[str, Any]:
    if "name" not in source:
        raise ValueError("data source requires name")
    if "path" not in source:
        raise ValueError("data source requires path")
    normalized = {
        "name": str(source["name"]),
        "path": str(source["path"]),
        "sample_role": str(source.get("sample_role", "development")),
        "purpose": str(source.get("purpose", "research_context")),
        "llm_visible": bool(source.get("llm_visible", False)),
        "fingerprint": fingerprint_file(source["path"], mode=str(source.get("fingerprint_mode", "metadata"))),
    }
    extra = {str(key): _normalize(value) for key, value in source.items() if key not in normalized and key != "fingerprint_mode"}
    normalized.update(extra)
    return normalized


def _add_run_artifact_checks(add: Any, run_dir: Path, manifest: dict[str, Any]) -> None:
    requirements = _default_audit_requirements(manifest.get("audit_requirements", {}))
    add("run_artifacts", "run_dir_exists", run_dir.exists(), "true", run_dir.exists(), run_dir)

    if bool(requirements.get("require_development_report", True)):
        dev_path = run_dir / "research" / "development_report.csv"
        add("run_artifacts", "development_report_exists", dev_path.exists(), "file exists", dev_path.exists(), dev_path)

    if bool(requirements.get("require_research_discipline_gate", True)):
        discipline_path = run_dir / "research" / "research_discipline_gate.csv"
        if discipline_path.exists():
            discipline = pd.read_csv(discipline_path)
            row = discipline.loc[discipline["check"].astype(str).eq("promotion_eligible")].head(1)
            status = str(row.iloc[0].get("status", "")) if not row.empty else "missing"
            add(
                "run_artifacts",
                "research_discipline_promotion_eligible",
                status,
                "PASS",
                status == "PASS",
                discipline_path,
            )
        else:
            add("run_artifacts", "research_discipline_promotion_eligible", "missing", "PASS", False, discipline_path)

    if bool(requirements.get("require_bar_exposure_audit", True)):
        bar_path = run_dir / "research" / "bar_exposure_audit" / "bar_exposure_audit_summary.csv"
        add("run_artifacts", "bar_exposure_audit_exists", bar_path.exists(), "file exists", bar_path.exists(), bar_path)

    if bool(requirements.get("require_execution_realism", True)):
        exec_path = run_dir / "research" / "execution_realism" / "execution_realism_summary.csv"
        add("run_artifacts", "execution_realism_report_exists", exec_path.exists(), "file exists", exec_path.exists(), exec_path)

    if bool(requirements.get("require_prop_walkforward", True)):
        prop_path = run_dir / "research" / "walkforward" / "prop_firm" / "walkforward_stitched_summary.csv"
        add("run_artifacts", "prop_walkforward_summary_exists", prop_path.exists(), "file exists", prop_path.exists(), prop_path)

    if _manifest_uses_tbbo(manifest) and bool(requirements.get("require_tbbo_baseline_when_tbbo_used", True)):
        tbbo_path = Path(str(requirements.get("tbbo_baseline_summary_path")))
        add("run_artifacts", "tbbo_baseline_summary_exists", tbbo_path.exists(), "file exists", tbbo_path.exists(), tbbo_path)


def _manifest_uses_tbbo(manifest: dict[str, Any]) -> bool:
    return any(
        _is_tbbo_source(
            str(source.get("name", "")),
            Path(str(source.get("path", ""))),
            str(source.get("sample_role", "")),
        )
        for source in manifest.get("data_sources", []) or []
        if isinstance(source, dict)
    )


def _is_tbbo_source(name: str, path: Path, sample_role: str) -> bool:
    joined = f"{name} {path} {sample_role}".lower()
    return "tbbo" in joined or sample_role in TBBO_SAMPLE_ROLES


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
    return value


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return f"{value:.6g}"
    return str(value)


def _parse_data_source(value: str) -> dict[str, Any]:
    parts = value.split(":")
    if len(parts) < 4:
        raise argparse.ArgumentTypeError(
            "--data-source must use name:path:sample_role:purpose[:llm_visible][:fingerprint_mode]"
        )
    source: dict[str, Any] = {
        "name": parts[0],
        "path": parts[1],
        "sample_role": parts[2],
        "purpose": parts[3],
    }
    if len(parts) >= 5:
        source["llm_visible"] = parts[4].strip().lower() in {"1", "true", "yes", "y"}
    if len(parts) >= 6:
        source["fingerprint_mode"] = parts[5]
    return source


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or verify an agentic research-control manifest without running a backtest."
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH), help="Research protocol manifest path.")
    parser.add_argument("--write-manifest", action="store_true", help="Write a new research protocol manifest.")
    parser.add_argument("--experiment-id", default="tbbo_execution_first_audit")
    parser.add_argument(
        "--objective",
        default="Keep strategy research honest while using TBBO only for execution-realism evidence.",
    )
    parser.add_argument(
        "--hypothesis",
        default=(
            "Execution costs and fill realism are the next bottleneck; TBBO should audit assumptions "
            "before any new candidate is promoted."
        ),
    )
    parser.add_argument("--candidate", default=None, choices=sorted(CANDIDATE_CONFIGS.keys()))
    parser.add_argument("--phase", default="hypothesis", choices=sorted(ALLOWED_PHASES))
    parser.add_argument(
        "--data-source",
        action="append",
        type=_parse_data_source,
        default=[],
        help="Source in name:path:sample_role:purpose[:llm_visible][:fingerprint_mode] format.",
    )
    parser.add_argument(
        "--llm-visible-artifact",
        action="append",
        default=[],
        help="Artifact label/path visible to the LLM. Lockbox/OOS metric labels fail the protocol gate.",
    )
    parser.add_argument("--evaluation-metrics-exposed-to-llm", action="store_true")
    parser.add_argument("--run-dir", default=None, help="Optional saved results/runs/<label> directory to check.")
    parser.add_argument("--out-dir", default=None, help="Optional output directory for CSV/Markdown report.")
    parser.add_argument("--append-event", action="store_true", help="Append a simple audit event to --audit-log.")
    parser.add_argument(
        "--audit-log",
        default="results/research_master/research_protocol_audit.jsonl",
        help="Audit JSONL path for --append-event. Defaults to ignored results/research_master/ output.",
    )
    parser.add_argument("--actor", default="codex")
    parser.add_argument("--event-type", default="protocol_check")
    parser.add_argument("--action", default="verify_research_protocol")
    parser.add_argument("--notes", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    manifest_path = Path(args.manifest)
    if args.write_manifest:
        write_research_protocol_manifest(
            manifest_path,
            experiment_id=args.experiment_id,
            objective=args.objective,
            hypothesis=args.hypothesis,
            candidate=args.candidate,
            phase=args.phase,
            data_sources=args.data_source,
            llm_visible_artifacts=args.llm_visible_artifact,
            evaluation_metrics_exposed_to_llm=args.evaluation_metrics_exposed_to_llm,
        )
        print(f"Wrote research protocol manifest: {manifest_path}")

    report = verify_research_protocol(manifest_path, run_dir=args.run_dir)
    print(report.summary())
    if args.out_dir:
        paths = export_research_protocol_report(report, args.out_dir)
        print(f"Wrote {paths.csv_path}")
        print(f"Wrote {paths.markdown_path}")
    if args.append_event:
        event = append_research_audit_event(
            args.audit_log,
            actor=args.actor,
            event_type=args.event_type,
            action=args.action,
            inputs={"manifest": str(manifest_path), "run_dir": args.run_dir},
            outputs={"passed": report.passed},
            notes=args.notes,
        )
        print(f"Appended audit event: {event['created_at_utc']}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
