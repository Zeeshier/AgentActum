"""Compensation result contracts."""

from typing import Self
from uuid import UUID

from pydantic import JsonValue, model_validator

from agentactum._model import DomainModel, Timestamp
from agentactum.execution import FailureDetail


class CompensationResult(DomainModel):
    """Immutable result of one compensation attempt."""

    compensation_id: UUID
    execution_id: UUID
    transaction_id: UUID
    intent_id: UUID
    succeeded: bool
    started_at: Timestamp
    completed_at: Timestamp
    output: JsonValue = None
    error: FailureDetail | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        """Require coherent timing and error fields."""
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        if self.succeeded and self.error is not None:
            raise ValueError("successful compensation cannot contain an error")
        if not self.succeeded and self.error is None:
            raise ValueError("failed compensation requires an error")
        return self
