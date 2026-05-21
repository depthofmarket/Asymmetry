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

from backtest.live_prop_rules import validate_prop_research_gate
from config.backtest_config import (
    BACKTEST_CONFIG,
    CANDIDATE_CONFIGS,
    FUTURES_SPECS,
    RESEARCH_CONFIG,
    STRATEGY_PARAMS,
)


DEFAULT_MANIFEST_PATH = Path("config/research_freeze.json")
DEFAULT_FREEZE_CANDIDATE = "edge_microstructure_liquidity_taking_trend_probe"


@dataclass(frozen=True)
class FreezeCheck:
    name: str
    passed: bool
    value: Any
    threshold: str
    source: str


@dataclass(frozen=True)
class FreezeReport:
    manifest_path: Path
    candidate: str
    phase: str
    manifest_status: str
    active_candidate: bool
    archive_reason: str
    checks: list[FreezeCheck]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def summary(self) -> str:
        lines = [
            f"Research freeze manifest check: {'PASS' if self.passed else 'FAIL'}",
            f"Manifest: {self.manifest_path}",
            f"Manifest status: {self.manifest_status}",
            f"Candidate: {self.candidate}",
            f"Active validation freeze: {'YES' if self.active_candidate else 'NO'}",
            f"Phase: {self.phase}",
        ]
        if self.archive_reason:
            lines.append(f"Archive reason: {self.archive_reason}")
        for check in self.checks:
            status = "PASS" if check.passed else "FAIL"
            lines.append(
                f"- {status} {check.name}: value={check.value} threshold={check.threshold} source={check.source}"
            )
        return "\n".join(lines)


def build_freeze_manifest(candidate: str = DEFAULT_FREEZE_CANDIDATE) -> dict[str, Any]:
    payload = current_freeze_payload(candidate)
    return {
        "schema_version": 1,
        "status": "frozen",
        "active_candidate": True,
        "candidate": candidate,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "candidate_config_sha256": freeze_payload_sha256(payload),
        "freeze_payload": payload,
        "research_protocol": {
            "development_sample": "Historical research sample. Allowed for rejection and hypothesis generation.",
            "lockbox_sample": "Untouched forward or held-out sample. Do not inspect or tune on it before a frozen run.",
            "tbbo_note": (
                "TBBO data is an execution-realism lockbox unless converted into bars with the same "
                "point-in-time feature pipeline; do not use it to mine new signal filters."
            ),
        },
        "acceptance_criteria": {
            "development": {
                "development_report_pass_checks": [
                    "trade_profit_factor",
                    "bar_profit_factor",
                    "trades_per_year",
                    "obvious_overfit_smell",
                    "sharpe_overfit_smell",
                    "stitched_oos_profit_factor",
                    "stitched_oos_bar_profit_factor",
                    "stitched_oos_total_pnl",
                    "stitched_oos_trades_per_year",
                    "selected_param_neighborhood_ratio",
                    "combined_mild_profit_factor",
                    "combined_mild_total_pnl",
                ],
                "require_all_optimization_folds_pass": True,
                "require_prop_research_gate_pass": True,
                "require_research_discipline_gate_pass": True,
            },
            "lockbox": {
                "min_trades": 5,
                "min_profit_factor": 1.05,
                "min_total_pnl": 0.0,
                "min_combined_mild_profit_factor": 1.0,
            },
        },
    }


def current_freeze_payload(candidate: str) -> dict[str, Any]:
    if candidate not in CANDIDATE_CONFIGS:
        raise KeyError(f"Unknown candidate: {candidate}")
    return _normalize(
        {
            "candidate": candidate,
            "strategy_params": STRATEGY_PARAMS,
            "backtest_config": BACKTEST_CONFIG,
            "candidate_config": CANDIDATE_CONFIGS[candidate],
            "futures_specs": FUTURES_SPECS,
            "research_config": RESEARCH_CONFIG,
        }
    )


def freeze_payload_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(_normalize(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_manifest(path: Path | str = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    manifest_path = Path(path)
    with manifest_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_manifest(path: Path | str, candidate: str = DEFAULT_FREEZE_CANDIDATE) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = build_freeze_manifest(candidate)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def verify_freeze(
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    *,
    run_dir: Path | str | None = None,
    phase: str = "development",
) -> FreezeReport:
    path = Path(manifest_path)
    manifest = load_manifest(path)
    candidate = str(manifest["candidate"])
    manifest_status = str(manifest.get("status", ""))
    active_candidate = bool(manifest.get("active_candidate", manifest_status == "frozen"))
    archive_decision = manifest.get("archive_decision", {})
    archive_reason = str(archive_decision.get("reason", "")) if isinstance(archive_decision, dict) else ""
    current_hash = freeze_payload_sha256(current_freeze_payload(candidate))
    checks = [
        FreezeCheck(
            name="candidate_config_sha256",
            passed=current_hash == manifest.get("candidate_config_sha256"),
            value=current_hash,
            threshold=str(manifest.get("candidate_config_sha256")),
            source=str(path),
        ),
        FreezeCheck(
            name="manifest_status",
            passed=manifest_status in {"frozen", "archived_rejected"},
            value=manifest_status,
            threshold="frozen|archived_rejected",
            source=str(path),
        ),
        FreezeCheck(
            name="active_validation_candidate",
            passed=isinstance(manifest.get("active_candidate", True), bool),
            value=active_candidate,
            threshold="explicit boolean; false means archived/reproducibility only",
            source=str(path),
        ),
    ]

    if run_dir is not None:
        checks.extend(_evaluate_run(Path(run_dir), manifest, phase))

    return FreezeReport(
        manifest_path=path,
        candidate=candidate,
        phase=phase,
        manifest_status=manifest_status,
        active_candidate=active_candidate,
        archive_reason=archive_reason,
        checks=checks,
    )


def _evaluate_run(run_dir: Path, manifest: dict[str, Any], phase: str) -> list[FreezeCheck]:
    candidate = str(manifest["candidate"])
    checks = [
        FreezeCheck(
            name="run_dir_candidate_label",
            passed=candidate in run_dir.name,
            value=run_dir.name,
            threshold=f"contains {candidate}",
            source=str(run_dir),
        )
    ]

    criteria = manifest.get("acceptance_criteria", {}).get(phase, {})
    if phase == "development":
        checks.extend(_development_checks(run_dir, criteria))
    elif phase == "lockbox":
        checks.extend(_lockbox_checks(run_dir, criteria))
    else:
        checks.append(
            FreezeCheck(
                name="phase",
                passed=False,
                value=phase,
                threshold="development|lockbox",
                source=str(run_dir),
            )
        )
    return checks


def _development_checks(run_dir: Path, criteria: dict[str, Any]) -> list[FreezeCheck]:
    checks: list[FreezeCheck] = []
    dev_path = run_dir / "research" / "development_report.csv"
    required_checks = list(criteria.get("development_report_pass_checks", []))
    if dev_path.exists():
        dev = pd.read_csv(dev_path)
        for check_name in required_checks:
            row = dev.loc[dev["check"].eq(check_name)].head(1)
            if row.empty:
                checks.append(_missing_check(f"development_report:{check_name}", dev_path, "status PASS"))
                continue
            item = row.iloc[0]
            checks.append(
                FreezeCheck(
                    name=f"development_report:{check_name}",
                    passed=str(item.get("status")) == "PASS",
                    value=item.get("value"),
                    threshold=str(item.get("threshold")),
                    source=str(dev_path),
                )
            )
    else:
        for check_name in required_checks or ["development_report"]:
            checks.append(_missing_check(f"development_report:{check_name}", dev_path, "file exists"))

    if bool(criteria.get("require_all_optimization_folds_pass", False)):
        opt_path = run_dir / "research" / "optimization_stability.csv"
        if opt_path.exists():
            opt = pd.read_csv(opt_path)
            failing = opt.loc[~opt["status"].eq("PASS")]
            checks.append(
                FreezeCheck(
                    name="optimization_stability:all_folds_pass",
                    passed=failing.empty,
                    value=0 if failing.empty else failing["fold_idx"].tolist(),
                    threshold="all fold status values PASS",
                    source=str(opt_path),
                )
            )
        else:
            checks.append(_missing_check("optimization_stability:all_folds_pass", opt_path, "file exists"))

    if bool(criteria.get("require_prop_research_gate_pass", False)):
        report = validate_prop_research_gate(run_dir)
        checks.append(
            FreezeCheck(
                name="prop_research_gate",
                passed=report.passed,
                value="PASS" if report.passed else "FAIL",
                threshold="PASS",
                source=str(run_dir),
            )
        )

    if bool(criteria.get("require_research_discipline_gate_pass", False)):
        discipline_path = run_dir / "research" / "research_discipline_gate.csv"
        if discipline_path.exists():
            discipline = pd.read_csv(discipline_path)
            row = discipline.loc[discipline["check"].eq("promotion_eligible")].head(1)
            if row.empty:
                checks.append(_missing_check("research_discipline_gate:promotion_eligible", discipline_path, "status PASS"))
            else:
                item = row.iloc[0]
                checks.append(
                    FreezeCheck(
                        name="research_discipline_gate:promotion_eligible",
                        passed=str(item.get("status")) == "PASS",
                        value=item.get("value"),
                        threshold=str(item.get("threshold")),
                        source=str(discipline_path),
                    )
                )
        else:
            checks.append(_missing_check("research_discipline_gate:promotion_eligible", discipline_path, "file exists"))
    return checks


def _lockbox_checks(run_dir: Path, criteria: dict[str, Any]) -> list[FreezeCheck]:
    checks: list[FreezeCheck] = []
    trade_path = run_dir / "trades" / "trade_log.csv"
    if trade_path.exists():
        trades = pd.read_csv(trade_path)
        pnl = pd.to_numeric(trades.get("pnl", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
        gross_profit = float(pnl[pnl > 0].sum())
        gross_loss = abs(float(pnl[pnl < 0].sum()))
        profit_factor = math.inf if gross_loss == 0 and gross_profit > 0 else gross_profit / gross_loss if gross_loss else 0.0
        total_pnl = float(pnl.sum())
        checks.extend(
            [
                FreezeCheck(
                    name="lockbox:min_trades",
                    passed=len(trades) >= int(criteria.get("min_trades", 0)),
                    value=len(trades),
                    threshold=f">= {int(criteria.get('min_trades', 0))}",
                    source=str(trade_path),
                ),
                FreezeCheck(
                    name="lockbox:profit_factor",
                    passed=profit_factor >= float(criteria.get("min_profit_factor", 0.0)),
                    value=profit_factor,
                    threshold=f">= {float(criteria.get('min_profit_factor', 0.0))}",
                    source=str(trade_path),
                ),
                FreezeCheck(
                    name="lockbox:total_pnl",
                    passed=total_pnl > float(criteria.get("min_total_pnl", 0.0)),
                    value=total_pnl,
                    threshold=f"> {float(criteria.get('min_total_pnl', 0.0))}",
                    source=str(trade_path),
                ),
            ]
        )
    else:
        checks.append(_missing_check("lockbox:trade_log", trade_path, "file exists"))

    stress_path = run_dir / "simulations" / "stress_trade_stress_tests.csv"
    if stress_path.exists():
        stress = pd.read_csv(stress_path)
        row = stress.loc[stress["scenario"].eq("combined_mild")].head(1)
        if row.empty:
            checks.append(_missing_check("lockbox:combined_mild_profit_factor", stress_path, "scenario exists"))
        else:
            pf = _finite_float(row.iloc[0].get("profit_factor"))
            min_pf = float(criteria.get("min_combined_mild_profit_factor", 1.0))
            checks.append(
                FreezeCheck(
                    name="lockbox:combined_mild_profit_factor",
                    passed=pf >= min_pf,
                    value=pf,
                    threshold=f">= {min_pf}",
                    source=str(stress_path),
                )
            )
    else:
        checks.append(_missing_check("lockbox:combined_mild_profit_factor", stress_path, "file exists"))
    return checks


def _missing_check(name: str, path: Path, threshold: str) -> FreezeCheck:
    return FreezeCheck(name=name, passed=False, value="missing", threshold=threshold, source=str(path))


def _finite_float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result if math.isfinite(result) else float("nan")


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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and verify frozen research-candidate manifests.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH), help="Freeze manifest path.")
    parser.add_argument("--candidate", default=DEFAULT_FREEZE_CANDIDATE, choices=sorted(CANDIDATE_CONFIGS))
    parser.add_argument("--write-manifest", action="store_true", help="Write a new manifest for --candidate.")
    parser.add_argument("--run-dir", default=None, help="Saved results/runs/<label> directory to evaluate.")
    parser.add_argument("--phase", choices=["development", "lockbox"], default="development")
    parser.add_argument("--print-command", action="store_true", help="Print the frozen backtest command for the user terminal.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    manifest_path = Path(args.manifest)
    if args.write_manifest:
        write_manifest(manifest_path, args.candidate)
        print(f"Wrote freeze manifest: {manifest_path}")

    if args.print_command:
        manifest = load_manifest(manifest_path)
        manifest_status = str(manifest.get("status", ""))
        active_candidate = bool(manifest.get("active_candidate", manifest_status == "frozen"))
        candidate = str(manifest.get("candidate", args.candidate))
        if active_candidate:
            print(f"caffeinate -dimsu python3 main_backtest.py --candidate {candidate} --start 2021-01-01")
        else:
            print("No active frozen candidate. Run the pre-candidate signal gate and write a fresh hypothesis before freezing a new candidate.")

    report = verify_freeze(manifest_path, run_dir=args.run_dir, phase=args.phase)
    print(report.summary())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
