"""Chart-tracker replay of the MotiveWave studies.

This replays the rules in the Java ``calculate`` methods. It does not replay
live order submission. Live submission also requires a verified
``demo_parity_state.json``, which is not reconstructed here.

The Java chart tracker fills at the signal-bar open and at the exact stop,
target, or flatten close. It checks the target before the stop on the same
later bar, and it does not deduct commission or slippage. Those zeros are
reported explicitly. They are not a claim that live fills are free.

Bars at or after 2025-01-01 are rejected. The price files are single-symbol
series with timezone-naive timestamps treated as ET wall time, not verified
continuous contracts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from backtest.gold_contract_value import confirmed_point_value

OOS_START = pd.Timestamp("2025-01-01")
REPORT_START = pd.Timestamp("2021-01-01")
REPORT_END = pd.Timestamp("2024-12-31 23:59:59")

# Chart path when the daemon state is unverified. Live resolveContracts
# returns 0 in that same situation and submits nothing.
CHART_FALLBACK_CONTRACTS = 2

TRADE_COLUMNS = [
    "strategy_id",
    "instrument",
    "signal",
    "quantity",
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "exit_reason",
    "gross_pnl",
    "commission_usd",
    "slippage_usd",
    "net_pnl",
]


@dataclass(frozen=True)
class ReplaySpec:
    strategy_id: str
    instrument: str
    point_value: float
    tick_size: float
    source: str


def assert_insample_bars(times: pd.Series) -> None:
    t = pd.to_datetime(times)
    if t.empty:
        raise ValueError("No bars available before the out-of-sample cutoff.")
    if t.max() >= OOS_START:
        raise ValueError("Protected-period bars were passed to a study replay.")
    if t.duplicated().any():
        raise ValueError("Duplicate timestamps. Replay refuses to drop them.")
    if not t.is_monotonic_increasing:
        raise ValueError("Timestamps are not monotonic.")


def exclusive_end(end_date: str) -> pd.Timestamp:
    """Inclusive calendar date to the next-day exclusive timestamp."""
    if end_date > "2024-12-31":
        raise ValueError(f"Refusing end date {end_date}. Dates after 2024-12-31 are protected.")
    return pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1)


def overlapping_cutoff_row_groups(path: Path, upper: pd.Timestamp) -> int:
    """Row groups whose time statistics cross the cutoff.

    Predicate pushdown still reads a row group when its min/max range crosses
    the cutoff. The local files each have one such group. This count is not a
    claim that those bytes are unread.
    """
    parquet = pq.ParquetFile(path)
    time_index = parquet.schema_arrow.get_field_index("time")
    cutoff = upper.to_pydatetime()
    overlapping = 0
    for group in range(parquet.num_row_groups):
        stats = parquet.metadata.row_group(group).column(time_index).statistics
        if stats is None or not stats.has_min_max:
            continue
        if stats.min < cutoff and stats.max >= cutoff:
            overlapping += 1
    return overlapping


def load_bars_through(path: Path, end_date: str = "2024-12-31") -> pd.DataFrame:
    """Load bars with a Parquet predicate. No returned row is on or after the cutoff."""
    upper = exclusive_end(end_date)
    if upper > OOS_START:
        raise ValueError("Requested end reaches the protected period.")
    upper_scalar = pa.scalar(np.datetime64(upper.to_datetime64(), "us"))
    table = ds.dataset(str(path), format="parquet").to_table(
        columns=["time", "open", "high", "low", "close", "volume"],
        filter=ds.field("time") < upper_scalar,
    )
    frame = table.to_pandas()
    if "time" not in frame.columns:
        raise ValueError(f"{path} has no time column.")
    frame["time"] = pd.to_datetime(frame["time"])
    frame = frame.sort_values("time").reset_index(drop=True)
    if frame.empty or frame["time"].max() >= upper or frame["time"].max() >= OOS_START:
        raise ValueError("Loaded bars are empty or cross the requested cutoff.")
    assert_insample_bars(frame["time"])
    return frame


def load_insample_bars(path: Path, end_date: str = "2024-12-31") -> pd.DataFrame:
    return load_bars_through(path, end_date)


def trade_list_sha256(trades: pd.DataFrame) -> str:
    frame = trades.loc[:, TRADE_COLUMNS].copy()
    for col in ("entry_time", "exit_time"):
        frame[col] = pd.to_datetime(frame[col]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    for col in ("entry_price", "exit_price", "gross_pnl", "commission_usd", "slippage_usd", "net_pnl"):
        frame[col] = frame[col].map(lambda v: f"{float(v):.10f}")
    payload = frame.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parameter_sha256(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _minutes(times: pd.Series) -> np.ndarray:
    t = pd.to_datetime(times)
    return (t.dt.hour.to_numpy(dtype=np.int32) * 60 + t.dt.minute.to_numpy(dtype=np.int32))


def _day_bounds(dates: np.ndarray) -> list[tuple[int, int]]:
    if len(dates) == 0:
        return []
    change = np.flatnonzero(dates[1:] != dates[:-1]) + 1
    starts = np.concatenate((np.array([0], dtype=int), change))
    ends = np.concatenate((change, np.array([len(dates)], dtype=int)))
    return list(zip(starts.tolist(), ends.tolist()))


def _value_area_from_bars(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    tick: float,
) -> tuple[float, float, float]:
    """70% value area from one completed session.

    Java Math.round is used for tick keys. When several prices share the
    maximum volume, this replay keeps the lower price. Java HashMap
    iteration does not define that tie.
    """
    if len(high) == 0 or tick <= 0:
        return (np.nan, np.nan, np.nan)
    vol = np.asarray(volume, dtype=float)
    rth_volume = float(vol.sum())
    if rth_volume <= 0:
        return (np.nan, np.nan, np.nan)
    rth_high = float(np.max(high))
    rth_low = float(np.min(low))
    low_tick = np.floor(low / tick + 0.5).astype(np.int64)
    high_tick = np.floor(high / tick + 0.5).astype(np.int64)
    close_tick = np.floor(close / tick + 0.5).astype(np.int64)
    lo = int(min(int(low_tick.min()), int(close_tick.min())))
    hi = int(max(int(high_tick.max()), int(close_tick.max())))
    arr = np.zeros(hi - lo + 1, dtype=np.float64)
    for lt, ht, ct, each in zip(low_tick, high_tick, close_tick, vol):
        span = int(ht - lt + 1)
        if span <= 1:
            arr[int(ct) - lo] += float(each)
        else:
            arr[int(lt) - lo:int(ht) - lo + 1] += float(each) / span
    best = int(np.argmax(arr))
    target = rth_volume * 0.70
    current = float(arr[best])
    up = best + 1
    down = best - 1
    while current < target:
        up_vol = float(arr[up]) if 0 <= up < len(arr) else 0.0
        down_vol = float(arr[down]) if 0 <= down < len(arr) else 0.0
        if up_vol == 0.0 and down_vol == 0.0:
            if (lo + up) * tick > rth_high and (lo + down) * tick < rth_low:
                break
            up += 1
            down -= 1
            continue
        if up_vol >= down_vol:
            current += up_vol
            up += 1
        else:
            current += down_vol
            down -= 1
    return ((lo + up - 1) * tick, (lo + down + 1) * tick, (lo + best) * tick)


def _flatten_index(times: np.ndarray, minutes: np.ndarray, start: int, end: int, at: np.datetime64, minute_at: int | None) -> int | None:
    """First same-day bar at which the Java tracker would flatten.

    A later calendar day is not used. If the session ends first, the chart
    trade stays open and the replay omits it.
    """
    for j in range(start, end):
        if times[j] >= at or (minute_at is not None and int(minutes[j]) >= minute_at):
            return j
    return None


def _chart_row(
    spec: ReplaySpec,
    signal: str,
    entry_time,
    exit_time,
    entry_price: float,
    exit_price: float,
    reason: str,
) -> dict:
    points = (exit_price - entry_price) if signal == "long" else (entry_price - exit_price)
    gross = points * spec.point_value * CHART_FALLBACK_CONTRACTS
    return {
        "strategy_id": spec.strategy_id,
        "instrument": spec.instrument,
        "signal": signal,
        "quantity": CHART_FALLBACK_CONTRACTS,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "entry_price": float(entry_price),
        "exit_price": float(exit_price),
        "exit_reason": reason,
        "gross_pnl": float(gross),
        "commission_usd": 0.0,
        "slippage_usd": 0.0,
        "net_pnl": float(gross),
    }


def _walk_exit(
    spec: ReplaySpec,
    signal: str,
    entry_i: int,
    entry_price: float,
    stop_price: float,
    target_price: float,
    flatten_i: int,
    news_flatten_i: int | None,
    times: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
) -> dict:
    if flatten_i <= entry_i:
        return None
    reason = "time_flatten"
    exit_i = flatten_i
    exit_price = float(close[flatten_i])
    for i in range(entry_i + 1, flatten_i + 1):
        if signal == "long":
            if high[i] >= target_price:
                reason, exit_i, exit_price = "target", i, target_price
                break
            if low[i] <= stop_price:
                reason, exit_i, exit_price = "stop", i, stop_price
                break
        else:
            if low[i] <= target_price:
                reason, exit_i, exit_price = "target", i, target_price
                break
            if high[i] >= stop_price:
                reason, exit_i, exit_price = "stop", i, stop_price
                break
        if news_flatten_i is not None and i >= news_flatten_i:
            reason, exit_i, exit_price = "news_flatten", i, float(close[i])
            break
        if i >= flatten_i:
            reason, exit_i, exit_price = "time_flatten", i, float(close[i])
            break
    return _chart_row(spec, signal, times[entry_i], times[exit_i], entry_price, exit_price, reason)


def _report_end(report_end) -> pd.Timestamp:
    return REPORT_END if report_end is None else pd.Timestamp(report_end)


def _in_report_window(entry_time, report_end) -> bool:
    t = pd.Timestamp(entry_time)
    return REPORT_START <= t <= _report_end(report_end)


def _exit_inside(exit_time, report_end) -> bool:
    return pd.Timestamp(exit_time) <= _report_end(report_end)


def is_s1_news_day(day: pd.Timestamp) -> bool:
    """Port of LucidMorningVABreakoutStudy.is10amNewsDay."""
    dom = int(day.day)
    dow = int(day.dayofweek) + 1  # Monday=1
    if dow == 3 and dom <= 7:
        return True
    if dow == 2 and dom >= 24:
        return True
    if dow == 5 and ((8 <= dom <= 14) or (22 <= dom <= 28)):
        return True
    if dom <= 3 and dow <= 4:
        return True
    if (3 <= dom <= 5) and (1 <= dow <= 3):
        return True
    return False


def replay_morning_va(df: pd.DataFrame, spec: ReplaySpec, report_end=None) -> pd.DataFrame:
    """LucidMorningVABreakoutStudy.calculate, default settings, one chart."""
    assert_insample_bars(df["time"])
    is_es = "ES" in spec.instrument
    min_stop = 15.0
    max_stop = 35.0 if is_es else 60.0
    min_ret = 0.0010
    min_long_loc = 0.60
    max_short_loc = 0.40
    rr = 1.5
    vol_pct = 0.72 if is_es else 1.25
    exhaustion = 2.50
    tick = spec.tick_size

    times = pd.to_datetime(df["time"]).to_numpy()
    minutes = _minutes(df["time"])
    dates = pd.to_datetime(df["time"]).dt.strftime("%Y-%m-%d").to_numpy()
    open_ = df["open"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    volume = df["volume"].to_numpy(dtype=float)

    rows: list[dict] = []
    areas: dict[str, tuple[float, float]] = {}
    for start, end in _day_bounds(dates):
        day = str(dates[start])
        mins = minutes[start:end]
        rth = (mins >= 9 * 60 + 30) & (mins < 16 * 60)
        if np.any(rth):
            abs_rth = np.flatnonzero(rth) + start
            areas[day] = _value_area_from_bars(high[abs_rth], low[abs_rth], close[abs_rth], volume[abs_rth], tick)[:2]
        signal_at = np.flatnonzero((mins >= 9 * 60 + 45) & (mins < 10 * 60))
        if len(signal_at) == 0:
            continue
        opening = (mins >= 9 * 60 + 30) & (mins < 9 * 60 + 45)
        if not np.any(opening):
            continue
        opened = np.flatnonzero(opening)
        or_open = float(open_[start + int(opened[0])])
        or_high = float(np.max(high[start:end][opening]))
        or_low = float(np.min(low[start:end][opening]))
        or_close = float(close[start + int(opened[-1])])
        or_vol = float(volume[start:end][opening].sum())
        typical = (high[start:end][opening] + low[start:end][opening] + close[start:end][opening]) / 3.0
        or_pv = float((typical * volume[start:end][opening]).sum())
        prior = [d for d in areas if d < day]
        if not prior or or_high <= or_low or not np.isfinite(or_open):
            continue
        vah, val = areas[max(prior)]
        if not np.isfinite(vah) or not np.isfinite(val):
            continue
        ret = (or_close - or_open) / or_open
        loc = (or_close - or_low) / (or_high - or_low)
        is_long = ret >= min_ret and loc >= min_long_loc and or_close > vah
        is_short = ret <= -min_ret and loc <= max_short_loc and or_close < val
        mvt = (or_pv / or_vol) if or_vol > 0 else or_close
        sigma = or_close * (vol_pct / 100.0) * np.sqrt(15.0 / 390.0)
        z = (or_close - mvt) / max(sigma, 1e-4)
        if (is_long and z > exhaustion) or (is_short and z < -exhaustion):
            is_long = False
            is_short = False
        if not is_long and not is_short:
            continue
        i = start + int(signal_at[0])
        signal = "long" if is_long else "short"
        stop_pts = min(max_stop, max(min_stop, or_high - or_low))
        entry = float(open_[i])
        stop = entry - stop_pts if is_long else entry + stop_pts
        target = entry + stop_pts * rr if is_long else entry - stop_pts * rr
        flatten_at = np.datetime64(pd.Timestamp(times[i]) + pd.Timedelta(minutes=30))
        flatten_i = _flatten_index(times, minutes, i, end, flatten_at, 10 * 60 + 15)
        if flatten_i is None:
            continue
        news_i = None
        if is_s1_news_day(pd.Timestamp(day)):
            for j in range(i + 1, flatten_i + 1):
                if int(minutes[j]) >= 9 * 60 + 59:
                    news_i = j
                    break
        row = _walk_exit(spec, signal, i, entry, stop, target, flatten_i, news_i, times, high, low, close)
        if row is not None and _in_report_window(row["entry_time"], report_end) and _exit_inside(row["exit_time"], report_end):
            rows.append(row)
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def replay_macro_0835(df: pd.DataFrame, spec: ReplaySpec, report_end=None) -> pd.DataFrame:
    """LucidMacroMomentumStudy 08:35 path only. The 10:00 window is not replayed."""
    assert_insample_bars(df["time"])
    min_vol_mult = 2.50
    min_long_loc = 0.65
    max_short_loc = 0.35
    rr = 1.5
    min_stop = 20.0
    max_stop = 50.0
    high_vol_gate = False
    max_ovn = 180.0

    times = pd.to_datetime(df["time"]).to_numpy()
    minutes = _minutes(df["time"])
    dates = pd.to_datetime(df["time"]).dt.strftime("%Y-%m-%d").to_numpy()
    open_ = df["open"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    volume = df["volume"].to_numpy(dtype=float)

    rows: list[dict] = []
    for start, end in _day_bounds(dates):
        mins = minutes[start:end]
        signal_at = np.flatnonzero((mins >= 8 * 60 + 35) & (mins < 9 * 60))
        if len(signal_at) == 0:
            continue
        overnight = mins < 8 * 60 + 30
        spike = (mins >= 8 * 60 + 30) & (mins < 8 * 60 + 35)
        if not np.any(overnight) or not np.any(spike):
            continue
        ovn_high = float(np.max(high[start:end][overnight]))
        ovn_low = float(np.min(low[start:end][overnight]))
        pre = (mins >= 8 * 60) & (mins < 8 * 60 + 30)
        pre_bars = int(np.count_nonzero(pre))
        pre_vol = float(volume[start:end][pre].sum()) if pre_bars else 0.0
        spiked = np.flatnonzero(spike)
        spike_open = float(open_[start + int(spiked[0])])
        spike_high = float(np.max(high[start:end][spike]))
        spike_low = float(np.min(low[start:end][spike]))
        spike_close = float(close[start + int(spiked[-1])])
        spike_vol = float(volume[start:end][spike].sum())
        if not np.isfinite(spike_open) or spike_high <= spike_low or not np.isfinite(ovn_high):
            continue
        pre5 = (pre_vol / (pre_bars / 5.0)) if pre_bars >= 10 and pre_vol > 0 else 1.0
        vol_mult = spike_vol / max(1.0, pre5)
        loc = (spike_close - spike_low) / (spike_high - spike_low)
        is_long = vol_mult >= min_vol_mult and spike_close > ovn_high and loc >= min_long_loc
        is_short = vol_mult >= min_vol_mult and spike_close < ovn_low and loc <= max_short_loc
        if high_vol_gate and max_ovn > 0 and (ovn_high - ovn_low) > max_ovn:
            is_long = False
            is_short = False
        if not is_long and not is_short:
            continue
        i = start + int(signal_at[0])
        signal = "long" if is_long else "short"
        stop_pts = min(max_stop, max(min_stop, (spike_high - spike_low) * 0.50))
        entry = float(open_[i])
        stop = entry - stop_pts if is_long else entry + stop_pts
        target = entry + stop_pts * rr if is_long else entry - stop_pts * rr
        flatten_at = np.datetime64(pd.Timestamp(times[i]) + pd.Timedelta(minutes=50))
        flatten_i = _flatten_index(times, minutes, i, end, flatten_at, None)
        if flatten_i is None:
            continue
        row = _walk_exit(spec, signal, i, entry, stop, target, flatten_i, None, times, high, low, close)
        if row is not None and _in_report_window(row["entry_time"], report_end) and _exit_inside(row["exit_time"], report_end):
            rows.append(row)
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def replay_gold_fix(df: pd.DataFrame, spec: ReplaySpec, report_end=None) -> pd.DataFrame:
    """LucidGoldFixBreakoutStudy.calculate, default long-only settings."""
    assert_insample_bars(df["time"])
    if abs(spec.point_value - confirmed_point_value(spec.instrument)) > 1e-9:
        raise ValueError("Gold replay point value does not match the identified contract.")
    tick = spec.tick_size
    min_ret = 0.001125
    min_long_loc = 0.70
    rr = 1.5
    min_stop = 3.0
    max_stop = 18.0

    times = pd.to_datetime(df["time"]).to_numpy()
    minutes = _minutes(df["time"])
    dates = pd.to_datetime(df["time"]).dt.strftime("%Y-%m-%d").to_numpy()
    open_ = df["open"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    volume = df["volume"].to_numpy(dtype=float)

    rows: list[dict] = []
    areas: dict[str, float] = {}
    for start, end in _day_bounds(dates):
        day = str(dates[start])
        mins = minutes[start:end]
        session = (mins >= 8 * 60 + 20) & (mins <= 13 * 60 + 30)
        if np.any(session):
            chosen = np.flatnonzero(session) + start
            vah, _val, _poc = _value_area_from_bars(high[chosen], low[chosen], close[chosen], volume[chosen], tick)
            areas[day] = vah
        signal_at = np.flatnonzero(mins >= 10 * 60 + 15)
        if len(signal_at) == 0:
            continue
        london = (mins >= 3 * 60) & (mins < 8 * 60 + 20)
        ib = (mins >= 8 * 60 + 20) & (mins < 9 * 60 + 20)
        fix = (mins >= 10 * 60) & (mins < 10 * 60 + 15)
        if not np.any(fix):
            continue
        fixed = np.flatnonzero(fix)
        fix_open = float(open_[start + int(fixed[0])])
        fix_high = float(np.max(high[start:end][fix]))
        fix_low = float(np.min(low[start:end][fix]))
        fix_close = float(close[start + int(fixed[-1])])
        lon_high = float(np.max(high[start:end][london])) if np.any(london) else np.nan
        ib_high = float(np.max(high[start:end][ib])) if np.any(ib) else np.nan
        prior = [d for d in areas if d < day]
        vah = areas[max(prior)] if prior else np.nan
        if fix_high <= fix_low or not np.isfinite(fix_open):
            continue
        ret = (fix_close - fix_open) / fix_open
        loc = (fix_close - fix_low) / (fix_high - fix_low)
        va_pass = np.isfinite(vah) and fix_close > vah
        lon_pass = np.isfinite(lon_high) and fix_close > lon_high
        ib_pass = np.isfinite(ib_high) and fix_close > ib_high
        if not (ret >= min_ret and loc >= min_long_loc and va_pass and lon_pass and ib_pass):
            continue
        i = start + int(signal_at[0])
        stop_pts = min(max_stop, max(min_stop, fix_high - fix_low))
        entry = float(open_[i])
        stop = entry - stop_pts
        target = entry + stop_pts * rr
        flatten_at = np.datetime64(pd.Timestamp(times[i]) + pd.Timedelta(minutes=45))
        flatten_i = _flatten_index(times, minutes, i, end, flatten_at, 11 * 60)
        if flatten_i is None:
            continue
        row = _walk_exit(spec, "long", i, entry, stop, target, flatten_i, None, times, high, low, close)
        if row is not None and _in_report_window(row["entry_time"], report_end) and _exit_inside(row["exit_time"], report_end):
            rows.append(row)
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


def summarize(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {
            "trades": 0,
            "gross_pnl": 0.0,
            "commission_usd": 0.0,
            "slippage_usd": 0.0,
            "net_pnl": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "largest_win": 0.0,
        }
    net = trades["net_pnl"].to_numpy(dtype=float)
    wins = net[net > 0].sum()
    losses = -net[net < 0].sum()
    equity = np.cumsum(net)
    peak = np.maximum.accumulate(equity)
    dd = float((equity - peak).min()) if len(equity) else 0.0
    return {
        "trades": int(len(trades)),
        "gross_pnl": float(trades["gross_pnl"].sum()),
        "commission_usd": float(trades["commission_usd"].sum()),
        "slippage_usd": float(trades["slippage_usd"].sum()),
        "net_pnl": float(net.sum()),
        "profit_factor": float(wins / losses) if losses > 0 else 0.0,
        "max_drawdown": dd,
        "win_rate": float((net > 0).mean() * 100.0),
        "largest_win": float(net.max()),
    }


def frozen_parameters(spec: ReplaySpec, report_end: str = "2024-12-31") -> dict:
    base = {
        "strategy_id": spec.strategy_id,
        "instrument": spec.instrument,
        "point_value": spec.point_value,
        "tick_size": spec.tick_size,
        "quantity": CHART_FALLBACK_CONTRACTS,
        "commission_usd": 0.0,
        "slippage_usd": 0.0,
        "fill_model": "java_chart_tracker_target_before_stop",
        "report_start": str(REPORT_START.date()),
        "report_end": report_end,
        "oos_excluded_from": str(OOS_START.date()),
        "source": spec.source,
    }
    base["parameter_sha256"] = parameter_sha256({k: v for k, v in base.items() if k != "parameter_sha256"})
    return base


def iter_specs() -> Iterable[tuple[ReplaySpec, str]]:
    return (
        (ReplaySpec("morning_va_breakout_s1", "MNQ", 2.0, 0.25, "LucidMorningVABreakoutStudy"), "nq"),
        (ReplaySpec("morning_va_breakout_s1", "MES", 5.0, 0.25, "LucidMorningVABreakoutStudy"), "es"),
        (ReplaySpec("macro_momentum_s2", "MNQ", 2.0, 0.25, "LucidMacroMomentumStudy"), "nq"),
        (ReplaySpec("gold_london_fix_s3", "MGC", 10.0, 0.10, "LucidGoldFixBreakoutStudy"), "gc"),
    )
