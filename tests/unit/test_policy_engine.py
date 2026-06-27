"""Tests for deterministic policy evaluation."""

from datetime import UTC, datetime
from uuid import UUID

from agentactum.contracts import ActionIntent, ToolContract
from agentactum.enums import PolicyDecisionType, RiskLevel
from agentactum.policies import (
    NumericApprovalThresholdPolicy,
    PolicyConstraint,
    PolicyDecision,
    PolicyEngine,
    RequiredPermissionPolicy,
    RiskApprovalPolicy,
    ToolAllowDenyPolicy,
)

from .test_enums_and_contracts import make_contract, make_intent

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def decision_type(policy_decision: PolicyDecision) -> PolicyDecisionType:
    """Return a decision type while keeping test assertions terse."""
    return policy_decision.decision_type


class AllowPolicy:
    """Test policy that always allows."""

    def evaluate(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        context: dict[str, object],
    ) -> PolicyDecision:
        """Return an allow decision."""
        del context
        return PolicyDecision(
            decision_id=UUID("20000000-0000-4000-8000-000000000001"),
            intent_id=action.intent_id,
            decision_type=PolicyDecisionType.ALLOW,
            risk_level=contract.risk_level,
            policy_name="allow-test",
            policy_version="1.0.0",
            reason="Allowed for test.",
            decided_at=NOW,
        )


class ConstrainedAllowPolicy:
    """Test policy that returns a constrained allow decision."""

    def evaluate(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        context: dict[str, object],
    ) -> PolicyDecision:
        """Return a constrained allow decision."""
        del context
        return PolicyDecision(
            decision_id=UUID("20000000-0000-4000-8000-000000000002"),
            intent_id=action.intent_id,
            decision_type=PolicyDecisionType.ALLOW_WITH_CONSTRAINTS,
            risk_level=contract.risk_level,
            policy_name="constraint-test",
            policy_version="1.0.0",
            reason="Allowed with constraints for test.",
            decided_at=NOW,
            constraints=(PolicyConstraint(name="limit", parameters={"amount": 100}),),
        )


class BadReturnPolicy:
    """Test policy that violates the policy protocol at runtime."""

    def evaluate(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        context: dict[str, object],
    ) -> object:
        """Return an invalid decision object."""
        del action, contract, context
        return object()


class WrongIntentPolicy:
    """Test policy that returns a decision bound to the wrong intent."""

    def evaluate(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        context: dict[str, object],
    ) -> PolicyDecision:
        """Return a decision with an incorrect intent id."""
        del context
        return PolicyDecision(
            decision_id=UUID("20000000-0000-4000-8000-000000000003"),
            intent_id=UUID("20000000-0000-4000-8000-000000000004"),
            decision_type=PolicyDecisionType.ALLOW,
            risk_level=contract.risk_level,
            policy_name="wrong-intent-test",
            policy_version="1.0.0",
            reason="Incorrectly allowed for test.",
            decided_at=NOW,
        )


class RaisingPolicy:
    """Test policy that raises during evaluation."""

    def evaluate(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        context: dict[str, object],
    ) -> PolicyDecision:
        """Raise an ordinary policy exception."""
        del action, contract, context
        raise RuntimeError("policy exploded")


def test_unknown_tool_is_denied_without_contract() -> None:
    """A failed registry lookup can be represented as a fail-closed denial."""
    action = make_intent(tool_name="refund_payment")

    decision = PolicyEngine().evaluate(action=action, contract=None, context={})

    assert decision.intent_id == action.intent_id
    assert decision.decision_type is PolicyDecisionType.DENY
    assert decision.risk_level is RiskLevel.CRITICAL
    assert "Unknown tool" in decision.reason


def test_action_contract_mismatch_is_denied() -> None:
    """The engine rejects a supplied contract that does not match the action."""
    action = make_intent(tool_name="refund_payment")
    contract = make_contract(name="send_email")

    decision = PolicyEngine().evaluate(action=action, contract=contract, context={})

    assert decision.decision_type is PolicyDecisionType.DENY
    assert "does not match" in decision.reason


def test_empty_engine_allows_low_risk_known_tool() -> None:
    """With no configured rules, a low-risk known tool is allowed."""
    contract = make_contract(name="refund_payment", risk_level=RiskLevel.LOW)
    action = make_intent(
        contract_id=contract.contract_id,
        tool_name=contract.name,
        contract_version=contract.version,
    )

    decision = PolicyEngine().evaluate(action=action, contract=contract, context={})

    assert decision.decision_type is PolicyDecisionType.ALLOW
    assert decision.risk_level is RiskLevel.LOW


def test_high_and_critical_risk_require_approval_even_when_allowed() -> None:
    """The engine enforces mandatory approval for high-risk contract floors."""
    for risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
        contract = make_contract(name="refund_payment", risk_level=risk_level)
        action = make_intent(
            contract_id=contract.contract_id,
            tool_name=contract.name,
            contract_version=contract.version,
        )

        decision = PolicyEngine([AllowPolicy()]).evaluate(
            action=action,
            contract=contract,
            context={},
        )

        assert decision.decision_type is PolicyDecisionType.REQUIRE_APPROVAL
        assert decision.risk_level is risk_level


def test_tool_allow_deny_policy_supports_allow_and_deny_lists() -> None:
    """Exact tool-name rules allow known names and deny denied or absent names."""
    contract = make_contract(name="refund_payment", risk_level=RiskLevel.LOW)
    action = make_intent(
        contract_id=contract.contract_id,
        tool_name=contract.name,
        contract_version=contract.version,
    )

    allowed = PolicyEngine(
        [ToolAllowDenyPolicy(allowed_tools=["refund_payment"])],
    ).evaluate(action=action, contract=contract, context={})
    denied = PolicyEngine(
        [ToolAllowDenyPolicy(denied_tools=["refund_payment"])],
    ).evaluate(action=action, contract=contract, context={})
    absent = PolicyEngine(
        [ToolAllowDenyPolicy(allowed_tools=["send_email"])],
    ).evaluate(action=action, contract=contract, context={})

    assert decision_type(allowed) is PolicyDecisionType.ALLOW
    assert decision_type(denied) is PolicyDecisionType.DENY
    assert decision_type(absent) is PolicyDecisionType.DENY


def test_required_permission_policy_uses_trusted_context() -> None:
    """Required permissions are read from trusted context, not the action."""
    contract = make_contract(name="refund_payment", risk_level=RiskLevel.LOW)
    action = make_intent(
        contract_id=contract.contract_id,
        tool_name=contract.name,
        contract_version=contract.version,
        context={"permissions": ["caller.claimed.permission"]},
    )
    engine = PolicyEngine(
        [
            RequiredPermissionPolicy(
                {"refund_payment": ["payments.refund", "payments.write"]},
            ),
        ],
    )

    denied = engine.evaluate(
        action=action,
        contract=contract,
        context={"permissions": ["payments.refund"]},
    )
    allowed = engine.evaluate(
        action=action,
        contract=contract,
        context={"permissions": ["payments.write", "payments.refund"]},
    )

    assert denied.decision_type is PolicyDecisionType.DENY
    assert "payments.write" in denied.reason
    assert allowed.decision_type is PolicyDecisionType.ALLOW


def test_required_permission_policy_denies_malformed_context() -> None:
    """Permissions must be a JSON list of strings."""
    contract = make_contract(name="refund_payment", risk_level=RiskLevel.LOW)
    action = make_intent(
        contract_id=contract.contract_id,
        tool_name=contract.name,
        contract_version=contract.version,
    )
    engine = PolicyEngine(
        [RequiredPermissionPolicy({"refund_payment": ["payments.refund"]})],
    )

    missing = engine.evaluate(action=action, contract=contract, context={})
    malformed = engine.evaluate(
        action=action,
        contract=contract,
        context={"permissions": [1]},
    )

    assert missing.decision_type is PolicyDecisionType.DENY
    assert malformed.decision_type is PolicyDecisionType.DENY


def test_required_permission_policy_allows_tools_without_requirements() -> None:
    """A permission policy with no entry for a tool does not deny it."""
    contract = make_contract(name="refund_payment", risk_level=RiskLevel.LOW)
    action = make_intent(
        contract_id=contract.contract_id,
        tool_name=contract.name,
        contract_version=contract.version,
    )

    decision = PolicyEngine(
        [RequiredPermissionPolicy({"send_email": ["email.send"]})],
    ).evaluate(action=action, contract=contract, context={})

    assert decision.decision_type is PolicyDecisionType.ALLOW


def test_risk_approval_policy_supports_configured_risk_floor() -> None:
    """Risk approval can be configured to start below high risk."""
    contract = make_contract(name="refund_payment", risk_level=RiskLevel.MEDIUM)
    action = make_intent(
        contract_id=contract.contract_id,
        tool_name=contract.name,
        contract_version=contract.version,
    )
    engine = PolicyEngine([RiskApprovalPolicy(minimum_risk=RiskLevel.MEDIUM)])

    decision = engine.evaluate(action=action, contract=contract, context={})

    assert decision.decision_type is PolicyDecisionType.REQUIRE_APPROVAL


def test_risk_approval_policy_allows_risk_below_floor() -> None:
    """A risk approval policy allows contract risk below its configured floor."""
    contract = make_contract(name="refund_payment", risk_level=RiskLevel.LOW)
    action = make_intent(
        contract_id=contract.contract_id,
        tool_name=contract.name,
        contract_version=contract.version,
    )
    engine = PolicyEngine([RiskApprovalPolicy(minimum_risk=RiskLevel.MEDIUM)])

    decision = engine.evaluate(action=action, contract=contract, context={})

    assert decision.decision_type is PolicyDecisionType.ALLOW


def test_numeric_threshold_policy_requires_approval_above_threshold() -> None:
    """Numeric thresholds support amount-style approval rules."""
    contract = make_contract(name="refund_payment", risk_level=RiskLevel.LOW)
    base = {
        "contract_id": contract.contract_id,
        "tool_name": contract.name,
        "contract_version": contract.version,
    }
    engine = PolicyEngine(
        [NumericApprovalThresholdPolicy(field="amount", threshold=100)],
    )

    at_threshold = engine.evaluate(
        action=make_intent(arguments={"amount": 100}, **base),
        contract=contract,
        context={},
    )
    above_threshold = engine.evaluate(
        action=make_intent(arguments={"amount": 100.01}, **base),
        contract=contract,
        context={},
    )

    assert at_threshold.decision_type is PolicyDecisionType.ALLOW
    assert above_threshold.decision_type is PolicyDecisionType.REQUIRE_APPROVAL


def test_numeric_threshold_policy_can_be_scoped_to_tools() -> None:
    """A scoped numeric threshold ignores tools outside its scope."""
    contract = make_contract(name="refund_payment", risk_level=RiskLevel.LOW)
    action = make_intent(
        contract_id=contract.contract_id,
        tool_name=contract.name,
        contract_version=contract.version,
        arguments={"amount": 10_000},
    )
    engine = PolicyEngine(
        [
            NumericApprovalThresholdPolicy(
                field="amount",
                threshold=100,
                tools=["send_email"],
            ),
        ],
    )

    decision = engine.evaluate(action=action, contract=contract, context={})

    assert decision.decision_type is PolicyDecisionType.ALLOW


def test_numeric_threshold_policy_denies_missing_or_non_numeric_values() -> None:
    """A configured numeric rule fails closed on absent, boolean, or text data."""
    contract = make_contract(name="refund_payment", risk_level=RiskLevel.LOW)
    base = {
        "contract_id": contract.contract_id,
        "tool_name": contract.name,
        "contract_version": contract.version,
    }
    engine = PolicyEngine(
        [NumericApprovalThresholdPolicy(field="amount", threshold=100)],
    )

    missing = engine.evaluate(
        action=make_intent(arguments={}, **base),
        contract=contract,
        context={},
    )
    boolean = engine.evaluate(
        action=make_intent(arguments={"amount": True}, **base),
        contract=contract,
        context={},
    )
    text = engine.evaluate(
        action=make_intent(arguments={"amount": "1000"}, **base),
        contract=contract,
        context={},
    )

    assert missing.decision_type is PolicyDecisionType.DENY
    assert boolean.decision_type is PolicyDecisionType.DENY
    assert text.decision_type is PolicyDecisionType.DENY


def test_policy_composition_precedence_and_constraints() -> None:
    """Deny wins over approval; otherwise approval wins over constrained allow."""
    contract = make_contract(name="refund_payment", risk_level=RiskLevel.LOW)
    action = make_intent(
        contract_id=contract.contract_id,
        tool_name=contract.name,
        contract_version=contract.version,
    )

    constrained = PolicyEngine([ConstrainedAllowPolicy()]).evaluate(
        action=action,
        contract=contract,
        context={},
    )
    approval = PolicyEngine(
        [
            ConstrainedAllowPolicy(),
            NumericApprovalThresholdPolicy(field="amount", threshold=1),
        ],
    ).evaluate(
        action=make_intent(
            contract_id=contract.contract_id,
            tool_name=contract.name,
            contract_version=contract.version,
            arguments={"amount": 10},
        ),
        contract=contract,
        context={},
    )
    denied = PolicyEngine(
        [
            RiskApprovalPolicy(minimum_risk=RiskLevel.LOW),
            ToolAllowDenyPolicy(denied_tools=["refund_payment"]),
        ],
    ).evaluate(action=action, contract=contract, context={})

    assert constrained.decision_type is PolicyDecisionType.ALLOW_WITH_CONSTRAINTS
    assert constrained.constraints[0].name == "limit"
    assert approval.decision_type is PolicyDecisionType.REQUIRE_APPROVAL
    assert denied.decision_type is PolicyDecisionType.DENY


def test_policy_engine_fails_closed_on_exceptions_and_bad_decisions() -> None:
    """Policy exceptions, invalid objects, and wrong intent bindings deny."""
    contract = make_contract(name="refund_payment", risk_level=RiskLevel.LOW)
    action = make_intent(
        contract_id=contract.contract_id,
        tool_name=contract.name,
        contract_version=contract.version,
    )

    raised = PolicyEngine([RaisingPolicy()]).evaluate(
        action=action,
        contract=contract,
        context={},
    )
    malformed = PolicyEngine([BadReturnPolicy()]).evaluate(  # type: ignore[list-item]
        action=action,
        contract=contract,
        context={},
    )
    wrong_intent = PolicyEngine([WrongIntentPolicy()]).evaluate(
        action=action,
        contract=contract,
        context={},
    )

    assert raised.decision_type is PolicyDecisionType.DENY
    assert malformed.decision_type is PolicyDecisionType.DENY
    assert wrong_intent.decision_type is PolicyDecisionType.DENY
