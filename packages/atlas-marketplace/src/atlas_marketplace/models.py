"""Pydantic data models for ATLAS Workflow Packages, Manifests, and Permissions."""

import re
from enum import StrEnum
from typing import Any

from atlas_core.contracts.agent import AgentCapability
from atlas_core.contracts.graph import DependencyType
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PackageType(StrEnum):
    """Classification of an ATLAS marketplace package."""

    WORKFLOW = "WORKFLOW"
    SKILL = "SKILL"
    PLUGIN = "PLUGIN"


class PermissionScope(StrEnum):
    """Scope of system capability requested by a workflow or skill."""

    FILESYSTEM = "filesystem"
    NETWORK = "network"
    BROWSER = "browser"
    DESKTOP = "desktop"
    SYSTEM = "system"
    MODEL = "model"


class PermissionDeclaration(BaseModel):
    """Explicit declaration of required system access or driver capability."""

    model_config = ConfigDict(validate_assignment=True)

    scope: PermissionScope
    access: str  # e.g., "read", "read_write", "domain_allowlist", "execute"
    path_pattern: str | None = None
    domains: list[str] = Field(default_factory=list)
    justification: str | None = None


class ResourceLimits(BaseModel):
    """Enforced upper bounds on resource consumption for a package."""

    model_config = ConfigDict(validate_assignment=True)

    max_tokens: int = 100000
    max_steps: int = 50
    timeout_seconds: int = 1800


class PackageDependency(BaseModel):
    """Declared dependency on another marketplace package with SemVer constraint."""

    model_config = ConfigDict(validate_assignment=True)

    package_id: str
    version_constraint: str  # e.g. "^1.0.0", ">=1.2.0, <2.0.0"


class RetryPolicy(BaseModel):
    """Fault recovery and retry configuration."""

    model_config = ConfigDict(validate_assignment=True)

    max_retries: int = 3
    backoff_multiplier: float = 1.5
    retryable_errors: list[str] = Field(default_factory=list)


class PublisherIdentity(BaseModel):
    """Cryptographic and organizational identity of a package publisher."""

    model_config = ConfigDict(validate_assignment=True)

    publisher_id: str
    name: str
    email: str
    public_key: str
    is_trusted: bool = True
    verified_at: str | None = None


class WorkflowNodeDefinition(BaseModel):
    """Individual task node definition inside a package workflow DAG."""

    model_config = ConfigDict(validate_assignment=True)

    node_id: str
    name: str
    required_capability: AgentCapability
    parameters: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    dependency_type: DependencyType = DependencyType.HARD


class WorkflowGraphDefinition(BaseModel):
    """Specification of an executable dependency DAG in a workflow package."""

    model_config = ConfigDict(validate_assignment=True)

    graph_id: str
    nodes: list[WorkflowNodeDefinition] = Field(default_factory=list)


class PackageManifest(BaseModel):
    """Canonical, versioned specification describing an ATLAS package."""

    model_config = ConfigDict(validate_assignment=True)

    schema_version: str = "1.0"
    package_id: str
    package_type: PackageType
    name: str
    description: str
    version: str
    publisher: PublisherIdentity
    atlas_compatibility: str = ">=0.7.0, <1.0.0"
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    required_capabilities: list[AgentCapability] = Field(default_factory=list)
    permissions: list[PermissionDeclaration] = Field(default_factory=list)
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    dependencies: list[PackageDependency] = Field(default_factory=list)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    verification_criteria: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("package_id")
    @classmethod
    def validate_package_id(cls, v: str) -> str:
        pattern = r"^[a-z0-9][a-z0-9._-]{2,64}$"
        if not re.match(pattern, v):
            raise ValueError(
                f"Invalid package_id '{v}'. Must be lowercase alphanumeric, dots, hyphens, or underscores (3-65 chars)."
            )
        return v

    @field_validator("version")
    @classmethod
    def validate_semver(cls, v: str) -> str:
        # Standard SemVer: MAJOR.MINOR.PATCH(-PRERELEASE)?
        pattern = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
        if not re.match(pattern, v):
            raise ValueError(
                f"Invalid version string '{v}'. Must adhere to Semantic Versioning (e.g. '1.0.0')."
            )
        return v


class WorkflowPackage(BaseModel):
    """In-memory validated container for an unpacked workflow or skill package."""

    model_config = ConfigDict(validate_assignment=True)

    manifest: PackageManifest
    workflow: WorkflowGraphDefinition | None = None
    checksums: dict[str, str] = Field(default_factory=dict)
    signature: str | None = None
    archive_bytes: bytes | None = None
