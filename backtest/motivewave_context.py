from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MotiveWaveContextConfig:
    time_col: str = "time"
    timezone: str = "America/New_York"
    availability_lag: str = "0min"
    require_sorted: bool = True
    allow_result_columns: bool = False
    blocked_column_terms: tuple[str, ...] = (
        "pnl",
        "realized",
        "profit",
        "loss",
        "trade_result",
        "mae",
        "mfe",
        "fill_price",
        "fill_time",
        "exit_price",
        "entry_price",
    )


@dataclass(frozen=True)
class MotiveWaveContextArtifacts:
    frame: pd.DataFrame
    report_md: str
    column_map: dict[str, list[str]]


_TIME_ALIASES = (
    "time",
    "datetime",
    "date_time",
    "timestamp",
    "timestamp_et",
    "bar_time",
    "ts_event",
    "context_available_time",
)

_BOOL_ALIASES: dict[str, tuple[str, ...]] = {
    "mw_buy_absorption": ("buy_side_absorption", "buy_absorption", "signal_buy_absorption"),
    "mw_sell_absorption": ("sell_side_absorption", "sell_absorption", "signal_sell_absorption"),
    "mw_buy_initiation": ("buy_side_initiation", "buy_initiation", "signal_buy_initiation"),
    "mw_sell_initiation": ("sell_side_initiation", "sell_initiation", "signal_sell_initiation"),
    "mw_buy_dominance": (
        "buy_side_dominance",
        "buy_sidedom",
        "buy_dominance",
        "color_buy_dom",
        "color_buysidedom",
    ),
    "mw_sell_dominance": (
        "sell_side_dominance",
        "sell_sidedom",
        "sell_dominance",
        "color_sell_dom",
        "color_sellsidedom",
    ),
    "mw_buy_aggression": ("buy_side_aggression", "buy_aggression", "buying_aggression"),
    "mw_sell_aggression": ("sell_side_aggression", "sell_aggression", "selling_aggression"),
    "mw_bid_tower": ("bid_tower", "red_tower", "signal_bid_tower", "lbl_signal_bid_tower"),
    "mw_ask_tower": ("ask_tower", "blue_tower", "signal_ask_tower", "lbl_signal_ask_tower"),
    "mw_extreme_positive_delta": (
        "extreme_positive_delta",
        "signal_extreme_positive_delta",
    ),
    "mw_extreme_negative_delta": (
        "extreme_negative_delta",
        "signal_extreme_negative_delta",
    ),
    "mw_extreme_positive_delta_close": (
        "extreme_positive_delta_close",
        "extreme_positive_delta_close_signal",
        "signal_extreme_positive_delta_close",
    ),
    "mw_extreme_negative_delta_close": (
        "extreme_negative_delta_close",
        "extreme_negative_delta_close_signal",
        "signal_extreme_negative_delta_close",
    ),
    "mw_window_threshold_positive": (
        "positive_window_threshold",
        "window_threshold_positive",
        "signal_window_threshold_positive",
    ),
    "mw_window_threshold_negative": (
        "negative_window_threshold",
        "window_threshold_negative",
        "signal_window_threshold_negative",
    ),
    "mw_recon_bid_dominant_1": ("bid_dominant_1",),
    "mw_recon_bid_dominant_2": ("bid_dominant_2",),
    "mw_recon_bid_dominant_3": ("bid_dominant_3",),
    "mw_recon_ask_dominant_1": ("ask_dominant_1",),
    "mw_recon_ask_dominant_2": ("ask_dominant_2",),
    "mw_recon_ask_dominant_3": ("ask_dominant_3",),
}

_NUMERIC_ALIASES: dict[str, tuple[str, ...]] = {
    "mw_window_delta": ("window_delta", "value_window_delta"),
    "mw_delta_map_gradient": ("delta_map_gradient", "delta_color_gradient", "value_delta_gradient"),
    "mw_delta_percent": ("delta_percent", "delta_pct"),
    "mw_delta_plus_percent": ("delta_plus_percent", "delta_plus_pct"),
    "mw_dominance_percent": ("dominance_percent", "dom_percent"),
}

_TEXT_SIGNAL_ALIASES: dict[str, tuple[str, ...]] = {
    "extreme_delta_signal": ("extreme_delta_signal", "value_extreme_delta_signal"),
    "extreme_delta_close_signal": ("extreme_delta_close_signal", "value_extreme_delta_close_signal"),
    "window_threshold_signal": ("window_threshold_signal", "value_window_threshold_signal"),
    "tape_dominance": ("tape_dominance", "display_dominance", "reconstructed_tape_dominance"),
}


def build_motivewave_context(
    export: pd.DataFrame | Path | str,
    *,
    config: MotiveWaveContextConfig | None = None,
) -> MotiveWaveContextArtifacts:
    """
    Normalize MotiveWave indicator exports into point-in-time trigger context.

    The output is an adapter layer for parity and replay gates. It is not an
    edge claim, and it intentionally refuses result-like columns by default.
    """

    cfg = config or MotiveWaveContextConfig()
    raw = _read_frame(export)
    if raw.empty:
        empty = pd.DataFrame(columns=["time", "source_signal_time", "context_available_time"])
        return MotiveWaveContextArtifacts(empty, render_motivewave_context_report(empty, cfg, {}), {})

    time_col = _resolve_time_col(raw, cfg.time_col)
    if not cfg.allow_result_columns:
        _reject_result_columns(raw.columns, time_col=time_col, blocked_terms=cfg.blocked_column_terms)

    out = pd.DataFrame(index=raw.index)
    source_time = _to_utc_time(raw[time_col], cfg.timezone)
    lag = pd.Timedelta(cfg.availability_lag)
    out["source_signal_time"] = source_time
    out["time"] = source_time + lag
    out["context_available_time"] = out["time"]

    column_map: dict[str, list[str]] = {}
    for canonical, aliases in _BOOL_ALIASES.items():
        cols = _matching_columns(raw, aliases, exclude={time_col})
        out[canonical] = _truthy_any(raw, cols)
        column_map[canonical] = cols

    for canonical, aliases in _NUMERIC_ALIASES.items():
        cols = _matching_columns(raw, aliases, exclude={time_col})
        out[canonical] = _first_numeric(raw, cols)
        column_map[canonical] = cols

    _add_text_signal_columns(raw, out, column_map, time_col=time_col)
    _add_reconstructed_tape_tiers(out)
    _add_directional_trigger_columns(out)

    out = out.dropna(subset=["time"])
    if cfg.require_sorted:
        out = out.sort_values("time", kind="stable")
    out = out.reset_index(drop=True)
    report = render_motivewave_context_report(out, cfg, column_map)
    return MotiveWaveContextArtifacts(frame=out, report_md=report, column_map=column_map)


def write_motivewave_context_artifacts(
    artifacts: MotiveWaveContextArtifacts,
    out_dir: Path | str,
    *,
    prefix: str = "motivewave_context",
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


def render_motivewave_context_report(
    frame: pd.DataFrame,
    cfg: MotiveWaveContextConfig,
    column_map: dict[str, list[str]],
) -> str:
    mapped = {key: value for key, value in column_map.items() if value}
    trigger_cols = [
        "mw_any_long_trigger",
        "mw_any_short_trigger",
        "mw_absorption_long_trigger",
        "mw_absorption_short_trigger",
        "mw_initiative_long_trigger",
        "mw_initiative_short_trigger",
    ]
    lines = [
        "# MotiveWave Context",
        "",
        "This artifact normalizes exported MotiveWave orderflow studies into timestamped trigger fields for replay gates. It is an adapter and parity artifact, not a backtest or proof of edge.",
        "",
        "## Config",
        "",
        f"- Timezone for naive export timestamps: `{cfg.timezone}`",
        f"- Availability lag: `{cfg.availability_lag}`",
        f"- Result-column guard enabled: {not cfg.allow_result_columns}",
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
            ]
        )
        for col in trigger_cols:
            if col in frame.columns:
                lines.append(f"- {col}: {int(frame[col].fillna(False).astype(bool).sum()):,} true rows")
    lines.extend(["", "## Mapped Columns", ""])
    if mapped:
        for key in sorted(mapped):
            lines.append(f"- `{key}` <- {', '.join(f'`{col}`' for col in mapped[key])}")
    else:
        lines.append("- No known MotiveWave signal columns were mapped.")
    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Exported signals are shifted by `availability_lag` before replay consumption.",
            "- EAD absorption direction is mapped from bytecode-inspected marker placement: sell-side absorption is lower/bullish, buy-side absorption is upper/bearish.",
            "- Non-EAD study semantics still need chart/export parity checks before being treated as directional triggers.",
            "- Use `long_trigger_col` and `short_trigger_col` in the strategy config if your export names the manual trigger columns directly.",
            "- Do not treat indicator export parity as edge evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def _add_text_signal_columns(
    raw: pd.DataFrame,
    out: pd.DataFrame,
    column_map: dict[str, list[str]],
    *,
    time_col: str,
) -> None:
    extreme_cols = _matching_columns(raw, _TEXT_SIGNAL_ALIASES["extreme_delta_signal"], exclude={time_col})
    close_cols = _matching_columns(raw, _TEXT_SIGNAL_ALIASES["extreme_delta_close_signal"], exclude={time_col})
    threshold_cols = _matching_columns(raw, _TEXT_SIGNAL_ALIASES["window_threshold_signal"], exclude={time_col})
    tape_cols = _matching_columns(raw, _TEXT_SIGNAL_ALIASES["tape_dominance"], exclude={time_col})

    if extreme_cols:
        out["mw_extreme_positive_delta"] = out["mw_extreme_positive_delta"] | _text_contains_any(
            raw, extreme_cols, ("positive", "pos")
        )
        out["mw_extreme_negative_delta"] = out["mw_extreme_negative_delta"] | _text_contains_any(
            raw, extreme_cols, ("negative", "neg")
        )
        column_map.setdefault("mw_extreme_delta_signal_text", extreme_cols)
    if close_cols:
        out["mw_extreme_positive_delta_close"] = out["mw_extreme_positive_delta_close"] | _text_contains_any(
            raw, close_cols, ("positive", "pos")
        )
        out["mw_extreme_negative_delta_close"] = out["mw_extreme_negative_delta_close"] | _text_contains_any(
            raw, close_cols, ("negative", "neg")
        )
        column_map.setdefault("mw_extreme_delta_close_signal_text", close_cols)
    if threshold_cols:
        out["mw_window_threshold_positive"] = out["mw_window_threshold_positive"] | _text_contains_any(
            raw, threshold_cols, ("positive", "pos")
        )
        out["mw_window_threshold_negative"] = out["mw_window_threshold_negative"] | _text_contains_any(
            raw, threshold_cols, ("negative", "neg")
        )
        column_map.setdefault("mw_window_threshold_signal_text", threshold_cols)
    if tape_cols:
        bid_text = _text_contains_any(raw, tape_cols, ("bid_dominant", "bid dominant"))
        ask_text = _text_contains_any(raw, tape_cols, ("ask_dominant", "ask dominant", "offer dominant"))
        for tier in (1, 2, 3):
            out[f"mw_recon_bid_dominant_{tier}"] = out[f"mw_recon_bid_dominant_{tier}"] | (
                bid_text & _text_contains_any(raw, tape_cols, (str(tier),))
            )
            out[f"mw_recon_ask_dominant_{tier}"] = out[f"mw_recon_ask_dominant_{tier}"] | (
                ask_text & _text_contains_any(raw, tape_cols, (str(tier),))
            )
        column_map.setdefault("mw_tape_dominance_text", tape_cols)


def _add_reconstructed_tape_tiers(out: pd.DataFrame) -> None:
    bid_tier = pd.Series(0, index=out.index, dtype="int64")
    ask_tier = pd.Series(0, index=out.index, dtype="int64")
    for tier in (1, 2, 3):
        bid_col = f"mw_recon_bid_dominant_{tier}"
        ask_col = f"mw_recon_ask_dominant_{tier}"
        bid_tier = bid_tier.mask(out[bid_col].fillna(False).astype(bool), tier)
        ask_tier = ask_tier.mask(out[ask_col].fillna(False).astype(bool), tier)
    out["mw_tape_bid_dominance_tier"] = bid_tier
    out["mw_tape_ask_dominance_tier"] = ask_tier


def _add_directional_trigger_columns(out: pd.DataFrame) -> None:
    out["mw_absorption_long_trigger"] = out["mw_sell_absorption"].fillna(False).astype(bool)
    out["mw_absorption_short_trigger"] = out["mw_buy_absorption"].fillna(False).astype(bool)
    out["mw_initiative_long_trigger"] = _any_bool(
        out,
        (
            "mw_buy_initiation",
            "mw_buy_aggression",
            "mw_buy_dominance",
            "mw_ask_tower",
            "mw_extreme_positive_delta",
            "mw_extreme_positive_delta_close",
            "mw_window_threshold_positive",
        ),
    )
    out["mw_initiative_short_trigger"] = _any_bool(
        out,
        (
            "mw_sell_initiation",
            "mw_sell_aggression",
            "mw_sell_dominance",
            "mw_bid_tower",
            "mw_extreme_negative_delta",
            "mw_extreme_negative_delta_close",
            "mw_window_threshold_negative",
        ),
    )
    out["mw_orderflow_long_trigger"] = out["mw_initiative_long_trigger"] | (
        out["mw_tape_ask_dominance_tier"].fillna(0).astype(int) > 0
    )
    out["mw_orderflow_short_trigger"] = out["mw_initiative_short_trigger"] | (
        out["mw_tape_bid_dominance_tier"].fillna(0).astype(int) > 0
    )
    out["mw_any_long_trigger"] = out["mw_absorption_long_trigger"] | out["mw_orderflow_long_trigger"]
    out["mw_any_short_trigger"] = out["mw_absorption_short_trigger"] | out["mw_orderflow_short_trigger"]


def _read_frame(value: pd.DataFrame | Path | str) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    path = Path(value)
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, low_memory=False)


def _resolve_time_col(frame: pd.DataFrame, requested: str) -> str:
    if requested in frame.columns:
        return requested
    normalized = {_normalize_name(col): col for col in frame.columns}
    requested_norm = _normalize_name(requested)
    if requested_norm in normalized:
        return normalized[requested_norm]
    for alias in _TIME_ALIASES:
        if alias in normalized:
            return normalized[alias]
    raise ValueError(f"MotiveWave export is missing time column: {requested}")


def _reject_result_columns(columns: pd.Index, *, time_col: str, blocked_terms: tuple[str, ...]) -> None:
    blocked: list[str] = []
    terms = tuple(_normalize_name(term) for term in blocked_terms)
    for col in columns:
        if col == time_col:
            continue
        norm = _normalize_name(col)
        if any(term and term in norm for term in terms):
            blocked.append(str(col))
    if blocked:
        raise ValueError(
            "MotiveWave export contains result-like column(s); pass allow_result_columns=True only for manual audit: "
            + ", ".join(blocked)
        )


def _matching_columns(frame: pd.DataFrame, aliases: tuple[str, ...], *, exclude: set[str]) -> list[str]:
    alias_norms = tuple(_normalize_name(alias) for alias in aliases)
    cols: list[str] = []
    for col in frame.columns:
        if col in exclude:
            continue
        norm = _normalize_name(col)
        if any(alias == norm or alias in norm for alias in alias_norms):
            cols.append(str(col))
    return cols


def _truthy_any(frame: pd.DataFrame, cols: list[str]) -> pd.Series:
    if not cols:
        return pd.Series(False, index=frame.index)
    signals = [_truthy_series(frame[col]) for col in cols]
    result = signals[0].copy()
    for signal in signals[1:]:
        result = result | signal
    return result.fillna(False).astype(bool)


def _truthy_series(values: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False).astype(bool)
    numeric = pd.to_numeric(values, errors="coerce")
    numeric_truth = numeric.fillna(0.0).ne(0.0)
    text = values.astype("string").fillna("").map(_normalize_name)
    text_truth = text.isin(
        {
            "true",
            "t",
            "yes",
            "y",
            "on",
            "signal",
            "trigger",
            "buy",
            "sell",
            "bid",
            "ask",
            "positive",
            "negative",
            "pos",
            "neg",
            "red_tower",
            "blue_tower",
            "buy_side_absorption",
            "sell_side_absorption",
            "buy_side_initiation",
            "sell_side_initiation",
            "buy_side_dominance",
            "sell_side_dominance",
            "extreme_positive_delta",
            "extreme_negative_delta",
            "extreme_positive_delta_close",
            "extreme_negative_delta_close",
            "positive_window_threshold",
            "negative_window_threshold",
        }
    )
    return numeric_truth | text_truth


def _text_contains_any(frame: pd.DataFrame, cols: list[str], needles: tuple[str, ...]) -> pd.Series:
    if not cols:
        return pd.Series(False, index=frame.index)
    normalized_needles = tuple(_normalize_name(needle) for needle in needles)
    result = pd.Series(False, index=frame.index)
    for col in cols:
        text = frame[col].astype("string").fillna("").map(_normalize_name)
        col_match = pd.Series(False, index=frame.index)
        for needle in normalized_needles:
            col_match = col_match | text.str.contains(re.escape(needle), regex=True, na=False)
        result = result | col_match
    return result.fillna(False).astype(bool)


def _first_numeric(frame: pd.DataFrame, cols: list[str]) -> pd.Series:
    if not cols:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    out = pd.Series(np.nan, index=frame.index, dtype="float64")
    for col in cols:
        values = pd.to_numeric(frame[col], errors="coerce")
        out = out.mask(out.isna() & values.notna(), values)
    return out


def _any_bool(frame: pd.DataFrame, cols: tuple[str, ...]) -> pd.Series:
    result = pd.Series(False, index=frame.index)
    for col in cols:
        if col in frame.columns:
            result = result | frame[col].fillna(False).astype(bool)
    return result


def _to_utc_time(values: pd.Series, timezone: str) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce")
    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(str(timezone), ambiguous="NaT", nonexistent="shift_forward")
    return parsed.dt.tz_convert("UTC")


def _normalize_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("%", " percent ")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


__all__ = [
    "MotiveWaveContextArtifacts",
    "MotiveWaveContextConfig",
    "build_motivewave_context",
    "render_motivewave_context_report",
    "write_motivewave_context_artifacts",
]
