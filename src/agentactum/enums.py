"""Stable enumerations used by AgentActum domain contracts."""

from enum import StrEnum


class EffectType(StrEnum):
    """Primary effect classification declared by a tool contract."""

    READ_ONLY = "read_only"
    IDEMPOTENT = "idempotent"
    REVERSIBLE = "reversible"
    COMPENSATABLE = "compensatable"
    STAGEABLE = "stageable"
    IRREVERSIBLE = "irreversible"


class RiskLevel(StrEnum):
    """Ordered-by-policy risk label attached to contracts and decisions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyDecisionType(StrEnum):
    """Declarative outcome produced by a policy decision."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    ALLOW_WITH_CONSTRAINTS = "allow_with_constraints"


class TransactionStatus(StrEnum):
    """Snapshot status of a transaction."""

    PROPOSED = "proposed"
    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMMITTED = "committed"
    REJECTED = "rejected"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    PARTIALLY_COMPENSATED = "partially_compensated"
