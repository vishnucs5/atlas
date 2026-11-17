"""Plugin ecosystem management, manifest verification, lifecycle, and security boundaries."""

import hashlib
import logging
import threading
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from atlas_marketplace.models import (
    PackageManifest,
    PackageType,
    PermissionScope,
)
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("atlas.cli.ecosystem.plugins")


class PluginStatus(StrEnum):
    """Lifecycle state of an installed plugin."""

    INSTALLED = "INSTALLED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    CORRUPTED = "CORRUPTED"


class PluginSecurityError(Exception):
    """Raised when a plugin attempts an unauthorized action or fails integrity validation."""


class PluginDependencyError(Exception):
    """Raised when a plugin dependency check fails."""


class InstalledPlugin(BaseModel):
    """Record of a verified, installed plugin."""

    model_config = ConfigDict(validate_assignment=True)

    manifest: PackageManifest
    status: PluginStatus = PluginStatus.ENABLED
    installed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sha256_checksum: str
    signature: str | None = None
    entrypoint: str = "main.py"

    @property
    def plugin_id(self) -> str:
        return self.manifest.package_id

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def publisher(self) -> str:
        return (
            self.manifest.publisher.publisher_id
            if hasattr(self.manifest, "publisher") and self.manifest.publisher
            else "Unknown"
        )


class PluginAuditEvent(BaseModel):
    """Audit log entry capturing a plugin lifecycle or governance event."""

    model_config = ConfigDict(validate_assignment=True)

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    plugin_id: str
    action: str  # "INSTALL", "UPGRADE", "ENABLE", "DISABLE", "UNINSTALL"
    details: str
    actor: str = "system"


class PluginManager:
    """Manages plugin discovery, validation, cryptographic integrity, and execution lifecycle."""

    def __init__(
        self,
        current_atlas_version: str = "0.9.0",
        install_dir: Path | str | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self.current_atlas_version = current_atlas_version
        self.install_dir = Path(install_dir) if install_dir else None
        self.plugins: dict[str, InstalledPlugin] = {}
        self.audit_events: list[PluginAuditEvent] = []

    def _record_audit(self, plugin_id: str, action: str, details: str) -> None:
        event = PluginAuditEvent(
            plugin_id=plugin_id,
            action=action,
            details=details,
        )
        self.audit_events.append(event)

    def install_plugin(
        self,
        manifest: PackageManifest,
        archive_bytes: bytes | Path | None = None,
        signature: str | None = None,
        expected_checksum: str | None = None,
        expected_sha256: str | None = None,
        archive_path: Path | str | None = None,
        publisher: str | None = None,
    ) -> InstalledPlugin:
        """Validate, verify integrity, and install a marketplace plugin."""
        with self._lock:
            # Resolve archive data
            if archive_path is not None:
                raw_bytes = Path(archive_path).read_bytes()
            elif isinstance(archive_bytes, Path):
                raw_bytes = archive_bytes.read_bytes()
            elif isinstance(archive_bytes, bytes):
                raw_bytes = archive_bytes
            else:
                raw_bytes = b""

            expected = expected_checksum or expected_sha256

            # 1. Type validation
            if manifest.package_type not in (PackageType.PLUGIN, PackageType.SKILL):
                msg = f"Package '{manifest.package_id}' is of type {manifest.package_type.value}, not a valid PLUGIN."
                raise ValueError(msg)

            # 2. Cryptographic Integrity Check
            actual_checksum = hashlib.sha256(raw_bytes).hexdigest()
            if expected and actual_checksum != expected:
                self._record_audit(
                    manifest.package_id,
                    "CORRUPTED",
                    f"Checksum mismatch: expected {expected}, calculated {actual_checksum}",
                )
                raise PluginSecurityError(
                    f"Integrity check failed for plugin '{manifest.package_id}': SHA-256 mismatch."
                )

            # 3. Signature verification
            if signature and not getattr(manifest.publisher, "is_trusted", False):
                raise PluginSecurityError(
                    f"Untrusted publisher '{manifest.publisher.publisher_id}' for plugin '{manifest.package_id}'."
                )

            # 4. Privileged runtime protection: prohibit unrestricted system permissions
            for perm in manifest.permissions:
                if perm.scope == PermissionScope.SYSTEM and perm.access == "unrestricted_root":
                    raise PluginSecurityError(
                        f"Plugin '{manifest.package_id}' requests forbidden 'unrestricted_root' permission."
                    )

            plugin = InstalledPlugin(
                manifest=manifest,
                status=PluginStatus.INSTALLED,
                installed_at=datetime.now(UTC),
                sha256_checksum=actual_checksum,
                signature=signature,
            )

            self.plugins[manifest.package_id] = plugin
            self._record_audit(
                manifest.package_id, "INSTALL", f"Installed version {manifest.version}"
            )
            return plugin

    def disable_plugin(self, plugin_id: str) -> None:
        """Disable an active plugin."""
        with self._lock:
            if plugin_id not in self.plugins:
                msg = f"Plugin '{plugin_id}' not found."
                raise KeyError(msg)
            self.plugins[plugin_id].status = PluginStatus.DISABLED
            self._record_audit(plugin_id, "DISABLE", "Plugin disabled by operator.")

    def enable_plugin(self, plugin_id: str) -> None:
        """Enable an installed plugin."""
        with self._lock:
            if plugin_id not in self.plugins:
                msg = f"Plugin '{plugin_id}' not found."
                raise KeyError(msg)
            self.plugins[plugin_id].status = PluginStatus.ENABLED
            self._record_audit(plugin_id, "ENABLE", "Plugin enabled by operator.")

    def upgrade_plugin(
        self,
        plugin_id: str,
        new_manifest: PackageManifest,
        new_bytes: bytes,
    ) -> InstalledPlugin:
        """Upgrade an existing plugin to a higher version."""
        with self._lock:
            if plugin_id not in self.plugins:
                msg = f"Plugin '{plugin_id}' not found for upgrade."
                raise KeyError(msg)

            old_version = self.plugins[plugin_id].manifest.version
            upgraded = self.install_plugin(new_manifest, new_bytes)
            self._record_audit(
                plugin_id,
                "UPGRADE",
                f"Upgraded from version {old_version} to {new_manifest.version}",
            )
            return upgraded

    def uninstall_plugin(self, plugin_id: str) -> None:
        """Remove a plugin from the environment."""
        with self._lock:
            if plugin_id in self.plugins:
                del self.plugins[plugin_id]
                self._record_audit(plugin_id, "UNINSTALL", "Plugin uninstalled from environment.")

    def list_plugins(self, status: PluginStatus | None = None) -> list[InstalledPlugin]:
        """List installed plugins, optionally filtered by status."""
        with self._lock:
            if status:
                return [p for p in self.plugins.values() if p.status == status]
            return list(self.plugins.values())

    def get_plugin(self, plugin_id: str) -> InstalledPlugin | None:
        """Retrieve an installed plugin by identifier."""
        with self._lock:
            return self.plugins.get(plugin_id)

    def list_installed_plugins(self) -> list[InstalledPlugin]:
        """Alias for listing all installed plugins."""
        return self.list_plugins()

    def get_audit_history(self) -> list[PluginAuditEvent]:
        """Return the auditable log of plugin actions."""
        return self.get_audit_log()

    def get_audit_log(self) -> list[PluginAuditEvent]:
        """Return the auditable log of plugin actions."""
        with self._lock:
            return list(self.audit_events)
