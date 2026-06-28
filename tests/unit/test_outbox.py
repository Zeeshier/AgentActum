"""Tests for the in-memory effect outbox."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from agentactum.execution import FailureDetail
from agentactum.ledger import InMemoryLedger
from agentactum.outbox import (
    InMemoryOutboxBackend,
    OutboxOperation,
    OutboxStatus,
    UnknownOutboxOperationError,
)

TRANSACTION_ID = UUID("90000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def test_stage_does_not_release_irreversible_operation_before_commit() -> None:
    """Staging a confirmation email records it without invoking the handler."""
    sent: list[str] = []
    outbox = InMemoryOutboxBackend(clock=_clock())

    operation = outbox.stage(
        transaction_id=TRANSACTION_ID,
        operation_name="confirmation_email",
        arguments={"email": "customer@example.test"},
        handler=lambda **arguments: sent.append(arguments["email"]),
    )

    assert operation.status is OutboxStatus.STAGED
    assert sent == []
    assert outbox.list_operations() == (operation,)


def test_release_all_after_transaction_commit_releases_confirmation_email() -> None:
    """Refund and CRM can succeed before commit releases the staged email."""
    sent: list[str] = []
    outbox = InMemoryOutboxBackend(clock=_clock())
    outbox.stage(
        transaction_id=TRANSACTION_ID,
        operation_name="confirmation_email",
        arguments={"email": "customer@example.test"},
        handler=lambda **arguments: sent.append(arguments["email"]) or {"sent": True},
    )

    summary = outbox.release_all(TRANSACTION_ID)

    assert sent == ["customer@example.test"]
    assert summary.succeeded is True
    assert summary.failed == ()
    assert summary.released[0].status is OutboxStatus.RELEASED
    assert summary.released[0].output == {"sent": True}


def test_release_is_idempotent_after_operation_is_terminal() -> None:
    """Releasing the same operation twice does not duplicate the side effect."""
    sent: list[str] = []
    outbox = InMemoryOutboxBackend(clock=_clock())
    operation = outbox.stage(
        transaction_id=TRANSACTION_ID,
        operation_name="confirmation_email",
        arguments={"email": "customer@example.test"},
        handler=lambda **arguments: sent.append(arguments["email"]) or {"sent": True},
    )

    first = outbox.release(operation.operation_id)
    second = outbox.release(operation.operation_id)

    assert first == second
    assert sent == ["customer@example.test"]


def test_release_failure_is_recorded_and_not_retried_by_default() -> None:
    """A failing staged operation becomes terminal failed evidence."""
    calls: list[str] = []

    def failing_handler(**_arguments: object) -> object:
        calls.append("email")
        raise RuntimeError("smtp down")

    outbox = InMemoryOutboxBackend(clock=_clock())
    operation = outbox.stage(
        transaction_id=TRANSACTION_ID,
        operation_name="confirmation_email",
        arguments={"email": "customer@example.test"},
        handler=failing_handler,
    )

    first = outbox.release(operation.operation_id)
    second = outbox.release(operation.operation_id)

    assert first.status is OutboxStatus.FAILED
    assert first.error
    assert first.error.code == "outbox_release_failed"
    assert second == first
    assert calls == ["email"]


def test_release_all_reports_failed_release() -> None:
    """Release summaries include failed staged operations."""
    outbox = InMemoryOutboxBackend(clock=_clock())
    outbox.stage(
        transaction_id=TRANSACTION_ID,
        operation_name="confirmation_email",
        arguments={"email": "customer@example.test"},
        handler=lambda **_arguments: (_ for _ in ()).throw(RuntimeError("smtp down")),
    )

    summary = outbox.release_all(TRANSACTION_ID)

    assert summary.succeeded is False
    assert summary.released == ()
    assert len(summary.failed) == 1


def test_release_all_reports_mixed_success_and_failure() -> None:
    """Release summaries can include both released and failed operations."""
    outbox = InMemoryOutboxBackend(clock=_clock())
    outbox.stage(
        transaction_id=TRANSACTION_ID,
        operation_name="audit_email",
        arguments={"email": "audit@example.test"},
        handler=lambda **_arguments: (_ for _ in ()).throw(RuntimeError("smtp down")),
    )
    outbox.stage(
        transaction_id=TRANSACTION_ID,
        operation_name="confirmation_email",
        arguments={"email": "customer@example.test"},
        handler=lambda **_arguments: {"sent": True},
    )

    summary = outbox.release_all(TRANSACTION_ID)

    assert summary.succeeded is False
    assert len(summary.released) == 1
    assert len(summary.failed) == 1


def test_release_all_filters_by_transaction() -> None:
    """Only operations for the committed transaction are released."""
    sent: list[str] = []
    other_transaction_id = UUID("90000000-0000-4000-8000-000000000002")
    outbox = InMemoryOutboxBackend(clock=_clock())
    outbox.stage(
        transaction_id=TRANSACTION_ID,
        operation_name="confirmation_email",
        arguments={"email": "first@example.test"},
        handler=lambda **arguments: sent.append(arguments["email"]),
    )
    outbox.stage(
        transaction_id=other_transaction_id,
        operation_name="confirmation_email",
        arguments={"email": "second@example.test"},
        handler=lambda **arguments: sent.append(arguments["email"]),
    )

    summary = outbox.release_all(TRANSACTION_ID)

    assert len(summary.released) == 1
    assert sent == ["first@example.test"]
    assert [operation.status for operation in outbox.list_operations()] == [
        OutboxStatus.RELEASED,
        OutboxStatus.STAGED,
    ]


def test_unknown_operation_and_invalid_handler_are_rejected() -> None:
    """Outbox operations must be staged with a callable before release."""
    outbox = InMemoryOutboxBackend(clock=_clock())

    with pytest.raises(TypeError, match="handler must be callable"):
        outbox.stage(
            transaction_id=TRANSACTION_ID,
            operation_name="confirmation_email",
            arguments={},
            handler=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(UnknownOutboxOperationError) as exc_info:
        outbox.release(uuid4())
    assert exc_info.value.operation_id


def test_outbox_operation_model_validates_status_fields() -> None:
    """Outbox records reject contradictory lifecycle data."""
    operation_id = uuid4()
    values = {
        "operation_id": operation_id,
        "transaction_id": TRANSACTION_ID,
        "operation_name": "confirmation_email",
        "arguments": {"email": "customer@example.test"},
        "staged_at": NOW,
    }

    with pytest.raises(ValidationError, match="staged"):
        OutboxOperation(
            **values,
            status=OutboxStatus.STAGED,
            output={"sent": True},
        )
    with pytest.raises(ValidationError, match="staged"):
        OutboxOperation(
            **values,
            status=OutboxStatus.STAGED,
            error=FailureDetail(code="unexpected", message="Unexpected error."),
        )
    with pytest.raises(ValidationError, match="released"):
        OutboxOperation(**values, status=OutboxStatus.RELEASED)
    with pytest.raises(ValidationError, match="cannot contain an error"):
        OutboxOperation(
            **values,
            status=OutboxStatus.RELEASED,
            released_at=NOW,
            error=FailureDetail(code="unexpected", message="Unexpected error."),
        )
    with pytest.raises(ValidationError, match="failed"):
        OutboxOperation(**values, status=OutboxStatus.FAILED)
    with pytest.raises(ValidationError, match="failed"):
        OutboxOperation(**values, status=OutboxStatus.FAILED, released_at=NOW)
    with pytest.raises(ValidationError, match="must not precede"):
        OutboxOperation(
            **values,
            status=OutboxStatus.RELEASED,
            released_at=NOW - timedelta(seconds=1),
        )


def test_outbox_writes_ledger_events_for_stage_and_release() -> None:
    """Outbox lifecycle events are visible in the append-only ledger."""
    ledger = InMemoryLedger(clock=_clock())
    outbox = InMemoryOutboxBackend(clock=_clock(), ledger=ledger)
    operation = outbox.stage(
        transaction_id=TRANSACTION_ID,
        operation_name="confirmation_email",
        arguments={"email": "customer@example.test"},
        handler=lambda **_arguments: {"sent": True},
    )

    outbox.release(operation.operation_id)

    assert [event.event_type for event in ledger.list_events()] == [
        "outbox.staged",
        "outbox.released",
    ]
    assert all(event.transaction_id == TRANSACTION_ID for event in ledger.list_events())


def test_outbox_writes_failure_ledger_event() -> None:
    """Failed releases are auditable."""
    ledger = InMemoryLedger(clock=_clock())
    outbox = InMemoryOutboxBackend(clock=_clock(), ledger=ledger)
    operation = outbox.stage(
        transaction_id=TRANSACTION_ID,
        operation_name="confirmation_email",
        arguments={"email": "customer@example.test"},
        handler=lambda **_arguments: (_ for _ in ()).throw(RuntimeError("smtp down")),
    )

    outbox.release(operation.operation_id)

    assert [event.event_type for event in ledger.list_events()] == [
        "outbox.staged",
        "outbox.release_failed",
    ]


def test_default_clock_records_aware_timestamps() -> None:
    """The default outbox clock is timezone-aware UTC."""
    operation = InMemoryOutboxBackend().stage(
        transaction_id=TRANSACTION_ID,
        operation_name="confirmation_email",
        arguments={},
        handler=lambda **_arguments: None,
    )

    assert operation.staged_at.tzinfo is UTC


def _clock() -> object:
    moments = iter(NOW + timedelta(microseconds=offset) for offset in range(1_000))
    return lambda: next(moments)
