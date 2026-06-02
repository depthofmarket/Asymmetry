from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class L2ActionPolicy:
    name: str
    set_actions: tuple[int, ...]
    clear_actions: tuple[int, ...]
    ignore_actions: tuple[int, ...] = ()
    action_operations: tuple[tuple[int, str], ...] = ()
    book_key: str = "level"
    side_mapping: tuple[tuple[int, str], ...] = ((0, "bid"), (1, "ask"))
    zero_size_clears: bool = True
    description: str = ""


@dataclass(frozen=True)
class L2BookValidationArtifacts:
    summary: pd.DataFrame
    snapshots: pd.DataFrame
    report_md: str


def default_l2_action_policies() -> tuple[L2ActionPolicy, ...]:
    return (
        L2ActionPolicy(
            name="price_key_0_1_set_2_delete",
            set_actions=(0, 1),
            clear_actions=(2,),
            book_key="price",
            description="Treat side+price as the book key; actions 0/1 set displayed size and action 2 deletes price.",
        ),
        L2ActionPolicy(
            name="price_key_all_actions_set",
            set_actions=(0, 1, 2),
            clear_actions=(),
            book_key="price",
            description="Treat side+price as the book key; every action sets displayed size and zero size deletes.",
        ),
        L2ActionPolicy(
            name="price_key_reversed_side_0_1_set_2_delete",
            set_actions=(0, 1),
            clear_actions=(2,),
            book_key="price",
            side_mapping=((0, "ask"), (1, "bid")),
            description="Reverse side mapping, then treat side+price as the book key with actions 0/1 set and action 2 delete.",
        ),
        L2ActionPolicy(
            name="0_insert_1_update_2_delete",
            set_actions=(),
            clear_actions=(),
            action_operations=((0, "insert"), (1, "update"), (2, "delete")),
            description="Treat action 0 as level insert, action 1 as level update, and action 2 as level delete.",
        ),
        L2ActionPolicy(
            name="0_insert_1_delete_2_update",
            set_actions=(),
            clear_actions=(),
            action_operations=((0, "insert"), (1, "delete"), (2, "update")),
            description="Treat action 0 as level insert, action 1 as level delete, and action 2 as level update.",
        ),
        L2ActionPolicy(
            name="0_update_1_insert_2_delete",
            set_actions=(),
            clear_actions=(),
            action_operations=((0, "update"), (1, "insert"), (2, "delete")),
            description="Treat action 0 as level update, action 1 as level insert, and action 2 as level delete.",
        ),
        L2ActionPolicy(
            name="all_actions_set",
            set_actions=(0, 1, 2),
            clear_actions=(),
            description="Treat every depth event as a level replacement; zero size clears.",
        ),
        L2ActionPolicy(
            name="0_1_set_2_clear",
            set_actions=(0, 1),
            clear_actions=(2,),
            description="Treat actions 0/1 as level replacement and action 2 as delete/clear.",
        ),
        L2ActionPolicy(
            name="0_2_set_1_clear",
            set_actions=(0, 2),
            clear_actions=(1,),
            description="Treat actions 0/2 as level replacement and action 1 as delete/clear.",
        ),
        L2ActionPolicy(
            name="0_set_1_2_clear",
            set_actions=(0,),
            clear_actions=(1, 2),
            description="Treat action 0 as level replacement and actions 1/2 as delete/clear.",
        ),
        L2ActionPolicy(
            name="0_1_2_set_no_zero_clear",
            set_actions=(0, 1, 2),
            clear_actions=(),
            zero_size_clears=False,
            description="Treat every depth event as level replacement and preserve zero-size levels.",
        ),
    )


def validate_l2_book_semantics(
    events: pd.DataFrame,
    *,
    policies: Iterable[L2ActionPolicy] | None = None,
    tick_size: float = 0.25,
    max_reasonable_spread_ticks: float = 20.0,
    max_snapshots_per_policy: int = 5_000,
) -> L2BookValidationArtifacts:
    selected_policies = tuple(policies or default_l2_action_policies())
    summary_frames: list[pd.DataFrame] = []
    snapshot_frames: list[pd.DataFrame] = []

    if events.empty:
        empty = pd.DataFrame()
        return L2BookValidationArtifacts(
            summary=empty,
            snapshots=empty,
            report_md=render_l2_book_validation_report(empty),
        )

    if "source_label" in events.columns:
        grouped = events.groupby("source_label", dropna=False, sort=True)
    else:
        grouped = [("events", events)]

    for source_label, frame in grouped:
        for policy in selected_policies:
            policy_result = _evaluate_l2_action_policy(
                frame,
                policy=policy,
                source_label=str(source_label),
                tick_size=float(tick_size),
                max_reasonable_spread_ticks=float(max_reasonable_spread_ticks),
                max_snapshots=int(max_snapshots_per_policy),
            )
            summary_frames.append(policy_result.summary)
            if not policy_result.snapshots.empty:
                snapshot_frames.append(policy_result.snapshots)

    summary = pd.concat(summary_frames, ignore_index=True) if summary_frames else pd.DataFrame()
    if not summary.empty:
        summary = summary.sort_values(
            ["source_label", "sanity_score", "valid_top_book_pct", "crossed_or_locked_pct"],
            ascending=[True, False, False, True],
        ).reset_index(drop=True)
    snapshots = pd.concat(snapshot_frames, ignore_index=True) if snapshot_frames else pd.DataFrame()
    return L2BookValidationArtifacts(
        summary=summary,
        snapshots=snapshots,
        report_md=render_l2_book_validation_report(summary),
    )


def write_l2_book_validation_artifacts(
    artifacts: L2BookValidationArtifacts,
    out_dir: Path | str,
    *,
    prefix: str = "l2_book_validation",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    summary_path = out_path / f"{prefix}_summary.csv"
    snapshots_path = out_path / f"{prefix}_snapshots.csv"
    report_path = out_path / f"{prefix}_report.md"
    artifacts.summary.to_csv(summary_path, index=False)
    artifacts.snapshots.to_csv(snapshots_path, index=False)
    report_path.write_text(artifacts.report_md, encoding="utf-8")
    return {"summary_csv": summary_path, "snapshots_csv": snapshots_path, "report_md": report_path}


@dataclass(frozen=True)
class _PolicyEvaluation:
    summary: pd.DataFrame
    snapshots: pd.DataFrame


def _evaluate_l2_action_policy(
    events: pd.DataFrame,
    *,
    policy: L2ActionPolicy,
    source_label: str,
    tick_size: float,
    max_reasonable_spread_ticks: float,
    max_snapshots: int,
) -> _PolicyEvaluation:
    depth = _prepare_depth_events(events)
    bid_book: dict[float | int, tuple[float, float]] = {}
    ask_book: dict[float | int, tuple[float, float]] = {}

    snapshot_rows: list[dict[str, object]] = []
    observed = _ObservedBookMetrics()
    for row in depth.itertuples(index=False):
        action = int(row.action_code)
        level = int(row.level)
        side = _side_for_policy(policy, side_code=int(row.side_or_code), fallback=str(row.book_side))
        size = float(row.size)
        price = float(row.price)
        target_book = bid_book if side == "bid" else ask_book

        _apply_policy_update(target_book, level=level, price=price, size=size, action=action, policy=policy)

        snapshot = _book_snapshot(
            bid_book,
            ask_book,
            event_time_utc=row.event_time_utc,
            event_time_ny=row.event_time_ny,
            source_label=source_label,
            policy=policy.name,
            action_code=action,
            updated_side=side,
            updated_level=level,
            tick_size=tick_size,
            book_key=policy.book_key,
        )
        observed.observe(snapshot, max_reasonable_spread_ticks=max_reasonable_spread_ticks)
        if len(snapshot_rows) < max_snapshots:
            snapshot_rows.append(snapshot)

    summary = pd.DataFrame(
        [
            observed.to_row(
                source_label=source_label,
                policy=policy,
                depth_events=len(depth),
                tick_size=tick_size,
                max_reasonable_spread_ticks=max_reasonable_spread_ticks,
            )
        ]
    )
    snapshots = pd.DataFrame(snapshot_rows)
    return _PolicyEvaluation(summary=summary, snapshots=snapshots)


def _prepare_depth_events(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    required = [
        "event_family",
        "book_side",
        "side_or_code",
        "level",
        "price",
        "size",
        "action_code",
        "event_time_utc",
        "event_time_ny",
    ]
    missing = [col for col in required if col not in events.columns]
    if missing:
        raise ValueError(f"Decoded L2 events are missing required column(s): {', '.join(missing)}")

    depth = events.loc[events["event_family"].astype(str).eq("depth_update")].copy()
    if depth.empty:
        return depth
    for col in ("level", "price", "size", "action_code"):
        depth[col] = pd.to_numeric(depth[col], errors="coerce")
    depth = depth.dropna(subset=["book_side", "level", "price", "size", "action_code", "event_time_utc"])
    depth = depth.loc[depth["book_side"].isin(["bid", "ask"])]
    depth = depth.loc[depth["level"].between(1, 10)]
    return depth.sort_values("event_time_utc").reset_index(drop=True)


def _book_snapshot(
    bid_book: dict[float | int, tuple[float, float]],
    ask_book: dict[float | int, tuple[float, float]],
    *,
    event_time_utc,
    event_time_ny,
    source_label: str,
    policy: str,
    action_code: int,
    updated_side: str,
    updated_level: int,
    tick_size: float,
    book_key: str,
) -> dict[str, object]:
    bid_top = _best_book_level(bid_book, side="bid", book_key=book_key)
    ask_top = _best_book_level(ask_book, side="ask", book_key=book_key)
    bid_price = bid_top[0] if bid_top is not None else np.nan
    ask_price = ask_top[0] if ask_top is not None else np.nan
    spread = ask_price - bid_price if np.isfinite(bid_price) and np.isfinite(ask_price) else np.nan
    bid_monotonic = _book_side_monotonic(bid_book, side="bid", book_key=book_key)
    ask_monotonic = _book_side_monotonic(ask_book, side="ask", book_key=book_key)
    return {
        "source_label": source_label,
        "policy": policy,
        "event_time_utc": event_time_utc,
        "event_time_ny": event_time_ny,
        "action_code": action_code,
        "updated_side": updated_side,
        "updated_level": updated_level,
        "bid_px_00": bid_price,
        "ask_px_00": ask_price,
        "bid_sz_00": bid_top[1] if bid_top is not None else np.nan,
        "ask_sz_00": ask_top[1] if ask_top is not None else np.nan,
        "spread_points": spread,
        "spread_ticks": spread / tick_size if np.isfinite(spread) and tick_size > 0 else np.nan,
        "valid_top_book": bool(np.isfinite(spread)),
        "crossed_or_locked": bool(np.isfinite(spread) and spread <= 0.0),
        "bid_monotonic": bid_monotonic,
        "ask_monotonic": ask_monotonic,
        "book_monotonic": bool(bid_monotonic and ask_monotonic),
        "bid_levels_present": len(bid_book),
        "ask_levels_present": len(ask_book),
    }


def _best_book_level(
    book: dict[float | int, tuple[float, float]],
    *,
    side: str,
    book_key: str,
) -> tuple[float, float] | None:
    if not book:
        return None
    if book_key == "level":
        return book.get(1)
    if book_key == "price":
        prices = [float(value[0]) for value in book.values() if np.isfinite(value[0])]
        if not prices:
            return None
        best_price = max(prices) if side == "bid" else min(prices)
        return book.get(best_price)
    raise ValueError(f"Unsupported L2 book key: {book_key}")


def _book_side_monotonic(book: dict[float | int, tuple[float, float]], *, side: str, book_key: str) -> bool:
    if len(book) <= 1:
        return True
    if book_key == "price":
        return True
    prices = [(level, float(value[0])) for level, value in sorted(book.items()) if np.isfinite(value[0])]
    if len(prices) <= 1:
        return True
    for (_, prev_price), (_, next_price) in zip(prices, prices[1:]):
        if side == "bid" and not (prev_price > next_price):
            return False
        if side == "ask" and not (prev_price < next_price):
            return False
    return True


def _apply_policy_update(
    book: dict[float | int, tuple[float, float]],
    *,
    level: int,
    price: float,
    size: float,
    action: int,
    policy: L2ActionPolicy,
) -> None:
    operation = _operation_for_action(policy, action=action, size=size)
    if policy.book_key == "price":
        if operation in {"set", "update", "insert"}:
            book[price] = (price, size)
        elif operation == "delete":
            book.pop(price, None)
        elif operation != "ignore":
            raise ValueError(f"Unsupported L2 action operation for price-keyed book: {operation}")
        return

    if operation == "ignore":
        return
    if operation in {"set", "update"}:
        book[level] = (price, size)
        return
    if operation == "insert":
        for existing_level in range(10, level, -1):
            prev = existing_level - 1
            if prev in book:
                book[existing_level] = book[prev]
            else:
                book.pop(existing_level, None)
        book[level] = (price, size)
        return
    if operation == "delete":
        for existing_level in range(level, 10):
            next_level = existing_level + 1
            if next_level in book:
                book[existing_level] = book[next_level]
            else:
                book.pop(existing_level, None)
        book.pop(10, None)
        return
    raise ValueError(f"Unsupported L2 action operation: {operation}")


def _operation_for_action(policy: L2ActionPolicy, *, action: int, size: float) -> str:
    if policy.zero_size_clears and size <= 0.0:
        return "delete"
    if policy.action_operations:
        operations = dict(policy.action_operations)
        return operations.get(action, "ignore")
    if action in policy.ignore_actions:
        return "ignore"
    if action in policy.clear_actions:
        return "delete"
    if action in policy.set_actions:
        return "set"
    return "ignore"


def _side_for_policy(policy: L2ActionPolicy, *, side_code: int, fallback: str) -> str:
    mapping = dict(policy.side_mapping)
    return mapping.get(side_code, fallback)


@dataclass
class _ObservedBookMetrics:
    snapshots: int = 0
    valid_top_book: int = 0
    crossed_or_locked: int = 0
    monotonic_ok: int = 0
    reasonable_spread: int = 0
    off_tick_spread: int = 0
    missing_top_book: int = 0
    spread_ticks: list[float] | None = None
    bid_levels: list[int] | None = None
    ask_levels: list[int] | None = None

    def __post_init__(self) -> None:
        self.spread_ticks = []
        self.bid_levels = []
        self.ask_levels = []

    def observe(self, snapshot: dict[str, object], *, max_reasonable_spread_ticks: float) -> None:
        self.snapshots += 1
        self.bid_levels.append(int(snapshot["bid_levels_present"]))
        self.ask_levels.append(int(snapshot["ask_levels_present"]))
        if bool(snapshot["book_monotonic"]):
            self.monotonic_ok += 1
        if not bool(snapshot["valid_top_book"]):
            self.missing_top_book += 1
            return
        self.valid_top_book += 1
        if bool(snapshot["crossed_or_locked"]):
            self.crossed_or_locked += 1
        spread_ticks = float(snapshot["spread_ticks"])
        self.spread_ticks.append(spread_ticks)
        if 0.0 < spread_ticks <= max_reasonable_spread_ticks:
            self.reasonable_spread += 1
        if not np.isclose(spread_ticks, round(spread_ticks), atol=1e-7):
            self.off_tick_spread += 1

    def to_row(
        self,
        *,
        source_label: str,
        policy: L2ActionPolicy,
        depth_events: int,
        tick_size: float,
        max_reasonable_spread_ticks: float,
    ) -> dict[str, object]:
        snapshots = max(1, self.snapshots)
        valid = max(1, self.valid_top_book)
        spread_series = pd.Series(self.spread_ticks, dtype="float64")
        missing_top_book_pct = self.missing_top_book / snapshots
        crossed_or_locked_pct = self.crossed_or_locked / valid if self.valid_top_book else 1.0
        monotonic_violation_pct = 1.0 - (self.monotonic_ok / snapshots)
        unreasonable_spread_pct = 1.0 - (self.reasonable_spread / valid) if self.valid_top_book else 1.0
        off_tick_spread_pct = self.off_tick_spread / valid if self.valid_top_book else 1.0
        valid_top_book_pct = self.valid_top_book / snapshots
        sanity_score = _sanity_score(
            valid_top_book_pct=valid_top_book_pct,
            missing_top_book_pct=missing_top_book_pct,
            crossed_or_locked_pct=crossed_or_locked_pct,
            monotonic_violation_pct=monotonic_violation_pct,
            unreasonable_spread_pct=unreasonable_spread_pct,
            off_tick_spread_pct=off_tick_spread_pct,
        )
        return {
            "source_label": source_label,
            "policy": policy.name,
            "description": policy.description,
            "depth_events": depth_events,
            "snapshots_evaluated": self.snapshots,
            "valid_top_book_pct": valid_top_book_pct,
            "missing_top_book_pct": missing_top_book_pct,
            "crossed_or_locked_pct": crossed_or_locked_pct,
            "book_monotonic_ok_pct": self.monotonic_ok / snapshots,
            "monotonic_violation_pct": monotonic_violation_pct,
            "reasonable_spread_pct": self.reasonable_spread / valid if self.valid_top_book else 0.0,
            "unreasonable_spread_pct": unreasonable_spread_pct,
            "off_tick_spread_pct": off_tick_spread_pct,
            "median_spread_ticks": _safe_quantile(spread_series, 0.50),
            "p95_spread_ticks": _safe_quantile(spread_series, 0.95),
            "median_spread_points": _safe_quantile(spread_series, 0.50) * tick_size,
            "p95_spread_points": _safe_quantile(spread_series, 0.95) * tick_size,
            "median_bid_levels_present": _safe_median(self.bid_levels),
            "median_ask_levels_present": _safe_median(self.ask_levels),
            "max_reasonable_spread_ticks": max_reasonable_spread_ticks,
            "sanity_score": sanity_score,
        }


def _sanity_score(
    *,
    valid_top_book_pct: float,
    missing_top_book_pct: float,
    crossed_or_locked_pct: float,
    monotonic_violation_pct: float,
    unreasonable_spread_pct: float,
    off_tick_spread_pct: float,
) -> float:
    raw = valid_top_book_pct
    raw *= max(0.0, 1.0 - 0.25 * missing_top_book_pct)
    raw *= max(0.0, 1.0 - 3.0 * crossed_or_locked_pct)
    raw *= max(0.0, 1.0 - monotonic_violation_pct)
    raw *= max(0.0, 1.0 - 0.50 * unreasonable_spread_pct)
    raw *= max(0.0, 1.0 - off_tick_spread_pct)
    return float(np.clip(raw, 0.0, 1.0))


def _safe_quantile(series: pd.Series, q: float) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.quantile(q)) if not clean.empty else np.nan


def _safe_median(values: list[int] | None) -> float:
    if not values:
        return np.nan
    return float(pd.Series(values, dtype="float64").median())


def render_l2_book_validation_report(summary: pd.DataFrame) -> str:
    lines = [
        "# L2 Book Semantics Validation",
        "",
        "This is a bounded semantic validator. It ranks action-code hypotheses by book sanity; it is not a backtest or signal-mining pass.",
        "",
    ]
    if summary.empty:
        lines.extend(["No validation rows were produced.", ""])
        return "\n".join(lines)

    for source_label, frame in summary.groupby("source_label", sort=True):
        best = frame.sort_values("sanity_score", ascending=False).iloc[0]
        lines.extend(
            [
                f"## {source_label}",
                "",
                f"- Leading policy: `{best['policy']}`",
                f"- Sanity score: {float(best['sanity_score']):.3f}",
                f"- Plausibility: {_plausibility_label(best)}",
                f"- Valid top-book snapshots: {float(best['valid_top_book_pct']):.3%}",
                f"- Crossed/locked valid snapshots: {float(best['crossed_or_locked_pct']):.3%}",
                f"- Monotonic violation snapshots: {float(best['monotonic_violation_pct']):.3%}",
                f"- Median spread: {float(best['median_spread_ticks']):.2f} ticks",
                "",
                "| policy | score | valid top book | crossed/locked | monotonic violations | median spread ticks | p95 spread ticks |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for _, row in frame.sort_values("sanity_score", ascending=False).iterrows():
            lines.append(
                "| "
                f"`{row['policy']}` | "
                f"{float(row['sanity_score']):.3f} | "
                f"{float(row['valid_top_book_pct']):.3%} | "
                f"{float(row['crossed_or_locked_pct']):.3%} | "
                f"{float(row['monotonic_violation_pct']):.3%} | "
                f"{float(row['median_spread_ticks']):.2f} | "
                f"{float(row['p95_spread_ticks']):.2f} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Decision Rule",
            "",
            "A policy is plausible only if it keeps top-of-book valid, avoids crossed/locked books, preserves monotonic bid/ask levels, and produces tick-grid spreads. Treat the ranking as evidence, not proof; source documentation or trade/quote cross-checks should still confirm the raw codes.",
            "",
        ]
    )
    return "\n".join(lines)


def _plausibility_label(row: pd.Series) -> str:
    score = float(row.get("sanity_score", 0.0))
    crossed = float(row.get("crossed_or_locked_pct", 1.0))
    monotonic = float(row.get("monotonic_violation_pct", 1.0))
    valid = float(row.get("valid_top_book_pct", 0.0))
    if score >= 0.75 and crossed <= 0.005 and monotonic <= 0.01 and valid >= 0.95:
        return "plausible"
    if score >= 0.40 and crossed <= 0.02 and monotonic <= 0.10 and valid >= 0.80:
        return "needs cross-check"
    return "rejected by this sample"
