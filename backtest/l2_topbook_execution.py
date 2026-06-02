from __future__ import annotations

from dataclasses import dataclass
import heapq
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.l2_book_validation import (
    L2ActionPolicy,
    _operation_for_action,
    _prepare_depth_events,
    _side_for_policy,
    default_l2_action_policies,
)
from backtest.l2_semantic_diagnostics import reconstruct_l2_top_book_snapshots
from backtest.tbbo_execution import TbboExecutionStats, aggregate_tbbo_daily_stats, aggregate_tbbo_minute_stats


@dataclass(frozen=True)
class L2TopBookExecutionConfig:
    symbol: str = "NQ_L2"
    tick_size: float = 0.25
    policy: str = "auto"
    coalesce_window: str = "100ms"
    max_spread_ticks: float = 40.0
    trade_alignment_tolerance: str = "5s"
    include_unknown_side_trades: bool = False


@dataclass(frozen=True)
class L2TopBookExecutionArtifacts:
    topbook_events: pd.DataFrame
    minute_stats: pd.DataFrame
    daily_stats: pd.DataFrame
    quality_summary: pd.DataFrame
    report_md: str


def build_l2_topbook_execution_artifacts(
    events: pd.DataFrame,
    *,
    config: L2TopBookExecutionConfig | None = None,
) -> L2TopBookExecutionArtifacts:
    cfg = config or L2TopBookExecutionConfig()
    topbook = build_l2_topbook_frame(events, config=cfg)
    minute_stats = aggregate_tbbo_minute_stats(topbook)
    daily_stats = aggregate_tbbo_daily_stats(minute_stats)
    quality_summary = summarize_l2_topbook_quality(events, topbook, config=cfg)
    return L2TopBookExecutionArtifacts(
        topbook_events=topbook,
        minute_stats=minute_stats,
        daily_stats=daily_stats,
        quality_summary=quality_summary,
        report_md=render_l2_topbook_execution_report(quality_summary, minute_stats),
    )


def build_l2_topbook_execution_stats(
    events: pd.DataFrame,
    *,
    config: L2TopBookExecutionConfig | None = None,
) -> TbboExecutionStats:
    artifacts = build_l2_topbook_execution_artifacts(events, config=config)
    return TbboExecutionStats(minute_stats=artifacts.minute_stats, daily_stats=artifacts.daily_stats)


def build_l2_topbook_frame(
    events: pd.DataFrame,
    *,
    config: L2TopBookExecutionConfig | None = None,
) -> pd.DataFrame:
    cfg = config or L2TopBookExecutionConfig()
    policy = resolve_l2_topbook_policy(events, requested_policy=cfg.policy)
    depth = _prepare_topbook_depth_events(events, policy=policy)
    if policy.book_key == "price":
        snapshots = _reconstruct_price_key_top_book_snapshots(depth, policy=policy, tick_size=cfg.tick_size)
    else:
        snapshots = reconstruct_l2_top_book_snapshots(depth, policy=policy, tick_size=cfg.tick_size)
    usable_quotes = _usable_topbook_snapshots(snapshots, config=cfg)
    quote_rows = _quote_rows_from_snapshots(usable_quotes, config=cfg)
    trade_rows = _trade_rows_from_events(events, usable_quotes, config=cfg)
    out = pd.concat([quote_rows, trade_rows], ignore_index=True) if not quote_rows.empty or not trade_rows.empty else pd.DataFrame()
    if out.empty:
        return out
    out["ts_event"] = pd.to_datetime(out["ts_event"], utc=True, errors="coerce")
    out["ts_recv"] = pd.to_datetime(out["ts_recv"], utc=True, errors="coerce")
    out = out.dropna(subset=["ts_event", "bid_px_00", "ask_px_00"])
    out = out.sort_values(["ts_event", "action"], kind="stable").reset_index(drop=True)
    return normalize_l2_topbook_frame(out, tick_size=cfg.tick_size)


def normalize_l2_topbook_frame(frame: pd.DataFrame, *, tick_size: float = 0.25) -> pd.DataFrame:
    out = frame.copy()
    for col in ("ts_recv", "ts_event"):
        out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")
    for col in ("price", "size", "bid_px_00", "ask_px_00", "bid_sz_00", "ask_sz_00"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    for col in ("action", "side", "symbol"):
        if col in out.columns:
            out[col] = out[col].astype("string")

    bid = pd.to_numeric(out["bid_px_00"], errors="coerce")
    ask = pd.to_numeric(out["ask_px_00"], errors="coerce")
    bid_size = pd.to_numeric(out["bid_sz_00"], errors="coerce")
    ask_size = pd.to_numeric(out["ask_sz_00"], errors="coerce")
    trade_price = pd.to_numeric(out.get("price", pd.Series(np.nan, index=out.index)), errors="coerce")
    trade_size = pd.to_numeric(out.get("size", pd.Series(np.nan, index=out.index)), errors="coerce")

    out["mid_price"] = (bid + ask) / 2.0
    out["spread_points"] = ask - bid
    out["spread_ticks"] = out["spread_points"] / float(tick_size)
    denom = bid_size + ask_size
    out["top_book_imbalance"] = np.where(denom > 0.0, (bid_size - ask_size) / denom, np.nan)
    out["trade_price_vs_mid"] = trade_price - out["mid_price"]
    out["is_trade"] = out["action"].astype(str).eq("T")

    side = out.get("side", pd.Series("", index=out.index)).astype(str).str.upper()
    opposite_best_size = np.select(
        [side.eq("B"), side.eq("A") | side.eq("S")],
        [ask_size, bid_size],
        default=np.nan,
    )
    same_side_best_size = np.select(
        [side.eq("B"), side.eq("A") | side.eq("S")],
        [bid_size, ask_size],
        default=np.nan,
    )
    valid_opposite_depth = np.asarray(opposite_best_size, dtype=float) > 0.0
    is_trade = out["is_trade"].fillna(False).astype(bool)
    out["opposite_best_size"] = opposite_best_size
    out["same_side_best_size"] = same_side_best_size
    out["trade_size_to_opposite_best_size"] = np.where(
        valid_opposite_depth,
        trade_size / np.asarray(opposite_best_size, dtype=float),
        np.nan,
    )
    out["top_book_depth_exhausted"] = is_trade & valid_opposite_depth & trade_size.ge(opposite_best_size)
    out["zero_impact_depth_supported"] = is_trade & valid_opposite_depth & trade_size.lt(opposite_best_size)
    out["top_book_excess_trade_size"] = np.where(
        is_trade & valid_opposite_depth,
        np.maximum(trade_size - np.asarray(opposite_best_size, dtype=float), 0.0),
        np.nan,
    )
    out["event_time_ny"] = out["ts_event"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    out["minute"] = out["event_time_ny"].dt.floor("min")
    out["trade_date"] = out["event_time_ny"].dt.date.astype("string")
    out["hour"] = out["event_time_ny"].dt.hour
    out["minute_of_day"] = out["event_time_ny"].dt.hour * 60 + out["event_time_ny"].dt.minute
    out["rth_session"] = out["minute_of_day"].between(9 * 60 + 30, 16 * 60, inclusive="left")
    return out


def summarize_l2_topbook_quality(
    events: pd.DataFrame,
    topbook: pd.DataFrame,
    *,
    config: L2TopBookExecutionConfig | None = None,
) -> pd.DataFrame:
    cfg = config or L2TopBookExecutionConfig()
    policy = resolve_l2_topbook_policy(events, requested_policy=cfg.policy)
    depth = events.loc[events.get("event_family", pd.Series(index=events.index, dtype="string")).astype(str).eq("depth_update")]
    policy_depth = _prepare_topbook_depth_events(events, policy=policy)
    type1 = events.loc[
        events.get("event_family", pd.Series(index=events.index, dtype="string")).astype(str).eq("trade_or_market_event")
    ]
    l1_quotes = events.loc[
        events.get("event_family", pd.Series(index=events.index, dtype="string")).astype(str).eq("l1_quote")
    ]
    l1_stats = events.loc[
        events.get("event_family", pd.Series(index=events.index, dtype="string")).astype(str).eq("l1_stat")
    ]
    quote_rows = topbook.loc[topbook.get("action", pd.Series(index=topbook.index, dtype="string")).astype(str).eq("Q")]
    trade_rows = topbook.loc[topbook.get("action", pd.Series(index=topbook.index, dtype="string")).astype(str).eq("T")]
    valid_spread = pd.to_numeric(quote_rows.get("spread_ticks", pd.Series(dtype="float64")), errors="coerce").dropna()
    return pd.DataFrame(
        [
            {
                "symbol": cfg.symbol,
                "requested_policy": cfg.policy,
                "policy": policy.name,
                "coalesce_window": cfg.coalesce_window,
                "max_spread_ticks": cfg.max_spread_ticks,
                "source_schemas": _value_counts_text(events.get("source_schema", pd.Series(dtype="string"))),
                "sample_start_row_group": _first_non_null(events, "sample_start_row_group"),
                "parquet_row_groups": _first_non_null(events, "parquet_row_groups"),
                "decoded_rows": int(len(events)),
                "depth_update_rows": int(len(depth)),
                "usable_depth_rows_for_policy": int(len(policy_depth)),
                "l1_quote_rows": int(len(l1_quotes)),
                "l1_trade_rows": int(len(type1)),
                "l1_stat_rows": int(len(l1_stats)),
                "type1_event_rows": int(len(type1)),
                "usable_quote_rows": int(len(quote_rows)),
                "usable_trade_rows": int(len(trade_rows)),
                "action_code_sources": _value_counts_text(depth.get("action_code_source", pd.Series(dtype="string"))),
                "type1_side_0_1_trade_rows": int(type1["side_or_code"].isin([0, 1]).sum()) if "side_or_code" in type1 else 0,
                "inferred_buy_trade_rows": int(trade_rows["side"].astype(str).eq("B").sum()) if "side" in trade_rows else 0,
                "inferred_sell_trade_rows": int(trade_rows["side"].astype(str).eq("A").sum()) if "side" in trade_rows else 0,
                "unknown_side_trade_rows": int(trade_rows["side"].astype(str).eq("").sum()) if "side" in trade_rows else 0,
                "quote_rows_per_depth_update": _safe_ratio(len(quote_rows), len(depth)),
                "trade_rows_per_type1_event": _safe_ratio(len(trade_rows), len(type1)),
                "median_spread_ticks": float(valid_spread.median()) if not valid_spread.empty else np.nan,
                "p95_spread_ticks": float(valid_spread.quantile(0.95)) if not valid_spread.empty else np.nan,
                "max_observed_spread_ticks": float(valid_spread.max()) if not valid_spread.empty else np.nan,
                "minute_rows": int(len(aggregate_tbbo_minute_stats(topbook))) if not topbook.empty else 0,
            }
        ]
    )


def write_l2_topbook_execution_artifacts(
    artifacts: L2TopBookExecutionArtifacts,
    out_dir: Path | str,
    *,
    prefix: str = "l2_topbook_execution",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "topbook_events_csv": out_path / f"{prefix}_events.csv",
        "minute_stats_csv": out_path / f"{prefix}_minute_stats.csv",
        "daily_stats_csv": out_path / f"{prefix}_daily_stats.csv",
        "quality_summary_csv": out_path / f"{prefix}_quality_summary.csv",
        "report_md": out_path / f"{prefix}_report.md",
    }
    artifacts.topbook_events.to_csv(paths["topbook_events_csv"], index=False)
    artifacts.minute_stats.to_csv(paths["minute_stats_csv"], index=False)
    artifacts.daily_stats.to_csv(paths["daily_stats_csv"], index=False)
    artifacts.quality_summary.to_csv(paths["quality_summary_csv"], index=False)
    paths["report_md"].write_text(artifacts.report_md, encoding="utf-8")
    return paths


def render_l2_topbook_execution_report(quality_summary: pd.DataFrame, minute_stats: pd.DataFrame) -> str:
    lines = [
        "# L2 Top-Book Execution Stats",
        "",
        "This report converts decoded L2 events into guarded top-of-book execution stats. It does not run a strategy backtest and it must not be used as signal evidence.",
        "",
    ]
    if quality_summary.empty:
        lines.extend(["No top-book execution stats were produced.", ""])
        return "\n".join(lines)
    row = quality_summary.iloc[0]
    lines.extend(
        [
            "## Decode Coverage",
            "",
            f"- Decoded rows: {int(row['decoded_rows']):,}",
            f"- Depth update rows: {int(row['depth_update_rows']):,}",
            f"- L1 quote rows: {int(row.get('l1_quote_rows', 0)):,}",
            f"- L1 trade rows: {int(row.get('l1_trade_rows', row['type1_event_rows'])):,}",
            f"- L1 stat rows: {int(row.get('l1_stat_rows', 0)):,}",
            f"- Usable quote rows after filters: {int(row['usable_quote_rows']):,}",
            f"- Usable trade rows after quote alignment/side inference: {int(row['usable_trade_rows']):,}",
            f"- Minute stat rows: {int(row['minute_rows']):,}",
            f"- Source schemas: {row.get('source_schemas', '')}",
            "",
            "## Top-Book Filter",
            "",
            f"- Requested policy: `{row.get('requested_policy', row['policy'])}`",
            f"- Effective policy: `{row['policy']}`",
            f"- Coalesce window: `{row['coalesce_window']}`",
            f"- Max retained spread: {float(row['max_spread_ticks']):.2f} ticks",
            f"- Median retained spread: {_fmt_float(row['median_spread_ticks'])} ticks",
            f"- P95 retained spread: {_fmt_float(row['p95_spread_ticks'])} ticks",
            "",
            "## Guardrails",
            "",
            "- This is top-of-book only; full-depth MBP-10 reconstruction is still disabled until depth-level semantics are proven.",
            "- Structured five-column files have no explicit depth level/action fields, so `auto` uses a price-keyed top-book policy and treats zero-size depth rows as deletes.",
            "- Only L1 `type_code=2` rows are treated as trade prints.",
            "- Trade side is inferred from trade price versus the aligned top of book; unknown-side trades are excluded unless explicitly requested.",
            "- L1 bid/ask ticks and stat records such as daily volume are not treated as trades.",
            "- Use these stats to stress costs, spreads, depth, and adverse selection. Do not mine entry filters from them.",
            "",
        ]
    )
    if not minute_stats.empty:
        spreads = pd.to_numeric(minute_stats.get("median_spread_ticks"), errors="coerce").dropna()
        lines.extend(
            [
                "## Minute Stats Snapshot",
                "",
                f"- Minute rows: {len(minute_stats):,}",
                f"- Trade dates: {minute_stats['trade_date'].nunique() if 'trade_date' in minute_stats else 0:,}",
                f"- Median minute spread: {_fmt_float(spreads.median())} ticks",
                f"- P95 minute spread: {_fmt_float(spreads.quantile(0.95))} ticks",
                "",
            ]
        )
    return "\n".join(lines)


def _usable_topbook_snapshots(
    snapshots: pd.DataFrame,
    *,
    config: L2TopBookExecutionConfig,
) -> pd.DataFrame:
    if snapshots.empty:
        return pd.DataFrame()
    out = snapshots.copy()
    event_time = pd.to_datetime(out["event_time_utc"], utc=True, errors="coerce")
    out["event_time_utc"] = event_time
    if config.coalesce_window and config.coalesce_window != "event":
        out["_coalesce_bin"] = event_time.dt.floor(config.coalesce_window)
        out = out.dropna(subset=["_coalesce_bin"]).groupby("_coalesce_bin", sort=True).tail(1)
        out = out.drop(columns=["_coalesce_bin"])
    spread_ticks = pd.to_numeric(out["spread_ticks"], errors="coerce")
    mask = (
        out["valid_top_book"].fillna(False).astype(bool)
        & ~out["crossed_or_locked"].fillna(True).astype(bool)
        & ~out["off_tick_spread"].fillna(True).astype(bool)
        & spread_ticks.gt(0.0)
        & spread_ticks.le(float(config.max_spread_ticks))
    )
    return out.loc[mask].sort_values("event_time_utc").reset_index(drop=True)


def _quote_rows_from_snapshots(
    snapshots: pd.DataFrame,
    *,
    config: L2TopBookExecutionConfig,
) -> pd.DataFrame:
    if snapshots.empty:
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "ts_recv": snapshots["event_time_utc"],
            "ts_event": snapshots["event_time_utc"],
            "instrument_id": pd.NA,
            "action": "Q",
            "side": "",
            "price": np.nan,
            "size": np.nan,
            "bid_px_00": snapshots["bid_px_00"],
            "ask_px_00": snapshots["ask_px_00"],
            "bid_sz_00": snapshots["bid_sz_00"],
            "ask_sz_00": snapshots["ask_sz_00"],
            "bid_ct_00": np.nan,
            "ask_ct_00": np.nan,
            "symbol": config.symbol,
            "l2_source": "quote_snapshot",
        }
    )


def resolve_l2_topbook_policy(events: pd.DataFrame, *, requested_policy: str = "auto") -> L2ActionPolicy:
    requested = (requested_policy or "auto").strip()
    if requested.lower() != "auto":
        return _policy_by_name(requested)

    policies = {policy.name: policy for policy in default_l2_action_policies()}
    depth = events.loc[
        events.get("event_family", pd.Series(index=events.index, dtype="string")).astype(str).eq("depth_update")
    ]
    if depth.empty:
        return policies["all_actions_set"]

    level = pd.to_numeric(depth.get("level", pd.Series(np.nan, index=depth.index)), errors="coerce")
    usable_level_pct = float(level.between(1, 10).mean()) if len(level) else 0.0
    if usable_level_pct >= 0.50:
        return policies["all_actions_set"]
    return policies["price_key_all_actions_set"]


def _prepare_topbook_depth_events(events: pd.DataFrame, *, policy: L2ActionPolicy) -> pd.DataFrame:
    if policy.book_key != "price":
        return _prepare_depth_events(events)
    if events.empty:
        return pd.DataFrame()

    required = [
        "event_family",
        "book_side",
        "side_or_code",
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
    for col in ("side_or_code", "price", "size", "action_code"):
        depth[col] = pd.to_numeric(depth[col], errors="coerce")
    if "level" in depth:
        depth["level"] = pd.to_numeric(depth["level"], errors="coerce")
    else:
        depth["level"] = np.nan
    depth = depth.dropna(subset=["book_side", "side_or_code", "price", "size", "action_code", "event_time_utc"])
    depth = depth.loc[depth["book_side"].isin(["bid", "ask"])]
    depth = depth.loc[depth["price"].gt(0.0)]
    depth["level"] = depth["level"].where(depth["level"].between(1, 10), 1).astype("int64")
    return depth.sort_values("event_time_utc").reset_index(drop=True)


def _reconstruct_price_key_top_book_snapshots(
    depth: pd.DataFrame,
    *,
    policy: L2ActionPolicy,
    tick_size: float,
) -> pd.DataFrame:
    if depth.empty:
        return pd.DataFrame()

    bid_book: dict[float, float] = {}
    ask_book: dict[float, float] = {}
    bid_heap: list[float] = []
    ask_heap: list[float] = []
    rows: list[dict[str, object]] = []

    for row in depth.itertuples(index=False):
        action = int(row.action_code)
        side = _side_for_policy(policy, side_code=int(row.side_or_code), fallback=str(row.book_side))
        price = float(row.price)
        size = float(row.size)
        operation = _operation_for_action(policy, action=action, size=size)
        target_book = bid_book if side == "bid" else ask_book
        target_heap = bid_heap if side == "bid" else ask_heap

        if operation in {"set", "update", "insert"}:
            target_book[price] = size
            heapq.heappush(target_heap, -price if side == "bid" else price)
        elif operation == "delete":
            target_book.pop(price, None)
        elif operation != "ignore":
            raise ValueError(f"Unsupported L2 action operation for price-keyed top book: {operation}")

        bid_top = _heap_best_level(bid_book, bid_heap, side="bid")
        ask_top = _heap_best_level(ask_book, ask_heap, side="ask")
        bid_price = bid_top[0] if bid_top is not None else np.nan
        ask_price = ask_top[0] if ask_top is not None else np.nan
        spread = ask_price - bid_price if np.isfinite(bid_price) and np.isfinite(ask_price) else np.nan
        rows.append(
            {
                "source_label": getattr(row, "source_label", ""),
                "policy": policy.name,
                "event_time_utc": row.event_time_utc,
                "event_time_ny": row.event_time_ny,
                "updated_side": side,
                "updated_price": price,
                "updated_size": size,
                "updated_level": int(row.level),
                "action_code": action,
                "action_operation": operation,
                "bid_px_00": bid_price,
                "ask_px_00": ask_price,
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
                "bid_duplicate_prices": False,
                "ask_duplicate_prices": False,
                "book_monotonic": True,
            }
        )
    return pd.DataFrame(rows)


def _heap_best_level(
    book: dict[float, float],
    heap: list[float],
    *,
    side: str,
) -> tuple[float, float] | None:
    while heap:
        price = -heap[0] if side == "bid" else heap[0]
        size = book.get(price)
        if size is not None and np.isfinite(size) and size > 0.0:
            return price, float(size)
        heapq.heappop(heap)
    return None


def _trade_rows_from_events(
    events: pd.DataFrame,
    snapshots: pd.DataFrame,
    *,
    config: L2TopBookExecutionConfig,
) -> pd.DataFrame:
    if events.empty or snapshots.empty:
        return pd.DataFrame()
    trades = events.loc[events["event_family"].astype(str).eq("trade_or_market_event")].copy()
    if trades.empty:
        return pd.DataFrame()
    for col in ("event_time_utc", "price", "size"):
        trades[col] = pd.to_numeric(trades[col], errors="coerce") if col != "event_time_utc" else pd.to_datetime(
            trades[col],
            utc=True,
            errors="coerce",
        )
    trades = trades.dropna(subset=["event_time_utc", "price", "size"])
    trades = trades.loc[trades["price"].gt(0.0) & trades["size"].gt(0.0)]
    if trades.empty:
        return pd.DataFrame()

    book = snapshots.loc[:, ["event_time_utc", "bid_px_00", "ask_px_00", "bid_sz_00", "ask_sz_00"]].copy()
    book["event_time_utc"] = pd.to_datetime(book["event_time_utc"], utc=True, errors="coerce")
    trades = trades.sort_values("event_time_utc")
    book = book.dropna(subset=["event_time_utc"]).sort_values("event_time_utc")
    aligned = pd.merge_asof(
        trades,
        book,
        on="event_time_utc",
        direction="backward",
        tolerance=pd.Timedelta(config.trade_alignment_tolerance),
    ).dropna(subset=["bid_px_00", "ask_px_00"])
    if aligned.empty:
        return pd.DataFrame()

    price = pd.to_numeric(aligned["price"], errors="coerce")
    bid = pd.to_numeric(aligned["bid_px_00"], errors="coerce")
    ask = pd.to_numeric(aligned["ask_px_00"], errors="coerce")
    side = pd.Series(
        np.select([price.ge(ask), price.le(bid)], ["B", "A"], default=""),
        index=aligned.index,
        dtype="string",
    )
    aligned = aligned.assign(_inferred_side=side)
    if not config.include_unknown_side_trades:
        aligned = aligned.loc[aligned["_inferred_side"].astype(str).ne("")]
    if aligned.empty:
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "ts_recv": aligned["event_time_utc"],
            "ts_event": aligned["event_time_utc"],
            "instrument_id": pd.NA,
            "action": "T",
            "side": aligned["_inferred_side"],
            "price": aligned["price"],
            "size": aligned["size"],
            "bid_px_00": aligned["bid_px_00"],
            "ask_px_00": aligned["ask_px_00"],
            "bid_sz_00": aligned["bid_sz_00"],
            "ask_sz_00": aligned["ask_sz_00"],
            "bid_ct_00": np.nan,
            "ask_ct_00": np.nan,
            "symbol": config.symbol,
            "l2_source": "type1_trade_proxy",
            "l2_side_or_code": aligned.get("side_or_code", pd.Series(np.nan, index=aligned.index)),
            "l2_trade_side_inference": "price_vs_topbook",
        }
    )


def _policy_by_name(name: str):
    for policy in default_l2_action_policies():
        if policy.name == name:
            return policy
    available = ", ".join(policy.name for policy in default_l2_action_policies())
    raise ValueError(f"unknown L2 action policy: {name}. Available: {available}")


def _safe_ratio(num: int | float, den: int | float) -> float:
    den = float(den)
    return float(num) / den if den else np.nan


def _value_counts_text(series: pd.Series, *, max_items: int = 20) -> str:
    if series.empty:
        return ""
    counts = series.dropna().value_counts().sort_index()
    return ";".join(f"{key}:{int(value)}" for key, value in counts.head(max_items).items())


def _first_non_null(frame: pd.DataFrame, column: str) -> object:
    if column not in frame.columns:
        return np.nan
    clean = frame[column].dropna()
    return clean.iloc[0] if not clean.empty else np.nan


def _fmt_float(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "nan"
    if not np.isfinite(numeric):
        return "nan"
    return f"{numeric:.3f}"
