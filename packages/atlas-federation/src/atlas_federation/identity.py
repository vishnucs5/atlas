"""ATLAS Federated Cryptographic Identity & Trust Model.

Provides hierarchical participant identity, signed federation credentials,
mutual authentication, credential rotation, and revocation registries.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field


class TrustRelationship(StrEnum):
    """Pairwise trust level established between participating organizations."""

    TRUSTED = "TRUSTED"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    PROBATION = "PROBATION"
    BLOCKED = "BLOCKED"


class ParticipantIdentity(BaseModel):
    """Hierarchical identity identifying a federation peer."""

    organization_id: str
    installation_id: str
    agent_id: str | None = None

    @property
    def urn(self) -> str:
        """Construct universal resource name for this identity."""
        if self.agent_id:
            return f"urn:atlas:org:{self.organization_id}:inst:{self.installation_id}:agent:{self.agent_id}"
        return f"urn:atlas:org:{self.organization_id}:inst:{self.installation_id}"


class FederationCredentials(BaseModel):
    """Cryptographic authorization credential for mutual federation authentication."""

    credential_id: str = Field(default_factory=lambda: f"cred_fed_{uuid.uuid4().hex[:10]}")
    organization_id: str
    installation_id: str
    public_key: str = "ed25519_pk_simulated"
    issued_at: float = Field(default_factory=time.time)
    expires_at: float
    scopes: list[str] = Field(default_factory=lambda: ["federation:read", "federation:propose"])
    signature: str = ""

    def is_valid(self, now: float | None = None) -> bool:
        """Check if credential is currently active and unexpired."""
        current = time.time() if now is None else now
        return self.issued_at <= current <= self.expires_at


class FederationIdentityManager:
    """Manages participant enrollment, credential issuance, rotation, and revocation."""

    SIGNING_SECRET = "atlas-federation-master-root-v15"

    def __init__(self) -> None:
        self._credentials: dict[str, FederationCredentials] = {}
        self._revocations: dict[str, str] = {}  # credential_id -> reason
        self._trust_policies: dict[str, TrustRelationship] = {}  # org_id -> relationship

    def issue_credentials(
        self,
        organization_id: str,
        installation_id: str,
        duration_seconds: float = 86400.0,
        scopes: list[str] | None = None,
        public_key: str = "ed25519_pk_simulated",
    ) -> FederationCredentials:
        """Issue a cryptographically signed federation credential."""
        now = time.time()
        scopes = scopes or ["federation:read", "federation:propose"]
        payload = f"{organization_id}:{installation_id}:{now}:{now + duration_seconds}:{','.join(scopes)}:{self.SIGNING_SECRET}"
        sig = f"sig_ed25519_{hashlib.sha256(payload.encode()).hexdigest()[:32]}"

        cred = FederationCredentials(
            organization_id=organization_id,
            installation_id=installation_id,
            public_key=public_key,
            issued_at=now,
            expires_at=now + duration_seconds,
            scopes=scopes,
            signature=sig,
        )

        self._credentials[cred.credential_id] = cred
        return cred

    def rotate_credentials(
        self,
        credential_id: str,
        new_duration_seconds: float = 86400.0,
    ) -> FederationCredentials:
        """Rotate existing credentials, issuing a fresh credential and retiring the old one."""
        old = self._credentials.get(credential_id)
        if not old:
            raise KeyError(f"Credential '{credential_id}' not found.")

        # Revoke old credential
        self.revoke_credential(credential_id, reason="Credential rotated")

        # Issue fresh replacement
        return self.issue_credentials(
            organization_id=old.organization_id,
            installation_id=old.installation_id,
            duration_seconds=new_duration_seconds,
            scopes=old.scopes,
            public_key=old.public_key,
        )

    def revoke_credential(
        self, credential_id: str, reason: str = "Administrative revocation"
    ) -> None:
        """Immediately revoke a credential and broadcast to the revocation registry."""
        self._revocations[credential_id] = reason

    def is_revoked(self, credential_id: str) -> bool:
        """Check if a credential has been revoked."""
        return credential_id in self._revocations

    def authenticate_peer(
        self,
        credentials: FederationCredentials,
        now: float | None = None,
    ) -> bool:
        """Verify peer identity against cryptographic signature, expiry, and revocation registry."""
        if self.is_revoked(credentials.credential_id):
            return False

        if not credentials.is_valid(now):
            return False

        # Verify cryptographic signature
        expected_payload = (
            f"{credentials.organization_id}:{credentials.installation_id}:"
            f"{credentials.issued_at}:{credentials.expires_at}:"
            f"{','.join(credentials.scopes)}:{self.SIGNING_SECRET}"
        )
        expected_sig = f"sig_ed25519_{hashlib.sha256(expected_payload.encode()).hexdigest()[:32]}"
        return credentials.signature == expected_sig

    def set_pairwise_trust(self, organization_id: str, relationship: TrustRelationship) -> None:
        """Establish or update pairwise trust policy with a partner organization."""
        self._trust_policies[organization_id] = relationship

    def get_pairwise_trust(self, organization_id: str) -> TrustRelationship:
        """Get the current trust relationship with an organization."""
        return self._trust_policies.get(organization_id, TrustRelationship.PROBATION)
