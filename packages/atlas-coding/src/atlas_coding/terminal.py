"""Authorized terminal execution governed by Action Firewall and security policies."""

import os
import re
import shlex
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from atlas_core.contracts.action import ActionTarget, ComputerAction
from atlas_core.contracts.policy import PolicyDecisionType
from atlas_policy.firewall import ActionFirewall
from pydantic import BaseModel, Field

from atlas_coding.explorer import RepositoryExplorer

SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+[a-zA-Z0-9_\-\.]{12,})"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{12,}['\"]?)"),
    re.compile(r"(?i)(token\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{12,}['\"]?)"),
    re.compile(r"(?i)(password\s*[:=]\s*['\"]?[^\s'\"]+['\"]?)"),
    re.compile(r"(?i)(secret\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{12,}['\"]?)"),
]


def redact_secrets(text: str) -> str:
    """Mask credentials and sensitive tokens from console outputs."""
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


class TerminalResult(BaseModel):
    """Structured outcome of a terminal execution."""

    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    cwd: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)


class AuthorizedTerminalDriver:
    """Terminal execution driver enforcing Action Firewall policies and process isolation."""

    def __init__(
        self,
        explorer: RepositoryExplorer,
        firewall: ActionFirewall | None = None,
        approval_handler: Callable[[ComputerAction], bool] | None = None,
        auto_approve_safe_commands: bool = True,
        default_timeout_seconds: float = 60.0,
        max_timeout_seconds: float = 600.0,
    ) -> None:
        self.explorer = explorer
        self.firewall = firewall or ActionFirewall()
        self.approval_handler = approval_handler
        self.auto_approve_safe_commands = auto_approve_safe_commands
        self.default_timeout_seconds = default_timeout_seconds
        self.max_timeout_seconds = max_timeout_seconds

    def execute(
        self,
        command: list[str] | str,
        cwd: str | Path | None = None,
        timeout: float | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> TerminalResult:
        """Evaluate policy and safely execute a terminal command."""
        # Normalize argv
        if isinstance(command, str):
            cmd_argv = shlex.split(command, posix=os.name != "nt")
            cmd_str = command
        else:
            cmd_argv = list(command)
            cmd_str = " ".join(cmd_argv)

        if not cmd_argv:
            msg = "Empty command supplied to terminal driver."
            raise ValueError(msg)

        # Validate working directory within workspace bounds
        target_cwd = self.explorer.resolve_safe_path(cwd or self.explorer.repo_root)
        if not target_cwd.is_dir():
            msg = f"Working directory does not exist: {target_cwd}"
            raise NotADirectoryError(msg)

        # Action Firewall evaluation
        act_id = f"act_{uuid.uuid4().hex[:12]}"
        action = ComputerAction(
            action_id=act_id,
            task_id="task_coding",
            session_id="session_coding",
            action_type="terminal.execute",
            target=ActionTarget(strategy="command", value=cmd_argv[0]),
            parameters={
                "command": cmd_str,
                "argv": cmd_argv,
                "cwd": str(target_cwd),
            },
            idempotency_key=act_id,
        )
        decision = self.firewall.evaluate(action)

        if decision.decision == PolicyDecisionType.DENY:
            from atlas_coding.file_ops import PolicyAuthorizationError

            msg = f"Terminal command denied by firewall: {decision.reason}"
            raise PolicyAuthorizationError(msg)

        if decision.decision == PolicyDecisionType.REQUIRE_APPROVAL:
            if not self.auto_approve_safe_commands:
                if not (self.approval_handler and self.approval_handler(action)):
                    from atlas_coding.file_ops import PolicyAuthorizationError

                    msg = f"Terminal command requires explicit human approval: {decision.reason}"
                    raise PolicyAuthorizationError(msg)

        # Prepare execution environment
        exec_timeout = min(timeout or self.default_timeout_seconds, self.max_timeout_seconds)
        merged_env = os.environ.copy()
        if env_vars:
            merged_env.update(env_vars)

        start_time = time.monotonic()
        timed_out = False

        try:
            # Safe process execution: shell=False prevents shell injection
            proc = subprocess.run(
                cmd_argv,
                cwd=str(target_cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=exec_timeout,
                env=merged_env,
                shell=False,
            )
            stdout = redact_secrets(proc.stdout)
            stderr = redact_secrets(proc.stderr)
            exit_code = proc.returncode

        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = redact_secrets(exc.stdout or "" if isinstance(exc.stdout, str) else "")
            stderr = redact_secrets(
                exc.stderr or f"Command timed out after {exec_timeout} seconds."
            )
            exit_code = 124

        except Exception as exc:
            stdout = ""
            stderr = f"Execution error: {exc}"
            exit_code = 1

        duration = time.monotonic() - start_time

        return TerminalResult(
            command=cmd_argv,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=round(duration, 3),
            timed_out=timed_out,
            cwd=str(target_cwd),
        )
