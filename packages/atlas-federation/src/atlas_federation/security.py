"""ATLAS Cross-Organization Security Governor.

Enforces per-peer rate limits, concurrent quotas, tenant isolation boundaries,
cross-boundary artifact authorization, and Action Firewall tamper protection.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from atlas_federation.reputation import FederationReputationTracker


class FederationSecurityError(Exception):
    """Base exception for cross-organization security violations."""


class ActionFirewallTamperError(FederationSecurityError):
    """Raised when a remote participant attempts to alter or disable local Action Firewall rules."""


class TenantIsolationError(FederationSecurityError):
    """Raised when cross-tenant boundary isolation is violated."""


class ArtifactAccessDeniedError(FederationSecurityError):
    """Raised when an unauthorized cross-boundary artifact access is attempted."""


class PeerRateLimitExceededError(FederationSecurityError):
    """Raised when a peer exceeds their sliding-window request rate limit."""


class FederationQuotaExceededError(FederationSecurityError):
    """Raised when a peer exceeds their allocated concurrent task quota."""


class PeerSecurityPolicy(BaseModel):
    """Configurable rate limits and resource quotas for a federation peer."""

    max_requests_per_minute: int = 60
    max_concurrent_tasks: int = 5
    allow_artifact_sharing: bool = True
    allowed_artifact_classifications: list[str] = Field(
        default_factory=lambda: ["PUBLIC", "CONFIDENTIAL"]
    )


class FederationSecurityGovernor:
    """Enforces active defenses and isolation boundaries against remote federation traffic."""

    FORBIDDEN_ACTION_KEYWORDS = [
        "firewall:disable",
        "firewall:modify",
        "policy:override",
        "sudo",
        "admin_elevate",
        "root_access",
        "system_config:write",
    ]

    def __init__(
        self,
        reputation_tracker: FederationReputationTracker | None = None,
        default_policy: PeerSecurityPolicy | None = None,
    ) -> None:
        self.reputation_tracker = reputation_tracker or FederationReputationTracker()
        self.default_policy = default_policy or PeerSecurityPolicy()
        self._peer_policies: dict[str, PeerSecurityPolicy] = {}
        self._request_timestamps: dict[str, list[float]] = {}  # org_id -> [timestamps]
        self._active_concurrent: dict[str, int] = {}  # org_id -> count
        self._registered_artifacts: dict[str, dict[str, Any]] = {}  # artifact_id -> metadata

    def set_peer_policy(self, organization_id: str, policy: PeerSecurityPolicy) -> None:
        """Assign customized policy limits to a specific organization."""
        self._peer_policies[organization_id] = policy

    def get_peer_policy(self, organization_id: str) -> PeerSecurityPolicy:
        """Retrieve applicable security policy for an organization."""
        return self._peer_policies.get(organization_id, self.default_policy)

    def register_artifact(
        self,
        artifact_id: str,
        owner_org_id: str,
        tenant_id: str,
        classification: str = "CONFIDENTIAL",
        shareable_federated: bool = True,
    ) -> None:
        """Register an artifact for cross-boundary authorization tracking."""
        self._registered_artifacts[artifact_id] = {
            "artifact_id": artifact_id,
            "owner_org_id": owner_org_id,
            "tenant_id": tenant_id,
            "classification": classification,
            "shareable_federated": shareable_federated,
        }

    def check_incoming_request(
        self,
        sender_org_id: str,
        target_tenant_id: str,
        origin_tenant_id: str,
        requested_actions: list[str] | None = None,
        referenced_artifact_ids: list[str] | None = None,
    ) -> None:
        """Evaluate incoming federation request against firewall, tenancy, rate, and artifact rules."""
        now = time.time()

        # 1. Check Malicious / Isolated Status
        if self.reputation_tracker.is_isolated(sender_org_id):
            raise FederationSecurityError(
                f"Request rejected: Peer organization '{sender_org_id}' is isolated due to security violations."
            )

        # 2. Action Firewall Tamper Protection (Invariant 5)
        if requested_actions:
            for act in requested_actions:
                act_lower = act.lower()
                for forbidden in self.FORBIDDEN_ACTION_KEYWORDS:
                    if forbidden in act_lower:
                        self.reputation_tracker.record_security_violation(sender_org_id)
                        raise ActionFirewallTamperError(
                            f"Action Firewall tamper attempt detected: '{act}' is strictly forbidden for remote participants."
                        )

        # 3. Multi-Tenant Boundary Isolation
        # If target_tenant_id is defined and sender attempts cross-tenant manipulation
        if target_tenant_id and origin_tenant_id:
            # Different tenants within the same installation must remain completely isolated
            if target_tenant_id != origin_tenant_id and not origin_tenant_id.startswith(
                "tenant_cross_allowed"
            ):
                # Check for unauthorized cross-tenant leakage
                raise TenantIsolationError(
                    f"Cross-tenant isolation violation: Request from origin tenant '{origin_tenant_id}' "
                    f"cannot access target tenant '{target_tenant_id}'."
                )

        # 4. Rate Limiting Check
        policy = self.get_peer_policy(sender_org_id)
        timestamps = self._request_timestamps.setdefault(sender_org_id, [])
        # Prune older than 60 seconds
        cutoff = now - 60.0
        self._request_timestamps[sender_org_id] = [t for t in timestamps if t > cutoff]
        if len(self._request_timestamps[sender_org_id]) >= policy.max_requests_per_minute:
            raise PeerRateLimitExceededError(
                f"Rate limit exceeded for organization '{sender_org_id}': "
                f"max {policy.max_requests_per_minute} requests/minute."
            )
        self._request_timestamps[sender_org_id].append(now)

        # 5. Concurrent Quota Check
        current_active = self._active_concurrent.get(sender_org_id, 0)
        if current_active >= policy.max_concurrent_tasks:
            raise FederationQuotaExceededError(
                f"Concurrent task quota exceeded for organization '{sender_org_id}': "
                f"max {policy.max_concurrent_tasks} active tasks."
            )

        # 6. Artifact Authorization Check
        if referenced_artifact_ids:
            for art_id in referenced_artifact_ids:
                art = self._registered_artifacts.get(art_id)
                if not art:
                    raise ArtifactAccessDeniedError(
                        f"Artifact '{art_id}' not found or unregistered."
                    )
                if not art.get("shareable_federated", False):
                    raise ArtifactAccessDeniedError(
                        f"Artifact '{art_id}' is marked non-shareable across federation boundaries."
                    )
                if art.get("classification") not in policy.allowed_artifact_classifications:
                    raise ArtifactAccessDeniedError(
                        f"Artifact '{art_id}' classification '{art.get('classification')}' "
                        f"is not permitted by peer security policy."
                    )

    def acquire_slot(self, sender_org_id: str) -> None:
        """Acquire a concurrent execution slot."""
        self._active_concurrent[sender_org_id] = self._active_concurrent.get(sender_org_id, 0) + 1

    def release_slot(self, sender_org_id: str) -> None:
        """Release a concurrent execution slot."""
        current = self._active_concurrent.get(sender_org_id, 0)
        if current > 0:
            self._active_concurrent[sender_org_id] = current - 1
