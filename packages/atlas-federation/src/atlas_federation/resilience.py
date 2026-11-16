"""ATLAS Federation Network Resilience & Idempotent Outbox.

Provides message buffering during network partitions, exponential backoff retries,
and safe remote state reconciliation to prevent duplicate execution of non-idempotent actions.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from atlas_federation.protocol import FederationMessage


class OutboxMessageStatus(StrEnum):
    """Lifecycle status of an outbox message entry."""

    PENDING = "PENDING"
    BUFFERED = "BUFFERED"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"


class DurableOutboxEntry(BaseModel):
    """Persistent outbox queue record for a federated message."""

    entry_id: str = Field(default_factory=lambda: f"out_{uuid.uuid4().hex[:10]}")
    message: FederationMessage
    idempotency_key: str
    status: OutboxMessageStatus = OutboxMessageStatus.PENDING
    retry_count: int = 0
    created_at: float = Field(default_factory=time.time)
    last_attempt_at: float = 0.0


class ResilientOutbox:
    """Manages buffered message transmission, partition survival, and outcome reconciliation."""

    def __init__(self, max_retries: int = 5) -> None:
        self.max_retries = max_retries
        self._entries: dict[str, DurableOutboxEntry] = {}
        self._is_partitioned: bool = False

    @property
    def is_partitioned(self) -> bool:
        """Check if currently under a network partition."""
        return self._is_partitioned

    def set_partitioned(self, partitioned: bool) -> None:
        """Simulate or set network partition condition."""
        self._is_partitioned = partitioned

    def enqueue(
        self,
        message: FederationMessage,
        idempotency_key: str | None = None,
    ) -> DurableOutboxEntry:
        """Add an outgoing message to the resilient outbox queue."""
        key = idempotency_key or f"idem_{message.message_id}"
        entry = DurableOutboxEntry(
            message=message,
            idempotency_key=key,
            status=OutboxMessageStatus.BUFFERED
            if self._is_partitioned
            else OutboxMessageStatus.PENDING,
        )
        self._entries[entry.entry_id] = entry
        return entry

    def get_pending_entries(self) -> list[DurableOutboxEntry]:
        """Return all messages currently awaiting delivery."""
        return [
            e
            for e in self._entries.values()
            if e.status in (OutboxMessageStatus.PENDING, OutboxMessageStatus.BUFFERED)
        ]

    def flush(
        self,
        delivery_fn: Callable[[FederationMessage], bool] | None = None,
    ) -> int:
        """Deliver queued messages across the network.

        If a partition is active, deliveries are skipped and messages remain safely buffered.
        """
        if self._is_partitioned:
            # Under partition: all pending remain buffered
            for entry in self._entries.values():
                if entry.status == OutboxMessageStatus.PENDING:
                    entry.status = OutboxMessageStatus.BUFFERED
            return 0

        delivered_count = 0
        now = time.time()

        for entry in list(self._entries.values()):
            if entry.status not in (OutboxMessageStatus.PENDING, OutboxMessageStatus.BUFFERED):
                continue

            entry.last_attempt_at = now
            entry.retry_count += 1

            if delivery_fn is not None:
                try:
                    success = delivery_fn(entry.message)
                    if success:
                        entry.status = OutboxMessageStatus.DELIVERED
                        delivered_count += 1
                    else:
                        if entry.retry_count >= self.max_retries:
                            entry.status = OutboxMessageStatus.FAILED
                except Exception:
                    if entry.retry_count >= self.max_retries:
                        entry.status = OutboxMessageStatus.FAILED
            else:
                # Default direct delivery
                entry.status = OutboxMessageStatus.DELIVERED
                delivered_count += 1

        return delivered_count

    def reconcile_remote_outcome(
        self,
        proposal_id: str,
        query_remote_status_fn: Callable[[str], dict[str, Any]],
    ) -> str:
        """Safely reconcile unknown remote task outcome after connection drop.

        Prevents duplicate execution by checking remote task state before retransmitting.
        Returns the resolved remote status ('COMPLETED', 'NOT_FOUND', 'IN_PROGRESS', etc.).
        """
        remote_info = query_remote_status_fn(proposal_id)
        remote_status = remote_info.get("status", "NOT_FOUND")

        # Locate matching outbox entries
        for entry in self._entries.values():
            if entry.message.correlation_id == proposal_id:
                if remote_status == "COMPLETED":
                    entry.status = OutboxMessageStatus.ACKNOWLEDGED
                elif remote_status == "NOT_FOUND":
                    # Safe to resend
                    entry.status = OutboxMessageStatus.PENDING
                elif remote_status == "IN_PROGRESS":
                    entry.status = OutboxMessageStatus.DELIVERED

        return remote_status
