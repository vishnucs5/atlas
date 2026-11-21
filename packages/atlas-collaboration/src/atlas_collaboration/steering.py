"""Active Human Steering & Mid-Flight Workflow Intervention Controller."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from atlas_collaboration.models import SteeringEvent


class WorkflowNotPausedError(RuntimeError):
    """Raised when steering parameters are injected into a workflow that is not paused."""


class SteeringController:
    """Coordinates operator pause, parameter injection, and child idempotency key derivation."""

    def __init__(self) -> None:
        self._paused_instances: dict[str, dict[str, Any]] = {}
        self._steering_history: list[SteeringEvent] = []

    def pause_workflow(
        self,
        process_instance_id: str,
        task_instance_id: str,
        operator_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """Pause in-flight execution for human operator steering."""
        pause_record = {
            "process_instance_id": process_instance_id,
            "task_instance_id": task_instance_id,
            "operator_id": operator_id,
            "reason": reason,
            "status": "PAUSED_FOR_STEERING",
        }
        self._paused_instances[process_instance_id] = pause_record
        return pause_record

    def is_paused(self, process_instance_id: str) -> bool:
        return process_instance_id in self._paused_instances

    @staticmethod
    def derive_child_idempotency_key(
        parent_key: str,
        steering_id: str,
        modified_params: dict[str, Any],
    ) -> str:
        """Mathematically derive child idempotency key preventing accidental parent replay.

        Formula:
            key_child = SHA-256(key_parent || steering_id || SHA-256(canonical_json(modified_params)))
        """
        canonical_params = json.dumps(modified_params, sort_keys=True)
        param_hash = hashlib.sha256(canonical_params.encode("utf-8")).hexdigest()
        compound = f"{parent_key}:{steering_id}:{param_hash}"
        return hashlib.sha256(compound.encode("utf-8")).hexdigest()

    def inject_and_resume(
        self,
        process_instance_id: str,
        task_instance_id: str,
        operator_id: str,
        parent_operation_key: str,
        original_parameters: dict[str, Any],
        modified_parameters: dict[str, Any],
        reason: str,
    ) -> tuple[str, SteeringEvent]:
        """Inject modified parameters, derive child key, and resume workflow execution."""
        if not self.is_paused(process_instance_id):
            raise WorkflowNotPausedError(
                f"Process instance '{process_instance_id}' is not paused for steering."
            )

        steering_id = f"steer_{uuid.uuid4().hex[:10]}"
        child_key = self.derive_child_idempotency_key(
            parent_key=parent_operation_key,
            steering_id=steering_id,
            modified_params=modified_parameters,
        )

        event = SteeringEvent(
            steering_id=steering_id,
            process_instance_id=process_instance_id,
            task_instance_id=task_instance_id,
            operator_id=operator_id,
            parent_operation_key=parent_operation_key,
            child_operation_key=child_key,
            original_parameters=original_parameters,
            modified_parameters=modified_parameters,
            reason=reason,
        )

        self._steering_history.append(event)
        del self._paused_instances[process_instance_id]
        return child_key, event

    def list_steering_history(self, process_instance_id: str | None = None) -> list[SteeringEvent]:
        if process_instance_id:
            return [
                e for e in self._steering_history if e.process_instance_id == process_instance_id
            ]
        return list(self._steering_history)
