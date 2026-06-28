#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backtest.location_context import (  # noqa: E402
    LocationContextConfig,
    build_location_context,
    write_location_context_artifacts,
)
from config.backtest_config import BACKTEST_CONFIG, OPTIONS_FLOW_CONFIG  # noqa: E402


OUTRIGHT_NQ_SYMBOL_RE = re.compile(r"^NQ[FGHJKMNQUVXZ]\d{1,2}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build point-in-time VP/TPO shelves, VAL/VAH, GEX wall, volume-spike, "
            "and bid/ask dominance context for L2 replay."
        )
    )
    parser.add_argument("--bars", default=BACKTEST_CONFIG["data_path"], help="Bars CSV/parquet with OHLCV columns.")
    parser.add_argument(
        "--options-flow",
        default=OPTIONS_FLOW_CONFIG.get("features_path"),
        help="Optional options-flow feature CSV/parquet with options_available_time.",
    )
    parser.add_argument(
        "--orderflow-minute-stats",
        default="data/processed/orderflow/aggressive_flow_minute_stats.csv",
        help="Optional aggressive-flow or TBBO minute stats CSV/parquet.",
    )
    parser.add_argument("--out-dir", default="data/processed/location_context")
    parser.add_argument("--prefix", default="location_context")
    parser.add_argument(
        "--checkpoint-dir",
        default=None,
        help="Optional directory for a pre-orderflow parquet checkpoint after profile/options context.",
    )
    parser.add_argument(
        "--resume-checkpoint",
        action="store_true",
        help="Resume from the pre-orderflow checkpoint if it exists.",
    )
    parser.add_argument("--start", default=None, help="Optional inclusive start timestamp/date for bounded builds.")
    parser.add_argument("--end", default=None, help="Optional inclusive end timestamp/date for bounded builds.")
    parser.add_argument("--max-rows", type=int, default=None, help="Limit input bars after date filtering.")
    parser.add_argument(
        "--continuous-contract-method",
        default=BACKTEST_CONFIG.get("continuous_contract_method", "prior_session_volume"),
        help="Selection rule for multi-contract Databento bars.",
    )
    parser.add_argument(
        "--skip-continuous-contract-selection",
        action="store_true",
        help="Use when the bars file is already a single continuous series.",
    )
    parser.add_argument("--tick-size", type=float, default=0.25)
    parser.add_argument("--value-area-pct", type=float, default=0.70)
    parser.add_argument("--min-profile-bars", type=int, default=3)
    parser.add_argument("--shelf-count", type=int, default=6)
    parser.add_argument("--shelf-min-volume-share", type=float, default=0.05)
    parser.add_argument("--shelf-min-distance-points", type=float, default=1.0)
    parser.add_argument("--volume-spike-lookback", type=int, default=20)
    parser.add_argument("--volume-spike-min-periods", type=int, default=5)
    parser.add_argument("--volume-spike-multiplier", type=float, default=1.5)
    parser.add_argument("--dominance-threshold", type=float, default=0.20)
    parser.add_argument("--availability-lag", default="1min")
    parser.add_argument("--session-timezone", default="America/New_York")
    parser.add_argument("--session-start-hour", type=int, default=18)
    parser.add_argument("--session-start-minute", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(f"Loading bars: {args.bars}", flush=True)
    bars = _load_bars(
        args.bars,
        start=args.start,
        end=args.end,
        max_rows=args.max_rows,
        continuous_contract_method=None
        if args.skip_continuous_contract_selection
        else args.continuous_contract_method,
    )
    print(f"Loaded bars: {len(bars):,} rows", flush=True)
    print(f"Loading options-flow features: {args.options_flow}", flush=True)
    options_flow = _read_optional_frame(args.options_flow)
    print(
        f"Loaded options-flow features: {len(options_flow):,} rows"
        if options_flow is not None
        else "Loaded options-flow features: none",
        flush=True,
    )
    print(f"Loading orderflow minute stats: {args.orderflow_minute_stats}", flush=True)
    orderflow = _read_optional_frame(args.orderflow_minute_stats)
    print(
        f"Loaded orderflow minute stats: {len(orderflow):,} rows"
        if orderflow is not None
        else "Loaded orderflow minute stats: none",
        flush=True,
    )
    config = LocationContextConfig(
        tick_size=float(args.tick_size),
        value_area_pct=float(args.value_area_pct),
        min_profile_bars=int(args.min_profile_bars),
        shelf_count=int(args.shelf_count),
        shelf_min_volume_share=float(args.shelf_min_volume_share),
        shelf_min_distance_points=float(args.shelf_min_distance_points),
        volume_spike_lookback=int(args.volume_spike_lookback),
        volume_spike_min_periods=int(args.volume_spike_min_periods),
        volume_spike_multiplier=float(args.volume_spike_multiplier),
        dominance_threshold=float(args.dominance_threshold),
        availability_lag=str(args.availability_lag),
        session_timezone=str(args.session_timezone),
        session_start_hour=int(args.session_start_hour),
        session_start_minute=int(args.session_start_minute),
    )
    print("Building point-in-time location context...", flush=True)
    checkpoint_path = (
        Path(args.checkpoint_dir) / f"{args.prefix}_pre_orderflow.parquet"
        if args.checkpoint_dir
        else None
    )
    artifacts = build_location_context(
        bars,
        options_flow_features=options_flow,
        orderflow_minute_stats=orderflow,
        config=config,
        progress_callback=lambda message: print(message, flush=True),
        pre_orderflow_checkpoint=checkpoint_path,
        resume_pre_orderflow_checkpoint=bool(args.resume_checkpoint),
    )
    print(f"Built location context: {len(artifacts.frame):,} rows", flush=True)
    print(f"Writing location context artifacts to: {args.out_dir}", flush=True)
    paths = write_location_context_artifacts(artifacts, args.out_dir, prefix=args.prefix)
    print(f"Location context CSV:    {paths['csv']} ({len(artifacts.frame):,} rows)")
    print(f"Location context report: {paths['report_md']}")
    if not artifacts.frame.empty:
        cols = [
            "time",
            "source_bar_time",
            "close",
            "profile_lower",
            "profile_poc",
            "profile_upper",
            "vp_val",
            "vp_vah",
            "options_gamma_wall_strike",
            "options_put_call_oi_ratio",
            "options_call_put_oi_ratio",
            "volume_spike",
            "orderflow_bid_ask_dominance",
        ]
        print(artifacts.frame[[col for col in cols if col in artifacts.frame.columns]].tail(10).to_string(index=False))
    return 0


def _load_bars(
    path: str | Path,
    *,
    start: str | None,
    end: str | None,
    max_rows: int | None,
    continuous_contract_method: str | None,
) -> pd.DataFrame:
    frame = _read_frame(path)
    if "ts_event" in frame.columns:
        frame["time"] = pd.to_datetime(frame["ts_event"], utc=True, errors="coerce")
        frame["time"] = frame["time"].dt.tz_convert("America/New_York").dt.tz_localize(None)
        if continuous_contract_method and "symbol" in frame.columns:
            frame = _select_continuous_outright_contract(frame, method=continuous_contract_method)
    else:
        frame.columns = frame.columns.str.lower()
        if "timestamp et" in frame.columns:
            frame["time"] = pd.to_datetime(frame["timestamp et"], errors="coerce")
        elif "datetime" in frame.columns:
            frame["time"] = pd.to_datetime(frame["datetime"], errors="coerce")
        elif "time" in frame.columns:
            frame["time"] = pd.to_datetime(frame["time"], errors="coerce")
    required = ["time", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError(f"bars missing required column(s): {', '.join(missing)}")
    if start is not None:
        frame = frame.loc[pd.to_datetime(frame["time"], errors="coerce").ge(pd.Timestamp(start))]
    if end is not None:
        end_ts = pd.Timestamp(end)
        if end_ts == end_ts.normalize():
            end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
        frame = frame.loc[pd.to_datetime(frame["time"], errors="coerce").le(end_ts)]
    frame = frame.sort_values("time", kind="stable")
    if max_rows is not None:
        frame = frame.head(int(max_rows))
    keep = [col for col in ["time", "open", "high", "low", "close", "volume"] if col in frame.columns]
    return frame[keep].reset_index(drop=True)


def _read_optional_frame(path: str | Path | None) -> pd.DataFrame | None:
    if path is None or str(path).strip() == "":
        return None
    file_path = Path(path)
    if not file_path.exists():
        return None
    return _read_frame(file_path)


def _read_frame(path: str | Path) -> pd.DataFrame:
    file_path = Path(path)
    if file_path.suffix.lower() == ".parquet":
        return pd.read_parquet(file_path)
    return pd.read_csv(file_path, low_memory=False)


def _select_continuous_outright_contract(df: pd.DataFrame, method: str = "prior_session_volume") -> pd.DataFrame:
    symbol = df["symbol"].astype(str)
    work = df.loc[symbol.str.match(OUTRIGHT_NQ_SYMBOL_RE)].copy()
    if work.empty:
        return work

    method = str(method or "prior_session_volume").lower()

    def timestamp_volume_selection(frame: pd.DataFrame) -> pd.DataFrame:
        return (
            frame.sort_values(["time", "volume"], ascending=[True, False])
            .drop_duplicates(subset="time", keep="first")
            .reset_index(drop=True)
        )

    if method in ("timestamp_volume", "minute_volume", "per_timestamp"):
        return timestamp_volume_selection(work)

    if method in ("daily_volume", "prior_daily_volume", "previous_daily_volume"):
        work["_contract_bucket"] = pd.to_datetime(work["time"]).dt.normalize()
    else:
        work["_contract_bucket"] = _futures_session_key(work["time"])

    by_contract = (
        work.groupby(["_contract_bucket", "symbol"], sort=True)["volume"]
        .sum()
        .reset_index()
        .sort_values(["_contract_bucket", "volume", "symbol"], ascending=[True, False, True])
    )

    use_prior_bucket = method in (
        "prior_session_volume",
        "previous_session_volume",
        "prior_daily_volume",
        "previous_daily_volume",
    )
    if use_prior_bucket:
        ranked_symbols = {
            bucket: group["symbol"].astype(str).tolist()
            for bucket, group in by_contract.groupby("_contract_bucket", sort=True)
        }
        available_symbols = {
            bucket: set(group["symbol"].astype(str))
            for bucket, group in work.groupby("_contract_bucket", sort=True)
        }
        first_timestamp_fallback = (
            work.sort_values(["_contract_bucket", "time", "volume", "symbol"], ascending=[True, True, False, True])
            .drop_duplicates(subset="_contract_bucket", keep="first")
            .set_index("_contract_bucket")["symbol"]
            .astype(str)
            .to_dict()
        )
        selected_rows: list[dict[str, object]] = []
        buckets = list(ranked_symbols)
        for idx, bucket in enumerate(buckets):
            selected_symbol = None
            if idx > 0:
                prior_bucket = buckets[idx - 1]
                current_available = available_symbols.get(bucket, set())
                for candidate in ranked_symbols.get(prior_bucket, []):
                    if candidate in current_available:
                        selected_symbol = candidate
                        break
            if selected_symbol is None:
                selected_symbol = first_timestamp_fallback.get(bucket)
            if selected_symbol is not None:
                selected_rows.append({"_contract_bucket": bucket, "_selected_symbol": selected_symbol})
        selected = pd.DataFrame(selected_rows)
    else:
        selected = by_contract.drop_duplicates(subset="_contract_bucket", keep="first")
        selected = selected.rename(columns={"symbol": "_selected_symbol"})[["_contract_bucket", "_selected_symbol"]]

    if selected.empty:
        return timestamp_volume_selection(work.drop(columns=["_contract_bucket"], errors="ignore"))

    work = work.merge(selected, on="_contract_bucket", how="left")
    work = work.loc[work["symbol"].eq(work["_selected_symbol"])].copy()
    return (
        work.drop(columns=["_contract_bucket", "_selected_symbol"], errors="ignore")
        .sort_values(["time", "volume"], ascending=[True, False])
        .drop_duplicates(subset="time", keep="first")
        .reset_index(drop=True)
    )


def _futures_session_key(times: pd.Series) -> pd.Series:
    dt = pd.to_datetime(times)
    session = dt.dt.normalize()
    return session.mask(_clock_ge(dt, "18:00"), session + pd.Timedelta(days=1))


def _clock_ge(times: pd.Series, hour_min: str) -> pd.Series:
    hour, minute = [int(part) for part in hour_min.split(":", 1)]
    return (times.dt.hour > hour) | ((times.dt.hour == hour) & (times.dt.minute >= minute))


if __name__ == "__main__":
    raise SystemExit(main())
