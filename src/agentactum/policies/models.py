"""Declarative policy decision models."""

from typing import Self
from uuid import UUID

from pydantic import model_validator

from agentactum._model import DomainModel, JsonObject, LongText, ShortText, Timestamp
from agentactum.enums import PolicyDecisionType, RiskLevel


class PolicyConstraint(DomainModel):
    """Named, structured constraint attached to a policy decision."""

    name: ShortText
    parameters: JsonObject


class PolicyDecision(DomainModel):
    """Immutable policy outcome for one action intent."""

    decision_id: UUID
    intent_id: UUID
    decision_type: PolicyDecisionType
    risk_level: RiskLevel
    policy_name: ShortText
    policy_version: ShortText
    reason: LongText
    decided_at: Timestamp
    constraints: tuple[PolicyConstraint, ...] = ()

    @model_validator(mode="after")
    def validate_constraints(self) -> Self:
        """Bind constraints exclusively to constrained allow decisions."""
        has_constraints = bool(self.constraints)
        if self.decision_type is PolicyDecisionType.ALLOW_WITH_CONSTRAINTS:
            if not has_constraints:
                raise ValueError("ALLOW_WITH_CONSTRAINTS requires constraints")
        elif has_constraints:
            raise ValueError("constraints require ALLOW_WITH_CONSTRAINTS")

        names = [constraint.name for constraint in self.constraints]
        if len(names) != len(set(names)):
            raise ValueError("constraint names must be unique")
        return self
