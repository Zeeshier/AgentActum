"""Tests for transaction snapshots and ledger event contracts."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from agentactum.contracts import ActionIntent
from agentactum.enums import TransactionStatus
from agentactum.ledger import LedgerEvent
from agentactum.transactions import IllegalTransactionTransitionError, Transaction

INTENT_ID = UUID("20000000-0000-4000-8000-000000000001")
SECOND_INTENT_ID = UUID("20000000-0000-4000-8000-000000000002")
CONTRACT_ID = UUID("20000000-0000-4000-8000-000000000003")
TRANSACTION_ID = UUID("20000000-0000-4000-8000-000000000004")
APPROVAL_ID = UUID("20000000-0000-4000-8000-000000000005")
EVENT_ID = UUID("20000000-0000-4000-8000-000000000006")
CORRELATION_ID = UUID("20000000-0000-4000-8000-000000000007")
NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def make_intent(intent_id: UUID = INTENT_ID) -> ActionIntent:
    """Build a valid intent for a transaction snapshot."""
    return ActionIntent(
        intent_id=intent_id,
        contract_id=CONTRACT_ID,
        tool_name="files.write",
        contract_version="1",
        requester_id="agent:test",
        arguments={"path": "fake.txt"},
        created_at=NOW,
        idempotency_key="write-1",
    )


def make_transaction(**overrides: object) -> Transaction:
    """Build a proposed transaction while allowing selected fields to vary."""
    values: dict[str, object] = {
        "transaction_id": TRANSACTION_ID,
        "status": TransactionStatus.PROPOSED,
        "intents": (make_intent(),),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return Transaction(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "extra"),
    [
        (TransactionStatus.PROPOSED, {}),
        (TransactionStatus.VALIDATING, {}),
        (
            TransactionStatus.AWAITING_APPROVAL,
            {"approval_request_ids": (APPROVAL_ID,)},
        ),
        (TransactionStatus.APPROVED, {}),
        (TransactionStatus.EXECUTING, {}),
        (TransactionStatus.COMPENSATING, {}),
        (TransactionStatus.COMMITTED, {"completed_at": NOW}),
        (
            TransactionStatus.REJECTED,
            {"status_reason": "Denied.", "completed_at": NOW},
        ),
        (
            TransactionStatus.FAILED,
            {"status_reason": "Execution failed.", "completed_at": NOW},
        ),
        (TransactionStatus.COMPENSATED, {"completed_at": NOW}),
        (
            TransactionStatus.PARTIALLY_COMPENSATED,
            {"status_reason": "One compensation failed.", "completed_at": NOW},
        ),
    ],
)
def test_transaction_status_snapshots_accept_coherent_fields(
    status: TransactionStatus,
    extra: dict[str, object],
) -> None:
    """Every requested status has at least one valid snapshot shape."""
    transaction = make_transaction(status=status, **extra)

    assert transaction.status is status
    assert Transaction.model_validate_json(transaction.model_dump_json()) == transaction


def test_transaction_requires_at_least_one_unique_intent() -> None:
    """Empty and duplicate intent collections fail validation."""
    with pytest.raises(ValidationError, match="at least one intent"):
        make_transaction(intents=())
    with pytest.raises(ValidationError, match="intent identifiers must be unique"):
        make_transaction(intents=(make_intent(), make_intent()))


def test_transaction_rejects_duplicate_approval_identifiers() -> None:
    """An approval request cannot appear twice in one transaction snapshot."""
    with pytest.raises(ValidationError, match="approval request identifiers"):
        make_transaction(approval_request_ids=(APPROVAL_ID, APPROVAL_ID))


def test_transaction_timestamps_are_monotonic() -> None:
    """Updated and completed timestamps may not move backwards."""
    with pytest.raises(ValidationError, match="updated_at must not precede"):
        make_transaction(updated_at=NOW - timedelta(microseconds=1))
    with pytest.raises(ValidationError, match="completed_at must not precede"):
        make_transaction(
            status=TransactionStatus.COMMITTED,
            updated_at=NOW + timedelta(seconds=1),
            completed_at=NOW,
        )


def test_awaiting_approval_requires_request_identifier() -> None:
    """An awaiting snapshot must identify the approval work it awaits."""
    with pytest.raises(ValidationError, match="requires an approval request"):
        make_transaction(status=TransactionStatus.AWAITING_APPROVAL)


@pytest.mark.parametrize(
    "status",
    [
        TransactionStatus.REJECTED,
        TransactionStatus.FAILED,
        TransactionStatus.PARTIALLY_COMPENSATED,
    ],
)
def test_failure_terminal_statuses_require_reason(status: TransactionStatus) -> None:
    """Failure-like terminal snapshots must explain their state."""
    with pytest.raises(ValidationError, match="requires a reason"):
        make_transaction(status=status, completed_at=NOW)


def test_terminal_and_nonterminal_completion_fields_are_consistent() -> None:
    """Terminal states need completion time and live states reject one."""
    with pytest.raises(ValidationError, match="requires completed_at"):
        make_transaction(status=TransactionStatus.COMMITTED)
    with pytest.raises(ValidationError, match="non-terminal"):
        make_transaction(completed_at=NOW)


def test_legal_transaction_transitions_return_new_snapshot() -> None:
    """The explicit state machine governs state without mutating snapshots."""
    proposed = make_transaction()
    validating = proposed.transition(
        TransactionStatus.VALIDATING,
        updated_at=NOW + timedelta(seconds=1),
    )
    awaiting = validating.transition(
        TransactionStatus.AWAITING_APPROVAL,
        approval_request_ids=(APPROVAL_ID,),
        updated_at=NOW + timedelta(seconds=2),
    )
    approved = awaiting.transition(
        TransactionStatus.APPROVED,
        updated_at=NOW + timedelta(seconds=3),
    )
    executing = approved.transition(
        TransactionStatus.EXECUTING,
        updated_at=NOW + timedelta(seconds=4),
    )
    committed = executing.transition(
        TransactionStatus.COMMITTED,
        updated_at=NOW + timedelta(seconds=5),
    )

    assert proposed.status is TransactionStatus.PROPOSED
    assert validating.status is TransactionStatus.VALIDATING
    assert awaiting.approval_request_ids == (APPROVAL_ID,)
    assert approved.status is TransactionStatus.APPROVED
    assert executing.status is TransactionStatus.EXECUTING
    assert committed.status is TransactionStatus.COMMITTED
    assert committed.completed_at == NOW + timedelta(seconds=5)
    assert committed.intents == proposed.intents


def test_failure_and_compensation_transitions_preserve_reason_fields() -> None:
    """Failure-like legal transitions require and retain an explicit reason."""
    failed = (
        make_transaction()
        .transition(TransactionStatus.VALIDATING, updated_at=NOW + timedelta(seconds=1))
        .transition(
            TransactionStatus.FAILED,
            updated_at=NOW + timedelta(seconds=2),
            status_reason="Validation failed.",
        )
    )
    partially_compensated = (
        make_transaction()
        .transition(TransactionStatus.VALIDATING, updated_at=NOW + timedelta(seconds=1))
        .transition(TransactionStatus.APPROVED, updated_at=NOW + timedelta(seconds=2))
        .transition(TransactionStatus.EXECUTING, updated_at=NOW + timedelta(seconds=3))
        .transition(
            TransactionStatus.COMPENSATING,
            updated_at=NOW + timedelta(seconds=4),
        )
        .transition(
            TransactionStatus.PARTIALLY_COMPENSATED,
            updated_at=NOW + timedelta(seconds=5),
            status_reason="One compensation failed.",
        )
    )

    assert failed.status is TransactionStatus.FAILED
    assert failed.status_reason == "Validation failed."
    assert failed.completed_at == NOW + timedelta(seconds=2)
    assert partially_compensated.status is TransactionStatus.PARTIALLY_COMPENSATED
    assert partially_compensated.status_reason == "One compensation failed."


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (TransactionStatus.PROPOSED, TransactionStatus.COMMITTED),
        (TransactionStatus.FAILED, TransactionStatus.EXECUTING),
        (TransactionStatus.REJECTED, TransactionStatus.APPROVED),
        (TransactionStatus.COMMITTED, TransactionStatus.EXECUTING),
        (TransactionStatus.VALIDATING, TransactionStatus.EXECUTING),
    ],
)
def test_illegal_transaction_transitions_are_rejected(
    current: TransactionStatus,
    requested: TransactionStatus,
) -> None:
    """Invalid edges raise a typed error before a new snapshot is created."""
    extras: dict[str, object] = {}
    if current in {
        TransactionStatus.FAILED,
        TransactionStatus.REJECTED,
    }:
        extras["status_reason"] = "Terminal."
        extras["completed_at"] = NOW
    elif current is TransactionStatus.COMMITTED:
        extras["completed_at"] = NOW

    transaction = make_transaction(status=current, **extras)

    with pytest.raises(IllegalTransactionTransitionError) as exc_info:
        transaction.transition(requested, updated_at=NOW + timedelta(seconds=1))

    assert exc_info.value.current_status is current
    assert exc_info.value.requested_status is requested


def test_transition_validates_required_target_state_metadata() -> None:
    """Legal transitions still validate target snapshot invariants."""
    validating = make_transaction().transition(
        TransactionStatus.VALIDATING,
        updated_at=NOW + timedelta(seconds=1),
    )

    with pytest.raises(ValidationError, match="requires an approval request"):
        validating.transition(
            TransactionStatus.AWAITING_APPROVAL,
            updated_at=NOW + timedelta(seconds=2),
        )
    with pytest.raises(ValidationError, match="requires a reason"):
        validating.transition(
            TransactionStatus.FAILED,
            updated_at=NOW + timedelta(seconds=2),
        )


def test_ledger_event_serializes_ordered_audit_data() -> None:
    """Ledger events retain correlation, aggregate, and JSON detail values."""
    event = LedgerEvent(
        event_id=EVENT_ID,
        correlation_id=CORRELATION_ID,
        sequence_number=1,
        event_type="transaction.proposed",
        occurred_at=NOW,
        transaction_id=TRANSACTION_ID,
        intent_id=INTENT_ID,
        actor_id="agent:test",
        details={"risk": "high", "tags": ["fake", "unit"]},
    )

    assert event.sequence_number == 1
    assert LedgerEvent.model_validate_json(event.model_dump_json()) == event


def test_ledger_sequence_starts_at_one_and_event_name_is_canonical() -> None:
    """Zero/negative sequences and malformed event names fail validation."""
    values = {
        "event_id": EVENT_ID,
        "correlation_id": CORRELATION_ID,
        "occurred_at": NOW,
    }
    with pytest.raises(ValidationError):
        LedgerEvent(sequence_number=0, event_type="transaction.proposed", **values)
    with pytest.raises(ValidationError):
        LedgerEvent(sequence_number=1, event_type="Transaction Proposed", **values)
