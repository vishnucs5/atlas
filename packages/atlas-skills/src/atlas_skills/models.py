"""Pydantic contracts and schemas for the ATLAS Skill SDK."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SkillCapability(StrEnum):
    """Capability domains provided by specialist skills."""

    RESEARCH = "RESEARCH"
    CODE = "CODE"
    QUALITY_ASSURANCE = "QUALITY_ASSURANCE"
    BROWSER = "BROWSER"
    DESKTOP = "DESKTOP"
    DATA_ANALYSIS = "DATA_ANALYSIS"
    SECURITY_AUDIT = "SECURITY_AUDIT"
    TEXT_PROCESSING = "TEXT_PROCESSING"
    CUSTOM = "CUSTOM"


class SkillParameter(BaseModel):
    """Specification of a typed input or output parameter for a skill."""

    model_config = ConfigDict(validate_assignment=True)

    name: str
    type_name: str = "string"  # e.g. "string", "integer", "float", "boolean", "list", "dict"
    description: str = ""
    required: bool = True
    default_value: Any = None


class SkillManifest(BaseModel):
    """Formal metadata, interface declarations, and permissions for a skill."""

    model_config = ConfigDict(validate_assignment=True)

    skill_id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    capabilities: list[SkillCapability] = Field(default_factory=list)
    inputs: dict[str, SkillParameter] = Field(default_factory=dict)
    outputs: dict[str, SkillParameter] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    timeout_seconds: float = 60.0


class SkillResult(BaseModel):
    """Structured execution output produced by a skill invocation."""

    model_config = ConfigDict(validate_assignment=True)

    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    execution_time_ms: float = 0.0
    logs: list[str] = Field(default_factory=list)
