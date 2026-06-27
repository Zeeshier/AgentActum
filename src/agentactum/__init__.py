"""Public domain contracts for AgentActum."""

from agentactum.approvals import ApprovalRequest
from agentactum.compensation import CompensationResult
from agentactum.contracts import (
    ActionIntent,
    DuplicateToolRegistrationError,
    RegisteredTool,
    ToolContract,
    ToolHandler,
    ToolRegistry,
    ToolRegistryError,
    ToolSchema,
    UnknownToolError,
)
from agentactum.enums import (
    EffectType,
    PolicyDecisionType,
    RiskLevel,
    TransactionStatus,
)
from agentactum.execution import ExecutionResult, FailureDetail
from agentactum.idempotency import (
    IdempotencyBackend,
    IdempotencyClaim,
    IdempotencyError,
    IdempotencyKeyError,
    IdempotencyOwnershipError,
    IdempotencyRecord,
    IdempotencyRecordStatus,
    InMemoryIdempotencyBackend,
    MissingIdempotencyFieldError,
    create_key,
)
from agentactum.ledger import LedgerEvent
from agentactum.policies import (
    NumericApprovalThresholdPolicy,
    Policy,
    PolicyConstraint,
    PolicyDecision,
    PolicyEngine,
    RequiredPermissionPolicy,
    RiskApprovalPolicy,
    ToolAllowDenyPolicy,
)
from agentactum.transactions import Transaction

__version__ = "0.1.0a0"

__all__ = [
    "ActionIntent",
    "ApprovalRequest",
    "CompensationResult",
    "DuplicateToolRegistrationError",
    "EffectType",
    "ExecutionResult",
    "FailureDetail",
    "IdempotencyBackend",
    "IdempotencyClaim",
    "IdempotencyError",
    "IdempotencyKeyError",
    "IdempotencyOwnershipError",
    "IdempotencyRecord",
    "IdempotencyRecordStatus",
    "InMemoryIdempotencyBackend",
    "LedgerEvent",
    "MissingIdempotencyFieldError",
    "NumericApprovalThresholdPolicy",
    "Policy",
    "PolicyConstraint",
    "PolicyDecision",
    "PolicyDecisionType",
    "PolicyEngine",
    "RiskLevel",
    "RegisteredTool",
    "RequiredPermissionPolicy",
    "RiskApprovalPolicy",
    "ToolHandler",
    "ToolContract",
    "ToolAllowDenyPolicy",
    "ToolRegistry",
    "ToolRegistryError",
    "ToolSchema",
    "Transaction",
    "TransactionStatus",
    "UnknownToolError",
    "__version__",
    "create_key",
]
