"""Effect outbox records."""

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import JsonValue, model_validator

from agentactum._model import DomainModel, DomainName, JsonObject, Timestamp
from agentactum.execution import FailureDetail


class OutboxStatus(StrEnum):
    """Lifecycle status for a staged outbox operation."""

    STAGED = "staged"
    RELEASED = "released"
    FAILED = "failed"


class OutboxOperation(DomainModel):
    """Immutable record for an irreversible operation staged behind commit."""

    operation_id: UUID
    transaction_id: UUID
    operation_name: DomainName
    arguments: JsonObject
    status: OutboxStatus
    staged_at: Timestamp
    released_at: Timestamp | None = None
    output: JsonValue = None
    error: FailureDetail | None = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> Self:
        """Keep staged, released, and failed records internally coherent."""
        if self.status is OutboxStatus.STAGED:
            if self.released_at is not None or self.output is not None:
                raise ValueError("staged outbox operations cannot contain release data")
            if self.error is not None:
                raise ValueError("staged outbox operations cannot contain an error")
        elif self.status is OutboxStatus.RELEASED:
            if self.released_at is None:
                raise ValueError("released outbox operations require released_at")
            if self.error is not None:
                raise ValueError("released outbox operations cannot contain an error")
        else:
            if self.released_at is None:
                raise ValueError("failed outbox operations require released_at")
            if self.error is None:
                raise ValueError("failed outbox operations require an error")

        if self.released_at is not None and self.released_at < self.staged_at:
            raise ValueError("released_at must not precede staged_at")
        return self


class OutboxReleaseSummary(DomainModel):
    """Summary returned after releasing staged operations."""

    transaction_id: UUID
    released: tuple[OutboxOperation, ...]
    failed: tuple[OutboxOperation, ...]

    @property
    def succeeded(self) -> bool:
        """Return whether every attempted operation released successfully."""
        return not self.failed
