from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_mpl_config_dir = Path("results/.mplconfig").resolve()
_mpl_config_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_mpl_config_dir))

import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.animation as animation
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import Normalize, TwoSlopeNorm

try:
    from scipy.ndimage import gaussian_filter  # type: ignore
except Exception:  # pragma: no cover
    gaussian_filter = None


BG = "#020404"
PANEL = "#050708"
GRID = "#2d343a"
TEXT = "#d8dee9"
MUTED = "#7f8b94"
GREEN = "#2bd67b"
RED = "#ff564f"
BLUE = "#1c93ff"
CYAN = "#24d8ff"
YELLOW = "#f5aa24"
ORANGE = "#ff6b35"


@dataclass(frozen=True)
class ResearchAnimationPaths:
    animation_dir: Path
    signal_surface_gif: Path
    walkforward_validation_gif: Path
    index_md: Path


@dataclass(frozen=True)
class SurfaceData:
    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    x_labels: list[str]
    y_labels: list[str]
    z_label: str


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _load_trades(run_dir: Path) -> pd.DataFrame:
    trades = _read_csv(run_dir / "trades" / "trade_log.csv")
    if trades.empty or "pnl" not in trades.columns:
        return pd.DataFrame()

    trades = trades.copy()
    time_col = "exit_time" if "exit_time" in trades.columns else "entry_time"
    trades[time_col] = pd.to_datetime(trades[time_col], errors="coerce")
    if "entry_time" in trades.columns:
        trades["entry_time"] = pd.to_datetime(trades["entry_time"], errors="coerce")
    if "exit_time" in trades.columns:
        trades["exit_time"] = pd.to_datetime(trades["exit_time"], errors="coerce")

    trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce")
    trades = trades.dropna(subset=[time_col, "pnl"]).sort_values(time_col).reset_index(drop=True)
    if trades.empty:
        return pd.DataFrame()

    if "entry_hour" not in trades.columns:
        source = trades["entry_time"] if "entry_time" in trades.columns else trades[time_col]
        trades["entry_hour"] = source.dt.hour
    trades["entry_hour"] = pd.to_numeric(trades["entry_hour"], errors="coerce").fillna(0).astype(int)

    if "equity" not in trades.columns:
        trades["equity"] = 100_000.0 + trades["pnl"].cumsum()
    else:
        trades["equity"] = pd.to_numeric(trades["equity"], errors="coerce")
        if trades["equity"].isna().all():
            trades["equity"] = 100_000.0 + trades["pnl"].cumsum()
    trades["cumulative_pnl"] = trades["pnl"].cumsum()
    trades["_time"] = trades[time_col]
    return trades


def _load_folds(run_dir: Path) -> pd.DataFrame:
    folds = _read_csv(run_dir / "research" / "walkforward" / "walkforward_folds.csv")
    if folds.empty:
        return pd.DataFrame()
    folds = folds.copy()
    for col in ["fold_idx", "test_profit_factor", "train_metric", "test_total_pnl", "test_total_trades"]:
        if col in folds.columns:
            folds[col] = pd.to_numeric(folds[col], errors="coerce")
    if "fold_idx" not in folds.columns:
        folds["fold_idx"] = np.arange(len(folds))
    return folds.sort_values("fold_idx").reset_index(drop=True)


def _short_label(value: Any, max_len: int = 14) -> str:
    text = str(value)
    return text if len(text) <= max_len else f"{text[: max_len - 1]}..."


def _tick_positions(count: int, max_ticks: int = 5) -> np.ndarray:
    if count <= 1:
        return np.array([0], dtype=int)
    n = min(max_ticks, count)
    return np.unique(np.linspace(0, count - 1, n).round().astype(int))


def _smooth(values: np.ndarray, sigma: float = 0.9) -> np.ndarray:
    if gaussian_filter is None:
        return values
    return gaussian_filter(values, sigma=sigma, mode="nearest")


def _fill_matrix(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return values
    if np.isfinite(values).all():
        return values

    filled = values.copy()
    global_median = np.nanmedian(filled)
    if not np.isfinite(global_median):
        global_median = 0.0

    row_medians = np.nanmedian(filled, axis=1)
    col_medians = np.nanmedian(filled, axis=0)
    for r in range(filled.shape[0]):
        for c in range(filled.shape[1]):
            if np.isfinite(filled[r, c]):
                continue
            candidates = [row_medians[r], col_medians[c], global_median]
            filled[r, c] = next((float(v) for v in candidates if np.isfinite(v)), 0.0)
    return filled


def _profit_factor(values: pd.Series) -> float:
    pnl = pd.to_numeric(values, errors="coerce").dropna()
    wins = float(pnl[pnl > 0].sum())
    losses = abs(float(pnl[pnl <= 0].sum()))
    if losses == 0:
        return 2.5 if wins > 0 else np.nan
    return min(wins / losses, 3.0)


def _date_bin_labels(times: pd.Series, bins: np.ndarray) -> list[str]:
    labels: list[str] = []
    for idx in range(len(bins) - 1):
        lo = int(bins[idx])
        hi = max(int(bins[idx + 1]) - 1, lo)
        midpoint = times.iloc[min((lo + hi) // 2, len(times) - 1)]
        labels.append(pd.Timestamp(midpoint).strftime("%Y-%m"))
    return labels


def _build_trade_surface(
    trades: pd.DataFrame,
    *,
    metric: str = "avg_pnl",
    x_bins: int = 18,
    y_bins: int = 16,
) -> SurfaceData:
    if trades.empty:
        return SurfaceData(np.zeros((1, 1)), np.zeros((1, 1)), np.zeros((1, 1)), [""], [""], metric)

    work = trades.sort_values("_time").reset_index(drop=True).copy()
    x_bins = max(4, min(int(x_bins), len(work)))
    y_values = sorted(work["entry_hour"].dropna().astype(int).unique().tolist())
    if len(y_values) > y_bins:
        y_edges = np.linspace(min(y_values), max(y_values) + 1, y_bins + 1)
        work["_hour_bin"] = pd.cut(work["entry_hour"], bins=y_edges, labels=False, include_lowest=True)
        y_labels = [f"{int(y_edges[i]):02d}" for i in range(y_bins)]
        y_index = list(range(y_bins))
    else:
        work["_hour_bin"] = work["entry_hour"].astype(int)
        y_index = y_values or [0]
        y_labels = [f"{hour:02d}" for hour in y_index]

    edges = np.linspace(0, len(work), x_bins + 1).round().astype(int)
    edges[0] = 0
    edges[-1] = len(work)
    edges = np.maximum.accumulate(edges)
    for idx in range(1, len(edges)):
        if edges[idx] <= edges[idx - 1]:
            edges[idx] = min(len(work), edges[idx - 1] + 1)
    edges[-1] = len(work)

    work["_time_bin"] = np.searchsorted(edges[1:-1], np.arange(len(work)), side="right")
    if metric == "profit_factor":
        matrix = work.pivot_table(index="_hour_bin", columns="_time_bin", values="pnl", aggfunc=_profit_factor)
        z_label = "profit factor"
    elif metric == "win_rate":
        work["_win"] = work["pnl"].gt(0).astype(float)
        matrix = work.pivot_table(index="_hour_bin", columns="_time_bin", values="_win", aggfunc="mean") * 100.0
        z_label = "win rate %"
    else:
        matrix = work.pivot_table(index="_hour_bin", columns="_time_bin", values="pnl", aggfunc="mean")
        z_label = "avg pnl"

    matrix = matrix.reindex(index=y_index, columns=range(x_bins))
    z = _smooth(_fill_matrix(matrix.to_numpy(dtype=float)))
    x, y = np.meshgrid(np.arange(z.shape[1], dtype=float), np.arange(z.shape[0], dtype=float))
    return SurfaceData(
        x=x,
        y=y,
        z=z,
        x_labels=_date_bin_labels(work["_time"], edges),
        y_labels=y_labels,
        z_label=z_label,
    )


def _style_3d_axis(ax: plt.Axes, surface: SurfaceData, title: str, frame_idx: int, frames: int) -> None:
    ax.set_facecolor(BG)
    ax.set_title(title, color=TEXT, fontsize=9, fontweight="bold", pad=2)
    ax.set_xlabel("time", color=MUTED, labelpad=-2, fontsize=6)
    ax.set_ylabel("entry hour", color=MUTED, labelpad=-2, fontsize=6)
    ax.set_zlabel(surface.z_label, color=MUTED, labelpad=-2, fontsize=6)
    ax.tick_params(colors=MUTED, labelsize=5, pad=-2)
    ax.grid(True)
    ax.xaxis.pane.set_facecolor((0.0, 0.0, 0.0, 1.0))
    ax.yaxis.pane.set_facecolor((0.0, 0.0, 0.0, 1.0))
    ax.zaxis.pane.set_facecolor((0.0, 0.0, 0.0, 1.0))
    ax.xaxis.pane.set_edgecolor(GRID)
    ax.yaxis.pane.set_edgecolor(GRID)
    ax.zaxis.pane.set_edgecolor(GRID)

    xticks = _tick_positions(len(surface.x_labels), max_ticks=5)
    yticks = _tick_positions(len(surface.y_labels), max_ticks=5)
    ax.set_xticks(xticks)
    ax.set_xticklabels([surface.x_labels[i] for i in xticks], rotation=12, ha="right")
    ax.set_yticks(yticks)
    ax.set_yticklabels([surface.y_labels[i] for i in yticks])
    ax.view_init(elev=31 + 3 * np.sin(frame_idx / max(frames, 1) * np.pi), azim=-58 + frame_idx * 1.15)


def _draw_surface(
    ax: plt.Axes,
    surface: SurfaceData,
    *,
    frame_idx: int,
    frames: int,
    title: str,
    cmap_name: str,
    center_zero: bool,
) -> None:
    ax.clear()
    z = surface.z.copy()
    min_visible_cols = 2 if z.shape[1] > 1 else 1
    reveal_col = int(np.interp(frame_idx, [0, max(frames - 1, 1)], [min_visible_cols, z.shape[1]]))
    z[:, reveal_col:] = np.nan
    z_masked = np.ma.masked_invalid(z)

    finite = surface.z[np.isfinite(surface.z)]
    if finite.size == 0:
        finite = np.array([0.0, 1.0])
    if center_zero and float(np.nanmin(finite)) < 0 < float(np.nanmax(finite)):
        bound = max(abs(float(np.nanmin(finite))), abs(float(np.nanmax(finite))), 1.0)
        norm = TwoSlopeNorm(vmin=-bound, vcenter=0.0, vmax=bound)
    else:
        lo = float(np.nanpercentile(finite, 5))
        hi = float(np.nanpercentile(finite, 95))
        if lo == hi:
            lo, hi = lo - 1.0, hi + 1.0
        norm = Normalize(vmin=lo, vmax=hi)

    colors = matplotlib.colormaps[cmap_name](norm(surface.z))
    ax.plot_surface(
        surface.x,
        surface.y,
        z_masked,
        facecolors=colors,
        rstride=1,
        cstride=1,
        linewidth=0.18,
        antialiased=True,
        shade=False,
        alpha=0.98,
    )
    ax.plot_wireframe(surface.x, surface.y, z_masked, color="#083352", linewidth=0.12, alpha=0.25)

    z_min = float(np.nanmin(finite))
    z_max = float(np.nanmax(finite))
    if z_min == z_max:
        z_min -= 1.0
        z_max += 1.0
    pad = max((z_max - z_min) * 0.18, 1.0)
    ax.set_zlim(z_min - pad, z_max + pad)
    _style_3d_axis(ax, surface, title, frame_idx, frames)


def _style_panel_axis(ax: plt.Axes, title: str) -> None:
    ax.set_facecolor(PANEL)
    ax.set_title(title, color=TEXT, fontsize=8, fontweight="bold", pad=7, loc="left")
    ax.tick_params(colors=MUTED, labelsize=6)
    for spine in ax.spines.values():
        spine.set_edgecolor("#101820")
    ax.grid(True, color=GRID, alpha=0.28, linewidth=0.5)


def _draw_equity_panel(ax: plt.Axes, trades: pd.DataFrame, frame_idx: int, frames: int) -> None:
    ax.clear()
    _style_panel_axis(ax, "equity cursor")
    if trades.empty:
        ax.text(0.5, 0.5, "No trade log", color=MUTED, ha="center", va="center", transform=ax.transAxes)
        return

    x = np.arange(len(trades))
    pnl = pd.to_numeric(trades["cumulative_pnl"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    equity = pd.to_numeric(trades["equity"], errors="coerce").to_numpy(dtype=float)
    equity_offset = equity - equity[0] if np.isfinite(equity).any() else pnl
    cursor = int(np.interp(frame_idx, [0, max(frames - 1, 1)], [0, len(trades) - 1]))

    ax.plot(x, pnl, color="#163a55", linewidth=1.0, alpha=0.8)
    ax.plot(x[: cursor + 1], pnl[: cursor + 1], color=YELLOW, linewidth=1.6)
    ax.plot(x[: cursor + 1], equity_offset[: cursor + 1], color=CYAN, linewidth=0.9, alpha=0.70)
    ax.fill_between(x[: cursor + 1], 0, pnl[: cursor + 1], color=YELLOW, alpha=0.09)
    ax.axhline(0, color=MUTED, linewidth=0.7, alpha=0.6)
    ax.axvline(cursor, color=ORANGE, linewidth=1.0, alpha=0.95)

    tick_positions = _tick_positions(len(trades), max_ticks=4)
    labels = [pd.Timestamp(trades["_time"].iloc[i]).strftime("%Y") for i in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(labels)
    ax.set_ylabel("cumulative pnl", color=MUTED, fontsize=6)
    current = trades.iloc[cursor]
    ax.text(
        0.98,
        0.93,
        f"{pd.Timestamp(current['_time']).strftime('%Y-%m-%d')}  pnl {pnl[cursor]:,.0f}",
        color=TEXT,
        fontsize=6,
        ha="right",
        va="top",
        transform=ax.transAxes,
    )


def _draw_validation_panel(ax: plt.Axes, folds: pd.DataFrame, trades: pd.DataFrame, frame_idx: int, frames: int) -> None:
    ax.clear()
    _style_panel_axis(ax, "point-in-time validation")
    if folds.empty:
        _draw_equity_panel(ax, trades, frame_idx, frames)
        return

    x = np.arange(len(folds))
    cursor = int(np.interp(frame_idx, [0, max(frames - 1, 1)], [0, len(folds) - 1]))
    if "train_metric" in folds.columns:
        train = pd.to_numeric(folds["train_metric"], errors="coerce")
        ax.plot(x, train, color=BLUE, linewidth=1.2, marker="o", markersize=3, alpha=0.8, label="train metric")
    if "test_profit_factor" in folds.columns:
        test_pf = pd.to_numeric(folds["test_profit_factor"], errors="coerce")
        colors = np.where(test_pf >= 1.0, GREEN, RED)
        if "test_total_trades" in folds.columns:
            trade_counts = pd.to_numeric(folds["test_total_trades"], errors="coerce").fillna(20)
        else:
            trade_counts = pd.Series(20, index=folds.index, dtype=float)
        sizes = np.clip(trade_counts * 1.8, 22, 150)
        ax.scatter(x, test_pf, color=colors, s=sizes, edgecolor=TEXT, linewidth=0.35, alpha=0.9, label="test PF")
    if "test_total_pnl" in folds.columns and len(folds) > 1:
        pnl = pd.to_numeric(folds["test_total_pnl"], errors="coerce").fillna(0.0)
        denom = max(abs(float(pnl.min())), abs(float(pnl.max())), 1.0)
        scaled = 1.0 + (pnl / denom) * 0.35
        ax.plot(x, scaled, color=YELLOW, linewidth=1.0, alpha=0.75, label="test pnl scaled")

    ax.axhline(1.0, color=TEXT, linestyle="--", linewidth=0.7, alpha=0.55)
    ax.axvline(cursor, color=ORANGE, linewidth=1.0, alpha=0.95)
    ax.set_xlabel("fold", color=MUTED, fontsize=6)
    ax.set_ylabel("validation score", color=MUTED, fontsize=6)
    ax.set_xticks(x)
    fold_labels = []
    for idx, value in enumerate(folds["fold_idx"]):
        fold_labels.append(str(int(value)) if np.isfinite(value) else str(idx))
    ax.set_xticklabels(fold_labels)
    ax.legend(facecolor=PANEL, edgecolor="#101820", labelcolor=TEXT, fontsize=5, loc="upper left")
    row = folds.iloc[cursor]
    label = f"fold {int(row.get('fold_idx', cursor))}"
    if np.isfinite(row.get("test_profit_factor", np.nan)):
        label += f"  test PF {float(row['test_profit_factor']):.2f}"
    ax.text(0.98, 0.93, label, color=TEXT, fontsize=6, ha="right", va="top", transform=ax.transAxes)


def _new_figure(title: str, subtitle: str) -> tuple[plt.Figure, plt.Axes, plt.Axes]:
    fig = plt.figure(figsize=(4.5, 8.0), facecolor=BG)
    grid = fig.add_gridspec(2, 1, height_ratios=[1.32, 0.92], hspace=0.18, top=0.91, bottom=0.055)
    ax_surface = fig.add_subplot(grid[0], projection="3d")
    ax_panel = fig.add_subplot(grid[1])
    fig.text(0.5, 0.972, title, ha="center", va="top", color=TEXT, fontsize=10, fontweight="bold")
    fig.text(0.5, 0.947, subtitle, ha="center", va="top", color=MUTED, fontsize=5.8)
    return fig, ax_surface, ax_panel


def _save_gif(fig: plt.Figure, anim: animation.FuncAnimation, path: Path, *, fps: int, dpi: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = animation.PillowWriter(fps=fps)
    anim.save(path, writer=writer, dpi=dpi)
    plt.close(fig)


def _save_placeholder(path: Path, title: str, message: str, *, fps: int, dpi: int) -> None:
    fig, _, ax = _new_figure(title, "no animation data")
    ax.text(0.5, 0.5, message, ha="center", va="center", color=MUTED, transform=ax.transAxes)
    ax.axis("off")
    anim = animation.FuncAnimation(fig, lambda _: None, frames=1, interval=1000)
    _save_gif(fig, anim, path, fps=fps, dpi=dpi)


def _animate_signal_surface(
    trades: pd.DataFrame,
    path: Path,
    *,
    frames: int,
    fps: int,
    dpi: int,
    run_name: str,
) -> None:
    if trades.empty:
        _save_placeholder(path, "Rolling Signal Performance Surface", "No trade log found", fps=fps, dpi=dpi)
        return

    surface = _build_trade_surface(trades, metric="avg_pnl")
    fig, ax_surface, ax_panel = _new_figure("Rolling Signal Performance Surface", f"{run_name} | avg pnl by entry hour")

    def update(frame_idx: int) -> None:
        _draw_surface(
            ax_surface,
            surface,
            frame_idx=frame_idx,
            frames=frames,
            title="realized edge surface",
            cmap_name="viridis",
            center_zero=True,
        )
        _draw_equity_panel(ax_panel, trades, frame_idx, frames)

    anim = animation.FuncAnimation(fig, update, frames=frames, interval=1000 / max(fps, 1), repeat=True)
    _save_gif(fig, anim, path, fps=fps, dpi=dpi)


def _animate_walkforward_validation(
    trades: pd.DataFrame,
    folds: pd.DataFrame,
    path: Path,
    *,
    frames: int,
    fps: int,
    dpi: int,
    run_name: str,
) -> None:
    if trades.empty and folds.empty:
        _save_placeholder(path, "Walk-Forward Robustness Analysis", "No validation data found", fps=fps, dpi=dpi)
        return

    source_trades = trades if not trades.empty else pd.DataFrame({"pnl": [0.0], "_time": [pd.Timestamp("1970-01-01")], "entry_hour": [0], "equity": [0.0], "cumulative_pnl": [0.0]})
    surface = _build_trade_surface(source_trades, metric="profit_factor")
    fig, ax_surface, ax_panel = _new_figure("Walk-Forward Robustness Analysis", f"{run_name} | train vs test")

    def update(frame_idx: int) -> None:
        _draw_surface(
            ax_surface,
            surface,
            frame_idx=frame_idx,
            frames=frames,
            title="rolling validation surface",
            cmap_name="turbo",
            center_zero=False,
        )
        _draw_validation_panel(ax_panel, folds, trades, frame_idx, frames)

    anim = animation.FuncAnimation(fig, update, frames=frames, interval=1000 / max(fps, 1), repeat=True)
    _save_gif(fig, anim, path, fps=fps, dpi=dpi)


def _write_index(paths: ResearchAnimationPaths) -> None:
    lines = [
        "# Research Animations",
        "",
        "Generated 9:16 animated research visuals for this run.",
        "",
        f"- [Rolling signal performance surface]({paths.signal_surface_gif.name})",
        f"- [Walk-forward validation surface]({paths.walkforward_validation_gif.name})",
        "",
    ]
    paths.index_md.write_text("\n".join(lines), encoding="utf-8")


def export_research_animations(
    run_dir: Path | str,
    *,
    frames: int = 48,
    fps: int = 12,
    dpi: int = 110,
) -> ResearchAnimationPaths:
    """
    Generate vertical GIF animations from research CSVs already emitted for a run.

    The exporter is report-only: it reads the trade log and validation CSVs, then
    renders compact 9:16 GIFs using Matplotlib's Pillow writer.
    """
    run_dir = Path(run_dir)
    animation_dir = run_dir / "research" / "animations"
    animation_dir.mkdir(parents=True, exist_ok=True)
    frames = max(2, int(frames))
    fps = max(1, int(fps))
    dpi = max(72, int(dpi))

    paths = ResearchAnimationPaths(
        animation_dir=animation_dir,
        signal_surface_gif=animation_dir / "signal_surface.gif",
        walkforward_validation_gif=animation_dir / "walkforward_validation.gif",
        index_md=animation_dir / "animation_index.md",
    )

    trades = _load_trades(run_dir)
    folds = _load_folds(run_dir)
    run_name = _short_label(run_dir.name, 42)
    _animate_signal_surface(trades, paths.signal_surface_gif, frames=frames, fps=fps, dpi=dpi, run_name=run_name)
    _animate_walkforward_validation(trades, folds, paths.walkforward_validation_gif, frames=frames, fps=fps, dpi=dpi, run_name=run_name)
    _write_index(paths)
    return paths
