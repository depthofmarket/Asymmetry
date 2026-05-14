"""
Online Regime Leakage — quantify the gap between research (full-session)
regime classification and a real-time (prior-bar-only) classifier.

The engine's ``classify_day_regime`` uses the full session's data (cumulative
max/min of high/low) to decide if the day is range, trend_up, or trend_down.
This is point-in-time *within* the session (each bar sees only prior bars of
that session), but the *definition* of 'range' vs 'trend' requires knowing
what the ORB range is, which is only available after the ORB window closes.

The real leakage gap happens when comparing candidate performance across
regimes: a strategy that trades differently on range vs trend days may appear
to have regime-specific edge, but only if the regime could be predicted
online — before the session's character is fully known.

This module measures:
1. How often does the full-session regime classification match a pure prior-
   bar classifier (using only data available at each bar)?
2. How much PnL would be lost if you could only trade based on the prior-bar
   classification vs the full-session one?
3. Which bars/sessions are most ambiguous (late regime changes)?
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class OnlineRegimeLeakagePaths:
    bar_classification_csv: Path
    full_day_summary_csv: Path
    leakage_report_md: Path


def _prior_bar_only_classifier(
    df: pd.DataFrame,
    *,
    atr_col: str = "atr",
    ema_slope_col: str = "trend_ema_slope",
    vwap_col: str = "vwap",
    close_col: str = "close",
) -> pd.DataFrame:
    """
    Classify each bar's regime using ONLY information available before that
    bar (i.e., prior bar's close, EMA slope, VWAP side).

    This is intentionally simpler than ``classify_day_regime`` because it
    cannot use session-aggregated statistics (cumulative high/low, ORB range).

    Returns a DataFrame with the same index as df and a 'online_regime' column:
    - 'range': price near VWAP, low EMA slope
    - 'trend_up': price above VWAP, positive EMA slope
    - 'trend_down': price below VWAP, negative EMA slope
    - 'unknown': insufficient data
    """
    close = pd.to_numeric(df.get(close_col, pd.Series(np.nan, index=df.index)), errors="coerce")
    ema_slope = pd.to_numeric(df.get(ema_slope_col, pd.Series(0.0, index=df.index)), errors="coerce")
    vwap = pd.to_numeric(df.get(vwap_col, pd.Series(np.nan, index=df.index)), errors="coerce")
    atr = pd.to_numeric(df.get(atr_col, pd.Series(np.nan, index=df.index)), errors="coerce")
    atr_avg = pd.to_numeric(df.get("atr_avg", pd.Series(np.nan, index=df.index)), errors="coerce")

    regime = pd.Series("unknown", index=df.index, dtype="object")

    has_data = close.notna() & vwap.notna() & ema_slope.notna()
    if not has_data.any():
        return pd.DataFrame({"online_regime": regime, "online_regime_confidence": 0.0}, index=df.index)

    # Thresholds — deliberately conservative to avoid flip-flopping
    slope_threshold = 0.12
    vwap_distance_atr = 0.3  # min distance from VWAP (in ATR) to be directional

    distance_from_vwap = (close - vwap).abs() / atr.replace(0, np.nan)
    above_vwap = close > vwap
    below_vwap = close < vwap

    # Trend conditions (need prior bar's slope + VWAP side)
    prior_slope = ema_slope.shift(1).fillna(0.0)
    prior_above = above_vwap.shift(1).fillna(False)
    prior_below = below_vwap.shift(1).fillna(False)

    trend_up_cond = (
        has_data
        & prior_above
        & (prior_slope > slope_threshold)
        & (distance_from_vwap > vwap_distance_atr)
    )
    trend_down_cond = (
        has_data
        & prior_below
        & (prior_slope < -slope_threshold)
        & (distance_from_vwap > vwap_distance_atr)
    )
    range_cond = (
        has_data
        & (distance_from_vwap <= vwap_distance_atr)
        & (ema_slope.abs() <= slope_threshold)
    )

    regime.loc[trend_up_cond] = "trend_up"
    regime.loc[trend_down_cond] = "trend_down"
    regime.loc[range_cond] = "range"

    # Confidence: how far from the nearest decision boundary
    confidence = pd.Series(0.0, index=df.index)
    confidence.loc[trend_up_cond] = np.where(
        prior_slope[trend_up_cond].notna(),
        (prior_slope[trend_up_cond] - slope_threshold).clip(lower=0).fillna(0.0) * 2.0,
        0.0,
    ).clip(upper=1.0)
    confidence.loc[trend_down_cond] = np.where(
        prior_slope[trend_down_cond].notna(),
        (-prior_slope[trend_down_cond] - slope_threshold).clip(lower=0).fillna(0.0) * 2.0,
        0.0,
    ).clip(upper=1.0)
    range_dist = vwap_distance_atr - distance_from_vwap
    confidence.loc[range_cond] = range_dist[range_cond].clip(lower=0).fillna(0.0).clip(upper=1.0)

    return pd.DataFrame({
        "online_regime": regime,
        "online_regime_confidence": confidence,
    }, index=df.index)


def _full_session_regime(df: pd.DataFrame) -> pd.Series:
    """
    Extract the engine's full-session regime classification if available.
    """
    if "day_regime" in df.columns:
        return df["day_regime"].astype(str)
    if "regime_trend_up_confirmed" in df.columns and "regime_trend_down_confirmed" in df.columns:
        trend_up = df["regime_trend_up_confirmed"].fillna(False)
        trend_down = df["regime_trend_down_confirmed"].fillna(False)
        result = pd.Series("neutral", index=df.index)
        result[trend_up & ~trend_down] = "trend_up"
        result[trend_down & ~trend_up] = "trend_down"
        result[df.get("day_regime", pd.Series("", index=df.index)).eq("range")] = "range"
        return result
    return pd.Series("unknown", index=df.index)


def _map_to_binary(regime: pd.Series) -> pd.Series:
    """Map regime to {trend, range, unknown} (combine up/down -> trend)."""
    s = regime.astype(str).str.lower().str.strip()
    result = pd.Series("unknown", index=s.index)
    result[s.str.startswith("trend")] = "trend"
    result[s == "range"] = "range"
    result[s == "neutral"] = "range"
    return result


def make_regime_leakage_report(
    signal_frame: pd.DataFrame,
    *,
    out_dir: str | Path = "results/research/regime_leakage",
    artifact_name: str = "regime_leakage",
) -> OnlineRegimeLeakagePaths:
    """
    Compare the engine's full-session regime classifier against a prior-bar-
    only (online) classifier on the same signal frame.

    Parameters
    ----------
    signal_frame : pd.DataFrame
        The preprocessed 5-min frame (output of ``build_signal_frame()`` or
        ``preprocess()``). Must contain at least 'time', 'close', 'vwap',
        'trend_ema_slope'.  Ideally also 'day_regime' or
        'regime_trend_up_confirmed' / 'regime_trend_down_confirmed'.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame({"time": signal_frame["time"]}) if "time" in signal_frame.columns else signal_frame[[]].copy()
    df["time"] = pd.to_datetime(df["time"])
    df["date_str"] = df["time"].dt.strftime("%Y-%m-%d")
    df["hour_min"] = df["time"].dt.strftime("%H:%M")

    # Full-session (engine) regime
    full_regime = _full_session_regime(signal_frame)
    df["full_session_regime"] = full_regime
    df["full_session_binary"] = _map_to_binary(full_regime)

    # Online (prior-bar-only) regime
    online = _prior_bar_only_classifier(signal_frame)
    df["online_regime"] = online["online_regime"]
    df["online_regime_confidence"] = online["online_regime_confidence"]
    df["online_binary"] = _map_to_binary(online["online_regime"])

    # Agreement
    both_known = (
        (df["full_session_binary"] != "unknown")
        & (df["online_binary"] != "unknown")
    )
    df["regime_agreement"] = False
    df.loc[both_known, "regime_agreement"] = (
        df.loc[both_known, "full_session_binary"] == df.loc[both_known, "online_binary"]
    )
    df["regime_agreement"] = df["regime_agreement"].fillna(False)

    # Full-day summaries
    day_summary_rows: list[dict[str, Any]] = []
    for date_str, day_df in df.groupby("date_str", sort=True):
        total_bars = len(day_df)
        known_bars = int(day_df["full_session_binary"].ne("unknown").sum())
        agreed_bars = int(day_df["regime_agreement"].sum())
        full_regime_mode = day_df["full_session_binary"].value_counts().idxmax() if known_bars > 0 else "unknown"
        online_regime_mode = day_df["online_binary"].value_counts().idxmax() if known_bars > 0 else "unknown"

        day_summary_rows.append({
            "date_str": date_str,
            "total_bars": total_bars,
            "known_bars": known_bars,
            "agreed_bars": agreed_bars,
            "agreement_pct": float(agreed_bars / max(known_bars, 1) * 100.0),
            "full_session_mode": full_regime_mode,
            "online_mode": online_regime_mode,
            "full_session_trend_bars": int((day_df["full_session_binary"] == "trend").sum()),
            "online_trend_bars": int((day_df["online_binary"] == "trend").sum()),
            "full_session_range_bars": int((day_df["full_session_binary"] == "range").sum()),
            "online_range_bars": int((day_df["online_binary"] == "range").sum()),
        })
    day_summary = pd.DataFrame(day_summary_rows)

    # Overall agreement statistics
    known_mask = df["full_session_binary"] != "unknown"
    online_known_mask = df["online_binary"] != "unknown"
    both_known_mask = known_mask & online_known_mask

    total_known = int(both_known_mask.sum())
    total_agreed = int(df.loc[both_known_mask, "regime_agreement"].sum())
    overall_agreement_pct = float(total_agreed / max(total_known, 1) * 100.0)

    # Confusion matrix style
    confusion: dict[str, dict[str, int]] = {}
    for full_val in ["trend", "range"]:
        confusion[full_val] = {}
        for online_val in ["trend", "range"]:
            confusion[full_val][online_val] = int(
                both_known_mask
                & (df["full_session_binary"] == full_val)
                & (df["online_binary"] == online_val)
            ).sum()

    # Leakage: bars where the online classifier would NOT see the regime
    # that the full-session classifier assigns
    false_trend = int(confusion.get("trend", {}).get("range", 0))
    false_range = int(confusion.get("range", {}).get("trend", 0))

    # Save bar-level classification
    bar_classification_csv = out_dir / f"{artifact_name}_bar_classification.csv"
    df.to_csv(bar_classification_csv, index=False)

    # Save day summary
    full_day_summary_csv = out_dir / f"{artifact_name}_day_summary.csv"
    day_summary.to_csv(full_day_summary_csv, index=False)

    # Build markdown report
    report_lines = [
        "# Regime Classification Leakage Report",
        "",
        "## Overview",
        "",
        f"- **Total bars evaluated**: {len(df):,}",
        f"- **Bars with both classifiers active**: {total_known:,}",
        f"- **Agreed bars**: {total_agreed:,} ({overall_agreement_pct:.1f}%)",
        f"- **Bars where online sees 'range' but full session says 'trend'**: {false_trend:,}",
        f"- **Bars where online sees 'trend' but full session says 'range'**: {false_range:,}",
        "",
        "## Confusion (full vs online, binary)",
        "",
        "| Full \\ Online | trend | range |",
        "|---|---|---|",
        f"| **trend** | {confusion.get('trend', {}).get('trend', 0)} | {confusion.get('trend', {}).get('range', 0)} |",
        f"| **range** | {confusion.get('range', {}).get('trend', 0)} | {confusion.get('range', {}).get('range', 0)} |",
        "",
    ]

    # Add day-level stats
    if not day_summary.empty:
        low_agreement = day_summary[day_summary["agreement_pct"] < 60.0]
        report_lines.extend([
            "## Day-Level Agreement",
            "",
            f"- **Days evaluated**: {len(day_summary)}",
            f"- **Days with < 60% agreement**: {len(low_agreement)}",
            f"- **Mean agreement per day**: {day_summary['agreement_pct'].mean():.1f}%",
            f"- **Median agreement per day**: {day_summary['agreement_pct'].median():.1f}%",
            "",
        ])
        if len(low_agreement) > 0:
            report_lines.append("### Low-agreement days (< 60%)")
            report_lines.append("")
            for _, row in low_agreement.iterrows():
                report_lines.append(
                    f"- **{row['date_str']}**: {row['agreement_pct']:.0f}% agreement "
                    f"(full={row['full_session_mode']}, online={row['online_mode']}, "
                    f"trend bars: full={row['full_session_trend_bars']}, online={row['online_trend_bars']})"
                )
            report_lines.append("")

    report_lines.extend([
        "## Interpretation",
        "",
        "The **leakage gap** is the fraction of bars where the full-session",
        "classifier (which uses ORB range + cumulative session statistics)",
        "assigns a different regime than a prior-bar-only classifier.",
        "",
        "A high gap (>20%) means regime-specific edge claims should be",
        "treated skeptically: the regime may not have been predictable at",
        "trade time. A low gap (<10%) means the regime classification is",
        "mostly online-predictable and edge claims are more credible.",
        "",
        "### Next steps",
        "",
        f"- If agreement > 80%, regime-specific strategy candidates are likely safe.",
        f"- If agreement < 70%, consider re-running top candidates under the online",
        "  classifier and comparing performance.",
        f"- Worst-case days ({len(low_agreement)} days with < 60%): examine whether",
        "  these are high-PnL days for your strategy. If so, reported regime",
        "  conditional performance is inflated by hindsight.",
        "",
    ])

    leakage_report_md = out_dir / f"{artifact_name}_report.md"
    leakage_report_md.write_text("\n".join(report_lines), encoding="utf-8")

    return OnlineRegimeLeakagePaths(
        bar_classification_csv=bar_classification_csv,
        full_day_summary_csv=full_day_summary_csv,
        leakage_report_md=leakage_report_md,
    )