"""Transaction snapshot domain contracts."""

from typing import Self
from uuid import UUID

from pydantic import model_validator

from agentactum._model import DomainModel, LongText, Timestamp
from agentactum.contracts import ActionIntent
from agentactum.enums import TransactionStatus


class Transaction(DomainModel):
    """Immutable snapshot of a transaction and its admitted action intents."""

    transaction_id: UUID
    status: TransactionStatus
    intents: tuple[ActionIntent, ...]
    created_at: Timestamp
    updated_at: Timestamp
    approval_request_ids: tuple[UUID, ...] = ()
    status_reason: LongText | None = None
    completed_at: Timestamp | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        """Reject internally inconsistent transaction snapshots."""
        if not self.intents:
            raise ValueError("transaction must contain at least one intent")

        intent_ids = [intent.intent_id for intent in self.intents]
        if len(intent_ids) != len(set(intent_ids)):
            raise ValueError("transaction intent identifiers must be unique")
        if len(self.approval_request_ids) != len(set(self.approval_request_ids)):
            raise ValueError("approval request identifiers must be unique")

        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if (
            self.status is TransactionStatus.AWAITING_APPROVAL
            and not self.approval_request_ids
        ):
            raise ValueError("awaiting approval requires an approval request")

        reason_required = {
            TransactionStatus.REJECTED,
            TransactionStatus.FAILED,
            TransactionStatus.PARTIALLY_COMPENSATED,
        }
        if self.status in reason_required and self.status_reason is None:
            raise ValueError("terminal failure status requires a reason")

        terminal = {
            TransactionStatus.COMMITTED,
            TransactionStatus.REJECTED,
            TransactionStatus.FAILED,
            TransactionStatus.COMPENSATED,
            TransactionStatus.PARTIALLY_COMPENSATED,
        }
        if self.status in terminal:
            if self.completed_at is None:
                raise ValueError("terminal transaction requires completed_at")
            if self.completed_at < self.updated_at:
                raise ValueError("completed_at must not precede updated_at")
        elif self.completed_at is not None:
            raise ValueError("non-terminal transaction cannot have completed_at")
        return self
