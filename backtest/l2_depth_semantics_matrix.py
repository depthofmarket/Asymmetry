from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.l2_book_validation import (
    L2ActionPolicy,
    default_l2_action_policies,
    validate_l2_book_semantics,
)
from backtest.l2_mbp import L2ParquetSourceRef, decode_l2_mbp_sources
from backtest.l2_topbook_validation_matrix import (
    DEFAULT_VALIDATION_DATES,
    discover_l2_date_members,
)


@dataclass(frozen=True)
class L2DepthSemanticsProofConfig:
    tick_size: float = 0.25
    max_reasonable_spread_ticks: float = 20.0
    max_rows_per_member: int = 200_000
    start_row_group: int = 0
    max_snapshots_per_policy: int = 20_000
    min_depth_events: int = 1_000
    min_snapshots: int = 1_000
    min_valid_top_book_pct: float = 0.95
    max_crossed_or_locked_pct: float = 0.005
    max_monotonic_violation_pct: float = 0.01
    min_reasonable_spread_pct: float = 0.95
    max_off_tick_spread_pct: float = 0.0
    min_median_levels_present: float = 2.0
    topbook_min_valid_top_book_pct: float = 0.95
    topbook_max_crossed_or_locked_pct: float = 0.05
    topbook_min_reasonable_spread_pct: float = 0.90
    topbook_max_off_tick_spread_pct: float = 0.0


@dataclass(frozen=True)
class L2DepthSemanticsProofResult:
    targets: pd.DataFrame
    policy_evidence: pd.DataFrame
    decision_summary: pd.DataFrame
    report_md: str


def build_l2_depth_semantics_proof(
    events: pd.DataFrame,
    *,
    config: L2DepthSemanticsProofConfig | None = None,
    policies: tuple[L2ActionPolicy, ...] | None = None,
    date: str = "",
    source_path: str = "",
    member: str = "",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = config or L2DepthSemanticsProofConfig()
    source_schema = _source_schema_text(events)
    depth_capability = _depth_capability(events)
    if events.empty:
        evidence = _non_reconstructable_policy_row(
            date=date,
            source_path=source_path,
            member=member,
            source_schema=source_schema,
            reason="no decoded events",
        )
        return evidence, _decision_summary_from_evidence(evidence, cfg)

    if not depth_capability["has_explicit_depth_level"] or not depth_capability["has_explicit_action_code"]:
        reason_parts = []
        if not depth_capability["has_explicit_depth_level"]:
            reason_parts.append("missing explicit depth level")
        if not depth_capability["has_explicit_action_code"]:
            reason_parts.append("missing explicit action code")
        evidence = _non_reconstructable_policy_row(
            date=date,
            source_path=source_path,
            member=member,
            source_schema=source_schema,
            reason="; ".join(reason_parts),
            decoded_rows=len(events),
            depth_events=depth_capability["depth_events"],
        )
        return evidence, _decision_summary_from_evidence(evidence, cfg)

    validation = validate_l2_book_semantics(
        events,
        policies=policies or default_l2_action_policies(),
        tick_size=float(cfg.tick_size),
        max_reasonable_spread_ticks=float(cfg.max_reasonable_spread_ticks),
        max_snapshots_per_policy=int(cfg.max_snapshots_per_policy),
    )
    evidence = validation.summary.copy()
    if evidence.empty:
        evidence = _non_reconstructable_policy_row(
            date=date,
            source_path=source_path,
            member=member,
            source_schema=source_schema,
            reason="no policy validation rows",
            decoded_rows=len(events),
            depth_events=depth_capability["depth_events"],
        )
        return evidence, _decision_summary_from_evidence(evidence, cfg)

    policy_lookup = {policy.name: policy for policy in default_l2_action_policies()}
    evidence.insert(0, "date", date)
    evidence.insert(1, "source_schema", source_schema)
    evidence["source_path"] = source_path
    evidence["member"] = member
    evidence["decoded_rows"] = int(len(events))
    evidence["policy_book_key"] = evidence["policy"].map(
        lambda value: policy_lookup.get(str(value)).book_key if policy_lookup.get(str(value)) else ""
    )
    evidence["policy_proof_status"], evidence["policy_rejection_reason"] = zip(
        *[_classify_policy_row(row, cfg) for _, row in evidence.iterrows()]
    )
    evidence["full_depth_allowed"] = evidence["policy_proof_status"].eq("accepted")
    evidence["topbook_only_allowed"] = evidence.apply(lambda row: _topbook_policy_allowed(row, cfg), axis=1)
    evidence["topbook_score"] = evidence.apply(_topbook_score, axis=1)
    return evidence, _decision_summary_from_evidence(evidence, cfg)


def build_l2_depth_semantics_proof_matrix(
    archive_root: Path | str,
    *,
    target_dates: list[str] | tuple[str, ...] | None = None,
    config: L2DepthSemanticsProofConfig | None = None,
    policies: tuple[L2ActionPolicy, ...] | None = None,
    dry_run: bool = False,
) -> L2DepthSemanticsProofResult:
    cfg = config or L2DepthSemanticsProofConfig()
    dates = tuple(target_dates or DEFAULT_VALIDATION_DATES)
    discovered = discover_l2_date_members(archive_root, target_dates=dates)
    target_rows: list[dict[str, object]] = []
    evidence_frames: list[pd.DataFrame] = []
    decision_frames: list[pd.DataFrame] = []

    for date in dates:
        item = discovered.get(date)
        if item is None:
            target_rows.append(
                {
                    "date": date,
                    "status": "missing",
                    "source_path": "",
                    "member": "",
                    "duplicate_sources": 0,
                    "error": "date_not_found_in_archives",
                }
            )
            continue
        target_rows.append(
            {
                "date": date,
                "status": "found" if dry_run else "pending",
                "source_path": item.source_path,
                "member": item.member,
                "duplicate_sources": item.duplicate_sources,
                "error": "",
            }
        )
        if dry_run:
            continue
        try:
            refs = [
                L2ParquetSourceRef(
                    source_path=Path(item.source_path),
                    label=f"{Path(item.source_path).name}:{item.member}",
                    zip_member=item.member,
                )
            ]
            decoded = decode_l2_mbp_sources(
                refs,
                max_rows_per_source=int(cfg.max_rows_per_member),
                start_row_group=int(cfg.start_row_group),
            )
            evidence, decision = build_l2_depth_semantics_proof(
                decoded.events,
                config=cfg,
                policies=policies,
                date=date,
                source_path=item.source_path,
                member=item.member,
            )
            evidence_frames.append(evidence)
            decision_frames.append(decision)
            target_rows[-1]["status"] = "processed"
        except Exception as exc:  # pragma: no cover - artifact logging path
            target_rows[-1]["status"] = "error"
            target_rows[-1]["error"] = str(exc)

    targets = pd.DataFrame(target_rows)
    policy_evidence = pd.concat(evidence_frames, ignore_index=True) if evidence_frames else pd.DataFrame()
    decision_summary = pd.concat(decision_frames, ignore_index=True) if decision_frames else pd.DataFrame()
    report_md = render_l2_depth_semantics_proof_report(
        targets,
        policy_evidence,
        decision_summary,
        config=cfg,
        dry_run=dry_run,
    )
    return L2DepthSemanticsProofResult(
        targets=targets,
        policy_evidence=policy_evidence,
        decision_summary=decision_summary,
        report_md=report_md,
    )


def write_l2_depth_semantics_proof_matrix(
    result: L2DepthSemanticsProofResult,
    out_dir: Path | str,
    *,
    prefix: str = "l2_depth_semantics_proof_matrix",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "targets_csv": out_path / f"{prefix}_targets.csv",
        "policy_evidence_csv": out_path / f"{prefix}_policy_evidence.csv",
        "decision_summary_csv": out_path / f"{prefix}_decision_summary.csv",
        "report_md": out_path / f"{prefix}_report.md",
    }
    result.targets.to_csv(paths["targets_csv"], index=False)
    result.policy_evidence.to_csv(paths["policy_evidence_csv"], index=False)
    result.decision_summary.to_csv(paths["decision_summary_csv"], index=False)
    paths["report_md"].write_text(result.report_md, encoding="utf-8")
    return paths


def render_l2_depth_semantics_proof_report(
    targets: pd.DataFrame,
    policy_evidence: pd.DataFrame,
    decision_summary: pd.DataFrame,
    *,
    config: L2DepthSemanticsProofConfig,
    dry_run: bool,
) -> str:
    lines = [
        "# L2 Depth Semantics Proof Matrix",
        "",
        "This matrix tests whether decoded L2 depth updates can support full-depth replay. It is not a strategy backtest and must not be used as signal evidence.",
        "",
        "## Run Config",
        "",
        f"- Dry run: `{dry_run}`",
        f"- Max rows per member: {int(config.max_rows_per_member):,}",
        f"- Start row group: {int(config.start_row_group):,}",
        f"- Max snapshots per policy: {int(config.max_snapshots_per_policy):,}",
        f"- Full-depth thresholds: valid top book >= {config.min_valid_top_book_pct:.1%}, crossed/locked <= {config.max_crossed_or_locked_pct:.2%}, monotonic violations <= {config.max_monotonic_violation_pct:.2%}",
        "",
        "## Targets",
        "",
        _frame_to_markdown(targets, ["date", "status", "member", "duplicate_sources", "error"], max_rows=80),
        "",
    ]
    if not decision_summary.empty:
        lines.extend(
            [
                "## Depth Decision",
                "",
                _frame_to_markdown(
                    decision_summary,
                    [
                        "date",
                        "source_schema",
                        "best_policy",
                        "full_depth_allowed",
                        "topbook_only_allowed",
                        "decision",
                        "decision_reason",
                    ],
                    max_rows=80,
                ),
                "",
            ]
        )
    if not policy_evidence.empty:
        lines.extend(
            [
                "## Policy Evidence",
                "",
                _frame_to_markdown(
                    policy_evidence.sort_values(
                        ["date", "full_depth_allowed", "topbook_only_allowed", "topbook_score"],
                        ascending=[True, False, False, False],
                    ),
                    [
                        "date",
                        "policy",
                        "policy_book_key",
                        "policy_proof_status",
                        "topbook_only_allowed",
                        "valid_top_book_pct",
                        "crossed_or_locked_pct",
                        "monotonic_violation_pct",
                        "reasonable_spread_pct",
                        "median_spread_ticks",
                        "policy_rejection_reason",
                    ],
                    max_rows=120,
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation",
            "",
            "- `full_depth_allowed=True` means the policy passed strict MBP-depth checks and can be used by a full-depth execution simulator.",
            "- `topbook_only_allowed=True` means top-of-book execution can be usable while full-depth replay remains rejected.",
            "- Structured five-column files are rejected for full-depth replay unless a later proof establishes explicit depth levels and action semantics.",
            "",
        ]
    )
    return "\n".join(lines)


def _depth_capability(events: pd.DataFrame) -> dict[str, object]:
    if events.empty:
        return {"depth_events": 0, "has_explicit_depth_level": False, "has_explicit_action_code": False}
    depth = events.loc[events.get("event_family", pd.Series(index=events.index, dtype="string")).astype(str).eq("depth_update")]
    if depth.empty:
        return {"depth_events": 0, "has_explicit_depth_level": False, "has_explicit_action_code": False}
    level = pd.to_numeric(depth.get("level", pd.Series(np.nan, index=depth.index)), errors="coerce")
    action = pd.to_numeric(depth.get("action_code", pd.Series(np.nan, index=depth.index)), errors="coerce")
    explicit_level = bool(level.between(1, 10).mean() >= 0.50)
    explicit_action = bool(action.notna().mean() >= 0.95)
    return {
        "depth_events": int(len(depth)),
        "has_explicit_depth_level": explicit_level,
        "has_explicit_action_code": explicit_action,
    }


def _source_schema_text(events: pd.DataFrame) -> str:
    if events.empty or "source_schema" not in events:
        return ""
    counts = events["source_schema"].dropna().astype(str).value_counts().sort_index()
    return ";".join(f"{key}:{int(value)}" for key, value in counts.items())


def _non_reconstructable_policy_row(
    *,
    date: str,
    source_path: str,
    member: str,
    source_schema: str,
    reason: str,
    decoded_rows: int = 0,
    depth_events: int = 0,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": date,
                "source_schema": source_schema,
                "source_path": source_path,
                "member": member,
                "source_label": member or source_path,
                "policy": "no_full_depth_policy",
                "description": "",
                "policy_book_key": "",
                "decoded_rows": int(decoded_rows),
                "depth_events": int(depth_events),
                "snapshots_evaluated": 0,
                "valid_top_book_pct": 0.0,
                "missing_top_book_pct": 1.0,
                "crossed_or_locked_pct": 1.0,
                "book_monotonic_ok_pct": 0.0,
                "monotonic_violation_pct": 1.0,
                "reasonable_spread_pct": 0.0,
                "unreasonable_spread_pct": 1.0,
                "off_tick_spread_pct": 1.0,
                "median_spread_ticks": np.nan,
                "p95_spread_ticks": np.nan,
                "median_bid_levels_present": np.nan,
                "median_ask_levels_present": np.nan,
                "sanity_score": 0.0,
                "topbook_score": 0.0,
                "policy_proof_status": "rejected",
                "policy_rejection_reason": reason,
                "full_depth_allowed": False,
                "topbook_only_allowed": False,
            }
        ]
    )


def _classify_policy_row(row: pd.Series, cfg: L2DepthSemanticsProofConfig) -> tuple[str, str]:
    reasons = []
    if str(row.get("policy_book_key", "")) != "level":
        reasons.append("policy is not level-keyed MBP depth")
    if _float(row.get("depth_events")) < cfg.min_depth_events:
        reasons.append(f"depth events < {cfg.min_depth_events}")
    if _float(row.get("snapshots_evaluated")) < cfg.min_snapshots:
        reasons.append(f"snapshots < {cfg.min_snapshots}")
    if _float(row.get("valid_top_book_pct")) < cfg.min_valid_top_book_pct:
        reasons.append(f"valid top book < {cfg.min_valid_top_book_pct:.1%}")
    if _float(row.get("crossed_or_locked_pct")) > cfg.max_crossed_or_locked_pct:
        reasons.append(f"crossed/locked > {cfg.max_crossed_or_locked_pct:.2%}")
    if _float(row.get("monotonic_violation_pct")) > cfg.max_monotonic_violation_pct:
        reasons.append(f"monotonic violations > {cfg.max_monotonic_violation_pct:.2%}")
    if _float(row.get("reasonable_spread_pct")) < cfg.min_reasonable_spread_pct:
        reasons.append(f"reasonable spread < {cfg.min_reasonable_spread_pct:.1%}")
    if _float(row.get("off_tick_spread_pct")) > cfg.max_off_tick_spread_pct:
        reasons.append(f"off-tick spread > {cfg.max_off_tick_spread_pct:.2%}")
    bid_levels = _float(row.get("median_bid_levels_present"))
    ask_levels = _float(row.get("median_ask_levels_present"))
    if min(bid_levels, ask_levels) < cfg.min_median_levels_present:
        reasons.append(f"median depth levels < {cfg.min_median_levels_present:.1f}")
    if reasons:
        return "rejected", "; ".join(reasons)
    return "accepted", "accepted full-depth policy"


def _topbook_policy_allowed(row: pd.Series, cfg: L2DepthSemanticsProofConfig) -> bool:
    if _float(row.get("valid_top_book_pct")) < cfg.topbook_min_valid_top_book_pct:
        return False
    if _float(row.get("crossed_or_locked_pct")) > cfg.topbook_max_crossed_or_locked_pct:
        return False
    if _float(row.get("reasonable_spread_pct")) < cfg.topbook_min_reasonable_spread_pct:
        return False
    if _float(row.get("off_tick_spread_pct")) > cfg.topbook_max_off_tick_spread_pct:
        return False
    return True


def _topbook_score(row: pd.Series) -> float:
    valid = _float(row.get("valid_top_book_pct"))
    crossed = _float(row.get("crossed_or_locked_pct"))
    reasonable = _float(row.get("reasonable_spread_pct"))
    off_tick = _float(row.get("off_tick_spread_pct"))
    return float(np.clip(valid * max(0.0, 1.0 - 3.0 * crossed) * reasonable * max(0.0, 1.0 - off_tick), 0.0, 1.0))


def _decision_summary_from_evidence(evidence: pd.DataFrame, cfg: L2DepthSemanticsProofConfig) -> pd.DataFrame:
    if evidence.empty:
        return pd.DataFrame()
    work = evidence.copy()
    if "topbook_score" not in work.columns:
        work["topbook_score"] = work.apply(_topbook_score, axis=1)
    sort_cols = ["full_depth_allowed", "topbook_only_allowed", "topbook_score", "sanity_score"]
    for col in sort_cols:
        if col not in work.columns:
            work[col] = False if col.endswith("allowed") else 0.0
    best = work.sort_values(sort_cols, ascending=[False, False, False, False]).iloc[0]
    full_depth_allowed = bool(work["full_depth_allowed"].fillna(False).astype(bool).any())
    topbook_allowed = bool(work["topbook_only_allowed"].fillna(False).astype(bool).any())
    if full_depth_allowed:
        decision = "full_depth_allowed"
        reason = "at least one policy passed strict full-depth checks"
    elif topbook_allowed:
        decision = "topbook_only"
        reason = "top-book checks pass but no policy passed full-depth monotonic/depth checks"
    else:
        decision = "rejected"
        reason = str(best.get("policy_rejection_reason", "no acceptable policy"))
    return pd.DataFrame(
        [
            {
                "date": best.get("date", ""),
                "source_schema": best.get("source_schema", ""),
                "source_path": best.get("source_path", ""),
                "member": best.get("member", ""),
                "best_policy": best.get("policy", ""),
                "full_depth_allowed": full_depth_allowed,
                "topbook_only_allowed": topbook_allowed and not full_depth_allowed,
                "decision": decision,
                "decision_reason": reason,
                "best_policy_topbook_score": _float(best.get("topbook_score")),
                "best_policy_sanity_score": _float(best.get("sanity_score")),
                "accepted_policy_count": int(work["full_depth_allowed"].fillna(False).astype(bool).sum()),
                "topbook_policy_count": int(work["topbook_only_allowed"].fillna(False).astype(bool).sum()),
                "proof_config": asdict(cfg),
            }
        ]
    )


def _float(value: object) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(out):
        return 0.0
    return out


def _frame_to_markdown(frame: pd.DataFrame, columns: list[str], *, max_rows: int = 40) -> str:
    if frame.empty:
        return "_None._"
    visible_cols = [col for col in columns if col in frame.columns]
    visible = frame.loc[:, visible_cols].head(max_rows).copy()
    lines = [
        "| " + " | ".join(visible_cols) + " |",
        "| " + " | ".join("---" for _ in visible_cols) + " |",
    ]
    for _, row in visible.iterrows():
        lines.append("| " + " | ".join(_fmt_value(row[col]) for col in visible_cols) + " |")
    if len(frame) > max_rows:
        lines.append(f"\n_Only showing first {max_rows} of {len(frame)} rows._")
    return "\n".join(lines)


def _fmt_value(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.4g}"
    if isinstance(value, dict):
        return str(value).replace("|", "/")
    return str(value).replace("|", "/")
