"""Event streaming, subscription management, sequence ordering, and deduplication."""

from collections.abc import Callable, Sequence
from typing import Any

from atlas_core.contracts.event import ExecutionEvent


class EventStreamSubscriber:
    """Manages event subscriptions, enforces monotonic sequence ordering,

    and protects against duplicate or stale events.
    """

    def __init__(self, task_id: str | None = None) -> None:
        self.task_id = task_id
        self.seen_event_ids: set[str] = set()
        self.last_sequence: int = -1
        self.buffered_events: list[ExecutionEvent] = []
        self._listeners: list[Callable[[ExecutionEvent], None]] = []

    def subscribe(self, callback: Callable[[ExecutionEvent], None]) -> None:
        """Register an event listener callback."""
        self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[ExecutionEvent], None]) -> None:
        """Unregister an event listener callback."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def ingest_event(self, event: ExecutionEvent | dict[str, Any]) -> bool:
        """Ingest, validate, deduplicate, and order an incoming event.

        Returns True if the event was newly accepted and dispatched to listeners,

        False if dropped as a duplicate or stale.
        """
        if isinstance(event, dict):
            # Parse dict into ExecutionEvent
            event = ExecutionEvent.model_validate(event)

        # 1. Filter by task_id if configured
        if self.task_id and event.task_id != self.task_id:
            return False

        # 2. Duplicate Event Protection
        if event.event_id in self.seen_event_ids:
            return False

        # 3. Sequence Ordering Check
        if event.sequence <= self.last_sequence:
            # Stale event with sequence earlier than or equal to current sequence
            return False

        # Accept event
        self.seen_event_ids.add(event.event_id)
        self.last_sequence = event.sequence
        self.buffered_events.append(event)

        # Dispatch to listeners
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                pass

        return True

    def ingest_batch(self, events: Sequence[ExecutionEvent | dict[str, Any]]) -> int:
        """Ingest a batch of events, sorting by sequence to guarantee ordering."""
        # Normalize and sort
        normalized: list[ExecutionEvent] = []
        for e in events:
            if isinstance(e, dict):
                normalized.append(ExecutionEvent.model_validate(e))
            else:
                normalized.append(e)

        sorted_events = sorted(normalized, key=lambda ev: ev.sequence)
        accepted_count = 0
        for ev in sorted_events:
            if self.ingest_event(ev):
                accepted_count += 1
        return accepted_count

    def resynchronize(self, events_history: list[ExecutionEvent | dict[str, Any]]) -> None:
        """Resynchronize subscriber state from authoritative server history after a reconnect."""
        self.ingest_batch(events_history)
