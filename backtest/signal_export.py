from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.portfolio import Portfolio


DEFAULT_CONTEXT_COLUMNS = (
    "signal_type",
    "direction",
    "setup_tag",
    "hour",
    "session_bucket",
    "vwap_side",
    "open_context",
    "inside_ib",
    "cusum_event",
    "cusum_event_direction",
    "market_memory_state",
    "markov_state",
)


@dataclass(frozen=True)
class PreparedSignalExportPaths:
    signals_csv: Path
    manifest_md: Path


def load_ohlcv_data(
    filepath: str | Path,
    *,
    continuous_contract_method: str | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Load historical bars for signal export without writing side-effect caches.

    This intentionally mirrors the main backtest loader closely enough for
    point-in-time signal preparation, but it does not replay strategy execution.
    """
    path = Path(filepath)
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, low_memory=False)

    if "ts_event" in df.columns:
        df["time"] = pd.to_datetime(df["ts_event"], utc=True)
        df["time"] = df["time"].dt.tz_convert("America/New_York").dt.tz_localize(None)
        if "symbol" in df.columns:
            from main_backtest import select_continuous_outright_contract

            df = select_continuous_outright_contract(
                df,
                method=continuous_contract_method or "prior_session_volume",
            )
    else:
        df.columns = df.columns.str.lower()
        if "timestamp et" in df.columns:
            df["time"] = pd.to_datetime(df["timestamp et"])
        elif "datetime" in df.columns:
            df["time"] = pd.to_datetime(df["datetime"])
        elif "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"])

    required = ["time", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"bar data missing required columns: {missing}")

    out = df.loc[:, required].sort_values("time").reset_index(drop=True)
    if start is not None:
        out = out.loc[out["time"].ge(pd.Timestamp(start))]
    if end is not None:
        end_ts = pd.Timestamp(end)
        if end_ts == end_ts.normalize():
            end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        out = out.loc[out["time"].le(end_ts)]
    return out.reset_index(drop=True)


def build_prepared_signal_export(
    data: pd.DataFrame,
    *,
    futures_specs: dict,
    strategy_params: dict,
    starting_capital: float,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = (),
    context_cols: Iterable[str] = DEFAULT_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    params = dict(strategy_params)
    portfolio = Portfolio(
        float(starting_capital),
        futures_specs,
        max_drawdown_pct=_resolve_max_drawdown_pct(params),
    )
    engine = BacktestEngine(data, portfolio, futures_specs, params)
    pre_df = engine.preprocess()
    signal_frame = engine.build_signal_frame(pre_df)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def prepare_signal_export_frame(
    signal_frame: pd.DataFrame,
    *,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = (),
    context_cols: Iterable[str] = DEFAULT_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    if "time" not in signal_frame.columns:
        raise ValueError("signal frame must contain a time column")
    if "close" not in signal_frame.columns:
        raise ValueError("signal frame must contain a close column")
    if "signal" not in signal_frame.columns:
        raise ValueError("signal frame must contain a signal column")

    missing_features = [col for col in feature_cols if col not in signal_frame.columns]
    if missing_features:
        raise ValueError(f"feature columns not found in signal frame: {missing_features}")

    df = signal_frame.copy().reset_index(drop=True)
    df["time"] = pd.to_datetime(df["time"])
    signal = pd.to_numeric(df["signal"], errors="coerce").fillna(0.0)
    direction = pd.Series(
        np.where(signal.gt(0), "long", np.where(signal.lt(0), "short", "flat")),
        index=df.index,
    )
    signal_type = (
        df["signal_type"].fillna("").astype(str)
        if "signal_type" in df.columns
        else pd.Series("", index=df.index)
    )
    setup_tag = pd.Series(
        np.where(
            direction.eq("flat"),
            "",
            np.where(signal_type.ne(""), signal_type + "_" + direction, direction),
        ),
        index=df.index,
    )

    base_cols = [col for col in ("time", "open", "high", "low", "close", "volume") if col in df.columns]
    out = df.loc[:, base_cols].copy()
    out[signal_col_name] = signal.astype(float)
    out["signal_active"] = signal.ne(0)
    out["direction"] = direction
    out["signal_type"] = signal_type
    out["setup_tag"] = setup_tag
    out["hour"] = df["time"].dt.hour.astype(int)
    out["minute"] = df["time"].dt.minute.astype(int)
    out["session_bucket"] = _session_bucket(df["time"])

    for col in feature_cols:
        if col not in out.columns:
            out[col] = pd.to_numeric(df[col], errors="coerce")

    for col in context_cols:
        if col in out.columns:
            continue
        if col in df.columns:
            out[col] = df[col]

    return out.reset_index(drop=True)


def write_prepared_signal_export(
    frame: pd.DataFrame,
    *,
    out_dir: Path | str,
    artifact_name: str,
    metadata: dict[str, object],
) -> PreparedSignalExportPaths:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _slugify(artifact_name) or "prepared_signals"
    signals_csv = output_dir / f"{safe_name}.csv"
    manifest_md = output_dir / f"{safe_name}_manifest.md"
    frame.to_csv(signals_csv, index=False)
    _write_manifest(manifest_md, frame, metadata=metadata, signals_csv=signals_csv)
    return PreparedSignalExportPaths(signals_csv=signals_csv, manifest_md=manifest_md)


def _resolve_max_drawdown_pct(params: dict) -> float | None:
    if not params.get("enable_circuit_breaker", False):
        return None
    value = params.get("max_drawdown_pct")
    return None if value is None else float(value)


def _session_bucket(times: pd.Series) -> pd.Series:
    dt = pd.to_datetime(times)
    minutes = dt.dt.hour * 60 + dt.dt.minute
    buckets = np.select(
        [
            minutes.lt(9 * 60 + 30),
            minutes.lt(10 * 60 + 30),
            minutes.lt(12 * 60),
            minutes.lt(14 * 60),
            minutes.lt(16 * 60),
        ],
        ["pre_rth", "rth_open", "rth_morning", "rth_midday", "rth_late"],
        default="post_rth",
    )
    return pd.Series(buckets, index=times.index)


def _write_manifest(
    path: Path,
    frame: pd.DataFrame,
    *,
    metadata: dict[str, object],
    signals_csv: Path,
) -> None:
    lines = [
        "# Prepared Signal Export",
        "",
        "This artifact is for pre-candidate signal research. It contains point-in-time signal rows and context only; it does not contain executed trades.",
        "",
        "## Artifact",
        "",
        f"- Signals CSV: `{signals_csv}`",
        f"- Rows: {len(frame):,}",
        f"- Columns: {len(frame.columns):,}",
    ]
    if "time" in frame.columns and not frame.empty:
        times = pd.to_datetime(frame["time"], errors="coerce")
        lines.extend(
            [
                f"- First timestamp: {times.min()}",
                f"- Last timestamp: {times.max()}",
            ]
        )
    if "signal_active" in frame.columns:
        active = frame["signal_active"].astype(bool)
        lines.append(f"- Active signal rows: {int(active.sum()):,} ({active.mean() * 100.0:.2f}%)")
    lines.extend(["", "## Source", ""])
    for key, value in metadata.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Discipline Notes",
            "",
            "- Running this over a full historical range is a full-sample signal scan, even though it is not a trade backtest.",
            "- Do not create a new candidate unless the separate signal research report shows raw IC, signed return after costs, and period stability.",
            "- Explicit feature columns are copied only when requested; broad feature mining remains testing debt.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in str(value)).strip("_")
