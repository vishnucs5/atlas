"""ATLAS Workflow Marketplace & Package System."""

from atlas_marketplace.executor import (
    PermissionDeniedError,
    WorkflowExecutionError,
    WorkflowExecutionResult,
    WorkflowExecutor,
)
from atlas_marketplace.models import (
    PackageDependency,
    PackageManifest,
    PackageType,
    PermissionDeclaration,
    PermissionScope,
    PublisherIdentity,
    ResourceLimits,
    RetryPolicy,
    WorkflowGraphDefinition,
    WorkflowNodeDefinition,
    WorkflowPackage,
)
from atlas_marketplace.package import (
    PackageIntegrityError,
    PackageSignatureError,
    PackageValidationError,
    build_package_archive,
    calculate_sha256,
    sign_payload,
    unpack_and_validate_package,
    validate_workflow_dag_cycles,
    verify_payload_signature,
)
from atlas_marketplace.registry import (
    InstallationRecord,
    MarketplaceRegistry,
    PackageRecord,
    PackageStatus,
)
from atlas_marketplace.resolver import (
    CircularDependencyError,
    DependencyResolutionError,
    DependencyResolver,
    IncompatibleDependencyError,
    matches_constraint,
    parse_semver,
)
from atlas_marketplace.security import (
    PackageSecurityScanner,
    PrivilegeEscalationError,
    SecurityViolationError,
    UntrustedInstructionError,
)

__version__ = "0.1.0"

__all__ = [
    "CircularDependencyError",
    "DependencyResolutionError",
    "DependencyResolver",
    "IncompatibleDependencyError",
    "InstallationRecord",
    "MarketplaceRegistry",
    "PackageDependency",
    "PackageIntegrityError",
    "PackageManifest",
    "PackageRecord",
    "PackageSecurityScanner",
    "PackageSignatureError",
    "PackageStatus",
    "PackageType",
    "PackageValidationError",
    "PermissionDeclaration",
    "PermissionDeniedError",
    "PermissionScope",
    "PrivilegeEscalationError",
    "PublisherIdentity",
    "ResourceLimits",
    "RetryPolicy",
    "SecurityViolationError",
    "UntrustedInstructionError",
    "WorkflowExecutionError",
    "WorkflowExecutionResult",
    "WorkflowExecutor",
    "WorkflowGraphDefinition",
    "WorkflowNodeDefinition",
    "WorkflowPackage",
    "build_package_archive",
    "calculate_sha256",
    "matches_constraint",
    "parse_semver",
    "sign_payload",
    "unpack_and_validate_package",
    "validate_workflow_dag_cycles",
    "verify_payload_signature",
]
