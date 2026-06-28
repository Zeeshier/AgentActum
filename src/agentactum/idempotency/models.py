"""Validated idempotency records and claim results."""

from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import JsonValue, model_validator

from agentactum._model import DomainModel, LongText, ShortText, Timestamp


class IdempotencyRecordStatus(StrEnum):
    """Lifecycle status for an in-memory idempotency record."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class IdempotencyRecord(DomainModel):
    """Record that reserves one idempotency key for one logical effect."""

    key: ShortText
    owner_token: UUID
    status: IdempotencyRecordStatus
    claimed_at: Timestamp
    completed_at: Timestamp | None = None
    result_reference: LongText | None = None
    result: JsonValue = None

    @model_validator(mode="after")
    def validate_completion(self) -> Self:
        """Keep completion fields consistent with record status."""
        if self.status is IdempotencyRecordStatus.IN_PROGRESS:
            if (
                self.completed_at is not None
                or self.result_reference is not None
                or self.result is not None
            ):
                raise ValueError("in-progress records cannot contain completion data")
        else:
            if self.completed_at is None:
                raise ValueError("completed records require completed_at")
            if self.completed_at < self.claimed_at:
                raise ValueError("completed_at must not precede claimed_at")
        return self


class IdempotencyClaim(DomainModel):
    """Result of attempting to reserve an idempotency key."""

    record: IdempotencyRecord
    acquired: bool
