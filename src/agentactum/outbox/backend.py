"""In-memory effect outbox."""

from collections.abc import Callable
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import JsonValue

from agentactum._model import JsonObject
from agentactum.execution import FailureDetail
from agentactum.ledger import Ledger
from agentactum.outbox.models import (
    OutboxOperation,
    OutboxReleaseSummary,
    OutboxStatus,
)

type OutboxHandler = Callable[..., JsonValue]


class OutboxError(Exception):
    """Base class for outbox failures."""


class UnknownOutboxOperationError(OutboxError):
    """Raised when releasing an operation id that is not staged."""

    def __init__(self, operation_id: UUID) -> None:
        """Create an unknown outbox operation error."""
        self.operation_id = operation_id
        super().__init__(f"unknown outbox operation: {operation_id}")


class OutboxBackend(Protocol):
    """Storage and release boundary for staged irreversible operations."""

    def stage(
        self,
        *,
        transaction_id: UUID,
        operation_name: str,
        arguments: JsonObject,
        handler: OutboxHandler,
    ) -> OutboxOperation:
        """Stage an operation without invoking its handler."""

    def release(self, operation_id: UUID) -> OutboxOperation:
        """Release one staged operation after commit."""

    def release_all(self, transaction_id: UUID) -> OutboxReleaseSummary:
        """Release every staged operation for a committed transaction."""

    def list_operations(
        self,
        transaction_id: UUID | None = None,
    ) -> tuple[OutboxOperation, ...]:
        """Return an immutable snapshot of staged/released operations."""


class InMemoryOutboxBackend:
    """Thread-safe in-memory implementation of the effect outbox."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        ledger: Ledger | None = None,
    ) -> None:
        """Create an empty in-process outbox."""
        self._clock = clock or _utc_now
        self._ledger = ledger
        self._lock = RLock()
        self._operations: dict[UUID, OutboxOperation] = {}
        self._handlers: dict[UUID, OutboxHandler] = {}

    def stage(
        self,
        *,
        transaction_id: UUID,
        operation_name: str,
        arguments: JsonObject,
        handler: OutboxHandler,
    ) -> OutboxOperation:
        """Stage an operation without invoking its handler."""
        if not callable(handler):
            raise TypeError("handler must be callable")

        with self._lock:
            operation = OutboxOperation(
                operation_id=uuid4(),
                transaction_id=transaction_id,
                operation_name=operation_name,
                arguments=arguments,
                status=OutboxStatus.STAGED,
                staged_at=self._clock(),
            )
            self._operations[operation.operation_id] = operation
            self._handlers[operation.operation_id] = handler
            self._append_event("outbox.staged", operation)
            return operation

    def release(self, operation_id: UUID) -> OutboxOperation:
        """Release one staged operation after commit."""
        with self._lock:
            operation = self._operations.get(operation_id)
            if operation is None:
                raise UnknownOutboxOperationError(operation_id)
            if operation.status is not OutboxStatus.STAGED:
                return operation
            handler = self._handlers[operation_id]

            try:
                output = handler(**operation.arguments)
            except Exception:
                released = OutboxOperation(
                    operation_id=operation.operation_id,
                    transaction_id=operation.transaction_id,
                    operation_name=operation.operation_name,
                    arguments=operation.arguments,
                    status=OutboxStatus.FAILED,
                    staged_at=operation.staged_at,
                    released_at=self._clock(),
                    error=FailureDetail(
                        code="outbox_release_failed",
                        message="Staged operation handler raised an exception.",
                    ),
                )
            else:
                released = OutboxOperation(
                    operation_id=operation.operation_id,
                    transaction_id=operation.transaction_id,
                    operation_name=operation.operation_name,
                    arguments=operation.arguments,
                    status=OutboxStatus.RELEASED,
                    staged_at=operation.staged_at,
                    released_at=self._clock(),
                    output=output,
                )

            self._operations[operation_id] = released
            self._append_event(
                "outbox.released"
                if released.status is OutboxStatus.RELEASED
                else "outbox.release_failed",
                released,
            )
            return released

    def release_all(self, transaction_id: UUID) -> OutboxReleaseSummary:
        """Release every staged operation for a committed transaction."""
        staged_operations = [
            operation
            for operation in self.list_operations(transaction_id)
            if operation.status is OutboxStatus.STAGED
        ]
        released: list[OutboxOperation] = []
        failed: list[OutboxOperation] = []
        for operation in staged_operations:
            result = self.release(operation.operation_id)
            if result.status is OutboxStatus.RELEASED:
                released.append(result)
            else:
                failed.append(result)

        return OutboxReleaseSummary(
            transaction_id=transaction_id,
            released=tuple(released),
            failed=tuple(failed),
        )

    def list_operations(
        self,
        transaction_id: UUID | None = None,
    ) -> tuple[OutboxOperation, ...]:
        """Return an immutable snapshot of operations in insertion order."""
        with self._lock:
            operations = tuple(self._operations.values())
        if transaction_id is None:
            return operations
        return tuple(
            operation
            for operation in operations
            if operation.transaction_id == transaction_id
        )

    def _append_event(self, event_type: str, operation: OutboxOperation) -> None:
        if self._ledger is None:
            return
        self._ledger.append(
            correlation_id=operation.transaction_id,
            event_type=event_type,
            transaction_id=operation.transaction_id,
            details={
                "operation_id": str(operation.operation_id),
                "operation_name": operation.operation_name,
                "status": operation.status.value,
            },
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)
