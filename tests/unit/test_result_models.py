"""Tests for execution and compensation result contracts."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from agentactum.compensation import CompensationResult
from agentactum.execution import ExecutionResult, FailureDetail

EXECUTION_ID = UUID("30000000-0000-4000-8000-000000000001")
COMPENSATION_ID = UUID("30000000-0000-4000-8000-000000000002")
TRANSACTION_ID = UUID("30000000-0000-4000-8000-000000000003")
INTENT_ID = UUID("30000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
ERROR = FailureDetail(code="tool_error", message="The fake tool failed.")


def make_execution(**overrides: object) -> ExecutionResult:
    """Build a successful execution while allowing selected fields to vary."""
    values: dict[str, object] = {
        "execution_id": EXECUTION_ID,
        "transaction_id": TRANSACTION_ID,
        "intent_id": INTENT_ID,
        "succeeded": True,
        "started_at": NOW,
        "completed_at": NOW + timedelta(seconds=1),
        "output": {"external_id": "fake-1"},
        "postcondition_verified": True,
    }
    values.update(overrides)
    return ExecutionResult(**values)  # type: ignore[arg-type]


def make_compensation(**overrides: object) -> CompensationResult:
    """Build a successful compensation while allowing selected fields to vary."""
    values: dict[str, object] = {
        "compensation_id": COMPENSATION_ID,
        "execution_id": EXECUTION_ID,
        "transaction_id": TRANSACTION_ID,
        "intent_id": INTENT_ID,
        "succeeded": True,
        "started_at": NOW,
        "completed_at": NOW + timedelta(seconds=1),
        "output": {"restored": True},
    }
    values.update(overrides)
    return CompensationResult(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("verified", [True, None])
def test_successful_execution_is_serializable(verified: bool | None) -> None:
    """Success supports an optional verifier and nested JSON output."""
    result = make_execution(postcondition_verified=verified)

    assert result.error is None
    assert ExecutionResult.model_validate_json(result.model_dump_json()) == result


def test_failed_execution_requires_structured_error() -> None:
    """A failed execution carries a sanitized explicit error model."""
    result = make_execution(
        succeeded=False,
        error=ERROR,
        postcondition_verified=False,
    )

    assert result.error == ERROR
    with pytest.raises(ValidationError, match="requires an error"):
        make_execution(succeeded=False, postcondition_verified=None)


def test_execution_rejects_incoherent_success_fields() -> None:
    """Success cannot contain an error or a failed postcondition."""
    with pytest.raises(ValidationError, match="cannot contain an error"):
        make_execution(error=ERROR)
    with pytest.raises(ValidationError, match="cannot fail its postcondition"):
        make_execution(postcondition_verified=False)


def test_execution_completion_must_follow_start() -> None:
    """An execution result cannot finish before it starts."""
    with pytest.raises(ValidationError, match="must not precede"):
        make_execution(completed_at=NOW - timedelta(microseconds=1))


def test_successful_compensation_is_serializable() -> None:
    """A successful compensation round-trips without an error."""
    result = make_compensation()

    assert result.error is None
    assert CompensationResult.model_validate_json(result.model_dump_json()) == result


def test_failed_compensation_requires_structured_error() -> None:
    """Failed compensation requires a safe explicit failure detail."""
    result = make_compensation(succeeded=False, error=ERROR)

    assert result.error == ERROR
    with pytest.raises(ValidationError, match="requires an error"):
        make_compensation(succeeded=False)


def test_compensation_rejects_error_on_success_and_backwards_time() -> None:
    """Compensation success/error and timestamps remain coherent."""
    with pytest.raises(ValidationError, match="cannot contain an error"):
        make_compensation(error=ERROR)
    with pytest.raises(ValidationError, match="must not precede"):
        make_compensation(completed_at=NOW - timedelta(microseconds=1))
