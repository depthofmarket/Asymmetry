"""
Agent Execution Guardrails & Subprocess Boundaries.

Provides runtime command validation, shell injection prevention, dangerous binary
blocking, unauthorized exploratory backtest protection, and safe subprocess execution
with enforced wall-clock timeouts.
"""

from __future__ import annotations

import logging
from pathlib import Path
import shlex
import subprocess
from typing import Any, Sequence, Tuple, Optional

from backtest.research_protocol import DEFAULT_BLOCKED_AGENT_COMMANDS

logger = logging.getLogger(__name__)


class CommandExecutionBlockedError(PermissionError):
    """Raised when a command violates agent execution guardrails."""
    pass


# Dangerous shell injection and command chaining patterns
DANGEROUS_SHELL_TOKENS: list[str] = [
    "&&",
    "||",
    ";",
    "|",
    "$(",
    "`",
    "\n",
    "\r",
    ">>",
    ">",
    "<<",
    "<",
    "&",
]

# Dangerous system binaries and administrative tools
DANGEROUS_BINARIES: set[str] = {
    "rm",
    "sudo",
    "su",
    "curl",
    "wget",
    "chmod",
    "chown",
    "chgrp",
    "kill",
    "pkill",
    "killall",
    "dd",
    "mkfs",
    "fdisk",
    "parted",
    "shutdown",
    "reboot",
    "poweroff",
    "init",
    "telnet",
    "nc",
    "netcat",
    "bash",
    "sh",
    "zsh",
    "csh",
    "tcsh",
    "dash",
}

# Blocked agent exploratory search scripts and base names
BLOCKED_SCRIPTS: set[str] = set(DEFAULT_BLOCKED_AGENT_COMMANDS)
BLOCKED_SCRIPT_BASENAMES: set[str] = {Path(s).name.lower() for s in DEFAULT_BLOCKED_AGENT_COMMANDS}
BLOCKED_MODULES: set[str] = {
    "main_backtest",
    "scripts.probe_candidate_frequency",
    "probe_candidate_frequency",
}


def validate_command(cmd: str | Sequence[str]) -> Tuple[bool, Optional[str]]:
    """
    Validates a command before execution against security guardrails.

    Checks for:
    1. Dangerous shell chaining / injection tokens (&&, ||, ;, |, $(, `, newlines).
    2. Dangerous shell commands and system binaries (rm, sudo, curl, wget, chmod, chown, kill, etc.).
    3. Unauthorized exploratory search scripts and batch runners (main_backtest.py, probe_candidate_frequency.py, etc.).

    Args:
        cmd: A command string (e.g. "pytest tests/") or argument sequence (e.g. ["pytest", "tests/"]).

    Returns:
        Tuple[bool, Optional[str]]: (True, None) if command is permitted, or (False, reason) if blocked.
    """
    if cmd is None:
        return False, "Command cannot be None"

    if isinstance(cmd, str):
        trimmed = cmd.strip()
        if not trimmed:
            return False, "Command cannot be empty"

        # Check raw string for shell chaining / injection tokens
        for token in DANGEROUS_SHELL_TOKENS:
            if token in cmd:
                return False, f"Shell chaining/injection detected: contains '{token}'"

        try:
            tokens = shlex.split(cmd)
        except ValueError as exc:
            return False, f"Malformed command string: {exc}"

        if not tokens:
            return False, "Command cannot be empty"

    elif isinstance(cmd, (list, tuple)):
        if len(cmd) == 0:
            return False, "Command cannot be empty"

        tokens = []
        for i, item in enumerate(cmd):
            if not isinstance(item, str):
                return False, f"Command argument at index {i} must be a string, got {type(item).__name__}"
            for token in DANGEROUS_SHELL_TOKENS:
                if token in item:
                    # Allow semicolon only if explicitly passed as code to python -c
                    if token == ";" and i > 0 and cmd[i - 1] == "-c":
                        continue
                    return False, f"Shell chaining/injection detected in argument '{item}': contains '{token}'"
            tokens.append(item)
    else:
        return False, f"Command must be a string or sequence of strings, got {type(cmd).__name__}"

    # Check executable binary (first token)
    executable_token = tokens[0]
    exec_base = Path(executable_token).name.lower()

    if exec_base in DANGEROUS_BINARIES:
        return False, f"Blocked dangerous binary: '{executable_token}'"

    # Check for dangerous binaries anywhere in arguments (e.g. env rm, xargs sudo)
    for token in tokens[1:]:
        if Path(token).name.lower() in DANGEROUS_BINARIES:
            return False, f"Blocked dangerous binary in command arguments: '{token}'"

    # Check for unauthorized agent exploratory scripts and modules
    for i, token in enumerate(tokens):
        token_lower = token.lower()
        token_base = Path(token).name.lower()

        # Check direct script name or basename
        if token_lower in BLOCKED_SCRIPTS or token_base in BLOCKED_SCRIPT_BASENAMES:
            return False, f"Blocked unauthorized agent exploratory script: '{token}'"

        # Check Python module execution flag (-m module_name)
        if token == "-m" and (i + 1) < len(tokens):
            module_target = tokens[i + 1].lower()
            if module_target in BLOCKED_MODULES or module_target in BLOCKED_SCRIPT_BASENAMES:
                return False, f"Blocked unauthorized agent exploratory module: '{tokens[i + 1]}'"

        for blocked_mod in BLOCKED_MODULES:
            if blocked_mod in token_lower:
                return False, f"Blocked unauthorized agent exploratory module in '{token}'"

    return True, None


def safe_subprocess_run(
    cmd: str | Sequence[str],
    timeout: float = 300.0,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """
    Executes a subprocess safely with mandatory agent guardrail validation,
    wall-clock timeout enforcement, and structured error logging.

    Args:
        cmd: Command string or sequence of command arguments.
        timeout: Mandatory wall-clock timeout in seconds (default 300s).
        **kwargs: Additional keyword arguments forwarded to subprocess.run.

    Returns:
        subprocess.CompletedProcess: Execution result.

    Raises:
        CommandExecutionBlockedError: If command fails guardrail validation or shell=True.
        ValueError: If timeout is not positive.
        subprocess.TimeoutExpired: If execution exceeds timeout.
        subprocess.CalledProcessError: If check=True and process returns non-zero.
    """
    if kwargs.get("shell", False):
        logger.error("Execution with shell=True is strictly prohibited by agent guardrails: %s", cmd)
        raise CommandExecutionBlockedError("Execution with shell=True is strictly prohibited by agent guardrails")

    is_valid, reason = validate_command(cmd)
    if not is_valid:
        logger.error("Command blocked by agent guardrails: %s (reason: %s)", cmd, reason)
        raise CommandExecutionBlockedError(f"Command blocked by agent guardrails: {reason}")

    if timeout is None:
        timeout = 300.0
    else:
        try:
            timeout = float(timeout)
        except (ValueError, TypeError):
            raise ValueError(f"Timeout must be a numeric value, got {timeout}")

    if timeout <= 0:
        raise ValueError(f"Timeout must be positive, got {timeout}")

    # If cmd is a string and shell=False (default), parse into argument list for POSIX
    if isinstance(cmd, str) and not kwargs.get("shell", False):
        exec_cmd: str | list[str] = shlex.split(cmd)
    else:
        exec_cmd = cmd

    logger.info("Executing safe subprocess: %s (timeout=%.1fs)", cmd, timeout)
    try:
        return subprocess.run(exec_cmd, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as exc:
        logger.error("Subprocess timed out after %.1f seconds: %s", timeout, cmd)
        raise
    except subprocess.CalledProcessError as exc:
        logger.error("Subprocess failed with exit code %s: %s", exc.returncode, cmd)
        raise
    except Exception as exc:
        logger.error("Subprocess execution error for %s: %s", cmd, exc)
        raise
