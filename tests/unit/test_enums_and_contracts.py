"""Tests for enums, tool contracts, and action intents."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from agentactum.contracts import ActionIntent, ToolContract, ToolSchema
from agentactum.enums import (
    EffectType,
    PolicyDecisionType,
    RiskLevel,
    TransactionStatus,
)

CONTRACT_ID = UUID("00000000-0000-4000-8000-000000000001")
INTENT_ID = UUID("00000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def make_schema(name: str = "charge_input") -> ToolSchema:
    """Build a valid explicit schema for tests."""
    return ToolSchema(
        name=name,
        document={
            "type": "object",
            "properties": {"amount": {"type": "integer", "minimum": 1}},
            "required": ["amount"],
        },
    )


def make_contract(**overrides: object) -> ToolContract:
    """Build a contract while allowing one field to vary."""
    values: dict[str, object] = {
        "contract_id": CONTRACT_ID,
        "name": "payments.charge",
        "version": "1.0.0",
        "description": "Charge a fake payment account.",
        "effect_type": EffectType.IRREVERSIBLE,
        "risk_level": RiskLevel.HIGH,
        "input_schema": make_schema(),
        "output_schema": make_schema("charge_output"),
        "idempotency_key_required": True,
    }
    values.update(overrides)
    return ToolContract(**values)  # type: ignore[arg-type]


def make_intent(**overrides: object) -> ActionIntent:
    """Build an action intent while allowing one field to vary."""
    values: dict[str, object] = {
        "intent_id": INTENT_ID,
        "contract_id": CONTRACT_ID,
        "tool_name": "payments.charge",
        "contract_version": "1.0.0",
        "requester_id": "agent:test",
        "arguments": {"amount": 25},
        "created_at": NOW,
        "idempotency_key": "payment-123",
    }
    values.update(overrides)
    return ActionIntent(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("enum_type", "expected"),
    [
        (
            EffectType,
            {
                "READ_ONLY": "read_only",
                "IDEMPOTENT": "idempotent",
                "REVERSIBLE": "reversible",
                "COMPENSATABLE": "compensatable",
                "STAGEABLE": "stageable",
                "IRREVERSIBLE": "irreversible",
            },
        ),
        (
            RiskLevel,
            {
                "LOW": "low",
                "MEDIUM": "medium",
                "HIGH": "high",
                "CRITICAL": "critical",
            },
        ),
        (
            PolicyDecisionType,
            {
                "ALLOW": "allow",
                "DENY": "deny",
                "REQUIRE_APPROVAL": "require_approval",
                "ALLOW_WITH_CONSTRAINTS": "allow_with_constraints",
            },
        ),
        (
            TransactionStatus,
            {
                "PROPOSED": "proposed",
                "VALIDATING": "validating",
                "AWAITING_APPROVAL": "awaiting_approval",
                "APPROVED": "approved",
                "EXECUTING": "executing",
                "COMMITTED": "committed",
                "REJECTED": "rejected",
                "FAILED": "failed",
                "COMPENSATING": "compensating",
                "COMPENSATED": "compensated",
                "PARTIALLY_COMPENSATED": "partially_compensated",
            },
        ),
    ],
)
def test_enum_members_have_stable_string_values(
    enum_type: type[EffectType | RiskLevel | PolicyDecisionType | TransactionStatus],
    expected: dict[str, str],
) -> None:
    """All requested enum members serialize with explicit stable values."""
    assert {member.name: member.value for member in enum_type} == expected
    assert all(str(member) == member.value for member in enum_type)


def test_unknown_and_untyped_enum_values_fail_closed() -> None:
    """Unknown values and raw strings do not bypass strict enum validation."""
    with pytest.raises(ValueError):
        EffectType("unknown")
    with pytest.raises(ValidationError):
        make_contract(effect_type="irreversible")


def test_tool_contract_is_valid_and_round_trips_as_json() -> None:
    """A complete contract retains UUID, enum, and schema data through JSON."""
    contract = make_contract(effect_type=EffectType.STAGEABLE)

    payload = contract.model_dump(mode="json")

    assert payload["contract_id"] == str(CONTRACT_ID)
    assert payload["effect_type"] == "stageable"
    assert ToolContract.model_validate_json(contract.model_dump_json()) == contract


def test_schema_must_be_explicit_json_data() -> None:
    """Empty and non-JSON schema documents fail validation."""
    with pytest.raises(ValidationError, match="schema document must not be empty"):
        ToolSchema(name="input", document={})

    with pytest.raises(ValidationError):
        ToolSchema(name="input", document={"invalid": object()})


@pytest.mark.parametrize("name", ["", " Payments.Charge", "9invalid", "has space"])
def test_tool_names_are_nonblank_canonical_names(name: str) -> None:
    """Tool names reject empty, uppercase, numeric-leading, and spaced values."""
    with pytest.raises(ValidationError):
        make_contract(name=name)


def test_contract_rejects_unknown_fields_and_is_frozen() -> None:
    """Domain models fail closed on extra fields and attribute mutation."""
    contract = make_contract()

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        make_contract(unknown=True)
    with pytest.raises(ValidationError, match="Instance is frozen"):
        contract.name = "payments.refund"


def test_action_intent_defaults_context_and_round_trips() -> None:
    """An intent supports zero metadata and JSON round-trip serialization."""
    intent = make_intent()

    assert intent.context == {}
    assert ActionIntent.model_validate_json(intent.model_dump_json()) == intent


def test_action_intent_accepts_json_boundary_values() -> None:
    """Arguments and context accept nested JSON values at their open boundaries."""
    intent = make_intent(
        arguments={"items": [1, "two", True, None], "nested": {"rate": 1.5}},
        context={"trace": "test", "attempt": 1},
        idempotency_key=None,
    )

    assert intent.arguments["nested"] == {"rate": 1.5}
    assert intent.idempotency_key is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_action_intent_rejects_non_finite_json_numbers(value: float) -> None:
    """Non-finite floats are not losslessly interoperable JSON values."""
    with pytest.raises(ValidationError):
        make_intent(arguments={"amount": value})


def test_action_intent_requires_strict_identifiers_and_aware_time() -> None:
    """String UUIDs in Python and naive timestamps fail strict validation."""
    with pytest.raises(ValidationError):
        make_intent(intent_id=str(INTENT_ID))
    with pytest.raises(ValidationError):
        make_intent(created_at=datetime(2026, 1, 1, 12))


def test_short_text_boundaries_strip_and_reject_blank_values() -> None:
    """Human identifiers are normalized but may not become blank or oversized."""
    assert make_intent(requester_id="  agent:test  ").requester_id == "agent:test"
    with pytest.raises(ValidationError):
        make_intent(requester_id="   ")
    with pytest.raises(ValidationError):
        make_intent(idempotency_key="x" * 257)
