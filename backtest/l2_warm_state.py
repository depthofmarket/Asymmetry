from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import heapq
import zipfile

import numpy as np
import pandas as pd

from backtest.l2_mbp import (
    L2ParquetSourceRef,
    L2_TIMESTAMP_FORMAT,
    STRUCTURED_L2_COLUMNS,
    parse_l2_mbp_structured_frame,
    _require_pyarrow,
)
from backtest.l2_topbook_execution import (
    L2TopBookExecutionConfig,
    _heap_best_level,
    _quote_rows_from_snapshots,
    _trade_rows_from_events,
    _usable_topbook_snapshots,
    normalize_l2_topbook_frame,
    summarize_l2_topbook_quality,
)
from backtest.tbbo_execution import aggregate_tbbo_daily_stats, aggregate_tbbo_minute_stats


@dataclass(frozen=True)
class L2WarmStateWindowConfig:
    window_start: str
    window_end: str
    warmup_start_row_group: int = 0
    max_row_groups: int | None = None
    max_rows: int | None = None
    stale_level_ttl: str | None = None
    source_timezone: str = "America/New_York"


@dataclass(frozen=True)
class L2WarmStateTopBookArtifacts:
    topbook_events: pd.DataFrame
    minute_stats: pd.DataFrame
    daily_stats: pd.DataFrame
    quality_summary: pd.DataFrame
    warm_state_summary: pd.DataFrame
    report_md: str


def build_l2_warm_state_topbook_execution_artifacts(
    source_ref: L2ParquetSourceRef,
    *,
    window_config: L2WarmStateWindowConfig,
    execution_config: L2TopBookExecutionConfig | None = None,
) -> L2WarmStateTopBookArtifacts:
    exec_cfg = execution_config or L2TopBookExecutionConfig(policy="price_key_all_actions_set")
    if exec_cfg.policy not in {"auto", "price_key_all_actions_set"}:
        raise ValueError("Warm-state structured L2 sampling currently supports `auto` or `price_key_all_actions_set` only")

    stream = _stream_structured_price_key_window(source_ref, window_config=window_config, execution_config=exec_cfg)
    snapshots = stream.snapshots
    window_events = stream.window_events

    raw_quote_cfg = replace(exec_cfg, coalesce_window="event")
    usable_for_trades = _usable_topbook_snapshots(snapshots, config=raw_quote_cfg)
    usable_for_quotes = _usable_topbook_snapshots(snapshots, config=exec_cfg)
    quote_rows = _quote_rows_from_snapshots(usable_for_quotes, config=exec_cfg)
    trade_rows = _trade_rows_from_events(window_events, usable_for_trades, config=exec_cfg)
    topbook = (
        pd.concat([quote_rows, trade_rows], ignore_index=True)
        if not quote_rows.empty or not trade_rows.empty
        else pd.DataFrame()
    )
    if not topbook.empty:
        topbook["ts_event"] = pd.to_datetime(topbook["ts_event"], utc=True, errors="coerce")
        topbook["ts_recv"] = pd.to_datetime(topbook["ts_recv"], utc=True, errors="coerce")
        topbook = topbook.dropna(subset=["ts_event", "bid_px_00", "ask_px_00"])
        topbook = topbook.sort_values(["ts_event", "action"], kind="stable").reset_index(drop=True)
        topbook = normalize_l2_topbook_frame(topbook, tick_size=exec_cfg.tick_size)

    minute_stats = aggregate_tbbo_minute_stats(topbook)
    daily_stats = aggregate_tbbo_daily_stats(minute_stats)
    quality_summary = summarize_l2_topbook_quality(window_events, topbook, config=exec_cfg)
    warm_summary = _build_warm_state_summary(
        stream,
        topbook=topbook,
        minute_stats=minute_stats,
        usable_for_quotes=usable_for_quotes,
        usable_for_trades=usable_for_trades,
        window_config=window_config,
        execution_config=exec_cfg,
        source_ref=source_ref,
    )
    return L2WarmStateTopBookArtifacts(
        topbook_events=topbook,
        minute_stats=minute_stats,
        daily_stats=daily_stats,
        quality_summary=quality_summary,
        warm_state_summary=warm_summary,
        report_md=render_l2_warm_state_topbook_report(warm_summary, quality_summary, minute_stats),
    )


def write_l2_warm_state_topbook_artifacts(
    artifacts: L2WarmStateTopBookArtifacts,
    out_dir: Path | str,
    *,
    prefix: str = "l2_warm_state_topbook",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "topbook_events_csv": out_path / f"{prefix}_events.csv",
        "minute_stats_csv": out_path / f"{prefix}_minute_stats.csv",
        "daily_stats_csv": out_path / f"{prefix}_daily_stats.csv",
        "quality_summary_csv": out_path / f"{prefix}_quality_summary.csv",
        "warm_state_summary_csv": out_path / f"{prefix}_warm_state_summary.csv",
        "report_md": out_path / f"{prefix}_report.md",
    }
    artifacts.topbook_events.to_csv(paths["topbook_events_csv"], index=False)
    artifacts.minute_stats.to_csv(paths["minute_stats_csv"], index=False)
    artifacts.daily_stats.to_csv(paths["daily_stats_csv"], index=False)
    artifacts.quality_summary.to_csv(paths["quality_summary_csv"], index=False)
    artifacts.warm_state_summary.to_csv(paths["warm_state_summary_csv"], index=False)
    paths["report_md"].write_text(artifacts.report_md, encoding="utf-8")
    return paths


@dataclass(frozen=True)
class _WarmStreamResult:
    snapshots: pd.DataFrame
    window_events: pd.DataFrame
    rows_read: int
    row_groups_processed: int
    parquet_rows: int
    parquet_row_groups: int
    depth_updates_applied: int
    window_depth_rows: int
    window_type1_rows: int
    first_event_utc: str
    last_event_utc: str
    warm_start_snapshot_emitted: bool
    warm_start_valid_top_book: bool
    max_rows_reached: bool
    max_row_groups_reached: bool


def _stream_structured_price_key_window(
    source_ref: L2ParquetSourceRef,
    *,
    window_config: L2WarmStateWindowConfig,
    execution_config: L2TopBookExecutionConfig,
) -> _WarmStreamResult:
    pq, pa = _require_pyarrow()
    parquet_file = _open_parquet_file(source_ref, pq=pq, pa=pa)
    names = set(parquet_file.schema.names)
    if not set(STRUCTURED_L2_COLUMNS).issubset(names):
        raise ValueError(
            "Warm-state streaming currently supports structured five-column L2 parquet only "
            f"({', '.join(STRUCTURED_L2_COLUMNS)}). Use the regular L2 top-book decoder for older semicolon files."
        )

    start_utc = _parse_window_time(window_config.window_start, timezone=window_config.source_timezone)
    end_utc = _parse_window_time(window_config.window_end, timezone=window_config.source_timezone)
    if end_utc <= start_utc:
        raise ValueError("window_end must be after window_start")
    start_raw = _format_l2_raw_timestamp(start_utc)
    end_raw = _format_l2_raw_timestamp(end_utc)

    bid_book: dict[float, float] = {}
    ask_book: dict[float, float] = {}
    bid_updated_at: dict[float, pd.Timestamp] = {}
    ask_updated_at: dict[float, pd.Timestamp] = {}
    bid_heap: list[float] = []
    ask_heap: list[float] = []
    snapshot_rows: list[dict[str, object]] = []
    window_event_frames: list[pd.DataFrame] = []

    rows_read = 0
    row_groups_processed = 0
    depth_updates_applied = 0
    window_depth_rows = 0
    window_type1_rows = 0
    first_event_utc = ""
    last_event_utc = ""
    warm_start_snapshot_emitted = False
    warm_start_valid_top_book = False
    max_rows_reached = False
    max_row_groups_reached = False
    stale_ttl = pd.Timedelta(window_config.stale_level_ttl) if window_config.stale_level_ttl else None
    last_expire_at: pd.Timestamp | None = None

    start_row_group = int(window_config.warmup_start_row_group)
    if start_row_group < 0:
        raise ValueError("warmup_start_row_group must be non-negative")

    for row_group_idx in range(start_row_group, parquet_file.num_row_groups):
        if window_config.max_row_groups is not None and row_groups_processed >= int(window_config.max_row_groups):
            max_row_groups_reached = True
            break
        if window_config.max_rows is not None and rows_read >= int(window_config.max_rows):
            max_rows_reached = True
            break

        table = parquet_file.read_row_group(row_group_idx, columns=list(STRUCTURED_L2_COLUMNS))
        if window_config.max_rows is not None:
            remaining = int(window_config.max_rows) - rows_read
            if remaining <= 0:
                max_rows_reached = True
                break
            if table.num_rows > remaining:
                table = table.slice(0, remaining)
                max_rows_reached = True

        frame = table.to_pandas()
        if frame.empty:
            row_groups_processed += 1
            continue

        raw_ts = frame["raw_timestamp"].astype("string")
        first_raw = str(raw_ts.iloc[0])
        last_raw = str(raw_ts.iloc[-1])
        if first_raw > end_raw:
            break

        frame = frame.loc[raw_ts.le(end_raw)].copy()
        if frame.empty:
            row_groups_processed += 1
            continue

        event_time = pd.to_datetime(
            frame["raw_timestamp"].astype("string"),
            format=L2_TIMESTAMP_FORMAT,
            utc=True,
            errors="coerce",
        )
        frame["event_time_utc_for_stream"] = event_time
        if not first_event_utc:
            clean = event_time.dropna()
            if not clean.empty:
                first_event_utc = str(clean.iloc[0])
        clean_event_time = event_time.dropna()
        if not clean_event_time.empty:
            last_event_utc = str(clean_event_time.iloc[-1])

        window_mask = event_time.ge(start_utc) & event_time.le(end_utc)
        if window_mask.any():
            decoded_window = parse_l2_mbp_structured_frame(
                frame.loc[window_mask, list(STRUCTURED_L2_COLUMNS)],
                source_path=str(source_ref.source_path),
                source_member=source_ref.zip_member or "",
                source_label=source_ref.label,
            )
            decoded_window["parquet_num_rows"] = int(parquet_file.metadata.num_rows)
            decoded_window["parquet_row_groups"] = int(parquet_file.metadata.num_row_groups)
            decoded_window["sample_start_row_group"] = start_row_group
            window_event_frames.append(decoded_window)
            window_depth_rows += int(decoded_window["event_family"].eq("depth_update").sum())
            window_type1_rows += int(decoded_window["event_family"].eq("trade_or_market_event").sum())

        depth = frame.loc[pd.to_numeric(frame["msg_type"], errors="coerce").eq(2)].copy()
        depth["event_time_utc_for_stream"] = event_time.loc[depth.index]
        depth = depth.dropna(subset=["event_time_utc_for_stream"])
        depth_to_process = depth
        if not warm_start_snapshot_emitted and event_time.ge(start_utc).any():
            pre_start_depth = depth.loc[depth["event_time_utc_for_stream"].lt(start_utc)]
            for row in pre_start_depth.itertuples(index=False):
                if _apply_structured_depth_update(
                    row,
                    bid_book,
                    ask_book,
                    bid_updated_at,
                    ask_updated_at,
                    bid_heap,
                    ask_heap,
                ) is not None:
                    depth_updates_applied += 1

            _expire_stale_levels(
                bid_book,
                ask_book,
                bid_updated_at,
                ask_updated_at,
                now=start_utc,
                ttl=stale_ttl,
            )
            warm_start_snapshot_emitted = True
            warm_start = _price_key_snapshot(
                bid_book,
                ask_book,
                bid_heap,
                ask_heap,
                event_time_utc=start_utc,
                source_label=source_ref.label,
                action_code=-1,
                action_operation="warm_state_open",
                updated_side="",
                updated_price=np.nan,
                updated_size=np.nan,
                tick_size=execution_config.tick_size,
            )
            warm_start_valid_top_book = bool(warm_start["valid_top_book"]) and not bool(warm_start["crossed_or_locked"])
            snapshot_rows.append(warm_start)
            last_expire_at = start_utc
            depth_to_process = depth.loc[depth["event_time_utc_for_stream"].ge(start_utc)]

        for row in depth_to_process.itertuples(index=False):
            event_utc = row.event_time_utc_for_stream
            if stale_ttl is not None and _should_expire(last_expire_at, event_utc):
                _expire_stale_levels(
                    bid_book,
                    ask_book,
                    bid_updated_at,
                    ask_updated_at,
                    now=event_utc,
                    ttl=stale_ttl,
                )
                last_expire_at = event_utc
            update = _apply_structured_depth_update(
                row,
                bid_book,
                ask_book,
                bid_updated_at,
                ask_updated_at,
                bid_heap,
                ask_heap,
            )
            if update is None:
                continue
            side, price, size, action_code = update
            depth_updates_applied += 1

            if start_utc <= event_utc <= end_utc:
                snapshot_rows.append(
                    _price_key_snapshot(
                        bid_book,
                        ask_book,
                        bid_heap,
                        ask_heap,
                        event_time_utc=event_utc,
                        source_label=source_ref.label,
                        action_code=action_code,
                        action_operation="delete" if action_code == 2 else "set",
                        updated_side=side,
                        updated_price=price,
                        updated_size=size,
                        tick_size=execution_config.tick_size,
                    )
                )

        rows_read += len(frame)
        row_groups_processed += 1
        if last_raw >= end_raw:
            break

    snapshots = pd.DataFrame(snapshot_rows)
    window_events = pd.concat(window_event_frames, ignore_index=True) if window_event_frames else pd.DataFrame()
    return _WarmStreamResult(
        snapshots=snapshots,
        window_events=window_events,
        rows_read=int(rows_read),
        row_groups_processed=int(row_groups_processed),
        parquet_rows=int(parquet_file.metadata.num_rows),
        parquet_row_groups=int(parquet_file.metadata.num_row_groups),
        depth_updates_applied=int(depth_updates_applied),
        window_depth_rows=int(window_depth_rows),
        window_type1_rows=int(window_type1_rows),
        first_event_utc=first_event_utc,
        last_event_utc=last_event_utc,
        warm_start_snapshot_emitted=bool(warm_start_snapshot_emitted),
        warm_start_valid_top_book=bool(warm_start_valid_top_book),
        max_rows_reached=bool(max_rows_reached),
        max_row_groups_reached=bool(max_row_groups_reached),
    )


def _apply_structured_depth_update(
    row,
    bid_book: dict[float, float],
    ask_book: dict[float, float],
    bid_updated_at: dict[float, pd.Timestamp],
    ask_updated_at: dict[float, pd.Timestamp],
    bid_heap: list[float],
    ask_heap: list[float],
) -> tuple[str, float, float, int] | None:
    side_code = int(getattr(row, "book_level"))
    price = float(getattr(row, "price"))
    size = float(getattr(row, "size"))
    if side_code not in (0, 1) or not np.isfinite(price) or price <= 0.0:
        return None
    side = "bid" if side_code == 0 else "ask"
    book = bid_book if side == "bid" else ask_book
    updated_at = bid_updated_at if side == "bid" else ask_updated_at
    heap = bid_heap if side == "bid" else ask_heap
    action_code = 2 if size <= 0.0 else 1
    if size <= 0.0:
        book.pop(price, None)
        updated_at.pop(price, None)
    else:
        book[price] = size
        updated_at[price] = row.event_time_utc_for_stream
        heapq.heappush(heap, -price if side == "bid" else price)
    return side, price, size, action_code


def _should_expire(last_expire_at: pd.Timestamp | None, now: pd.Timestamp) -> bool:
    return last_expire_at is None or (now - last_expire_at) >= pd.Timedelta("1s")


def _expire_stale_levels(
    bid_book: dict[float, float],
    ask_book: dict[float, float],
    bid_updated_at: dict[float, pd.Timestamp],
    ask_updated_at: dict[float, pd.Timestamp],
    *,
    now: pd.Timestamp,
    ttl: pd.Timedelta | None,
) -> None:
    if ttl is None:
        return
    cutoff = now - ttl
    _expire_side(bid_book, bid_updated_at, cutoff=cutoff)
    _expire_side(ask_book, ask_updated_at, cutoff=cutoff)


def _expire_side(book: dict[float, float], updated_at: dict[float, pd.Timestamp], *, cutoff: pd.Timestamp) -> None:
    stale = [price for price, ts in updated_at.items() if ts < cutoff]
    for price in stale:
        book.pop(price, None)
        updated_at.pop(price, None)


def _price_key_snapshot(
    bid_book: dict[float, float],
    ask_book: dict[float, float],
    bid_heap: list[float],
    ask_heap: list[float],
    *,
    event_time_utc,
    source_label: str,
    action_code: int,
    action_operation: str,
    updated_side: str,
    updated_price: float,
    updated_size: float,
    tick_size: float,
) -> dict[str, object]:
    bid_top = _heap_best_level(bid_book, bid_heap, side="bid")
    ask_top = _heap_best_level(ask_book, ask_heap, side="ask")
    bid_price = bid_top[0] if bid_top is not None else np.nan
    ask_price = ask_top[0] if ask_top is not None else np.nan
    spread = ask_price - bid_price if np.isfinite(bid_price) and np.isfinite(ask_price) else np.nan
    event_utc = pd.Timestamp(event_time_utc).tz_convert("UTC")
    return {
        "source_label": source_label,
        "policy": "price_key_all_actions_set",
        "event_time_utc": event_utc,
        "event_time_ny": event_utc.tz_convert("America/New_York").tz_localize(None),
        "updated_side": updated_side,
        "updated_price": updated_price,
        "updated_size": updated_size,
        "updated_level": 1,
        "action_code": action_code,
        "action_operation": action_operation,
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


def _build_warm_state_summary(
    stream: _WarmStreamResult,
    *,
    topbook: pd.DataFrame,
    minute_stats: pd.DataFrame,
    usable_for_quotes: pd.DataFrame,
    usable_for_trades: pd.DataFrame,
    window_config: L2WarmStateWindowConfig,
    execution_config: L2TopBookExecutionConfig,
    source_ref: L2ParquetSourceRef,
) -> pd.DataFrame:
    warnings: list[str] = []
    if not stream.warm_start_valid_top_book:
        warnings.append("warm start did not have a valid non-crossed top book")
    if len(usable_for_quotes) < 1_000:
        warnings.append("fewer than 1,000 usable quote snapshots")
    if len(minute_stats) < 5:
        warnings.append("fewer than 5 minute rows")
    if stream.max_rows_reached:
        warnings.append("max rows cap reached before window completion")
    if stream.max_row_groups_reached:
        warnings.append("max row-groups cap reached before window completion")

    trade_rows = topbook.loc[topbook.get("action", pd.Series(index=topbook.index, dtype="string")).astype(str).eq("T")]
    return pd.DataFrame(
        [
            {
                "source_label": source_ref.label,
                "source_path": str(source_ref.source_path),
                "source_member": source_ref.zip_member or "",
                "window_start": window_config.window_start,
                "window_end": window_config.window_end,
                "source_timezone": window_config.source_timezone,
                "warmup_start_row_group": int(window_config.warmup_start_row_group),
                "stale_level_ttl": window_config.stale_level_ttl or "",
                "row_groups_processed": stream.row_groups_processed,
                "parquet_row_groups": stream.parquet_row_groups,
                "rows_read": stream.rows_read,
                "parquet_rows": stream.parquet_rows,
                "first_event_utc": stream.first_event_utc,
                "last_event_utc": stream.last_event_utc,
                "depth_updates_applied": stream.depth_updates_applied,
                "window_depth_rows": stream.window_depth_rows,
                "window_type1_rows": stream.window_type1_rows,
                "raw_snapshot_rows": len(stream.snapshots),
                "usable_quote_snapshots_for_trades": len(usable_for_trades),
                "coalesced_quote_rows": len(usable_for_quotes),
                "topbook_rows": len(topbook),
                "trade_rows": len(trade_rows),
                "minute_rows": len(minute_stats),
                "warm_start_snapshot_emitted": stream.warm_start_snapshot_emitted,
                "warm_start_valid_top_book": stream.warm_start_valid_top_book,
                "max_rows": window_config.max_rows if window_config.max_rows is not None else "",
                "max_row_groups": window_config.max_row_groups if window_config.max_row_groups is not None else "",
                "max_rows_reached": stream.max_rows_reached,
                "max_row_groups_reached": stream.max_row_groups_reached,
                "policy": "price_key_all_actions_set",
                "coalesce_window": execution_config.coalesce_window,
                "trade_alignment_tolerance": execution_config.trade_alignment_tolerance,
                "warnings": "; ".join(warnings),
            }
        ]
    )


def render_l2_warm_state_topbook_report(
    warm_state_summary: pd.DataFrame,
    quality_summary: pd.DataFrame,
    minute_stats: pd.DataFrame,
) -> str:
    lines = [
        "# L2 Warm-State Top-Book Execution Stats",
        "",
        "This report warms a structured L2 price-key book before emitting a requested window. It does not run a strategy backtest and must not be used as signal evidence.",
        "",
    ]
    if warm_state_summary.empty:
        lines.extend(["No warm-state rows were produced.", ""])
        return "\n".join(lines)

    row = warm_state_summary.iloc[0]
    lines.extend(
        [
            "## Window",
            "",
            f"- Window NY: `{row['window_start']}` to `{row['window_end']}`",
            f"- Source: `{row['source_member'] or row['source_path']}`",
            f"- Rows read: {int(row['rows_read']):,}",
            f"- Row groups processed: {int(row['row_groups_processed']):,} / {int(row['parquet_row_groups']):,}",
            f"- Warm-start valid top book: `{bool(row['warm_start_valid_top_book'])}`",
            f"- Stale level TTL: `{row.get('stale_level_ttl', '')}`",
            f"- Raw snapshots in window: {int(row['raw_snapshot_rows']):,}",
            f"- Coalesced quote rows: {int(row['coalesced_quote_rows']):,}",
            f"- Trade rows aligned: {int(row['trade_rows']):,}",
            f"- Minute rows: {int(row['minute_rows']):,}",
            "",
            "## Guardrails",
            "",
            "- This path is for structured five-column files only.",
            "- The pre-window rows update book state but are not emitted into execution stats.",
            "- Trades are aligned to uncoalesced prior quotes to avoid 100ms coalescing lookahead.",
            "- Use the output to stress costs, spread, depth, and adverse selection. Do not mine entry filters from it.",
            "",
        ]
    )
    if str(row.get("warnings", "")):
        lines.extend(["## Warnings", "", f"- {row['warnings']}", ""])

    if not quality_summary.empty:
        q = quality_summary.iloc[0]
        lines.extend(
            [
                "## Top-Book Quality",
                "",
                f"- Effective policy: `{q['policy']}`",
                f"- Usable quote rows: {int(q['usable_quote_rows']):,}",
                f"- Usable trade rows: {int(q['usable_trade_rows']):,}",
                f"- Median retained spread: {_fmt_float(q['median_spread_ticks'])} ticks",
                f"- P95 retained spread: {_fmt_float(q['p95_spread_ticks'])} ticks",
                "",
            ]
        )

    if not minute_stats.empty:
        spreads = pd.to_numeric(minute_stats.get("median_spread_ticks"), errors="coerce").dropna()
        lines.extend(
            [
                "## Minute Snapshot",
                "",
                f"- Minute rows: {len(minute_stats):,}",
                f"- Median minute spread: {_fmt_float(spreads.median())} ticks",
                f"- P95 minute spread: {_fmt_float(spreads.quantile(0.95))} ticks",
                "",
            ]
        )
    return "\n".join(lines)


def _open_parquet_file(source_ref: L2ParquetSourceRef, *, pq, pa):
    if source_ref.zip_member is not None:
        with zipfile.ZipFile(source_ref.source_path) as zf:
            raw = zf.read(source_ref.zip_member)
        return pq.ParquetFile(pa.BufferReader(raw))
    return pq.ParquetFile(source_ref.source_path)


def _parse_window_time(value: str, *, timezone: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize(timezone)
    else:
        ts = ts.tz_convert(timezone)
    return ts.tz_convert("UTC")


def _format_l2_raw_timestamp(ts: pd.Timestamp) -> str:
    utc = pd.Timestamp(ts).tz_convert("UTC")
    return utc.strftime("%Y%m%d%H%M%S%f")


def _fmt_float(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "nan"
    if not np.isfinite(numeric):
        return "nan"
    return f"{numeric:.3f}"
