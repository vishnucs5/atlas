"""Continuous Compliance Evidence Generator for Enterprise Regulatory Audits."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from atlas_collaboration.models import ComplianceBundle

SUPPORTED_FRAMEWORKS = {"SOC2", "HIPAA", "ISO27001", "EU_AI_ACT"}


class ComplianceEvidenceGenerator:
    """Generates and cryptographically certifies tamper-evident compliance audit packages."""

    def __init__(self, signing_secret: str = "atlas-enterprise-signing-key") -> None:
        self.signing_secret = signing_secret

    def _hash_record(self, record: dict[str, Any]) -> str:
        canonical = json.dumps(record, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def calculate_bundle_merkle_root(self, records: list[dict[str, Any]]) -> str:
        if not records:
            return hashlib.sha256(b"empty_bundle").hexdigest()

        current_level = [self._hash_record(r) for r in records]
        while len(current_level) > 1:
            next_level = []
            for i in range(0, len(current_level), 2):
                if i + 1 < len(current_level):
                    combined = current_level[i] + current_level[i + 1]
                else:
                    combined = current_level[i] + current_level[i]
                next_level.append(hashlib.sha256(combined.encode("utf-8")).hexdigest())
            current_level = next_level
        return current_level[0]

    def generate_bundle(
        self,
        tenant_id: str,
        framework: str,
        records: list[dict[str, Any]],
    ) -> ComplianceBundle:
        fw = framework.upper()
        if fw not in SUPPORTED_FRAMEWORKS:
            raise ValueError(
                f"Unsupported compliance framework '{framework}'. Must be one of: {sorted(SUPPORTED_FRAMEWORKS)}"
            )

        bundle_id = f"cmp_{uuid.uuid4().hex[:12]}"
        now = time.time()
        merkle_root = self.calculate_bundle_merkle_root(records)

        # Compute HMAC signature over bundle metadata and Merkle root
        signature_payload = f"{bundle_id}:{tenant_id}:{fw}:{merkle_root}:{now}:{len(records)}"
        signature = hmac.new(
            self.signing_secret.encode("utf-8"),
            signature_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return ComplianceBundle(
            bundle_id=bundle_id,
            tenant_id=tenant_id,
            framework=fw,
            root_merkle_hash=merkle_root,
            generated_at=now,
            record_count=len(records),
            signature=signature,
            records=records,
        )

    def verify_bundle(self, bundle: ComplianceBundle) -> bool:
        """Verify the integrity and HMAC signature of a compliance bundle."""
        # 1. Verify Merkle root matches record contents
        recomputed_root = self.calculate_bundle_merkle_root(bundle.records)
        if recomputed_root != bundle.root_merkle_hash:
            return False

        # 2. Verify HMAC signature
        expected_payload = f"{bundle.bundle_id}:{bundle.tenant_id}:{bundle.framework}:{bundle.root_merkle_hash}:{bundle.generated_at}:{bundle.record_count}"
        expected_sig = hmac.new(
            self.signing_secret.encode("utf-8"),
            expected_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected_sig, bundle.signature)
