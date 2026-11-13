"""BaseSkill interface, SkillContext sandbox, and lifecycle hook orchestration."""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from atlas_skills.models import SkillManifest, SkillResult

logger = logging.getLogger("atlas.skills")


class SkillError(Exception):
    """Base exception for all skill framework errors."""


class SkillExecutionError(SkillError):
    """Raised when an error occurs during skill execution."""


class SkillCancellationError(SkillError):
    """Raised when skill execution is aborted due to task cancellation."""


class SkillInputValidationError(SkillError):
    """Raised when provided inputs violate the skill manifest specification."""


class SkillLogger:
    """Scoped in-memory and logging adapter for a running skill invocation."""

    def __init__(self, skill_id: str, task_id: str) -> None:
        self.skill_id = skill_id
        self.task_id = task_id
        self.records: list[str] = []

    def info(self, msg: str, *args: Any) -> None:
        formatted = msg % args if args else msg
        entry = f"[{datetime.now(UTC).strftime('%H:%M:%S.%f')[:-3]}] [INFO] [{self.skill_id}] {formatted}"
        self.records.append(entry)
        logger.info(entry)

    def warning(self, msg: str, *args: Any) -> None:
        formatted = msg % args if args else msg
        entry = f"[{datetime.now(UTC).strftime('%H:%M:%S.%f')[:-3]}] [WARN] [{self.skill_id}] {formatted}"
        self.records.append(entry)
        logger.warning(entry)

    def error(self, msg: str, *args: Any) -> None:
        formatted = msg % args if args else msg
        entry = f"[{datetime.now(UTC).strftime('%H:%M:%S.%f')[:-3]}] [ERROR] [{self.skill_id}] {formatted}"
        self.records.append(entry)
        logger.error(entry)


class SkillContext:
    """Isolated execution boundary provided to a skill invocation."""

    def __init__(
        self,
        task_id: str,
        agent_id: str = "specialist_agent",
        session_id: str = "sess_default",
        memory: dict[str, Any] | None = None,
    ) -> None:
        self.task_id = task_id
        self.agent_id = agent_id
        self.session_id = session_id
        self.memory = memory if memory is not None else {}
        self.logger = SkillLogger("skill", task_id)
        self.is_cancelled = False

    def cancel(self) -> None:
        """Mark this context as cancelled."""
        self.is_cancelled = True

    def check_cancellation(self) -> None:
        """Raise SkillCancellationError if cancellation has been flagged."""
        if self.is_cancelled:
            raise SkillCancellationError(f"Skill execution cancelled for task '{self.task_id}'.")


class BaseSkill(ABC):
    """Abstract base class that all ATLAS specialist skills must inherit from."""

    def __init__(self, manifest: SkillManifest) -> None:
        self.manifest = manifest
        self._is_loaded = False

    async def on_load(self, context: SkillContext) -> None:
        """Lifecycle hook invoked once when the skill is loaded into memory."""
        self._is_loaded = True

    async def on_unload(self, context: SkillContext) -> None:
        """Lifecycle hook invoked when the skill is evicted or unloaded."""
        self._is_loaded = False

    @abstractmethod
    async def execute(self, context: SkillContext, **inputs: Any) -> dict[str, Any]:
        """Execute core skill logic. Subclasses must implement this method."""

    def validate_inputs(self, **inputs: Any) -> dict[str, Any]:
        """Validate input parameters against the declared manifest schema."""
        validated: dict[str, Any] = {}
        for param_name, param_spec in self.manifest.inputs.items():
            if param_name in inputs:
                validated[param_name] = inputs[param_name]
            elif param_spec.required:
                raise SkillInputValidationError(
                    f"Missing required parameter '{param_name}' for skill '{self.manifest.skill_id}'."
                )
            else:
                validated[param_name] = param_spec.default_value
        return validated

    async def run(self, context: SkillContext, **inputs: Any) -> SkillResult:
        """Safe execution wrapper handling lifecycle, input validation, timeouts, and metrics."""
        context.logger.skill_id = self.manifest.skill_id
        start_time = time.perf_counter()

        try:
            context.check_cancellation()

            # Ensure on_load was called
            if not self._is_loaded:
                await self.on_load(context)

            # Input validation
            clean_inputs = self.validate_inputs(**inputs)

            # Execution with timeout
            output = await asyncio.wait_for(
                self.execute(context, **clean_inputs),
                timeout=self.manifest.timeout_seconds,
            )

            context.check_cancellation()
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            return SkillResult(
                success=True,
                output=output,
                execution_time_ms=elapsed_ms,
                logs=context.logger.records,
            )

        except TimeoutError:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            err_msg = f"Skill execution timed out after {self.manifest.timeout_seconds}s"
            context.logger.error(err_msg)
            return SkillResult(
                success=False,
                error=err_msg,
                execution_time_ms=elapsed_ms,
                logs=context.logger.records,
            )

        except SkillCancellationError as c_err:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            context.logger.warning(f"Skill execution aborted: {c_err}")
            return SkillResult(
                success=False,
                error=str(c_err),
                execution_time_ms=elapsed_ms,
                logs=context.logger.records,
            )

        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            context.logger.error(f"Skill execution failed: {exc}")
            return SkillResult(
                success=False,
                error=str(exc),
                execution_time_ms=elapsed_ms,
                logs=context.logger.records,
            )
