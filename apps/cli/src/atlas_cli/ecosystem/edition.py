"""ATLAS CLI Edition Feature Matrix & Tier Separation.

Guarantees clear architectural separation between the 100% open-source core
(which operates fully offline with zero enterprise dependencies) and optional
enterprise governance, IAM, centralized audit, and federation extensions.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class EditionTier(StrEnum):
    """Supported product editions of ATLAS CLI."""

    OPEN_SOURCE = "open-source"
    ENTERPRISE = "enterprise"


class EnterpriseFeatureRequiredError(Exception):
    """Raised when an enterprise-only feature is requested in open-source mode."""

    def __init__(self, feature_name: str, message: str | None = None) -> None:
        self.feature_name = feature_name
        msg = (
            message
            or f"Feature '{feature_name}' requires the ATLAS Enterprise Edition. "
            "The Open-Source Core operates fully offline and does not include centralized "
            "enterprise IAM, fleet policy distribution, or centralized audit ledgers."
        )
        super().__init__(msg)


class FeatureDefinition(BaseModel):
    """Specification of an ATLAS capability and its edition availability."""

    name: str
    description: str
    tier: EditionTier
    requires_network: bool = False
    requires_cloud_auth: bool = False


class EditionFeatureMatrix:
    """Manages feature gating and graceful degradation across ATLAS editions."""

    FEATURES: dict[str, FeatureDefinition] = {
        # Open-source core capabilities (100% offline, local-first)
        "local_coding": FeatureDefinition(
            name="local_coding",
            description="Autonomous coding engine, AST parsing, and test execution",
            tier=EditionTier.OPEN_SOURCE,
            requires_network=False,
        ),
        "minimal_tui": FeatureDefinition(
            name="minimal_tui",
            description="Clean terminal conversation with diff previews and approval gates",
            tier=EditionTier.OPEN_SOURCE,
            requires_network=False,
        ),
        "advanced_tui": FeatureDefinition(
            name="advanced_tui",
            description="Multi-panel interactive Textual dashboard",
            tier=EditionTier.OPEN_SOURCE,
            requires_network=False,
        ),
        "local_code_intelligence": FeatureDefinition(
            name="local_code_intelligence",
            description="Local AST symbol indexing, language parsers, and dependency graph",
            tier=EditionTier.OPEN_SOURCE,
            requires_network=False,
        ),
        "local_multi_agent": FeatureDefinition(
            name="local_multi_agent",
            description="Local specialist agents and supervisory task graph orchestration",
            tier=EditionTier.OPEN_SOURCE,
            requires_network=False,
        ),
        "local_mcp": FeatureDefinition(
            name="local_mcp",
            description="Model Context Protocol tool discovery and firewall execution",
            tier=EditionTier.OPEN_SOURCE,
            requires_network=False,
        ),
        "local_plugins": FeatureDefinition(
            name="local_plugins",
            description="Local plugin package management with SHA-256 integrity checks",
            tier=EditionTier.OPEN_SOURCE,
            requires_network=False,
        ),
        "local_skills": FeatureDefinition(
            name="local_skills",
            description="Built-in and custom skills with prompt injection scanning",
            tier=EditionTier.OPEN_SOURCE,
            requires_network=False,
        ),
        "workspace_profiles": FeatureDefinition(
            name="workspace_profiles",
            description="Project-specific tool configurations and privilege boundary ceilings",
            tier=EditionTier.OPEN_SOURCE,
            requires_network=False,
        ),
        # Enterprise capabilities (requires atlas-enterprise connectivity)
        "central_iam": FeatureDefinition(
            name="central_iam",
            description="Centralized enterprise SSO, RBAC roles, and tenant isolation",
            tier=EditionTier.ENTERPRISE,
            requires_network=True,
            requires_cloud_auth=True,
        ),
        "central_audit": FeatureDefinition(
            name="central_audit",
            description="Tamper-evident centralized audit ledger and compliance reporting",
            tier=EditionTier.ENTERPRISE,
            requires_network=True,
            requires_cloud_auth=True,
        ),
        "remote_runtime": FeatureDefinition(
            name="remote_runtime",
            description="Federated remote execution workers, session leasing, and gateway routing",
            tier=EditionTier.ENTERPRISE,
            requires_network=True,
            requires_cloud_auth=True,
        ),
        "fleet_policy": FeatureDefinition(
            name="fleet_policy",
            description="Organization-wide policy rule distribution to local Action Firewalls",
            tier=EditionTier.ENTERPRISE,
            requires_network=True,
            requires_cloud_auth=True,
        ),
        "distributed_locks": FeatureDefinition(
            name="distributed_locks",
            description="Centralized multi-tenant coordination and resource leases",
            tier=EditionTier.ENTERPRISE,
            requires_network=True,
            requires_cloud_auth=True,
        ),
    }

    def __init__(self, override_tier: EditionTier | None = None) -> None:
        self._override_tier = override_tier

    def get_current_edition(self) -> EditionTier:
        """Resolve current active edition from environment or override."""
        if self._override_tier:
            return self._override_tier

        env_val = os.getenv("ATLAS_EDITION", "").lower().strip()
        if env_val in ("enterprise", "ent", "prod"):
            return EditionTier.ENTERPRISE
        return EditionTier.OPEN_SOURCE

    def is_feature_available(self, feature_name: str) -> bool:
        """Check if a named feature is supported in the current edition."""
        feat = self.FEATURES.get(feature_name)
        if not feat:
            return False

        current_edition = self.get_current_edition()
        if feat.tier == EditionTier.OPEN_SOURCE:
            return True
        return current_edition == EditionTier.ENTERPRISE

    def require_feature(self, feature_name: str) -> FeatureDefinition:
        """Assert feature is available; raise informative error if unavailable."""
        feat = self.FEATURES.get(feature_name)
        if not feat:
            raise ValueError(f"Unknown ATLAS feature: {feature_name}")

        if not self.is_feature_available(feature_name):
            raise EnterpriseFeatureRequiredError(feature_name)
        return feat

    def get_edition_report(self) -> dict[str, Any]:
        """Generate a structured summary of active edition and feature availability."""
        edition = self.get_current_edition()
        available = []
        unavailable = []

        for name, _feat in self.FEATURES.items():
            if self.is_feature_available(name):
                available.append(name)
            else:
                unavailable.append(name)

        return {
            "current_edition": edition.value,
            "offline_ready": edition == EditionTier.OPEN_SOURCE,
            "available_features": available,
            "enterprise_gated_features": unavailable,
        }
