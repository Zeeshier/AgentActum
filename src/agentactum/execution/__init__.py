"""Tool execution result contracts and single-action runtime."""

from agentactum.execution.models import ExecutionResult, FailureDetail
from agentactum.execution.runtime import (
    ApprovalChecker,
    NoApprovalChecker,
    RuntimeCheck,
    SchemaValidationError,
    SingleActionRuntime,
    StaticApprovalChecker,
)

__all__ = [
    "ApprovalChecker",
    "ExecutionResult",
    "FailureDetail",
    "NoApprovalChecker",
    "RuntimeCheck",
    "SchemaValidationError",
    "SingleActionRuntime",
    "StaticApprovalChecker",
]
