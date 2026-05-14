#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.backtest_config import RESEARCH_CONFIG
from results.research_animations import export_research_animations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export 9:16 animated research GIFs for an existing run directory.",
    )
    parser.add_argument("run_dir", help="Path to a run directory under results/runs.")
    parser.add_argument(
        "--frames",
        type=int,
        default=int(RESEARCH_CONFIG.get("research_animation_frames", 48)),
        help="Number of frames per GIF.",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=int(RESEARCH_CONFIG.get("research_animation_fps", 12)),
        help="Frames per second for the GIF writer.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=int(RESEARCH_CONFIG.get("research_animation_dpi", 110)),
        help="Render DPI.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = export_research_animations(Path(args.run_dir), frames=args.frames, fps=args.fps, dpi=args.dpi)
    print(f"Research animations: {paths.animation_dir}")
    print(f"Index:              {paths.index_md}")
    print(f"Signal surface:     {paths.signal_surface_gif}")
    print(f"Validation:         {paths.walkforward_validation_gif}")


if __name__ == "__main__":
    main()
