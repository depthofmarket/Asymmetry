from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


TRADE_LOG_COLUMNS = [
    "entry_time",
    "exit_time",
    "direction",
    "quantity",
    "entry_price",
    "exit_price",
    "pnl_points",
    "pnl",
    "duration_seconds",
    "entry_order_id",
    "exit_order_id",
    "entry_tag",
    "exit_tag",
    "signal_id",
    "setup_tag",
]
DAILY_PATH_COLUMNS = [
    "trade_date",
    "net_pnl",
    "min_intraday_pnl",
    "max_intraday_pnl",
    "trade_count",
    "source",
]


@dataclass(frozen=True)
class L2PropBridgeArtifacts:
    trade_log: pd.DataFrame
    daily_prop_path: pd.DataFrame
    summary: pd.DataFrame
    report_md: str


@dataclass(frozen=True)
class L2PropBridgePaths:
    trade_log_csv: Path
    daily_prop_path_csv: Path
    summary_csv: Path
    report_md: Path


def build_l2_trade_log_from_fills(
    fills: pd.DataFrame,
    *,
    contract_value: float = 20.0,
) -> pd.DataFrame:
    """
    Convert L2 fills into FIFO realized trades.

    Open inventory is intentionally excluded from the trade log. The prop layer
    consumes realized daily paths; open-position mark-to-market requires a
    separate policy and should not be silently invented here.
    """
    if fills.empty:
        return pd.DataFrame(columns=TRADE_LOG_COLUMNS)
    required = {"side", "fill_time", "quantity", "price"}
    missing = sorted(required.difference(fills.columns))
    if missing:
        raise ValueError(f"L2 fills are missing required column(s): {', '.join(missing)}")

    frame = fills.copy()
    frame["fill_time"] = pd.to_datetime(frame["fill_time"], utc=True, errors="coerce")
    frame["event_seq"] = pd.to_numeric(frame.get("event_seq", pd.Series(0, index=frame.index)), errors="coerce").fillna(0)
    frame["quantity"] = pd.to_numeric(frame["quantity"], errors="coerce").fillna(0.0)
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame = frame.dropna(subset=["fill_time", "price"])
    frame = frame.loc[frame["quantity"] > 0.0].sort_values(["fill_time", "event_seq"], kind="stable")

    lots: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        side = str(row.get("side", "")).strip().lower()
        sign = 1.0 if side == "buy" else -1.0 if side == "sell" else 0.0
        if sign == 0.0:
            continue
        qty = float(row["quantity"])
        price = float(row["price"])
        fill_time = pd.Timestamp(row["fill_time"])
        tag = str(row.get("tag", "") or "")
        order_id = str(row.get("order_id", "") or "")

        while qty > 1e-12 and lots and float(lots[0]["sign"]) != sign:
            lot = lots[0]
            close_qty = min(qty, float(lot["quantity"]))
            direction = "long" if float(lot["sign"]) > 0.0 else "short"
            entry_price = float(lot["price"])
            pnl_points = (price - entry_price) * close_qty if direction == "long" else (entry_price - price) * close_qty
            entry_time = pd.Timestamp(lot["fill_time"])
            trades.append(
                {
                    "entry_time": entry_time,
                    "exit_time": fill_time,
                    "direction": direction,
                    "quantity": float(close_qty),
                    "entry_price": entry_price,
                    "exit_price": price,
                    "pnl_points": float(pnl_points),
                    "pnl": float(pnl_points * float(contract_value)),
                    "duration_seconds": float((fill_time - entry_time).total_seconds()),
                    "entry_order_id": str(lot.get("order_id", "")),
                    "exit_order_id": order_id,
                    "entry_tag": str(lot.get("tag", "")),
                    "exit_tag": tag,
                    "signal_id": _signal_id_from_tags(str(lot.get("tag", "")), tag),
                    "setup_tag": _setup_tag_from_entry_tag(str(lot.get("tag", ""))),
                }
            )
            qty -= close_qty
            lot["quantity"] = float(lot["quantity"]) - close_qty
            if float(lot["quantity"]) <= 1e-12:
                lots.pop(0)

        if qty > 1e-12:
            lots.append(
                {
                    "sign": sign,
                    "quantity": qty,
                    "price": price,
                    "fill_time": fill_time,
                    "order_id": order_id,
                    "tag": tag,
                }
            )

    return pd.DataFrame(trades, columns=TRADE_LOG_COLUMNS)


def build_l2_daily_prop_path(
    trades: pd.DataFrame,
    *,
    timezone: str = "America/New_York",
) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(columns=DAILY_PATH_COLUMNS)
    if "exit_time" not in trades.columns or "pnl" not in trades.columns:
        raise ValueError("L2 trade log requires exit_time and pnl columns")
    frame = trades.copy()
    frame["exit_time"] = pd.to_datetime(frame["exit_time"], utc=True, errors="coerce")
    frame["pnl"] = pd.to_numeric(frame["pnl"], errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["exit_time"]).sort_values("exit_time", kind="stable")
    if frame.empty:
        return pd.DataFrame(columns=DAILY_PATH_COLUMNS)
    frame["trade_date"] = frame["exit_time"].dt.tz_convert(timezone).dt.strftime("%Y-%m-%d")

    rows = []
    for trade_date, group in frame.groupby("trade_date", sort=True):
        realized_curve = group["pnl"].cumsum()
        rows.append(
            {
                "trade_date": trade_date,
                "net_pnl": float(group["pnl"].sum()),
                "min_intraday_pnl": float(min(0.0, realized_curve.min())),
                "max_intraday_pnl": float(max(0.0, realized_curve.max())),
                "trade_count": int(len(group)),
                "source": "realized_l2_fills_only",
            }
        )
    return pd.DataFrame(rows, columns=DAILY_PATH_COLUMNS)


def build_l2_prop_bridge_artifacts(
    fills: pd.DataFrame,
    *,
    contract_value: float = 20.0,
    timezone: str = "America/New_York",
) -> L2PropBridgeArtifacts:
    trade_log = build_l2_trade_log_from_fills(fills, contract_value=contract_value)
    daily = build_l2_daily_prop_path(trade_log, timezone=timezone)
    summary = _build_summary(fills, trade_log, daily, contract_value=contract_value)
    return L2PropBridgeArtifacts(
        trade_log=trade_log,
        daily_prop_path=daily,
        summary=summary,
        report_md=render_l2_prop_bridge_report(summary, trade_log, daily),
    )


def write_l2_prop_bridge_artifacts(
    fills_csv: Path | str,
    out_dir: Path | str,
    *,
    prefix: str = "l2_prop_bridge",
    contract_value: float = 20.0,
    timezone: str = "America/New_York",
) -> L2PropBridgePaths:
    fills_path = Path(fills_csv)
    fills = pd.read_csv(fills_path)
    artifacts = build_l2_prop_bridge_artifacts(fills, contract_value=contract_value, timezone=timezone)
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = L2PropBridgePaths(
        trade_log_csv=out_path / f"{prefix}_trade_log.csv",
        daily_prop_path_csv=out_path / f"{prefix}_daily_prop_path.csv",
        summary_csv=out_path / f"{prefix}_summary.csv",
        report_md=out_path / f"{prefix}_report.md",
    )
    artifacts.trade_log.to_csv(paths.trade_log_csv, index=False)
    artifacts.daily_prop_path.to_csv(paths.daily_prop_path_csv, index=False)
    artifacts.summary.to_csv(paths.summary_csv, index=False)
    paths.report_md.write_text(artifacts.report_md, encoding="utf-8")
    return paths


def render_l2_prop_bridge_report(summary: pd.DataFrame, trade_log: pd.DataFrame, daily_path: pd.DataFrame) -> str:
    lines = [
        "# L2 Prop Bridge",
        "",
        "This artifact converts existing L2 replay fills into realized trades and daily PnL paths for the prop-firm evaluation layer. It does not run a backtest or prove live edge.",
        "",
    ]
    if not summary.empty:
        row = summary.iloc[0]
        lines.extend(
            [
                "## Summary",
                "",
                f"- Fills: {int(row.get('fills', 0)):,}",
                f"- Realized trades: {int(row.get('realized_trades', 0)):,}",
                f"- Trading days: {int(row.get('trading_days', 0)):,}",
                f"- Net realized PnL: ${float(row.get('net_realized_pnl', 0.0)):.2f}",
                f"- Open quantity after fills: {float(row.get('open_quantity_after_fills', 0.0)):.4g}",
                "",
            ]
        )
    lines.extend(
        [
            "## Guardrails",
            "",
            "- Daily paths are realized-fill paths only; open-position mark-to-market is not invented here.",
            "- These artifacts can feed prop-rule simulation, but prop payout probability is not live-edge proof.",
            "- Candidate promotion still requires OOS discipline and execution-realism evidence.",
            "",
        ]
    )
    if not daily_path.empty:
        lines.extend(["## Daily Path Preview", "", _frame_markdown_table(daily_path.head(12)), ""])
    if not trade_log.empty:
        lines.extend(["## Trade Preview", "", _frame_markdown_table(trade_log.head(12)), ""])
    return "\n".join(lines)


def _build_summary(
    fills: pd.DataFrame,
    trade_log: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    contract_value: float,
) -> pd.DataFrame:
    if fills.empty:
        open_qty = 0.0
    else:
        side = fills.get("side", pd.Series(dtype="string")).astype(str).str.lower()
        qty = pd.to_numeric(fills.get("quantity", pd.Series(dtype="float64")), errors="coerce").fillna(0.0)
        open_qty = float((side.map({"buy": 1.0, "sell": -1.0}).fillna(0.0) * qty).sum())
    pnl = pd.to_numeric(trade_log.get("pnl", pd.Series(dtype="float64")), errors="coerce").fillna(0.0)
    return pd.DataFrame(
        [
            {
                "fills": int(len(fills)),
                "realized_trades": int(len(trade_log)),
                "trading_days": int(len(daily)),
                "net_realized_pnl": float(pnl.sum()),
                "gross_profit": float(pnl[pnl > 0.0].sum()),
                "gross_loss": float(pnl[pnl < 0.0].sum()),
                "min_daily_realized_pnl": float(daily["net_pnl"].min()) if not daily.empty else 0.0,
                "max_daily_realized_pnl": float(daily["net_pnl"].max()) if not daily.empty else 0.0,
                "open_quantity_after_fills": open_qty,
                "contract_value": float(contract_value),
                "artifact_scope": "l2_replay_fill_bridge",
                "l2_result_is_live_edge_proof": False,
                "prop_claim_requires_prop_engine": True,
            }
        ]
    )


def _signal_id_from_tags(entry_tag: str, exit_tag: str) -> str:
    for tag in (entry_tag, exit_tag):
        parts = tag.split(":")
        if tag.startswith("bar_signal_entry:") and len(parts) >= 2:
            return parts[1]
        if tag.startswith("bar_signal_exit:") and len(parts) >= 3:
            return parts[2]
    return ""


def _setup_tag_from_entry_tag(entry_tag: str) -> str:
    parts = entry_tag.split(":")
    if entry_tag.startswith("bar_signal_entry:") and len(parts) >= 3:
        return parts[2]
    return ""


def _frame_markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_None._"
    columns = [str(col) for col in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(_fmt_cell(row[col]) for col in frame.columns) + " |")
    return "\n".join(lines)


def _fmt_cell(value: object) -> str:
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            return ""
        return f"{float(value):.6g}"
    if pd.isna(value):
        return ""
    return str(value).replace("|", "/")


__all__ = [
    "L2PropBridgeArtifacts",
    "L2PropBridgePaths",
    "build_l2_daily_prop_path",
    "build_l2_prop_bridge_artifacts",
    "build_l2_trade_log_from_fills",
    "render_l2_prop_bridge_report",
    "write_l2_prop_bridge_artifacts",
]
