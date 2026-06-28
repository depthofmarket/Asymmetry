from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backtest.motivewave_context import MotiveWaveContextConfig, build_motivewave_context


CANONICAL_EAD_COLUMNS = (
    "mw_buy_absorption",
    "mw_sell_absorption",
    "mw_buy_initiation",
    "mw_sell_initiation",
)


@dataclass(frozen=True)
class MotiveWaveEADConfig:
    """
    Native EAD candidate config.

    These defaults are bytecode-recovered, but the native formula remains a
    parity target until a MotiveWave comparison report passes.
    """

    absorption_intensity: int = 3
    volume_sensitivity: int = 10
    threshold: float = 0.6669999957084656
    mode: str = "default"

    @classmethod
    def for_mode(cls, mode: str) -> "MotiveWaveEADConfig":
        normalized = str(mode or "default").strip().lower()
        if normalized in {"default", "normal"}:
            return cls(mode="default")
        if normalized == "fast":
            return cls(absorption_intensity=6, volume_sensitivity=20, mode="fast")
        raise ValueError("EAD mode must be one of: default, fast")


@dataclass(frozen=True)
class MotiveWaveEADParityResult:
    passed: bool
    native_ead: pd.DataFrame
    motivewave_ead: pd.DataFrame
    aligned: pd.DataFrame
    mismatches: pd.DataFrame
    report_md: str


def build_trade_buckets(
    trades: pd.DataFrame,
    *,
    bucket_mode: str,
    bucket_size: float,
    time_col: str = "ts_event",
    side_col: str = "side",
    price_col: str = "price",
    size_col: str = "size",
    timezone: str = "UTC",
) -> pd.DataFrame:
    """
    Build completed tick or volume buckets from normalized trade prints.

    Volume buckets keep whole trades intact; a trade that crosses the target
    volume stays in its current bucket rather than being split.
    """

    mode = str(bucket_mode).strip().lower()
    if mode not in {"tick", "volume"}:
        raise ValueError("bucket_mode must be one of: tick, volume")
    if float(bucket_size) <= 0.0:
        raise ValueError("bucket_size must be positive")

    required = [time_col, side_col, price_col, size_col]
    missing = [col for col in required if col not in trades.columns]
    if missing:
        raise ValueError(f"trade frame missing required column(s): {', '.join(missing)}")

    work = trades.copy()
    work["_time"] = _to_utc_time(work[time_col], timezone)
    work["_price"] = pd.to_numeric(work[price_col], errors="coerce")
    work["_size"] = pd.to_numeric(work[size_col], errors="coerce")
    work["_side"] = work[side_col].astype("string").fillna("").str.strip().str.upper()
    work = work.dropna(subset=["_time", "_price", "_size"])
    work = work.loc[work["_size"].astype(float) > 0.0].copy()
    work = work.sort_values("_time", kind="stable").reset_index(drop=True)
    if work.empty:
        return _empty_bucket_frame()

    if mode == "tick":
        tick_size = int(bucket_size)
        if tick_size <= 0 or not float(bucket_size).is_integer():
            raise ValueError("tick bucket_size must be a positive integer")
        work["_bucket_id"] = np.arange(len(work), dtype="int64") // tick_size
    else:
        cumulative_before = work["_size"].astype(float).cumsum() - work["_size"].astype(float)
        work["_bucket_id"] = np.floor(cumulative_before / float(bucket_size)).astype("int64")

    work["_buy_volume"] = np.where(_is_buy_side(work["_side"]), work["_size"].astype(float), 0.0)
    work["_sell_volume"] = np.where(_is_sell_side(work["_side"]), work["_size"].astype(float), 0.0)
    work["_buy_count"] = _is_buy_side(work["_side"]).astype("int64")
    work["_sell_count"] = _is_sell_side(work["_side"]).astype("int64")

    grouped = work.groupby("_bucket_id", sort=True)
    out = grouped.agg(
        time=("_time", "last"),
        bucket_start_time=("_time", "first"),
        bucket_end_time=("_time", "last"),
        trade_count=("_time", "size"),
        volume=("_size", "sum"),
        buy_volume=("_buy_volume", "sum"),
        sell_volume=("_sell_volume", "sum"),
        buy_count=("_buy_count", "sum"),
        sell_count=("_sell_count", "sum"),
        open=("_price", "first"),
        high=("_price", "max"),
        low=("_price", "min"),
        close=("_price", "last"),
    ).reset_index()
    out = out.rename(columns={"_bucket_id": "bucket_id"})
    out["bucket_mode"] = mode
    out["bucket_size"] = float(bucket_size)
    out["delta_volume"] = out["buy_volume"].astype(float) - out["sell_volume"].astype(float)
    out["delta_share"] = np.where(
        out["volume"].astype(float) > 0.0,
        out["delta_volume"].astype(float) / out["volume"].astype(float),
        np.nan,
    )
    return out


def compute_native_ead(
    buckets: pd.DataFrame,
    *,
    config: MotiveWaveEADConfig | None = None,
) -> pd.DataFrame:
    """
    Compute native EAD candidate marks from completed trade buckets.

    The returned columns use MotiveWave-context names so the parity gate can
    compare booleans directly. Passing parity is required before replay use.
    """

    cfg = config or MotiveWaveEADConfig()
    _validate_ead_config(cfg)
    required = ["time", "open", "high", "low", "close", "volume", "buy_volume", "sell_volume"]
    missing = [col for col in required if col not in buckets.columns]
    if missing:
        raise ValueError(f"bucket frame missing required column(s): {', '.join(missing)}")

    out = buckets.copy()
    out["time"] = _to_utc_time(out["time"], "UTC")
    for col in ("open", "high", "low", "close", "volume", "buy_volume", "sell_volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=required).sort_values("time", kind="stable").reset_index(drop=True)
    if out.empty:
        return _empty_ead_frame()

    volume = out["volume"].astype(float)
    buy_volume = out["buy_volume"].astype(float)
    sell_volume = out["sell_volume"].astype(float)
    buy_share = buy_volume / volume.replace(0.0, np.nan)
    sell_share = sell_volume / volume.replace(0.0, np.nan)
    price_change = out["close"].astype(float) - out["open"].astype(float)
    volume_baseline = volume.ewm(span=int(cfg.volume_sensitivity), adjust=False, min_periods=1).mean()
    buy_pressure_ema = buy_share.fillna(0.0).ewm(
        span=int(cfg.absorption_intensity),
        adjust=False,
        min_periods=1,
    ).mean()
    sell_pressure_ema = sell_share.fillna(0.0).ewm(
        span=int(cfg.absorption_intensity),
        adjust=False,
        min_periods=1,
    ).mean()

    active_volume = volume.ge(volume_baseline * float(cfg.threshold))
    buy_extreme = active_volume & buy_share.ge(float(cfg.threshold)) & buy_volume.gt(sell_volume)
    sell_extreme = active_volume & sell_share.ge(float(cfg.threshold)) & sell_volume.gt(buy_volume)

    out["ead_mode"] = cfg.mode
    out["ead_absorption_intensity"] = int(cfg.absorption_intensity)
    out["ead_volume_sensitivity"] = int(cfg.volume_sensitivity)
    out["ead_threshold"] = float(cfg.threshold)
    out["ead_volume_baseline"] = volume_baseline
    out["ead_buy_pressure_ema"] = buy_pressure_ema
    out["ead_sell_pressure_ema"] = sell_pressure_ema
    out["mw_buy_absorption"] = buy_extreme & price_change.le(0.0)
    out["mw_sell_absorption"] = sell_extreme & price_change.ge(0.0)
    out["mw_buy_initiation"] = buy_extreme & price_change.gt(0.0)
    out["mw_sell_initiation"] = sell_extreme & price_change.lt(0.0)
    out["mw_absorption_long_trigger"] = out["mw_sell_absorption"].fillna(False).astype(bool)
    out["mw_absorption_short_trigger"] = out["mw_buy_absorption"].fillna(False).astype(bool)
    out["mw_initiative_long_trigger"] = out["mw_buy_initiation"].fillna(False).astype(bool)
    out["mw_initiative_short_trigger"] = out["mw_sell_initiation"].fillna(False).astype(bool)
    out["mw_any_long_trigger"] = out["mw_absorption_long_trigger"] | out["mw_initiative_long_trigger"]
    out["mw_any_short_trigger"] = out["mw_absorption_short_trigger"] | out["mw_initiative_short_trigger"]
    out["ead_buy_absorption_price"] = np.where(out["mw_buy_absorption"], out["high"], np.nan)
    out["ead_sell_absorption_price"] = np.where(out["mw_sell_absorption"], out["low"], np.nan)
    out["ead_buy_initiation_price"] = np.where(out["mw_buy_initiation"], out["low"], np.nan)
    out["ead_sell_initiation_price"] = np.where(out["mw_sell_initiation"], out["high"], np.nan)
    for col in CANONICAL_EAD_COLUMNS:
        out[col] = out[col].fillna(False).astype(bool)
    return out


def build_motivewave_ead_parity(
    trades: pd.DataFrame,
    motivewave_export: pd.DataFrame | Path | str,
    *,
    bucket_mode: str,
    bucket_size: float,
    ead_config: MotiveWaveEADConfig | None = None,
    trade_time_col: str = "ts_event",
    trade_timezone: str = "UTC",
    motivewave_time_col: str = "time",
    motivewave_timezone: str = "America/New_York",
    motivewave_availability_lag: str = "0min",
    allow_result_columns: bool = False,
) -> MotiveWaveEADParityResult:
    buckets = build_trade_buckets(
        trades,
        bucket_mode=bucket_mode,
        bucket_size=bucket_size,
        time_col=trade_time_col,
        timezone=trade_timezone,
    )
    native = compute_native_ead(buckets, config=ead_config)
    motivewave_context = build_motivewave_context(
        motivewave_export,
        config=MotiveWaveContextConfig(
            time_col=motivewave_time_col,
            timezone=motivewave_timezone,
            availability_lag=motivewave_availability_lag,
            allow_result_columns=allow_result_columns,
        ),
    )
    return compare_native_ead_to_motivewave(
        native,
        motivewave_context.frame,
        config=ead_config or MotiveWaveEADConfig(),
        bucket_mode=bucket_mode,
        bucket_size=bucket_size,
    )


def compare_native_ead_to_motivewave(
    native_ead: pd.DataFrame,
    motivewave_ead: pd.DataFrame,
    *,
    config: MotiveWaveEADConfig | None = None,
    bucket_mode: str = "",
    bucket_size: float | int | str = "",
) -> MotiveWaveEADParityResult:
    cfg = config or MotiveWaveEADConfig()
    native = _canonical_ead_frame(native_ead, prefix="native")
    motivewave = _canonical_ead_frame(motivewave_ead, prefix="motivewave")

    native_duplicate_count = int(native["time"].duplicated().sum()) if "time" in native.columns else 0
    motivewave_duplicate_count = int(motivewave["time"].duplicated().sum()) if "time" in motivewave.columns else 0
    native = native.drop_duplicates(subset=["time"], keep="first")
    motivewave = motivewave.drop_duplicates(subset=["time"], keep="first")

    aligned = native.merge(motivewave, on="time", how="outer", indicator=True).sort_values("time", kind="stable")
    aligned["alignment_status"] = aligned["_merge"].astype("string")
    mismatch_cols: list[str] = []
    for col in CANONICAL_EAD_COLUMNS:
        native_col = f"native_{col}"
        motivewave_col = f"motivewave_{col}"
        mismatch_col = f"mismatch_{col}"
        both = aligned["_merge"].eq("both")
        aligned[mismatch_col] = both & (
            aligned[native_col].fillna(False).astype(bool) != aligned[motivewave_col].fillna(False).astype(bool)
        )
        mismatch_cols.append(mismatch_col)
    aligned["ead_bool_mismatch"] = aligned[mismatch_cols].any(axis=1) if mismatch_cols else False
    aligned["parity_failure"] = aligned["_merge"].ne("both") | aligned["ead_bool_mismatch"]
    mismatches = aligned.loc[aligned["parity_failure"]].drop(columns=["_merge"]).reset_index(drop=True)
    aligned = aligned.drop(columns=["_merge"]).reset_index(drop=True)

    passed = (
        native_duplicate_count == 0
        and motivewave_duplicate_count == 0
        and int(aligned["parity_failure"].sum()) == 0
    )
    report = render_motivewave_ead_parity_report(
        passed=passed,
        native_rows=len(native),
        motivewave_rows=len(motivewave),
        aligned_rows=len(aligned),
        mismatch_rows=len(mismatches),
        native_duplicate_count=native_duplicate_count,
        motivewave_duplicate_count=motivewave_duplicate_count,
        config=cfg,
        bucket_mode=bucket_mode,
        bucket_size=bucket_size,
    )
    return MotiveWaveEADParityResult(
        passed=passed,
        native_ead=native_ead,
        motivewave_ead=motivewave_ead,
        aligned=aligned,
        mismatches=mismatches,
        report_md=report,
    )


def write_motivewave_ead_parity_result(
    result: MotiveWaveEADParityResult,
    out_dir: Path | str,
    *,
    prefix: str = "motivewave_ead_parity",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "native_ead_csv": out_path / f"{prefix}_native_ead.csv",
        "motivewave_ead_csv": out_path / f"{prefix}_motivewave_ead.csv",
        "aligned_csv": out_path / f"{prefix}_aligned.csv",
        "mismatches_csv": out_path / f"{prefix}_mismatches.csv",
        "report_md": out_path / f"{prefix}_report.md",
    }
    result.native_ead.to_csv(paths["native_ead_csv"], index=False)
    result.motivewave_ead.to_csv(paths["motivewave_ead_csv"], index=False)
    result.aligned.to_csv(paths["aligned_csv"], index=False)
    result.mismatches.to_csv(paths["mismatches_csv"], index=False)
    paths["report_md"].write_text(result.report_md, encoding="utf-8")
    return paths


def render_motivewave_ead_parity_report(
    *,
    passed: bool,
    native_rows: int,
    motivewave_rows: int,
    aligned_rows: int,
    mismatch_rows: int,
    native_duplicate_count: int,
    motivewave_duplicate_count: int,
    config: MotiveWaveEADConfig,
    bucket_mode: str,
    bucket_size: float | int | str,
) -> str:
    lines = [
        "# MotiveWave EAD Parity Gate",
        "",
        f"Status: {'PASS' if passed else 'FAIL'}",
        "",
        "This report compares native EAD candidate booleans against exported MotiveWave EAD booleans. It is a parity gate, not a backtest, not an edge claim, and not permission to promote a strategy.",
        "",
        "## Config",
        "",
        f"- Bucket mode: `{bucket_mode}`",
        f"- Bucket size: `{bucket_size}`",
        f"- EAD mode: `{config.mode}`",
        f"- Absorption intensity: {int(config.absorption_intensity)}",
        f"- Volume sensitivity: {int(config.volume_sensitivity)}",
        f"- Threshold: {float(config.threshold):.15g}",
        "",
        "## Coverage",
        "",
        f"- Native rows: {native_rows:,}",
        f"- MotiveWave rows: {motivewave_rows:,}",
        f"- Aligned rows: {aligned_rows:,}",
        f"- Mismatch rows: {mismatch_rows:,}",
        f"- Native duplicate timestamps: {native_duplicate_count:,}",
        f"- MotiveWave duplicate timestamps: {motivewave_duplicate_count:,}",
        "",
        "## Gate Rule",
        "",
        "- PASS requires exact timestamp alignment and exact boolean equality for buy/sell absorption and buy/sell initiation.",
        "- Any missing bucket, duplicate timestamp, or boolean mismatch is a FAIL.",
        "- Native EAD output must not be used as `trigger_context_csv` unless this report passes on the intended sample.",
        "",
    ]
    return "\n".join(lines)


def read_frame(path: Path | str, *, max_rows: int | None = None) -> pd.DataFrame:
    frame_path = Path(path)
    if frame_path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(frame_path)
        return frame.head(int(max_rows)) if max_rows is not None else frame
    return pd.read_csv(frame_path, nrows=max_rows, low_memory=False)


def _canonical_ead_frame(frame: pd.DataFrame, *, prefix: str) -> pd.DataFrame:
    if "time" not in frame.columns:
        raise ValueError(f"{prefix} EAD frame missing required column: time")
    out = pd.DataFrame({"time": _to_utc_time(frame["time"], "UTC")})
    for col in CANONICAL_EAD_COLUMNS:
        if col not in frame.columns:
            raise ValueError(f"{prefix} EAD frame missing required column: {col}")
        out[f"{prefix}_{col}"] = frame[col].fillna(False).astype(bool)
    out = out.dropna(subset=["time"]).sort_values("time", kind="stable").reset_index(drop=True)
    return out


def _empty_bucket_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "bucket_id",
            "time",
            "bucket_start_time",
            "bucket_end_time",
            "trade_count",
            "volume",
            "buy_volume",
            "sell_volume",
            "buy_count",
            "sell_count",
            "open",
            "high",
            "low",
            "close",
            "bucket_mode",
            "bucket_size",
            "delta_volume",
            "delta_share",
        ]
    )


def _empty_ead_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["time", *CANONICAL_EAD_COLUMNS])


def _validate_ead_config(config: MotiveWaveEADConfig) -> None:
    if int(config.absorption_intensity) <= 0:
        raise ValueError("absorption_intensity must be positive")
    if int(config.volume_sensitivity) <= 0:
        raise ValueError("volume_sensitivity must be positive")
    if not 0.0 < float(config.threshold) <= 1.0:
        raise ValueError("threshold must be in (0, 1]")


def _to_utc_time(values: pd.Series, timezone: str) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    if parsed.empty:
        return parsed
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(str(timezone), ambiguous="NaT", nonexistent="shift_forward")
    return parsed.dt.tz_convert("UTC")


def _is_buy_side(side: pd.Series) -> pd.Series:
    return side.astype("string").fillna("").str.upper().isin({"B", "BUY", "ASK", "A_BUY", "AGGRESSIVE_BUY"})


def _is_sell_side(side: pd.Series) -> pd.Series:
    return side.astype("string").fillna("").str.upper().isin({"A", "SELL", "BID", "A_SELL", "AGGRESSIVE_SELL"})


__all__ = [
    "CANONICAL_EAD_COLUMNS",
    "MotiveWaveEADConfig",
    "MotiveWaveEADParityResult",
    "build_motivewave_ead_parity",
    "build_trade_buckets",
    "compare_native_ead_to_motivewave",
    "compute_native_ead",
    "read_frame",
    "render_motivewave_ead_parity_report",
    "write_motivewave_ead_parity_result",
]
