from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Literal

_mpl_config_dir = Path("results/.mplconfig").resolve()
_mpl_config_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_mpl_config_dir))

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd

try:
    import seaborn as sns  # type: ignore
except Exception:  # pragma: no cover
    sns = None

CHART_BG = "#080d14"
CHART_PANEL = "#111827"
CHART_GRID = "#2b3a4f"
CHART_TEXT = "#e5eefb"
CHART_MUTED = "#94a3b8"
CHART_GREEN = "#34d399"
CHART_RED = "#fb7185"
CHART_BLUE = "#60a5fa"
CHART_CYAN = "#22d3ee"
CHART_AMBER = "#fbbf24"
CHART_ORANGE = "#fb923c"

BootstrapMode = Literal["trade", "day", "week", "month"]


@dataclass(frozen=True)
class MonteCarloSummary:
    n_sims: int
    bootstrap_mode: BootstrapMode
    final_equity_percentiles: dict[str, float]
    max_drawdown_percentiles: dict[str, float]
    cagr_like_percentiles: dict[str, float]
    paths_csv: Path
    paths_png: Path
    final_equity_png: Path
    max_drawdown_png: Path


@dataclass(frozen=True)
class AdvancedMonteCarloSummary:
    n_sims: int
    methods: list[str]
    summary_csv: Path
    distributions_csv: Path
    path_risk_csv: Path
    transition_matrix_csv: Path | None
    path_csvs: dict[str, Path]
    path_pngs: dict[str, Path]


@dataclass(frozen=True)
class StressTestSummary:
    scenarios: int
    summary_csv: Path


@dataclass(frozen=True)
class ExecutionDelayStressSummary:
    scenarios: int
    summary_csv: Path
    chart_png: Path


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _style_dark_axis(ax) -> None:
    ax.set_facecolor(CHART_PANEL)
    ax.tick_params(colors=CHART_MUTED)
    ax.xaxis.label.set_color(CHART_TEXT)
    ax.yaxis.label.set_color(CHART_TEXT)
    ax.title.set_color(CHART_TEXT)
    for spine in ax.spines.values():
        spine.set_edgecolor(CHART_GRID)
    ax.grid(True, color=CHART_GRID, alpha=0.28, linewidth=0.75)


def _style_monte_carlo_fan_axis(ax) -> None:
    ax.set_facecolor("#05070b")
    ax.tick_params(colors="#cbd5e1")
    ax.xaxis.label.set_color(CHART_TEXT)
    ax.yaxis.label.set_color(CHART_TEXT)
    ax.title.set_color("#f8fafc")
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(True, color="#243041", alpha=0.35, linewidth=0.7)


def _monte_carlo_fan_cmap() -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list(
        "monte_carlo_fan",
        [
            "#163246",
            "#1f6f86",
            "#2aa38f",
            "#9be7c4",
        ],
    )


def _annotate_vertical_line(ax, x: float, label: str, color: str) -> None:
    if not np.isfinite(x):
        return
    ymin, ymax = ax.get_ylim()
    ax.text(
        x,
        ymax - (ymax - ymin) * 0.08,
        label,
        rotation=90,
        va="top",
        ha="right",
        color=color,
        fontsize=9,
        fontweight="bold",
    )


def _render_monte_carlo_fan(
    ax,
    paths: np.ndarray,
    *,
    title: str,
    x_label: str,
    y_label: str,
    reference_path: np.ndarray | None = None,
) -> None:
    if paths.size == 0:
        ax.set_title(title, fontsize=17, fontweight="semibold", pad=18)
        ax.set_xlabel(x_label)
        ax.set_ylabel(y_label)
        _style_monte_carlo_fan_axis(ax)
        return

    cmap = _monte_carlo_fan_cmap()
    final_values = paths[:, -1]
    order = np.argsort(final_values)
    ranked = np.empty_like(order)
    ranked[order] = np.arange(len(order))
    color_positions = ranked / max(1, len(order) - 1)

    for idx, color_position in enumerate(color_positions):
        ax.plot(
            paths[idx],
            color=cmap(float(color_position)),
            linewidth=0.7,
            alpha=0.085,
            zorder=2,
        )

    x = np.arange(paths.shape[1], dtype=float)
    p10, p25, p50, p75, p90 = np.percentile(paths, [10, 25, 50, 75, 90], axis=0)
    ax.fill_between(x, p10, p90, color="#1b6076", alpha=0.18, linewidth=0, zorder=1)
    ax.fill_between(x, p25, p75, color="#37b3c9", alpha=0.22, linewidth=0, zorder=1)
    ax.plot(x, p50, color="#f8fafc", linewidth=1.6, alpha=0.92, zorder=3)

    if reference_path is not None and len(reference_path) == paths.shape[1]:
        ax.plot(x, reference_path, color=CHART_CYAN, linewidth=2.0, alpha=0.95, zorder=4)

    ax.axhline(0.0, color="#d8dee9", linewidth=0.8, alpha=0.28, zorder=0)
    ax.set_title(title, fontsize=17, fontweight="semibold", pad=18)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    _style_monte_carlo_fan_axis(ax)


def _equity_from_pnl(pnls: np.ndarray, starting_capital: float) -> np.ndarray:
    eq = np.empty(pnls.size + 1, dtype=float)
    eq[0] = float(starting_capital)
    np.cumsum(pnls, out=eq[1:])
    eq[1:] += eq[0]
    return eq


def _max_drawdown_pct(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / peak
    return float(np.nanmax(dd) * 100.0)


def _max_drawdown_dollars(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    return float(np.nanmax(peak - equity))


def _max_runup_pct(equity: np.ndarray, starting_capital: float) -> float:
    if equity.size == 0 or starting_capital <= 0:
        return 0.0
    return float((np.nanmax(equity) - starting_capital) / starting_capital * 100.0)


def _max_runup_dollars(equity: np.ndarray, starting_capital: float) -> float:
    if equity.size == 0:
        return 0.0
    return float(np.nanmax(equity) - starting_capital)


def _profit_factor(pnls: np.ndarray) -> float:
    wins = float(pnls[pnls > 0].sum())
    losses = abs(float(pnls[pnls <= 0].sum()))
    if losses == 0:
        return np.nan
    return wins / losses


def _percentiles(x: np.ndarray, ps: tuple[int, ...] = (5, 25, 50, 75, 95)) -> dict[str, float]:
    if x.size == 0:
        return {f"p{p}": 0.0 for p in ps}
    vals = np.percentile(x, ps)
    return {f"p{p}": float(v) for p, v in zip(ps, vals, strict=True)}


def _infer_years_covered(trades: pd.DataFrame) -> float:
    if "exit_time" not in trades.columns or len(trades) < 2:
        return 1.0
    t = pd.to_datetime(trades["exit_time"])
    days = (t.max() - t.min()).total_seconds() / (24 * 3600)
    return max(1.0 / 252.0, float(days / 365.25))


def _cagr_like(starting_capital: float, ending_equity: float, years: float) -> float:
    if starting_capital <= 0 or ending_equity <= 0 or years <= 0:
        return 0.0
    return float((ending_equity / starting_capital) ** (1.0 / years) - 1.0)


def _bootstrap_samples(
    trades: pd.DataFrame,
    mode: BootstrapMode,
    seed: int,
) -> tuple[np.ndarray, float]:
    """
    Returns (samples_1d, years_covered).

    - trade: sample trade pnls with replacement
    - day: sample daily pnl with replacement (preserves within-day clustering)
    - week: sample weekly pnl with replacement
    - month: sample monthly pnl with replacement
    """
    if "pnl" not in trades.columns or len(trades) == 0:
        return np.asarray([], dtype=float), 1.0

    years = _infer_years_covered(trades)

    if mode == "trade":
        pnls = trades["pnl"].astype(float).to_numpy()
        return pnls, years

    if "exit_time" not in trades.columns:
        pnls = trades["pnl"].astype(float).to_numpy()
        return pnls, years

    exit_time = pd.to_datetime(trades["exit_time"])
    if mode == "day":
        key = exit_time.dt.normalize()
    elif mode == "week":
        key = exit_time.dt.to_period("W").dt.start_time
    elif mode == "month":
        key = exit_time.dt.to_period("M").dt.to_timestamp()
    else:
        raise ValueError(f"Unsupported bootstrap mode: {mode}")

    grouped_pnl = trades.groupby(key)["pnl"].sum().astype(float).to_numpy()
    return grouped_pnl, years


def run_monte_carlo(
    results: dict[str, Any],
    starting_capital: float,
    artifact_name: str,
    n_sims: int = 2000,
    bootstrap_mode: BootstrapMode = "trade",
    seed: int = 7,
    out_dir: Path | str = "results/simulations",
    max_paths_to_plot: int = 200,
) -> MonteCarloSummary:
    trades = results.get("trades")
    if not isinstance(trades, pd.DataFrame) or len(trades) == 0:
        raise ValueError("results['trades'] must be a non-empty DataFrame to run Monte Carlo.")

    base_samples, years = _bootstrap_samples(trades, bootstrap_mode, seed=seed)
    if base_samples.size == 0:
        raise ValueError("No PnL samples available for Monte Carlo.")

    n_obs = int(base_samples.size)
    rng = np.random.default_rng(seed)

    final_equities = np.empty(n_sims, dtype=float)
    max_dds = np.empty(n_sims, dtype=float)
    cagrs = np.empty(n_sims, dtype=float)

    store_paths = min(int(max_paths_to_plot), n_sims)
    stored_paths = np.empty((store_paths, n_obs + 1), dtype=float)

    for i in range(n_sims):
        idx = rng.integers(0, n_obs, size=n_obs)
        sim_pnls = base_samples[idx]
        eq = _equity_from_pnl(sim_pnls, starting_capital=starting_capital)
        final_equities[i] = eq[-1]
        max_dds[i] = _max_drawdown_pct(eq)
        cagrs[i] = _cagr_like(starting_capital, eq[-1], years=years)
        if i < store_paths:
            stored_paths[i] = eq

    out_dir = Path(out_dir)
    _ensure_dir(out_dir)

    paths_csv = out_dir / f"{artifact_name}_mc_paths_{bootstrap_mode}.csv"
    pd.DataFrame(stored_paths).to_csv(paths_csv, index=False)
    paths_png = out_dir / f"{artifact_name}_mc_paths_{bootstrap_mode}.png"
    final_equity_png = out_dir / f"{artifact_name}_mc_final_equity_{bootstrap_mode}.png"
    max_drawdown_png = out_dir / f"{artifact_name}_mc_max_dd_{bootstrap_mode}.png"

    plotted_pnl_paths = stored_paths - float(starting_capital)
    observed_pnl_path = np.concatenate(([0.0], np.cumsum(base_samples, dtype=float)))
    x_label = "trade #" if bootstrap_mode == "trade" else f"{bootstrap_mode} bucket #"

    fig, ax = plt.subplots(figsize=(13.5, 7.0))
    fig.patch.set_facecolor(CHART_BG)
    _render_monte_carlo_fan(
        ax,
        plotted_pnl_paths,
        title=f"Monte Carlo - {n_sims:,} bootstrapped paths ({store_paths:,} shown individually)\nEquity-curve fan",
        x_label=x_label,
        y_label="cumulative P&L ($)",
        reference_path=observed_pnl_path,
    )
    plt.tight_layout()
    plt.savefig(paths_png, dpi=160, facecolor=fig.get_facecolor())
    plt.close()

    fig, ax = plt.subplots(figsize=(10, 4.8))
    fig.patch.set_facecolor(CHART_BG)
    median_final = float(np.median(final_equities))
    ax.hist(final_equities, bins=60, color=CHART_GREEN, alpha=0.82, edgecolor="#182032", linewidth=0.5)
    ax.axvline(median_final, color=CHART_AMBER, linestyle="--", linewidth=1.2, alpha=0.9)
    ax.set_title(f"Monte Carlo Final Equity ({bootstrap_mode}-bootstrap, n={n_sims})", fontsize=16, fontweight="bold")
    ax.set_xlabel("Final equity ($)")
    ax.set_ylabel("Count")
    _style_dark_axis(ax)
    _annotate_vertical_line(ax, median_final, f"median ${median_final:,.0f}", CHART_AMBER)
    plt.tight_layout()
    plt.savefig(final_equity_png, dpi=160, facecolor=fig.get_facecolor())
    plt.close()

    fig, ax = plt.subplots(figsize=(10, 4.8))
    fig.patch.set_facecolor(CHART_BG)
    median_dd = float(np.median(max_dds))
    ax.hist(max_dds, bins=60, color=CHART_ORANGE, alpha=0.84, edgecolor="#182032", linewidth=0.5)
    ax.axvline(median_dd, color=CHART_CYAN, linestyle="--", linewidth=1.2, alpha=0.9)
    ax.set_title(f"Monte Carlo Max Drawdown (%) ({bootstrap_mode}-bootstrap, n={n_sims})", fontsize=16, fontweight="bold")
    ax.set_xlabel("Max drawdown (%)")
    ax.set_ylabel("Count")
    _style_dark_axis(ax)
    _annotate_vertical_line(ax, median_dd, f"median {median_dd:.1f}%", CHART_CYAN)
    plt.tight_layout()
    plt.savefig(max_drawdown_png, dpi=160, facecolor=fig.get_facecolor())
    plt.close()

    return MonteCarloSummary(
        n_sims=n_sims,
        bootstrap_mode=bootstrap_mode,
        final_equity_percentiles=_percentiles(final_equities),
        max_drawdown_percentiles=_percentiles(max_dds),
        cagr_like_percentiles=_percentiles(cagrs),
        paths_csv=paths_csv,
        paths_png=paths_png,
        final_equity_png=final_equity_png,
        max_drawdown_png=max_drawdown_png,
    )


def _infer_regime_col(trades: pd.DataFrame, preferred: str | None = None) -> str | None:
    candidates = [
        preferred,
        "entry_day_regime",
        "entry_open_context",
        "setup_tag",
        "signal_type",
        "direction",
    ]
    for col in candidates:
        if not col or col not in trades.columns:
            continue
        series = trades[col].fillna("missing").astype(str)
        series = series.replace({"": "missing", "nan": "missing", "None": "missing"})
        if series.nunique(dropna=False) >= 1:
            return col
    return None


def _regime_transition_model(
    trades: pd.DataFrame,
    *,
    regime_col: str,
    smoothing: float = 1.0,
) -> tuple[pd.Series, pd.DataFrame, dict[str, np.ndarray]]:
    work = trades.sort_values("exit_time" if "exit_time" in trades.columns else "entry_time").copy()
    regimes = work[regime_col].fillna("missing").astype(str).replace({"": "missing", "nan": "missing", "None": "missing"})
    values = sorted(regimes.unique())
    counts = pd.DataFrame(float(smoothing), index=values, columns=values)

    regime_arr = regimes.to_numpy()
    for prior, current in zip(regime_arr[:-1], regime_arr[1:], strict=False):
        counts.loc[str(prior), str(current)] += 1.0

    transition = counts.div(counts.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(1.0 / max(1, len(values)))
    initial_probs = regimes.value_counts(normalize=True).reindex(values).fillna(0.0)
    if initial_probs.sum() <= 0:
        initial_probs[:] = 1.0 / max(1, len(values))
    else:
        initial_probs = initial_probs / initial_probs.sum()

    samples: dict[str, np.ndarray] = {}
    for regime in values:
        pnls = pd.to_numeric(work.loc[regimes.eq(regime), "pnl"], errors="coerce").dropna().to_numpy(dtype=float)
        samples[regime] = pnls
    return initial_probs, transition, samples


def _simulate_trade_reshuffle(
    pnls: np.ndarray,
    *,
    n_sims: int,
    n_obs: int,
    rng: np.random.Generator,
) -> np.ndarray:
    idx = rng.integers(0, len(pnls), size=(n_sims, n_obs))
    return pnls[idx]


def _simulate_parametric_student_t(
    pnls: np.ndarray,
    *,
    n_sims: int,
    n_obs: int,
    rng: np.random.Generator,
    degrees_of_freedom: float,
) -> np.ndarray:
    mu = float(np.mean(pnls))
    sigma = float(np.std(pnls, ddof=1)) if len(pnls) > 1 else 0.0
    if sigma <= 0 or not np.isfinite(sigma):
        return np.full((n_sims, n_obs), mu, dtype=float)

    df = max(2.1, float(degrees_of_freedom))
    # Scale Student-t so its variance roughly matches the observed trade variance.
    scale = sigma / np.sqrt(df / (df - 2.0))
    return rng.standard_t(df=df, size=(n_sims, n_obs)) * scale + mu


def _simulate_regime_switching(
    all_pnls: np.ndarray,
    *,
    initial_probs: pd.Series,
    transition: pd.DataFrame,
    regime_samples: dict[str, np.ndarray],
    n_sims: int,
    n_obs: int,
    rng: np.random.Generator,
) -> np.ndarray:
    regimes = list(initial_probs.index.astype(str))
    initial_p = initial_probs.to_numpy(dtype=float)
    initial_p = initial_p / initial_p.sum() if initial_p.sum() > 0 else np.full(len(regimes), 1.0 / len(regimes))
    transition_arr = transition.reindex(index=regimes, columns=regimes).fillna(0.0).to_numpy(dtype=float).copy()
    row_sums = transition_arr.sum(axis=1)
    for row_idx, row_sum in enumerate(row_sums):
        if row_sum <= 0:
            transition_arr[row_idx, :] = 1.0 / len(regimes)
        else:
            transition_arr[row_idx, :] /= row_sum

    out = np.empty((n_sims, n_obs), dtype=float)
    fallback = all_pnls
    for sim_idx in range(n_sims):
        regime_idx = int(rng.choice(len(regimes), p=initial_p))
        for obs_idx in range(n_obs):
            regime = regimes[regime_idx]
            samples = regime_samples.get(regime, np.asarray([], dtype=float))
            if samples.size == 0:
                samples = fallback
            out[sim_idx, obs_idx] = float(rng.choice(samples))
            regime_idx = int(rng.choice(len(regimes), p=transition_arr[regime_idx]))
    return out


def _simulation_metrics(
    simulated_pnls: np.ndarray,
    *,
    starting_capital: float,
    years: float,
) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    for pnls in simulated_pnls:
        equity = _equity_from_pnl(pnls, starting_capital=starting_capital)
        rows.append({
            "final_equity": float(equity[-1]),
            "total_pnl": float(np.nansum(pnls)),
            "return_pct": float((equity[-1] - starting_capital) / starting_capital * 100.0) if starting_capital else np.nan,
            "max_drawdown_pct": _max_drawdown_pct(equity),
            "max_drawdown_dollars": _max_drawdown_dollars(equity),
            "max_runup_pct": _max_runup_pct(equity, starting_capital=starting_capital),
            "max_runup_dollars": _max_runup_dollars(equity, starting_capital=starting_capital),
            "avg_trade": float(np.nanmean(pnls)),
            "median_trade": float(np.nanmedian(pnls)),
            "profit_factor": _profit_factor(pnls),
            "cagr_like": _cagr_like(starting_capital, equity[-1], years=years),
            "min_equity": float(np.nanmin(equity)),
        })
    return pd.DataFrame(rows)


def _summary_from_metrics(
    *,
    method: str,
    metrics: pd.DataFrame,
    observed_pnls: np.ndarray,
    observed_equity: np.ndarray,
    starting_capital: float,
    n_obs: int,
    regime_col: str | None = None,
    regime_count: int | None = None,
) -> dict[str, float | int | str]:
    avg_trade = metrics["avg_trade"].astype(float).to_numpy()
    avg_p05, avg_p95 = np.percentile(avg_trade, [5, 95])
    avg_95_low, avg_95_high = np.percentile(avg_trade, [2.5, 97.5])
    final_p05, final_p50, final_p95 = np.percentile(metrics["final_equity"], [5, 50, 95])
    dd_p50, dd_p95, dd_p99 = np.percentile(metrics["max_drawdown_pct"], [50, 95, 99])
    runup_p50, runup_p95 = np.percentile(metrics["max_runup_pct"], [50, 95])

    observed_avg = float(np.mean(observed_pnls)) if observed_pnls.size else np.nan
    observed_final = float(observed_equity[-1]) if observed_equity.size else float(starting_capital)
    observed_dd = _max_drawdown_pct(observed_equity)

    return {
        "method": method,
        "n_sims": int(len(metrics)),
        "observations_per_path": int(n_obs),
        "regime_col": regime_col or "",
        "regime_count": int(regime_count or 0),
        "observed_final_equity": observed_final,
        "observed_avg_trade": observed_avg,
        "observed_expected_value_per_trade": observed_avg,
        "observed_max_drawdown_pct": observed_dd,
        "final_equity_p05": float(final_p05),
        "final_equity_p50": float(final_p50),
        "final_equity_p95": float(final_p95),
        "max_drawdown_pct_p50": float(dd_p50),
        "max_drawdown_pct_p95": float(dd_p95),
        "max_drawdown_pct_p99": float(dd_p99),
        "max_runup_pct_p50": float(runup_p50),
        "max_runup_pct_p95": float(runup_p95),
        "avg_trade_p05": float(avg_p05),
        "avg_trade_p50": float(np.percentile(avg_trade, 50)),
        "avg_trade_p95": float(avg_p95),
        "avg_trade_ci90_low": float(avg_p05),
        "avg_trade_ci90_high": float(avg_p95),
        "avg_trade_ci95_low": float(avg_95_low),
        "avg_trade_ci95_high": float(avg_95_high),
        "expected_value_ci90_low": float(avg_p05),
        "expected_value_ci90_high": float(avg_p95),
        "expected_value_ci95_low": float(avg_95_low),
        "expected_value_ci95_high": float(avg_95_high),
        "avg_trade_ci90_spans_zero": bool(avg_p05 <= 0.0 <= avg_p95),
        "avg_trade_ci95_spans_zero": bool(avg_95_low <= 0.0 <= avg_95_high),
        "expected_value_ci90_spans_zero": bool(avg_p05 <= 0.0 <= avg_p95),
        "expected_value_ci95_spans_zero": bool(avg_95_low <= 0.0 <= avg_95_high),
        "pct_paths_final_below_start": float((metrics["final_equity"] < starting_capital).mean() * 100.0),
        "pct_paths_avg_trade_le_zero": float((metrics["avg_trade"] <= 0).mean() * 100.0),
        "pct_paths_dd_over_10pct": float((metrics["max_drawdown_pct"] >= 10.0).mean() * 100.0),
        "pct_paths_dd_over_20pct": float((metrics["max_drawdown_pct"] >= 20.0).mean() * 100.0),
        "pct_paths_dd_over_25pct": float((metrics["max_drawdown_pct"] >= 25.0).mean() * 100.0),
    }


def _first_hit_outcomes(
    simulated_pnls: np.ndarray,
    *,
    starting_capital: float,
    profit_target_pct: float,
    drawdown_limit_pct: float,
) -> tuple[float, float, float]:
    target_equity = starting_capital * (1.0 + max(0.0, float(profit_target_pct)) / 100.0)
    drawdown_equity = starting_capital * (1.0 - max(0.0, float(drawdown_limit_pct)) / 100.0)
    target_first = 0
    drawdown_first = 0
    neither = 0

    for pnls in simulated_pnls:
        equity = _equity_from_pnl(pnls, starting_capital=starting_capital)
        target_hits = np.flatnonzero(equity >= target_equity)
        drawdown_hits = np.flatnonzero(equity <= drawdown_equity)
        target_idx = int(target_hits[0]) if target_hits.size else None
        drawdown_idx = int(drawdown_hits[0]) if drawdown_hits.size else None

        if target_idx is None and drawdown_idx is None:
            neither += 1
        elif target_idx is None:
            drawdown_first += 1
        elif drawdown_idx is None:
            target_first += 1
        elif target_idx < drawdown_idx:
            target_first += 1
        else:
            drawdown_first += 1

    n = max(1, len(simulated_pnls))
    return (
        float(target_first / n * 100.0),
        float(drawdown_first / n * 100.0),
        float(neither / n * 100.0),
    )


def _path_risk_rows(
    *,
    method: str,
    simulated_pnls: np.ndarray,
    starting_capital: float,
    horizon_trades: int,
    drawdown_barriers_pct: tuple[float, ...],
    profit_target_pct: float,
    drawdown_limit_pct: float,
) -> dict[str, float | int | str]:
    metrics = _simulation_metrics(simulated_pnls, starting_capital=starting_capital, years=1.0)
    final = metrics["final_equity"].astype(float)
    ret = metrics["return_pct"].astype(float)
    dd = metrics["max_drawdown_pct"].astype(float)
    target_first, drawdown_first, neither = _first_hit_outcomes(
        simulated_pnls,
        starting_capital=starting_capital,
        profit_target_pct=profit_target_pct,
        drawdown_limit_pct=drawdown_limit_pct,
    )

    row: dict[str, float | int | str] = {
        "method": method,
        "horizon_trades": int(horizon_trades),
        "n_sims": int(len(simulated_pnls)),
        "prob_final_below_start_pct": float(final.lt(starting_capital).mean() * 100.0),
        "prob_return_negative_pct": float(ret.lt(0.0).mean() * 100.0),
        "final_equity_p05": float(np.percentile(final, 5)),
        "final_equity_p50": float(np.percentile(final, 50)),
        "final_equity_p95": float(np.percentile(final, 95)),
        "return_pct_p05": float(np.percentile(ret, 5)),
        "return_pct_p50": float(np.percentile(ret, 50)),
        "return_pct_p95": float(np.percentile(ret, 95)),
        "max_drawdown_pct_p50": float(np.percentile(dd, 50)),
        "max_drawdown_pct_p95": float(np.percentile(dd, 95)),
        "profit_target_pct": float(profit_target_pct),
        "drawdown_limit_pct": float(drawdown_limit_pct),
        "prob_profit_target_before_drawdown_pct": target_first,
        "prob_drawdown_before_profit_target_pct": drawdown_first,
        "prob_neither_target_nor_drawdown_pct": neither,
    }
    for barrier in drawdown_barriers_pct:
        barrier = float(barrier)
        key = str(barrier).replace(".", "_")
        row[f"prob_max_drawdown_ge_{key}pct"] = float(dd.ge(barrier).mean() * 100.0)
    return row


def _parse_float_tuple(values) -> tuple[float, ...]:
    if values is None:
        return tuple()
    if isinstance(values, str):
        values = [item.strip() for item in values.split(",") if item.strip()]
    return tuple(float(x) for x in values)


def _parse_int_tuple(values) -> tuple[int, ...]:
    if values is None:
        return tuple()
    if isinstance(values, str):
        values = [item.strip() for item in values.split(",") if item.strip()]
    return tuple(int(x) for x in values)


def _store_advanced_paths(
    simulated_pnls: np.ndarray,
    *,
    method: str,
    starting_capital: float,
    out_dir: Path,
    artifact_name: str,
    max_paths: int = 200,
) -> tuple[Path, Path]:
    store_paths = min(int(max_paths), len(simulated_pnls))
    paths = np.empty((store_paths, simulated_pnls.shape[1] + 1), dtype=float)
    for idx in range(store_paths):
        paths[idx] = _equity_from_pnl(simulated_pnls[idx], starting_capital=starting_capital)

    paths_csv = out_dir / f"{artifact_name}_advanced_mc_paths_{method}.csv"
    paths_png = out_dir / f"{artifact_name}_advanced_mc_paths_{method}.png"
    pd.DataFrame(paths).to_csv(paths_csv, index=False)

    fig, ax = plt.subplots(figsize=(13.5, 7.0))
    fig.patch.set_facecolor(CHART_BG)
    _render_monte_carlo_fan(
        ax,
        paths - float(starting_capital),
        title=f"Advanced Monte Carlo - {method.replace('_', ' ')}\nEquity-curve fan",
        x_label="trade #",
        y_label="cumulative P&L ($)",
    )
    plt.tight_layout()
    plt.savefig(paths_png, dpi=160, facecolor=fig.get_facecolor())
    plt.close()
    return paths_csv, paths_png


def run_advanced_monte_carlo(
    results: dict[str, Any],
    starting_capital: float,
    artifact_name: str = "mc",
    n_sims: int = 2000,
    seed: int = 7,
    out_dir: Path | str = "results/simulations",
    regime_col: str | None = None,
    transition_smoothing: float = 1.0,
    student_t_df: float = 5.0,
    path_horizons: tuple[int, ...] | list[int] = (40, 100, 250, 500, 1000),
    drawdown_barriers_pct: tuple[float, ...] | list[float] = (5.0, 10.0, 15.0, 20.0, 25.0),
    profit_target_pct: float = 8.0,
    drawdown_limit_pct: float = 5.0,
) -> AdvancedMonteCarloSummary:
    """
    Run three strategy-validation Monte Carlo variants.

    1. trade_reshuffle: samples observed trades with replacement.
    2. regime_switch: samples from regime-specific trade distributions using a
       Markov transition matrix inferred from the observed trade sequence.
    3. parametric_student_t: samples a continuous heavy-tailed distribution
       calibrated to observed trade mean/variance.
    """
    trades = results.get("trades")
    if not isinstance(trades, pd.DataFrame) or len(trades) == 0:
        raise ValueError("results['trades'] must be a non-empty DataFrame to run advanced Monte Carlo.")
    if "pnl" not in trades.columns:
        raise ValueError("Trade DataFrame must contain a 'pnl' column.")

    work = trades.copy()
    if "exit_time" in work.columns:
        work = work.sort_values("exit_time")
    elif "entry_time" in work.columns:
        work = work.sort_values("entry_time")
    pnls = pd.to_numeric(work["pnl"], errors="coerce").dropna().to_numpy(dtype=float)
    if pnls.size == 0:
        raise ValueError("No valid trade PnL values available for advanced Monte Carlo.")

    n_sims = max(1, int(n_sims))
    n_obs = int(pnls.size)
    path_horizons = tuple(sorted({max(1, int(x)) for x in _parse_int_tuple(path_horizons)}))
    drawdown_barriers_pct = tuple(sorted({max(0.0, float(x)) for x in _parse_float_tuple(drawdown_barriers_pct)}))
    years = _infer_years_covered(work)
    observed_equity = _equity_from_pnl(pnls, starting_capital=starting_capital)
    rng = np.random.default_rng(int(seed))
    out_dir = Path(out_dir)
    _ensure_dir(out_dir)

    inferred_regime_col = _infer_regime_col(work, regime_col)
    transition_matrix_csv: Path | None = None
    regime_count = 0
    regime_sims: np.ndarray | None = None
    if inferred_regime_col is not None:
        initial_probs, transition, regime_samples = _regime_transition_model(
            work,
            regime_col=inferred_regime_col,
            smoothing=float(transition_smoothing),
        )
        regime_count = len(initial_probs)
        transition_matrix_csv = out_dir / f"{artifact_name}_advanced_mc_regime_transition_matrix.csv"
        transition.to_csv(transition_matrix_csv)
        regime_sims = _simulate_regime_switching(
            pnls,
            initial_probs=initial_probs,
            transition=transition,
            regime_samples=regime_samples,
            n_sims=n_sims,
            n_obs=n_obs,
            rng=rng,
        )

    simulated_by_method: dict[str, np.ndarray] = {
        "trade_reshuffle": _simulate_trade_reshuffle(pnls, n_sims=n_sims, n_obs=n_obs, rng=rng),
        "parametric_student_t": _simulate_parametric_student_t(
            pnls,
            n_sims=n_sims,
            n_obs=n_obs,
            rng=rng,
            degrees_of_freedom=student_t_df,
        ),
    }
    if regime_sims is not None:
        simulated_by_method["regime_switch"] = regime_sims

    summary_rows: list[dict[str, float | int | str]] = []
    distributions: list[pd.DataFrame] = []
    path_risk_rows: list[dict[str, float | int | str]] = []
    path_csvs: dict[str, Path] = {}
    path_pngs: dict[str, Path] = {}

    for method, simulated_pnls in simulated_by_method.items():
        metrics = _simulation_metrics(simulated_pnls, starting_capital=starting_capital, years=years)
        metrics.insert(0, "method", method)
        metrics.insert(1, "sim_id", np.arange(len(metrics), dtype=int))
        distributions.append(metrics)
        summary_rows.append(
            _summary_from_metrics(
                method=method,
                metrics=metrics,
                observed_pnls=pnls,
                observed_equity=observed_equity,
                starting_capital=starting_capital,
                n_obs=n_obs,
                regime_col=inferred_regime_col if method == "regime_switch" else None,
                regime_count=regime_count if method == "regime_switch" else None,
            )
        )
        paths_csv, paths_png = _store_advanced_paths(
            simulated_pnls,
            method=method,
            starting_capital=starting_capital,
            out_dir=out_dir,
            artifact_name=artifact_name,
        )
        path_csvs[method] = paths_csv
        path_pngs[method] = paths_png

        for horizon in path_horizons:
            if method == "trade_reshuffle":
                horizon_pnls = _simulate_trade_reshuffle(pnls, n_sims=n_sims, n_obs=horizon, rng=rng)
            elif method == "parametric_student_t":
                horizon_pnls = _simulate_parametric_student_t(
                    pnls,
                    n_sims=n_sims,
                    n_obs=horizon,
                    rng=rng,
                    degrees_of_freedom=student_t_df,
                )
            elif method == "regime_switch" and inferred_regime_col is not None:
                horizon_pnls = _simulate_regime_switching(
                    pnls,
                    initial_probs=initial_probs,
                    transition=transition,
                    regime_samples=regime_samples,
                    n_sims=n_sims,
                    n_obs=horizon,
                    rng=rng,
                )
            else:
                continue
            path_risk_rows.append(
                _path_risk_rows(
                    method=method,
                    simulated_pnls=horizon_pnls,
                    starting_capital=starting_capital,
                    horizon_trades=horizon,
                    drawdown_barriers_pct=drawdown_barriers_pct,
                    profit_target_pct=profit_target_pct,
                    drawdown_limit_pct=drawdown_limit_pct,
                )
            )

    summary = pd.DataFrame(summary_rows)
    distributions_df = pd.concat(distributions, ignore_index=True, sort=False)
    path_risk_df = pd.DataFrame(path_risk_rows)
    summary_csv = out_dir / f"{artifact_name}_advanced_mc_summary.csv"
    distributions_csv = out_dir / f"{artifact_name}_advanced_mc_distributions.csv"
    path_risk_csv = out_dir / f"{artifact_name}_advanced_mc_path_risk.csv"
    summary.to_csv(summary_csv, index=False)
    distributions_df.to_csv(distributions_csv, index=False)
    path_risk_df.to_csv(path_risk_csv, index=False)

    return AdvancedMonteCarloSummary(
        n_sims=n_sims,
        methods=list(simulated_by_method),
        summary_csv=summary_csv,
        distributions_csv=distributions_csv,
        path_risk_csv=path_risk_csv,
        transition_matrix_csv=transition_matrix_csv,
        path_csvs=path_csvs,
        path_pngs=path_pngs,
    )


def _stress_metrics(scenario: str, pnls: np.ndarray, starting_capital: float) -> dict[str, float | int | str]:
    equity = _equity_from_pnl(pnls, starting_capital=starting_capital)
    wins = pnls > 0
    return {
        "scenario": scenario,
        "trades": int(pnls.size),
        "total_pnl": float(pnls.sum()),
        "final_equity": float(equity[-1]) if equity.size else float(starting_capital),
        "return_pct": float((equity[-1] - starting_capital) / starting_capital * 100.0) if starting_capital else np.nan,
        "win_rate_pct": float(wins.mean() * 100.0) if pnls.size else np.nan,
        "avg_trade": float(pnls.mean()) if pnls.size else np.nan,
        "profit_factor": _profit_factor(pnls),
        "max_drawdown_pct": _max_drawdown_pct(equity),
        "max_drawdown_dollars": _max_drawdown_dollars(equity),
    }


def run_trade_stress_tests(
    results: dict[str, Any],
    starting_capital: float,
    artifact_name: str = "stress",
    out_dir: Path | str = "results/simulations",
) -> StressTestSummary:
    """
    Deterministic stress scenarios for execution fragility.

    These are intentionally simple: if a candidate only works with perfect
    costs, full winner capture, and unexpanded losses, it is not ready for
    deeper research.
    """
    trades = results.get("trades")
    if not isinstance(trades, pd.DataFrame) or len(trades) == 0:
        raise ValueError("results['trades'] must be a non-empty DataFrame to run stress tests.")

    base = trades["pnl"].astype(float).to_numpy()
    scenarios: dict[str, np.ndarray] = {
        "base": base,
        "extra_cost_25_per_trade": base - 25.0,
        "extra_cost_50_per_trade": base - 50.0,
        "extra_cost_100_per_trade": base - 100.0,
        "winners_haircut_10pct": np.where(base > 0, base * 0.90, base),
        "winners_haircut_20pct": np.where(base > 0, base * 0.80, base),
        "losses_expanded_10pct": np.where(base <= 0, base * 1.10, base),
        "losses_expanded_25pct": np.where(base <= 0, base * 1.25, base),
        "combined_mild": np.where(base > 0, base * 0.90, base * 1.10) - 25.0,
        "combined_harsh": np.where(base > 0, base * 0.80, base * 1.25) - 50.0,
    }

    out_dir = Path(out_dir)
    _ensure_dir(out_dir)
    summary_csv = out_dir / f"{artifact_name}_trade_stress_tests.csv"
    pd.DataFrame(
        [_stress_metrics(name, pnls, starting_capital=starting_capital) for name, pnls in scenarios.items()]
    ).to_csv(summary_csv, index=False)

    return StressTestSummary(
        scenarios=len(scenarios),
        summary_csv=summary_csv,
    )


def _resolve_max_drawdown_pct(params: dict[str, Any]) -> float | None:
    if not params.get("enable_circuit_breaker", False):
        return None
    value = params.get("max_drawdown_pct")
    return None if value is None else float(value)


def _result_stress_row(
    scenario: str,
    delay_bars: int,
    results: dict[str, Any],
    starting_capital: float,
) -> dict[str, float | int | str]:
    if "error" in results:
        return {
            "scenario": scenario,
            "entry_delay_bars": int(delay_bars),
            "entry_delay_minutes": int(delay_bars) * 5,
            "error": str(results["error"]),
            "trades": 0,
            "total_pnl": np.nan,
            "final_equity": starting_capital,
            "return_pct": np.nan,
            "win_rate_pct": np.nan,
            "avg_trade": np.nan,
            "profit_factor": np.nan,
            "max_drawdown_pct": np.nan,
            "max_drawdown_dollars": np.nan,
        }

    trades = results.get("trades")
    max_dd_dollars = np.nan
    if isinstance(trades, pd.DataFrame) and "equity" in trades.columns and len(trades):
        equity = np.concatenate([[float(starting_capital)], trades["equity"].astype(float).to_numpy()])
        max_dd_dollars = _max_drawdown_dollars(equity)

    return {
        "scenario": scenario,
        "entry_delay_bars": int(delay_bars),
        "entry_delay_minutes": int(delay_bars) * 5,
        "error": "",
        "trades": int(results.get("total_trades", 0)),
        "total_pnl": float(results.get("total_pnl", np.nan)),
        "final_equity": float(results.get("final_equity", np.nan)),
        "return_pct": float(results.get("return_pct", np.nan)),
        "win_rate_pct": float(results.get("win_rate", np.nan)),
        "avg_trade": float(results.get("expectancy", np.nan)),
        "profit_factor": float(results.get("profit_factor", np.nan)),
        "max_drawdown_pct": float(results.get("max_drawdown", np.nan)),
        "max_drawdown_dollars": float(max_dd_dollars),
    }


def _plot_execution_delay_stress(summary: pd.DataFrame, out_path: Path) -> None:
    df = summary[summary["error"].fillna("").eq("")].copy()
    fig, ax = plt.subplots(figsize=(10.8, 5.4))
    fig.patch.set_facecolor(CHART_BG)
    if not df.empty:
        df = df.sort_values("entry_delay_bars")
        x = df["entry_delay_minutes"].astype(float)
        pnl = df["total_pnl"].astype(float)
        ax.plot(x, pnl, marker="o", linewidth=2.0, color=CHART_GREEN, label="Total P&L")
        for x_value, y_value in zip(x, pnl, strict=False):
            ax.text(x_value, y_value, f"${y_value:,.0f}", color=CHART_TEXT, fontsize=8, ha="center", va="bottom")
        ax.axhline(0, color=CHART_MUTED, linewidth=1.0, alpha=0.45)
        ax2 = ax.twinx()
        ax2.plot(x, df["profit_factor"].astype(float), marker="s", linewidth=1.7, color=CHART_AMBER, label="Profit factor")
        ax2.set_ylabel("Profit factor")
        ax2.tick_params(colors=CHART_MUTED)
        ax2.yaxis.label.set_color(CHART_TEXT)
        for spine in ax2.spines.values():
            spine.set_edgecolor(CHART_GRID)
    ax.set_title("Execution Delay Stress", fontsize=16, fontweight="bold")
    ax.set_xlabel("Extra entry delay (minutes)")
    ax.set_ylabel("Total P&L ($)")
    _style_dark_axis(ax)
    plt.tight_layout()
    plt.savefig(out_path, dpi=160, facecolor=fig.get_facecolor())
    plt.close()


def run_execution_delay_stress_tests(
    *,
    pre_df: pd.DataFrame,
    raw_data: pd.DataFrame,
    futures_specs: dict[str, Any],
    base_params: dict[str, Any],
    starting_capital: float,
    delay_bars: list[int] | tuple[int, ...] = (0, 1, 2, 3),
    artifact_name: str = "stress",
    out_dir: Path | str = "results/simulations",
) -> ExecutionDelayStressSummary:
    """
    Rerun the strategy while delaying entries by extra 5-minute signal bars.

    This tests whether an edge depends on perfect signal-to-execution timing.
    """
    from backtest.engine import BacktestEngine
    from backtest.portfolio import Portfolio

    delays = sorted({max(0, int(x)) for x in delay_bars})
    rows: list[dict[str, float | int | str]] = []

    for delay in delays:
        params = {**base_params, "entry_delay_bars": delay}
        portfolio = Portfolio(
            starting_capital,
            futures_specs,
            max_drawdown_pct=_resolve_max_drawdown_pct(params),
        )
        engine = BacktestEngine(raw_data, portfolio, futures_specs, params)
        results = engine.run_on_preprocessed(pre_df)
        label = f"delay_{delay}_bars"
        rows.append(_result_stress_row(label, delay, results, starting_capital=starting_capital))

    out_dir = Path(out_dir)
    _ensure_dir(out_dir)
    summary = pd.DataFrame(rows)
    summary_csv = out_dir / f"{artifact_name}_execution_delay_stress.csv"
    chart_png = out_dir / f"{artifact_name}_execution_delay_stress.png"
    summary.to_csv(summary_csv, index=False)
    _plot_execution_delay_stress(summary, chart_png)

    return ExecutionDelayStressSummary(
        scenarios=len(rows),
        summary_csv=summary_csv,
        chart_png=chart_png,
    )


# ---------------------------------------------------------------------------
# Regime-conditional cost model
#
# NQ slippage and commission are not uniform.  Slippage widens in high-vol
# regimes (trend days, news events) and narrows in low-vol regimes (range
# days).  Running the same backtest with regime-conditional costs shows
# whether the edge survives realistic execution frictions.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegimeCostStressSummary:
    scenarios: int
    summary_csv: Path
    chart_png: Path
    detail_csv: Path


def _infer_bar_regime_batch(
    pre_df: pd.DataFrame,
    params: dict[str, Any],
) -> np.ndarray:
    """
    Return a per-bar regime label: 0 = range/neutral, 1 = trend, -1 = unknown.
    Aligned to *pre_df* index.
    """
    out = np.full(len(pre_df), -1, dtype=np.int8)
    if "day_regime" in pre_df.columns:
        regime = pre_df["day_regime"].astype(str)
        out[regime.str.startswith("trend")] = 1
        out[regime == "range"] = 0
        out[regime == "neutral"] = 0
    elif "regime_trend_up_confirmed" in pre_df.columns:
        up = pre_df["regime_trend_up_confirmed"].fillna(False).astype(bool).to_numpy()
        down = pre_df["regime_trend_down_confirmed"].fillna(False).astype(bool).to_numpy()
        out[(up | down)] = 1
        out[~(up | down)] = 0
    return out


def _regime_conditional_slippage(
    regime: int,
    base_slippage_points: float,
    regime_slippage_multipliers: dict[str, float],
) -> float:
    """Return slippage points for a given regime."""
    key = "trend" if regime == 1 else "range" if regime == 0 else "unknown"
    mult = regime_slippage_multipliers.get(key, 1.0)
    return base_slippage_points * mult


def _regime_conditional_commission(
    regime: int,
    base_commission: float,
    regime_commission_multipliers: dict[str, float],
) -> float:
    """Return commission for a given regime."""
    key = "trend" if regime == 1 else "range" if regime == 0 else "unknown"
    mult = regime_commission_multipliers.get(key, 1.0)
    return base_commission * mult


def run_regime_conditional_cost_stress(
    *,
    pre_df: pd.DataFrame,
    raw_data: pd.DataFrame,
    futures_specs: dict[str, Any],
    base_params: dict[str, Any],
    starting_capital: float,
    regime_slippage_multipliers: dict[str, float] | None = None,
    regime_commission_multipliers: dict[str, float] | None = None,
    artifact_name: str = "regime_cost_stress",
    out_dir: Path | str = "results/simulations",
) -> RegimeCostStressSummary:
    """
    Run the backtest with regime-conditional execution costs.

    Parameters
    ----------
    regime_slippage_multipliers : dict or None
        e.g. {'range': 0.5, 'trend': 2.0, 'unknown': 1.0}
        Default: range=0.5 (tighter), trend=2.0 (wider), unknown=1.0.
    regime_commission_multipliers : dict or None
        e.g. {'range': 1.0, 'trend': 1.5, 'unknown': 1.0}
        Default: all 1.0 (no regime effect on commission).

    Returns
    -------
    RegimeCostStressSummary with per-bar cost detail + scenario comparison.
    """
    if regime_slippage_multipliers is None:
        regime_slippage_multipliers = {"range": 0.5, "trend": 2.0, "unknown": 1.0}
    if regime_commission_multipliers is None:
        regime_commission_multipliers = {"range": 1.0, "trend": 1.0, "unknown": 1.0}

    from backtest.engine import BacktestEngine
    from backtest.portfolio import Portfolio

    out_dir = Path(out_dir)
    _ensure_dir(out_dir)

    base_slippage = float(futures_specs.get("slippage_points", 1.50))
    base_commission = float(futures_specs.get("commission_per_round_trip", 3.50))

    # Pre-compute per-bar regime labels from the preprocessed frame
    bar_regime = _infer_bar_regime_batch(pre_df, base_params)

    scenarios: list[dict[str, Any]] = []

    # Scenario 1: baseline (uniform costs)
    portfolio = Portfolio(starting_capital, futures_specs, max_drawdown_pct=None)
    engine = BacktestEngine(raw_data, portfolio, futures_specs, base_params)
    base_results = engine.run_on_preprocessed(pre_df)
    if "error" not in base_results:
        scenarios.append({
            "scenario": "baseline_uniform",
            "description": "Uniform slippage + commission (default)",
            "slippage_points": base_slippage,
            "commission": base_commission,
            **{k: base_results.get(k, 0.0) for k in (
                "total_trades", "total_pnl", "profit_factor", "win_rate",
                "sharpe_ratio", "max_drawdown", "final_equity",
            )},
        })

    # Scenario 2: regime-conditional costs
    # We modify the futures_specs per trade based on the regime at entry time.
    # Since the engine uses portfolio.exit_position with fixed costs from
    # futures_specs, we need a modified spec.  We'll do this by running with
    # an adjusted base spec that uses a "blended" cost, then re-run per-regime.
    # If the engine only uses the spec at exit time, we can hack it by passing
    # a dynamically-modified spec dict.
    #
    # A cleaner approach: slice pre_df by regime, run each slice with its
    # regime-adjusted costs, then concatenate trades.
    regime_labels = {"range": 0, "trend": 1}
    stitched_trades: list[pd.DataFrame] = []
    detail_rows: list[dict[str, Any]] = []

    for label, regime_val in regime_labels.items():
        reg_mask = bar_regime == regime_val
        if not reg_mask.any():
            continue

        # Find entry times that fall in this regime
        reg_df = pre_df.loc[reg_mask].reset_index(drop=True)
        if len(reg_df) < 10:
            continue

        # Build regime-adjusted specs
        reg_slippage = _regime_conditional_slippage(regime_val, base_slippage, regime_slippage_multipliers)
        reg_commission = _regime_conditional_commission(regime_val, base_commission, regime_commission_multipliers)
        reg_specs = dict(futures_specs)
        reg_specs["slippage_points"] = reg_slippage
        reg_specs["commission_per_round_trip"] = reg_commission

        portfolio = Portfolio(starting_capital, reg_specs, max_drawdown_pct=None)
        engine = BacktestEngine(raw_data[:1], portfolio, reg_specs, base_params)
        # Replace data entirely — we need a contiguous subset that includes
        # this regime's bars plus enough surround for signal/setup computation.
        reg_start_idx = int(np.flatnonzero(reg_mask)[0])
        reg_end_idx = int(np.flatnonzero(reg_mask)[-1]) + 1
        buffer = max(20, int(len(pre_df) * 0.02))
        start_idx = max(0, reg_start_idx - buffer)
        end_idx = min(len(raw_data), reg_end_idx + buffer)

        segment_raw = raw_data.iloc[start_idx:end_idx].reset_index(drop=True)
        segment_pre = pre_df.iloc[start_idx:end_idx].reset_index(drop=True)

        engine = BacktestEngine(segment_raw, portfolio, reg_specs, base_params)
        results = engine.run_on_preprocessed(segment_pre)

        if "error" not in results and results.get("total_trades", 0) > 5:
            trades = results["trades"].copy()
            trades["cost_scenario"] = label
            stitched_trades.append(trades)
            scenarios.append({
                "scenario": f"regime_{label}",
                "description": f"Regime-conditional costs ({label}: slippage={reg_slippage:.2f}, commission=${reg_commission:.2f})",
                "slippage_points": reg_slippage,
                "commission": reg_commission,
                **{k: results.get(k, 0.0) for k in (
                    "total_trades", "total_pnl", "profit_factor", "win_rate",
                    "sharpe_ratio", "max_drawdown", "final_equity",
                )},
            })
            for _, trade in trades.iterrows():
                detail_rows.append({
                    "cost_scenario": label,
                    "entry_time": trade.get("entry_time", ""),
                    "exit_time": trade.get("exit_time", ""),
                    "direction": trade.get("direction", ""),
                    "signal_type": trade.get("signal_type", ""),
                    "pnl": trade.get("pnl", 0.0),
                    "regime_slippage_points": reg_slippage,
                    "regime_commission": reg_commission,
                })

    summary = pd.DataFrame(scenarios)
    detail = pd.DataFrame(detail_rows)

    summary_csv = out_dir / f"{artifact_name}_summary.csv"
    chart_png = out_dir / f"{artifact_name}_chart.png"
    detail_csv = out_dir / f"{artifact_name}_detail.csv"

    summary.to_csv(summary_csv, index=False)
    detail.to_csv(detail_csv, index=False)

    # Plot comparison
    if not summary.empty:
        fig, ax = plt.subplots(figsize=(10, 5.2))
        fig.patch.set_facecolor(CHART_BG)
        _style_dark_axis(ax)

        labels = summary["scenario"].tolist()
        pnl_values = summary["total_pnl"].astype(float).tolist()
        pf_values = summary["profit_factor"].astype(float).tolist()

        x = np.arange(len(labels))
        width = 0.35
        bars1 = ax.bar(x - width / 2, pnl_values, width, color=CHART_GREEN, alpha=0.82, label="Total P&L ($)")
        for bar, value in zip(bars1, pnl_values, strict=False):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value,
                f"${value:,.0f}",
                ha="center",
                va="bottom" if value >= 0 else "top",
                color=CHART_TEXT,
                fontsize=8,
            )
        ax.set_ylabel("Total P&L ($)", color=CHART_TEXT)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=30, ha="right", color=CHART_TEXT)

        ax2 = ax.twinx()
        bars2 = ax2.bar(x + width / 2, pf_values, width, color=CHART_AMBER, alpha=0.82, label="Profit Factor")
        for bar, value in zip(bars2, pf_values, strict=False):
            ax2.text(
                bar.get_x() + bar.get_width() / 2,
                value,
                f"{value:.2f}",
                ha="center",
                va="bottom" if value >= 0 else "top",
                color=CHART_TEXT,
                fontsize=8,
            )
        ax2.set_ylabel("Profit Factor", color=CHART_TEXT)
        ax2.tick_params(colors=CHART_MUTED)
        for spine in ax2.spines.values():
            spine.set_edgecolor(CHART_GRID)

        lines = [bars1, bars2]
        labels_list = ["Total P&L", "Profit Factor"]
        ax.legend(lines, labels_list, loc="upper right", fontsize=10)
        ax.set_title("Regime-Conditional Cost Stress", fontsize=16, fontweight="bold", color=CHART_TEXT)
        plt.tight_layout()
        plt.savefig(chart_png, dpi=160, facecolor=fig.get_facecolor())
        plt.close()

    return RegimeCostStressSummary(
        scenarios=len(scenarios),
        summary_csv=summary_csv,
        chart_png=chart_png,
        detail_csv=detail_csv,
    )
