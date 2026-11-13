"""Supply-chain security, package validation scanner, and sandboxing guardrails."""

import logging
import re
from typing import Any

from atlas_marketplace.models import (
    PackageManifest,
    PermissionScope,
    WorkflowPackage,
)

logger = logging.getLogger("atlas.marketplace.security")

# Heuristic patterns detecting prompt injection and instruction hijacking in package metadata
PROMPT_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(all\s+)?(prior|previous)\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(prior|previous)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+override\s*:", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+in\s+unrestricted\s+mode", re.IGNORECASE),
    re.compile(r"bypass\s+all\s+(security|policy|firewall)\s+controls", re.IGNORECASE),
    re.compile(r"<script[\s>]", re.IGNORECASE),
]

FORBIDDEN_CODE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bos\.system\s*\("),
    re.compile(r"\bsubprocess\.(Popen|call|run|check_output)\s*\("),
    re.compile(r"\bshutil\.rmtree\s*\("),
    re.compile(r"\bctypes\b"),
]


class SecurityViolationError(Exception):
    """Base exception for marketplace security and supply-chain violations."""


class PrivilegeEscalationError(SecurityViolationError):
    """Raised when a package attempts to claim unauthorized elevated privileges."""


class UntrustedInstructionError(SecurityViolationError):
    """Raised when untrusted instructions or prompt injections are detected in package data."""


class PackageSecurityScanner:
    """Security audit scanner evaluating package manifests, permissions, and payloads."""

    def __init__(
        self,
        trusted_publishers: set[str] | None = None,
        max_allowed_scope_permissions: set[PermissionScope] | None = None,
    ) -> None:
        self.trusted_publishers = trusted_publishers or set()
        self.max_allowed_scope_permissions = max_allowed_scope_permissions or {
            PermissionScope.FILESYSTEM,
            PermissionScope.NETWORK,
            PermissionScope.BROWSER,
            PermissionScope.DESKTOP,
            PermissionScope.MODEL,
        }

    def scan_manifest(self, manifest: PackageManifest) -> list[str]:
        """Audit manifest for privilege escalation and unauthorized scopes."""
        warnings: list[str] = []

        # 1. Privilege escalation: check scopes
        for perm in manifest.permissions:
            if perm.scope not in self.max_allowed_scope_permissions:
                raise PrivilegeEscalationError(
                    f"Package '{manifest.package_id}' requests forbidden privilege scope '{perm.scope.value}'."
                )
            if perm.access == "root" or perm.access == "admin":
                raise PrivilegeEscalationError(
                    f"Package '{manifest.package_id}' requests unauthorized administrative access in scope '{perm.scope.value}'."
                )

        # 2. Resource limits sanity check
        if manifest.resource_limits.max_tokens > 1_000_000:
            raise PrivilegeEscalationError(
                f"Package '{manifest.package_id}' requests excessive token limit ({manifest.resource_limits.max_tokens} > 1M)."
            )

        return warnings

    def scan_for_prompt_injection(self, data: Any, location: str = "") -> None:
        """Recursively scan strings in package data for prompt injection attacks."""
        if isinstance(data, str):
            for pattern in PROMPT_INJECTION_PATTERNS:
                if pattern.search(data):
                    raise UntrustedInstructionError(
                        f"Malicious instruction / prompt injection pattern detected in '{location}': {pattern.pattern}"
                    )
        elif isinstance(data, dict):
            for k, v in data.items():
                self.scan_for_prompt_injection(v, location=f"{location}.{k}" if location else k)
        elif isinstance(data, list | tuple | set):
            for i, item in enumerate(data):
                self.scan_for_prompt_injection(item, location=f"{location}[{i}]")

    def scan_skill_source_code(self, source_code: str) -> None:
        """Scan third-party skill source code for dangerous system invocations."""
        for pattern in FORBIDDEN_CODE_PATTERNS:
            if pattern.search(source_code):
                raise SecurityViolationError(
                    f"Forbidden system invocation detected in skill source: '{pattern.pattern}'."
                )

    def scan_package(self, package: WorkflowPackage) -> None:
        """Run comprehensive security scanner across package manifest, workflow, and payload."""
        # 1. Manifest scan
        self.scan_manifest(package.manifest)

        # 2. Prompt injection scan across manifest descriptions and node parameters
        self.scan_for_prompt_injection(package.manifest.description, "manifest.description")
        if package.workflow:
            for node in package.workflow.nodes:
                self.scan_for_prompt_injection(node.parameters, f"node({node.node_id}).parameters")
