"""Deterministic in-process policy evaluation."""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Protocol, TypeGuard, cast
from uuid import uuid4

from pydantic import JsonValue

from agentactum._model import JsonObject
from agentactum.contracts import ActionIntent, ToolContract
from agentactum.enums import PolicyDecisionType, RiskLevel
from agentactum.policies.models import PolicyConstraint, PolicyDecision

_RISK_RANK: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


class Policy(Protocol):
    """Synchronous deterministic policy rule."""

    def evaluate(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        context: JsonObject,
    ) -> PolicyDecision:
        """Evaluate one action against a known contract and trusted context."""


class PolicyEngine:
    """Compose typed Python policies with fail-closed semantics."""

    def __init__(self, policies: Iterable[Policy] = ()) -> None:
        """Create a policy engine from deterministic Python policy objects."""
        self._policies = tuple(policies)

    def evaluate(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract | None,
        context: JsonObject,
    ) -> PolicyDecision:
        """Evaluate an action, denying unknown or invalid tool bindings."""
        if contract is None:
            return _decision(
                action=action,
                decision_type=PolicyDecisionType.DENY,
                risk_level=RiskLevel.CRITICAL,
                policy_name="policy_engine",
                reason=f"Unknown tool denied: {action.tool_name}.",
            )

        if not _action_matches_contract(action=action, contract=contract):
            return _decision(
                action=action,
                decision_type=PolicyDecisionType.DENY,
                risk_level=contract.risk_level,
                policy_name="policy_engine",
                reason="Action intent does not match the supplied contract.",
            )

        decisions: list[PolicyDecision] = []
        for policy in self._policies:
            try:
                decision = policy.evaluate(
                    action=action,
                    contract=contract,
                    context=context,
                )
            except Exception:
                return _decision(
                    action=action,
                    decision_type=PolicyDecisionType.DENY,
                    risk_level=contract.risk_level,
                    policy_name="policy_engine",
                    reason="Policy evaluation failed closed.",
                )

            if not isinstance(decision, PolicyDecision):
                return _decision(
                    action=action,
                    decision_type=PolicyDecisionType.DENY,
                    risk_level=contract.risk_level,
                    policy_name="policy_engine",
                    reason="Policy returned an invalid decision.",
                )
            if decision.intent_id != action.intent_id:
                return _decision(
                    action=action,
                    decision_type=PolicyDecisionType.DENY,
                    risk_level=contract.risk_level,
                    policy_name="policy_engine",
                    reason="Policy decision was bound to the wrong action intent.",
                )
            decisions.append(decision)

        return _compose(action=action, contract=contract, decisions=decisions)


class ToolAllowDenyPolicy:
    """Allow or deny tools by exact registered tool name."""

    def __init__(
        self,
        *,
        allowed_tools: Iterable[str] | None = None,
        denied_tools: Iterable[str] = (),
    ) -> None:
        """Create a tool policy from optional allow and deny sets."""
        self._allowed_tools = (
            None if allowed_tools is None else frozenset(allowed_tools)
        )
        self._denied_tools = frozenset(denied_tools)

    def evaluate(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        context: JsonObject,
    ) -> PolicyDecision:
        """Deny explicit deny-list matches and names absent from an allow list."""
        del context
        if action.tool_name in self._denied_tools:
            return _decision(
                action=action,
                decision_type=PolicyDecisionType.DENY,
                risk_level=contract.risk_level,
                policy_name="tool_allow_deny",
                reason=f"Tool denied by policy: {action.tool_name}.",
            )
        if (
            self._allowed_tools is not None
            and action.tool_name not in self._allowed_tools
        ):
            return _decision(
                action=action,
                decision_type=PolicyDecisionType.DENY,
                risk_level=contract.risk_level,
                policy_name="tool_allow_deny",
                reason=f"Tool is not in the allow list: {action.tool_name}.",
            )
        return _allow(action=action, contract=contract, policy_name="tool_allow_deny")


class RequiredPermissionPolicy:
    """Require named permissions from trusted context for selected tools."""

    def __init__(self, required_permissions: Mapping[str, Iterable[str]]) -> None:
        """Create a permission policy keyed by tool name."""
        self._required_permissions = {
            tool_name: frozenset(permissions)
            for tool_name, permissions in required_permissions.items()
        }

    def evaluate(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        context: JsonObject,
    ) -> PolicyDecision:
        """Allow only when trusted context contains every required permission."""
        required = self._required_permissions.get(action.tool_name, frozenset())
        if not required:
            return _allow(
                action=action,
                contract=contract,
                policy_name="required_permission",
            )

        permissions = _string_set(context.get("permissions"))
        if permissions is None:
            return _decision(
                action=action,
                decision_type=PolicyDecisionType.DENY,
                risk_level=contract.risk_level,
                policy_name="required_permission",
                reason="Trusted context does not contain a valid permissions list.",
            )

        missing = sorted(required - permissions)
        if missing:
            return _decision(
                action=action,
                decision_type=PolicyDecisionType.DENY,
                risk_level=contract.risk_level,
                policy_name="required_permission",
                reason=f"Missing required permissions: {', '.join(missing)}.",
            )

        return _allow(
            action=action,
            contract=contract,
            policy_name="required_permission",
        )


class RiskApprovalPolicy:
    """Require approval at or above a configured risk level."""

    def __init__(self, *, minimum_risk: RiskLevel = RiskLevel.HIGH) -> None:
        """Create a risk approval policy."""
        self._minimum_risk = minimum_risk

    def evaluate(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        context: JsonObject,
    ) -> PolicyDecision:
        """Require approval when the contract risk reaches the configured floor."""
        del context
        if _risk_at_least(contract.risk_level, self._minimum_risk):
            return _decision(
                action=action,
                decision_type=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=contract.risk_level,
                policy_name="risk_approval",
                reason=f"Risk level requires approval: {contract.risk_level.value}.",
            )
        return _allow(action=action, contract=contract, policy_name="risk_approval")


class NumericApprovalThresholdPolicy:
    """Require approval when a numeric action argument exceeds a threshold."""

    def __init__(
        self,
        *,
        field: str,
        threshold: int | float,
        tools: Iterable[str] | None = None,
    ) -> None:
        """Create a numeric threshold policy for all tools or selected tools."""
        self._field = field
        self._threshold = float(threshold)
        self._tools = None if tools is None else frozenset(tools)

    def evaluate(
        self,
        *,
        action: ActionIntent,
        contract: ToolContract,
        context: JsonObject,
    ) -> PolicyDecision:
        """Require approval when the configured argument exceeds the threshold."""
        del context
        if self._tools is not None and action.tool_name not in self._tools:
            return _allow(
                action=action,
                contract=contract,
                policy_name="numeric_threshold",
            )

        value = action.arguments.get(self._field)
        if not _is_number(value):
            return _decision(
                action=action,
                decision_type=PolicyDecisionType.DENY,
                risk_level=contract.risk_level,
                policy_name="numeric_threshold",
                reason=f"Argument is not a valid number: {self._field}.",
            )

        if value > self._threshold:
            return _decision(
                action=action,
                decision_type=PolicyDecisionType.REQUIRE_APPROVAL,
                risk_level=contract.risk_level,
                policy_name="numeric_threshold",
                reason=f"Argument exceeds approval threshold: {self._field}.",
            )

        return _allow(action=action, contract=contract, policy_name="numeric_threshold")


def _action_matches_contract(*, action: ActionIntent, contract: ToolContract) -> bool:
    return (
        action.contract_id == contract.contract_id
        and action.tool_name == contract.name
        and action.contract_version == contract.version
    )


def _allow(
    *,
    action: ActionIntent,
    contract: ToolContract,
    policy_name: str,
) -> PolicyDecision:
    return _decision(
        action=action,
        decision_type=PolicyDecisionType.ALLOW,
        risk_level=contract.risk_level,
        policy_name=policy_name,
        reason="Policy allowed the action.",
    )


def _compose(
    *,
    action: ActionIntent,
    contract: ToolContract,
    decisions: list[PolicyDecision],
) -> PolicyDecision:
    effective_risk = _max_risk(
        [contract.risk_level, *(decision.risk_level for decision in decisions)],
    )
    constraints = tuple(
        constraint
        for decision in decisions
        if decision.decision_type is PolicyDecisionType.ALLOW_WITH_CONSTRAINTS
        for constraint in decision.constraints
    )

    denial = next(
        (
            decision
            for decision in decisions
            if decision.decision_type is PolicyDecisionType.DENY
        ),
        None,
    )
    if denial is not None:
        return _decision(
            action=action,
            decision_type=PolicyDecisionType.DENY,
            risk_level=effective_risk,
            policy_name="policy_engine",
            reason=denial.reason,
        )

    if _risk_at_least(effective_risk, RiskLevel.HIGH) or any(
        decision.decision_type is PolicyDecisionType.REQUIRE_APPROVAL
        for decision in decisions
    ):
        return _decision(
            action=action,
            decision_type=PolicyDecisionType.REQUIRE_APPROVAL,
            risk_level=effective_risk,
            policy_name="policy_engine",
            reason="Approval is required before this action may proceed.",
        )

    if constraints:
        return _decision(
            action=action,
            decision_type=PolicyDecisionType.ALLOW_WITH_CONSTRAINTS,
            risk_level=effective_risk,
            policy_name="policy_engine",
            reason="Policies allowed the action with constraints.",
            constraints=constraints,
        )

    return _decision(
        action=action,
        decision_type=PolicyDecisionType.ALLOW,
        risk_level=effective_risk,
        policy_name="policy_engine",
        reason="Policies allowed the action.",
    )


def _decision(
    *,
    action: ActionIntent,
    decision_type: PolicyDecisionType,
    risk_level: RiskLevel,
    policy_name: str,
    reason: str,
    constraints: tuple[PolicyConstraint, ...] = (),
) -> PolicyDecision:
    return PolicyDecision(
        decision_id=uuid4(),
        intent_id=action.intent_id,
        decision_type=decision_type,
        risk_level=risk_level,
        policy_name=policy_name,
        policy_version="1.0.0",
        reason=reason,
        decided_at=datetime.now(UTC),
        constraints=constraints,
    )


def _max_risk(risk_levels: Iterable[RiskLevel]) -> RiskLevel:
    return max(risk_levels, key=lambda risk_level: _RISK_RANK[risk_level])


def _risk_at_least(actual: RiskLevel, minimum: RiskLevel) -> bool:
    return _RISK_RANK[actual] >= _RISK_RANK[minimum]


def _string_set(value: JsonValue | None) -> frozenset[str] | None:
    if not isinstance(value, list):
        return None
    if not all(isinstance(item, str) for item in value):
        return None
    return frozenset(cast(list[str], value))


def _is_number(value: JsonValue | None) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)
