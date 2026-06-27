"""Tests for idempotency key creation and in-memory claims."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

import agentactum.idempotency as idempotency
from agentactum.idempotency import (
    IdempotencyOwnershipError,
    IdempotencyRecord,
    IdempotencyRecordStatus,
    InMemoryIdempotencyBackend,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def test_create_key_matches_required_usage_and_is_stable() -> None:
    """The public key helper supports the milestone's required call shape."""
    key = idempotency.create_key(
        tool_name="refund_payment",
        arguments={
            "payment_id": "PAY-100",
            "amount": 250,
        },
        fields=["payment_id", "amount"],
    )
    repeated = idempotency.create_key(
        tool_name="refund_payment",
        arguments={
            "amount": 250,
            "ignored": "trace-only",
            "payment_id": "PAY-100",
        },
        fields=["payment_id", "amount"],
    )

    assert key == repeated
    assert key.startswith("agentactum:v1:refund_payment:")
    assert len(key.removeprefix("agentactum:v1:refund_payment:")) == 64


def test_create_key_changes_for_selected_semantic_values() -> None:
    """A changed selected field or tool name produces a different key."""
    base = idempotency.create_key(
        tool_name="refund_payment",
        arguments={"payment_id": "PAY-100", "amount": 250},
        fields=["payment_id", "amount"],
    )
    changed_amount = idempotency.create_key(
        tool_name="refund_payment",
        arguments={"payment_id": "PAY-100", "amount": 251},
        fields=["payment_id", "amount"],
    )
    changed_tool = idempotency.create_key(
        tool_name="void_payment",
        arguments={"payment_id": "PAY-100", "amount": 250},
        fields=["payment_id", "amount"],
    )

    assert changed_amount != base
    assert changed_tool != base


@pytest.mark.parametrize(
    ("tool_name", "arguments", "fields", "error"),
    [
        (" ", {"payment_id": "PAY-100"}, ["payment_id"], "tool_name"),
        ("refund_payment", {"payment_id": "PAY-100"}, [], "fields"),
        (
            "refund_payment",
            {"payment_id": "PAY-100"},
            ["payment_id", "payment_id"],
            "duplicates",
        ),
        ("refund_payment", {"payment_id": "PAY-100"}, [" "], "blank"),
    ],
)
def test_create_key_rejects_ambiguous_key_material(
    tool_name: str,
    arguments: dict[str, object],
    fields: list[str],
    error: str,
) -> None:
    """Blank, empty, or duplicate key material is rejected."""
    with pytest.raises(idempotency.IdempotencyKeyError, match=error):
        idempotency.create_key(
            tool_name=tool_name,
            arguments=arguments,  # type: ignore[arg-type]
            fields=fields,
        )


def test_create_key_rejects_missing_and_non_json_values() -> None:
    """All selected fields must exist and serialize as strict JSON."""
    with pytest.raises(idempotency.MissingIdempotencyFieldError) as exc_info:
        idempotency.create_key(
            tool_name="refund_payment",
            arguments={"payment_id": "PAY-100"},
            fields=["payment_id", "amount"],
        )
    assert exc_info.value.field == "amount"

    with pytest.raises(ValueError):
        idempotency.create_key(
            tool_name="refund_payment",
            arguments={"payment_id": "PAY-100", "amount": float("nan")},
            fields=["payment_id", "amount"],
        )

    with pytest.raises(TypeError):
        idempotency.create_key(
            tool_name="refund_payment",
            arguments={"payment_id": object()},
            fields=["payment_id"],
        )


def test_backend_first_claim_acquires_and_duplicate_observes_existing_record() -> None:
    """A duplicated key cannot acquire a second release token."""
    backend = InMemoryIdempotencyBackend(clock=lambda: NOW)
    key = idempotency.create_key(
        tool_name="refund_payment",
        arguments={"payment_id": "PAY-100", "amount": 250},
        fields=["payment_id", "amount"],
    )

    first = backend.claim(key)
    second = backend.claim(key)

    assert first.acquired is True
    assert second.acquired is False
    assert second.record == first.record
    assert first.record.status is IdempotencyRecordStatus.IN_PROGRESS
    assert backend.get_record(key) == first.record


def test_backend_default_clock_uses_aware_utc_time() -> None:
    """The default in-memory backend clock records timezone-aware UTC values."""
    claim = InMemoryIdempotencyBackend().claim(
        "agentactum:v1:refund_payment:" + "c" * 64,
    )

    assert claim.record.claimed_at.tzinfo is UTC


def test_backend_can_mark_owner_completed_and_replay_completed_record() -> None:
    """Completion is stored once and subsequent claims observe that terminal data."""
    moments = iter([NOW, NOW + timedelta(seconds=5), NOW + timedelta(seconds=10)])
    backend = InMemoryIdempotencyBackend(clock=lambda: next(moments))
    first = backend.claim("agentactum:v1:refund_payment:" + "a" * 64)

    completed = backend.mark_completed(
        first.record.key,
        owner_token=first.record.owner_token,
        result_reference="execution:success:1",
    )
    repeated_completion = backend.mark_completed(
        first.record.key,
        owner_token=first.record.owner_token,
        result_reference="execution:success:2",
    )
    duplicate = backend.claim(first.record.key)

    assert completed.status is IdempotencyRecordStatus.COMPLETED
    assert completed.completed_at == NOW + timedelta(seconds=5)
    assert completed.result_reference == "execution:success:1"
    assert repeated_completion == completed
    assert duplicate.acquired is False
    assert duplicate.record == completed


def test_backend_rejects_completion_by_non_owner() -> None:
    """Only the token that acquired a key can mark it completed."""
    backend = InMemoryIdempotencyBackend(clock=lambda: NOW)
    first = backend.claim("agentactum:v1:refund_payment:" + "a" * 64)

    with pytest.raises(IdempotencyOwnershipError) as exc_info:
        backend.mark_completed(first.record.key, owner_token=uuid4())

    assert exc_info.value.key == first.record.key
    assert backend.get_record(first.record.key) == first.record


def test_backend_claim_is_atomic_across_threads() -> None:
    """Concurrent duplicate claims produce one owner and no duplicate release token."""
    backend = InMemoryIdempotencyBackend(clock=lambda: NOW)
    key = "agentactum:v1:refund_payment:" + "b" * 64

    with ThreadPoolExecutor(max_workers=8) as executor:
        claims = list(executor.map(lambda _: backend.claim(key), range(32)))

    acquired = [claim for claim in claims if claim.acquired]
    observed = [claim for claim in claims if not claim.acquired]

    assert len(acquired) == 1
    assert len(observed) == 31
    assert {claim.record.owner_token for claim in claims} == {
        acquired[0].record.owner_token,
    }


def test_records_validate_completion_state_and_are_frozen() -> None:
    """Idempotency records reject inconsistent lifecycle state."""
    record = IdempotencyRecord(
        key="agentactum:v1:refund_payment:" + "a" * 64,
        owner_token=uuid4(),
        status=IdempotencyRecordStatus.IN_PROGRESS,
        claimed_at=NOW,
    )

    with pytest.raises(ValidationError, match="Instance is frozen"):
        record.status = IdempotencyRecordStatus.COMPLETED
    with pytest.raises(ValidationError, match="in-progress"):
        IdempotencyRecord(
            key=record.key,
            owner_token=record.owner_token,
            status=IdempotencyRecordStatus.IN_PROGRESS,
            claimed_at=NOW,
            completed_at=NOW,
        )
    with pytest.raises(ValidationError, match="completed records require"):
        IdempotencyRecord(
            key=record.key,
            owner_token=record.owner_token,
            status=IdempotencyRecordStatus.COMPLETED,
            claimed_at=NOW,
        )
    with pytest.raises(ValidationError, match="completed_at must not precede"):
        IdempotencyRecord(
            key=record.key,
            owner_token=record.owner_token,
            status=IdempotencyRecordStatus.COMPLETED,
            claimed_at=NOW,
            completed_at=NOW - timedelta(seconds=1),
        )
