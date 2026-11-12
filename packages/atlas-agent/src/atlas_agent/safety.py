"""Safety bounding, loop detection, and budget limit enforcement."""

import hashlib
import json
from typing import Any


class ActionLoopDetectedError(Exception):
    """Raised when the agent attempts repeated duplicate actions without state progression."""


class BudgetExhaustedError(Exception):
    """Raised when an execution ceiling (steps, tokens, cost, or timeout) is exceeded."""


class SafetyEngine:
    """Enforces execution boundaries, action idempotency, and budget limits."""

    def __init__(self, consecutive_duplicate_threshold: int = 3) -> None:
        self.threshold = consecutive_duplicate_threshold
        self._action_history: list[str] = []

    def compute_action_hash(self, action_name: str, target: Any, parameters: dict[str, Any]) -> str:
        """Compute a canonical SHA-256 hash of an action proposal."""
        normalized_target = str(target)
        try:
            normalized_params = json.dumps(parameters, sort_keys=True)
        except Exception:
            normalized_params = str(parameters)

        canonical = f"{action_name}::{normalized_target}::{normalized_params}"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def check_and_record_action(
        self, action_name: str, target: Any, parameters: dict[str, Any]
    ) -> None:
        """Verify proposed action does not exceed consecutive duplicate threshold, then record."""
        action_hash = self.compute_action_hash(action_name, target, parameters)

        # Check trailing consecutive identical actions
        consecutive = 0
        for prev_hash in reversed(self._action_history):
            if prev_hash == action_hash:
                consecutive += 1
            else:
                break

        if consecutive + 1 >= self.threshold:
            raise ActionLoopDetectedError(
                f"Action loop detected: action '{action_name}' with parameters {parameters} "
                f"was proposed {consecutive + 1} times consecutively without progress."
            )

        self._action_history.append(action_hash)

    def check_budget(
        self,
        current_step: int,
        max_steps: int,
        total_tokens: int,
        max_tokens: int,
        total_cost: float,
        max_cost: float,
        elapsed_seconds: float,
        timeout_seconds: float,
    ) -> None:
        """Enforce ceilings across step count, token usage, cost, and time."""
        if current_step > max_steps:
            raise BudgetExhaustedError(
                f"Step limit exceeded: {current_step} > {max_steps} allowed steps"
            )

        if total_tokens > max_tokens:
            raise BudgetExhaustedError(
                f"Token budget exceeded: {total_tokens} > {max_tokens} allowed tokens"
            )

        if total_cost > max_cost:
            raise BudgetExhaustedError(
                f"Cost budget exceeded: ${total_cost:.4f} > ${max_cost:.4f} allowed cost"
            )

        if elapsed_seconds > timeout_seconds:
            raise BudgetExhaustedError(
                f"Timeout exceeded: {elapsed_seconds:.1f}s > {timeout_seconds:.1f}s limit"
            )
