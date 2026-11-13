"""Marketplace REST API routes for workflow and skill discovery, publishing, installation, and execution."""

import base64
import logging
from typing import Annotated, Any

from atlas_core.contracts.agent import AgentCapability
from atlas_marketplace.executor import (
    PermissionDeniedError,
    WorkflowExecutionError,
    WorkflowExecutionResult,
    WorkflowExecutor,
)
from atlas_marketplace.models import (
    PackageType,
    PublisherIdentity,
)
from atlas_marketplace.package import (
    PackageIntegrityError,
    PackageSignatureError,
    PackageValidationError,
)
from atlas_marketplace.registry import (
    InstallationRecord,
    MarketplaceRegistry,
    PackageRecord,
)
from atlas_marketplace.security import (
    PackageSecurityScanner,
    PrivilegeEscalationError,
    SecurityViolationError,
    UntrustedInstructionError,
)
from atlas_orchestration.supervisor import ReviewRejectionError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from atlas_api.auth import AuthenticatedUser, Role, require_role

logger = logging.getLogger("atlas.api.marketplace")
router = APIRouter(prefix="/api/v1/marketplace", tags=["Workflow Marketplace"])


class PublishPackagePayload(BaseModel):
    """Payload containing package manifest or base64-encoded package archive and metadata."""

    archive_base64: str | None = None
    manifest: dict[str, Any] | None = None
    workflow: dict[str, Any] | None = None
    is_org_private: bool = False
    signing_key: str | None = None


class SecurityScanPayload(BaseModel):
    """Payload for pre-installation or registry security scanning."""

    package_id: str | None = None
    manifest: dict[str, Any] | None = None
    source_code: str | None = None


class InstallPackagePayload(BaseModel):
    """Payload to install a package with SemVer constraint."""

    version_constraint: str = "*"


class ExecuteWorkflowPayload(BaseModel):
    """Payload to execute an installed or published workflow package."""

    version: str | None = None
    task_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    max_parallel: int = 4
    enforce_review: bool = True


class PackageSearchResult(BaseModel):
    """Search response wrapper containing packages and total count."""

    packages: list[PackageRecord]
    total_count: int
    page: int
    page_size: int


def _get_registry(request: Request) -> MarketplaceRegistry:
    """Retrieve or lazily initialize the MarketplaceRegistry singleton on app state."""
    registry = getattr(request.app.state, "marketplace_registry", None)
    if not registry:
        registry = MarketplaceRegistry()
        request.app.state.marketplace_registry = registry
    return registry


def _get_executor(request: Request) -> WorkflowExecutor:
    """Retrieve or lazily initialize the WorkflowExecutor on app state."""
    executor = getattr(request.app.state, "marketplace_executor", None)
    if not executor:
        from atlas_api.routes.orchestration import _get_supervisor

        registry = _get_registry(request)
        supervisor = _get_supervisor(request)
        executor = WorkflowExecutor(registry=registry, supervisor=supervisor)
        request.app.state.marketplace_executor = executor
    return executor


def _get_scanner(request: Request) -> PackageSecurityScanner:
    """Retrieve or lazily initialize the PackageSecurityScanner on app state."""
    scanner = getattr(request.app.state, "marketplace_scanner", None)
    if not scanner:
        scanner = PackageSecurityScanner()
        request.app.state.marketplace_scanner = scanner
    return scanner


@router.get("/packages", response_model=PackageSearchResult)
async def search_packages(
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
    query: Annotated[str | None, Query(description="Search query string")] = None,
    package_type: Annotated[PackageType | None, Query(description="Filter by package type")] = None,
    capability: Annotated[AgentCapability | None, Query(description="Filter by capability")] = None,
    include_deprecated: Annotated[bool, Query(description="Include deprecated versions")] = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PackageSearchResult:
    """Search and discover packages in the marketplace with filters and pagination."""
    registry = _get_registry(request)
    packages, total = registry.search_packages(
        query=query,
        package_type=package_type,
        capability=capability,
        tenant_id="default",
        include_deprecated=include_deprecated,
        page=page,
        page_size=page_size,
    )
    return PackageSearchResult(
        packages=packages,
        total_count=total,
        page=page,
        page_size=page_size,
    )


@router.post("/packages", response_model=PackageRecord, status_code=status.HTTP_201_CREATED)
async def publish_package(
    payload: PublishPackagePayload,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
) -> PackageRecord:
    """Publish a validated and signed workflow or skill package to the registry."""
    registry = _get_registry(request)
    scanner = _get_scanner(request)

    if payload.archive_base64:
        try:
            archive_bytes = base64.b64decode(payload.archive_base64)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid base64 payload: {exc}",
            ) from exc
    elif payload.manifest:
        from atlas_marketplace.models import PackageManifest, WorkflowGraphDefinition
        from atlas_marketplace.package import build_package_archive

        try:
            manifest_obj = PackageManifest.model_validate(payload.manifest)
            wf_obj = (
                WorkflowGraphDefinition.model_validate(payload.workflow)
                if payload.workflow
                else None
            )
            key = payload.signing_key or manifest_obj.publisher.public_key
            archive_bytes = build_package_archive(
                manifest=manifest_obj,
                workflow=wf_obj,
                signing_key=key,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Failed to assemble package from manifest: {exc}",
            ) from exc
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either archive_base64 or manifest must be provided.",
        )

    # Unpack and security scan before publishing
    from atlas_marketplace.package import unpack_and_validate_package

    try:
        pkg = unpack_and_validate_package(
            archive_bytes=archive_bytes,
            signing_key=payload.signing_key,
            revoked_publishers=registry._revoked_publishers,
        )
        scanner.scan_package(pkg)
    except (
        PrivilegeEscalationError,
        UntrustedInstructionError,
        SecurityViolationError,
    ) as sec_err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Package failed security policy scan: {sec_err}",
        ) from sec_err
    except (PackageValidationError, PackageIntegrityError, PackageSignatureError) as pkg_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Package validation failure: {pkg_err}",
        ) from pkg_err

    # Store in registry
    record = registry.publish_package(
        package_archive=archive_bytes,
        signing_key=payload.signing_key,
        is_org_private=payload.is_org_private,
        tenant_id="default",
    )
    return record


@router.get("/packages/{package_id}", response_model=PackageRecord)
async def get_package_detail(
    package_id: str,
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
    version: Annotated[str | None, Query(description="Specific SemVer version")] = None,
) -> PackageRecord:
    """Retrieve detailed package information, manifest, and latest active version."""
    registry = _get_registry(request)
    record = registry.get_package(package_id, version=version, tenant_id="default")
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Package '{package_id}' not found.",
        )
    return record


@router.get("/packages/{package_id}/versions", response_model=list[PackageRecord])
async def list_package_versions(
    package_id: str,
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
) -> list[PackageRecord]:
    """List all available versions and lifecycle states for a package."""
    registry = _get_registry(request)
    versions = registry.list_package_versions(package_id, tenant_id="default")
    if not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Package '{package_id}' not found.",
        )
    return versions


@router.post("/packages/{package_id}/install", response_model=list[InstallationRecord])
async def install_package(
    package_id: str,
    payload: InstallPackagePayload,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
) -> list[InstallationRecord]:
    """Resolve transitive dependencies and install package and prerequisites into workspace."""
    registry = _get_registry(request)
    try:
        installed = registry.install_package(
            package_id=package_id,
            version_constraint=payload.version_constraint,
            tenant_id="default",
            installed_by=user.user_id,
        )
        return installed
    except KeyError as k_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(k_err),
        ) from k_err
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Installation failed: {exc}",
        ) from exc


@router.post("/packages/{package_id}/rollback", response_model=InstallationRecord)
async def rollback_package(
    package_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
) -> InstallationRecord:
    """Roll back an installed package to its previous installed version."""
    registry = _get_registry(request)
    try:
        return registry.rollback_package(package_id, tenant_id="default")
    except KeyError as k_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(k_err),
        ) from k_err
    except ValueError as v_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(v_err),
        ) from v_err


@router.post("/packages/{package_id}/uninstall", response_model=dict[str, Any])
async def uninstall_package(
    package_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
) -> dict[str, Any]:
    """Uninstall a package from the workspace."""
    registry = _get_registry(request)
    success = registry.uninstall_package(package_id, tenant_id="default")
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Package '{package_id}' is not installed.",
        )
    return {"status": "uninstalled", "package_id": package_id}


@router.get("/skills")
async def list_skills(
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
) -> dict[str, Any]:
    """List all specialist skills, including built-in and installed specialist skills."""
    registry = _get_registry(request)
    builtins = [
        {
            "skill_id": "com.atlas.skill.linter",
            "name": "Code Linter Skill",
            "version": "1.0.0",
            "capabilities": ["CODE_GENERATION"],
            "timeout_seconds": 30,
        },
        {
            "skill_id": "com.atlas.skill.analysis",
            "name": "Data Analysis Skill",
            "version": "1.0.0",
            "capabilities": ["DATA_ANALYSIS"],
            "timeout_seconds": 60,
        },
        {
            "skill_id": "com.atlas.skill.summary",
            "name": "Text Summarizer Skill",
            "version": "1.0.0",
            "capabilities": ["RESEARCH"],
            "timeout_seconds": 30,
        },
    ]
    skills_pkgs, _ = registry.search_packages(package_type=PackageType.SKILL, tenant_id="default")
    pkg_skills = [
        {
            "skill_id": p.package_id,
            "name": p.name,
            "version": p.version,
            "capabilities": [
                c.value if hasattr(c, "value") else str(c) for c in p.required_capabilities
            ],
            "timeout_seconds": 60,
        }
        for p in skills_pkgs
    ]
    return {"skills": builtins + pkg_skills}


@router.post("/security/scan")
async def scan_package_security(
    payload: SecurityScanPayload,
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
) -> dict[str, Any]:
    """Perform security scanning for privilege escalation, prompt injection, and forbidden syscalls."""
    scanner = _get_scanner(request)
    registry = _get_registry(request)
    violations = []

    if payload.source_code:
        try:
            scanner.scan_skill_source_code(payload.source_code)
        except SecurityViolationError as err:
            violations.append(str(err))

    if payload.manifest:
        try:
            from atlas_marketplace.models import PackageManifest

            m = PackageManifest.model_validate(payload.manifest)
            scanner.scan_manifest(m)
        except Exception as err:
            violations.append(str(err))

    if payload.package_id:
        record = registry.get_package(payload.package_id, tenant_id="default")
        if record:
            try:
                scanner.scan_manifest(record.manifest)
            except Exception as err:
                violations.append(str(err))

    is_safe = len(violations) == 0
    return {
        "safe": is_safe,
        "risk_score": 0.0 if is_safe else 0.85,
        "violations": violations,
    }


@router.get("/installations", response_model=list[InstallationRecord])
@router.get("/installed", response_model=list[InstallationRecord])
async def list_installed_packages(
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
) -> list[InstallationRecord]:
    """List all currently installed packages for the workspace."""
    registry = _get_registry(request)
    return registry.list_installed(tenant_id="default")


@router.post("/workflows/{package_id}/execute", response_model=WorkflowExecutionResult)
async def execute_workflow(
    package_id: str,
    payload: ExecuteWorkflowPayload,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN, Role.OPERATOR))],
) -> WorkflowExecutionResult:
    """Execute a marketplace workflow package through the canonical ATLAS multi-agent runtime."""
    executor = _get_executor(request)
    try:
        result = await executor.execute_workflow(
            package_id=package_id,
            version=payload.version,
            tenant_id="default",
            task_id=payload.task_id,
            inputs=payload.inputs,
            max_parallel=payload.max_parallel,
            enforce_review=payload.enforce_review,
        )
        return result
    except KeyError as k_err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(k_err),
        ) from k_err
    except PermissionDeniedError as p_err:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: {p_err}",
        ) from p_err
    except ReviewRejectionError as rev_err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Deliverables rejected by Independent Reviewer: {rev_err}",
        ) from rev_err
    except WorkflowExecutionError as exec_err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exec_err),
        ) from exec_err


@router.get("/publishers/{publisher_id}", response_model=PublisherIdentity)
async def get_publisher(
    publisher_id: str,
    request: Request,
    user: Annotated[
        AuthenticatedUser,
        Depends(require_role(Role.ADMIN, Role.OPERATOR, Role.WORKER, Role.VIEWER)),
    ],
) -> PublisherIdentity:
    """Retrieve publisher profile, verified identity, and public signing key."""
    registry = _get_registry(request)
    publisher = registry._publishers.get(publisher_id)
    if not publisher:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Publisher '{publisher_id}' not found.",
        )
    return publisher


@router.post("/publishers/{publisher_id}/revoke", response_model=dict[str, Any])
async def revoke_publisher(
    publisher_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(require_role(Role.ADMIN))],
) -> dict[str, Any]:
    """Revoke a publisher's credentials across the registry (Admin only)."""
    registry = _get_registry(request)
    registry.revoke_publisher(publisher_id)
    return {
        "status": "revoked",
        "publisher_id": publisher_id,
        "message": f"Publisher '{publisher_id}' credentials successfully revoked.",
    }
