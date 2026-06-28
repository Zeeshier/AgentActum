"""Reverse-order compensation coordination."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast
from uuid import uuid4

from pydantic import JsonValue

from agentactum.enums import EffectType
from agentactum.execution import ExecutionResult, FailureDetail
from agentactum.ledger import Ledger

from .models import CompensationResult

type Compensator = Callable[[ExecutionResult], JsonValue]

_COMPENSATABLE_EFFECTS = frozenset(
    {
        EffectType.REVERSIBLE,
        EffectType.COMPENSATABLE,
        EffectType.STAGEABLE,
    },
)


class CompensationSummaryStatus(StrEnum):
    """Overall outcome of a compensation run."""

    NOT_REQUIRED = "not_required"
    COMPENSATED = "compensated"
    PARTIALLY_COMPENSATED = "partially_compensated"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CompensationPlan:
    """A completed execution and optional way to compensate its effect."""

    execution: ExecutionResult
    effect_type: EffectType
    compensator: Compensator | None = None


@dataclass(frozen=True, slots=True)
class CompensationSummary:
    """Explicit result of best-effort compensation attempts."""

    status: CompensationSummaryStatus
    results: tuple[CompensationResult, ...]
    uncompensated_executions: tuple[ExecutionResult, ...]


class CompensationCoordinator:
    """Attempt best-effort compensation in reverse execution order."""

    def __init__(self, *, ledger: Ledger | None = None) -> None:
        """Create a compensation coordinator with an optional audit ledger."""
        self._ledger = ledger

    def compensate(
        self,
        plans: Iterable[CompensationPlan],
        *,
        failed_execution: ExecutionResult | None = None,
    ) -> CompensationSummary:
        """Compensate completed effects in reverse order without claiming rollback."""
        ordered_plans = tuple(plans)
        if failed_execution is not None:
            self._append_event(
                "compensation.started",
                failed_execution,
                details={"failed_execution_id": str(failed_execution.execution_id)},
            )

        results: list[CompensationResult] = []
        uncompensated: list[ExecutionResult] = []

        for plan in reversed(ordered_plans):
            if not plan.execution.succeeded:
                continue
            if plan.effect_type is EffectType.READ_ONLY:
                self._append_event("compensation.skipped_read_only", plan.execution)
                continue
            if plan.effect_type is EffectType.IRREVERSIBLE:
                uncompensated.append(plan.execution)
                self._append_event("compensation.irreversible", plan.execution)
                continue
            if plan.effect_type not in _COMPENSATABLE_EFFECTS:
                self._append_event(
                    "compensation.skipped_uncompensatable",
                    plan.execution,
                )
                continue
            if plan.compensator is None:
                uncompensated.append(plan.execution)
                self._append_event("compensation.missing_compensator", plan.execution)
                continue

            results.append(self._attempt_compensation(plan))

        status = _summarize_status(results=results, uncompensated=uncompensated)
        if failed_execution is not None:
            self._append_event(
                "compensation.completed",
                failed_execution,
                details={"status": status.value},
            )
        return CompensationSummary(
            status=status,
            results=tuple(results),
            uncompensated_executions=tuple(uncompensated),
        )

    def _attempt_compensation(self, plan: CompensationPlan) -> CompensationResult:
        started_at = datetime.now(UTC)
        self._append_event("compensation.attempted", plan.execution)
        compensator = cast(Compensator, plan.compensator)
        try:
            output = compensator(plan.execution)
        except Exception:
            result = CompensationResult(
                compensation_id=uuid4(),
                execution_id=plan.execution.execution_id,
                transaction_id=plan.execution.transaction_id,
                intent_id=plan.execution.intent_id,
                succeeded=False,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                error=FailureDetail(
                    code="compensation_failed",
                    message="Compensator raised an exception.",
                ),
            )
        else:
            result = CompensationResult(
                compensation_id=uuid4(),
                execution_id=plan.execution.execution_id,
                transaction_id=plan.execution.transaction_id,
                intent_id=plan.execution.intent_id,
                succeeded=True,
                started_at=started_at,
                completed_at=datetime.now(UTC),
                output=output,
            )

        self._append_event(
            "compensation.succeeded" if result.succeeded else "compensation.failed",
            plan.execution,
            details={"compensation_id": str(result.compensation_id)},
        )
        return result

    def _append_event(
        self,
        event_type: str,
        execution: ExecutionResult,
        *,
        details: dict[str, JsonValue] | None = None,
    ) -> None:
        if self._ledger is None:
            return
        self._ledger.append(
            correlation_id=execution.transaction_id,
            event_type=event_type,
            transaction_id=execution.transaction_id,
            intent_id=execution.intent_id,
            details=details,
        )


def _summarize_status(
    *,
    results: list[CompensationResult],
    uncompensated: list[ExecutionResult],
) -> CompensationSummaryStatus:
    if not results and not uncompensated:
        return CompensationSummaryStatus.NOT_REQUIRED
    if uncompensated:
        if results and any(result.succeeded for result in results):
            return CompensationSummaryStatus.PARTIALLY_COMPENSATED
        return CompensationSummaryStatus.FAILED
    if all(result.succeeded for result in results):
        return CompensationSummaryStatus.COMPENSATED
    if any(result.succeeded for result in results):
        return CompensationSummaryStatus.PARTIALLY_COMPENSATED
    return CompensationSummaryStatus.FAILED
