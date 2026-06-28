"""Transaction snapshot domain contracts."""

from datetime import UTC, datetime
from typing import Self
from uuid import UUID

from pydantic import model_validator

from agentactum._model import DomainModel, LongText, Timestamp
from agentactum.contracts import ActionIntent
from agentactum.enums import TransactionStatus

LEGAL_TRANSACTION_TRANSITIONS: dict[
    TransactionStatus,
    frozenset[TransactionStatus],
] = {
    TransactionStatus.PROPOSED: frozenset(
        {
            TransactionStatus.VALIDATING,
            TransactionStatus.REJECTED,
        },
    ),
    TransactionStatus.VALIDATING: frozenset(
        {
            TransactionStatus.AWAITING_APPROVAL,
            TransactionStatus.APPROVED,
            TransactionStatus.REJECTED,
            TransactionStatus.FAILED,
        },
    ),
    TransactionStatus.AWAITING_APPROVAL: frozenset(
        {
            TransactionStatus.APPROVED,
            TransactionStatus.REJECTED,
            TransactionStatus.FAILED,
        },
    ),
    TransactionStatus.APPROVED: frozenset(
        {
            TransactionStatus.EXECUTING,
            TransactionStatus.REJECTED,
            TransactionStatus.FAILED,
        },
    ),
    TransactionStatus.EXECUTING: frozenset(
        {
            TransactionStatus.COMMITTED,
            TransactionStatus.FAILED,
            TransactionStatus.COMPENSATING,
        },
    ),
    TransactionStatus.COMPENSATING: frozenset(
        {
            TransactionStatus.COMPENSATED,
            TransactionStatus.PARTIALLY_COMPENSATED,
            TransactionStatus.FAILED,
        },
    ),
    TransactionStatus.COMMITTED: frozenset(),
    TransactionStatus.REJECTED: frozenset(),
    TransactionStatus.FAILED: frozenset(),
    TransactionStatus.COMPENSATED: frozenset(),
    TransactionStatus.PARTIALLY_COMPENSATED: frozenset(),
}


class IllegalTransactionTransitionError(ValueError):
    """Raised when a transaction transition is not allowed."""

    def __init__(
        self,
        current_status: TransactionStatus,
        requested_status: TransactionStatus,
    ) -> None:
        """Create an illegal-transition error."""
        self.current_status = current_status
        self.requested_status = requested_status
        super().__init__(
            "illegal transaction transition: "
            f"{current_status.value} -> {requested_status.value}",
        )


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

    def transition(
        self,
        status: TransactionStatus,
        *,
        updated_at: Timestamp | None = None,
        approval_request_ids: tuple[UUID, ...] | None = None,
        status_reason: LongText | None = None,
        completed_at: Timestamp | None = None,
    ) -> "Transaction":
        """Return a new transaction snapshot after a legal state transition."""
        if status not in LEGAL_TRANSACTION_TRANSITIONS[self.status]:
            raise IllegalTransactionTransitionError(self.status, status)

        next_updated_at = updated_at or datetime.now(UTC)
        terminal = {
            TransactionStatus.COMMITTED,
            TransactionStatus.REJECTED,
            TransactionStatus.FAILED,
            TransactionStatus.COMPENSATED,
            TransactionStatus.PARTIALLY_COMPENSATED,
        }
        next_completed_at = completed_at
        if status in terminal and next_completed_at is None:
            next_completed_at = next_updated_at

        return Transaction(
            transaction_id=self.transaction_id,
            status=status,
            intents=self.intents,
            created_at=self.created_at,
            updated_at=next_updated_at,
            approval_request_ids=(
                self.approval_request_ids
                if approval_request_ids is None
                else approval_request_ids
            ),
            status_reason=status_reason,
            completed_at=next_completed_at,
        )

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
