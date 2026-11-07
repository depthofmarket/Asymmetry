#!/usr/bin/env python3
"""
Cache Point-in-Time Daily Markov Regimes for NQ and ES (2020-2026).
Implements Track C from Jeffy Motta's AntiAchismo Quant Masterclass.
Zero-lookahead: For session d, the Markov regime is determined using data up to session d-1.
"""

from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest.markov_regime import add_markov_regime_features

def compute_and_cache_daily_markov(symbol: str, raw_parquet: Path, out_parquet: Path):
    print(f"Loading {symbol} raw 1m bars from {raw_parquet.name}...")
    df = pd.read_parquet(raw_parquet)
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")

    daily = df.groupby("date_str").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum")
    ).reset_index()

    print(f"Aggregated {len(daily)} daily bars for {symbol} ({daily['date_str'].min()} to {daily['date_str'].max()}).")
    print(f"Fitting Point-in-Time 3-State Gaussian Markov Regime Model (60-day window, refit every 5 bars)...")

    daily_markov = add_markov_regime_features(
        daily,
        n_states=3,
        calibration_bars=60,
        min_calibration_bars=30,
        refit_every_bars=5,
        volatility_method="range_close"
    )

    # Strictly zero-lookahead shift:
    # A trade occurring on date d only knows the regime computed on session d-1 close.
    daily_markov["trade_date_str"] = daily_markov["date_str"].shift(-1)
    
    # Filter to 2020-2026
    out_df = daily_markov[daily_markov["trade_date_str"] >= "2020-01-01"].copy()
    out_df = out_df.rename(columns={"trade_date_str": "date_str", "date_str": "prior_session_date_str"})

    cols = [
        "date_str",
        "prior_session_date_str",
        "markov_state",
        "markov_state_label",
        "markov_state_confidence",
        "markov_prob_low_vol",
        "markov_prob_mid_vol",
        "markov_prob_high_vol",
        "markov_emission_mean_low_vol",
        "markov_emission_mean_mid_vol",
        "markov_emission_mean_high_vol",
    ]
    out_df = out_df[cols].reset_index(drop=True)

    out_df.to_parquet(out_parquet, index=False)
    print(f"Saved {len(out_df)} trading days of {symbol} Markov regimes to {out_parquet.name}.")
    print("State Distribution:")
    print(out_df["markov_state_label"].value_counts(normalize=True).round(3))
    print()

def main():
    out_dir = ROOT / "data/processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    nq_raw = ROOT / "data/raw/nq_1m_2017_2026_cqg_et.parquet"
    nq_out = out_dir / "nq_daily_markov_regimes_2020_2026.parquet"
    compute_and_cache_daily_markov("NQ", nq_raw, nq_out)

    es_raw = ROOT / "data/raw/es_1m_2020_2026_cqg_et.parquet"
    es_out = out_dir / "es_daily_markov_regimes_2020_2026.parquet"
    compute_and_cache_daily_markov("ES", es_raw, es_out)

if __name__ == "__main__":
    main()
