"""Model interaction, message, tool, and capability contracts."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TextPart(BaseModel):
    """Textual content part for multimodal model messages."""

    model_config = ConfigDict(validate_assignment=True)

    type: Literal["text"] = "text"
    text: str
    schema_version: str = "1.0"


class ImagePart(BaseModel):
    """Image content part for multimodal model messages."""

    model_config = ConfigDict(validate_assignment=True)

    type: Literal["image"] = "image"
    media_type: str = "image/png"
    data: str | None = None  # Base64 encoded string
    url: str | None = None
    detail: Literal["auto", "low", "high"] = "auto"
    schema_version: str = "1.0"


ContentPart = Annotated[TextPart | ImagePart, Field(discriminator="type")]


class ModelMessage(BaseModel):
    """Role-based chat message exchanged with model providers."""

    model_config = ConfigDict(validate_assignment=True)

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[ContentPart] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"

    def __getitem__(self, item: str) -> Any:
        try:
            return getattr(self, item)
        except AttributeError:
            raise KeyError(item) from None

    def __contains__(self, item: object) -> bool:
        return hasattr(self, str(item))

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


class ToolDefinition(BaseModel):
    """Declaration of a callable tool / function schema for models."""

    model_config = ConfigDict(validate_assignment=True)

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"

    def __getitem__(self, item: str) -> Any:
        try:
            return getattr(self, item)
        except AttributeError:
            raise KeyError(item) from None

    def __contains__(self, item: object) -> bool:
        return hasattr(self, str(item))

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


class ToolCall(BaseModel):
    """Invocation request emitted by a model targeting a declared tool."""

    model_config = ConfigDict(validate_assignment=True)

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    type: str = "function"
    schema_version: str = "1.0"

    def __getitem__(self, item: str) -> Any:
        try:
            return getattr(self, item)
        except AttributeError:
            raise KeyError(item) from None

    def __contains__(self, item: object) -> bool:
        return hasattr(self, str(item))

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


class TokenUsage(BaseModel):
    """Quantified token metrics and cost accounting for model invocations."""

    model_config = ConfigDict(validate_assignment=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    estimated_cost_usd: float = 0.0
    schema_version: str = "1.0"

    def __getitem__(self, item: str) -> Any:
        try:
            return getattr(self, item)
        except AttributeError:
            raise KeyError(item) from None

    def __contains__(self, item: object) -> bool:
        return hasattr(self, str(item))

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


class ProviderHealth(BaseModel):
    """Diagnostic health state of a model provider or endpoint."""

    model_config = ConfigDict(validate_assignment=True)

    status: Literal["HEALTHY", "DEGRADED", "UNAVAILABLE"] = "HEALTHY"
    provider_id: str
    model_name: str | None = None
    latency_ms: int = 0
    error: str | None = None
    last_checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = "1.0"


class ModelError(BaseModel):
    """Normalized error envelope returned when a model invocation fails."""

    model_config = ConfigDict(validate_assignment=True)

    error_type: Literal[
        "RATE_LIMIT",
        "CONTEXT_LENGTH_EXCEEDED",
        "AUTHENTICATION",
        "INVALID_REQUEST",
        "SERVER_ERROR",
        "TIMEOUT",
        "UNKNOWN",
    ]
    message: str
    provider: str | None = None
    status_code: int | None = None
    retryable: bool = False
    raw_error: dict[str, Any] | None = None
    schema_version: str = "1.0"


class ModelCapabilities(BaseModel):
    """Declared capabilities, limits, and pricing of an AI model adapter."""

    model_config = ConfigDict(validate_assignment=True)

    model_name: str | None = None
    provider: str | None = None
    vision: bool = True
    tool_calling: bool = True
    structured_output: bool = True
    streaming: bool = True
    context_window: int = 128000
    max_output_tokens: int = 4096
    supported_modalities: list[str] = Field(default_factory=lambda: ["text", "image"])
    cost_per_1k_input_tokens: float = 0.0
    cost_per_1k_output_tokens: float = 0.0
    schema_version: str = "1.0"


class ModelRequest(BaseModel):
    """Standardized request envelope passed to model adapters."""

    model_config = ConfigDict(validate_assignment=True)

    request_id: str
    task_id: str
    model_name: str
    messages: list[ModelMessage | dict[str, Any]] = Field(default_factory=list)
    tools: list[ToolDefinition | dict[str, Any]] = Field(default_factory=list)
    system_prompt: str | None = None
    temperature: float = 0.0
    max_tokens: int | None = None
    stop_sequences: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"


class ModelResponse(BaseModel):
    """Standardized response envelope returned by model adapters."""

    model_config = ConfigDict(validate_assignment=True)

    response_id: str
    request_id: str
    model_name: str
    content: str | None = None
    tool_calls: list[ToolCall | dict[str, Any]] = Field(default_factory=list)
    raw_finish_reason: str | None = None
    usage: TokenUsage | dict[str, Any] = Field(default_factory=TokenUsage)
    latency_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"
