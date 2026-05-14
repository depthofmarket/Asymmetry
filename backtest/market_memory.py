from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


MARKET_MEMORY_FEATURE_COLUMNS = [
    "market_memory_return_points",
    "market_memory_log_return",
    "market_memory_hurst",
    "market_memory_hurst_regime",
    "market_memory_entropy",
    "market_memory_entropy_regime",
    "market_memory_lz_complexity",
    "market_memory_lz_regime",
    "market_memory_tail_alpha",
    "market_memory_tail_alpha_regime",
    "market_memory_tail_threshold_points",
    "market_memory_tail_event",
    "market_memory_state",
]


@dataclass(frozen=True)
class MarketMemoryReportPaths:
    feature_summary_csv: Path
    state_summary_csv: Path
    period_summary_csv: Path
    drift_csv: Path
    warnings_csv: Path
    report_md: Path


def _finite(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    return values[np.isfinite(values)]


def estimate_hurst_rs(values: np.ndarray, *, min_chunk: int = 8) -> float:
    """
    Rolling R/S Hurst estimate using only the supplied historical window.

    This is intentionally modest: enough to label persistence vs mean
    reversion, not enough to justify parameter mining on tiny differences.
    """
    x = _finite(values)
    n = len(x)
    if n < max(min_chunk * 2, 16):
        return np.nan

    chunk_sizes = [s for s in (8, 12, 16, 24, 32, 48, 64, 96, 128) if s <= n // 2]
    rs_values: list[float] = []
    used_sizes: list[int] = []
    for size in chunk_sizes:
        chunks = n // size
        if chunks < 2:
            continue
        sample = x[-chunks * size :].reshape(chunks, size)
        chunk_rs: list[float] = []
        for chunk in sample:
            centered = chunk - np.mean(chunk)
            scale = np.std(chunk, ddof=1)
            if not np.isfinite(scale) or scale <= 0:
                continue
            cumulative = np.cumsum(centered)
            observed_range = float(np.max(cumulative) - np.min(cumulative))
            if observed_range > 0:
                chunk_rs.append(observed_range / scale)
        if chunk_rs:
            rs_values.append(float(np.mean(chunk_rs)))
            used_sizes.append(size)

    if len(rs_values) < 2:
        return np.nan

    rs = np.asarray(rs_values, dtype=float)
    sizes = np.asarray(used_sizes, dtype=float)
    valid = np.isfinite(rs) & (rs > 0)
    if valid.sum() < 2:
        return np.nan
    slope, _ = np.polyfit(np.log(sizes[valid]), np.log(rs[valid]), 1)
    return float(np.clip(slope, 0.0, 1.0))


def shannon_entropy(values: np.ndarray, *, bins: int = 10) -> float:
    x = _finite(values)
    if len(x) < 3:
        return np.nan
    lo = float(np.min(x))
    hi = float(np.max(x))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return 0.0

    hist, _ = np.histogram(x, bins=max(2, int(bins)), range=(lo, hi))
    total = int(hist.sum())
    if total <= 0:
        return np.nan
    p = hist[hist > 0].astype(float) / float(total)
    entropy = -float(np.sum(p * np.log(p)))
    return entropy / float(np.log(max(2, int(bins))))


def lempel_ziv_complexity(binary_sequence: np.ndarray) -> float:
    seq = [str(int(x)) for x in np.asarray(binary_sequence) if pd.notna(x)]
    n = len(seq)
    if n < 4:
        return np.nan

    text = "".join(seq)
    seen: set[str] = set()
    complexity = 0
    i = 0
    while i < n:
        added = False
        for j in range(i + 1, n + 1):
            phrase = text[i:j]
            if phrase not in seen or j == n:
                seen.add(phrase)
                complexity += 1
                i = j
                added = True
                break
        if not added:
            break

    random_baseline = n / np.log2(n)
    if random_baseline <= 0:
        return np.nan
    return float(complexity / random_baseline)


def hill_tail_alpha(
    values: np.ndarray,
    *,
    tail_fraction: float = 0.10,
    min_tail_observations: int = 8,
) -> float:
    x = np.abs(_finite(values))
    x = x[x > 0]
    if len(x) < max(min_tail_observations * 2, 20):
        return np.nan
    sorted_desc = np.sort(x)[::-1]
    k = max(int(len(sorted_desc) * float(tail_fraction)), int(min_tail_observations))
    k = min(k, len(sorted_desc) - 1)
    if k <= 1:
        return np.nan
    tail = sorted_desc[:k]
    threshold = float(tail[-1])
    if threshold <= 0:
        return np.nan
    logs = np.log(tail / threshold)
    mean_log = float(np.mean(logs))
    if mean_log <= 0 or not np.isfinite(mean_log):
        return np.nan
    return float(1.0 / mean_log)


def _rolling_sparse(
    values: np.ndarray,
    *,
    window: int,
    min_bars: int,
    recompute_every: int,
    func,
) -> pd.Series:
    arr = np.asarray(values, dtype=float)
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)
    window = max(1, int(window))
    min_bars = max(1, int(min_bars))
    recompute_every = max(1, int(recompute_every))

    for end in range(n):
        available = end + 1
        if available < min_bars:
            continue
        if end != min_bars - 1 and end % recompute_every != 0 and end != n - 1:
            continue
        start = max(0, available - window)
        sample = arr[start:available]
        if np.isfinite(sample).sum() < min_bars:
            continue
        out[end] = func(sample)

    return pd.Series(out).ffill()


def _label_hurst(hurst: pd.Series, low: float, high: float) -> pd.Series:
    out = pd.Series("unknown", index=hurst.index, dtype="object")
    out.loc[hurst.notna()] = "neutral_memory"
    out.loc[hurst.le(low)] = "mean_reverting_memory"
    out.loc[hurst.ge(high)] = "persistent_memory"
    return out


def _label_high_low(series: pd.Series, low: float, high: float, low_label: str, high_label: str) -> pd.Series:
    out = pd.Series("unknown", index=series.index, dtype="object")
    out.loc[series.notna()] = "neutral"
    out.loc[series.le(low)] = low_label
    out.loc[series.ge(high)] = high_label
    return out


def _label_tail_alpha(alpha: pd.Series, fat_threshold: float, thin_threshold: float) -> pd.Series:
    out = pd.Series("unknown", index=alpha.index, dtype="object")
    out.loc[alpha.notna()] = "normal_tail"
    out.loc[alpha.le(fat_threshold)] = "fat_tail"
    out.loc[alpha.ge(thin_threshold)] = "thin_tail"
    return out


def add_market_memory_features(
    df: pd.DataFrame,
    *,
    hurst_window_bars: int = 156,
    hurst_min_bars: int = 64,
    entropy_window_bars: int = 156,
    entropy_min_bars: int = 64,
    entropy_bins: int = 10,
    lz_window_bars: int = 96,
    lz_min_bars: int = 48,
    tail_window_bars: int = 390,
    tail_min_bars: int = 120,
    tail_fraction: float = 0.10,
    tail_min_observations: int = 8,
    tail_event_quantile: float = 0.99,
    recompute_every_bars: int = 6,
    hurst_low_threshold: float = 0.45,
    hurst_high_threshold: float = 0.55,
    entropy_low_threshold: float = 0.55,
    entropy_high_threshold: float = 0.85,
    lz_low_threshold: float = 0.75,
    lz_high_threshold: float = 1.05,
    tail_alpha_fat_threshold: float = 3.0,
    tail_alpha_thin_threshold: float = 5.0,
) -> pd.DataFrame:
    required = {"close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Market-memory features require columns: {sorted(missing)}")

    out = df.copy()
    close = pd.to_numeric(out["close"], errors="coerce")
    out["market_memory_return_points"] = close.diff()
    with np.errstate(divide="ignore", invalid="ignore"):
        out["market_memory_log_return"] = np.log(close).diff()

    log_returns = pd.to_numeric(out["market_memory_log_return"], errors="coerce")
    point_returns = pd.to_numeric(out["market_memory_return_points"], errors="coerce")

    out["market_memory_hurst"] = _rolling_sparse(
        log_returns.to_numpy(),
        window=hurst_window_bars,
        min_bars=hurst_min_bars,
        recompute_every=recompute_every_bars,
        func=estimate_hurst_rs,
    ).to_numpy()
    out["market_memory_entropy"] = _rolling_sparse(
        log_returns.to_numpy(),
        window=entropy_window_bars,
        min_bars=entropy_min_bars,
        recompute_every=recompute_every_bars,
        func=lambda sample: shannon_entropy(sample, bins=entropy_bins),
    ).to_numpy()
    binary_returns = np.where(log_returns.to_numpy() > 0, 1.0, 0.0)
    binary_returns[~np.isfinite(log_returns.to_numpy())] = np.nan
    out["market_memory_lz_complexity"] = _rolling_sparse(
        binary_returns,
        window=lz_window_bars,
        min_bars=lz_min_bars,
        recompute_every=recompute_every_bars,
        func=lempel_ziv_complexity,
    ).to_numpy()
    out["market_memory_tail_alpha"] = _rolling_sparse(
        log_returns.to_numpy(),
        window=tail_window_bars,
        min_bars=tail_min_bars,
        recompute_every=recompute_every_bars,
        func=lambda sample: hill_tail_alpha(
            sample,
            tail_fraction=tail_fraction,
            min_tail_observations=tail_min_observations,
        ),
    ).to_numpy()

    abs_return_points = point_returns.abs()
    out["market_memory_tail_threshold_points"] = (
        abs_return_points.rolling(window=int(tail_window_bars), min_periods=int(tail_min_bars))
        .quantile(float(tail_event_quantile))
        .shift(1)
    )
    out["market_memory_tail_event"] = (
        abs_return_points.gt(pd.to_numeric(out["market_memory_tail_threshold_points"], errors="coerce"))
        & out["market_memory_tail_threshold_points"].notna()
    )

    out["market_memory_hurst_regime"] = _label_hurst(
        pd.to_numeric(out["market_memory_hurst"], errors="coerce"),
        float(hurst_low_threshold),
        float(hurst_high_threshold),
    )
    out["market_memory_entropy_regime"] = _label_high_low(
        pd.to_numeric(out["market_memory_entropy"], errors="coerce"),
        float(entropy_low_threshold),
        float(entropy_high_threshold),
        "low_entropy",
        "high_entropy",
    )
    out["market_memory_lz_regime"] = _label_high_low(
        pd.to_numeric(out["market_memory_lz_complexity"], errors="coerce"),
        float(lz_low_threshold),
        float(lz_high_threshold),
        "low_complexity",
        "high_complexity",
    )
    out["market_memory_tail_alpha_regime"] = _label_tail_alpha(
        pd.to_numeric(out["market_memory_tail_alpha"], errors="coerce"),
        float(tail_alpha_fat_threshold),
        float(tail_alpha_thin_threshold),
    )

    state = pd.Series("unknown", index=out.index, dtype="object")
    has_any = (
        out["market_memory_hurst"].notna()
        | out["market_memory_entropy"].notna()
        | out["market_memory_lz_complexity"].notna()
        | out["market_memory_tail_alpha"].notna()
    )
    state.loc[has_any] = "neutral_memory"
    state.loc[out["market_memory_hurst_regime"].eq("persistent_memory")] = "persistent_memory"
    state.loc[out["market_memory_hurst_regime"].eq("mean_reverting_memory")] = "mean_reverting_memory"
    state.loc[
        out["market_memory_entropy_regime"].eq("high_entropy")
        | out["market_memory_lz_regime"].eq("high_complexity")
    ] = "chaotic_memory"
    state.loc[
        out["market_memory_tail_event"].fillna(False)
        | out["market_memory_tail_alpha_regime"].eq("fat_tail")
    ] = "tail_risk_memory"
    out["market_memory_state"] = state
    return out


def wasserstein_distance_1d(
    baseline: pd.Series | np.ndarray,
    comparison: pd.Series | np.ndarray,
    *,
    n_quantiles: int = 101,
) -> float:
    a = _finite(np.asarray(baseline, dtype=float))
    b = _finite(np.asarray(comparison, dtype=float))
    if len(a) == 0 or len(b) == 0:
        return np.nan
    q = np.linspace(0.0, 1.0, max(3, int(n_quantiles)))
    return float(np.mean(np.abs(np.quantile(a, q) - np.quantile(b, q))))


def _profit_factor(points: pd.Series) -> float:
    values = pd.to_numeric(points, errors="coerce").dropna()
    wins = float(values[values > 0].sum())
    losses = abs(float(values[values <= 0].sum()))
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def _feature_columns(bars: pd.DataFrame) -> list[str]:
    return [col for col in MARKET_MEMORY_FEATURE_COLUMNS if col in bars.columns]


def summarize_market_memory_features(bars: pd.DataFrame) -> pd.DataFrame:
    numeric_cols = [
        "market_memory_hurst",
        "market_memory_entropy",
        "market_memory_lz_complexity",
        "market_memory_tail_alpha",
        "market_memory_tail_threshold_points",
    ]
    rows: list[dict[str, object]] = []
    for col in numeric_cols:
        if col not in bars.columns:
            continue
        values = pd.to_numeric(bars[col], errors="coerce").dropna()
        if values.empty:
            rows.append({"feature": col, "observations": 0})
            continue
        rows.append(
            {
                "feature": col,
                "observations": int(len(values)),
                "mean": float(values.mean()),
                "median": float(values.median()),
                "std": float(values.std(ddof=0)),
                "p05": float(np.percentile(values, 5)),
                "p25": float(np.percentile(values, 25)),
                "p75": float(np.percentile(values, 75)),
                "p95": float(np.percentile(values, 95)),
            }
        )
    return pd.DataFrame(rows)


def summarize_market_memory_states(
    bars: pd.DataFrame,
    *,
    forward_horizon_bars: int = 3,
) -> pd.DataFrame:
    if "close" not in bars.columns:
        return pd.DataFrame()
    work = bars.copy()
    work["forward_return_points"] = pd.to_numeric(work["close"], errors="coerce").shift(-int(forward_horizon_bars)) - pd.to_numeric(
        work["close"], errors="coerce"
    )
    work["forward_abs_return_points"] = work["forward_return_points"].abs()

    group_cols = [
        "market_memory_state",
        "market_memory_hurst_regime",
        "market_memory_entropy_regime",
        "market_memory_lz_regime",
        "market_memory_tail_alpha_regime",
        "market_memory_tail_event",
    ]
    rows: list[dict[str, object]] = []
    for col in group_cols:
        if col not in work.columns:
            continue
        for value, group in work.groupby(col, dropna=False, sort=True):
            fwd = pd.to_numeric(group["forward_return_points"], errors="coerce").dropna()
            if fwd.empty:
                continue
            rows.append(
                {
                    "context_type": col.replace("market_memory_", ""),
                    "context_value": value,
                    "bars": int(len(fwd)),
                    "sample_share_pct": float(len(fwd) / len(work) * 100.0),
                    "avg_forward_points": float(fwd.mean()),
                    "median_forward_points": float(fwd.median()),
                    "avg_abs_forward_points": float(fwd.abs().mean()),
                    "up_rate_pct": float(fwd.gt(0).mean() * 100.0),
                    "directionless_profit_factor": _profit_factor(fwd),
                }
            )
    return pd.DataFrame(rows).sort_values(["context_type", "bars"], ascending=[True, False]).reset_index(drop=True)


def summarize_market_memory_periods(
    bars: pd.DataFrame,
    *,
    period: str = "Q",
    forward_horizon_bars: int = 3,
) -> pd.DataFrame:
    if "time" not in bars.columns or "market_memory_state" not in bars.columns or "close" not in bars.columns:
        return pd.DataFrame()
    work = bars.copy()
    work["time"] = pd.to_datetime(work["time"])
    work["period"] = work["time"].dt.to_period(period).astype(str)
    work["forward_return_points"] = pd.to_numeric(work["close"], errors="coerce").shift(-int(forward_horizon_bars)) - pd.to_numeric(
        work["close"], errors="coerce"
    )
    rows: list[dict[str, object]] = []
    for (state, label), group in work.groupby(["market_memory_state", "period"], dropna=False, sort=True):
        fwd = pd.to_numeric(group["forward_return_points"], errors="coerce").dropna()
        if fwd.empty:
            continue
        rows.append(
            {
                "market_memory_state": state,
                "period": label,
                "bars": int(len(fwd)),
                "avg_forward_points": float(fwd.mean()),
                "avg_abs_forward_points": float(fwd.abs().mean()),
                "up_rate_pct": float(fwd.gt(0).mean() * 100.0),
            }
        )
    return pd.DataFrame(rows).sort_values(["period", "market_memory_state"]).reset_index(drop=True)


def summarize_market_memory_drift(
    bars: pd.DataFrame,
    *,
    recent_fraction: float = 0.25,
    n_quantiles: int = 101,
) -> pd.DataFrame:
    numeric_cols = [
        "market_memory_hurst",
        "market_memory_entropy",
        "market_memory_lz_complexity",
        "market_memory_tail_alpha",
        "market_memory_return_points",
    ]
    available = [col for col in numeric_cols if col in bars.columns]
    if not available:
        return pd.DataFrame()

    n = len(bars)
    recent_n = max(1, int(n * float(recent_fraction)))
    if n - recent_n < 10 or recent_n < 10:
        return pd.DataFrame()
    baseline = bars.iloc[: n - recent_n]
    recent = bars.iloc[n - recent_n :]

    rows: list[dict[str, object]] = []
    for col in available:
        base = pd.to_numeric(baseline[col], errors="coerce").dropna()
        comp = pd.to_numeric(recent[col], errors="coerce").dropna()
        if len(base) < 10 or len(comp) < 10:
            rows.append({"feature": col, "baseline_observations": int(len(base)), "recent_observations": int(len(comp))})
            continue
        distance = wasserstein_distance_1d(base, comp, n_quantiles=n_quantiles)
        iqr = float(np.percentile(base, 75) - np.percentile(base, 25))
        normalized = distance / iqr if iqr > 0 else np.nan
        rows.append(
            {
                "feature": col,
                "baseline_observations": int(len(base)),
                "recent_observations": int(len(comp)),
                "baseline_mean": float(base.mean()),
                "recent_mean": float(comp.mean()),
                "wasserstein_distance": float(distance),
                "baseline_iqr": iqr,
                "normalized_wasserstein": float(normalized) if np.isfinite(normalized) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("normalized_wasserstein", ascending=False, na_position="last")


def build_market_memory_warnings(
    bars: pd.DataFrame,
    drift: pd.DataFrame,
    *,
    drift_warning_threshold: float = 0.75,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if not _feature_columns(bars):
        rows.append(
            {
                "warning": "market_memory_features_missing",
                "severity": "review",
                "detail": "No market-memory columns are present. Enable market_memory_enabled or a market-memory candidate.",
            }
        )
        return pd.DataFrame(rows)

    if "market_memory_state" in bars.columns:
        states = bars["market_memory_state"].dropna().astype(str)
        observed = set(states.unique())
        if len(observed) <= 2:
            rows.append(
                {
                    "warning": "low_state_diversity",
                    "severity": "hypothesis",
                    "detail": f"Only {len(observed)} market-memory states were observed: {sorted(observed)}.",
                }
            )
        tail_share = float(states.eq("tail_risk_memory").mean() * 100.0) if len(states) else 0.0
        if tail_share > 20.0:
            rows.append(
                {
                    "warning": "frequent_tail_risk_state",
                    "severity": "review",
                    "detail": f"Tail-risk memory state appears on {tail_share:.1f}% of bars; thresholds may be too loose.",
                }
            )

    if not drift.empty and "normalized_wasserstein" in drift.columns:
        shifted = drift[pd.to_numeric(drift["normalized_wasserstein"], errors="coerce").gt(float(drift_warning_threshold))]
        for _, row in shifted.iterrows():
            rows.append(
                {
                    "warning": "feature_distribution_drift",
                    "severity": "review",
                    "detail": f"{row.get('feature')} recent distribution drift is {float(row.get('normalized_wasserstein')):.2f} baseline IQRs.",
                }
            )

    return pd.DataFrame(rows)


def _fmt(value: object, decimals: int = 3) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(number):
        return "nan"
    return f"{number:.{decimals}f}"


def _markdown_table(df: pd.DataFrame, columns: list[str], *, max_rows: int = 10) -> list[str]:
    if df.empty:
        return ["No rows."]
    shown = df.head(max_rows)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in shown.iterrows():
        values = []
        for col in columns:
            value = row.get(col, "")
            values.append(_fmt(value) if isinstance(value, (float, int, np.number)) else str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def _write_market_memory_markdown(
    path: Path,
    feature_summary: pd.DataFrame,
    state_summary: pd.DataFrame,
    drift: pd.DataFrame,
    warnings: pd.DataFrame,
) -> None:
    lines = [
        "# Market Memory Report",
        "",
        "Point-in-time Hurst, entropy, Lempel-Ziv complexity, tail-risk, and distribution-drift diagnostics.",
        "These are research contexts for NQ futures execution, not a standalone strategy.",
        "",
        "## Feature Summary",
        "",
    ]
    lines.extend(
        _markdown_table(
            feature_summary,
            ["feature", "observations", "mean", "median", "p05", "p95"],
            max_rows=12,
        )
    )
    lines.extend(["", "## State Forward Returns", ""])
    lines.extend(
        _markdown_table(
            state_summary,
            ["context_type", "context_value", "bars", "avg_forward_points", "avg_abs_forward_points", "up_rate_pct"],
            max_rows=18,
        )
    )
    lines.extend(["", "## Recent Distribution Drift", ""])
    lines.extend(
        _markdown_table(
            drift,
            ["feature", "baseline_observations", "recent_observations", "wasserstein_distance", "normalized_wasserstein"],
            max_rows=10,
        )
    )
    lines.extend(["", "## Warnings", ""])
    if warnings.empty:
        lines.append("No warnings triggered.")
    else:
        for _, row in warnings.iterrows():
            lines.append(f"- **{row.get('severity', 'review')}** `{row.get('warning')}`: {row.get('detail')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_market_memory_report(
    bars: pd.DataFrame,
    out_dir: Path | str,
    *,
    artifact_name: str = "market_memory",
    period: str = "Q",
    forward_horizon_bars: int = 3,
    recent_fraction: float = 0.25,
    n_quantiles: int = 101,
    drift_warning_threshold: float = 0.75,
) -> MarketMemoryReportPaths:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    feature_summary_csv = out_dir / f"{artifact_name}_feature_summary.csv"
    state_summary_csv = out_dir / f"{artifact_name}_state_summary.csv"
    period_summary_csv = out_dir / f"{artifact_name}_period_summary.csv"
    drift_csv = out_dir / f"{artifact_name}_drift.csv"
    warnings_csv = out_dir / f"{artifact_name}_warnings.csv"
    report_md = out_dir / f"{artifact_name}_report.md"

    work = bars.copy()
    feature_summary = summarize_market_memory_features(work)
    state_summary = summarize_market_memory_states(work, forward_horizon_bars=forward_horizon_bars)
    period_summary = summarize_market_memory_periods(
        work,
        period=period,
        forward_horizon_bars=forward_horizon_bars,
    )
    drift = summarize_market_memory_drift(
        work,
        recent_fraction=recent_fraction,
        n_quantiles=n_quantiles,
    )
    warnings = build_market_memory_warnings(
        work,
        drift,
        drift_warning_threshold=drift_warning_threshold,
    )

    feature_summary.to_csv(feature_summary_csv, index=False)
    state_summary.to_csv(state_summary_csv, index=False)
    period_summary.to_csv(period_summary_csv, index=False)
    drift.to_csv(drift_csv, index=False)
    warnings.to_csv(warnings_csv, index=False)
    _write_market_memory_markdown(report_md, feature_summary, state_summary, drift, warnings)

    return MarketMemoryReportPaths(
        feature_summary_csv=feature_summary_csv,
        state_summary_csv=state_summary_csv,
        period_summary_csv=period_summary_csv,
        drift_csv=drift_csv,
        warnings_csv=warnings_csv,
        report_md=report_md,
    )
