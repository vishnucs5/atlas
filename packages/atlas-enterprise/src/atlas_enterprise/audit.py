"""Enterprise Immutable Audit Ledger with Cryptographic SHA-256 Hash Chaining."""

import hashlib
import json
import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from atlas_enterprise.iam import EnterpriseIAMEngine
from atlas_enterprise.models import AuditRecord, PermissionAction
from atlas_enterprise.organization import (
    EnterpriseOrganizationManager,
)

logger = logging.getLogger("atlas.enterprise.audit")

GENESIS_HASH = "0" * 64


class EnterpriseAuditError(Exception):
    """Base exception for audit ledger errors."""


class AuditTamperDetectedError(EnterpriseAuditError):
    """Raised when an audit chain verification identifies an integrity or hash mismatch."""


def compute_record_hash(
    sequence: int,
    org_id: str,
    department_id: str | None,
    event_type: str,
    actor_id: str,
    actor_type: str,
    action: str,
    target_resource_id: str | None,
    details: dict[str, Any],
    timestamp: datetime,
    previous_hash: str,
) -> str:
    """Compute the deterministic SHA-256 hash committing to record contents and prior hash."""
    canonical_dict = {
        "sequence": sequence,
        "org_id": org_id,
        "department_id": department_id,
        "event_type": event_type,
        "actor_id": actor_id,
        "actor_type": actor_type,
        "action": action,
        "target_resource_id": target_resource_id,
        "details": details,
        "timestamp": timestamp.isoformat(),
    }
    canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    to_hash = canonical_json + b":" + previous_hash.encode("utf-8")
    return hashlib.sha256(to_hash).hexdigest()


class EnterpriseAuditLedger:
    """Multi-tenant, immutable audit ledger maintaining cryptographically chained event records."""

    def __init__(
        self,
        org_manager: EnterpriseOrganizationManager,
        iam_engine: EnterpriseIAMEngine,
    ) -> None:
        self.org_manager = org_manager
        self.iam_engine = iam_engine
        self._lock = threading.RLock()
        self._chains: dict[str, list[AuditRecord]] = {}  # org_id -> list of records

    def append_entry(
        self,
        org_id: str,
        event_type: str,
        actor_id: str,
        actor_type: str,
        action: str,
        target_resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        department_id: str | None = None,
    ) -> AuditRecord:
        """Append an immutable audit entry into the tenant's cryptographic hash chain."""
        with self._lock:
            # Ensure organization exists
            self.org_manager.get_organization(org_id)

            chain = self._chains.setdefault(org_id, [])
            sequence = len(chain) + 1
            previous_hash = chain[-1].record_hash if chain else GENESIS_HASH

            now = datetime.now(UTC)
            safe_details = details or {}

            rec_hash = compute_record_hash(
                sequence=sequence,
                org_id=org_id,
                department_id=department_id,
                event_type=event_type,
                actor_id=actor_id,
                actor_type=actor_type,
                action=action,
                target_resource_id=target_resource_id,
                details=safe_details,
                timestamp=now,
                previous_hash=previous_hash,
            )

            record = AuditRecord(
                record_id=f"aud_{uuid.uuid4().hex[:12]}",
                org_id=org_id,
                department_id=department_id,
                sequence=sequence,
                event_type=event_type,
                actor_id=actor_id,
                actor_type=actor_type,
                action=action,
                target_resource_id=target_resource_id,
                details=safe_details,
                timestamp=now,
                previous_hash=previous_hash,
                record_hash=rec_hash,
            )

            chain.append(record)
            logger.info(
                "Appended audit record seq=%d for org=%s hash=%s", sequence, org_id, rec_hash[:16]
            )
            return record

    def query_records(
        self,
        caller_user_id: str,
        org_id: str,
        start_sequence: int = 1,
        limit: int = 100,
        department_id: str | None = None,
        event_type: str | None = None,
        actor_id: str | None = None,
    ) -> list[AuditRecord]:
        """Query audit records with RBAC verification and tenant boundary enforcement."""
        with self._lock:
            self.iam_engine.assert_permission(
                user_id=caller_user_id,
                org_id=org_id,
                action=PermissionAction.AUDIT_READ,
            )

            chain = self._chains.get(org_id, [])
            filtered: list[AuditRecord] = []

            for rec in chain:
                if rec.sequence < start_sequence:
                    continue
                if department_id and rec.department_id != department_id:
                    continue
                if event_type and rec.event_type != event_type:
                    continue
                if actor_id and rec.actor_id != actor_id:
                    continue
                filtered.append(rec)
                if len(filtered) >= limit:
                    break

            return filtered

    def verify_chain_integrity(self, org_id: str) -> tuple[bool, int | None, str | None]:
        """Verify the cryptographic hash chain for an organization.

        Returns (is_intact, broken_sequence, failure_reason).
        """
        with self._lock:
            chain = self._chains.get(org_id, [])
            if not chain:
                return True, None, None

            expected_prev_hash = GENESIS_HASH
            for idx, rec in enumerate(chain):
                expected_seq = idx + 1
                if rec.sequence != expected_seq:
                    return (
                        False,
                        rec.sequence,
                        f"Sequence continuity broken: expected {expected_seq}, found {rec.sequence}",
                    )

                if rec.previous_hash != expected_prev_hash:
                    return (
                        False,
                        rec.sequence,
                        f"Previous hash link broken at sequence {rec.sequence}: {rec.previous_hash} != {expected_prev_hash}",
                    )

                recomputed_hash = compute_record_hash(
                    sequence=rec.sequence,
                    org_id=rec.org_id,
                    department_id=rec.department_id,
                    event_type=rec.event_type,
                    actor_id=rec.actor_id,
                    actor_type=rec.actor_type,
                    action=rec.action,
                    target_resource_id=rec.target_resource_id,
                    details=rec.details,
                    timestamp=rec.timestamp,
                    previous_hash=rec.previous_hash,
                )

                if rec.record_hash != recomputed_hash:
                    return (
                        False,
                        rec.sequence,
                        f"Record hash mismatch at sequence {rec.sequence}: data was tampered",
                    )

                expected_prev_hash = rec.record_hash

            return True, None, None

    def export_audit_trail(
        self,
        caller_user_id: str,
        org_id: str,
    ) -> list[dict[str, Any]]:
        """Export full verifiable audit trail for compliance and SOC2 auditing."""
        with self._lock:
            self.iam_engine.assert_permission(
                user_id=caller_user_id,
                org_id=org_id,
                action=PermissionAction.AUDIT_EXPORT,
            )

            is_intact, seq, reason = self.verify_chain_integrity(org_id)
            if not is_intact:
                raise AuditTamperDetectedError(f"Cannot export corrupted audit trail: {reason}")

            chain = self._chains.get(org_id, [])
            return [rec.model_dump(mode="json") for rec in chain]
