"""Point-in-time cross-asset morning context ($TICK, VIX Futures, Spot VIX, SPX + IV)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backtest.point_in_time import mask_columns_before_clock

DEFAULT_CROSS_ASSET_FEATURES_PATH = Path("data/processed/macro_context/morning_cross_asset_features_0945.parquet")

# Column names below MUST match the parquet produced by the integration script
# (data/processed/macro_context/morning_cross_asset_features_0945.parquet).
# `tests/test_cross_asset_context.py::test_real_feature_file_schema` guards this.

# Known at/before the 09:30 open (prior-session values, overnight change, 09:30 opens).
CROSS_ASSET_OPEN_930_COLUMNS: tuple[str, ...] = (
    "vx_prior_rth_close",
    "vx_overnight_change_pct",
    "vx_open_930",
    "vix_spot_open_930",
    "spx_open_930",
    "spx_iv_open_930",
)

# Built from the 09:30/09:35/09:40 5-min bars -> known only at 09:45 ET.
CROSS_ASSET_OR15_945_COLUMNS: tuple[str, ...] = (
    "tick_or15_open",
    "tick_or15_close",
    "tick_or15_mean",
    "tick_or15_max",
    "tick_or15_min",
    "vx_close_945",
    "vx_high_945",
    "vx_low_945",
    "vx_or15_volume",
    "vx_or15_change_pct",
    "vx_or15_change",  # derived: vx_close_945 - vx_open_930 (VX points)
    "vix_spot_close_945",
    "vix_spot_or15_change_pct",
    "spx_close_945",
    "spx_iv_close_945",
    "spx_or15_return_pct",
    "spx_iv_or15_change_pct",
    "vx_minus_vix_spot_945",  # VX futures minus spot VIX (>=0 contango)
)

ALL_CROSS_ASSET_COLUMNS: tuple[str, ...] = (
    *CROSS_ASSET_OPEN_930_COLUMNS,
    *CROSS_ASSET_OR15_945_COLUMNS,
)


def load_morning_cross_asset_features(
    source: pd.DataFrame | Path | str | None = None,
) -> pd.DataFrame:
    """Load the standardized 09:45 ET daily cross-asset feature table."""
    if isinstance(source, pd.DataFrame):
        df = source.copy()
    else:
        path = Path(source) if source is not None else DEFAULT_CROSS_ASSET_FEATURES_PATH
        if not path.exists():
            csv_fallback = path.with_suffix(".csv")
            if csv_fallback.exists():
                path = csv_fallback
            else:
                return pd.DataFrame()
        if path.suffix.lower() == ".parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path)
    if df.empty or "date_str" not in df.columns:
        return pd.DataFrame()
    df["date_str"] = df["date_str"].astype(str)
    if "vx_or15_change" not in df.columns and {"vx_close_945", "vx_open_930"}.issubset(df.columns):
        df["vx_or15_change"] = pd.to_numeric(df["vx_close_945"], errors="coerce") - pd.to_numeric(
            df["vx_open_930"], errors="coerce"
        )
    return df.drop_duplicates(subset=["date_str"], keep="last").reset_index(drop=True)


def add_morning_cross_asset_features(
    bars_5m: pd.DataFrame,
    cross_asset_features: pd.DataFrame | Path | str | None = None,
    *,
    rth_start: str = "09:30",
    or15_available_at: str = "09:40",
) -> pd.DataFrame:
    """
    Merge morning cross-asset features into a 5-min bar dataframe with strict
    point-in-time clock masking:
      - 09:30 opening values are masked before `rth_start` (09:30).
      - 09:30..09:44 (OR15) summary values are masked before `or15_available_at`
        (09:40 5-min bar, which closes at 09:45 ET).
    """
    if bars_5m.empty:
        return bars_5m.copy()
    feat = load_morning_cross_asset_features(cross_asset_features)
    if feat.empty:
        return bars_5m.copy()

    out = bars_5m.copy()
    if "date_str" not in out.columns:
        out["date_str"] = pd.to_datetime(out["time"]).dt.strftime("%Y-%m-%d")

    keep_cols = ["date_str", *[c for c in ALL_CROSS_ASSET_COLUMNS if c in feat.columns]]
    out = out.merge(feat[keep_cols], on="date_str", how="left")

    present_open_cols = tuple(c for c in CROSS_ASSET_OPEN_930_COLUMNS if c in out.columns)
    if present_open_cols:
        out = mask_columns_before_clock(out, present_open_cols, available_at=str(rth_start))

    present_or15_cols = tuple(c for c in CROSS_ASSET_OR15_945_COLUMNS if c in out.columns)
    if present_or15_cols:
        out = mask_columns_before_clock(out, present_or15_cols, available_at=str(or15_available_at))

    return out
