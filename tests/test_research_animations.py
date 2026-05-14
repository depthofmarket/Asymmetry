from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from results.research_animations import _build_trade_surface, _load_trades, export_research_animations
import matplotlib.animation as animation


def _write_fixture_run(run_dir: Path) -> None:
    trades_dir = run_dir / "trades"
    folds_dir = run_dir / "research" / "walkforward"
    trades_dir.mkdir(parents=True)
    folds_dir.mkdir(parents=True)

    times = pd.date_range("2024-01-02 09:30", periods=12, freq="30min")
    pnl = np.array([-120, 80, 140, -60, 220, 90, -70, 130, 160, -110, 210, 95], dtype=float)
    trades = pd.DataFrame(
        {
            "entry_time": times,
            "exit_time": times + pd.Timedelta(minutes=5),
            "entry_hour": times.hour,
            "pnl": pnl,
            "equity": 100_000 + pnl.cumsum(),
        }
    )
    trades.to_csv(trades_dir / "trade_log.csv", index=False)

    folds = pd.DataFrame(
        {
            "fold_idx": [0, 1],
            "train_metric": [0.9, 1.1],
            "test_profit_factor": [1.2, 0.95],
            "test_total_pnl": [500, -100],
            "test_total_trades": [8, 4],
        }
    )
    folds.to_csv(folds_dir / "walkforward_folds.csv", index=False)


class ResearchAnimationTests(unittest.TestCase):
    def test_trade_surface_has_expected_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            _write_fixture_run(run_dir)
            trades = _load_trades(run_dir)

            surface = _build_trade_surface(trades, metric="avg_pnl", x_bins=4, y_bins=6)

            self.assertEqual(surface.z.shape, (6, 4))
            self.assertTrue(np.isfinite(surface.z).all())
            self.assertEqual(len(surface.x_labels), 4)

    def test_export_research_animations_writes_gifs(self):
        if "pillow" not in animation.writers.list():
            self.skipTest("Matplotlib Pillow animation writer is unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            _write_fixture_run(run_dir)

            paths = export_research_animations(run_dir, frames=2, fps=2, dpi=72)

            self.assertTrue(paths.signal_surface_gif.exists())
            self.assertTrue(paths.walkforward_validation_gif.exists())
            self.assertTrue(paths.index_md.exists())
            self.assertGreater(paths.signal_surface_gif.stat().st_size, 0)
            self.assertGreater(paths.walkforward_validation_gif.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
