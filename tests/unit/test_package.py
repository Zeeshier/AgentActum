"""Public package smoke tests."""

import agentactum


def test_public_package_exports_domain_contracts() -> None:
    """The package exposes version metadata and the intended contract surface."""
    assert agentactum.__version__ == "0.1.0a0"
    assert set(agentactum.__all__) == {
        "ActionIntent",
        "ApprovalRequest",
        "CompensationResult",
        "DuplicateToolRegistrationError",
        "EffectType",
        "ExecutionResult",
        "FailureDetail",
        "LedgerEvent",
        "PolicyConstraint",
        "PolicyDecision",
        "PolicyDecisionType",
        "RiskLevel",
        "RegisteredTool",
        "ToolHandler",
        "ToolContract",
        "ToolRegistry",
        "ToolRegistryError",
        "ToolSchema",
        "Transaction",
        "TransactionStatus",
        "UnknownToolError",
        "__version__",
    }
