"""Framework-independent AgentActum facade."""

import inspect
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from functools import wraps
from typing import Any, ParamSpec, cast
from uuid import uuid4

from pydantic import JsonValue

from agentactum._model import JsonObject
from agentactum.contracts import ActionIntent, ToolContract, ToolRegistry
from agentactum.execution import (
    ApprovalChecker,
    ExecutionResult,
    RuntimeCheck,
    SingleActionRuntime,
)
from agentactum.idempotency import (
    IdempotencyBackend,
    InMemoryIdempotencyBackend,
    create_key,
)
from agentactum.ledger import InMemoryLedger, Ledger
from agentactum.policies import PolicyEngine

P = ParamSpec("P")


class AgentActum:
    """Framework-independent entry point for protecting Python tool functions."""

    def __init__(
        self,
        *,
        policy_engine: PolicyEngine | None = None,
        registry: ToolRegistry | None = None,
        idempotency_backend: IdempotencyBackend | None = None,
        ledger: Ledger | None = None,
        approval_checker: ApprovalChecker | None = None,
        preconditions: Iterable[RuntimeCheck] = (),
        postconditions: Iterable[RuntimeCheck] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Create an in-process AgentActum facade from explicit core services."""
        self.registry = registry or ToolRegistry()
        self.policy_engine = policy_engine or PolicyEngine()
        self.idempotency_backend = idempotency_backend or InMemoryIdempotencyBackend()
        self.ledger = ledger or InMemoryLedger()
        self._approval_checker = approval_checker
        self._preconditions = tuple(preconditions)
        self._postconditions = tuple(postconditions)
        self._clock = clock or _utc_now

    def protect(
        self,
        *,
        contract: ToolContract,
        idempotency_fields: Iterable[str] | None = None,
        context_factory: Callable[[JsonObject], JsonObject] | None = None,
    ) -> Callable[[Callable[P, JsonValue]], Callable[P, ExecutionResult]]:
        """Protect a Python tool function behind AgentActum's action boundary."""

        def decorator(function: Callable[P, JsonValue]) -> Callable[P, ExecutionResult]:
            self.registry.register(contract, function)

            @wraps(function)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> ExecutionResult:
                arguments = _bind_json_arguments(function, *args, **kwargs)
                key = None
                if contract.idempotency_key_required:
                    key = create_key(
                        tool_name=contract.name,
                        arguments=arguments,
                        fields=tuple(
                            idempotency_fields
                            if idempotency_fields is not None
                            else _required_schema_fields(contract)
                        ),
                    )
                action = ActionIntent(
                    intent_id=uuid4(),
                    contract_id=contract.contract_id,
                    tool_name=contract.name,
                    contract_version=contract.version,
                    requester_id="agentactum.facade",
                    arguments=arguments,
                    created_at=self._clock(),
                    idempotency_key=key,
                )
                runtime = SingleActionRuntime(
                    registry=self.registry,
                    policy_engine=self.policy_engine,
                    idempotency_backend=self.idempotency_backend,
                    ledger=self.ledger,
                    approval_checker=self._approval_checker,
                    preconditions=self._preconditions,
                    postconditions=self._postconditions,
                    clock=self._clock,
                )
                context = {} if context_factory is None else context_factory(arguments)
                return runtime.execute(action=action, context=context)

            return wrapper

        return decorator


def _bind_json_arguments(
    function: Callable[..., JsonValue],
    *args: Any,
    **kwargs: Any,
) -> JsonObject:
    signature = inspect.signature(function)
    bound = signature.bind(*args, **kwargs)
    bound.apply_defaults()
    arguments = dict(bound.arguments)
    return {
        name: _as_json_value(value=value, name=name)
        for name, value in arguments.items()
    }


def _as_json_value(*, value: Any, name: str) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_as_json_value(value=item, name=name) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _as_json_value(value=item, name=name)
            for key, item in value.items()
        }
    raise TypeError(f"argument is not JSON-compatible: {name}")


def _required_schema_fields(contract: ToolContract) -> tuple[str, ...]:
    required = contract.input_schema.document.get("required", [])
    if not isinstance(required, list) or not all(
        isinstance(field, str) for field in required
    ):
        return ()
    return tuple(cast(list[str], required))


def _utc_now() -> datetime:
    return datetime.now(UTC)
