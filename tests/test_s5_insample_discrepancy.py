import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

import pandas as pd

from strategies.crude_rth_expansion_s5 import CrudeRthExpansionParams, simulate_intrabar_execution

ROOT = Path(__file__).resolve().parents[1]


def _old_module():
    source = subprocess.check_output(
        ["git", "show", "ec17df0:strategies/crude_rth_expansion_s5.py"],
        cwd=ROOT,
    )
    path = Path("/tmp/crude_rth_expansion_s5_ec17df0.py")
    path.write_bytes(source)
    spec = importlib.util.spec_from_file_location("crude_rth_expansion_s5_ec17df0", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _same_bar_frames():
    times = pd.to_datetime(["2024-06-03 10:15", "2024-06-03 10:16", "2024-06-03 12:30"])
    rth = pd.DataFrame({
        "date_str": ["2024-06-03"] * 3,
        "time": times,
        "high": [70.20, 70.50, 70.10],
        "low": [69.90, 69.50, 70.00],
        "close": [70.10, 70.00, 70.05],
        "m": [615, 616, 750],
    })
    signals = pd.DataFrame({
        "signal": [1, 0, 0],
        "signal_type": ["crude_rth_expansion_long", "", ""],
        "date_str": ["2024-06-03"] * 3,
        "time": times,
        "entry_price": [70.01, float("nan"), float("nan")],
        "stop_price": [69.56, float("nan"), float("nan")],
        "target_price": [70.91, float("nan"), float("nan")],
    })
    return rth, signals


class TestS5Discrepancy(unittest.TestCase):
    def test_same_bar_breakeven_is_the_intentional_exit_change(self) -> None:
        rth, signals = _same_bar_frames()
        params = CrudeRthExpansionParams()
        current = simulate_intrabar_execution(rth, signals, params)
        old = _old_module().simulate_intrabar_execution(rth, signals, params)
        self.assertEqual(old.iloc[0]["exit_reason"], "breakeven")
        self.assertEqual(current.iloc[0]["exit_reason"], "stop_loss")

    def test_current_entry_delay_is_separate_from_the_breakeven_fix(self) -> None:
        params = CrudeRthExpansionParams(warmup_rth_sessions=0)
        minutes = list(range(570, 615)) + list(range(615, 676))
        # 45 consolidation bars and 61 trade-window bars, all inside 2024.
        base = 70.0
        rows = []
        for i, minute in enumerate(minutes):
            price = base if minute <= 614 else base + 0.80
            rows.append({
                "date_str": "2024-06-03",
                "time": pd.Timestamp("2024-06-03") + pd.Timedelta(minutes=minute),
                "open": price,
                "high": price + 0.05,
                "low": price - 0.05,
                "close": price,
                "m": minute,
            })
        rth = pd.DataFrame(rows)
        # Consolidation range is about 0.10, below the frozen 0.30 gate.
        # Widen two consolidation bars without changing frozen parameters.
        rth.loc[0, "low"] = 69.70
        rth.loc[10, "high"] = 70.40
        daily = {
            "2024-06-03": {"atr14": 2.5, "rvol": 1.5, "sma50": 69.0, "macro_trend": 1},
        }
        current = __import__(
            "strategies.crude_rth_expansion_s5", fromlist=["generate_signals"]
        ).generate_signals(rth, daily, params)
        old = _old_module().generate_signals(rth, daily, params)
        current_hits = current.index[current["signal"] != 0]
        old_hits = old.index[old["signal"] != 0]
        self.assertTrue(len(old_hits) == 1 and len(current_hits) == 1)
        self.assertLess(int(old_hits[0]), int(current_hits[0]))
        self.assertEqual(int(rth.loc[current_hits[0], "m"]), 615 + 29)

    def test_regenerator_refuses_the_protected_period(self) -> None:
        ran = subprocess.run(
            ["python", "scripts/regenerate_insample_study_trades.py", "--end", "2025-01-02"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(ran.returncode, 0)
        self.assertIn("protected", ran.stderr.lower() + ran.stdout.lower())
