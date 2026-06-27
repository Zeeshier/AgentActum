"""In-process registry for trusted tool contracts and handlers."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import RLock

from agentactum.contracts.models import ToolContract

type ToolHandler = Callable[..., object]


class ToolRegistryError(Exception):
    """Base class for tool-registry failures."""


class DuplicateToolRegistrationError(ToolRegistryError):
    """Raised when a tool name is registered more than once."""

    def __init__(self, tool_name: str) -> None:
        """Create an error for a duplicate tool registration."""
        self.tool_name = tool_name
        super().__init__(f"tool is already registered: {tool_name}")


class UnknownToolError(ToolRegistryError):
    """Raised when a caller asks for an unregistered tool."""

    def __init__(self, tool_name: str) -> None:
        """Create an error for an unknown tool lookup."""
        self.tool_name = tool_name
        super().__init__(f"tool is not registered: {tool_name}")


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    """Trusted binding between a tool contract and its Python handler."""

    contract: ToolContract
    handler: ToolHandler


class ToolRegistry:
    """Explicit in-memory registry of known tool contracts.

    The registry stores trusted contracts separately from opaque Python handler
    callables. It does not execute handlers, evaluate policy, or rely on any
    agent-framework integration.
    """

    def __init__(self, registrations: Iterable[RegisteredTool] = ()) -> None:
        """Create an empty registry, optionally seeded with registrations."""
        self._lock = RLock()
        self._registrations: dict[str, RegisteredTool] = {}
        for registration in registrations:
            self.register(registration.contract, registration.handler)

    def register(
        self,
        contract: ToolContract,
        handler: ToolHandler,
    ) -> RegisteredTool:
        """Register one trusted tool contract and its separate handler.

        Duplicate names are rejected so that later `get()` calls cannot become
        ambiguous. The handler is stored but never invoked by the registry.
        """
        if not isinstance(contract, ToolContract):
            raise TypeError("contract must be a ToolContract")
        if not callable(handler):
            raise TypeError("handler must be callable")

        with self._lock:
            if contract.name in self._registrations:
                raise DuplicateToolRegistrationError(contract.name)

            registration = RegisteredTool(contract=contract, handler=handler)
            self._registrations[contract.name] = registration
            return registration

    def get(self, tool_name: str) -> RegisteredTool:
        """Return the registration for a known tool name.

        Raises:
            UnknownToolError: If the tool has not been registered.
        """
        with self._lock:
            try:
                return self._registrations[tool_name]
            except KeyError as exc:
                raise UnknownToolError(tool_name) from exc

    def contains(self, tool_name: str) -> bool:
        """Return whether a tool name is registered."""
        with self._lock:
            return tool_name in self._registrations

    def list_contracts(self) -> tuple[ToolContract, ...]:
        """Return registered contracts in registration order."""
        with self._lock:
            return tuple(
                registration.contract for registration in self._registrations.values()
            )
