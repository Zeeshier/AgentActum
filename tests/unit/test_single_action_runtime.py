"""Tests for the single-action execution pipeline."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import JsonValue

from agentactum.contracts import ActionIntent, ToolContract, ToolRegistry
from agentactum.enums import EffectType, PolicyDecisionType, RiskLevel
from agentactum.execution import (
    SingleActionRuntime,
    StaticApprovalChecker,
)
from agentactum.execution.runtime import _validate_against_schema
from agentactum.idempotency import InMemoryIdempotencyBackend, create_key
from agentactum.ledger import InMemoryLedger
from agentactum.policies import PolicyDecision, PolicyEngine, ToolAllowDenyPolicy

from .test_enums_and_contracts import make_schema

CONTRACT_ID = UUID("60000000-0000-4000-8000-000000000001")
INTENT_ID = UUID("60000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


class RequireApprovalPolicy:
    """Test policy that requires approval."""

    def evaluate(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        context: dict[str, JsonValue],
    ) -> PolicyDecision:
        """Return a require-approval policy decision."""
        del context
        return PolicyDecision(
            decision_id=UUID("60000000-0000-4000-8000-000000000003"),
            intent_id=action.intent_id,
            decision_type=PolicyDecisionType.REQUIRE_APPROVAL,
            risk_level=contract.risk_level,
            policy_name="approval-test",
            policy_version="1.0.0",
            reason="Approval required for test.",
            decided_at=NOW,
        )


class FailingLedger:
    """Ledger test double that fails before an effect can be released."""

    def append(self, **_kwargs: object) -> object:
        """Raise for every append."""
        raise RuntimeError("ledger unavailable")

    def list_events(self) -> tuple[object, ...]:
        """Return no events."""
        return ()


class FailOnExecutionStartLedger(InMemoryLedger):
    """Ledger that fails immediately before handler release."""

    def append(self, **kwargs: object) -> object:
        """Fail on execution_started after prior events succeed."""
        if kwargs.get("event_type") == "execution_started":
            raise RuntimeError("ledger unavailable")
        return super().append(**kwargs)  # type: ignore[arg-type]


class RaisingApprovalChecker:
    """Approval checker that fails closed."""

    def is_approved(self, **_kwargs: object) -> bool:
        """Raise instead of approving."""
        raise RuntimeError("approval backend unavailable")


def refund_handler(**arguments: object) -> dict[str, object]:
    """Fake refund handler."""
    return {
        "refund_id": "REF-1",
        "payment_id": arguments["payment_id"],
        "amount": arguments["amount"],
    }


def make_refund_contract(**overrides: object) -> ToolContract:
    """Build a valid refund contract for runtime tests."""
    output_schema = make_schema("refund_output").model_copy(
        update={
            "document": {
                "type": "object",
                "properties": {
                    "refund_id": {"type": "string"},
                    "payment_id": {"type": "string"},
                    "amount": {"type": "integer", "minimum": 1},
                },
                "required": ["refund_id", "payment_id", "amount"],
            },
        },
    )
    values: dict[str, object] = {
        "contract_id": CONTRACT_ID,
        "name": "refund_payment",
        "version": "1.0.0",
        "description": "Refund a fake payment.",
        "effect_type": EffectType.IDEMPOTENT,
        "risk_level": RiskLevel.LOW,
        "input_schema": make_schema("refund_input").model_copy(
            update={
                "document": {
                    "type": "object",
                    "properties": {
                        "payment_id": {"type": "string"},
                        "amount": {"type": "integer", "minimum": 1},
                    },
                    "required": ["payment_id", "amount"],
                },
            },
        ),
        "output_schema": output_schema,
        "idempotency_key_required": True,
    }
    values.update(overrides)
    return ToolContract(**values)  # type: ignore[arg-type]


def make_action(**overrides: object) -> ActionIntent:
    """Build a valid refund action."""
    arguments = {"payment_id": "PAY-100", "amount": 250}
    values: dict[str, object] = {
        "intent_id": INTENT_ID,
        "contract_id": CONTRACT_ID,
        "tool_name": "refund_payment",
        "contract_version": "1.0.0",
        "requester_id": "agent:test",
        "arguments": arguments,
        "created_at": NOW,
        "idempotency_key": create_key(
            tool_name="refund_payment",
            arguments=arguments,
            fields=["payment_id", "amount"],
        ),
    }
    values.update(overrides)
    return ActionIntent(**values)  # type: ignore[arg-type]


def make_runtime(
    *,
    contract: ToolContract | None = None,
    handler: object = refund_handler,
    policy_engine: PolicyEngine | None = None,
    ledger: InMemoryLedger | None = None,
    idempotency_backend: InMemoryIdempotencyBackend | None = None,
    approval_checker: object | None = None,
    preconditions: tuple[object, ...] = (),
    postconditions: tuple[object, ...] = (),
) -> tuple[SingleActionRuntime, list[dict[str, object]], InMemoryLedger]:
    """Build a runtime with a counting fake handler."""
    calls: list[dict[str, object]] = []
    registry = ToolRegistry()
    runtime_contract = contract or make_refund_contract()

    def counting_handler(**arguments: object) -> object:
        calls.append(arguments)
        if callable(handler):
            return handler(**arguments)
        return handler

    registry.register(runtime_contract, counting_handler)
    runtime_ledger = ledger or InMemoryLedger(clock=_clock())
    runtime = SingleActionRuntime(
        registry=registry,
        policy_engine=policy_engine or PolicyEngine(),
        idempotency_backend=idempotency_backend
        or InMemoryIdempotencyBackend(clock=_clock()),
        ledger=runtime_ledger,
        approval_checker=approval_checker,  # type: ignore[arg-type]
        preconditions=preconditions,  # type: ignore[arg-type]
        postconditions=postconditions,  # type: ignore[arg-type]
        clock=_clock(),
    )
    return runtime, calls, runtime_ledger


def test_single_action_success_writes_ledger_and_completes_idempotency() -> None:
    """A valid single action reaches the fake handler exactly once."""
    backend = InMemoryIdempotencyBackend(clock=_clock())
    runtime, calls, ledger = make_runtime(idempotency_backend=backend)
    action = make_action()

    result = runtime.execute(action=action, context={})

    assert result.succeeded is True
    assert result.output == {
        "refund_id": "REF-1",
        "payment_id": "PAY-100",
        "amount": 250,
    }
    assert calls == [{"payment_id": "PAY-100", "amount": 250}]
    assert backend.get_record(action.idempotency_key).result is not None
    assert [event.event_type for event in ledger.list_events()] == [
        "action_received",
        "contract_validated",
        "policy_evaluated",
        "execution_started",
        "execution_succeeded",
    ]


def test_unknown_tool_fails_without_execution() -> None:
    """Unknown tools are denied before any handler can run."""
    registry = ToolRegistry()
    runtime = SingleActionRuntime(
        registry=registry,
        policy_engine=PolicyEngine(),
        ledger=InMemoryLedger(clock=_clock()),
        clock=_clock(),
    )

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "unknown_tool"


def test_contract_mismatch_fails_without_execution() -> None:
    """A caller cannot pair an action with a different registered contract."""
    runtime, calls, _ledger = make_runtime()
    action = make_action(contract_version="2.0.0")

    result = runtime.execute(action=action, context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "contract_mismatch"
    assert calls == []


def test_input_validation_failure_fails_without_execution() -> None:
    """Invalid input fails before policy and execution."""
    runtime, calls, _ledger = make_runtime()
    action = make_action(arguments={"payment_id": "PAY-100", "amount": 0})

    result = runtime.execute(action=action, context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "input_validation_failed"
    assert calls == []


def test_policy_denial_fails_without_execution() -> None:
    """A deny policy blocks execution."""
    runtime, calls, _ledger = make_runtime(
        policy_engine=PolicyEngine(
            [ToolAllowDenyPolicy(denied_tools=["refund_payment"])],
        ),
    )

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "policy_denied"
    assert calls == []


def test_missing_approval_fails_without_execution() -> None:
    """Approval-required decisions do not execute without trusted approval."""
    runtime, calls, _ledger = make_runtime(
        policy_engine=PolicyEngine([RequireApprovalPolicy()]),
    )

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "approval_required"
    assert calls == []


def test_approval_checker_exception_fails_closed_without_execution() -> None:
    """Approval checker errors do not authorize execution."""
    runtime, calls, _ledger = make_runtime(
        policy_engine=PolicyEngine([RequireApprovalPolicy()]),
        approval_checker=RaisingApprovalChecker(),
    )

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "approval_required"
    assert calls == []


def test_static_approval_allows_approved_intent_to_execute() -> None:
    """A trusted approval checker can satisfy an approval-required decision."""
    action = make_action()
    runtime, calls, _ledger = make_runtime(
        policy_engine=PolicyEngine([RequireApprovalPolicy()]),
        approval_checker=StaticApprovalChecker([action.intent_id]),
    )

    result = runtime.execute(action=action, context={})

    assert result.succeeded is True
    assert len(calls) == 1


def test_missing_idempotency_key_fails_without_execution() -> None:
    """Contracts requiring idempotency reject actions without a key."""
    runtime, calls, _ledger = make_runtime()

    result = runtime.execute(action=make_action(idempotency_key=None), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "idempotency_key_missing"
    assert calls == []


def test_optional_idempotency_key_can_execute_without_claim() -> None:
    """A contract may opt out of idempotency-key requirement for one action."""
    runtime, calls, _ledger = make_runtime(
        contract=make_refund_contract(idempotency_key_required=False),
    )

    result = runtime.execute(action=make_action(idempotency_key=None), context={})

    assert result.succeeded is True
    assert len(calls) == 1


def test_duplicate_in_progress_key_fails_without_execution() -> None:
    """An in-progress duplicate observes the existing claim and does not run."""
    backend = InMemoryIdempotencyBackend(clock=_clock())
    action = make_action()
    backend.claim(action.idempotency_key)
    runtime, calls, _ledger = make_runtime(idempotency_backend=backend)

    result = runtime.execute(action=action, context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "idempotency_in_progress"
    assert calls == []


def test_duplicate_idempotency_key_replays_without_second_side_effect() -> None:
    """The same idempotency key does not call the handler twice."""
    runtime, calls, _ledger = make_runtime()
    action = make_action()

    first = runtime.execute(action=action, context={})
    second = runtime.execute(action=action, context={})

    assert first == second
    assert len(calls) == 1


def test_precondition_exception_fails_without_execution() -> None:
    """Precondition exceptions fail closed before the handler."""

    def raises(
        _action: ActionIntent,
        _contract: ToolContract,
        _context: object,
    ) -> bool:
        raise RuntimeError("precondition exploded")

    runtime, calls, _ledger = make_runtime(preconditions=(raises,))

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "precondition_failed"
    assert calls == []


def test_passing_preconditions_and_postconditions_continue_execution() -> None:
    """Passing checks do not block execution and can be chained."""
    runtime, calls, _ledger = make_runtime(
        preconditions=(
            lambda _action, _contract, _context: True,
            lambda _action, _contract, _context: True,
        ),
        postconditions=(
            lambda _action, _contract, _context: True,
            lambda _action, _contract, _context: True,
        ),
    )

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is True
    assert len(calls) == 1


def test_precondition_failure_fails_without_execution() -> None:
    """Precondition failure blocks the handler."""
    runtime, calls, _ledger = make_runtime(
        preconditions=(lambda _action, _contract, _context: False,),
    )

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "precondition_failed"
    assert calls == []


def test_executor_exception_is_structured_and_claimed() -> None:
    """Handler exceptions become structured failure results and are replayed."""

    def exploding_handler(**_arguments: object) -> object:
        raise RuntimeError("boom")

    runtime, calls, _ledger = make_runtime(handler=exploding_handler)
    action = make_action()

    first = runtime.execute(action=action, context={})
    second = runtime.execute(action=action, context={})

    assert first == second
    assert first.error and first.error.code == "tool_execution_failed"
    assert len(calls) == 1


def test_output_validation_failure_records_failure_after_execution() -> None:
    """Malformed output fails after the fake handler has run once."""
    runtime, calls, _ledger = make_runtime(handler={"refund_id": "REF-1"})

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "output_validation_failed"
    assert len(calls) == 1


def test_output_validation_failure_with_non_json_output_omits_output() -> None:
    """Non-JSON output is not copied into the failure result."""
    runtime, calls, _ledger = make_runtime(handler=object())

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "output_validation_failed"
    assert result.output is None
    assert len(calls) == 1


def test_postcondition_exception_records_failure_after_execution() -> None:
    """Postcondition exceptions fail closed after handler execution."""

    def raises(
        _action: ActionIntent,
        _contract: ToolContract,
        _context: object,
    ) -> bool:
        raise RuntimeError("postcondition exploded")

    runtime, calls, _ledger = make_runtime(postconditions=(raises,))

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "postcondition_failed"
    assert len(calls) == 1


def test_postcondition_failure_records_failure_after_execution() -> None:
    """Postcondition failure is reported after handler execution."""
    runtime, calls, _ledger = make_runtime(
        postconditions=(lambda _action, _contract, _context: False,),
    )

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "postcondition_failed"
    assert len(calls) == 1


def test_ledger_failure_before_resolution_fails_without_execution() -> None:
    """Ledger failure before tool resolution prevents execution."""
    runtime, calls, _ledger = make_runtime(ledger=FailingLedger())  # type: ignore[arg-type]

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "ledger_error"
    assert calls == []


def test_ledger_failure_before_execution_start_fails_without_execution() -> None:
    """A pre-effect ledger failure blocks handler release after admission."""
    runtime, calls, _ledger = make_runtime(
        ledger=FailOnExecutionStartLedger(clock=_clock()),
    )

    result = runtime.execute(action=make_action(), context={})

    assert result.succeeded is False
    assert result.error and result.error.code == "ledger_error"
    assert calls == []


def test_in_memory_ledger_default_clock_is_aware_utc() -> None:
    """The default ledger clock records timezone-aware UTC timestamps."""
    event = InMemoryLedger().append(
        correlation_id=INTENT_ID,
        event_type="action_received",
    )

    assert event.occurred_at.tzinfo is UTC


def test_schema_validator_reports_supported_failure_shapes() -> None:
    """The internal schema subset fails closed for unsupported or malformed data."""
    cases = [
        ([], {"type": "object"}, "$ must be an object"),
        ({}, {"type": "object", "required": ["amount"]}, "$.amount is required"),
        (1, {"type": "string"}, "$ must be a string"),
        (True, {"type": "integer"}, "$ must be an integer"),
        ("1", {"type": "number"}, "$ must be a number"),
        ("true", {"type": "boolean"}, "$ must be a boolean"),
        ({}, {"type": "array"}, "$ must be an array"),
        ("x", {"type": "null"}, "$ has unsupported schema type"),
        ({"x": object()}, {"type": "object"}, "$ must be JSON serializable"),
    ]

    for value, schema, expected in cases:
        assert _validate_against_schema(value, schema) == expected


def test_schema_validator_accepts_ignored_malformed_optional_schema_sections() -> None:
    """Unknown optional schema shapes are ignored rather than treated as authority."""
    assert (
        _validate_against_schema(
            {"amount": 2},
            {
                "type": "object",
                "required": "amount",
                "properties": "not-a-dict",
            },
        )
        is None
    )


def test_schema_validator_accepts_successful_branch_shapes() -> None:
    """Valid values cover supported schema branches without errors."""
    valid_cases = [
        (
            {"amount": 2},
            {"type": "object", "properties": {"amount": {"type": "integer"}}},
        ),
        (
            {"other": 2},
            {"type": "object", "properties": {"amount": {"type": "integer"}}},
        ),
        (2.5, {"type": "number", "minimum": 1}),
        (True, {"type": "boolean"}),
        ([], {"type": "array"}),
        ({}, {"type": "object", "properties": {}}),
        ("anything", {}),
    ]

    for value, schema in valid_cases:
        assert _validate_against_schema(value, schema) is None


def test_runtime_default_clock_can_return_failure_result() -> None:
    """The runtime default clock is used when no explicit clock is supplied."""
    runtime = SingleActionRuntime(
        registry=ToolRegistry(),
        policy_engine=PolicyEngine(),
    )

    result = runtime.execute(action=make_action(), context={})

    assert result.completed_at.tzinfo is UTC


def _clock() -> object:
    moments = iter(NOW + timedelta(microseconds=offset) for offset in range(1_000))
    return lambda: next(moments)
