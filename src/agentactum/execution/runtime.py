"""Single-action execution pipeline."""

import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID, uuid4

from pydantic import JsonValue

from agentactum._model import JsonObject
from agentactum.contracts import (
    ActionIntent,
    ToolContract,
    ToolRegistry,
    UnknownToolError,
)
from agentactum.enums import PolicyDecisionType
from agentactum.execution.models import ExecutionResult, FailureDetail
from agentactum.idempotency import (
    IdempotencyBackend,
    IdempotencyClaim,
    IdempotencyRecordStatus,
    InMemoryIdempotencyBackend,
)
from agentactum.ledger import InMemoryLedger, Ledger
from agentactum.policies import PolicyDecision, PolicyEngine

type RuntimeCheck = Callable[[ActionIntent, ToolContract, JsonObject], bool]


class ApprovalChecker(Protocol):
    """Boundary that answers whether an exact policy decision is approved."""

    def is_approved(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        decision: PolicyDecision,
        context: JsonObject,
    ) -> bool:
        """Return whether a pending action has trusted approval."""


class NoApprovalChecker:
    """Approval checker that denies every approval request."""

    def is_approved(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        decision: PolicyDecision,
        context: JsonObject,
    ) -> bool:
        """Deny approval for all actions."""
        del action, contract, decision, context
        return False


class StaticApprovalChecker:
    """Approval checker for tests and simple host-managed approvals."""

    def __init__(self, approved_intent_ids: Iterable[UUID]) -> None:
        """Create a checker that approves selected action intent ids."""
        self._approved_intent_ids = frozenset(approved_intent_ids)

    def is_approved(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        decision: PolicyDecision,
        context: JsonObject,
    ) -> bool:
        """Return whether the action intent id is in the approved set."""
        del contract, decision, context
        return action.intent_id in self._approved_intent_ids


class SingleActionRuntime:
    """Execute one registered action through safety gates."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        policy_engine: PolicyEngine,
        idempotency_backend: IdempotencyBackend | None = None,
        ledger: Ledger | None = None,
        approval_checker: ApprovalChecker | None = None,
        preconditions: Iterable[RuntimeCheck] = (),
        postconditions: Iterable[RuntimeCheck] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Create a single-action runtime from explicit components."""
        self._registry = registry
        self._policy_engine = policy_engine
        self._idempotency = idempotency_backend or InMemoryIdempotencyBackend()
        self._ledger = ledger or InMemoryLedger()
        self._approval_checker = approval_checker or NoApprovalChecker()
        self._preconditions = tuple(preconditions)
        self._postconditions = tuple(postconditions)
        self._clock = clock or _utc_now

    def execute(self, *, action: ActionIntent, context: JsonObject) -> ExecutionResult:
        """Run one action through resolution, policy, idempotency, and execution."""
        execution_id = uuid4()
        transaction_id = uuid4()
        started_at = self._clock()
        correlation_id = action.intent_id

        if not self._append_event(
            correlation_id=correlation_id,
            event_type="action_received",
            intent_id=action.intent_id,
            details={"tool_name": action.tool_name},
        ):
            return self._failure(
                execution_id=execution_id,
                transaction_id=transaction_id,
                intent_id=action.intent_id,
                started_at=started_at,
                code="ledger_error",
                message="Audit ledger failed before tool resolution.",
            )

        try:
            registered_tool = self._registry.get(action.tool_name)
        except UnknownToolError:
            decision = self._policy_engine.evaluate(
                action=action,
                contract=None,
                context=context,
            )
            self._append_event(
                correlation_id=correlation_id,
                event_type="tool_unknown",
                intent_id=action.intent_id,
                details={"decision_type": decision.decision_type.value},
            )
            return self._failure(
                execution_id=execution_id,
                transaction_id=transaction_id,
                intent_id=action.intent_id,
                started_at=started_at,
                code="unknown_tool",
                message=f"Tool is not registered: {action.tool_name}.",
            )

        contract = registered_tool.contract
        if not _action_matches_contract(action=action, contract=contract):
            self._append_event(
                correlation_id=correlation_id,
                event_type="contract_mismatch",
                intent_id=action.intent_id,
                details={"tool_name": action.tool_name},
            )
            return self._failure(
                execution_id=execution_id,
                transaction_id=transaction_id,
                intent_id=action.intent_id,
                started_at=started_at,
                code="contract_mismatch",
                message="Action intent does not match the registered contract.",
            )

        input_error = _validate_against_schema(
            action.arguments,
            contract.input_schema.document,
        )
        if input_error is not None:
            self._append_event(
                correlation_id=correlation_id,
                event_type="input_validation_failed",
                intent_id=action.intent_id,
                details={"message": input_error},
            )
            return self._failure(
                execution_id=execution_id,
                transaction_id=transaction_id,
                intent_id=action.intent_id,
                started_at=started_at,
                code="input_validation_failed",
                message=input_error,
            )

        self._append_event(
            correlation_id=correlation_id,
            event_type="contract_validated",
            intent_id=action.intent_id,
            details={"contract_id": str(contract.contract_id)},
        )

        decision = self._policy_engine.evaluate(
            action=action,
            contract=contract,
            context=context,
        )
        self._append_event(
            correlation_id=correlation_id,
            event_type="policy_evaluated",
            intent_id=action.intent_id,
            details={
                "decision_type": decision.decision_type.value,
                "risk_level": decision.risk_level.value,
            },
        )
        if decision.decision_type is PolicyDecisionType.DENY:
            return self._failure(
                execution_id=execution_id,
                transaction_id=transaction_id,
                intent_id=action.intent_id,
                started_at=started_at,
                code="policy_denied",
                message=decision.reason,
            )

        if decision.decision_type is PolicyDecisionType.REQUIRE_APPROVAL:
            try:
                approved = self._approval_checker.is_approved(
                    action=action,
                    contract=contract,
                    decision=decision,
                    context=context,
                )
            except Exception:
                approved = False
            if not approved:
                self._append_event(
                    correlation_id=correlation_id,
                    event_type="approval_required",
                    intent_id=action.intent_id,
                    details={"decision_id": str(decision.decision_id)},
                )
                return self._failure(
                    execution_id=execution_id,
                    transaction_id=transaction_id,
                    intent_id=action.intent_id,
                    started_at=started_at,
                    code="approval_required",
                    message="Approval is required before execution.",
                )

        if contract.idempotency_key_required and action.idempotency_key is None:
            self._append_event(
                correlation_id=correlation_id,
                event_type="idempotency_key_missing",
                intent_id=action.intent_id,
            )
            return self._failure(
                execution_id=execution_id,
                transaction_id=transaction_id,
                intent_id=action.intent_id,
                started_at=started_at,
                code="idempotency_key_missing",
                message="The registered contract requires an idempotency key.",
            )

        claim: IdempotencyClaim | None = None
        if action.idempotency_key is not None:
            claim = self._idempotency.claim(action.idempotency_key)
            if not claim.acquired:
                self._append_event(
                    correlation_id=correlation_id,
                    event_type="idempotency_replayed",
                    intent_id=action.intent_id,
                    details={"status": claim.record.status.value},
                )
                if (
                    claim.record.status is IdempotencyRecordStatus.COMPLETED
                    and claim.record.result is not None
                ):
                    return _decode_execution_result(claim.record.result)
                return self._failure(
                    execution_id=execution_id,
                    transaction_id=transaction_id,
                    intent_id=action.intent_id,
                    started_at=started_at,
                    code="idempotency_in_progress",
                    message=(
                        "An action with this idempotency key is already in progress."
                    ),
                )

        for precondition in self._preconditions:
            try:
                passed = precondition(action, contract, context)
            except Exception:
                passed = False
            if not passed:
                self._append_event(
                    correlation_id=correlation_id,
                    event_type="precondition_failed",
                    intent_id=action.intent_id,
                )
                result = self._failure(
                    execution_id=execution_id,
                    transaction_id=transaction_id,
                    intent_id=action.intent_id,
                    started_at=started_at,
                    code="precondition_failed",
                    message="A precondition failed before execution.",
                )
                self._complete_claim(claim, result)
                return result

        if not self._append_event(
            correlation_id=correlation_id,
            event_type="execution_started",
            intent_id=action.intent_id,
            transaction_id=transaction_id,
        ):
            result = self._failure(
                execution_id=execution_id,
                transaction_id=transaction_id,
                intent_id=action.intent_id,
                started_at=started_at,
                code="ledger_error",
                message="Audit ledger failed before execution.",
            )
            self._complete_claim(claim, result)
            return result

        try:
            raw_output = registered_tool.handler(**action.arguments)
        except Exception:
            result = self._failure(
                execution_id=execution_id,
                transaction_id=transaction_id,
                intent_id=action.intent_id,
                started_at=started_at,
                code="tool_execution_failed",
                message="Tool handler raised an exception.",
                postcondition_verified=False,
            )
            self._append_event(
                correlation_id=correlation_id,
                event_type="execution_failed",
                intent_id=action.intent_id,
                transaction_id=transaction_id,
                details={"code": result.error.code if result.error else "unknown"},
            )
            self._complete_claim(claim, result)
            return result

        output_error = _validate_against_schema(
            raw_output,
            contract.output_schema.document,
        )
        if output_error is not None:
            result = self._failure(
                execution_id=execution_id,
                transaction_id=transaction_id,
                intent_id=action.intent_id,
                started_at=started_at,
                code="output_validation_failed",
                message=output_error,
                output=_json_or_none(raw_output),
                postcondition_verified=False,
            )
            self._append_event(
                correlation_id=correlation_id,
                event_type="output_validation_failed",
                intent_id=action.intent_id,
                transaction_id=transaction_id,
                details={"message": output_error},
            )
            self._complete_claim(claim, result)
            return result

        for postcondition in self._postconditions:
            try:
                passed = postcondition(action, contract, context)
            except Exception:
                passed = False
            if not passed:
                result = self._failure(
                    execution_id=execution_id,
                    transaction_id=transaction_id,
                    intent_id=action.intent_id,
                    started_at=started_at,
                    code="postcondition_failed",
                    message="A postcondition failed after execution.",
                    output=_json_or_none(raw_output),
                    postcondition_verified=False,
                )
                self._append_event(
                    correlation_id=correlation_id,
                    event_type="postcondition_failed",
                    intent_id=action.intent_id,
                    transaction_id=transaction_id,
                )
                self._complete_claim(claim, result)
                return result

        result = ExecutionResult(
            execution_id=execution_id,
            transaction_id=transaction_id,
            intent_id=action.intent_id,
            succeeded=True,
            started_at=started_at,
            completed_at=self._clock(),
            output=_json_or_raise(value=raw_output, path="$"),
            postcondition_verified=True,
        )
        self._append_event(
            correlation_id=correlation_id,
            event_type="execution_succeeded",
            intent_id=action.intent_id,
            transaction_id=transaction_id,
        )
        self._complete_claim(claim, result)
        return result

    def _append_event(
        self,
        *,
        correlation_id: UUID,
        event_type: str,
        intent_id: UUID | None = None,
        transaction_id: UUID | None = None,
        details: JsonObject | None = None,
    ) -> bool:
        try:
            self._ledger.append(
                correlation_id=correlation_id,
                event_type=event_type,
                intent_id=intent_id,
                transaction_id=transaction_id,
                details=details,
            )
        except Exception:
            return False
        return True

    def _failure(
        self,
        *,
        execution_id: UUID,
        transaction_id: UUID,
        intent_id: UUID,
        started_at: datetime,
        code: str,
        message: str,
        output: JsonValue = None,
        postcondition_verified: bool | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            execution_id=execution_id,
            transaction_id=transaction_id,
            intent_id=intent_id,
            succeeded=False,
            started_at=started_at,
            completed_at=self._clock(),
            output=output,
            error=FailureDetail(code=code, message=message),
            postcondition_verified=postcondition_verified,
        )

    def _complete_claim(
        self,
        claim: IdempotencyClaim | None,
        result: ExecutionResult,
    ) -> None:
        if claim is None:
            return
        owner_token = claim.record.owner_token
        self._idempotency.mark_completed(
            claim.record.key,
            owner_token=owner_token,
            result_reference=str(result.execution_id),
            result=result.model_dump(mode="json"),
        )


class SchemaValidationError(ValueError):
    """Raised when a value does not satisfy the supported JSON Schema subset."""


def _action_matches_contract(*, action: ActionIntent, contract: ToolContract) -> bool:
    return (
        action.contract_id == contract.contract_id
        and action.tool_name == contract.name
        and action.contract_version == contract.version
    )


def _validate_against_schema(value: object, schema: JsonObject) -> str | None:
    try:
        _validate_value(value=value, schema=schema, path="$")
    except SchemaValidationError as exc:
        return str(exc)
    return None


def _validate_value(*, value: object, schema: JsonObject, path: str) -> None:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            raise SchemaValidationError(f"{path} must be an object")
        required = schema.get("required", [])
        if isinstance(required, list):
            for field in required:
                if isinstance(field, str) and field not in value:
                    raise SchemaValidationError(f"{path}.{field} is required")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for field, field_schema in properties.items():
                if (
                    isinstance(field, str)
                    and isinstance(field_schema, dict)
                    and field in value
                ):
                    _validate_value(
                        value=value[field],
                        schema=field_schema,
                        path=f"{path}.{field}",
                    )
    elif expected_type == "string":
        if not isinstance(value, str):
            raise SchemaValidationError(f"{path} must be a string")
    elif expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise SchemaValidationError(f"{path} must be an integer")
        _validate_minimum(value=value, schema=schema, path=path)
    elif expected_type == "number":
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise SchemaValidationError(f"{path} must be a number")
        _validate_minimum(value=value, schema=schema, path=path)
    elif expected_type == "boolean":
        if not isinstance(value, bool):
            raise SchemaValidationError(f"{path} must be a boolean")
    elif expected_type == "array":
        if not isinstance(value, list):
            raise SchemaValidationError(f"{path} must be an array")
    elif expected_type is not None:
        raise SchemaValidationError(f"{path} has unsupported schema type")
    _json_or_raise(value=value, path=path)


def _validate_minimum(*, value: int | float, schema: JsonObject, path: str) -> None:
    minimum = schema.get("minimum")
    if (
        isinstance(minimum, int | float)
        and not isinstance(minimum, bool)
        and value < minimum
    ):
        raise SchemaValidationError(f"{path} must be at least {minimum}")


def _json_or_none(value: object) -> JsonValue:
    try:
        return _json_or_raise(value=value, path="$")
    except SchemaValidationError:
        return None


def _json_or_raise(*, value: object, path: str) -> JsonValue:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError(f"{path} must be JSON serializable") from exc
    return cast(JsonValue, value)


def _decode_execution_result(value: JsonValue) -> ExecutionResult:
    return ExecutionResult.model_validate_json(
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True),
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)
