from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class LocalExtreme:
    """A confirmed local top or bottom.

    `index` is where the top/bottom actually occurred. `confirmed_index` is the
    first bar where the strategy could know about it, so features built from this
    class avoid repainting.
    """

    type: int  # 1 = top, -1 = bottom
    price: float
    index: int
    timestamp: pd.Timestamp
    confirmed_index: int
    confirmed_timestamp: pd.Timestamp


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def directional_change_extremes(
    data: pd.DataFrame,
    atr_period: int = 78,
    atr_multiplier: float = 1.0,
) -> list[LocalExtreme]:
    """Find non-repainting alternating extremes with an ATR threshold.

    This implements the directional-change idea from the transcript: after a
    confirmed bottom we track the highest high until price reverses by ATR;
    after a confirmed top we track the lowest low until price reverses by ATR.
    """

    required = {"time", "high", "low", "close"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"market structure requires columns: {sorted(missing)}")

    if atr_period < 2:
        atr_period = 2
    atr_multiplier = max(float(atr_multiplier), 0.01)

    df = data.reset_index(drop=True).copy()
    times = pd.to_datetime(df["time"])
    atr = _true_range(df).rolling(window=atr_period, min_periods=atr_period).mean()

    extremes: list[LocalExtreme] = []
    mode = 0  # 0 unknown, 1 looking for top, -1 looking for bottom
    pending_high = np.nan
    pending_high_idx = -1
    pending_low = np.nan
    pending_low_idx = -1

    def append_extreme(extreme_type: int, price: float, idx: int, confirmed_idx: int) -> None:
        if idx < 0 or confirmed_idx < 0:
            return
        if extremes and extremes[-1].type == extreme_type:
            return
        extremes.append(
            LocalExtreme(
                type=int(extreme_type),
                price=float(price),
                index=int(idx),
                timestamp=pd.Timestamp(times.iloc[idx]),
                confirmed_index=int(confirmed_idx),
                confirmed_timestamp=pd.Timestamp(times.iloc[confirmed_idx]),
            )
        )

    for i, row in df.iterrows():
        threshold = atr.iloc[i]
        if not np.isfinite(threshold):
            continue

        high = float(row["high"])
        low = float(row["low"])
        threshold = float(threshold) * atr_multiplier

        if pending_high_idx < 0:
            pending_high = high
            pending_high_idx = int(i)
            pending_low = low
            pending_low_idx = int(i)
            continue

        if mode == 0:
            if high > pending_high:
                pending_high = high
                pending_high_idx = int(i)
            if low < pending_low:
                pending_low = low
                pending_low_idx = int(i)

            if high >= pending_low + threshold:
                append_extreme(-1, pending_low, pending_low_idx, int(i))
                mode = 1
                pending_high = high
                pending_high_idx = int(i)
            elif low <= pending_high - threshold:
                append_extreme(1, pending_high, pending_high_idx, int(i))
                mode = -1
                pending_low = low
                pending_low_idx = int(i)
            continue

        if mode == 1:
            if high > pending_high:
                pending_high = high
                pending_high_idx = int(i)
                continue

            if low <= pending_high - threshold:
                append_extreme(1, pending_high, pending_high_idx, int(i))
                mode = -1
                pending_low = low
                pending_low_idx = int(i)
            continue

        if mode == -1:
            if low < pending_low:
                pending_low = low
                pending_low_idx = int(i)
                continue

            if high >= pending_low + threshold:
                append_extreme(-1, pending_low, pending_low_idx, int(i))
                mode = 1
                pending_high = high
                pending_high_idx = int(i)

    return extremes


def _strongest_between(
    extremes: list[LocalExtreme],
    start_idx: int,
    end_idx: int,
    extreme_type: int,
    confirmed_index: int,
    confirmed_timestamp: pd.Timestamp,
) -> tuple[LocalExtreme, int] | None:
    candidates = [
        (idx, extremes[idx])
        for idx in range(start_idx + 1, end_idx)
        if extremes[idx].type == extreme_type
    ]
    if not candidates:
        return None

    if extreme_type == 1:
        chosen_idx, chosen = max(candidates, key=lambda item: item[1].price)
    else:
        chosen_idx, chosen = min(candidates, key=lambda item: item[1].price)

    return (
        LocalExtreme(
            type=chosen.type,
            price=chosen.price,
            index=chosen.index,
            timestamp=chosen.timestamp,
            confirmed_index=int(confirmed_index),
            confirmed_timestamp=pd.Timestamp(confirmed_timestamp),
        ),
        chosen_idx,
    )


def _upgrade_level(prior_level: list[LocalExtreme]) -> list[LocalExtreme]:
    """Upgrade surrounded highs/lows into the next significance level."""

    upgraded: list[LocalExtreme] = []
    upgraded_source_positions: list[int] = []
    if len(prior_level) < 5:
        return upgraded

    for current_pos in range(4, len(prior_level)):
        current = prior_level[current_pos]
        candidate = prior_level[current_pos - 2]
        earlier = prior_level[current_pos - 4]

        if current.type != candidate.type or earlier.type != candidate.type:
            continue

        if candidate.type == 1:
            qualifies = candidate.price >= current.price and candidate.price >= earlier.price
        else:
            qualifies = candidate.price <= current.price and candidate.price <= earlier.price
        if not qualifies:
            continue

        promoted = LocalExtreme(
            type=candidate.type,
            price=candidate.price,
            index=candidate.index,
            timestamp=candidate.timestamp,
            confirmed_index=current.confirmed_index,
            confirmed_timestamp=current.confirmed_timestamp,
        )

        if upgraded and upgraded[-1].type == promoted.type:
            last_pos = upgraded_source_positions[-1]
            opposite = _strongest_between(
                prior_level,
                last_pos,
                current_pos - 2,
                -promoted.type,
                promoted.confirmed_index,
                promoted.confirmed_timestamp,
            )
            if opposite is not None and (not upgraded or upgraded[-1].type != opposite[0].type):
                opposite_extreme, opposite_pos = opposite
                upgraded.append(opposite_extreme)
                upgraded_source_positions.append(opposite_pos)

        if not upgraded or upgraded[-1].type != promoted.type:
            upgraded.append(promoted)
            upgraded_source_positions.append(current_pos - 2)

    return upgraded


def hierarchical_extremes(
    data: pd.DataFrame,
    levels: int = 3,
    atr_period: int = 78,
    atr_multiplier: float = 1.0,
) -> list[list[LocalExtreme]]:
    """Return level-0 directional-change extremes plus upgraded levels."""

    level_count = max(1, int(levels))
    all_levels: list[list[LocalExtreme]] = [
        directional_change_extremes(data, atr_period=atr_period, atr_multiplier=atr_multiplier)
    ]

    for _ in range(1, level_count):
        all_levels.append(_upgrade_level(all_levels[-1]))

    return all_levels


def add_market_structure_features(
    data: pd.DataFrame,
    levels: int = 3,
    atr_period: int = 78,
    atr_multiplier: float = 1.0,
) -> pd.DataFrame:
    """Append confirmed market-structure hierarchy columns to an OHLC dataframe."""

    df = data.reset_index(drop=True).copy()
    all_levels = hierarchical_extremes(
        df,
        levels=levels,
        atr_period=atr_period,
        atr_multiplier=atr_multiplier,
    )

    close = df["close"].astype(float)
    for level, extremes in enumerate(all_levels):
        prefix = f"ms_l{level}"
        last_type = pd.Series(np.nan, index=df.index, dtype=float)
        last_price = pd.Series(np.nan, index=df.index, dtype=float)
        last_top_price = pd.Series(np.nan, index=df.index, dtype=float)
        last_bottom_price = pd.Series(np.nan, index=df.index, dtype=float)
        last_confirmed_index = pd.Series(np.nan, index=df.index, dtype=float)
        new_top = pd.Series(False, index=df.index, dtype=bool)
        new_bottom = pd.Series(False, index=df.index, dtype=bool)

        for extreme in extremes:
            idx = extreme.confirmed_index
            if idx < 0 or idx >= len(df):
                continue
            last_type.iloc[idx] = extreme.type
            last_price.iloc[idx] = extreme.price
            last_confirmed_index.iloc[idx] = idx
            if extreme.type == 1:
                last_top_price.iloc[idx] = extreme.price
                new_top.iloc[idx] = True
            else:
                last_bottom_price.iloc[idx] = extreme.price
                new_bottom.iloc[idx] = True

        last_type = last_type.ffill()
        last_price = last_price.ffill()
        last_top_price = last_top_price.ffill()
        last_bottom_price = last_bottom_price.ffill()
        last_confirmed_index = last_confirmed_index.ffill()

        df[f"{prefix}_last_type"] = last_type
        df[f"{prefix}_last_price"] = last_price
        df[f"{prefix}_last_top_price"] = last_top_price
        df[f"{prefix}_last_bottom_price"] = last_bottom_price
        df[f"{prefix}_bars_since_extreme"] = (
            pd.Series(np.arange(len(df)), index=df.index) - last_confirmed_index
        )
        df[f"{prefix}_swing_direction"] = np.where(
            last_type.eq(-1),
            1,
            np.where(last_type.eq(1), -1, 0),
        )
        df[f"{prefix}_dist_to_support"] = close - last_bottom_price
        df[f"{prefix}_dist_to_resistance"] = last_top_price - close
        df[f"{prefix}_new_top_confirmed"] = new_top
        df[f"{prefix}_new_bottom_confirmed"] = new_bottom
        df[f"{prefix}_extreme_count"] = len(extremes)

    return df
