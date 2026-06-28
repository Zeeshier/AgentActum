"""In-memory append-only audit ledger."""

from collections.abc import Callable
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4

from agentactum._model import JsonObject
from agentactum.ledger.models import LedgerEvent


class LedgerError(Exception):
    """Base class for audit-ledger failures."""


class Ledger(Protocol):
    """Append-only audit event sink."""

    def append(
        self,
        *,
        correlation_id: UUID,
        event_type: str,
        intent_id: UUID | None = None,
        transaction_id: UUID | None = None,
        actor_id: str | None = None,
        details: JsonObject | None = None,
    ) -> LedgerEvent:
        """Append one audit event and return the immutable event value."""

    def list_events(self) -> tuple[LedgerEvent, ...]:
        """Return an immutable snapshot of stored audit events."""


class InMemoryLedger:
    """Thread-safe in-memory append-only audit ledger."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        """Create an empty in-process ledger."""
        self._clock = clock or _utc_now
        self._lock = RLock()
        self._events: list[LedgerEvent] = []

    def append(
        self,
        *,
        correlation_id: UUID,
        event_type: str,
        intent_id: UUID | None = None,
        transaction_id: UUID | None = None,
        actor_id: str | None = None,
        details: JsonObject | None = None,
    ) -> LedgerEvent:
        """Append one audit event with a monotonic in-process sequence number."""
        with self._lock:
            event = LedgerEvent(
                event_id=uuid4(),
                correlation_id=correlation_id,
                sequence_number=len(self._events) + 1,
                event_type=event_type,
                occurred_at=self._clock(),
                transaction_id=transaction_id,
                intent_id=intent_id,
                actor_id=actor_id,
                details={} if details is None else details,
            )
            self._events.append(event)
            return event

    def list_events(self) -> tuple[LedgerEvent, ...]:
        """Return an immutable snapshot of the append-only event sequence."""
        with self._lock:
            return tuple(self._events)


def _utc_now() -> datetime:
    return datetime.now(UTC)
