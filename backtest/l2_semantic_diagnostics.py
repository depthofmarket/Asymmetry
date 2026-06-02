from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.l2_book_validation import (
    L2ActionPolicy,
    _apply_policy_update,
    _best_book_level,
    _book_side_monotonic,
    _operation_for_action,
    _prepare_depth_events,
    _side_for_policy,
    default_l2_action_policies,
)


@dataclass(frozen=True)
class L2SemanticDiagnosticsArtifacts:
    field_summary: pd.DataFrame
    depth_action_summary: pd.DataFrame
    initial_depth_sample: pd.DataFrame
    top_book_summary: pd.DataFrame
    trade_alignment_summary: pd.DataFrame
    report_md: str


def diagnose_l2_semantics(
    events: pd.DataFrame,
    *,
    tick_size: float = 0.25,
    coalesce_windows: Iterable[str] = ("event", "1ms", "10ms", "100ms", "1s"),
    policy_names: Iterable[str] = ("0_insert_1_update_2_delete", "all_actions_set"),
    initial_depth_rows: int = 40,
) -> L2SemanticDiagnosticsArtifacts:
    if events.empty:
        empty = pd.DataFrame()
        return L2SemanticDiagnosticsArtifacts(
            field_summary=empty,
            depth_action_summary=empty,
            initial_depth_sample=empty,
            top_book_summary=empty,
            trade_alignment_summary=empty,
            report_md=render_l2_semantic_diagnostics_report(empty, empty, empty, empty, empty),
        )

    field_summary = _field_summary(events)
    depth = _prepare_depth_events(events)
    depth_action_summary = _depth_action_summary(depth)
    initial_depth_sample = _initial_depth_sample(depth, rows=int(initial_depth_rows))

    policy_lookup = {policy.name: policy for policy in default_l2_action_policies()}
    selected_policies = [policy_lookup[name] for name in policy_names if name in policy_lookup]
    snapshot_frames: list[pd.DataFrame] = []
    top_rows: list[dict[str, object]] = []
    for policy in selected_policies:
        snapshots = reconstruct_l2_top_book_snapshots(depth, policy=policy, tick_size=tick_size)
        if snapshots.empty:
            continue
        snapshot_frames.append(snapshots)
        for window in coalesce_windows:
            reduced = _coalesce_snapshots(snapshots, window=window)
            top_rows.append(_summarize_top_book(reduced, policy=policy.name, window=window, tick_size=tick_size))

    top_book_summary = pd.DataFrame(top_rows)
    trade_alignment_summary = pd.DataFrame()
    if snapshot_frames:
        primary_snapshots = snapshot_frames[0]
        trade_alignment_summary = _trade_alignment_summary(events, primary_snapshots)

    return L2SemanticDiagnosticsArtifacts(
        field_summary=field_summary,
        depth_action_summary=depth_action_summary,
        initial_depth_sample=initial_depth_sample,
        top_book_summary=top_book_summary,
        trade_alignment_summary=trade_alignment_summary,
        report_md=render_l2_semantic_diagnostics_report(
            field_summary,
            depth_action_summary,
            initial_depth_sample,
            top_book_summary,
            trade_alignment_summary,
        ),
    )


def reconstruct_l2_top_book_snapshots(
    depth: pd.DataFrame,
    *,
    policy: L2ActionPolicy | None = None,
    tick_size: float = 0.25,
) -> pd.DataFrame:
    if depth.empty:
        return pd.DataFrame()
    selected_policy = policy or next(
        item for item in default_l2_action_policies() if item.name == "0_insert_1_update_2_delete"
    )
    bid_book: dict[float | int, tuple[float, float]] = {}
    ask_book: dict[float | int, tuple[float, float]] = {}
    rows: list[dict[str, object]] = []

    for row in depth.itertuples(index=False):
        action = int(row.action_code)
        level = int(row.level)
        side = _side_for_policy(selected_policy, side_code=int(row.side_or_code), fallback=str(row.book_side))
        size = float(row.size)
        price = float(row.price)
        target_book = bid_book if side == "bid" else ask_book
        operation = _operation_for_action(selected_policy, action=action, size=size)
        _apply_policy_update(target_book, level=level, price=price, size=size, action=action, policy=selected_policy)

        bid_top = _best_book_level(bid_book, side="bid", book_key=selected_policy.book_key)
        ask_top = _best_book_level(ask_book, side="ask", book_key=selected_policy.book_key)
        bid_px = bid_top[0] if bid_top is not None else np.nan
        ask_px = ask_top[0] if ask_top is not None else np.nan
        spread = ask_px - bid_px if np.isfinite(bid_px) and np.isfinite(ask_px) else np.nan
        bid_monotonic = _book_side_monotonic(bid_book, side="bid", book_key=selected_policy.book_key)
        ask_monotonic = _book_side_monotonic(ask_book, side="ask", book_key=selected_policy.book_key)
        rows.append(
            {
                "source_label": getattr(row, "source_label", ""),
                "policy": selected_policy.name,
                "event_time_utc": row.event_time_utc,
                "event_time_ny": row.event_time_ny,
                "updated_side": side,
                "updated_price": price,
                "updated_size": size,
                "updated_level": level,
                "action_code": action,
                "action_operation": operation,
                "bid_px_00": bid_px,
                "ask_px_00": ask_px,
                "bid_sz_00": bid_top[1] if bid_top is not None else np.nan,
                "ask_sz_00": ask_top[1] if ask_top is not None else np.nan,
                "spread_points": spread,
                "spread_ticks": spread / tick_size if np.isfinite(spread) and tick_size > 0 else np.nan,
                "valid_top_book": bool(np.isfinite(spread)),
                "crossed_or_locked": bool(np.isfinite(spread) and spread <= 0.0),
                "off_tick_spread": bool(
                    np.isfinite(spread)
                    and tick_size > 0
                    and not np.isclose(spread / tick_size, round(spread / tick_size), atol=1e-7)
                ),
                "bid_levels_present": len(bid_book),
                "ask_levels_present": len(ask_book),
                "bid_duplicate_prices": _has_duplicate_prices(bid_book),
                "ask_duplicate_prices": _has_duplicate_prices(ask_book),
                "book_monotonic": bool(bid_monotonic and ask_monotonic),
            }
        )
    return pd.DataFrame(rows)


def write_l2_semantic_diagnostics_artifacts(
    artifacts: L2SemanticDiagnosticsArtifacts,
    out_dir: Path | str,
    *,
    prefix: str = "l2_semantic_diagnostics",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "field_summary_csv": out_path / f"{prefix}_field_summary.csv",
        "depth_action_summary_csv": out_path / f"{prefix}_depth_action_summary.csv",
        "initial_depth_sample_csv": out_path / f"{prefix}_initial_depth_sample.csv",
        "top_book_summary_csv": out_path / f"{prefix}_top_book_summary.csv",
        "trade_alignment_summary_csv": out_path / f"{prefix}_trade_alignment_summary.csv",
        "report_md": out_path / f"{prefix}_report.md",
    }
    artifacts.field_summary.to_csv(paths["field_summary_csv"], index=False)
    artifacts.depth_action_summary.to_csv(paths["depth_action_summary_csv"], index=False)
    artifacts.initial_depth_sample.to_csv(paths["initial_depth_sample_csv"], index=False)
    artifacts.top_book_summary.to_csv(paths["top_book_summary_csv"], index=False)
    artifacts.trade_alignment_summary.to_csv(paths["trade_alignment_summary_csv"], index=False)
    paths["report_md"].write_text(artifacts.report_md, encoding="utf-8")
    return paths


def render_l2_semantic_diagnostics_report(
    field_summary: pd.DataFrame,
    depth_action_summary: pd.DataFrame,
    initial_depth_sample: pd.DataFrame,
    top_book_summary: pd.DataFrame,
    trade_alignment_summary: pd.DataFrame,
) -> str:
    lines = [
        "# L2 Semantic Diagnostics",
        "",
        "This is a bounded data-decoding diagnostic. It is not a backtest, strategy scan, or signal-mining pass.",
        "",
    ]
    if field_summary.empty:
        lines.extend(["No decoded events were supplied.", ""])
        return "\n".join(lines)

    lines.extend(
        [
            "## Field Shapes",
            "",
            _markdown_table(
                field_summary,
                ["source_label", "event_type_code", "field_count", "rows", "row_pct"],
                max_rows=20,
            ),
            "",
            "## Depth Action Behavior",
            "",
            _markdown_table(
                depth_action_summary,
                [
                    "source_label",
                    "action_code",
                    "rows",
                    "zero_size_pct",
                    "size_min",
                    "size_median",
                    "size_max",
                    "level_min",
                    "level_max",
                ],
                max_rows=20,
            ),
            "",
            "## Initial Depth Sample",
            "",
            _markdown_table(
                initial_depth_sample,
                ["source_label", "event_time_ny", "book_side", "price", "size", "level", "action_code"],
                max_rows=24,
            ),
            "",
            "## Top Book Reconstruction",
            "",
            _markdown_table(
                top_book_summary,
                [
                    "policy",
                    "window",
                    "snapshots",
                    "valid_top_book_pct",
                    "crossed_or_locked_pct",
                    "median_spread_ticks",
                    "p95_spread_ticks",
                    "duplicate_price_level_pct",
                    "monotonic_violation_pct",
                ],
                max_rows=30,
            ),
            "",
            "## Type-1 Event Alignment",
            "",
            _markdown_table(
                trade_alignment_summary,
                [
                    "source_label",
                    "side_or_code",
                    "rows",
                    "zero_price_pct",
                    "at_bid_pct",
                    "at_ask_pct",
                    "inside_spread_pct",
                    "outside_spread_pct",
                    "median_size",
                ],
                max_rows=20,
            ),
            "",
            "## Current Read",
            "",
        ]
    )
    lines.extend(_current_read_lines(depth_action_summary, top_book_summary))
    lines.append("")
    return "\n".join(lines)


def _field_summary(events: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["source_label", "event_type_code", "field_count"]
    missing = [col for col in group_cols if col not in events.columns]
    if missing:
        raise ValueError(f"Decoded events are missing required column(s): {', '.join(missing)}")
    total_by_source = events.groupby("source_label", dropna=False).size().rename("source_rows")
    out = events.groupby(group_cols, dropna=False).size().rename("rows").reset_index()
    out = out.merge(total_by_source.reset_index(), on="source_label", how="left")
    out["row_pct"] = out["rows"] / out["source_rows"].replace(0, np.nan)
    return out.drop(columns=["source_rows"]).sort_values(group_cols).reset_index(drop=True)


def _depth_action_summary(depth: pd.DataFrame) -> pd.DataFrame:
    if depth.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    group_cols = ["source_label", "action_code"] if "source_label" in depth.columns else ["action_code"]
    for key, frame in depth.groupby(group_cols, dropna=False, sort=True):
        key_values = key if isinstance(key, tuple) else (key,)
        row = dict(zip(group_cols, key_values))
        row.update(
            {
                "rows": len(frame),
                "zero_size_pct": float((frame["size"] <= 0).mean()),
                "size_min": float(frame["size"].min()),
                "size_median": float(frame["size"].median()),
                "size_max": float(frame["size"].max()),
                "level_min": float(frame["level"].min()),
                "level_max": float(frame["level"].max()),
                "bid_rows": int(frame["book_side"].eq("bid").sum()),
                "ask_rows": int(frame["book_side"].eq("ask").sum()),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _initial_depth_sample(depth: pd.DataFrame, *, rows: int) -> pd.DataFrame:
    if depth.empty:
        return pd.DataFrame()
    columns = ["source_label", "event_time_ny", "book_side", "price", "size", "level", "action_code"]
    existing = [col for col in columns if col in depth.columns]
    return depth[existing].head(max(0, rows)).copy()


def _coalesce_snapshots(snapshots: pd.DataFrame, *, window: str) -> pd.DataFrame:
    if snapshots.empty or window == "event":
        return snapshots
    out = snapshots.copy()
    event_time = pd.to_datetime(out["event_time_utc"], utc=True, errors="coerce")
    out["_coalesce_bin"] = event_time.dt.floor(window)
    out = out.dropna(subset=["_coalesce_bin"])
    return out.groupby("_coalesce_bin", sort=True).tail(1).drop(columns=["_coalesce_bin"])


def _summarize_top_book(
    snapshots: pd.DataFrame,
    *,
    policy: str,
    window: str,
    tick_size: float,
) -> dict[str, object]:
    if snapshots.empty:
        return {
            "policy": policy,
            "window": window,
            "tick_size": tick_size,
            "snapshots": 0,
        }
    valid = snapshots.loc[snapshots["valid_top_book"].astype(bool)]
    duplicate_price = snapshots["bid_duplicate_prices"].astype(bool) | snapshots["ask_duplicate_prices"].astype(bool)
    return {
        "policy": policy,
        "window": window,
        "tick_size": tick_size,
        "snapshots": len(snapshots),
        "valid_top_book_pct": float(snapshots["valid_top_book"].mean()),
        "crossed_or_locked_pct": float(valid["crossed_or_locked"].mean()) if not valid.empty else 1.0,
        "off_tick_spread_pct": float(valid["off_tick_spread"].mean()) if not valid.empty else 1.0,
        "median_spread_ticks": float(valid["spread_ticks"].median()) if not valid.empty else np.nan,
        "p95_spread_ticks": float(valid["spread_ticks"].quantile(0.95)) if not valid.empty else np.nan,
        "duplicate_price_level_pct": float(duplicate_price.mean()),
        "monotonic_violation_pct": float((~snapshots["book_monotonic"].astype(bool)).mean()),
    }


def _trade_alignment_summary(events: pd.DataFrame, snapshots: pd.DataFrame) -> pd.DataFrame:
    trades = events.loc[events["event_family"].astype(str).eq("trade_or_market_event")].copy()
    if trades.empty or snapshots.empty:
        return pd.DataFrame()
    for col in ("price", "size", "side_or_code"):
        trades[col] = pd.to_numeric(trades[col], errors="coerce")
    trades = trades.dropna(subset=["event_time_utc", "price", "side_or_code"]).sort_values("event_time_utc")
    book = snapshots.loc[
        snapshots["valid_top_book"].astype(bool) & ~snapshots["crossed_or_locked"].astype(bool),
        ["event_time_utc", "bid_px_00", "ask_px_00"],
    ].copy()
    book = book.sort_values("event_time_utc")
    if trades.empty or book.empty:
        return pd.DataFrame()

    aligned = pd.merge_asof(
        trades,
        book,
        on="event_time_utc",
        direction="backward",
        tolerance=pd.Timedelta("5s"),
    )
    aligned = aligned.dropna(subset=["bid_px_00", "ask_px_00"])
    if aligned.empty:
        return pd.DataFrame()
    aligned["at_bid"] = np.isclose(aligned["price"], aligned["bid_px_00"], atol=1e-9)
    aligned["at_ask"] = np.isclose(aligned["price"], aligned["ask_px_00"], atol=1e-9)
    aligned["inside_spread"] = (aligned["price"] > aligned["bid_px_00"]) & (aligned["price"] < aligned["ask_px_00"])
    aligned["outside_spread"] = (aligned["price"] < aligned["bid_px_00"]) | (aligned["price"] > aligned["ask_px_00"])
    aligned["zero_price"] = aligned["price"].eq(0)

    rows: list[dict[str, object]] = []
    for (source_label, side_code), frame in aligned.groupby(["source_label", "side_or_code"], dropna=False, sort=True):
        rows.append(
            {
                "source_label": source_label,
                "side_or_code": side_code,
                "rows": len(frame),
                "zero_price_pct": float(frame["zero_price"].mean()),
                "at_bid_pct": float(frame["at_bid"].mean()),
                "at_ask_pct": float(frame["at_ask"].mean()),
                "inside_spread_pct": float(frame["inside_spread"].mean()),
                "outside_spread_pct": float(frame["outside_spread"].mean()),
                "median_size": float(frame["size"].median()),
            }
        )
    return pd.DataFrame(rows)


def _has_duplicate_prices(book: dict[float | int, tuple[float, float]]) -> bool:
    prices = [float(value[0]) for value in book.values() if np.isfinite(value[0])]
    return len(prices) != len(set(prices))


def _markdown_table(df: pd.DataFrame, columns: list[str], *, max_rows: int) -> str:
    if df.empty:
        return "_No rows._"
    existing = [col for col in columns if col in df.columns]
    if not existing:
        return "_No requested columns are available._"
    view = df[existing].head(max_rows)
    lines = [
        "| " + " | ".join(existing) + " |",
        "| " + " | ".join("---" for _ in existing) + " |",
    ]
    for _, row in view.iterrows():
        lines.append("| " + " | ".join(_format_cell(row[col], column=col) for col in existing) + " |")
    if len(df) > max_rows:
        lines.append(f"| ... {len(df) - max_rows} more rows |" + " |" * (len(existing) - 1))
    return "\n".join(lines)


def _format_cell(value: object, *, column: str) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        if column.endswith("_pct") and np.isfinite(value):
            return f"{value:.3%}"
        if "price" in column or "_px" in column:
            return f"{value:.2f}"
        if np.isfinite(value) and float(value).is_integer():
            return str(int(value))
        return f"{value:.4g}"
    return str(value)


def _current_read_lines(depth_action_summary: pd.DataFrame, top_book_summary: pd.DataFrame) -> list[str]:
    lines: list[str] = []
    if not depth_action_summary.empty:
        action2 = depth_action_summary.loc[pd.to_numeric(depth_action_summary["action_code"], errors="coerce").eq(2)]
        if not action2.empty and float(action2["zero_size_pct"].min()) >= 1.0:
            lines.append("- `action_code=2` behaves like a delete/clear code in this sample because every observed row has zero size.")
    if not top_book_summary.empty:
        event_rows = top_book_summary.loc[top_book_summary["window"].eq("event")]
        best = event_rows.sort_values(["crossed_or_locked_pct", "valid_top_book_pct"], ascending=[True, False]).head(1)
        if not best.empty:
            row = best.iloc[0]
            lines.append(
                "- Level-key top-book reconstruction is partially usable for diagnostics, "
                f"but not clean enough for fills yet: best event-level crossed/locked rate is {float(row['crossed_or_locked_pct']):.3%}."
            )
        duplicate = float(top_book_summary["duplicate_price_level_pct"].max())
        if duplicate > 0.05:
            lines.append(
                "- Deep level reconstruction remains suspect because duplicate adjacent price levels are common under tested policies."
            )
    if not lines:
        lines.append("- No strong semantic conclusion was produced from this bounded sample.")
    lines.append("- Do not use this data for backtest fills until the remaining crossed/locked and depth-level issues are resolved or explicitly filtered.")
    return lines
