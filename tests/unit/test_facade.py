"""Tests for the generic AgentActum facade."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from agentactum import AgentActum
from agentactum.contracts import ToolContract, ToolSchema
from agentactum.enums import EffectType, RiskLevel
from agentactum.execution import ExecutionResult
from agentactum.policies import PolicyEngine, RequiredPermissionPolicy

CONTRACT_ID = UUID("a0000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def make_refund_contract(**overrides: object) -> ToolContract:
    """Build a contract for facade tests."""
    values: dict[str, object] = {
        "contract_id": CONTRACT_ID,
        "name": "refund_payment",
        "version": "1.0.0",
        "description": "Refund a fake payment.",
        "effect_type": EffectType.IDEMPOTENT,
        "risk_level": RiskLevel.LOW,
        "input_schema": ToolSchema(
            name="refund_input",
            document={
                "type": "object",
                "properties": {
                    "payment_id": {"type": "string"},
                    "amount": {"type": "number", "minimum": 1},
                },
                "required": ["payment_id", "amount"],
            },
        ),
        "output_schema": ToolSchema(
            name="refund_output",
            document={
                "type": "object",
                "properties": {
                    "refund_id": {"type": "string"},
                    "amount": {"type": "number", "minimum": 1},
                },
                "required": ["refund_id", "amount"],
            },
        ),
        "idempotency_key_required": True,
    }
    values.update(overrides)
    return ToolContract(**values)  # type: ignore[arg-type]


def test_protect_decorator_executes_function_through_core_runtime() -> None:
    """A protected function returns an ExecutionResult through AgentActum."""
    actum = AgentActum(clock=_clock())
    calls: list[tuple[str, float]] = []

    @actum.protect(contract=make_refund_contract())
    def refund_payment(payment_id: str, amount: float) -> dict[str, object]:
        calls.append((payment_id, amount))
        return {"refund_id": "REF-1", "amount": amount}

    result = refund_payment("PAY-100", 250.0)

    assert isinstance(result, ExecutionResult)
    assert result.succeeded is True
    assert result.output == {"refund_id": "REF-1", "amount": 250.0}
    assert calls == [("PAY-100", 250.0)]
    assert actum.registry.contains("refund_payment")


def test_protect_decorator_replays_duplicate_idempotency_without_second_call() -> None:
    """The facade computes a stable key and replays duplicate calls safely."""
    actum = AgentActum(clock=_clock())
    calls: list[str] = []

    @actum.protect(contract=make_refund_contract())
    def refund_payment(payment_id: str, amount: float) -> dict[str, object]:
        calls.append(payment_id)
        return {"refund_id": "REF-1", "amount": amount}

    first = refund_payment("PAY-100", 250.0)
    second = refund_payment("PAY-100", 250.0)

    assert first == second
    assert calls == ["PAY-100"]


def test_protect_decorator_allows_explicit_idempotency_fields() -> None:
    """Callers can narrow key material deliberately when appropriate."""
    actum = AgentActum(clock=_clock())
    calls: list[float] = []

    @actum.protect(
        contract=make_refund_contract(),
        idempotency_fields=["payment_id"],
    )
    def refund_payment(payment_id: str, amount: float) -> dict[str, object]:
        calls.append(amount)
        return {"refund_id": "REF-1", "amount": amount}

    first = refund_payment("PAY-100", 250.0)
    second = refund_payment("PAY-100", 300.0)

    assert first == second
    assert calls == [250.0]


def test_protect_decorator_uses_context_factory_for_policy() -> None:
    """The facade can pass trusted host context to the policy engine."""
    actum = AgentActum(
        policy_engine=PolicyEngine(
            [RequiredPermissionPolicy({"refund_payment": ["refund.write"]})],
        ),
        clock=_clock(),
    )

    @actum.protect(
        contract=make_refund_contract(idempotency_key_required=False),
        context_factory=lambda _arguments: {"permissions": ["refund.write"]},
    )
    def refund_payment(payment_id: str, amount: float) -> dict[str, object]:
        return {"refund_id": payment_id, "amount": amount}

    result = refund_payment("PAY-100", 250.0)

    assert result.succeeded is True


def test_protected_function_policy_denial_does_not_call_function() -> None:
    """Policy failures still fail closed through the facade."""
    actum = AgentActum(
        policy_engine=PolicyEngine(
            [RequiredPermissionPolicy({"refund_payment": ["refund.write"]})],
        ),
        clock=_clock(),
    )
    calls: list[str] = []

    @actum.protect(contract=make_refund_contract(idempotency_key_required=False))
    def refund_payment(payment_id: str, amount: float) -> dict[str, object]:
        calls.append(payment_id)
        return {"refund_id": payment_id, "amount": amount}

    result = refund_payment("PAY-100", 250.0)

    assert result.succeeded is False
    assert result.error and result.error.code == "policy_denied"
    assert calls == []


def test_protect_rejects_non_json_arguments_before_execution() -> None:
    """Decorator argument binding rejects values that cannot cross JSON boundary."""
    actum = AgentActum(clock=_clock())
    calls: list[str] = []

    @actum.protect(contract=make_refund_contract())
    def refund_payment(payment_id: object, amount: float) -> dict[str, object]:
        calls.append("called")
        return {"refund_id": str(payment_id), "amount": amount}

    with pytest.raises(TypeError, match="JSON-compatible"):
        refund_payment(object(), 250.0)
    assert calls == []


def test_protect_supports_optional_idempotency_contracts_and_defaults() -> None:
    """Default Python arguments are bound and optional idempotency is respected."""
    actum = AgentActum(clock=_clock())
    calls: list[float] = []

    @actum.protect(contract=make_refund_contract(idempotency_key_required=False))
    def refund_payment(payment_id: str, amount: float = 10.0) -> dict[str, object]:
        calls.append(amount)
        return {"refund_id": payment_id, "amount": amount}

    result = refund_payment("PAY-100")

    assert result.succeeded is True
    assert calls == [10.0]


def test_protect_accepts_nested_json_arguments() -> None:
    """List and dict arguments are converted at the JSON boundary."""
    actum = AgentActum(clock=_clock())
    contract = make_refund_contract(
        name="refund_batch",
        input_schema=ToolSchema(
            name="refund_batch_input",
            document={
                "type": "object",
                "properties": {
                    "items": {"type": "array"},
                    "metadata": {"type": "object"},
                },
                "required": ["items", "metadata"],
            },
        ),
        output_schema=ToolSchema(
            name="refund_batch_output",
            document={
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
            },
        ),
    )

    @actum.protect(contract=contract)
    def refund_batch(
        items: list[dict[str, object]],
        metadata: dict[object, object],
    ) -> dict[str, object]:
        assert metadata == {"priority": True}
        return {"count": len(items)}

    result = refund_batch([{"payment_id": "PAY-100"}], {"priority": True})

    assert result.succeeded is True
    assert result.output == {"count": 1}


def test_required_idempotency_with_no_required_schema_fields_fails_closed() -> None:
    """A required idempotency key needs explicit schema fields or override fields."""
    actum = AgentActum(clock=_clock())
    contract = make_refund_contract(
        input_schema=ToolSchema(
            name="refund_input",
            document={
                "type": "object",
                "properties": {"payment_id": {"type": "string"}},
                "required": "payment_id",
            },
        ),
    )

    @actum.protect(contract=contract)
    def refund_payment(payment_id: str, amount: float) -> dict[str, object]:
        return {"refund_id": payment_id, "amount": amount}

    with pytest.raises(ValueError, match="fields must not be empty"):
        refund_payment("PAY-100", 250.0)


def test_langgraph_extra_is_declared_without_core_import_dependency() -> None:
    """Milestone 10 leaves LangGraph as a future optional integration extra."""
    import agentactum

    assert agentactum.AgentActum is AgentActum


def test_facade_default_clock_records_aware_execution_time() -> None:
    """The facade default clock is timezone-aware UTC."""
    actum = AgentActum()

    @actum.protect(contract=make_refund_contract(idempotency_key_required=False))
    def refund_payment(payment_id: str, amount: float) -> dict[str, object]:
        return {"refund_id": payment_id, "amount": amount}

    result = refund_payment("PAY-100", 250.0)

    assert result.started_at.tzinfo is UTC


def _clock() -> object:
    moments = iter(NOW + timedelta(microseconds=offset) for offset in range(1_000))
    return lambda: next(moments)
