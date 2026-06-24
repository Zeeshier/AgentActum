"""Package scaffold smoke tests."""

from importlib import import_module

import agentactum


def test_package_and_declared_namespaces_import() -> None:
    """The package and its architectural namespaces are importable."""
    namespaces = (
        "approvals",
        "compensation",
        "contracts",
        "execution",
        "idempotency",
        "ledger",
        "policies",
        "transactions",
    )

    assert agentactum.__version__ == "0.1.0a0"
    for namespace in namespaces:
        import_module(f"agentactum.{namespace}")
