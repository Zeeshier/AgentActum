"""Tests for reverse-order compensation coordination."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import JsonValue

from agentactum.compensation import (
    CompensationCoordinator,
    CompensationPlan,
    CompensationSummaryStatus,
)
from agentactum.enums import EffectType
from agentactum.execution import ExecutionResult, FailureDetail
from agentactum.ledger import InMemoryLedger

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
TRANSACTION_ID = UUID("80000000-0000-4000-8000-000000000001")


def make_execution(index: int, *, succeeded: bool = True) -> ExecutionResult:
    """Build an execution result for compensation tests."""
    intent_id = UUID(f"80000000-0000-4000-8000-{index:012d}")
    execution_id = UUID(f"80000000-0000-4000-9000-{index:012d}")
    if succeeded:
        return ExecutionResult(
            execution_id=execution_id,
            transaction_id=TRANSACTION_ID,
            intent_id=intent_id,
            succeeded=True,
            started_at=NOW + timedelta(seconds=index),
            completed_at=NOW + timedelta(seconds=index, milliseconds=1),
            output={"step": index},
            postcondition_verified=True,
        )
    return ExecutionResult(
        execution_id=execution_id,
        transaction_id=TRANSACTION_ID,
        intent_id=intent_id,
        succeeded=False,
        started_at=NOW + timedelta(seconds=index),
        completed_at=NOW + timedelta(seconds=index, milliseconds=1),
        error=FailureDetail(code="tool_failed", message="The fake action failed."),
        postcondition_verified=False,
    )


def compensator_for(name: str, calls: list[str]) -> object:
    """Return a compensator that records call order."""

    def compensate(_execution: ExecutionResult) -> JsonValue:
        calls.append(name)
        return {"compensated": name}

    return compensate


def failing_compensator(name: str, calls: list[str]) -> object:
    """Return a compensator that records and fails."""

    def compensate(_execution: ExecutionResult) -> JsonValue:
        calls.append(name)
        raise RuntimeError("compensation failed")

    return compensate


def test_successful_compensation_runs_in_reverse_execution_order() -> None:
    """After C fails, B is compensated before A."""
    calls: list[str] = []
    failed_c = make_execution(3, succeeded=False)
    plans = [
        CompensationPlan(
            execution=make_execution(1),
            effect_type=EffectType.REVERSIBLE,
            compensator=compensator_for("A", calls),  # type: ignore[arg-type]
        ),
        CompensationPlan(
            execution=make_execution(2),
            effect_type=EffectType.REVERSIBLE,
            compensator=compensator_for("B", calls),  # type: ignore[arg-type]
        ),
    ]

    summary = CompensationCoordinator().compensate(
        plans,
        failed_execution=failed_c,
    )

    assert calls == ["B", "A"]
    assert summary.status is CompensationSummaryStatus.COMPENSATED
    assert [result.succeeded for result in summary.results] == [True, True]
    assert summary.uncompensated_executions == ()


def test_compensation_failure_is_recorded_without_claiming_rollback() -> None:
    """A failed compensator creates an explicit failed compensation result."""
    calls: list[str] = []
    plan = CompensationPlan(
        execution=make_execution(1),
        effect_type=EffectType.REVERSIBLE,
        compensator=failing_compensator("A", calls),  # type: ignore[arg-type]
    )

    summary = CompensationCoordinator().compensate([plan])

    assert calls == ["A"]
    assert summary.status is CompensationSummaryStatus.FAILED
    assert summary.results[0].succeeded is False
    assert summary.results[0].error
    assert summary.results[0].error.code == "compensation_failed"


def test_partial_compensation_reports_successes_and_failures() -> None:
    """If B compensates and A fails, the summary is partial."""
    calls: list[str] = []
    plans = [
        CompensationPlan(
            execution=make_execution(1),
            effect_type=EffectType.REVERSIBLE,
            compensator=failing_compensator("A", calls),  # type: ignore[arg-type]
        ),
        CompensationPlan(
            execution=make_execution(2),
            effect_type=EffectType.REVERSIBLE,
            compensator=compensator_for("B", calls),  # type: ignore[arg-type]
        ),
    ]

    summary = CompensationCoordinator().compensate(plans)

    assert calls == ["B", "A"]
    assert summary.status is CompensationSummaryStatus.PARTIALLY_COMPENSATED
    assert [result.succeeded for result in summary.results] == [True, False]


def test_irreversible_actions_are_not_compensated_and_are_reported() -> None:
    """Irreversible effects are marked uncompensated rather than rolled back."""
    calls: list[str] = []
    irreversible = make_execution(1)
    plan = CompensationPlan(
        execution=irreversible,
        effect_type=EffectType.IRREVERSIBLE,
        compensator=compensator_for("A", calls),  # type: ignore[arg-type]
    )

    summary = CompensationCoordinator().compensate([plan])

    assert calls == []
    assert summary.status is CompensationSummaryStatus.FAILED
    assert summary.uncompensated_executions == (irreversible,)


def test_missing_compensator_and_skipped_effects_do_not_invoke_callbacks() -> None:
    """Only successful compensatable effects with a compensator are attempted."""
    calls: list[str] = []
    failed_execution = make_execution(4, succeeded=False)
    plans = [
        CompensationPlan(
            execution=make_execution(1),
            effect_type=EffectType.READ_ONLY,
            compensator=compensator_for("read", calls),  # type: ignore[arg-type]
        ),
        CompensationPlan(
            execution=make_execution(2),
            effect_type=EffectType.IDEMPOTENT,
            compensator=compensator_for("idempotent", calls),  # type: ignore[arg-type]
        ),
        CompensationPlan(
            execution=make_execution(3),
            effect_type=EffectType.REVERSIBLE,
            compensator=None,
        ),
        CompensationPlan(
            execution=failed_execution,
            effect_type=EffectType.REVERSIBLE,
            compensator=compensator_for("failed", calls),  # type: ignore[arg-type]
        ),
    ]

    summary = CompensationCoordinator().compensate(plans)

    assert calls == []
    assert summary.status is CompensationSummaryStatus.FAILED
    assert summary.uncompensated_executions == (make_execution(3),)


def test_no_compensation_required_summary_is_explicit() -> None:
    """An empty or read-only-only plan says compensation was not required."""
    summary = CompensationCoordinator().compensate(
        [
            CompensationPlan(
                execution=make_execution(1),
                effect_type=EffectType.READ_ONLY,
            ),
        ],
    )

    assert summary.status is CompensationSummaryStatus.NOT_REQUIRED
    assert summary.results == ()


def test_ledger_events_are_created_for_compensation_lifecycle() -> None:
    """The coordinator emits audit events for attempts, results, and summary."""
    ledger = InMemoryLedger()
    calls: list[str] = []
    failed_c = make_execution(3, succeeded=False)
    plans = [
        CompensationPlan(
            execution=make_execution(1),
            effect_type=EffectType.REVERSIBLE,
            compensator=compensator_for("A", calls),  # type: ignore[arg-type]
        ),
        CompensationPlan(
            execution=make_execution(2),
            effect_type=EffectType.IRREVERSIBLE,
        ),
    ]

    summary = CompensationCoordinator(ledger=ledger).compensate(
        plans,
        failed_execution=failed_c,
    )

    assert summary.status is CompensationSummaryStatus.PARTIALLY_COMPENSATED
    assert [event.event_type for event in ledger.list_events()] == [
        "compensation.started",
        "compensation.irreversible",
        "compensation.attempted",
        "compensation.succeeded",
        "compensation.completed",
    ]
    assert all(event.transaction_id == TRANSACTION_ID for event in ledger.list_events())
