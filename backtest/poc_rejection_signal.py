from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.signal_export import DEFAULT_CONTEXT_COLUMNS, prepare_signal_export_frame


DEFAULT_POC_REJECTION_FEATURE_COLUMNS = (
    "poc_rejection_score",
    "reference_level_price",
    "touch_open_distance_points",
    "entry_to_level_points",
    "prior_rth_poc",
    "prior_rth_vah",
    "prior_rth_val",
)

DEFAULT_POC_REJECTION_CONTEXT_COLUMNS = (
    *DEFAULT_CONTEXT_COLUMNS,
    "reference_level_type",
    "approach_direction",
)


@dataclass(frozen=True)
class PocRejectionSignalConfig:
    tick_size: float = 1.0  # 1-pt price bins for 1-minute bar volume profile approximation
    value_area_pct: float = 0.70
    max_touch_open_distance_points: float = 8.0
    target_distance_fraction: float = 0.50
    stop_level_breach_points: float = 5.0
    rth_start: str = "09:30"
    rth_end: str = "16:00"
    touch_window_start: str = "09:31"
    touch_window_end: str = "10:15"
    max_open_to_level_range_mult: float = 1.5


def build_poc_rejection_signal_export(
    data: pd.DataFrame,
    *,
    config: PocRejectionSignalConfig | None = None,
    signal_col_name: str = "candidate_signal",
    feature_cols: Iterable[str] = DEFAULT_POC_REJECTION_FEATURE_COLUMNS,
    context_cols: Iterable[str] = DEFAULT_POC_REJECTION_CONTEXT_COLUMNS,
) -> pd.DataFrame:
    signal_frame = build_poc_rejection_signal_frame(data, config=config)
    return prepare_signal_export_frame(
        signal_frame,
        signal_col_name=signal_col_name,
        feature_cols=feature_cols,
        context_cols=context_cols,
    )


def build_poc_rejection_signal_frame(
    data: pd.DataFrame,
    *,
    config: PocRejectionSignalConfig | None = None,
) -> pd.DataFrame:
    cfg = config or PocRejectionSignalConfig()
    df = _base_ohlcv_frame(data)

    minutes = df["time"].dt.hour * 60 + df["time"].dt.minute
    rth_start_min = _parse_hhmm(cfg.rth_start)
    rth_end_min = _parse_hhmm(cfg.rth_end)
    touch_start_min = _parse_hhmm(cfg.touch_window_start)
    touch_end_min = _parse_hhmm(cfg.touch_window_end)

    rth_mask = minutes.ge(rth_start_min) & minutes.le(rth_end_min)
    rth = df.loc[rth_mask].copy()

    # 1. Compute prior RTH session POC, VAH, VAL, and range strictly from completed prior sessions
    prior_profiles = _compute_prior_session_profiles(
        rth,
        bin_size=float(cfg.tick_size),
        value_area_pct=float(cfg.value_area_pct),
    )

    session = df["time"].dt.date
    prof_by_session = prior_profiles.set_index("session")
    prior_poc = session.map(prof_by_session["prior_poc"])
    prior_vah = session.map(prof_by_session["prior_vah"])
    prior_val = session.map(prof_by_session["prior_val"])
    prior_range = session.map(prof_by_session["prior_range"])

    # 09:30 bar open and close per session
    bars_930 = df.loc[minutes.eq(rth_start_min)]
    open_930_map = bars_930.groupby(bars_930["time"].dt.date, sort=True)["open"].first()
    close_930_map = bars_930.groupby(bars_930["time"].dt.date, sort=True)["close"].first()
    open_930 = session.map(open_930_map)
    close_930 = session.map(close_930_map)

    n = len(df)
    candidate_signal = np.zeros(n, dtype=float)
    poc_rejection_score = np.zeros(n, dtype=float)
    ref_level_price = np.full(n, np.nan, dtype=float)
    touch_open_dist = np.full(n, np.nan, dtype=float)
    entry_to_level_dist = np.full(n, np.nan, dtype=float)
    stop_pts = np.full(n, np.nan, dtype=float)
    target_pts = np.full(n, np.nan, dtype=float)
    ref_level_type = np.full(n, "none", dtype=object)
    approach_dir_col = np.full(n, "none", dtype=object)

    open_arr = df["open"].to_numpy(dtype=float)
    high_arr = df["high"].to_numpy(dtype=float)
    low_arr = df["low"].to_numpy(dtype=float)
    close_arr = df["close"].to_numpy(dtype=float)
    min_arr = minutes.to_numpy(dtype=int)
    sess_arr = session.to_numpy()
    poc_arr = prior_poc.to_numpy(dtype=float)
    vah_arr = prior_vah.to_numpy(dtype=float)
    val_arr = prior_val.to_numpy(dtype=float)
    rng_arr = prior_range.to_numpy(dtype=float)
    o930_arr = open_930.to_numpy(dtype=float)
    c930_arr = close_930.to_numpy(dtype=float)

    # Iterate session by session over the touch window (09:31..10:15)
    # Signal is emitted on the reject confirmation bar (t + 1) so entry at next bar open is t + 2
    used_levels_by_session: dict[object, set[str]] = {}
    for i in range(n - 2):
        m = min_arr[i]
        if m < touch_start_min or m > touch_end_min:
            continue
        cur_sess = sess_arr[i]
        if sess_arr[i + 1] != cur_sess or sess_arr[i + 2] != cur_sess:
            continue
        c930 = c930_arr[i]
        o930 = o930_arr[i]
        prng = rng_arr[i]
        if not np.isfinite(c930) or not np.isfinite(o930) or not np.isfinite(prng) or prng <= 0:
            continue

        used = used_levels_by_session.setdefault(cur_sess, set())
        # Check levels in order: POC, VAH, VAL
        levels = (("POC", poc_arr[i]), ("VAH", vah_arr[i]), ("VAL", val_arr[i]))
        for lvl_name, lvl in levels:
            if lvl_name in used or not np.isfinite(lvl):
                continue
            # Proximity at 09:30 open: within 1.5x prior session range
            if abs(o930 - lvl) > float(cfg.max_open_to_level_range_mult) * prng:
                continue
            # Touch criterion at bar i: low <= level <= high and |open - level| <= 8 pts
            if not (low_arr[i] <= lvl <= high_arr[i]):
                continue
            dist_open = abs(open_arr[i] - lvl)
            if dist_open > float(cfg.max_touch_open_distance_points):
                continue
            # Approach direction: move from 09:30 close to touch bar midpoint/close
            move_from_930 = ((high_arr[i] + low_arr[i]) * 0.5) - c930
            if move_from_930 == 0.0:
                continue
            # If move_from_930 > 0, price approached from below (going up into level) -> fade is SHORT (-1)
            # Reject confirmation bar (i + 1) must close on the fade side of the level:
            # For approaching from below (going up), reject bar (i + 1) closes < level -> SHORT (-1)
            # For approaching from above (going down), reject bar (i + 1) closes > level -> LONG (+1)
            if move_from_930 > 0.0 and close_arr[i + 1] < lvl:
                fade_dir = -1.0
                app_label = "from_below"
            elif move_from_930 < 0.0 and close_arr[i + 1] > lvl:
                fade_dir = 1.0
                app_label = "from_above"
            else:
                continue

            # Deduplicate first touch of this level for the session
            used.add(lvl_name)

            # Signal is recorded at confirmation bar (i + 1), entry at open of (i + 2)
            sig_idx = i + 1
            if candidate_signal[sig_idx] != 0.0:
                continue
            entry_px = open_arr[i + 2]
            dist_entry_lvl = abs(entry_px - lvl)

            candidate_signal[sig_idx] = fade_dir
            poc_rejection_score[sig_idx] = fade_dir * (float(cfg.max_touch_open_distance_points) - dist_open + 1.0)
            ref_level_price[sig_idx] = lvl
            touch_open_dist[sig_idx] = dist_open
            entry_to_level_dist[sig_idx] = dist_entry_lvl
            ref_level_type[sig_idx] = lvl_name
            approach_dir_col[sig_idx] = app_label
            # Stop: level breach by > 5 pts from entry
            stop_pts[sig_idx] = dist_entry_lvl + float(cfg.stop_level_breach_points)
            # Target: 50% of distance from entry to reference level (or min 4 pts if entry is right near level)
            target_pts[sig_idx] = max(4.0, float(cfg.target_distance_fraction) * max(dist_entry_lvl, dist_open))
            break

    direction = pd.Series("flat", index=df.index, dtype="object")
    direction.loc[candidate_signal > 0.0] = "long"
    direction.loc[candidate_signal < 0.0] = "short"

    out = df.copy()
    out["signal"] = candidate_signal
    out["signal_type"] = np.where(candidate_signal != 0.0, "poc_rejection", "")
    out["candidate_signal"] = candidate_signal
    out["direction"] = direction
    out["poc_rejection_score"] = poc_rejection_score
    out["reference_level_price"] = ref_level_price
    out["touch_open_distance_points"] = touch_open_dist
    out["entry_to_level_points"] = entry_to_level_dist
    out["prior_rth_poc"] = prior_poc
    out["prior_rth_vah"] = prior_vah
    out["prior_rth_val"] = prior_val
    out["stop_points"] = stop_pts
    out["target_points"] = target_pts
    out["reference_level_type"] = ref_level_type
    out["approach_direction"] = approach_dir_col
    out["session_bucket"] = "rth_open"
    return out


def _compute_prior_session_profiles(
    rth: pd.DataFrame,
    *,
    bin_size: float = 1.0,
    value_area_pct: float = 0.70,
) -> pd.DataFrame:
    if rth.empty:
        return pd.DataFrame(columns=["session", "prior_poc", "prior_vah", "prior_val", "prior_range"])

    session_col = rth["time"].dt.date
    rows: list[dict[str, object]] = []
    for sess, grp in rth.groupby(session_col, sort=True):
        s_high = float(grp["high"].max())
        s_low = float(grp["low"].min())
        s_range = max(0.0, s_high - s_low)
        typical = (grp["high"] + grp["low"] + grp["close"]) / 3.0
        bins = np.round(typical / bin_size) * bin_size
        vol_by_price = grp.groupby(bins, sort=True)["volume"].sum()
        if vol_by_price.empty or float(vol_by_price.sum()) <= 0.0:
            rows.append({"session": sess, "poc": np.nan, "vah": np.nan, "val": np.nan, "range": s_range})
            continue
        prices = vol_by_price.index.to_numpy(dtype=float)
        weights = vol_by_price.to_numpy(dtype=float)
        poc_idx = int(np.argmax(weights))
        poc = float(prices[poc_idx])
        val, vah = _value_area_two_pointer(prices, weights, value_area_pct=value_area_pct)
        rows.append({"session": sess, "poc": poc, "vah": vah, "val": val, "range": s_range})

    daily = pd.DataFrame(rows)
    daily["prior_poc"] = daily["poc"].shift(1)
    daily["prior_vah"] = daily["vah"].shift(1)
    daily["prior_val"] = daily["val"].shift(1)
    daily["prior_range"] = daily["range"].shift(1)
    return daily.loc[:, ["session", "prior_poc", "prior_vah", "prior_val", "prior_range"]]


def _value_area_two_pointer(
    prices: np.ndarray,
    weights: np.ndarray,
    *,
    value_area_pct: float,
) -> tuple[float, float]:
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


def _base_ohlcv_frame(data: pd.DataFrame) -> pd.DataFrame:
    required = ["time", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in data.columns]
    if missing:
        raise ValueError(f"Missing required OHLCV columns: {missing}")

    work = data.copy()
    if "symbol" in work.columns:
        from main_backtest import select_continuous_outright_contract

        work = select_continuous_outright_contract(work, method="prior_session_volume")

    df = work.loc[:, required].copy()
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    df = df.dropna(subset=["time"]).sort_values("time", kind="stable").reset_index(drop=True)
    return df


def _parse_hhmm(value: str) -> int:
    hour, minute = str(value).split(":", 1)
    return int(hour) * 60 + int(minute)
