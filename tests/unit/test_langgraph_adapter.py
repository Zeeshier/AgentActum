"""Tests for the optional LangGraph adapter."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import cast
from uuid import UUID

import pytest
from pydantic import JsonValue

import agentactum.langgraph as langgraph_adapter_module
from agentactum import AgentActum
from agentactum.contracts import ToolContract, ToolSchema
from agentactum.enums import EffectType, RiskLevel
from agentactum.langgraph import LangGraphAdapter, LangGraphIntegrationError

CONTRACT_ID = UUID("b0000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


class FakeToolNode:
    """Small fake for langgraph.prebuilt.ToolNode."""

    def __init__(self, tools: list[object]) -> None:
        """Capture tools passed to the fake ToolNode."""
        self.tools = tools


def make_contract(**overrides: object) -> ToolContract:
    """Build a contract for LangGraph adapter tests."""
    values: dict[str, object] = {
        "contract_id": CONTRACT_ID,
        "name": "refund_payment",
        "version": "1.0.0",
        "description": "Refund a fake payment.",
        "effect_type": EffectType.IDEMPOTENT,
        "risk_level": RiskLevel.LOW,
        "input_schema": ToolSchema(
            name="refund_input",
            document={
                "type": "object",
                "properties": {
                    "payment_id": {"type": "string"},
                    "amount": {"type": "number", "minimum": 1},
                },
                "required": ["payment_id", "amount"],
            },
        ),
        "output_schema": ToolSchema(
            name="refund_output",
            document={
                "type": "object",
                "properties": {
                    "refund_id": {"type": "string"},
                    "amount": {"type": "number", "minimum": 1},
                },
                "required": ["refund_id", "amount"],
            },
        ),
    }
    values.update(overrides)
    return ToolContract(**values)  # type: ignore[arg-type]


def test_langgraph_adapter_protect_tool_returns_serialized_result() -> None:
    """Protected LangGraph callables return JSON-friendly execution results."""
    adapter = LangGraphAdapter(AgentActum(clock=_clock()))
    calls: list[str] = []

    @adapter.protect_tool(contract=make_contract())
    def refund_payment(payment_id: str, amount: float) -> dict[str, JsonValue]:
        calls.append(payment_id)
        return {"refund_id": "REF-1", "amount": amount}

    result = refund_payment("PAY-100", 250.0)

    assert isinstance(result, dict)
    assert result["succeeded"] is True
    assert result["output"] == {"refund_id": "REF-1", "amount": 250.0}
    assert calls == ["PAY-100"]
    assert refund_payment.__name__ == "refund_payment"


def test_langgraph_adapter_output_mode_returns_output_on_success() -> None:
    """Output mode is convenient for LangGraph tool outputs."""
    adapter = LangGraphAdapter(AgentActum(clock=_clock()))

    @adapter.protect_tool(contract=make_contract(), return_mode="output")
    def refund_payment(payment_id: str, amount: float) -> dict[str, JsonValue]:
        return {"refund_id": payment_id, "amount": amount}

    assert refund_payment("PAY-100", 250.0) == {
        "refund_id": "PAY-100",
        "amount": 250.0,
    }


def test_langgraph_adapter_output_mode_returns_failure_result_on_failure() -> None:
    """Output mode still exposes structured failures instead of hiding denial."""
    adapter = LangGraphAdapter(AgentActum(clock=_clock()))

    @adapter.protect_tool(contract=make_contract(), return_mode="output")
    def refund_payment(payment_id: str, amount: float) -> dict[str, JsonValue]:
        return {"refund_id": payment_id, "amount": amount}

    result = refund_payment("PAY-100", 0.0)

    assert isinstance(result, dict)
    error = cast(dict[str, JsonValue], result["error"])
    assert result["succeeded"] is False
    assert error["code"] == "input_validation_failed"


def test_langgraph_adapter_rejects_unknown_return_mode() -> None:
    """Return mode is deliberately a tiny explicit set."""
    adapter = LangGraphAdapter(AgentActum(clock=_clock()))

    with pytest.raises(ValueError, match="return_mode"):
        adapter.protect_tool(
            contract=make_contract(),
            return_mode="raw",  # type: ignore[arg-type]
        )


def test_tool_node_imports_langgraph_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    """ToolNode is imported only when explicitly requested."""
    prebuilt_module = ModuleType("langgraph.prebuilt")
    prebuilt_module.ToolNode = FakeToolNode  # type: ignore[attr-defined]

    def fake_import_module(name: str) -> ModuleType:
        assert name == "langgraph.prebuilt"
        return prebuilt_module

    monkeypatch.setattr(
        langgraph_adapter_module,
        "import_module",
        fake_import_module,
    )
    adapter = LangGraphAdapter(AgentActum(clock=_clock()))

    node = adapter.tool_node([lambda: {"ok": True}])

    assert isinstance(node, FakeToolNode)
    assert len(node.tools) == 1


def test_tool_node_missing_langgraph_has_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing optional dependency tells users which extra to install."""

    def raise_import_error(name: str) -> ModuleType:
        assert name == "langgraph.prebuilt"
        raise ImportError("langgraph is not installed")

    monkeypatch.setattr(
        langgraph_adapter_module,
        "import_module",
        raise_import_error,
    )
    adapter = LangGraphAdapter(AgentActum(clock=_clock()))

    with pytest.raises(LangGraphIntegrationError, match="agentactum\\[langgraph\\]"):
        adapter.tool_node([])


def test_tool_node_missing_toolnode_symbol_has_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed LangGraph install fails clearly."""
    prebuilt_module = ModuleType("langgraph.prebuilt")

    def fake_import_module(name: str) -> ModuleType:
        assert name == "langgraph.prebuilt"
        return prebuilt_module

    monkeypatch.setattr(
        langgraph_adapter_module,
        "import_module",
        fake_import_module,
    )
    adapter = LangGraphAdapter(AgentActum(clock=_clock()))

    with pytest.raises(LangGraphIntegrationError, match="ToolNode"):
        adapter.tool_node([])


def test_core_package_does_not_export_langgraph_adapter() -> None:
    """LangGraph stays outside the core top-level export surface."""
    import agentactum

    assert "LangGraphAdapter" not in agentactum.__all__


def _clock() -> Callable[[], datetime]:
    moments = iter(NOW + timedelta(microseconds=offset) for offset in range(1_000))
    return lambda: next(moments)
