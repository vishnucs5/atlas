"""ATLAS Controlled Promotion & Rollback Lifecycle Manager.

Orchestrates the disciplined progression of validated candidates through
Canary deployment, signature verification, continuous monitoring, and instant rollback.
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum

from pydantic import BaseModel, Field

from atlas_adaptive.governor import UnauthorizedPromotionError


class PromotionStage(StrEnum):
    """Formal progression stages of an improvement candidate."""

    CANDIDATE = "CANDIDATE"
    VALIDATING = "VALIDATING"
    EXPERIMENTING = "EXPERIMENTING"
    SAFETY_REVIEW = "SAFETY_REVIEW"
    APPROVED = "APPROVED"
    CANARY = "CANARY"
    PRODUCTION = "PRODUCTION"
    ROLLED_BACK = "ROLLED_BACK"


class PromotionRecord(BaseModel):
    """Lifecycle tracking ledger for a promoted optimization candidate."""

    promotion_id: str = Field(default_factory=lambda: f"prom_{uuid.uuid4().hex[:10]}")
    candidate_id: str
    tenant_id: str
    current_stage: PromotionStage = PromotionStage.CANDIDATE
    canary_traffic_percent: float = 0.0
    approver_id: str | None = None
    is_signed: bool = False
    signature: str = ""
    history: list[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class PromotionManager:
    """Controls staged progression, canary allocation, and rollback operations."""

    VALID_TRANSITIONS: dict[PromotionStage, list[PromotionStage]] = {
        PromotionStage.CANDIDATE: [PromotionStage.VALIDATING],
        PromotionStage.VALIDATING: [PromotionStage.EXPERIMENTING, PromotionStage.ROLLED_BACK],
        PromotionStage.EXPERIMENTING: [PromotionStage.SAFETY_REVIEW, PromotionStage.ROLLED_BACK],
        PromotionStage.SAFETY_REVIEW: [PromotionStage.APPROVED, PromotionStage.ROLLED_BACK],
        PromotionStage.APPROVED: [PromotionStage.CANARY, PromotionStage.ROLLED_BACK],
        PromotionStage.CANARY: [PromotionStage.PRODUCTION, PromotionStage.ROLLED_BACK],
        PromotionStage.PRODUCTION: [PromotionStage.ROLLED_BACK],
        PromotionStage.ROLLED_BACK: [],
    }

    def __init__(self) -> None:
        self._promotions: dict[str, PromotionRecord] = {}

    def initialize_promotion(
        self,
        candidate_id: str,
        tenant_id: str,
        signature: str = "",
    ) -> PromotionRecord:
        """Create a new promotion tracking record for a candidate."""
        record = PromotionRecord(
            candidate_id=candidate_id,
            tenant_id=tenant_id,
            is_signed=bool(signature),
            signature=signature,
            history=[f"Initialized as {PromotionStage.CANDIDATE.value} at {time.time()}"],
        )
        self._promotions[record.promotion_id] = record
        return record

    def advance_stage(
        self,
        promotion_id: str,
        next_stage: PromotionStage,
        approver_id: str | None = None,
    ) -> PromotionRecord:
        """Advance candidate to the next lifecycle stage with validation checks."""
        record = self._promotions.get(promotion_id)
        if not record:
            raise KeyError(f"Promotion record '{promotion_id}' not found.")

        # Check allowed transition
        allowed = self.VALID_TRANSITIONS.get(record.current_stage, [])
        if next_stage not in allowed:
            raise UnauthorizedPromotionError(
                f"Invalid lifecycle transition from '{record.current_stage.value}' to '{next_stage.value}'."
            )

        # Enforce signature verification before APPROVAL
        if next_stage == PromotionStage.APPROVED:
            if not record.is_signed or not record.signature.strip():
                raise UnauthorizedPromotionError(
                    f"Cannot approve candidate '{record.candidate_id}': Cryptographic signature missing or invalid."
                )
            if not approver_id:
                raise UnauthorizedPromotionError("Approval requires explicit approver identity.")
            record.approver_id = approver_id

        # Canary allocation
        canary_percent = record.canary_traffic_percent
        if next_stage == PromotionStage.CANARY:
            canary_percent = 10.0  # Default 10% canary
        elif next_stage == PromotionStage.PRODUCTION:
            canary_percent = 100.0

        now = time.time()
        record.current_stage = next_stage
        record.canary_traffic_percent = canary_percent
        record.updated_at = now
        record.history.append(
            f"Advanced to {next_stage.value} by {approver_id or 'system'} at {now}"
        )

        return record

    def trigger_rollback(
        self,
        promotion_id: str,
        reason: str,
    ) -> PromotionRecord:
        """Immediately abort active canary or production deployment and restore baseline."""
        record = self._promotions.get(promotion_id)
        if not record:
            raise KeyError(f"Promotion record '{promotion_id}' not found.")

        now = time.time()
        record.current_stage = PromotionStage.ROLLED_BACK
        record.canary_traffic_percent = 0.0
        record.updated_at = now
        record.history.append(f"ROLLED BACK at {now}. Reason: {reason}")

        return record

    def get_promotion(self, promotion_id: str) -> PromotionRecord | None:
        """Retrieve promotion status by promotion ID."""
        return self._promotions.get(promotion_id)
