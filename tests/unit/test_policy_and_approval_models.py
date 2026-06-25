"""Tests for policy decision and approval request contracts."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from agentactum.approvals import ApprovalRequest
from agentactum.enums import PolicyDecisionType, RiskLevel
from agentactum.policies import PolicyConstraint, PolicyDecision

DECISION_ID = UUID("10000000-0000-4000-8000-000000000001")
INTENT_ID = UUID("10000000-0000-4000-8000-000000000002")
TRANSACTION_ID = UUID("10000000-0000-4000-8000-000000000003")
APPROVAL_ID = UUID("10000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def make_decision(**overrides: object) -> PolicyDecision:
    """Build a policy decision while allowing selected fields to vary."""
    values: dict[str, object] = {
        "decision_id": DECISION_ID,
        "intent_id": INTENT_ID,
        "decision_type": PolicyDecisionType.ALLOW,
        "risk_level": RiskLevel.LOW,
        "policy_name": "default-policy",
        "policy_version": "1.0.0",
        "reason": "The declared action is allowed.",
        "decided_at": NOW,
    }
    values.update(overrides)
    return PolicyDecision(**values)  # type: ignore[arg-type]


def make_approval(**overrides: object) -> ApprovalRequest:
    """Build an approval request while allowing selected fields to vary."""
    values: dict[str, object] = {
        "approval_request_id": APPROVAL_ID,
        "intent_id": INTENT_ID,
        "transaction_id": TRANSACTION_ID,
        "policy_decision_id": DECISION_ID,
        "intent_fingerprint": "a" * 64,
        "risk_level": RiskLevel.HIGH,
        "reason": "Human authorization is required.",
        "requested_at": NOW,
        "expires_at": NOW + timedelta(minutes=15),
    }
    values.update(overrides)
    return ApprovalRequest(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "decision_type",
    [
        PolicyDecisionType.ALLOW,
        PolicyDecisionType.DENY,
        PolicyDecisionType.REQUIRE_APPROVAL,
    ],
)
def test_unconstrained_policy_decisions_are_valid(
    decision_type: PolicyDecisionType,
) -> None:
    """Allow, deny, and approval decisions are valid without constraints."""
    assert make_decision(decision_type=decision_type).constraints == ()


def test_constrained_allow_requires_unique_structured_constraints() -> None:
    """A constrained allow carries explicit named parameter models."""
    constraint = PolicyConstraint(
        name="maximum_amount",
        parameters={"currency": "USD", "amount": 100},
    )
    decision = make_decision(
        decision_type=PolicyDecisionType.ALLOW_WITH_CONSTRAINTS,
        constraints=(constraint,),
    )

    assert decision.constraints == (constraint,)
    assert PolicyDecision.model_validate_json(decision.model_dump_json()) == decision


def test_constrained_allow_rejects_missing_constraints() -> None:
    """The constrained decision type may not carry an empty constraint set."""
    with pytest.raises(ValidationError, match="requires constraints"):
        make_decision(decision_type=PolicyDecisionType.ALLOW_WITH_CONSTRAINTS)


def test_other_decisions_reject_constraints() -> None:
    """Constraints cannot be smuggled into a differently typed decision."""
    constraint = PolicyConstraint(name="region", parameters={"allowed": ["us"]})
    with pytest.raises(ValidationError, match="constraints require"):
        make_decision(constraints=(constraint,))


def test_constraint_names_must_be_unique() -> None:
    """Duplicate constraint names are ambiguous and fail validation."""
    constraints = (
        PolicyConstraint(name="limit", parameters={"amount": 10}),
        PolicyConstraint(name="limit", parameters={"amount": 20}),
    )
    with pytest.raises(ValidationError, match="constraint names must be unique"):
        make_decision(
            decision_type=PolicyDecisionType.ALLOW_WITH_CONSTRAINTS,
            constraints=constraints,
        )


def test_approval_request_is_bound_and_serializable() -> None:
    """Approval identifiers and fingerprints survive JSON serialization."""
    request = make_approval()
    payload = request.model_dump(mode="json")

    assert payload["policy_decision_id"] == str(DECISION_ID)
    assert payload["intent_fingerprint"] == "a" * 64
    assert ApprovalRequest.model_validate_json(request.model_dump_json()) == request


@pytest.mark.parametrize(
    "expires_at",
    [NOW, NOW - timedelta(microseconds=1)],
)
def test_approval_expiry_must_follow_request_time(expires_at: datetime) -> None:
    """Zero-length and backwards approval windows fail validation."""
    with pytest.raises(ValidationError, match="expires_at must be after"):
        make_approval(expires_at=expires_at)


@pytest.mark.parametrize("fingerprint", ["a" * 63, "A" * 64, "g" * 64])
def test_approval_fingerprint_is_lowercase_sha256_shape(fingerprint: str) -> None:
    """Approval binding accepts exactly 64 lowercase hexadecimal characters."""
    with pytest.raises(ValidationError):
        make_approval(intent_fingerprint=fingerprint)
