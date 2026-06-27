"""In-memory idempotency backend and backend protocol."""

from collections.abc import Callable
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4

from agentactum.idempotency.models import (
    IdempotencyClaim,
    IdempotencyRecord,
    IdempotencyRecordStatus,
)


class IdempotencyError(Exception):
    """Base class for idempotency failures."""


class IdempotencyOwnershipError(IdempotencyError):
    """Raised when a caller tries to complete a record it did not claim."""

    def __init__(self, key: str) -> None:
        """Create an ownership error for an idempotency key."""
        self.key = key
        super().__init__(f"idempotency record is owned by another token: {key}")


class IdempotencyBackend(Protocol):
    """Storage boundary for atomic idempotency claims."""

    def claim(self, key: str) -> IdempotencyClaim:
        """Atomically claim an idempotency key or observe the existing record."""

    def get_record(self, key: str) -> IdempotencyRecord | None:
        """Return the current record for a key, if one exists."""

    def mark_completed(
        self,
        key: str,
        *,
        owner_token: UUID,
        result_reference: str | None = None,
    ) -> IdempotencyRecord:
        """Mark a caller-owned idempotency record as completed."""


class InMemoryIdempotencyBackend:
    """Thread-safe in-memory backend for one Python process."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        """Create an empty backend with an optional timezone-aware clock."""
        self._clock = clock or _utc_now
        self._lock = RLock()
        self._records: dict[str, IdempotencyRecord] = {}

    def claim(self, key: str) -> IdempotencyClaim:
        """Atomically claim an idempotency key or return the existing claim."""
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                return IdempotencyClaim(record=existing, acquired=False)

            record = IdempotencyRecord(
                key=key,
                owner_token=uuid4(),
                status=IdempotencyRecordStatus.IN_PROGRESS,
                claimed_at=self._clock(),
            )
            self._records[key] = record
            return IdempotencyClaim(record=record, acquired=True)

    def get_record(self, key: str) -> IdempotencyRecord | None:
        """Return the current immutable record for a key, if one exists."""
        with self._lock:
            return self._records.get(key)

    def mark_completed(
        self,
        key: str,
        *,
        owner_token: UUID,
        result_reference: str | None = None,
    ) -> IdempotencyRecord:
        """Mark a caller-owned idempotency record as completed."""
        with self._lock:
            record = self._records[key]
            if record.owner_token != owner_token:
                raise IdempotencyOwnershipError(key)
            if record.status is IdempotencyRecordStatus.COMPLETED:
                return record

            completed = IdempotencyRecord(
                key=record.key,
                owner_token=record.owner_token,
                status=IdempotencyRecordStatus.COMPLETED,
                claimed_at=record.claimed_at,
                completed_at=self._clock(),
                result_reference=result_reference,
            )
            self._records[key] = completed
            return completed


def _utc_now() -> datetime:
    return datetime.now(UTC)
