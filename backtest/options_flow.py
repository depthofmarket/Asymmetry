from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Any, Iterable
import zipfile

import numpy as np
import pandas as pd

from backtest.options_ingestion import _read_csv_member, parse_nq_option_symbol, schema_members


STAT_SETTLEMENT_PRICE = 3
STAT_CLEARED_VOLUME = 6
STAT_OPEN_INTEREST = 9
STAT_VOLATILITY = 14
STAT_DELTA = 15


STAT_TYPE_COLUMNS = {
    STAT_SETTLEMENT_PRICE: "settlement_price",
    STAT_CLEARED_VOLUME: "cleared_volume",
    STAT_OPEN_INTEREST: "open_interest",
    STAT_VOLATILITY: "official_iv",
    STAT_DELTA: "official_delta",
}


OPTIONS_DTE_BUCKETS: tuple[tuple[str, float | None, float | None, int], ...] = (
    ("0dte", 0.0, 1.0, 0),
    ("1_7dte", 1.0, 8.0, 1),
    ("8_30dte", 8.0, 31.0, 2),
    ("31_120dte", 31.0, 121.0, 3),
    ("all", None, None, 99),
)


@dataclass(frozen=True)
class OptionsFlowBuildConfig:
    contract_multiplier: float = 20.0
    risk_free_rate: float = 0.0
    min_dte: int = 0
    max_dte: int = 120
    strike_window_points: float = 600.0
    min_open_interest: int = 1
    iv_floor: float = 0.01
    iv_cap: float = 5.0
    gex_neutral_threshold: float = 0.0
    put_gamma_sign: float = -1.0


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black76_price(
    futures_price: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    option_type: str,
    risk_free_rate: float = 0.0,
) -> float:
    f = float(futures_price)
    k = float(strike)
    t = max(float(time_to_expiry_years), 0.0)
    sigma = max(float(volatility), 0.0)
    if f <= 0 or k <= 0 or t <= 0 or sigma <= 0:
        intrinsic = max(f - k, 0.0) if str(option_type).upper() == "C" else max(k - f, 0.0)
        return intrinsic * math.exp(-float(risk_free_rate) * t)

    sqrt_t = math.sqrt(t)
    d1 = (math.log(f / k) + 0.5 * sigma * sigma * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    discount = math.exp(-float(risk_free_rate) * t)
    if str(option_type).upper() == "C":
        return discount * (f * _norm_cdf(d1) - k * _norm_cdf(d2))
    return discount * (k * _norm_cdf(-d2) - f * _norm_cdf(-d1))


def black76_greeks(
    futures_price: float,
    strike: float,
    time_to_expiry_years: float,
    volatility: float,
    option_type: str,
    risk_free_rate: float = 0.0,
) -> dict[str, float]:
    f = float(futures_price)
    k = float(strike)
    t = max(float(time_to_expiry_years), 0.0)
    sigma = max(float(volatility), 0.0)
    if f <= 0 or k <= 0 or t <= 0 or sigma <= 0:
        if str(option_type).upper() == "C":
            delta = 1.0 if f > k else 0.0
        else:
            delta = -1.0 if f < k else 0.0
        return {"delta": delta, "gamma": 0.0, "vega": 0.0, "theta": np.nan}

    sqrt_t = math.sqrt(t)
    discount = math.exp(-float(risk_free_rate) * t)
    d1 = (math.log(f / k) + 0.5 * sigma * sigma * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    pdf = _norm_pdf(d1)
    if str(option_type).upper() == "C":
        delta = discount * _norm_cdf(d1)
        theta = (
            -discount * f * pdf * sigma / (2.0 * sqrt_t)
            + float(risk_free_rate) * discount * (f * _norm_cdf(d1) - k * _norm_cdf(d2))
        )
    else:
        delta = -discount * _norm_cdf(-d1)
        theta = (
            -discount * f * pdf * sigma / (2.0 * sqrt_t)
            + float(risk_free_rate) * discount * (k * _norm_cdf(-d2) - f * _norm_cdf(-d1))
        )
    gamma = discount * pdf / (f * sigma * sqrt_t)
    vega = discount * f * pdf * sqrt_t
    return {"delta": float(delta), "gamma": float(gamma), "vega": float(vega), "theta": float(theta / 365.25)}


def implied_volatility_black76(
    option_price: float,
    futures_price: float,
    strike: float,
    time_to_expiry_years: float,
    option_type: str,
    risk_free_rate: float = 0.0,
    *,
    min_vol: float = 0.001,
    max_vol: float = 5.0,
    tolerance: float = 1e-5,
    max_iter: int = 80,
) -> float:
    price = float(option_price)
    f = float(futures_price)
    k = float(strike)
    t = float(time_to_expiry_years)
    if price <= 0 or f <= 0 or k <= 0 or t <= 0:
        return np.nan

    intrinsic = black76_price(f, k, t, min_vol, option_type, risk_free_rate)
    upper = black76_price(f, k, t, max_vol, option_type, risk_free_rate)
    if price < intrinsic - tolerance or price > upper + tolerance:
        return np.nan

    lo = float(min_vol)
    hi = float(max_vol)
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        mid_price = black76_price(f, k, t, mid, option_type, risk_free_rate)
        if abs(mid_price - price) <= tolerance:
            return mid
        if mid_price < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _normalize_feature_time(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, utc=True, errors="coerce")
    return dt.dt.tz_convert("America/New_York").dt.tz_localize(None)


def _naive_datetime_ns(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce")
    if getattr(dt.dtype, "tz", None) is not None:
        dt = dt.dt.tz_convert("America/New_York").dt.tz_localize(None)
    return dt.astype("datetime64[ns]")


def _filtered_statistics_members(
    source: Path | str,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    max_files: int | None = None,
) -> list[str]:
    source_path = Path(source)
    start_date = pd.Timestamp(start).date() if start is not None else None
    end_date = pd.Timestamp(end).date() if end is not None else None
    members = schema_members(source_path, "statistics")
    filtered_members: list[str] = []
    for member in members:
        date = _date_from_member(member)
        if date is not None:
            if start_date is not None and date < start_date:
                continue
            if end_date is not None and date > end_date:
                continue
        filtered_members.append(member)
        if max_files is not None and len(filtered_members) >= int(max_files):
            break
    return filtered_members


def _filtered_definition_members(
    source: Path | str,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    max_files: int | None = None,
) -> list[str]:
    source_path = Path(source)
    start_date = pd.Timestamp(start).date() if start is not None else None
    end_date = pd.Timestamp(end).date() if end is not None else None
    members = schema_members(source_path, "definition")
    filtered_members: list[str] = []
    for member in members:
        date = _date_from_member(member)
        if date is not None:
            if start_date is not None and date < start_date:
                continue
            if end_date is not None and date > end_date:
                continue
        filtered_members.append(member)
        if max_files is not None and len(filtered_members) >= int(max_files):
            break
    return filtered_members


def _definition_member_by_date(source: Path | str) -> dict[Any, str]:
    return {
        _date_from_member(member): member
        for member in schema_members(Path(source), "definition")
        if _date_from_member(member) is not None
    }


def _read_definition_frame(
    source: Path | str,
    member: str,
    *,
    zip_file: zipfile.ZipFile | None = None,
) -> pd.DataFrame:
    source_path = Path(source)
    usecols = [
        "ts_event",
        "instrument_id",
        "raw_symbol",
        "symbol",
        "instrument_class",
        "underlying",
        "strike_price",
        "expiration",
        "activation",
    ]
    frame = _read_csv_member(
        source_path,
        member,
        usecols=lambda col: col in usecols,
        zip_file=zip_file,
    )
    frame["source_member"] = member
    return normalize_definition_frame(frame)


def iter_statistics_frames(
    source: Path | str,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    max_files: int | None = None,
    rows_per_file: int | None = None,
) -> Iterable[pd.DataFrame]:
    source_path = Path(source)
    filtered_members = _filtered_statistics_members(
        source_path,
        start=start,
        end=end,
        max_files=max_files,
    )

    usecols = [
        "ts_recv",
        "ts_event",
        "instrument_id",
        "ts_ref",
        "price",
        "quantity",
        "stat_type",
        "update_action",
        "symbol",
    ]
    if source_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(source_path) as zf:
            for member in filtered_members:
                frame = _read_csv_member(
                    source_path,
                    member,
                    nrows=rows_per_file,
                    usecols=lambda col: col in usecols,
                    zip_file=zf,
                )
                frame["source_member"] = member
                yield normalize_statistics_frame(frame)
        return

    for member in filtered_members:
        frame = _read_csv_member(
            source_path,
            member,
            nrows=rows_per_file,
            usecols=lambda col: col in usecols,
        )
        frame["source_member"] = member
        yield normalize_statistics_frame(frame)


def _date_from_member(member: str) -> Any:
    name = Path(str(member)).name
    match = re.search(r"(20\d{6})", name)
    if match:
        return pd.Timestamp(match.group(1)).date()
    return None


def normalize_statistics_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("ts_recv", "ts_event", "ts_ref"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")
    for col in ("instrument_id", "price", "quantity", "stat_type", "update_action"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "symbol" in out.columns:
        out["symbol"] = out["symbol"].astype(str)
    return out


def normalize_definition_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("ts_event", "expiration", "activation"):
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], utc=True, errors="coerce")
    for col in ("instrument_id", "strike_price"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "symbol" in out.columns:
        out["symbol"] = out["symbol"].astype(str)
    if "raw_symbol" in out.columns:
        out["raw_symbol"] = out["raw_symbol"].astype(str)
    if "instrument_class" in out.columns:
        out["instrument_class"] = out["instrument_class"].astype(str).str.upper().str[0]
    return out


def statistics_snapshot(statistics: pd.DataFrame) -> pd.DataFrame:
    if statistics.empty:
        return pd.DataFrame()
    stats = normalize_statistics_frame(statistics)
    stats = stats.loc[stats["stat_type"].isin(STAT_TYPE_COLUMNS)].copy()
    stats = stats.loc[~stats.get("update_action", pd.Series(1, index=stats.index)).eq(2)].copy()
    if stats.empty:
        return pd.DataFrame()

    source_date = (
        stats["source_member"].map(_date_from_member)
        if "source_member" in stats.columns
        else pd.Series(pd.NaT, index=stats.index)
    )
    ts_ref_date = pd.to_datetime(stats["ts_ref"], utc=True, errors="coerce").dt.date
    ts_event_date = pd.to_datetime(stats["ts_event"], utc=True, errors="coerce").dt.date
    # GLBX option OI/cleared-volume records can omit ts_ref. Use the split-file
    # date as the point-in-time snapshot date so settlement/OI/volume published
    # in the same daily member join into one feature row.
    trade_date = source_date.where(pd.notna(source_date), ts_ref_date)
    stats["trade_date"] = trade_date.where(pd.notna(trade_date), ts_event_date)
    stats["stat_name"] = stats["stat_type"].map(STAT_TYPE_COLUMNS)
    stats["stat_value"] = np.where(
        stats["stat_type"].isin({STAT_CLEARED_VOLUME, STAT_OPEN_INTEREST}),
        stats["quantity"],
        stats["price"],
    )
    stats = stats.dropna(subset=["symbol", "trade_date", "stat_name", "stat_value"])
    stats = stats.sort_values(["symbol", "trade_date", "stat_name", "ts_event"])
    last = stats.groupby(["symbol", "trade_date", "stat_name"], sort=False).tail(1)
    instrument_ids = (
        stats.sort_values(["symbol", "trade_date", "ts_event"])
        .groupby(["symbol", "trade_date"], sort=False)["instrument_id"]
        .last()
        .reset_index()
    )
    pivot = (
        last.pivot_table(
            index=["symbol", "trade_date"],
            columns="stat_name",
            values="stat_value",
            aggfunc="last",
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    pivot = pivot.merge(instrument_ids, on=["symbol", "trade_date"], how="left")
    availability = (
        stats.groupby("trade_date", dropna=False)["ts_event"]
        .max()
        .reset_index()
        .rename(columns={"ts_event": "available_time"})
    )
    pivot = pivot.merge(availability, on="trade_date", how="left")
    pivot["available_time"] = _normalize_feature_time(pivot["available_time"])
    for col in ("settlement_price", "cleared_volume", "open_interest", "official_iv", "official_delta"):
        if col in pivot.columns:
            pivot[col] = pd.to_numeric(pivot[col], errors="coerce")
    return pivot


def definition_snapshot(definitions: pd.DataFrame) -> pd.DataFrame:
    if definitions.empty:
        return pd.DataFrame()
    defs = normalize_definition_frame(definitions)
    source_date = (
        defs["source_member"].map(_date_from_member)
        if "source_member" in defs.columns
        else pd.Series(pd.NaT, index=defs.index)
    )
    ts_event_date = pd.to_datetime(defs.get("ts_event"), utc=True, errors="coerce").dt.date
    defs["trade_date"] = source_date.where(pd.notna(source_date), ts_event_date)
    defs = defs.dropna(subset=["instrument_id", "trade_date", "strike_price"])
    if defs.empty:
        return pd.DataFrame()
    defs = defs.sort_values(["instrument_id", "trade_date", "ts_event"])
    last = defs.groupby(["instrument_id", "trade_date"], sort=False).tail(1).copy()
    out = pd.DataFrame(
        {
            "instrument_id": pd.to_numeric(last["instrument_id"], errors="coerce"),
            "trade_date": last["trade_date"],
            "definition_symbol": last.get("symbol", pd.Series(np.nan, index=last.index)).astype(str),
            "definition_raw_symbol": last.get("raw_symbol", pd.Series(np.nan, index=last.index)).astype(str),
            "definition_option_type": last.get("instrument_class", pd.Series(np.nan, index=last.index)).astype(str).str.upper().str[0],
            "definition_strike": pd.to_numeric(last["strike_price"], errors="coerce"),
            "definition_expiration": _normalize_feature_time(last["expiration"])
            if "expiration" in last.columns
            else pd.NaT,
        }
    )
    out.loc[~out["definition_option_type"].isin(["C", "P"]), "definition_option_type"] = np.nan
    return out.dropna(subset=["instrument_id", "trade_date"])


def add_option_metadata(snapshot: pd.DataFrame, definitions: pd.DataFrame | None = None) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot.copy()
    out = snapshot.copy()
    parsed_cache: dict[tuple[str, Any], dict[str, Any] | None] = {}
    option_type = []
    strike = []
    expiration = []
    for symbol, trade_date in zip(out["symbol"].astype(str), out["trade_date"], strict=False):
        key = (symbol, trade_date)
        if key not in parsed_cache:
            parsed_cache[key] = parse_nq_option_symbol(symbol, pd.Timestamp(trade_date))
        parsed = parsed_cache[key]
        option_type.append(parsed["option_type"] if parsed else np.nan)
        strike.append(parsed["strike"] if parsed else np.nan)
        expiration.append(parsed["estimated_expiration"] if parsed else pd.NaT)
    out["option_type"] = option_type
    out["strike"] = pd.to_numeric(strike, errors="coerce")
    out["estimated_expiration"] = pd.to_datetime(expiration, errors="coerce")
    if definitions is not None and not definitions.empty and "instrument_id" in out.columns:
        defs = definition_snapshot(definitions)
        if not defs.empty:
            out["instrument_id"] = pd.to_numeric(out["instrument_id"], errors="coerce")
            out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.date
            defs["trade_date"] = pd.to_datetime(defs["trade_date"], errors="coerce").dt.date
            out = out.merge(
                defs,
                on=["instrument_id", "trade_date"],
                how="left",
            )
            out["option_type"] = out["definition_option_type"].where(
                out["definition_option_type"].isin(["C", "P"]),
                out["option_type"],
            )
            out["strike"] = out["definition_strike"].where(out["definition_strike"].notna(), out["strike"])
            out["estimated_expiration"] = out["definition_expiration"].where(
                out["definition_expiration"].notna(),
                out["estimated_expiration"],
            )
            out = out.drop(
                columns=[
                    "definition_symbol",
                    "definition_raw_symbol",
                    "definition_option_type",
                    "definition_strike",
                    "definition_expiration",
                ],
                errors="ignore",
            )
    out["dte"] = (
        (out["estimated_expiration"] - pd.to_datetime(out["available_time"]))
        .dt.total_seconds()
        .div(24 * 3600)
    )
    return out


def _prepare_futures_prices(futures_bars: pd.DataFrame) -> pd.DataFrame:
    if futures_bars.empty:
        return pd.DataFrame(columns=["time", "underlying_price"])
    futures = futures_bars.copy()
    futures["time"] = _naive_datetime_ns(futures["time"])
    futures["underlying_price"] = pd.to_numeric(futures["close"], errors="coerce")
    return futures.dropna(subset=["time", "underlying_price"]).sort_values("time")


def _attach_underlying_price(options: pd.DataFrame, futures_prices: pd.DataFrame) -> pd.DataFrame:
    if options.empty or futures_prices.empty:
        out = options.copy()
        out["underlying_price"] = np.nan
        return out
    out = options.sort_values("available_time").copy()
    out["available_time"] = _naive_datetime_ns(out["available_time"])
    prices = futures_prices.copy()
    prices["time"] = _naive_datetime_ns(prices["time"])
    return pd.merge_asof(
        out,
        prices[["time", "underlying_price"]],
        left_on="available_time",
        right_on="time",
        direction="backward",
    ).drop(columns=["time"], errors="ignore")


def compute_option_greeks(snapshot: pd.DataFrame, config: OptionsFlowBuildConfig | None = None) -> pd.DataFrame:
    cfg = config or OptionsFlowBuildConfig()
    out = snapshot.copy()
    if out.empty:
        return out
    for col in ("settlement_price", "open_interest", "cleared_volume", "strike", "underlying_price", "dte"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    deltas: list[float] = []
    gammas: list[float] = []
    vegas: list[float] = []
    thetas: list[float] = []
    ivs: list[float] = []
    for row in out.itertuples(index=False):
        price = getattr(row, "settlement_price", np.nan)
        official_iv = getattr(row, "official_iv", np.nan)
        official_delta = getattr(row, "official_delta", np.nan)
        f = getattr(row, "underlying_price", np.nan)
        k = getattr(row, "strike", np.nan)
        dte = getattr(row, "dte", np.nan)
        option_type = getattr(row, "option_type", "")
        t = max(float(dte), 0.0) / 365.25 if pd.notna(dte) else np.nan
        iv = float(official_iv) if pd.notna(official_iv) and float(official_iv) > 0 else np.nan
        if pd.isna(iv):
            iv = implied_volatility_black76(
                price,
                f,
                k,
                t,
                option_type,
                risk_free_rate=cfg.risk_free_rate,
                min_vol=cfg.iv_floor,
                max_vol=cfg.iv_cap,
            )
        if pd.isna(iv) or iv <= 0:
            deltas.append(float(official_delta) if pd.notna(official_delta) else np.nan)
            gammas.append(np.nan)
            vegas.append(np.nan)
            thetas.append(np.nan)
            ivs.append(np.nan)
            continue
        greeks = black76_greeks(f, k, t, iv, option_type, risk_free_rate=cfg.risk_free_rate)
        delta = float(official_delta) if pd.notna(official_delta) else greeks["delta"]
        deltas.append(delta)
        gammas.append(greeks["gamma"])
        vegas.append(greeks["vega"])
        thetas.append(greeks["theta"])
        ivs.append(iv)
    out["implied_volatility"] = ivs
    out["delta"] = deltas
    out["gamma"] = gammas
    out["vega"] = vegas
    out["theta"] = thetas
    return out


def _options_for_dte_bucket(options: pd.DataFrame, min_dte: float | None, max_dte: float | None) -> pd.DataFrame:
    if min_dte is None and max_dte is None:
        return options.copy()
    dte = pd.to_numeric(options["dte"], errors="coerce")
    mask = dte.notna()
    if min_dte is not None:
        mask &= dte.ge(float(min_dte))
    if max_dte is not None:
        mask &= dte.lt(float(max_dte))
    return options.loc[mask].copy()


def _add_bucket_columns(
    frame: pd.DataFrame,
    *,
    bucket: str,
    min_dte: float | None,
    max_dte: float | None,
    priority: int,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    out = frame.copy()
    insert_at = 1 if "options_trade_date" in out.columns else 0
    out.insert(insert_at, "options_dte_bucket", bucket)
    out.insert(insert_at + 1, "options_dte_min", min_dte)
    out.insert(insert_at + 2, "options_dte_max_exclusive", max_dte)
    out.insert(insert_at + 3, "options_dte_bucket_priority", priority)
    return out


def _aggregate_options_dashboard(options: pd.DataFrame, cfg: OptionsFlowBuildConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_frames: list[pd.DataFrame] = []
    strike_frames: list[pd.DataFrame] = []
    for bucket, min_dte, max_dte, priority in OPTIONS_DTE_BUCKETS:
        bucket_options = _options_for_dte_bucket(options, min_dte, max_dte)
        if bucket_options.empty:
            continue
        daily = _aggregate_options_flow(bucket_options, cfg)
        if daily.empty:
            continue
        daily = _add_bucket_columns(
            daily,
            bucket=bucket,
            min_dte=min_dte,
            max_dte=max_dte,
            priority=priority,
        )
        strikes = _aggregate_options_strike_levels(bucket_options, daily)
        strikes = _add_bucket_columns(
            strikes,
            bucket=bucket,
            min_dte=min_dte,
            max_dte=max_dte,
            priority=priority,
        )
        daily_frames.append(daily)
        if not strikes.empty:
            strike_frames.append(strikes)
    dashboard = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    dashboard_strikes = pd.concat(strike_frames, ignore_index=True) if strike_frames else pd.DataFrame()
    if not dashboard.empty:
        dashboard = dashboard.sort_values(["options_available_time", "options_dte_bucket_priority"]).reset_index(drop=True)
    if not dashboard_strikes.empty:
        dashboard_strikes = dashboard_strikes.sort_values(
            ["options_available_time", "options_dte_bucket_priority", "options_strike"]
        ).reset_index(drop=True)
    return dashboard, dashboard_strikes


def build_options_flow_feature_sets(
    statistics: pd.DataFrame,
    futures_bars: pd.DataFrame,
    config: OptionsFlowBuildConfig | None = None,
    definitions: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    futures_prices = _prepare_futures_prices(futures_bars)
    return _build_options_flow_feature_sets_from_statistics(statistics, futures_prices, config, definitions)


def build_options_flow_features(
    statistics: pd.DataFrame,
    futures_bars: pd.DataFrame,
    config: OptionsFlowBuildConfig | None = None,
    definitions: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    feature_sets = build_options_flow_feature_sets(statistics, futures_bars, config, definitions)
    return feature_sets["daily"], feature_sets["strike_levels"]


def _build_options_flow_feature_sets_from_statistics(
    statistics: pd.DataFrame,
    futures_prices: pd.DataFrame,
    config: OptionsFlowBuildConfig | None = None,
    definitions: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    cfg = config or OptionsFlowBuildConfig()
    snapshot = statistics_snapshot(statistics)
    if snapshot.empty:
        return {
            "daily": pd.DataFrame(),
            "strike_levels": pd.DataFrame(),
            "dashboard": pd.DataFrame(),
            "dashboard_strike_levels": pd.DataFrame(),
        }
    options = add_option_metadata(snapshot, definitions)
    options = _attach_underlying_price(options, futures_prices)
    for col in ("settlement_price", "cleared_volume", "open_interest", "official_iv", "official_delta"):
        if col not in options.columns:
            options[col] = np.nan
    options = options.loc[
        options["option_type"].isin(["C", "P"])
        & options["dte"].between(float(cfg.min_dte), float(cfg.max_dte))
        & options["open_interest"].fillna(0).ge(float(cfg.min_open_interest))
        & options["settlement_price"].notna()
        & options["underlying_price"].notna()
    ].copy()
    if cfg.strike_window_points and cfg.strike_window_points > 0:
        options = options.loc[(options["strike"] - options["underlying_price"]).abs().le(float(cfg.strike_window_points))]
    if options.empty:
        return {
            "daily": pd.DataFrame(),
            "strike_levels": pd.DataFrame(),
            "dashboard": pd.DataFrame(),
            "dashboard_strike_levels": pd.DataFrame(),
        }

    options = compute_option_greeks(options, cfg)
    options = options.dropna(subset=["gamma", "delta", "implied_volatility"])
    if options.empty:
        return {
            "daily": pd.DataFrame(),
            "strike_levels": pd.DataFrame(),
            "dashboard": pd.DataFrame(),
            "dashboard_strike_levels": pd.DataFrame(),
        }
    sign = np.where(options["option_type"].eq("C"), 1.0, float(cfg.put_gamma_sign))
    oi = options["open_interest"].fillna(0).astype(float)
    f = options["underlying_price"].astype(float)
    multiplier = float(cfg.contract_multiplier)
    options["gamma_exposure"] = options["gamma"].astype(float) * oi * multiplier * (f ** 2) * 0.01 * sign
    options["abs_gamma_exposure"] = options["gamma_exposure"].abs()
    options["delta_exposure"] = options["delta"].astype(float) * oi * multiplier * f
    options["vega_exposure"] = options["vega"].astype(float) * oi * multiplier

    daily = _aggregate_options_flow(options, cfg)
    strike_levels = _aggregate_options_strike_levels(options, daily)
    dashboard, dashboard_strike_levels = _aggregate_options_dashboard(options, cfg)
    return {
        "daily": daily,
        "strike_levels": strike_levels,
        "dashboard": dashboard,
        "dashboard_strike_levels": dashboard_strike_levels,
    }


def _build_options_flow_features_from_statistics(
    statistics: pd.DataFrame,
    futures_prices: pd.DataFrame,
    config: OptionsFlowBuildConfig | None = None,
    definitions: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    feature_sets = _build_options_flow_feature_sets_from_statistics(
        statistics,
        futures_prices,
        config,
        definitions,
    )
    return feature_sets["daily"], feature_sets["strike_levels"]


def _nearest_wall(strikes: pd.Series, reference: float, side: str) -> float:
    values = pd.to_numeric(strikes, errors="coerce").dropna().astype(float)
    if side == "above":
        values = values.loc[values.ge(reference)]
        return float(values.min()) if not values.empty else np.nan
    values = values.loc[values.le(reference)]
    return float(values.max()) if not values.empty else np.nan


def _aggregate_options_flow(options: pd.DataFrame, cfg: OptionsFlowBuildConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for trade_date, group in options.groupby("trade_date", sort=True):
        calls = group.loc[group["option_type"].eq("C")]
        puts = group.loc[group["option_type"].eq("P")]
        underlying = float(group["underlying_price"].median())
        by_strike = group.groupby("strike", dropna=False).agg(
            gamma_exposure=("gamma_exposure", "sum"),
            abs_gamma_exposure=("abs_gamma_exposure", "sum"),
            open_interest=("open_interest", "sum"),
        ).reset_index()
        max_gamma_row = by_strike.sort_values("abs_gamma_exposure", ascending=False).head(1)
        gamma_wall = float(max_gamma_row["strike"].iloc[0]) if not max_gamma_row.empty else np.nan
        gamma_above = _nearest_wall(by_strike.sort_values("abs_gamma_exposure", ascending=False)["strike"], underlying, "above")
        gamma_below = _nearest_wall(by_strike.sort_values("abs_gamma_exposure", ascending=False)["strike"], underlying, "below")

        call_oi_by_strike = calls.groupby("strike")["open_interest"].sum().sort_values(ascending=False)
        put_oi_by_strike = puts.groupby("strike")["open_interest"].sum().sort_values(ascending=False)
        call_wall = float(call_oi_by_strike.index[0]) if not call_oi_by_strike.empty else np.nan
        put_wall = float(put_oi_by_strike.index[0]) if not put_oi_by_strike.empty else np.nan
        net_gex = float(group["gamma_exposure"].sum())
        threshold = float(cfg.gex_neutral_threshold)
        regime = "neutral"
        if net_gex > threshold:
            regime = "positive"
        elif net_gex < -threshold:
            regime = "negative"
        gamma_environment = f"{regime}_gamma"
        gamma_wall_role = "neutral"
        call_wall_role = "neutral"
        put_wall_role = "neutral"
        if regime == "positive":
            gamma_wall_role = "pinning_wall"
            call_wall_role = "resistance_pin"
            put_wall_role = "support_pin"
        elif regime == "negative":
            gamma_wall_role = "volatility_trigger"
            call_wall_role = "upside_amplifier"
            put_wall_role = "downside_amplifier"
        rows.append(
            {
                "options_trade_date": str(trade_date),
                "options_available_time": group["available_time"].max(),
                "options_underlying_price": underlying,
                "options_contracts": int(group["symbol"].nunique()),
                "options_total_oi": float(group["open_interest"].sum()),
                "options_call_oi": float(calls["open_interest"].sum()),
                "options_put_oi": float(puts["open_interest"].sum()),
                "options_put_call_oi_ratio": float(puts["open_interest"].sum() / calls["open_interest"].sum())
                if calls["open_interest"].sum() > 0
                else np.nan,
                "options_cleared_volume": float(group.get("cleared_volume", pd.Series(dtype=float)).fillna(0).sum()),
                "options_call_volume": float(calls.get("cleared_volume", pd.Series(dtype=float)).fillna(0).sum()),
                "options_put_volume": float(puts.get("cleared_volume", pd.Series(dtype=float)).fillna(0).sum()),
                "options_net_gex": net_gex,
                "options_abs_gex": float(group["abs_gamma_exposure"].sum()),
                "options_call_gex": float(calls["gamma_exposure"].sum()),
                "options_put_gex": float(puts["gamma_exposure"].sum()),
                "options_net_dex": float(group["delta_exposure"].sum()),
                "options_call_dex": float(calls["delta_exposure"].sum()),
                "options_put_dex": float(puts["delta_exposure"].sum()),
                "options_vega_exposure": float(group["vega_exposure"].sum()),
                "options_avg_iv": float(np.average(group["implied_volatility"], weights=group["open_interest"]))
                if group["open_interest"].sum() > 0
                else float(group["implied_volatility"].mean()),
                "options_gex_regime": regime,
                "options_gamma_environment": gamma_environment,
                "options_gamma_wall_strike": gamma_wall,
                "options_gamma_wall_role": gamma_wall_role,
                "options_gamma_wall_above": gamma_above,
                "options_gamma_wall_below": gamma_below,
                "options_gamma_wall_distance": gamma_wall - underlying if pd.notna(gamma_wall) else np.nan,
                "options_gamma_wall_above_distance": gamma_above - underlying if pd.notna(gamma_above) else np.nan,
                "options_gamma_wall_below_distance": underlying - gamma_below if pd.notna(gamma_below) else np.nan,
                "options_call_wall_strike": call_wall,
                "options_put_wall_strike": put_wall,
                "options_call_wall_role": call_wall_role,
                "options_put_wall_role": put_wall_role,
                "options_call_wall_distance": call_wall - underlying if pd.notna(call_wall) else np.nan,
                "options_put_wall_distance": underlying - put_wall if pd.notna(put_wall) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("options_available_time").reset_index(drop=True)


def _weighted_average(values: pd.Series, weights: pd.Series) -> float:
    numeric_values = pd.to_numeric(values, errors="coerce")
    numeric_weights = pd.to_numeric(weights, errors="coerce").fillna(0.0)
    valid = numeric_values.notna() & numeric_weights.gt(0.0)
    if valid.any():
        return float(np.average(numeric_values.loc[valid], weights=numeric_weights.loc[valid]))
    return float(numeric_values.mean()) if numeric_values.notna().any() else np.nan


def _strike_role(
    strike: float,
    *,
    gamma_wall: float,
    call_wall: float,
    put_wall: float,
    gamma_above: float,
    gamma_below: float,
) -> str:
    roles: list[str] = []
    checks = [
        ("gamma_wall", gamma_wall),
        ("call_wall", call_wall),
        ("put_wall", put_wall),
        ("nearest_gamma_above", gamma_above),
        ("nearest_gamma_below", gamma_below),
    ]
    for name, level in checks:
        if pd.notna(level) and math.isclose(float(strike), float(level), abs_tol=1e-9):
            roles.append(name)
    return "|".join(roles) if roles else "level"


def _aggregate_options_strike_levels(options: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Build a by-strike GEX surface from option-level rows.

    The daily feature file is the compact point-in-time join artifact for
    backtests. This strike-level file is the research surface: one row per
    trade date and strike, with calls and puts split out like a GEX dashboard.
    """
    if options.empty:
        return pd.DataFrame()

    daily_lookup: dict[Any, pd.Series] = {}
    if not daily.empty and "options_trade_date" in daily.columns:
        for row in daily.itertuples(index=False):
            daily_lookup[str(getattr(row, "options_trade_date"))] = pd.Series(row._asdict())

    rows: list[dict[str, Any]] = []
    for (trade_date, strike), group in options.groupby(["trade_date", "strike"], sort=True):
        calls = group.loc[group["option_type"].eq("C")]
        puts = group.loc[group["option_type"].eq("P")]
        underlying = float(group["underlying_price"].median())
        trade_date_key = str(trade_date)
        daily_row = daily_lookup.get(trade_date_key, pd.Series(dtype=object))
        gamma_wall = pd.to_numeric(daily_row.get("options_gamma_wall_strike", np.nan), errors="coerce")
        call_wall = pd.to_numeric(daily_row.get("options_call_wall_strike", np.nan), errors="coerce")
        put_wall = pd.to_numeric(daily_row.get("options_put_wall_strike", np.nan), errors="coerce")
        gamma_above = pd.to_numeric(daily_row.get("options_gamma_wall_above", np.nan), errors="coerce")
        gamma_below = pd.to_numeric(daily_row.get("options_gamma_wall_below", np.nan), errors="coerce")

        call_oi = float(calls["open_interest"].sum())
        put_oi = float(puts["open_interest"].sum())
        call_volume = float(calls.get("cleared_volume", pd.Series(dtype=float)).fillna(0.0).sum())
        put_volume = float(puts.get("cleared_volume", pd.Series(dtype=float)).fillna(0.0).sum())
        call_gex = float(calls["gamma_exposure"].sum())
        put_gex = float(puts["gamma_exposure"].sum())
        call_dex = float(calls["delta_exposure"].sum())
        put_dex = float(puts["delta_exposure"].sum())

        rows.append(
            {
                "options_trade_date": trade_date_key,
                "options_available_time": group["available_time"].max(),
                "options_underlying_price": underlying,
                "options_strike": float(strike),
                "options_distance_from_underlying_points": float(strike) - underlying,
                "options_distance_from_underlying_pct": (float(strike) / underlying - 1.0)
                if underlying > 0
                else np.nan,
                "options_contracts": int(group["symbol"].nunique()),
                "options_total_oi": call_oi + put_oi,
                "options_call_oi": call_oi,
                "options_put_oi": put_oi,
                "options_net_call_put_oi": call_oi - put_oi,
                "options_cleared_volume": call_volume + put_volume,
                "options_call_volume": call_volume,
                "options_put_volume": put_volume,
                "options_net_call_put_volume": call_volume - put_volume,
                "options_net_gex": call_gex + put_gex,
                "options_abs_gex": float(group["abs_gamma_exposure"].sum()),
                "options_call_gex": call_gex,
                "options_put_gex": put_gex,
                "options_net_dex": call_dex + put_dex,
                "options_call_dex": call_dex,
                "options_put_dex": put_dex,
                "options_vega_exposure": float(group["vega_exposure"].sum()),
                "options_avg_iv": _weighted_average(group["implied_volatility"], group["open_interest"]),
                "options_call_avg_iv": _weighted_average(calls["implied_volatility"], calls["open_interest"])
                if not calls.empty
                else np.nan,
                "options_put_avg_iv": _weighted_average(puts["implied_volatility"], puts["open_interest"])
                if not puts.empty
                else np.nan,
                "options_call_avg_delta": _weighted_average(calls["delta"], calls["open_interest"])
                if not calls.empty
                else np.nan,
                "options_put_avg_delta": _weighted_average(puts["delta"], puts["open_interest"])
                if not puts.empty
                else np.nan,
                "options_is_gamma_wall": bool(pd.notna(gamma_wall) and math.isclose(float(strike), float(gamma_wall), abs_tol=1e-9)),
                "options_is_call_wall": bool(pd.notna(call_wall) and math.isclose(float(strike), float(call_wall), abs_tol=1e-9)),
                "options_is_put_wall": bool(pd.notna(put_wall) and math.isclose(float(strike), float(put_wall), abs_tol=1e-9)),
                "options_is_nearest_gamma_above": bool(
                    pd.notna(gamma_above) and math.isclose(float(strike), float(gamma_above), abs_tol=1e-9)
                ),
                "options_is_nearest_gamma_below": bool(
                    pd.notna(gamma_below) and math.isclose(float(strike), float(gamma_below), abs_tol=1e-9)
                ),
                "options_strike_role": _strike_role(
                    float(strike),
                    gamma_wall=gamma_wall,
                    call_wall=call_wall,
                    put_wall=put_wall,
                    gamma_above=gamma_above,
                    gamma_below=gamma_below,
                ),
            }
        )

    return (
        pd.DataFrame(rows)
        .sort_values(["options_available_time", "options_strike"])
        .reset_index(drop=True)
    )


def build_options_flow_features_from_source(
    statistics_source: Path | str,
    futures_bars: pd.DataFrame,
    config: OptionsFlowBuildConfig | None = None,
    *,
    definition_source: Path | str | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    max_files: int | None = None,
    rows_per_file: int | None = None,
    progress_every: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    feature_sets = build_options_flow_feature_sets_from_source(
        statistics_source,
        futures_bars,
        config,
        definition_source=definition_source,
        start=start,
        end=end,
        max_files=max_files,
        rows_per_file=rows_per_file,
        progress_every=progress_every,
    )
    return feature_sets["daily"], feature_sets["strike_levels"]


def build_options_flow_feature_sets_from_source(
    statistics_source: Path | str,
    futures_bars: pd.DataFrame,
    config: OptionsFlowBuildConfig | None = None,
    *,
    definition_source: Path | str | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    max_files: int | None = None,
    rows_per_file: int | None = None,
    progress_every: int | None = None,
) -> dict[str, pd.DataFrame]:
    members = _filtered_statistics_members(
        statistics_source,
        start=start,
        end=end,
        max_files=max_files,
    )
    if not members:
        return {
            "daily": pd.DataFrame(),
            "strike_levels": pd.DataFrame(),
            "dashboard": pd.DataFrame(),
            "dashboard_strike_levels": pd.DataFrame(),
        }

    futures_prices = _prepare_futures_prices(futures_bars)
    daily_frames: list[pd.DataFrame] = []
    strike_frames: list[pd.DataFrame] = []
    dashboard_frames: list[pd.DataFrame] = []
    dashboard_strike_frames: list[pd.DataFrame] = []
    total_strike_rows = 0
    total_dashboard_rows = 0
    total_dashboard_strike_rows = 0
    total_members = len(members)
    should_log_progress = progress_every is not None and int(progress_every) > 0
    definition_members_by_date = _definition_member_by_date(definition_source) if definition_source else {}
    definition_zip: zipfile.ZipFile | None = None
    definition_source_path = Path(definition_source) if definition_source else None
    if definition_source_path is not None and definition_source_path.suffix.lower() == ".zip":
        definition_zip = zipfile.ZipFile(definition_source_path)

    try:
        for index, (member, frame) in enumerate(
            zip(
                members,
                iter_statistics_frames(
                    statistics_source,
                    start=start,
                    end=end,
                    max_files=max_files,
                    rows_per_file=rows_per_file,
                ),
                strict=False,
            ),
            start=1,
        ):
            definitions = pd.DataFrame()
            if definition_source_path is not None:
                definition_member = definition_members_by_date.get(_date_from_member(member))
                if definition_member is not None:
                    definitions = _read_definition_frame(
                        definition_source_path,
                        definition_member,
                        zip_file=definition_zip,
                    )
            feature_sets = _build_options_flow_feature_sets_from_statistics(frame, futures_prices, config, definitions)
            daily = feature_sets["daily"]
            strikes = feature_sets["strike_levels"]
            dashboard = feature_sets["dashboard"]
            dashboard_strikes = feature_sets["dashboard_strike_levels"]
            if not daily.empty:
                daily_frames.append(daily)
            if not strikes.empty:
                strike_frames.append(strikes)
                total_strike_rows += len(strikes)
            if not dashboard.empty:
                dashboard_frames.append(dashboard)
                total_dashboard_rows += len(dashboard)
            if not dashboard_strikes.empty:
                dashboard_strike_frames.append(dashboard_strikes)
                total_dashboard_strike_rows += len(dashboard_strikes)
            if should_log_progress and (index == 1 or index == total_members or index % int(progress_every) == 0):
                print(
                    f"[options-flow] processed {index}/{total_members} members; "
                    f"feature days={sum(len(df) for df in daily_frames):,}; "
                    f"strike rows={total_strike_rows:,}; "
                    f"dashboard rows={total_dashboard_rows:,}; "
                    f"dashboard strike rows={total_dashboard_strike_rows:,}",
                    flush=True,
                )
    finally:
        if definition_zip is not None:
            definition_zip.close()

    daily_out = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    if not daily_out.empty and "options_available_time" in daily_out.columns:
        daily_out = daily_out.sort_values("options_available_time").reset_index(drop=True)

    strike_out = pd.concat(strike_frames, ignore_index=True) if strike_frames else pd.DataFrame()
    if not strike_out.empty and "options_available_time" in strike_out.columns:
        strike_out = strike_out.sort_values(["options_available_time", "options_strike"]).reset_index(drop=True)
    dashboard_out = pd.concat(dashboard_frames, ignore_index=True) if dashboard_frames else pd.DataFrame()
    if not dashboard_out.empty and "options_available_time" in dashboard_out.columns:
        dashboard_out = dashboard_out.sort_values(
            ["options_available_time", "options_dte_bucket_priority"]
        ).reset_index(drop=True)
    dashboard_strike_out = (
        pd.concat(dashboard_strike_frames, ignore_index=True) if dashboard_strike_frames else pd.DataFrame()
    )
    if not dashboard_strike_out.empty and "options_available_time" in dashboard_strike_out.columns:
        dashboard_strike_out = dashboard_strike_out.sort_values(
            ["options_available_time", "options_dte_bucket_priority", "options_strike"]
        ).reset_index(drop=True)
    return {
        "daily": daily_out,
        "strike_levels": strike_out,
        "dashboard": dashboard_out,
        "dashboard_strike_levels": dashboard_strike_out,
    }


def add_options_flow_features(
    futures_bars: pd.DataFrame,
    options_flow_features: pd.DataFrame | Path | str,
) -> pd.DataFrame:
    out = futures_bars.copy()
    if isinstance(options_flow_features, (str, Path)):
        path = Path(options_flow_features)
        if not path.exists():
            return out
        flow = pd.read_csv(path)
    else:
        flow = options_flow_features.copy()
    if flow.empty or "options_available_time" not in flow.columns:
        return out

    out["time"] = _naive_datetime_ns(out["time"])
    flow["options_available_time"] = _naive_datetime_ns(flow["options_available_time"])
    out = out.sort_values("time")
    flow = flow.dropna(subset=["options_available_time"]).sort_values("options_available_time")
    merged = pd.merge_asof(
        out,
        flow,
        left_on="time",
        right_on="options_available_time",
        direction="backward",
    )
    if "close" in merged.columns:
        price = pd.to_numeric(merged["close"], errors="coerce")
        wall_strikes = {
            "options_gamma_wall_distance": ("options_gamma_wall_strike", "strike_minus_price"),
            "options_gamma_wall_above_distance": ("options_gamma_wall_above", "strike_minus_price"),
            "options_gamma_wall_below_distance": ("options_gamma_wall_below", "price_minus_strike"),
            "options_call_wall_distance": ("options_call_wall_strike", "strike_minus_price"),
            "options_put_wall_distance": ("options_put_wall_strike", "price_minus_strike"),
        }
        for distance_col, (strike_col, mode) in wall_strikes.items():
            if strike_col not in merged.columns:
                continue
            strike = pd.to_numeric(merged[strike_col], errors="coerce")
            if mode == "strike_minus_price":
                merged[distance_col] = strike - price
            else:
                merged[distance_col] = price - strike
    return merged.sort_values("time").reset_index(drop=True)
