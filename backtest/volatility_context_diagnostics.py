from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from backtest.microstructure_diagnostics import (
    build_microstructure_cost_state,
    build_signal_adverse_selection_diagnostics,
)
from backtest.volatility_state import VolatilityStateConfig, add_volatility_state_features


DEFAULT_FUTURE_RV_HORIZONS_BARS = (5, 15, 60)
DEFAULT_SPREAD_REVERSION_HORIZONS_MINUTES = (1, 5, 15)
DEFAULT_REGIME_COLUMNS = (
    "volatility_compression_state",
    "volatility_vol_of_vol_state",
    "volatility_roughness_state",
    "markov_state_label",
)
DEFAULT_EXPANSION_STATES = (
    "expanded_volatility_context",
    "high_markov_volatility_context",
    "unstable_volatility_context",
    "jump_volatility_context",
)


@dataclass(frozen=True)
class VolatilityContextDiagnostics:
    future_realized_vol_by_state: pd.DataFrame
    future_realized_vol_splits: pd.DataFrame
    tbbo_cost_state_by_vol_state: pd.DataFrame
    tbbo_cost_state_splits: pd.DataFrame
    spread_reversion_during_expansion: pd.DataFrame
    signal_adverse_selection_by_vol_state: pd.DataFrame
    signal_adverse_selection_splits: pd.DataFrame


@dataclass(frozen=True)
class VolatilityContextDiagnosticPaths:
    future_realized_vol_by_state_csv: Path
    future_realized_vol_splits_csv: Path
    tbbo_cost_state_by_vol_state_csv: Path
    tbbo_cost_state_splits_csv: Path
    spread_reversion_during_expansion_csv: Path
    signal_adverse_selection_by_vol_state_csv: Path
    signal_adverse_selection_splits_csv: Path
    report_md: Path


def build_volatility_context_diagnostics(
    bars: pd.DataFrame,
    *,
    volatility_state: pd.DataFrame | None = None,
    tbbo_minute_stats: pd.DataFrame | None = None,
    aggressive_flow_minute_stats: pd.DataFrame | None = None,
    signals: pd.DataFrame | None = None,
    future_rv_horizons_bars: Iterable[int] = DEFAULT_FUTURE_RV_HORIZONS_BARS,
    spread_reversion_horizons_minutes: Iterable[int] = DEFAULT_SPREAD_REVERSION_HORIZONS_MINUTES,
    regime_cols: Iterable[str] = DEFAULT_REGIME_COLUMNS,
    volatility_config: VolatilityStateConfig | None = None,
) -> VolatilityContextDiagnostics:
    vol = _prepare_volatility_context(
        bars,
        volatility_state=volatility_state,
        volatility_config=volatility_config,
    )
    clean_future_horizons = _clean_ints(future_rv_horizons_bars, DEFAULT_FUTURE_RV_HORIZONS_BARS)
    clean_spread_horizons = _clean_ints(spread_reversion_horizons_minutes, DEFAULT_SPREAD_REVERSION_HORIZONS_MINUTES)
    active_regime_cols = [col for col in regime_cols if col in vol.columns]

    future_detail = _future_realized_vol_rows(vol, horizons_bars=clean_future_horizons)
    future_by_state = _summarize_future_realized_vol(future_detail, split_type="all", split_value="all")
    future_splits = _split_summaries(
        future_detail,
        summary_func=_summarize_future_realized_vol,
        time_col="time",
        regime_cols=active_regime_cols,
    )

    if tbbo_minute_stats is not None and not tbbo_minute_stats.empty:
        cost_state = build_microstructure_cost_state(
            tbbo_minute_stats,
            aggressive_flow_minute_stats=aggressive_flow_minute_stats,
        )
        cost_context = _merge_minute_vol_context(cost_state, vol, minute_col="minute")
        cost_by_state = _summarize_tbbo_cost_state(cost_context, split_type="all", split_value="all")
        cost_splits = _split_summaries(
            cost_context,
            summary_func=_summarize_tbbo_cost_state,
            time_col="minute",
            regime_cols=active_regime_cols,
        )
        spread_reversion = _spread_reversion_during_expansion(
            tbbo_minute_stats,
            vol,
            horizons_minutes=clean_spread_horizons,
        )
    else:
        cost_by_state = pd.DataFrame()
        cost_splits = pd.DataFrame()
        spread_reversion = pd.DataFrame()

    if (
        signals is not None
        and not signals.empty
        and tbbo_minute_stats is not None
        and not tbbo_minute_stats.empty
    ):
        adverse = build_signal_adverse_selection_diagnostics(
            signals,
            tbbo_minute_stats,
            aggressive_flow_minute_stats=aggressive_flow_minute_stats,
            horizons_minutes=clean_spread_horizons,
        )
        adverse_context = _merge_minute_vol_context(adverse.events, vol, minute_col="signal_minute")
        signal_by_state = _summarize_signal_adverse_selection(adverse_context, split_type="all", split_value="all")
        signal_splits = _split_summaries(
            adverse_context,
            summary_func=_summarize_signal_adverse_selection,
            time_col="signal_minute",
            regime_cols=active_regime_cols,
        )
    else:
        signal_by_state = pd.DataFrame()
        signal_splits = pd.DataFrame()

    return VolatilityContextDiagnostics(
        future_realized_vol_by_state=future_by_state,
        future_realized_vol_splits=future_splits,
        tbbo_cost_state_by_vol_state=cost_by_state,
        tbbo_cost_state_splits=cost_splits,
        spread_reversion_during_expansion=spread_reversion,
        signal_adverse_selection_by_vol_state=signal_by_state,
        signal_adverse_selection_splits=signal_splits,
    )


def write_volatility_context_diagnostics(
    diagnostics: VolatilityContextDiagnostics,
    out_dir: Path | str,
    *,
    artifact_name: str = "volatility_context_diagnostics",
) -> VolatilityContextDiagnosticPaths:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _slugify(artifact_name) or "volatility_context_diagnostics"
    paths = VolatilityContextDiagnosticPaths(
        future_realized_vol_by_state_csv=output_dir / f"{safe_name}_future_realized_vol_by_state.csv",
        future_realized_vol_splits_csv=output_dir / f"{safe_name}_future_realized_vol_splits.csv",
        tbbo_cost_state_by_vol_state_csv=output_dir / f"{safe_name}_tbbo_cost_state_by_vol_state.csv",
        tbbo_cost_state_splits_csv=output_dir / f"{safe_name}_tbbo_cost_state_splits.csv",
        spread_reversion_during_expansion_csv=output_dir / f"{safe_name}_spread_reversion_during_expansion.csv",
        signal_adverse_selection_by_vol_state_csv=output_dir
        / f"{safe_name}_signal_adverse_selection_by_vol_state.csv",
        signal_adverse_selection_splits_csv=output_dir / f"{safe_name}_signal_adverse_selection_splits.csv",
        report_md=output_dir / f"{safe_name}.md",
    )
    diagnostics.future_realized_vol_by_state.to_csv(paths.future_realized_vol_by_state_csv, index=False)
    diagnostics.future_realized_vol_splits.to_csv(paths.future_realized_vol_splits_csv, index=False)
    diagnostics.tbbo_cost_state_by_vol_state.to_csv(paths.tbbo_cost_state_by_vol_state_csv, index=False)
    diagnostics.tbbo_cost_state_splits.to_csv(paths.tbbo_cost_state_splits_csv, index=False)
    diagnostics.spread_reversion_during_expansion.to_csv(paths.spread_reversion_during_expansion_csv, index=False)
    diagnostics.signal_adverse_selection_by_vol_state.to_csv(
        paths.signal_adverse_selection_by_vol_state_csv,
        index=False,
    )
    diagnostics.signal_adverse_selection_splits.to_csv(paths.signal_adverse_selection_splits_csv, index=False)
    paths.report_md.write_text(render_volatility_context_diagnostics_markdown(diagnostics), encoding="utf-8")
    return paths


def render_volatility_context_diagnostics_markdown(diagnostics: VolatilityContextDiagnostics) -> str:
    lines = [
        "# Volatility Context Diagnostics",
        "",
        "This is an artifact-only diagnostics report. It summarizes existing bars, volatility state, TBBO minute stats, and optional prepared signals; it does not replay strategy logic or create trades.",
        "",
        "## Future Realized Volatility By Current Vol State",
        "",
        _frame_to_markdown(diagnostics.future_realized_vol_by_state, max_rows=30),
        "",
        "## Year And Regime Splits For Future Realized Volatility",
        "",
        _frame_to_markdown(diagnostics.future_realized_vol_splits, max_rows=40),
        "",
        "## TBBO Cost State By Vol State",
        "",
        _frame_to_markdown(diagnostics.tbbo_cost_state_by_vol_state, max_rows=30),
        "",
        "## Year And Regime Splits For TBBO Cost State",
        "",
        _frame_to_markdown(diagnostics.tbbo_cost_state_splits, max_rows=40),
        "",
        "## Spread/Reversion During Vol Expansion",
        "",
        _frame_to_markdown(diagnostics.spread_reversion_during_expansion, max_rows=40),
        "",
        "## Signal Adverse Selection By Vol State",
        "",
        _frame_to_markdown(diagnostics.signal_adverse_selection_by_vol_state, max_rows=30),
        "",
        "## Year And Regime Splits For Signal Adverse Selection",
        "",
        _frame_to_markdown(diagnostics.signal_adverse_selection_splits, max_rows=40),
        "",
        "## Guardrails",
        "",
        "- Future realized volatility rows are diagnostics only; do not merge them into signal features.",
        "- TBBO rows are execution-cost context, not alpha-mining input.",
        "- Treat a good or bad volatility slice as a hypothesis requiring separate-sample validation.",
        "- Year and regime splits are included to expose one-sample stories before they become candidate rules.",
    ]
    return "\n".join(lines) + "\n"


def _prepare_volatility_context(
    bars: pd.DataFrame,
    *,
    volatility_state: pd.DataFrame | None,
    volatility_config: VolatilityStateConfig | None,
) -> pd.DataFrame:
    if volatility_state is None or volatility_state.empty:
        out = add_volatility_state_features(bars, config=volatility_config)
    else:
        out = volatility_state.copy()
    if "time" not in out.columns:
        raise ValueError("volatility context must include a time column")
    out["time"] = _coerce_time(out["time"])
    if "volatility_state" not in out.columns:
        out["volatility_state"] = "unknown"
    if "volatility_compression_state" not in out.columns:
        out["volatility_compression_state"] = "unknown"
    if "close" not in out.columns and "close" in bars.columns:
        prices = bars.loc[:, ["time", "close"]].copy()
        prices["time"] = _coerce_time(prices["time"])
        out = out.merge(prices, on="time", how="left")
    if "close" not in out.columns:
        raise ValueError("bars or volatility context must include a close column")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out["volatility_state"] = out["volatility_state"].fillna("unknown").astype(str)
    return out.dropna(subset=["time", "close"]).sort_values("time").reset_index(drop=True)


def _future_realized_vol_rows(vol: pd.DataFrame, *, horizons_bars: Iterable[int]) -> pd.DataFrame:
    close = pd.to_numeric(vol["close"], errors="coerce")
    log_return = np.log(close).diff()
    rows: list[pd.DataFrame] = []
    for horizon in horizons_bars:
        horizon = int(horizon)
        future_rv = _forward_rolling_std(log_return, horizon) * np.sqrt(float(252 * 390))
        piece = vol.loc[:, _context_columns(vol)].copy()
        piece["horizon_bars"] = horizon
        piece["future_realized_vol"] = future_rv
        piece["future_abs_return_points"] = (close.shift(-horizon) - close).abs()
        rows.append(piece)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True).dropna(subset=["future_realized_vol"])


def _summarize_future_realized_vol(frame: pd.DataFrame, *, split_type: str, split_value: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    valid = frame.dropna(subset=["future_realized_vol"]).copy()
    if valid.empty:
        return pd.DataFrame()
    grouped = valid.groupby(["horizon_bars", "volatility_state"], dropna=False, sort=True)
    out = grouped.agg(
        observations=("future_realized_vol", "size"),
        median_future_realized_vol=("future_realized_vol", "median"),
        mean_future_realized_vol=("future_realized_vol", "mean"),
        p75_future_realized_vol=("future_realized_vol", lambda s: float(s.quantile(0.75))),
        median_future_abs_return_points=("future_abs_return_points", "median"),
        current_realized_vol_short=("realized_vol_short", "median")
        if "realized_vol_short" in valid.columns
        else ("future_realized_vol", _nan_agg),
        jump_event_pct=("volatility_jump_event", "mean")
        if "volatility_jump_event" in valid.columns
        else ("future_realized_vol", _nan_agg),
    ).reset_index()
    out.insert(0, "split_value", split_value)
    out.insert(0, "split_type", split_type)
    return out


def _summarize_tbbo_cost_state(frame: pd.DataFrame, *, split_type: str, split_value: str) -> pd.DataFrame:
    if frame.empty or "volatility_state" not in frame.columns:
        return pd.DataFrame()
    valid = frame.dropna(subset=["volatility_state"]).copy()
    if valid.empty:
        return pd.DataFrame()
    for col in (
        "microstructure_cost_score",
        "median_spread_points",
        "p95_spread_points",
        "p95_abs_trade_price_vs_mid",
        "top_book_depth_exhausted_trade_pct",
    ):
        if col not in valid.columns:
            valid[col] = np.nan
    if "microstructure_cost_state" not in valid.columns:
        valid["microstructure_cost_state"] = "unknown"
    valid["is_stressed_or_worse"] = valid["microstructure_cost_state"].astype(str).isin(
        {"stressed", "fragile", "dislocated"}
    )
    grouped = valid.groupby("volatility_state", dropna=False, sort=True)
    out = grouped.agg(
        minutes=("volatility_state", "size"),
        median_microstructure_cost_score=("microstructure_cost_score", "median"),
        median_spread_points=("median_spread_points", "median"),
        p90_spread_points=("median_spread_points", lambda s: float(pd.to_numeric(s, errors="coerce").quantile(0.90))),
        median_p95_spread_points=("p95_spread_points", "median"),
        median_p95_trade_vs_mid_points=("p95_abs_trade_price_vs_mid", "median"),
        median_depth_exhausted_trade_pct=("top_book_depth_exhausted_trade_pct", "median"),
        stressed_or_worse_pct=("is_stressed_or_worse", "mean"),
    ).reset_index()
    out.insert(0, "split_value", split_value)
    out.insert(0, "split_type", split_type)
    return out


def _spread_reversion_during_expansion(
    tbbo_minute_stats: pd.DataFrame,
    vol: pd.DataFrame,
    *,
    horizons_minutes: Iterable[int],
) -> pd.DataFrame:
    market = _prepare_minute_stats(tbbo_minute_stats)
    if market.empty or "median_spread_points" not in market.columns:
        return pd.DataFrame()
    market = _merge_minute_vol_context(market, vol, minute_col="minute")
    market["is_vol_expansion_context"] = _is_expansion_context(market)
    market = market.loc[market["is_vol_expansion_context"]].copy()
    if market.empty:
        return pd.DataFrame()
    market["median_spread_points"] = pd.to_numeric(market["median_spread_points"], errors="coerce")
    current = market.dropna(subset=["minute", "median_spread_points"]).copy()
    right = _prepare_minute_stats(tbbo_minute_stats).loc[:, ["symbol", "minute", "median_spread_points"]].rename(
        columns={"minute": "future_minute_key", "median_spread_points": "future_spread_points"}
    )
    rows: list[pd.DataFrame] = []
    for horizon in horizons_minutes:
        left = current.copy()
        left["horizon_minutes"] = int(horizon)
        left["future_minute"] = left["minute"] + pd.Timedelta(minutes=int(horizon))
        left_keys = ["future_minute"]
        right_keys = ["future_minute_key"]
        if "symbol" in left.columns and "symbol" in right.columns:
            left_keys.insert(0, "symbol")
            right_keys.insert(0, "symbol")
        joined = left.merge(right, left_on=left_keys, right_on=right_keys, how="left")
        joined["spread_change_points"] = (
            pd.to_numeric(joined["future_spread_points"], errors="coerce")
            - pd.to_numeric(joined["median_spread_points"], errors="coerce")
        )
        rows.append(joined)
    detail = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    detail = detail.dropna(subset=["spread_change_points"])
    if detail.empty:
        return pd.DataFrame()
    grouped = detail.groupby(["horizon_minutes", "volatility_state"], dropna=False, sort=True)
    return grouped.agg(
        observations=("spread_change_points", "size"),
        median_current_spread_points=("median_spread_points", "median"),
        median_future_spread_points=("future_spread_points", "median"),
        median_spread_change_points=("spread_change_points", "median"),
        mean_spread_change_points=("spread_change_points", "mean"),
        pct_spread_narrows=("spread_change_points", lambda s: float((s < 0.0).mean())),
        pct_spread_widens=("spread_change_points", lambda s: float((s > 0.0).mean())),
    ).reset_index()


def _summarize_signal_adverse_selection(frame: pd.DataFrame, *, split_type: str, split_value: str) -> pd.DataFrame:
    if frame.empty or "volatility_state" not in frame.columns:
        return pd.DataFrame()
    valid = frame.dropna(subset=["signed_mid_move_points", "volatility_state"]).copy()
    if valid.empty:
        return pd.DataFrame()
    optional_numeric = [
        "microstructure_cost_score",
        "median_spread_points",
        "signed_mid_move_after_spread_points",
        "temporary_overshoot_points",
        "limit_wait_opportunity_cost_points",
    ]
    for col in optional_numeric:
        if col not in valid.columns:
            valid[col] = np.nan
    if "adverse_after_spread" not in valid.columns:
        valid["adverse_after_spread"] = pd.to_numeric(valid["signed_mid_move_after_spread_points"], errors="coerce").lt(0.0)
    if "impact_reverted_after_immediate" not in valid.columns:
        valid["impact_reverted_after_immediate"] = False
    grouped = valid.groupby(["horizon_minutes", "volatility_state"], dropna=False, sort=True)
    out = grouped.agg(
        signals=("signed_mid_move_points", "size"),
        median_signed_mid_move_points=("signed_mid_move_points", "median"),
        median_signed_mid_move_after_spread_points=("signed_mid_move_after_spread_points", "median"),
        adverse_after_spread_pct=("adverse_after_spread", "mean"),
        median_temporary_overshoot_points=("temporary_overshoot_points", "median"),
        overshoot_reversion_pct=("impact_reverted_after_immediate", "mean"),
        median_limit_wait_opportunity_cost_points=("limit_wait_opportunity_cost_points", "median"),
        median_current_spread_points=("median_spread_points", "median"),
        median_microstructure_cost_score=("microstructure_cost_score", "median"),
    ).reset_index()
    out.insert(0, "split_value", split_value)
    out.insert(0, "split_type", split_type)
    return out


def _split_summaries(
    frame: pd.DataFrame,
    *,
    summary_func,
    time_col: str,
    regime_cols: Iterable[str],
) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = [summary_func(frame, split_type="all", split_value="all")]
    if not frame.empty and time_col in frame.columns:
        work = frame.copy()
        work["_split_year"] = _coerce_time(work[time_col]).dt.year.astype("Int64").astype(str)
        for year, group in work.groupby("_split_year", dropna=True, sort=True):
            if year == "<NA>":
                continue
            pieces.append(summary_func(group.drop(columns=["_split_year"]), split_type="year", split_value=str(year)))
    for regime_col in regime_cols:
        if frame.empty or regime_col not in frame.columns:
            continue
        values = frame[regime_col].fillna("unknown").astype(str)
        for value, idx in values.groupby(values, sort=True).groups.items():
            pieces.append(summary_func(frame.loc[idx], split_type=f"regime:{regime_col}", split_value=str(value)))
    pieces = [piece for piece in pieces if piece is not None and not piece.empty]
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def _merge_minute_vol_context(frame: pd.DataFrame, vol: pd.DataFrame, *, minute_col: str) -> pd.DataFrame:
    if frame.empty or minute_col not in frame.columns:
        return pd.DataFrame()
    left = frame.copy()
    left[minute_col] = _coerce_time(left[minute_col]).dt.floor("min")
    context_cols = _context_columns(vol)
    right = vol.loc[:, context_cols].copy()
    right["vol_context_minute"] = _coerce_time(right["time"]).dt.floor("min")
    right = right.drop(columns=["time"]).drop_duplicates(subset=["vol_context_minute"], keep="last")
    merged = left.merge(right, left_on=minute_col, right_on="vol_context_minute", how="left")
    return merged.drop(columns=["vol_context_minute"], errors="ignore")


def _context_columns(frame: pd.DataFrame) -> list[str]:
    base = [
        "time",
        "volatility_state",
        "volatility_compression_state",
        "volatility_vol_of_vol_state",
        "volatility_roughness_state",
        "volatility_jump_event",
        "realized_vol_short",
        "realized_vol_long",
        "realized_vol_ratio",
        "markov_state_label",
    ]
    return [col for col in base if col in frame.columns]


def _is_expansion_context(frame: pd.DataFrame) -> pd.Series:
    state = frame.get("volatility_state", pd.Series("", index=frame.index)).fillna("").astype(str)
    compression = frame.get("volatility_compression_state", pd.Series("", index=frame.index)).fillna("").astype(str)
    jump = frame.get("volatility_jump_event", pd.Series(False, index=frame.index)).fillna(False).astype(bool)
    return state.isin(DEFAULT_EXPANSION_STATES) | compression.eq("expanded_volatility") | jump


def _prepare_minute_stats(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    if "minute" not in frame.columns:
        raise ValueError("minute stats must include a minute column")
    out = frame.copy()
    out["minute"] = _coerce_time(out["minute"])
    if "symbol" not in out.columns:
        out["symbol"] = ""
    for col in ("median_spread_points", "p95_spread_points", "trade_count"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["minute"])


def _forward_rolling_std(series: pd.Series, horizon: int) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values.shift(-1).iloc[::-1].rolling(int(horizon), min_periods=int(horizon)).std(ddof=0).iloc[::-1]


def _clean_ints(values: Iterable[int], fallback: Iterable[int]) -> list[int]:
    clean = sorted({int(value) for value in values if int(value) > 0})
    return clean or list(fallback)


def _coerce_time(series: pd.Series) -> pd.Series:
    out = pd.to_datetime(series, errors="coerce")
    if getattr(out.dt, "tz", None) is not None:
        out = out.dt.tz_convert("America/New_York").dt.tz_localize(None)
    return out


def _nan_agg(_: pd.Series) -> float:
    return np.nan


def _frame_to_markdown(frame: pd.DataFrame, *, max_rows: int) -> str:
    if frame.empty:
        return "_No rows._"
    preview = frame.head(max_rows).copy()
    headers = [str(col) for col in preview.columns]
    rows = [[_markdown_cell(value) for value in row] for row in preview.itertuples(index=False, name=None)]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _markdown_cell(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in str(value)).strip("_")
