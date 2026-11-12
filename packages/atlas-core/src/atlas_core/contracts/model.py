"""Model interaction and capability contracts."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ModelCapabilities(BaseModel):
    """Declared capabilities and constraints of an AI model adapter."""

    model_config = ConfigDict(validate_assignment=True)

    model_name: str | None = None
    vision: bool = True
    tool_calling: bool = True
    streaming: bool = True
    context_window: int = 128000
    supported_modalities: list[str] = Field(default_factory=lambda: ["text", "image"])
    schema_version: str = "1.0"


class ModelRequest(BaseModel):
    """Standardized request envelope passed to model adapters."""

    model_config = ConfigDict(validate_assignment=True)

    request_id: str
    task_id: str
    model_name: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    temperature: float = 0.0
    max_tokens: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"


class ModelResponse(BaseModel):
    """Standardized response envelope returned by model adapters."""

    model_config = ConfigDict(validate_assignment=True)

    response_id: str
    request_id: str
    model_name: str
    content: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    raw_finish_reason: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    latency_ms: int = 0
    schema_version: str = "1.0"
