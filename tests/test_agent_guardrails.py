"""
Unit tests for Agent Execution Guardrails & Subprocess Boundaries.

Tests command validation, blocked binary rejection, exploratory backtest script blocking,
shell injection detection, timeout enforcement, and safe subprocess execution.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest

from backtest.agent_guardrails import (
    DANGEROUS_BINARIES,
    DANGEROUS_SHELL_TOKENS,
    safe_subprocess_run,
    validate_command,
)
from backtest.research_protocol import DEFAULT_BLOCKED_AGENT_COMMANDS


class AgentGuardrailsTests(unittest.TestCase):
    def test_validate_command_permits_benign_commands(self) -> None:
        benign_commands = [
            "pytest tests/test_agent_guardrails.py",
            ["python", "scripts/query_provenance.py", "--list"],
            ["git", "status"],
            "git diff --stat",
            ["echo", "hello world"],
            [sys.executable, "--version"],
        ]
        for cmd in benign_commands:
            valid, reason = validate_command(cmd)
            self.assertTrue(valid, f"Expected {cmd} to be valid, got reason: {reason}")
            self.assertIsNone(reason)

    def test_validate_command_rejects_empty_and_malformed_inputs(self) -> None:
        invalid_inputs = [
            None,
            "",
            "   ",
            [],
            (),
            12345,
            {"cmd": "pytest"},
            [123, 456],
            "python -c 'unclosed quote",
        ]
        for bad_input in invalid_inputs:
            valid, reason = validate_command(bad_input)  # type: ignore[arg-type]
            self.assertFalse(valid, f"Expected {bad_input!r} to be rejected")
            self.assertIsNotNone(reason)

    def test_validate_command_rejects_shell_chaining_and_injection_tokens(self) -> None:
        injection_patterns = [
            "pytest && rm -rf /",
            "pytest || exit 1",
            "pytest ; ls -la",
            "pytest | tee test.log",
            "echo $(whoami)",
            "echo `id`",
            "pytest\nrm -rf /",
            "pytest\rrm -rf /",
        ]
        for cmd_str in injection_patterns:
            valid, reason = validate_command(cmd_str)
            self.assertFalse(valid, f"Expected injection '{cmd_str}' to be rejected")
            self.assertIn("Shell chaining/injection detected", reason or "")

    def test_validate_command_rejects_shell_tokens_in_argument_list(self) -> None:
        list_injections = [
            ["pytest", "-k", "test_foo ; test_bar"],
            ["pytest", "-k", "test_foo && test_bar"],
            ["pytest", "-k", "test_foo || test_bar"],
            ["echo", "foo; rm -rf /"],
            ["cat", "file | grep secret"],
            ["echo", "$(whoami)"],
            ["echo", "`id`"],
        ]
        for cmd_list in list_injections:
            valid, reason = validate_command(cmd_list)
            self.assertFalse(valid, f"Expected argument injection in {cmd_list} to be rejected")
            self.assertIn("Shell chaining/injection detected", reason or "")

    def test_validate_command_rejects_blocked_module_inside_python_c(self) -> None:
        blocked_c_cmds = [
            ["python", "-c", "import main_backtest; main_backtest.main()"],
            ["python3", "-c", "import probe_candidate_frequency; probe_candidate_frequency.run()"],
        ]
        for cmd in blocked_c_cmds:
            valid, reason = validate_command(cmd)
            self.assertFalse(valid, f"Expected blocked script inside -c to be rejected: {cmd}")
            self.assertIn("Blocked unauthorized agent exploratory module", reason or "")

    def test_validate_command_rejects_dangerous_binaries(self) -> None:
        for binary in ["rm", "sudo", "su", "curl", "wget", "chmod", "chown", "kill", "pkill", "bash", "sh"]:
            cmd_str = f"{binary} some_target"
            valid, reason = validate_command(cmd_str)
            self.assertFalse(valid, f"Expected dangerous binary '{binary}' to be blocked")
            self.assertIn("Blocked dangerous binary", reason or "")

            # Also check absolute path invocation (e.g. /bin/rm, /usr/bin/sudo)
            path_cmd = [f"/usr/bin/{binary}", "target"]
            valid_path, reason_path = validate_command(path_cmd)
            self.assertFalse(valid_path, f"Expected path binary '{path_cmd}' to be blocked")
            self.assertIn("Blocked dangerous binary", reason_path or "")

    def test_validate_command_rejects_dangerous_binaries_in_arguments(self) -> None:
        wrapper_commands = [
            ["env", "rm", "-rf", "/tmp/test"],
            ["xargs", "kill", "-9"],
            ["sudo", "ls"],
        ]
        for cmd in wrapper_commands:
            valid, reason = validate_command(cmd)
            self.assertFalse(valid, f"Expected argument wrapper '{cmd}' to be blocked")
            self.assertIn("Blocked dangerous binary", reason or "")

    def test_validate_command_rejects_all_default_blocked_agent_scripts(self) -> None:
        for script in DEFAULT_BLOCKED_AGENT_COMMANDS:
            # Test direct string execution
            valid_str, reason_str = validate_command(f"python {script}")
            self.assertFalse(valid_str, f"Expected '{script}' to be blocked in string command")
            self.assertIn("Blocked unauthorized agent exploratory", reason_str or "")

            # Test list execution
            valid_list, reason_list = validate_command(["python3", script])
            self.assertFalse(valid_list, f"Expected '{script}' to be blocked in list command")
            self.assertIn("Blocked unauthorized agent exploratory", reason_list or "")

            # Test with path prefix
            valid_path, reason_path = validate_command([sys.executable, f"./{script}"])
            self.assertFalse(valid_path, f"Expected './{script}' to be blocked")
            self.assertIn("Blocked unauthorized agent exploratory", reason_path or "")

    def test_validate_command_rejects_blocked_module_execution(self) -> None:
        module_commands = [
            ["python", "-m", "main_backtest"],
            ["python3", "-m", "scripts.probe_candidate_frequency"],
            "python -m main_backtest",
        ]
        for cmd in module_commands:
            valid, reason = validate_command(cmd)
            self.assertFalse(valid, f"Expected module invocation '{cmd}' to be blocked")
            self.assertIn("Blocked unauthorized agent exploratory module", reason or "")

    def test_safe_subprocess_run_raises_permission_error_on_blocked_command(self) -> None:
        blocked_commands = [
            "rm -rf /tmp/scratch",
            "sudo apt-get update",
            "python main_backtest.py",
            ["python", "scripts/probe_candidate_frequency.py"],
            "pytest && rm -rf",
        ]
        for cmd in blocked_commands:
            with self.assertRaises(PermissionError) as ctx:
                safe_subprocess_run(cmd)
            self.assertIn("Command blocked by agent guardrails", str(ctx.exception))

    def test_safe_subprocess_run_enforces_positive_numeric_timeout(self) -> None:
        invalid_timeouts = [0, -10, "abc", None]  # None should fallback to 300, not error
        for to in [0, -1, -300]:
            with self.assertRaises(ValueError):
                safe_subprocess_run(["echo", "hi"], timeout=to)

        with self.assertRaises(ValueError):
            safe_subprocess_run(["echo", "hi"], timeout="not_a_number")  # type: ignore[arg-type]

    def test_safe_subprocess_run_executes_valid_command_successfully(self) -> None:
        res = safe_subprocess_run(
            [sys.executable, "-c", "import sys; sys.stdout.write('guardrails_verified\\n')"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "guardrails_verified")

    def test_safe_subprocess_run_executes_valid_string_command(self) -> None:
        res = safe_subprocess_run(
            f"{sys.executable} -c \"print('string_cmd_ok')\"",
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "string_cmd_ok")

    def test_safe_subprocess_run_enforces_wall_clock_timeout(self) -> None:
        # Launch python sleep that exceeds timeout
        with self.assertRaises(subprocess.TimeoutExpired):
            safe_subprocess_run(
                [sys.executable, "-c", "import time; time.sleep(3.0)"],
                timeout=0.3,
            )

    def test_safe_subprocess_run_handles_process_errors(self) -> None:
        # Non-zero exit with check=False returns CompletedProcess
        res = safe_subprocess_run(
            [sys.executable, "-c", "import sys; sys.exit(7)"],
            check=False,
            timeout=5,
        )
        self.assertEqual(res.returncode, 7)

        # Non-zero exit with check=True raises CalledProcessError
        with self.assertRaises(subprocess.CalledProcessError) as ctx:
            safe_subprocess_run(
                [sys.executable, "-c", "import sys; sys.exit(7)"],
                check=True,
                timeout=5,
            )
        self.assertEqual(ctx.exception.returncode, 7)


if __name__ == "__main__":
    unittest.main()
