"""ComputerAction and ActionResult domain contracts."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionTarget(BaseModel):
    """Specification of target UI/DOM/system element for an action."""

    model_config = ConfigDict(validate_assignment=True)

    strategy: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExpectedState(BaseModel):
    """Deterministic post-condition expectation for action verification."""

    model_config = ConfigDict(validate_assignment=True)

    condition: str
    target: str
    value: Any | None = None
    timeout_ms: int = 5000


class ComputerAction(BaseModel):
    """Structured, versioned representation of an action proposal."""

    model_config = ConfigDict(validate_assignment=True)

    action_id: str
    task_id: str
    session_id: str
    action_type: str
    target: ActionTarget | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_state: ExpectedState | None = None
    idempotency_key: str
    timeout_ms: int = 10000
    schema_version: str = "1.0"


class ActionResult(BaseModel):
    """Deterministic execution outcome of a ComputerAction."""

    model_config = ConfigDict(validate_assignment=True)

    action_id: str
    success: bool
    output: Any | None = None
    error: str | None = None
    duration_ms: int
    evidence: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"
