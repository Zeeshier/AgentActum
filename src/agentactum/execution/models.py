"""Tool execution result contracts."""

from typing import Self
from uuid import UUID

from pydantic import JsonValue, model_validator

from agentactum._model import DomainModel, LongText, ShortText, Timestamp


class FailureDetail(DomainModel):
    """Sanitized, structured description of a domain-operation failure."""

    code: ShortText
    message: LongText


class ExecutionResult(DomainModel):
    """Immutable result of one attempted action execution."""

    execution_id: UUID
    transaction_id: UUID
    intent_id: UUID
    succeeded: bool
    started_at: Timestamp
    completed_at: Timestamp
    output: JsonValue = None
    error: FailureDetail | None = None
    postcondition_verified: bool | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        """Require coherent timing, error, and verification fields."""
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        if self.succeeded:
            if self.error is not None:
                raise ValueError("successful execution cannot contain an error")
            if self.postcondition_verified is False:
                raise ValueError("successful execution cannot fail its postcondition")
        elif self.error is None:
            raise ValueError("failed execution requires an error")
        return self
