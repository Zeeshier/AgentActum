"""Public package smoke tests."""

import agentactum


def test_public_package_exports_domain_contracts() -> None:
    """The package exposes version metadata and the intended contract surface."""
    assert agentactum.__version__ == "0.1.0a0"
    assert set(agentactum.__all__) == {
        "ActionIntent",
        "ApprovalRequest",
        "CompensationResult",
        "EffectType",
        "ExecutionResult",
        "FailureDetail",
        "LedgerEvent",
        "PolicyConstraint",
        "PolicyDecision",
        "PolicyDecisionType",
        "RiskLevel",
        "ToolContract",
        "ToolSchema",
        "Transaction",
        "TransactionStatus",
        "__version__",
    }
