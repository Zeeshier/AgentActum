"""Optional LangGraph adapter for AgentActum-protected tools."""

from collections.abc import Callable, Iterable
from functools import wraps
from importlib import import_module
from typing import Literal, ParamSpec, cast

from pydantic import JsonValue

from agentactum._model import JsonObject
from agentactum.contracts import ToolContract
from agentactum.execution import ExecutionResult
from agentactum.facade import AgentActum

P = ParamSpec("P")
type LangGraphReturnMode = Literal["result", "output"]


class LangGraphIntegrationError(ImportError):
    """Raised when LangGraph adapter functionality is unavailable."""


class LangGraphAdapter:
    """Adapter that exposes AgentActum-protected callables to LangGraph."""

    def __init__(self, actum: AgentActum) -> None:
        """Create an adapter around an explicit AgentActum instance."""
        self._actum = actum

    def protect_tool(
        self,
        *,
        contract: ToolContract,
        idempotency_fields: Iterable[str] | None = None,
        context_factory: Callable[[JsonObject], JsonObject] | None = None,
        return_mode: LangGraphReturnMode = "result",
    ) -> Callable[[Callable[P, JsonValue]], Callable[P, JsonValue]]:
        """Protect a function and return a LangGraph-friendly callable."""
        if return_mode not in {"result", "output"}:
            raise ValueError("return_mode must be 'result' or 'output'")

        def decorator(function: Callable[P, JsonValue]) -> Callable[P, JsonValue]:
            protected = self._actum.protect(
                contract=contract,
                idempotency_fields=idempotency_fields,
                context_factory=context_factory,
            )(function)

            @wraps(function)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> JsonValue:
                result = protected(*args, **kwargs)
                return _serialize_result(result, return_mode=return_mode)

            return wrapper

        return decorator

    def tool_node(self, tools: Iterable[Callable[..., JsonValue]]) -> object:
        """Create a LangGraph ToolNode from protected tools using lazy import."""
        try:
            prebuilt = import_module("langgraph.prebuilt")
        except ImportError as exc:
            raise LangGraphIntegrationError(
                'Install the optional extra with: pip install "agentactum[langgraph]"',
            ) from exc

        tool_node_type = getattr(prebuilt, "ToolNode", None)
        if tool_node_type is None:
            raise LangGraphIntegrationError(
                "Installed langgraph package does not expose "
                "langgraph.prebuilt.ToolNode",
            )
        tool_node_factory = cast(
            Callable[[list[Callable[..., JsonValue]]], object],
            tool_node_type,
        )
        return tool_node_factory(list(tools))


def _serialize_result(
    result: ExecutionResult,
    *,
    return_mode: LangGraphReturnMode,
) -> JsonValue:
    if return_mode == "result":
        return cast(JsonValue, result.model_dump(mode="json"))
    if result.succeeded:
        return result.output
    return cast(JsonValue, result.model_dump(mode="json"))
