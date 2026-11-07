from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np
import pandas as pd


_mpl_config_dir = Path("results/.mplconfig").resolve()
_mpl_config_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_mpl_config_dir))

BG = "#080d14"
PANEL = "#111827"
GRID = "#2b3a4f"
TEXT = "#e5eefb"
MUTED = "#94a3b8"


@dataclass(frozen=True)
class HeatmapPaths:
    csv_path: Path
    png_path: Path


def _style_dark_axis(ax) -> None:
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=MUTED)
    ax.xaxis.label.set_color(TEXT)
    ax.yaxis.label.set_color(TEXT)
    ax.title.set_color(TEXT)
    for spine in ax.spines.values():
        spine.set_edgecolor(GRID)
    ax.grid(False)


def _diverging_text_color(value: float, limit: float) -> str:
    if not np.isfinite(value) or limit <= 0:
        return TEXT
    return "#f8fafc" if abs(value) >= limit * 0.45 else "#07101a"


def plot_heatmap(
    matrix: pd.DataFrame,
    title: str,
    out_dir: Path,
    filename_stem: str,
    fmt: str = ".2f",
) -> HeatmapPaths:
    """
    Plot a numeric 2D dataframe as a heatmap using matplotlib only.
    Rows/cols are the axes labels.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{filename_stem}.csv"
    png_path = out_dir / f"{filename_stem}.png"

    matrix.to_csv(csv_path)

    values = matrix.to_numpy(dtype=float)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        vmin, vmax = -1.0, 1.0
        norm = None
    else:
        vmin, vmax = float(np.percentile(finite, 5)), float(np.percentile(finite, 95))
        if vmin == vmax:
            vmin, vmax = vmin - 1.0, vmax + 1.0
        if vmin < 0 < vmax:
            vmax_abs = max(abs(vmin), abs(vmax))
            vmin, vmax = -vmax_abs, vmax_abs
            norm = TwoSlopeNorm(vmin=vmin, vcenter=0.0, vmax=vmax)
        else:
            norm = None

    fig, ax = plt.subplots(figsize=(10.5, 7.2))
    fig.patch.set_facecolor(BG)
    cmap = "RdYlGn" if finite.size and np.nanmin(finite) < 0 < np.nanmax(finite) else "magma"
    im = ax.imshow(values, aspect="auto", cmap=cmap, vmin=vmin, vmax=vmax, norm=norm)
    ax.set_title(title, fontsize=17, fontweight="bold", pad=12)

    ax.set_xticks(np.arange(matrix.shape[1]))
    ax.set_xticklabels([str(c) for c in matrix.columns], rotation=45, ha="right")
    ax.set_yticks(np.arange(matrix.shape[0]))
    ax.set_yticklabels([str(i) for i in matrix.index])

    # annotate cells (skip if too large)
    if matrix.shape[0] <= 25 and matrix.shape[1] <= 25:
        for r in range(matrix.shape[0]):
            for c in range(matrix.shape[1]):
                v = values[r, c]
                if np.isfinite(v):
                    text_color = (
                        _diverging_text_color(float(v), max(abs(vmin), abs(vmax)))
                        if cmap == "RdYlGn"
                        else TEXT
                    )
                    ax.text(c, r, format(v, fmt), ha="center", va="center", fontsize=8, color=text_color)

    _style_dark_axis(ax)
    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.ax.tick_params(colors=MUTED)
    cbar.ax.yaxis.label.set_color(TEXT)
    cbar.outline.set_edgecolor(GRID)
    plt.tight_layout()
    plt.savefig(png_path, dpi=160, facecolor=fig.get_facecolor())
    plt.close()

    return HeatmapPaths(csv_path=csv_path, png_path=png_path)
