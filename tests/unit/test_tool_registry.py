"""Tests for the in-process tool registry."""

import pytest

import agentactum
from agentactum.contracts import (
    DuplicateToolRegistrationError,
    RegisteredTool,
    ToolRegistry,
    UnknownToolError,
)

from .test_enums_and_contracts import make_contract


def fake_refund_payment(**_arguments: object) -> dict[str, str]:
    """Fake handler used only to prove the registry stores a callable."""
    return {"status": "not-called-by-registry"}


def fake_send_email(**_arguments: object) -> dict[str, str]:
    """Second fake handler used for ordering tests."""
    return {"status": "not-called-by-registry"}


def test_registry_register_get_contains_and_list_contracts() -> None:
    """Registered contracts can be looked up without invoking handlers."""
    registry = ToolRegistry()
    contract = make_contract(name="refund_payment")

    registration = registry.register(contract, fake_refund_payment)

    assert registration == RegisteredTool(
        contract=contract,
        handler=fake_refund_payment,
    )
    assert registry.contains("refund_payment")
    assert not registry.contains("send_email")
    assert registry.get("refund_payment") is registration
    assert registry.list_contracts() == (contract,)


def test_registry_can_be_seeded_with_explicit_registrations() -> None:
    """Construction can seed a registry without creating global state."""
    first = RegisteredTool(
        contract=make_contract(name="refund_payment"),
        handler=fake_refund_payment,
    )
    second = RegisteredTool(
        contract=make_contract(name="send_email"),
        handler=fake_send_email,
    )

    registry = ToolRegistry([first, second])

    assert registry.list_contracts() == (first.contract, second.contract)
    assert registry.get("send_email").handler is fake_send_email


def test_duplicate_registration_is_rejected_by_default() -> None:
    """A second registration for the same tool name fails closed."""
    registry = ToolRegistry()
    contract = make_contract(name="refund_payment")
    replacement = make_contract(
        name="refund_payment",
        version="2.0.0",
        description="Another fake refund implementation.",
    )
    registry.register(contract, fake_refund_payment)

    with pytest.raises(DuplicateToolRegistrationError) as exc_info:
        registry.register(replacement, fake_send_email)

    assert exc_info.value.tool_name == "refund_payment"
    assert registry.get("refund_payment").contract is contract


def test_unknown_tool_lookup_raises_typed_error() -> None:
    """Unknown tools do not return an empty or permissive fallback."""
    registry = ToolRegistry()

    with pytest.raises(UnknownToolError) as exc_info:
        registry.get("refund_payment")

    assert exc_info.value.tool_name == "refund_payment"


def test_registry_rejects_invalid_registration_inputs() -> None:
    """The registry requires a contract object and a callable handler."""
    registry = ToolRegistry()
    contract = make_contract(name="refund_payment")

    with pytest.raises(TypeError, match="contract must be a ToolContract"):
        registry.register("refund_payment", fake_refund_payment)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="handler must be callable"):
        registry.register(contract, object())  # type: ignore[arg-type]


def test_root_package_exports_registry_api() -> None:
    """Registry types are available from the top-level package API."""
    registry = agentactum.ToolRegistry()
    contract = make_contract(name="refund_payment")

    registration = registry.register(contract, fake_refund_payment)

    assert isinstance(registration, agentactum.RegisteredTool)
    assert agentactum.ToolRegistryError
    assert agentactum.DuplicateToolRegistrationError
    assert agentactum.UnknownToolError
