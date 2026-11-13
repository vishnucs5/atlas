"""Marketplace Registry managing package publication, discovery, SemVer installation, and rollback."""

import threading
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from enum import StrEnum

from atlas_core.contracts.agent import AgentCapability
from pydantic import BaseModel, ConfigDict, Field

from atlas_marketplace.models import (
    PackageManifest,
    PackageType,
    PublisherIdentity,
    WorkflowPackage,
)
from atlas_marketplace.package import (
    PackageSignatureError,
    PackageValidationError,
    unpack_and_validate_package,
)
from atlas_marketplace.resolver import (
    DependencyResolver,
    parse_semver,
)


class PackageStatus(StrEnum):
    """Lifecycle status of a published package in the registry."""

    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    WITHDRAWN = "WITHDRAWN"


class PackageRecord(BaseModel):
    """Registry entry representing a published package version."""

    model_config = ConfigDict(validate_assignment=True)

    package_id: str
    version: str
    manifest: PackageManifest
    status: PackageStatus = PackageStatus.ACTIVE
    published_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    archive_bytes: bytes = Field(default=b"", exclude=True)
    download_count: int = 0
    tenant_id: str = "default"
    is_org_private: bool = False


class InstallationRecord(BaseModel):
    """Ledger entry tracking installed package state per workspace/tenant."""

    model_config = ConfigDict(validate_assignment=True)

    installation_id: str = Field(default_factory=lambda: f"inst_{uuid.uuid4().hex[:10]}")
    package_id: str
    version: str
    previous_version: str | None = None
    installed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    enabled: bool = True
    tenant_id: str = "default"
    installed_by: str = "admin"


class MarketplaceRegistry:
    """Thread-safe registry managing public and organizational packages, versioning, and installations."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # package_id -> {version_str: PackageRecord}
        self._packages: dict[str, dict[str, PackageRecord]] = defaultdict(dict)
        # publisher_id -> PublisherIdentity
        self._publishers: dict[str, PublisherIdentity] = {}
        # publisher_id -> is_revoked (bool)
        self._revoked_publishers: set[str] = set()
        # tenant_id -> {package_id: InstallationRecord}
        self._installations: dict[str, dict[str, InstallationRecord]] = defaultdict(dict)

    def register_publisher(self, publisher: PublisherIdentity) -> None:
        """Register an authorized package publisher with their public signing key."""
        with self._lock:
            self._publishers[publisher.publisher_id] = publisher

    def revoke_publisher(self, publisher_id: str) -> None:
        """Revoke a publisher's credentials; immediately blocks installation and verification."""
        with self._lock:
            self._revoked_publishers.add(publisher_id)

    def is_publisher_revoked(self, publisher_id: str) -> bool:
        """Check if publisher identity has been marked revoked."""
        with self._lock:
            return publisher_id in self._revoked_publishers

    def publish_package(
        self,
        package_archive: bytes,
        signing_key: str | None = None,
        is_org_private: bool = False,
        tenant_id: str = "default",
    ) -> PackageRecord:
        """Validate package archive and register it in the registry (idempotent)."""
        with self._lock:
            pkg: WorkflowPackage = unpack_and_validate_package(
                archive_bytes=package_archive,
                signing_key=signing_key,
                revoked_publishers=self._revoked_publishers,
            )

            manifest = pkg.manifest
            pkg_id = manifest.package_id
            ver = manifest.version

            # Check if publisher is registered / revoked
            if self.is_publisher_revoked(manifest.publisher.publisher_id):
                raise PackageSignatureError(
                    f"Publisher '{manifest.publisher.publisher_id}' is revoked."
                )

            # Store publisher if not already registered
            if manifest.publisher.publisher_id not in self._publishers:
                self.register_publisher(manifest.publisher)

            # Idempotent re-publishing: if version exists and is identical, return it
            existing = self._packages[pkg_id].get(ver)
            if existing:
                if existing.archive_bytes == package_archive:
                    return existing
                raise PackageValidationError(
                    f"Package '{pkg_id}' version '{ver}' already exists with different contents."
                )

            record = PackageRecord(
                package_id=pkg_id,
                version=ver,
                manifest=manifest,
                status=PackageStatus.ACTIVE,
                archive_bytes=package_archive,
                tenant_id=tenant_id,
                is_org_private=is_org_private,
            )
            self._packages[pkg_id][ver] = record
            return record

    def get_package(
        self,
        package_id: str,
        version: str | None = None,
        tenant_id: str = "default",
    ) -> PackageRecord | None:
        """Retrieve package record for a specific version or latest active version."""
        with self._lock:
            versions = self._packages.get(package_id, {})
            if not versions:
                return None

            # Filter visible packages (public or matching tenant)
            visible = {
                v: r
                for v, r in versions.items()
                if not r.is_org_private or r.tenant_id == tenant_id
            }
            if not visible:
                return None

            if version:
                return visible.get(version)

            # Find highest active SemVer
            active_records = [r for r in visible.values() if r.status != PackageStatus.WITHDRAWN]
            if not active_records:
                return None

            active_records.sort(key=lambda r: parse_semver(r.version), reverse=True)
            return active_records[0]

    def list_package_versions(
        self,
        package_id: str,
        tenant_id: str = "default",
    ) -> list[PackageRecord]:
        """List all published versions for a package."""
        with self._lock:
            versions = self._packages.get(package_id, {})
            records = [
                r for r in versions.values() if not r.is_org_private or r.tenant_id == tenant_id
            ]
            records.sort(key=lambda r: parse_semver(r.version), reverse=True)
            return records

    def search_packages(
        self,
        query: str | None = None,
        package_type: PackageType | None = None,
        capability: AgentCapability | None = None,
        tenant_id: str = "default",
        include_deprecated: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PackageRecord], int]:
        """Search and filter published packages with pagination."""
        with self._lock:
            matched_records: list[PackageRecord] = []
            for pkg_id, _versions in self._packages.items():
                latest = self.get_package(pkg_id, tenant_id=tenant_id)
                if not latest:
                    continue

                if not include_deprecated and latest.status == PackageStatus.DEPRECATED:
                    continue
                if latest.status == PackageStatus.WITHDRAWN:
                    continue

                if package_type and latest.manifest.package_type != package_type:
                    continue
                if capability and capability not in latest.manifest.required_capabilities:
                    continue

                if query:
                    q_lower = query.lower()
                    in_id = q_lower in latest.package_id.lower()
                    in_name = q_lower in latest.manifest.name.lower()
                    in_desc = q_lower in latest.manifest.description.lower()
                    in_tags = any(q_lower in t.lower() for t in latest.manifest.tags)
                    if not (in_id or in_name or in_desc or in_tags):
                        continue

                matched_records.append(latest)

            total_count = len(matched_records)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            return matched_records[start_idx:end_idx], total_count

    def deprecate_package(
        self,
        package_id: str,
        version: str,
        tenant_id: str = "default",
    ) -> None:
        """Mark a package version as DEPRECATED (visible with warning)."""
        with self._lock:
            record = self._packages.get(package_id, {}).get(version)
            if not record:
                raise KeyError(f"Package '{package_id}' version '{version}' not found.")
            if record.is_org_private and record.tenant_id != tenant_id:
                raise PermissionError("Unauthorized to modify package in another tenant.")
            record.status = PackageStatus.DEPRECATED

    def withdraw_package(
        self,
        package_id: str,
        version: str,
        tenant_id: str = "default",
    ) -> None:
        """Withdraw a package version completely (prevents new installations)."""
        with self._lock:
            record = self._packages.get(package_id, {}).get(version)
            if not record:
                raise KeyError(f"Package '{package_id}' version '{version}' not found.")
            if record.is_org_private and record.tenant_id != tenant_id:
                raise PermissionError("Unauthorized to modify package in another tenant.")
            record.status = PackageStatus.WITHDRAWN

    def install_package(
        self,
        package_id: str,
        version_constraint: str = "*",
        tenant_id: str = "default",
        installed_by: str = "admin",
    ) -> list[InstallationRecord]:
        """Resolve dependencies and install a package and its prerequisites atomically."""
        with self._lock:
            target_pkg = self.get_package(package_id, tenant_id=tenant_id)
            if not target_pkg or target_pkg.status == PackageStatus.WITHDRAWN:
                raise KeyError(f"Package '{package_id}' is not available for installation.")

            # Available packages index
            avail_index: dict[str, list[str]] = {}
            for pid, v_dict in self._packages.items():
                avail_index[pid] = [
                    v
                    for v, r in v_dict.items()
                    if r.status != PackageStatus.WITHDRAWN
                    and (not r.is_org_private or r.tenant_id == tenant_id)
                ]

            resolver = DependencyResolver(avail_index)

            def _get_deps(pid: str, v: str):
                rec = self._packages[pid][v]
                return rec.manifest.dependencies

            # Resolve transitive dependencies
            order = resolver.resolve(
                root_package_id=package_id,
                root_dependencies=target_pkg.manifest.dependencies,
                package_dependency_lookup=_get_deps,
            )

            installed_records: list[InstallationRecord] = []
            now = datetime.now(UTC)

            # Install dependencies in topological order
            for dep_id, dep_v in order:
                existing_inst = self._installations[tenant_id].get(dep_id)
                prev_v = existing_inst.version if existing_inst else None
                inst = InstallationRecord(
                    package_id=dep_id,
                    version=dep_v,
                    previous_version=prev_v,
                    installed_at=existing_inst.installed_at if existing_inst else now,
                    updated_at=now,
                    enabled=True,
                    tenant_id=tenant_id,
                    installed_by=installed_by,
                )
                self._installations[tenant_id][dep_id] = inst
                self._packages[dep_id][dep_v].download_count += 1
                installed_records.append(inst)

            # Install the root target package
            root_v = resolver.find_best_version(package_id, version_constraint)
            existing_root = self._installations[tenant_id].get(package_id)
            prev_root_v = existing_root.version if existing_root else None
            root_inst = InstallationRecord(
                package_id=package_id,
                version=root_v,
                previous_version=prev_root_v,
                installed_at=existing_root.installed_at if existing_root else now,
                updated_at=now,
                enabled=True,
                tenant_id=tenant_id,
                installed_by=installed_by,
            )
            self._installations[tenant_id][package_id] = root_inst
            self._packages[package_id][root_v].download_count += 1
            installed_records.append(root_inst)

            return installed_records

    def rollback_package(
        self,
        package_id: str,
        tenant_id: str = "default",
    ) -> InstallationRecord:
        """Roll back an installed package to its previous installed version."""
        with self._lock:
            inst = self._installations[tenant_id].get(package_id)
            if not inst:
                raise KeyError(f"Package '{package_id}' is not installed in tenant '{tenant_id}'.")
            if not inst.previous_version:
                raise ValueError(f"Package '{package_id}' has no previous version to roll back to.")

            prev_v = inst.previous_version
            now = datetime.now(UTC)
            inst.previous_version = inst.version
            inst.version = prev_v
            inst.updated_at = now
            return inst

    def uninstall_package(
        self,
        package_id: str,
        tenant_id: str = "default",
    ) -> bool:
        """Uninstall a package from the workspace."""
        with self._lock:
            return self._installations[tenant_id].pop(package_id, None) is not None

    def list_installed(self, tenant_id: str = "default") -> list[InstallationRecord]:
        """List all currently installed packages for a tenant."""
        with self._lock:
            return list(self._installations[tenant_id].values())
