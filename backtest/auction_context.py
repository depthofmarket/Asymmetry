from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.point_in_time import clock_ge


def _time_mask(df: pd.DataFrame, start: str, end: str) -> pd.Series:
    hour_min = df["hour_min"].astype(str)
    return hour_min.ge(start) & hour_min.lt(end)


def _first_valid(series: pd.Series):
    series = series.dropna()
    return series.iloc[0] if len(series) else np.nan


def _last_valid(series: pd.Series):
    series = series.dropna()
    return series.iloc[-1] if len(series) else np.nan


def add_futures_auction_context(
    data: pd.DataFrame,
    *,
    rth_start: str = "09:30",
    rth_end: str = "16:00",
    initial_balance_end: str = "10:30",
    atr_col: str = "atr",
) -> pd.DataFrame:
    """
    Add futures-only auction context features with no lookahead leakage.

    The features are intentionally descriptive rather than prescriptive:
    prior RTH range, gap/open location, overnight inventory, and live initial
    balance state. Strategy candidates can later decide which parts matter.
    """
    required = {"time", "open", "high", "low", "close", "volume"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"auction context requires columns: {sorted(missing)}")

    df = data.copy()
    df["time_dt"] = pd.to_datetime(df["time"])
    if "date_str" not in df.columns:
        df["date_str"] = df["time_dt"].dt.strftime("%Y-%m-%d")
    if "hour_min" not in df.columns:
        df["hour_min"] = df["time_dt"].dt.strftime("%H:%M")

    generated_cols = {
        "rth_open", "rth_high", "rth_low", "rth_close", "rth_volume", "rth_range",
        "prior_rth_open", "prior_rth_high", "prior_rth_low", "prior_rth_close",
        "prior_rth_volume", "prior_rth_range", "overnight_open", "overnight_high",
        "overnight_low", "overnight_close", "overnight_volume", "overnight_range",
        "gap_points", "gap_prior_range_pct", "open_location_prior_range",
        "open_above_prior_high", "open_below_prior_low", "open_inside_prior_range",
        "overnight_inventory_points", "overnight_inventory_direction", "gap_atr",
        "overnight_inventory_atr", "overnight_range_atr", "prior_rth_range_atr",
        "rth_bar_number", "rth_minutes_since_open", "rth_session_high_so_far",
        "rth_session_low_so_far", "rth_session_range_so_far", "rth_range_so_far_atr",
        "ib_high_so_far", "ib_low_so_far", "ib_range_so_far", "ib_high", "ib_low",
        "ib_range", "ib_range_atr", "above_ib_high", "below_ib_low", "inside_ib",
        "gap_inventory_alignment", "open_context",
    }
    # Make the transform idempotent for research scripts that pass an already
    # preprocessed frame back through auction-context enrichment.
    df = df.drop(columns=[col for col in generated_cols if col in df.columns], errors="ignore")

    session_dates = pd.Index(sorted(df["date_str"].unique()), name="date_str")
    rth_mask = _time_mask(df, rth_start, rth_end)
    ib_mask = _time_mask(df, rth_start, initial_balance_end)

    rth = (
        df.loc[rth_mask]
        .groupby("date_str", sort=True)
        .agg(
            rth_open=("open", _first_valid),
            rth_high=("high", "max"),
            rth_low=("low", "min"),
            rth_close=("close", _last_valid),
            rth_volume=("volume", "sum"),
        )
    )
    rth["rth_range"] = rth["rth_high"] - rth["rth_low"]

    # Shift across actual RTH sessions only. Reindexing before the shift would
    # insert Sunday/holiday overnight dates with no RTH data, which breaks
    # Monday's prior-session references.
    for col in ("rth_open", "rth_high", "rth_low", "rth_close", "rth_volume", "rth_range"):
        rth[f"prior_{col}"] = rth[col].shift(1)
    rth = rth.reindex(session_dates)

    # Overnight for session date D includes bars after prior RTH close plus bars
    # before today's RTH open. This keeps the feature known before cash open.
    ovn_df = df.loc[~rth_mask].copy()
    ovn_df["overnight_date"] = ovn_df["date_str"]
    after_rth = ovn_df["hour_min"].ge(rth_end)
    ovn_df.loc[after_rth, "overnight_date"] = (
        ovn_df.loc[after_rth, "time_dt"] + pd.Timedelta(days=1)
    ).dt.strftime("%Y-%m-%d")
    overnight = (
        ovn_df.groupby("overnight_date", sort=True)
        .agg(
            overnight_open=("open", _first_valid),
            overnight_high=("high", "max"),
            overnight_low=("low", "min"),
            overnight_close=("close", _last_valid),
            overnight_volume=("volume", "sum"),
        )
        .reindex(session_dates)
    )
    overnight.index.name = "date_str"
    overnight["overnight_range"] = overnight["overnight_high"] - overnight["overnight_low"]

    context = rth.join(overnight, how="left")
    context["gap_points"] = context["rth_open"] - context["prior_rth_close"]
    prior_range = context["prior_rth_range"].replace(0, np.nan)
    context["gap_prior_range_pct"] = context["gap_points"] / prior_range * 100.0
    context["open_location_prior_range"] = (
        (context["rth_open"] - context["prior_rth_low"]) / prior_range
    )
    context["open_above_prior_high"] = context["rth_open"] > context["prior_rth_high"]
    context["open_below_prior_low"] = context["rth_open"] < context["prior_rth_low"]
    context["open_inside_prior_range"] = context["open_location_prior_range"].between(0.0, 1.0, inclusive="both")
    context["overnight_inventory_points"] = context["overnight_close"] - context["prior_rth_close"]
    context["overnight_inventory_direction"] = np.sign(context["overnight_inventory_points"].fillna(0.0))

    df = df.merge(context.reset_index(), on="date_str", how="left")

    atr = pd.to_numeric(df[atr_col], errors="coerce") if atr_col in df.columns else pd.Series(np.nan, index=df.index)
    df["gap_atr"] = df["gap_points"] / atr.replace(0, np.nan)
    df["overnight_inventory_atr"] = df["overnight_inventory_points"] / atr.replace(0, np.nan)
    df["overnight_range_atr"] = df["overnight_range"] / atr.replace(0, np.nan)
    df["prior_rth_range_atr"] = df["prior_rth_range"] / atr.replace(0, np.nan)

    df["rth_bar_number"] = np.nan
    df.loc[rth_mask, "rth_bar_number"] = df.loc[rth_mask].groupby("date_str").cumcount()
    df["rth_minutes_since_open"] = df["rth_bar_number"] * 5.0
    df["rth_session_high_so_far"] = df.loc[rth_mask].groupby("date_str")["high"].cummax()
    df["rth_session_low_so_far"] = df.loc[rth_mask].groupby("date_str")["low"].cummin()
    df["rth_session_range_so_far"] = df["rth_session_high_so_far"] - df["rth_session_low_so_far"]
    df["rth_range_so_far_atr"] = df["rth_session_range_so_far"] / atr.replace(0, np.nan)

    df["ib_high_so_far"] = df.loc[ib_mask].groupby("date_str")["high"].cummax()
    df["ib_low_so_far"] = df.loc[ib_mask].groupby("date_str")["low"].cummin()
    df["ib_range_so_far"] = df["ib_high_so_far"] - df["ib_low_so_far"]
    final_ib = (
        df.loc[ib_mask]
        .groupby("date_str", sort=True)
        .agg(ib_high=("high", "max"), ib_low=("low", "min"))
    )
    final_ib["ib_range"] = final_ib["ib_high"] - final_ib["ib_low"]
    df = df.merge(final_ib.reset_index(), on="date_str", how="left")

    # Final IB is only known after the IB window closes.
    ib_known = df["hour_min"].ge(initial_balance_end)
    for col in ("ib_high", "ib_low", "ib_range"):
        df.loc[~ib_known, col] = np.nan
    df["ib_range_atr"] = df["ib_range"] / atr.replace(0, np.nan)
    df["above_ib_high"] = ib_known & df["close"].gt(df["ib_high"])
    df["below_ib_low"] = ib_known & df["close"].lt(df["ib_low"])
    df["inside_ib"] = ib_known & df["close"].between(df["ib_low"], df["ib_high"], inclusive="both")

    inventory = df["overnight_inventory_direction"].fillna(0.0)
    gap = np.sign(df["gap_points"].fillna(0.0))
    df["gap_inventory_alignment"] = np.where((inventory != 0) & (gap != 0), inventory == gap, False)
    df["open_context"] = "unknown"
    df.loc[df["open_inside_prior_range"].fillna(False), "open_context"] = "inside_prior_range"
    df.loc[df["open_above_prior_high"].fillna(False), "open_context"] = "gap_above_prior_high"
    df.loc[df["open_below_prior_low"].fillna(False), "open_context"] = "gap_below_prior_low"

    rth_open_known = clock_ge(df["time_dt"], rth_start)
    rth_final_known = clock_ge(df["time_dt"], rth_end)

    # Current-session final RTH and overnight aggregates are not point-in-time
    # during their own forming windows. Keep prior-session references, live
    # running RTH/IB columns, and RTH-open context available when they are known.
    opening_numeric_cols = [
        "rth_open",
        "overnight_open",
        "overnight_high",
        "overnight_low",
        "overnight_close",
        "overnight_volume",
        "overnight_range",
        "gap_points",
        "gap_prior_range_pct",
        "open_location_prior_range",
        "overnight_inventory_points",
        "overnight_inventory_direction",
        "gap_atr",
        "overnight_inventory_atr",
        "overnight_range_atr",
    ]
    opening_bool_cols = [
        "open_above_prior_high",
        "open_below_prior_low",
        "open_inside_prior_range",
        "gap_inventory_alignment",
    ]
    final_rth_cols = ["rth_high", "rth_low", "rth_close", "rth_volume", "rth_range"]

    df.loc[~rth_open_known, [col for col in opening_numeric_cols if col in df.columns]] = np.nan
    df.loc[~rth_open_known, [col for col in opening_bool_cols if col in df.columns]] = False
    df.loc[~rth_open_known, "open_context"] = "unknown"
    df.loc[~rth_final_known, [col for col in final_rth_cols if col in df.columns]] = np.nan

    return df
