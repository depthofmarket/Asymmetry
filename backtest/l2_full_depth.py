from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.l2_book_validation import (
    L2ActionPolicy,
    _apply_policy_update,
    _book_side_monotonic,
    _operation_for_action,
    _prepare_depth_events,
    _side_for_policy,
    default_l2_action_policies,
)


@dataclass(frozen=True)
class L2FullDepthConfig:
    symbol: str = "NQ_L2"
    tick_size: float = 0.25
    policy: str = "all_actions_set"
    max_depth_levels: int = 10
    coalesce_window: str = "event"
    max_spread_ticks: float = 40.0
    trade_alignment_tolerance: str = "5s"
    include_unknown_side_trades: bool = False


@dataclass(frozen=True)
class L2FullDepthArtifacts:
    full_depth_events: pd.DataFrame
    quality_summary: pd.DataFrame
    report_md: str


def build_l2_full_depth_artifacts(
    events: pd.DataFrame,
    *,
    config: L2FullDepthConfig | None = None,
) -> L2FullDepthArtifacts:
    cfg = config or L2FullDepthConfig()
    full_depth = build_l2_full_depth_frame(events, config=cfg)
    quality = summarize_l2_full_depth_quality(events, full_depth, config=cfg)
    return L2FullDepthArtifacts(
        full_depth_events=full_depth,
        quality_summary=quality,
        report_md=render_l2_full_depth_report(quality),
    )


def build_l2_full_depth_frame(
    events: pd.DataFrame,
    *,
    config: L2FullDepthConfig | None = None,
) -> pd.DataFrame:
    cfg = config or L2FullDepthConfig()
    policy = _resolve_full_depth_policy(cfg.policy)
    if policy.book_key != "level":
        raise ValueError(
            "Full-depth replay requires an explicit level-keyed policy. "
            f"Policy `{policy.name}` uses book_key={policy.book_key!r}."
        )

    depth = _prepare_depth_events(events)
    if depth.empty:
        return pd.DataFrame()

    snapshots = reconstruct_l2_full_depth_snapshots(
        depth,
        policy=policy,
        tick_size=float(cfg.tick_size),
        max_depth_levels=int(cfg.max_depth_levels),
    )
    usable = _usable_full_depth_snapshots(snapshots, config=cfg)
    quote_rows = _quote_rows_from_full_depth_snapshots(usable, config=cfg)
    trade_rows = _trade_rows_from_full_depth_events(events, usable, config=cfg)
    out = pd.concat([quote_rows, trade_rows], ignore_index=True) if not quote_rows.empty or not trade_rows.empty else pd.DataFrame()
    if out.empty:
        return out
    out["ts_event"] = pd.to_datetime(out["ts_event"], utc=True, errors="coerce")
    out["ts_recv"] = pd.to_datetime(out["ts_recv"], utc=True, errors="coerce")
    out = out.dropna(subset=["ts_event", "bid_px_00", "ask_px_00"])
    out = out.sort_values(["ts_event", "action"], kind="stable").reset_index(drop=True)
    return normalize_l2_full_depth_frame(out, tick_size=float(cfg.tick_size), max_depth_levels=int(cfg.max_depth_levels))


def reconstruct_l2_full_depth_snapshots(
    depth: pd.DataFrame,
    *,
    policy: L2ActionPolicy,
    tick_size: float = 0.25,
    max_depth_levels: int = 10,
) -> pd.DataFrame:
    if depth.empty:
        return pd.DataFrame()
    if policy.book_key != "level":
        raise ValueError("Full-depth snapshots require a level-keyed L2 policy")

    levels = _depth_level_count(max_depth_levels)
    bid_book: dict[float | int, tuple[float, float]] = {}
    ask_book: dict[float | int, tuple[float, float]] = {}
    rows: list[dict[str, object]] = []

    for row in depth.itertuples(index=False):
        action = int(row.action_code)
        level = int(row.level)
        side = _side_for_policy(policy, side_code=int(row.side_or_code), fallback=str(row.book_side))
        size = float(row.size)
        price = float(row.price)
        target_book = bid_book if side == "bid" else ask_book
        operation = _operation_for_action(policy, action=action, size=size)
        _apply_policy_update(target_book, level=level, price=price, size=size, action=action, policy=policy)

        bid_top = bid_book.get(1)
        ask_top = ask_book.get(1)
        bid_price = bid_top[0] if bid_top is not None else np.nan
        ask_price = ask_top[0] if ask_top is not None else np.nan
        spread = ask_price - bid_price if np.isfinite(bid_price) and np.isfinite(ask_price) else np.nan
        bid_monotonic = _book_side_monotonic(bid_book, side="bid", book_key=policy.book_key)
        ask_monotonic = _book_side_monotonic(ask_book, side="ask", book_key=policy.book_key)
        record: dict[str, object] = {
            "source_label": getattr(row, "source_label", ""),
            "policy": policy.name,
            "event_time_utc": row.event_time_utc,
            "event_time_ny": row.event_time_ny,
            "updated_side": side,
            "updated_price": price,
            "updated_size": size,
            "updated_level": level,
            "action_code": action,
            "action_operation": operation,
            "spread_points": spread,
            "spread_ticks": spread / tick_size if np.isfinite(spread) and tick_size > 0 else np.nan,
            "valid_top_book": bool(np.isfinite(spread)),
            "crossed_or_locked": bool(np.isfinite(spread) and spread <= 0.0),
            "off_tick_spread": bool(
                np.isfinite(spread)
                and tick_size > 0
                and not np.isclose(spread / tick_size, round(spread / tick_size), atol=1e-7)
            ),
            "book_monotonic": bool(bid_monotonic and ask_monotonic),
            "bid_levels_present": _present_levels(bid_book, levels),
            "ask_levels_present": _present_levels(ask_book, levels),
        }
        record.update(_flatten_book_side(bid_book, side="bid", max_depth_levels=levels))
        record.update(_flatten_book_side(ask_book, side="ask", max_depth_levels=levels))
        rows.append(record)

    return pd.DataFrame(rows)


def normalize_l2_full_depth_frame(
    frame: pd.DataFrame,
    *,
    tick_size: float = 0.25,
    max_depth_levels: int = 10,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    levels = _depth_level_count(max_depth_levels)
    out = frame.copy()
    for col in ("ts_recv", "ts_event"):
        out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")
    for col in ("action", "side", "symbol", "l2_source", "policy"):
        if col in out.columns:
            out[col] = out[col].astype("string")
    numeric_cols = ["price", "size"]
    for idx in range(levels):
        numeric_cols.extend(
            [
                f"bid_px_{idx:02d}",
                f"ask_px_{idx:02d}",
                f"bid_sz_{idx:02d}",
                f"ask_sz_{idx:02d}",
            ]
        )
    for col in numeric_cols:
        if col not in out.columns:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")

    bid = out["bid_px_00"]
    ask = out["ask_px_00"]
    bid_size = out["bid_sz_00"]
    ask_size = out["ask_sz_00"]
    out["mid_price"] = (bid + ask) / 2.0
    out["spread_points"] = ask - bid
    out["spread_ticks"] = out["spread_points"] / float(tick_size)
    top_denom = bid_size + ask_size
    out["top_book_imbalance"] = np.where(top_denom > 0.0, (bid_size - ask_size) / top_denom, np.nan)

    bid_depth = sum(pd.to_numeric(out[f"bid_sz_{idx:02d}"], errors="coerce").fillna(0.0) for idx in range(levels))
    ask_depth = sum(pd.to_numeric(out[f"ask_sz_{idx:02d}"], errors="coerce").fillna(0.0) for idx in range(levels))
    total_depth = bid_depth + ask_depth
    out["bid_depth_total"] = bid_depth
    out["ask_depth_total"] = ask_depth
    out["depth_imbalance"] = np.where(total_depth > 0.0, (bid_depth - ask_depth) / total_depth, np.nan)
    out["max_depth_levels"] = levels
    out["book_depth_mode"] = "full_depth"
    out["event_time_ny"] = out["ts_event"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    out["minute"] = out["event_time_ny"].dt.floor("min")
    out["trade_date"] = out["event_time_ny"].dt.date.astype("string")
    out["hour"] = out["event_time_ny"].dt.hour
    out["minute_of_day"] = out["event_time_ny"].dt.hour * 60 + out["event_time_ny"].dt.minute
    out["rth_session"] = out["minute_of_day"].between(9 * 60 + 30, 16 * 60, inclusive="left")
    return out


def summarize_l2_full_depth_quality(
    events: pd.DataFrame,
    full_depth: pd.DataFrame,
    *,
    config: L2FullDepthConfig | None = None,
) -> pd.DataFrame:
    cfg = config or L2FullDepthConfig()
    depth = events.loc[
        events.get("event_family", pd.Series(index=events.index, dtype="string")).astype(str).eq("depth_update")
    ] if not events.empty else pd.DataFrame()
    quote_rows = full_depth.loc[full_depth.get("action", pd.Series(dtype="string")).astype(str).eq("Q")] if not full_depth.empty else pd.DataFrame()
    trade_rows = full_depth.loc[full_depth.get("action", pd.Series(dtype="string")).astype(str).eq("T")] if not full_depth.empty else pd.DataFrame()
    spread_ticks = pd.to_numeric(quote_rows.get("spread_ticks", pd.Series(dtype="float64")), errors="coerce").dropna()
    return pd.DataFrame(
        [
            {
                "symbol": cfg.symbol,
                "policy": cfg.policy,
                "max_depth_levels": int(cfg.max_depth_levels),
                "coalesce_window": cfg.coalesce_window,
                "max_spread_ticks": float(cfg.max_spread_ticks),
                "decoded_rows": int(len(events)),
                "depth_update_rows": int(len(depth)),
                "full_depth_event_rows": int(len(full_depth)),
                "quote_rows": int(len(quote_rows)),
                "trade_rows": int(len(trade_rows)),
                "median_spread_ticks": float(spread_ticks.median()) if not spread_ticks.empty else np.nan,
                "p95_spread_ticks": float(spread_ticks.quantile(0.95)) if not spread_ticks.empty else np.nan,
                "median_bid_levels_present": _safe_median(quote_rows.get("bid_levels_present", pd.Series(dtype="float64"))),
                "median_ask_levels_present": _safe_median(quote_rows.get("ask_levels_present", pd.Series(dtype="float64"))),
            }
        ]
    )


def write_l2_full_depth_artifacts(
    artifacts: L2FullDepthArtifacts,
    out_dir: Path | str,
    *,
    prefix: str = "l2_full_depth",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "full_depth_events_csv": out_path / f"{prefix}_events.csv",
        "quality_summary_csv": out_path / f"{prefix}_quality_summary.csv",
        "report_md": out_path / f"{prefix}_report.md",
    }
    artifacts.full_depth_events.to_csv(paths["full_depth_events_csv"], index=False)
    artifacts.quality_summary.to_csv(paths["quality_summary_csv"], index=False)
    paths["report_md"].write_text(artifacts.report_md, encoding="utf-8")
    return paths


def render_l2_full_depth_report(quality_summary: pd.DataFrame) -> str:
    lines = [
        "# L2 Full-Depth Replay Frame",
        "",
        "This report builds a full-depth event stream from decoded L2 depth rows. It is not an OHLCV backtest.",
        "",
    ]
    if quality_summary.empty:
        lines.extend(["No full-depth events were produced.", ""])
        return "\n".join(lines)
    row = quality_summary.iloc[0]
    lines.extend(
        [
            "## Summary",
            "",
            f"- Symbol: `{row['symbol']}`",
            f"- Policy: `{row['policy']}`",
            f"- Max depth levels: {int(row['max_depth_levels']):,}",
            f"- Decoded rows: {int(row['decoded_rows']):,}",
            f"- Depth update rows: {int(row['depth_update_rows']):,}",
            f"- Full-depth event rows: {int(row['full_depth_event_rows']):,}",
            f"- Quote rows: {int(row['quote_rows']):,}",
            f"- Trade rows: {int(row['trade_rows']):,}",
            f"- Median spread: {_fmt_float(row['median_spread_ticks'])} ticks",
            f"- Median bid levels present: {_fmt_float(row['median_bid_levels_present'])}",
            f"- Median ask levels present: {_fmt_float(row['median_ask_levels_present'])}",
            "",
            "## Guardrails",
            "",
            "- Full-depth replay requires explicit depth level and action-code semantics.",
            "- The protocol gate should point to a depth-semantics proof before using this in strategy replay.",
            "- Marketable orders may sweep displayed depth, but hidden liquidity and true queue priority are still not known.",
            "",
        ]
    )
    return "\n".join(lines)


def _usable_full_depth_snapshots(
    snapshots: pd.DataFrame,
    *,
    config: L2FullDepthConfig,
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
        & out["book_monotonic"].fillna(False).astype(bool)
        & spread_ticks.gt(0.0)
        & spread_ticks.le(float(config.max_spread_ticks))
    )
    return out.loc[mask].sort_values("event_time_utc").reset_index(drop=True)


def _quote_rows_from_full_depth_snapshots(
    snapshots: pd.DataFrame,
    *,
    config: L2FullDepthConfig,
) -> pd.DataFrame:
    if snapshots.empty:
        return pd.DataFrame()
    base = pd.DataFrame(
        {
            "ts_recv": snapshots["event_time_utc"],
            "ts_event": snapshots["event_time_utc"],
            "instrument_id": pd.NA,
            "action": "Q",
            "side": "",
            "price": np.nan,
            "size": np.nan,
            "symbol": config.symbol,
            "l2_source": "full_depth_snapshot",
            "policy": snapshots.get("policy", config.policy),
            "source_label": snapshots.get("source_label", ""),
            "bid_levels_present": snapshots.get("bid_levels_present", np.nan),
            "ask_levels_present": snapshots.get("ask_levels_present", np.nan),
        }
    )
    for col in _depth_columns(int(config.max_depth_levels)):
        base[col] = snapshots[col] if col in snapshots.columns else np.nan
    return base


def _trade_rows_from_full_depth_events(
    events: pd.DataFrame,
    snapshots: pd.DataFrame,
    *,
    config: L2FullDepthConfig,
) -> pd.DataFrame:
    if events.empty or snapshots.empty:
        return pd.DataFrame()
    trades = events.loc[events["event_family"].astype(str).eq("trade_or_market_event")].copy()
    if trades.empty:
        return pd.DataFrame()
    trades["event_time_utc"] = pd.to_datetime(trades["event_time_utc"], utc=True, errors="coerce")
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades["size"] = pd.to_numeric(trades["size"], errors="coerce")
    trades = trades.dropna(subset=["event_time_utc", "price", "size"])
    trades = trades.loc[trades["price"].gt(0.0) & trades["size"].gt(0.0)]
    if trades.empty:
        return pd.DataFrame()

    book_cols = ["event_time_utc", "policy", "source_label", "bid_levels_present", "ask_levels_present"]
    book_cols.extend(_depth_columns(int(config.max_depth_levels)))
    book = snapshots.loc[:, [col for col in book_cols if col in snapshots.columns]].copy()
    book["event_time_utc"] = pd.to_datetime(book["event_time_utc"], utc=True, errors="coerce")
    aligned = pd.merge_asof(
        trades.sort_values("event_time_utc"),
        book.dropna(subset=["event_time_utc"]).sort_values("event_time_utc"),
        on="event_time_utc",
        direction="backward",
        tolerance=pd.Timedelta(config.trade_alignment_tolerance),
    ).dropna(subset=["bid_px_00", "ask_px_00"])
    if aligned.empty:
        return pd.DataFrame()

    price = pd.to_numeric(aligned["price"], errors="coerce")
    bid = pd.to_numeric(aligned["bid_px_00"], errors="coerce")
    ask = pd.to_numeric(aligned["ask_px_00"], errors="coerce")
    side = pd.Series(np.select([price.ge(ask), price.le(bid)], ["B", "A"], default=""), index=aligned.index, dtype="string")
    aligned = aligned.assign(_inferred_side=side)
    if not config.include_unknown_side_trades:
        aligned = aligned.loc[aligned["_inferred_side"].astype(str).ne("")]
    if aligned.empty:
        return pd.DataFrame()

    out = pd.DataFrame(
        {
            "ts_recv": aligned["event_time_utc"],
            "ts_event": aligned["event_time_utc"],
            "instrument_id": pd.NA,
            "action": "T",
            "side": aligned["_inferred_side"],
            "price": aligned["price"],
            "size": aligned["size"],
            "symbol": config.symbol,
            "l2_source": "type1_trade_proxy",
            "policy": aligned.get("policy", config.policy),
            "source_label": aligned.get("source_label", ""),
            "l2_side_or_code": aligned.get("side_or_code", pd.Series(np.nan, index=aligned.index)),
            "l2_trade_side_inference": "price_vs_full_depth_topbook",
            "bid_levels_present": aligned.get("bid_levels_present", np.nan),
            "ask_levels_present": aligned.get("ask_levels_present", np.nan),
        }
    )
    for col in _depth_columns(int(config.max_depth_levels)):
        out[col] = aligned[col] if col in aligned.columns else np.nan
    return out


def _resolve_full_depth_policy(name: str) -> L2ActionPolicy:
    requested = (name or "all_actions_set").strip()
    if requested == "auto":
        requested = "all_actions_set"
    for policy in default_l2_action_policies():
        if policy.name == requested:
            return policy
    available = ", ".join(policy.name for policy in default_l2_action_policies() if policy.book_key == "level")
    raise ValueError(f"unknown full-depth L2 policy: {name}. Available level-keyed policies: {available}")


def _flatten_book_side(
    book: dict[float | int, tuple[float, float]],
    *,
    side: str,
    max_depth_levels: int,
) -> dict[str, object]:
    out: dict[str, object] = {}
    for idx in range(max_depth_levels):
        level = idx + 1
        price, size = book.get(level, (np.nan, np.nan))
        out[f"{side}_px_{idx:02d}"] = price
        out[f"{side}_sz_{idx:02d}"] = size
    return out


def _depth_columns(max_depth_levels: int) -> list[str]:
    levels = _depth_level_count(max_depth_levels)
    cols: list[str] = []
    for idx in range(levels):
        cols.extend([f"bid_px_{idx:02d}", f"ask_px_{idx:02d}", f"bid_sz_{idx:02d}", f"ask_sz_{idx:02d}"])
    return cols


def _present_levels(book: dict[float | int, tuple[float, float]], levels: int) -> int:
    count = 0
    for level in range(1, levels + 1):
        value = book.get(level)
        if value is not None and np.isfinite(value[0]) and np.isfinite(value[1]) and value[1] > 0.0:
            count += 1
    return count


def _depth_level_count(value: int) -> int:
    return max(1, min(int(value), 10))


def _safe_median(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.median()) if not clean.empty else np.nan


def _fmt_float(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "nan"
    if not np.isfinite(numeric):
        return "nan"
    return f"{numeric:.3f}"
