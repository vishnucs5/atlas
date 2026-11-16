"""ATLAS Advisory Trust & Reputation Tracker.

Tracks cross-organization operational performance, verification integrity,
and security violations while enforcing that reputation scores remain strictly
advisory and never bypass cryptographic authentication or firewall policies.
"""

from __future__ import annotations

from pydantic import BaseModel


class ParticipantReputation(BaseModel):
    """Execution telemetry and advisory reputation metrics for a federation peer."""

    organization_id: str
    completed_tasks: int = 0
    failed_tasks: int = 0
    verification_failures: int = 0
    security_violations: int = 0
    score: float = 1.0  # 0.0 to 1.0
    is_advisory_only: bool = True


class FederationReputationTracker:
    """Manages empirical reputation scoring across federated participants."""

    ISOLATION_THRESHOLD: float = 0.3

    def __init__(self) -> None:
        self._profiles: dict[str, ParticipantReputation] = {}

    def get_or_create(self, organization_id: str) -> ParticipantReputation:
        """Retrieve existing reputation profile or initialize a fresh one."""
        if organization_id not in self._profiles:
            self._profiles[organization_id] = ParticipantReputation(organization_id=organization_id)
        return self._profiles[organization_id]

    def record_success(self, organization_id: str) -> None:
        """Record a successfully verified task completion."""
        profile = self.get_or_create(organization_id)
        profile.completed_tasks += 1
        # Moderate positive adjustment capped at 1.0
        profile.score = min(1.0, profile.score + 0.02)

    def record_failure(self, organization_id: str) -> None:
        """Record a general task execution failure."""
        profile = self.get_or_create(organization_id)
        profile.failed_tasks += 1
        profile.score = max(0.0, profile.score - 0.05)

    def record_verification_failure(self, organization_id: str) -> None:
        """Record a failed post-condition evidence verification (medium severity)."""
        profile = self.get_or_create(organization_id)
        profile.verification_failures += 1
        profile.score = max(0.0, profile.score - 0.20)

    def record_security_violation(self, organization_id: str) -> None:
        """Record a critical policy or firewall breach attempt (high severity)."""
        profile = self.get_or_create(organization_id)
        profile.security_violations += 1
        # Severe penalty immediately triggering isolation
        profile.score = max(0.0, profile.score - 0.50)

    def is_isolated(self, organization_id: str) -> bool:
        """Check if participant should be isolated based on critical violations or low score."""
        profile = self.get_or_create(organization_id)
        return profile.security_violations > 0 or profile.score < self.ISOLATION_THRESHOLD

    def get_score(self, organization_id: str) -> float:
        """Return the current advisory score for an organization."""
        return self.get_or_create(organization_id).score
