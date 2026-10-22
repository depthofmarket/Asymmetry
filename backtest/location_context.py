from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from backtest.options_flow import add_options_flow_features


@dataclass(frozen=True)
class LocationContextConfig:
    tick_size: float = 0.25
    value_area_pct: float = 0.70
    min_profile_bars: int = 3
    shelf_count: int = 6
    shelf_min_volume_share: float = 0.05
    shelf_min_distance_points: float = 1.0
    volume_spike_lookback: int = 20
    volume_spike_min_periods: int = 5
    volume_spike_multiplier: float = 1.5
    dominance_threshold: float = 0.20
    availability_lag: str = "1min"
    session_timezone: str = "America/New_York"
    session_start_hour: int = 18
    session_start_minute: int = 0


@dataclass(frozen=True)
class LocationContextArtifacts:
    frame: pd.DataFrame
    report_md: str


def build_location_context(
    bars: pd.DataFrame,
    *,
    options_flow_features: pd.DataFrame | Path | str | None = None,
    orderflow_minute_stats: pd.DataFrame | Path | str | None = None,
    config: LocationContextConfig | None = None,
    progress_callback: Callable[[str], None] | None = None,
    pre_orderflow_checkpoint: Path | str | None = None,
    resume_pre_orderflow_checkpoint: bool = False,
) -> LocationContextArtifacts:
    """
    Build point-in-time profile/GEX/orderflow location context.

    Profile levels use only bars available up to each row. The output `time` is
    shifted by `availability_lag` so L2 replay consumes completed-bar context.
    """

    cfg = config or LocationContextConfig()
    _validate_config(cfg)
    checkpoint_path = Path(pre_orderflow_checkpoint) if pre_orderflow_checkpoint is not None else None
    if resume_pre_orderflow_checkpoint and checkpoint_path is not None and checkpoint_path.exists():
        out = pd.read_parquet(checkpoint_path)
        out["time"] = _datetime64_ns(out["time"])
        _emit_progress(progress_callback, f"Loaded pre-orderflow checkpoint: {checkpoint_path} ({len(out):,} rows)")
    else:
        out = _normalize_bars(bars, cfg)
        _emit_progress(progress_callback, f"Normalized bars: {len(out):,} rows")
        out = _add_session_profile_context(out, cfg, progress_callback=progress_callback)
        _emit_progress(progress_callback, "Built profile context")
        out = _add_volume_spike_context(out, cfg)
        _emit_progress(progress_callback, "Built volume-spike context")
        if options_flow_features is not None:
            out = add_options_flow_features(out, options_flow_features)
            _emit_progress(progress_callback, "Merged options-flow context")
        out = _add_options_ratio_context(out)
        if checkpoint_path is not None:
            checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            out.to_parquet(checkpoint_path, index=False)
            _emit_progress(progress_callback, f"Saved pre-orderflow checkpoint: {checkpoint_path}")
    if orderflow_minute_stats is not None:
        out = _merge_orderflow_context(out, orderflow_minute_stats, cfg)
        _emit_progress(progress_callback, "Merged orderflow context")
    else:
        out = _ensure_orderflow_columns(out)
    out = _finalize_location_aliases(out)

    lag = pd.Timedelta(cfg.availability_lag)
    out["source_bar_time"] = pd.to_datetime(out["time"], errors="coerce")
    out["time"] = out["source_bar_time"] + lag
    out["context_available_time"] = out["time"]
    out = out.sort_values("time", kind="stable").reset_index(drop=True)
    return LocationContextArtifacts(frame=out, report_md=render_location_context_report(out, cfg))


def write_location_context_artifacts(
    artifacts: LocationContextArtifacts,
    out_dir: Path | str,
    *,
    prefix: str = "location_context",
) -> dict[str, Path]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    paths = {
        "csv": out_path / f"{prefix}.csv",
        "report_md": out_path / f"{prefix}.md",
    }
    artifacts.frame.to_csv(paths["csv"], index=False)
    paths["report_md"].write_text(artifacts.report_md, encoding="utf-8")
    return paths


def render_location_context_report(frame: pd.DataFrame, cfg: LocationContextConfig) -> str:
    lines = [
        "# Location Context",
        "",
        "This artifact computes point-in-time VP/TPO shelves, value area, GEX walls, volume spikes, and bid/ask dominance. It is a context file, not a backtest or signal proof.",
        "",
        "## Config",
        "",
        f"- Tick size: {cfg.tick_size:g}",
        f"- Value area pct: {cfg.value_area_pct:.1%}",
        f"- Availability lag: `{cfg.availability_lag}`",
        f"- Session timezone: `{cfg.session_timezone}`",
        f"- Session start: {cfg.session_start_hour:02d}:{cfg.session_start_minute:02d}",
        f"- Shelf count: {cfg.shelf_count}",
        f"- Volume spike lookback: {cfg.volume_spike_lookback}",
        "",
        "## Coverage",
        "",
        f"- Rows: {len(frame):,}",
    ]
    if not frame.empty:
        lines.extend(
            [
                f"- Start: `{frame['time'].iloc[0]}`",
                f"- End: `{frame['time'].iloc[-1]}`",
                f"- Rows with profile POC: {int(frame['profile_poc'].notna().sum()):,}",
                f"- Rows with GEX wall: {int(frame.get('options_gamma_wall_strike', pd.Series(dtype=float)).notna().sum()):,}",
                f"- Volume spike rows: {int(frame['volume_spike'].fillna(False).astype(bool).sum()):,}",
            ]
        )
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Profile shelves and value area are calculated from bars seen so far in the session.",
            "- Options flow is merged backward by `options_available_time`.",
            "- Orderflow dominance is merged from supplied completed-minute stats.",
            "- Do not use final-session profile/TPO levels as intraday context.",
            "",
        ]
    )
    return "\n".join(lines)


def _normalize_bars(bars: pd.DataFrame, cfg: LocationContextConfig) -> pd.DataFrame:
    required = ["time", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in bars.columns]
    if missing:
        raise ValueError(f"location context bars missing required column(s): {', '.join(missing)}")
    out = bars.copy()
    out["time"] = pd.to_datetime(out["time"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["time", "high", "low", "close", "volume"])
    out = out.sort_values("time", kind="stable").reset_index(drop=True)
    session_time = _session_clock(out["time"], cfg.session_timezone)
    session_key = session_time.dt.normalize()
    starts_next_session = _clock_ge(session_time, int(cfg.session_start_hour), int(cfg.session_start_minute))
    session_key = session_key.mask(starts_next_session, session_key + pd.Timedelta(days=1))
    out["profile_session"] = session_key.dt.date.astype("string")
    return out


def _session_clock(times: pd.Series, timezone: str) -> pd.Series:
    dt = pd.to_datetime(times, errors="coerce")
    if getattr(dt.dt, "tz", None) is not None:
        return dt.dt.tz_convert(timezone).dt.tz_localize(None)
    return dt


def _clock_ge(times: pd.Series, hour: int, minute: int) -> pd.Series:
    return (times.dt.hour > hour) | ((times.dt.hour == hour) & (times.dt.minute >= minute))


def _add_session_profile_context(
    bars: pd.DataFrame,
    cfg: LocationContextConfig,
    *,
    progress_callback: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    total_rows = len(bars)
    total_sessions = int(bars["profile_session"].nunique(dropna=False)) if total_rows else 0
    processed_rows = 0
    for session_idx, (session_key, session) in enumerate(bars.groupby("profile_session", sort=False), start=1):
        session = session.reset_index(drop=True)
        rows.extend(_session_profile_rows_incremental(session, cfg))
        processed_rows += len(session)
        if (
            progress_callback is not None
            and (session_idx == 1 or session_idx % 25 == 0 or processed_rows == total_rows)
        ):
            progress_callback(
                "Profile context "
                f"{session_idx:,}/{total_sessions:,} sessions "
                f"({processed_rows:,}/{total_rows:,} rows), current={session_key}"
            )
    profile = pd.DataFrame(rows)
    return pd.concat([bars.reset_index(drop=True), profile.reset_index(drop=True)], axis=1)


def _session_profile_rows_incremental(session: pd.DataFrame, cfg: LocationContextConfig) -> list[dict[str, object]]:
    state = _IncrementalVolumeTpoProfile(float(cfg.tick_size))
    rows: list[dict[str, object]] = []
    for row in session.itertuples(index=False):
        state.update(low=float(row.low), high=float(row.high), volume=float(row.volume))
        rows.append(state.profile_row(current_price=float(row.close), cfg=cfg))
    return rows


def _profile_row(window: pd.DataFrame, cfg: LocationContextConfig) -> dict[str, object]:
    if len(window) < int(cfg.min_profile_bars):
        return _empty_profile_row()
    profile = _volume_tpo_profile(window, cfg)
    if profile.empty:
        return _empty_profile_row()
    prices = profile["price"].to_numpy(dtype=float)
    volume = profile["volume_at_price"].to_numpy(dtype=float)
    tpo = profile["tpo_count"].to_numpy(dtype=float)
    current_price = float(window["close"].iloc[-1])
    return _profile_row_from_arrays(prices, volume, tpo, current_price=current_price, cfg=cfg)


@dataclass
class _IncrementalVolumeTpoProfile:
    tick: float
    start_tick: int | None = None
    volume_at_tick: np.ndarray | None = None
    tpo_at_tick: np.ndarray | None = None
    bars_seen: int = 0

    def update(self, *, low: float, high: float, volume: float) -> None:
        low_tick = _floor_tick_index(low, self.tick)
        high_tick = _ceil_tick_index(high, self.tick)
        if low_tick is None or high_tick is None or high_tick < low_tick:
            return
        self._ensure_range(low_tick, high_tick)
        if self.start_tick is None or self.volume_at_tick is None or self.tpo_at_tick is None:
            return
        left = low_tick - self.start_tick
        right = high_tick - self.start_tick + 1
        count = max(1, high_tick - low_tick + 1)
        self.volume_at_tick[left:right] += float(volume) / count
        self.tpo_at_tick[left:right] += 1.0
        self.bars_seen += 1

    def profile_row(self, *, current_price: float, cfg: LocationContextConfig) -> dict[str, object]:
        if self.bars_seen < int(cfg.min_profile_bars):
            return _empty_profile_row()
        arrays = self._arrays()
        if arrays is None:
            return _empty_profile_row()
        prices, volume, tpo = arrays
        return _profile_row_from_arrays(prices, volume, tpo, current_price=current_price, cfg=cfg)

    def _ensure_range(self, low_tick: int, high_tick: int) -> None:
        if self.start_tick is None or self.volume_at_tick is None or self.tpo_at_tick is None:
            self.start_tick = int(low_tick)
            size = int(high_tick - low_tick + 1)
            self.volume_at_tick = np.zeros(size, dtype=float)
            self.tpo_at_tick = np.zeros(size, dtype=float)
            return

        old_start = int(self.start_tick)
        old_end = old_start + len(self.volume_at_tick) - 1
        new_start = min(old_start, int(low_tick))
        new_end = max(old_end, int(high_tick))
        if new_start == old_start and new_end == old_end:
            return

        size = int(new_end - new_start + 1)
        new_volume = np.zeros(size, dtype=float)
        new_tpo = np.zeros(size, dtype=float)
        offset = old_start - new_start
        new_volume[offset : offset + len(self.volume_at_tick)] = self.volume_at_tick
        new_tpo[offset : offset + len(self.tpo_at_tick)] = self.tpo_at_tick
        self.start_tick = new_start
        self.volume_at_tick = new_volume
        self.tpo_at_tick = new_tpo

    def _arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        if self.start_tick is None or self.volume_at_tick is None or self.tpo_at_tick is None:
            return None
        ticks = np.arange(self.start_tick, self.start_tick + len(self.volume_at_tick), dtype=float)
        prices = np.round(ticks * float(self.tick), 10)
        return prices, self.volume_at_tick, self.tpo_at_tick


def _profile_row_from_arrays(
    prices: np.ndarray,
    volume: np.ndarray,
    tpo: np.ndarray,
    *,
    current_price: float,
    cfg: LocationContextConfig,
) -> dict[str, object]:
    total_volume = float(np.nansum(volume))
    poc = _poc(prices, volume)
    tpo_poc = _poc(prices, tpo)
    val, vah = _value_area(prices, volume, value_area_pct=float(cfg.value_area_pct))
    tpo_val, tpo_vah = _value_area(prices, tpo, value_area_pct=float(cfg.value_area_pct))
    shelves = _shelves_from_arrays(prices, volume, current_price=current_price, config=cfg)
    shelf_below = _nearest_shelf(shelves, current_price, side="below")
    shelf_above = _nearest_shelf(shelves, current_price, side="above")
    strongest = shelves[0] if shelves else {}
    return {
        "profile_poc": poc,
        "profile_val": val,
        "profile_vah": vah,
        "profile_value_area_width_points": vah - val if np.isfinite(vah) and np.isfinite(val) else np.nan,
        "tpo_poc": tpo_poc,
        "tpo_val": tpo_val,
        "tpo_vah": tpo_vah,
        "profile_shelf_below": shelf_below.get("price", np.nan),
        "profile_shelf_below_volume_share": shelf_below.get("volume_share", np.nan),
        "profile_shelf_above": shelf_above.get("price", np.nan),
        "profile_shelf_above_volume_share": shelf_above.get("volume_share", np.nan),
        "profile_strongest_shelf": strongest.get("price", np.nan),
        "profile_strongest_shelf_volume_share": strongest.get("volume_share", np.nan),
        "profile_total_volume": total_volume,
        "profile_bin_count": int(len(prices)),
        "profile_shelf_count": int(len(shelves)),
    }


def _volume_tpo_profile(window: pd.DataFrame, cfg: LocationContextConfig) -> pd.DataFrame:
    tick = float(cfg.tick_size)
    lo = _floor_to_tick(pd.to_numeric(window["low"], errors="coerce").min(), tick)
    hi = _ceil_to_tick(pd.to_numeric(window["high"], errors="coerce").max(), tick)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi < lo:
        return pd.DataFrame()
    prices = np.round(np.arange(lo, hi + tick / 2.0, tick), 10)
    volume = np.zeros(len(prices), dtype=float)
    tpo = np.zeros(len(prices), dtype=float)
    for row in window.itertuples(index=False):
        low = _floor_to_tick(float(row.low), tick)
        high = _ceil_to_tick(float(row.high), tick)
        mask = (prices >= low) & (prices <= high)
        count = int(mask.sum())
        if count <= 0:
            continue
        row_volume = float(row.volume)
        volume[mask] += row_volume / count
        tpo[mask] += 1.0
    return pd.DataFrame({"price": prices, "volume_at_price": volume, "tpo_count": tpo})


def _shelves(profile: pd.DataFrame, *, current_price: float, config: LocationContextConfig) -> list[dict[str, float]]:
    volume = profile["volume_at_price"].to_numpy(dtype=float)
    prices = profile["price"].to_numpy(dtype=float)
    return _shelves_from_arrays(prices, volume, current_price=current_price, config=config)


def _shelves_from_arrays(
    prices: np.ndarray,
    volume: np.ndarray,
    *,
    current_price: float,
    config: LocationContextConfig,
) -> list[dict[str, float]]:
    total = float(np.nansum(volume))
    if total <= 0.0:
        return []
    candidates: list[dict[str, float]] = []
    left = np.concatenate(([float("-inf")], volume[:-1]))
    right = np.concatenate((volume[1:], [float("-inf")]))
    shares = volume / total
    local_maxima = np.flatnonzero(
        np.logical_and.reduce(
            [
                volume >= left,
                volume >= right,
                shares >= float(config.shelf_min_volume_share),
            ]
        )
    )
    for idx in local_maxima:
        vol = float(volume[idx])
        if vol > 0.0:
            candidates.append(
                {
                    "price": float(prices[idx]),
                    "volume": vol,
                    "volume_share": float(shares[idx]),
                    "distance_points": float(prices[idx] - current_price),
                }
            )
    if not candidates:
        order = np.argsort(volume)[::-1]
        for idx in order[: int(config.shelf_count)]:
            if volume[idx] <= 0.0:
                continue
            candidates.append(
                {
                    "price": float(prices[idx]),
                    "volume": float(volume[idx]),
                    "volume_share": float(volume[idx] / total),
                    "distance_points": float(prices[idx] - current_price),
                }
            )
    return _dedupe_shelves(candidates, config)


def _dedupe_shelves(candidates: list[dict[str, float]], config: LocationContextConfig) -> list[dict[str, float]]:
    chosen: list[dict[str, float]] = []
    min_distance = float(config.shelf_min_distance_points)
    for item in sorted(candidates, key=lambda row: row["volume"], reverse=True):
        if all(abs(item["price"] - prior["price"]) >= min_distance for prior in chosen):
            chosen.append(item)
        if len(chosen) >= int(config.shelf_count):
            break
    return chosen


def _nearest_shelf(shelves: list[dict[str, float]], current_price: float, *, side: str) -> dict[str, float]:
    if side == "below":
        candidates = [item for item in shelves if item["price"] <= current_price]
        return max(candidates, key=lambda item: item["price"], default={})
    candidates = [item for item in shelves if item["price"] >= current_price]
    return min(candidates, key=lambda item: item["price"], default={})


def _poc(prices: np.ndarray, weights: np.ndarray) -> float:
    if len(prices) == 0 or len(weights) == 0 or np.nansum(weights) <= 0.0:
        return np.nan
    return float(prices[int(np.nanargmax(weights))])


def _value_area(prices: np.ndarray, weights: np.ndarray, *, value_area_pct: float) -> tuple[float, float]:
    total = float(np.nansum(weights))
    if len(prices) == 0 or total <= 0.0:
        return np.nan, np.nan
    target = total * float(value_area_pct)
    poc_idx = int(np.nanargmax(weights))
    left_idx = poc_idx
    right_idx = poc_idx
    current = float(weights[poc_idx])
    n_weights = len(weights)
    while current < target and (left_idx > 0 or right_idx + 1 < n_weights):
        left_weight = weights[left_idx - 1] if left_idx > 0 else -np.inf
        right_weight = weights[right_idx + 1] if right_idx + 1 < n_weights else -np.inf
        if left_weight >= right_weight:
            left_idx -= 1
            current += float(weights[left_idx])
        else:
            right_idx += 1
            current += float(weights[right_idx])
    return float(prices[left_idx]), float(prices[right_idx])

def _empty_profile_row() -> dict[str, object]:
    return {
        "profile_poc": np.nan,
        "profile_val": np.nan,
        "profile_vah": np.nan,
        "profile_value_area_width_points": np.nan,
        "tpo_poc": np.nan,
        "tpo_val": np.nan,
        "tpo_vah": np.nan,
        "profile_shelf_below": np.nan,
        "profile_shelf_below_volume_share": np.nan,
        "profile_shelf_above": np.nan,
        "profile_shelf_above_volume_share": np.nan,
        "profile_strongest_shelf": np.nan,
        "profile_strongest_shelf_volume_share": np.nan,
        "profile_total_volume": np.nan,
        "profile_bin_count": 0,
        "profile_shelf_count": 0,
    }


def _add_volume_spike_context(frame: pd.DataFrame, cfg: LocationContextConfig) -> pd.DataFrame:
    out = frame.copy()
    volume = pd.to_numeric(out["volume"], errors="coerce")
    baseline = (
        volume.groupby(out["profile_session"], sort=False)
        .transform(lambda s: s.shift(1).rolling(int(cfg.volume_spike_lookback), min_periods=int(cfg.volume_spike_min_periods)).mean())
    )
    out["volume_spike_baseline"] = baseline
    out["volume_spike_ratio"] = np.where(baseline.gt(0.0), volume / baseline, np.nan)
    out["volume_spike"] = out["volume_spike_ratio"].ge(float(cfg.volume_spike_multiplier))
    return out


def _add_options_ratio_context(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    call_oi = pd.to_numeric(out.get("options_call_oi", pd.Series(np.nan, index=out.index)), errors="coerce")
    put_oi = pd.to_numeric(out.get("options_put_oi", pd.Series(np.nan, index=out.index)), errors="coerce")
    if "options_put_call_oi_ratio" not in out.columns:
        out["options_put_call_oi_ratio"] = np.where(call_oi.gt(0.0), put_oi / call_oi, np.nan)
    out["options_call_put_oi_ratio"] = np.where(put_oi.gt(0.0), call_oi / put_oi, np.nan)
    return out


def _merge_orderflow_context(
    frame: pd.DataFrame,
    orderflow_minute_stats: pd.DataFrame | Path | str,
    cfg: LocationContextConfig,
) -> pd.DataFrame:
    out = frame.copy()
    flow = pd.read_csv(orderflow_minute_stats) if isinstance(orderflow_minute_stats, (str, Path)) else orderflow_minute_stats.copy()
    if flow.empty or "minute" not in flow.columns:
        return _ensure_orderflow_columns(out)
    out["time"] = _datetime64_ns(out["time"])
    flow["minute"] = _datetime64_ns(flow["minute"])
    flow = flow.dropna(subset=["minute"]).sort_values("minute", kind="stable")
    if flow.empty:
        return _ensure_orderflow_columns(out, cfg)
    out = pd.merge_asof(
        out.sort_values("time", kind="stable"),
        flow,
        left_on="time",
        right_on="minute",
        direction="backward",
        suffixes=("", "_orderflow"),
    )
    return _ensure_orderflow_columns(out, cfg)


def _ensure_orderflow_columns(frame: pd.DataFrame, cfg: LocationContextConfig | None = None) -> pd.DataFrame:
    out = frame.copy()
    threshold = float((cfg or LocationContextConfig()).dominance_threshold)
    raw_share = pd.to_numeric(out.get("raw_b_minus_a_trade_size_share", pd.Series(np.nan, index=out.index)), errors="coerce")
    book_imbalance = pd.to_numeric(out.get("median_top_book_imbalance", pd.Series(np.nan, index=out.index)), errors="coerce")
    bid_size = pd.to_numeric(out.get("mean_bid_size", pd.Series(np.nan, index=out.index)), errors="coerce")
    ask_size = pd.to_numeric(out.get("mean_ask_size", pd.Series(np.nan, index=out.index)), errors="coerce")
    size_denom = bid_size + ask_size
    size_imbalance = pd.Series(np.where(size_denom.gt(0.0), (bid_size - ask_size) / size_denom, np.nan), index=out.index)
    dominance = raw_share.where(raw_share.notna(), book_imbalance).where(lambda s: s.notna(), size_imbalance)
    out["orderflow_bid_ask_dominance"] = dominance
    out["orderflow_bid_dominant"] = dominance.ge(threshold)
    out["orderflow_ask_dominant"] = dominance.le(-threshold)
    return out


def _finalize_location_aliases(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["profile_lower"] = _nearest_lower(out, ["profile_shelf_below", "profile_val", "tpo_val"])
    out["profile_upper"] = _nearest_upper(out, ["profile_shelf_above", "profile_vah", "tpo_vah"])
    out["vp_val"] = out["profile_val"]
    out["vp_vah"] = out["profile_vah"]
    out["vp_poc"] = out["profile_poc"]
    return out


def _nearest_lower(frame: pd.DataFrame, cols: list[str]) -> pd.Series:
    close = pd.to_numeric(frame["close"], errors="coerce")
    candidates = []
    for col in cols:
        if col in frame.columns:
            value = pd.to_numeric(frame[col], errors="coerce")
            candidates.append(value.where(value.le(close)))
    if not candidates:
        return pd.Series(np.nan, index=frame.index)
    return pd.concat(candidates, axis=1).max(axis=1)


def _nearest_upper(frame: pd.DataFrame, cols: list[str]) -> pd.Series:
    close = pd.to_numeric(frame["close"], errors="coerce")
    candidates = []
    for col in cols:
        if col in frame.columns:
            value = pd.to_numeric(frame[col], errors="coerce")
            candidates.append(value.where(value.ge(close)))
    if not candidates:
        return pd.Series(np.nan, index=frame.index)
    return pd.concat(candidates, axis=1).min(axis=1)


def _floor_to_tick(value: float, tick: float) -> float:
    return np.floor(float(value) / tick) * tick if np.isfinite(value) and tick > 0.0 else np.nan


def _ceil_to_tick(value: float, tick: float) -> float:
    return np.ceil(float(value) / tick) * tick if np.isfinite(value) and tick > 0.0 else np.nan


def _floor_tick_index(value: float, tick: float) -> int | None:
    if not np.isfinite(value) or tick <= 0.0:
        return None
    return int(np.floor(float(value) / tick))


def _ceil_tick_index(value: float, tick: float) -> int | None:
    if not np.isfinite(value) or tick <= 0.0:
        return None
    return int(np.ceil(float(value) / tick))


def _datetime64_ns(values: pd.Series) -> pd.Series:
    out = pd.to_datetime(values, errors="coerce")
    if getattr(out.dt, "tz", None) is not None:
        out = out.dt.tz_convert("UTC").dt.tz_localize(None)
    return out.astype("datetime64[ns]")


def _emit_progress(callback: Callable[[str], None] | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _validate_config(cfg: LocationContextConfig) -> None:
    if cfg.tick_size <= 0.0:
        raise ValueError("tick_size must be positive")
    if not 0.0 < cfg.value_area_pct <= 1.0:
        raise ValueError("value_area_pct must be in (0, 1]")
    if cfg.min_profile_bars < 1:
        raise ValueError("min_profile_bars must be positive")
    if cfg.shelf_count < 1:
        raise ValueError("shelf_count must be positive")
    if cfg.volume_spike_lookback < 1:
        raise ValueError("volume_spike_lookback must be positive")
    if not 0 <= int(cfg.session_start_hour) <= 23:
        raise ValueError("session_start_hour must be between 0 and 23")
    if not 0 <= int(cfg.session_start_minute) <= 59:
        raise ValueError("session_start_minute must be between 0 and 59")


__all__ = [
    "LocationContextArtifacts",
    "LocationContextConfig",
    "build_location_context",
    "render_location_context_report",
    "write_location_context_artifacts",
]
